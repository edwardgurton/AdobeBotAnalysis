"""CLI entry point for adobe-downloader."""

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
    """List Adobe users for a client. (Requires Step 2 — auth not yet implemented.)"""
    click.secho("Not yet implemented. Requires Step 2 (auth + API client).", fg="yellow")
    sys.exit(1)


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True, path_type=Path))
def run(config: Path) -> None:
    """Execute a job. (Requires Steps 2–7 — not yet implemented.)"""
    click.secho("Not yet implemented. Requires Steps 2–7.", fg="yellow")
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
