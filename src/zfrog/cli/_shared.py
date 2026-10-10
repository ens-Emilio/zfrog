"""Shared helpers for CLI commands."""

import asyncio
import html as html_module
import os
import signal
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown

console = Console()

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
    except TimeoutError:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        await proc.wait()


async def _run_dev(host: str, api_port: int, web_port: int, dashboard_dir: Path, reload: bool,
                   redis_ok: bool = False) -> int:
    """Run API, dashboard and — when Redis answers — a worker, until one exits.

    The worker is not optional polish: the API dispatches to Celery whenever Redis
    answers and returns `pending` immediately. Without a worker consuming the
    queue, every extraction started from the panel sits at `pending` forever with
    nothing anywhere saying why. Either both run or neither does.
    """
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
        "VITE_API_URL": os.environ.get("VITE_API_URL", f"http://{host}:{api_port}"),
    }

    api_cmd = [
        sys.executable, "-m", "uvicorn", "zfrog.api:app",
        "--host", host, "--port", str(api_port),
    ]
    if reload:
        api_cmd.append("--reload")

    web_cmd = ["npm", "run", "dev", "--", "--port", str(web_port)]

    # `-m celery` rather than the console script: a virtualenv that was moved or
    # renamed keeps absolute paths in `bin/celery`'s shebang, and the script then
    # fails with "bad interpreter" while `python -m` works.
    worker_cmd = [sys.executable, "-m", "celery", "-A", "zfrog.queue", "worker", "-l", "info", "-c", "2"]

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
    worker_proc = None
    if redis_ok:
        worker_proc = await asyncio.create_subprocess_exec(
            *worker_cmd,
            env=child_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )

    children = [p for p in (api_proc, web_proc, worker_proc) if p is not None]

    # Install signal handlers to kill child process groups when terminal closes.
    # Without this, SIGHUP kills the parent but orphaned children survive.
    asyncio.get_running_loop()  # ensure we're inside a running loop before installing handlers
    _original_sighup = signal.getsignal(signal.SIGHUP)
    _original_sigterm = signal.getsignal(signal.SIGTERM)

    def _signal_cleanup(sig, frame):
        for proc in children:
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
    if worker_proc is not None:
        console.print(
            "  Worker    [green]celery[/]  [dim](consumes the queue;"
            " without it the job stays 'queued')[/]"
        )
    else:
        console.print("  Worker    [yellow]no Redis, jobs run in the API process[/]")
    console.print("  [dim]Ctrl+C to stop all[/]")
    console.print()

    pumps = [
        asyncio.create_task(_pump_output(api_proc.stdout, "api", "cyan")),
        asyncio.create_task(_pump_output(web_proc.stdout, "web", "magenta")),
    ]
    if worker_proc is not None:
        pumps.append(asyncio.create_task(_pump_output(worker_proc.stdout, "worker", "green")))
    waits = [asyncio.create_task(proc.wait()) for proc in children]
    labels = {id(api_proc): "API", id(web_proc): "dashboard"}
    if worker_proc is not None:
        labels[id(worker_proc)] = "worker"

    exit_code = 0
    try:
        done, _ = await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        finished = done.pop()
        exit_code = finished.result() or 0
        # `waits[i]` belongs to `children[i]`, so the finished future names the
        # process through its position.
        name = labels.get(id(children[waits.index(finished)]), "process")
        console.print(f"\n[yellow]{name} exited (code {exit_code}); stopping the rest.[/]")
    except asyncio.CancelledError:
        raise
    finally:
        # Restore original signal handlers
        signal.signal(signal.SIGTERM, _original_sigterm)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, _original_sighup)
        for proc in children:
            await _terminate(proc)
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

    client = None
    try:
        import redis

        client = redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        return True, settings.redis_url
    except Exception:
        return False, settings.redis_url
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def settings_region() -> str:
    """The configured region (helper for the worker command)."""
    from zfrog.config import settings

    return settings.region


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
        f"- **Source**: {card.url}",
        f"- **Captured**: {card.captured_at_label}",
        f"- **Mode**: {card.mode} · {card.engine}",
        f"- **Tags**: {', '.join(card.tags) or '—'}",
    ]
    if card.screenshot:
        lines.append(f"- **Screenshot**: {card.screenshot}")
    if card.note:
        lines += ["", f"> {card.note}"]

    palette = tokens.get("palette", [])
    if palette:
        lines += ["", "## Palette", ""]
        for entry in palette[:12]:
            role = f" · *{entry['role']}*" if entry.get("role") else ""
            lines.append(f"- `{entry.get('hex')}` ×{entry.get('count')}{role}")

    fonts = tokens.get("fonts", [])
    if fonts:
        lines += ["", "## Typography", ""]
        for font in fonts[:6]:
            sizes = ", ".join(list(font.get("sizes", {}).keys())[:4]) or "—"
            lines.append(f"- **{font.get('family')}** — sizes: {sizes}")

    return "\n".join(lines) + "\n"


def _swatch(entry: dict) -> str:
    """One palette swatch as a <figure>."""

    hex_color = html_module.escape(str(entry.get("hex", "")))
    role = entry.get("role")
    caption = f"{hex_color} · {html_module.escape(str(role))}" if role else hex_color
    return (
        f'<figure><div style="background:{hex_color}"></div>'
        f"<figcaption><code>{caption}</code></figcaption></figure>"
    )


def _card_html(card) -> str:
    """A capture as a self-contained mini style guide."""

    escape = html_module.escape
    tokens = card.tokens or {}

    swatches = "".join(_swatch(entry) for entry in tokens.get("palette", [])[:16])
    fonts = "".join(
        f"<li><strong>{escape(str(font.get('family', '')))}</strong> — "
        f"{escape(', '.join(list(font.get('sizes', {}).keys())[:5]))}</li>"
        for font in tokens.get("fonts", [])[:8]
    )
    screenshot = (
        f'<img src="{escape(card.screenshot)}" alt="Capture of {escape(card.site)}">'
        if card.screenshot
        else ""
    )
    tags = (
        f'<span>{" ".join(escape(tag) for tag in card.tags)}</span>' if card.tags else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(card.title or card.url)} — zfrog reference</title>
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
  <h2>Palette</h2>
  <div class="swatches">{swatches}</div>
  <h2>Typography</h2>
  <ul>{fonts}</ul>
</body>
</html>
"""


