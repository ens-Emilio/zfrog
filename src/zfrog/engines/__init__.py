"""Engine registry and factory with plugin discovery.

Engines are collected from three sources, in precedence order:

1. Built-in engines shipped with Zfrog (``_BUILTIN_ENGINES``).
2. Entry points published by third-party packages under the ``zfrog.engines``
   group (``[project.entry-points."zfrog.engines"]`` in their ``pyproject.toml``).
3. Local plugin files (``*.py``) found in ``settings.plugins_dir``.

A broken plugin never breaks Zfrog: load failures and name collisions are logged
and the offending plugin is skipped.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import logging
import sys
from pathlib import Path

from zfrog.config import settings
from zfrog.engines.base import EngineAdapter
from zfrog.engines.wget import WgetEngine
from zfrog.engines.static_file import StaticFileEngine
from zfrog.engines.playwright import PlaywrightEngine
from zfrog.engines.scrapy import ScrapyEngine
from zfrog.engines.jump import JumpEngine
from zfrog.engines.tongue import TongueEngine
from zfrog.engines.analyze import AnalyzeEngine
from zfrog.engines.compare import CompareEngine
from zfrog.engines.ask import AskEngine
from zfrog.engines.pdf import PdfEngine
from zfrog.engines.summarize import SummarizeEngine
from zfrog.engines.delta import DeltaEngine
from zfrog.engines.entities import EntitiesEngine
from zfrog.engines.enrich import EnrichEngine
from zfrog.engines.video import VideoEngine
from zfrog.engines.translate import TranslateEngine
from zfrog.engines.api_discovery import ApiDiscoveryEngine

logger = logging.getLogger(__name__)

# Registry of engines shipped with Zfrog.
#
# The four capture motors have distinct, non-overlapping roles:
#   playwright   visual capture — renders the page, keeps the CSS/JS/images the
#                browser loaded. The default motor.
#   scrapy       discovery — maps which pages exist on a site before capture.
#   static_file  light capture — pages that render without JavaScript.
#   wget         assets — downloads the static files behind a reference.
# Two more motors serve the design-reference use case directly:
#   jump         captures a page as a reference card: screenshot + design tokens.
#   tongue       extracts one component: its HTML and its computed CSS.
# The remaining entries are analysis/export engines, not capture motors.
_BUILTIN_ENGINES: dict[str, type[EngineAdapter]] = {
    "playwright": PlaywrightEngine,
    "scrapy": ScrapyEngine,
    "static_file": StaticFileEngine,
    "wget": WgetEngine,
    "jump": JumpEngine,
    "tongue": TongueEngine,
    "analyze": AnalyzeEngine,
    "compare": CompareEngine,
    "ask": AskEngine,
    "pdf": PdfEngine,
    "summarize": SummarizeEngine,
    "delta": DeltaEngine,
    "entities": EntitiesEngine,
    "enrich": EnrichEngine,
    "video": VideoEngine,
    "translate": TranslateEngine,
    "api_discovery": ApiDiscoveryEngine,
}

# Where each registered engine came from:
# "built-in", "entry-point:<value>" or "local:<filename>".
ENGINE_SOURCES: dict[str, str] = {}


def _register(
    registry: dict[str, type[EngineAdapter]],
    name: str,
    cls: type[EngineAdapter],
    source: str,
) -> None:
    """Add an engine to the registry, keeping the first registration of a name."""
    if not name:
        logger.warning("engine %s has no name, skipping %s", cls, source)
        return
    if name in registry:
        logger.warning("engine name %r shadowed by built-in, skipping %s", name, source)
        return
    registry[name] = cls
    ENGINE_SOURCES[name] = source


def _load_entry_point_engines(registry: dict[str, type[EngineAdapter]]) -> None:
    """Register engines published by installed packages under ``zfrog.engines``."""
    try:
        entry_points = importlib.metadata.entry_points(group="zfrog.engines")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("entry point discovery failed: %s", exc)
        return

    for ep in entry_points:
        source = f"entry-point:{ep.value}"
        try:
            cls = ep.load()
        except Exception as exc:
            logger.warning("failed to load %s: %s", source, exc)
            continue
        if isinstance(cls, type) and issubclass(cls, EngineAdapter):
            _register(registry, getattr(cls, "name", ""), cls, source)
        else:
            logger.warning("%s is not an EngineAdapter subclass, skipping", source)


def _load_local_plugins(registry: dict[str, type[EngineAdapter]]) -> None:
    """Register engines defined in ``settings.plugins_dir/*.py``."""
    plugins_dir = Path(settings.plugins_dir)
    if not plugins_dir.is_dir():
        return

    for path in sorted(plugins_dir.glob("*.py")):
        module_name = f"zfrog_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                logger.warning("cannot load plugin %s", path)
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(module_name, None)
            logger.warning("failed to load plugin %s: %s", path, exc)
            continue

        source = f"local:{path.name}"
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and obj is not EngineAdapter
                and issubclass(obj, EngineAdapter)
            ):
                _register(registry, getattr(obj, "name", ""), obj, source)


def discover_engines() -> dict[str, type[EngineAdapter]]:
    """Build the engine registry from built-ins, entry points and local plugins.

    Returns:
        Mapping of engine name to engine class. Earlier sources win on name
        collisions, so a plugin can never shadow a built-in engine.
    """
    ENGINE_SOURCES.clear()
    registry: dict[str, type[EngineAdapter]] = dict(_BUILTIN_ENGINES)
    for name in registry:
        ENGINE_SOURCES[name] = "built-in"

    _load_entry_point_engines(registry)
    _load_local_plugins(registry)
    return registry


# Registry of available engines (discovered once at import time)
ENGINES: dict[str, type[EngineAdapter]] = discover_engines()


def engine_source(name: str) -> str:
    """Return where a registered engine came from ("built-in", "local:x.py", ...)."""
    return ENGINE_SOURCES.get(name, "unknown")


def get_engine(name: str) -> EngineAdapter:
    """Get an engine instance by name.
    
    Args:
        name: Engine name.
        
    Returns:
        Engine instance.
        
    Raises:
        ValueError: If engine not found.
    """
    engine_cls = ENGINES.get(name)
    if not engine_cls:
        raise ValueError(f"Unknown engine: {name}. Available: {list(ENGINES.keys())}")
    return engine_cls()


def get_engine_for_probe(probe) -> EngineAdapter:
    """Get the appropriate engine based on probe results.

    The decision follows the zfrog capture flow: a page that needs JavaScript
    goes to Playwright (the visual capture motor), a plain static page goes to
    StaticFile (the light motor), and anything the probe could not classify
    falls back to Playwright — a missed render loses the design, while a missed
    shortcut only costs speed.

    Args:
        probe: ProbeResult with suggested_engine.

    Returns:
        Engine instance that can handle the probe.
    """
    # Try suggested engine first
    if probe.suggested_engine in ENGINES:
        engine = ENGINES[probe.suggested_engine]()
        if engine.can_handle(probe):
            return engine

    # Fallback to Playwright: rendering always works, even when it is slower
    # than the light path would have been.
    return PlaywrightEngine()
