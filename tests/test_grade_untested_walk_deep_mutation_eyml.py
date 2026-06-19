"""Deep-mutation hardening for the true-untested-count grade fix + sorted walk.

Two Batch-3 fixes in ``app/engine/health_score.py`` and
``app/tools/project_profile.py``:

FIX 1 (grade honesty): the profile truncates ``untested_modules`` to 5 for
DISPLAY, but the Testing penalty must score the FULL untested count
(``untested_count``). ``_untested_penalty_count`` prefers that field, falling
back to the (capped) list length only when it is absent/zero. These tests pin
the exact count fed into the penalty math AND the exact ``points_lost`` the
``_score_testing`` scorer produces (with the divisor, the 0.5 shallow factor,
the 25-cap, and the bug-vs-fix divergence), so a flipped comparison or a swapped
``untested``↔``len(untested_list)`` cannot survive.

FIX 2 (determinism): the base file walk sorts ``rglob`` BEFORE the ``max_files``
cap, so the sampled subset is the same SORTED-order prefix on every machine.
These tests pin the EXACT sampled prefix under simulated hostile FS orders and
that the result is identical across those orders.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.health_score import (
    _GradeMetrics,
    _score_testing,
    _untested_penalty_count,
    grade,
)
from app.tools.project_profile import ProjectProfile, ProjectProfiler


# --------------------------------------------------------------------------- #
# FIX 1 — _untested_penalty_count: prefer the true count, exact fallbacks.     #
# --------------------------------------------------------------------------- #


def test_penalty_count_prefers_true_field_over_capped_list():
    """A truthy ``untested_count`` is used verbatim even when the display list is
    capped at 5 — the penalty reads the full total, not ``len(list)``."""
    p = ProjectProfile(root=".")
    p.untested_modules = ["a.py", "b.py", "c.py", "d.py", "e.py"]
    p.untested_count = 17
    assert _untested_penalty_count(p) == 17
    assert _untested_penalty_count(p) != len(p.untested_modules)


def test_penalty_count_falls_back_to_list_len_when_field_zero():
    """A falsy (zero) ``untested_count`` falls back to the EXACT list length —
    kills a mutant that returned 0 or skipped the fallback branch."""
    p = ProjectProfile(root=".")
    p.untested_modules = ["a.py", "b.py", "c.py"]
    p.untested_count = 0
    assert _untested_penalty_count(p) == 3


def test_penalty_count_falls_back_when_field_absent():
    """An older/partial profile object with no ``untested_count`` attribute uses
    the list length (the ``getattr(..., None)`` default path)."""
    class _Old:
        untested_modules = ["x.py", "y.py"]
    assert _untested_penalty_count(_Old()) == 2


def test_penalty_count_zero_when_both_empty():
    """No untested modules at all -> exactly 0 (no off-by-one)."""
    p = ProjectProfile(root=".")
    p.untested_modules = []
    p.untested_count = 0
    assert _untested_penalty_count(p) == 0


# --------------------------------------------------------------------------- #
# FIX 1 — _score_testing: exact penalty math (divisor, cap, 0.5, bug-contrast).#
# --------------------------------------------------------------------------- #


def _metrics(untested: int, shallow: int, total: int) -> _GradeMetrics:
    return _GradeMetrics(
        cycles=0, fragile=0, untested=untested, shallow=shallow,
        total_modules=total, arch_top=[], untested_list=[], debt_modules=set(),
        correctness_bugs=0, findings=0, weighted_findings=0, top_sec_files=[],
        top_bug_files=[], over_complex=0, maint_top=[], dup_block_count=0,
        dup_top=[],
    )


def test_score_testing_uses_true_count_exact_points():
    """11 untested of 12 -> round(11/12*25) == 23 points lost (the TRUE count),
    NOT the capped-5 value (round(5/12*25) == 10). Pins the divisor + the *25."""
    component, _fix = _score_testing(_metrics(11, 0, 12))
    assert component.points_lost == 23
    assert component.detail == "11 untested module(s) of ~12"
    # The bug would have scored the capped display count.
    capped, _ = _score_testing(_metrics(5, 0, 12))
    assert capped.points_lost == 10
    assert component.points_lost != capped.points_lost


def test_score_testing_shallow_counts_half():
    """Shallow-tested modules get HALF credit: 4 untested + 4 shallow of 12 ->
    effective 6 -> round(6/12*25) == 12. Pins the 0.5 factor exactly."""
    component, _ = _score_testing(_metrics(4, 4, 12))
    assert component.points_lost == 12
    assert component.detail == "4 untested + 4 shallow-tested module(s) of ~12"


def test_score_testing_is_capped_at_exactly_25():
    """A repo whose raw penalty (round(200/100*25) == 50) far exceeds the cap
    loses EXACTLY 25 — pins the ``min(25, ...)`` cap constant (a 25->26 mutant
    would surface 26 here)."""
    component, _ = _score_testing(_metrics(200, 0, 100))
    assert component.points_lost == 25


def test_score_testing_clean_repo_loses_nothing():
    """Zero untested + zero shallow -> exactly 0 points lost and no fix surfaced."""
    component, fix = _score_testing(_metrics(0, 0, 50))
    assert component.points_lost == 0
    assert fix is None


# --------------------------------------------------------------------------- #
# FIX 1 — end-to-end grade on a built repo: penalty reflects the true count.    #
# --------------------------------------------------------------------------- #


def _build_undertested(root: Path, n_untested: int, n_total: int = 12) -> None:
    """A repo of ``n_total`` source modules where ``n_untested`` lack a test."""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    for i in range(n_total):
        (root / "app" / f"mod{i:02d}.py").write_text(
            f"def helper_{i}(x):\n    return x + {i}\n", encoding="utf-8")
    for i in range(n_untested, n_total):
        (root / "tests" / f"test_mod{i:02d}.py").write_text(
            f"from app.mod{i:02d} import helper_{i}\n"
            f"def test_h():\n    assert helper_{i}(0) == {i}\n",
            encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='p'\nversion='0'\n", encoding="utf-8")


def test_profile_carries_full_count_but_capped_display(tmp_path):
    """11/12 untested: the display list is capped at 5 yet ``untested_count`` is
    the honest 11, and the penalty helper reads the 11."""
    _build_undertested(tmp_path, n_untested=11)
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.untested_count == 11
    assert len(profile.untested_modules) == 5
    assert _untested_penalty_count(profile) == 11


def test_grade_testing_penalty_is_exact_23(tmp_path):
    """End-to-end grade: an 11/12-untested repo loses EXACTLY 23 Testing points,
    not the 10 the capped-display bug would have produced."""
    _build_undertested(tmp_path, n_untested=11)
    result = grade(str(tmp_path))
    testing = next(c for c in result.components if c.name == "Testing")
    assert testing.points_lost == 23
    assert testing.detail == "11 untested module(s) of ~12"
    assert len(testing.top_files) <= 5


def test_few_untested_repo_is_unchanged(tmp_path):
    """<= 5 untested: true count == display-list len, so the grade is identical
    to pre-fix behaviour. 3/12 -> round(3/12*25) == 6 points lost."""
    _build_undertested(tmp_path, n_untested=3)
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.untested_count == 3
    assert len(profile.untested_modules) == 3
    assert _untested_penalty_count(profile) == len(profile.untested_modules)
    testing = next(c for c in grade(str(tmp_path)).components if c.name == "Testing")
    assert testing.points_lost == 6


# --------------------------------------------------------------------------- #
# FIX 2 — base walk samples the SORTED-order prefix before the max_files cap.   #
# --------------------------------------------------------------------------- #


def _build_many_files(root: Path) -> None:
    """8 source files each carrying the ``auth`` sensitive hint, so every SCANNED
    one lands in ``profile.sensitive_paths`` — a clean observable of the sampled
    subset. Names sort auth0.py .. auth7.py."""
    (root / "app").mkdir()
    for i in range(8):
        (root / "app" / f"auth{i}.py").write_text(f"x = {i}\n", encoding="utf-8")


def _run_walk(root: Path, max_files: int, order_fn, monkeypatch):
    """Profile ``root`` with rglob's raw order transformed by ``order_fn``."""
    real_rglob = Path.rglob

    def patched(self, pattern):
        return order_fn(list(real_rglob(self, pattern)))

    monkeypatch.setattr(Path, "rglob", patched)
    profile = ProjectProfiler(str(root), max_files=max_files).profile(light=True)
    monkeypatch.undo()
    return profile


def _sampled(profile) -> list[str]:
    return sorted(Path(x).as_posix() for x in profile.sensitive_paths)


def test_capped_walk_samples_sorted_prefix_under_reversed_fs(tmp_path, monkeypatch):
    """Hostile FS order (rglob reversed) + cap 3: the SORTED prefix auth0..auth2
    is sampled, not the reversed tail — the sort runs BEFORE the cap."""
    _build_many_files(tmp_path)
    profile = _run_walk(tmp_path, 3, lambda xs: list(reversed(xs)), monkeypatch)
    assert profile.total_files == 3
    assert _sampled(profile) == ["app/auth0.py", "app/auth1.py", "app/auth2.py"]


def test_capped_walk_prefix_length_tracks_max_files(tmp_path, monkeypatch):
    """A different cap selects a different-length sorted prefix: cap 5 -> the
    first FIVE sorted names, regardless of raw order."""
    _build_many_files(tmp_path)
    profile = _run_walk(tmp_path, 5, lambda xs: list(reversed(xs)), monkeypatch)
    assert profile.total_files == 5
    assert _sampled(profile) == [
        "app/auth0.py", "app/auth1.py", "app/auth2.py",
        "app/auth3.py", "app/auth4.py",
    ]


def test_capped_walk_is_deterministic_across_simulated_fs_orders(tmp_path, monkeypatch):
    """Forward vs reversed raw FS order yield the IDENTICAL sampled subset and
    file count — the determinism the grade relies on."""
    _build_many_files(tmp_path)
    forward = _run_walk(tmp_path, 3, lambda xs: xs, monkeypatch)
    backward = _run_walk(tmp_path, 3, lambda xs: list(reversed(xs)), monkeypatch)
    assert forward.total_files == 3
    assert backward.total_files == 3
    assert _sampled(forward) == _sampled(backward)
    assert _sampled(forward) == ["app/auth0.py", "app/auth1.py", "app/auth2.py"]


def test_uncapped_walk_scans_every_file(tmp_path, monkeypatch):
    """With a cap above the file count, all 8 files are scanned regardless of raw
    order — the cap is a ``>=`` break, not an off-by-one truncation."""
    _build_many_files(tmp_path)
    profile = _run_walk(tmp_path, 50, lambda xs: list(reversed(xs)), monkeypatch)
    assert profile.total_files == 8
    assert _sampled(profile) == [f"app/auth{i}.py" for i in range(8)]
