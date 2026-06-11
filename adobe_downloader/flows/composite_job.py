"""Composite job runner — executes a sequence of steps with inter-step output references."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable

from adobe_downloader.config.schema import (
    CompositeJobConfig,
    CompositeStep,
    DateRange,
    RsidSource,
    SegmentSource,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_composite_job(
    job: CompositeJobConfig,
    config_path: Path,
    sm: Any,  # StateManager
    ac: Any,  # AdobeClient
    no_resume: bool = False,
    on_progress: Callable[[str, str], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Execute all steps in *job* sequentially.

    Returns a mapping of step_id -> outputs dict for every executed step.
    Completed steps are skipped on resume (outputs reloaded from step_state).

    on_progress(step_id, message) is called at key moments for CLI display.
    """
    step_outputs: dict[str, dict[str, Any]] = {}

    sm.mark_job_started()

    try:
        for step in job.steps:
            step_id = step.id

            # Honour depends_on: if the dependency failed or was never run, stop.
            if step.depends_on:
                dep_id = step.depends_on
                if dep_id not in step_outputs:
                    # Try to reload from DB (e.g. dep completed in a prior run)
                    dep_out = sm.get_step_outputs(dep_id)
                    if dep_out is not None:
                        step_outputs[dep_id] = dep_out
                    else:
                        raise RuntimeError(
                            f"Step {step_id!r} depends_on {dep_id!r} "
                            "which has not completed successfully"
                        )

            # Resume: skip already-completed steps
            if not no_resume and sm.is_step_complete(step_id):
                stored = sm.get_step_outputs(step_id)
                if stored is not None:
                    step_outputs[step_id] = stored
                _log.info("SKIP step %s (already done)", step_id)
                if on_progress:
                    on_progress(step_id, f"SKIP (already completed)")
                continue

            _log.info("START step %s [%s]", step_id, step.step)
            if on_progress:
                on_progress(step_id, f"starting ({step.step})")
            sm.mark_step_started(step_id)

            try:
                outputs = await _dispatch_step(
                    step=step,
                    job=job,
                    step_outputs=step_outputs,
                    sm=sm,
                    ac=ac,
                    no_resume=no_resume,
                    on_progress=on_progress,
                )
            except Exception as exc:
                sm.mark_step_failed(step_id, str(exc))
                _log.error("FAIL step %s: %s", step_id, exc)
                raise

            sm.mark_step_complete(step_id, outputs)
            step_outputs[step_id] = outputs
            _log.info("DONE step %s", step_id)
            if on_progress:
                on_progress(step_id, "completed")

    except Exception:
        sm.mark_job_failed("step failure")
        raise

    sm.mark_job_completed()
    return step_outputs


# ---------------------------------------------------------------------------
# Step dispatcher
# ---------------------------------------------------------------------------


async def _dispatch_step(
    step: CompositeStep,
    job: CompositeJobConfig,
    step_outputs: dict[str, dict[str, Any]],
    sm: Any,
    ac: Any,
    no_resume: bool,
    on_progress: Callable[[str, str], None] | None,
) -> dict[str, Any]:
    step_type = step.step

    if step_type == "report_download":
        return await _run_report_download_step(step, job, step_outputs, sm, ac, no_resume)
    if step_type == "segment_creation":
        return await _run_segment_creation_step(step, job, step_outputs, sm, ac)
    if step_type == "transform_concat":
        return await _run_transform_concat_step(step, job, step_outputs)
    if step_type == "validate_output":
        return await _run_validate_output_step(step, job, step_outputs, sm, ac, no_resume)
    if step_type == "lookup_generation":
        return await _run_lookup_generation_step(step, job, step_outputs, ac)
    if step_type == "dim_to_segments":
        return await _run_dim_to_segments_step(step, job, step_outputs, ac)
    if step_type == "bot_rule_compare":
        return await _run_bot_rule_compare_step(step, job, step_outputs, sm, ac, no_resume)
    if step_type == "final_bot_metrics":
        return await _run_final_bot_metrics_step(step, job, step_outputs, sm, ac, no_resume)
    if step_type == "rsid_update":
        return await _run_rsid_update_step(step, job, step_outputs, ac)
    if step_type == "generate_country_matrix":
        raise NotImplementedError(
            "generate_country_matrix step type is not yet implemented"
        )
    raise ValueError(f"Unknown step type: {step_type!r}")


# ---------------------------------------------------------------------------
# Step handlers
# ---------------------------------------------------------------------------


async def _run_report_download_step(
    step: CompositeStep,
    job: CompositeJobConfig,
    step_outputs: dict[str, dict[str, Any]],
    sm: Any,
    ac: Any,
    no_resume: bool,
) -> dict[str, Any]:
    from adobe_downloader.config.report_definitions import load_report_group, load_report_registry
    from adobe_downloader.flows.report_download import run_report_download

    extra = step.extra_fields()
    client_name = job.client

    # Resolve date_range: step override > job level
    date_range = _coerce_date_range(extra.get("date_range") or job.date_range)
    if date_range is None:
        raise ValueError(f"Step {step.id!r}: date_range is required for report_download")

    interval: str = extra.get("interval", "full")
    file_name_extra: str | None = extra.get("file_name_extra")

    # Resolve output base folder
    output_base = _resolve_output_base(extra, job)

    # Resolve rsids
    rsids_raw = extra.get("rsids")
    if rsids_raw is None:
        raise ValueError(f"Step {step.id!r}: rsids is required for report_download")
    rsids = RsidSource.model_validate(rsids_raw)

    # Resolve segments (handle step_output references)
    segments = _resolve_segments(extra.get("segments"), step_outputs)

    # Resolve report definitions
    report_defs = _resolve_report_defs(extra)

    from adobe_downloader.flows.preflight import validate_report_metrics
    from adobe_downloader.flows.report_download import iterate_rsids

    rsid_list = list(iterate_rsids(rsids))
    await validate_report_metrics(ac, rsid_list, report_defs, date_range)

    def _progress(status: str, rsid: str, name: str) -> None:
        _log.info("  %s %s / %s", status, rsid, name)

    result = await run_report_download(
        client=ac,
        client_name=client_name,
        report_defs=report_defs,
        rsids=rsids,
        date_range=date_range,
        interval=interval,
        output_base=output_base,
        sm=sm,
        segments=segments,
        file_name_extra=file_name_extra,
        no_resume=no_resume,
        step_id=step.id,
        test_limits=job.test_limits if job.test_mode else None,
        on_progress=_progress,
        job_name=job.output.job_name if job.output else None,
    )

    if result.failed:
        raise RuntimeError(
            f"Step {step.id!r}: {result.failed} download(s) failed — "
            + "; ".join(result.errors[:3])
        )

    return {
        "job_id": result.job_id,
        "json_folder": str(result.json_folder),
        "downloaded": result.downloaded,
        "skipped": result.skipped,
        "copied": result.copied,
    }


async def _run_segment_creation_step(
    step: CompositeStep,
    job: CompositeJobConfig,
    step_outputs: dict[str, dict[str, Any]],
    sm: Any,
    ac: Any,
) -> dict[str, Any]:
    from adobe_downloader.flows.segment_creation import run_segment_creation
    from adobe_downloader.utils.rsid_lookup import find_latest_rsid_file

    extra = step.extra_fields()
    sc_raw = extra.get("segment_creation") or {}

    input_csv = Path(sc_raw["input_csv"])
    share_with_users: list[str] = sc_raw.get("share_with_users", [])
    test_mode_row: int | None = sc_raw.get("test_mode_row")
    compare_list_path = Path(sc_raw["compare_list_path"]) if sc_raw.get("compare_list_path") else None
    validate_list_path = Path(sc_raw["validate_list_path"]) if sc_raw.get("validate_list_path") else None
    segment_list_path = Path(sc_raw["segment_list_path"]) if sc_raw.get("segment_list_path") else None

    data_root = Path("data")
    lookup_base = data_root / "lookups"
    rsid_file = find_latest_rsid_file(data_root / "report_suite_lists")
    if rsid_file is None:
        raise FileNotFoundError("No RSID lookup file found in data/report_suite_lists")

    result = await run_segment_creation(
        client=ac,
        input_csv=input_csv,
        share_with_users=share_with_users,
        compare_list_path=compare_list_path,
        validate_list_path=validate_list_path,
        segment_list_path=segment_list_path,
        lookup_base=lookup_base,
        rsid_lookup_file=rsid_file,
        test_mode_row=test_mode_row,
    )

    if result.error_count:
        raise RuntimeError(
            f"Step {step.id!r}: {result.error_count} segment creation error(s) — "
            + "; ".join(result.errors[:3])
        )

    return {
        "segment_list_file": str(result.segment_list_file) if result.segment_list_file else None,
        "compare_list_file": str(result.compare_list_file) if result.compare_list_file else None,
        "validate_list_file": str(result.validate_list_file) if result.validate_list_file else None,
        "created_count": result.created_count,
    }


async def _run_transform_concat_step(
    step: CompositeStep,
    job: CompositeJobConfig,
    step_outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    from adobe_downloader.transforms.base import make_csv_output_path, transform_report
    from adobe_downloader.transforms.concatenate import concatenate_csvs
    from adobe_downloader.transforms.specialized import transform_report_dispatch

    extra = step.extra_fields()
    transform_raw = extra.get("transform") or {}
    concat_raw = extra.get("concat") or {}

    explicit_type: str | None = transform_raw.get("type")
    source_pattern: str | None = transform_raw.get("source_pattern")
    concat_enabled: bool = concat_raw.get("enabled", True)

    # Resolve source folder from explicit config or previous step outputs
    source_folder_str: str | None = transform_raw.get("source_folder")
    if source_folder_str is None:
        # Auto-detect: use json_folder from depends_on or most recent report_download step
        dep_id = step.depends_on
        if dep_id and dep_id in step_outputs:
            source_folder_str = step_outputs[dep_id].get("json_folder")
        if source_folder_str is None:
            # Walk step_outputs in reverse to find latest report_download result
            for out in reversed(list(step_outputs.values())):
                if "json_folder" in out:
                    source_folder_str = out["json_folder"]
                    break

    if source_folder_str is None:
        raise ValueError(f"Step {step.id!r}: could not determine source folder for transform_concat")

    source_folder = Path(source_folder_str)
    if not source_folder.exists():
        raise FileNotFoundError(f"Step {step.id!r}: source folder not found: {source_folder}")

    glob_pattern = source_pattern or "*.json"
    # If source_pattern is a regex, convert to glob via '*' fallback
    if source_pattern and any(c in source_pattern for c in r"()[]?+^$"):
        json_files = [f for f in source_folder.iterdir() if re.search(source_pattern, f.name)]
    else:
        json_files = sorted(source_folder.glob(glob_pattern))

    if not json_files:
        _log.warning("Step %s: no JSON files matched in %s", step.id, source_folder)
        return {"csv_folder": str(source_folder.parent / "CSV"), "concatenated_file": None}

    ok = failed = 0
    csv_paths = []
    for jf in json_files:
        csv_path = make_csv_output_path(jf)
        try:
            transform_report_dispatch(jf, explicit_type, output_path=csv_path)
            csv_paths.append(csv_path)
            ok += 1
        except Exception as exc:
            _log.error("Step %s: FAIL transform %s: %s", step.id, jf.name, exc)
            failed += 1

    _log.info("Step %s: transformed %d/%d JSON files", step.id, ok, ok + failed)

    csv_folder = csv_paths[0].parent if csv_paths else source_folder.parent / "CSV"
    concatenated_file: str | None = None

    if concat_enabled and csv_paths:
        file_pattern = concat_raw.get("file_pattern", "*.csv")
        job_name = job.output.job_name if job.output else None
        if job_name:
            final_folder = Path(job.output.base_folder) / job.client / "BotRuleCompareFinal"
            final_folder.mkdir(parents=True, exist_ok=True)
            concat_out = final_folder / f"BOTCOMPARE_{job_name}.csv"
        else:
            concat_out = csv_folder / f"{step.id}_concat.csv"
        count = concatenate_csvs(csv_folder, file_pattern, concat_out)
        if count:
            _log.info("Step %s: concatenated %d CSVs -> %s", step.id, count, concat_out)
            concatenated_file = str(concat_out)

    return {
        "csv_folder": str(csv_folder),
        "concatenated_file": concatenated_file,
        "ok": ok,
        "failed": failed,
    }


async def _run_validate_output_step(
    step: CompositeStep,
    job: CompositeJobConfig,
    step_outputs: dict[str, dict[str, Any]],
    sm: Any,
    ac: Any,
    no_resume: bool,
) -> dict[str, Any]:
    """Check all expected output files from a prior download step.

    Supports both report_download and bot_rule_compare config_refs.
    For report_download steps, retry=True resets stale DB rows and re-downloads.
    For bot_rule_compare steps, retry=True logs a warning (retry not supported).
    """
    from adobe_downloader.flows.report_download import run_report_download
    from adobe_downloader.flows.validation import (
        check_output_files,
        enumerate_bot_rule_compare_paths,
        enumerate_expected_paths,
    )

    extra = step.extra_fields()
    config_ref: str | None = extra.get("config_ref")
    retry: bool = extra.get("retry", False)

    if config_ref is None:
        raise ValueError(f"Step {step.id!r}: config_ref is required for validate_output")

    ref_step = next((s for s in job.steps if s.id == config_ref), None)
    if ref_step is None:
        raise ValueError(
            f"Step {step.id!r}: config_ref {config_ref!r} does not match any step id"
        )

    ref_extra = ref_step.extra_fields()

    date_range = _coerce_date_range(ref_extra.get("date_range") or job.date_range)
    if date_range is None:
        raise ValueError(f"Step {step.id!r}: date_range required for validation enumeration")

    output_base = Path(_resolve_output_base(ref_extra, job))

    # --- bot_rule_compare: enumerate Segment + AllTraffic pairs ---
    if ref_step.step == "bot_rule_compare":
        from adobe_downloader.config.report_definitions import load_report_group
        from adobe_downloader.flows.report_download import iterate_rsids

        rsids_raw = ref_extra.get("rsids")
        if rsids_raw is None:
            raise ValueError(f"Step {step.id!r}: rsids required on referenced step {config_ref!r}")
        rsid_clean_names = list(iterate_rsids(RsidSource.model_validate(rsids_raw)))

        comparison_round = float(ref_extra.get("comparison_round", 1.0))
        bot_rules = _parse_bot_rules_from_config(
            ref_extra.get("bot_rules") or {}, step_outputs, step.id
        )
        report_defs = load_report_group("bot_rule_compare")

        expected = enumerate_bot_rule_compare_paths(
            client_name=job.client,
            rsid_clean_names=rsid_clean_names,
            bot_rules=bot_rules,
            date_range=date_range,
            comparison_round=comparison_round,
            output_base=output_base,
            report_defs=report_defs,
            job_name=job.output.job_name if job.output else None,
        )

        valid, missing = check_output_files(expected)
        missing_count = len(missing)
        _log.info(
            "Step %s: %d expected, %d valid, %d missing/empty",
            step.id, len(expected), len(valid), missing_count,
        )
        for p in missing[:5]:
            _log.warning("  missing: %s", p)
        if missing_count and retry:
            _log.warning(
                "Step %s: retry=True is not supported for bot_rule_compare steps — "
                "re-run the download step manually to recover missing files",
                step.id,
            )
        return {"missing_count": missing_count}

    # --- report_download: standard enumeration with optional retry ---
    interval: str = ref_extra.get("interval", "full")
    file_name_extra: str | None = ref_extra.get("file_name_extra")

    rsids_raw = ref_extra.get("rsids")
    if rsids_raw is None:
        raise ValueError(f"Step {step.id!r}: rsids required on referenced step {config_ref!r}")
    rsids = RsidSource.model_validate(rsids_raw)

    segments = _resolve_segments(ref_extra.get("segments"), step_outputs)
    report_defs = _resolve_report_defs(ref_extra)

    expected = enumerate_expected_paths(
        client_name=job.client,
        report_defs=report_defs,
        rsids=rsids,
        date_range=date_range,
        interval=interval,
        output_base=output_base,
        segments=segments,
        file_name_extra=file_name_extra,
        job_name=job.output.job_name if job.output else None,
    )

    valid, missing = check_output_files(expected)
    missing_count = len(missing)

    _log.info(
        "Step %s: %d expected, %d valid, %d missing/empty",
        step.id, len(expected), len(valid), missing_count,
    )
    for p in missing[:5]:
        _log.warning("  missing: %s", p)

    if missing_count and retry:
        _log.info("Step %s: retry=True — resetting and re-downloading %d file(s)", step.id, missing_count)
        for p in missing:
            sm.reset_completed_for_path(p)
        sm.reset_incomplete_for_step(config_ref)

        def _progress(status: str, rsid: str, name: str) -> None:
            _log.info("  %s %s / %s", status, rsid, name)

        result = await run_report_download(
            client=ac,
            client_name=job.client,
            report_defs=report_defs,
            rsids=rsids,
            date_range=date_range,
            interval=interval,
            output_base=output_base,
            sm=sm,
            segments=segments,
            file_name_extra=file_name_extra,
            no_resume=False,
            step_id=config_ref,
            test_limits=job.test_limits if job.test_mode else None,
            on_progress=_progress,
        )

        if result.failed:
            raise RuntimeError(
                f"Step {step.id!r}: {result.failed} file(s) still failed after retry — "
                + "; ".join(result.errors[:3])
            )

        valid, missing = check_output_files(expected)
        missing_count = len(missing)

    return {"missing_count": missing_count}


async def _run_lookup_generation_step(
    step: CompositeStep,
    job: CompositeJobConfig,
    step_outputs: dict[str, dict[str, Any]],
    ac: Any,
) -> dict[str, Any]:
    from adobe_downloader.config.schema import LookupGenerationConfig
    from adobe_downloader.flows.lookup_generation import run_lookup_generation

    extra = step.extra_fields()
    lg_raw = extra.get("lookup_generation") or {}
    lg = LookupGenerationConfig.model_validate(lg_raw)

    date_range = _coerce_date_range(extra.get("date_range") or job.date_range)
    if date_range is None:
        raise ValueError(f"Step {step.id!r}: date_range is required for lookup_generation")

    data_root = Path("data")
    lookup_base = data_root / "lookups"

    dest = await run_lookup_generation(
        client=ac,
        client_name=job.client,
        config=lg,
        date_range=date_range,
        lookup_base=lookup_base,
    )

    return {"lookup_file": str(dest)}


async def _run_dim_to_segments_step(
    step: CompositeStep,
    job: CompositeJobConfig,
    step_outputs: dict[str, dict[str, Any]],
    ac: Any,
) -> dict[str, Any]:
    from adobe_downloader.segments.dim_to_segments import dim_to_segments

    extra = step.extra_fields()
    d2s_raw = extra.get("dim_to_segments") or {}

    output_base = _resolve_output_base(extra, job)
    segment_list_path = Path(output_base) / job.client / "segments" / f"{step.id}_segments.json"
    segment_list_path.parent.mkdir(parents=True, exist_ok=True)

    if job.date_range is None:
        raise ValueError("dim_to_segments step requires a date_range on the composite job")

    result = await dim_to_segments(
        client=ac,
        dimension=d2s_raw["dimension"],
        rsid=d2s_raw["rsid"],
        date_range=job.date_range,
        output_path=segment_list_path,
        additional_segments=d2s_raw.get("additional_segments"),
        num_pairs=d2s_raw.get("num_pairs", 1),
    )

    return {"segment_list_file": str(result.segment_list_file)}


async def _run_bot_rule_compare_step(
    step: CompositeStep,
    job: CompositeJobConfig,
    step_outputs: dict[str, dict[str, Any]],
    sm: Any,
    ac: Any,
    no_resume: bool,
) -> dict[str, Any]:
    from adobe_downloader.flows.bot_rule_compare import run_bot_rule_compare
    from adobe_downloader.utils.rsid_lookup import find_latest_rsid_file

    extra = step.extra_fields()

    date_range = _coerce_date_range(extra.get("date_range") or job.date_range)
    if date_range is None:
        raise ValueError(f"Step {step.id!r}: date_range is required for bot_rule_compare")

    output_base = _resolve_output_base(extra, job)
    comparison_round: float = float(extra.get("comparison_round", 1.0))

    rsids_raw = extra.get("rsids")
    if rsids_raw is None:
        raise ValueError(f"Step {step.id!r}: rsids is required for bot_rule_compare")
    rsids = RsidSource.model_validate(rsids_raw)

    from adobe_downloader.flows.report_download import iterate_rsids
    rsid_clean_names = list(iterate_rsids(rsids))

    rsid_lookup_raw: str | None = extra.get("rsid_lookup_file")
    if rsid_lookup_raw:
        rsid_lookup_file = Path(rsid_lookup_raw)
    else:
        data_root = Path("data")
        rsid_lookup_file = find_latest_rsid_file(data_root / "report_suite_lists")
        if rsid_lookup_file is None:
            raise FileNotFoundError("No RSID lookup file found in data/report_suite_lists")

    bot_rules = _parse_bot_rules_from_config(extra.get("bot_rules") or {}, step_outputs, step.id)

    result = await run_bot_rule_compare(
        client=ac,
        client_name=job.client,
        rsid_clean_names=rsid_clean_names,
        rsid_lookup_file=rsid_lookup_file,
        bot_rules=bot_rules,
        date_range=date_range,
        comparison_round=comparison_round,
        output_base=output_base,
        sm=sm,
        no_resume=no_resume,
        step_id=step.id,
        test_limits=job.test_limits if job.test_mode else None,
        job_name=job.output.job_name if job.output else None,
    )

    if result.failed:
        raise RuntimeError(
            f"Step {step.id!r}: {result.failed} download(s) failed — "
            + "; ".join(result.errors[:3])
        )

    return {
        "job_id": result.job_id,
        "json_folder": str(result.json_folder),
        "downloaded": result.downloaded,
        "skipped": result.skipped,
        "copied": result.copied,
    }


async def _run_final_bot_metrics_step(
    step: CompositeStep,
    job: CompositeJobConfig,
    step_outputs: dict[str, dict[str, Any]],
    sm: Any,
    ac: Any,
    no_resume: bool,
) -> dict[str, Any]:
    from adobe_downloader.flows.final_bot_metrics import run_final_bot_metrics
    from adobe_downloader.utils.rsid_lookup import find_latest_rsid_file

    extra = step.extra_fields()

    date_range = _coerce_date_range(extra.get("date_range") or job.date_range)
    if date_range is None:
        raise ValueError(f"Step {step.id!r}: date_range is required for final_bot_metrics")

    output_base = _resolve_output_base(extra, job)
    interval: str = extra.get("interval", "full")
    job_name: str = extra.get("job_name", step.id)

    rsids_raw = extra.get("rsids")
    if rsids_raw is None:
        raise ValueError(f"Step {step.id!r}: rsids is required for final_bot_metrics")
    rsids = RsidSource.model_validate(rsids_raw)

    # Resolve segment list file (literal path or step_output reference)
    seg_file_raw: str | None = extra.get("segment_list_file")
    if seg_file_raw is None:
        seg_src = extra.get("segment_list")
        if seg_src and seg_src.get("source") == "step_output":
            dep_id = seg_src["step_id"]
            key = seg_src.get("output_key", "segment_list_file")
            if dep_id not in step_outputs:
                raise ValueError(
                    f"Step {step.id!r}: segment_list references step {dep_id!r} "
                    "which has not completed"
                )
            seg_file_raw = step_outputs[dep_id][key]
        else:
            raise ValueError(f"Step {step.id!r}: segment_list_file is required for final_bot_metrics")
    segment_list_file = Path(seg_file_raw)

    rsid_lookup_raw: str | None = extra.get("rsid_lookup_file")
    if rsid_lookup_raw:
        rsid_lookup_file = Path(rsid_lookup_raw)
    else:
        data_root = Path("data")
        rsid_lookup_file = find_latest_rsid_file(data_root / "report_suite_lists")
        if rsid_lookup_file is None:
            raise FileNotFoundError("No RSID lookup file found in data/report_suite_lists")

    result = await run_final_bot_metrics(
        client=ac,
        client_name=job.client,
        rsids=rsids,
        rsid_lookup_file=rsid_lookup_file,
        segment_list_file=segment_list_file,
        job_name=job_name,
        date_range=date_range,
        interval=interval,
        output_base=output_base,
        sm=sm,
        no_resume=no_resume,
        step_id=step.id,
        test_limits=job.test_limits if job.test_mode else None,
    )

    if result.failed:
        raise RuntimeError(
            f"Step {step.id!r}: {result.failed} download(s) failed — "
            + "; ".join(result.errors[:3])
        )

    return {
        "job_id": result.job_id,
        "json_folder": str(result.json_folder),
        "downloaded": result.downloaded,
        "skipped": result.skipped,
    }


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def _resolve_segments(
    segments_raw: dict[str, Any] | None,
    step_outputs: dict[str, dict[str, Any]],
) -> SegmentSource | None:
    """Return a resolved SegmentSource, substituting step_output references."""
    if segments_raw is None:
        return None

    source = segments_raw.get("source")

    if source == "step_output":
        dep_step_id = segments_raw["step_id"]
        output_key = segments_raw["output_key"]
        if dep_step_id not in step_outputs:
            raise ValueError(
                f"segments.step_output references {dep_step_id!r} "
                "which has not yet produced outputs"
            )
        resolved_path = step_outputs[dep_step_id].get(output_key)
        if not resolved_path:
            raise ValueError(
                f"segments.step_output: key {output_key!r} not found "
                f"in outputs of step {dep_step_id!r}"
            )
        return SegmentSource(source="segment_list_file", file=str(resolved_path))

    return SegmentSource.model_validate(segments_raw)


def _resolve_report_defs(extra: dict[str, Any]) -> list[Any]:
    """Return report definitions from report_group, report_ref, or inline report."""
    from adobe_downloader.config.report_definitions import load_report_group, load_report_registry
    from adobe_downloader.config.schema import ReportDefinitionInline

    if "report_group" in extra:
        return load_report_group(extra["report_group"])
    if "report_ref" in extra:
        registry = load_report_registry()
        key = extra["report_ref"]
        if key not in registry:
            raise KeyError(f"report_ref {key!r} not found in report_definitions/")
        return [registry[key]]
    if "report" in extra:
        return [ReportDefinitionInline.model_validate(extra["report"])]
    raise ValueError("Step requires one of report_group, report_ref, or report")


async def _run_rsid_update_step(
    step: CompositeStep,
    job: CompositeJobConfig,
    step_outputs: dict[str, dict[str, Any]],
    ac: Any,
) -> dict[str, Any]:
    from adobe_downloader.config.schema import RsidUpdateConfig
    from adobe_downloader.flows.rsid_update import run_rsid_update

    extra = step.extra_fields()
    ru_raw = extra.get("rsid_update") or {}

    date_range = _coerce_date_range(extra.get("date_range") or job.date_range)
    if date_range is None:
        raise ValueError(f"Step {step.id!r}: date_range is required for rsid_update")

    rsid_update_cfg = RsidUpdateConfig.model_validate(ru_raw) if ru_raw else RsidUpdateConfig()
    output_base = extra.get("output", {}).get("base_folder", "data/rsid_lists")
    suite_pairs_dir = extra.get("suite_pairs_dir", "data/report_suite_lists")
    exclusion_file_raw = extra.get("exclusion_file", "data/rsid_lists/excludedRsidCleanNames.txt")
    exclusion_file = Path(exclusion_file_raw) if exclusion_file_raw else None

    result = await run_rsid_update(
        client=ac,
        rsid_update_cfg=rsid_update_cfg,
        date_range=date_range,
        output_base=output_base,
        exclusion_file=exclusion_file if exclusion_file and exclusion_file.exists() else None,
        suite_pairs_dir=suite_pairs_dir,
    )

    return {
        "investigation_list": str(result.investigation_list),
        "validation_list": str(result.validation_list),
    }


def _parse_bot_rules_from_config(
    bot_rules_raw: dict[str, Any],
    step_outputs: dict[str, dict[str, Any]],
    step_id: str,
) -> list[Any]:  # list[BotRule]
    """Parse a bot_rules config dict into a list of BotRule objects."""
    from adobe_downloader.flows.bot_rule_compare import DIMENSION_MAPPING, BotRule, parse_bot_rule_csv

    source: str = bot_rules_raw.get("source", "file")

    if source == "file":
        return parse_bot_rule_csv(Path(bot_rules_raw["file"]))
    if source == "step_output":
        dep_step_id = bot_rules_raw["step_id"]
        output_key = bot_rules_raw["output_key"]
        if dep_step_id not in step_outputs:
            raise ValueError(
                f"Step {step_id!r}: bot_rules.step_output references {dep_step_id!r} "
                "which has not yet produced outputs"
            )
        return parse_bot_rule_csv(Path(step_outputs[dep_step_id][output_key]))
    if source == "inline":
        raw_rules: list[dict[str, Any]] = bot_rules_raw.get("rules", [])
        bot_rules = []
        for r in raw_rules:
            short = r.get("report_to_skip", "")
            full = DIMENSION_MAPPING.get(
                short,
                short if short.startswith("botInvestigation") else f"botInvestigationMetricsBy{short}",
            )
            bot_rules.append(BotRule(
                segment_id=r["segment_id"],
                segment_name=r["segment_name"],
                report_to_skip=full,
            ))
        return bot_rules
    raise ValueError(f"Step {step_id!r}: unknown bot_rules.source {source!r}")


def _resolve_output_base(extra: dict[str, Any], job: CompositeJobConfig) -> str:
    """Return the output base folder: step-level override or composite job default."""
    if "output" in extra:
        out = extra["output"]
        if isinstance(out, dict):
            return out.get("base_folder", "")
        return str(out)
    if job.output:
        return job.output.base_folder
    raise ValueError("No output.base_folder configured on the composite job or step")


def _coerce_date_range(raw: Any) -> DateRange | None:
    """Accept a DateRange instance or a raw dict and return a DateRange."""
    if raw is None:
        return None
    if isinstance(raw, DateRange):
        return raw
    return DateRange.model_validate(raw)
