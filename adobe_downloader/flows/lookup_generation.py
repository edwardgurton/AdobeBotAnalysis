"""Top-level flow for lookup_generation job type."""

import logging
from pathlib import Path

from adobe_downloader.config.schema import DateRange, LookupGenerationConfig
from adobe_downloader.core.api_client import AdobeClient
from adobe_downloader.segments.lookup_generator import generate_lookup_file

_log = logging.getLogger(__name__)


async def run_lookup_generation(
    client: AdobeClient,
    client_name: str,
    config: LookupGenerationConfig,
    date_range: DateRange,
    lookup_base: Path,
) -> Path:
    """Run the lookup_generation job: download all dimension values and write lookup file.

    Returns the path to the generated lookup file.
    """
    output_path = Path(config.output_file) if config.output_file else None
    return await generate_lookup_file(
        client=client,
        client_name=client_name,
        dimension=config.dimension,
        rsid=config.rsid,
        date_range=date_range,
        segments=config.segments,
        lookup_base=lookup_base,
        output_path=output_path,
    )
