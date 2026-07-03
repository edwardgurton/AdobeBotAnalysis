"""Schema discovery flow — fetches dimension/metric metadata and populates the schema cache."""

from __future__ import annotations

import logging

from adobe_downloader.config.schema import SchemaDiscoveryJobConfig
from adobe_downloader.core.api_client import AdobeClient
from adobe_downloader.flows.report_download import iterate_rsids
from adobe_downloader.utils import schema_cache
from adobe_downloader.utils.rsid_lookup import resolve_rsid_names

logger = logging.getLogger(__name__)


async def run_schema_discovery(client: AdobeClient, job: SchemaDiscoveryJobConfig) -> None:
    """Iterate RSIDs, fetch stale schema entries, then rebuild the search index."""
    rsids = resolve_rsid_names(list(iterate_rsids(job.rsids)))
    ttl = job.cache_ttl_days
    force = job.force_refresh

    fetch_dims = job.mode in ("dimensions", "both")
    fetch_mets = job.mode in ("metrics", "both")

    for rsid in rsids:
        if fetch_dims and (force or schema_cache.dimensions_stale(rsid, ttl)):
            logger.info("Fetching dimensions for %s", rsid)
            dims = await client.get_dimensions(rsid)
            schema_cache.write_dimensions(rsid, dims)

        if fetch_mets and (force or schema_cache.metrics_stale(rsid, ttl)):
            logger.info("Fetching metrics for %s", rsid)
            mets = await client.get_metrics(rsid)
            schema_cache.write_metrics(rsid, mets)

    if fetch_mets and (force or schema_cache.calculated_metrics_stale(ttl)):
        logger.info("Fetching calculated metrics")
        calc = await client.get_calculated_metrics()
        schema_cache.write_calculated_metrics(calc)

    schema_cache.rebuild_index()
    logger.info("Schema discovery complete — %d RSIDs processed", len(rsids))
