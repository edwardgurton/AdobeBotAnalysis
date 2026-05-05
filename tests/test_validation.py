"""Tests for Step 17: validation flow — flows/validation.py and validate-output CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adobe_downloader.config.schema import DateRange, RsidSource, SegmentSource
from adobe_downloader.flows.validation import (
    check_output_files,
    enumerate_expected_paths,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_report_def(name: str) -> MagicMock:
    rd = MagicMock()
    rd.name = name
    return rd


def _rsids_single(rsid: str) -> RsidSource:
    return RsidSource(source="single", single=rsid)


def _rsids_list(rsids: list[str]) -> RsidSource:
    return RsidSource(source="list", list=rsids)


def _date_range(from_date: str, to: str) -> DateRange:
    return DateRange.model_validate({"from": from_date, "to": to})


# ---------------------------------------------------------------------------
# enumerate_expected_paths
# ---------------------------------------------------------------------------


def test_enumerate_single_rsid_single_report(tmp_path: Path) -> None:
    paths = enumerate_expected_paths(
        client_name="TestClient",
        report_defs=[_make_report_def("myReport")],
        rsids=_rsids_single("rsidA"),
        date_range=_date_range("2025-01-01", "2025-02-01"),
        interval="full",
        output_base=tmp_path,
    )
    assert len(paths) == 1
    assert paths[0].suffix == ".json"
    assert "myReport" in paths[0].name
    assert "rsidA" not in paths[0].name  # rsid not in filename, but date is


def test_enumerate_multiple_rsids(tmp_path: Path) -> None:
    paths = enumerate_expected_paths(
        client_name="C",
        report_defs=[_make_report_def("r1")],
        rsids=_rsids_list(["a", "b", "c"]),
        date_range=_date_range("2025-01-01", "2025-04-01"),
        interval="month",
        output_base=tmp_path,
    )
    # 3 rsids × 3 months × 1 report = 9
    assert len(paths) == 9


def test_enumerate_multiple_reports(tmp_path: Path) -> None:
    paths = enumerate_expected_paths(
        client_name="C",
        report_defs=[_make_report_def("r1"), _make_report_def("r2")],
        rsids=_rsids_single("rsid1"),
        date_range=_date_range("2025-01-01", "2025-02-01"),
        interval="full",
        output_base=tmp_path,
    )
    assert len(paths) == 2
    names = {p.name for p in paths}
    assert any("r1" in n for n in names)
    assert any("r2" in n for n in names)


def test_enumerate_with_segment_list(tmp_path: Path) -> None:
    import json

    seg_file = tmp_path / "segs.json"
    seg_file.write_text(json.dumps([{"id": "seg1"}, {"id": "seg2"}]))

    paths = enumerate_expected_paths(
        client_name="C",
        report_defs=[_make_report_def("rep")],
        rsids=_rsids_single("rsid1"),
        date_range=_date_range("2025-01-01", "2025-02-01"),
        interval="full",
        output_base=tmp_path,
        segments=SegmentSource(source="segment_list_file", file=str(seg_file)),
    )
    # 1 rsid × 1 date × 2 segments × 1 report = 2
    assert len(paths) == 2


def test_enumerate_paths_live_under_client_json_folder(tmp_path: Path) -> None:
    paths = enumerate_expected_paths(
        client_name="MyClient",
        report_defs=[_make_report_def("report")],
        rsids=_rsids_single("rsid"),
        date_range=_date_range("2025-01-01", "2025-02-01"),
        interval="full",
        output_base=tmp_path,
    )
    assert paths[0].parent == tmp_path / "MyClient" / "JSON"


def test_enumerate_count_rsids_x_dates(tmp_path: Path) -> None:
    # RSID is NOT in the output filename, so 2 rsids × 2 months = 4 entries
    # (each pair shares the same path; the downloader overwrites sequentially).
    paths = enumerate_expected_paths(
        client_name="C",
        report_defs=[_make_report_def("rep")],
        rsids=_rsids_list(["a", "b"]),
        date_range=_date_range("2025-01-01", "2025-03-01"),
        interval="month",
        output_base=tmp_path,
    )
    assert len(paths) == 4  # 2 rsids × 2 months × 1 report
    assert len(set(paths)) == 2  # only 2 unique file paths (rsid not in name)


# ---------------------------------------------------------------------------
# check_output_files
# ---------------------------------------------------------------------------


def test_check_all_present(tmp_path: Path) -> None:
    files = [tmp_path / f"f{i}.json" for i in range(3)]
    for f in files:
        f.write_text('{"rows": []}')
    valid, missing = check_output_files(files)
    assert valid == files
    assert missing == []


def test_check_all_missing(tmp_path: Path) -> None:
    files = [tmp_path / f"missing{i}.json" for i in range(3)]
    valid, missing = check_output_files(files)
    assert valid == []
    assert missing == files


def test_check_empty_file_counts_as_missing(tmp_path: Path) -> None:
    present = tmp_path / "present.json"
    empty = tmp_path / "empty.json"
    present.write_text('{"rows": []}')
    empty.write_text("")
    valid, missing = check_output_files([present, empty])
    assert present in valid
    assert empty in missing


def test_check_mixed(tmp_path: Path) -> None:
    ok = tmp_path / "ok.json"
    ok.write_text('{"rows": [1]}')
    bad = tmp_path / "bad.json"  # doesn't exist
    valid, missing = check_output_files([ok, bad])
    assert ok in valid
    assert bad in missing


# ---------------------------------------------------------------------------
# StateManager.reset_incomplete_for_step
# ---------------------------------------------------------------------------


def test_reset_incomplete_for_step(tmp_path: Path) -> None:
    from adobe_downloader.state_manager import StateManager, compute_config_hash, compute_job_id

    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("job_type: report_download\nclient: X\n")
    h = compute_config_hash(cfg)
    jid = compute_job_id(cfg, h)
    sm = StateManager(tmp_path / "state.db", jid, cfg, h)

    # Track requests for two steps
    sm.track_request("step_a|key1", {}, tmp_path / "a1.json")
    sm.track_request("step_a|key2", {}, tmp_path / "a2.json")
    sm.track_request("step_b|key1", {}, tmp_path / "b1.json")

    # Fail step_a requests
    with sm._connect() as conn:
        conn.execute(
            "UPDATE requests SET status='failed' WHERE request_key LIKE 'step_a|%'"
        )
        conn.execute(
            "UPDATE requests SET status='in_progress' WHERE request_key = 'step_b|key1'"
        )

    count = sm.reset_incomplete_for_step("step_a")
    assert count == 2

    # step_b should be untouched
    with sm._connect() as conn:
        row = conn.execute(
            "SELECT status FROM requests WHERE request_key = 'step_b|key1'"
        ).fetchone()
    assert row["status"] == "in_progress"


# ---------------------------------------------------------------------------
# StateManager.reset_completed_for_path
# ---------------------------------------------------------------------------


def test_reset_completed_for_path(tmp_path: Path) -> None:
    from adobe_downloader.state_manager import StateManager, compute_config_hash, compute_job_id

    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("job_type: report_download\nclient: X\n")
    h = compute_config_hash(cfg)
    jid = compute_job_id(cfg, h)
    sm = StateManager(tmp_path / "state.db", jid, cfg, h)

    out_path = tmp_path / "output.json"
    req_id, _ = sm.track_request("key1", {}, out_path)
    sm.mark_started(req_id)
    sm.mark_complete(req_id, out_path)

    # Should reset it
    assert sm.reset_completed_for_path(out_path) is True

    with sm._connect() as conn:
        row = conn.execute(
            "SELECT status FROM requests WHERE request_id = ?", (req_id,)
        ).fetchone()
    assert row["status"] == "pending"


def test_reset_completed_for_path_no_match(tmp_path: Path) -> None:
    from adobe_downloader.state_manager import StateManager, compute_config_hash, compute_job_id

    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("job_type: report_download\nclient: X\n")
    h = compute_config_hash(cfg)
    jid = compute_job_id(cfg, h)
    sm = StateManager(tmp_path / "state.db", jid, cfg, h)
    assert sm.reset_completed_for_path(tmp_path / "nonexistent.json") is False


# ---------------------------------------------------------------------------
# run_validate_output — unit tests with mocked API
# ---------------------------------------------------------------------------


def _make_job_mock(tmp_path: Path, report_name: str = "testReport") -> MagicMock:
    job = MagicMock()
    job.report_group = "grp"
    job.report_ref = None
    job.report = None
    job.client = "Client"
    job.rsids = _rsids_single("rsid1")
    job.date_range = _date_range("2025-01-01", "2025-02-01")
    job.interval = "full"
    job.output = MagicMock()
    job.output.base_folder = str(tmp_path)
    job.segments = None
    job.file_name_extra = None
    return job


@pytest.mark.asyncio
async def test_run_validate_output_all_present(tmp_path: Path) -> None:
    """All files present → missing_count 0, no re-download."""
    rd = _make_report_def("testReport")
    job = _make_job_mock(tmp_path, "testReport")

    # Seed the expected file on disk.
    from adobe_downloader.flows.report_download import make_output_path
    p = make_output_path(
        base_folder=tmp_path,
        client="Client",
        report_name="testReport",
        date_range=_date_range("2025-01-01", "2025-02-01"),
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"rows": []}')

    with (
        patch("adobe_downloader.config.report_definitions.load_report_registry"),
        patch("adobe_downloader.config.report_definitions.load_report_group", return_value=[rd]),
    ):
        from adobe_downloader.flows.validation import run_validate_output
        result = await run_validate_output(job, retry=False, dry_run=False)

    assert result["missing_count"] == 0
    assert result["total"] == 1
    assert result["valid"] == 1


@pytest.mark.asyncio
async def test_run_validate_output_missing_file_no_retry(tmp_path: Path) -> None:
    """Missing file, no retry → reports missing but does not download."""
    rd = _make_report_def("rep")
    job = _make_job_mock(tmp_path)

    with (
        patch("adobe_downloader.config.report_definitions.load_report_registry"),
        patch("adobe_downloader.config.report_definitions.load_report_group", return_value=[rd]),
        patch("adobe_downloader.flows.report_download.run_report_download") as mock_dl,
    ):
        from adobe_downloader.flows.validation import run_validate_output
        result = await run_validate_output(job, retry=False, dry_run=False)

    assert result["missing_count"] == 1
    mock_dl.assert_not_called()


@pytest.mark.asyncio
async def test_run_validate_output_retry_calls_download(tmp_path: Path) -> None:
    """Missing file + retry=True → resets DB and calls run_report_download."""
    from adobe_downloader.state_manager import StateManager, compute_config_hash, compute_job_id

    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("job_type: report_download\nclient: X\n")
    h = compute_config_hash(cfg)
    jid = compute_job_id(cfg, h)
    sm = StateManager(tmp_path / "state.db", jid, cfg, h)

    rd = _make_report_def("rep")
    job = _make_job_mock(tmp_path)
    ac = MagicMock()

    with (
        patch("adobe_downloader.config.report_definitions.load_report_registry"),
        patch("adobe_downloader.config.report_definitions.load_report_group", return_value=[rd]),
        patch("adobe_downloader.flows.report_download.run_report_download", new_callable=AsyncMock) as mock_dl,
    ):
        from adobe_downloader.flows.validation import run_validate_output
        await run_validate_output(job, retry=True, dry_run=False, ac=ac, sm=sm)

    mock_dl.assert_called_once()


@pytest.mark.asyncio
async def test_run_validate_output_dry_run_no_download(tmp_path: Path) -> None:
    """dry_run=True, retry=True → does NOT call download even with missing files."""
    rd = _make_report_def("rep")
    job = _make_job_mock(tmp_path)

    with (
        patch("adobe_downloader.config.report_definitions.load_report_registry"),
        patch("adobe_downloader.config.report_definitions.load_report_group", return_value=[rd]),
        patch("adobe_downloader.flows.report_download.run_report_download", new_callable=AsyncMock) as mock_dl,
    ):
        from adobe_downloader.flows.validation import run_validate_output
        result = await run_validate_output(job, retry=True, dry_run=True)

    assert result["missing_count"] == 1
    mock_dl.assert_not_called()


# ---------------------------------------------------------------------------
# _run_validate_output_step (composite)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_validate_output_step_all_present(tmp_path: Path) -> None:
    """validate_output composite step returns missing_count=0 when all files exist."""
    from adobe_downloader.config.schema import CompositeJobConfig
    from adobe_downloader.flows.composite_job import _run_validate_output_step

    # Build a minimal expected file on disk
    json_dir = tmp_path / "C" / "JSON"
    json_dir.mkdir(parents=True)
    out_file = json_dir / "C_rep_2025-01-01_2025-02-01.json"
    out_file.write_text('{"rows": [1]}')

    with patch("adobe_downloader.flows.composite_job._resolve_report_defs") as mock_rds:
        rd = _make_report_def("rep")
        mock_rds.return_value = [rd]

        step = MagicMock()
        step.id = "validate"
        step.extra_fields.return_value = {
            "config_ref": "download",
            "retry": False,
        }

        ref_step = MagicMock()
        ref_step.id = "download"
        ref_step.extra_fields.return_value = {
            "rsids": {"source": "single", "single": "rsid1"},
            "interval": "full",
        }

        job = MagicMock(spec=CompositeJobConfig)
        job.client = "C"
        job.steps = [ref_step, step]
        job.date_range = _date_range("2025-01-01", "2025-02-01")
        job.output = MagicMock()
        job.output.base_folder = str(tmp_path)
        job.test_mode = False

        sm = MagicMock()
        ac = MagicMock()

        with patch("adobe_downloader.flows.composite_job._coerce_date_range") as mock_cdr, \
             patch("adobe_downloader.flows.composite_job._resolve_output_base") as mock_ob, \
             patch("adobe_downloader.flows.composite_job._resolve_segments", return_value=None), \
             patch("adobe_downloader.flows.validation.enumerate_expected_paths") as mock_enum, \
             patch("adobe_downloader.flows.validation.check_output_files") as mock_check:

            mock_cdr.return_value = _date_range("2025-01-01", "2025-02-01")
            mock_ob.return_value = str(tmp_path)
            mock_enum.return_value = [out_file]
            mock_check.return_value = ([out_file], [])

            result = await _run_validate_output_step(
                step, job, {}, sm, ac, no_resume=False
            )

    assert result["missing_count"] == 0


@pytest.mark.asyncio
async def test_composite_validate_output_step_missing_no_retry(tmp_path: Path) -> None:
    """validate_output step with missing files and retry=False → returns missing_count > 0."""
    from adobe_downloader.config.schema import CompositeJobConfig
    from adobe_downloader.flows.composite_job import _run_validate_output_step

    missing_file = tmp_path / "C" / "JSON" / "C_rep_2025-01-01_2025-02-01.json"

    with patch("adobe_downloader.flows.composite_job._resolve_report_defs") as mock_rds, \
         patch("adobe_downloader.flows.composite_job._coerce_date_range") as mock_cdr, \
         patch("adobe_downloader.flows.composite_job._resolve_output_base") as mock_ob, \
         patch("adobe_downloader.flows.composite_job._resolve_segments", return_value=None), \
         patch("adobe_downloader.flows.validation.enumerate_expected_paths") as mock_enum, \
         patch("adobe_downloader.flows.validation.check_output_files") as mock_check:

        rd = _make_report_def("rep")
        mock_rds.return_value = [rd]
        mock_cdr.return_value = _date_range("2025-01-01", "2025-02-01")
        mock_ob.return_value = str(tmp_path)
        mock_enum.return_value = [missing_file]
        mock_check.return_value = ([], [missing_file])

        step = MagicMock()
        step.id = "validate"
        step.extra_fields.return_value = {"config_ref": "download", "retry": False}

        ref_step = MagicMock()
        ref_step.id = "download"
        ref_step.extra_fields.return_value = {
            "rsids": {"source": "single", "single": "rsid1"},
            "interval": "full",
        }

        job = MagicMock(spec=CompositeJobConfig)
        job.client = "C"
        job.steps = [ref_step, step]
        job.date_range = _date_range("2025-01-01", "2025-02-01")
        job.output = MagicMock()
        job.output.base_folder = str(tmp_path)
        job.test_mode = False

        result = await _run_validate_output_step(
            step, job, {}, MagicMock(), MagicMock(), no_resume=False
        )

    assert result["missing_count"] == 1


@pytest.mark.asyncio
async def test_composite_validate_output_missing_config_ref_raises(tmp_path: Path) -> None:
    """validate_output step without config_ref raises ValueError."""
    from adobe_downloader.config.schema import CompositeJobConfig
    from adobe_downloader.flows.composite_job import _run_validate_output_step

    step = MagicMock()
    step.id = "validate"
    step.extra_fields.return_value = {}

    job = MagicMock(spec=CompositeJobConfig)
    job.steps = []

    with pytest.raises(ValueError, match="config_ref"):
        await _run_validate_output_step(step, job, {}, MagicMock(), MagicMock(), False)
