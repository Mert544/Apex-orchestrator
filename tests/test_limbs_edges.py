"""Edge / error-path tests for app.agents.limbs.

Targets the branches the smoke tests in test_limbs.py don't reach: the full
debug fix-suggestion flow, traceback root-cause classification, exec() / parse
scanning, the coverage no-pytest and JSON-parsing paths, refactor parse
failures, dependency/doc exception swallowing, and the performance analyzers.
External tools (pytest/pip/ruff/python -c) are stubbed via monkeypatch so the
tests stay deterministic and offline.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

from app.agents.limbs import (
    CILimb,
    CoverageLimb,
    DebugLimb,
    DependencyLimb,
    DocLimb,
    Limb,
    PerformanceLimb,
    RefactorLimb,
    get_limb,
    list_limbs,
)


# --- Limb base NotImplementedError -------------------------------------------

def test_base_limb_execute_raises_not_implemented():
    import pytest

    with pytest.raises(NotImplementedError):
        Limb(name="x", role="y")._execute()


# --- DebugLimb: full fix-suggestion flow -------------------------------------

def test_debug_limb_import_error_yields_fix_and_suggestion():
    """An ImportError trace classifies a root cause and produces a fix
    (lines 68-84, 112-113, 126-130)."""
    limb = DebugLimb()
    result = limb.run(error_trace="Traceback...\nModuleNotFoundError: no module named x")
    assert result["root_cause"]["type"] == "ImportError"
    assert result["fixes"]
    assert any("Install missing module" in s for s in result["suggestions"])


def test_debug_limb_nameerror_suggests_definition():
    limb = DebugLimb()
    result = limb.run(error_trace="NameError: name 'foo' is not defined")
    assert result["root_cause"]["type"] == "NameError"
    assert any("Define undefined" in s for s in result["suggestions"])


def test_debug_limb_attributeerror_fix():
    limb = DebugLimb()
    result = limb.run(error_trace="AttributeError: 'X' object has no attribute 'y'")
    assert result["root_cause"]["type"] == "AttributeError"
    assert result["fixes"][0]["action"].startswith("add null check")


def test_debug_limb_typeerror_fix():
    limb = DebugLimb()
    result = limb.run(error_trace="TypeError: bad operand")
    assert result["root_cause"]["type"] == "TypeError"
    assert result["fixes"]


def test_debug_limb_valueerror_no_fix_suggested():
    """ValueError is classified but _suggest_fix returns None (line 147 fall-through)."""
    limb = DebugLimb()
    result = limb.run(error_trace="ValueError: invalid literal")
    assert result["root_cause"]["type"] == "ValueError"
    # No fix mapping for ValueError -> fixes stays empty.
    assert result["fixes"] == []


def test_debug_limb_unrecognized_trace_reports_no_root_cause():
    limb = DebugLimb()
    result = limb.run(error_trace="something totally unrelated and benign")
    assert result["root_cause"] is None
    assert any("Could not identify" in s for s in result["suggestions"])


def test_debug_limb_traceback_file_match(tmp_path):
    """A 'File "...", line N' line inside the project dir is parsed (lines 99-106)."""
    proj = tmp_path / "myproj"
    proj.mkdir()
    limb = DebugLimb()
    trace = f'File "{proj}/myproj/mod.py", line 42, in f\n    boom()'
    cause = limb._analyze_traceback(trace, proj)
    assert cause["type"] == "error_in_file"
    assert cause["line"] == 42


def test_debug_limb_scans_target_file_for_exec(tmp_path):
    """_scan_file_for_common_issues flags exec() (line 160 region)."""
    (tmp_path / "danger.py").write_text("def g():\n    exec('x=1')\n", encoding="utf-8")
    limb = DebugLimb()
    result = limb.run(project_root=str(tmp_path), target_file="danger.py")
    assert any("exec" in a for a in result["analysis"])


def test_debug_limb_scan_unparseable_file_reports_error(tmp_path):
    """A syntactically broken target file is caught (lines 162-163)."""
    (tmp_path / "broken.py").write_text("def (: bad\n", encoding="utf-8")
    limb = DebugLimb()
    result = limb.run(project_root=str(tmp_path), target_file="broken.py")
    assert any("Could not parse file" in a for a in result["analysis"])


# --- CoverageLimb: no-pytest and JSON parsing paths --------------------------

def test_coverage_limb_no_pytest(monkeypatch):
    """When pytest is unavailable, recommend installing it and stop (197-200)."""
    limb = CoverageLimb()
    monkeypatch.setattr(limb, "_check_pytest", lambda: False)
    result = limb.run(project_root=".")
    assert any("pytest not found" in r for r in result["recommendations"])
    assert result["current_coverage"] == 0.0


def test_coverage_limb_parses_coverage_json(monkeypatch, tmp_path):
    """_run_coverage reads coverage.json and classifies low-coverage files and
    uncovered functions (lines 245-262)."""
    cov = {
        "totals": {"percent_covered": 55.0},
        "files": {
            "app/low.py": {
                "summary": {"percent_covered": 40.0},
                "functions": {"dead": {"count": 0}, "live": {"count": 3}},
            },
            "app/high.py": {
                "summary": {"percent_covered": 95.0},
                "functions": {},
            },
        },
    }
    (tmp_path / "coverage.json").write_text(json.dumps(cov), encoding="utf-8")
    monkeypatch.setattr(
        "app.agents.limbs.subprocess.run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    limb = CoverageLimb()
    out = limb._run_coverage(tmp_path)
    assert out["total"] == 55.0
    assert "app/low.py" in out["low_coverage_files"]
    assert "app/high.py" not in out["low_coverage_files"]
    assert "app/low.py::dead" in out["uncovered_functions"]
    assert "app/low.py::live" not in out["uncovered_functions"]


def test_coverage_limb_run_coverage_fallback_on_missing_json(monkeypatch, tmp_path):
    """No coverage.json -> the static fallback dict is returned (lines 267-271)."""
    monkeypatch.setattr(
        "app.agents.limbs.subprocess.run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    out = CoverageLimb()._run_coverage(tmp_path)
    assert out["total"] == 75.0


def test_coverage_limb_meets_target(monkeypatch):
    limb = CoverageLimb()
    monkeypatch.setattr(limb, "_check_pytest", lambda: True)
    monkeypatch.setattr(
        limb, "_run_coverage", lambda p: {"total": 90.0, "low_coverage_files": [], "uncovered_functions": []}
    )
    result = limb.run(project_root=".", min_coverage=80.0)
    assert any("meets target" in r for r in result["recommendations"])


def test_coverage_limb_below_target_lists_files(monkeypatch):
    limb = CoverageLimb()
    monkeypatch.setattr(limb, "_check_pytest", lambda: True)
    monkeypatch.setattr(
        limb,
        "_run_coverage",
        lambda p: {"total": 50.0, "low_coverage_files": ["a.py", "b.py"], "uncovered_functions": []},
    )
    result = limb.run(project_root=".", min_coverage=80.0)
    assert any("below target" in r for r in result["recommendations"])
    assert any("Add tests for a.py" in r for r in result["recommendations"])


def test_check_pytest_handles_subprocess_failure(monkeypatch):
    def boom(*a, **k):
        raise OSError("no python")

    monkeypatch.setattr("app.agents.limbs.subprocess.run", boom)
    assert CoverageLimb()._check_pytest() is False


# --- RefactorLimb: parse-failure path ----------------------------------------

def test_refactor_limb_skips_unparseable_file(tmp_path):
    """A syntax-error file is silently skipped (lines 319-320)."""
    (tmp_path / "good.py").write_text(
        "def undocumented():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "bad.py").write_text("def (: nope\n", encoding="utf-8")
    result = RefactorLimb().run(project_root=str(tmp_path))
    # The good file still produces a 'Missing docstring' finding; bad file ignored.
    assert any("undocumented" in i for i in result["issues_found"])


def test_refactor_limb_target_pattern_filters(tmp_path):
    (tmp_path / "m.py").write_text(
        "def alpha():\n    return 1\n\ndef beta():\n    return 2\n", encoding="utf-8"
    )
    result = RefactorLimb().run(project_root=str(tmp_path), target_pattern="alpha")
    assert result["issues_found"]
    assert all("alpha" in i.lower() for i in result["issues_found"])


# --- DependencyLimb: exception swallowing ------------------------------------

def test_dependency_check_outdated_swallows_errors(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("pip missing")

    monkeypatch.setattr("app.agents.limbs.subprocess.run", boom)
    assert DependencyLimb()._check_outdated(tmp_path) == {"outdated": [], "updates": []}


def test_dependency_check_security_swallows_errors(monkeypatch, tmp_path):
    """pip audit raising is caught and returns [] (lines 416-417)."""
    def boom(*a, **k):
        raise OSError("no audit")

    monkeypatch.setattr("app.agents.limbs.subprocess.run", boom)
    assert DependencyLimb()._check_security_issues(tmp_path) == []


def test_dependency_check_security_parses_vulnerabilities(monkeypatch, tmp_path):
    """A successful pip-audit JSON with vulnerabilities is parsed (lines 415-417)."""
    data = {"vulnerabilities": [{"name": "cve-a"}, {"name": "cve-b"}]}
    monkeypatch.setattr(
        "app.agents.limbs.subprocess.run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr=""),
    )
    out = DependencyLimb()._check_security_issues(tmp_path)
    assert out == ["cve-a", "cve-b"]


def test_dependency_check_outdated_parses_json(monkeypatch, tmp_path):
    pkgs = [{"name": "requests", "latest_version": "9.9.9"}]
    monkeypatch.setattr(
        "app.agents.limbs.subprocess.run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=json.dumps(pkgs), stderr=""),
    )
    out = DependencyLimb()._check_outdated(tmp_path)
    assert out["outdated"] == ["requests"]
    assert out["updates"] == ["requests>=9.9.9"]


def test_dependency_limb_records_requirements_file(tmp_path):
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    limb = DependencyLimb()
    result = limb.run(project_root=str(tmp_path), check_outdated=False)
    assert result["requirements_file"] == "requirements.txt"


# --- DocLimb: parse-failure path ---------------------------------------------

def test_doc_limb_skips_unparseable_file(tmp_path):
    """A broken module is swallowed (lines 468-469) and not counted."""
    (tmp_path / "ok.py").write_text('"""doc."""\n', encoding="utf-8")
    (tmp_path / "broken.py").write_text("def (: bad\n", encoding="utf-8")
    result = DocLimb().run(project_root=str(tmp_path), target="all")
    # broken.py has no module docstring but cannot be parsed -> not in missing_docs.
    assert not any("broken.py" in m for m in result["missing_docs"])


# --- CILimb: subprocess exception handling -----------------------------------

def test_ci_limb_lint_falls_back_when_no_linters(monkeypatch):
    """All linter subprocess calls raising -> the default 'lint' stage (568-571)."""
    def boom(*a, **k):
        raise FileNotFoundError("no ruff")

    monkeypatch.setattr("app.agents.limbs.subprocess.run", boom)
    stages = CILimb()._run_lint(Path("."))
    assert stages == [{"name": "lint", "passed": True, "output": "No linters configured"}]


def test_ci_limb_tests_exception_marks_failed(monkeypatch):
    def boom(*a, **k):
        raise OSError("no pytest")

    monkeypatch.setattr("app.agents.limbs.subprocess.run", boom)
    stages = CILimb()._run_tests(Path("."))
    assert stages[0]["name"] == "test"
    assert stages[0]["passed"] is False


def test_ci_limb_summary_reports_pass(monkeypatch):
    limb = CILimb()
    monkeypatch.setattr(
        limb, "_run_lint", lambda p: [{"name": "lint", "passed": True, "output": ""}]
    )
    monkeypatch.setattr(
        limb, "_run_tests", lambda p: [{"name": "test", "passed": True, "output": ""}]
    )
    result = limb.run(project_root=".")
    assert result["passed"] is True
    assert "PASSED" in result["summary"]
    assert result["failed_checks"] == []


def test_ci_limb_summary_reports_failure(monkeypatch):
    limb = CILimb()
    monkeypatch.setattr(
        limb, "_run_lint", lambda p: [{"name": "lint-ruff", "passed": False, "output": "x"}]
    )
    monkeypatch.setattr(
        limb, "_run_tests", lambda p: [{"name": "test", "passed": True, "output": ""}]
    )
    result = limb.run(project_root=".")
    assert result["passed"] is False
    assert "lint-ruff" in result["failed_checks"]
    assert "FAILED" in result["summary"]


# --- PerformanceLimb: metrics, analyzers, bottlenecks ------------------------

def test_performance_limb_measure_import_time_handles_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("no python")

    monkeypatch.setattr("app.agents.limbs.subprocess.run", boom)
    assert PerformanceLimb()._measure_import_time(Path(".")) == 0.0


def test_performance_analyze_metrics_acceptable_default():
    rec = PerformanceLimb()._analyze_metrics({"total_lines": 10, "import_time": 0.1})
    assert rec == ["Performance looks acceptable"]


def test_performance_analyze_metrics_flags_large_and_slow():
    rec = PerformanceLimb()._analyze_metrics({"total_lines": 20000, "import_time": 2.0})
    assert any("splitting large modules" in r for r in rec)
    assert any("High import time" in r for r in rec)


def test_performance_find_bottlenecks():
    bn = PerformanceLimb()._find_bottlenecks({"total_lines": 60000, "import_time": 3.0})
    assert "Slow module imports" in bn
    assert "Large codebase may benefit from lazy loading" in bn


def test_performance_find_bottlenecks_empty_for_small():
    assert PerformanceLimb()._find_bottlenecks({"total_lines": 1, "import_time": 0.0}) == []


def test_performance_collect_metrics_counts_lines(monkeypatch, tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (tmp_path / "test_skip.py").write_text("z = 3\n", encoding="utf-8")
    limb = PerformanceLimb()
    monkeypatch.setattr(limb, "_measure_import_time", lambda p: 0.0)
    metrics = limb._collect_metrics(tmp_path)
    assert metrics["total_lines"] == 2  # test file excluded
    assert metrics["file_count"] == 1


def test_performance_collect_metrics_swallows_read_error(monkeypatch, tmp_path):
    """A file with invalid UTF-8 raises on read_text and is skipped (lines 644-645)."""
    good = tmp_path / "good.py"
    good.write_text("a = 1\n", encoding="utf-8")
    bad = tmp_path / "bad.py"
    bad.write_bytes(b"\xff\xfe invalid utf8 \x80\n")
    limb = PerformanceLimb()
    monkeypatch.setattr(limb, "_measure_import_time", lambda p: 0.0)
    metrics = limb._collect_metrics(tmp_path)
    # good.py counted (1 line); bad.py skipped without crashing.
    assert metrics["total_lines"] == 1


def test_performance_limb_full_run(monkeypatch, tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    limb = PerformanceLimb()
    monkeypatch.setattr(limb, "_measure_import_time", lambda p: 0.0)
    result = limb.run(project_root=str(tmp_path))
    assert result["limb"] == "performance"
    assert "metrics" in result
    assert result["recommendations"]


# --- factory ------------------------------------------------------------------

def test_get_limb_performance():
    assert isinstance(get_limb("performance"), PerformanceLimb)


def test_get_limb_unknown_message_lists_available():
    import pytest

    with pytest.raises(ValueError) as exc:
        get_limb("zzz")
    assert "Available" in str(exc.value)


def test_list_limbs_complete():
    assert set(list_limbs()) == {
        "debug", "coverage", "refactor", "dependency", "doc", "ci", "performance"
    }
