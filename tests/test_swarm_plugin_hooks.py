"""The event-driven swarm path must fire plugin lifecycle hooks.

Previously `main()`'s swarm path bypassed the plugin registry, so
before_scan/after_scan/on_report never fired during the primary flow.
"""
from __future__ import annotations

from pathlib import Path

from app.main import _build_swarm_for_plan, _run_swarm_with_plugins
from app.plugins.registry import PluginRegistry

_PLUGIN_SRC = '''
from pathlib import Path

_LOG = Path(__file__).with_name("hooks.log")


def _record(name):
    def hook(ctx):
        with _LOG.open("a", encoding="utf-8") as f:
            f.write(name + "\\n")
    return hook


def register(proxy):
    proxy.add_hook("before_scan", _record("before_scan"))
    proxy.add_hook("after_scan", _record("after_scan"))
    proxy.add_hook("on_report", _record("on_report"))
'''


def _load_recording_plugins(plugin_dir: Path) -> PluginRegistry:
    (plugin_dir / "audit_plugin.py").write_text(_PLUGIN_SRC, encoding="utf-8")
    plugins = PluginRegistry(plugin_dirs=[str(plugin_dir)])
    plugins.load_all()
    return plugins


def test_swarm_path_fires_plugin_lifecycle_hooks(tmp_path: Path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugins = _load_recording_plugins(plugin_dir)
    # At least our recording plugin loaded (the repo's plugins/ dir may add more).
    assert any(p["name"] == "audit_plugin" for p in plugins.list_plugins())

    swarm = _build_swarm_for_plan("project_scan")
    results, md_path = _run_swarm_with_plugins(
        swarm,
        plugins,
        objective="scan the project",
        target="examples/flask_mini",
        mode="report",
        plan_name="project_scan",
        report_dir=tmp_path / ".apex",
    )

    # The swarm still produces scanner results and a report.
    assert len(results) >= 1
    assert md_path.exists()

    # All three lifecycle hooks fired, in order.
    fired = (plugin_dir / "hooks.log").read_text(encoding="utf-8").split()
    assert fired == ["before_scan", "after_scan", "on_report"]


def test_swarm_with_no_plugins_still_runs(tmp_path: Path):
    plugins = PluginRegistry(plugin_dirs=[])  # no plugins loaded
    plugins.load_all()
    swarm = _build_swarm_for_plan("project_scan")

    results, md_path = _run_swarm_with_plugins(
        swarm,
        plugins,
        objective="scan the project",
        target="examples/flask_mini",
        mode="report",
        plan_name="project_scan",
        report_dir=tmp_path / ".apex",
    )
    assert len(results) >= 1
    assert md_path.exists()
