"""Dual-handler logging: console (INFO/DEBUG) + rotating file (DEBUG)."""

import logging
import logging.handlers
from pathlib import Path


def setup_logging(
    output_dir: Path | None,
    client: str,
    job_name: str = "job",
    *,
    debug: bool = False,
) -> logging.Logger:
    """Configure the root logger.

    Handlers attached:
      - Console: INFO normally; DEBUG when *debug* is True.
      - File (rotating): DEBUG and above, written to
        ``<output_dir>/<client>/.logs/<job_name>.log``.
        Omitted when *output_dir* is None.

    Safe to call multiple times — duplicate handlers are not added.
    """
    root = logging.getLogger()
    if root.handlers:
        return logging.getLogger("adobe_downloader")

    root.setLevel(logging.DEBUG)

    console_level = logging.DEBUG if debug else logging.INFO
    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(
        logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(console)

    if output_dir is not None:
        log_dir = output_dir / client / ".logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{job_name}.log"

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
        root.addHandler(file_handler)

    return logging.getLogger("adobe_downloader")


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the adobe_downloader namespace."""
    return logging.getLogger(f"adobe_downloader.{name}")
