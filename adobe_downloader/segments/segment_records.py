"""One YAML record per segment created by ``segment_creation`` (MDL plan A5).

Records live in ``data/segment_records/{client}/{RuleID}.yaml`` by default. They
are the hand-off between segment creation, the post-run ``segment_records`` step
(which fills in visits) and the Master Decision Log.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_RECORDS_ROOT = Path("data") / "segment_records"

# Segment ID written for Special rows until the segment is created by hand in Adobe.
PLACEHOLDER_SEGMENT_ID = "UPDATE-SEGMENT-ID"


def default_records_path(client: str) -> Path:
    return DEFAULT_RECORDS_ROOT / client


def record_filename(rule_id: str | None, segment_name: str) -> str:
    """``{RuleID}.yaml``, or a sanitised segment name when there is no Rule ID."""
    if rule_id:
        return f"{rule_id}.yaml"
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", segment_name).strip("_")[:150]
    return f"{stem or 'segment'}.yaml"


def build_record(
    *,
    rule_id: str | None,
    round_id: str | None,
    super_investigation: str | None,
    parent_rule_id: str | None,
    compare_validate: str,
    next_step: str | None,
    segment_name: str,
    bot_rule_name: str,
    bot_rule_number: int | None,
    segment_id: str | None,
    rsid: str | None,
    rsid_clean_name: str,
    conditions: list[dict[str, Any]],
    prior_rules: list[str],
    has_prior_step: bool | None,
    has_following_step: bool | None,
    created_by_job: str,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Return the record as an ordered dict, in the layout from the plan (§3 A5)."""
    when = (created_at or datetime.now(UTC)).astimezone(UTC)
    return {
        "rule_id": rule_id,
        "round_id": round_id,
        "super_investigation": super_investigation,
        "parent_rule_id": parent_rule_id,
        "compare_validate": compare_validate,
        "next_step": next_step,
        "segment_name": segment_name,
        "bot_rule_name": bot_rule_name,
        "bot_rule_number": bot_rule_number,
        "segment_id": segment_id,
        "rsid": rsid,
        "rsid_clean_name": rsid_clean_name,
        "conditions": conditions,
        "prior_rules": prior_rules,
        "has_prior_step": has_prior_step,
        "has_following_step": has_following_step,
        "created_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_by_job": created_by_job,
        "visits_last_12_months": None,
        "visits_window": {"from": None, "to": None},
    }


def write_record(folder: Path, record: dict[str, Any]) -> Path:
    """Write *record* to *folder*; an existing record for the same rule is replaced."""
    path = folder / record_filename(record.get("rule_id"), record["segment_name"])
    if path.exists():
        logger.warning("Replacing existing segment record %s", path)
    folder.mkdir(parents=True, exist_ok=True)
    save_record(path, record)
    return path


def save_record(path: Path, record: dict[str, Any]) -> None:
    """Write *record* to *path* as YAML, keeping the key order."""
    path.write_text(
        yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=1000),
        encoding="utf-8",
    )


def load_record(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Segment record {path} is not a mapping")
    return data
