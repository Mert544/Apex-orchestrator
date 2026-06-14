"""Plugins can contribute development operators to the Idea Permutation Engine."""
from pathlib import Path

from app.engine.idea_permutation import DEVELOPMENT_OPERATORS, IdeaPermutationEngine, Operator
from app.plugins.registry import PluginRegistry

_PLUGIN_SRC = '''
__plugin_name__ = "tracing_ops"

def register(proxy):
    proxy.add_operator("trace", "Add distributed tracing to {x}", 0.5)
'''


def _project(tmp: Path) -> Path:
    (tmp / "app").mkdir()
    (tmp / "app" / "main.py").write_text("def main():\n    return 1\n")
    return tmp


def test_proxy_collects_operators(tmp_path):
    (tmp_path / "p.py").write_text(_PLUGIN_SRC, encoding="utf-8")
    reg = PluginRegistry(plugin_dirs=[str(tmp_path)])
    reg.load_all()
    ops = reg.idea_operators()
    assert any(o["name"] == "trace" and "{x}" in o["template"] for o in ops)


def test_engine_uses_plugin_operator(tmp_path):
    _project(tmp_path)
    extra = [{"name": "trace", "template": "Add distributed tracing to {x}", "feasibility": 0.5}]
    # Breadth must span the whole alphabet (built-ins + the plugin) so the
    # appended operator is reachable regardless of how many built-in lenses
    # exist — otherwise a single-module project fills its budget with the
    # earlier lenses and never applies the plugin's.
    breadth = len(DEVELOPMENT_OPERATORS) + len(extra)
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 40, "max_idea_depth": 2, "breadth": breadth}, tmp_path,
        extra_operators=extra,
    ).run()
    assert any(i.operator == "trace" for i in rep.ideas)


def test_invalid_operator_template_is_ignored(tmp_path):
    _project(tmp_path)
    extra = [{"name": "bad", "template": "no placeholder", "feasibility": 0.5}]
    eng = IdeaPermutationEngine({"max_total_ideas": 10}, tmp_path, extra_operators=extra)
    assert all(op.name != "bad" for op in eng.operators)


def test_accepts_operator_instances(tmp_path):
    _project(tmp_path)
    eng = IdeaPermutationEngine(
        {"max_total_ideas": 10}, tmp_path,
        extra_operators=[Operator("trace", "Trace {x}", 0.5)],
    )
    assert any(op.name == "trace" for op in eng.operators)
