"""Find the highest bot rule number among tagged candidate segments.

Validate segments are named ``NNNN BOT RULE: ...`` and tagged ``BotRuleCandidates``
(see :data:`adobe_downloader.config.schema.DEFAULT_CANDIDATE_TAG`). The next rule
number is the highest leading 4-digit number plus one. Uniqueness is not guaranteed
(there is no lock); the numbers are housekeeping.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

import httpx

from adobe_downloader.config.schema import DEFAULT_CANDIDATE_TAG

logger = logging.getLogger(__name__)

_NUMBER_RE = re.compile(r"^(\d{4})(?!\d)")

# Tried in order: "all" sees every owner's segments but needs admin rights; "shared"
# adds segments shared with the caller to their own.
_INCLUDE_TYPES = ("all", "shared")
_FALLBACK_STATUSES = {400, 403}


def parse_bot_rule_number(name: str) -> int | None:
    """Return the leading 4-digit bot rule number in *name*, or None."""
    match = _NUMBER_RE.match(name)
    return int(match.group(1)) if match else None


def highest_bot_rule_number(names: Iterable[str]) -> int:
    """Return the highest leading 4-digit number across *names*, or 0."""
    numbers = [n for n in (parse_bot_rule_number(name) for name in names) if n is not None]
    return max(numbers, default=0)


async def _list_tagged(client: Any, tag: str) -> list[dict[str, Any]]:
    last_exc: httpx.HTTPStatusError | None = None
    for include_type in _INCLUDE_TYPES:
        try:
            segments: list[dict[str, Any]] = await client.list_segments(
                tag_names=[tag], include_type=include_type
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _FALLBACK_STATUSES:
                raise
            logger.warning(
                "Segment listing with includeType=%s was rejected (%d); trying the next option",
                include_type,
                exc.response.status_code,
            )
            last_exc = exc
            continue
        logger.debug(
            "Found %d segment(s) tagged %r (includeType=%s)", len(segments), tag, include_type
        )
        return segments
    assert last_exc is not None
    raise last_exc


async def get_highest_bot_rule_candidate_number(
    client: Any, tag: str = DEFAULT_CANDIDATE_TAG
) -> int:
    """Return the highest bot rule number among segments tagged *tag* (0 if none)."""
    segments = await _list_tagged(client, tag)
    return highest_bot_rule_number(str(s.get("name", "")) for s in segments)
