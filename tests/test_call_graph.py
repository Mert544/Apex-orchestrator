from __future__ import annotations

from pathlib import Path

from app.engine.call_graph import CallGraph, render_impact_markdown


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    # Unique names so name-based resolution is unambiguous:
    #   alpha <- beta <- gamma  (gamma calls beta calls alpha)
    (tmp_path / "app" / "core.py").write_text(
        "def alpha(x):\n    return x + 1\n\n"
        "def beta(x):\n    return alpha(x)\n"
    )
    (tmp_path / "app" / "use.py").write_text(
        "from app.core import beta\n\ndef gamma(x):\n    return beta(x)\n\n"
        "def lonely():\n    return 1\n"
    )
    return tmp_path


def test_definitions_located():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    _project(tmp)
    g = CallGraph.build(str(tmp))
    defs = g.definitions("alpha")
    assert len(defs) == 1
    assert defs[0].module == "app/core.py" and defs[0].name == "alpha"


def test_direct_callers(tmp_path):
    _project(tmp_path)
    g = CallGraph.build(str(tmp_path))
    callers = {c.name for c in g.direct_callers("alpha")}
    assert callers == {"beta"}  # only beta calls alpha directly


def test_transitive_blast_radius(tmp_path):
    _project(tmp_path)
    g = CallGraph.build(str(tmp_path))
    radius = {r.name for r in g.blast_radius("alpha")}
    # beta calls alpha; gamma calls beta -> both are in alpha's blast radius.
    assert radius == {"beta", "gamma"}


def test_leaf_function_has_no_callers(tmp_path):
    _project(tmp_path)
    g = CallGraph.build(str(tmp_path))
    assert g.direct_callers("lonely") == []
    assert g.blast_radius("lonely") == []


def test_unknown_function(tmp_path):
    _project(tmp_path)
    g = CallGraph.build(str(tmp_path))
    assert g.definitions("does_not_exist") == []
    assert g.blast_radius("does_not_exist") == []


def test_recursion_terminates(tmp_path):
    (tmp_path / "r.py").write_text("def recur(n):\n    return recur(n - 1)\n")
    g = CallGraph.build(str(tmp_path))
    # Self-call must not loop forever; recur is its own (only) caller.
    assert {r.name for r in g.blast_radius("recur")} == {"recur"}


def test_hub_names_stop_propagation(tmp_path):
    # `run` is a hub: changing `target` reaches run() directly, but run()'s many
    # callers are NOT pulled in transitively through the generic name.
    (tmp_path / "h.py").write_text(
        "def target():\n    return 1\n\n"
        "def run():\n    return target()\n\n"
        "def a():\n    return run()\n\n"
        "def b():\n    return run()\n"
    )
    g = CallGraph.build(str(tmp_path))
    radius = {r.name for r in g.blast_radius("target")}
    assert "run" in radius              # direct caller still reported
    assert "a" not in radius and "b" not in radius  # not expanded through the hub


def test_render_markdown(tmp_path):
    _project(tmp_path)
    g = CallGraph.build(str(tmp_path))
    md = render_impact_markdown("alpha", g)
    assert "Impact of changing `alpha()`" in md
    assert "Blast radius" in md
    assert "beta" in md and "gamma" in md
    # Unknown function renders a clean message, not a crash.
    assert "No function named" in render_impact_markdown("nope", g)


def test_max_depth_limits_propagation(tmp_path):
    (tmp_path / "c.py").write_text(
        "def f0():\n    return 1\n\ndef f1():\n    return f0()\n\n"
        "def f2():\n    return f1()\n\ndef f3():\n    return f2()\n"
    )
    g = CallGraph.build(str(tmp_path))
    names = {r.name for r in g.blast_radius("f0", max_depth=1)}
    assert "f1" in names          # depth 1 reached
    assert "f3" not in names      # beyond the depth cap
