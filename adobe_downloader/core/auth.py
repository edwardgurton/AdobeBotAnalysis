"""OAuth 2.0 client-credentials token fetching for Adobe IMS."""

import time

import httpx

_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
_SCOPE = "openid,AdobeID,additional_info.projectedProductContext"
_EXPIRY_BUFFER = 300  # treat token as stale this many seconds before nominal expiry


async def fetch_token(
    client_id: str, client_secret: str, http: httpx.AsyncClient
) -> tuple[str, float]:
    """POST to Adobe IMS and return (access_token, expiry_monotonic)."""
    response = await http.post(
        _TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": _SCOPE,
        },
    )
    response.raise_for_status()
    payload = response.json()
    access_token: str = payload["access_token"]
    expires_in: int = int(payload["expires_in"])
    expiry = time.monotonic() + expires_in - _EXPIRY_BUFFER
    return access_token, expiry
