"""Pydantic models for all job config types."""

import re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Shared sub-models
# ---------------------------------------------------------------------------


class DateRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_date: str = Field(alias="from")
    to: str
    lookback_days: int | None = None

    @field_validator("from_date", "to")
    @classmethod
    def _validate_date_str(cls, v: str) -> str:
        if v == "today":
            return v
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError(f"Date must be YYYY-MM-DD or 'today', got: {v!r}")
        return v


class TestLimits(BaseModel):
    max_rsids: int = 3
    max_date_intervals: int = 2
    max_segments: int = 5


class PostProcessing(BaseModel):
    delete_json_after_transform: bool = False
    zip_csvs_after_concat: bool = True


class OutputConfig(BaseModel):
    # extra="allow" so unrecognized fields (e.g. a misplaced compare_list_path)
    # surface in __pydantic_extra__ instead of being silently dropped — the CLI
    # warns about them right after config load.
    model_config = ConfigDict(extra="allow")

    base_folder: str = "C:/Adobe_Downloads"
    job_name: str | None = None


class RsidSource(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: Literal["file", "list", "single", "step_output"]
    file: str | None = None
    rsid_list: list[str] | None = Field(default=None, alias="list")
    single: str | None = None
    batch_size: int = Field(default=12, ge=1)
    step_id: str | None = None
    output_key: str | None = None

    @model_validator(mode="after")
    def _check_source_value(self) -> "RsidSource":
        if self.source == "file" and not self.file:
            raise ValueError("rsids.file is required when source='file'")
        if self.source == "list" and not self.rsid_list:
            raise ValueError("rsids.list is required when source='list'")
        if self.source == "single" and not self.single:
            raise ValueError("rsids.single is required when source='single'")
        if self.source == "step_output":
            if not self.step_id:
                raise ValueError("rsids.step_id is required when source='step_output'")
            if not self.output_key:
                raise ValueError("rsids.output_key is required when source='step_output'")
        return self


class SegmentSource(BaseModel):
    source: Literal["inline", "segment_list_file", "step_output", "latest_segment_list"]
    ids: list[str] | None = None
    file: str | None = None
    step_id: str | None = None
    output_key: str | None = None

    @model_validator(mode="after")
    def _check_source_value(self) -> "SegmentSource":
        if self.source == "inline" and not self.ids:
            raise ValueError("segments.ids is required when source='inline'")
        if self.source == "segment_list_file" and not self.file:
            raise ValueError("segments.file is required when source='segment_list_file'")
        if self.source == "step_output":
            if not self.step_id:
                raise ValueError("segments.step_id is required when source='step_output'")
            if not self.output_key:
                raise ValueError("segments.output_key is required when source='step_output'")
        return self


class TransformConfig(BaseModel):
    enabled: bool = True
    type: Literal[
        "standard",
        "bot_investigation",
        "bot_rule_compare",
        "bot_validation",
        "final_bot_metrics",
        "summary_total",
    ]
    concat: bool = True
    source_pattern: str | None = None
    source_folder: str | None = None
    output_subfolder: str | None = None


class ConcatConfig(BaseModel):
    enabled: bool = True
    file_pattern: str = ".*\\.csv$"
    custom_headers: dict[int, str] | None = None
    # NOTE: not enforced on the composite-step transform_concat path — that path
    # reads this block as a raw dict via CompositeStep.extra_fields() rather than
    # through this model (see composite_job.py::_run_transform_concat_step).
    # Declared here for typing/doc parity with ReportDownloadConfig.file_name_extra.
    file_name_extra: str | None = None


class ReportDefinitionInline(BaseModel):
    name: str
    dimension: str | None = None
    row_limit: int = 500
    segments: list[str] = []
    metrics: list[str]
    csv_headers: list[str]
    # Shared reports (e.g. bot_validation's botFilterExclude/IncludeMetricsByMonth)
    # ignore whatever per-iteration segment a caller is looping over (a bot rule, a
    # segment_list_file entry) — only report_def.segments applies. This lets one real
    # download serve every iteration via the state manager's canonical-request dedup,
    # instead of downloading the same shared totals once per rule.
    shared: bool = False


class SegmentCreationConfig(BaseModel):
    input_csv: str
    share_with_users: list[str] = []
    test_mode_row: int | None = None
    compare_list_path: str | None = None
    validate_list_path: str | None = None
    segment_list_path: str | None = None

    @model_validator(mode="after")
    def _require_list_paths(self) -> "SegmentCreationConfig":
        missing = [
            name
            for name, value in (
                ("compare_list_path", self.compare_list_path),
                ("validate_list_path", self.validate_list_path),
                ("segment_list_path", self.segment_list_path),
            )
            if value is None
        ]
        if missing:
            raise ValueError(
                "segment_creation is missing required field(s): "
                + ", ".join(missing)
                + ". These belong under 'segment_creation:', not 'output:' "
                "('output:' only supports base_folder/job_name) - without them, "
                "segments are still created via the API but no local list is written."
            )
        return self


class RsidUpdateConfig(BaseModel):
    investigation_threshold: int = 1000
    validation_threshold: int = 1000
    include_virtual: bool = False
    batch_size: int = Field(default=12, ge=1)


class LookupGenerationConfig(BaseModel):
    dimension: str
    rsid: str
    segments: list[str] = []
    output_file: str | None = None


class BotRulesSource(BaseModel):
    source: Literal["step_output", "file", "inline"]
    step_id: str | None = None
    output_key: str | None = None
    file: str | None = None
    rules: list[str] | None = None


class MatrixSource(BaseModel):
    """Where a country_investigation step's RSID×country matrix comes from."""

    source: Literal["step_output", "file"]
    step_id: str | None = None
    output_key: str | None = None
    file: str | None = None

    @model_validator(mode="after")
    def _check_source_value(self) -> "MatrixSource":
        if self.source == "step_output":
            if not self.step_id:
                raise ValueError("matrix.step_id is required when source='step_output'")
            if not self.output_key:
                raise ValueError("matrix.output_key is required when source='step_output'")
        if self.source == "file" and not self.file:
            raise ValueError("matrix.file is required when source='file'")
        return self


class DimToSegmentsConfig(BaseModel):
    dimension: str
    rsid: str
    additional_segments: list[str] = []
    num_pairs: int = 1


# ---------------------------------------------------------------------------
# Per-job-type top-level models
# ---------------------------------------------------------------------------


class ReportDownloadConfig(BaseModel):
    job_type: Literal["report_download"]
    client: str
    description: str = ""
    report_ref: str | None = None
    report_group: str | None = None
    report: ReportDefinitionInline | None = None
    rsids: RsidSource
    segments: SegmentSource | None = None
    interval: Literal["full", "month", "day"] = "full"
    date_range: DateRange | None = None
    transform: TransformConfig | None = None
    test_mode: bool = False
    test_limits: TestLimits = Field(default_factory=TestLimits)
    resume: bool = True
    post_processing: PostProcessing = Field(default_factory=PostProcessing)
    output: OutputConfig
    file_name_extra: str | None = None
    include_segment_id_in_filename: bool = False
    bot_rules: BotRulesSource | None = None

    @model_validator(mode="after")
    def _check_report_spec(self) -> "ReportDownloadConfig":
        specs = [self.report_ref, self.report_group, self.report]
        if sum(s is not None for s in specs) != 1:
            raise ValueError("Exactly one of report_ref, report_group, or report must be specified")
        return self


class TransformConcatJobConfig(BaseModel):
    job_type: Literal["transform_concat"]
    client: str
    description: str = ""
    transform: TransformConfig
    concat: ConcatConfig = Field(default_factory=ConcatConfig)
    output: OutputConfig
    test_mode: bool = False


class SegmentCreationJobConfig(BaseModel):
    job_type: Literal["segment_creation"]
    client: str
    description: str = ""
    segment_creation: SegmentCreationConfig
    output: OutputConfig
    date_range: DateRange | None = None
    test_mode: bool = False


class LookupGenerationJobConfig(BaseModel):
    job_type: Literal["lookup_generation"]
    client: str
    description: str = ""
    lookup_generation: LookupGenerationConfig
    output: OutputConfig
    date_range: DateRange | None = None


class RsidUpdateJobConfig(BaseModel):
    job_type: Literal["rsid_update"]
    client: str
    description: str = ""
    rsid_update: RsidUpdateConfig = Field(default_factory=RsidUpdateConfig)
    output: OutputConfig
    date_range: DateRange | None = None


class SchemaDiscoveryJobConfig(BaseModel):
    job_type: Literal["schema_discovery"]
    client: str
    description: str = ""
    rsids: RsidSource
    mode: Literal["dimensions", "metrics", "both"] = "both"
    cache_ttl_days: int = 30
    force_refresh: bool = False


class CompositeStep(BaseModel):
    """One step in a composite job. Extra fields are allowed for step-specific config."""

    model_config = ConfigDict(extra="allow")

    step: Literal[
        "report_download",
        "transform_concat",
        "segment_creation",
        "validate_output",
        "rsid_update",
        "dim_to_segments",
        "generate_country_matrix",
        "lookup_generation",
        "bot_rule_compare",
        "final_bot_metrics",
        "country_investigation",
    ]
    id: str
    depends_on: str | None = None

    def extra_fields(self) -> dict[str, Any]:
        return self.__pydantic_extra__ or {}


class CompositeJobConfig(BaseModel):
    job_type: Literal["composite"]
    client: str
    description: str = ""
    steps: list[CompositeStep]
    date_range: DateRange | None = None
    test_mode: bool = False
    test_limits: TestLimits = Field(default_factory=TestLimits)
    output: OutputConfig | None = None

    @model_validator(mode="after")
    def _require_unique_step_ids(self) -> "CompositeJobConfig":
        # Step state (resume markers, step_outputs, depends_on lookups) is keyed
        # purely by step id — a duplicate id makes the second step silently look
        # "already complete" the moment the first one finishes, so it never runs.
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(
                    f"Duplicate step id {step.id!r} — step ids must be unique within "
                    "a composite job, since state, outputs, and depends_on are all "
                    "keyed by id"
                )
            seen.add(step.id)
        return self

    @model_validator(mode="after")
    def _require_job_name_for_transform_concat(self) -> "CompositeJobConfig":
        # report_download / bot_rule_compare only get a job-specific JSON subfolder
        # when output.job_name is set (see make_output_path / run_bot_rule_compare).
        # Without it, every such step writes into the shared per-client JSON folder,
        # so a downstream transform_concat can silently sweep up other jobs' files too.
        api_download_steps = {"report_download", "bot_rule_compare", "country_investigation"}
        step_types = {s.step for s in self.steps}
        downloads = sorted(step_types & api_download_steps)
        if downloads and "transform_concat" in step_types:
            if self.output is None or not self.output.job_name:
                raise ValueError(
                    f"steps include {', '.join(downloads)} plus transform_concat, but "
                    "output.job_name is not set. Without job_name, downloaded JSON files "
                    "land in the shared '<base_folder>/<client>/JSON/' folder instead of a "
                    "job-specific subfolder, so transform_concat can silently sweep up "
                    "every other job's files for this client. Set output.job_name to fix "
                    "this."
                )
        return self


# ---------------------------------------------------------------------------
# Cleanup job
#
# Deliberately self-contained: cleanup never touches the Adobe API, never writes
# state, and is not a valid CompositeStep. It is reachable only via the
# `adobe-downloader clean` command, so a mistyped config path in a batch script
# cannot run a cleanup where a download was intended.
# ---------------------------------------------------------------------------

# Final concatenated outputs are named <PREFIX>_<job_name>[_extra][_<split>].csv and
# written to the job folder root (see flows/composite_job.py::_TRANSFORM_TYPE_PREFIXES).
# They are the point of the whole pipeline — cleanup must never remove one.
DEFAULT_FINAL_OUTPUT_PREFIXES = (
    "INVESTIGATION",
    "VALIDATION",
    "COMPARE",
    "FINALMETRICS",
    "REPORT",
    "SUMMARY",
    "OUTPUT",
)

# When a composite job has no output.job_name, transform_concat falls back to
# "<step_id><extra>_concat.csv" written *inside* the CSV/ folder — a final output
# living among the disposable per-interval CSVs. Matched by suffix, not location.
DEFAULT_FINAL_OUTPUT_SUFFIXES = ("_concat.csv",)

JobStatusFilter = Literal["completed", "failed", "any"]


class CleanupTarget(BaseModel):
    """Which client and job folders the scan walks."""

    base_folder: str = "C:/Adobe_Downloads"
    clients: list[str] = []
    jobs: list[str] = []
    exclude_jobs: list[str] = []


class CleanupDefaults(BaseModel):
    """Global switches applying to every category."""

    dry_run: bool = True
    action: Literal["quarantine", "delete"] = "quarantine"
    quarantine_folder: str = "_trash"
    # Hard floor enforced in code, not just config: nothing younger than this is
    # ever removed, however permissive a per-category older_than_days is.
    absolute_min_age_days: int = Field(default=7, ge=0)


class CleanupProtect(BaseModel):
    """Never-delete rules. Applied before any category rule is consulted."""

    final_outputs: bool = True
    final_output_prefixes: list[str] = list(DEFAULT_FINAL_OUTPUT_PREFIXES)
    final_output_suffixes: list[str] = list(DEFAULT_FINAL_OUTPUT_SUFFIXES)
    history: bool = True
    running_jobs: bool = True
    patterns: list[str] = []


class CleanupCategory(BaseModel):
    """Base per-category rule: on/off plus a staleness threshold in days."""

    enabled: bool = True
    older_than_days: int = Field(default=30, ge=0)


class StateDbCleanup(CleanupCategory):
    """<client>/.state/<job_id>.db — the largest single files on disk."""

    require_job_status: list[JobStatusFilter] = ["completed"]
    keep_unknown: bool = True


class LogsCleanup(CleanupCategory):
    """<client>/.logs/<config-stem>.log and its .log.N rotations."""

    require_job_status: list[JobStatusFilter] = ["completed"]
    keep_unknown: bool = True
    # Rotations are superseded by the live log and carry no unique summary, so
    # they age out sooner than the primary .log file.
    rotated_older_than_days: int = Field(default=7, ge=0)


class JsonCleanup(CleanupCategory):
    """<job>/JSON/*.json raw API responses."""

    older_than_days: int = Field(default=14, ge=0)
    # transforms/base.py::make_csv_output_path is a pure path rewrite, so "was this
    # converted?" is answered exactly by the sibling CSV's existence — not a guess.
    require_csv_sibling: bool = True


class IntervalCsvCleanup(CleanupCategory):
    """<job>/CSV/*.csv per-interval transforms, 1:1 with the JSON files."""

    require_final_output: bool = True
    require_final_output_newer: bool = True


class ProcessedJsonCleanup(CleanupCategory):
    """<job>/JSON/_processed/*.json moved aside by post_process.move_json_to_processed."""

    older_than_days: int = Field(default=14, ge=0)


class ZipArchivesCleanup(CleanupCategory):
    """<job>/*.zip produced by post_processing.zip_csvs_after_concat."""

    enabled: bool = False
    older_than_days: int = Field(default=90, ge=0)


class TrashCleanup(CleanupCategory):
    """<client>/<quarantine_folder>/<timestamp>/ batches from earlier runs.

    Purging quarantine is the only path by which cleanup permanently destroys a
    file, and it only ever reaches files that appeared in a previous run's report.
    """

    older_than_days: int = Field(default=14, ge=0)


class CleanupCategories(BaseModel):
    # The YAML key is "json", but a field of that name shadows BaseModel.json —
    # same builtin-shadowing trap as RsidSource.rsid_list/alias="list", solved the
    # same way, so configs stay readable without the Pydantic warning.
    model_config = ConfigDict(populate_by_name=True)

    state_db: StateDbCleanup = Field(default_factory=StateDbCleanup)
    logs: LogsCleanup = Field(default_factory=LogsCleanup)
    json_files: JsonCleanup = Field(default_factory=JsonCleanup, alias="json")
    interval_csv: IntervalCsvCleanup = Field(default_factory=IntervalCsvCleanup)
    processed_json: ProcessedJsonCleanup = Field(default_factory=ProcessedJsonCleanup)
    zip_archives: ZipArchivesCleanup = Field(default_factory=ZipArchivesCleanup)
    trash: TrashCleanup = Field(default_factory=TrashCleanup)


class CleanupReport(BaseModel):
    console: bool = True
    write_to: str | None = ".history/cleanup"
    formats: list[Literal["markdown", "json"]] = ["markdown", "json"]
    top_n_largest_kept: int = Field(default=20, ge=0)


class CleanupJobConfig(BaseModel):
    job_type: Literal["cleanup"]
    description: str = ""
    target: CleanupTarget = Field(default_factory=CleanupTarget)
    defaults: CleanupDefaults = Field(default_factory=CleanupDefaults)
    protect: CleanupProtect = Field(default_factory=CleanupProtect)
    categories: CleanupCategories = Field(default_factory=CleanupCategories)
    report: CleanupReport = Field(default_factory=CleanupReport)

    @model_validator(mode="after")
    def _check_quarantine_folder(self) -> "CleanupJobConfig":
        folder = self.defaults.quarantine_folder.strip()
        if not folder:
            raise ValueError("defaults.quarantine_folder must not be empty")
        if Path(folder).is_absolute() or len(Path(folder).parts) != 1:
            raise ValueError(
                "defaults.quarantine_folder must be a single folder name relative to the "
                f"client folder (e.g. '_trash'), got: {folder!r}"
            )
        return self


# ---------------------------------------------------------------------------
# Discriminated union — the public type for a loaded config
# ---------------------------------------------------------------------------

JobConfig = Annotated[
    ReportDownloadConfig
    | TransformConcatJobConfig
    | SegmentCreationJobConfig
    | LookupGenerationJobConfig
    | RsidUpdateJobConfig
    | SchemaDiscoveryJobConfig
    | CompositeJobConfig
    | CleanupJobConfig,
    Field(discriminator="job_type"),
]
