"""Shared filename-sanitization helpers for output paths across flows.

Lives outside flows/ so report_download.py, bot_rule_compare.py, and
composite_job.py can all depend on it without creating an import cycle
(bot_rule_compare.py already imports from report_download.py).
"""

import re

_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_windows_filename_component(value: str) -> str:
    """Replace characters illegal in Windows filenames with '-'."""
    return _ILLEGAL_FILENAME_CHARS.sub("-", value)


def sanitize_bot_rule_name(name: str) -> str:
    """Replace underscores with hyphens for safe embedding in output filenames.

    Filename-parsing transforms split on "_" to locate positional tokens; an
    underscore inside a human-readable name shifts that split and corrupts
    parsing. Names may still use hyphens freely.
    """
    return name.replace("_", "-")


def sanitize_segment_name_for_filename(name: str) -> str:
    """Apply both passes needed to embed a segment/bot-rule name in a filename."""
    return sanitize_windows_filename_component(sanitize_bot_rule_name(name))
