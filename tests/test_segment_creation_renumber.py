"""Tests for bot rule renumbering and candidate tagging in segment_creation (MDL plan A3)."""

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from adobe_downloader.config.schema import DEFAULT_CANDIDATE_TAG, SegmentCreationConfig
from adobe_downloader.flows.segment_creation import (
    _CsvRow,
    apply_bot_rule_number,
    renumber_validate_rows,
    run_segment_creation,
)

_FIELDS = [
    "CompareValidate",
    "SegmentName",
    "RSIDCleanName",
    "Dimension1",
    "Dimension1Item",
    "Dimension2",
    "Dimension2Item",
    "Dimension3",
    "Dimension3Item",
    "Dimension4",
    "Dimension4Item",
]


def _row(compare_validate: str, name: str, rsid: str = "TestClient") -> dict[str, str]:
    return {
        "CompareValidate": compare_validate,
        "SegmentName": name,
        "RSIDCleanName": rsid,
        "Dimension1": "Domain",
        "Dimension1Item": "bad.com",
    }


def _make_csv(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    f = tmp_path / "Round.csv"
    with f.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return f


def _csv_row(compare_validate: str, name: str, row_num: int = 1) -> _CsvRow:
    return _CsvRow(compare_validate, name, "", "", "", "", "", "", "", "", "", row_num)


class FakeClient:
    """Records calls; behaves like AdobeClient for the methods segment_creation uses."""

    def __init__(
        self,
        tagged_names: list[str] | None = None,
        list_error: Exception | None = None,
        tag_error: Exception | None = None,
    ) -> None:
        self.tagged_names = tagged_names or []
        self.list_error = list_error
        self.tag_error = tag_error
        self.list_calls: list[dict[str, Any]] = []
        self.created: list[str] = []
        self.tagged: list[tuple[str, list[str]]] = []
        self._next_id = 1

    async def list_segments(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_calls.append(kwargs)
        if self.list_error is not None:
            raise self.list_error
        return [{"name": n} for n in self.tagged_names]

    async def create_segment(self, seg_def: dict[str, Any]) -> dict[str, Any]:
        self.created.append(seg_def["name"])
        seg_id = f"s3938_fake{self._next_id:03d}"
        self._next_id += 1
        return {"id": seg_id, "name": seg_def["name"]}

    async def share_segment(self, seg_id: str, user_ids: list[str]) -> None:
        pass

    async def tag_segment(self, seg_id: str, tags: list[str]) -> list[str]:
        if self.tag_error is not None:
            raise self.tag_error
        self.tagged.append((seg_id, tags))
        return tags


async def _run(tmp_path: Path, client: Any, rows: list[dict[str, str]], **kwargs: Any) -> Any:
    rsid_file = tmp_path / "suites.txt"
    rsid_file.write_text("rsid123:TestClient\n")
    return await run_segment_creation(
        client=client,
        input_csv=_make_csv(tmp_path, rows),
        share_with_users=[],
        compare_list_path=tmp_path / "compare",
        validate_list_path=tmp_path / "validate",
        segment_list_path=tmp_path / "segments",
        lookup_base=tmp_path,
        rsid_lookup_file=rsid_file,
        **kwargs,
    )


def _read(path: Path | None) -> list[dict[str, str]]:
    assert path is not None
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_apply_bot_rule_number_replaces_leading_digits() -> None:
    assert apply_bot_rule_number("0256 BOT RULE: x - D=1", 257) == "0257 BOT RULE: x - D=1"


def test_apply_bot_rule_number_prepends_when_missing() -> None:
    assert apply_bot_rule_number("BOT RULE: x - D=1", 7) == "0007 BOT RULE: x - D=1"


def test_apply_bot_rule_number_does_not_treat_five_digits_as_number() -> None:
    assert apply_bot_rule_number("12345 thing", 9) == "0009 12345 thing"


def test_renumber_validate_rows_skips_compares_and_numbers_specials() -> None:
    rows = [
        _csv_row("Compare", "BOTCOMPARE_A~x", 1),
        _csv_row("Validate", "0256 BOT RULE: a", 2),
        _csv_row("Compare - Special", "BOTCOMPARE_B~y", 3),
        _csv_row("Validate - Special", "0257 BOT RULE: b", 4),
        _csv_row("Validate", "BOT RULE: c", 5),
    ]
    assert renumber_validate_rows(rows, 300) == 3
    assert [r.segment_name for r in rows] == [
        "BOTCOMPARE_A~x",
        "0300 BOT RULE: a",
        "BOTCOMPARE_B~y",
        "0301 BOT RULE: b",
        "0302 BOT RULE: c",
    ]


def test_config_defaults() -> None:
    sc = SegmentCreationConfig(
        input_csv="x.csv",
        compare_list_path="c",
        validate_list_path="v",
        segment_list_path="s",
    )
    assert sc.renumber_validates is True
    assert sc.candidate_tag == DEFAULT_CANDIDATE_TAG


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validates_renumbered_from_adobe_and_tagged(tmp_path: Path) -> None:
    client = FakeClient(tagged_names=["0256 BOT RULE: old", "0100 BOT RULE: older", "junk"])
    result = await _run(
        tmp_path,
        client,
        [
            _row("Compare", "BOTCOMPARE_AH-X-R1A~compare"),
            _row("Validate", "0001 BOT RULE: TestClient - Domain=bad.com"),
            _row("Validate - Special", "0002 BOT RULE: TestClient - Special", rsid=""),
            _row("Validate", "BOT RULE: TestClient - Domain=worse.com"),
        ],
    )

    assert result.error_count == 0
    assert len(client.list_calls) == 1
    assert client.list_calls[0]["tag_names"] == [DEFAULT_CANDIDATE_TAG]

    # Compare is created untouched; validates created under their new numbers
    assert client.created == [
        "BOTCOMPARE_AH-X-R1A~compare",
        "0257 BOT RULE: TestClient - Domain=bad.com",
        "0259 BOT RULE: TestClient - Domain=worse.com",
    ]
    # Only the two created validates are tagged (not the compare, not the special)
    assert client.tagged == [
        ("s3938_fake002", [DEFAULT_CANDIDATE_TAG]),
        ("s3938_fake003", [DEFAULT_CANDIDATE_TAG]),
    ]

    assert result.special_validate_names == ["0258 BOT RULE: TestClient - Special"]

    validate = _read(result.validate_list_file)
    assert [r["DimSegmentId"] for r in validate] == [
        "s3938_fake002",
        "UPDATE-SEGMENT-ID",
        "s3938_fake003",
    ]
    assert [r["botRuleName"][:4] for r in validate] == ["0257", "0258", "0259"]

    segs = json.loads(result.segment_list_file.read_text())
    assert [s["name"][:4] for s in segs] == ["BOTC", "0257", "0259"]


@pytest.mark.asyncio
async def test_lookup_failure_falls_back_to_excel_numbers(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client = FakeClient(list_error=RuntimeError("broker unreachable"))
    result = await _run(
        tmp_path, client, [_row("Validate", "0042 BOT RULE: TestClient - Domain=bad.com")]
    )
    assert result.error_count == 0
    assert client.created == ["0042 BOT RULE: TestClient - Domain=bad.com"]
    assert "keeping the numbers from the input CSV" in caplog.text


@pytest.mark.asyncio
async def test_renumber_disabled_keeps_names_and_skips_lookup(tmp_path: Path) -> None:
    client = FakeClient(tagged_names=["0500 BOT RULE: x"])
    await _run(
        tmp_path,
        client,
        [_row("Validate", "0042 BOT RULE: TestClient - Domain=bad.com")],
        renumber_validates=False,
    )
    assert client.list_calls == []
    assert client.created == ["0042 BOT RULE: TestClient - Domain=bad.com"]
    # Tagging is independent of renumbering
    assert client.tagged == [("s3938_fake001", [DEFAULT_CANDIDATE_TAG])]


@pytest.mark.asyncio
async def test_compare_only_list_does_not_look_up_numbers(tmp_path: Path) -> None:
    client = FakeClient(tagged_names=["0500 BOT RULE: x"])
    await _run(tmp_path, client, [_row("Compare", "BOTCOMPARE_AH-X-R1A~compare")])
    assert client.list_calls == []
    assert client.tagged == []


@pytest.mark.asyncio
async def test_test_mode_row_makes_no_lookup(tmp_path: Path) -> None:
    client = FakeClient(tagged_names=["0500 BOT RULE: x"])
    (tmp_path / "Domain").mkdir()
    await _run(
        tmp_path,
        client,
        [_row("Validate", "0042 BOT RULE: TestClient - Domain=bad.com")],
        test_mode_row=1,
    )
    assert client.list_calls == []
    assert client.created == []


@pytest.mark.asyncio
async def test_tag_failure_does_not_fail_row(tmp_path: Path) -> None:
    client = FakeClient(tag_error=RuntimeError("not owner"))
    result = await _run(
        tmp_path, client, [_row("Validate", "0042 BOT RULE: TestClient - Domain=bad.com")]
    )
    assert result.error_count == 0
    assert result.created_count == 1
    assert len(result.tag_failures) == 1
    assert "not owner" in result.tag_failures[0]
    assert _read(result.validate_list_file)[0]["DimSegmentId"] == "s3938_fake001"


@pytest.mark.asyncio
async def test_custom_candidate_tag_used_for_lookup_and_tagging(tmp_path: Path) -> None:
    client = FakeClient(tagged_names=["0010 BOT RULE: x"])
    await _run(
        tmp_path,
        client,
        [_row("Validate", "BOT RULE: TestClient - Domain=bad.com")],
        candidate_tag="OtherTag",
    )
    assert client.list_calls[0]["tag_names"] == ["OtherTag"]
    assert client.created == ["0011 BOT RULE: TestClient - Domain=bad.com"]
    assert client.tagged == [("s3938_fake001", ["OtherTag"])]
