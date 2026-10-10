"""CLI jobs commands — split from cli.py."""

import asyncio
import json
import sys
from pathlib import Path

import typer
from rich.markdown import Markdown
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.table import Table

from zfrog.cli import app
from zfrog.cli._shared import console
from zfrog.models import JobCreate


@app.command()
def clone(
    url: str = typer.Argument(..., help="Target URL to clone"),
    mode: str = typer.Option(
        "auto",
        "--mode",
        "-m",
        help=(
            "Engine mode: auto (default: the probe picks the capture motor), mirror, singlepage, "
            "scrape, delta, extract, analyze, compare, ask, pdf, summarize, entities, translate, "
            "sentiment, tags, video, api_discovery"
        ),
    ),
    depth: int = typer.Option(3, "--depth", "-d", help="Max crawl depth"),
    no_robots: bool = typer.Option(False, "--no-robots", help="Ignore robots.txt"),
    output: str = typer.Option("output", "--output", "-o", help="Output directory"),
    rate_limit: float = typer.Option(1.0, "--rate-limit", "-r", help="Requests per second"),
    pdf_filename: str | None = typer.Option(
        help="Name of the generated PDF (pdf mode; default: index)"
    ),
    versioned: bool = typer.Option(
        False, "--versioned", help="Save a version of the site to history (rollback later)"
    ),
    translate_target: str | None = typer.Option(
        None, "--target", help="Target language in translate mode (e.g.: pt, en, es)"
    ),
    org: str | None = typer.Option(
        None, "--org", "-O", help="Organization that owns the data (isolated in output/orgs/<slug>)"
    ),
):
    """Clone a website."""
    from pathlib import Path

    from zfrog.config import settings
    from zfrog.orchestrator import run_job
    from zfrog.utils.rate_limit import global_limiter
    
    # Override output directory
    settings.output_dir = Path(output)
    
    # Set rate limit
    global_limiter.set_rate(rate_limit)
    
    # Create job
    job = JobCreate(
        url=url,
        mode=mode,
        max_depth=depth,
        respect_robots=not no_robots,
        pdf_filename=pdf_filename,
        versioned=versioned,
        translate_target=translate_target,
        org=org,
    )
    
    console.print(f"[bold green]Cloning {url} with mode={mode}[/]")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Processing...", total=100)
        
        stages = {
            "probing": 10,
            "downloading": 50,
            "processing": 80,
            "packaging": 95,
        }
        
        def on_progress(msg: str):
            # Parse stage from message and update progress
            msg_lower = msg.lower()
            if "probe" in msg_lower:
                progress.update(task, completed=stages["probing"], description=msg[:50])
            elif "download" in msg_lower or "wget" in msg_lower:
                progress.update(task, completed=stages["downloading"], description=msg[:50])
            elif "rewrite" in msg_lower or "clean" in msg_lower:
                progress.update(task, completed=stages["processing"], description=msg[:50])
            elif "package" in msg_lower or "zip" in msg_lower:
                progress.update(task, completed=stages["packaging"], description=msg[:50])
            else:
                progress.update(task, description=msg[:50])
        
        try:
            result = asyncio.run(run_job(job))
            
            progress.update(task, completed=100, description="[bold green]Complete![/]")
            
            # Print results
            console.print("\n[bold]Results:[/]")
            console.print(f"  Job ID: {result.job_id}")
            console.print(f"  Engine: {result.engine_used}")
            console.print(f"  Files: {result.files_count}")
            console.print(f"  Size: {result.total_size_bytes:,} bytes")
            console.print(f"  Duration: {result.duration_seconds:.2f}s")
            console.print(f"  Output: {result.output_path}")
            
        except NotImplementedError as e:
            console.print(f"[bold red]Error: {e}[/]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[bold red]Failed: {e}[/]")
            sys.exit(1)


@app.command()
def probe(
    url: str = typer.Argument(..., help="URL to probe"),
):
    """Probe a URL to detect its type."""
    from zfrog.probe import probe_url
    from zfrog.utils.http import create_client
    
    console.print(f"[bold blue]Probing {url}...[/]")
    
    async def _probe():
        async with create_client() as client:
            return await probe_url(url, client)
    
    result = asyncio.run(_probe())
    
    # Pretty print result
    table = Table(title="Probe Result")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("URL", result.url)
    table.add_row("Is SPA", str(result.is_spa))
    table.add_row("JS Rendering", str(result.has_js_rendering))
    table.add_row("Robots Restricted", str(result.robots_restricted))
    table.add_row("Framework", result.framework or "None")
    table.add_row("Content Type", result.content_type)
    table.add_row("Suggested Engine", result.suggested_engine)
    
    console.print(table)


@app.command()
def summarize_dir(
    output_dir: Path = typer.Argument(..., help="Directory of a clone (mirror/scrape)"),
    url: str = typer.Option("", "--url", "-u", help="Original URL (for the global summary)"),
    max_pages: int = typer.Option(30, "--max-pages", help="Max pages to summarize"),
):
    """Summarize every page of a cloned directory with AI."""

    from zfrog.ai.summarize import summarize_directory, to_markdown

    if not output_dir.is_dir():
        console.print(f"[red]Directory not found: {output_dir}[/]")
        sys.exit(1)

    source_url = url or "(local)"
    result = asyncio.run(summarize_directory(output_dir, source_url, max_pages))

    payload = {
        "url": result["url"],
        "pages": result["pages"],
        "global_summary": result["global_summary"],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "summary.md").write_text(
        to_markdown(source_url, result["global_summary"], result["pages"]), encoding="utf-8"
    )

    console.print(f"[green]Summarized {len(result['pages'])} page(s)[/]")
    global_summary = result["global_summary"]
    if global_summary.get("error"):
        console.print(f"[yellow]{global_summary['error']}[/]")
    elif global_summary.get("summary"):
        console.print(Markdown(global_summary["summary"]))
    console.print(f"[dim]Saved to {output_dir / 'summary.json'} and {output_dir / 'summary.md'}[/]")


@app.command()
def snapshots(
    url: str = typer.Argument(None, help="URL (omit to list everything)"),
):
    """List captured snapshots."""

    from zfrog.diff import list_snapshots

    paths = list_snapshots(url)
    if not paths:
        console.print("[dim]No snapshots saved yet.[/]")
        return

    table = Table(title="Snapshots")
    table.add_column("FILE", style="cyan")
    table.add_column("URL")
    table.add_column("CAPTURED", style="green")
    table.add_column("PAGES", justify="right")

    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        table.add_row(
            path.name,
            data.get("url", "-"),
            data.get("captured_at", "-"),
            str(len(data.get("pages", []))),
        )

    console.print(table)


@app.command()
def diff(
    snapshot_a: Path = typer.Argument(..., help="Older snapshot (path to .json)"),
    snapshot_b: Path = typer.Argument(..., help="Newer snapshot (path to .json)"),
    url: str = typer.Option("", "--url", "-u", help="URL (optional; otherwise read from snapshot)"),
    as_json: bool = typer.Option(False, "--json", help="Print the report as JSON"),
):
    """Compare two snapshots and report changes."""

    from zfrog.diff import diff_snapshots, diff_to_markdown, report_to_dict

    for path in (snapshot_a, snapshot_b):
        if not path.is_file():
            console.print(f"[red]Snapshot not found: {path}[/]")
            sys.exit(1)

    try:
        report = diff_snapshots(snapshot_a, snapshot_b)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    if url:
        report.url = url

    if as_json:
        console.print_json(json.dumps(report_to_dict(report), ensure_ascii=False))
        return

    console.print(Markdown(diff_to_markdown(report)))


@app.command()
def engines():
    """List available engines (built-in and plugins)."""
    from zfrog.engines import ENGINES, engine_source

    table = Table(title="Engines")
    table.add_column("NAME", style="cyan")
    table.add_column("SOURCE", style="green")
    table.add_column("CLASS", style="dim")

    for name in sorted(ENGINES):
        cls = ENGINES[name]
        table.add_row(name, engine_source(name), f"{cls.__module__}.{cls.__name__}")

    console.print(table)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="API host"),
    port: int = typer.Option(8000, "--port", "-p", help="API port"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
):
    """Start the API server."""
    import uvicorn
    uvicorn.run("zfrog.api:app", host=host, port=port, reload=reload)


@app.command()
def jobs():
    """List all jobs."""
    from zfrog.orchestrator import list_jobs
    
    job_list = list_jobs()
    
    if not job_list:
        console.print("[yellow]No jobs found.[/]")
        return
    
    table = Table(title="Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("URL")
    table.add_column("Mode")
    table.add_column("Status")
    table.add_column("Created")
    
    for job in job_list:
        status_color = {
            "completed": "green",
            "failed": "red",
            "running": "yellow",
            "pending": "blue",
        }.get(job.status.value, "white")
        
        table.add_row(
            job.id[:8],
            job.url[:40],
            job.mode,
            f"[{status_color}]{job.status.value}[/]",
            job.created_at.strftime("%Y-%m-%d %H:%M") if job.created_at else "-",
        )
    
    console.print(table)


@app.command()
def cancel(
    job_id: str = typer.Argument(..., help="Job ID to cancel"),
):
    """Cancel a running job."""
    from zfrog.utils.cleanup import cancel_job
    
    if asyncio.run(cancel_job(job_id)):
        console.print(f"[green]Job {job_id} marked for cancellation[/]")
    else:
        console.print(f"[red]Job {job_id} not found[/]")


@app.command()
def config():
    """Show current configuration."""
    from zfrog.config import settings
    
    table = Table(title="Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Redis URL", settings.redis_url)
    table.add_row("Output Dir", str(settings.output_dir))
    table.add_row("Max Concurrent Jobs", str(settings.max_concurrent_jobs))
    table.add_row("Worker Concurrency", str(settings.worker_concurrency))
    table.add_row("Proxy URL", settings.proxy_url or "None")
    
    console.print(table)


@app.command()
def search(
    query: str = typer.Argument(..., help="What to look for"),
    directory: Path | None = typer.Option(
        None, "--dir", "-d", help="Cloned folder (default: the output directory)"
    ),
    semantic: bool = typer.Option(False, "--semantic", help="Search by meaning (needs AI)"),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum number of results"),
    reindex: bool = typer.Option(False, "--reindex", help="Index the folder before searching"),
):
    """Search inside cloned content."""
    from zfrog.config import settings
    from zfrog.search import SearchIndex

    target = directory or Path(settings.output_dir)
    index = SearchIndex()

    if reindex:
        count = index.index_directory(target)
        console.print(f"[dim]{count} page(s) indexed in {target}[/]")

    mode = "semantic" if semantic else "fulltext"
    hits = index.search(query, mode=mode, limit=limit)

    if not hits:
        console.print(f"[yellow]Nothing found for '{query}'.[/]")
        if semantic:
            console.print("[dim]Semantic search needs an AI model configured.[/]")
        return

    table = Table(title=f"Results for '{query}' ({mode})")
    table.add_column("WHERE", style="cyan")
    table.add_column("SNIPPET")
    table.add_column("SCORE", justify="right", style="green")

    for hit in hits:
        table.add_row(hit.title or hit.path, hit.snippet, f"{hit.score:.3f}")

    console.print(table)


@app.command()
def analytics(
    engine: str | None = typer.Option(None, "--engine", "-e", help="Filter by engine"),
):
    """Show which engines work best (success rate, speed, size)."""
    from zfrog.analytics import MetricsStore, format_engine_table

    store = MetricsStore()
    stats = store.engine_stats(engine)
    totals = store.totals()

    if not stats:
        console.print("[dim]No runs recorded yet.[/]")
        return

    console.print(
        f"[bold]{totals['runs']}[/] run(s) — "
        f"success {totals['success_rate'] * 100:.1f}% — "
        f"{totals['bytes']:,} bytes — avg {totals['avg_duration_s']:.2f}s"
    )

    table = Table(title="Performance by engine")
    table.add_column("ENGINE", style="cyan")
    table.add_column("RUNS", justify="right")
    table.add_column("SUCCESS", justify="right", style="green")
    table.add_column("FAILURES", justify="right", style="red")
    table.add_column("AVG TIME", justify="right")
    table.add_column("AVG SIZE", justify="right")

    for row in format_engine_table(stats):
        table.add_row(
            row["engine"],
            str(row["runs"]),
            row["success_rate"],
            str(row["failed"]),
            f"{row['avg_duration_s']:.2f}s",
            f"{int(row['avg_bytes']):,} B",
        )

    console.print(table)


@app.command()
def audit(
    limit: int = typer.Option(50, "--limit", "-n", help="How many entries to show"),
    action: str | None = typer.Option(None, "--action", "-a", help="Filter by action"),
    actor: str | None = typer.Option(None, "--actor", help="Filter by origin"),
):
    """Show the audit trail of actions."""
    from zfrog.utils.audit import AuditLog

    entries = AuditLog().read(limit=limit, action=action, actor=actor)
    if not entries:
        console.print("[dim]No entries in the audit log.[/]")
        return

    table = Table(title="Audit")
    table.add_column("WHEN", style="green")
    table.add_column("ACTION", style="cyan")
    table.add_column("ORIGIN")
    table.add_column("TARGET")
    table.add_column("RESULT")

    for entry in entries:
        color = "green" if entry.outcome == "ok" else "red"
        table.add_row(
            entry.timestamp[:19],
            entry.action,
            entry.actor,
            entry.target[:40],
            f"[{color}]{entry.outcome}[/]",
        )

    console.print(table)


@app.command()
def safety(
    directory: Path = typer.Argument(..., help="Cloned folder to scan"),
):
    """Scan cloned content for malware and phishing indicators."""
    from zfrog.pipeline.safety import scan_directory

    if not directory.is_dir():
        console.print(f"[red]Folder not found: {directory}[/]")
        sys.exit(1)

    report = scan_directory(directory)
    colors = {"clean": "green", "low": "yellow", "medium": "yellow", "high": "red"}
    color = colors.get(report.risk, "white")

    console.print(f"[{color}]{report.summary}[/]")

    if not report.findings:
        return

    table = Table(title="Findings")
    table.add_column("SEVERITY", style="red")
    table.add_column("TYPE", style="cyan")
    table.add_column("FILE")
    table.add_column("DETAIL")

    for finding in report.findings:
        table.add_row(finding.severity, finding.kind, finding.file[:40], finding.detail[:60])

    console.print(table)


@app.command()
def ipfs(
    directory: Path = typer.Argument(..., help="Cloned folder to publish"),
    gateway: str = typer.Option("https://ipfs.io", "--gateway", help="Gateway to build the link"),
):
    """Publish a clone to IPFS through a local node."""
    from zfrog.storage.ipfs import gateway_url, publish_output

    if not directory.is_dir():
        console.print(f"[red]Folder not found: {directory}[/]")
        sys.exit(1)

    try:
        result = asyncio.run(publish_output(directory))
    except RuntimeError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Published[/] — {result.files} file(s), {result.size:,} bytes")
    console.print(f"CID: [cyan]{result.cid}[/]")
    console.print(f"[dim]{gateway_url(result.cid, gateway)}[/]")
