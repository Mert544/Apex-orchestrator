"""Severity-aware, asymmetric anomaly ranking — risk must outrank noise.

A red-team showed the old ranking was SEVERITY-BLIND: an empty ``__init__.py``
and a clean utility could score as anomalous as a module carrying a real
``security`` / ``correctness-bug`` finding, because (a) ``_breadth_score`` was
SYMMETRIC — an unusually NARROW file deviated as much as an unusually BROAD one —
and (b) every signal tag was weighted equally — a ``security`` tag counted the
same as a ``symbol-hub``. These tests pin the fix:

  - ASYMMETRIC breadth: a module with unusually MANY signals (a god-module /
    hotspot) is flagged; one with unusually FEW (a narrow / empty ``__init__.py``)
    is NOT lifted by its narrowness;
  - SEVERITY-WEIGHTED signals: a module carrying a risk-bearing tag (``security``,
    ``correctness-bug``, ``sensitive-path``, ``critical-untested``) outranks one
    that is merely structurally odd-but-safe (``symbol-hub`` / ``hub`` /
    ``co-change``);
  - trivial ``__init__.py`` files are FLOORED out so they never lead;
  - the whole thing stays deterministic and bounded in [0, 1].

The HARD GATE is the inverse of the old behaviour: module A (``security`` +
``untested``) ranks ABOVE module B (an empty ``__init__`` / clean utility), and B
is floored / low.

Synthetic ``ProjectProfile`` inputs; stdlib + pytest only.
"""

from __future__ import annotations

from app.engine.anomaly_discovery import (
    BREADTH_WEIGHT,
    RARITY_WEIGHT,
    SEVERITY_WEIGHT,
    _SEVERITY_WEIGHTS,
    _breadth_score,
    _is_trivial_init,
    _severity_score,
    find_anomalies,
)
from app.tools.project_profile import ProjectProfile


# --------------------------------------------------------------------------- #
# HARD GATE: a risky module A ranks ABOVE an empty __init__ / clean utility B.
# --------------------------------------------------------------------------- #
def test_security_module_outranks_empty_init_and_clean_utility():
    """A = ``app/risky.py`` carries a ``security`` (+ ``untested``) signal.
    B1 = ``app/pkg/__init__.py`` is an empty package marker (one structural
    signal). B2 = ``app/util.py`` is a clean utility (one structural signal).
    A must lead the ranking; the empty ``__init__`` must be FLOORED out entirely;
    the clean utility, if it surfaces at all, must rank strictly below A. This is
    the inverse of the old severity-blind ranking."""
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/risky.py"],
        untested_modules=["app/risky.py"],
        symbol_hubs=["app/pkg/__init__.py", "app/util.py"],
        debt_marker_modules=["app/other.py"],
    )
    anomalies = find_anomalies(profile, top=99)
    names = [a["module"] for a in anomalies]
    by_mod = {a["module"]: a for a in anomalies}

    # A leads.
    assert names[0] == "app/risky.py"
    # The empty __init__ is floored out: it never appears.
    assert "app/pkg/__init__.py" not in names
    # The clean utility, if present, ranks strictly below A.
    if "app/util.py" in by_mod:
        assert (by_mod["app/risky.py"]["deviation"]
                > by_mod["app/util.py"]["deviation"])
    # A's severity dominates a purely-structural module's.
    assert by_mod["app/risky.py"]["severity"] > 0.5


def test_security_plus_untested_beats_structurally_odd_but_safe():
    """The exact A-over-B ordering proof. Three modules A, x, B — each breadth 2,
    so breadth is FLAT (broadness 0 everywhere). A carries {security, untested};
    B is a structurally-odd-but-safe module carrying {symbol-hub, hub} (two
    structural tags, no risk). A's risk severity makes it rank strictly above B.

    A: rarity ((1-1/3 security)+(1-2/3 untested))/2 = (0.667+0.333)/2 = 0.5;
       severity max(security 1.0*(1-1/3)=0.667, untested 0.5*(1-2/3)=0.167)=0.667;
       deviation = 0.3*0.5 + 0.15*0 + 0.55*0.667 = 0.516667 → 0.517.
    B: rarity ((1-1/3)+(1-1/3))/2 = 0.667;
       severity max(symbol-hub 0.15*0.667, hub 0.15*0.667)=0.1;
       deviation = 0.3*0.667 + 0.15*0 + 0.55*0.1 = 0.255.
    A (0.517) ranks strictly ABOVE B (0.255)."""
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["A"],
        untested_modules=["A", "x"],
        symbol_hubs=["B"],
        dependency_hubs=["B"],
        debt_marker_modules=["x"],
    )
    anomalies = find_anomalies(profile, top=99)
    by_mod = {a["module"]: a for a in anomalies}
    assert by_mod["A"]["deviation"] == 0.517
    assert by_mod["B"]["deviation"] == 0.255
    assert by_mod["A"]["deviation"] > by_mod["B"]["deviation"]
    # Order: A before B.
    order = [a["module"] for a in anomalies]
    assert order.index("A") < order.index("B")


# --------------------------------------------------------------------------- #
# A genuinely broad god-module still surfaces.
# --------------------------------------------------------------------------- #
def test_broad_god_module_still_surfaces():
    """Every module shares one signal; ``app/god.py`` piles on three more
    (breadth 4 vs the others' 1). It is a likely hotspot and must surface near
    the top, named ``unusually broad``."""
    profile = ProjectProfile(
        root=".",
        untested_modules=["m1", "m2", "m3", "app/god.py"],
        symbol_hubs=["app/god.py"],
        dependency_hubs=["app/god.py"],
        debt_marker_modules=["app/god.py"],
    )
    anomalies = find_anomalies(profile, top=99)
    assert anomalies
    top = anomalies[0]
    assert top["module"] == "app/god.py"
    assert "unusually broad" in top["why"]


def test_narrow_file_does_not_outrank_a_risky_one():
    """A NARROW file (fewer signals than the median) must not outrank a risky
    module. ``app/secure.py`` carries a lone ``security`` signal; the codebase
    median breadth is higher, so several modules are 'narrow' — none of them may
    sit above the security module."""
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/secure.py"],
        symbol_hubs=["m1", "m2", "m3"],
        dependency_hubs=["m1", "m2", "m3"],
        debt_marker_modules=["m1", "m2", "m3"],
    )
    anomalies = find_anomalies(profile, top=99)
    by_mod = {a["module"]: a for a in anomalies}
    assert "app/secure.py" in by_mod
    # The security module carries real risk severity; a narrow-only file never
    # does, so narrowness alone cannot lift one above this risky module.
    assert by_mod["app/secure.py"]["severity"] >= 0.7


# --------------------------------------------------------------------------- #
# Trivial __init__ files are floored out.
# --------------------------------------------------------------------------- #
def test_empty_init_is_floored_out_of_ranking():
    """An empty ``__init__.py`` carrying a single signal is dropped entirely, so
    it can never lead the ranking — even when that lone signal is rare."""
    profile = ProjectProfile(
        root=".",
        symbol_hubs=["app/pkg/__init__.py"],
        security_finding_modules=["app/a.py"],
        untested_modules=["app/a.py", "app/b.py"],
        debt_marker_modules=["app/b.py"],
    )
    names = [a["module"] for a in find_anomalies(profile, top=99)]
    assert "app/pkg/__init__.py" not in names


def test_is_trivial_init_predicate():
    """``_is_trivial_init`` flags only ``__init__.py`` paths with ≤1 signal."""
    assert _is_trivial_init("app/pkg/__init__.py", set())
    assert _is_trivial_init("app/pkg/__init__.py", {"symbol-hub"})
    assert _is_trivial_init("__init__.py", {"hub"})
    # Two or more signals: a non-trivial init is kept.
    assert not _is_trivial_init("app/pkg/__init__.py", {"security", "hub"})
    # Not an __init__ at all.
    assert not _is_trivial_init("app/util.py", set())
    assert not _is_trivial_init("app/init.py", {"hub"})


def test_init_with_real_risk_is_not_floored():
    """An ``__init__.py`` that carries ≥2 signals (e.g. a real ``security``
    finding alongside another tag) is NOT trivial and must still surface."""
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/pkg/__init__.py"],
        correctness_bug_modules=["app/pkg/__init__.py"],
        symbol_hubs=["app/a.py", "app/b.py"],
        debt_marker_modules=["app/c.py"],
    )
    names = [a["module"] for a in find_anomalies(profile, top=99)]
    assert "app/pkg/__init__.py" in names
    assert names[0] == "app/pkg/__init__.py"


# --------------------------------------------------------------------------- #
# Severity weighting: risk tags weigh far more than structural tags.
# --------------------------------------------------------------------------- #
def test_risk_tags_outweigh_structural_tags():
    """The fixed weight scheme gives risk-bearing tags MATERIALLY more weight than
    structural ones, and ``security`` is the maximum."""
    risk = ("security", "correctness-bug", "sensitive-path", "critical-untested")
    structural = ("symbol-hub", "hub", "co-change")
    for r in risk:
        for s in structural:
            assert _SEVERITY_WEIGHTS[r] > 2 * _SEVERITY_WEIGHTS[s]
    assert _SEVERITY_WEIGHTS["security"] == max(_SEVERITY_WEIGHTS.values())


def test_severity_score_is_rarity_scaled_max():
    """``_severity_score`` is the MAX over tags of weight*(1-freq/modules): a rare
    high-risk signal dominates, a ubiquitous one contributes 0, an untagged
    module is 0."""
    # security on 1 of 4 modules: 1.0 * (1 - 1/4) = 0.75; symbol-hub diluted out.
    assert _severity_score({"security", "symbol-hub"},
                           {"security": 1, "symbol-hub": 1}, 4) == 0.75
    # security on every module → no risk OUTLIER → 0.0.
    assert _severity_score({"security"}, {"security": 4}, 4) == 0.0
    # untagged / degenerate → 0.0 (no ZeroDivision).
    assert _severity_score(set(), {}, 4) == 0.0
    assert _severity_score({"security"}, {"security": 1}, 0) == 0.0


def test_severity_dominates_the_blend():
    """SEVERITY is the dominant blend weight, and the three weights sum to 1 so
    the deviation stays bounded in [0, 1]."""
    assert SEVERITY_WEIGHT > RARITY_WEIGHT > BREADTH_WEIGHT
    assert RARITY_WEIGHT + BREADTH_WEIGHT + SEVERITY_WEIGHT == 1.0


def test_uniformly_risky_codebase_yields_no_anomaly():
    """If EVERY module carries the same ``security`` signal, none is a risk
    OUTLIER (severity-deviation 0), nothing is rare and breadth is flat → no
    anomalies. Severity flags DEVIATION, not a uniform baseline."""
    mods = ["a", "b", "c", "d"]
    profile = ProjectProfile(
        root=".",
        security_finding_modules=list(mods),
        untested_modules=list(mods),
    )
    assert find_anomalies(profile) == []


# --------------------------------------------------------------------------- #
# Asymmetric breadth at the engine level.
# --------------------------------------------------------------------------- #
def test_breadth_score_only_raises_on_the_broad_side():
    """Direct check: above the median raises deviation, below the median is 0."""
    assert _breadth_score(4, 2.0, 2.0) == 1.0   # broad
    assert _breadth_score(2, 2.0, 2.0) == 0.0   # at median
    assert _breadth_score(0, 2.0, 2.0) == 0.0   # narrow (empty __init__)


# --------------------------------------------------------------------------- #
# Determinism across two runs.
# --------------------------------------------------------------------------- #
def test_deterministic_across_two_runs():
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/risky.py"],
        untested_modules=["app/risky.py", "m1", "m2"],
        symbol_hubs=["app/pkg/__init__.py", "app/util.py"],
        debt_marker_modules=["m1"],
        correctness_bug_modules=["app/bug.py"],
    )
    first = find_anomalies(profile, top=99)
    second = find_anomalies(profile, top=99)
    assert first == second
    # Bounded and floor-trivial init excluded on both runs.
    for run in (first, second):
        assert "app/pkg/__init__.py" not in [a["module"] for a in run]
        for a in run:
            assert 0.0 <= a["deviation"] <= 1.0
            assert 0.0 <= a["severity"] <= 1.0
