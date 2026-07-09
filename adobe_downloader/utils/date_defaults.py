"""Fallback date ranges applied when a job or step omits date_range explicitly."""

from datetime import date, timedelta

from adobe_downloader.config.schema import DateRange

_ROLLING_MONTHS_REPORT_GROUPS = {"bot_validation"}
_ROLLING_MONTHS_STEP_TYPES = {"bot_rule_compare"}
_ROLLING_DAYS_REPORT_GROUPS = {"bot_investigation"}

_ROLLING_MONTHS = 25  # past 24 full months plus the current month
_ROLLING_DAYS = 120


def default_date_range(
    report_group: str | None = None,
    step_type: str | None = None,
    *,
    today: date | None = None,
) -> DateRange | None:
    """Return a rolling fallback DateRange, or None if no fallback applies.

    bot_validation report_group and bot_rule_compare steps default to the past
    24 months plus the current month. bot_investigation defaults to the past
    120 days. Every other report_group/step_type returns None, leaving
    date_range required as before.
    """
    today = today or date.today()
    if report_group in _ROLLING_MONTHS_REPORT_GROUPS or step_type in _ROLLING_MONTHS_STEP_TYPES:
        return _rolling_months(today, _ROLLING_MONTHS)
    if report_group in _ROLLING_DAYS_REPORT_GROUPS:
        return _rolling_days(today, _ROLLING_DAYS)
    return None


def _rolling_months(today: date, months: int) -> DateRange:
    zero_based = today.year * 12 + (today.month - 1) - (months - 1)
    start_year, start_month = divmod(zero_based, 12)
    start = date(start_year, start_month + 1, 1)
    return DateRange.model_validate({"from": start.isoformat(), "to": today.isoformat()})


def _rolling_days(today: date, days: int) -> DateRange:
    start = today - timedelta(days=days)
    return DateRange.model_validate({"from": start.isoformat(), "to": today.isoformat()})
