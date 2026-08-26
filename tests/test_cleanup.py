"""Tests for the cleanup job — config schema, scanning, classification, reporting."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from adobe_downloader.config.loader import load_config
from adobe_downloader.config.schema import CleanupJobConfig

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
