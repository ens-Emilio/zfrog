"""CLI entry point for Zfrog."""

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from zfrog.models import JobCreate

app = typer.Typer(
    name="zfrog",
    help="Design reference engine: capture, organize and adapt web design references.",
    no_args_is_help=True,
)
console = Console()


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
    pdf_filename: Optional[str] = typer.Option(
        None, "--pdf-filename", help="Nome do PDF gerado (modo pdf; default: index)"
    ),
    versioned: bool = typer.Option(
        False, "--versioned", help="Guardar uma versão do site no histórico (rollback depois)"
    ),
    translate_target: Optional[str] = typer.Option(
        None, "--target", help="Idioma de destino no modo translate (ex.: pt, en, es)"
    ),
    org: Optional[str] = typer.Option(
        None, "--org", "-O", help="Organização dona dos dados (isola em output/orgs/<slug>)"
    ),
):
    """Clone a website."""
    from pathlib import Path
    from zfrog.config import settings
    from zfrog.orchestrator import run_job
    from zfrog.utils.rate_limit import _global_limiter
    
    # Override output directory
    settings.output_dir = Path(output)
    
    # Set rate limit
    _global_limiter.set_rate(rate_limit)
    
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
    output_dir: Path = typer.Argument(..., help="Diretório de um clone (mirror/scrape)"),
    url: str = typer.Option("", "--url", "-u", help="URL original (para o resumo global)"),
    max_pages: int = typer.Option(30, "--max-pages", help="Máx. de páginas a resumir"),
):
    """Summarize every page of a cloned directory with AI."""
    import json

    from zfrog.ai.summarize import summarize_directory, to_markdown

    if not output_dir.is_dir():
        console.print(f"[red]Diretório não encontrado: {output_dir}[/]")
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

    console.print(f"[green]Resumidas {len(result['pages'])} página(s)[/]")
    global_summary = result["global_summary"]
    if global_summary.get("error"):
        console.print(f"[yellow]{global_summary['error']}[/]")
    elif global_summary.get("summary"):
        console.print(Markdown(global_summary["summary"]))
    console.print(f"[dim]Salvo em {output_dir / 'summary.json'} e {output_dir / 'summary.md'}[/]")

@app.command()
def snapshots(
    url: str = typer.Argument(None, help="URL (omite para listar tudo)"),
):
    """List captured snapshots."""
    import json

    from zfrog.diff import list_snapshots

    paths = list_snapshots(url)
    if not paths:
        console.print("[dim]Nenhum snapshot salvo ainda.[/]")
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
    snapshot_a: Path = typer.Argument(..., help="Snapshot mais antigo (caminho p/ .json)"),
    snapshot_b: Path = typer.Argument(..., help="Snapshot mais novo (caminho p/ .json)"),
    url: str = typer.Option("", "--url", "-u", help="URL (opcional; senão lê do snapshot)"),
    as_json: bool = typer.Option(False, "--json", help="Imprime o relatório em JSON"),
):
    """Compare two snapshots and report changes."""
    import json

    from zfrog.diff import diff_snapshots, diff_to_markdown, report_to_dict

    for path in (snapshot_a, snapshot_b):
        if not path.is_file():
            console.print(f"[red]Snapshot não encontrado: {path}[/]")
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


def _find_project_root() -> Path:
    """Locate the project root containing both pyproject.toml and dashboard/."""
    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    for candidate in candidates:
        if (candidate / "pyproject.toml").exists() and (candidate / "dashboard").is_dir():
            return candidate
    raise RuntimeError(
        "Could not find project root (need pyproject.toml and dashboard/). "
        "Run this from inside the zfrog repository."
    )


async def _pump_output(stream, label: str, color: str) -> None:
    """Forward a child process stream to the console with a label prefix."""
    while True:
        line = await stream.readline()
        if not line:
            return
        text = line.decode("utf-8", errors="replace").rstrip()
        if text:
            console.print(f"[{color}]{label}[/] {text}")


async def _terminate(proc) -> None:
    """Terminate a process and its whole process group."""
    if proc.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
    except asyncio.TimeoutError:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        await proc.wait()


async def _run_dev(host: str, api_port: int, web_port: int, dashboard_dir: Path, reload: bool) -> int:
    """Run API and dashboard concurrently until either exits or user interrupts."""
    # The dashboard calls the API from the browser with the session cookie, and a
    # browser only attaches that cookie when the response names its exact origin —
    # the spec forbids pairing credentials with "*". Without this the default
    # `ZFROG_CORS_ORIGINS=*` makes every dashboard request fail as "Failed to fetch"
    # while `curl` keeps working, which is a confusing first run. Listing the two
    # origins the dev server answers on turns credential mode on for exactly them.
    dashboard_origins = f"http://localhost:{web_port},http://127.0.0.1:{web_port}"
    child_env = {
        **os.environ,
        "ZFROG_CORS_ORIGINS": os.environ.get("ZFROG_CORS_ORIGINS", dashboard_origins),
        # The dashboard reads this at build time; pointing it at the API port keeps
        # `--api-port` from silently having no effect on the browser.
        "NEXT_PUBLIC_API_URL": os.environ.get("NEXT_PUBLIC_API_URL", f"http://{host}:{api_port}"),
    }

    api_cmd = [
        sys.executable, "-m", "uvicorn", "zfrog.api:app",
        "--host", host, "--port", str(api_port),
    ]
    if reload:
        api_cmd.append("--reload")

    web_cmd = ["npm", "run", "dev", "--", "-p", str(web_port)]

    api_proc = await asyncio.create_subprocess_exec(
        *api_cmd,
        env=child_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    web_proc = await asyncio.create_subprocess_exec(
        *web_cmd,
        cwd=dashboard_dir,
        env=child_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )

    # Install signal handlers to kill child process groups when terminal closes.
    # Without this, SIGHUP kills the parent but orphaned children survive.
    loop = asyncio.get_running_loop()
    _original_sighup = signal.getsignal(signal.SIGHUP)
    _original_sigterm = signal.getsignal(signal.SIGTERM)

    def _signal_cleanup(sig, frame):
        for proc in (api_proc, web_proc):
            if proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    try:
                        proc.terminate()
                    except (ProcessLookupError, PermissionError):
                        pass

    signal.signal(signal.SIGTERM, _signal_cleanup)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _signal_cleanup)

    console.print()
    console.print(f"  API       [cyan]http://{host}:{api_port}[/]  [dim](docs: /docs)[/]")
    console.print(f"  Dashboard [magenta]http://localhost:{web_port}[/]")
    console.print("  [dim]Ctrl+C to stop both[/]")
    console.print()

    pumps = [
        asyncio.create_task(_pump_output(api_proc.stdout, "api", "cyan")),
        asyncio.create_task(_pump_output(web_proc.stdout, "web", "magenta")),
    ]
    waits = [
        asyncio.create_task(api_proc.wait()),
        asyncio.create_task(web_proc.wait()),
    ]

    exit_code = 0
    try:
        done, _ = await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        finished = done.pop()
        exit_code = finished.result() or 0
        name = "API" if finished is waits[0] else "dashboard"
        console.print(f"\n[yellow]{name} exited (code {exit_code}); stopping the other.[/]")
    except asyncio.CancelledError:
        raise
    finally:
        # Restore original signal handlers
        signal.signal(signal.SIGTERM, _original_sigterm)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, _original_sighup)
        await _terminate(api_proc)
        await _terminate(web_proc)
        for task in pumps:
            task.cancel()
        await asyncio.gather(*pumps, return_exceptions=True)
        for task in waits:
            task.cancel()
        await asyncio.gather(*waits, return_exceptions=True)

    return exit_code


def _redis_state() -> tuple[bool, str]:
    """Whether Redis answers, and the URL it was asked at.

    Checked from here rather than from the API because the point is to say it in the
    `dev` banner: the status card in the panel already reports it, but that is behind
    a browser tab, and the dev command is where someone looks when something is off.
    """
    from zfrog.config import settings

    try:
        import redis

        client = redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        client.close()
        return True, settings.redis_url
    except Exception:
        return False, settings.redis_url


@app.command()
def dev(
    api_port: int = typer.Option(8000, "--api-port", help="API port"),
    web_port: int = typer.Option(3000, "--web-port", help="Dashboard port"),
    host: str = typer.Option("127.0.0.1", "--host", help="API host"),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Auto-reload API on changes"),
    install: bool = typer.Option(True, "--install/--no-install", help="Run npm install if needed"),
):
    """Run API and dashboard together with one command.

    Redis is not started here — `docker compose up` does that, and a local server may
    already be the user's own. Its state is reported so the panel's "pendência" warning
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
            f"[yellow]Redis não respondeu[/] em [cyan]{redis_url}[/]. "
            "O painel e os jobs funcionam sem ele (rodam no processo); "
            "o que fica de fora é a fila entre workers e o progresso ao vivo."
        )
        console.print(
            "[dim]Para ligar:[/] [cyan]redis-server[/] "
            "[dim]ou[/] [cyan]docker compose up -d redis[/]"
        )

    try:
        exit_code = asyncio.run(_run_dev(host, api_port, web_port, dashboard_dir, reload))
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/]")
        return

    raise typer.Exit(exit_code)


@app.command()
def versions(
    url: str = typer.Argument(..., help="URL do site"),
    branch: str = typer.Option("main", "--branch", "-b", help="Ramo a listar"),
):
    """List saved versions of a site."""
    from zfrog.versioning import VersionStore

    store = VersionStore()
    log = store.log(url, branch)

    if not log:
        console.print(f"[dim]Nenhuma versão salva para {url} em '{branch}'.[/]")
        console.print("[dim]Use --versioned no clone para começar o histórico.[/]")
        return

    table = Table(title=f"Versões de {url} ({branch})")
    table.add_column("ID", style="cyan")
    table.add_column("QUANDO", style="green")
    table.add_column("PÁGINAS", justify="right")
    table.add_column("MENSAGEM")
    table.add_column("ANTERIOR", style="dim")

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
    url: str = typer.Argument(..., help="URL do site"),
    ref: str = typer.Argument(..., help="Versão (id, prefixo, HEAD) ou ramo"),
    dest: Optional[Path] = typer.Option(None, "--dest", "-d", help="Onde restaurar"),
):
    """Restore the files of a saved version."""
    from zfrog.versioning import VersionStore

    try:
        restored = VersionStore().rollback(url, ref, dest)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    files = [f for f in restored.rglob("*") if f.is_file()]
    console.print(f"[green]{len(files)} arquivo(s) restaurado(s) em {restored}[/]")

@app.command()
def branches(
    url: str = typer.Argument(..., help="URL do site"),
):
    """List the version branches of a site."""
    from zfrog.versioning import VersionStore

    store = VersionStore()
    names = store.branches(url)
    if not names:
        console.print(f"[dim]Nenhum ramo para {url}.[/]")
        return

    head = store.head(url, "main")
    for name in names:
        marker = " [bold](HEAD)[/]" if head and name == "main" else ""
        console.print(f"  {name}{marker}")

@app.command()
def branch(
    url: str = typer.Argument(..., help="URL do site"),
    name: str = typer.Argument(..., help="Nome do novo ramo"),
    from_branch: str = typer.Option("main", "--from", help="Ramo de origem"),
):
    """Create a new version branch."""
    from zfrog.versioning import VersionStore

    try:
        VersionStore().create_branch(url, name, from_branch)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Ramo '{name}' criado a partir de '{from_branch}'.[/]")

schedule_app = typer.Typer(help="Agendar cópias recorrentes de um site.")
app.add_typer(schedule_app, name="schedule")

@schedule_app.command("add")
def schedule_add(
    url: str = typer.Argument(..., help="URL do site"),
    cron: str = typer.Option(..., "--cron", "-c", help='Quando rodar, ex.: "0 2 * * *"'),
    mode: str = typer.Option("auto", "--mode", "-m", help="Modo do job (auto = o probe escolhe o motor)"),
    depth: int = typer.Option(1, "--depth", "-d", help="Profundidade máxima do crawl"),
):
    """Agenda uma cópia recorrente."""
    from zfrog.cron import describe
    from zfrog.scheduler import ScheduleStore, next_run_for

    try:
        schedule = ScheduleStore().add(cron, url, mode=mode, max_depth=depth)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Agendado ({schedule.id})[/] — {describe(cron)}")
    console.print(f"[dim]Próxima execução: {schedule.next_run or next_run_for(schedule)}[/]")

@schedule_app.command("list")
def schedule_list():
    """Lista os agendamentos."""
    from zfrog.cron import describe
    from zfrog.scheduler import ScheduleStore

    schedules = ScheduleStore().list()
    if not schedules:
        console.print("[dim]Nenhum agendamento. Use: zfrog schedule add <url> --cron \"0 2 * * *\"[/]")
        return

    table = Table(title="Agendamentos")
    table.add_column("ID", style="cyan")
    table.add_column("QUANDO")
    table.add_column("URL")
    table.add_column("MODO")
    table.add_column("ATIVO", justify="center")
    table.add_column("PRÓXIMA", style="green")

    for schedule in schedules:
        table.add_row(
            schedule.id,
            describe(schedule.cron),
            schedule.url[:36],
            schedule.mode,
            "sim" if schedule.enabled else "não",
            schedule.next_run or "-",
        )

    console.print(table)

@schedule_app.command("remove")
def schedule_remove(
    schedule_id: str = typer.Argument(..., help="ID do agendamento"),
):
    """Remove um agendamento."""
    from zfrog.scheduler import ScheduleStore

    if ScheduleStore().remove(schedule_id):
        console.print(f"[green]Agendamento {schedule_id} removido.[/]")
    else:
        console.print(f"[red]Agendamento {schedule_id} não encontrado.[/]")
        sys.exit(1)

@schedule_app.command("run")
def schedule_run(
    schedule_id: str = typer.Argument(..., help="ID do agendamento"),
):
    """Roda um agendamento agora, sem esperar o horário."""
    from zfrog.models import JobCreate
    from zfrog.orchestrator import run_job
    from zfrog.scheduler import ScheduleStore

    schedule = ScheduleStore().get(schedule_id)
    if not schedule:
        console.print(f"[red]Agendamento {schedule_id} não encontrado.[/]")
        sys.exit(1)

    console.print(f"[dim]Rodando {schedule.url} ({schedule.mode})...[/]")
    job = JobCreate(url=schedule.url, mode=schedule.mode, max_depth=schedule.max_depth)
    try:
        result = asyncio.run(run_job(job))
    except Exception as e:
        console.print(f"[red]Falhou: {e}[/]")
        sys.exit(1)

    console.print(f"[green]Job {result.job_id[:8]} concluído[/] — {result.files_count} arquivo(s)")

@app.command()
def scheduler(
    interval: int = typer.Option(30, "--interval", help="Segundos entre verificações"),
):
    """Run the schedule daemon until interrupted."""
    from zfrog.scheduler import daemon

    console.print(f"[green]Agendador ativo[/] — verificando a cada {interval}s. Ctrl+C para parar.")
    try:
        asyncio.run(daemon(interval_s=interval))
    except KeyboardInterrupt:
        console.print("\n[dim]Agendador parado.[/]")

@app.command()
def search(
    query: str = typer.Argument(..., help="O que procurar"),
    directory: Optional[Path] = typer.Option(
        None, "--dir", "-d", help="Pasta clonada (default: o diretório de saída)"
    ),
    semantic: bool = typer.Option(False, "--semantic", help="Busca por significado (precisa de IA)"),
    limit: int = typer.Option(10, "--limit", "-n", help="Máximo de resultados"),
    reindex: bool = typer.Option(False, "--reindex", help="Indexar a pasta antes de buscar"),
):
    """Search inside cloned content."""
    from zfrog.config import settings
    from zfrog.search import SearchIndex

    target = directory or Path(settings.output_dir)
    index = SearchIndex()

    if reindex:
        count = index.index_directory(target)
        console.print(f"[dim]{count} página(s) indexada(s) em {target}[/]")

    mode = "semantic" if semantic else "fulltext"
    hits = index.search(query, mode=mode, limit=limit)

    if not hits:
        console.print(f"[yellow]Nada encontrado para '{query}'.[/]")
        if semantic:
            console.print("[dim]A busca semântica precisa de um modelo de IA configurado.[/]")
        return

    table = Table(title=f"Resultados para '{query}' ({mode})")
    table.add_column("ONDE", style="cyan")
    table.add_column("TRECHO")
    table.add_column("SCORE", justify="right", style="green")

    for hit in hits:
        table.add_row(hit.title or hit.path, hit.snippet, f"{hit.score:.3f}")

    console.print(table)

@app.command()
def login(
    url: str = typer.Argument(..., help="URL do site onde você vai entrar"),
    no_wait: bool = typer.Option(
        False, "--no-wait", help="Não esperar o Enter (útil em automação)"
    ),
):
    """Open a browser so you can sign in, then save the session."""
    from zfrog.session import capture_session

    console.print(f"[green]Abrindo o navegador em {url}[/]")
    console.print("[dim]Entre na sua conta e depois volte aqui e aperte Enter.[/]")

    try:
        state = asyncio.run(capture_session(url, wait_for_enter=not no_wait))
    except Exception as e:
        console.print(f"[red]Falhou: {e}[/]")
        sys.exit(1)

    cookies = len(state.get("cookies", []))
    console.print(f"[green]Sessão salva[/] — {cookies} cookie(s). Os próximos clones deste site usam ela.")

@app.command()
def sessions():
    """List saved login sessions."""
    from zfrog.session import SessionStore

    entries = SessionStore().list()
    if not entries:
        console.print("[dim]Nenhuma sessão salva. Use: zfrog login <url>[/]")
        return

    table = Table(title="Sessões salvas")
    table.add_column("SITE", style="cyan")
    table.add_column("QUANDO", style="green")
    table.add_column("COOKIES", justify="right")

    for entry in entries:
        table.add_row(entry["domain"], entry["saved_at"], str(entry["cookies"]))

    console.print(table)

@app.command()
def logout(
    domain: str = typer.Argument(..., help="Site da sessão (ex.: exemplo.com.br)"),
):
    """Delete a saved login session."""
    from zfrog.session import SessionStore

    if SessionStore().delete(domain):
        console.print(f"[green]Sessão de {domain} apagada.[/]")
    else:
        console.print(f"[red]Nenhuma sessão salva para {domain}.[/]")
        sys.exit(1)

workflow_app = typer.Typer(help="Sequências de passos salvas (pipelines).")
app.add_typer(workflow_app, name="workflow")

@workflow_app.command("list")
def workflow_list():
    """Lista os fluxos salvos."""
    from zfrog.workflows import WorkflowStore

    workflows = WorkflowStore().list()
    if not workflows:
        console.print("[dim]Nenhum fluxo salvo.[/]")
        return

    table = Table(title="Fluxos")
    table.add_column("ID", style="cyan")
    table.add_column("NOME")
    table.add_column("PASSOS", justify="right")
    table.add_column("SEQUÊNCIA", style="dim")

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
    workflow_id: str = typer.Argument(..., help="ID do fluxo"),
):
    """Mostra os passos de um fluxo."""
    from zfrog.workflows import WorkflowStore

    workflow = WorkflowStore().get(workflow_id)
    if not workflow:
        console.print(f"[red]Fluxo {workflow_id} não encontrado.[/]")
        sys.exit(1)

    console.print(f"[bold]{workflow.name}[/] [dim]({workflow.id})[/]")
    for index, step in enumerate(workflow.steps, 1):
        params = ", ".join(f"{k}={v}" for k, v in step.params.items()) or "-"
        console.print(f"  {index}. [cyan]{step.type}[/] [dim]({params})[/]")

@workflow_app.command("run")
def workflow_run(
    workflow_id: str = typer.Argument(..., help="ID do fluxo"),
):
    """Roda um fluxo do começo ao fim."""
    from zfrog.workflows import WorkflowStore, run_workflow

    workflow = WorkflowStore().get(workflow_id)
    if not workflow:
        console.print(f"[red]Fluxo {workflow_id} não encontrado.[/]")
        sys.exit(1)

    def on_progress(message: str) -> None:
        console.print(f"[dim]{message}[/]")

    result = asyncio.run(run_workflow(workflow, on_progress=on_progress))

    for step in result.steps:
        color = {"ok": "green", "failed": "red", "skipped": "dim"}.get(step.status, "white")
        console.print(f"  [{color}]{step.status:7}[/] {step.type:10} {step.detail}")

    if result.status == "failed":
        console.print(f"[red]Fluxo falhou: {result.error}[/]")
        sys.exit(1)

    console.print("[green]Fluxo concluído.[/]")

@app.command()
def operator(
    interval: float = typer.Option(5.0, "--interval", help="Segundos entre reconciliações"),
):
    """Run the Kubernetes operator (watches ZfrogJob resources)."""
    from zfrog.k8s.operator import Operator

    console.print(f"[green]Operador ativo[/] — reconciliando a cada {interval}s. Ctrl+C para parar.")
    try:
        asyncio.run(Operator(reconcile_interval_s=interval).run())
    except KeyboardInterrupt:
        console.print("\n[dim]Operador parado.[/]")

@app.command()
def analytics(
    engine: Optional[str] = typer.Option(None, "--engine", "-e", help="Filtrar por motor"),
):
    """Show which engines work best (success rate, speed, size)."""
    from zfrog.analytics import MetricsStore, format_engine_table

    store = MetricsStore()
    stats = store.engine_stats(engine)
    totals = store.totals()

    if not stats:
        console.print("[dim]Nenhuma execução registrada ainda.[/]")
        return

    console.print(
        f"[bold]{totals['runs']}[/] execução(ões) — "
        f"sucesso {totals['success_rate'] * 100:.1f}% — "
        f"{totals['bytes']:,} bytes — média {totals['avg_duration_s']:.2f}s"
    )

    table = Table(title="Desempenho por motor")
    table.add_column("MOTOR", style="cyan")
    table.add_column("EXECUÇÕES", justify="right")
    table.add_column("SUCESSO", justify="right", style="green")
    table.add_column("FALHAS", justify="right", style="red")
    table.add_column("TEMPO MÉDIO", justify="right")
    table.add_column("TAMANHO MÉDIO", justify="right")

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
    limit: int = typer.Option(50, "--limit", "-n", help="Quantas entradas mostrar"),
    action: Optional[str] = typer.Option(None, "--action", "-a", help="Filtrar por ação"),
    actor: Optional[str] = typer.Option(None, "--actor", help="Filtrar por origem"),
):
    """Show the audit trail of actions."""
    from zfrog.utils.audit import AuditLog

    entries = AuditLog().read(limit=limit, action=action, actor=actor)
    if not entries:
        console.print("[dim]Nenhuma entrada no registro de auditoria.[/]")
        return

    table = Table(title="Auditoria")
    table.add_column("QUANDO", style="green")
    table.add_column("AÇÃO", style="cyan")
    table.add_column("ORIGEM")
    table.add_column("ALVO")
    table.add_column("RESULTADO")

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
    directory: Path = typer.Argument(..., help="Pasta clonada para verificar"),
):
    """Scan cloned content for malware and phishing indicators."""
    from zfrog.pipeline.safety import scan_directory

    if not directory.is_dir():
        console.print(f"[red]Pasta não encontrada: {directory}[/]")
        sys.exit(1)

    report = scan_directory(directory)
    colors = {"clean": "green", "low": "yellow", "medium": "yellow", "high": "red"}
    color = colors.get(report.risk, "white")

    console.print(f"[{color}]{report.summary}[/]")

    if not report.findings:
        return

    table = Table(title="Achados")
    table.add_column("GRAVIDADE", style="red")
    table.add_column("TIPO", style="cyan")
    table.add_column("ARQUIVO")
    table.add_column("DETALHE")

    for finding in report.findings:
        table.add_row(finding.severity, finding.kind, finding.file[:40], finding.detail[:60])

    console.print(table)

@app.command()
def ipfs(
    directory: Path = typer.Argument(..., help="Pasta clonada para publicar"),
    gateway: str = typer.Option("https://ipfs.io", "--gateway", help="Gateway para montar o link"),
):
    """Publish a clone to IPFS through a local node."""
    from zfrog.storage.ipfs import gateway_url, publish_output

    if not directory.is_dir():
        console.print(f"[red]Pasta não encontrada: {directory}[/]")
        sys.exit(1)

    try:
        result = asyncio.run(publish_output(directory))
    except RuntimeError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Publicado[/] — {result.files} arquivo(s), {result.size:,} bytes")
    console.print(f"CID: [cyan]{result.cid}[/]")
    console.print(f"[dim]{gateway_url(result.cid, gateway)}[/]")

chat_app = typer.Typer(help="Conversar com sites já clonados, mantendo o histórico.")
app.add_typer(chat_app, name="chat")

@chat_app.command("ask")
def chat_ask(
    question: str = typer.Argument(..., help="Pergunta em linguagem natural"),
    site: list[str] = typer.Option(
        [], "--site", "-s", help="Pasta de um site clonado, como 'Rótulo=caminho' (pode repetir)"
    ),
    conversation: Optional[str] = typer.Option(
        None, "--conversation", "-c", help="Continuar uma conversa existente (id)"
    ),
    show_history: bool = typer.Option(False, "--history", help="Mostrar o histórico ao final"),
):
    """Ask a question, keeping the conversation context."""
    from zfrog.ai.chat import ChatSession

    session = ChatSession()
    if conversation:
        if session.load(conversation) is None:
            console.print(f"[red]Conversa {conversation} não encontrada.[/]")
            sys.exit(1)
    elif not site:
        console.print("[red]Informe pelo menos um --site, ou continue com --conversation.[/]")
        sys.exit(1)

    for entry in site:
        label, _, raw_path = entry.partition("=")
        if not raw_path:
            label, raw_path = Path(entry).name, entry
        path = Path(raw_path)
        if not path.is_dir():
            console.print(f"[red]Pasta não encontrada: {path}[/]")
            sys.exit(1)
        session.add_site(label, path)

    result = asyncio.run(session.ask(question))
    console.print(Markdown(result["answer"]))
    console.print()

    for i, citation in enumerate(result["citations"], 1):
        url = citation.get("url") or citation.get("site") or ""
        console.print(f"[dim][{i}] {url} — {citation.get('path', '')}[/]")

    saved = session.save()
    console.print(f"[dim]Conversa {saved.stem} salva em {saved}[/]")

    if show_history:
        console.print()
        for turn in session.history():
            label = "Você" if turn.role == "user" else "Zfrog"
            console.print(f"[bold]{label}:[/] {turn.content[:200]}")

@chat_app.command("list")
def chat_list():
    """List saved conversations."""
    from zfrog.ai.chat import ChatSession

    directory = ChatSession().history_dir
    files = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not files:
        console.print("[dim]Nenhuma conversa salva ainda.[/]")
        return

    table = Table(title="Conversas")
    table.add_column("ID", style="cyan")
    table.add_column("TROCAS", justify="right")
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
    directory: Path = typer.Argument(..., help="Pasta clonada para mapear"),
    dot: bool = typer.Option(False, "--dot", help="Imprimir em formato Graphviz"),
):
    """Map the relationships between entities found in cloned pages."""
    from zfrog.ai.entities import extract_entities
    from zfrog.ai.graph import build_graph, describe, to_dot, to_json
    from zfrog.utils.text import extract_text

    if not directory.is_dir():
        console.print(f"[red]Pasta não encontrada: {directory}[/]")
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
    console.print(f"[dim]Salvo em {out}[/]")

    if built.nodes:
        table = Table(title="Entidades")
        table.add_column("NOME", style="cyan")
        table.add_column("TIPO")
        table.add_column("MENÇÕES", justify="right")
        for node in sorted(built.nodes, key=lambda n: n.mentions, reverse=True)[:15]:
            table.add_row(node.name, node.type, str(node.mentions))
        console.print(table)

@app.command()
def tos(
    url: str = typer.Argument(..., help="URL do site a verificar"),
):
    """Check robots.txt and Terms of Use for restrictions on automated collection."""
    from zfrog.ai.tos import check_site

    report = asyncio.run(check_site(url))

    colors = {"clear": "green", "caution": "yellow", "restricted": "red"}
    color = colors.get(report.risk, "white")
    console.print(f"[{color}]{report.summary}[/]")

    if report.error:
        console.print(f"[yellow]Aviso: {report.error}[/]")

    if not report.findings:
        return

    table = Table(title="Sinais encontrados")
    table.add_column("GRAVIDADE", style="red")
    table.add_column("TIPO", style="cyan")
    table.add_column("DETALHE")
    table.add_column("TRECHO", style="dim")

    for finding in report.findings:
        table.add_row(finding.severity, finding.kind, finding.detail[:50], finding.evidence[:50])

    console.print(table)

@app.command()
def watermark(
    directory: Path = typer.Argument(..., help="Pasta clonada a marcar"),
    source: str = typer.Option("", "--source", help="URL de origem a registrar"),
    verify_only: bool = typer.Option(False, "--verify", help="Só verificar, sem marcar"),
):
    """Mark (or verify) cloned content with provenance metadata."""
    from zfrog.pipeline.watermark import make_mark, verify_directory, watermark_directory

    if not directory.is_dir():
        console.print(f"[red]Pasta não encontrada: {directory}[/]")
        sys.exit(1)

    if verify_only:
        summary = asyncio.run(verify_directory(directory))
        if not summary["marked"]:
            console.print("[dim]Nenhum arquivo marcado nesta pasta.[/]")
            return
        console.print(f"[green]{summary['marked']} de {summary['files']} arquivo(s) marcado(s)[/]")
        for mark in summary["marks"]:
            console.print(f"  {mark}")
        return

    mark = make_mark(source or str(directory))
    summary = asyncio.run(watermark_directory(directory, mark, source))
    console.print(f"[green]{summary['marked']} arquivo(s) marcado(s)[/] — {summary['mark']}")

@app.command()
def regions(
    url: str = typer.Argument(..., help="URL que seria processada"),
):
    """Show which region would process a URL and why."""
    from zfrog.regions import data_residency_note, known_regions, route

    available = known_regions()
    decision = route(url, available)

    table = Table(title="Regiões")
    table.add_column("REGIÃO", style="cyan")
    table.add_column("LATÊNCIA", justify="right")
    table.add_column("WORKERS", justify="right")
    table.add_column("ATIVA", justify="center")

    for region in available:
        table.add_row(
            region.name,
            f"{region.latency_ms} ms",
            str(region.workers),
            "sim" if region.enabled else "não",
        )

    console.print(table)
    console.print(f"[green]Escolhida: {decision.region}[/] — {decision.reason}")
    console.print(f"[dim]{data_residency_note(url, decision.region)}[/]")

key_app = typer.Typer(help="Chaves de acesso da API.")
app.add_typer(key_app, name="key")

@key_app.command("create")
def key_create(
    name: str = typer.Argument(..., help="Nome para identificar a chave"),
    role: str = typer.Option("viewer", "--role", "-r", help="viewer, operator ou admin"),
    org: Optional[str] = typer.Option(
        None, "--org", "-O", help="Organização dona dos dados desta chave"
    ),
):
    """Create an API key (the secret is shown only once)."""
    from zfrog.auth import ApiKeyStore

    try:
        secret, key = ApiKeyStore().create(name, role, org=org or "")
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Chave criada[/] ({key.id}, papel {key.role})")
    if key.org:
        console.print(f"[dim]Organização: {key.org} — os dados ficam em output/orgs/{key.org}[/]")
    console.print(f"[bold]{secret}[/]")
    console.print("[yellow]Guarde agora: o segredo não é armazenado e não pode ser recuperado.[/]")

@key_app.command("list")
def key_list():
    """List API keys (never shows the secret)."""
    from zfrog.auth import ApiKeyStore

    keys = ApiKeyStore().list()
    if not keys:
        console.print("[dim]Nenhuma chave criada.[/]")
        return

    table = Table(title="Chaves")
    table.add_column("ID", style="cyan")
    table.add_column("NOME")
    table.add_column("PAPEL", style="green")
    table.add_column("ATIVA", justify="center")
    table.add_column("ÚLTIMO USO", style="dim")

    for key in keys:
        table.add_row(
            key.id, key.name, key.role, "sim" if key.enabled else "não", key.last_used_at or "-"
        )

    console.print(table)

@key_app.command("revoke")
def key_revoke(
    key_id: str = typer.Argument(..., help="ID da chave"),
):
    """Revoke an API key."""
    from zfrog.auth import ApiKeyStore

    if ApiKeyStore().revoke(key_id):
        console.print(f"[green]Chave {key_id} revogada.[/]")
    else:
        console.print(f"[red]Chave {key_id} não encontrada.[/]")
        sys.exit(1)

market_app = typer.Typer(help="Marketplace de fluxos, plugins e templates.")
app.add_typer(market_app, name="market")

@market_app.command("list")
def market_list(
    kind: Optional[str] = typer.Option(None, "--kind", "-k", help="workflow, plugin ou template"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Buscar por texto"),
):
    """List published assets."""
    from zfrog.marketplace import Marketplace

    assets = Marketplace().list(kind=kind, query=query)
    if not assets:
        console.print("[dim]Nada publicado ainda.[/]")
        return

    table = Table(title="Marketplace")
    table.add_column("ID", style="cyan")
    table.add_column("TIPO")
    table.add_column("NOME")
    table.add_column("AUTOR", style="dim")
    table.add_column("INSTALAÇÕES", justify="right")
    table.add_column("NOTA", justify="right", style="green")

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
    asset_id: str = typer.Argument(..., help="ID do item"),
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
def cost():
    """Show the estimated cost per engine (needs the cost rates configured)."""
    from zfrog.analytics import MetricsStore, format_cost, rates_from_settings

    rates = rates_from_settings()
    rows = MetricsStore().cost_by_engine(rates)

    if not rows:
        console.print("[dim]Nenhuma execução registrada ainda.[/]")
        return

    table = Table(title=f"Custo estimado ({rates.currency})")
    table.add_column("MOTOR", style="cyan")
    table.add_column("EXECUÇÕES", justify="right")
    table.add_column("DADOS", justify="right")
    table.add_column("TEMPO", justify="right")
    table.add_column("CUSTO", justify="right", style="green")
    table.add_column("POR EXECUÇÃO", justify="right")

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
            "[yellow]Nenhuma tarifa configurada — os valores são zero.[/]\n"
            "[dim]Defina ZFROG_COST_PER_GB_TRANSFER, ZFROG_COST_PER_CPU_HOUR e "
            "ZFROG_COST_PER_GB_MONTH.[/]"
        )

integ_app = typer.Typer(help="Destinos externos (Sheets, Airtable, Notion).")
app.add_typer(integ_app, name="integrations")

@integ_app.command("list")
def integrations_list():
    """List configured destinations."""
    from zfrog.integrations.base import DestinationStore, redact

    destinations = DestinationStore().list()
    if not destinations:
        console.print("[dim]Nenhum destino configurado.[/]")
        return

    for destination in destinations:
        console.print(f"  [cyan]{destination.name}[/] ({destination.kind}) — {redact(destination)}")

@integ_app.command("push")
def integrations_push(
    name: str = typer.Argument(..., help="Nome do destino"),
    file: Path = typer.Argument(..., help="Arquivo JSON com uma lista de registros"),
):
    """Send records to a destination."""
    from zfrog.integrations.base import DestinationStore, client_for

    destination = DestinationStore().get(name)
    if destination is None:
        console.print(f"[red]Destino {name} não encontrado.[/]")
        sys.exit(1)

    if not file.is_file():
        console.print(f"[red]Arquivo não encontrado: {file}[/]")
        sys.exit(1)

    records = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        console.print("[red]O arquivo precisa conter uma lista de registros.[/]")
        sys.exit(1)

    result = asyncio.run(client_for(destination).push(destination, records))
    console.print(f"[green]{result.created} criado(s)[/], {result.updated} atualizado(s)")

    for error in result.errors:
        console.print(f"[red]{error}[/]")

user_app = typer.Typer(help="Usuários e organizações.")
app.add_typer(user_app, name="user")

@user_app.command("create")
def user_create(
    email: str = typer.Argument(..., help="E-mail do usuário"),
    name: str = typer.Option("", "--name", "-n", help="Nome de exibição"),
    role: str = typer.Option("viewer", "--role", "-r", help="viewer, operator ou admin"),
    password: str = typer.Option("", "--password", "-p", help="Senha (vazio = só SSO)"),
    org: list[str] = typer.Option([], "--org", "-o", help="Organização (pode repetir)"),
):
    """Create a local user."""
    from zfrog.users import UserStore

    try:
        user, secret = UserStore().create(email, name=name, role=role, password=password, orgs=list(org))
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Usuário criado[/] {user.email} ({user.id}, papel {user.role})")
    if secret:
        console.print(f"[bold]{secret}[/]")
        console.print("[yellow]Guarde agora: a senha não é armazenada em texto claro.[/]")
    else:
        console.print("[dim]Sem senha: entre apenas por SSO.[/]")

@user_app.command("list")
def user_list():
    """List users."""
    from zfrog.users import UserStore

    users = UserStore().list()
    if not users:
        console.print("[dim]Nenhum usuário criado.[/]")
        return

    table = Table(title="Usuários")
    table.add_column("ID", style="cyan")
    table.add_column("E-MAIL")
    table.add_column("NOME")
    table.add_column("PAPEL", style="green")
    table.add_column("ORGANIZAÇÕES", style="dim")
    table.add_column("ATIVO", justify="center")

    for user in users:
        table.add_row(
            user.id,
            user.email,
            user.name or "-",
            user.role,
            ", ".join(user.orgs) or "-",
            "sim" if user.enabled else "não",
        )

    console.print(table)

@user_app.command("disable")
def user_disable(
    user_id: str = typer.Argument(..., help="ID do usuário"),
):
    """Disable a user."""
    from zfrog.users import UserStore

    if UserStore().set_enabled(user_id, False):
        console.print(f"[green]Usuário {user_id} desativado.[/]")
    else:
        console.print(f"[red]Usuário {user_id} não encontrado.[/]")
        sys.exit(1)

org_app = typer.Typer(help="Organizações e isolamento de dados.")
app.add_typer(org_app, name="org")

@org_app.command("create")
def org_create(
    name: str = typer.Argument(..., help="Nome da organização"),
    owner: str = typer.Option(..., "--owner", help="ID do usuário dono"),
):
    """Create an organization."""
    from zfrog.users import OrgStore

    try:
        org = OrgStore().create(name, owner)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Organização criada[/] {org.name} ({org.id})")

@org_app.command("list")
def org_list():
    """List organizations."""
    from zfrog.users import OrgStore
    from zfrog.workspaces import WorkspaceManager

    orgs = OrgStore().list()
    if not orgs:
        console.print("[dim]Nenhuma organização criada.[/]")
        return

    manager = WorkspaceManager()
    table = Table(title="Organizações")
    table.add_column("ID", style="cyan")
    table.add_column("NOME")
    table.add_column("DONO", style="dim")
    table.add_column("MEMBROS", justify="right")
    table.add_column("DADOS", justify="center")

    for org in orgs:
        table.add_row(
            org.id,
            org.name,
            org.owner,
            str(len(org.members)),
            "sim" if manager.exists(org.id) else "-",
        )

    console.print(table)

@org_app.command("add-member")
def org_add_member(
    org_id: str = typer.Argument(..., help="ID da organização"),
    user_id: str = typer.Argument(..., help="ID do usuário"),
    role: str = typer.Option("viewer", "--role", "-r", help="Papel dentro da organização"),
):
    """Add a user to an organization."""
    from zfrog.users import add_member

    try:
        add_member(org_id, user_id, role)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]{user_id} adicionado a {org_id} como {role}.[/]")

@app.command()
def annotate(
    job_id: str = typer.Argument(..., help="ID do job (cópia)"),
    path: str = typer.Argument(..., help="Página dentro da cópia"),
    text: str = typer.Argument(..., help="Comentário"),
    selector: str = typer.Option("", "--selector", "-s", help="Seletor CSS dentro da página"),
    author: str = typer.Option("", "--author", "-a", help="Quem está comentando"),
    tag: list[str] = typer.Option([], "--tag", "-t", help="Etiqueta (pode repetir)"),
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

    console.print(f"[green]Comentário {note.id} adicionado[/] em {note.path}")

@app.command()
def annotations(
    job_id: str = typer.Argument(..., help="ID do job"),
    open_only: bool = typer.Option(False, "--open", help="Mostrar só os não resolvidos"),
):
    """List the comments on a clone."""
    from zfrog.annotations import AnnotationStore

    store = AnnotationStore()
    notes = store.list(job_id=job_id, resolved=False if open_only else None)

    if not notes:
        console.print("[dim]Nenhum comentário nesta cópia.[/]")
        return

    counts = store.counts(job_id)
    console.print(
        f"[bold]{counts['total']}[/] comentário(s) — "
        f"{counts['open']} em aberto, {counts['resolved']} resolvido(s)"
    )

    for note in notes:
        mark = "[green]x[/]" if note.resolved else "[ ]"
        console.print(f"{mark} [cyan]{note.id}[/] {note.path} [dim]({note.author or 'anônimo'})[/]")
        if note.selector:
            console.print(f"    [dim]seletor: {note.selector}[/]")
        console.print(f"    {note.text}")
        for reply in note.replies:
            console.print(f"    [dim]↳ {reply.get('author', '')}: {reply.get('text', '')}[/]")

domain_app = typer.Typer(help="Perfis de domínio (vocabulário e instruções por área).")
app.add_typer(domain_app, name="domain")

@domain_app.command("list")
def domain_list():
    """List the built-in and saved domain profiles."""
    from zfrog.ai.domains import DomainProfileStore

    store = DomainProfileStore()
    rows = store.list() + store.builtin()

    table = Table(title="Perfis de domínio")
    table.add_column("ID", style="cyan")
    table.add_column("NOME")
    table.add_column("ORIGEM", style="dim")
    table.add_column("TERMOS", justify="right")
    table.add_column("EXEMPLOS", justify="right")

    saved_ids = {p.id for p in store.list()}
    for profile in rows:
        table.add_row(
            profile.id,
            profile.name,
            "salvo" if profile.id in saved_ids else "embutido",
            str(len(profile.terminology)),
            str(len(profile.examples)),
        )

    console.print(table)

@domain_app.command("suggest")
def domain_suggest(
    url: str = typer.Argument(..., help="URL ou texto a classificar"),
):
    """Suggest a domain profile for a URL or text."""
    from zfrog.ai.domains import resolve, suggest_profile

    profile_id = suggest_profile(url, url)
    if not profile_id:
        console.print("[dim]Nenhum perfil sugerido para isso.[/]")
        return

    profile = resolve(profile_id)
    console.print(f"[green]{profile_id}[/] — {profile.description if profile else ''}")

worker_app = typer.Typer(help="Workers e atribuição por região.")
app.add_typer(worker_app, name="worker")

@worker_app.command("list")
def worker_list():
    """List registered workers."""
    from zfrog.workers import WorkerRegistry

    registry = WorkerRegistry()
    registry.reap()
    workers = registry.list(alive_only=False)

    if not workers:
        console.print("[dim]Nenhum worker registrado.[/]")
        return

    table = Table(title="Workers")
    table.add_column("ID", style="cyan")
    table.add_column("REGIÃO", style="green")
    table.add_column("OCUPADO", justify="right")
    table.add_column("LIVRE", justify="right")
    table.add_column("VIVO", justify="center")
    table.add_column("VISTO", style="dim")

    for worker in workers:
        table.add_row(
            worker.id,
            worker.region,
            f"{worker.running}/{worker.capacity}",
            str(worker.free()),
            "sim" if registry.alive(worker.id) else "não",
            worker.last_seen[:19],
        )

    console.print(table)

@worker_app.command("assign")
def worker_assign(
    url: str = typer.Argument(..., help="URL que seria processada"),
    region: Optional[str] = typer.Option(None, "--region", "-r", help="Forçar uma região"),
):
    """Show which worker would take a job, and why."""
    from zfrog.workers import WorkerRegistry

    assignment = WorkerRegistry().assign(url, preferred_region=region)
    if assignment.worker is None:
        console.print(f"[yellow]Nenhum worker disponível[/] — {assignment.reason}")
        return

    console.print(f"[green]{assignment.worker.id}[/] em {assignment.worker.region}")
    console.print(f"[dim]{assignment.reason}[/]")

@worker_app.command("run")
def worker_run(
    region: Optional[str] = typer.Option(None, "--region", "-r", help="Região deste worker"),
    capacity: int = typer.Option(1, "--capacity", "-c", help="Jobs simultâneos"),
    interval: int = typer.Option(20, "--interval", help="Segundos entre batidas"),
):
    """Register this machine as a worker and keep its heartbeat."""
    from zfrog.workers import WorkerRegistry, current_worker_id, heartbeat_loop

    worker_id = current_worker_id()
    target = region or settings_region()

    # Register explicitly: the heartbeat loop only re-registers a missing worker,
    # so the region and capacity the user asked for have to land here.
    WorkerRegistry().register(worker_id, target, capacity=capacity)

    console.print(f"[green]Worker {worker_id}[/] na região {target} (capacidade {capacity}).")
    console.print("[dim]Ctrl+C para parar.[/]")

    try:
        asyncio.run(heartbeat_loop(worker_id, interval_s=interval))
    except KeyboardInterrupt:
        console.print("\n[dim]Worker parado.[/]")

def settings_region() -> str:
    """The configured region (helper for the worker command)."""
    from zfrog.config import settings

    return settings.region

market_sync_app = typer.Typer(help="Sincronizar um índice de marketplace remoto.")
app.add_typer(market_sync_app, name="market-index")

@market_sync_app.command("build")
def market_index_build(
    output: Path = typer.Option(Path("marketplace-index.json"), "--output", "-o", help="Arquivo de saída"),
    source: str = typer.Option("", "--source", help="Nome da origem (para o cabeçalho)"),
):
    """Build an index of the locally published marketplace assets."""
    from zfrog.marketplace_index import index_from_marketplace, index_summary, write_index

    index = index_from_marketplace(source=source)
    path = write_index(output, index)
    console.print(f"[green]Índice escrito[/] em {path}")
    console.print(f"[dim]{index_summary(index)}[/]")

@market_sync_app.command("sync")
def market_index_sync(
    index_url: str = typer.Argument(..., help="URL do índice remoto"),
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
        f"[green]{result.added} novo(s)[/], {result.updated} atualizado(s), "
        f"{result.unchanged} sem mudança, {result.skipped} ignorado(s)"
    )
    for error in result.errors:
        console.print(f"[yellow]{error}[/]")

@app.command()
def timeline(
    url: str = typer.Argument(..., help="URL do site"),
    when: Optional[str] = typer.Option(
        None, "--when", "-w", help="Ver como estava nesta data (ex.: 2026-09-01)"
    ),
    ref: Optional[str] = typer.Option(None, "--ref", help="Abrir uma versão específica"),
    page: Optional[str] = typer.Option(None, "--page", help="Mostrar o conteúdo de uma página"),
    restore: Optional[Path] = typer.Option(None, "--restore", help="Restaurar a versão nesta pasta"),
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
            console.print(f"[yellow]Nenhuma versão guardada até {when}.[/]")
            sys.exit(1)

        entry = next((e for e in machine.timeline() if e.ref == found), None)
        console.print(
            f"[green]Versão de {entry.captured_at if entry else found}[/]"
            + (f" — {entry.message}" if entry and entry.message else "")
        )
        ref = ref or found

    entries = machine.timeline()
    if not entries:
        console.print("[dim]Nenhuma versão guardada. Use --versioned no clone.[/]")
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
        console.print(f"[green]{len(files)} arquivo(s) restaurado(s) em {dest}[/]")
        return

    if page:
        if not ref:
            ref = entries[-1].ref
        archived = machine.page(ref, page)
        if archived is None:
            console.print(f"[red]Página {page} não existe nessa versão.[/]")
            sys.exit(1)

        html = machine.content(ref, page)
        console.print(f"[bold]{archived.title or archived.path}[/] ({archived.url})")
        if html:
            console.print(Markdown(f"```html\n{html[:2000]}\n```"))
        else:
            console.print("[dim]Conteúdo não disponível (blob ausente).[/]")
        return

    if ref:
        pages = machine.at(ref)
        table = Table(title=f"Versão {ref}")
        table.add_column("PÁGINA", style="cyan")
        table.add_column("TÍTULO")
        table.add_column("TAMANHO", justify="right")
        for archived in pages:
            table.add_row(archived.path, archived.title or "-", f"{archived.size_bytes:,} B")
        console.print(table)
        return

    console.print(f"[bold]{timeline_summary(entries)}[/]")
    listing = Table(title=f"Versões de {url}")
    listing.add_column("VERSÃO", style="cyan")
    listing.add_column("QUANDO", style="green")
    listing.add_column("PÁGINAS", justify="right")
    listing.add_column("TAMANHO", justify="right")
    listing.add_column("MENSAGEM", style="dim")
    for entry in entries:
        listing.add_row(
            entry.ref[:10],
            entry.captured_at[:19],
            str(entry.pages),
            f"{entry.size_bytes:,} B",
            entry.message[:30],
        )
    console.print(listing)

price_app = typer.Typer(help="Acompanhar preços ao longo do tempo.")
app.add_typer(price_app, name="price")

@price_app.command("watch")
def price_watch(
    url: str = typer.Argument(..., help="URL cujo último snapshot será lido"),
):
    """Read a site's latest snapshot and record its prices."""
    from zfrog.pricing import format_change, watch_url

    result = watch_url(url)
    console.print(f"[green]{result['prices']} preço(s) registrado(s)[/] em {url}")

    for change in result["changes"]:
        color = "green" if change["direction"] == "down" else "yellow"
        console.print(f"  [{color}]{format_change(change)}[/]")

@price_app.command("changes")
def price_changes(
    url: str = typer.Argument(..., help="URL a consultar"),
):
    """Show how the recorded prices moved."""
    from zfrog.pricing import PriceTracker, format_change

    changes = PriceTracker().changes(url)
    if not changes:
        console.print("[dim]Nenhum preço registrado para esse site.[/]")
        return

    table = Table(title=f"Preços de {url}")
    table.add_column("ITEM", style="cyan")
    table.add_column("ANTES", justify="right")
    table.add_column("AGORA", justify="right")
    table.add_column("VARIAÇÃO", justify="right")
    table.add_column("ALERTA", justify="center")

    for change in changes:
        color = "green" if change.direction == "down" else "red" if change.direction == "up" else "white"
        table.add_row(
            change.label,
            f"{change.before:,.2f}",
            f"{change.after:,.2f}",
            f"[{color}]{change.change_pct:+.1f}%[/]",
            "[red]sim[/]" if change.significant else "-",
        )

    console.print(table)

@app.command()
def compare_sites(
    site: list[str] = typer.Option(
        ..., "--site", "-s", help="Rótulo=pasta de um clone (pode repetir)"
    ),
    markdown: bool = typer.Option(False, "--markdown", help="Imprimir o relatório em Markdown"),
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
            console.print(f"[red]Pasta não encontrada: {path}[/]")
            sys.exit(1)
        sites[label] = path

    if len(sites) < 2:
        console.print("[yellow]Informe pelo menos dois sites para comparar.[/]")
        sys.exit(1)

    comparison = asyncio.run(compare_directories(sites))

    if markdown:
        console.print(Markdown(to_markdown(comparison)))
        return

    console.print(f"[bold]{comparison.summary}[/]")

    table = Table(title="Comparação")
    table.add_column("SITE", style="cyan")
    table.add_column("PÁGINAS", justify="right")
    table.add_column("PALAVRAS", justify="right")
    table.add_column("PREÇOS", justify="right")
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
    url: str = typer.Argument(..., help="URL do site"),
    term: list[str] = typer.Option(..., "--term", "-t", help="Termo a acompanhar (pode repetir)"),
):
    """Track terms across a site's saved history."""
    from zfrog.analysis.trends import summarize, to_markdown, trends as compute

    found = compute(url, list(term))
    if not found:
        console.print("[dim]Nenhum snapshot guardado para esse site.[/]")
        return

    console.print(Markdown(to_markdown(url, found)))
    console.print(f"[bold]{summarize(found)}[/]")

totp_app = typer.Typer(help="Códigos de dois fatores da sua própria conta.")
app.add_typer(totp_app, name="totp")

@totp_app.command("add")
def totp_add(
    name: str = typer.Argument(..., help="Nome para identificar a conta"),
    secret: str = typer.Argument(..., help="Segredo base32 (o que o site mostra)"),
    issuer: str = typer.Option("", "--issuer", help="Nome do serviço"),
):
    """Register a two-factor account."""
    from zfrog.totp import TotpStore

    try:
        account = TotpStore().add(name, secret, issuer)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Conta {account.name} registrada[/] — segredo guardado com permissão 0600")

@totp_app.command("code")
def totp_code(
    name: str = typer.Argument(..., help="Nome da conta"),
):
    """Show the current code."""
    from zfrog.totp import TotpStore, seconds_remaining

    try:
        code = TotpStore().code(name)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[bold]{code}[/] [dim](válido por {seconds_remaining()}s)[/]")

@totp_app.command("list")
def totp_list():
    """List registered two-factor accounts."""
    from zfrog.totp import TotpStore

    accounts = TotpStore().list()
    if not accounts:
        console.print("[dim]Nenhuma conta registrada.[/]")
        return

    table = Table(title="Contas de dois fatores")
    table.add_column("NOME", style="cyan")
    table.add_column("SERVIÇO")
    for account in accounts:
        table.add_row(account.get("name", ""), account.get("issuer", "") or "-")
    console.print(table)

@app.command()
def dataset(
    directory: Path = typer.Argument(..., help="Pasta clonada para virar dataset"),
    kind: str = typer.Option("extraction", "--kind", "-k", help="extraction, summary, qa ou entities"),
    fmt: str = typer.Option("chat", "--format", "-f", help="chat ou alpaca"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Arquivo .jsonl de saída"),
):
    """Build a fine-tuning dataset from a clone (training runs elsewhere)."""
    from zfrog.finetune import DatasetBuilder, dataset_summary
    from zfrog.utils.text import extract_text

    if not directory.is_dir():
        console.print(f"[red]Pasta não encontrada: {directory}[/]")
        sys.exit(1)

    pages = []
    for path in sorted(f for f in directory.rglob("*.html") if f.is_file()):
        html = path.read_text(encoding="utf-8", errors="replace")
        pages.append({"url": str(path), "path": str(path.name), "text": extract_text(html), "html": html})

    if not pages:
        console.print("[yellow]Nenhuma página HTML nessa pasta.[/]")
        sys.exit(1)

    builder = DatasetBuilder()
    added = builder.add_pages(pages, kind=kind)
    console.print(f"[green]{added} exemplo(s) gerado(s)[/]")

    try:
        written = builder.export(output, fmt=fmt)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[dim]{dataset_summary(written)}[/]")
    console.print(f"[dim]Salvo em {written}[/]")

@app.command()
def roi():
    """Show what the automation saved versus what it cost."""
    from zfrog.analytics import MetricsStore
    from zfrog.roi import inputs_from_settings, roi_from_metrics, to_markdown

    result = roi_from_metrics(inputs_from_settings(), store=MetricsStore())
    if not result.runs:
        console.print("[dim]Nada medido ainda — rode algumas extrações.[/]")
        return

    console.print(Markdown(to_markdown(result)))

@app.command()
def market_serve(
    host: str = typer.Option("", "--host", help="Endereço (default: ZFROG_MARKETPLACE_HOST)"),
    port: int = typer.Option(0, "--port", "-p", help="Porta (default: ZFROG_MARKETPLACE_PORT)"),
    source: str = typer.Option("", "--source", help="Nome da origem no índice"),
    token: str = typer.Option("", "--token", help="Exigir este token para publicar"),
):
    """Serve the marketplace index over HTTP."""
    from zfrog.marketplace_server import serve

    console.print(f"[green]Marketplace em http://{host or '127.0.0.1'}:{port or 8200}[/]")
    if token:
        console.print("[dim]Publicar exige o token informado.[/]")

    try:
        serve(host=host, port=port, source=source, require_token=token)
    except KeyboardInterrupt:
        console.print("\n[dim]Servidor parado.[/]")

@app.command()
def dispatch(
    url: list[str] = typer.Option(..., "--url", "-u", help="URL a enviar (pode repetir)"),
    mode: str = typer.Option("auto", "--mode", "-m", help="Modo do job (auto = o probe escolhe o motor)"),
    region: Optional[str] = typer.Option(None, "--region", "-r", help="Região preferida"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Só mostrar para onde iria"),
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
    directory: Path = typer.Argument(..., help="Pasta clonada a arquivar"),
):
    """Publish a clone to Arweave for permanent archiving."""
    from zfrog.storage.arweave import publish_clone

    if not directory.is_dir():
        console.print(f"[red]Pasta não encontrada: {directory}[/]")
        sys.exit(1)

    try:
        result = asyncio.run(publish_clone(directory))
    except RuntimeError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    console.print(f"[green]Publicado[/] — {result['size_bytes']:,} bytes")
    console.print(f"ID: [cyan]{result['item_id']}[/]")
    console.print(f"[dim]{result['gateway_url']}[/]")

# ── referências de design ───────────────────────────────────────────────────────
# jump/tongue/pond: as três palavras do sapo. jump captura, tongue extrai um
# componente, pond é o catálogo onde tudo fica.

@app.command()
def jump(
    url: str = typer.Argument(..., help="Endereço da página a capturar"),
    breakpoint_name: str = typer.Option(
        "desktop",
        "--breakpoint",
        "-b",
        help="Resolução do screenshot: desktop, tablet ou mobile",
    ),
    tag: list[str] = typer.Option([], "--tag", "-t", help="Etiqueta para a referência (pode repetir)"),
    viewport_only: bool = typer.Option(
        False,
        "--viewport-only",
        help="Captura só o que cabe na tela, em vez da página inteira",
    ),
    image_format: str = typer.Option(
        "png", "--format", "-f", help="Formato da imagem: png (sem perda) ou webp (menor)"
    ),
    output: str = typer.Option("output", "--output", "-o", help="Diretório de saída"),
):
    """Capture uma página como referência: screenshot + tokens de design."""
    from zfrog.engines.jump import BREAKPOINTS, DEFAULT_BREAKPOINT
    from zfrog.orchestrator import run_job

    if breakpoint_name not in BREAKPOINTS:
        console.print(
            f"[red]Resolução desconhecida:[/] {breakpoint_name}. "
            f"Use uma de: {', '.join(BREAKPOINTS)}"
        )
        sys.exit(1)

    if image_format.lower() not in ("png", "webp"):
        console.print(f"[red]Formato desconhecido:[/] {image_format} (use png ou webp)")
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
        f"Capturando [cyan]{url}[/] em {breakpoint_name}"
        + ("" if not viewport_only else " (só o viewport)")
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Capturando…", total=None)

        try:
            result = asyncio.run(run_job(job))
        except Exception as e:
            console.print(f"[red]Falhou:[/] {e}")
            sys.exit(1)

        progress.update(task, description="[green]Pronto[/]")

    console.print(f"[green]Capturado[/] — {result.files_count} arquivos, "
                  f"{result.total_size_bytes:,} bytes em {result.duration_seconds:.1f}s")
    _print_tokens_summary(_job_dir(result))

@app.command()
def tongue(
    url: str = typer.Argument(..., help="Endereço da página"),
    selector: str = typer.Argument(..., help="Seletor CSS do componente (ex.: .hero, #nav)"),
    output: str = typer.Option("output", "--output", "-o", help="Diretório de saída"),
):
    """Extrai um componente: o HTML e o CSS que o navegador aplicou nele."""
    from zfrog.config import settings
    from zfrog.orchestrator import run_job

    settings.output_dir = Path(output)

    job = JobCreate(url=url, mode="tongue", selector=selector)

    console.print(f"Extraindo [cyan]{selector}[/] de {url}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Extraindo…", total=None)

        try:
            result = asyncio.run(run_job(job))
        except Exception as e:
            console.print(f"[red]Falhou:[/] {e}")
            sys.exit(1)

        progress.update(task, description="[green]Pronto[/]")

    console.print(f"[green]Extraído[/] — {result.files_count} arquivos")
    _print_component_summary(_job_dir(result))

@app.command()
def pond(
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filtrar por etiqueta"),
    color: Optional[str] = typer.Option(None, "--color", "-c", help="Filtrar por cor (ex.: #3BD487)"),
    site: Optional[str] = typer.Option(None, "--site", "-s", help="Filtrar por site"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Buscar no endereço, título ou nota"),
    describe: Optional[str] = typer.Option(
        None,
        "--search",
        help="Buscar por descrição visual (ex.: \"layouts escuros com cards arredondados\")",
    ),
    reindex: bool = typer.Option(
        False, "--reindex", help="Reindexar os embeddings do catálogo antes de buscar"
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="Quantas referências mostrar"),
):
    """Lista as referências capturadas, ou busca por descrição com --search."""
    from zfrog.catalog import Catalog
    from zfrog.config import settings

    catalog = Catalog(Path(settings.catalog_db))

    if reindex:
        from zfrog.visual_search import embed_catalog_sync

        result = embed_catalog_sync(catalog, force=True)
        if result.indexed:
            console.print(f"[green]{result.indexed} referência(s) indexada(s).[/]")
        else:
            # Say *why*, not just "nothing happened": an empty catalog, an already
            # indexed one and a broken model need three different actions.
            console.print(f"[yellow]Nada indexado.[/] {result.reason}")

    if describe:
        from zfrog.visual_search import search_descriptive

        hits = asyncio.run(search_descriptive(catalog, describe, limit=limit))
        if not hits:
            console.print(f"[yellow]Nada encontrado para[/] “{describe}”.")
            return

        table = Table(title=f"Busca por descrição — “{describe}” ({len(hits)})")
        table.add_column("ID", style="dim")
        table.add_column("RELEVÂNCIA", justify="right", style="green")
        table.add_column("SITE", style="cyan")
        table.add_column("TÍTULO")
        table.add_column("COR", style="green")
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
            console.print("[yellow]Nenhuma referência bate com esses filtros.[/]")
        else:
            console.print(
                "[yellow]O catálogo está vazio.[/] Capture uma página com "
                "[cyan]zfrog jump <url>[/]."
            )
        return

    table = Table(title=f"Referências ({len(cards)} de {catalog.count()})")
    table.add_column("ID", style="dim")
    table.add_column("SITE", style="cyan")
    table.add_column("TÍTULO")
    table.add_column("COR", style="green")
    table.add_column("TAGS", style="magenta")
    table.add_column("QUANDO", style="dim")

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
                "[dim]cores:[/] " + " · ".join(f"{hex_color} ({count})" for hex_color, count in colors)
            )

@app.command()
def show(
    card_id: str = typer.Argument(..., help="ID da referência (prefixo serve)"),
):
    """Mostra os detalhes de uma referência capturada."""
    from zfrog.catalog import Catalog
    from zfrog.config import settings

    catalog = Catalog(Path(settings.catalog_db))

    card = catalog.get(card_id)
    if card is None:
        matches = [c for c in catalog.list(limit=1000) if c.id.startswith(card_id)]
        if len(matches) == 1:
            card = matches[0]
        elif len(matches) > 1:
            console.print(f"[yellow]Prefixo ambíguo:[/] {len(matches)} referências começam com isso.")
            for match in matches[:10]:
                console.print(f"  {match.id[:12]} — {match.site}")
            sys.exit(1)

    if card is None:
        console.print(f"[red]Referência não encontrada:[/] {card_id}")
        sys.exit(1)

    console.print(f"[bold]{card.title or card.url}[/]")
    console.print(f"[dim]{card.url}[/]")
    console.print()

    details = Table.grid(padding=(0, 2))
    details.add_column(style="dim")
    details.add_column()
    details.add_row("ID", card.id)
    details.add_row("Site", card.site)
    details.add_row("Capturado", card.captured_at_label)
    details.add_row("Modo", f"{card.mode} · {card.engine}")
    details.add_row("Screenshot", card.screenshot or "—")
    details.add_row("Tags", ", ".join(card.tags) or "—")
    details.add_row("Nota", card.note or "—")
    console.print(details)

    tokens = card.tokens or {}
    palette = tokens.get("palette", [])
    if palette:
        console.print()
        palette_table = Table(title="Paleta")
        palette_table.add_column("COR", style="green")
        palette_table.add_column("USOS", justify="right")
        palette_table.add_column("PAPEL", style="cyan")
        for entry in palette[:12]:
            palette_table.add_row(entry.get("hex", ""), str(entry.get("count", 0)), entry.get("role") or "—")
        console.print(palette_table)

    fonts = tokens.get("fonts", [])
    if fonts:
        console.print()
        for font in fonts[:6]:
            console.print(f"[bold]{font.get('family')}[/] — {font.get('count')} elementos")

@app.command()
def export(
    card_id: str = typer.Argument(..., help="ID da referência"),
    fmt: str = typer.Option("json", "--format", "-f", help="json, md ou html"),
    dest: Optional[Path] = typer.Option(None, "--dest", "-d", help="Onde salvar (default: stdout)"),
):
    """Exporta uma referência como JSON, Markdown ou um mini style guide em HTML."""
    from zfrog.catalog import Catalog
    from zfrog.config import settings

    catalog = Catalog(Path(settings.catalog_db))
    card = catalog.get(card_id)
    if card is None:
        matches = [c for c in catalog.list(limit=1000) if c.id.startswith(card_id)]
        if len(matches) == 1:
            card = matches[0]

    if card is None:
        console.print(f"[red]Referência não encontrada:[/] {card_id}")
        sys.exit(1)

    if fmt == "json":
        payload = json.dumps(card.to_dict(), ensure_ascii=False, indent=2)
    elif fmt == "md":
        payload = _card_markdown(card)
    elif fmt == "html":
        payload = _card_html(card)
    else:
        console.print(f"[red]Formato desconhecido:[/] {fmt} (use json, md ou html)")
        sys.exit(1)

    if dest is None:
        console.print(payload)
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(payload, encoding="utf-8")
    console.print(f"[green]Salvo[/] em {dest}")

def _job_dir(result) -> Path:
    """The job's output *directory*.

    ``JobResult.output_path`` is the packaged ZIP, not the directory — the reports
    (tokens, component) are siblings of it, so the parent is what callers need.
    """
    path = Path(result.output_path)
    return path.parent if path.is_file() or path.suffix == ".zip" else path


def _print_tokens_summary(output_dir: Path) -> None:
    """Show the token report of a finished jump, when there is one."""
    report = output_dir / "design-tokens.md"
    if not report.exists():
        return
    console.print()
    console.print(Markdown(report.read_text(encoding="utf-8")))


def _print_component_summary(output_dir: Path) -> None:
    """Show the component report of a finished tongue, when there is one."""
    report = output_dir / "component.md"
    if not report.exists():
        return
    console.print()
    console.print(Markdown(report.read_text(encoding="utf-8")))

def _card_markdown(card) -> str:
    """A capture as a Markdown reference sheet."""
    tokens = card.tokens or {}
    lines = [
        f"# {card.title or card.url}",
        "",
        f"- **Site**: {card.site}",
        f"- **Origem**: {card.url}",
        f"- **Capturado**: {card.captured_at_label}",
        f"- **Modo**: {card.mode} · {card.engine}",
        f"- **Tags**: {', '.join(card.tags) or '—'}",
    ]
    if card.screenshot:
        lines.append(f"- **Screenshot**: {card.screenshot}")
    if card.note:
        lines += ["", f"> {card.note}"]

    palette = tokens.get("palette", [])
    if palette:
        lines += ["", "## Paleta", ""]
        for entry in palette[:12]:
            role = f" · *{entry['role']}*" if entry.get("role") else ""
            lines.append(f"- `{entry.get('hex')}` ×{entry.get('count')}{role}")

    fonts = tokens.get("fonts", [])
    if fonts:
        lines += ["", "## Tipografia", ""]
        for font in fonts[:6]:
            sizes = ", ".join(list(font.get("sizes", {}).keys())[:4]) or "—"
            lines.append(f"- **{font.get('family')}** — tamanhos: {sizes}")

    return "\n".join(lines) + "\n"

def _swatch(entry: dict) -> str:
    """One palette swatch as a <figure>."""
    import html as html_module

    hex_color = html_module.escape(str(entry.get("hex", "")))
    role = entry.get("role")
    caption = f"{hex_color} · {html_module.escape(str(role))}" if role else hex_color
    return (
        f'<figure><div style="background:{hex_color}"></div>'
        f"<figcaption><code>{caption}</code></figcaption></figure>"
    )


def _card_html(card) -> str:
    """A capture as a self-contained mini style guide."""
    import html as html_module

    escape = html_module.escape
    tokens = card.tokens or {}

    swatches = "".join(_swatch(entry) for entry in tokens.get("palette", [])[:16])
    fonts = "".join(
        f"<li><strong>{escape(str(font.get('family', '')))}</strong> — "
        f"{escape(', '.join(list(font.get('sizes', {}).keys())[:5]))}</li>"
        for font in tokens.get("fonts", [])[:8]
    )
    screenshot = (
        f'<img src="{escape(card.screenshot)}" alt="Captura de {escape(card.site)}">'
        if card.screenshot
        else ""
    )
    tags = (
        f'<span>{" ".join(escape(tag) for tag in card.tags)}</span>' if card.tags else ""
    )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>{escape(card.title or card.url)} — referência zfrog</title>
<style>
  body {{ font: 14px/1.6 system-ui, sans-serif; margin: 0 auto; max-width: 900px; padding: 32px; }}
  h1 {{ font-size: 24px; margin: 0 0 4px; }}
  h2 {{ font-size: 16px; margin: 28px 0 10px; }}
  .url {{ color: #666; font-family: ui-monospace, monospace; font-size: 13px; }}
  .meta {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 16px 0 24px; font-size: 13px; color: #555; }}
  .swatches {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 12px; }}
  figure {{ margin: 0; }}
  figure div {{ height: 56px; border-radius: 8px; border: 1px solid rgba(0,0,0,.1); }}
  figcaption {{ font-size: 11px; margin-top: 4px; color: #666; }}
  img {{ max-width: 100%; border-radius: 8px; border: 1px solid rgba(0,0,0,.1); }}
  ul {{ padding-left: 18px; }}
</style>
</head>
<body>
  <h1>{escape(card.title or card.url)}</h1>
  <p class="url">{escape(card.url)}</p>
  <div class="meta">
    <span>{escape(card.site)}</span>
    <span>{escape(card.captured_at_label)}</span>
    <span>{escape(card.mode)} · {escape(card.engine)}</span>
    {tags}
  </div>
  {screenshot}
  <h2>Paleta</h2>
  <div class="swatches">{swatches}</div>
  <h2>Tipografia</h2>
  <ul>{fonts}</ul>
</body>
</html>
"""

if __name__ == "__main__":
    app()
