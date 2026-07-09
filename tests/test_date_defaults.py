"""Tests for utils/date_defaults.py."""

from datetime import date

from adobe_downloader.utils.date_defaults import default_date_range


def test_bot_validation_report_group_defaults_to_25_rolling_months():
    result = default_date_range(report_group="bot_validation", today=date(2026, 7, 9))
    assert result is not None
    assert result.from_date == "2024-07-01"
    assert result.to == "2026-07-09"


def test_bot_rule_compare_step_type_defaults_to_25_rolling_months():
    result = default_date_range(step_type="bot_rule_compare", today=date(2026, 7, 9))
    assert result is not None
    assert result.from_date == "2024-07-01"
    assert result.to == "2026-07-09"


def test_rolling_months_crosses_year_boundary():
    result = default_date_range(report_group="bot_validation", today=date(2026, 1, 15))
    assert result is not None
    assert result.from_date == "2024-01-01"
    assert result.to == "2026-01-15"


def test_bot_investigation_report_group_defaults_to_120_rolling_days():
    result = default_date_range(report_group="bot_investigation", today=date(2026, 7, 9))
    assert result is not None
    assert result.from_date == "2026-03-11"
    assert result.to == "2026-07-09"


def test_unlisted_report_group_has_no_fallback():
    assert default_date_range(report_group="clickouts", today=date(2026, 7, 9)) is None


def test_no_report_group_or_step_type_has_no_fallback():
    assert default_date_range(today=date(2026, 7, 9)) is None


def test_unlisted_step_type_has_no_fallback():
    assert default_date_range(step_type="rsid_update", today=date(2026, 7, 9)) is None
