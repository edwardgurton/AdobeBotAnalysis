"""Local credential broker for the Adobe Analytics 2.0 API.

Run this yourself in a separate terminal::

    python broker/adobe_broker.py            # listens on http://127.0.0.1:8765

It reads the OAuth Server-to-Server credentials from the OS keychain, obtains and caches
an IMS access token in memory, and forwards requests to Adobe with the auth headers added:

    http://127.0.0.1:8765/<path>?<query>
        -> https://analytics.adobe.io/api/<globalCompanyId>/<path>?<query>

Guarantees:

- Binds to 127.0.0.1 only.
- Never logs or returns the client secret, the access token or any request headers,
  including in error messages. Logs record method, path and status only.
- Caller-supplied headers are discarded except ``Content-Type`` and ``Accept``.
- Only GET and POST are forwarded, only to the Analytics API host.

Keychain entries (service ``adobe-downloader-broker``): ``client_id``, ``client_secret``,
``org_id``, ``company_id``. See README.md for how to set them.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

KEYRING_SERVICE = "adobe-downloader-broker"
KEY_CLIENT_ID = "client_id"
KEY_CLIENT_SECRET = "client_secret"
KEY_ORG_ID = "org_id"
KEY_COMPANY_ID = "company_id"
_REQUIRED_KEYS = (KEY_CLIENT_ID, KEY_CLIENT_SECRET, KEY_ORG_ID, KEY_COMPANY_ID)

BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
IMS_SCOPE = "openid,AdobeID,additional_info.projectedProductContext"
ANALYTICS_API_ROOT = "https://analytics.adobe.io/api"

REFRESH_BUFFER_SECONDS = 300  # refresh this long before the token's nominal expiry
MAX_BODY_BYTES = 10 * 1024 * 1024
UPSTREAM_TIMEOUT_SECONDS = 600

# Only these caller headers are forwarded upstream; everything else is dropped.
_FORWARDED_REQUEST_HEADERS = ("Content-Type", "Accept")
# Only these upstream headers are passed back to the caller.
_RETURNED_RESPONSE_HEADERS = ("Content-Type", "Retry-After")

log = logging.getLogger("adobe_broker")


class BrokerError(Exception):
    """An error whose message is safe to log and return to the caller.

    Never construct one from an upstream exception's text or from request headers.
    """

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class Credentials:
    """Credentials read from the keychain. ``repr`` never reveals values."""

    __slots__ = ("client_id", "client_secret", "org_id", "company_id")

    def __init__(self, client_id: str, client_secret: str, org_id: str, company_id: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.org_id = org_id
        self.company_id = company_id

    def __repr__(self) -> str:
        return "Credentials(<redacted>)"


def load_credentials() -> Credentials:
    """Read all four entries from the OS keychain. Reports missing key *names* only."""
    try:
        import keyring
    except ImportError:
        raise BrokerError(500, "the 'keyring' package is not installed") from None

    values: dict[str, str] = {}
    missing: list[str] = []
    for key in _REQUIRED_KEYS:
        try:
            value = keyring.get_password(KEYRING_SERVICE, key)
        except Exception as exc:  # keyring backends raise assorted types
            raise BrokerError(
                500, f"keychain lookup failed for '{key}' ({type(exc).__name__})"
            ) from None
        if value:
            values[key] = value.strip()
        else:
            missing.append(key)
    if missing:
        raise BrokerError(
            500,
            f"missing keychain entries under service '{KEYRING_SERVICE}': {', '.join(missing)}",
        )
    return Credentials(
        client_id=values[KEY_CLIENT_ID],
        client_secret=values[KEY_CLIENT_SECRET],
        org_id=values[KEY_ORG_ID],
        company_id=values[KEY_COMPANY_ID],
    )


class TokenCache:
    """Holds one IMS access token in memory and refreshes it before expiry."""

    def __init__(self, creds: Credentials, http: httpx.Client) -> None:
        self._creds = creds
        self._http = http
        self._token: str | None = None
        self._expiry = 0.0  # time.monotonic() after which the token counts as stale
        self._lock = threading.Lock()

    def get(self) -> str:
        with self._lock:
            if self._token is None or time.monotonic() >= self._expiry:
                self._refresh_locked()
            assert self._token is not None
            return self._token

    def invalidate(self, stale: str) -> None:
        """Drop *stale* so the next ``get`` refreshes (no-op if already replaced)."""
        with self._lock:
            if self._token == stale:
                self._token = None

    def seconds_remaining(self) -> float:
        with self._lock:
            return max(0.0, self._expiry - time.monotonic()) if self._token else 0.0

    def _refresh_locked(self) -> None:
        try:
            resp = self._http.post(
                IMS_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._creds.client_id,
                    "client_secret": self._creds.client_secret,
                    "scope": IMS_SCOPE,
                },
            )
        except httpx.HTTPError as exc:
            raise BrokerError(
                502, f"token request to Adobe IMS failed ({type(exc).__name__})"
            ) from None
        if resp.status_code != 200:
            # The IMS error body is not echoed: it is not needed and is not ours to vouch for.
            raise BrokerError(502, f"token request to Adobe IMS failed (HTTP {resp.status_code})")
        try:
            payload = resp.json()
            token = str(payload["access_token"])
            expires_in = int(payload["expires_in"])
        except Exception:
            raise BrokerError(502, "unexpected token response from Adobe IMS") from None
        self._token = token
        self._expiry = time.monotonic() + max(0, expires_in - REFRESH_BUFFER_SECONDS)
        log.info("obtained access token (valid for about %d min)", expires_in // 60)


class Forwarder:
    """Builds the upstream request, adds auth headers, retries once on 401."""

    def __init__(self, creds: Credentials, tokens: TokenCache, http: httpx.Client) -> None:
        self._creds = creds
        self._tokens = tokens
        self._http = http

    def upstream_url(self, raw_path: str) -> str:
        parts = urlsplit(raw_path)
        if parts.scheme or parts.netloc or not parts.path.startswith("/"):
            raise BrokerError(400, "request target must be a relative path")
        decoded = unquote(parts.path)
        segments = decoded.split("/")[1:]
        if (
            not decoded.strip("/")
            or "\\" in decoded
            or any(seg in (".", "..") for seg in segments)
            or decoded.startswith("//")
        ):
            raise BrokerError(400, "invalid request path")
        url = f"{ANALYTICS_API_ROOT}/{self._creds.company_id}{parts.path}"
        return f"{url}?{parts.query}" if parts.query else url

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "x-api-key": self._creds.client_id,
            "x-proxy-global-company-id": self._creds.company_id,
            "x-gw-ims-org-id": self._creds.org_id,
        }

    def forward(
        self, method: str, raw_path: str, caller_headers: dict[str, str], body: bytes | None
    ) -> httpx.Response:
        url = self.upstream_url(raw_path)
        passthrough = {
            name: caller_headers[name]
            for name in _FORWARDED_REQUEST_HEADERS
            if name in caller_headers
        }
        for attempt in (1, 2):
            token = self._tokens.get()
            headers = {**passthrough, **self._auth_headers(token)}
            try:
                resp = self._http.request(method, url, headers=headers, content=body)
            except httpx.HTTPError as exc:
                raise BrokerError(
                    502, f"upstream request to Adobe failed ({type(exc).__name__})"
                ) from None
            if resp.status_code == 401 and attempt == 1:
                self._tokens.invalidate(token)
                continue
            return resp
        raise AssertionError("unreachable")


class BrokerHandler(BaseHTTPRequestHandler):
    """HTTP handler. The server instance carries ``forwarder`` and ``port`` attributes."""

    server: BrokerServer
    protocol_version = "HTTP/1.1"
    server_version = "adobe-broker"
    sys_version = ""

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def _handle(self, method: str) -> None:
        status = 500
        try:
            self._check_local_caller()
            if self.path == "/_broker/health":
                status = self._health()
                return
            body = self._read_body() if method == "POST" else None
            caller_headers = {
                name: value
                for name in _FORWARDED_REQUEST_HEADERS
                if (value := self.headers.get(name)) is not None
            }
            resp = self.server.forwarder.forward(method, self.path, caller_headers, body)
            status = resp.status_code
            extra = {
                name: resp.headers[name]
                for name in _RETURNED_RESPONSE_HEADERS
                if name in resp.headers
            }
            self._send(status, resp.content, extra)
        except BrokerError as exc:
            status = exc.status
            self._send_error_json(exc.status, exc.message)
        except Exception as exc:  # never let a traceback (or its message) escape
            status = 500
            log.error("internal error handling request (%s)", type(exc).__name__)
            self._send_error_json(500, "internal broker error")
        finally:
            log.info("%s %s -> %d", method, urlsplit(self.path).path, status)

    def _check_local_caller(self) -> None:
        # Defend against browser pages (DNS rebinding / cross-site POSTs) reaching the broker.
        allowed_hosts = {f"127.0.0.1:{self.server.port}", f"localhost:{self.server.port}"}
        if self.headers.get("Host") not in allowed_hosts:
            raise BrokerError(403, "unexpected Host header")
        if self.headers.get("Origin") is not None:
            raise BrokerError(403, "browser-originated requests are not accepted")

    def _read_body(self) -> bytes:
        if self.headers.get("Transfer-Encoding"):
            raise BrokerError(411, "chunked request bodies are not supported")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise BrokerError(400, "invalid Content-Length") from None
        if length < 0 or length > MAX_BODY_BYTES:
            raise BrokerError(413, "request body too large")
        if length and not (self.headers.get("Content-Type") or "").startswith("application/json"):
            raise BrokerError(415, "request bodies must be application/json")
        return self.rfile.read(length) if length else b""

    def _health(self) -> int:
        tokens = self.server.forwarder._tokens
        tokens.get()  # proves the keychain credentials work; the token itself is not returned
        payload = {"status": "ok", "token_seconds_remaining": int(tokens.seconds_remaining())}
        self._send(200, json.dumps(payload).encode(), {"Content-Type": "application/json"})
        return 200

    def _send(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        body = json.dumps({"error": f"broker: {message}"}).encode()
        self.close_connection = True  # any unread request body would desync keep-alive
        try:
            self._send(status, body, {"Content-Type": "application/json"})
        except OSError:
            pass  # caller went away

    # The stdlib logs raw request lines and error details to stderr; route everything
    # through _handle's own one-line summary instead.
    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        pass

    def log_error(self, format: str, *args: Any) -> None:
        log.warning("malformed request rejected")

    def log_message(self, format: str, *args: Any) -> None:
        pass


class BrokerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, forwarder: Forwarder) -> None:
        super().__init__((BIND_HOST, port), BrokerHandler)
        self.port: int = self.server_address[1]  # the bound port (differs when port=0)
        self.forwarder = forwarder

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Default prints a full traceback; report the exception type only.
        exc = sys.exc_info()[1]
        log.error("connection error (%s)", type(exc).__name__ if exc else "unknown")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Adobe Analytics credential broker.")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"port on {BIND_HOST} (default {DEFAULT_PORT})",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # httpx/httpcore log request URLs at INFO/DEBUG; keep them quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    try:
        creds = load_credentials()
    except BrokerError as exc:
        log.error("%s", exc.message)
        return 1

    http = httpx.Client(timeout=UPSTREAM_TIMEOUT_SECONDS)
    tokens = TokenCache(creds, http)
    try:
        tokens.get()  # fail fast if the credentials are wrong
    except BrokerError as exc:
        log.error("%s", exc.message)
        http.close()
        return 1

    server = BrokerServer(args.port, Forwarder(creds, tokens, http))
    log.info("broker listening on http://%s:%d", BIND_HOST, server.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        server.server_close()
        http.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
