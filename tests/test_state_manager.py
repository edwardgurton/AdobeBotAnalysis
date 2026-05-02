"""Tests for adobe_downloader.state_manager."""

import json
from pathlib import Path

import pytest

from adobe_downloader.state_manager import (
    StateManager,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    compute_config_hash,
    compute_job_id,
    compute_request_body_hash,
    compute_request_key,
    state_db_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path, config_hash: str = "abc123") -> StateManager:
    config_file = tmp_path / "job.yaml"
    config_file.write_text("job_type: report_download\nclient: TestClient\n")
    job_id = compute_job_id(config_file, config_hash)
    db_path = state_db_path(tmp_path, "TestClient", job_id)
    return StateManager(db_path, job_id, config_file, config_hash)


def _dummy_body(rsid: str = "rsid1", seg: str = "") -> dict:
    return {"rsid": rsid, "globalFilters": [{"type": "segment", "segmentId": seg}]}


# ---------------------------------------------------------------------------
# compute_* helpers
# ---------------------------------------------------------------------------


def test_compute_request_key_stable() -> None:
    k1 = compute_request_key("rsid1", "reportA", "2025-01-01", "2025-02-01", ["s1", "s2"])
    k2 = compute_request_key("rsid1", "reportA", "2025-01-01", "2025-02-01", ["s2", "s1"])
    assert k1 == k2


def test_compute_request_key_differs_on_rsid() -> None:
    k1 = compute_request_key("rsid1", "reportA", "2025-01-01", "2025-02-01", [])
    k2 = compute_request_key("rsid2", "reportA", "2025-01-01", "2025-02-01", [])
    assert k1 != k2


def test_compute_request_body_hash_stable() -> None:
    body = {"rsid": "rsid1", "metrics": [{"id": "m1"}, {"id": "m2"}]}
    h1 = compute_request_body_hash(body)
    h2 = compute_request_body_hash({"metrics": [{"id": "m1"}, {"id": "m2"}], "rsid": "rsid1"})
    assert h1 == h2


def test_compute_config_hash(tmp_path: Path) -> None:
    f = tmp_path / "config.yaml"
    f.write_text("hello: world\n")
    h = compute_config_hash(f)
    assert len(h) == 64
    f.write_text("hello: world2\n")
    assert compute_config_hash(f) != h


def test_compute_job_id_stable(tmp_path: Path) -> None:
    f = tmp_path / "config.yaml"
    f.write_text("x: 1\n")
    h = compute_config_hash(f)
    assert compute_job_id(f, h) == compute_job_id(f, h)


def test_state_db_path(tmp_path: Path) -> None:
    p = state_db_path(tmp_path, "MyClient", "abc123")
    assert p == tmp_path / "MyClient" / ".state" / "abc123.db"


# ---------------------------------------------------------------------------
# StateManager — initialisation
# ---------------------------------------------------------------------------


def test_manager_creates_db(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path)
    assert sm._db_path.exists()


def test_manager_stores_config_hash(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path, config_hash="hash42")
    assert sm.get_config_hash() == "hash42"


# ---------------------------------------------------------------------------
# track_request / is_complete
# ---------------------------------------------------------------------------


def test_track_new_request_returns_ids(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path)
    req_id, canonical_id = sm.track_request(
        "rsid1|reportA|2025-01-01|2025-02-01|",
        _dummy_body(),
        tmp_path / "out.json",
    )
    assert req_id is not None
    assert canonical_id is None  # first request is canonical


def test_is_complete_false_before_completion(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path)
    key = "rsid1|reportA|2025-01-01|2025-02-01|"
    sm.track_request(key, _dummy_body(), tmp_path / "out.json")
    assert sm.is_complete(key) is False


def test_is_complete_true_after_mark_complete(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path)
    key = "rsid1|reportA|2025-01-01|2025-02-01|"
    req_id, _ = sm.track_request(key, _dummy_body(), tmp_path / "out.json")
    sm.mark_complete(req_id, tmp_path / "out.json")
    assert sm.is_complete(key) is True


def test_is_complete_false_unknown_key(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path)
    assert sm.is_complete("nonexistent_key") is False


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


def test_mark_started_sets_in_progress(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path)
    key = "rsid1|reportA|2025-01-01|2025-02-01|"
    req_id, _ = sm.track_request(key, _dummy_body(), tmp_path / "out.json")
    sm.mark_started(req_id)
    summary = sm.get_summary()
    assert summary["in_progress"] == 1


def test_mark_failed_increments_retry(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path)
    key = "rsid1|reportA|2025-01-01|2025-02-01|"
    req_id, _ = sm.track_request(key, _dummy_body(), tmp_path / "out.json")
    sm.mark_failed(req_id, "API error 500")
    summary = sm.get_summary()
    assert summary["failed"] == 1
    assert summary["last_errors"][0]["error"] == "API error 500"


# ---------------------------------------------------------------------------
# Shared-report (canonical) detection
# ---------------------------------------------------------------------------


def test_shared_report_canonical_id_set(tmp_path: Path) -> None:
    """Second request with same body hash should get canonical_request_id of the first."""
    sm = _make_manager(tmp_path)
    body = _dummy_body("rsid1")
    req_id1, canonical1 = sm.track_request("key1", body, tmp_path / "out1.json")
    req_id2, canonical2 = sm.track_request("key2", body, tmp_path / "out2.json")
    assert canonical1 is None
    assert canonical2 == req_id1


def test_get_canonical_output_path_none_before_completion(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path)
    body = _dummy_body("rsid1")
    req_id1, _ = sm.track_request("key1", body, tmp_path / "out1.json")
    _, canonical2 = sm.track_request("key2", body, tmp_path / "out2.json")
    assert canonical2 == req_id1
    # Canonical not yet completed
    assert sm.get_canonical_output_path(req_id1) is None


def test_get_canonical_output_path_after_completion(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path)
    body = _dummy_body("rsid1")
    req_id1, _ = sm.track_request("key1", body, tmp_path / "out1.json")
    sm.mark_complete(req_id1, tmp_path / "out1.json")
    _, canonical2 = sm.track_request("key2", body, tmp_path / "out2.json")
    result = sm.get_canonical_output_path(canonical2)  # type: ignore[arg-type]
    assert result == tmp_path / "out1.json"


# ---------------------------------------------------------------------------
# Resume: track_request idempotent for existing key
# ---------------------------------------------------------------------------


def test_track_request_idempotent_on_resume(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path)
    key = "rsid1|reportA|2025-01-01|2025-02-01|"
    body = _dummy_body()
    req_id1, _ = sm.track_request(key, body, tmp_path / "out.json")
    sm.mark_complete(req_id1, tmp_path / "out.json")
    req_id2, _ = sm.track_request(key, body, tmp_path / "out.json")
    assert req_id1 == req_id2
    assert sm.is_complete(key) is True


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_summary_aggregates_correctly(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path)
    k1 = "rsid1|rep|2025-01-01|2025-02-01|"
    k2 = "rsid2|rep|2025-01-01|2025-02-01|"
    k3 = "rsid3|rep|2025-01-01|2025-02-01|"
    r1, _ = sm.track_request(k1, _dummy_body("r1"), tmp_path / "a.json")
    r2, _ = sm.track_request(k2, _dummy_body("r2"), tmp_path / "b.json")
    r3, _ = sm.track_request(k3, _dummy_body("r3"), tmp_path / "c.json")
    sm.mark_complete(r1, tmp_path / "a.json")
    sm.mark_failed(r2, "err")
    summary = sm.get_summary()
    assert summary["completed"] == 1
    assert summary["failed"] == 1
    assert summary["pending"] == 1
    assert summary["total"] == 3


# ---------------------------------------------------------------------------
# reset_failed / reset_all / full_reset
# ---------------------------------------------------------------------------


def test_reset_failed_resets_to_pending(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path)
    key = "rsid1|rep|2025-01-01|2025-02-01|"
    req_id, _ = sm.track_request(key, _dummy_body(), tmp_path / "out.json")
    sm.mark_failed(req_id, "err")
    count = sm.reset_failed()
    assert count == 1
    assert sm.is_complete(key) is False
    summary = sm.get_summary()
    assert summary["failed"] == 0
    assert summary["pending"] == 1


def test_full_reset_clears_all(tmp_path: Path) -> None:
    sm = _make_manager(tmp_path)
    key = "rsid1|rep|2025-01-01|2025-02-01|"
    req_id, _ = sm.track_request(key, _dummy_body(), tmp_path / "out.json")
    sm.mark_complete(req_id, tmp_path / "out.json")
    sm.full_reset()
    summary = sm.get_summary()
    assert summary["total"] == 0
    assert summary["job_status"] == "unknown"
