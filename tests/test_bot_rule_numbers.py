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


_LEGEND_TAG = {"id": "aaa111", "name": "Legend"}
_CANDIDATE_TAG = {"id": "6aa1682d979a3131ba22ccf4", "name": DEFAULT_CANDIDATE_TAG}


class _FakeAdobe:
    """Minimal stateful stand-in for the segment + tag endpoints."""

    def __init__(self, segment_tags: list[dict[str, str]], apply_put: bool = True) -> None:
        self.segment_tags = segment_tags
        self.apply_put = apply_put
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path == "/segments/s3938_abc":
            assert request.url.params["expansion"] == "tags"
            return httpx.Response(200, json={"id": "s3938_abc", "tags": self.segment_tags})
        if request.method == "GET" and path == "/componentmetadata/tags":
            page = int(request.url.params["page"])
            content = [[_LEGEND_TAG], [_CANDIDATE_TAG]][page]
            return httpx.Response(200, json={"content": content, "lastPage": page == 1})
        if request.method == "PUT" and path == "/componentmetadata/tags/tagitems":
            if self.apply_put:
                self.segment_tags = json.loads(request.content)[0]["tags"]
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected {request.method} {path}")


async def test_tag_segment_merges_with_existing_tags_by_id() -> None:
    fake = _FakeAdobe([_LEGEND_TAG])
    client = _client(fake)
    try:
        result = await client.tag_segment("s3938_abc", [DEFAULT_CANDIDATE_TAG])
    finally:
        await client.close()

    assert result == ["Legend", DEFAULT_CANDIDATE_TAG]
    (put,) = [r for r in fake.requests if r.method == "PUT"]
    assert json.loads(put.content) == [
        {
            "componentType": "segment",
            "componentId": "s3938_abc",
            "tags": [_LEGEND_TAG, _CANDIDATE_TAG],
        }
    ]
    # Read back after the PUT to confirm it applied.
    assert fake.requests[-1].url.path == "/segments/s3938_abc"


async def test_tag_segment_is_idempotent() -> None:
    fake = _FakeAdobe([_CANDIDATE_TAG])
    client = _client(fake)
    try:
        result = await client.tag_segment("s3938_abc", [DEFAULT_CANDIDATE_TAG])
    finally:
        await client.close()

    assert result == [DEFAULT_CANDIDATE_TAG]
    assert [r.method for r in fake.requests] == ["GET"]


async def test_tag_segment_raises_when_adobe_ignores_the_put() -> None:
    fake = _FakeAdobe([], apply_put=False)
    client = _client(fake)
    try:
        with pytest.raises(RuntimeError, match="still missing: BotRuleCandidates"):
            await client.tag_segment("s3938_abc", [DEFAULT_CANDIDATE_TAG])
    finally:
        await client.close()


async def test_tag_segment_unknown_tag_is_not_created() -> None:
    fake = _FakeAdobe([])
    client = _client(fake)
    try:
        with pytest.raises(LookupError, match="NoSuchTag"):
            await client.tag_segment("s3938_abc", ["NoSuchTag"])
    finally:
        await client.close()

    assert not [r for r in fake.requests if r.method in ("PUT", "POST")]


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
