"""Pre-flight validation — check job config against the live Adobe Analytics API."""

from __future__ import annotations

import logging
from typing import Any

from adobe_downloader.config.schema import DateRange
from adobe_downloader.core.api_client import AdobeClient

_log = logging.getLogger(__name__)


async def validate_report_metrics(
    client: AdobeClient,
    rsids: list[str],
    report_defs: list[Any],
    date_range: DateRange,
) -> None:
    """Raise ValueError if any metric in report_defs produces a column error.

    Makes one probe report request per RSID (1 row, 1 day). Column errors in the
    response indicate metrics that are inaccessible or invalid for that RSID.
    Collects all problems before raising so the caller sees the full picture.
    """
    requested = _unique_metrics(report_defs)
    if not requested:
        return

    col_to_metric: dict[str, str] = {str(i): mid for i, mid in enumerate(requested)}

    problems: list[str] = []
    for rsid in rsids:
        _log.info("Pre-flight: probing %d metric(s) against %s", len(requested), rsid)
        body = _build_probe_request(rsid, requested, date_range)
        response = await client.get_report(body)
        column_errors = response.get("columns", {}).get("columnErrors", [])
        bad_metrics = sorted(
            col_to_metric[e["columnId"]]
            for e in column_errors
            if e["columnId"] in col_to_metric
        )
        if bad_metrics:
            problems.append(f"  {rsid}: {', '.join(bad_metrics)}")

    if problems:
        raise ValueError(
            "Pre-flight metric validation failed — "
            "the following metrics are not accessible for their target RSIDs:\n"
            + "\n".join(problems)
        )


def _unique_metrics(report_defs: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for rd in report_defs:
        for mid in rd.metrics:
            if mid not in seen:
                seen.add(mid)
                result.append(mid)
    return result


def _build_probe_request(
    rsid: str,
    metric_ids: list[str],
    date_range: DateRange,
) -> dict[str, Any]:
    probe_date = date_range.from_date
    return {
        "rsid": rsid,
        "globalFilters": [
            {
                "type": "dateRange",
                "dateRange": f"{probe_date}T00:00:00.000/{probe_date}T23:59:59.000",
            }
        ],
        "metricContainer": {
            "metrics": [
                {"columnId": str(i), "id": mid}
                for i, mid in enumerate(metric_ids)
            ]
        },
        "dimension": "variables/page",
        "settings": {
            "limit": 1,
            "page": 0,
            "countRepeatInstances": True,
            "nonesBehavior": "return-nones",
        },
    }
