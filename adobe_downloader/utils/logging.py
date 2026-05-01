"""Dual-handler logging: console (INFO) + rotating file (DEBUG)."""

import logging
import logging.handlers
from pathlib import Path


def setup_logging(output_dir: Path, client: str, job_name: str = "job") -> logging.Logger:
    """
    Configure the root logger with two handlers:
      - Console: INFO and above, human-readable format.
      - File: DEBUG and above, written to <output_dir>/<client>/.logs/<job_name>.log.

    Safe to call multiple times; duplicate handlers are not added.
    """
    log_dir = output_dir / client / ".logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{job_name}.log"

    root = logging.getLogger()
    if root.handlers:
        # Already configured — update file handler path only if needed.
        return logging.getLogger("adobe_downloader")

    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s", datefmt="%H:%M:%S")
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s  %(funcName)s:%(lineno)d  %(message)s"
        )
    )

    root.addHandler(console)
    root.addHandler(file_handler)

    return logging.getLogger("adobe_downloader")


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the adobe_downloader namespace."""
    return logging.getLogger(f"adobe_downloader.{name}")
