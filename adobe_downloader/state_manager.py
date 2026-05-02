"""SQLite-backed state persistence for adobe-downloader jobs.

Every API request is registered before execution and its outcome recorded after,
enabling resume-on-restart and shared-report file copying.
"""

import hashlib
import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# Request lifecycle statuses
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT PRIMARY KEY,
    config_path     TEXT NOT NULL,
    config_hash     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    completed_at    TEXT,
    total_requests  INTEGER DEFAULT 0,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS requests (
    request_id              TEXT PRIMARY KEY,
    job_id                  TEXT NOT NULL REFERENCES jobs(job_id),
    request_key             TEXT NOT NULL,
    request_body_hash       TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'pending',
    created_at              TEXT NOT NULL,
    started_at              TEXT,
    completed_at            TEXT,
    retry_count             INTEGER DEFAULT 0,
    error_message           TEXT,
    output_path             TEXT,
    canonical_request_id    TEXT REFERENCES requests(request_id),
    UNIQUE(job_id, request_key)
);

CREATE TABLE IF NOT EXISTS step_state (
    step_id         TEXT NOT NULL,
    job_id          TEXT NOT NULL REFERENCES jobs(job_id),
    status          TEXT NOT NULL DEFAULT 'pending',
    outputs         TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    PRIMARY KEY (job_id, step_id)
);

CREATE INDEX IF NOT EXISTS idx_requests_job_status ON requests(job_id, status);
CREATE INDEX IF NOT EXISTS idx_requests_body_hash ON requests(job_id, request_body_hash);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_config_hash(config_path: Path) -> str:
    """Return SHA-256 of the config file contents."""
    content = config_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def compute_job_id(config_path: Path, config_hash: str) -> str:
    """Return a stable job ID derived from config path + content hash."""
    key = f"{config_path.resolve()}|{config_hash}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def compute_request_key(
    rsid: str,
    report_name: str,
    date_from: str,
    date_to: str,
    segment_ids: list[str],
) -> str:
    """Return a stable string key identifying one unique download request."""
    seg_part = "|".join(sorted(segment_ids))
    return f"{rsid}|{report_name}|{date_from}|{date_to}|{seg_part}"


def compute_request_body_hash(request_body: dict[str, Any]) -> str:
    """Return SHA-256 of the canonical JSON of the request body."""
    canonical = json.dumps(request_body, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def state_db_path(base_folder: str | Path, client: str, job_id: str) -> Path:
    """Return the path to the SQLite state DB for a job."""
    return Path(base_folder) / client / ".state" / f"{job_id}.db"


class StateManager:
    """Manages SQLite state for a single job run."""

    def __init__(self, db_path: Path, job_id: str, config_path: Path, config_hash: str) -> None:
        self._db_path = db_path
        self._job_id = job_id
        self._config_path = config_path
        self._config_hash = config_hash
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @property
    def job_id(self) -> str:
        return self._job_id

    @contextmanager
    def _connect(self):  # type: ignore[no-untyped-def]
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)
            conn.execute(
                """
                INSERT OR IGNORE INTO jobs (job_id, config_path, config_hash, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (self._job_id, str(self._config_path), self._config_hash, _now()),
            )

    def get_config_hash(self) -> str | None:
        """Return the config_hash stored for this job_id, or None if not found."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT config_hash FROM jobs WHERE job_id = ?", (self._job_id,)
            ).fetchone()
        return row["config_hash"] if row else None

    def mark_job_started(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'in_progress', started_at = ? WHERE job_id = ?",
                (_now(), self._job_id),
            )

    def mark_job_completed(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'completed', completed_at = ? WHERE job_id = ?",
                (_now(), self._job_id),
            )

    def mark_job_failed(self, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'failed', completed_at = ?, error_message = ? WHERE job_id = ?",
                (_now(), error, self._job_id),
            )

    def track_request(
        self,
        request_key: str,
        request_body: dict[str, Any],
        output_path: Path,
    ) -> tuple[str, str | None]:
        """Register a request before execution.

        Returns (request_id, canonical_request_id).
        canonical_request_id is non-None when this is a shared-report copy request.
        """
        body_hash = compute_request_body_hash(request_body)
        with self._connect() as conn:
            # Check for an existing canonical request with the same body hash
            canonical_row = conn.execute(
                """
                SELECT request_id FROM requests
                WHERE job_id = ? AND request_body_hash = ? AND canonical_request_id IS NULL
                AND request_key != ?
                LIMIT 1
                """,
                (self._job_id, body_hash, request_key),
            ).fetchone()
            canonical_id: str | None = canonical_row["request_id"] if canonical_row else None

            request_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT OR IGNORE INTO requests
                    (request_id, job_id, request_key, request_body_hash, status,
                     created_at, output_path, canonical_request_id)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    request_id,
                    self._job_id,
                    request_key,
                    body_hash,
                    _now(),
                    str(output_path),
                    canonical_id,
                ),
            )
            # If the key already existed (resume), retrieve the existing row
            existing = conn.execute(
                "SELECT request_id, canonical_request_id FROM requests WHERE job_id = ? AND request_key = ?",
                (self._job_id, request_key),
            ).fetchone()
        return existing["request_id"], existing["canonical_request_id"]

    def mark_started(self, request_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE requests SET status = 'in_progress', started_at = ? WHERE request_id = ?",
                (_now(), request_id),
            )

    def mark_complete(self, request_id: str, output_path: Path) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE requests
                SET status = 'completed', completed_at = ?, output_path = ?
                WHERE request_id = ?
                """,
                (_now(), str(output_path), request_id),
            )

    def mark_failed(self, request_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE requests
                SET status = 'failed', completed_at = ?, error_message = ?,
                    retry_count = retry_count + 1
                WHERE request_id = ?
                """,
                (_now(), error, request_id),
            )

    def is_complete(self, request_key: str) -> bool:
        """Return True if this request_key has status=completed for this job."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM requests WHERE job_id = ? AND request_key = ?",
                (self._job_id, request_key),
            ).fetchone()
        return row is not None and row["status"] == STATUS_COMPLETED

    def get_canonical_output_path(self, canonical_request_id: str) -> Path | None:
        """Return the output_path of a completed canonical request, or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT output_path, status FROM requests WHERE request_id = ?",
                (canonical_request_id,),
            ).fetchone()
        if row and row["status"] == STATUS_COMPLETED and row["output_path"]:
            return Path(row["output_path"])
        return None

    def get_summary(self) -> dict[str, Any]:
        """Return counts by status plus job metadata."""
        with self._connect() as conn:
            job_row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (self._job_id,)
            ).fetchone()
            counts = conn.execute(
                """
                SELECT status, COUNT(*) as cnt
                FROM requests WHERE job_id = ?
                GROUP BY status
                """,
                (self._job_id,),
            ).fetchall()
            last_errors = conn.execute(
                """
                SELECT request_key, error_message FROM requests
                WHERE job_id = ? AND status = 'failed'
                ORDER BY completed_at DESC LIMIT 5
                """,
                (self._job_id,),
            ).fetchall()

        status_counts: dict[str, int] = {r["status"]: r["cnt"] for r in counts}
        return {
            "job_id": self._job_id,
            "job_status": job_row["status"] if job_row else "unknown",
            "created_at": job_row["created_at"] if job_row else None,
            "started_at": job_row["started_at"] if job_row else None,
            "completed_at": job_row["completed_at"] if job_row else None,
            "pending": status_counts.get(STATUS_PENDING, 0),
            "in_progress": status_counts.get(STATUS_IN_PROGRESS, 0),
            "completed": status_counts.get(STATUS_COMPLETED, 0),
            "failed": status_counts.get(STATUS_FAILED, 0),
            "total": sum(status_counts.values()),
            "last_errors": [
                {"key": r["request_key"], "error": r["error_message"]} for r in last_errors
            ],
        }

    def reset_failed(self) -> int:
        """Reset all failed requests to pending. Returns count of rows updated."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE requests SET status = 'pending', error_message = NULL, completed_at = NULL
                WHERE job_id = ? AND status = 'failed'
                """,
                (self._job_id,),
            )
        return cur.rowcount

    def reset_all(self) -> int:
        """Reset all non-completed requests to pending. Returns count of rows updated."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE requests SET status = 'pending', error_message = NULL,
                    started_at = NULL, completed_at = NULL
                WHERE job_id = ? AND status != 'completed'
                """,
                (self._job_id,),
            )
            conn.execute(
                "UPDATE jobs SET status = 'pending', started_at = NULL, completed_at = NULL, error_message = NULL WHERE job_id = ?",
                (self._job_id,),
            )
        return cur.rowcount

    def full_reset(self) -> None:
        """Delete all state for this job (requests and job record)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM requests WHERE job_id = ?", (self._job_id,))
            conn.execute("DELETE FROM step_state WHERE job_id = ?", (self._job_id,))
            conn.execute("DELETE FROM jobs WHERE job_id = ?", (self._job_id,))
