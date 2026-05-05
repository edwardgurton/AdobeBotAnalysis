"""Apply TestLimits to cap download iterations when running in --test mode."""

from __future__ import annotations

from typing import Any, TypeVar

from adobe_downloader.config.schema import TestLimits

T = TypeVar("T")


def apply_rsid_limit(rsids: list[str], limits: TestLimits) -> list[str]:
    return rsids[: limits.max_rsids]


def apply_date_limit(intervals: list[T], limits: TestLimits) -> list[T]:
    return intervals[: limits.max_date_intervals]


def apply_segment_limit(segments: list[T], limits: TestLimits) -> list[T]:
    return segments[: limits.max_segments]


def apply_all_limits(
    rsids: list[str],
    date_intervals: list[Any],
    segments: list[Any],
    limits: TestLimits,
) -> tuple[list[str], list[Any], list[Any]]:
    """Cap all three iteration dimensions at once."""
    return (
        apply_rsid_limit(rsids, limits),
        apply_date_limit(date_intervals, limits),
        apply_segment_limit(segments, limits),
    )
