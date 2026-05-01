"""Pydantic models for report_definitions/*.yaml files and registry loader."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from adobe_downloader.config.schema import ReportDefinitionInline


class ReportEntry(BaseModel):
    """Per-report config within a report_definitions YAML file."""

    dimension: str | None = None
    row_limit: int | None = None
    segments: list[str] | None = None
    metrics: list[str] | None = None
    csv_headers: list[str] | None = None


class ReportDefinitionDefaults(BaseModel):
    """Default values shared by all reports in a group file."""

    segments: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    row_limit: int = 500
    csv_headers: list[str] = Field(default_factory=list)


class ReportDefinitionFile(BaseModel):
    """Top-level schema for a report_definitions/*.yaml file."""

    group: str | None = None
    description: str = ""
    transform_type: str | None = None
    defaults: ReportDefinitionDefaults = Field(
        default_factory=ReportDefinitionDefaults
    )
    reports: dict[str, ReportEntry]

    def resolve(self, report_name: str) -> ReportDefinitionInline:
        """Merge a report entry with group defaults into a ReportDefinitionInline."""
        entry = self.reports[report_name]
        return ReportDefinitionInline(
            name=report_name,
            dimension=entry.dimension,
            row_limit=(
                entry.row_limit
                if entry.row_limit is not None
                else self.defaults.row_limit
            ),
            segments=(
                entry.segments
                if entry.segments is not None
                else self.defaults.segments
            ),
            metrics=(
                entry.metrics
                if entry.metrics is not None
                else self.defaults.metrics
            ),
            csv_headers=(
                entry.csv_headers
                if entry.csv_headers is not None
                else self.defaults.csv_headers
            ),
        )


def load_report_registry(
    report_defs_dir: Path | None = None,
) -> dict[str, ReportDefinitionInline]:
    """Scan report_definitions/*.yaml and return a flat {name → definition} registry."""
    if report_defs_dir is None:
        report_defs_dir = Path(__file__).parent.parent.parent / "report_definitions"
    registry: dict[str, ReportDefinitionInline] = {}
    for yaml_file in sorted(report_defs_dir.glob("*.yaml")):
        raw = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        rdf = ReportDefinitionFile.model_validate(raw)
        for report_name in rdf.reports:
            registry[report_name] = rdf.resolve(report_name)
    return registry


def load_report_group(
    group_name: str,
    report_defs_dir: Path | None = None,
) -> list[ReportDefinitionInline]:
    """Return all resolved definitions for a named group, in YAML declaration order."""
    if report_defs_dir is None:
        report_defs_dir = Path(__file__).parent.parent.parent / "report_definitions"
    for yaml_file in sorted(report_defs_dir.glob("*.yaml")):
        raw = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        rdf = ReportDefinitionFile.model_validate(raw)
        if rdf.group == group_name:
            return [rdf.resolve(name) for name in rdf.reports]
    raise KeyError(f"No report group {group_name!r} found in {report_defs_dir}")
