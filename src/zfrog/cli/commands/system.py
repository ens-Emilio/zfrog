"""CLI system commands — split from cli.py."""

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from rich.markdown import Markdown
from rich.table import Table

from zfrog.cli import app
from zfrog.cli._shared import (
    _find_project_root,
    _redis_state,
    _run_dev,
    console,
)


@app.command()
def dev(
    api_port: int = typer.Option(8000, "--api-port", help="API port"),
    web_port: int = typer.Option(3067, "--web-port", help="Dashboard port"),
    host: str = typer.Option("127.0.0.1", "--host", help="API host"),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Auto-reload API on changes"),
    install: bool = typer.Option(True, "--install/--no-install", help="Run npm install if needed"),
):
    """Run API and dashboard together with one command.

    Redis is not started here — `docker compose up` does that, and a local server may
    already be the user's own. Its state is reported so the panel's "pending" warning
    is not a surprise discovered in another window.
    """
    try:
        root = _find_project_root()
    except RuntimeError as e:
        console.print(f"[bold red]{e}[/]")
        raise typer.Exit(1)

    dashboard_dir = root / "dashboard"

    if not shutil.which("npm"):
        console.print("[bold red]npm not found. Install Node.js to run the dashboard.[/]")
        raise typer.Exit(1)

    if install and not (dashboard_dir / "node_modules").is_dir():
        console.print("[yellow]Installing dashboard dependencies (npm install)...[/]")
        try:
            subprocess.run(["npm", "install"], cwd=dashboard_dir, check=True)
        except subprocess.CalledProcessError:
            console.print("[bold red]npm install failed.[/]")
            raise typer.Exit(1)

    redis_ok, redis_url = _redis_state()
    if not redis_ok:
        console.print(
            f"[yellow]Redis did not respond[/] at [cyan]{redis_url}[/]. "
            "The panel and jobs work without it (they run in-process); "
            "what is left out is the queue between workers and live progress."
        )
        console.print(
            "[dim]To enable it:[/] [cyan]redis-server[/] "
            "[dim]or[/] [cyan]docker compose up -d redis[/]"
        )

    try:
        exit_code = asyncio.run(_run_dev(host, api_port, web_port, dashboard_dir, reload, redis_ok))
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/]")
        return

    raise typer.Exit(exit_code)


@app.command()
def operator(
    interval: float = typer.Option(5.0, "--interval", help="Seconds between reconciliations"),
):
    """Run the Kubernetes operator (watches ZfrogJob resources)."""
    from zfrog.k8s.operator import Operator

    console.print(f"[green]Operator active[/] — reconciling every {interval}s. Ctrl+C to stop.")
    try:
        asyncio.run(Operator(reconcile_interval_s=interval).run())
    except KeyboardInterrupt:
        console.print("\n[dim]Operator stopped.[/]")


@app.command()
def cost():
    """Show the estimated cost per engine (needs the cost rates configured)."""
    from zfrog.analytics import MetricsStore, format_cost, rates_from_settings

    rates = rates_from_settings()
    rows = MetricsStore().cost_by_engine(rates)

    if not rows:
        console.print("[dim]No runs recorded yet.[/]")
        return

    table = Table(title=f"Estimated cost ({rates.currency})")
    table.add_column("ENGINE", style="cyan")
    table.add_column("RUNS", justify="right")
    table.add_column("DATA", justify="right")
    table.add_column("TIME", justify="right")
    table.add_column("COST", justify="right", style="green")
    table.add_column("PER RUN", justify="right")

    for row in rows:
        table.add_row(
            row["engine"],
            str(row["runs"]),
            f"{row['bytes']:,} B",
            f"{row['duration_s']:.1f}s",
            format_cost(row["cost"], rates.currency),
            format_cost(row["cost_per_run"], rates.currency),
        )

    console.print(table)

    if not any((rates.per_gb_transfer, rates.per_cpu_hour, rates.per_gb_month)):
        console.print(
            "[yellow]No rates configured — the values are zero.[/]\n"
            "[dim]Set ZFROG_COST_PER_GB_TRANSFER, ZFROG_COST_PER_CPU_HOUR and "
            "ZFROG_COST_PER_GB_MONTH.[/]"
        )


integ_app = typer.Typer(help="External destinations (Sheets, Airtable, Notion).")


app.add_typer(integ_app, name="integrations")


@integ_app.command("list")
def integrations_list():
    """List configured destinations."""
    from zfrog.integrations.base import DestinationStore, redact

    destinations = DestinationStore().list()
    if not destinations:
        console.print("[dim]No destinations configured.[/]")
        return

    for destination in destinations:
        console.print(f"  [cyan]{destination.name}[/] ({destination.kind}) — {redact(destination)}")


@integ_app.command("push")
def integrations_push(
    name: str = typer.Argument(..., help="Name of the destination"),
    file: Path = typer.Argument(..., help="JSON file with a list of records"),
):
    """Send records to a destination."""
    from zfrog.integrations.base import DestinationStore, client_for

    destination = DestinationStore().get(name)
    if destination is None:
        console.print(f"[red]Destination {name} not found.[/]")
        sys.exit(1)

    if not file.is_file():
        console.print(f"[red]File not found: {file}[/]")
        sys.exit(1)

    records = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        console.print("[red]The file must contain a list of records.[/]")
        sys.exit(1)

    result = asyncio.run(client_for(destination).push(destination, records))
    console.print(f"[green]{result.created} created[/], {result.updated} updated")

    for error in result.errors:
        console.print(f"[red]{error}[/]")


user_app = typer.Typer(help="Users and organizations.")


app.add_typer(user_app, name="user")


@user_app.command("create")
def user_create(
    email: str = typer.Argument(..., help="User's email"),
    name: str = typer.Option("", "--name", "-n", help="Display name"),
    role: str = typer.Option("viewer", "--role", "-r", help="viewer, operator or admin"),
    password: str = typer.Option("", "--password", "-p", help="Password (empty = SSO only)"),
    org: list[str] = typer.Option([], "--org", "-o", help="Organization (may repeat)"),
):
    """Create a local user."""
    from zfrog.users import UserStore

    try:
        user, secret = UserStore().create(email, name=name, role=role, password=password, orgs=list(org))
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]User created[/] {user.email} ({user.id}, role {user.role})")
    if secret:
        console.print(f"[bold]{secret}[/]")
        console.print("[yellow]Save it now: the password is not stored in plain text.[/]")
    else:
        console.print("[dim]No password: sign in via SSO only.[/]")


@user_app.command("list")
def user_list():
    """List users."""
    from zfrog.users import UserStore

    users = UserStore().list()
    if not users:
        console.print("[dim]No users created.[/]")
        return

    table = Table(title="Users")
    table.add_column("ID", style="cyan")
    table.add_column("EMAIL")
    table.add_column("NAME")
    table.add_column("ROLE", style="green")
    table.add_column("ORGANIZATIONS", style="dim")
    table.add_column("ACTIVE", justify="center")

    for user in users:
        table.add_row(
            user.id,
            user.email,
            user.name or "-",
            user.role,
            ", ".join(user.orgs) or "-",
            "yes" if user.enabled else "no",
        )

    console.print(table)


@user_app.command("disable")
def user_disable(
    user_id: str = typer.Argument(..., help="User ID"),
):
    """Disable a user."""
    from zfrog.users import UserStore

    if UserStore().set_enabled(user_id, False):
        console.print(f"[green]User {user_id} disabled.[/]")
    else:
        console.print(f"[red]User {user_id} not found.[/]")
        sys.exit(1)


org_app = typer.Typer(help="Organizations and data isolation.")


app.add_typer(org_app, name="org")


@org_app.command("create")
def org_create(
    name: str = typer.Argument(..., help="Name of the organization"),
    owner: str = typer.Option(..., "--owner", help="ID of the owner user"),
):
    """Create an organization."""
    from zfrog.users import OrgStore

    try:
        org = OrgStore().create(name, owner)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Organization created[/] {org.name} ({org.id})")


@org_app.command("list")
def org_list():
    """List organizations."""
    from zfrog.users import OrgStore
    from zfrog.workspaces import WorkspaceManager

    orgs = OrgStore().list()
    if not orgs:
        console.print("[dim]No organizations created.[/]")
        return

    manager = WorkspaceManager()
    table = Table(title="Organizations")
    table.add_column("ID", style="cyan")
    table.add_column("NAME")
    table.add_column("OWNER", style="dim")
    table.add_column("MEMBERS", justify="right")
    table.add_column("DATA", justify="center")

    for org in orgs:
        table.add_row(
            org.id,
            org.name,
            org.owner,
            str(len(org.members)),
            "yes" if manager.exists(org.id) else "-",
        )

    console.print(table)


@org_app.command("add-member")
def org_add_member(
    org_id: str = typer.Argument(..., help="Organization ID"),
    user_id: str = typer.Argument(..., help="User ID"),
    role: str = typer.Option("viewer", "--role", "-r", help="Role within the organization"),
):
    """Add a user to an organization."""
    from zfrog.users import add_member

    try:
        add_member(org_id, user_id, role)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]{user_id} added to {org_id} as {role}.[/]")


market_sync_app = typer.Typer(help="Sync a remote marketplace index.")


app.add_typer(market_sync_app, name="market-index")


@market_sync_app.command("build")
def market_index_build(
    output: Path = typer.Option(Path("marketplace-index.json"), "--output", "-o", help="Output file"),
    source: str = typer.Option("", "--source", help="Name of the source (for the header)"),
):
    """Build an index of the locally published marketplace assets."""
    from zfrog.marketplace_index import (
        index_from_marketplace,
        index_summary,
        write_index,
    )

    index = index_from_marketplace(source=source)
    path = write_index(output, index)
    console.print(f"[green]Index written[/] to {path}")
    console.print(f"[dim]{index_summary(index)}[/]")


@market_sync_app.command("sync")
def market_index_sync(
    index_url: str = typer.Argument(..., help="URL of the remote index"),
):
    """Import the assets of a remote index into the local marketplace."""
    from zfrog.marketplace_index import fetch_index, merge_index

    try:
        index = asyncio.run(fetch_index(index_url))
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    result = merge_index(index)
    console.print(
        f"[green]{result.added} new[/], {result.updated} updated, "
        f"{result.unchanged} unchanged, {result.skipped} skipped"
    )
    for error in result.errors:
        console.print(f"[yellow]{error}[/]")


totp_app = typer.Typer(help="Two-factor codes for your own account.")


app.add_typer(totp_app, name="totp")


@totp_app.command("add")
def totp_add(
    name: str = typer.Argument(..., help="Name to identify the account"),
    secret: str = typer.Argument(..., help="Base32 secret (what the site shows)"),
    issuer: str = typer.Option("", "--issuer", help="Name of the service"),
):
    """Register a two-factor account."""
    from zfrog.totp import TotpStore

    try:
        account = TotpStore().add(name, secret, issuer)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(
        f"[green]Account {account.name} registered[/] — secret stored with 0600 permission"
    )


@totp_app.command("code")
def totp_code(
    name: str = typer.Argument(..., help="Name of the account"),
):
    """Show the current code."""
    from zfrog.totp import TotpStore, seconds_remaining

    try:
        code = TotpStore().code(name)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[bold]{code}[/] [dim](valid for {seconds_remaining()}s)[/]")


@totp_app.command("list")
def totp_list():
    """List registered two-factor accounts."""
    from zfrog.totp import TotpStore

    accounts = TotpStore().list()
    if not accounts:
        console.print("[dim]No accounts registered.[/]")
        return

    table = Table(title="Two-factor accounts")
    table.add_column("NAME", style="cyan")
    table.add_column("SERVICE")
    for account in accounts:
        table.add_row(account.get("name", ""), account.get("issuer", "") or "-")
    console.print(table)


@app.command()
def dataset(
    directory: Path = typer.Argument(..., help="Cloned folder to turn into a dataset"),
    kind: str = typer.Option(
        "extraction", "--kind", "-k", help="extraction, summary, qa or entities"
    ),
    fmt: str = typer.Option("chat", "--format", "-f", help="chat or alpaca"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output .jsonl file"),
):
    """Build a fine-tuning dataset from a clone (training runs elsewhere)."""
    from zfrog.finetune import DatasetBuilder, dataset_summary
    from zfrog.utils.text import extract_text

    if not directory.is_dir():
        console.print(f"[red]Folder not found: {directory}[/]")
        sys.exit(1)

    pages = []
    for path in sorted(f for f in directory.rglob("*.html") if f.is_file()):
        html = path.read_text(encoding="utf-8", errors="replace")
        pages.append({"url": str(path), "path": str(path.name), "text": extract_text(html), "html": html})

    if not pages:
        console.print("[yellow]No HTML pages in that folder.[/]")
        sys.exit(1)

    builder = DatasetBuilder()
    added = builder.add_pages(pages, kind=kind)
    console.print(f"[green]{added} example(s) generated[/]")

    try:
        written = builder.export(output, fmt=fmt)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[dim]{dataset_summary(written)}[/]")
    console.print(f"[dim]Saved to {written}[/]")


@app.command()
def roi():
    """Show what the automation saved versus what it cost."""
    from zfrog.analytics import MetricsStore
    from zfrog.roi import inputs_from_settings, roi_from_metrics, to_markdown

    result = roi_from_metrics(inputs_from_settings(), store=MetricsStore())
    if not result.runs:
        console.print("[dim]Nothing measured yet — run some extractions.[/]")
        return

    console.print(Markdown(to_markdown(result)))


@app.command()
def market_serve(
    host: str = typer.Option("", "--host", help="Address (default: ZFROG_MARKETPLACE_HOST)"),
    port: int = typer.Option(0, "--port", "-p", help="Port (default: ZFROG_MARKETPLACE_PORT)"),
    source: str = typer.Option("", "--source", help="Name of the source in the index"),
    token: str = typer.Option("", "--token", help="Require this token to publish"),
):
    """Serve the marketplace index over HTTP."""
    from zfrog.marketplace_server import serve

    console.print(f"[green]Marketplace at http://{host or '127.0.0.1'}:{port or 8200}[/]")
    if token:
        console.print("[dim]Publishing requires the given token.[/]")

    try:
        serve(host=host, port=port, source=source, require_token=token)
    except KeyboardInterrupt:
        console.print("\n[dim]Server stopped.[/]")


@app.command()
def dispatch(
    url: list[str] = typer.Option(..., "--url", "-u", help="URL to dispatch (may repeat)"),
    mode: str = typer.Option(
        "auto", "--mode", "-m", help="Job mode (auto = the probe picks the engine)"
    ),
    region: str | None = typer.Option(None, "--region", "-r", help="Preferred region"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show where it would go"),
):
    """Hand jobs to workers (or show where they would go)."""
    from zfrog.dispatch import Dispatcher, dispatch_summary, plan_dispatch

    jobs = [{"url": u, "mode": mode} for u in url]

    if dry_run:
        for plan in plan_dispatch(jobs):
            target = plan.get("worker") or "—"
            console.print(f"  {plan['url']} -> [cyan]{target}[/] ({plan.get('region', '')})")
        return

    async def run():
        dispatcher = Dispatcher()
        try:
            results = await dispatcher.send_many(jobs, preferred_region=region)
            for result in results:
                color = "green" if result.accepted else "red"
                console.print(f"  [{color}]{result.worker or '—'}[/] {result.job_id or result.detail}")
            console.print(f"[bold]{dispatch_summary(results)}[/]")
        finally:
            await dispatcher.aclose()

    asyncio.run(run())


@app.command()
def arweave(
    directory: Path = typer.Argument(..., help="Cloned folder to archive"),
):
    """Publish a clone to Arweave for permanent archiving."""
    from zfrog.storage.arweave import publish_clone

    if not directory.is_dir():
        console.print(f"[red]Folder not found: {directory}[/]")
        sys.exit(1)

    try:
        result = asyncio.run(publish_clone(directory))
    except RuntimeError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Published[/] — {result['size_bytes']:,} bytes")
    console.print(f"ID: [cyan]{result['item_id']}[/]")
    console.print(f"[dim]{result['gateway_url']}[/]")
