"""CLI capture commands — split from cli.py."""

import asyncio
import json
import sys
from pathlib import Path

import typer
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
)
from rich.table import Table

from zfrog.cli import app
from zfrog.cli._shared import (
    _card_html,
    _card_markdown,
    _job_dir,
    _print_component_summary,
    _print_tokens_summary,
    console,
)
from zfrog.models import JobCreate


@app.command()
def jump(
    url: str = typer.Argument(..., help="Address of the page to capture"),
    breakpoint_name: str = typer.Option(
        "desktop",
        "--breakpoint",
        "-b",
        help="Screenshot resolution: desktop, tablet or mobile",
    ),
    tag: list[str] = typer.Option([], "--tag", "-t", help="Tag for the reference (may repeat)"),
    viewport_only: bool = typer.Option(
        False,
        "--viewport-only",
        help="Capture only what fits on screen, instead of the full page",
    ),
    image_format: str = typer.Option(
        "png", "--format", "-f", help="Image format: png (lossless) or webp (smaller)"
    ),
    output: str = typer.Option("output", "--output", "-o", help="Output directory"),
):
    """Capture a page as a reference: screenshot + design tokens."""
    from zfrog.engines.jump import BREAKPOINTS
    from zfrog.orchestrator import run_job

    if breakpoint_name not in BREAKPOINTS:
        console.print(
            f"[red]Unknown resolution:[/] {breakpoint_name}. "
            f"Use one of: {', '.join(BREAKPOINTS)}"
        )
        sys.exit(1)

    if image_format.lower() not in ("png", "webp"):
        console.print(f"[red]Unknown format:[/] {image_format} (use png or webp)")
        sys.exit(1)

    settings_output = Path(output)
    from zfrog.config import settings

    settings.output_dir = settings_output

    job = JobCreate(
        url=url,
        mode="jump",
        token_breakpoint=breakpoint_name,
        screenshot_full_page=not viewport_only,
        screenshot_format=image_format.lower(),
        card_tags=list(tag),
    )

    console.print(
        f"Capturing [cyan]{url}[/] at {breakpoint_name}"
        + ("" if not viewport_only else " (viewport only)")
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Capturing…", total=None)

        try:
            result = asyncio.run(run_job(job))
        except Exception as e:
            console.print(f"[red]Failed:[/] {e}")
            sys.exit(1)

        progress.update(task, description="[green]Done[/]")

    console.print(f"[green]Captured[/] — {result.files_count} files, "
                  f"{result.total_size_bytes:,} bytes in {result.duration_seconds:.1f}s")
    _print_tokens_summary(_job_dir(result))


@app.command()
def tongue(
    url: str = typer.Argument(..., help="Address of the page"),
    selector: str = typer.Argument(..., help="CSS selector of the component (e.g.: .hero, #nav)"),
    output: str = typer.Option("output", "--output", "-o", help="Output directory"),
):
    """Extract a component: the HTML and the CSS the browser applied to it."""
    from zfrog.config import settings
    from zfrog.orchestrator import run_job

    settings.output_dir = Path(output)

    job = JobCreate(url=url, mode="tongue", selector=selector)

    console.print(f"Extracting [cyan]{selector}[/] from {url}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Extracting…", total=None)

        try:
            result = asyncio.run(run_job(job))
        except Exception as e:
            console.print(f"[red]Failed:[/] {e}")
            sys.exit(1)

        progress.update(task, description="[green]Done[/]")

    console.print(f"[green]Extracted[/] — {result.files_count} files")
    _print_component_summary(_job_dir(result))


@app.command()
def pond(
    tag: str | None = typer.Option(None, "--tag", "-t", help="Filter by tag"),
    color: str | None = typer.Option(
        None, "--color", "-c", help="Filter by color (e.g.: #3BD487)"
    ),
    site: str | None = typer.Option(None, "--site", "-s", help="Filter by site"),
    query: str | None = typer.Option(
        None, "--query", "-q", help="Search in the address, title or note"
    ),
    describe: str | None = typer.Option(
        None,
        "--search",
        help="Search by visual description (e.g.: \"dark layouts with rounded cards\")",
    ),
    reindex: bool = typer.Option(
        False, "--reindex", help="Reindex the catalog embeddings before searching"
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="How many references to show"),
):
    """List the captured references, or search by description with --search."""
    from zfrog.catalog import Catalog
    from zfrog.config import settings

    catalog = Catalog(Path(settings.catalog_db))

    if reindex:
        from zfrog.visual_search import embed_catalog_sync

        result = embed_catalog_sync(catalog, force=True)
        if result.indexed:
            console.print(f"[green]{result.indexed} reference(s) indexed.[/]")
        else:
            # Say *why*, not just "nothing happened": an empty catalog, an already
            # indexed one and a broken model need three different actions.
            console.print(f"[yellow]Nothing indexed.[/] {result.reason}")

    if describe:
        from zfrog.visual_search import search_descriptive

        hits = asyncio.run(search_descriptive(catalog, describe, limit=limit))
        if not hits:
            console.print(f"[yellow]Nothing found for[/] “{describe}”.")
            return

        table = Table(title=f"Search by description — “{describe}” ({len(hits)})")
        table.add_column("ID", style="dim")
        table.add_column("RELEVANCE", justify="right", style="green")
        table.add_column("SITE", style="cyan")
        table.add_column("TITLE")
        table.add_column("COLOR", style="green")
        table.add_column("TAGS", style="magenta")

        for hit in hits:
            table.add_row(
                hit.card.id[:8],
                f"{hit.score:.2f}",
                hit.card.site,
                (hit.card.title or "—")[:40],
                hit.card.dominant or "—",
                ", ".join(hit.card.tags) or "—",
            )

        console.print(table)
        return

    cards = catalog.list(tag=tag, color=color, site=site, query=query, limit=limit)

    if not cards:
        if catalog.count():
            console.print("[yellow]No reference matches these filters.[/]")
        else:
            console.print(
                "[yellow]The catalog is empty.[/] Capture a page with "
                "[cyan]zfrog jump <url>[/]."
            )
        return

    table = Table(title=f"References ({len(cards)} of {catalog.count()})")
    table.add_column("ID", style="dim")
    table.add_column("SITE", style="cyan")
    table.add_column("TITLE")
    table.add_column("COLOR", style="green")
    table.add_column("TAGS", style="magenta")
    table.add_column("WHEN", style="dim")

    for card in cards:
        table.add_row(
            card.id[:8],
            card.site,
            (card.title or "—")[:40],
            card.dominant or "—",
            ", ".join(card.tags) or "—",
            card.captured_at_label,
        )

    console.print(table)

    if tag is None and color is None and site is None and query is None:
        tags = catalog.tags()
        if tags:
            console.print(
                "[dim]tags:[/] " + " · ".join(f"{name} ({count})" for name, count in tags[:12])
            )
        colors = catalog.colors(12)
        if colors:
            console.print(
                "[dim]colors:[/] " + " · ".join(f"{hex_color} ({count})" for hex_color, count in colors)
            )


@app.command()
def show(
    card_id: str = typer.Argument(..., help="Reference ID (prefix works)"),
):
    """Show the details of a captured reference."""
    from zfrog.catalog import Catalog
    from zfrog.config import settings

    catalog = Catalog(Path(settings.catalog_db))

    card = catalog.get(card_id)
    if card is None:
        matches = [c for c in catalog.list(limit=1000) if c.id.startswith(card_id)]
        if len(matches) == 1:
            card = matches[0]
        elif len(matches) > 1:
            console.print(
                f"[yellow]Ambiguous prefix:[/] {len(matches)} references start with this."
            )
            for match in matches[:10]:
                console.print(f"  {match.id[:12]} — {match.site}")
            sys.exit(1)

    if card is None:
        console.print(f"[red]Reference not found:[/] {card_id}")
        sys.exit(1)

    console.print(f"[bold]{card.title or card.url}[/]")
    console.print(f"[dim]{card.url}[/]")
    console.print()

    details = Table.grid(padding=(0, 2))
    details.add_column(style="dim")
    details.add_column()
    details.add_row("ID", card.id)
    details.add_row("Site", card.site)
    details.add_row("Captured", card.captured_at_label)
    details.add_row("Mode", f"{card.mode} · {card.engine}")
    details.add_row("Screenshot", card.screenshot or "—")
    details.add_row("Tags", ", ".join(card.tags) or "—")
    details.add_row("Note", card.note or "—")
    console.print(details)

    tokens = card.tokens or {}
    palette = tokens.get("palette", [])
    if palette:
        console.print()
        palette_table = Table(title="Palette")
        palette_table.add_column("COLOR", style="green")
        palette_table.add_column("USES", justify="right")
        palette_table.add_column("ROLE", style="cyan")
        for entry in palette[:12]:
            palette_table.add_row(entry.get("hex", ""), str(entry.get("count", 0)), entry.get("role") or "—")
        console.print(palette_table)

    fonts = tokens.get("fonts", [])
    if fonts:
        console.print()
        for font in fonts[:6]:
            console.print(f"[bold]{font.get('family')}[/] — {font.get('count')} elements")


@app.command()
def export(
    card_id: str = typer.Argument(..., help="Reference ID"),
    fmt: str = typer.Option("json", "--format", "-f", help="json, md or html"),
    dest: Path | None = typer.Option(
        None, "--dest", "-d", help="Where to save (default: stdout)"
    ),
):
    """Export a reference as JSON, Markdown or an HTML mini style guide."""
    from zfrog.catalog import Catalog
    from zfrog.config import settings

    catalog = Catalog(Path(settings.catalog_db))
    card = catalog.get(card_id)
    if card is None:
        matches = [c for c in catalog.list(limit=1000) if c.id.startswith(card_id)]
        if len(matches) == 1:
            card = matches[0]

    if card is None:
        console.print(f"[red]Reference not found:[/] {card_id}")
        sys.exit(1)

    if fmt == "json":
        payload = json.dumps(card.to_dict(), ensure_ascii=False, indent=2)
    elif fmt == "md":
        payload = _card_markdown(card)
    elif fmt == "html":
        payload = _card_html(card)
    else:
        console.print(f"[red]Unknown format:[/] {fmt} (use json, md or html)")
        sys.exit(1)

    if dest is None:
        console.print(payload)
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(payload, encoding="utf-8")
    console.print(f"[green]Saved[/] to {dest}")
