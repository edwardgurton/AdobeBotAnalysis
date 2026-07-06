"""Tests for the Windows extended-length path (\\\\?\\) helper."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from adobe_downloader.utils.winpath import to_long_path


def test_noop_on_non_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    p = tmp_path / "file.txt"
    assert to_long_path(p) == p


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only path semantics")
def test_prefixes_absolute_windows_path(tmp_path: Path) -> None:
    p = tmp_path / "file.txt"
    long_p = to_long_path(p)
    assert str(long_p).startswith("\\\\?\\")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only path semantics")
def test_noop_if_already_prefixed(tmp_path: Path) -> None:
    p = tmp_path / "file.txt"
    once = to_long_path(p)
    twice = to_long_path(once)
    assert str(twice) == str(once)


def _realistic_long_path(tmp_path: Path) -> Path:
    """Build a path shaped like a real bot_rule_compare output: several short
    directory components plus one long-but-<255-char filename, totaling >260
    chars overall. A single component >255 chars hits NTFS's separate
    per-component limit, which \\\\?\\ does NOT lift — that's a different
    constraint from the 260-char total-path limit this helper targets.
    """
    filename = (
        "Legend_botInvestigationMetricsByMobileManufacturer_Apuestasdeportivascom-"
        "BOTCOMPARE-AdHocSEOHomepageNL-04CORGOperatingSystem=Android10ANDCountries="
        "Netherlands-Compare-V1.0-Segment_DIMSEGs3938_6a479deb2a2fae163b24d59c_"
        "2024-07-01_2026-07-01.json"
    )
    assert len(filename) < 255
    return tmp_path / "Legend" / "BotRuleCompareAdHocSeoHomepageNLV1" / "JSON" / filename


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only path semantics")
def test_writes_and_reads_path_over_260_chars(tmp_path: Path) -> None:
    """The actual regression this helper exists for: mkdir/write/read on a path
    Windows would otherwise reject with [Errno 2] No such file or directory."""
    target = _realistic_long_path(tmp_path)
    assert len(str(target)) > 260

    long_target = to_long_path(target)
    long_target.parent.mkdir(parents=True, exist_ok=True)
    long_target.write_text("hello", encoding="utf-8")

    assert to_long_path(target).exists()
    assert to_long_path(target).read_text(encoding="utf-8") == "hello"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only path semantics")
def test_plain_path_fails_over_260_chars_without_wrapper(tmp_path: Path) -> None:
    """Sanity check that the >260-char path really would fail unwrapped on this
    machine — otherwise test_writes_and_reads_path_over_260_chars proves nothing."""
    target = _realistic_long_path(tmp_path)
    assert len(str(target)) > 260
    target.parent.mkdir(parents=True, exist_ok=True)

    with pytest.raises(OSError):
        target.write_text("hello", encoding="utf-8")
