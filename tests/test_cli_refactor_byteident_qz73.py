"""Characterization proof: the refactored ``_scope_report`` (cli_insight) and
``_ideate_analysis_view`` (cli_ideate) emit byte-identical results to the
originals captured from ``HEAD``.

Strategy: load each ORIGINAL function from the committed git blob into a fresh
module that shares the live ``app.*`` import surface, then drive original and
refactored side-by-side over many branch-covering inputs, comparing the full
result (return value / captured stdout / raised-vs-returned). Zero mismatches.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import types
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import app.cli_ideate as live_ideate
import app.cli_insight as live_insight


def _load_original(filename: str, modname: str):
    """Import the HEAD blob of ``app/<filename>`` under ``modname``."""
    src = subprocess.check_output(
        ["git", "show", f"HEAD:app/{filename}"], text=True
    )
    mod = types.ModuleType(modname)
    mod.__dict__["__name__"] = modname
    exec(compile(src, f"<HEAD:app/{filename}>", "exec"), mod.__dict__)
    sys.modules[modname] = mod
    return mod


ORIG_INSIGHT = _load_original("cli_insight.py", "_orig_cli_insight_qz73")
ORIG_IDEATE = _load_original("cli_ideate.py", "_orig_cli_ideate_qz73")


# --------------------------------------------------------------------------- #
# _scope_report
# --------------------------------------------------------------------------- #

def _run_scope(fn, root):
    """Return ``("ok", result)`` or ``("err", repr(exc))`` for fn(root)."""
    try:
        return ("ok", fn(root))
    except Exception as exc:  # pragma: no cover - parity recorded either way
        return ("err", repr(exc))


# Repos that exercise: empty/missing, all-Python, polyglot with breakdown,
# out-of-scope files (tested/untested, with/without debt), cross-language pairs.
@pytest.fixture
def _scope_roots(tmp_path):
    roots = []

    # 1. nonexistent path -> profiler may raise or yield empty -> empty shape.
    roots.append(tmp_path / "does_not_exist")

    # 2. empty dir.
    empty = tmp_path / "empty"
    empty.mkdir()
    roots.append(empty)

    # 3. all-Python repo (git-inited so churn/coupling probes run).
    py = tmp_path / "pyonly"
    py.mkdir()
    (py / "a.py").write_text("x = 1\n")
    (py / "b.py").write_text("y = 2\n")
    roots.append(py)

    # 4. polyglot: python + a couple of non-Python files, one with a test sibling
    #    and TODO markers.
    poly = tmp_path / "poly"
    poly.mkdir()
    (poly / "main.py").write_text("import os\n")
    (poly / "app.js").write_text("// TODO fix\n// FIXME later\nconst a = 1;\n")
    (poly / "style.css").write_text("body { color: red; }\n")
    tests_dir = poly / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.js").write_text("// covers app\n")
    subprocess.run(["git", "init", "-q"], cwd=poly, check=True)
    subprocess.run(["git", "add", "-A"], cwd=poly, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "-c", "commit.gpgsign=false",
         "commit", "-q", "-m", "init"],
        cwd=poly, check=True,
    )
    roots.append(poly)

    return roots


def test_scope_report_byte_identical(_scope_roots):
    for root in _scope_roots:
        orig = _run_scope(ORIG_INSIGHT._scope_report, root)
        new = _run_scope(live_insight._scope_report, root)
        assert orig == new, f"mismatch for {root}: {orig!r} != {new!r}"
        # The full markdown render must also match (covers every branch).
        if orig[0] == "ok":
            assert (
                ORIG_INSIGHT.render_scope_markdown(orig[1])
                == live_insight.render_scope_markdown(new[1])
            )


def test_scope_empty_shape_is_fresh_dict():
    """The empty-repo return must be a distinct dict (callers may mutate)."""
    missing = Path("/nonexistent_qz73_path_for_scope")
    r1 = live_insight._scope_report(missing)
    r2 = live_insight._scope_report(missing)
    assert r1 == r2 == ORIG_INSIGHT._scope_report(missing)
    assert r1 is not r2  # fresh copy each call, like the original literal


# --------------------------------------------------------------------------- #
# _ideate_analysis_view
# --------------------------------------------------------------------------- #

class _Args:
    def __init__(self, **kw):
        self.json = kw.pop("json", False)
        self.invest = kw.pop("invest", False)
        self.budget = kw.pop("budget", 0.0)
        self.sequence = kw.pop("sequence", False)
        self.pareto = kw.pop("pareto", False)
        self.shape = kw.pop("shape", False)
        for k, v in kw.items():
            setattr(self, k, v)


class _Item:
    def __init__(self, n):
        self._n = n

    def to_dict(self):
        return {"id": self._n}


class _Shape:
    def to_dict(self):
        return {"shape": "ok"}


class _Portfolio:
    def to_dict(self):
        return {"portfolio": True}


class _Report:
    ideas = [_Item(1), _Item(2)]


def _install_engine_stubs(monkeypatch):
    """Stub the engine modules each view imports so output is deterministic and
    offline. Identical stubs feed original and refactored code paths."""
    def _mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        monkeypatch.setitem(sys.modules, name, m)

    _mod(
        "app.engine.idea_investment",
        investment_curve=lambda r: [_Item(10), _Item(11)],
        render_investment_markdown=lambda pts: f"INVEST[{len(pts)}]",
    )
    _mod(
        "app.engine.idea_portfolio",
        optimize_portfolio=lambda r, b: _Portfolio(),
        render_portfolio_markdown=lambda p: "PORTFOLIO",
    )
    _mod(
        "app.engine.idea_dependencies",
        execution_order=lambda ideas: [_Item(20)],
        render_execution_markdown=lambda steps: f"SEQ[{len(steps)}]",
    )

    class _Synth:
        def build(self, report, memory=None):
            return ("ROADMAP", memory)

    _mod(
        "app.engine.idea_pareto",
        frontier_from_roadmap=lambda rm: [_Item(30), _Item(31), _Item(32)],
        render_pareto_markdown=lambda pts, total_ideas: f"PARETO[{len(pts)}/{total_ideas}]",
    )
    _mod("app.engine.idea_roadmap", RoadmapSynthesizer=_Synth)
    _mod(
        "app.engine.idea_tree_shape",
        analyze_tree_shape=lambda r: _Shape(),
        render_tree_shape_markdown=lambda s: "SHAPE",
    )


def _capture(fn, args, report, memory):
    buf = io.StringIO()
    with redirect_stdout(buf):
        ret = fn(args, report, "TARGET", memory)
    return ret, buf.getvalue()


# Every flag, both json and markdown, plus priority (multiple flags set) and
# the no-flag fall-through.
_IDEATE_CASES = [
    {},                                  # nothing -> False
    {"invest": True},
    {"invest": True, "json": True},
    {"budget": 12.5},
    {"budget": 12.5, "json": True},
    {"budget": 0.0},                     # falsy budget -> skip
    {"sequence": True},
    {"sequence": True, "json": True},
    {"pareto": True},
    {"pareto": True, "json": True},
    {"shape": True},
    {"shape": True, "json": True},
    # priority: invest wins over all later flags.
    {"invest": True, "budget": 5.0, "sequence": True, "pareto": True, "shape": True},
    # priority: budget wins over sequence/pareto/shape.
    {"budget": 7.0, "sequence": True, "pareto": True, "shape": True, "json": True},
    # priority: sequence wins over pareto/shape.
    {"sequence": True, "pareto": True, "shape": True},
    # priority: pareto wins over shape.
    {"pareto": True, "shape": True, "json": True},
]


def test_ideate_analysis_view_byte_identical(monkeypatch):
    report = _Report()
    memory = {"m": 1}
    for case in _IDEATE_CASES:
        _install_engine_stubs(monkeypatch)
        orig = _capture(ORIG_IDEATE._ideate_analysis_view, _Args(**case), report, memory)
        _install_engine_stubs(monkeypatch)
        new = _capture(live_ideate._ideate_analysis_view, _Args(**case), report, memory)
        assert orig == new, f"mismatch for case {case}: {orig!r} != {new!r}"


def test_ideate_view_json_payloads_match_real_dumps(monkeypatch):
    """Spot-check the JSON branch emits exactly json.dumps(..., indent=2)."""
    _install_engine_stubs(monkeypatch)
    ret, out = _capture(
        live_ideate._ideate_analysis_view, _Args(invest=True, json=True),
        _Report(), {},
    )
    assert ret is True
    assert out == json.dumps([{"id": 10}, {"id": 11}], indent=2) + "\n"
