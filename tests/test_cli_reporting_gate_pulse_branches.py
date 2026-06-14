"""Branch/defensive coverage for the gate + pulse paths of app.cli_reporting.

Complements ``test_cli_gate.py`` / ``test_cli_pulse.py`` (the happy-path CLI
suites) by exercising the remaining defensive and render branches the snapshot /
verdict helpers leave uncovered:

  * every ``_pulse_*`` section's degrade-on-exception path (grade, scope, the
    polyglot-scan-only failure, moves, track record);
  * the ``_pulse_moves`` anchor->focus construction (symbol + metric + line, and
    symbol-only) and the no-anchor branch;
  * ``render_pulse``'s score-None header, the empty-out-of-scope-files branch,
    and the no-moves line;
  * ``_gate_evaluate``'s skip branches (max-security / max-bugs disabled via
    ``None``), and ``render_gate``'s no-checks read-out line.

All inputs are explicit (hand-built ``argparse.Namespace`` + tiny fake report
objects); no git, no time, no random, no order assertions.
"""

from __future__ import annotations

import argparse

import app.cli_reporting as cr


# --- _pulse_grade: degrade on engine failure (229-230) ----------------------

def test_pulse_grade_degrades_on_exception(monkeypatch):
    import app.engine.health_score as hs

    def _boom(_root):
        raise RuntimeError("grade boom")

    monkeypatch.setattr(hs, "grade", _boom)
    out = cr._pulse_grade(__import__("pathlib").Path("."))
    assert out == {"letter": "", "score": None, "scope_line": ""}


# --- _pulse_scope: profiler failure -> all-Python shape (243-244) -----------

def test_pulse_scope_degrades_when_profiler_raises(monkeypatch):
    import app.tools.project_profile as pp

    class _Boom:
        def __init__(self, root):
            pass

        def profile(self, *, light=False):
            raise RuntimeError("profile boom")

    monkeypatch.setattr(pp, "ProjectProfiler", _Boom)
    out = cr._pulse_scope(__import__("pathlib").Path("."))
    assert out == {"all_python": True, "analyzed_pct": 100, "out_of_scope_pct": 0, "files": []}


def test_pulse_scope_none_profile_is_all_python(monkeypatch):
    """A None profile (or zero source files) collapses to the all-Python shape."""
    import app.tools.project_profile as pp

    class _NoneProfiler:
        def __init__(self, root):
            pass

        def profile(self, *, light=False):
            return None

    monkeypatch.setattr(pp, "ProjectProfiler", _NoneProfiler)
    out = cr._pulse_scope(__import__("pathlib").Path("."))
    assert out["all_python"] is True


class _Profile:
    def __init__(self, *, source_file_count=10, out_of_scope_ratio=0.0,
                 language_breakdown=None, analyzed_ratio=1.0):
        self.source_file_count = source_file_count
        self.out_of_scope_ratio = out_of_scope_ratio
        self.language_breakdown = language_breakdown or {}
        self.analyzed_ratio = analyzed_ratio


def test_pulse_scope_polyglot_scan_failure_yields_no_files(monkeypatch):
    """When the profile says out-of-scope but scan_polyglot_facts raises, the
    section still returns (files == []) rather than crashing (256-257)."""
    import app.tools.polyglot_facts as pf
    import app.tools.project_profile as pp

    class _Profiler:
        def __init__(self, root):
            pass

        def profile(self, *, light=False):
            return _Profile(out_of_scope_ratio=0.4,
                            language_breakdown={"JavaScript": 5}, analyzed_ratio=0.6)

    def _scan_boom(*args, **kwargs):
        raise RuntimeError("scan boom")

    monkeypatch.setattr(pp, "ProjectProfiler", _Profiler)
    monkeypatch.setattr(pf, "scan_polyglot_facts", _scan_boom)
    out = cr._pulse_scope(__import__("pathlib").Path("."))
    assert out["all_python"] is False
    assert out["files"] == []
    assert out["out_of_scope_pct"] == 40
    assert out["analyzed_pct"] == 60


# --- _pulse_moves: engine failure + anchor->focus shapes (286-303) ----------

def test_pulse_moves_degrades_on_exception(monkeypatch):
    import app.engine.idea_permutation as ip

    class _Boom:
        def __init__(self, *a, **k):
            pass

        def run(self):
            raise RuntimeError("engine boom")

    monkeypatch.setattr(ip, "IdeaPermutationEngine", _Boom)
    assert cr._pulse_moves(__import__("pathlib").Path(".")) == []


class _Idea:
    def __init__(self, title, branch_path, value, anchors=None):
        self.title = title
        self.branch_path = branch_path
        self.value = value
        self.anchors = anchors or []


class _Report:
    def __init__(self, ideas):
        self.ideas = ideas


def _patch_engine(monkeypatch, ideas):
    import app.engine.idea_permutation as ip

    class _Fake:
        def __init__(self, *a, **k):
            pass

        def run(self):
            return _Report(ideas)

    monkeypatch.setattr(ip, "IdeaPermutationEngine", _Fake)


def test_pulse_moves_focus_with_symbol_metric_and_line(monkeypatch):
    """An anchor with symbol + metric + line builds 'symbol (metric, line N)'."""
    idea = _Idea("Refactor hub", "x.t0", 0.9123456,
                 anchors=[{"symbol": "app.core.compute", "metric": "complexity 12", "line": 5}])
    _patch_engine(monkeypatch, [idea])
    moves = cr._pulse_moves(__import__("pathlib").Path("."))
    assert len(moves) == 1
    m = moves[0]
    assert m["title"] == "Refactor hub"
    assert m["value"] == round(0.9123456, 4)
    # symbol is the last dotted segment; detail joins metric + 'line N'.
    assert m["focus"] == "compute (complexity 12, line 5)"


def test_pulse_moves_focus_symbol_only(monkeypatch):
    """No metric, no line -> focus is just the bare symbol (no parenthetical)."""
    idea = _Idea("Tidy", "x.t1", 0.5,
                 anchors=[{"symbol": "mod.thing", "metric": "", "line": None}])
    _patch_engine(monkeypatch, [idea])
    moves = cr._pulse_moves(__import__("pathlib").Path("."))
    assert moves[0]["focus"] == "thing"


def test_pulse_moves_no_anchor_has_empty_focus(monkeypatch):
    idea = _Idea("No anchor", "x.t2", 0.4, anchors=[])
    _patch_engine(monkeypatch, [idea])
    moves = cr._pulse_moves(__import__("pathlib").Path("."))
    assert moves[0]["focus"] == ""


def test_pulse_moves_anchor_blank_symbol_has_empty_focus(monkeypatch):
    """An anchor whose symbol resolves to empty leaves focus empty."""
    idea = _Idea("Blank", "x.t3", 0.3, anchors=[{"symbol": "", "metric": "m", "line": 9}])
    _patch_engine(monkeypatch, [idea])
    moves = cr._pulse_moves(__import__("pathlib").Path("."))
    assert moves[0]["focus"] == ""


# --- _pulse_trackrecord: degrade on exception (321-322) ---------------------

def test_pulse_trackrecord_degrades_on_exception(monkeypatch):
    import app.engine.idea_memory as im

    def _boom(_root):
        raise RuntimeError("memory boom")

    monkeypatch.setattr(im.IdeaMemory, "load", staticmethod(_boom))
    out = cr._pulse_trackrecord(__import__("pathlib").Path("."))
    assert out == {"by_type": [], "has_record": False}


# --- render_pulse: score-None header + empty files + no moves ----------------

def _snap(*, score=80, letter="B", all_python=True, files=None, moves=None,
          out_pct=0, analysed=100, by_type=None):
    return {
        "project_root": ".",
        "grade": {"letter": letter, "score": score, "scope_line": ""},
        "scope": {"all_python": all_python, "analyzed_pct": analysed,
                  "out_of_scope_pct": out_pct, "files": files or []},
        "moves": moves or [],
        "trackrecord": {"by_type": by_type or [], "has_record": bool(by_type)},
    }


def test_render_pulse_score_none_header():
    """A None score (grading failed) renders the bare 'Grade: **letter**' header
    with no /100 suffix."""
    out = cr.render_pulse(_snap(score=None, letter=""))
    assert "Grade: **—**" in out
    assert "/100" not in out


def test_render_pulse_polyglot_without_named_files():
    """all_python False but no biggest-file list -> scope line has no '— biggest
    outside:' suffix (the files-empty branch, 390->393)."""
    out = cr.render_pulse(_snap(all_python=False, out_pct=30, analysed=70, files=[]))
    assert "30% out of scope" in out
    assert "biggest outside" not in out


def test_render_pulse_no_moves_line():
    out = cr.render_pulse(_snap(moves=[]))
    assert "- (no ideas generated for this target)" in out


def test_render_pulse_named_out_of_scope_file():
    out = cr.render_pulse(_snap(all_python=False, out_pct=30, analysed=70,
                                files=[{"path": "web/app.js", "language": "JavaScript", "loc": 120}]))
    assert "biggest outside: `web/app.js` (120 LOC)" in out


# --- _gate_evaluate: disabled checks via None (522->535, 535->548) -----------

def _gate_ns(**kw):
    base = dict(min_score=0, max_security=0, max_bugs=0, max_out_of_scope=-1)
    base.update(kw)
    return argparse.Namespace(**base)


_METRICS = {"score": 90, "letter": "A", "security_modules": 0,
            "bug_modules": 0, "out_of_scope_pct": 0.0}


def test_gate_evaluate_max_security_none_skips_check():
    verdict = cr._gate_evaluate(_METRICS, _gate_ns(max_security=None))
    names = {c["name"] for c in verdict["checks"]}
    assert "max-security" not in names
    # max-bugs (default 0) still present.
    assert "max-bugs" in names


def test_gate_evaluate_max_bugs_none_skips_check():
    verdict = cr._gate_evaluate(_METRICS, _gate_ns(max_bugs=None))
    names = {c["name"] for c in verdict["checks"]}
    assert "max-bugs" not in names
    assert "max-security" in names


def test_gate_evaluate_all_disabled_passes_with_no_checks():
    """min-score 0, security/bugs None, out-of-scope -1 -> empty check set, which
    passes (a pure metrics read-out)."""
    verdict = cr._gate_evaluate(
        _METRICS, _gate_ns(min_score=0, max_security=None, max_bugs=None, max_out_of_scope=-1))
    assert verdict["checks"] == []
    assert verdict["passed"] is True


def test_gate_evaluate_min_score_none_input_treated_as_off():
    """A None min_score coalesces to the OFF sentinel (0), so no min-score check."""
    verdict = cr._gate_evaluate(_METRICS, _gate_ns(min_score=None))
    names = {c["name"] for c in verdict["checks"]}
    assert "min-score" not in names


def test_gate_evaluate_min_score_with_none_metric_fails_honestly():
    """When grading failed (score None) but a min-score is requested, the check
    fails with actual 'n/a' rather than crashing."""
    metrics = {**_METRICS, "score": None}
    verdict = cr._gate_evaluate(metrics, _gate_ns(min_score=50))
    check = next(c for c in verdict["checks"] if c["name"] == "min-score")
    assert check["passed"] is False
    assert check["actual"] == "n/a"
    assert verdict["passed"] is False


# --- render_gate: no-checks read-out line (581) ------------------------------

def test_render_gate_no_checks_readout_line():
    verdict = {"passed": True, "checks": [], "metrics": _METRICS}
    out = cr.render_gate(verdict)
    assert "(no checks enabled — metrics read-out only)" in out
    assert "GATE PASSED" in out


def test_render_gate_none_score_renders_na():
    metrics = {**_METRICS, "score": None, "letter": ""}
    verdict = {"passed": True, "checks": [], "metrics": metrics}
    out = cr.render_gate(verdict)
    assert "Grade: — (n/a)" in out
