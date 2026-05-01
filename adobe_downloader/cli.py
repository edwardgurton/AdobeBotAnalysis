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
            loc = " → ".join(str(x) for x in err["loc"])
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
def run(config: Path, report: str | None) -> None:
    """Execute a report_download job: iterate all RSIDs x date intervals x segments."""
    from adobe_downloader.config.loader import load_config
    from adobe_downloader.config.report_definitions import load_report_group, load_report_registry
    from adobe_downloader.config.schema import ReportDownloadConfig
    from adobe_downloader.core.api_client import AdobeClient
    from adobe_downloader.core.request_builder import build_request
    from adobe_downloader.flows.report_download import (
        download_report,
        iterate_dates,
        iterate_rsids,
        iterate_segments,
        make_output_path,
    )

    try:
        job = load_config(config)
    except Exception as exc:
        click.secho(f"Failed to load config: {exc}", fg="red", bold=True)
        sys.exit(1)

    if not isinstance(job, ReportDownloadConfig):
        click.secho(
            f"'run' currently supports job_type=report_download (got {job.job_type!r})",
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

    date_intervals = list(iterate_dates(job.date_range, job.interval))
    rsid_list = list(iterate_rsids(job.rsids))

    click.echo(f"RSIDs   : {len(rsid_list)}")
    click.echo(f"Reports : {len(report_defs)}")
    click.echo(f"Dates   : {job.date_range.from_date} -> {job.date_range.to} ({job.interval}, {len(date_intervals)} interval(s))")

    async def _run() -> None:
        ac = AdobeClient(job.client)
        total = 0
        try:
            for rsid in rsid_list:
                for date_interval in date_intervals:
                    for seg_id, seg_ids in iterate_segments(job.segments):
                        for rd in report_defs:
                            req_body = build_request(
                                report_def=rd,
                                date_range=date_interval,
                                rsid=rsid,
                                segments=seg_ids,
                            )
                            out_path = make_output_path(
                                base_folder=job.output.base_folder,
                                client=job.client,
                                report_name=rd.name,
                                date_range=date_interval,
                                file_name_extra=job.file_name_extra,
                                segment_id=seg_id,
                            )
                            await download_report(ac, req_body, out_path)
                            click.secho(f"  OK {rsid} / {rd.name} -> {out_path.name}", fg="green")
                            total += 1
        finally:
            await ac.close()
        click.echo(f"Done. {total} file(s) downloaded.")

    try:
        asyncio.run(_run())
    except FileNotFoundError as exc:
        click.secho(str(exc), fg="red", bold=True)
        sys.exit(1)
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", bold=True)
        sys.exit(1)


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True, path_type=Path))
def status(config: Path) -> None:
    """Print job state. (Requires Step 7 — state DB not yet implemented.)"""
    click.secho("Not yet implemented. Requires Step 7 (state persistence).", fg="yellow")
    sys.exit(1)


@main.command()
@click.option("--client", "-c", required=True)
@click.option("--last", default=10, show_default=True)
def history(client: str, last: int) -> None:
    """Show recent job history. (Requires Step 15 — post-processing not yet implemented.)"""
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
