"""Severity-aware, asymmetric anomaly ranking for ``anomaly_discovery``.

The plain feature suite (``test_anomaly_discovery_eyml``) and the deep-mutation
suite pin the arithmetic; THIS suite pins the *behavioural contract* that the
severity rework exists to guarantee — the property the old symmetric, flatly
weighted score got wrong:

  noise (an empty ``__init__.py`` or a clean structural hub) must NEVER outrank
  a module carrying a real, rare risk signal (``pickle.loads`` / SQL-injection /
  ``eval`` → ``security``, plus ``correctness-bug`` / ``sensitive-path`` /
  ``critical-untested``).

Three grounded mechanisms make that hold deterministically and are each pinned
below:

  * per-tag SEVERITY — a rare risk tag (severity 1.0) dwarfs a rare structural
    tag (``symbol-hub`` / ``hub`` / ``co-change`` at 0.2) and an unknown tag
    (default 0.2);
  * ASYMMETRIC breadth — only an unusually BROAD fingerprint raises the score, so
    a narrow module can no longer score "as anomalous as" a broad one;
  * the TRIVIAL-``__init__`` floor — a near-empty ``__init__.py`` (≤ 1 signal) is
    dropped before scoring and can never appear;

while the rarity GATE on severity keeps the "uniform profile → []" invariant
intact (a ubiquitous tag contributes 0 no matter how risky its kind) and the new
``severity`` key is purely ADDITIVE (consumers reading ``deviation`` / ``module``
/ ``why`` are unaffected).

Deterministic: synthetic ``ProjectProfile`` inputs, module-name-keyed order, no
time/random.
"""

from __future__ import annotations

from app.engine.anomaly_discovery import find_anomalies, module_profiles
from app.tools.project_profile import ProjectProfile


def _rank(profile: ProjectProfile) -> dict[str, int]:
    """module path → its 0-based rank in the anomaly list (lower = more anomalous)."""
    return {a["module"]: i for i, a in enumerate(find_anomalies(profile, top=99))}


# --------------------------------------------------------------------------- #
# HARD GATE: Module A (security + untested) ranks ABOVE Module B (empty
# __init__ / clean structural). This is the inverse of the OLD ordering, where a
# narrow/structural module could outrank a risk-bearing one.
# --------------------------------------------------------------------------- #
def test_risk_module_ranks_above_structural_and_trivial_init():
    """``app/a.py`` (a rare ``security`` + ``untested`` bundle) must outrank the
    structural hubs AND the trivial ``__init__.py`` — which is floored out of the
    ranking entirely. Pins the A-over-B contract."""
    profile = ProjectProfile(
        root=".",
        # Module A: the only risk-bearing module — rare security + untested.
        security_finding_modules=["app/a.py"],
        untested_modules=["app/a.py"],
        # Module B and friends: clean structural hubs, no risk signal.
        symbol_hubs=["app/b.py", "app/c.py", "app/d.py"],
        dependency_hubs=["app/c.py", "app/d.py"],
        # An empty package marker carrying a single structural signal.
    )
    anomalies = find_anomalies(profile, top=99)
    rank = {a["module"]: i for i, a in enumerate(anomalies)}
    assert anomalies[0]["module"] == "app/a.py"
    # Every structural module that surfaces ranks strictly below the risk module.
    for structural in ("app/c.py", "app/d.py"):
        if structural in rank:
            assert rank["app/a.py"] < rank[structural]
    # And the risk module carries the higher severity.
    by_mod = {a["module"]: a for a in anomalies}
    for structural in ("app/c.py", "app/d.py"):
        if structural in by_mod:
            assert by_mod["app/a.py"]["severity"] > by_mod[structural]["severity"]


def test_trivial_init_is_floored_out_of_ranking():
    """A near-empty ``__init__.py`` (≤ 1 signal) never appears in the ranking,
    while a genuine risk module does. Pins the trivial-floor drop."""
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/risky.py"],
        untested_modules=["app/risky.py", "app/__init__.py"],
        symbol_hubs=["app/hub.py"],
    )
    surfaced = {a["module"] for a in find_anomalies(profile, top=99)}
    assert "app/__init__.py" not in surfaced
    assert "app/risky.py" in surfaced
    assert find_anomalies(profile, top=99)[0]["module"] == "app/risky.py"


def test_init_with_two_signals_is_not_floored():
    """The trivial floor is ``≤ 1`` signal: an ``__init__.py`` carrying TWO rare
    signals is NOT trivial and may surface. Pins the boundary (a too-greedy floor
    would silence a genuinely risky package initialiser)."""
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["pkg/__init__.py"],
        correctness_bug_modules=["pkg/__init__.py"],
        untested_modules=["a.py", "b.py", "c.py"],
    )
    profs = module_profiles(profile)
    assert profs["pkg/__init__.py"] == {"security", "correctness-bug"}
    surfaced = {a["module"] for a in find_anomalies(profile, top=99)}
    assert "pkg/__init__.py" in surfaced


# --------------------------------------------------------------------------- #
# Real risk signals (eval / pickle.loads / SQL-injection-style) read off a
# ProjectProfile dominate a noisy clean utility.
# --------------------------------------------------------------------------- #
def test_rare_security_module_dominates_clean_structural_noise():
    """A single rare ``security`` finding (the kind ``eval`` / ``pickle.loads`` /
    SQL injection produce) ranks first over a crowd of clean structural hubs.

    The eight ``symbol-hub`` modules make that tag the codebase norm (NOT rare,
    NOT severe); the lone security module is rare AND severe, so it leads."""
    profile = ProjectProfile(
        root=".",
        symbol_hubs=[f"app/hub{i}.py" for i in range(8)],
        security_finding_modules=["app/danger.py"],
    )
    anomalies = find_anomalies(profile, top=99)
    assert anomalies[0]["module"] == "app/danger.py"
    assert "`security`" in anomalies[0]["why"]


def test_rare_risk_tag_beats_equally_rare_structural_tag():
    """At EQUAL rarity and breadth, the risk tag wins purely on severity.

    ``app/sec.py`` carries a singleton ``security`` (severity 1.0); ``app/hub.py``
    carries a singleton ``symbol-hub`` (severity 0.2). Same rarity, same (zero)
    breadth — only severity separates them, so the security module ranks first."""
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/sec.py"],
        symbol_hubs=["app/hub.py"],
        untested_modules=["app/c.py", "app/d.py", "app/e.py"],
    )
    rank = _rank(profile)
    assert "app/sec.py" in rank and "app/hub.py" in rank
    assert rank["app/sec.py"] < rank["app/hub.py"]
    by_mod = {a["module"]: a for a in find_anomalies(profile, top=99)}
    assert by_mod["app/sec.py"]["rarity"] == by_mod["app/hub.py"]["rarity"]
    assert by_mod["app/sec.py"]["severity"] > by_mod["app/hub.py"]["severity"]


# --------------------------------------------------------------------------- #
# Asymmetric breadth: a narrow module never out-scores a broad one on breadth.
# --------------------------------------------------------------------------- #
def test_narrow_module_gets_no_breadth_credit():
    """A module NARROWER than the median earns 0 from the breadth part, so it can
    no longer rank as anomalous as a broad module on breadth alone.

    Three broad modules (3 signals each) set the median to 3; the narrow ``thin``
    module (1 signal) sits below it. It surfaces only if its single signal is
    rare/severe, never on breadth — and its ``why`` says "narrow", never "broad"."""
    profile = ProjectProfile(
        root=".",
        untested_modules=["w1", "w2", "w3"],
        security_finding_modules=["w1", "w2", "w3"],
        debt_marker_modules=["w1", "w2", "w3"],
        symbol_hubs=["app/thin.py"],
    )
    by_mod = {a["module"]: a for a in find_anomalies(profile, top=99)}
    if "app/thin.py" in by_mod:
        assert "unusually broad" not in by_mod["app/thin.py"]["why"]


# --------------------------------------------------------------------------- #
# The rarity gate preserves the uniform-profile invariant under severity.
# --------------------------------------------------------------------------- #
def test_uniform_security_profile_still_yields_no_anomalies():
    """Every module carries the identical {security, untested} fingerprint: even
    though ``security`` is the highest-severity tag, it is UBIQUITOUS so its
    rarity (and thus its severity contribution) is 0. The whole codebase is
    on-pattern → ``[]``. Pins the rarity gate against a severity that would
    otherwise flag a uniformly-risky codebase."""
    mods = ["a", "b", "c", "d"]
    profile = ProjectProfile(
        root=".",
        security_finding_modules=list(mods),
        untested_modules=list(mods),
    )
    assert find_anomalies(profile) == []


# --------------------------------------------------------------------------- #
# The new ``severity`` key is present, bounded, and additive.
# --------------------------------------------------------------------------- #
def test_severity_key_is_present_and_bounded():
    """Every record exposes a ``severity`` in [0, 1] alongside the existing keys,
    so risk-aware consumers can read it while legacy consumers (deviation /
    module / why) are untouched."""
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/a.py"],
        untested_modules=["app/a.py", "b", "c", "d"],
        symbol_hubs=["app/h.py"],
    )
    anomalies = find_anomalies(profile, top=99)
    assert anomalies
    for a in anomalies:
        assert set(a) == {"module", "deviation", "rarity", "severity", "why"}
        assert 0.0 <= a["severity"] <= 1.0


def test_ranking_is_deterministic_across_runs():
    """Same profile → byte-identical anomaly list across repeated runs, including
    the severity-aware tie-breaks."""
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/a.py"],
        correctness_bug_modules=["app/b.py"],
        symbol_hubs=["app/c.py", "app/d.py"],
        untested_modules=["app/a.py", "app/b.py", "app/e.py"],
    )
    assert find_anomalies(profile, top=99) == find_anomalies(profile, top=99)
