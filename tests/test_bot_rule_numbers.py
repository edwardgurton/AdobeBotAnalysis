"""Tests for bot rule number lookup, segment listing and segment tagging."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from click.testing import CliRunner

from adobe_downloader.config.schema import DEFAULT_CANDIDATE_TAG, SegmentCreationConfig
from adobe_downloader.core.api_client import AdobeClient
from adobe_downloader.segments import bot_rule_numbers
from adobe_downloader.segments.bot_rule_numbers import (
    get_highest_bot_rule_candidate_number,
    highest_bot_rule_number,
    parse_bot_rule_number,
)

Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler) -> AdobeClient:
    client = AdobeClient("http://127.0.0.1:8765")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


# ── Name parsing ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("0256 BOT RULE: oddspediacom - OperatingSystem=Linux", 256),
        ("0257BOTRULEoddspediacomOperatingSystem-Linux", 257),
        ("1203 BOT RULE: x", 1203),
        ("BOTCOMPARE_AH-Oddspedia-R1A~Oddspediacom", None),
        ("12 BOT RULE: x", None),
        ("12345 BOT RULE: x", None),
        (" 0256 BOT RULE", None),
        ("", None),
    ],
)
def test_parse_bot_rule_number(name: str, expected: int | None) -> None:
    assert parse_bot_rule_number(name) == expected


def test_highest_ignores_non_conforming_names() -> None:
    names = ["0256 BOT RULE: a", "BOTCOMPARE_AH-X-R1A~y", "12 BOT", "0099 BOT RULE: b"]
    assert highest_bot_rule_number(names) == 256


def test_highest_is_zero_when_nothing_matches() -> None:
    assert highest_bot_rule_number([]) == 0
    assert highest_bot_rule_number(["BOTCOMPARE_x", "untagged"]) == 0


# ── list_segments + highest number via the client ────────────────────────────


async def test_list_segments_paginates_and_sends_tag_filter() -> None:
    pages = {
        "0": {"content": [{"id": "s1", "name": "0256 BOT RULE: a"}], "lastPage": False},
        "1": {"content": [{"id": "s2", "name": "0301 BOT RULE: b"}], "lastPage": True},
    }
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=pages[request.url.params["page"]])

    client = _client(handler)
    try:
        result = await get_highest_bot_rule_candidate_number(client)
    finally:
        await client.close()

    assert result == 301
    assert len(seen) == 2
    params = seen[0].url.params
    assert seen[0].url.path == "/segments"
    assert params["tagNames"] == DEFAULT_CANDIDATE_TAG
    assert params["includeType"] == "all"


async def test_falls_back_to_shared_when_all_is_forbidden() -> None:
    include_types: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        include_type = request.url.params["includeType"]
        include_types.append(include_type)
        if include_type == "all":
            return httpx.Response(403, json={"errorCode": "forbidden"})
        return httpx.Response(
            200, json={"content": [{"name": "0042 BOT RULE: a"}], "lastPage": True}
        )

    client = _client(handler)
    try:
        assert await get_highest_bot_rule_candidate_number(client) == 42
    finally:
        await client.close()

    assert include_types == ["all", "shared"]


async def test_other_http_errors_are_not_swallowed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    client = _client(handler)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await get_highest_bot_rule_candidate_number(client)
    finally:
        await client.close()


async def test_no_tagged_segments_returns_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": [], "lastPage": True})

    client = _client(handler)
    try:
        assert await get_highest_bot_rule_candidate_number(client) == 0
    finally:
        await client.close()


# ── tag_segment ───────────────────────────────────────────────────────────────


async def test_tag_segment_merges_with_existing_tags() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": 7, "name": "Legend"}])
        return httpx.Response(200, json=[])

    client = _client(handler)
    try:
        result = await client.tag_segment("s3938_abc", [DEFAULT_CANDIDATE_TAG])
    finally:
        await client.close()

    assert result == ["Legend", DEFAULT_CANDIDATE_TAG]
    get, put = seen
    assert get.url.path == "/componentmetadata/tags/search"
    assert get.url.params["componentIds"] == "s3938_abc"
    assert put.method == "PUT"
    assert put.url.path == "/componentmetadata/tags/tagitems"
    assert json.loads(put.content) == [
        {
            "componentType": "segment",
            "componentId": "s3938_abc",
            "tags": [{"name": "Legend"}, {"name": DEFAULT_CANDIDATE_TAG}],
        }
    ]


async def test_tag_segment_is_idempotent() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json=[{"name": DEFAULT_CANDIDATE_TAG}])

    client = _client(handler)
    try:
        result = await client.tag_segment("s3938_abc", [DEFAULT_CANDIDATE_TAG])
    finally:
        await client.close()

    assert result == [DEFAULT_CANDIDATE_TAG]
    assert methods == ["GET"]


# ── Config + CLI ──────────────────────────────────────────────────────────────


def test_candidate_tag_defaults_in_config() -> None:
    cfg = SegmentCreationConfig(
        input_csv="x.csv",
        compare_list_path="c.csv",
        validate_list_path="v.csv",
        segment_list_path="s.csv",
    )
    assert cfg.candidate_tag == DEFAULT_CANDIDATE_TAG == "BotRuleCandidates"


@pytest.mark.parametrize(("flag", "expected"), [([], "256"), (["--next"], "257")])
def test_cli_prints_only_the_integer(
    monkeypatch: pytest.MonkeyPatch, flag: list[str], expected: str
) -> None:
    from adobe_downloader.cli import main

    seen_tags: list[str] = []

    async def fake(client: object, tag: str = DEFAULT_CANDIDATE_TAG) -> int:
        seen_tags.append(tag)
        return 256

    monkeypatch.setattr(bot_rule_numbers, "get_highest_bot_rule_candidate_number", fake)
    result = CliRunner().invoke(main, ["bot-rule-number", "--client", "Legend", *flag])

    assert result.exit_code == 0, result.output
    assert result.output == f"{expected}\n"
    assert seen_tags == [DEFAULT_CANDIDATE_TAG]
