"""Create one segment per dimension value; save a segment list JSON."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DimSegmentsResult:
    segment_list_file: Path
    segments: list[dict[str, str]] = field(default_factory=list)


async def dim_to_segments(
    client: Any,
    dimension: str,
    rsid: str,
    output_path: Path,
    additional_segments: list[str] | None = None,
    num_pairs: int = 1,
    name_prefix: str = "CompatabilityPrefix",
) -> DimSegmentsResult:
    """Download dimension values, create one segment per value, save list JSON.

    The segment name format mirrors the legacy JS output:
    ``CompatabilityPrefix={zero_padded_index}-{rsid_clean}-{dim_clean}``

    Args:
        client: ``AdobeClient`` instance.
        dimension: Adobe variable ID (e.g. ``variables/geocountry``).
        rsid: Report suite ID used in segment definitions.
        output_path: Where to write the segment list JSON.
        additional_segments: Extra segment IDs to add to the report filter.
        num_pairs: Not used yet (reserved for cube report pairing).
        name_prefix: Prefix used in segment names (default ``CompatabilityPrefix``).

    Returns:
        :class:`DimSegmentsResult` with ``segment_list_file`` and ``segments``.
    """
    from adobe_downloader.core.request_builder import build_request
    from adobe_downloader.config.schema import ReportDefinitionInline, DateRange

    raise NotImplementedError(
        "dim_to_segments requires a ranked-report download to get dimension values. "
        "This will be fully wired in Step 12 (composite job runner)."
    )
