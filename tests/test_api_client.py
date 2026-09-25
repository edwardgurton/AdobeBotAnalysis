"""Tests for AdobeClient base-URL resolution and broker connectivity errors."""

from __future__ import annotations

import httpx
import pytest

from adobe_downloader.core.api_client import (
    API_BASE_URL_ENV,
    DEFAULT_API_BASE_URL,
    AdobeClient,
    BrokerUnavailableError,
    resolve_base_url,
)


def test_default_base_url_is_local_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(API_BASE_URL_ENV, raising=False)
    assert resolve_base_url() == DEFAULT_API_BASE_URL == "http://127.0.0.1:8765"


def test_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_BASE_URL_ENV, "http://127.0.0.1:9999/")
    assert resolve_base_url() == "http://127.0.0.1:9999"


def test_explicit_arg_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_BASE_URL_ENV, "http://127.0.0.1:9999")
    assert resolve_base_url("http://127.0.0.1:1234") == "http://127.0.0.1:1234"


async def test_requests_are_relative_to_base_url_and_carry_no_auth() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "u1"})

    client = AdobeClient("http://127.0.0.1:8765")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await client.get_authenticated_user() == {"id": "u1"}
    finally:
        await client.close()

    assert str(seen[0].url) == "http://127.0.0.1:8765/users/me"
    assert "authorization" not in seen[0].headers
    assert "x-api-key" not in seen[0].headers


async def test_unreachable_broker_raises_clear_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = AdobeClient("http://127.0.0.1:8765")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(BrokerUnavailableError, match="adobe_broker.py"):
            await client.get_authenticated_user()
    finally:
        await client.close()
