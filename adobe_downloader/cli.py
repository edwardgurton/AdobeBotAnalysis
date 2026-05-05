"""CLI entry point for adobe-downloader."""

import asyncio
import sys
from pathlib import Path

import click
from pydantic import ValidationError

from adobe_downloader import __version__
from adobe_downloader.config.loader import check_referenced_files, credentials_exist, load_config


@click.group()
@click.version_option(__version__, prog_name="adobe-downloader")
def main() -> None:
    """Adobe Analytics report downloader and transformer."""


@main.command()
@click.option(
    "--config",
    "-c",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the job config YAML file.",
)
@click.option(
    "--check-credentials/--no-check-credentials",
    default=True,
    help="Warn if credentials file is missing for the config's client.",
)
def validate(config: Path, check_credentials: bool) -> None:
    """Validate a config file: parse YAML, check Pydantic schema, verify referenced files."""
    click.echo(f"Validating: {config}")

    try:
        job = load_config(config)
    except ValidationError as exc:
        click.secho("Schema validation failed:", fg="red", bold=True)
        for err in exc.errors():
            loc = " -> ".join(str(x) for x in err["loc"])
            click.secho(f"  {loc}: {err['msg']}", fg="red")
        sys.exit(1)
    except Exception as exc:
        click.secho(f"Failed to load config: {exc}", fg="red", bold=True)
        sys.exit(1)

    click.secho(f"  job_type   : {job.job_type}", fg="cyan")
    click.secho(f"  client     : {job.client}", fg="cyan")
    if job.description:
        click.secho(f"  description: {job.description}", fg="cyan")

    file_errors = check_referenced_files(job, config)
    if file_errors:
        click.secho("Referenced file checks failed:", fg="yellow", bold=True)
        for err in file_errors:
            click.secho(f"  {err}", fg="yellow")

    if check_credentials and not credentials_exist(job.client):
        click.secho(
            f"  Warning: no credentials file found for client '{job.client}'",
            fg="yellow",
        )

    if file_errors:
        click.secho("Validation completed with warnings.", fg="yellow")
        sys.exit(2)

    click.secho("Validation passed.", fg="green", bold=True)


@main.command("list-users")
@click.option("--client", "-c", required=True, help="Client name (matches credentials file).")
def list_users(client: str) -> None:
    """List Adobe Analytics users for a client."""
    from adobe_downloader.core.api_client import AdobeClient

    async def _run() -> list[dict]:  # type: ignore[type-arg]
        ac = AdobeClient(client)
        try:
            return await ac.get_users()
        finally:
            await ac.close()

    try:
        users = asyncio.run(_run())
    except FileNotFoundError as exc:
        click.secho(str(exc), fg="red", bold=True)
        sys.exit(1)
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", bold=True)
        sys.exit(1)

    click.echo(f"Found {len(users)} user(s):")
    for user in users:
        login = user.get("login", "")
        first = user.get("firstName", "")
        last = user.get("lastName", "")
        click.echo(f"  {login}  {first} {last}".rstrip())


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True, path_type=Path))
@click.option(
    "--report",
    "-r",
    default=None,
    help="Download only this named report (overrides report_group multi-report expansion).",
)
@click.option(
    "--no-resume",
    is_flag=True,
    default=False,
    help="Ignore existing state and re-download everything.",
)
@click.option(
    "--test",
    "test_mode",
    is_flag=True,
    default=False,
    help="Run in test mode: cap RSIDs, date intervals, and segments per test_limits config.",
)
def run(config: Path, report: str | None, no_resume: bool, test_mode: bool) -> None:
    """Execute a job: report_download, segment_creation, lookup_generation, or composite."""
    from adobe_downloader.config.loader import load_config
    from adobe_downloader.config.report_definitions import load_report_group, load_report_registry
    from adobe_downloader.config.schema import (
        CompositeJobConfig,
        LookupGenerationJobConfig,
        ReportDownloadConfig,
        RsidUpdateJobConfig,
        SegmentCreationJobConfig,
    )
    from adobe_downloader.core.api_client import AdobeClient
    from adobe_downloader.flows.report_download import iterate_dates, iterate_rsids
    from adobe_downloader.state_manager import (
        StateManager,
        compute_config_hash,
        compute_job_id,
        state_db_path,
    )

    try:
        job = load_config(config)
    except Exception as exc:
        click.secho(f"Failed to load config: {exc}", fg="red", bold=True)
        sys.exit(1)

    if isinstance(job, SegmentCreationJobConfig):
        _run_segment_creation_job(job)
        return

    if isinstance(job, LookupGenerationJobConfig):
        _run_lookup_generation_job(job)
        return

    if isinstance(job, RsidUpdateJobConfig):
        _run_rsid_update_job(job)
        return

    if isinstance(job, CompositeJobConfig):
        # CLI --test flag overrides config; merge into job object
        if test_mode and not job.test_mode:
            job = job.model_copy(update={"test_mode": True})
        _run_composite_job(job, config, no_resume)
        return

    if not isinstance(job, ReportDownloadConfig):
        click.secho(
            f"'run' supports report_download, segment_creation, lookup_generation, "
            f"or composite (got {job.job_type!r})",
            fg="yellow",
        )
        sys.exit(1)

    # CLI --test flag overrides config test_mode
    effective_test_mode = test_mode or job.test_mode

    if job.date_range is None:
        click.secho("date_range is required for report_download jobs.", fg="red", bold=True)
        sys.exit(1)

    # Resolve report definitions
    if job.report_ref:
        registry = load_report_registry()
        if job.report_ref not in registry:
            click.secho(f"report_ref {job.report_ref!r} not found in report_definitions/", fg="red")
            sys.exit(1)
        report_defs = [registry[job.report_ref]]
    elif job.report_group:
        try:
            report_defs = load_report_group(job.report_group)
        except KeyError as exc:
            click.secho(str(exc), fg="red")
            sys.exit(1)
    else:
        assert job.report is not None
        report_defs = [job.report]

    if report:
        report_defs = [rd for rd in report_defs if rd.name == report]
        if not report_defs:
            click.secho(f"Report {report!r} not found in resolved definitions.", fg="red")
            sys.exit(1)

    # Validate RSID file exists before starting downloads
    if job.rsids.source == "file":
        rsid_file = Path(job.rsids.file)  # type: ignore[arg-type]
        if not rsid_file.exists():
            click.secho(f"RSID file not found: {job.rsids.file}", fg="red")
            sys.exit(1)

    # Validate segment file exists before starting downloads
    if job.segments is not None and job.segments.source == "segment_list_file":
        seg_file = Path(job.segments.file)  # type: ignore[arg-type]
        if not seg_file.exists():
            click.secho(f"Segment list file not found: {job.segments.file}", fg="red")
            sys.exit(1)

    # Initialise state manager
    config_hash = compute_config_hash(config)
    job_id = compute_job_id(config, config_hash)
    db_path = state_db_path(job.output.base_folder, job.client, job_id)
    sm = StateManager(db_path, job_id, config, config_hash)

    # Warn if config has changed since last run
    if not no_resume:
        stored_hash = sm.get_config_hash()
        if stored_hash and stored_hash != config_hash:
            click.secho(
                "Warning: config has changed since the last run. "
                "Use --no-resume to start fresh or proceed to resume with new config.",
                fg="yellow",
            )

    date_intervals = list(iterate_dates(job.date_range, job.interval))
    rsid_list = list(iterate_rsids(job.rsids))

    click.echo(f"Job ID  : {job_id}")
    click.echo(f"RSIDs   : {len(rsid_list)}")
    click.echo(f"Reports : {len(report_defs)}")
    click.echo(
        f"Dates   : {job.date_range.from_date} -> {job.date_range.to} "
        f"({job.interval}, {len(date_intervals)} interval(s))"
    )
    if effective_test_mode:
        lim = job.test_limits
        click.secho(
            f"TEST MODE: capping to {lim.max_rsids} RSID(s), "
            f"{lim.max_date_intervals} date interval(s), "
            f"{lim.max_segments} segment(s).",
            fg="yellow",
        )

    async def _run() -> None:
        from adobe_downloader.flows.report_download import run_report_download

        ac = AdobeClient(job.client)
        try:
            result = await run_report_download(
                client=ac,
                client_name=job.client,
                report_defs=report_defs,
                rsids=job.rsids,
                date_range=job.date_range,  # type: ignore[arg-type]
                interval=job.interval,
                output_base=job.output.base_folder,
                sm=sm,
                segments=job.segments,
                file_name_extra=job.file_name_extra,
                no_resume=no_resume,
                test_limits=job.test_limits if effective_test_mode else None,
                on_progress=lambda status, rsid, name: click.secho(
                    f"  {status:<4} {rsid} / {name}",
                    fg={"OK": "green", "COPY": "blue", "SKIP": "cyan", "FAIL": "red"}.get(
                        status, "white"
                    ),
                ),
            )
        finally:
            await ac.close()

        if result.failed:
            sm.mark_job_failed(f"{result.failed} request(s) failed")
        else:
            sm.mark_job_completed()

        parts = [f"{result.downloaded} downloaded"]
        if result.skipped:
            parts.append(f"{result.skipped} skipped")
        if result.copied:
            parts.append(f"{result.copied} copied")
        if result.failed:
            parts.append(f"{result.failed} failed")
        click.echo(f"Done. {', '.join(parts)}.")

    try:
        asyncio.run(_run())
    except FileNotFoundError as exc:
        click.secho(str(exc), fg="red", bold=True)
        sys.exit(1)
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", bold=True)
        sys.exit(1)

    _write_job_completion(
        base_folder=Path(job.output.base_folder),
        client=job.client,
        config=config,
        sm=sm,
        job_id=job_id,
    )


def _run_composite_job(job: object, config: Path, no_resume: bool) -> None:
    """Dispatch helper for composite jobs (called from `run`)."""
    from adobe_downloader.config.schema import CompositeJobConfig
    from adobe_downloader.core.api_client import AdobeClient
    from adobe_downloader.flows.composite_job import run_composite_job
    from adobe_downloader.state_manager import (
        StateManager,
        compute_config_hash,
        compute_job_id,
        state_db_path,
    )

    assert isinstance(job, CompositeJobConfig)

    if job.output is None:
        click.secho(
            "composite jobs require output.base_folder to be set for state DB location.",
            fg="red",
            bold=True,
        )
        sys.exit(1)

    config_hash = compute_config_hash(config)
    job_id = compute_job_id(config, config_hash)
    db_path = state_db_path(job.output.base_folder, job.client, job_id)
    sm = StateManager(db_path, job_id, config, config_hash)

    click.echo(f"Job ID     : {job_id}")
    click.echo(f"Steps      : {len(job.steps)}")
    for s in job.steps:
        click.echo(f"  {s.id} [{s.step}]")
    if job.test_mode:
        lim = job.test_limits
        click.secho(
            f"TEST MODE: capping to {lim.max_rsids} RSID(s), "
            f"{lim.max_date_intervals} date interval(s), "
            f"{lim.max_segments} segment(s).",
            fg="yellow",
        )

    def _progress(step_id: str, msg: str) -> None:
        click.echo(f"  [{step_id}] {msg}")

    async def _run() -> None:
        ac = AdobeClient(job.client)
        try:
            await run_composite_job(
                job=job,
                config_path=config,
                sm=sm,
                ac=ac,
                no_resume=no_resume,
                on_progress=_progress,
            )
        finally:
            await ac.close()

    try:
        asyncio.run(_run())
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", bold=True)
        sys.exit(1)

    click.secho("Composite job completed.", fg="green", bold=True)

    _write_job_completion(
        base_folder=Path(job.output.base_folder),
        client=job.client,
        config=config,
        sm=sm,
        job_id=job_id,
    )


def _write_job_completion(
    base_folder: Path,
    client: str,
    config: Path,
    sm: object,
    job_id: str,
) -> None:
    """Archive config + append history record after a job finishes (success or failure)."""
    from datetime import datetime, timezone

    from adobe_downloader.utils.post_process import (
        archive_config,
        build_history_record,
        log_job_history,
    )

    date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        archived = archive_config(base_folder, client, config, date_prefix)
        archived_rel = str(archived.relative_to(base_folder / client))
    except Exception:
        archived_rel = ""

    try:
        summary = sm.get_summary()  # type: ignore[union-attr]
        output_folder = str(base_folder / client / "CSV")
        record = build_history_record(
            job_id=job_id,
            config_path=config,
            summary=summary,
            output_folder=output_folder,
            archived_config_rel=archived_rel,
        )
        log_job_history(base_folder, client, record)
    except Exception as exc:
        click.secho(f"Warning: could not write job history: {exc}", fg="yellow")


def _run_rsid_update_job(job: object) -> None:
    """Dispatch helper for rsid_update jobs (called from `run`)."""
    import asyncio

    from adobe_downloader.config.schema import RsidUpdateJobConfig
    from adobe_downloader.core.api_client import AdobeClient
    from adobe_downloader.flows.rsid_update import run_rsid_update

    assert isinstance(job, RsidUpdateJobConfig)

    if job.date_range is None:
        click.secho("date_range is required for rsid_update jobs.", fg="red", bold=True)
        sys.exit(1)

    data_root = Path("data")
    exclusion_file = data_root / "rsid_lists" / "excludedRsidCleanNames.txt"
    suite_pairs_dir = data_root / "report_suite_lists"

    click.echo(f"Investigation threshold : {job.rsid_update.investigation_threshold}")
    click.echo(f"Validation threshold    : {job.rsid_update.validation_threshold}")
    click.echo(f"Include virtual         : {job.rsid_update.include_virtual}")
    click.echo(f"Date range              : {job.date_range.from_date} -> {job.date_range.to}")
    click.echo(f"Output base             : {job.output.base_folder}")

    def _on_progress(rsid: str, status: str) -> None:
        fg = {"OK": "green", "FAIL": "red"}.get(status, "white")
        click.secho(f"  {status:<4} {rsid}", fg=fg)

    async def _run() -> None:
        ac = AdobeClient(job.client)
        try:
            result = await run_rsid_update(
                client=ac,
                rsid_update_cfg=job.rsid_update,
                date_range=job.date_range,  # type: ignore[arg-type]
                output_base=job.output.base_folder,
                exclusion_file=exclusion_file if exclusion_file.exists() else None,
                suite_pairs_dir=suite_pairs_dir,
                on_progress=_on_progress,
            )
        finally:
            await ac.close()

        click.secho(
            f"\nDone. {result.total_suites} suites, "
            f"{result.investigation_count} investigation, "
            f"{result.validation_count} validation, "
            f"{result.failed} failed.",
            fg="green" if result.failed == 0 else "yellow",
        )

    try:
        asyncio.run(_run())
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", bold=True)
        sys.exit(1)


def _run_segment_creation_job(job: object) -> None:
    """Dispatch helper for segment_creation jobs (called from `run`)."""
    import asyncio

    from adobe_downloader.config.schema import SegmentCreationJobConfig
    from adobe_downloader.core.api_client import AdobeClient
    from adobe_downloader.flows.segment_creation import run_segment_creation
    from adobe_downloader.utils.rsid_lookup import find_latest_rsid_file

    assert isinstance(job, SegmentCreationJobConfig)
    sc = job.segment_creation
    input_csv = Path(sc.input_csv)
    if not input_csv.exists():
        click.secho(f"Input CSV not found: {input_csv}", fg="red", bold=True)
        sys.exit(1)

    # Resolve output paths
    compare_path = Path(sc.compare_list_path) if sc.compare_list_path else None
    validate_path = Path(sc.validate_list_path) if sc.validate_list_path else None
    segment_path = Path(sc.segment_list_path) if sc.segment_list_path else None

    # Lookup files: data/ relative to repo root (discovered from CWD)
    data_root = Path("data")
    lookup_base = data_root / "lookups"
    rsid_dir = data_root / "report_suite_lists"
    rsid_file = find_latest_rsid_file(rsid_dir)
    if rsid_file is None:
        click.secho(f"No RSID lookup file found in {rsid_dir}", fg="red", bold=True)
        sys.exit(1)

    click.echo(f"Input CSV  : {input_csv}")
    click.echo(f"RSID file  : {rsid_file.name}")
    click.echo(f"Share with : {sc.share_with_users or '(none)'}")

    async def _run() -> None:
        ac = AdobeClient(job.client)
        try:
            result = await run_segment_creation(
                client=ac,
                input_csv=input_csv,
                share_with_users=sc.share_with_users,
                compare_list_path=compare_path,
                validate_list_path=validate_path,
                segment_list_path=segment_path,
                lookup_base=lookup_base,
                rsid_lookup_file=rsid_file,
                test_mode_row=sc.test_mode_row,
            )
        finally:
            await ac.close()

        click.secho(
            f"Done. Created: {result.created_count}, "
            f"Special: {result.special_count}, "
            f"Errors: {result.error_count}",
            fg="green" if result.error_count == 0 else "yellow",
        )
        if result.compare_list_file:
            click.echo(f"  Compare  -> {result.compare_list_file}")
        if result.validate_list_file:
            click.echo(f"  Validate -> {result.validate_list_file}")
        if result.segment_list_file:
            click.echo(f"  Segments -> {result.segment_list_file}")
        for err in result.errors:
            click.secho(f"  ERR {err}", fg="red")

    try:
        asyncio.run(_run())
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", bold=True)
        sys.exit(1)


def _run_lookup_generation_job(job: object) -> None:
    """Dispatch helper for lookup_generation jobs (called from `run`)."""
    import asyncio

    from adobe_downloader.config.schema import LookupGenerationJobConfig
    from adobe_downloader.core.api_client import AdobeClient
    from adobe_downloader.flows.lookup_generation import run_lookup_generation

    assert isinstance(job, LookupGenerationJobConfig)
    lg = job.lookup_generation

    if job.date_range is None:
        click.secho("date_range is required for lookup_generation jobs.", fg="red", bold=True)
        sys.exit(1)

    data_root = Path("data")
    lookup_base = data_root / "lookups"

    click.echo(f"Dimension  : {lg.dimension}")
    click.echo(f"RSID       : {lg.rsid}")
    click.echo(f"Date range : {job.date_range.from_date} -> {job.date_range.to}")
    if lg.segments:
        click.echo(f"Segments   : {lg.segments}")

    async def _run() -> Path:
        ac = AdobeClient(job.client)
        try:
            return await run_lookup_generation(
                client=ac,
                client_name=job.client,
                config=lg,
                date_range=job.date_range,  # type: ignore[arg-type]
                lookup_base=lookup_base,
            )
        finally:
            await ac.close()

    try:
        dest = asyncio.run(_run())
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", bold=True)
        sys.exit(1)

    click.secho(f"Lookup file generated: {dest}", fg="green", bold=True)


@main.command("get-segment")
@click.option("--client", "-c", required=True, help="Client name.")
@click.option("--segment-id", "-s", required=True, help="Adobe segment ID (e.g. s3938_...).")
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(path_type=Path),
    help="Output JSON file (default: data/saved_segments/<segment_id>.json).",
)
def get_segment(client: str, segment_id: str, output: Path | None) -> None:
    """Fetch a segment definition from the Adobe API and save it locally."""
    import asyncio

    from adobe_downloader.core.api_client import AdobeClient
    from adobe_downloader.segments.save_segment import save_segment

    if output is None:
        output = Path("data") / "saved_segments" / f"{segment_id}.json"

    async def _run() -> None:
        ac = AdobeClient(client)
        try:
            data = await save_segment(ac, segment_id, output)
        finally:
            await ac.close()
        click.secho(
            f"Saved segment {data.get('id', segment_id)} "
            f"({data.get('name', '')!r}) -> {output}",
            fg="green",
        )

    try:
        asyncio.run(_run())
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", bold=True)
        sys.exit(1)


@main.command("search-lookup")
@click.option("--dimension", "-d", required=True, help="Friendly dimension name (e.g. 'BrowserType').")
@click.option("--value", "-v", required=True, help="String value to look up.")
def search_lookup(dimension: str, value: str) -> None:
    """Search a local lookup file for a dimension value's numeric ID."""
    from adobe_downloader.segments.create_segment import (
        DIMENSIONS_REQUIRING_LOOKUP,
        get_dimension_id,
        load_lookup_file,
        normalize_monitor_resolution,
    )

    if dimension not in DIMENSIONS_REQUIRING_LOOKUP:
        click.secho(
            f"{dimension!r} does not require a numeric lookup. "
            f"Dimensions needing lookup: {sorted(DIMENSIONS_REQUIRING_LOOKUP)}",
            fg="yellow",
        )
        sys.exit(0)

    adobe_dim = get_dimension_id(dimension)
    if not adobe_dim:
        click.secho(f"Unknown dimension: {dimension!r}", fg="red")
        sys.exit(1)

    import re as _re

    clean_dim = _re.sub(r"[^a-zA-Z0-9]", "", adobe_dim)
    lookup_path = Path("data") / "lookups" / clean_dim / "lookup.txt"

    processed = value
    if "monitor" in dimension.lower() or "resolution" in dimension.lower():
        processed = normalize_monitor_resolution(value)

    lookup = load_lookup_file(lookup_path)
    if not lookup:
        click.secho(f"Lookup file not found or empty: {lookup_path}", fg="yellow")
        sys.exit(1)

    if processed in lookup:
        click.secho(f"{processed!r} -> {lookup[processed]}", fg="green")
    else:
        click.secho(f"Value {processed!r} not found in {lookup_path}", fg="yellow")
        close = [k for k in lookup if processed.lower() in k.lower()][:10]
        if close:
            click.echo("Similar entries:")
            for k in close:
                click.echo(f"  {k!r} -> {lookup[k]}")


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True, path_type=Path))
def status(config: Path) -> None:
    """Print job state: requests by status, last errors."""
    from adobe_downloader.config.loader import load_config
    from adobe_downloader.config.schema import ReportDownloadConfig
    from adobe_downloader.state_manager import (
        compute_config_hash,
        compute_job_id,
        state_db_path,
        StateManager,
    )

    try:
        job = load_config(config)
    except Exception as exc:
        click.secho(f"Failed to load config: {exc}", fg="red", bold=True)
        sys.exit(1)

    if not isinstance(job, ReportDownloadConfig):
        click.secho(f"'status' currently supports job_type=report_download.", fg="yellow")
        sys.exit(1)

    config_hash = compute_config_hash(config)
    job_id = compute_job_id(config, config_hash)
    db_path = state_db_path(job.output.base_folder, job.client, job_id)

    if not db_path.exists():
        click.secho(f"No state found for this config (job_id: {job_id}).", fg="yellow")
        sys.exit(0)

    sm = StateManager(db_path, job_id, config, config_hash)
    summary = sm.get_summary()

    click.echo(f"Job ID      : {summary['job_id']}")
    click.echo(f"Job status  : {summary['job_status']}")
    click.echo(f"Created     : {summary['created_at']}")
    click.echo(f"Started     : {summary['started_at'] or '-'}")
    click.echo(f"Completed   : {summary['completed_at'] or '-'}")
    click.echo(f"Total       : {summary['total']}")
    click.secho(f"  completed : {summary['completed']}", fg="green")
    click.secho(f"  pending   : {summary['pending']}", fg="cyan")
    click.secho(f"  in_progress: {summary['in_progress']}", fg="cyan")
    click.secho(f"  failed    : {summary['failed']}", fg="red" if summary["failed"] else "white")

    if summary["last_errors"]:
        click.secho("Last errors:", fg="red")
        for err in summary["last_errors"]:
            click.secho(f"  {err['key']}: {err['error']}", fg="red")


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--failed-only", is_flag=True, default=False, help="Re-queue only failed requests.")
def retry(config: Path, failed_only: bool) -> None:
    """Re-queue failed (or all pending+failed) requests for re-download."""
    from adobe_downloader.config.loader import load_config
    from adobe_downloader.config.schema import ReportDownloadConfig
    from adobe_downloader.state_manager import (
        compute_config_hash,
        compute_job_id,
        state_db_path,
        StateManager,
    )

    try:
        job = load_config(config)
    except Exception as exc:
        click.secho(f"Failed to load config: {exc}", fg="red", bold=True)
        sys.exit(1)

    if not isinstance(job, ReportDownloadConfig):
        click.secho(f"'retry' currently supports job_type=report_download.", fg="yellow")
        sys.exit(1)

    config_hash = compute_config_hash(config)
    job_id = compute_job_id(config, config_hash)
    db_path = state_db_path(job.output.base_folder, job.client, job_id)

    if not db_path.exists():
        click.secho(f"No state found for this config.", fg="yellow")
        sys.exit(1)

    sm = StateManager(db_path, job_id, config, config_hash)
    if failed_only:
        count = sm.reset_failed()
        click.echo(f"Reset {count} failed request(s) to pending.")
    else:
        count = sm.reset_all()
        click.echo(f"Reset {count} non-completed request(s) to pending.")

    click.echo("Run 'adobe-downloader run' to resume.")


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--confirm", is_flag=True, default=False, help="Required to confirm full state wipe.")
def reset(config: Path, confirm: bool) -> None:
    """Clear all state for a job (allows a clean restart)."""
    from adobe_downloader.config.loader import load_config
    from adobe_downloader.config.schema import ReportDownloadConfig
    from adobe_downloader.state_manager import (
        compute_config_hash,
        compute_job_id,
        state_db_path,
        StateManager,
    )

    if not confirm:
        click.secho(
            "This will delete all job state. Pass --confirm to proceed.", fg="yellow"
        )
        sys.exit(1)

    try:
        job = load_config(config)
    except Exception as exc:
        click.secho(f"Failed to load config: {exc}", fg="red", bold=True)
        sys.exit(1)

    if not isinstance(job, ReportDownloadConfig):
        click.secho(f"'reset' currently supports job_type=report_download.", fg="yellow")
        sys.exit(1)

    config_hash = compute_config_hash(config)
    job_id = compute_job_id(config, config_hash)
    db_path = state_db_path(job.output.base_folder, job.client, job_id)

    if not db_path.exists():
        click.secho(f"No state found for this config.", fg="yellow")
        sys.exit(0)

    sm = StateManager(db_path, job_id, config, config_hash)
    sm.full_reset()
    click.secho(f"State cleared for job {job_id}.", fg="green")


@main.command()
@click.option(
    "--json-dir",
    "-j",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Folder containing downloaded JSON files.",
)
@click.option(
    "--pattern",
    "-p",
    default="*.json",
    show_default=True,
    help="Glob pattern to select JSON files (e.g. 'Legend_botInvestigation*.json').",
)
@click.option(
    "--concat/--no-concat",
    default=True,
    show_default=True,
    help="After transforming, concatenate all CSVs into a single output file.",
)
@click.option(
    "--concat-output",
    default=None,
    type=click.Path(path_type=Path),
    help="Path for the concatenated CSV (default: <csv_dir>/<pattern_stem>.csv).",
)
def transform(
    json_dir: Path,
    pattern: str,
    concat: bool,
    concat_output: Path | None,
) -> None:
    """Transform downloaded JSON files to CSV, then optionally concatenate them."""
    import glob as _glob

    from adobe_downloader.transforms.base import make_csv_output_path, transform_report
    from adobe_downloader.transforms.concatenate import concatenate_csvs

    json_files = sorted(json_dir.glob(pattern))
    if not json_files:
        click.secho(f"No JSON files matched {pattern!r} in {json_dir}", fg="yellow")
        sys.exit(1)

    click.echo(f"Transforming {len(json_files)} file(s) from {json_dir}")

    ok = failed = 0
    for jf in json_files:
        csv_path = make_csv_output_path(jf)
        try:
            transform_report(jf, output_path=csv_path)
            click.secho(f"  OK   {jf.name} -> {csv_path.name}", fg="green")
            ok += 1
        except Exception as exc:
            click.secho(f"  FAIL {jf.name}: {exc}", fg="red")
            failed += 1

    click.echo(f"Transformed: {ok} ok, {failed} failed.")

    if concat and ok > 0:
        first_csv = make_csv_output_path(json_files[0])
        csv_dir = first_csv.parent
        csv_pattern = pattern.replace(".json", ".csv")
        if concat_output is None:
            stem = pattern.rstrip("*").rstrip("_").replace(".json", "") or "concat"
            concat_output = csv_dir / f"{stem}_concat.csv"
        count = concatenate_csvs(csv_dir, csv_pattern, concat_output)
        if count:
            click.secho(f"Concatenated {count} CSV(s) -> {concat_output}", fg="green")
        else:
            click.secho("No CSVs to concatenate.", fg="yellow")


@main.command()
@click.option("--client", "-c", required=True, help="Client name.")
@click.option(
    "--output-base",
    "-o",
    default=None,
    type=click.Path(path_type=Path),
    help="Base output folder (default: current directory).",
)
@click.option("--last", default=10, show_default=True, help="Maximum number of records to show.")
@click.option("--status", default=None, help="Filter by status (completed|failed|in_progress).")
@click.option(
    "--since",
    default=None,
    help="Show records started on or after this date (ISO format, e.g. 2025-06-01).",
)
def history(
    client: str,
    output_base: Path | None,
    last: int,
    status: str | None,
    since: str | None,
) -> None:
    """Show recent job history from the job log."""
    from adobe_downloader.utils.post_process import read_job_history

    base = output_base or Path.cwd()
    records = read_job_history(base, client, last=last, status=status, since=since)
    if not records:
        click.secho("No history records found.", fg="yellow")
        return
    for r in records:
        status_color = {"completed": "green", "failed": "red"}.get(r.get("status", ""), "white")
        click.secho(
            f"  {r.get('status', '?'):<12} {r.get('job_id', '?')}",
            fg=status_color,
        )
        click.echo(f"    config   : {r.get('config_path', '-')}")
        click.echo(f"    started  : {r.get('started_at', '-')}")
        click.echo(f"    completed: {r.get('completed_at', '-')}")
        dur = r.get("duration_minutes")
        click.echo(f"    duration : {dur} min" if dur is not None else "    duration : -")
        click.echo(
            f"    requests : {r.get('total_requests', 0)} total, "
            f"{r.get('completed_requests', 0)} ok, "
            f"{r.get('failed_requests', 0)} failed"
        )
        click.echo(f"    output   : {r.get('output_folder', '-')}")
        click.echo("")


@main.command()
@click.option("--client", "-c", required=True, help="Client name.")
@click.option(
    "--output-base",
    "-o",
    default=None,
    type=click.Path(path_type=Path),
    help="Base output folder (default: current directory).",
)
@click.option(
    "--older-than",
    "older_than",
    required=True,
    help="Delete files older than this (e.g. 30d).",
)
@click.option(
    "--type",
    "file_type",
    required=True,
    type=click.Choice(["processed-json", "logs", "state"], case_sensitive=False),
    help="Category of files to remove.",
)
@click.option("--confirm", is_flag=True, default=False, help="Required to actually delete.")
def cleanup(
    client: str,
    output_base: Path | None,
    older_than: str,
    file_type: str,
    confirm: bool,
) -> None:
    """Remove old processed files. Always requires --confirm to delete."""
    from adobe_downloader.utils.post_process import cleanup_old_files

    # Parse "30d" -> 30
    older_than = older_than.strip()
    if older_than.endswith("d"):
        try:
            days = int(older_than[:-1])
        except ValueError:
            click.secho(f"Invalid --older-than value: {older_than!r}. Use format like '30d'.", fg="red")
            sys.exit(1)
    else:
        try:
            days = int(older_than)
        except ValueError:
            click.secho(f"Invalid --older-than value: {older_than!r}. Use format like '30d'.", fg="red")
            sys.exit(1)

    base = output_base or Path.cwd()

    if not confirm:
        click.secho(
            f"Dry run: would delete {file_type!r} files older than {days} day(s) "
            f"for client {client!r}. Pass --confirm to actually delete.",
            fg="yellow",
        )
        return

    count = cleanup_old_files(base, client, days, file_type)
    click.secho(f"Deleted {count} file(s).", fg="green" if count else "yellow")


@main.command("validate-output")
@click.option("--config", "-c", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--retry/--no-retry", default=False, help="Re-download missing/empty files.")
@click.option("--dry-run/--no-dry-run", default=False, help="Report missing files without re-downloading.")
def validate_output(config: Path, retry: bool, dry_run: bool) -> None:
    """Check all expected output files exist and are non-empty."""
    import asyncio

    from adobe_downloader.config.loader import load_config
    from adobe_downloader.config.schema import ReportDownloadConfig
    from adobe_downloader.flows.validation import run_validate_output

    try:
        job = load_config(config)
    except Exception as exc:
        click.secho(f"Failed to load config: {exc}", fg="red", bold=True)
        sys.exit(1)

    if not isinstance(job, ReportDownloadConfig):
        click.secho(
            f"validate-output only supports report_download configs (got {job.job_type!r})",
            fg="red",
        )
        sys.exit(1)

    if job.date_range is None:
        click.secho("Config has no date_range — cannot enumerate expected files.", fg="red")
        sys.exit(1)

    ac = None
    sm = None

    if retry and not dry_run:
        from adobe_downloader.core.api_client import AdobeClient
        from adobe_downloader.state_manager import (
            StateManager,
            compute_config_hash,
            compute_job_id,
            state_db_path,
        )

        config_hash = compute_config_hash(config)
        job_id = compute_job_id(config, config_hash)
        db_path = state_db_path(job.output.base_folder, job.client, job_id)
        sm = StateManager(db_path, job_id, config, config_hash)
        ac = AdobeClient.from_client_name(job.client)

    result = asyncio.run(
        run_validate_output(job, retry=retry, dry_run=dry_run, ac=ac, sm=sm)
    )

    total = result["total"]
    valid = result["valid"]
    missing_count = result["missing_count"]

    click.echo(f"Expected : {total}")
    click.secho(f"Valid    : {valid}", fg="green" if valid == total else "yellow")
    click.secho(
        f"Missing  : {missing_count}",
        fg="red" if missing_count else "green",
    )

    if missing_count:
        for p in result["missing"][:20]:
            click.echo(f"  {p}")
        if len(result["missing"]) > 20:
            click.echo(f"  ... and {len(result['missing']) - 20} more")
        if dry_run:
            click.secho("Dry run — pass --retry to re-download.", fg="yellow")
        elif not retry:
            click.secho("Pass --retry to re-download missing files.", fg="yellow")
        sys.exit(1)

    click.secho("All expected output files are present.", fg="green")


@main.command("update-rsids")
@click.option("--client", "-c", required=True, help="Client name (matches credentials file).")
@click.option("--from", "from_date", required=True, help="Start date YYYY-MM-DD.")
@click.option("--to", "to_date", required=True, help="End date YYYY-MM-DD.")
@click.option(
    "--investigation-threshold",
    default=1000,
    show_default=True,
    help="Minimum visits for investigation list.",
)
@click.option(
    "--validation-threshold",
    default=1000,
    show_default=True,
    help="Minimum visits for validation list.",
)
@click.option(
    "--include-virtual/--no-include-virtual",
    default=False,
    show_default=True,
    help="Include virtual report suites (rsid prefix: vrs_).",
)
@click.option(
    "--output-base",
    "-o",
    default="data/rsid_lists",
    show_default=True,
    type=click.Path(path_type=Path),
    help="Directory to write botInvestigation/botValidation list files.",
)
@click.option(
    "--suite-pairs-dir",
    default="data/report_suite_lists",
    show_default=True,
    type=click.Path(path_type=Path),
    help="Directory to write dated rsid:cleanName pairs file (used by downstream lookups).",
)
@click.option(
    "--exclusion-file",
    default="data/rsid_lists/excludedRsidCleanNames.txt",
    show_default=True,
    type=click.Path(path_type=Path),
    help="Plain-text list of clean names to exclude (one per line).",
)
def update_rsids(
    client: str,
    from_date: str,
    to_date: str,
    investigation_threshold: int,
    validation_threshold: int,
    include_virtual: bool,
    output_base: Path,
    suite_pairs_dir: Path,
    exclusion_file: Path,
) -> None:
    """Fetch report suites, download topline metrics, and generate filtered RSID list files."""
    import asyncio

    from adobe_downloader.config.schema import DateRange, RsidUpdateConfig
    from adobe_downloader.core.api_client import AdobeClient
    from adobe_downloader.flows.rsid_update import run_rsid_update

    try:
        date_range = DateRange(from_date=from_date, to=to_date)
    except Exception as exc:
        click.secho(f"Invalid date range: {exc}", fg="red", bold=True)
        sys.exit(1)

    rsid_update_cfg = RsidUpdateConfig(
        investigation_threshold=investigation_threshold,
        validation_threshold=validation_threshold,
        include_virtual=include_virtual,
    )

    click.echo(f"Client               : {client}")
    click.echo(f"Date range           : {from_date} -> {to_date}")
    click.echo(f"Investigation thresh : {investigation_threshold} visits")
    click.echo(f"Validation thresh    : {validation_threshold} visits")
    click.echo(f"Include virtual      : {include_virtual}")
    click.echo(f"Output base          : {output_base}")

    def _on_progress(rsid: str, status: str) -> None:
        fg = {"OK": "green", "FAIL": "red"}.get(status, "white")
        click.secho(f"  {status:<4} {rsid}", fg=fg)

    async def _run() -> None:
        ac = AdobeClient(client)
        try:
            result = await run_rsid_update(
                client=ac,
                rsid_update_cfg=rsid_update_cfg,
                date_range=date_range,
                output_base=output_base,
                exclusion_file=exclusion_file if exclusion_file.exists() else None,
                suite_pairs_dir=suite_pairs_dir,
                on_progress=_on_progress,
            )
        finally:
            await ac.close()

        click.secho(
            f"\nDone. {result.total_suites} suites fetched, "
            f"{result.failed} failed.",
            fg="green" if result.failed == 0 else "yellow",
        )
        click.echo(f"  Investigation ({investigation_threshold}+ visits): {result.investigation_count}")
        click.echo(f"  Validation    ({validation_threshold}+ visits): {result.validation_count}")
        click.secho(f"  -> {result.investigation_list}", fg="cyan")
        click.secho(f"  -> {result.validation_list}", fg="cyan")
        if result.suite_pairs_file:
            click.secho(f"  -> {result.suite_pairs_file}", fg="cyan")

    try:
        asyncio.run(_run())
    except FileNotFoundError as exc:
        click.secho(str(exc), fg="red", bold=True)
        sys.exit(1)
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", bold=True)
        sys.exit(1)


@main.command("list-rsids")
@click.option("--client", "-c", required=True, help="Client name (matches credentials file).")
@click.option(
    "--include-virtual/--no-include-virtual",
    default=False,
    show_default=True,
    help="Include virtual report suites (rsid prefix: vrs_).",
)
def list_rsids(client: str, include_virtual: bool) -> None:
    """Fetch and display all report suites for a client."""
    import asyncio

    from adobe_downloader.core.api_client import AdobeClient
    from adobe_downloader.flows.rsid_update import clean_suite_name

    async def _run() -> list[dict]:  # type: ignore[type-arg]
        ac = AdobeClient(client)
        try:
            raw = await ac.get_report_suites()
        finally:
            await ac.close()
        return raw.get("content", [])

    try:
        suites = asyncio.run(_run())
    except FileNotFoundError as exc:
        click.secho(str(exc), fg="red", bold=True)
        sys.exit(1)
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", bold=True)
        sys.exit(1)

    if not include_virtual:
        suites = [s for s in suites if not s["rsid"].startswith("vrs_")]

    click.echo(f"Found {len(suites)} report suite(s):")
    for s in suites:
        name = s.get("name", "")
        rsid = s.get("rsid", "")
        clean = clean_suite_name(name)
        click.echo(f"  {rsid:<40} {name}  ({clean})")
