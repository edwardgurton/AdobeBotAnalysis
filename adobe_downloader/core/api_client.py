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
        self._tag_ids: dict[str, str] | None = None

    def _url(self, path: str) -> str:
        return f"{self._base_url}/{path.lstrip('/')}"

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one rate-limited request, translating connection failures."""
        try:
            return await self._rate_limiter.execute(self._http.request, method, url, **kwargs)
        except httpx.ConnectError as exc:
            raise BrokerUnavailableError(
                f"Cannot reach the Adobe credential broker at {self._base_url}. "
                "Start it with `python broker/adobe_broker.py` in a separate terminal."
            ) from exc

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Rate-limited request with tenacity retry."""
        url = self._url(path)

        if _log.isEnabledFor(logging.DEBUG):
            _log.debug("%-4s %s", method, url)
            if "params" in kwargs:
                _log.debug("  params:  %s", kwargs["params"])
            if "json" in kwargs:
                _log.debug(
                    "  body:\n%s",
                    json.dumps(kwargs["json"], indent=2, ensure_ascii=False)[:_BODY_LOG_LIMIT],
                )

        @self._retry
        async def _call() -> httpx.Response:
            r = await self._send(method, url, **kwargs)
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

    async def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        """Rate-limited GET with tenacity retry."""
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        """Rate-limited POST with tenacity retry."""
        return await self._request("POST", path, **kwargs)

    async def _put(self, path: str, **kwargs: Any) -> httpx.Response:
        """Rate-limited PUT with tenacity retry."""
        return await self._request("PUT", path, **kwargs)

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

    async def list_segments(
        self,
        tag_names: list[str] | None = None,
        include_type: str | None = None,
        expansion: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """List segments, optionally filtered by tag, paginating as needed.

        ``include_type`` is passed through as Adobe's ``includeType`` (e.g. ``"all"``
        needs admin rights; ``"shared"`` adds segments shared with the caller).
        """
        params: dict[str, Any] = {"limit": limit}
        if tag_names:
            params["tagNames"] = ",".join(tag_names)
        if include_type:
            params["includeType"] = include_type
        if expansion:
            params["expansion"] = expansion

        items: list[dict[str, Any]] = []
        page = 0
        while True:
            resp = await self._get("segments", params={**params, "page": page})
            data = resp.json()
            if isinstance(data, list):
                items.extend(data)
                break
            items.extend(data.get("content", []))
            if data.get("lastPage", True):
                break
            page += 1
        return items

    async def get_segment_tags(self, segment_id: str) -> list[dict[str, Any]]:
        """Return the tags (``{"id", "name"}``) currently assigned to a segment."""
        resp = await self._get(f"segments/{segment_id}", params={"expansion": "tags"})
        return list(resp.json().get("tags") or [])

    async def list_tags(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Fetch every tag defined for the company, paginating as needed."""
        items: list[dict[str, Any]] = []
        page = 0
        while True:
            resp = await self._get("componentmetadata/tags", params={"limit": limit, "page": page})
            data = resp.json()
            if isinstance(data, list):
                items.extend(data)
                break
            items.extend(data.get("content", []))
            if data.get("lastPage", True):
                break
            page += 1
        return items

    async def get_tag_ids(self, names: list[str]) -> dict[str, str]:
        """Map tag names to Adobe tag IDs. Raises ``LookupError`` for unknown names.

        The full tag list is fetched once per client and cached.
        """
        if self._tag_ids is None:
            self._tag_ids = {
                str(t["name"]): str(t["id"]) for t in await self.list_tags() if t.get("name")
            }
        unknown = [n for n in names if n not in self._tag_ids]
        if unknown:
            raise LookupError(
                f"Tag(s) not found in Adobe Analytics: {', '.join(unknown)}. "
                "Create the tag in Adobe first; it is never created automatically."
            )
        return {n: self._tag_ids[n] for n in names}

    async def tag_segment(self, segment_id: str, tags: list[str]) -> list[str]:
        """Add *tags* to a segment, keeping any tags it already has.

        Adobe's ``PUT componentmetadata/tags/tagitems`` replaces a component's whole
        tag list and ignores tags given without an ``id``, so the current tags are read
        first, the new tags' IDs are looked up, and the merged list is sent. No PUT is
        sent when every tag is already present. The result is read back and a
        ``RuntimeError`` is raised if Adobe did not apply it. Returns the segment's
        resulting tag names.
        """
        existing = [t for t in await self.get_segment_tags(segment_id) if t.get("name")]
        existing_names = [str(t["name"]) for t in existing]
        missing = [t for t in tags if t not in existing_names]
        if not missing:
            return existing_names
        new_ids = await self.get_tag_ids(missing)
        payload_tags = [{"id": str(t["id"]), "name": str(t["name"])} for t in existing] + [
            {"id": new_ids[name], "name": name} for name in missing
        ]
        await self._put(
            "componentmetadata/tags/tagitems",
            json=[
                {
                    "componentType": "segment",
                    "componentId": segment_id,
                    "tags": payload_tags,
                }
            ],
        )
        after = [str(t["name"]) for t in await self.get_segment_tags(segment_id) if t.get("name")]
        not_applied = [t for t in tags if t not in after]
        if not_applied:
            raise RuntimeError(
                f"Adobe accepted the tag update for {segment_id} but the segment is "
                f"still missing: {', '.join(not_applied)}"
            )
        return after

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
