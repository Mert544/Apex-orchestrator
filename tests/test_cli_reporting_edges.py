"""Additional edge/error-path coverage for app.cli_reporting.

Targets branches not exercised by the sibling suites: cmd_debug `analyze`
(file vs stdin, json vs text, root_cause present/absent), cmd_fractal markdown
and tree subcommands, _gate_metrics / _gate_compare_baseline / render_gate_baseline,
cmd_gate save-baseline + baseline composition, cmd_deps real-run + --strict, and
register_parsers wiring.

Deterministic, stdlib-only, no network, no wall-clock assertions. Heavy
builders are monkeypatched so the tests stay fast and reproducible.
"""

from __future__ import annotations

import argparse
import io
import json

import app.cli_reporting as cli_reporting


# --- cmd_debug analyze --------------------------------------------------

def test_cmd_debug_analyze_from_trace_file_text(monkeypatch, tmp_path, capsys):
    trace_file = tmp_path / "trace.txt"
    trace_file.write_text("Traceback ...\nValueError: boom\n", encoding="utf-8")

    class FakeLimb:
        def run(self, *, project_root, error_trace, target_file):
            assert "boom" in error_trace
            return {"root_cause": {"type": "ValueError"}, "suggestions": ["fix it"]}

    monkeypatch.setattr("app.agents.limbs.get_limb", lambda name: FakeLimb())
    args = argparse.Namespace(
        subcommand="analyze", target=str(tmp_path), trace=str(trace_file),
        file="", json=False,
    )
    assert cli_reporting.cmd_debug(args) == 0
    out = capsys.readouterr().out
    assert "Root cause: ValueError" in out
    assert "- fix it" in out


def test_cmd_debug_analyze_from_stdin_json(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("KeyError: 'x'\n"))

    class FakeLimb:
        def run(self, *, project_root, error_trace, target_file):
            return {"root_cause": {"type": "KeyError"}, "suggestions": []}

    monkeypatch.setattr("app.agents.limbs.get_limb", lambda name: FakeLimb())
    # trace == "-" forces the stdin branch; target empty exercises _get_project_root.
    args = argparse.Namespace(subcommand="analyze", target="", trace="-", file="", json=True)
    assert cli_reporting.cmd_debug(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["root_cause"]["type"] == "KeyError"


def test_cmd_debug_analyze_unidentified_root_cause(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("noise\n"))

    class FakeLimb:
        def run(self, *, project_root, error_trace, target_file):
            return {"root_cause": None, "suggestions": []}

    monkeypatch.setattr("app.agents.limbs.get_limb", lambda name: FakeLimb())
    args = argparse.Namespace(subcommand="analyze", target=str(tmp_path), trace="-", file="", json=False)
    assert cli_reporting.cmd_debug(args) == 0
    assert "Root cause: unidentified" in capsys.readouterr().out


# --- cmd_fractal: markdown (non-json) and tree --------------------------

def test_cmd_fractal_analyze_markdown_branch(monkeypatch, tmp_path, capsys):
    class FakeAgent:
        max_fractal_budget = 10

        def run(self, *, project_root, max_depth):
            return {"scanned_files": 2, "findings_count": 1, "fractal_analyzed": 1}

    monkeypatch.setattr("app.agents.fractal_agents.FractalSecurityAgent", FakeAgent)

    class FakeComposer:
        def __init__(self, results):
            self.results = results

        def to_markdown(self):
            return "## Fractal report"

    monkeypatch.setattr("app.reporting.composer.ReportComposer", FakeComposer)
    args = argparse.Namespace(
        subcommand="analyze", target=str(tmp_path), depth=2, json=False, max_fractal_budget=None
    )
    assert cli_reporting.cmd_fractal(args) == 0
    out = capsys.readouterr().out
    assert "Scanned 2 files" in out
    assert "## Fractal report" in out


def test_cmd_fractal_tree_branch(monkeypatch, tmp_path, capsys):
    class FakeEngine:
        def __init__(self, *, max_depth):
            self.max_depth = max_depth

        def analyze(self, finding):
            assert finding["issue"] == "eval()"
            return {"node": "root"}

        def summarize_tree(self, tree):
            return "why-1\nwhy-2"

    monkeypatch.setattr("app.engine.fractal_5whys.Fractal5WhysEngine", FakeEngine)
    args = argparse.Namespace(
        subcommand="tree", target=str(tmp_path), depth=3,
        finding='{"issue": "eval()", "file": "a.py"}',
    )
    assert cli_reporting.cmd_fractal(args) == 0
    out = capsys.readouterr().out
    assert "why-1" in out and "why-2" in out


# --- _gate_metrics: defensive degrade paths -----------------------------

def test_gate_metrics_score_none_when_grade_raises(monkeypatch, tmp_path):
    def boom(_root):
        raise RuntimeError("no grade")

    monkeypatch.setattr("app.engine.health_score.grade", boom)
    metrics = cli_reporting._gate_metrics(tmp_path)
    assert metrics["score"] is None
    assert metrics["letter"] == ""


def test_gate_metrics_counts_zero_when_profiler_raises(monkeypatch, tmp_path):
    class BoomProfiler:
        def __init__(self, root):
            pass

        def profile(self, light=False):
            raise RuntimeError("no profile")

    monkeypatch.setattr("app.tools.project_profile.ProjectProfiler", BoomProfiler)
    metrics = cli_reporting._gate_metrics(tmp_path)
    assert metrics["security_modules"] == 0
    assert metrics["bug_modules"] == 0
    assert metrics["out_of_scope_pct"] == 0.0


# --- _gate_compare_baseline + render_gate_baseline ----------------------

def _metrics(score, security=0, bugs=0, oos=0.0):
    return {
        "score": score,
        "letter": "",
        "security_modules": security,
        "bug_modules": bugs,
        "out_of_scope_pct": oos,
    }


def test_compare_baseline_all_same_no_regression():
    verdict = cli_reporting._gate_compare_baseline(_metrics(80), _metrics(80), tolerance=0)
    assert verdict["regressed"] is False
    assert verdict["regressions"] == 0
    statuses = {c["name"]: c["status"] for c in verdict["comparisons"]}
    assert statuses["score"] == "SAME"


def test_compare_baseline_score_drop_regresses():
    verdict = cli_reporting._gate_compare_baseline(_metrics(80), _metrics(70), tolerance=0)
    assert verdict["regressed"] is True
    score_cmp = next(c for c in verdict["comparisons"] if c["name"] == "score")
    assert score_cmp["status"] == "REGRESSED"


def test_compare_baseline_score_drop_within_tolerance_is_same():
    verdict = cli_reporting._gate_compare_baseline(_metrics(80), _metrics(78), tolerance=5)
    assert verdict["regressed"] is False
    score_cmp = next(c for c in verdict["comparisons"] if c["name"] == "score")
    assert score_cmp["status"] == "SAME"


def test_compare_baseline_score_improves():
    verdict = cli_reporting._gate_compare_baseline(_metrics(70), _metrics(85), tolerance=0)
    score_cmp = next(c for c in verdict["comparisons"] if c["name"] == "score")
    assert score_cmp["status"] == "IMPROVED"
    assert verdict["regressed"] is False


def test_compare_baseline_vanished_score_regresses():
    # baseline had a score, current grading failed (None) -> read as regression.
    verdict = cli_reporting._gate_compare_baseline(_metrics(80), _metrics(None), tolerance=0)
    score_cmp = next(c for c in verdict["comparisons"] if c["name"] == "score")
    assert score_cmp["status"] == "REGRESSED"
    assert "n/a" in score_cmp["detail"]


def test_compare_baseline_security_and_bug_increase_regress():
    verdict = cli_reporting._gate_compare_baseline(
        _metrics(80, security=0, bugs=0), _metrics(80, security=2, bugs=1), tolerance=0
    )
    by_name = {c["name"]: c for c in verdict["comparisons"]}
    assert by_name["security-modules"]["status"] == "REGRESSED"
    assert by_name["bug-modules"]["status"] == "REGRESSED"
    assert verdict["regressions"] == 2


def test_compare_baseline_out_of_scope_rise_beyond_epsilon_regresses():
    verdict = cli_reporting._gate_compare_baseline(
        _metrics(80, oos=1.0), _metrics(80, oos=5.0), tolerance=0
    )
    oos = next(c for c in verdict["comparisons"] if c["name"] == "out-of-scope")
    assert oos["status"] == "REGRESSED"


def test_compare_baseline_out_of_scope_noise_is_same():
    verdict = cli_reporting._gate_compare_baseline(
        _metrics(80, oos=1.0), _metrics(80, oos=1.02), tolerance=0
    )
    oos = next(c for c in verdict["comparisons"] if c["name"] == "out-of-scope")
    assert oos["status"] == "SAME"


def test_render_gate_baseline_passed_and_failed():
    passed = cli_reporting._gate_compare_baseline(_metrics(80), _metrics(80), tolerance=0)
    assert "GATE PASSED (no regressions)" in cli_reporting.render_gate_baseline(passed)
    failed = cli_reporting._gate_compare_baseline(_metrics(80), _metrics(60), tolerance=0)
    rendered = cli_reporting.render_gate_baseline(failed)
    assert "GATE FAILED" in rendered
    assert "[REGRESSED]" in rendered


# --- cmd_gate: save-baseline and baseline composition -------------------

def _gate_args(target, **over):
    base = dict(
        target=str(target), min_score=0, max_security=0, max_bugs=0,
        max_out_of_scope=-1, save_baseline=False, baseline=False, tolerance=0, json=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


def test_cmd_gate_save_baseline_writes_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli_reporting, "_gate_metrics",
        lambda root: _metrics(90, security=0, bugs=0, oos=0.0),
    )
    args = _gate_args(tmp_path, save_baseline=True)
    assert cli_reporting.cmd_gate(args) == 0
    baseline = tmp_path / ".apex" / "gate-baseline.json"
    assert baseline.is_file()
    assert "Saved gate baseline" in capsys.readouterr().out
    saved = json.loads(baseline.read_text())
    assert saved["score"] == 90


def test_cmd_gate_save_baseline_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli_reporting, "_gate_metrics", lambda root: _metrics(75))
    args = _gate_args(tmp_path, save_baseline=True, json=True)
    assert cli_reporting.cmd_gate(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["saved"] is True
    assert payload["metrics"]["score"] == 75


def test_cmd_gate_baseline_missing_returns_rc2(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli_reporting, "_gate_metrics", lambda root: _metrics(80))
    args = _gate_args(tmp_path, baseline=True)
    assert cli_reporting.cmd_gate(args) == 2
    assert "no baseline saved" in capsys.readouterr().out


def test_cmd_gate_baseline_missing_json_rc2(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli_reporting, "_gate_metrics", lambda root: _metrics(80))
    args = _gate_args(tmp_path, baseline=True, json=True)
    assert cli_reporting.cmd_gate(args) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["baseline_missing"] is True


def test_cmd_gate_baseline_regression_fails(monkeypatch, tmp_path, capsys):
    # Save a strong baseline, then present weaker metrics -> regression -> rc 1.
    monkeypatch.setattr(cli_reporting, "_gate_metrics", lambda root: _metrics(90))
    assert cli_reporting.cmd_gate(_gate_args(tmp_path, save_baseline=True)) == 0
    monkeypatch.setattr(cli_reporting, "_gate_metrics", lambda root: _metrics(70))
    args = _gate_args(tmp_path, baseline=True)
    assert cli_reporting.cmd_gate(args) == 1
    out = capsys.readouterr().out
    assert "Regression vs baseline" in out
    assert "GATE FAILED" in out


def test_cmd_gate_baseline_no_regression_passes_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli_reporting, "_gate_metrics", lambda root: _metrics(80))
    assert cli_reporting.cmd_gate(_gate_args(tmp_path, save_baseline=True)) == 0
    capsys.readouterr()  # discard the save-baseline message
    args = _gate_args(tmp_path, baseline=True, json=True)
    assert cli_reporting.cmd_gate(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["baseline"]["regressed"] is False


def test_cmd_gate_default_render_passes(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli_reporting, "_gate_metrics", lambda root: _metrics(80))
    assert cli_reporting.cmd_gate(_gate_args(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "# Apex gate" in out
    assert "GATE PASSED" in out


def test_cmd_gate_max_security_failure_returns_rc1(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cli_reporting, "_gate_metrics", lambda root: _metrics(80, security=3)
    )
    # default max_security == 0, so 3 modules fails the gate.
    assert cli_reporting.cmd_gate(_gate_args(tmp_path)) == 1


# --- cmd_deps: real run + json + strict ---------------------------------

def test_cmd_deps_real_run_markdown(monkeypatch, tmp_path, capsys):
    from app.engine.dependency_audit import DependencyFindings

    findings = DependencyFindings(
        declared=["requests"], imported_third_party=["requests"],
        unused=[], undeclared=[], unpinned=[],
    )
    monkeypatch.setattr(
        "app.engine.dependency_audit.audit_dependencies", lambda root: findings
    )
    monkeypatch.setattr(
        "app.engine.dependency_audit.render_dependency_audit_markdown",
        lambda f: "## Dependency audit",
    )
    args = argparse.Namespace(target=str(tmp_path), json=False, strict=False)
    assert cli_reporting.cmd_deps(args) == 0
    assert "## Dependency audit" in capsys.readouterr().out


def test_cmd_deps_json_shape(monkeypatch, tmp_path, capsys):
    from app.engine.dependency_audit import DependencyFindings

    findings = DependencyFindings(
        declared=["a"], imported_third_party=["b"],
        unused=["a"], undeclared=["b"], unpinned=["c"],
    )
    monkeypatch.setattr(
        "app.engine.dependency_audit.audit_dependencies", lambda root: findings
    )
    args = argparse.Namespace(target=str(tmp_path), json=True, strict=False)
    assert cli_reporting.cmd_deps(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["unused"] == ["a"]
    assert payload["undeclared"] == ["b"]
    assert payload["unpinned"] == ["c"]


def test_cmd_deps_strict_nonzero_on_findings(monkeypatch, tmp_path):
    from app.engine.dependency_audit import DependencyFindings

    findings = DependencyFindings(
        declared=[], imported_third_party=[], unused=["x"], undeclared=[], unpinned=[],
    )
    monkeypatch.setattr(
        "app.engine.dependency_audit.audit_dependencies", lambda root: findings
    )
    monkeypatch.setattr(
        "app.engine.dependency_audit.render_dependency_audit_markdown", lambda f: ""
    )
    args = argparse.Namespace(target=str(tmp_path), json=False, strict=True)
    assert cli_reporting.cmd_deps(args) == 1


def test_cmd_deps_strict_zero_when_clean(monkeypatch, tmp_path):
    from app.engine.dependency_audit import DependencyFindings

    findings = DependencyFindings(
        declared=[], imported_third_party=[], unused=[], undeclared=[], unpinned=[],
    )
    monkeypatch.setattr(
        "app.engine.dependency_audit.audit_dependencies", lambda root: findings
    )
    monkeypatch.setattr(
        "app.engine.dependency_audit.render_dependency_audit_markdown", lambda f: ""
    )
    args = argparse.Namespace(target=str(tmp_path), json=False, strict=True)
    assert cli_reporting.cmd_deps(args) == 0


# --- register_parsers wiring --------------------------------------------

def test_register_parsers_wires_all_subcommands():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    cli_reporting.register_parsers(subparsers)

    args = parser.parse_args(["dashboard", "--target", "/tmp/x"])
    assert args.func is cli_reporting.cmd_dashboard

    args = parser.parse_args(["hotspots", "--json"])
    assert args.func is cli_reporting.cmd_hotspots

    args = parser.parse_args(["deadcode", "--confirm", "--tests", "tests/unit"])
    assert args.func is cli_reporting.cmd_deadcode
    assert args.confirm is True
    assert args.tests == "tests/unit"

    args = parser.parse_args(["city", "--out", "/tmp/c.html"])
    assert args.func is cli_reporting.cmd_city

    args = parser.parse_args(["report", "--input", "i.json", "--output", "o.md"])
    assert args.func is cli_reporting.cmd_report
    assert args.format == "markdown"

    args = parser.parse_args(["fractal", "analyze", "--depth", "3"])
    assert args.func is cli_reporting.cmd_fractal
    assert args.subcommand == "analyze"

    args = parser.parse_args(["fractal", "tree", "--finding", "{}"])
    assert args.subcommand == "tree"

    args = parser.parse_args(["debug", "trace"])
    assert args.func is cli_reporting.cmd_debug

    args = parser.parse_args(["debug", "analyze", "--trace", "-"])
    assert args.subcommand == "analyze"

    args = parser.parse_args(["pulse", "--json"])
    assert args.func is cli_reporting.cmd_pulse

    args = parser.parse_args(["gate", "--min-score", "70", "--baseline"])
    assert args.func is cli_reporting.cmd_gate
    assert args.min_score == 70
    assert args.baseline is True

    args = parser.parse_args(["deps", "--strict"])
    assert args.func is cli_reporting.cmd_deps
    assert args.strict is True
