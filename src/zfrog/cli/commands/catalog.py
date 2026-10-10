"""CLI catalog commands — split from cli.py."""

import asyncio
import sys
from pathlib import Path

import typer
from rich.markdown import Markdown
from rich.table import Table

from zfrog.cli import app
from zfrog.cli._shared import console
from zfrog.models import JobCreate


@app.command()
def versions(
    url: str = typer.Argument(..., help="URL of the site"),
    branch: str = typer.Option("main", "--branch", "-b", help="Branch to list"),
):
    """List saved versions of a site."""
    from zfrog.versioning import VersionStore

    store = VersionStore()
    log = store.log(url, branch)

    if not log:
        console.print(f"[dim]No saved versions for {url} in '{branch}'.[/]")
        console.print("[dim]Use --versioned on the clone to start the history.[/]")
        return

    table = Table(title=f"Versions of {url} ({branch})")
    table.add_column("ID", style="cyan")
    table.add_column("WHEN", style="green")
    table.add_column("PAGES", justify="right")
    table.add_column("MESSAGE")
    table.add_column("PREVIOUS", style="dim")

    head_id = store.head(url, branch)
    for version in log:
        marker = " [bold]HEAD[/]" if head_id and version.id == head_id.id else ""
        table.add_row(
            version.id + marker,
            version.captured_at,
            str(version.pages),
            version.message or "-",
            (version.parent or "-")[:12],
        )

    console.print(table)


@app.command()
def rollback(
    url: str = typer.Argument(..., help="URL of the site"),
    ref: str = typer.Argument(..., help="Version (id, prefix, HEAD) or branch"),
    dest: Path | None = typer.Option(None, "--dest", "-d", help="Where to restore"),
):
    """Restore the files of a saved version."""
    from zfrog.versioning import VersionStore

    try:
        restored = VersionStore().rollback(url, ref, dest)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    files = [f for f in restored.rglob("*") if f.is_file()]
    console.print(f"[green]{len(files)} file(s) restored to {restored}[/]")


@app.command()
def branches(
    url: str = typer.Argument(..., help="URL of the site"),
):
    """List the version branches of a site."""
    from zfrog.versioning import VersionStore

    store = VersionStore()
    names = store.branches(url)
    if not names:
        console.print(f"[dim]No branches for {url}.[/]")
        return

    head = store.head(url, "main")
    for name in names:
        marker = " [bold](HEAD)[/]" if head and name == "main" else ""
        console.print(f"  {name}{marker}")


@app.command()
def branch(
    url: str = typer.Argument(..., help="URL of the site"),
    name: str = typer.Argument(..., help="Name of the new branch"),
    from_branch: str = typer.Option("main", "--from", help="Source branch"),
):
    """Create a new version branch."""
    from zfrog.versioning import VersionStore

    try:
        VersionStore().create_branch(url, name, from_branch)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Branch '{name}' created from '{from_branch}'.[/]")


schedule_app = typer.Typer(help="Schedule recurring copies of a site.")


app.add_typer(schedule_app, name="schedule")


@schedule_app.command("add")
def schedule_add(
    url: str = typer.Argument(..., help="URL of the site"),
    cron: str = typer.Option(..., "--cron", "-c", help='When to run, e.g.: "0 2 * * *"'),
    mode: str = typer.Option(
        "auto", "--mode", "-m", help="Job mode (auto = the probe picks the engine)"
    ),
    depth: int = typer.Option(1, "--depth", "-d", help="Max crawl depth"),
):
    """Schedule a recurring copy."""
    from zfrog.cron import describe
    from zfrog.scheduler import ScheduleStore, next_run_for

    try:
        schedule = ScheduleStore().add(cron, url, mode=mode, max_depth=depth)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Scheduled ({schedule.id})[/] — {describe(cron)}")
    console.print(f"[dim]Next run: {schedule.next_run or next_run_for(schedule)}[/]")


@schedule_app.command("list")
def schedule_list():
    """List the schedules."""
    from zfrog.cron import describe
    from zfrog.scheduler import ScheduleStore

    schedules = ScheduleStore().list()
    if not schedules:
        console.print("[dim]No schedules. Use: zfrog schedule add <url> --cron \"0 2 * * *\"[/]")
        return

    table = Table(title="Schedules")
    table.add_column("ID", style="cyan")
    table.add_column("WHEN")
    table.add_column("URL")
    table.add_column("MODE")
    table.add_column("ACTIVE", justify="center")
    table.add_column("NEXT", style="green")

    for schedule in schedules:
        table.add_row(
            schedule.id,
            describe(schedule.cron),
            schedule.url[:36],
            schedule.mode,
            "yes" if schedule.enabled else "no",
            schedule.next_run or "-",
        )

    console.print(table)


@schedule_app.command("remove")
def schedule_remove(
    schedule_id: str = typer.Argument(..., help="Schedule ID"),
):
    """Remove a schedule."""
    from zfrog.scheduler import ScheduleStore

    if ScheduleStore().remove(schedule_id):
        console.print(f"[green]Schedule {schedule_id} removed.[/]")
    else:
        console.print(f"[red]Schedule {schedule_id} not found.[/]")
        sys.exit(1)


@schedule_app.command("run")
def schedule_run(
    schedule_id: str = typer.Argument(..., help="Schedule ID"),
):
    """Run a schedule now, without waiting for its time."""
    from zfrog.orchestrator import run_job
    from zfrog.scheduler import ScheduleStore

    schedule = ScheduleStore().get(schedule_id)
    if not schedule:
        console.print(f"[red]Schedule {schedule_id} not found.[/]")
        sys.exit(1)

    console.print(f"[dim]Running {schedule.url} ({schedule.mode})...[/]")
    job = JobCreate(url=schedule.url, mode=schedule.mode, max_depth=schedule.max_depth)
    try:
        result = asyncio.run(run_job(job))
    except Exception as e:
        console.print(f"[red]Failed: {e}[/]")
        sys.exit(1)

    console.print(f"[green]Job {result.job_id[:8]} finished[/] — {result.files_count} file(s)")


@app.command()
def scheduler(
    interval: int = typer.Option(30, "--interval", help="Seconds between checks"),
):
    """Run the schedule daemon until interrupted."""
    from zfrog.scheduler import daemon

    console.print(f"[green]Scheduler active[/] — checking every {interval}s. Ctrl+C to stop.")
    try:
        asyncio.run(daemon(interval_s=interval))
    except KeyboardInterrupt:
        console.print("\n[dim]Scheduler stopped.[/]")


@app.command()
def timeline(
    url: str = typer.Argument(..., help="URL of the site"),
    when: str | None = typer.Option(
        None, "--when", "-w", help="See how it was on this date (e.g.: 2026-09-01)"
    ),
    ref: str | None = typer.Option(None, "--ref", help="Open a specific version"),
    page: str | None = typer.Option(None, "--page", help="Show the content of a page"),
    restore: Path | None = typer.Option(
        None, "--restore", help="Restore the version to this folder"
    ),
):
    """Browse a site as it was on a past date."""
    from zfrog.timemachine import TimeMachine, timeline_summary

    machine = TimeMachine(url)

    if when:
        try:
            found = machine.resolve_date(when)
        except ValueError as e:
            console.print(f"[red]{e}[/]")
            sys.exit(1)

        if found is None:
            console.print(f"[yellow]No version saved up to {when}.[/]")
            sys.exit(1)

        entry = next((e for e in machine.timeline() if e.ref == found), None)
        console.print(
            f"[green]Version from {entry.captured_at if entry else found}[/]"
            + (f" — {entry.message}" if entry and entry.message else "")
        )
        ref = ref or found

    entries = machine.timeline()
    if not entries:
        console.print("[dim]No versions saved. Use --versioned on the clone.[/]")
        return

    if restore:
        if not ref:
            ref = entries[-1].ref
        try:
            dest = machine.restore(ref, restore)
        except ValueError as e:
            console.print(f"[red]{e}[/]")
            sys.exit(1)
        files = [f for f in dest.rglob("*") if f.is_file()]
        console.print(f"[green]{len(files)} file(s) restored to {dest}[/]")
        return

    if page:
        if not ref:
            ref = entries[-1].ref
        archived = machine.page(ref, page)
        if archived is None:
            console.print(f"[red]Page {page} does not exist in that version.[/]")
            sys.exit(1)

        html = machine.content(ref, page)
        console.print(f"[bold]{archived.title or archived.path}[/] ({archived.url})")
        if html:
            console.print(Markdown(f"```html\n{html[:2000]}\n```"))
        else:
            console.print("[dim]Content not available (missing blob).[/]")
        return

    if ref:
        pages = machine.at(ref)
        table = Table(title=f"Version {ref}")
        table.add_column("PAGE", style="cyan")
        table.add_column("TITLE")
        table.add_column("SIZE", justify="right")
        for archived in pages:
            table.add_row(archived.path, archived.title or "-", f"{archived.size_bytes:,} B")
        console.print(table)
        return

    console.print(f"[bold]{timeline_summary(entries)}[/]")
    listing = Table(title=f"Versions of {url}")
    listing.add_column("VERSION", style="cyan")
    listing.add_column("WHEN", style="green")
    listing.add_column("PAGES", justify="right")
    listing.add_column("SIZE", justify="right")
    listing.add_column("MESSAGE", style="dim")
    for entry in entries:
        listing.add_row(
            entry.ref[:10],
            entry.captured_at[:19],
            str(entry.pages),
            f"{entry.size_bytes:,} B",
            entry.message[:30],
        )
    console.print(listing)


price_app = typer.Typer(help="Track prices over time.")


app.add_typer(price_app, name="price")


@price_app.command("watch")
def price_watch(
    url: str = typer.Argument(..., help="URL whose latest snapshot will be read"),
):
    """Read a site's latest snapshot and record its prices."""
    from zfrog.pricing import format_change, watch_url

    result = watch_url(url)
    console.print(f"[green]{result['prices']} price(s) recorded[/] at {url}")

    for change in result["changes"]:
        color = "green" if change["direction"] == "down" else "yellow"
        console.print(f"  [{color}]{format_change(change)}[/]")


@price_app.command("changes")
def price_changes(
    url: str = typer.Argument(..., help="URL to query"),
):
    """Show how the recorded prices moved."""
    from zfrog.pricing import PriceTracker

    changes = PriceTracker().changes(url)
    if not changes:
        console.print("[dim]No prices recorded for this site.[/]")
        return

    table = Table(title=f"Prices of {url}")
    table.add_column("ITEM", style="cyan")
    table.add_column("BEFORE", justify="right")
    table.add_column("NOW", justify="right")
    table.add_column("CHANGE", justify="right")
    table.add_column("ALERT", justify="center")

    for change in changes:
        color = "green" if change.direction == "down" else "red" if change.direction == "up" else "white"
        table.add_row(
            change.label,
            f"{change.before:,.2f}",
            f"{change.after:,.2f}",
            f"[{color}]{change.change_pct:+.1f}%[/]",
            "[red]yes[/]" if change.significant else "-",
        )

    console.print(table)


@app.command()
def compare_sites(
    site: list[str] = typer.Option(
        ..., "--site", "-s", help="Label=folder of a clone (may repeat)"
    ),
    markdown: bool = typer.Option(False, "--markdown", help="Print the report in Markdown"),
):
    """Compare several cloned sites side by side."""
    from zfrog.analysis.competitive import compare_directories, to_markdown

    sites: dict[str, Path] = {}
    for entry in site:
        label, _, raw_path = entry.partition("=")
        if not raw_path:
            label, raw_path = Path(entry).name, entry
        path = Path(raw_path)
        if not path.is_dir():
            console.print(f"[red]Folder not found: {path}[/]")
            sys.exit(1)
        sites[label] = path

    if len(sites) < 2:
        console.print("[yellow]Provide at least two sites to compare.[/]")
        sys.exit(1)

    comparison = asyncio.run(compare_directories(sites))

    if markdown:
        console.print(Markdown(to_markdown(comparison)))
        return

    console.print(f"[bold]{comparison.summary}[/]")

    table = Table(title="Comparison")
    table.add_column("SITE", style="cyan")
    table.add_column("PAGES", justify="right")
    table.add_column("WORDS", justify="right")
    table.add_column("PRICES", justify="right")
    for snapshot in comparison.sites:
        table.add_row(
            snapshot.site,
            str(snapshot.pages),
            f"{snapshot.words:,}",
            str(len(snapshot.prices)),
        )
    console.print(table)

    for gap in comparison.content_gaps:
        console.print(f"[yellow]• {gap}[/]")


@app.command()
def trends(
    url: str = typer.Argument(..., help="URL of the site"),
    term: list[str] = typer.Option(..., "--term", "-t", help="Term to track (may repeat)"),
):
    """Track terms across a site's saved history."""
    from zfrog.analysis.trends import summarize, to_markdown
    from zfrog.analysis.trends import trends as compute

    found = compute(url, list(term))
    if not found:
        console.print("[dim]No snapshots saved for this site.[/]")
        return

    console.print(Markdown(to_markdown(url, found)))
    console.print(f"[bold]{summarize(found)}[/]")
