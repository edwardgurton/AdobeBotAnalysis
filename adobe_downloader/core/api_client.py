"""Adobe Analytics API client."""

import time
from typing import Any

import httpx

from adobe_downloader.config.loader import load_credentials
from adobe_downloader.core.auth import fetch_token

_API_BASE = "https://analytics.adobe.io/api"


class AdobeClient:
    """Single entry point for all Adobe Analytics API calls."""

    def __init__(self, client_name: str) -> None:
        creds = load_credentials(client_name)
        adobe = creds["adobe"]
        self._client_id: str = adobe["clientID"]
        self._client_secret: str = adobe["clientSecret"]
        self._org_id: str = adobe["adobeOrgID"]
        self._company_id: str = adobe["globalCompanyID"]
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._http = httpx.AsyncClient(timeout=120)

    async def _get_token(self) -> str:
        """Return a valid bearer token, refreshing if within the expiry buffer."""
        if self._token is None or time.monotonic() >= self._token_expiry:
            self._token, self._token_expiry = await fetch_token(
                self._client_id, self._client_secret, self._http
            )
        return self._token

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "x-api-key": self._client_id,
            "x-proxy-global-company-id": self._company_id,
            "x-gw-ims-org-id": self._org_id,
        }

    async def get_users(self) -> list[dict[str, Any]]:
        """Fetch all Analytics users for the company, paginating as needed."""
        token = await self._get_token()
        headers = self._headers(token)
        users: list[dict[str, Any]] = []
        page = 0
        while True:
            resp = await self._http.get(
                f"{_API_BASE}/{self._company_id}/users",
                params={"limit": 100, "page": page},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            users.extend(data.get("content", []))
            if data.get("lastPage", True):
                break
            page += 1
        return users

    async def get_authenticated_user(self) -> dict[str, Any]:
        """Fetch the profile for the currently authenticated service account."""
        token = await self._get_token()
        resp = await self._http.get(
            f"{_API_BASE}/{self._company_id}/users/me",
            headers=self._headers(token),
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[return-value]

    async def get_report(self, request_body: dict[str, Any]) -> dict[str, Any]:
        """Submit a ranked report request. (Used from Step 5.)"""
        token = await self._get_token()
        resp = await self._http.post(
            f"{_API_BASE}/{self._company_id}/reports",
            json=request_body,
            headers=self._headers(token),
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[return-value]

    async def get_report_suites(self, limit: int = 1000) -> dict[str, Any]:
        """Fetch report suites for the company. (Used from Step 18.)"""
        token = await self._get_token()
        resp = await self._http.get(
            f"{_API_BASE}/{self._company_id}/collections/suites",
            params={"limit": limit},
            headers=self._headers(token),
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[return-value]

    async def create_segment(self, segment_def: dict[str, Any]) -> dict[str, Any]:
        """Create a segment and return the created object. (Used from Step 10.)"""
        token = await self._get_token()
        resp = await self._http.post(
            f"{_API_BASE}/{self._company_id}/segments",
            json=segment_def,
            headers=self._headers(token),
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[return-value]

    async def share_segment(self, segment_id: str, user_ids: list[str]) -> None:
        """Share a segment with each user in user_ids. (Used from Step 10.)"""
        token = await self._get_token()
        headers = self._headers(token)
        for user_id in user_ids:
            resp = await self._http.post(
                f"{_API_BASE}/{self._company_id}/componentmetadata/shares",
                json={
                    "componentType": "segment",
                    "componentId": segment_id,
                    "shareToId": user_id,
                    "shareToType": "user",
                },
                headers=headers,
            )
            resp.raise_for_status()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
