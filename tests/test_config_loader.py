"""Tests for adobe_downloader/config/loader.py."""

from __future__ import annotations

from adobe_downloader.config.loader import check_job_name_length
from adobe_downloader.config.schema import CompositeJobConfig, ReportDownloadConfig

_LONG_NAME = "BotRuleCompareAdHocSeoHomepageNLV1"  # 34 chars
_SHORT_NAME = "AdHocSeoNL-V1"  # 13 chars


def _composite(steps: list[dict], job_name: str | None) -> CompositeJobConfig:
    return CompositeJobConfig.model_validate(
        {
            "job_type": "composite",
            "client": "Legend",
            "steps": steps,
            "output": {"base_folder": "C:/Adobe_Downloads", "job_name": job_name}
            if job_name is not None
            else None,
        }
    )


def test_bot_rule_compare_step_with_long_job_name_warns() -> None:
    job = _composite([{"step": "bot_rule_compare", "id": "compare"}], _LONG_NAME)
    warnings = check_job_name_length(job)
    assert len(warnings) == 1
    assert _LONG_NAME in warnings[0]
    assert "34 chars" in warnings[0]


def test_bot_rule_compare_step_with_short_job_name_ok() -> None:
    job = _composite([{"step": "bot_rule_compare", "id": "compare"}], _SHORT_NAME)
    assert check_job_name_length(job) == []


def test_bot_validation_report_download_step_with_long_job_name_warns() -> None:
    job = _composite(
        [
            {
                "step": "report_download",
                "id": "download_validation",
                "report_group": "bot_validation",
            }
        ],
        _LONG_NAME,
    )
    warnings = check_job_name_length(job)
    assert len(warnings) == 1


def test_unrelated_report_group_does_not_warn() -> None:
    job = _composite(
        [
            {
                "step": "report_download",
                "id": "download_investigation",
                "report_group": "bot_investigation",
            }
        ],
        _LONG_NAME,
    )
    assert check_job_name_length(job) == []


def test_no_output_block_does_not_crash() -> None:
    job = _composite([{"step": "bot_rule_compare", "id": "compare"}], None)
    assert check_job_name_length(job) == []


def test_standalone_bot_validation_report_download_warns() -> None:
    job = ReportDownloadConfig.model_validate(
        {
            "job_type": "report_download",
            "client": "Legend",
            "report_group": "bot_validation",
            "rsids": {"source": "single", "single": "rsid1"},
            "output": {"base_folder": "C:/Adobe_Downloads", "job_name": _LONG_NAME},
        }
    )
    warnings = check_job_name_length(job)
    assert len(warnings) == 1


def test_standalone_unrelated_report_group_does_not_warn() -> None:
    job = ReportDownloadConfig.model_validate(
        {
            "job_type": "report_download",
            "client": "Legend",
            "report_group": "bot_investigation",
            "rsids": {"source": "single", "single": "rsid1"},
            "output": {"base_folder": "C:/Adobe_Downloads", "job_name": _LONG_NAME},
        }
    )
    assert check_job_name_length(job) == []
