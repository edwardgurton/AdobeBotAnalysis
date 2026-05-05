"""Tests for adobe_downloader/utils/post_process.py."""

import json
import time
import zipfile
from pathlib import Path

import pytest

from adobe_downloader.utils.post_process import (
    _CLEANUP_TYPES,
    archive_config,
    build_history_record,
    cleanup_old_files,
    log_job_history,
    move_json_to_processed,
    read_job_history,
    zip_csv_folder,
)


# ---------------------------------------------------------------------------
# move_json_to_processed
# ---------------------------------------------------------------------------


def test_move_json_to_processed_creates_dest_dir(tmp_path: Path) -> None:
    json_file = tmp_path / "report.json"
    json_file.write_text('{"rows": []}')
    dest = move_json_to_processed(json_file)
    assert dest == tmp_path / "_processed" / "report.json"
    assert dest.exists()
    assert not json_file.exists()


def test_move_json_to_processed_dir_already_exists(tmp_path: Path) -> None:
    processed = tmp_path / "_processed"
    processed.mkdir()
    json_file = tmp_path / "a.json"
    json_file.write_text("{}")
    dest = move_json_to_processed(json_file)
    assert dest.exists()


def test_move_json_to_processed_content_preserved(tmp_path: Path) -> None:
    payload = '{"rows": [1, 2, 3]}'
    json_file = tmp_path / "data.json"
    json_file.write_text(payload)
    dest = move_json_to_processed(json_file)
    assert dest.read_text() == payload


# ---------------------------------------------------------------------------
# zip_csv_folder
# ---------------------------------------------------------------------------


def test_zip_csv_folder_zips_all_csvs(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / "a.csv").write_text("col\n1\n")
    (csv_dir / "b.csv").write_text("col\n2\n")
    zip_dest = tmp_path / "archive.zip"
    count = zip_csv_folder(csv_dir, zip_dest)
    assert count == 2
    assert zip_dest.exists()
    with zipfile.ZipFile(zip_dest) as zf:
        names = set(zf.namelist())
    assert names == {"a.csv", "b.csv"}


def test_zip_csv_folder_returns_zero_when_empty(tmp_path: Path) -> None:
    csv_dir = tmp_path / "empty"
    csv_dir.mkdir()
    zip_dest = tmp_path / "out.zip"
    count = zip_csv_folder(csv_dir, zip_dest)
    assert count == 0
    assert not zip_dest.exists()


def test_zip_csv_folder_creates_parent_dirs(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / "x.csv").write_text("h\n1\n")
    zip_dest = tmp_path / "nested" / "deep" / "out.zip"
    count = zip_csv_folder(csv_dir, zip_dest)
    assert count == 1
    assert zip_dest.exists()


# ---------------------------------------------------------------------------
# log_job_history + read_job_history
# ---------------------------------------------------------------------------


def _sample_record(job_id: str = "abc123", status: str = "completed") -> dict:  # type: ignore[type-arg]
    return {
        "job_id": job_id,
        "config_path": "jobs/test.yaml",
        "started_at": "2025-07-01T10:00:00+00:00",
        "completed_at": "2025-07-01T11:00:00+00:00",
        "duration_minutes": 60.0,
        "status": status,
        "total_requests": 10,
        "completed_requests": 10,
        "failed_requests": 0,
        "output_folder": "/out/",
        "archived_config": ".history/configs/2025-07-01_test.yaml",
    }


def test_log_and_read_single_record(tmp_path: Path) -> None:
    rec = _sample_record()
    log_job_history(tmp_path, "TestClient", rec)
    records = read_job_history(tmp_path, "TestClient")
    assert len(records) == 1
    assert records[0]["job_id"] == "abc123"


def test_log_appends_multiple_records(tmp_path: Path) -> None:
    log_job_history(tmp_path, "C", _sample_record("j1"))
    log_job_history(tmp_path, "C", _sample_record("j2"))
    log_job_history(tmp_path, "C", _sample_record("j3"))
    records = read_job_history(tmp_path, "C")
    assert len(records) == 3
    assert [r["job_id"] for r in records] == ["j1", "j2", "j3"]


def test_read_job_history_empty_when_no_file(tmp_path: Path) -> None:
    assert read_job_history(tmp_path, "NoClient") == []


def test_read_job_history_filter_status(tmp_path: Path) -> None:
    log_job_history(tmp_path, "C", _sample_record("ok1", "completed"))
    log_job_history(tmp_path, "C", _sample_record("fail1", "failed"))
    log_job_history(tmp_path, "C", _sample_record("ok2", "completed"))
    completed = read_job_history(tmp_path, "C", status="completed")
    assert len(completed) == 2
    failed = read_job_history(tmp_path, "C", status="failed")
    assert len(failed) == 1


def test_read_job_history_filter_since(tmp_path: Path) -> None:
    r1 = _sample_record("old")
    r1["started_at"] = "2025-05-01T00:00:00+00:00"
    r2 = _sample_record("new")
    r2["started_at"] = "2025-07-01T00:00:00+00:00"
    log_job_history(tmp_path, "C", r1)
    log_job_history(tmp_path, "C", r2)
    result = read_job_history(tmp_path, "C", since="2025-06-01")
    assert len(result) == 1
    assert result[0]["job_id"] == "new"


def test_read_job_history_last_limits(tmp_path: Path) -> None:
    for i in range(5):
        log_job_history(tmp_path, "C", _sample_record(f"j{i}"))
    result = read_job_history(tmp_path, "C", last=3)
    assert len(result) == 3
    assert result[-1]["job_id"] == "j4"


def test_read_job_history_creates_dirs(tmp_path: Path) -> None:
    rec = _sample_record()
    log_job_history(tmp_path, "NewClient", rec)
    assert (tmp_path / "NewClient" / ".history" / "job_history.jsonl").exists()


# ---------------------------------------------------------------------------
# archive_config
# ---------------------------------------------------------------------------


def test_archive_config_copies_file(tmp_path: Path) -> None:
    config = tmp_path / "my_job.yaml"
    config.write_text("job_type: report_download\nclient: X\n")
    dest = archive_config(tmp_path, "X", config, "2025-07-15")
    assert dest.exists()
    assert dest.name == "2025-07-15_my_job.yaml"
    assert dest.read_text() == config.read_text()


def test_archive_config_creates_configs_dir(tmp_path: Path) -> None:
    config = tmp_path / "cfg.yaml"
    config.write_text("x: 1")
    dest = archive_config(tmp_path, "Client", config, "2025-01-01")
    assert dest.parent == tmp_path / "Client" / ".history" / "configs"


def test_archive_config_original_unchanged(tmp_path: Path) -> None:
    config = tmp_path / "cfg.yaml"
    config.write_text("original content")
    archive_config(tmp_path, "C", config, "2025-01-01")
    assert config.exists()
    assert config.read_text() == "original content"


# ---------------------------------------------------------------------------
# cleanup_old_files
# ---------------------------------------------------------------------------


def _make_old_file(path: Path, age_seconds: int = 100_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("data")
    old_mtime = time.time() - age_seconds
    import os
    os.utime(path, (old_mtime, old_mtime))


def test_cleanup_processed_json_removes_old(tmp_path: Path) -> None:
    processed = tmp_path / "TestClient" / "JSON" / "_processed"
    processed.mkdir(parents=True)
    old_file = processed / "old.json"
    _make_old_file(old_file, age_seconds=31 * 86_400)
    count = cleanup_old_files(tmp_path, "TestClient", older_than_days=30, file_type="processed-json")
    assert count == 1
    assert not old_file.exists()


def test_cleanup_does_not_remove_recent_files(tmp_path: Path) -> None:
    processed = tmp_path / "TestClient" / "JSON" / "_processed"
    processed.mkdir(parents=True)
    new_file = processed / "new.json"
    new_file.write_text("{}")
    count = cleanup_old_files(tmp_path, "TestClient", older_than_days=30, file_type="processed-json")
    assert count == 0
    assert new_file.exists()


def test_cleanup_logs(tmp_path: Path) -> None:
    logs_dir = tmp_path / "C" / ".logs"
    logs_dir.mkdir(parents=True)
    old_log = logs_dir / "job_abc.log"
    _make_old_file(old_log, age_seconds=8 * 86_400)
    count = cleanup_old_files(tmp_path, "C", older_than_days=7, file_type="logs")
    assert count == 1


def test_cleanup_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "C" / ".state"
    state_dir.mkdir(parents=True)
    old_db = state_dir / "old.db"
    _make_old_file(old_db, age_seconds=100 * 86_400)
    count = cleanup_old_files(tmp_path, "C", older_than_days=90, file_type="state")
    assert count == 1


def test_cleanup_returns_zero_when_dir_missing(tmp_path: Path) -> None:
    count = cleanup_old_files(tmp_path, "NoClient", older_than_days=1, file_type="logs")
    assert count == 0


def test_cleanup_raises_on_unknown_type(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown file_type"):
        cleanup_old_files(tmp_path, "C", older_than_days=1, file_type="unknown")


# ---------------------------------------------------------------------------
# build_history_record
# ---------------------------------------------------------------------------


def test_build_history_record_fields(tmp_path: Path) -> None:
    config = tmp_path / "job.yaml"
    config.write_text("")
    summary = {
        "job_id": "abc",
        "job_status": "completed",
        "started_at": "2025-07-01T10:00:00+00:00",
        "completed_at": "2025-07-01T11:00:00+00:00",
        "total": 100,
        "completed": 98,
        "failed": 2,
    }
    rec = build_history_record(
        job_id="abc",
        config_path=config,
        summary=summary,
        output_folder="/out/",
        archived_config_rel=".history/configs/2025-07-01_job.yaml",
    )
    assert rec["job_id"] == "abc"
    assert rec["status"] == "completed"
    assert rec["duration_minutes"] == 60.0
    assert rec["total_requests"] == 100
    assert rec["completed_requests"] == 98
    assert rec["failed_requests"] == 2


def test_build_history_record_no_timestamps(tmp_path: Path) -> None:
    config = tmp_path / "job.yaml"
    config.write_text("")
    summary: dict = {"job_status": "failed", "total": 0, "completed": 0, "failed": 0}  # type: ignore[type-arg]
    rec = build_history_record("x", config, summary, "/out/", "")
    assert rec["duration_minutes"] is None
    assert rec["status"] == "failed"
