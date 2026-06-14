"""Plugin discovery order is deterministic across repeated runs.

If two plugins register the same name, filesystem iteration order must not
decide which one wins; discovery sorts so load order is stable.
"""
from pathlib import Path

from app.plugins.registry import PluginRegistry

# Two plugins that both register the operator name "shared" but differ in the
# template, so load order is observable: whichever loads last appends last.
_PLUGIN_A = '''
__plugin_name__ = "a_plugin"

def register(proxy):
    proxy.add_operator("shared", "A handles {x}", 0.5)
'''

_PLUGIN_B = '''
__plugin_name__ = "b_plugin"

def register(proxy):
    proxy.add_operator("shared", "B handles {x}", 0.5)
'''


def _write_plugins(tmp: Path) -> None:
    (tmp / "b_plugin.py").write_text(_PLUGIN_B, encoding="utf-8")
    (tmp / "a_plugin.py").write_text(_PLUGIN_A, encoding="utf-8")


def _our_names(reg: PluginRegistry) -> list[str]:
    """Names contributed by our tmp dir, in discovery order (ignore the project
    default ``plugins/`` dir that ``discover`` also appends)."""
    ours = {"a_plugin", "b_plugin"}
    return [p.stem for p in reg.discover() if p.stem in ours]


def test_discover_order_is_sorted(tmp_path: Path):
    _write_plugins(tmp_path)
    reg = PluginRegistry(plugin_dirs=[str(tmp_path)])
    names = _our_names(reg)
    assert names == ["a_plugin", "b_plugin"]


def test_discover_order_is_stable_across_repeats(tmp_path: Path):
    _write_plugins(tmp_path)
    reg = PluginRegistry(plugin_dirs=[str(tmp_path)])
    first = _our_names(reg)
    for _ in range(5):
        assert _our_names(reg) == first


def test_same_name_registration_winner_is_deterministic(tmp_path: Path):
    _write_plugins(tmp_path)
    reg = PluginRegistry(plugin_dirs=[str(tmp_path)])
    reg.load_all()
    templates = [o["template"] for o in reg.idea_operators() if o["name"] == "shared"]
    # Sorted load order: a_plugin loads before b_plugin, so both appear in that
    # order and the last-writer ("B handles {x}") is stable run to run.
    assert templates == ["A handles {x}", "B handles {x}"]
