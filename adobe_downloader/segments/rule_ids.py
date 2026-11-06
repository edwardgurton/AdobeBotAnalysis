"""Rule ID grammar and segment naming for bot rule investigations.

See ``docs/MasterDecisionLog_Plan.md`` §1. A Rule ID looks like::

    {AH|RT}-{FreeText}-IR                 initial compare (Super-Investigation root)
    {AH|RT}-{FreeText}-R{round}{letters}  first generation   AH-Oddspedia-R1A
    {parentRuleId}{round}{letters}        later generations  AH-Oddspedia-R1A2B
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RULE_ID_RE = re.compile(r"^(?P<super>(?:AH|RT)-[A-Za-z0-9]+)-(?P<tail>IR|R\d[A-Z]+(?:\d[A-Z]+)*)$")
_GENERATION_RE = re.compile(r"\d[A-Z]+")

COMPARE_PREFIX = "BOTCOMPARE_"
DESCRIPTION_DELIMITER = "~"
BOT_RULE_NAME_MAX_LENGTH = 95


@dataclass(frozen=True)
class RuleIdParts:
    rule_id: str
    round_id: str
    super_investigation: str
    parent_rule_id: str | None


def parse_rule_id(rule_id: str) -> RuleIdParts:
    """Split *rule_id* into its derived parts, or raise ``ValueError``.

    The initial compare (``…-IR``) is its own round and has no parent. A
    first-generation rule's parent is the initial compare.
    """
    m = RULE_ID_RE.match(rule_id)
    if m is None:
        raise ValueError(
            f"Rule ID {rule_id!r} does not match {{AH|RT}}-{{FreeText}}-IR or "
            f"{{AH|RT}}-{{FreeText}}-R{{round}}{{letter}}[{{round}}{{letter}}…] "
            "(FreeText alphanumeric only)"
        )
    super_inv = m.group("super")
    tail = m.group("tail")
    if tail == "IR":
        return RuleIdParts(rule_id, rule_id, super_inv, None)

    round_id = rule_id.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    generations = _GENERATION_RE.findall(tail[1:])
    if len(generations) == 1:
        parent = f"{super_inv}-IR"
    else:
        parent = f"{super_inv}-R" + "".join(generations[:-1])
    return RuleIdParts(rule_id, round_id, super_inv, parent)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def condition_text(dimensions: list[tuple[str, str]]) -> str:
    """``Dim=ItemANDDim=Item`` — the description format the workbook produces."""
    return "AND".join(f"{dim}={item}" for dim, item in dimensions)


def build_validate_segment_name(
    rsid_clean_name: str, dimensions: list[tuple[str, str]], number: int | None
) -> str:
    """``{NNNN} BOT RULE: {rsid} - {conditions}``; no number prefix when *number* is None."""
    body = f"BOT RULE: {rsid_clean_name} - {condition_text(dimensions)}"
    return body if number is None else f"{number:04d} {body}"


def build_compare_segment_name(
    rule_id: str, rsid_clean_name: str, dimensions: list[tuple[str, str]]
) -> str:
    """``BOTCOMPARE_{RuleID}~ {rsid} - {conditions}``."""
    return (
        f"{COMPARE_PREFIX}{rule_id}{DESCRIPTION_DELIMITER} "
        f"{rsid_clean_name} - {condition_text(dimensions)}"
    )


_COMPACT_ABBREVIATIONS: list[tuple[str, str]] = [
    ("OperatingSystem", "OS"),
    ("MonitorResolution", "MonRes"),
    ("MarketingChannel", "MarCha"),
    ("ReferringDomain", "RefDom"),
    ("MobileManufacturer", "MobMan"),
    ("BrowserType", "BrowType"),
    ("UserAgent", "UsAg"),
    ("PageURL", "URL"),
    ("Region", "Reg"),
    ("Domain", "Dom"),
]


def compact_description(rsid_clean_name: str, dimensions: list[tuple[str, str]]) -> str:
    """Filename-safe description: ``{rsid}{Dim=Item}AND…`` with separators stripped.

    UserAgent values are dropped (only the dimension name is kept): they are long
    and full of characters that do not belong in a filename.
    """
    parts = [dim if dim.lower() == "useragent" else f"{dim}={item}" for dim, item in dimensions]
    text = rsid_clean_name + "AND".join(parts)
    return re.sub(r"[\s:./,\-~_]", "", text)


def _shorten(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    for long, short in _COMPACT_ABBREVIATIONS:
        text = re.sub(long, short, text, flags=re.IGNORECASE)
    return text[:max_len]


def build_compare_bot_rule_name(
    rule_id: str, rsid_clean_name: str, dimensions: list[tuple[str, str]]
) -> str:
    """``BOTCOMPARE_{RuleID}~{compacted description}``, at most 95 characters.

    The Rule ID is kept verbatim (hyphens included) so the next round's workbook
    can recover it; only the description after ``~`` is shortened.
    """
    prefix = f"{COMPARE_PREFIX}{rule_id}{DESCRIPTION_DELIMITER}"
    budget = BOT_RULE_NAME_MAX_LENGTH - len(prefix)
    if budget < 1:
        raise ValueError(f"Rule ID {rule_id!r} is too long to fit in a bot rule name")
    return prefix + _shorten(compact_description(rsid_clean_name, dimensions), budget)
