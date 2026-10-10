"""CLI workspaces commands — split from cli.py."""

import asyncio
import json
import sys
from pathlib import Path

import typer
from rich.markdown import Markdown
from rich.table import Table

from zfrog.cli import app
from zfrog.cli._shared import console, settings_region


@app.command()
def login(
    url: str = typer.Argument(..., help="URL of the site where you will sign in"),
    no_wait: bool = typer.Option(
        False, "--no-wait", help="Do not wait for Enter (useful in automation)"
    ),
):
    """Open a browser so you can sign in, then save the session."""
    from zfrog.session import capture_session

    console.print(f"[green]Opening the browser at {url}[/]")
    console.print("[dim]Sign in to your account, then come back here and press Enter.[/]")

    try:
        state = asyncio.run(capture_session(url, wait_for_enter=not no_wait))
    except Exception as e:
        console.print(f"[red]Failed: {e}[/]")
        sys.exit(1)

    cookies = len(state.get("cookies", []))
    console.print(
        f"[green]Session saved[/] — {cookies} cookie(s). Upcoming clones of this site use it."
    )


@app.command()
def sessions():
    """List saved login sessions."""
    from zfrog.session import SessionStore

    entries = SessionStore().list()
    if not entries:
        console.print("[dim]No saved sessions. Use: zfrog login <url>[/]")
        return

    table = Table(title="Saved sessions")
    table.add_column("SITE", style="cyan")
    table.add_column("WHEN", style="green")
    table.add_column("COOKIES", justify="right")

    for entry in entries:
        table.add_row(entry["domain"], entry["saved_at"], str(entry["cookies"]))

    console.print(table)


@app.command()
def logout(
    domain: str = typer.Argument(..., help="Site of the session (e.g.: example.com)"),
):
    """Delete a saved login session."""
    from zfrog.session import SessionStore

    if SessionStore().delete(domain):
        console.print(f"[green]Session for {domain} deleted.[/]")
    else:
        console.print(f"[red]No saved session for {domain}.[/]")
        sys.exit(1)


workflow_app = typer.Typer(help="Saved step sequences (pipelines).")


app.add_typer(workflow_app, name="workflow")


@workflow_app.command("list")
def workflow_list():
    """List the saved workflows."""
    from zfrog.workflows import WorkflowStore

    workflows = WorkflowStore().list()
    if not workflows:
        console.print("[dim]No saved workflows.[/]")
        return

    table = Table(title="Workflows")
    table.add_column("ID", style="cyan")
    table.add_column("NAME")
    table.add_column("STEPS", justify="right")
    table.add_column("SEQUENCE", style="dim")

    for workflow in workflows:
        table.add_row(
            workflow.id,
            workflow.name,
            str(len(workflow.steps)),
            " → ".join(step.type for step in workflow.steps),
        )

    console.print(table)


@workflow_app.command("show")
def workflow_show(
    workflow_id: str = typer.Argument(..., help="Workflow ID"),
):
    """Show the steps of a workflow."""
    from zfrog.workflows import WorkflowStore

    workflow = WorkflowStore().get(workflow_id)
    if not workflow:
        console.print(f"[red]Workflow {workflow_id} not found.[/]")
        sys.exit(1)

    console.print(f"[bold]{workflow.name}[/] [dim]({workflow.id})[/]")
    for index, step in enumerate(workflow.steps, 1):
        params = ", ".join(f"{k}={v}" for k, v in step.params.items()) or "-"
        console.print(f"  {index}. [cyan]{step.type}[/] [dim]({params})[/]")


@workflow_app.command("run")
def workflow_run(
    workflow_id: str = typer.Argument(..., help="Workflow ID"),
):
    """Run a workflow from start to finish."""
    from zfrog.workflows import WorkflowStore, run_workflow

    workflow = WorkflowStore().get(workflow_id)
    if not workflow:
        console.print(f"[red]Workflow {workflow_id} not found.[/]")
        sys.exit(1)

    def on_progress(message: str) -> None:
        console.print(f"[dim]{message}[/]")

    result = asyncio.run(run_workflow(workflow, on_progress=on_progress))

    for step in result.steps:
        color = {"ok": "green", "failed": "red", "skipped": "dim"}.get(step.status, "white")
        console.print(f"  [{color}]{step.status:7}[/] {step.type:10} {step.detail}")

    if result.status == "failed":
        console.print(f"[red]Workflow failed: {result.error}[/]")
        sys.exit(1)

    console.print("[green]Workflow finished.[/]")


chat_app = typer.Typer(help="Talk to already cloned sites, keeping the history.")


app.add_typer(chat_app, name="chat")


@chat_app.command("ask")
def chat_ask(
    question: str = typer.Argument(..., help="Question in natural language"),
    site: list[str] = typer.Option(
        [], "--site", "-s", help="Folder of a cloned site, as 'Label=path' (may repeat)"
    ),
    conversation: str | None = typer.Option(
        None, "--conversation", "-c", help="Continue an existing conversation (id)"
    ),
    show_history: bool = typer.Option(False, "--history", help="Show the history at the end"),
):
    """Ask a question, keeping the conversation context."""
    from zfrog.ai.chat import ChatSession

    session = ChatSession()
    if conversation:
        if session.load(conversation) is None:
            console.print(f"[red]Conversation {conversation} not found.[/]")
            sys.exit(1)
    elif not site:
        console.print("[red]Provide at least one --site, or continue with --conversation.[/]")
        sys.exit(1)

    for entry in site:
        label, _, raw_path = entry.partition("=")
        if not raw_path:
            label, raw_path = Path(entry).name, entry
        path = Path(raw_path)
        if not path.is_dir():
            console.print(f"[red]Folder not found: {path}[/]")
            sys.exit(1)
        session.add_site(label, path)

    result = asyncio.run(session.ask(question))
    console.print(Markdown(result["answer"]))
    console.print()

    for i, citation in enumerate(result["citations"], 1):
        url = citation.get("url") or citation.get("site") or ""
        console.print(f"[dim][{i}] {url} — {citation.get('path', '')}[/]")

    saved = session.save()
    console.print(f"[dim]Conversation {saved.stem} saved at {saved}[/]")

    if show_history:
        console.print()
        for turn in session.history():
            label = "You" if turn.role == "user" else "Zfrog"
            console.print(f"[bold]{label}:[/] {turn.content[:200]}")


@chat_app.command("list")
def chat_list():
    """List saved conversations."""
    from zfrog.ai.chat import ChatSession

    directory = ChatSession().history_dir
    files = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not files:
        console.print("[dim]No saved conversations yet.[/]")
        return

    table = Table(title="Conversations")
    table.add_column("ID", style="cyan")
    table.add_column("TURNS", justify="right")
    table.add_column("SITES", style="dim")

    session = ChatSession()
    for path in files:
        conversation = session.load(path.stem)
        if conversation is None:
            continue
        table.add_row(path.stem, str(len(conversation.turns)), ", ".join(conversation.sites)[:40])

    console.print(table)


@app.command()
def graph(
    directory: Path = typer.Argument(..., help="Cloned folder to map"),
    dot: bool = typer.Option(False, "--dot", help="Print in Graphviz format"),
):
    """Map the relationships between entities found in cloned pages."""
    from zfrog.ai.entities import extract_entities
    from zfrog.ai.graph import build_graph, describe, to_dot, to_json
    from zfrog.utils.text import extract_text

    if not directory.is_dir():
        console.print(f"[red]Folder not found: {directory}[/]")
        sys.exit(1)

    pages: list[dict] = []
    for path in sorted(f for f in directory.rglob("*.html") if f.is_file()):
        html = path.read_text(encoding="utf-8", errors="replace")
        text = extract_text(html)
        result = asyncio.run(extract_entities(text))
        pages.append({"url": str(path), "entities": result.get("entities", []), "text": text})

    built = build_graph(pages)

    if dot:
        console.print(to_dot(built))
        return

    console.print(f"[bold]{describe(built)}[/]")
    payload = to_json(built)
    out = directory / "graph.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[dim]Saved to {out}[/]")

    if built.nodes:
        table = Table(title="Entities")
        table.add_column("NAME", style="cyan")
        table.add_column("TYPE")
        table.add_column("MENTIONS", justify="right")
        for node in sorted(built.nodes, key=lambda n: n.mentions, reverse=True)[:15]:
            table.add_row(node.name, node.type, str(node.mentions))
        console.print(table)


@app.command()
def tos(
    url: str = typer.Argument(..., help="URL of the site to check"),
):
    """Check robots.txt and Terms of Use for restrictions on automated collection."""
    from zfrog.ai.tos import check_site

    report = asyncio.run(check_site(url))

    colors = {"clear": "green", "caution": "yellow", "restricted": "red"}
    color = colors.get(report.risk, "white")
    console.print(f"[{color}]{report.summary}[/]")

    if report.error:
        console.print(f"[yellow]Warning: {report.error}[/]")

    if not report.findings:
        return

    table = Table(title="Signals found")
    table.add_column("SEVERITY", style="red")
    table.add_column("TYPE", style="cyan")
    table.add_column("DETAIL")
    table.add_column("EXCERPT", style="dim")

    for finding in report.findings:
        table.add_row(finding.severity, finding.kind, finding.detail[:50], finding.evidence[:50])

    console.print(table)


@app.command()
def watermark(
    directory: Path = typer.Argument(..., help="Cloned folder to mark"),
    source: str = typer.Option("", "--source", help="Source URL to record"),
    verify_only: bool = typer.Option(False, "--verify", help="Only verify, without marking"),
):
    """Mark (or verify) cloned content with provenance metadata."""
    from zfrog.pipeline.watermark import (
        make_mark,
        verify_directory,
        watermark_directory,
    )

    if not directory.is_dir():
        console.print(f"[red]Folder not found: {directory}[/]")
        sys.exit(1)

    if verify_only:
        summary = asyncio.run(verify_directory(directory))
        if not summary["marked"]:
            console.print("[dim]No files marked in this folder.[/]")
            return
        console.print(f"[green]{summary['marked']} of {summary['files']} file(s) marked[/]")
        for mark in summary["marks"]:
            console.print(f"  {mark}")
        return

    mark = make_mark(source or str(directory))
    summary = asyncio.run(watermark_directory(directory, mark, source))
    console.print(f"[green]{summary['marked']} file(s) marked[/] — {summary['mark']}")


@app.command()
def regions(
    url: str = typer.Argument(..., help="URL that would be processed"),
):
    """Show which region would process a URL and why."""
    from zfrog.regions import data_residency_note, known_regions, route

    available = known_regions()
    decision = route(url, available)

    table = Table(title="Regions")
    table.add_column("REGION", style="cyan")
    table.add_column("LATENCY", justify="right")
    table.add_column("WORKERS", justify="right")
    table.add_column("ACTIVE", justify="center")

    for region in available:
        table.add_row(
            region.name,
            f"{region.latency_ms} ms",
            str(region.workers),
            "yes" if region.enabled else "no",
        )

    console.print(table)
    console.print(f"[green]Chosen: {decision.region}[/] — {decision.reason}")
    console.print(f"[dim]{data_residency_note(url, decision.region)}[/]")


key_app = typer.Typer(help="API access keys.")


app.add_typer(key_app, name="key")


@key_app.command("create")
def key_create(
    name: str = typer.Argument(..., help="Name to identify the key"),
    role: str = typer.Option("viewer", "--role", "-r", help="viewer, operator or admin"),
    org: str | None = typer.Option(
        None, "--org", "-O", help="Organization that owns this key's data"
    ),
):
    """Create an API key (the secret is shown only once)."""
    from zfrog.auth import ApiKeyStore

    try:
        secret, key = ApiKeyStore().create(name, role, org=org or "")
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Key created[/] ({key.id}, role {key.role})")
    if key.org:
        console.print(f"[dim]Organization: {key.org} — data lives in output/orgs/{key.org}[/]")
    console.print(f"[bold]{secret}[/]")
    console.print("[yellow]Save it now: the secret is not stored and cannot be recovered.[/]")


@key_app.command("list")
def key_list():
    """List API keys (never shows the secret)."""
    from zfrog.auth import ApiKeyStore

    keys = ApiKeyStore().list()
    if not keys:
        console.print("[dim]No keys created.[/]")
        return

    table = Table(title="Keys")
    table.add_column("ID", style="cyan")
    table.add_column("NAME")
    table.add_column("ROLE", style="green")
    table.add_column("ACTIVE", justify="center")
    table.add_column("LAST USED", style="dim")

    for key in keys:
        table.add_row(
            key.id, key.name, key.role, "yes" if key.enabled else "no", key.last_used_at or "-"
        )

    console.print(table)


@key_app.command("revoke")
def key_revoke(
    key_id: str = typer.Argument(..., help="Key ID"),
):
    """Revoke an API key."""
    from zfrog.auth import ApiKeyStore

    if ApiKeyStore().revoke(key_id):
        console.print(f"[green]Key {key_id} revoked.[/]")
    else:
        console.print(f"[red]Key {key_id} not found.[/]")
        sys.exit(1)


market_app = typer.Typer(help="Marketplace of workflows, plugins and templates.")


app.add_typer(market_app, name="market")


@market_app.command("list")
def market_list(
    kind: str | None = typer.Option(None, "--kind", "-k", help="workflow, plugin or template"),
    query: str | None = typer.Option(None, "--query", "-q", help="Search by text"),
):
    """List published assets."""
    from zfrog.marketplace import Marketplace

    assets = Marketplace().list(kind=kind, query=query)
    if not assets:
        console.print("[dim]Nothing published yet.[/]")
        return

    table = Table(title="Marketplace")
    table.add_column("ID", style="cyan")
    table.add_column("TYPE")
    table.add_column("NAME")
    table.add_column("AUTHOR", style="dim")
    table.add_column("INSTALLS", justify="right")
    table.add_column("RATING", justify="right", style="green")

    for asset in assets:
        table.add_row(
            asset.id,
            asset.kind,
            asset.name[:28],
            asset.author or "-",
            str(asset.installs),
            f"{asset.rating:.1f}" if asset.rating_count else "-",
        )

    console.print(table)


@market_app.command("install")
def market_install(
    asset_id: str = typer.Argument(..., help="Asset ID"),
):
    """Install a published asset."""
    from zfrog.marketplace import Marketplace

    try:
        result = Marketplace().install(asset_id)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    color = "green" if result["installed"] else "red"
    console.print(f"[{color}]{result['name']}[/] — {result['detail']}")
    if result["target"]:
        console.print(f"[dim]{result['target']}[/]")


@app.command()
def annotate(
    job_id: str = typer.Argument(..., help="Job (copy) ID"),
    path: str = typer.Argument(..., help="Page within the copy"),
    text: str = typer.Argument(..., help="Comment"),
    selector: str = typer.Option("", "--selector", "-s", help="CSS selector within the page"),
    author: str = typer.Option("", "--author", "-a", help="Who is commenting"),
    tag: list[str] = typer.Option([], "--tag", "-t", help="Tag (may repeat)"),
):
    """Leave a comment on a cloned page."""
    from zfrog.annotations import AnnotationStore

    try:
        note = AnnotationStore().add(
            job_id, path, text, author=author, selector=selector, tags=list(tag)
        )
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Comment {note.id} added[/] to {note.path}")


@app.command()
def annotations(
    job_id: str = typer.Argument(..., help="Job ID"),
    open_only: bool = typer.Option(False, "--open", help="Show only unresolved ones"),
):
    """List the comments on a clone."""
    from zfrog.annotations import AnnotationStore

    store = AnnotationStore()
    notes = store.list(job_id=job_id, resolved=False if open_only else None)

    if not notes:
        console.print("[dim]No comments on this copy.[/]")
        return

    counts = store.counts(job_id)
    console.print(
        f"[bold]{counts['total']}[/] comment(s) — "
        f"{counts['open']} open, {counts['resolved']} resolved"
    )

    for note in notes:
        mark = "[green]x[/]" if note.resolved else "[ ]"
        console.print(
            f"{mark} [cyan]{note.id}[/] {note.path} [dim]({note.author or 'anonymous'})[/]"
        )
        if note.selector:
            console.print(f"    [dim]selector: {note.selector}[/]")
        console.print(f"    {note.text}")
        for reply in note.replies:
            console.print(f"    [dim]↳ {reply.get('author', '')}: {reply.get('text', '')}[/]")


domain_app = typer.Typer(help="Domain profiles (vocabulary and instructions per area).")


app.add_typer(domain_app, name="domain")


@domain_app.command("list")
def domain_list():
    """List the built-in and saved domain profiles."""
    from zfrog.ai.domains import DomainProfileStore

    store = DomainProfileStore()
    rows = store.list() + store.builtin()

    table = Table(title="Domain profiles")
    table.add_column("ID", style="cyan")
    table.add_column("NAME")
    table.add_column("SOURCE", style="dim")
    table.add_column("TERMS", justify="right")
    table.add_column("EXAMPLES", justify="right")

    saved_ids = {p.id for p in store.list()}
    for profile in rows:
        table.add_row(
            profile.id,
            profile.name,
            "saved" if profile.id in saved_ids else "built-in",
            str(len(profile.terminology)),
            str(len(profile.examples)),
        )

    console.print(table)


@domain_app.command("suggest")
def domain_suggest(
    url: str = typer.Argument(..., help="URL or text to classify"),
):
    """Suggest a domain profile for a URL or text."""
    from zfrog.ai.domains import resolve, suggest_profile

    profile_id = suggest_profile(url, url)
    if not profile_id:
        console.print("[dim]No profile suggested for this.[/]")
        return

    profile = resolve(profile_id)
    console.print(f"[green]{profile_id}[/] — {profile.description if profile else ''}")


worker_app = typer.Typer(help="Workers and assignment by region.")


app.add_typer(worker_app, name="worker")


@worker_app.command("list")
def worker_list():
    """List registered workers."""
    from zfrog.workers import WorkerRegistry

    registry = WorkerRegistry()
    registry.reap()
    workers = registry.list(alive_only=False)

    if not workers:
        console.print("[dim]No workers registered.[/]")
        return

    table = Table(title="Workers")
    table.add_column("ID", style="cyan")
    table.add_column("REGION", style="green")
    table.add_column("BUSY", justify="right")
    table.add_column("FREE", justify="right")
    table.add_column("ALIVE", justify="center")
    table.add_column("SEEN", style="dim")

    for worker in workers:
        table.add_row(
            worker.id,
            worker.region,
            f"{worker.running}/{worker.capacity}",
            str(worker.free()),
            "yes" if registry.alive(worker.id) else "no",
            worker.last_seen[:19],
        )

    console.print(table)


@worker_app.command("assign")
def worker_assign(
    url: str = typer.Argument(..., help="URL that would be processed"),
    region: str | None = typer.Option(None, "--region", "-r", help="Force a region"),
):
    """Show which worker would take a job, and why."""
    from zfrog.workers import WorkerRegistry

    assignment = WorkerRegistry().assign(url, preferred_region=region)
    if assignment.worker is None:
        console.print(f"[yellow]No worker available[/] — {assignment.reason}")
        return

    console.print(f"[green]{assignment.worker.id}[/] in {assignment.worker.region}")
    console.print(f"[dim]{assignment.reason}[/]")


@worker_app.command("run")
def worker_run(
    region: str | None = typer.Option(None, "--region", "-r", help="Region of this worker"),
    capacity: int = typer.Option(1, "--capacity", "-c", help="Concurrent jobs"),
    interval: int = typer.Option(20, "--interval", help="Seconds between heartbeats"),
):
    """Register this machine as a worker and keep its heartbeat."""
    from zfrog.workers import WorkerRegistry, current_worker_id, heartbeat_loop

    worker_id = current_worker_id()
    target = region or settings_region()

    # Register explicitly: the heartbeat loop only re-registers a missing worker,
    # so the region and capacity the user asked for have to land here.
    WorkerRegistry().register(worker_id, target, capacity=capacity)

    console.print(f"[green]Worker {worker_id}[/] in region {target} (capacity {capacity}).")
    console.print("[dim]Ctrl+C to stop.[/]")

    try:
        asyncio.run(heartbeat_loop(worker_id, interval_s=interval))
    except KeyboardInterrupt:
        console.print("\n[dim]Worker stopped.[/]")
