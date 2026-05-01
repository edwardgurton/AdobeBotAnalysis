"""Build Adobe Analytics ranked-report request bodies."""

from typing import Any

from adobe_downloader.config.schema import DateRange, ReportDefinitionInline


def build_request(
    report_def: ReportDefinitionInline,
    date_range: DateRange,
    rsid: str,
    segments: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble a ranked-report request body.

    report_def.segments — base segments always applied (e.g. Master Bot Filter).
    segments — runtime extra segments (e.g. a specific bot rule being tested).
    """
    global_filters: list[dict[str, Any]] = [
        {
            "type": "dateRange",
            "dateRange": (
                f"{date_range.from_date}T00:00:00.000"
                f"/{date_range.to}T00:00:00.000"
            ),
        }
    ]
    for seg_id in report_def.segments:
        global_filters.append({"type": "segment", "segmentId": seg_id})
    for seg_id in (segments or []):
        global_filters.append({"type": "segment", "segmentId": seg_id})

    metrics: list[dict[str, Any]] = [
        {"columnId": "0", "id": "metrics/visitors", "sort": "desc"},
        {"columnId": "1", "id": "metrics/visits", "sort": "desc"},
    ]
    for i, metric_id in enumerate(report_def.metrics):
        metrics.append({"columnId": str(i + 2), "id": metric_id})

    body: dict[str, Any] = {
        "rsid": rsid,
        "globalFilters": global_filters,
        "metricContainer": {"metrics": metrics},
    }
    if report_def.dimension is not None:
        body["dimension"] = report_def.dimension
    body["settings"] = {
        "countRepeatInstances": True,
        "includeAnnotations": True,
        "page": 0,
        "nonesBehavior": "return-nones",
        "limit": report_def.row_limit,
    }
    return body
