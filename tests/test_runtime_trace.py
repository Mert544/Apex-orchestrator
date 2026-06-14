from __future__ import annotations

import os
from pathlib import Path

from app.engine.runtime_trace import (
    ConfirmedFinding,
    RuntimeEvidence,
    StaticFinding,
    confirm_findings,
    trace_callable,
)
from app.reporting.deadcode import find_dead_code

_SAMPLE = (
    "def used():\n"            # line 1
    "    return 41 + 1\n"      # line 2
    "\n"                       # line 3
    "def never_called():\n"    # line 4
    "    return 'dead'\n"      # line 5
)


def _write_sample(tmp: Path) -> Path:
    f = tmp / "sample.py"
    f.write_text(_SAMPLE, encoding="utf-8")
    return f


def _load(path: Path):
    # ``__file__`` must be present in the module globals: stdlib ``trace`` reads
    # ``frame.f_globals['__file__']`` to decide whether to follow a call, so an
    # exec'd namespace without it is invisible to the tracer (real modules always
    # carry ``__file__``).
    ns: dict = {"__file__": str(path)}
    code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
    exec(code, ns)
    return ns


def test_executed_lines_are_captured(tmp_path: Path):
    f = _write_sample(tmp_path)
    ns = _load(f)
    ev = trace_callable(lambda: ns["used"]())
    lines = ev.executed_lines(str(f))
    assert 2 in lines                       # body of used() ran
    assert 5 not in lines                   # never_called body never ran
    assert ev.was_executed(str(f), 2)
    assert not ev.was_executed(str(f), 5)


def test_uncalled_function_is_runtime_confirmed(tmp_path: Path):
    # The file *has* evidence (line 2 ran) but ``never_called``'s def line (4)
    # was never executed across the trace -> the static finding is strengthened.
    f = _write_sample(tmp_path)
    ns = _load(f)
    ev = trace_callable(lambda: ns["used"]())
    finding = StaticFinding(path=str(f), lineno=4, symbol="never_called")
    [res] = confirm_findings([finding], ev)
    assert res.confidence == "runtime-confirmed"


def test_called_function_is_refuted(tmp_path: Path):
    # Model a real test run: the module is imported *under trace*, so the
    # ``def`` lines (where the function objects are created) execute at import
    # time and any *called* function's body executes too.
    f = _write_sample(tmp_path)

    def exercise():
        ns = _load(f)
        ns["used"]()

    ev = trace_callable(exercise)
    # ``used``'s def line (1) ran at import AND its body (2) ran on call.
    finding = StaticFinding(path=str(f), lineno=1, symbol="used")
    [res] = confirm_findings([finding], ev)
    assert res.confidence == "refuted"


def test_file_with_no_evidence_is_static_only(tmp_path: Path):
    f = _write_sample(tmp_path)
    ns = _load(f)
    ev = trace_callable(lambda: ns["used"]())
    other = tmp_path / "untouched.py"
    other.write_text("def x():\n    return 1\n", encoding="utf-8")
    finding = StaticFinding(path=str(other), lineno=1, symbol="x")
    [res] = confirm_findings([finding], ev)
    assert res.confidence == "static-only"
    assert not ev.has_evidence_for(str(other))


def test_iterable_of_callables(tmp_path: Path):
    f = _write_sample(tmp_path)
    ns = _load(f)
    # Exercise both functions across two "tests".
    ev = trace_callable([lambda: ns["used"](), lambda: ns["never_called"]()])
    assert ev.was_executed(str(f), 2)
    assert ev.was_executed(str(f), 5)       # now refutable


def test_confirm_findings_deterministic_ordering():
    ev = RuntimeEvidence(executed=frozenset())
    findings = [
        StaticFinding(path="z.py", lineno=10, symbol="a"),
        StaticFinding(path="a.py", lineno=5, symbol="b"),
        StaticFinding(path="a.py", lineno=1, symbol="b"),
        StaticFinding(path="a.py", lineno=1, symbol="a"),
    ]
    out = confirm_findings(findings, ev)
    keys = [(c.path, c.lineno, c.symbol) for c in out]
    assert keys == sorted(keys)
    # All static-only since evidence is empty.
    assert {c.confidence for c in out} == {"static-only"}
    assert all(isinstance(c, ConfirmedFinding) for c in out)


def test_paths_normalised_to_absolute_real(tmp_path: Path):
    f = _write_sample(tmp_path)
    ns = _load(f)
    ev = trace_callable(lambda: ns["used"]())
    # A relative-ish / messy path with .. still matches the absolute trace key.
    messy = os.path.join(str(tmp_path), "sub", "..", "sample.py")
    assert ev.was_executed(messy, 2)


# --- deadcode integration -------------------------------------------------


def _proj(tmp: Path) -> Path:
    (tmp / "pkg").mkdir()
    (tmp / "pkg" / "__init__.py").write_text("")
    (tmp / "pkg" / "dead.py").write_text("def ghost():\n    return 2\n")
    (tmp / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    return tmp


def test_deadcode_output_unchanged_without_evidence(tmp_path: Path):
    root = _proj(tmp_path)
    rows = find_dead_code(str(root))
    assert any(r["symbol"] == "ghost" for r in rows)
    # No runtime key is added when evidence is absent.
    assert all("runtime" not in r for r in rows)


def test_deadcode_default_matches_explicit_none(tmp_path: Path):
    root = _proj(tmp_path)
    assert find_dead_code(str(root)) == find_dead_code(str(root), evidence=None)


def test_deadcode_annotates_runtime_confirmed(tmp_path: Path):
    root = _proj(tmp_path)
    # Empty evidence covering nothing -> file has no evidence -> static-only.
    rows = find_dead_code(str(root), evidence=RuntimeEvidence(executed=frozenset()))
    ghost = next(r for r in rows if r["symbol"] == "ghost")
    assert ghost["runtime"] == "static-only"


def test_deadcode_refuted_when_def_line_runs(tmp_path: Path):
    root = _proj(tmp_path)
    rows_no = find_dead_code(str(root))
    ghost = next(r for r in rows_no if r["symbol"] == "ghost")
    abs_path = str(root / ghost["module"])
    ev = RuntimeEvidence(executed=frozenset({(os.path.realpath(abs_path), ghost["line"])}))
    rows = find_dead_code(str(root), evidence=ev)
    ghost2 = next(r for r in rows if r["symbol"] == "ghost")
    assert ghost2["runtime"] == "refuted"


def test_deadcode_runtime_confirmed_when_file_loaded_but_def_not(tmp_path: Path):
    root = _proj(tmp_path)
    rows_no = find_dead_code(str(root))
    ghost = next(r for r in rows_no if r["symbol"] == "ghost")
    abs_path = os.path.realpath(str(root / ghost["module"]))
    # Some OTHER line of the file ran, but not the def line.
    ev = RuntimeEvidence(executed=frozenset({(abs_path, ghost["line"] + 1)}))
    rows = find_dead_code(str(root), evidence=ev)
    ghost2 = next(r for r in rows if r["symbol"] == "ghost")
    assert ghost2["runtime"] == "runtime-confirmed"
