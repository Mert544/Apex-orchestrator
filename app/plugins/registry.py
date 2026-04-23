from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class ApexPlugin:
    """A loaded plugin with metadata and hooks."""

    name: str
    version: str
    description: str
    hooks: dict[str, Callable[..., Any]] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "hooks": list(self.hooks.keys()),
        }


class PluginRegistry:
    """Discover, load, and run third-party plugins for Apex Orchestrator.

    Plugins are Python modules that expose a ``register(registry)`` function.
    The registry searches:
    1. ``plugins/`` directory under the project root
    2. ``APEX_PLUGIN_PATH`` environment variable (colon-separated)
    3. Entry points (future)
    """

    HOOK_POINTS = [
        "before_scan",
        "after_scan",
        "before_patch",
        "after_patch",
        "before_test",
        "after_test",
        "on_claim",
        "on_report",
    ]

    def __init__(self, plugin_dirs: list[str] | None = None) -> None:
        self.plugins: list[ApexPlugin] = []
        self._hooks: dict[str, list[Callable[..., Any]]] = {h: [] for h in self.HOOK_POINTS}
        self._plugin_dirs = plugin_dirs or []
        self._hook_errors: list[dict[str, Any]] = []

    def discover(self, extra_dirs: list[str] | None = None) -> list[Path]:
        """Return list of candidate plugin file paths."""
        dirs = list(self._plugin_dirs)
        if extra_dirs:
            dirs.extend(extra_dirs)
        # Default: plugins/ under project root
        root = Path(__file__).resolve().parent.parent.parent
        default_dir = root / "plugins"
        if default_dir.exists():
            dirs.append(str(default_dir))

        candidates: list[Path] = []
        for d in dirs:
            p = Path(d)
            if not p.exists():
                continue
            for f in p.glob("*.py"):
                if f.name.startswith("_"):
                    continue
                candidates.append(f)
        return candidates

    def load(self, plugin_path: Path) -> ApexPlugin | None:
        """Load a single plugin from *plugin_path*."""
        module_name = f"apex_plugin_{plugin_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_path)
        if not spec or not spec.loader:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            return None

        # Plugins must expose register(registry) callable
        register_fn = getattr(module, "register", None)
        if not callable(register_fn):
            return None

        proxy = _PluginProxy()
        try:
            register_fn(proxy)
        except Exception:
            return None

        plugin = ApexPlugin(
            name=getattr(module, "__plugin_name__", plugin_path.stem),
            version=getattr(module, "__plugin_version__", "0.0.1"),
            description=getattr(module, "__plugin_description__", ""),
            hooks=dict(proxy._hooks),
            config=dict(proxy._config),
        )
        self.plugins.append(plugin)
        for hook_name, fn in plugin.hooks.items():
            if hook_name in self._hooks:
                self._hooks[hook_name].append(fn)
        return plugin

    def load_all(self, extra_dirs: list[str] | None = None) -> list[ApexPlugin]:
        """Discover and load all plugins."""
        for path in self.discover(extra_dirs):
            self.load(path)
        return self.plugins

    def run_hook(self, hook_name: str, context: dict[str, Any]) -> dict[str, Any]:
        """Run all registered functions for *hook_name*, passing *context*.

        Each hook may mutate *context*. Returns the (possibly mutated) context.
        Isolated: one failing hook does not stop others.
        """
        errors: list[dict[str, Any]] = []
        for fn in self._hooks.get(hook_name, []):
            try:
                fn(context)
            except Exception as exc:
                errors.append({"hook": hook_name, "error": str(exc)})
        if errors:
            self._hook_errors.extend(errors)
            context.setdefault("_hook_errors", []).extend(errors)
        return context

    def list_plugins(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self.plugins]


class _PluginProxy:
    """Passed to plugin ``register()`` so they can safely add hooks."""

    def __init__(self) -> None:
        self._hooks: dict[str, Callable[..., Any]] = {}
        self._config: dict[str, Any] = {}

    def add_hook(self, name: str, fn: Callable[..., Any]) -> None:
        self._hooks[name] = fn

    def set_config(self, key: str, value: Any) -> None:
        self._config[key] = value
