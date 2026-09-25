"""Tests for the standalone credential broker (broker/adobe_broker.py).

The keychain and Adobe endpoints are faked; nothing here touches real credentials.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

_BROKER_PATH = Path(__file__).resolve().parents[1] / "broker" / "adobe_broker.py"
_spec = importlib.util.spec_from_file_location("adobe_broker", _BROKER_PATH)
assert _spec is not None and _spec.loader is not None
broker: Any = importlib.util.module_from_spec(_spec)
sys.modules["adobe_broker"] = broker
_spec.loader.exec_module(broker)

SECRET = "sekret-value-must-not-leak"
TOKEN = "tok-value-must-not-leak"


def _creds() -> Any:
    return broker.Credentials(
        client_id="cid", client_secret=SECRET, org_id="org@AdobeOrg", company_id="comp1"
    )


def _fake_keyring(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    module = types.ModuleType("keyring")

    def get_password(service: str, key: str) -> str | None:
        assert service == broker.KEYRING_SERVICE
        return values.get(key)

    module.get_password = get_password  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "keyring", module)


class FakeAdobe:
    """MockTransport handler standing in for IMS and the Analytics API."""

    def __init__(self) -> None:
        self.token_calls = 0
        self.api_requests: list[httpx.Request] = []
        self.api_status = 200
        self.fail_first_api_with_401 = False
        self.ims_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "ims-na1.adobelogin.com":
            self.token_calls += 1
            if self.ims_status != 200:
                return httpx.Response(self.ims_status, json={"error": f"bad {SECRET}"})
            return httpx.Response(
                200, json={"access_token": f"{TOKEN}{self.token_calls}", "expires_in": 86399}
            )
        self.api_requests.append(request)
        if self.fail_first_api_with_401 and len(self.api_requests) == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(
            self.api_status,
            json={"ok": True, "path": request.url.path},
            headers={"Set-Cookie": "x=y", "Retry-After": "3"},
        )


def _stack(fake: FakeAdobe) -> tuple[Any, Any, httpx.Client]:
    http = httpx.Client(transport=httpx.MockTransport(fake))
    creds = _creds()
    tokens = broker.TokenCache(creds, http)
    return tokens, broker.Forwarder(creds, tokens, http), http


# ---------------------------------------------------------------------------
# Keychain loading
# ---------------------------------------------------------------------------


def test_load_credentials_reads_all_four_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_keyring(
        monkeypatch,
        {"client_id": "a", "client_secret": "b", "org_id": "c", "company_id": "d"},
    )
    creds = broker.load_credentials()
    assert (creds.client_id, creds.client_secret, creds.org_id, creds.company_id) == (
        "a",
        "b",
        "c",
        "d",
    )


def test_load_credentials_reports_missing_names_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_keyring(monkeypatch, {"client_id": "a", "client_secret": SECRET})
    with pytest.raises(broker.BrokerError) as info:
        broker.load_credentials()
    assert "org_id" in info.value.message and "company_id" in info.value.message
    assert SECRET not in info.value.message


def test_credentials_repr_is_redacted() -> None:
    assert SECRET not in repr(_creds())
    assert SECRET not in str(_creds())


# ---------------------------------------------------------------------------
# Token cache
# ---------------------------------------------------------------------------


def test_token_is_cached_and_refreshed_before_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeAdobe()
    tokens, _, _ = _stack(fake)
    now = [1000.0]
    monkeypatch.setattr(broker.time, "monotonic", lambda: now[0])

    first = tokens.get()
    assert tokens.get() == first
    assert fake.token_calls == 1

    # Past (expires_in - buffer) the token counts as stale, before Adobe would reject it.
    now[0] += 86399 - broker.REFRESH_BUFFER_SECONDS
    assert tokens.get() != first
    assert fake.token_calls == 2


def test_ims_failure_message_hides_body_and_secret() -> None:
    fake = FakeAdobe()
    fake.ims_status = 400
    tokens, _, _ = _stack(fake)
    with pytest.raises(broker.BrokerError) as info:
        tokens.get()
    assert "HTTP 400" in info.value.message
    assert SECRET not in info.value.message


# ---------------------------------------------------------------------------
# Forwarding
# ---------------------------------------------------------------------------


def test_upstream_url_prefixes_company_id() -> None:
    _, fwd, _ = _stack(FakeAdobe())
    assert (
        fwd.upstream_url("/reports?rsid=x") == "https://analytics.adobe.io/api/comp1/reports?rsid=x"
    )


@pytest.mark.parametrize(
    "path",
    [
        "http://evil.example/x",
        "//evil.example/x",
        "/../other",
        "/segments/%2e%2e/x",
        "/a\\b",
        "/",
        "reports",
    ],
)
def test_upstream_url_rejects_unsafe_paths(path: str) -> None:
    _, fwd, _ = _stack(FakeAdobe())
    with pytest.raises(broker.BrokerError):
        fwd.upstream_url(path)


def test_forward_retries_once_on_401_with_fresh_token() -> None:
    fake = FakeAdobe()
    fake.fail_first_api_with_401 = True
    _, fwd, _ = _stack(fake)
    resp = fwd.forward("GET", "/users/me", {}, None)
    assert resp.status_code == 200
    assert fake.token_calls == 2
    auths = [r.headers["Authorization"] for r in fake.api_requests]
    assert auths[0] != auths[1]


# ---------------------------------------------------------------------------
# End-to-end over a real localhost socket
# ---------------------------------------------------------------------------


@pytest.fixture
def running_broker() -> Iterator[tuple[str, FakeAdobe]]:
    fake = FakeAdobe()
    _, fwd, http = _stack(fake)
    server = broker.BrokerServer(0, fwd)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.port}", fake
    finally:
        server.shutdown()
        server.server_close()
        http.close()


def test_server_binds_loopback_only(running_broker: tuple[str, FakeAdobe]) -> None:
    assert broker.BIND_HOST == "127.0.0.1"
    assert running_broker[0].startswith("http://127.0.0.1:")


def test_post_forwards_body_and_adds_auth_headers(
    running_broker: tuple[str, FakeAdobe],
) -> None:
    base, fake = running_broker
    resp = httpx.post(
        f"{base}/reports",
        json={"rsid": "x"},
        headers={"Authorization": "Bearer caller-supplied", "X-Custom": "drop-me"},
    )
    assert resp.status_code == 200
    assert resp.json()["path"] == "/api/comp1/reports"

    upstream = fake.api_requests[0]
    assert upstream.headers["Authorization"].startswith(f"Bearer {TOKEN}")
    assert upstream.headers["x-api-key"] == "cid"
    assert upstream.headers["x-proxy-global-company-id"] == "comp1"
    assert upstream.headers["x-gw-ims-org-id"] == "org@AdobeOrg"
    assert "X-Custom" not in upstream.headers
    assert upstream.content == b'{"rsid":"x"}'


def test_response_never_carries_token_or_upstream_headers(
    running_broker: tuple[str, FakeAdobe],
) -> None:
    base, _ = running_broker
    resp = httpx.get(f"{base}/users/me")
    assert TOKEN not in resp.text
    assert all(TOKEN not in v and SECRET not in v for v in resp.headers.values())
    assert "set-cookie" not in resp.headers
    assert resp.headers["retry-after"] == "3"


def test_upstream_error_status_is_passed_through(
    running_broker: tuple[str, FakeAdobe],
) -> None:
    base, fake = running_broker
    fake.api_status = 429
    resp = httpx.get(f"{base}/reports")
    assert resp.status_code == 429


def test_browser_origin_is_rejected(running_broker: tuple[str, FakeAdobe]) -> None:
    base, fake = running_broker
    resp = httpx.post(f"{base}/segments", json={}, headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    assert fake.api_requests == []


def test_non_json_body_is_rejected(running_broker: tuple[str, FakeAdobe]) -> None:
    base, fake = running_broker
    resp = httpx.post(f"{base}/segments", content=b"x=1", headers={"Content-Type": "text/plain"})
    assert resp.status_code == 415
    assert fake.api_requests == []


def test_health_does_not_return_token(running_broker: tuple[str, FakeAdobe]) -> None:
    base, _ = running_broker
    resp = httpx.get(f"{base}/_broker/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert TOKEN not in resp.text


def test_logs_contain_no_secrets(
    running_broker: tuple[str, FakeAdobe], caplog: pytest.LogCaptureFixture
) -> None:
    base, _ = running_broker
    with caplog.at_level("DEBUG"):
        httpx.post(f"{base}/reports", json={}, headers={"Authorization": "Bearer caller"})
        httpx.get(f"{base}/../x")
    assert caplog.records, "expected request summary lines"
    for record in caplog.records:
        text = record.getMessage()
        assert TOKEN not in text and SECRET not in text and "Bearer" not in text
