"""Config and credential loading."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter

from adobe_downloader.config.schema import CompositeJobConfig, JobConfig, ReportDownloadConfig

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CREDENTIALS_DIR = _REPO_ROOT / "credentials"

_job_config_adapter: TypeAdapter[JobConfig] = TypeAdapter(JobConfig)

# bot_rule_compare and bot_validation filenames both embed a verbose per-rule
# identifier (see sanitize_bot_rule_name / transform_bot_rule_compare), which
# already eats deep into Windows' 260-char MAX_PATH budget on its own — a long
# job_name compounds that risk. Recommended, not enforced: some paths are safe
# well past this (see composite_bot_rule_compare.yaml for the full breakdown).
JOB_NAME_LENGTH_LIMIT = 15


def load_config(path: Path) -> JobConfig:
    """Load and validate a job config YAML. Raises ValidationError on schema errors."""
    with path.open(encoding="utf-8") as fh:
        raw: Any = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"Config file must be a YAML mapping, got: {type(raw).__name__}")
    return _job_config_adapter.validate_python(raw)


def check_referenced_files(config: JobConfig, config_path: Path) -> list[str]:
    """
    Check that files referenced in the config actually exist.
    Returns a list of human-readable error strings (empty = all OK).
    """
    errors: list[str] = []

    def _check(field: str, value: str | None) -> None:
        if value is None:
            return
        p = Path(value)
        if not p.is_absolute():
            p = _REPO_ROOT / p
        if not p.exists():
            errors.append(f"{field}: file not found: {p}")

    match config:
        case _ if hasattr(config, "rsids"):
            rsids = getattr(config, "rsids", None)
            if rsids and rsids.source == "file":
                _check("rsids.file", rsids.file)

        case _:
            pass

    # segment_creation input CSV
    if hasattr(config, "segment_creation"):
        sc = getattr(config, "segment_creation", None)
        if sc:
            _check("segment_creation.input_csv", sc.input_csv)

    # segments source file
    if hasattr(config, "segments"):
        seg = getattr(config, "segments", None)
        if seg and seg.source == "segment_list_file":
            _check("segments.file", seg.file)

    return errors


def check_job_name_length(config: JobConfig) -> list[str]:
    """
    Warn if a bot_rule_compare or bot_validation job's output.job_name is long
    enough to risk exceeding Windows' 260-char MAX_PATH once combined with the
    per-rule identifier these flows already embed in every output filename.
    Returns a list of human-readable warning strings (empty = no concern).
    """
    warnings: list[str] = []

    def _check(job_name: str | None, label: str) -> None:
        if job_name and len(job_name) > JOB_NAME_LENGTH_LIMIT:
            warnings.append(
                f"{label}: output.job_name {job_name!r} is {len(job_name)} chars "
                f"(recommended <= {JOB_NAME_LENGTH_LIMIT}) — bot_rule_compare/bot_validation "
                "filenames already embed a long per-rule identifier, so a long job_name "
                "increases the risk of exceeding Windows' 260-character path limit"
            )

    if isinstance(config, CompositeJobConfig):
        step_types = {s.step for s in config.steps}
        is_bot_validation = any(
            s.step == "report_download" and s.extra_fields().get("report_group") == "bot_validation"
            for s in config.steps
        )
        if "bot_rule_compare" in step_types or is_bot_validation:
            _check(config.output.job_name if config.output else None, "output")
    elif isinstance(config, ReportDownloadConfig):
        if config.report_group == "bot_validation":
            _check(config.output.job_name, "output")

    return warnings


def load_credentials(client: str) -> dict[str, Any]:
    """Load client credentials YAML. Returns the parsed dict."""
    path = _CREDENTIALS_DIR / f"client{client}.yaml"
    if not path.exists():
        # Fall back to exact filename match
        path = _CREDENTIALS_DIR / f"{client}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Credentials file not found for client '{client}'. "
            f"Expected: {_CREDENTIALS_DIR / f'client{client}.yaml'}"
        )
    with path.open(encoding="utf-8") as fh:
        data: Any = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Credentials file must be a YAML mapping: {path}")
    return data  # type: ignore[return-value]


def credentials_exist(client: str) -> bool:
    """Return True if a credentials file exists for this client."""
    return (_CREDENTIALS_DIR / f"client{client}.yaml").exists() or (
        _CREDENTIALS_DIR / f"{client}.yaml"
    ).exists()
