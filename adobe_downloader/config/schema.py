"""Pydantic models for all job config types."""

import re
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
    base_folder: str


class RsidSource(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: Literal["file", "list", "single"]
    file: str | None = None
    rsid_list: list[str] | None = Field(default=None, alias="list")
    single: str | None = None
    batch_size: int = 12

    @model_validator(mode="after")
    def _check_source_value(self) -> "RsidSource":
        if self.source == "file" and not self.file:
            raise ValueError("rsids.file is required when source='file'")
        if self.source == "list" and not self.rsid_list:
            raise ValueError("rsids.list is required when source='list'")
        if self.source == "single" and not self.single:
            raise ValueError("rsids.single is required when source='single'")
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


class ReportDefinitionInline(BaseModel):
    name: str
    dimension: str | None = None
    row_limit: int = 500
    segments: list[str] = []
    metrics: list[str]
    csv_headers: list[str]


class SegmentCreationConfig(BaseModel):
    input_csv: str
    share_with_users: list[str] = []
    test_mode_row: int | None = None
    compare_list_path: str | None = None
    validate_list_path: str | None = None
    segment_list_path: str | None = None


class RsidUpdateConfig(BaseModel):
    investigation_threshold: int = 1000
    validation_threshold: int = 1000
    include_virtual: bool = False


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


class OptimisationConfig(BaseModel):
    shared_reports: bool = False
    shared_report_names: list[str] = []


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
    bot_rules: BotRulesSource | None = None
    optimisation: OptimisationConfig | None = None

    @model_validator(mode="after")
    def _check_report_spec(self) -> "ReportDownloadConfig":
        specs = [self.report_ref, self.report_group, self.report]
        if sum(s is not None for s in specs) != 1:
            raise ValueError(
                "Exactly one of report_ref, report_group, or report must be specified"
            )
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
    ]
    id: str
    depends_on: str | None = None
    optimisation: OptimisationConfig | None = None

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


# ---------------------------------------------------------------------------
# Discriminated union — the public type for a loaded config
# ---------------------------------------------------------------------------

JobConfig = Annotated[
    ReportDownloadConfig
    | TransformConcatJobConfig
    | SegmentCreationJobConfig
    | LookupGenerationJobConfig
    | RsidUpdateJobConfig
    | CompositeJobConfig,
    Field(discriminator="job_type"),
]
