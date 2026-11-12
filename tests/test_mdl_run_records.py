"""Tests for the generated run config (MDL plan A6) and the segment_records step (A7)."""

import csv
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from adobe_downloader.cli import main
from adobe_downloader.config.schema import CompositeJobConfig
from adobe_downloader.flows.composite_job import run_composite_job, run_segment_records_step
from adobe_downloader.flows.segment_creation import run_segment_creation
from adobe_downloader.flows.segment_records import (
    _month_start,
    run_segment_records,
    sum_visits,
    twelve_month_window,
)
from adobe_downloader.segments.run_config import (
    RunTemplate,
    build_run_config,
    check_lists_have_segment_ids,
    load_run_template,
    placeholder_rows,
)
from adobe_downloader.segments.segment_records import (
    PLACEHOLDER_SEGMENT_ID,
    build_record,
    load_record,
    write_record,
)

REPO = Path(__file__).parent.parent
TEMPLATE = REPO / "jobs" / "templates" / "mdl_run_template.yaml"

VALIDATION_HEADERS = [
    "id",
    "month",
    "unique_visitors",
    "visits",
    "raw_clickouts",
    "engaged_visits",
    "engagement_rate",
    "First_Time_Visits",
    "Total_Seconds_Spent",
    "Page_Views",
    "fileName",
    "requestName",
    "botRuleName",
    "rsidName",
]

V1 = "0301BOTRULEOddspediacomOperatingSystem-LinuxANDBrowserType-Google"
V2_SPECIAL = "0302BOTRULEOddspediacomOperatingSystem-LinuxANDDomain-special-com"
C1 = "BOTCOMPARE_AH-Odds-R1A~OddspediacomOS-Linux"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _template(**overrides: Any) -> RunTemplate:
    raw: dict[str, Any] = {
        "output": {"base_folder": "C:/Adobe_Downloads"},
        "rsids": {"source": "file", "file": "data/rsid_lists/x.txt", "batch_size": 6},
        "date_range": {"from": "2024-01-01"},
    }
    raw.update(overrides)
    return RunTemplate.model_validate(raw)


def _write_list(path: Path, rows: list[tuple[str, str]], compare: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["DimSegmentId", "botRuleName", "reportToIgnore"][: 3 if compare else 2])
        for seg_id, name in rows:
            w.writerow([seg_id, name, "OperatingSystem"][: 3 if compare else 2])
    return path


def _record(
    folder: Path,
    rule_id: str,
    kind: str,
    bot_rule_name: str,
    segment_id: str,
    number: int | None = None,
) -> Path:
    rec = build_record(
        rule_id=rule_id,
        round_id="AH-Odds-R1",
        super_investigation="AH-Odds",
        parent_rule_id="AH-Odds-IR",
        compare_validate=kind,
        next_step=None,
        segment_name=f"name of {rule_id}",
        bot_rule_name=bot_rule_name,
        bot_rule_number=number,
        segment_id=segment_id,
        rsid="rsid_odds",
        rsid_clean_name="Oddspediacom",
        conditions=[
            {"dimension": "OperatingSystem", "item": "Linux"},
            {"dimension": "BrowserType", "item": "Google"},
        ],
        prior_rules=[],
        has_prior_step=False,
        has_following_step=True,
        created_by_job="AH-Odds-R1",
    )
    return write_record(folder, rec)


def _month_rows(
    report: str, rule: str, rsid: str, visits: dict[tuple[int, int], float]
) -> list[dict[str, str]]:
    names = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return [
        {
            "id": f"1{y % 100:02d}{m - 1:02d}01",
            "month": f"{names[m - 1]} {y}",
            "visits": str(v),
            "requestName": report,
            "botRuleName": rule,
            "rsidName": rsid,
        }
        for (y, m), v in visits.items()
    ]


def _write_validation(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=VALIDATION_HEADERS, restval="0.0")
        w.writeheader()
        w.writerows(rows)
    return path


class TagClient:
    def __init__(self, tagged: list[dict[str, Any]], fail: bool = False) -> None:
        self.tagged = tagged
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def list_segments(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("broker down")
        return self.tagged


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# A6: run config
# ---------------------------------------------------------------------------


def test_shipped_template_loads() -> None:
    template = load_run_template(TEMPLATE)
    assert template.segment_records.visits_report == "botFilterExcludexBotRuleMetricsByMonth"
    assert template.date_range.to is None


def test_build_run_config_both_halves() -> None:
    config = build_run_config(
        client="Legend",
        round_id="AH-Odds-R1",
        template=_template(),
        validate_list=Path("jobs/inputs/bot_rule_lists/AH-Odds-R1_validate.csv"),
        compare_list=Path("jobs/inputs/bot_compare_lists/AH-Odds-R1_compare.csv"),
        records_path=Path("data/segment_records/Legend"),
        today=date(2026, 11, 12),
    )
    job = CompositeJobConfig.model_validate(config)
    assert job.output is not None and job.output.job_name == "AH-Odds-R1"
    assert job.date_range is not None
    assert (job.date_range.from_date, job.date_range.to) == ("2024-01-01", "2026-11-11")
    assert [s.id for s in job.steps] == [
        "download_validation",
        "validate_bot_rules",
        "transform_validation",
        "download_compare",
        "validate_bot_compares",
        "transform_compare",
        "segment_records",
    ]
    dl = job.steps[0].extra_fields()
    assert dl["bot_rules"] == {
        "source": "file",
        "file": "jobs/inputs/bot_rule_lists/AH-Odds-R1_validate.csv",
    }
    assert dl["rsids"]["batch_size"] == 6
    records = job.steps[-1]
    assert records.depends_on == "transform_compare"
    assert records.extra_fields()["segment_records"]["compare_list"].endswith("_compare.csv")


def test_build_run_config_validate_only_and_template_to() -> None:
    config = build_run_config(
        client="Legend",
        round_id="AH-Odds-R2",
        template=_template(date_range={"from": "2024-01-01", "to": "2026-08-31"}),
        validate_list=Path("v.csv"),
        compare_list=None,
        records_path=Path("r"),
    )
    assert [s["step"] for s in config["steps"]] == [
        "report_download",
        "validate_output",
        "transform_concat",
        "segment_records",
    ]
    assert config["steps"][-1]["depends_on"] == "transform_validation"
    assert "compare_list" not in config["steps"][-1]["segment_records"]
    assert config["date_range"]["to"] == "2026-08-31"


def test_build_run_config_needs_a_list() -> None:
    with pytest.raises(ValueError, match="no validate or compare list"):
        build_run_config(
            client="Legend",
            round_id="X",
            template=_template(),
            validate_list=None,
            compare_list=None,
            records_path=Path("r"),
        )


# segment_creation integration -------------------------------------------------


class CreateClient:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    async def list_segments(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": "s_old", "name": "0300 BOT RULE: old"}]

    async def create_segment(self, seg_def: dict[str, Any]) -> dict[str, Any]:
        self.created.append(seg_def)
        return {"id": f"s3938_fake{len(self.created):03d}"}

    async def share_segment(self, seg_id: str, user_ids: list[str]) -> None:
        pass

    async def tag_segment(self, seg_id: str, tags: list[str]) -> list[str]:
        return tags


def _creation_csv(path: Path, rule_ids: list[tuple[str, str]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "CompareValidate",
                "Rule ID",
                "SegmentName",
                "RSIDCleanName",
                "Dimension1",
                "Dimension1Item",
            ],
        )
        w.writeheader()
        for cv, rule_id in rule_ids:
            w.writerow(
                {
                    "CompareValidate": cv,
                    "Rule ID": rule_id,
                    "SegmentName": "" if rule_id else "0001 BOT RULE: legacy name",
                    "RSIDCleanName": "Oddspediacom",
                    "Dimension1": "OperatingSystem",
                    "Dimension1Item": "Linux",
                }
            )
    return path


async def _create(tmp_path: Path, input_csv: Path, client: Any, **kwargs: Any) -> Any:
    tmp_path.mkdir(parents=True, exist_ok=True)
    rsid_file = tmp_path / "suites.txt"
    rsid_file.write_text("rsid_odds:Oddspediacom\n")
    template = tmp_path / "template.yaml"
    template.write_text(
        yaml.safe_dump(
            {
                "output": {"base_folder": str(tmp_path / "out")},
                "rsids": {"source": "file", "file": "data/rsid_lists/x.txt"},
                "date_range": {"from": "2024-01-01"},
            }
        )
    )
    kwargs.setdefault("run_template", template)
    return await run_segment_creation(
        client=client,
        input_csv=input_csv,
        share_with_users=[],
        compare_list_path=tmp_path / "compare",
        validate_list_path=tmp_path / "validate",
        segment_list_path=tmp_path / "segments",
        lookup_base=tmp_path / "lookups",
        rsid_lookup_file=rsid_file,
        segment_records_path=tmp_path / "records",
        run_config_path=tmp_path / "generated",
        client_name="Legend",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_segment_creation_writes_run_config(tmp_path: Path) -> None:
    f = _creation_csv(
        tmp_path / "AH-Odds-R1.csv",
        [("Compare", "AH-Odds-R1A"), ("Validate", "AH-Odds-R1B")],
    )
    result = await _create(tmp_path, f, CreateClient())
    assert result.error_count == 0, result.errors
    assert result.run_config_file == tmp_path / "generated" / "AH-Odds-R1_run.yaml"
    job = CompositeJobConfig.model_validate(yaml.safe_load(result.run_config_file.read_text()))
    assert job.output is not None and job.output.job_name == "AH-Odds-R1"
    files = {
        s.id: s.extra_fields()["bot_rules"]["file"] for s in job.steps if s.id.startswith("down")
    }
    assert files == {
        "download_validation": result.validate_list_file.as_posix(),
        "download_compare": result.compare_list_file.as_posix(),
    }
    seg_records = job.steps[-1].extra_fields()["segment_records"]
    assert seg_records["records_path"] == (tmp_path / "records").as_posix()


@pytest.mark.asyncio
async def test_segment_creation_mixed_rounds_fails_before_api(tmp_path: Path) -> None:
    f = _creation_csv(
        tmp_path / "mixed.csv",
        [("Validate", "AH-Odds-R1B"), ("Validate", "AH-Odds-R2A")],
    )
    client = CreateClient()
    with pytest.raises(ValueError, match="AH-Odds-R1, AH-Odds-R2"):
        await _create(tmp_path, f, client)
    assert client.created == []


@pytest.mark.asyncio
async def test_segment_creation_without_template_or_in_test_mode(tmp_path: Path) -> None:
    f = _creation_csv(tmp_path / "AH-Odds-R1.csv", [("Validate", "AH-Odds-R1B")])
    without = await _create(tmp_path / "a", f, CreateClient(), run_template=None)
    assert without.run_config_file is None
    test_mode = await _create(tmp_path / "b", f, CreateClient(), test_mode_row=1)
    assert test_mode.run_config_file is None
    assert not (tmp_path / "b" / "generated").exists()


@pytest.mark.asyncio
async def test_list_without_rule_ids_uses_list_name(tmp_path: Path) -> None:
    f = _creation_csv(tmp_path / "LegacyList.csv", [("Validate", "")])
    result = await _create(tmp_path, f, CreateClient())
    assert result.run_config_file is not None
    assert result.run_config_file.name == "LegacyList_run.yaml"


# Run guard ---------------------------------------------------------------------


def _job_with_list(list_file: Path, source: str = "file") -> CompositeJobConfig:
    bot_rules: dict[str, Any] = {"source": source}
    if source == "file":
        bot_rules["file"] = str(list_file)
    else:
        bot_rules.update(step_id="create", output_key="validate_list_file")
    return CompositeJobConfig.model_validate(
        {
            "job_type": "composite",
            "client": "Legend",
            "output": {"base_folder": "x", "job_name": "J"},
            "steps": [
                {
                    "step": "report_download",
                    "id": "dl",
                    "report_group": "bot_validation",
                    "rsids": {"source": "single", "single": "Oddspediacom"},
                    "bot_rules": bot_rules,
                }
            ],
        }
    )


def test_run_guard_names_placeholder_rows(tmp_path: Path) -> None:
    lst = _write_list(tmp_path / "v.csv", [("s3938_a", V1), (PLACEHOLDER_SEGMENT_ID, V2_SPECIAL)])
    assert placeholder_rows(lst) == [f"row 3: {V2_SPECIAL}"]
    with pytest.raises(ValueError, match=f"row 3: {V2_SPECIAL}"):
        check_lists_have_segment_ids(_job_with_list(lst))


def test_run_guard_passes_clean_missing_and_step_output_lists(tmp_path: Path) -> None:
    clean = _write_list(tmp_path / "v.csv", [("s3938_a", V1)])
    check_lists_have_segment_ids(_job_with_list(clean))
    check_lists_have_segment_ids(_job_with_list(tmp_path / "missing.csv"))
    check_lists_have_segment_ids(_job_with_list(clean, source="step_output"))


class _NoStartSM:
    started = False

    def mark_job_started(self) -> None:
        self.started = True


@pytest.mark.asyncio
async def test_composite_job_refuses_to_start_with_placeholder(tmp_path: Path) -> None:
    lst = _write_list(tmp_path / "v.csv", [(PLACEHOLDER_SEGMENT_ID, V2_SPECIAL)])
    sm = _NoStartSM()
    with pytest.raises(ValueError, match=PLACEHOLDER_SEGMENT_ID):
        await run_composite_job(_job_with_list(lst), tmp_path / "c.yaml", sm, ac=None)
    assert sm.started is False


# ---------------------------------------------------------------------------
# A7: segment_records
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("date_to", "start"),
    [
        (date(2026, 8, 25), date(2025, 9, 1)),
        (date(2026, 1, 31), date(2025, 2, 1)),
        (date(2026, 12, 1), date(2026, 1, 1)),
    ],
)
def test_twelve_month_window(date_to: date, start: date) -> None:
    assert twelve_month_window(date_to) == (start, date_to)


def test_month_start_reads_label_then_adobe_id() -> None:
    assert _month_start({"month": "Sep 2025", "id": "x"}) == date(2025, 9, 1)
    assert _month_start({"month": "", "id": "1250801"}) == date(2025, 9, 1)
    assert _month_start({"month": "?", "id": "?"}) is None


def test_sum_visits_window_rsids_and_report_filter(tmp_path: Path) -> None:
    report = "botFilterExcludexBotRuleMetricsByMonth"
    # 3 years of 10 visits a month on one RSID, 1 a month on another.
    months = {(y, m): 10.0 for y in (2023, 2024, 2025, 2026) for m in range(1, 13)}
    rows = _month_rows(report, V1, "Oddspediacom", months)
    rows += _month_rows(report, V1, "Casinoorg", {k: 1.0 for k in months})
    rows += _month_rows("botFilterExcludeMetricsByMonth", V1, "Oddspediacom", months)
    rows += _month_rows(report, "OtherRule", "Oddspediacom", {(2020, 1): 5.0})
    f = _write_validation(tmp_path / "VALIDATION_J_x.csv", rows)
    totals = sum_visits([f], report, twelve_month_window(date(2026, 8, 25)))
    assert totals == {V1: 12 * 11.0, "OtherRule": 0.0}


def _setup_round(tmp_path: Path) -> dict[str, Path]:
    records = tmp_path / "records"
    _record(records, "AH-Odds-R1B", "Validate", V1, "s3938_val", 301)
    _record(records, "AH-Odds-R1C", "Validate - Special", V2_SPECIAL, PLACEHOLDER_SEGMENT_ID, 302)
    _record(records, "AH-Odds-R1A", "Compare", C1, "s3938_cmp")
    validate = _write_list(
        tmp_path / "lists" / "AH-Odds-R1_validate.csv",
        [("s3938_val", V1), ("s3938_special", V2_SPECIAL)],
    )
    compare = _write_list(
        tmp_path / "lists" / "AH-Odds-R1_compare.csv", [("s3938_cmp", C1)], compare=True
    )
    out = tmp_path / "out" / "Legend" / "AH-Odds-R1"
    report = "botFilterExcludexBotRuleMetricsByMonth"
    _write_validation(
        out / f"VALIDATION_AH-Odds-R1_{V1}.csv",
        _month_rows(report, V1, "Oddspediacom", {(2025, 8): 1000.0, (2025, 9): 5.0})
        + _month_rows(report, V1, "Casinoorg", {(2026, 8): 7.0}),
    )
    _write_validation(
        out / f"VALIDATION_AH-Odds-R1_{V2_SPECIAL}.csv",
        _month_rows(report, V2_SPECIAL, "Oddspediacom", {(2026, 1): 3.0}),
    )
    return {"records": records, "validate": validate, "compare": compare, "out": out}


@pytest.mark.asyncio
async def test_segment_records_end_to_end(tmp_path: Path) -> None:
    p = _setup_round(tmp_path)
    client = TagClient(
        [
            {"id": "s3938_val", "name": "0301 BOT RULE: x"},
            {"id": "s_other", "name": "0410 BOT RULE: someone else's"},
        ]
    )
    result = await run_segment_records(
        client=client,
        round_id="AH-Odds-R1",
        output_folder=p["out"],
        records_path=p["records"],
        validate_list=p["validate"],
        compare_list=p["compare"],
        date_to=date(2026, 8, 25),
    )

    assert client.calls[0]["tag_names"] == ["BotRuleCandidates"]
    assert result.backfilled == [f"{V2_SPECIAL}: s3938_special"]
    assert result.untagged == [f"{V2_SPECIAL} (s3938_special)"]
    assert result.missing_records == [] and result.missing_visits == []

    val = load_record(p["records"] / "AH-Odds-R1B.yaml")
    assert val["visits_last_12_months"] == 12  # Aug 2025 is outside the window
    assert val["visits_window"] == {"from": "2025-09-01", "to": "2026-08-25"}
    special = load_record(p["records"] / "AH-Odds-R1C.yaml")
    assert special["segment_id"] == "s3938_special"
    assert special["visits_last_12_months"] == 3
    cmp = load_record(p["records"] / "AH-Odds-R1A.yaml")
    assert cmp["visits_last_12_months"] is None
    assert cmp["visits_window"] == {"from": None, "to": None}

    rows = _read_csv(p["out"] / "AH-Odds-R1_segment_records.csv")
    assert [(r["RuleID"], r["SegmentId"], r["Visits12m"]) for r in rows] == [
        ("AH-Odds-R1B", "s3938_val", "12"),
        ("AH-Odds-R1C", "s3938_special", "3"),
        ("AH-Odds-R1A", "s3938_cmp", ""),
    ]
    assert rows[0]["BotRuleNumber"] == "301"
    assert rows[0]["Dimension2Item"] == "Google" and rows[0]["Dimension3"] == ""

    assert result.details_files == [p["out"] / "AH-Odds-R1A_segment_details.csv"]
    with result.details_files[0].open(newline="", encoding="utf-8") as fh:
        details = dict(list(csv.reader(fh))[1:])
    assert details["RuleID"] == "AH-Odds-R1A"
    assert details["RoundID"] == "AH-Odds-R1"
    assert details["SegmentId"] == "s3938_cmp"
    assert details["LastBotRuleNumber"] == "410"  # highest tagged in Adobe
    assert details["Dimension1"] == "OperatingSystem"
    assert details["Dimension1Item"] == "Linux"


@pytest.mark.asyncio
async def test_segment_records_placeholder_missing_and_tag_failure(tmp_path: Path) -> None:
    p = _setup_round(tmp_path)
    _write_list(
        p["validate"],
        [(PLACEHOLDER_SEGMENT_ID, V2_SPECIAL), ("s3938_new", "0303BOTRULEnorecord")],
    )
    result = await run_segment_records(
        client=TagClient([], fail=True),
        round_id="AH-Odds-R1",
        output_folder=p["out"],
        records_path=p["records"],
        validate_list=p["validate"],
        compare_list=p["compare"],
        date_to=date(2026, 8, 25),
    )
    assert result.tag_check_error == "broker down"
    assert result.untagged == []
    assert result.still_placeholder == [V2_SPECIAL]
    assert result.missing_records == ["Validate: 0303BOTRULEnorecord"]
    special = load_record(p["records"] / "AH-Odds-R1C.yaml")
    assert special["segment_id"] == PLACEHOLDER_SEGMENT_ID
    assert special["visits_last_12_months"] is None
    # Falls back to the highest number among this round's records.
    with (p["out"] / "AH-Odds-R1A_segment_details.csv").open(encoding="utf-8") as fh:
        assert "LastBotRuleNumber,302" in fh.read()


@pytest.mark.asyncio
async def test_segment_records_missing_visits_and_needs_date(tmp_path: Path) -> None:
    p = _setup_round(tmp_path)
    for f in p["out"].glob("VALIDATION_*.csv"):
        f.unlink()
    result = await run_segment_records(
        client=None,
        round_id="AH-Odds-R1",
        output_folder=p["out"],
        records_path=p["records"],
        validate_list=p["validate"],
        compare_list=None,
        date_to=date(2026, 8, 25),
    )
    assert result.missing_visits == [V1, V2_SPECIAL]
    assert load_record(p["records"] / "AH-Odds-R1B.yaml")["visits_last_12_months"] is None
    with pytest.raises(ValueError, match="date_to"):
        await run_segment_records(
            client=None,
            round_id="AH-Odds-R1",
            output_folder=p["out"],
            records_path=p["records"],
            validate_list=p["validate"],
            compare_list=None,
            date_to=None,
        )


def _run_job(p: dict[str, Path], tmp_path: Path) -> CompositeJobConfig:
    return CompositeJobConfig.model_validate(
        {
            "job_type": "composite",
            "client": "Legend",
            "date_range": {"from": "2023-09-01", "to": "2026-08-25"},
            "output": {"base_folder": str(tmp_path / "out"), "job_name": "AH-Odds-R1"},
            "steps": [
                {
                    "step": "segment_records",
                    "id": "segment_records",
                    "segment_records": {
                        "validate_list": str(p["validate"]),
                        "compare_list": str(p["compare"]),
                        "records_path": str(p["records"]),
                    },
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_segment_records_composite_step(tmp_path: Path) -> None:
    p = _setup_round(tmp_path)
    job = _run_job(p, tmp_path)
    out = await run_segment_records_step(job.steps[0], job, TagClient([]))
    assert out["records_csv"] == str(p["out"] / "AH-Odds-R1_segment_records.csv")
    assert out["records_updated"] == 2  # validate visits + special back-fill and visits
    assert len(out["untagged"]) == 2


def test_segment_records_config_needs_a_list() -> None:
    from adobe_downloader.config.schema import SegmentRecordsConfig

    with pytest.raises(ValueError, match="validate_list, compare_list or both"):
        SegmentRecordsConfig.model_validate({})


def test_segment_records_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _setup_round(tmp_path)
    config = tmp_path / "AH-Odds-R1_run.yaml"
    config.write_text(yaml.safe_dump(_run_job(p, tmp_path).model_dump(by_alias=True)))
    monkeypatch.setattr("adobe_downloader.utils.logging.setup_logging", lambda *a, **k: None)
    result = CliRunner().invoke(
        main, ["segment-records", "--config", str(config), "--no-tag-check"]
    )
    assert result.exit_code == 0, result.output
    assert "Records updated: 2" in result.output
    assert "AH-Odds-R1A_segment_details.csv" in result.output
    assert load_record(p["records"] / "AH-Odds-R1B.yaml")["visits_last_12_months"] == 12


def test_segment_records_cli_needs_one_source() -> None:
    result = CliRunner().invoke(main, ["segment-records"])
    assert result.exit_code == 1
    assert "exactly one of --job or --config" in result.output
