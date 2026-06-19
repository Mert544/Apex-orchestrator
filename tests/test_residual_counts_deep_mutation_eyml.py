"""Deep-mutation hardening for the Batch-B *residual-count* grade/readiness fixes.

Three profile fields carry the TRUE total of a signal, kept separate from the
(capped) display list the consumers render:

  * ``shallow_tested_count`` — the FULL shallow-tested total. The Testing grade
    penalty (``_shallow_penalty_count`` → ``_score_testing``) must read it, NOT
    ``len(shallow_tested_modules)`` (capped at 5).
  * ``fragile_count`` — the FULL fragile-module total. The Architecture penalty
    (``_fragile_penalty_count`` → ``_score_architecture``) must read it, NOT
    ``len(fragile_modules)`` (capped at 3).
  * ``security_finding_count`` — the FULL Python security-finding total. The
    readiness headline (``_findings_section`` → ``python_security_count`` /
    ``high_confidence_total``) must read it, NOT ``len(security_finding_modules)``
    (capped at 5).

These tests pin the EXACT penalty/headline value with a true-vs-capped contrast,
the fallback-to-``len`` behaviour for old profiles missing the field, and that a
repo AT/BELOW the cap is byte-identical to the pre-fix behaviour. The display
lists are pinned to stay ≤5 / ≤3.

Content of individual findings is owned by the kitchen-sink suites; this file
pins only that the residual-count plumbing reads the full total, not the cap.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.health_score import (
    _GradeMetrics,
    _fragile_penalty_count,
    _score_architecture,
    _score_testing,
    _shallow_penalty_count,
    grade,
)
from app.engine.readiness_report import _findings_section
from app.tools.project_profile import ProjectProfile, ProjectProfiler


def _metrics(*, fragile: int = 0, cycles: int = 0, untested: int = 0,
             shallow: int = 0, total: int = 50) -> _GradeMetrics:
    return _GradeMetrics(
        cycles=cycles, fragile=fragile, untested=untested, shallow=shallow,
        total_modules=total, arch_top=[], untested_list=[], debt_modules=set(),
        correctness_bugs=0, findings=0, weighted_findings=0, top_sec_files=[],
        top_bug_files=[], over_complex=0, maint_top=[], dup_block_count=0,
        dup_top=[],
    )


# --------------------------------------------------------------------------- #
# shallow_tested_count -> Testing penalty (full count, not capped-5).          #
# --------------------------------------------------------------------------- #


def test_shallow_penalty_count_prefers_true_field_over_capped_list():
    """A truthy ``shallow_tested_count`` is used verbatim even when the display
    list is capped at 5 — the penalty reads the full total, not ``len(list)``."""
    p = ProjectProfile(root=".")
    p.shallow_tested_modules = ["a.py", "b.py", "c.py", "d.py", "e.py"]
    p.shallow_tested_count = 40
    assert _shallow_penalty_count(p) == 40
    assert _shallow_penalty_count(p) != len(p.shallow_tested_modules)


def test_shallow_penalty_count_falls_back_to_list_len_when_field_zero():
    """A falsy (zero) ``shallow_tested_count`` falls back to the EXACT list
    length — kills a mutant that returned 0 or skipped the fallback branch."""
    p = ProjectProfile(root=".")
    p.shallow_tested_modules = ["a.py", "b.py", "c.py"]
    p.shallow_tested_count = 0
    assert _shallow_penalty_count(p) == 3


def test_shallow_penalty_count_falls_back_when_field_absent():
    """An older/partial profile object with no ``shallow_tested_count`` attribute
    uses the list length (the ``getattr(..., None)`` default path)."""
    class _Old:
        shallow_tested_modules = ["x.py", "y.py"]
    assert _shallow_penalty_count(_Old()) == 2


def test_shallow_penalty_count_zero_when_both_empty():
    p = ProjectProfile(root=".")
    p.shallow_tested_modules = []
    p.shallow_tested_count = 0
    assert _shallow_penalty_count(p) == 0


def test_score_testing_uses_full_shallow_count_exact_points():
    """40 shallow of 50 -> effective 0.5*40 == 20 -> round(20/50*25) == 10 points
    (the TRUE count), NOT the capped-5 value (round(2.5/50*25) == 1). Pins the
    0.5 factor, the divisor and the *25 against a swapped-count mutant."""
    component, _fix = _score_testing(_metrics(shallow=40, total=50))
    assert component.points_lost == 10
    assert component.detail == "0 untested + 40 shallow-tested module(s) of ~50"
    capped, _ = _score_testing(_metrics(shallow=5, total=50))
    assert capped.points_lost == 1
    assert component.points_lost != capped.points_lost


# --------------------------------------------------------------------------- #
# fragile_count -> Architecture penalty (full count, not capped-3).            #
# --------------------------------------------------------------------------- #


def test_fragile_penalty_count_prefers_true_field_over_capped_list():
    """A truthy ``fragile_count`` is used verbatim even when the display list is
    capped at 3 — the penalty reads the full total, not ``len(list)``."""
    p = ProjectProfile(root=".")
    p.fragile_modules = ["a.py", "b.py", "c.py"]
    p.fragile_count = 10
    assert _fragile_penalty_count(p) == 10
    assert _fragile_penalty_count(p) != len(p.fragile_modules)


def test_fragile_penalty_count_falls_back_to_list_len_when_field_zero():
    p = ProjectProfile(root=".")
    p.fragile_modules = ["a.py", "b.py"]
    p.fragile_count = 0
    assert _fragile_penalty_count(p) == 2


def test_fragile_penalty_count_falls_back_when_field_absent():
    class _Old:
        fragile_modules = ["x.py"]
    assert _fragile_penalty_count(_Old()) == 1


def test_fragile_penalty_count_zero_when_both_empty():
    p = ProjectProfile(root=".")
    p.fragile_modules = []
    p.fragile_count = 0
    assert _fragile_penalty_count(p) == 0


def test_score_architecture_uses_full_fragile_count_exact_points():
    """10 fragile, 0 cycles -> min(20, 0*5 + 10*4) == 20 points (the TRUE count),
    NOT the capped-3 value (3*4 == 12). Pins the *4 weight and the count source."""
    component, _fix = _score_architecture(_metrics(fragile=10))
    assert component.points_lost == 20
    assert component.detail == "0 import cycle(s), 10 fragile module(s)"
    capped, _ = _score_architecture(_metrics(fragile=3))
    assert capped.points_lost == 12
    assert component.points_lost != capped.points_lost


def test_score_architecture_fragile_weight_is_exactly_four():
    """1 fragile module, 0 cycles -> exactly 4 points (pins the *4 weight, not
    *3 or *5)."""
    component, _ = _score_architecture(_metrics(fragile=1))
    assert component.points_lost == 4


# --------------------------------------------------------------------------- #
# security_finding_count -> readiness headline (full count, not capped-5).     #
# --------------------------------------------------------------------------- #


def test_findings_section_prefers_true_security_count_over_capped_list():
    """A truthy ``security_finding_count`` drives the headline even when the
    module list is capped at 5 — the headline reflects every finding."""
    p = ProjectProfile(root=".")
    p.security_finding_modules = ["a.py", "b.py", "c.py", "d.py", "e.py"]
    p.security_finding_count = 20
    section = _findings_section(p, [])
    assert section["python_security_count"] == 20
    assert section["high_confidence_total"] == 20
    assert section["python_security_count"] != len(p.security_finding_modules)
    # The display list stays the capped 5 module names.
    assert section["python_security_modules"] == ["a.py", "b.py", "c.py", "d.py", "e.py"]


def test_findings_section_folds_full_count_into_high_confidence_total():
    """The high-confidence total is the FULL security count plus polyglot
    findings: 20 + 2 == 22 (pins the addition uses the full count, not the 5)."""
    p = ProjectProfile(root=".")
    p.security_finding_modules = ["a.py", "b.py", "c.py", "d.py", "e.py"]
    p.security_finding_count = 20
    section = _findings_section(p, [{"kind": "x"}, {"kind": "y"}])
    assert section["high_confidence_total"] == 22
    assert section["polyglot_findings_count"] == 2


def test_findings_section_falls_back_to_module_len_when_count_zero():
    """A falsy ``security_finding_count`` falls back to the EXACT module-list
    length (older/partial profiles)."""
    p = ProjectProfile(root=".")
    p.security_finding_modules = ["a.py", "b.py"]
    p.security_finding_count = 0
    section = _findings_section(p, [])
    assert section["python_security_count"] == 2
    assert section["high_confidence_total"] == 2


def test_findings_section_none_profile_is_zero():
    section = _findings_section(None, [])
    assert section["python_security_count"] == 0
    assert section["high_confidence_total"] == 0


# --------------------------------------------------------------------------- #
# End-to-end on built repos: the profile carries the full total, capped lists. #
# --------------------------------------------------------------------------- #


def _build_shallow_hub_repo(root: Path) -> None:
    """6 import-smoke-only-tested users of a single hub, plus a smoke-tested hub:
    7 shallow-tested modules (> the 5-cap), 1 fragile hub."""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "hub.py").write_text(
        "def core(x):\n    return x + 1\n", encoding="utf-8")
    for i in range(6):
        (root / "app" / f"user{i}.py").write_text(
            f"from app.hub import core\ndef u{i}(x):\n    return core(x)\n",
            encoding="utf-8")
        (root / "tests" / f"test_user{i}.py").write_text(
            f"import app.user{i}\n"
            f"def test_imports():\n    assert app.user{i} is not None\n",
            encoding="utf-8")
    (root / "tests" / "test_hub.py").write_text(
        "import app.hub\ndef test_imports():\n    assert app.hub is not None\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='p'\nversion='0'\n", encoding="utf-8")


def test_profile_carries_full_shallow_count_but_capped_display(tmp_path):
    """7 shallow-tested modules: the display list is capped at 5 yet
    ``shallow_tested_count`` is the honest 7, and the penalty helper reads 7."""
    _build_shallow_hub_repo(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile(light=True)
    assert profile.shallow_tested_count == 7
    assert len(profile.shallow_tested_modules) == 5
    assert _shallow_penalty_count(profile) == 7


def _build_many_fragile_repo(root: Path) -> None:
    """5 untested hubs each imported by 2 users -> 5 fragile modules (> the
    3-cap)."""
    (root / "app").mkdir()
    for h in range(5):
        (root / "app" / f"hub{h}.py").write_text(
            f"def core{h}(x):\n    return x + {h}\n", encoding="utf-8")
        for u in range(2):
            (root / "app" / f"u{h}_{u}.py").write_text(
                f"from app.hub{h} import core{h}\ndef f(x):\n    return core{h}(x)\n",
                encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='p'\nversion='0'\n", encoding="utf-8")


def test_profile_carries_full_fragile_count_but_capped_display(tmp_path):
    """5 fragile hubs: the display list is capped at 3 yet ``fragile_count`` is
    the honest 5, and the penalty helper reads 5."""
    _build_many_fragile_repo(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile(light=True)
    assert profile.fragile_count == 5
    assert len(profile.fragile_modules) == 3
    assert _fragile_penalty_count(profile) == 5


def _build_many_security_repo(root: Path) -> None:
    """8 modules each using eval() -> 8 Python security findings (> the 5-cap)."""
    (root / "app").mkdir()
    for i in range(8):
        (root / "app" / f"sec{i}.py").write_text(
            f"def run{i}(x):\n    return eval(x)\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='p'\nversion='0'\n", encoding="utf-8")


def test_profile_carries_full_security_count_but_capped_display(tmp_path):
    """8 eval() modules: the display list is capped at 5 yet
    ``security_finding_count`` is the honest 8, and the headline reads 8."""
    _build_many_security_repo(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile(light=True)
    assert profile.security_finding_count == 8
    assert len(profile.security_finding_modules) == 5
    section = _findings_section(profile, [])
    assert section["python_security_count"] == 8
    assert section["high_confidence_total"] == 8


# --------------------------------------------------------------------------- #
# A repo AT/BELOW the cap is byte-identical to the pre-fix (len-based) path.    #
# --------------------------------------------------------------------------- #


def test_at_cap_security_repo_count_equals_display_len(tmp_path):
    """Exactly 4 eval() modules (<= 5): the true count equals the display-list
    len, so the headline is identical to pre-fix behaviour."""
    (tmp_path / "app").mkdir()
    for i in range(4):
        (tmp_path / "app" / f"sec{i}.py").write_text(
            f"def run{i}(x):\n    return eval(x)\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='p'\nversion='0'\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile(light=True)
    assert profile.security_finding_count == 4
    assert len(profile.security_finding_modules) == 4
    section = _findings_section(profile, [])
    assert section["python_security_count"] == len(profile.security_finding_modules)
    assert section["python_security_count"] == 4


def test_below_cap_fragile_repo_count_equals_display_len(tmp_path):
    """2 fragile hubs (< the 3-cap): true count == display-list len, so the
    Architecture penalty is identical to pre-fix behaviour."""
    (tmp_path / "app").mkdir()
    for h in range(2):
        (tmp_path / "app" / f"hub{h}.py").write_text(
            f"def core{h}(x):\n    return x + {h}\n", encoding="utf-8")
        for u in range(2):
            (tmp_path / "app" / f"u{h}_{u}.py").write_text(
                f"from app.hub{h} import core{h}\ndef f(x):\n    return core{h}(x)\n",
                encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='p'\nversion='0'\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile(light=True)
    assert profile.fragile_count == 2
    assert len(profile.fragile_modules) == 2
    assert _fragile_penalty_count(profile) == len(profile.fragile_modules)


def test_grade_architecture_penalty_reflects_full_fragile_count(tmp_path):
    """End-to-end grade: a 5-fragile repo loses 5*4 == 20 Architecture points
    (capped at 20), not the 3*4 == 12 the capped-display bug would produce."""
    _build_many_fragile_repo(tmp_path)
    result = grade(str(tmp_path))
    arch = next(c for c in result.components if c.name == "Architecture")
    assert arch.points_lost == 20
    assert arch.detail == "0 import cycle(s), 5 fragile module(s)"
    assert len(arch.top_files) <= 3
