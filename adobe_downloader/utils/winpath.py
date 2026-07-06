"""Windows extended-length path support for generated output paths.

bot_rule_compare filenames embed a human-authored rule name plus RSID, segment,
and date tokens, and can exceed Windows' 260-character MAX_PATH once combined
with a client/job output folder. Prefixing an absolute path with \\\\?\\ (or
\\\\?\\UNC\\ for network shares) bypasses that limit unconditionally in the
Win32 file APIs - no registry setting or admin rights required, unlike the
LongPathsEnabled machine policy. This has been true since Windows 2000.

Call to_long_path() only immediately before a real filesystem operation
(mkdir/read_text/write_text/copy2/iterdir/exists). Never pass its result to
code that inspects .parts/.stem/.name for parsing (e.g. make_csv_output_path),
since the prefix changes how the path decomposes.
"""

from __future__ import annotations

import sys
from pathlib import Path

_EXTENDED_PREFIX = "\\\\?\\"
_UNC_PREFIX = "\\\\?\\UNC\\"


def to_long_path(path: Path) -> Path:
    """Return path resolved and prefixed for Windows extended-length file I/O.

    No-op on non-Windows platforms and on paths already carrying the prefix.
    """
    if sys.platform != "win32":
        return path

    resolved = path.resolve()
    text = str(resolved)
    if text.startswith(_EXTENDED_PREFIX):
        return resolved
    if text.startswith("\\\\"):
        return Path(_UNC_PREFIX + text.lstrip("\\"))
    return Path(_EXTENDED_PREFIX + text)
