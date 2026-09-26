"""Tests for engine plugin discovery (entry points and local plugins)."""

import importlib
import importlib.metadata
import sys

import pytest

import zfrog.engines as engines_module
from zfrog.config import settings
from zfrog.engines.base import EngineAdapter
from zfrog.engines.wget import WgetEngine

BUILTIN_NAMES = {"wget", "static_file", "playwright", "scrapy", "analyze", "compare", "ask"}

PLUGIN_SOURCE = '''
from zfrog.engines.base import EngineAdapter
from zfrog.models import JobCreate, ProbeResult


class MyPlugEngine(EngineAdapter):
    name = "testplug"

    async def execute(self, job: JobCreate, output_dir, on_progress=None):
        raise NotImplementedError

    def can_handle(self, probe: ProbeResult) -> bool:
        return False
'''


class FakeEntryPoint:
    """Minimal stand-in for importlib.metadata.EntryPoint."""

    def __init__(self, value, loaded):
        self.value = value
        self._loaded = loaded

    def load(self):
        if isinstance(self._loaded, Exception):
            raise self._loaded
        return self._loaded


class EntryPointEngine(EngineAdapter):
    """Engine returned by the fake entry point."""

    name = "epplug"

    async def execute(self, job, output_dir, on_progress=None):
        raise NotImplementedError

    def can_handle(self, probe) -> bool:
        return False


@pytest.fixture(autouse=True)
def _restore_engines():
    """Restore settings and the module-level registry after each test."""
    original_dir = settings.plugins_dir
    yield
    settings.plugins_dir = original_dir
    for name in [n for n in sys.modules if n.startswith("zfrog_plugin_")]:
        del sys.modules[name]
    importlib.reload(engines_module)


def test_discover_returns_builtins(tmp_path, monkeypatch):
    """Built-ins are always registered, even when the plugins dir is absent."""
    monkeypatch.setattr(settings, "plugins_dir", tmp_path / "does-not-exist")

    registry = engines_module.discover_engines()

    assert BUILTIN_NAMES <= set(registry)
    assert engines_module.engine_source("wget") == "built-in"


def test_local_plugin_discovered(tmp_path, monkeypatch):
    (tmp_path / "myplug.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
    monkeypatch.setattr(settings, "plugins_dir", tmp_path)

    importlib.reload(engines_module)

    assert "testplug" in engines_module.ENGINES
    assert engines_module.engine_source("testplug") == "local:myplug.py"
    engine_cls = engines_module.ENGINES["testplug"]
    assert engine_cls.__name__ == "MyPlugEngine"
    assert isinstance(engines_module.get_engine("testplug"), engine_cls)


def test_broken_plugin_skipped(tmp_path, monkeypatch):
    (tmp_path / "bad.py").write_text('raise RuntimeError("boom")\n', encoding="utf-8")
    (tmp_path / "good.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
    monkeypatch.setattr(settings, "plugins_dir", tmp_path)

    registry = engines_module.discover_engines()

    assert BUILTIN_NAMES <= set(registry)
    # A plugin that explodes on import must not stop the remaining ones
    assert "testplug" in registry


def test_name_collision_keeps_builtin(tmp_path, monkeypatch):
    shadow = PLUGIN_SOURCE.replace("MyPlugEngine", "ShadowWgetEngine").replace(
        'name = "testplug"', 'name = "wget"'
    )
    (tmp_path / "shadow.py").write_text(shadow, encoding="utf-8")
    monkeypatch.setattr(settings, "plugins_dir", tmp_path)

    importlib.reload(engines_module)

    assert engines_module.ENGINES["wget"] is WgetEngine
    assert engines_module.engine_source("wget") == "built-in"


def test_entry_point_discovered(monkeypatch):
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda group=None: [FakeEntryPoint("somepkg:EntryPointEngine", EntryPointEngine)],
    )

    registry = engines_module.discover_engines()

    assert registry["epplug"] is EntryPointEngine
    assert engines_module.engine_source("epplug") == "entry-point:somepkg:EntryPointEngine"


def test_broken_entry_point_skipped(monkeypatch):
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda group=None: [
            FakeEntryPoint("ghost:Missing", ImportError("no such module")),
            FakeEntryPoint("somepkg:EntryPointEngine", EntryPointEngine),
        ],
    )

    registry = engines_module.discover_engines()

    assert BUILTIN_NAMES <= set(registry)
    assert registry["epplug"] is EntryPointEngine
