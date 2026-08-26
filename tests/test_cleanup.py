"""Tests for the cleanup job — config schema, scanning, classification, reporting."""

from __future__ import annotations

import json as _json
import os
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from adobe_downloader.config.loader import load_config
from adobe_downloader.config.schema import CleanupJobConfig
from adobe_downloader.flows import cleanup as cl

_TEMPLATE = Path("jobs/templates/cleanup.yaml")


def _cfg(**overrides: object) -> CleanupJobConfig:
    base: dict[str, object] = {"job_type": "cleanup"}
    base.update(overrides)
    return CleanupJobConfig.model_validate(base)


# ---------------------------------------------------------------------------
# Discrimination and template
# ---------------------------------------------------------------------------


def test_template_loads_as_cleanup_config() -> None:
    """The shipped template must round-trip through the real loader."""
    cfg = load_config(_TEMPLATE)
    assert isinstance(cfg, CleanupJobConfig)
    assert cfg.job_type == "cleanup"


def test_job_type_discriminates_from_other_job_types() -> None:
    cfg = _cfg()
    assert isinstance(cfg, CleanupJobConfig)


def test_cleanup_config_needs_no_client() -> None:
    """Cleanup never calls the API, so it carries no client credential requirement."""
    assert not hasattr(_cfg(), "client")


# ---------------------------------------------------------------------------
# Safe-by-default posture
# ---------------------------------------------------------------------------


def test_defaults_are_safe() -> None:
    """An empty cleanup config must not be capable of destroying anything."""
    d = _cfg().defaults
    assert d.dry_run is True
    assert d.action == "quarantine"
    assert d.absolute_min_age_days == 7


def test_template_ships_with_dry_run_enabled() -> None:
    cfg = load_config(_TEMPLATE)
    assert isinstance(cfg, CleanupJobConfig)
    assert cfg.defaults.dry_run is True


def test_protect_defaults_cover_every_transform_prefix() -> None:
    """Every prefix composite_job can emit must be protected out of the box."""
    from adobe_downloader.flows.composite_job import _TRANSFORM_TYPE_PREFIXES

    protected = set(_cfg().protect.final_output_prefixes)
    assert set(_TRANSFORM_TYPE_PREFIXES.values()) <= protected
    # ...plus the fallback used when a transform type is unrecognised.
    assert "OUTPUT" in protected


def test_protect_defaults_cover_the_no_job_name_concat_fallback() -> None:
    """<step_id>_concat.csv lands inside CSV/, so it needs suffix protection."""
    assert "_concat.csv" in _cfg().protect.final_output_suffixes


def test_history_and_running_jobs_protected_by_default() -> None:
    p = _cfg().protect
    assert p.history is True
    assert p.running_jobs is True
    assert p.final_outputs is True


# ---------------------------------------------------------------------------
# Category rules
# ---------------------------------------------------------------------------


def test_yaml_json_key_populates_json_files_field() -> None:
    """The YAML key stays the readable 'json' despite the BaseModel.json clash."""
    cfg = _cfg(categories={"json": {"older_than_days": 3}})
    assert cfg.categories.json_files.older_than_days == 3


def test_json_category_requires_csv_sibling_by_default() -> None:
    assert _cfg().categories.json_files.require_csv_sibling is True


def test_interval_csv_requires_a_newer_final_output_by_default() -> None:
    c = _cfg().categories.interval_csv
    assert c.require_final_output is True
    assert c.require_final_output_newer is True


def test_state_and_log_categories_default_to_completed_jobs_only() -> None:
    cats = _cfg().categories
    assert cats.state_db.require_job_status == ["completed"]
    assert cats.logs.require_job_status == ["completed"]
    assert cats.state_db.keep_unknown is True
    assert cats.logs.keep_unknown is True


def test_rotated_logs_age_out_sooner_than_the_live_log() -> None:
    logs = _cfg().categories.logs
    assert logs.rotated_older_than_days < logs.older_than_days


def test_zip_archives_disabled_by_default() -> None:
    assert _cfg().categories.zip_archives.enabled is False


def test_negative_staleness_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _cfg(categories={"logs": {"older_than_days": -1}})
    with pytest.raises(ValidationError):
        _cfg(defaults={"absolute_min_age_days": -1})


def test_unknown_job_status_filter_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _cfg(categories={"state_db": {"require_job_status": ["nearly"]}})


# ---------------------------------------------------------------------------
# Quarantine folder validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "   ", "C:/trash", "/tmp/trash", "a/b", r"a\b"])
def test_quarantine_folder_must_be_a_single_relative_name(bad: str) -> None:
    """A quarantine path escaping the client folder would move files out of reach."""
    with pytest.raises(ValidationError):
        _cfg(defaults={"quarantine_folder": bad})


def test_quarantine_folder_accepts_a_plain_name() -> None:
    assert _cfg(defaults={"quarantine_folder": "_attic"}).defaults.quarantine_folder == "_attic"


# ---------------------------------------------------------------------------
# Separation from the download pipeline
# ---------------------------------------------------------------------------


def test_run_refuses_a_cleanup_config(tmp_path: Path) -> None:
    """`run` must never execute a cleanup — a mistyped path shouldn't delete output."""
    from click.testing import CliRunner

    from adobe_downloader.cli import main

    cfg = tmp_path / "my_cleanup.yaml"
    cfg.write_text("job_type: cleanup\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["run", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "clean --config" in result.output


def test_cleanup_is_not_a_valid_composite_step() -> None:
    """Cleanup must not be schedulable inside a download pipeline."""
    from adobe_downloader.config.schema import CompositeJobConfig

    with pytest.raises(ValidationError):
        CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "steps": [{"step": "cleanup", "id": "tidy"}],
            }
        )


def test_validate_accepts_a_cleanup_config(tmp_path: Path) -> None:
    """`validate` must handle a config that has no client and no credentials."""
    from click.testing import CliRunner

    from adobe_downloader.cli import main

    cfg = tmp_path / "my_cleanup.yaml"
    cfg.write_text("job_type: cleanup\ndescription: tidy up\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["validate", "--config", str(cfg), "--check-credentials"])
    assert result.exit_code == 0, result.output
    assert "Validation passed" in result.output
    assert "cleanup" in result.output
    # No client means no credentials line to print, and no crash looking for one.
    assert "credentials file found" not in result.output


# ===========================================================================
# Scanning and classification
# ===========================================================================

_NOW = 1_700_000_000.0  # fixed clock, safely in the past, so ages are exact


def _touch(path: Path, *, days_old: float, size: int = 32) -> Path:
    """Create a file of *size* bytes whose mtime is *days_old* days before _NOW."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = _NOW - days_old * cl.SECONDS_PER_DAY
    os.utime(path, (stamp, stamp))
    return path


def _write_history(client_dir: Path, records: list[dict[str, str]]) -> None:
    hist = client_dir / ".history"
    hist.mkdir(parents=True, exist_ok=True)
    lines = [_json.dumps(rec) for rec in records]
    (hist / "job_history.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A synthetic Adobe_Downloads tree covering every classification branch."""
    base = tmp_path / "Adobe_Downloads"
    client = base / "Legend"

    _write_history(
        client,
        [
            {"job_id": "aaa", "config_path": "jobs/done_job.yaml", "status": "completed"},
            {"job_id": "bbb", "config_path": "jobs/failed_job.yaml", "status": "failed"},
        ],
    )
    _touch(client / ".history" / "configs" / "old.yaml", days_old=999)

    # State DBs: completed / failed / no history record at all.
    _touch(client / ".state" / "aaa.db", days_old=60, size=5000)
    _touch(client / ".state" / "bbb.db", days_old=60, size=4000)
    _touch(client / ".state" / "ccc.db", days_old=60, size=3000)

    # Logs: a live log and a rotation for the completed job, plus a failed job's log.
    _touch(client / ".logs" / "done_job.log", days_old=60, size=900)
    _touch(client / ".logs" / "done_job.log.1", days_old=10, size=800)
    _touch(client / ".logs" / "failed_job.log", days_old=60, size=700)

    # A finished job: final output post-dates its intermediates.
    job = client / "MyJob"
    _touch(job / "COMPARE_MyJob_rule1.csv", days_old=999, size=100_000)
    _touch(job / "JSON" / "a.json", days_old=60)
    _touch(job / "JSON" / "b.json", days_old=60)  # no CSV sibling
    _touch(job / "JSON" / "_processed" / "old.json", days_old=60)
    _touch(job / "CSV" / "a.csv", days_old=60)
    _touch(job / "CSV" / "stray_concat.csv", days_old=60)  # no-job_name concat fallback
    _touch(job / "archive.zip", days_old=999, size=50_000)

    # A job that downloaded and transformed but never concatenated.
    unfinished = client / "Unfinished"
    _touch(unfinished / "JSON" / "x.json", days_old=60)
    _touch(unfinished / "CSV" / "x.csv", days_old=60)

    # A job re-run after its concatenation: the final output predates these CSVs.
    restale = client / "Restale"
    _touch(restale / "VALIDATION_Restale.csv", days_old=90, size=10_000)
    _touch(restale / "CSV" / "fresh.csv", days_old=60)

    return base


def _plan(tree_path: Path, **overrides: object) -> cl.CleanupPlan:
    target: dict[str, object] = {"base_folder": str(tree_path)}
    extra_target = overrides.pop("target", None)
    if isinstance(extra_target, dict):
        target.update(extra_target)
    cfg = _cfg(target=target, **overrides)
    return cl.scan(cfg, now=_NOW)


def _verdict_for(plan: cl.CleanupPlan, name: str) -> cl.Verdict:
    matches = [v for v in plan.verdicts if v.file.path.name == name]
    assert len(matches) == 1, f"expected exactly one verdict for {name}, got {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# The audit trail is never a candidate
# ---------------------------------------------------------------------------


def test_history_folder_is_never_scanned(tree: Path) -> None:
    plan = _plan(tree)
    assert not [v for v in plan.verdicts if ".history" in v.file.path.parts]


# ---------------------------------------------------------------------------
# Final outputs survive at any age
# ---------------------------------------------------------------------------


def test_final_output_kept_however_old(tree: Path) -> None:
    plan = _plan(tree)
    v = _verdict_for(plan, "COMPARE_MyJob_rule1.csv")
    assert v.remove is False
    assert v.reason == cl.KEEP_PROTECTED_FINAL_OUTPUT
    assert v.file.category == cl.CATEGORY_FINAL_OUTPUT
    assert plan.bytes_to_remove > 0  # the run did something, it just spared this


def test_concat_fallback_inside_csv_folder_is_kept(tree: Path) -> None:
    """The no-job_name concat output sits among the disposable per-interval CSVs."""
    v = _verdict_for(_plan(tree), "stray_concat.csv")
    assert v.remove is False
    assert v.reason == cl.KEEP_PROTECTED_FINAL_OUTPUT


def test_custom_protect_pattern_is_honoured(tree: Path) -> None:
    plan = _plan(tree, protect={"patterns": ["a.csv"]})
    assert _verdict_for(plan, "a.csv").reason == cl.KEEP_PROTECTED_PATTERN


# ---------------------------------------------------------------------------
# JSON: provable conversion
# ---------------------------------------------------------------------------


def test_json_with_csv_sibling_is_removed(tree: Path) -> None:
    assert _verdict_for(_plan(tree), "a.json").remove is True


def test_json_without_csv_sibling_is_kept(tree: Path) -> None:
    v = _verdict_for(_plan(tree), "b.json")
    assert v.remove is False
    assert v.reason == cl.KEEP_NO_CSV_SIBLING


def test_json_sibling_check_can_be_waived(tree: Path) -> None:
    plan = _plan(tree, categories={"json": {"require_csv_sibling": False}})
    assert _verdict_for(plan, "b.json").remove is True


# ---------------------------------------------------------------------------
# Interval CSVs: concatenation evidence
# ---------------------------------------------------------------------------


def test_csv_removed_when_a_newer_final_output_exists(tree: Path) -> None:
    assert _verdict_for(_plan(tree), "a.csv").remove is True


def test_csv_kept_when_job_never_concatenated(tree: Path) -> None:
    v = _verdict_for(_plan(tree), "x.csv")
    assert v.remove is False
    assert v.reason == cl.KEEP_NO_FINAL_OUTPUT


def test_csv_kept_when_final_output_predates_it(tree: Path) -> None:
    """A final output older than the CSV cannot contain that CSV's rows."""
    v = _verdict_for(_plan(tree), "fresh.csv")
    assert v.remove is False
    assert v.reason == cl.KEEP_FINAL_OUTPUT_OLDER


def test_json_kept_when_its_job_never_concatenated_but_csv_exists(tree: Path) -> None:
    """JSON cleanup keys off transformation, not concatenation, so x.json goes."""
    assert _verdict_for(_plan(tree), "x.json").remove is True


# ---------------------------------------------------------------------------
# State DBs and logs join to job status
# ---------------------------------------------------------------------------


def test_state_db_of_completed_job_is_removed(tree: Path) -> None:
    assert _verdict_for(_plan(tree), "aaa.db").remove is True


def test_state_db_of_failed_job_is_kept_by_default(tree: Path) -> None:
    v = _verdict_for(_plan(tree), "bbb.db")
    assert v.remove is False
    assert v.reason == cl.KEEP_JOB_NOT_COMPLETED


def test_state_db_with_no_history_record_is_kept(tree: Path) -> None:
    v = _verdict_for(_plan(tree), "ccc.db")
    assert v.remove is False
    assert v.reason == cl.KEEP_JOB_UNKNOWN


def test_failed_jobs_can_be_opted_in(tree: Path) -> None:
    plan = _plan(tree, categories={"state_db": {"require_job_status": ["completed", "failed"]}})
    assert _verdict_for(plan, "bbb.db").remove is True


def test_keep_unknown_false_allows_orphan_dbs(tree: Path) -> None:
    plan = _plan(tree, categories={"state_db": {"keep_unknown": False}})
    assert _verdict_for(plan, "ccc.db").remove is True


def test_log_of_completed_job_is_removed(tree: Path) -> None:
    assert _verdict_for(_plan(tree), "done_job.log").remove is True


def test_log_of_failed_job_is_kept(tree: Path) -> None:
    assert _verdict_for(_plan(tree), "failed_job.log").remove is False


def test_rotated_log_ages_out_before_the_live_log(tree: Path) -> None:
    """The 10-day-old rotation goes; a 10-day-old live log would not."""
    assert _verdict_for(_plan(tree), "done_job.log.1").remove is True
    plan = _plan(tree, categories={"logs": {"rotated_older_than_days": 30}})
    v = _verdict_for(plan, "done_job.log.1")
    assert v.remove is False
    assert v.reason == cl.KEEP_TOO_RECENT


# ---------------------------------------------------------------------------
# Universal gates
# ---------------------------------------------------------------------------


def test_absolute_min_age_overrides_a_looser_category_threshold(tree: Path) -> None:
    plan = _plan(
        tree,
        defaults={"absolute_min_age_days": 365},
        categories={"json": {"older_than_days": 0}},
    )
    v = _verdict_for(plan, "a.json")
    assert v.remove is False
    assert v.reason == cl.KEEP_BELOW_ABSOLUTE_MIN_AGE


def test_disabled_category_keeps_everything_with_a_clear_reason(tree: Path) -> None:
    plan = _plan(tree, categories={"json": {"enabled": False}})
    v = _verdict_for(plan, "a.json")
    assert v.remove is False
    assert v.reason == cl.KEEP_CATEGORY_DISABLED


def test_zip_archives_kept_by_default_and_removable_when_enabled(tree: Path) -> None:
    assert _verdict_for(_plan(tree), "archive.zip").reason == cl.KEEP_CATEGORY_DISABLED
    plan = _plan(tree, categories={"zip_archives": {"enabled": True}})
    assert _verdict_for(plan, "archive.zip").remove is True


def test_job_allow_list_and_exclude_list(tree: Path) -> None:
    only = _plan(tree, target={"jobs": ["MyJob"]})
    assert not [v for v in only.verdicts if v.file.job_name == "Unfinished"]

    without = _plan(tree, target={"exclude_jobs": ["MyJob"]})
    assert not [v for v in without.verdicts if v.file.job_name == "MyJob"]


def test_unknown_client_yields_nothing(tree: Path) -> None:
    plan = _plan(tree, target={"clients": ["NotAClient"]})
    assert plan.verdicts == []


def test_missing_base_folder_is_not_an_error(tmp_path: Path) -> None:
    plan = _plan(tmp_path / "nope")
    assert plan.verdicts == []


# ---------------------------------------------------------------------------
# The scan itself must be inert
# ---------------------------------------------------------------------------


def test_scan_modifies_nothing(tree: Path) -> None:
    def snapshot() -> dict[str, tuple[int, float]]:
        return {
            str(p): (p.stat().st_size, p.stat().st_mtime) for p in tree.rglob("*") if p.is_file()
        }

    before = snapshot()
    _plan(tree)
    assert snapshot() == before


def test_plan_totals_are_internally_consistent(tree: Path) -> None:
    plan = _plan(tree)
    assert len(plan.to_remove) + len(plan.to_keep) == len(plan.verdicts)
    assert plan.bytes_to_remove == sum(v.file.size for v in plan.to_remove)
    removed = plan.by_category(remove=True)
    assert sum(count for count, _ in removed.values()) == len(plan.to_remove)
    assert sum(count for count, _ in plan.by_keep_reason().values()) == len(plan.to_keep)


def test_largest_kept_is_ordered_and_bounded(tree: Path) -> None:
    plan = _plan(tree)
    largest = plan.largest_kept(3)
    assert len(largest) <= 3
    assert [v.file.size for v in largest] == sorted((v.file.size for v in largest), reverse=True)


# ---------------------------------------------------------------------------
# Cross-platform history parsing
# ---------------------------------------------------------------------------


def test_config_stem_handles_windows_separators() -> None:
    """job_history.jsonl records whatever separator the writing machine used."""
    windows_path = "jobs" + chr(92) + "legend_bot_compare.yaml"
    assert cl._config_stem(windows_path) == "legend_bot_compare"
    assert cl._config_stem("jobs/legend_bot_compare.yaml") == "legend_bot_compare"


def test_later_history_record_supersedes_earlier(tmp_path: Path) -> None:
    """A job that failed and was then re-run successfully reads as completed."""
    base = tmp_path / "Adobe_Downloads"
    client = base / "Legend"
    _write_history(
        client,
        [
            {"job_id": "aaa", "config_path": "jobs/j.yaml", "status": "failed"},
            {"job_id": "aaa", "config_path": "jobs/j.yaml", "status": "completed"},
        ],
    )
    index = cl.load_job_history_index(base, "Legend")
    assert index.status_for_job_id("aaa") == "completed"
    assert index.status_for_stem("j") == "completed"


def test_real_clock_is_used_when_now_is_omitted(tree: Path) -> None:
    """Guard the default argument: a broken clock would age every file to zero."""
    cfg = _cfg(target={"base_folder": str(tree)})
    plan = cl.scan(cfg)
    assert time.time() > _NOW  # sanity: the fixture clock really is in the past
    assert plan.verdicts  # a real-clock scan still classifies the tree


def test_loose_json_in_a_job_root_is_kept_as_unclassified(tree: Path) -> None:
    """country_matrix/matrix_*.json is a pipeline *input*, not a downloaded response.

    It sits in a job folder root rather than a JSON/ subfolder, so the JSON category
    never sees it and the catch-all keeps it. Verified against the real Legend tree,
    where these were the only two unclassified files.
    """
    matrix = tree / "Legend" / "country_matrix" / "matrix_matrix.json"
    _touch(matrix, days_old=999)

    v = _verdict_for(_plan(tree), "matrix_matrix.json")
    assert v.remove is False
    assert v.reason == cl.KEEP_UNCLASSIFIED
    assert v.file.category == cl.CATEGORY_UNCLASSIFIED
