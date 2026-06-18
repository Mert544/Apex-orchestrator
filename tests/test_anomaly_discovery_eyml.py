"""Feature tests for ``app/engine/anomaly_discovery.py``.

Anomaly discovery is the inverse of dream discovery: it surfaces the modules
whose signal fingerprint DEVIATES most from the codebase's deterministic
"normal". These tests pin: a clearly-deviant module ranks first with the right
``why``; a uniform codebase yields nothing; deviation is bounded in [0, 1];
results are deterministic; an empty (or too-small) profile yields ``[]`` and
never raises.

Synthetic ``ProjectProfile`` inputs; stdlib + pytest only.
"""

from __future__ import annotations

from app.engine.anomaly_discovery import (
    DEVIATION_FLOOR,
    MIN_MODULES,
    dominant_pattern,
    find_anomalies,
    module_profiles,
)
from app.tools.project_profile import ProjectProfile


# --------------------------------------------------------------------------- #
# A clearly-deviant module ranks first with the right "why".
# --------------------------------------------------------------------------- #
def test_rare_signal_module_ranks_first():
    # Four modules share the "normal" {security, untested}. One module, app/odd.py,
    # is the sole carrier of a rare bundle {mutable-defaults, symbol-hub, debt} and
    # carries none of the typical signals → it must be the top anomaly.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["app/a.py", "app/b.py", "app/c.py", "app/d.py"],
        untested_modules=["app/a.py", "app/b.py", "app/c.py", "app/d.py"],
        mutable_default_modules=["app/odd.py"],
        symbol_hubs=["app/odd.py"],
        debt_marker_modules=["app/odd.py"],
    )
    anomalies = find_anomalies(profile)
    assert anomalies, "a clearly-deviant module must surface"
    top = anomalies[0]
    assert top["module"] == "app/odd.py"
    assert "rare signal(s)" in top["why"]
    # The rare tags are named and the typical signals it lacks are flagged.
    assert "`debt`" in top["why"] and "`mutable-defaults`" in top["why"]
    assert "lacks the typical signal(s)" in top["why"]


def test_unusually_broad_module_is_flagged_for_breadth():
    # Every module carries one shared signal; app/wide.py also piles on three more.
    # Its breadth deviates from the median → "unusually broad" appears in why.
    profile = ProjectProfile(
        root=".",
        untested_modules=["m1", "m2", "m3", "app/wide.py"],
        security_finding_modules=["app/wide.py"],
        fragile_modules=["app/wide.py"],
        debt_marker_modules=["app/wide.py"],
    )
    anomalies = find_anomalies(profile)
    assert anomalies
    top = anomalies[0]
    assert top["module"] == "app/wide.py"
    assert "unusually broad" in top["why"]


# --------------------------------------------------------------------------- #
# A uniform codebase has nothing rare and no breadth spread → no anomalies.
# --------------------------------------------------------------------------- #
def test_uniform_profile_yields_no_anomalies():
    # Every module carries the identical fingerprint {security, untested}: nothing
    # is rare, every breadth equals the median → deviation 0 everywhere.
    mods = ["a", "b", "c", "d"]
    profile = ProjectProfile(
        root=".",
        security_finding_modules=list(mods),
        untested_modules=list(mods),
    )
    assert find_anomalies(profile) == []


# --------------------------------------------------------------------------- #
# Empty / too-small profiles → [] and never raise.
# --------------------------------------------------------------------------- #
def test_empty_profile_is_empty():
    assert find_anomalies(ProjectProfile(root=".")) == []
    assert module_profiles(ProjectProfile(root=".")) == {}


def test_below_min_modules_is_empty():
    # Two tagged modules is below MIN_MODULES: "rare" is meaningless, so abstain.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a"],
        debt_marker_modules=["b"],
    )
    assert MIN_MODULES == 3
    assert len(module_profiles(profile)) < MIN_MODULES
    assert find_anomalies(profile) == []


def test_non_positive_top_is_empty():
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b", "c", "d"],
        untested_modules=["a", "b", "c", "d"],
        debt_marker_modules=["app/odd.py"],
    )
    assert find_anomalies(profile, top=0) == []
    assert find_anomalies(profile, top=-1) == []


# --------------------------------------------------------------------------- #
# Bounded deviation in [0, 1] and bounded result length.
# --------------------------------------------------------------------------- #
def test_deviation_is_bounded_and_result_capped():
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b", "c"],
        untested_modules=["a", "b"],
        fragile_modules=["x1"],
        debt_marker_modules=["x2"],
        modernizable_modules=["x3"],
        symbol_hubs=["x4"],
        mutable_default_modules=["x5"],
        sensitive_paths=["x6"],
        hotspot_modules=["x7"],
    )
    anomalies = find_anomalies(profile, top=2)
    assert len(anomalies) <= 2
    for a in find_anomalies(profile, top=99):
        assert 0.0 <= a["deviation"] <= 1.0
        assert 0.0 <= a["rarity"] <= 1.0
        assert a["deviation"] >= DEVIATION_FLOOR


# --------------------------------------------------------------------------- #
# Deterministic: same profile → identical result (incl. stable ordering).
# --------------------------------------------------------------------------- #
def test_deterministic_repeated_runs_identical():
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b", "c", "d"],
        untested_modules=["a", "b", "c"],
        debt_marker_modules=["app/p.py", "app/q.py"],
        fragile_modules=["app/p.py"],
        symbol_hubs=["app/q.py"],
    )
    first = find_anomalies(profile)
    second = find_anomalies(profile)
    assert first == second
    keys = [a["module"] for a in first]
    assert keys == sorted(
        keys,
        key=lambda m: (-dict((a["module"], a["deviation"]) for a in first)[m], m),
    )


# --------------------------------------------------------------------------- #
# dominant_pattern reports the "normal": frequency, median, typical fingerprint.
# --------------------------------------------------------------------------- #
def test_dominant_pattern_reports_the_norm():
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b", "c"],
        untested_modules=["a", "b", "c"],
        debt_marker_modules=["a"],
    )
    norm = dominant_pattern(module_profiles(profile))
    assert norm["modules"] == 3
    assert norm["frequency"]["security"] == 3
    assert norm["frequency"]["debt"] == 1
    # security & untested are on a strict majority → typical; debt is not.
    assert norm["typical"] == {"security", "untested"}
    assert norm["median_breadth"] == 2.0


def test_dominant_pattern_empty_is_safe():
    norm = dominant_pattern({})
    assert norm == {"modules": 0, "frequency": {}, "median_breadth": 0.0,
                    "typical": set()}
