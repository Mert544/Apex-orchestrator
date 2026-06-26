"""Residual "display-list-as-count" honesty bugs (red-team follow-up to the
``untested_count`` fix).

Three quantitative signals were each fed by ``len()`` of a list that had already
been truncated for DISPLAY, understating the real total:

  A. Testing grade penalty read ``len(shallow_tested_modules)`` (capped at 5).
  B. Architecture grade penalty read ``len(fragile_modules)`` (capped at 3).
  C. Readiness headline read ``len(security_finding_modules)`` (capped at 5).

Each now carries a TRUE-total field (``shallow_tested_count`` / ``fragile_count``
/ ``security_finding_count``) consumed by the penalty/headline, while the offender
list stays capped for the seeder / idea-gen / dashboards. These tests pin the
true-vs-capped contrast AND that a repo at-or-below the cap is unchanged.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.engine.health_score import (
    _GradeMetrics,
    _fragile_penalty_count,
    _score_architecture,
    _score_testing,
    _shallow_penalty_count,
    grade,
)
from app.engine.readiness_report import _findings_section
from app.tools.project_profile import ProjectProfiler


def _metrics(**over) -> _GradeMetrics:
    base = dict(
        cycles=0, fragile=0, untested=0, shallow=0, total_modules=100,
        arch_top=[], untested_list=[], debt_modules=set(), correctness_bugs=0,
        findings=0, weighted_findings=0, top_sec_files=[], top_bug_files=[],
        over_complex=0, maint_top=[], dup_block_count=0, dup_top=[],
    )
    base.update(over)
    return _GradeMetrics(**base)


# --- RESIDUAL A: shallow_tested_count drives the Testing penalty -------------

def test_shallow_penalty_count_prefers_true_total_over_capped_list():
    # 5 displayed offenders, but 40 shallow in truth -> penalty must see 40.
    profile = SimpleNamespace(
        shallow_tested_modules=[f"m{i}.py" for i in range(5)],
        shallow_tested_count=40,
    )
    assert _shallow_penalty_count(profile) == 40


def test_shallow_penalty_count_falls_back_to_list_when_field_absent():
    profile = SimpleNamespace(shallow_tested_modules=["a.py", "b.py"])
    assert _shallow_penalty_count(profile) == 2


def test_testing_penalty_reflects_40_shallow_not_5():
    # The Testing penalty is (untested + 0.5*shallow)/total*25. A 40-shallow repo
    # (display-capped to 5) must be penalised for ~40, not 5.
    capped, _ = _score_testing(_metrics(shallow=5))
    true_total, _ = _score_testing(_metrics(shallow=40))
    assert true_total.points_lost > capped.points_lost
    # 0.5*40/100*25 = 5 points; 0.5*5/100*25 rounds to 1.
    assert true_total.points_lost == 5
    assert capped.points_lost == 1


# --- RESIDUAL B: fragile_count drives the Architecture penalty ---------------

def test_fragile_penalty_count_prefers_true_total_over_capped_list():
    profile = SimpleNamespace(
        fragile_modules=["a.py", "b.py", "c.py"],  # display cap 3
        fragile_count=10,
    )
    assert _fragile_penalty_count(profile) == 10


def test_fragile_penalty_count_falls_back_to_list_when_field_absent():
    profile = SimpleNamespace(fragile_modules=["a.py", "b.py"])
    assert _fragile_penalty_count(profile) == 2


def test_architecture_penalty_reflects_10_fragile_not_3():
    # Architecture loses fragile*4 (cap 20). 10 fragile -> 40 capped to 20;
    # 3 fragile -> 12. Display-as-count would under-penalise by 8.
    capped, _ = _score_architecture(_metrics(fragile=3))
    true_total, _ = _score_architecture(_metrics(fragile=10))
    assert capped.points_lost == 12
    assert true_total.points_lost == 20
    assert true_total.points_lost > capped.points_lost


# --- RESIDUAL C: security_finding_count drives the readiness headline --------

def test_readiness_headline_reflects_20_security_not_5():
    # 5 displayed module names, 20 in truth -> headline must report 20.
    profile = SimpleNamespace(
        security_finding_modules=[f"mod{i}" for i in range(5)],
        security_finding_count=20,
    )
    findings = _findings_section(profile, [])
    assert findings["python_security_count"] == 20
    assert findings["high_confidence_total"] == 20
    # The displayed module list stays capped (other consumers' contract).
    assert len(findings["python_security_modules"]) == 5


def test_readiness_headline_folds_true_security_with_polyglot():
    profile = SimpleNamespace(
        security_finding_modules=["a", "b", "c", "d", "e"],
        security_finding_count=20,
    )
    findings = _findings_section(profile, [{"kind": "js-eval"}, {"kind": "sh"}])
    assert findings["high_confidence_total"] == 22  # 20 + 2, additive


def test_readiness_headline_falls_back_to_list_when_field_absent():
    # Older/partial profiles without the count field keep the legacy len() path.
    profile = SimpleNamespace(security_finding_modules=["a", "b"])
    findings = _findings_section(profile, [])
    assert findings["python_security_count"] == 2
    assert findings["high_confidence_total"] == 2


def test_readiness_headline_none_profile_is_zero():
    findings = _findings_section(None, [])
    assert findings["python_security_count"] == 0
    assert findings["high_confidence_total"] == 0


# --- At-or-below the cap: counts equal the list, nothing shifts --------------

def _make_pkg(root: Path, n_modules: int) -> None:
    (root / "pkg").mkdir()
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")


def test_profiler_sets_true_shallow_and_fragile_counts(tmp_path: Path):
    # 7 modules, each shallow-tested AND a high-fan-in hub of the others, so both
    # the shallow set (>5) and the fragile set (>3) exceed their display caps.
    _make_pkg(tmp_path, 7)
    names = [f"m{i}" for i in range(7)]
    for name in names:
        # Each module imports every OTHER -> every module has fan-in >= 2 (fragile).
        imports = "".join(
            f"import pkg.{o}\n" for o in names if o != name)
        (tmp_path / "pkg" / f"{name}.py").write_text(
            imports + f"def f_{name}(x: int) -> int:\n    return x + 1\n")
        # Shape-only stub: linked but shallow.
        (tmp_path / "tests" / f"test_{name}.py").write_text(
            f"import pkg.{name}\n"
            f"def test_{name}():\n    assert isinstance(pkg.{name}.f_{name}(0), int)\n")

    profile = ProjectProfiler(str(tmp_path)).profile()

    # TRUE totals exceed the display caps...
    assert profile.shallow_tested_count == 7
    assert profile.fragile_count == 7
    # ...but every hub here is shallow-but-tested (linked test), NOT untested, so
    # the UNTESTED-only Architecture-penalty count is 0: these 7 cost TESTING, not
    # ARCHITECTURE (the field-test A-91 -> B+87 regression this fix prevents).
    assert profile.fragile_untested_count == 0
    # ...while the display lists stay capped (other consumers' contract).
    assert len(profile.shallow_tested_modules) == 5
    assert len(profile.fragile_modules) == 3


def test_at_cap_repo_count_equals_list(tmp_path: Path):
    # A single shallow module: count == len(list), no inflation, list not capped.
    _make_pkg(tmp_path, 1)
    (tmp_path / "pkg" / "only.py").write_text(
        "def f(x: int) -> int:\n    return x + 1\n")
    (tmp_path / "tests" / "test_only.py").write_text(
        "import pkg.only\ndef test_o():\n    assert isinstance(pkg.only.f(0), int)\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.shallow_tested_count == len(profile.shallow_tested_modules) == 1


# --- Apex self-grade is UNCHANGED (at/below cap) -----------------------------

@pytest.mark.timeout(300)  # whole-repo grade() is intrinsically ~95-154s; the
# 120s default is a hang tripwire, not a correctness bound — raise it for this one
# genuinely-heavy real-tree audit (mirrors test_owner_report_is_deterministic).
def test_apex_self_grade_unchanged():
    repo_root = Path(__file__).resolve().parent.parent
    g = grade(str(repo_root))
    assert (g.letter, g.score) == ("A+", 99)
    dup = next(c for c in g.components if c.name == "Duplication")
    assert "1 duplicated block(s)" in dup.detail
