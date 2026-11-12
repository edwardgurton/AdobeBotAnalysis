"""Generate the run config for a round of bot rule segments (MDL plan A6).

``segment_creation`` writes ``jobs/generated/{RoundID}_run.yaml`` after it writes the
compare and validate lists. The run config is an ordinary composite job:

    download_validation -> validate_bot_rules -> transform_validation
    download_compare    -> validate_bot_compares -> transform_compare
    segment_records     (MDL plan A7)

A half is left out when its list is empty. The steps point at the concrete list
files, so the run can start on its own once any Special segments have been created in
Adobe and their IDs written into the lists. Defaults come from a run template (see
``jobs/templates/mdl_run_template.yaml``).

This module also holds the run guard: a job refuses to start while any list it reads
from a file still contains the ``UPDATE-SEGMENT-ID`` placeholder.
"""

from __future__ import annotations

import csv
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from adobe_downloader.config.schema import (
    DEFAULT_CANDIDATE_TAG,
    DEFAULT_VISITS_REPORT,
    CompositeJobConfig,
    DateRange,
    RsidSource,
)
from adobe_downloader.segments.segment_records import PLACEHOLDER_SEGMENT_ID

logger = logging.getLogger(__name__)

DEFAULT_RUN_CONFIG_DIR = Path("jobs") / "generated"

# Step ids in the generated config. segment_records relies on these only through
# depends_on, so renaming one here is safe.
DOWNLOAD_VALIDATION = "download_validation"
VALIDATE_VALIDATION = "validate_bot_rules"
TRANSFORM_VALIDATION = "transform_validation"
DOWNLOAD_COMPARE = "download_compare"
VALIDATE_COMPARE = "validate_bot_compares"
TRANSFORM_COMPARE = "transform_compare"
SEGMENT_RECORDS = "segment_records"


# ---------------------------------------------------------------------------
# Run template
# ---------------------------------------------------------------------------


class _TemplateDateRange(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str | None = None


class _TemplateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_folder: str


class _TemplateValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_group: str = "bot_validation"
    interval: str = "month"


class _TemplateCompare(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_group: str = "bot_rule_compare"
    comparison_round: float = 1
    source_pattern: str = r".*Compare-V1.*\.json$"


class _TemplateSegmentRecords(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visits_report: str = DEFAULT_VISITS_REPORT


class RunTemplate(BaseModel):
    """Defaults for a generated run config, loaded from ``segment_creation.run_template``."""

    model_config = ConfigDict(extra="forbid")

    output: _TemplateOutput
    rsids: RsidSource
    date_range: _TemplateDateRange
    validation: _TemplateValidation = Field(default_factory=_TemplateValidation)
    compare: _TemplateCompare = Field(default_factory=_TemplateCompare)
    segment_records: _TemplateSegmentRecords = Field(default_factory=_TemplateSegmentRecords)


def load_run_template(path: Path) -> RunTemplate:
    """Read and validate a run template YAML file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Run template {path} is not a mapping")
    try:
        return RunTemplate.model_validate(raw)
    except Exception as exc:
        raise ValueError(f"Run template {path} is invalid: {exc}") from exc


# ---------------------------------------------------------------------------
# Building the run config
# ---------------------------------------------------------------------------


def _path_str(path: Path) -> str:
    """Forward slashes so the YAML reads the same on every platform."""
    return path.as_posix()


def build_run_config(
    *,
    client: str,
    round_id: str,
    template: RunTemplate,
    validate_list: Path | None,
    compare_list: Path | None,
    records_path: Path,
    candidate_tag: str = DEFAULT_CANDIDATE_TAG,
    today: date | None = None,
) -> dict[str, Any]:
    """Return the composite run config for one round, as a plain dict.

    ``date_range.to`` is the template's ``to`` when set, otherwise yesterday.
    """
    if validate_list is None and compare_list is None:
        raise ValueError("Cannot build a run config: there is no validate or compare list")

    to = template.date_range.to or ((today or date.today()) - timedelta(days=1)).isoformat()
    date_range = DateRange.model_validate({"from": template.date_range.from_, "to": to})
    rsids = template.rsids.model_dump(exclude_none=True, by_alias=True)

    steps: list[dict[str, Any]] = []
    last_transform: str | None = None

    if validate_list is not None:
        steps += [
            {
                "step": "report_download",
                "id": DOWNLOAD_VALIDATION,
                "report_group": template.validation.report_group,
                "rsids": rsids,
                "bot_rules": {"source": "file", "file": _path_str(validate_list)},
                "interval": template.validation.interval,
            },
            {
                "step": "validate_output",
                "id": VALIDATE_VALIDATION,
                "depends_on": DOWNLOAD_VALIDATION,
                "config_ref": DOWNLOAD_VALIDATION,
                "retry": True,
            },
            {
                "step": "transform_concat",
                "id": TRANSFORM_VALIDATION,
                "depends_on": VALIDATE_VALIDATION,
                "transform": {
                    "type": "bot_validation",
                    "concat": True,
                    "split_by_bot_rule": True,
                },
            },
        ]
        last_transform = TRANSFORM_VALIDATION

    if compare_list is not None:
        steps += [
            {
                "step": "bot_rule_compare",
                "id": DOWNLOAD_COMPARE,
                "report_group": template.compare.report_group,
                "rsids": rsids,
                "bot_rules": {"source": "file", "file": _path_str(compare_list)},
                "comparison_round": template.compare.comparison_round,
            },
            {
                "step": "validate_output",
                "id": VALIDATE_COMPARE,
                "depends_on": DOWNLOAD_COMPARE,
                "config_ref": DOWNLOAD_COMPARE,
                "retry": True,
            },
            {
                "step": "transform_concat",
                "id": TRANSFORM_COMPARE,
                "depends_on": VALIDATE_COMPARE,
                "transform": {
                    "type": "bot_rule_compare",
                    "source_pattern": template.compare.source_pattern,
                    "concat": True,
                    "split_by_bot_rule": True,
                },
            },
        ]
        last_transform = TRANSFORM_COMPARE

    records_cfg: dict[str, Any] = {"records_path": _path_str(records_path)}
    if validate_list is not None:
        records_cfg["validate_list"] = _path_str(validate_list)
    if compare_list is not None:
        records_cfg["compare_list"] = _path_str(compare_list)
    records_cfg["visits_report"] = template.segment_records.visits_report
    records_cfg["candidate_tag"] = candidate_tag
    steps.append(
        {
            "step": "segment_records",
            "id": SEGMENT_RECORDS,
            "depends_on": last_transform,
            "segment_records": records_cfg,
        }
    )

    config: dict[str, Any] = {
        "job_type": "composite",
        "client": client,
        "description": (
            f"Run for round {round_id}, generated by segment_creation. "
            "Edit freely; re-running segment_creation for this round overwrites it."
        ),
        "date_range": {"from": date_range.from_date, "to": date_range.to},
        "output": {"base_folder": template.output.base_folder, "job_name": round_id},
        "steps": steps,
    }
    # Fail now, not when the user runs it, if the generated config is not loadable.
    CompositeJobConfig.model_validate(config)
    return config


def write_run_config(folder: Path, round_id: str, config: dict[str, Any]) -> Path:
    """Write *config* to ``{folder}/{round_id}_run.yaml``; an existing file is replaced."""
    path = folder / f"{round_id}_run.yaml"
    if path.exists():
        logger.warning("Replacing existing run config %s", path)
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True, width=1000),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Run guard
# ---------------------------------------------------------------------------


def placeholder_rows(list_file: Path) -> list[str]:
    """Return ``"row N: botRuleName"`` for each row of a list still holding the placeholder.

    Row numbers count the header as row 1, matching what a spreadsheet shows.
    """
    found: list[str] = []
    with list_file.open(newline="", encoding="utf-8-sig") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=2):
            if (row.get("DimSegmentId") or "").strip() == PLACEHOLDER_SEGMENT_ID:
                found.append(f"row {i}: {row.get('botRuleName', '').strip()}")
    return found


def check_lists_have_segment_ids(job: CompositeJobConfig) -> None:
    """Raise ``ValueError`` if any ``bot_rules`` list file in *job* has a placeholder ID.

    Only ``source: file`` lists are checked: a list produced by a ``segment_creation``
    step in the same job does not exist yet when the job starts. Missing files are
    left for the step itself to report.
    """
    problems: list[str] = []
    for step in job.steps:
        bot_rules = step.extra_fields().get("bot_rules")
        if not isinstance(bot_rules, dict) or bot_rules.get("source") != "file":
            continue
        file = bot_rules.get("file")
        if not file:
            continue
        path = Path(str(file))
        if not path.is_file():
            continue
        rows = placeholder_rows(path)
        if rows:
            problems.append(f"{path} (step {step.id!r}):\n    " + "\n    ".join(rows))
    if problems:
        raise ValueError(
            f"These lists still contain {PLACEHOLDER_SEGMENT_ID}. Create the Special "
            "segments in Adobe (tag validates "
            f"{DEFAULT_CANDIDATE_TAG}), put their segment IDs in the lists, then run "
            "again:\n  " + "\n  ".join(problems)
        )
