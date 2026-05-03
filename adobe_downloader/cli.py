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
def run(config: Path, report: str | None, no_resume: bool) -> None:
    """Execute a job: report_download, segment_creation, lookup_generation, or composite."""
    from adobe_downloader.config.loader import load_config
    from adobe_downloader.config.report_definitions import load_report_group, load_report_registry
    from adobe_downloader.config.schema import (
        CompositeJobConfig,
        LookupGenerationJobConfig,
        ReportDownloadConfig,
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

    if isinstance(job, CompositeJobConfig):
        _run_composite_job(job, config, no_resume)
        return

    if not isinstance(job, ReportDownloadConfig):
        click.secho(
            f"'run' supports report_download, segment_creation, lookup_generation, "
            f"or composite (got {job.job_type!r})",
            fg="yellow",
        )
        sys.exit(1)

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
@click.option("--client", "-c", required=True)
@click.option("--last", default=10, show_default=True)
def history(client: str, last: int) -> None:
    """Show recent job history. (Requires Step 15 - post-processing not yet implemented.)"""
    click.secho("Not yet implemented. Requires Step 15 (post-processing).", fg="yellow")
    sys.exit(1)


@main.command()
@click.option("--client", "-c", required=True)
def cleanup(client: str) -> None:
    """Remove old processed files. (Requires Step 15.)"""
    click.secho("Not yet implemented. Requires Step 15 (post-processing).", fg="yellow")
    sys.exit(1)


@main.command("validate-output")
@click.option("--config", "-c", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--retry/--no-retry", default=False)
@click.option("--dry-run/--no-dry-run", default=False)
def validate_output(config: Path, retry: bool, dry_run: bool) -> None:
    """Check all expected output files exist. (Requires Step 17.)"""
    click.secho("Not yet implemented. Requires Step 17 (validation flow).", fg="yellow")
    sys.exit(1)


@main.command("update-rsids")
@click.option("--client", "-c", required=True)
@click.option("--from", "from_date", required=True)
@click.option("--to", "to_date", required=True)
@click.option("--investigation-threshold", default=1000, show_default=True)
@click.option("--validation-threshold", default=1000, show_default=True)
@click.option("--include-virtual/--no-include-virtual", default=False)
def update_rsids(
    client: str,
    from_date: str,
    to_date: str,
    investigation_threshold: int,
    validation_threshold: int,
    include_virtual: bool,
) -> None:
    """Fetch report suites and generate RSID list files. (Requires Step 18.)"""
    click.secho("Not yet implemented. Requires Step 18 (RSID updater).", fg="yellow")
    sys.exit(1)
