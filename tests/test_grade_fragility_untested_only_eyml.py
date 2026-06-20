"""Architecture fragility penalty counts only UNTESTED hubs (field-test fix).

A clean develop improvement must NEVER RAISE the grade's fragility penalty.

A field-test saw the grade slip A-91 -> B+87 after Apex landed *verified*
improvements: ``dataclassify`` shrank a module's assertable surface so its linked
test flipped non-shallow -> shallow, and the old fragility rule
``fragile = in_degree>=2 AND (untested OR shallow)`` then newly flagged the module,
costing Architecture -4 even though a real improvement had landed.

The fix: the Architecture penalty counts only the UNTESTED fragile hubs
(``fragile_untested_count``), while the ``fragile_modules`` / ``fragile_count``
DISCOVERY set (seeders / dashboards / anomaly-discovery) still flags shallow hubs.
Shallow hubs still cost TESTING (via ``shallow_tested_count``) — only ARCHITECTURE
is spared. These tests pin:

  1. A high-fan-in SHALLOW-but-tested hub is NOT in the Architecture penalty count
     but IS still in ``fragile_modules`` (the discovery surface) — penalty unchanged.
  2. A high-fan-in UNTESTED hub IS counted by the Architecture penalty.
  3. ``_fragile_penalty_count`` honors an explicit ``0`` (the common, clean case)
     and falls back to ``fragile_count`` / the capped list for older profiles.
  4. A clean improvement (add a real test to a fragile hub) makes the Architecture
     penalty FALL, and a shallow-only "improvement" can never make it RISE.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.engine.health_score import (
    _fragile_penalty_count,
    _score_architecture,
)
from app.tools.project_profile import ProjectProfiler


def _metrics(fragile: int):
    # The Architecture scorer only reads .cycles, .fragile, .arch_top here.
    return SimpleNamespace(cycles=0, fragile=fragile, arch_top=[])


def _write_hub(root: Path, name: str, fan_in: int) -> None:
    """A hub module imported by ``fan_in`` leaf importers (so in_degree == fan_in)."""
    (root / "app" / f"{name}.py").write_text(
        "def f(x):\n    return x\n", encoding="utf-8")
    for i in range(fan_in):
        (root / "app" / f"{name}_c{i}.py").write_text(
            f"from app.{name} import f\n\ndef u{i}():\n    return f({i})\n",
            encoding="utf-8")


def _shallow_test_for(root: Path, name: str) -> None:
    # Import-smoke + isinstance contract: linked but asserts no real behaviour.
    (root / "tests" / f"test_{name}.py").write_text(
        f"import app.{name}\n"
        f"def test_{name}():\n    assert isinstance(app.{name}.f(0), int)\n",
        encoding="utf-8")


def _real_test_for(root: Path, name: str) -> None:
    # A substantive assertion on the function's actual output.
    (root / "tests" / f"test_{name}.py").write_text(
        f"from app.{name} import f\n\ndef test_{name}():\n    assert f(3) == 3\n",
        encoding="utf-8")


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


# --- Profiler: shallow hub stays in discovery, out of the penalty count ------

def test_shallow_hub_in_discovery_not_in_untested_count(tmp_path: Path):
    # s0: high-fan-in hub whose ONLY linked test is shallow (still tested).
    repo = _make_repo(tmp_path)
    _write_hub(repo, "s0", fan_in=3)
    _shallow_test_for(repo, "s0")

    profile = ProjectProfiler(str(repo)).profile()

    # The DISCOVERY surface still flags the shallow hub (seeders/dashboards rely
    # on this) — fragile_modules / fragile_count are unchanged.
    assert "app/s0.py" in profile.fragile_modules
    assert profile.fragile_count >= 1
    # It is shallow-but-tested, so it is NOT untested...
    assert "app/s0.py" not in profile.untested_modules
    assert "app/s0.py" in profile.shallow_tested_modules
    # ...and therefore NOT in the UNTESTED-only Architecture-penalty count.
    assert profile.fragile_untested_count == 0


def test_untested_hub_is_in_penalty_count(tmp_path: Path):
    # u0: high-fan-in hub with NO linked test at all -> genuinely untested.
    repo = _make_repo(tmp_path)
    _write_hub(repo, "u0", fan_in=3)

    profile = ProjectProfiler(str(repo)).profile()

    assert "app/u0.py" in profile.fragile_modules
    assert "app/u0.py" in profile.untested_modules
    # The untested fragile hub IS counted for the Architecture penalty.
    assert profile.fragile_untested_count == 1


def test_mixed_repo_penalty_counts_only_untested(tmp_path: Path):
    # One untested hub (u0) + one shallow-but-tested hub (s0), both fragile.
    repo = _make_repo(tmp_path)
    _write_hub(repo, "u0", fan_in=3)
    _write_hub(repo, "s0", fan_in=3)
    _shallow_test_for(repo, "s0")

    profile = ProjectProfiler(str(repo)).profile()

    # Discovery sees BOTH fragile hubs...
    assert "app/u0.py" in profile.fragile_modules
    assert "app/s0.py" in profile.fragile_modules
    assert profile.fragile_count == 2
    # ...but the Architecture penalty counts ONLY the untested one.
    assert profile.fragile_untested_count == 1


# --- The penalty-count selector contract -------------------------------------

def test_penalty_count_honors_explicit_zero():
    # A clean repo with shallow-but-tested fragile hubs: fragile_count > 0 but
    # fragile_untested_count == 0. The explicit 0 MUST win (is not None), so the
    # Architecture penalty is 0 — the field-test regression cannot recur.
    profile = SimpleNamespace(
        fragile_untested_count=0,
        fragile_count=5,
        fragile_modules=["a.py", "b.py", "c.py"],
    )
    assert _fragile_penalty_count(profile) == 0


def test_penalty_count_uses_untested_total_when_present():
    profile = SimpleNamespace(
        fragile_untested_count=4,
        fragile_count=9,
        fragile_modules=["a.py", "b.py", "c.py"],
    )
    assert _fragile_penalty_count(profile) == 4


def test_penalty_count_falls_back_to_fragile_count_when_field_absent():
    # Older/partial profiles without the untested-only field keep prior behaviour
    # (this is the contract pinned by test_residual_count_honesty_eyml).
    profile = SimpleNamespace(
        fragile_modules=["a.py", "b.py", "c.py"],  # display cap 3
        fragile_count=10,
    )
    assert _fragile_penalty_count(profile) == 10


def test_penalty_count_falls_back_to_list_when_no_counts():
    profile = SimpleNamespace(fragile_modules=["a.py", "b.py"])
    assert _fragile_penalty_count(profile) == 2


def test_penalty_count_empty_profile_is_zero():
    assert _fragile_penalty_count(SimpleNamespace()) == 0


# --- Monotonicity: a clean improvement can never RAISE the penalty -----------

def test_shallow_hub_does_not_raise_architecture_penalty():
    # The field-test scenario, end to end at the scorer level. BEFORE: a hub is
    # non-shallow (a real test) -> not fragile at all -> fragile_untested 0.
    # AFTER a clean ``dataclassify`` shrinks its assertable surface: the test goes
    # shallow, so the hub enters fragile_modules (discovery) BUT stays out of
    # untested (still has a linked test) -> fragile_untested stays 0. The
    # Architecture penalty does NOT rise.
    before = SimpleNamespace(fragile_untested_count=0, fragile_count=0)
    after = SimpleNamespace(fragile_untested_count=0, fragile_count=1)

    pen_before, _ = _score_architecture(_metrics(_fragile_penalty_count(before)))
    pen_after, _ = _score_architecture(_metrics(_fragile_penalty_count(after)))
    assert pen_after.points_lost == pen_before.points_lost  # never rises


def test_adding_a_real_test_lowers_architecture_penalty(tmp_path: Path):
    # A fragile UNTESTED hub costs Architecture; landing a real test for it clears
    # it from untested -> the penalty FALLS (never rises). This is the canonical
    # clean develop improvement the grade must reward, not punish.
    repo = _make_repo(tmp_path)
    _write_hub(repo, "u0", fan_in=3)
    before = ProjectProfiler(str(repo)).profile()
    pen_before, _ = _score_architecture(
        _metrics(_fragile_penalty_count(before)))
    assert before.fragile_untested_count == 1
    assert pen_before.points_lost > 0

    # Land a substantive test for the hub (the develop improvement).
    _real_test_for(repo, "u0")
    after = ProjectProfiler(str(repo)).profile()
    pen_after, _ = _score_architecture(
        _metrics(_fragile_penalty_count(after)))
    # The hub is now genuinely tested -> not fragile-untested -> penalty falls.
    assert after.fragile_untested_count == 0
    assert pen_after.points_lost < pen_before.points_lost


def test_profiler_fragility_is_deterministic(tmp_path: Path):
    repo = _make_repo(tmp_path)
    _write_hub(repo, "u0", fan_in=3)
    _write_hub(repo, "s0", fan_in=3)
    _shallow_test_for(repo, "s0")
    a = ProjectProfiler(str(repo)).profile()
    b = ProjectProfiler(str(repo)).profile()
    assert a.fragile_untested_count == b.fragile_untested_count
    assert a.fragile_modules == b.fragile_modules
    assert a.fragile_count == b.fragile_count
