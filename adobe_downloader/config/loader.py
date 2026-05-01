"""Config and credential loading."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter

from adobe_downloader.config.schema import JobConfig

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CREDENTIALS_DIR = _REPO_ROOT / "credentials"

_job_config_adapter: TypeAdapter[JobConfig] = TypeAdapter(JobConfig)


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
    return (
        (_CREDENTIALS_DIR / f"client{client}.yaml").exists()
        or (_CREDENTIALS_DIR / f"{client}.yaml").exists()
    )
