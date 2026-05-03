"""Tests for segment creation utilities and flow."""

import csv
import json
from pathlib import Path

import pytest

from adobe_downloader.segments.create_segment import (
    build_dual_condition_segment,
    build_single_condition_segment,
    get_dimension_description,
    get_dimension_id,
    load_lookup_file,
    normalize_monitor_resolution,
    requires_lookup,
    resolve_dimension_value,
)
from adobe_downloader.flows.segment_creation import (
    _ensure_max_length,
    _read_csv,
    _validate_row,
    transform_to_bot_rule_name,
    transform_to_validate_bot_rule_name,
)
from adobe_downloader.utils.rsid_lookup import find_latest_rsid_file, load_rsid_lookup, lookup_rsid


# ---------------------------------------------------------------------------
# create_segment helpers
# ---------------------------------------------------------------------------


def test_get_dimension_id_known() -> None:
    assert get_dimension_id("Domain") == "variables/filtereddomain"
    assert get_dimension_id("BrowserType") == "variables/browsertype"
    assert get_dimension_id("User Agent") == "variables/evar23"


def test_get_dimension_id_unknown() -> None:
    assert get_dimension_id("Foobar") is None


def test_get_dimension_description() -> None:
    assert get_dimension_description("OperatingSystems") == "Operating Systems"
    assert get_dimension_description("Region") == "Region"


def test_requires_lookup_true() -> None:
    assert requires_lookup("BrowserType")
    assert requires_lookup("MonitorResolution")
    assert requires_lookup("Marketing Channel")
    assert requires_lookup("Regions")


def test_requires_lookup_false() -> None:
    assert not requires_lookup("Domain")
    assert not requires_lookup("UserAgent")
    assert not requires_lookup("Operating System")


def test_normalize_monitor_resolution() -> None:
    assert normalize_monitor_resolution("800x600") == "800 x 600"
    assert normalize_monitor_resolution("1920 x 1080") == "1920 x 1080"
    assert normalize_monitor_resolution("1024X768") == "1024 x 768"


def test_build_single_condition_segment_string() -> None:
    seg = build_single_condition_segment(
        name="Test Segment",
        rsid="myrsid123",
        dimension="Domain",
        value="example.com",
        is_numeric=False,
    )
    assert seg["name"] == "Test Segment"
    assert seg["rsid"] == "myrsid123"
    assert seg["isPostShardId"] is True
    assert seg["definition"]["func"] == "segment"
    pred = seg["definition"]["container"]["pred"]
    assert pred["func"] == "streq"
    assert pred["str"] == "example.com"
    assert pred["val"]["name"] == "variables/filtereddomain"


def test_build_single_condition_segment_numeric() -> None:
    seg = build_single_condition_segment(
        name="Browser Test",
        rsid="myrsid",
        dimension="BrowserType",
        value="8",
        is_numeric=True,
    )
    pred = seg["definition"]["container"]["pred"]
    assert pred["func"] == "eq"
    assert pred["num"] == 8
    assert "str" not in pred


def test_build_dual_condition_segment() -> None:
    seg = build_dual_condition_segment(
        name="Dual Test",
        rsid="myrsid",
        dimension1="Domain",
        value1="bad.com",
        is_numeric1=False,
        dimension2="BrowserType",
        value2="5",
        is_numeric2=True,
    )
    outer = seg["definition"]["container"]["pred"]
    assert outer["func"] == "container"
    assert outer["context"] == "hits"
    and_pred = outer["pred"]
    assert and_pred["func"] == "and"
    assert len(and_pred["preds"]) == 2
    assert and_pred["preds"][0]["func"] == "streq"
    assert and_pred["preds"][1]["func"] == "eq"


def test_load_lookup_file(tmp_path: Path) -> None:
    lf = tmp_path / "lookup.txt"
    lf.write_text(
        "// comment\n"
        "Google|8\n"
        "Apple|6\n"
        "* another comment\n"
        "Samsung|24\n"
    )
    result = load_lookup_file(lf)
    assert result == {"Google": "8", "Apple": "6", "Samsung": "24"}


def test_load_lookup_file_missing(tmp_path: Path) -> None:
    assert load_lookup_file(tmp_path / "nonexistent.txt") == {}


def test_resolve_dimension_value_string(tmp_path: Path) -> None:
    value, is_num = resolve_dimension_value("Domain", "example.com", tmp_path)
    assert value == "example.com"
    assert is_num is False


def test_resolve_dimension_value_numeric_found(tmp_path: Path) -> None:
    lookup_dir = tmp_path / "variablesbrowsertype"
    lookup_dir.mkdir()
    (lookup_dir / "lookup.txt").write_text("Google|8\nApple|6\n")
    value, is_num = resolve_dimension_value("BrowserType", "Google", tmp_path)
    assert value == "8"
    assert is_num is True


def test_resolve_dimension_value_numeric_not_found(tmp_path: Path) -> None:
    lookup_dir = tmp_path / "variablesbrowsertype"
    lookup_dir.mkdir()
    (lookup_dir / "lookup.txt").write_text("Google|8\n")
    with pytest.raises(LookupError, match="not found in lookup"):
        resolve_dimension_value("BrowserType", "Unknown Browser", tmp_path)


def test_resolve_dimension_value_monitor_normalised(tmp_path: Path) -> None:
    lookup_dir = tmp_path / "variablesmonitorresolution"
    lookup_dir.mkdir()
    (lookup_dir / "lookup.txt").write_text("1920 x 1080|42\n")
    value, is_num = resolve_dimension_value("MonitorResolution", "1920x1080", tmp_path)
    assert value == "42"
    assert is_num is True


# ---------------------------------------------------------------------------
# rsid_lookup
# ---------------------------------------------------------------------------


def test_load_rsid_lookup(tmp_path: Path) -> None:
    f = tmp_path / "suites.txt"
    f.write_text("rsid001:CleanNameA\nrsid002:CleanNameB\n")
    result = load_rsid_lookup(f)
    assert result == {"CleanNameA": "rsid001", "CleanNameB": "rsid002"}


def test_lookup_rsid_found(tmp_path: Path) -> None:
    f = tmp_path / "suites.txt"
    f.write_text("rsid001:CleanNameA\nrsid002:CleanNameB\n")
    assert lookup_rsid("CleanNameA", f) == "rsid001"


def test_lookup_rsid_case_insensitive(tmp_path: Path) -> None:
    f = tmp_path / "suites.txt"
    f.write_text("rsid001:CleanNameA\n")
    assert lookup_rsid("cleannamea", f) == "rsid001"


def test_lookup_rsid_not_found(tmp_path: Path) -> None:
    f = tmp_path / "suites.txt"
    f.write_text("rsid001:CleanNameA\n")
    assert lookup_rsid("NoSuchName", f) is None


def test_find_latest_rsid_file(tmp_path: Path) -> None:
    (tmp_path / "suites20250101.txt").write_text("x:y\n")
    import time; time.sleep(0.01)
    latest = tmp_path / "suites20251231.txt"
    latest.write_text("a:b\n")
    found = find_latest_rsid_file(tmp_path)
    assert found == latest


def test_find_latest_rsid_file_empty(tmp_path: Path) -> None:
    assert find_latest_rsid_file(tmp_path) is None


# ---------------------------------------------------------------------------
# bot rule name transformations
# ---------------------------------------------------------------------------


def test_transform_to_bot_rule_name_basic() -> None:
    result = transform_to_bot_rule_name("BOTCOMPARE_Test_01: Referring Domain = Bing")
    assert " " not in result
    assert ":" not in result


def test_transform_to_bot_rule_name_user_agent_stripped() -> None:
    result = transform_to_bot_rule_name(
        "BOTCOMPARE: UserAgent = Mozilla/5.0 (Windows; very long value) AND Domain = example.com"
    )
    assert "Mozilla" not in result
    assert "Windows" not in result
    # AND Domain portion should survive
    assert "example" in result


def test_transform_to_validate_bot_rule_name_basic() -> None:
    result = transform_to_validate_bot_rule_name("0158 BOT RULE: Cardschat - OperatingSystem=Android")
    assert " " not in result


def test_ensure_max_length_short() -> None:
    assert _ensure_max_length("short") == "short"


def test_ensure_max_length_with_abbreviations() -> None:
    name = "A" * 50 + "OperatingSystem" + "B" * 40
    result = _ensure_max_length(name)
    assert len(result) <= 95
    assert "OperatingSystem" not in result
    assert "OS" in result


def test_ensure_max_length_truncation() -> None:
    name = "x" * 200
    result = _ensure_max_length(name)
    assert len(result) == 95


# ---------------------------------------------------------------------------
# CSV reading and validation
# ---------------------------------------------------------------------------


def _make_csv(tmp_path: Path, rows: list[dict]) -> Path:
    f = tmp_path / "test.csv"
    fieldnames = ["CompareValidate", "SegmentName", "RSIDCleanName", "Dimension1", "Dimension1Item", "Dimension2", "Dimension2Item"]
    with f.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return f


def test_read_csv(tmp_path: Path) -> None:
    path = _make_csv(tmp_path, [
        {"CompareValidate": "Compare", "SegmentName": "Seg1", "RSIDCleanName": "CleanA",
         "Dimension1": "Domain", "Dimension1Item": "bad.com", "Dimension2": "", "Dimension2Item": ""},
    ])
    rows = _read_csv(path)
    assert len(rows) == 1
    assert rows[0].segment_name == "Seg1"
    assert rows[0].compare_validate == "Compare"


def test_validate_row_valid(tmp_path: Path) -> None:
    path = _make_csv(tmp_path, [
        {"CompareValidate": "Validate", "SegmentName": "S", "RSIDCleanName": "R",
         "Dimension1": "Domain", "Dimension1Item": "x.com", "Dimension2": "", "Dimension2Item": ""},
    ])
    rows = _read_csv(path)
    assert _validate_row(rows[0]) == []


def test_validate_row_missing_segment_name(tmp_path: Path) -> None:
    path = _make_csv(tmp_path, [
        {"CompareValidate": "Compare", "SegmentName": "", "RSIDCleanName": "R",
         "Dimension1": "Domain", "Dimension1Item": "x.com", "Dimension2": "", "Dimension2Item": ""},
    ])
    rows = _read_csv(path)
    errors = _validate_row(rows[0])
    assert any("SegmentName" in e for e in errors)


def test_validate_row_invalid_compare_validate(tmp_path: Path) -> None:
    path = _make_csv(tmp_path, [
        {"CompareValidate": "Bad", "SegmentName": "S", "RSIDCleanName": "R",
         "Dimension1": "Domain", "Dimension1Item": "x.com", "Dimension2": "", "Dimension2Item": ""},
    ])
    rows = _read_csv(path)
    errors = _validate_row(rows[0])
    assert any("CompareValidate" in e for e in errors)


def test_validate_row_special_skips_dim_check(tmp_path: Path) -> None:
    path = _make_csv(tmp_path, [
        {"CompareValidate": "Compare - Special", "SegmentName": "S", "RSIDCleanName": "",
         "Dimension1": "", "Dimension1Item": "", "Dimension2": "", "Dimension2Item": ""},
    ])
    rows = _read_csv(path)
    assert _validate_row(rows[0]) == []


# ---------------------------------------------------------------------------
# run_segment_creation (unit, no real API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_segment_creation_special_only(tmp_path: Path) -> None:
    """Special-only CSV produces no API calls and writes compare CSV."""
    from adobe_downloader.flows.segment_creation import run_segment_creation

    input_csv = _make_csv(tmp_path, [
        {"CompareValidate": "Compare - Special", "SegmentName": "BOTCOMPARE_Special_01: Test",
         "RSIDCleanName": "", "Dimension1": "Domain", "Dimension1Item": "",
         "Dimension2": "", "Dimension2Item": ""},
    ])
    rsid_file = tmp_path / "suites.txt"
    rsid_file.write_text("rsid001:SomeClient\n")

    compare_dir = tmp_path / "compare"
    result = await run_segment_creation(
        client=None,  # no API calls for special-only
        input_csv=input_csv,
        share_with_users=[],
        compare_list_path=compare_dir,
        validate_list_path=None,
        segment_list_path=None,
        lookup_base=tmp_path,
        rsid_lookup_file=rsid_file,
        test_mode_row=None,
    )
    assert result.error_count == 0
    assert result.compare_list_file is not None
    assert result.compare_list_file.exists()
    rows = list(csv.DictReader(result.compare_list_file.open()))
    assert len(rows) == 1
    assert rows[0]["DimSegmentId"] == "UPDATE-SEGMENT-ID"


@pytest.mark.asyncio
async def test_run_segment_creation_with_api(tmp_path: Path) -> None:
    """Normal row calls create_segment and share_segment on the client."""
    from adobe_downloader.flows.segment_creation import run_segment_creation

    input_csv = _make_csv(tmp_path, [
        {"CompareValidate": "Validate", "SegmentName": "0001 BOT: TestClient - Domain = bad.com",
         "RSIDCleanName": "TestClient", "Dimension1": "Domain", "Dimension1Item": "bad.com",
         "Dimension2": "", "Dimension2Item": ""},
    ])
    rsid_file = tmp_path / "suites.txt"
    rsid_file.write_text("rsid123:TestClient\n")

    validate_dir = tmp_path / "validate"
    seg_dir = tmp_path / "segments"

    class FakeClient:
        async def create_segment(self, seg_def: dict) -> dict:
            return {"id": "s3938_fakeid001", "name": seg_def["name"]}

        async def share_segment(self, seg_id: str, user_ids: list) -> None:
            pass

    result = await run_segment_creation(
        client=FakeClient(),
        input_csv=input_csv,
        share_with_users=["user1"],
        compare_list_path=None,
        validate_list_path=validate_dir,
        segment_list_path=seg_dir,
        lookup_base=tmp_path,
        rsid_lookup_file=rsid_file,
        test_mode_row=None,
    )
    assert result.created_count == 1
    assert result.error_count == 0
    assert result.validate_list_file is not None
    assert result.segment_list_file is not None

    rows = list(csv.DictReader(result.validate_list_file.open()))
    assert rows[0]["DimSegmentId"] == "s3938_fakeid001"

    segs = json.loads(result.segment_list_file.read_text())
    assert segs[0]["id"] == "s3938_fakeid001"


@pytest.mark.asyncio
async def test_run_segment_creation_api_error(tmp_path: Path) -> None:
    """API failure increments error_count without raising."""
    from adobe_downloader.flows.segment_creation import run_segment_creation

    input_csv = _make_csv(tmp_path, [
        {"CompareValidate": "Compare", "SegmentName": "Bad Seg",
         "RSIDCleanName": "TestClient", "Dimension1": "Domain", "Dimension1Item": "bad.com",
         "Dimension2": "", "Dimension2Item": ""},
    ])
    rsid_file = tmp_path / "suites.txt"
    rsid_file.write_text("rsid123:TestClient\n")

    class FailClient:
        async def create_segment(self, seg_def: dict) -> dict:
            raise RuntimeError("API down")

    result = await run_segment_creation(
        client=FailClient(),
        input_csv=input_csv,
        share_with_users=[],
        compare_list_path=None,
        validate_list_path=None,
        segment_list_path=None,
        lookup_base=tmp_path,
        rsid_lookup_file=rsid_file,
    )
    assert result.error_count == 1
    assert "API down" in result.errors[0]
