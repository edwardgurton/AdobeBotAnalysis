"""Adobe Analytics API client.

All Adobe calls go through :class:`AdobeClient`, which talks to the local credential
broker (``broker/adobe_broker.py``). The broker holds the OAuth credentials, adds the
auth and company headers, and prefixes the company ID onto the path, so this module
never handles a secret or an access token.
"""

import json
import logging
import os
from typing import Any

import httpx

from adobe_downloader.core.rate_limiter import SlidingWindowRateLimiter, make_retry

DEFAULT_API_BASE_URL = "http://127.0.0.1:8765"
API_BASE_URL_ENV = "ADOBE_API_BASE_URL"
_log = logging.getLogger(__name__)

_BODY_LOG_LIMIT = 20_000  # characters — cap logged body size to avoid flooding the console


def resolve_base_url(base_url: str | None = None) -> str:
    """Return the API base URL: explicit arg, then ``$ADOBE_API_BASE_URL``, then the broker."""
    url = base_url or os.environ.get(API_BASE_URL_ENV) or DEFAULT_API_BASE_URL
    return url.rstrip("/")


class BrokerUnavailableError(RuntimeError):
    """Raised when the credential broker cannot be reached."""


class AdobeClient:
    """Single entry point for all Adobe Analytics API calls.

    Endpoint paths are relative to the company root (e.g. ``"reports"``); the broker
    maps them onto ``https://analytics.adobe.io/api/{globalCompanyId}/...``.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = resolve_base_url(base_url)
        self._http = httpx.AsyncClient(timeout=600)
        self._rate_limiter = SlidingWindowRateLimiter()
        self._retry = make_retry(self._rate_limiter)

    def _url(self, path: str) -> str:
        return f"{self._base_url}/{path.lstrip('/')}"

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one rate-limited request, translating connection failures."""
        send = self._http.get if method == "GET" else self._http.post
        try:
            return await self._rate_limiter.execute(send, url, **kwargs)
        except httpx.ConnectError as exc:
            raise BrokerUnavailableError(
                f"Cannot reach the Adobe credential broker at {self._base_url}. "
                "Start it with `python broker/adobe_broker.py` in a separate terminal."
            ) from exc

    async def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        """Rate-limited GET with tenacity retry."""
        url = self._url(path)

        if _log.isEnabledFor(logging.DEBUG):
            _log.debug("GET  %s", url)
            if "params" in kwargs:
                _log.debug("  params:  %s", kwargs["params"])

        @self._retry
        async def _call() -> httpx.Response:
            r = await self._send("GET", url, **kwargs)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError:
                _log.debug(
                    "  response %d %s\n%s",
                    r.status_code,
                    r.reason_phrase,
                    r.text[:_BODY_LOG_LIMIT],
                )
                raise
            return r

        return await _call()

    async def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        """Rate-limited POST with tenacity retry."""
        url = self._url(path)

        if _log.isEnabledFor(logging.DEBUG):
            _log.debug("POST %s", url)
            if "json" in kwargs:
                _log.debug(
                    "  body:\n%s",
                    json.dumps(kwargs["json"], indent=2, ensure_ascii=False)[:_BODY_LOG_LIMIT],
                )

        @self._retry
        async def _call() -> httpx.Response:
            r = await self._send("POST", url, **kwargs)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError:
                _log.debug(
                    "  response %d %s\n%s",
                    r.status_code,
                    r.reason_phrase,
                    r.text[:_BODY_LOG_LIMIT],
                )
                raise
            return r

        return await _call()

    async def get_users(self) -> list[dict[str, Any]]:
        """Fetch all Analytics users for the company, paginating as needed."""
        users: list[dict[str, Any]] = []
        page = 0
        while True:
            resp = await self._get(
                "users",
                params={"limit": 100, "page": page},
            )
            data = resp.json()
            users.extend(data.get("content", []))
            if data.get("lastPage", True):
                break
            page += 1
        return users

    async def get_authenticated_user(self) -> dict[str, Any]:
        """Fetch the profile for the currently authenticated service account."""
        resp = await self._get("users/me")
        return resp.json()  # type: ignore[return-value]

    async def get_report(self, request_body: dict[str, Any]) -> dict[str, Any]:
        """Submit a ranked report request. (Used from Step 5.)"""
        resp = await self._post(
            "reports",
            json=request_body,
        )
        return resp.json()  # type: ignore[return-value]

    async def get_report_suites(self, limit: int = 1000) -> dict[str, Any]:
        """Fetch report suites for the company. (Used from Step 18.)"""
        resp = await self._get(
            "collections/suites",
            params={"limit": limit},
        )
        return resp.json()  # type: ignore[return-value]

    async def create_segment(self, segment_def: dict[str, Any]) -> dict[str, Any]:
        """Create a segment and return the created object. (Used from Step 10.)"""
        resp = await self._post(
            "segments",
            json=segment_def,
        )
        return resp.json()  # type: ignore[return-value]

    async def share_segment(self, segment_id: str, user_ids: list[str]) -> None:
        """Share a segment with each user in user_ids. (Used from Step 10.)"""
        for user_id in user_ids:
            await self._post(
                "componentmetadata/shares",
                json={
                    "componentType": "segment",
                    "componentId": segment_id,
                    "shareToId": user_id,
                    "shareToType": "user",
                },
            )

    async def get_dimensions(self, rsid: str) -> list[dict[str, Any]]:
        """Fetch all dimensions for an RSID, including classification dimensions."""
        resp = await self._get(
            "dimensions",
            params={"rsid": rsid, "expansion": "support"},
        )
        return resp.json()  # type: ignore[return-value]

    async def get_metrics(self, rsid: str) -> list[dict[str, Any]]:
        """Fetch all metrics (standard + events) for an RSID."""
        resp = await self._get(
            "metrics",
            params={"rsid": rsid},
        )
        return resp.json()  # type: ignore[return-value]

    async def get_calculated_metrics(self) -> list[dict[str, Any]]:
        """Fetch all calculated metrics for the company (not RSID-scoped)."""
        items: list[dict[str, Any]] = []
        limit = 1000
        page = 0
        while True:
            resp = await self._get(
                "calculatedmetrics",
                params={"limit": limit, "page": page},
            )
            data = resp.json()
            if isinstance(data, list):
                items.extend(data)
                break
            items.extend(data.get("content", []))
            if data.get("lastPage", True):
                break
            page += 1
        return items

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
