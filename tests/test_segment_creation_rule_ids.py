"""Tests for Rule ID naming (MDL plan A4) and per-segment YAML records (A5)."""

import csv
from pathlib import Path
from typing import Any

import pytest

from adobe_downloader.config.schema import SegmentCreationConfig
from adobe_downloader.flows.segment_creation import _read_csv, run_segment_creation
from adobe_downloader.segments.rule_ids import (
    build_compare_bot_rule_name,
    build_compare_segment_name,
    build_validate_segment_name,
    parse_rule_id,
)
from adobe_downloader.segments.segment_records import (
    default_records_path,
    load_record,
    record_filename,
)

FIXTURES = Path(__file__).parent / "fixtures" / "segment_creation"

# Headers exactly as SegmentCreationList_Final!J13:AA13 in the V3 workbook.
WORKBOOK_HEADERS = [
    "CompareValidate",
    "Round ID",
    "Rule ID",
    "SegmentName",
    "Has Prior Step",
    "Has Following Step",
    "Prior Rule 1",
    "Prior Rule 2",
    "Prior Rule 3",
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

RSIDS = {
    "Oddspediacom": "rsid_odds",
    "OnlineSlotscom": "rsid_slots",
    "coverscom": "rsid_covers",
    "OnlineGamblingcom": "rsid_og",
    "Casinoorg": "rsid_casino",
    "Gurumain": "rsid_guru",
}


class FakeClient:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.list_calls = 0

    async def list_segments(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_calls += 1
        return [{"name": "0300 BOT RULE: old"}]

    async def create_segment(self, seg_def: dict[str, Any]) -> dict[str, Any]:
        self.created.append(seg_def)
        return {"id": f"s3938_fake{len(self.created):03d}"}

    async def share_segment(self, seg_id: str, user_ids: list[str]) -> None:
        pass

    async def tag_segment(self, seg_id: str, tags: list[str]) -> list[str]:
        return tags


def _env(tmp_path: Path) -> tuple[Path, Path]:
    """RSID lookup file and lookup base (BrowserType / MonitorResolution need lookups)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    rsid_file = tmp_path / "suites.txt"
    rsid_file.write_text("".join(f"{v}:{k}\n" for k, v in RSIDS.items()))
    lookup_base = tmp_path / "lookups"
    for folder, lines in {
        "variablesbrowsertype": "Google|42\n",
        "variablesmonitorresolution": "1920 x 1080|7\n",
    }.items():
        (lookup_base / folder).mkdir(parents=True)
        (lookup_base / folder / "lookup.txt").write_text(lines)
    return rsid_file, lookup_base


async def _run(tmp_path: Path, input_csv: Path, client: Any, **kwargs: Any) -> Any:
    rsid_file, lookup_base = _env(tmp_path)
    kwargs.setdefault("segment_records_path", tmp_path / "records")
    return await run_segment_creation(
        client=client,
        input_csv=input_csv,
        share_with_users=[],
        compare_list_path=tmp_path / "compare",
        validate_list_path=tmp_path / "validate",
        segment_list_path=tmp_path / "segments",
        lookup_base=lookup_base,
        rsid_lookup_file=rsid_file,
        **kwargs,
    )


def _read(path: Path | None) -> list[dict[str, str]]:
    assert path is not None
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _workbook_csv(tmp_path: Path, rows: list[dict[str, str]], name: str = "AH-Odds-R1") -> Path:
    f = tmp_path / f"{name}.csv"
    with f.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=WORKBOOK_HEADERS, restval="")
        writer.writeheader()
        writer.writerows(rows)
    return f


def _wb_row(cv: str, rule_id: str, segment_name: str = "", **extra: str) -> dict[str, str]:
    row = {
        "CompareValidate": cv,
        "Rule ID": rule_id,
        "SegmentName": segment_name,
        "Has Prior Step": "FALSE",
        "Has Following Step": "TRUE",
        "Prior Rule 1": "None",
        "Prior Rule 2": "None",
        "Prior Rule 3": "None",
        "RSIDCleanName": "Oddspediacom",
        "Dimension1": "OperatingSystem",
        "Dimension1Item": "Linux",
        "Dimension2": "BrowserType",
        "Dimension2Item": "Google",
        "Dimension3": "Domain",
        "Dimension3Item": "cox.com",
    }
    row.update(extra)
    return row


# ---------------------------------------------------------------------------
# Rule ID grammar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule_id", "round_id", "parent"),
    [
        ("AH-Oddspedia-IR", "AH-Oddspedia-IR", None),
        ("AH-Oddspedia-R1A", "AH-Oddspedia-R1", "AH-Oddspedia-IR"),
        ("RT-Oddspedia-R1A2B", "AH-Oddspedia-R1A2".replace("AH", "RT"), "RT-Oddspedia-R1A"),
        ("AH-X9-R1A2B3AA", "AH-X9-R1A2B3", "AH-X9-R1A2B"),
    ],
)
def test_parse_rule_id(rule_id: str, round_id: str, parent: str | None) -> None:
    parts = parse_rule_id(rule_id)
    assert parts.round_id == round_id
    assert parts.parent_rule_id == parent
    assert parts.super_investigation == rule_id.rsplit("-", 1)[0]


@pytest.mark.parametrize(
    "bad",
    [
        "XX-Oddspedia-R1A",  # prefix must be AH or RT
        "AH-Odds-pedia-R1A",  # hyphen in free text
        "AH-Odds_pedia-R1A",  # underscore in free text
        "AH-Oddspedia-R1",  # no letter
        "AH-Oddspedia-RA",  # no round
        "AH-Oddspedia-R1a",  # lowercase letter
        "LegacyBotRule003B-RoundOne",
    ],
)
def test_parse_rule_id_rejects(bad: str) -> None:
    with pytest.raises(ValueError, match="does not match"):
        parse_rule_id(bad)


# ---------------------------------------------------------------------------
# Name builders
# ---------------------------------------------------------------------------

DIMS = [("OperatingSystem", "Linux"), ("BrowserType", "Google"), ("Domain", "cox.com")]


def test_validate_name_matches_workbook_format() -> None:
    assert (
        build_validate_segment_name("Oddspediacom", DIMS, 257) == "0257 BOT RULE: Oddspediacom - "
        "OperatingSystem=LinuxANDBrowserType=GoogleANDDomain=cox.com"
    )
    assert build_validate_segment_name("x", DIMS[:1], None) == "BOT RULE: x - OperatingSystem=Linux"


def test_compare_names_keep_rule_id_verbatim() -> None:
    assert (
        build_compare_segment_name("AH-Oddspedia-R1A", "Oddspediacom", DIMS)
        == "BOTCOMPARE_AH-Oddspedia-R1A~ Oddspediacom - "
        "OperatingSystem=LinuxANDBrowserType=GoogleANDDomain=cox.com"
    )
    assert (
        build_compare_bot_rule_name("AH-Oddspedia-R1A", "Oddspediacom", DIMS)
        # 100 chars unabbreviated, so the description is abbreviated to fit 95
        == "BOTCOMPARE_AH-Oddspedia-R1A~OddspediacomOS=LinuxANDBrowType=GoogleANDDom=coxcom"
    )


def test_compare_bot_rule_name_shortens_only_the_description() -> None:
    dims = [
        ("OperatingSystem", "Linux"),
        ("BrowserType", "Google"),
        ("Domain", "a-very-long-domain-name-for-testing.example.com"),
        ("UserAgent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"),
    ]
    name = build_compare_bot_rule_name("AH-OddspediaDomain-R1A2B", "Oddspediacom", dims)
    assert len(name) <= 95
    # The Rule ID is untouched even though it contains an abbreviatable word
    assert name.startswith("BOTCOMPARE_AH-OddspediaDomain-R1A2B~Oddspediacom")
    assert "OS=Linux" in name
    assert "Mozilla" not in name


def test_compare_bot_rule_name_drops_useragent_value_anywhere() -> None:
    dims = [("UserAgent", "Mozilla/5.0 (X11)"), ("Domain", "cox.com")]
    assert build_compare_bot_rule_name("AH-X-R1A", "s", dims) == (
        "BOTCOMPARE_AH-X-R1A~sUserAgentANDDomain=coxcom"
    )


# ---------------------------------------------------------------------------
# CSV reading
# ---------------------------------------------------------------------------


def test_read_csv_accepts_workbook_headers_and_treats_none_as_empty(tmp_path: Path) -> None:
    f = _workbook_csv(
        tmp_path,
        [
            _wb_row(
                "Validate",
                "AH-Odds-R1A",
                **{"Round ID": "AH-Odds-R1", "Prior Rule 2": "AH-Odds-R1B", "Has Prior Step": ""},
            )
        ],
    )
    (row,) = _read_csv(f)
    assert row.rule_id == "AH-Odds-R1A"
    assert row.round_id == "AH-Odds-R1"
    assert row.prior_rules == ["AH-Odds-R1B"]
    assert row.has_prior_step is None
    assert row.has_following_step is True


# ---------------------------------------------------------------------------
# Backwards compatibility — real lists without Rule IDs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("list_name", ["LegacyRule003B-RoundOne", "LegacyBotRule003B-RoundTwo"])
async def test_legacy_lists_unchanged(tmp_path: Path, list_name: str) -> None:
    input_csv = FIXTURES / f"{list_name}.csv"
    with input_csv.open(newline="", encoding="utf-8-sig") as fh:
        input_names = [r["SegmentName"] for r in csv.DictReader(fh)]

    client = FakeClient()
    result = await _run(tmp_path, input_csv, client, renumber_validates=False)

    assert result.error_count == 0, result.errors
    assert [s["name"] for s in client.created] == input_names
    assert all(s["description"] == "" for s in client.created)

    def expected(suffix: str) -> list[dict[str, str]]:
        return _read(FIXTURES / f"{list_name}_{suffix}_expected.csv")

    validate = _read(result.validate_list_file)
    assert [r["botRuleName"] for r in validate] == [r["botRuleName"] for r in expected("validate")]
    if (FIXTURES / f"{list_name}_compare_expected.csv").exists():
        compare = _read(result.compare_list_file)
        assert [(r["botRuleName"], r["reportToIgnore"]) for r in compare] == [
            (r["botRuleName"], r["reportToIgnore"]) for r in expected("compare")
        ]

    # Records fall back to the sanitised segment name
    assert len(result.record_files) == len(input_names)
    assert result.record_files[0].name == record_filename(None, input_names[0])
    rec = load_record(result.record_files[0])
    assert rec["rule_id"] is None
    assert rec["segment_name"] == input_names[0]


# ---------------------------------------------------------------------------
# Rule ID lists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rule_id_rows_get_python_built_names_and_records(tmp_path: Path) -> None:
    f = _workbook_csv(
        tmp_path,
        [
            _wb_row("Compare", "AH-Odds-R1A", "#garbage from Excel"),
            _wb_row(
                "Validate",
                "AH-Odds-R1B",
                "0257 BOT RULE: stale name",
                Dimension4="MonitorResolution",
                Dimension4Item="1920x1080",
                **{"Prior Rule 1": "AH-Odds-R1A"},
            ),
            _wb_row("Validate - Special", "AH-Odds-R1C", "", Dimension3Item="special.com"),
        ],
    )
    client = FakeClient()
    result = await _run(tmp_path, f, client)
    assert result.error_count == 0, result.errors

    # Validates renumbered from Adobe (highest 0300) after Python built the names
    assert [s["name"] for s in client.created] == [
        "BOTCOMPARE_AH-Odds-R1A~ Oddspediacom - "
        "OperatingSystem=LinuxANDBrowserType=GoogleANDDomain=cox.com",
        "0301 BOT RULE: Oddspediacom - OperatingSystem=LinuxANDBrowserType=Google"
        "ANDDomain=cox.comANDMonitorResolution=1920x1080",
    ]
    assert [s["description"] for s in client.created] == ["AH-Odds-R1A", "AH-Odds-R1B"]
    assert result.special_validate_names == [
        "0302 BOT RULE: Oddspediacom - OperatingSystem=LinuxANDBrowserType=Google"
        "ANDDomain=special.com"
    ]

    compare = _read(result.compare_list_file)
    assert compare[0]["botRuleName"].startswith("BOTCOMPARE_AH-Odds-R1A~Oddspediacom")

    records = {p.name: load_record(p) for p in result.record_files}
    assert sorted(records) == ["AH-Odds-R1A.yaml", "AH-Odds-R1B.yaml", "AH-Odds-R1C.yaml"]

    cmp_rec = records["AH-Odds-R1A.yaml"]
    assert cmp_rec["round_id"] == "AH-Odds-R1"
    assert cmp_rec["super_investigation"] == "AH-Odds"
    assert cmp_rec["parent_rule_id"] == "AH-Odds-IR"
    assert cmp_rec["bot_rule_number"] is None
    assert cmp_rec["segment_id"] == "s3938_fake001"
    assert cmp_rec["rsid"] == "rsid_odds"
    assert cmp_rec["created_by_job"] == "AH-Odds-R1"
    assert cmp_rec["has_following_step"] is True

    val_rec = records["AH-Odds-R1B.yaml"]
    assert val_rec["bot_rule_number"] == 301
    assert val_rec["prior_rules"] == ["AH-Odds-R1A"]
    assert val_rec["visits_last_12_months"] is None
    assert val_rec["conditions"][1] == {
        "dimension": "BrowserType",
        "adobe_variable": "variables/browsertype",
        "item": "Google",
        "resolved_value": "42",
        "operator": "equals",
    }
    assert val_rec["conditions"][3]["resolved_value"] == "7"

    special = records["AH-Odds-R1C.yaml"]
    assert special["segment_id"] == "UPDATE-SEGMENT-ID"
    assert special["bot_rule_number"] == 302
    assert special["conditions"][1]["resolved_value"] == "42"


@pytest.mark.asyncio
async def test_rule_id_validate_keeps_excel_number_when_renumbering_off(tmp_path: Path) -> None:
    f = _workbook_csv(tmp_path, [_wb_row("Validate", "AH-Odds-R1A", "0257 BOT RULE: stale")])
    client = FakeClient()
    await _run(tmp_path, f, client, renumber_validates=False)
    assert client.created[0]["name"].startswith("0257 BOT RULE: Oddspediacom - ")
    assert client.list_calls == 0


@pytest.mark.asyncio
async def test_records_skipped_without_path(tmp_path: Path) -> None:
    f = _workbook_csv(tmp_path, [_wb_row("Compare", "AH-Odds-R1A")])
    result = await _run(tmp_path, f, FakeClient(), segment_records_path=None)
    assert result.record_files == []
    assert not (tmp_path / "records").exists()


@pytest.mark.asyncio
async def test_rerun_replaces_record(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    f = _workbook_csv(tmp_path, [_wb_row("Compare", "AH-Odds-R1A")])
    first = await _run(tmp_path / "a", f, FakeClient(), segment_records_path=tmp_path / "rec")
    second = await _run(tmp_path / "b", f, FakeClient(), segment_records_path=tmp_path / "rec")
    assert first.record_files == second.record_files
    assert len(list((tmp_path / "rec").iterdir())) == 1
    assert "Replacing existing segment record" in caplog.text


@pytest.mark.asyncio
async def test_test_mode_writes_record_without_segment_id(tmp_path: Path) -> None:
    f = _workbook_csv(tmp_path, [_wb_row("Validate", "AH-Odds-R1A", "0257 BOT RULE: x")])
    client = FakeClient()
    result = await _run(tmp_path, f, client, test_mode_row=1)
    assert client.created == []
    (path,) = result.record_files
    rec = load_record(path)
    assert rec["segment_id"] is None
    assert rec["bot_rule_number"] == 257


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"Rule ID": "AH-Odds-pedia-R1A"}, "Row 1: Rule ID 'AH-Odds-pedia-R1A' does not match"),
        ({"Round ID": "AH-Odds-R2"}, "Row 1: RoundID 'AH-Odds-R2' does not match"),
        ({"Prior Rule 1": "nonsense"}, "Row 1: Prior rule 'nonsense' is not a valid Rule ID"),
        ({"Rule ID": "#REF!"}, "Row 1: column 'ruleid' holds an Excel error value"),
        ({"RSIDCleanName": ""}, "Row 1: Missing RSIDCleanName"),
    ],
)
async def test_bad_rule_id_rows_fail_before_any_api_call(
    tmp_path: Path, override: dict[str, str], message: str
) -> None:
    row = _wb_row("Compare - Special", "AH-Odds-R1A")
    row.update(override)
    f = _workbook_csv(tmp_path, [row])
    client = FakeClient()
    with pytest.raises(ValueError, match="CSV validation errors") as exc:
        await _run(tmp_path, f, client)
    assert message in str(exc.value)
    assert client.created == [] and client.list_calls == 0


def test_config_and_default_records_path() -> None:
    sc = SegmentCreationConfig(
        input_csv="x.csv", compare_list_path="c", validate_list_path="v", segment_list_path="s"
    )
    assert sc.segment_records_path is None
    assert default_records_path("Legend") == Path("data") / "segment_records" / "Legend"
