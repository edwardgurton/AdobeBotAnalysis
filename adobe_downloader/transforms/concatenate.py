"""CSV concatenation: merge per-interval CSVs into one output file."""

import logging
import re
from pathlib import Path

_log = logging.getLogger(__name__)


def concatenate_csvs(
    folder: Path,
    pattern: str,
    output_path: Path,
    custom_headers: dict[int, str] | None = None,
) -> int:
    """Concatenate all CSVs in folder matching pattern into output_path.

    The header row is taken from the first matching file; subsequent files have
    their header rows skipped.  custom_headers replaces specific column headers
    by 0-based index.

    Returns the number of files concatenated (0 if none matched).
    """
    regex = re.compile(pattern.replace("*", ".*"))
    csv_files = sorted(
        f for f in folder.iterdir() if regex.search(f.name) and f.suffix == ".csv"
    )

    if not csv_files:
        _log.warning("No CSV files matched pattern %r in %s", pattern, folder)
        return 0

    header: list[str] | None = None
    data_lines: list[str] = []

    for csv_file in csv_files:
        lines = [ln for ln in csv_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not lines:
            continue
        if header is None:
            header = lines[0].split(",")
            if custom_headers:
                for idx, new_name in custom_headers.items():
                    if 0 <= idx < len(header):
                        header[idx] = new_name
            data_lines.extend(lines[1:])
        else:
            data_lines.extend(lines[1:])

    if header is None:
        _log.warning("No non-empty CSV files found in %s", folder)
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join([",".join(header)] + data_lines)
    if not content.endswith("\n"):
        content += "\n"
    output_path.write_text(content, encoding="utf-8")
    _log.info("Concatenated %d file(s) -> %s", len(csv_files), output_path)
    return len(csv_files)
