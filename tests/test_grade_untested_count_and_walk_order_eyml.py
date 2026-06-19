"""Red-team regressions in the profiler/grade file-walk + grade-input path.

FIX 1 (grade inflation): the profile truncates ``untested_modules`` to 5 for
display, but the grade penalty must score the TRUE untested count — otherwise a
repo with hundreds of untested modules is graded as if only 5 were untested.

FIX 2 (determinism): the base file-walk sampled an UNSORTED ``rglob`` before the
``max_files`` cap, so a repo over the cap scanned a machine-dependent subset.
Sorting before the cap makes the sample a stable sorted-order prefix.
"""
from pathlib import Path

from app.engine.health_score import _untested_penalty_count, grade
from app.tools.project_profile import ProjectProfile, ProjectProfiler


# --------------------------------------------------------------------------- #
# FIX 1 — true untested count drives the penalty; display list stays capped.   #
# --------------------------------------------------------------------------- #

def _build_undertested(root: Path, n_untested: int) -> None:
    """A repo with 12 source modules where ``n_untested`` have no linked test."""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    for i in range(12):
        (root / "app" / f"mod{i:02d}.py").write_text(
            f"def helper_{i}(x):\n    return x + {i}\n", encoding="utf-8")
    # Only the modules at/after ``n_untested`` get a linked test.
    for i in range(n_untested, 12):
        (root / "tests" / f"test_mod{i:02d}.py").write_text(
            f"from app.mod{i:02d} import helper_{i}\n"
            f"def test_h():\n    assert helper_{i}(0) == {i}\n",
            encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='p'\nversion='0'\n", encoding="utf-8")


def test_untested_penalty_uses_true_count_not_capped_display(tmp_path):
    # 12 modules, 11 untested. The display offender list must stay <= 5, but the
    # profile carries the honest total so the grade penalty reflects ~11.
    _build_undertested(tmp_path, n_untested=11)
    profile = ProjectProfiler(str(tmp_path)).profile()

    assert profile.untested_count == 11
    assert len(profile.untested_modules) <= 5
    # The penalty helper reads the TRUE count, not the capped list length.
    assert _untested_penalty_count(profile) == 11
    assert _untested_penalty_count(profile) != len(profile.untested_modules)


def test_undertested_repo_loses_meaningful_testing_points(tmp_path):
    _build_undertested(tmp_path, n_untested=11)
    result = grade(str(tmp_path))
    testing = next(c for c in result.components if c.name == "Testing")
    # 11/12 untested -> ~23/25 lost. With the bug it would have been round(5/12*25)=10.
    assert testing.points_lost >= 20
    assert "11 untested" in testing.detail


def test_penalty_helper_falls_back_to_capped_list_when_field_absent():
    # Older/partial profiles without ``untested_count`` fall back to the list len.
    p = ProjectProfile(root=".")
    p.untested_modules = ["a.py", "b.py", "c.py"]
    p.untested_count = 0
    assert _untested_penalty_count(p) == 3


def test_repo_with_few_untested_is_unchanged(tmp_path):
    # A repo with <= 5 untested: true count == display-list len, so the grade
    # is byte-identical to the pre-fix behaviour.
    _build_undertested(tmp_path, n_untested=3)
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.untested_count == 3
    assert len(profile.untested_modules) == 3
    assert _untested_penalty_count(profile) == len(profile.untested_modules)


def test_apex_self_grade_unchanged_a_plus_99():
    # The honest-count fix must not move Apex's own grade (Apex has <= 5 untested).
    result = grade(".")
    assert result.letter == "A+"
    assert result.score == 99
    dup = next(c for c in result.components if c.name == "Duplication")
    assert dup.points_lost == 1


# --------------------------------------------------------------------------- #
# FIX 2 — file walk samples the SORTED-order prefix before the max_files cap.   #
# --------------------------------------------------------------------------- #

def _build_many_files(root: Path) -> list[str]:
    """8 source files, each carrying the ``auth`` sensitive hint so every scanned
    one lands in ``profile.sensitive_paths`` — a clean observable of the sampled
    subset. Names sort as auth0.py .. auth7.py."""
    (root / "app").mkdir()
    names = []
    for i in range(8):
        rel = f"app/auth{i}.py"
        (root / "app" / f"auth{i}.py").write_text(f"x = {i}\n", encoding="utf-8")
        names.append(rel)
    return names


def _run_walk(root: Path, max_files: int, order_fn, monkeypatch):
    """Profile ``root`` with rglob's raw order transformed by ``order_fn``."""
    real_rglob = Path.rglob

    def patched(self, pattern):
        return order_fn(list(real_rglob(self, pattern)))

    monkeypatch.setattr(Path, "rglob", patched)
    p = ProjectProfiler(str(root), max_files=max_files).profile(light=True)
    monkeypatch.undo()
    return p


def test_capped_walk_samples_sorted_prefix(tmp_path, monkeypatch):
    _build_many_files(tmp_path)
    # Simulate hostile FS order: rglob yields files reversed. The sorted() in the
    # walk must neutralise it and sample the lowest-sorting prefix.
    p = _run_walk(tmp_path, max_files=3, order_fn=lambda xs: list(reversed(xs)),
                  monkeypatch=monkeypatch)

    assert p.total_files == 3
    sampled = sorted(str(Path(x).as_posix()) for x in p.sensitive_paths)
    # Sorted prefix of auth0..auth7 -> auth0, auth1, auth2.
    assert sampled == ["app/auth0.py", "app/auth1.py", "app/auth2.py"]


def test_capped_walk_is_deterministic_across_simulated_fs_orders(tmp_path, monkeypatch):
    _build_many_files(tmp_path)
    forward = _run_walk(tmp_path, 3, lambda xs: xs, monkeypatch)
    backward = _run_walk(tmp_path, 3, lambda xs: list(reversed(xs)), monkeypatch)

    f = (forward.total_files, sorted(str(Path(x).as_posix()) for x in forward.sensitive_paths))
    b = (backward.total_files, sorted(str(Path(x).as_posix()) for x in backward.sensitive_paths))
    assert f == b
    assert f[0] == 3


def test_capped_walk_sampled_subset_is_sorted_prefix(tmp_path, monkeypatch):
    # Pin the exact subset under a different order + cap: the sorted-order prefix
    # of length max_files, independent of rglob's raw order.
    _build_many_files(tmp_path)
    p = _run_walk(tmp_path, max_files=4, order_fn=lambda xs: list(reversed(xs)),
                  monkeypatch=monkeypatch)
    sampled = sorted(str(Path(x).as_posix()) for x in p.sensitive_paths)
    assert sampled == ["app/auth0.py", "app/auth1.py", "app/auth2.py", "app/auth3.py"]
