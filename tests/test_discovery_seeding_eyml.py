"""Opt-in discovery-lead seeding for IdeaSeeder.

The fused cross-engine DISCOVERY leads (``discovery_synthesis.synthesize_
discoveries``) are read-only; this surface lets them reach the idea engine as
OPT-IN, recommend-only roots that NEVER displace the existing budgeted seeds.

Hard gates pinned here:

  - default OFF is byte-identical (the seeded root set is unchanged);
  - flag ON is a strict SUPERSET (every OFF root still appears, same order),
    plus the capped discovery roots;
  - discovery roots carry a ``::discovery-<kind>`` subject suffix and a
    ``discovery-<kind>`` fact_label the bridge routes to a recommend-only
    ``design_task`` (never executable);
  - best-effort: a raising/empty synthesis leaves seeding unchanged;
  - the appended set is deterministic and capped.

Determinism: assertions are on exact content (string equality, sorted
membership, counts); no clock / random / set-iteration order.
"""
from __future__ import annotations

from app.engine.idea_action_bridge import _FACT_ACTIONS
from app.engine.idea_seeder import IdeaSeeder
from app.tools.project_profile import ProjectProfile


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


# A representative profile that fires several budgeted families at once, so the
# byte-identical / superset gates are exercised against a non-trivial root set.
def _rich_profile() -> ProjectProfile:
    return _profile(
        dependency_hubs=["app/a.py", "app/b.py"],
        sensitive_paths=["app/auth.py"],
        critical_untested_modules=["app/pay.py"],
        entrypoints=["app/main.py"],
        churn_hotspots=[{"module": "app/a.py", "commits": 9}],
        ci_files=["ci.yml"],
    )


_LEADS = [
    {"kind": "anomaly", "subject": "app/odd.py", "score": 0.9,
     "source": "anomaly_discovery", "evidence": "off-pattern fingerprint.",
     "corroborated_by": 2},
    {"kind": "emerging-hotspot", "subject": "app/hot.py", "score": 0.7,
     "source": "temporal_discovery", "evidence": "change-rate accelerating.",
     "corroborated_by": 1},
    {"kind": "candidate-rule", "subject": "shape-x", "score": 0.5,
     "source": "rule_synthesis", "evidence": "structural shape recurs.",
     "corroborated_by": 1},
    {"kind": "spreading-pair", "subject": "app/p.py | app/q.py", "score": 0.3,
     "source": "temporal_discovery", "evidence": "coupling tightening.",
     "corroborated_by": 1},
]


def _patch_leads(monkeypatch, leads):
    # The seeder imports the symbol lazily inside the method, so patching the
    # SOURCE module is what the late ``from ... import synthesize_discoveries``
    # resolves to.
    import app.engine.discovery_synthesis as ds
    monkeypatch.setattr(ds, "synthesize_discoveries",
                        lambda *a, **k: list(leads))


# --------------------------------------------------------------------------
# Gate 1: default OFF is byte-identical.
# --------------------------------------------------------------------------
def test_default_off_is_byte_identical():
    profile = _rich_profile()
    # Two seeders, same fixed profile, flag absent vs explicitly False.
    baseline = [r.model_dump() for r in IdeaSeeder("/repo").seed(profile)]
    explicit_off = [
        r.model_dump()
        for r in IdeaSeeder("/repo").seed(profile, seed_discoveries=False)
    ]
    assert baseline == explicit_off


def test_default_off_unaffected_even_if_synthesis_would_fire(monkeypatch):
    # Even with discovery leads available, OFF must not append anything.
    _patch_leads(monkeypatch, _LEADS)
    profile = _rich_profile()
    off = IdeaSeeder("/repo").seed(profile, seed_discoveries=False)
    assert not any("::discovery-" in r.subject for r in off)


# --------------------------------------------------------------------------
# Gate 2: flag ON is a strict superset (no displacement) + capped extras.
# --------------------------------------------------------------------------
def test_on_is_superset_no_displacement(monkeypatch):
    _patch_leads(monkeypatch, _LEADS)
    profile = _rich_profile()
    off = IdeaSeeder("/repo").seed(profile, seed_discoveries=False)
    on = IdeaSeeder("/repo").seed(profile, seed_discoveries=True)

    off_dumps = [r.model_dump() for r in off]
    on_dumps = [r.model_dump() for r in on]

    # Every pre-existing root still appears, in the SAME order, as a prefix —
    # discovery roots are appended strictly AFTER the budgeted set.
    assert on_dumps[: len(off_dumps)] == off_dumps
    # And ON has strictly more roots (the appended discovery leads).
    assert len(on) > len(off)


def test_on_appends_capped_discovery_roots(monkeypatch):
    _patch_leads(monkeypatch, _LEADS)  # 4 leads, cap is 3
    profile = _rich_profile()
    on = IdeaSeeder("/repo").seed(profile, seed_discoveries=True)
    disc = [r for r in on if "::discovery-" in r.subject]
    assert len(disc) == IdeaSeeder._DISCOVERY_CAP == 3
    # Deterministic top-N by (-score, kind, subject): the 0.3 spreading-pair
    # is dropped (lowest score), the top three are kept.
    assert {r.subject for r in disc} == {
        "app/odd.py::discovery-anomaly",
        "app/hot.py::discovery-emerging-hotspot",
        "shape-x::discovery-candidate-rule",
    }


# --------------------------------------------------------------------------
# Gate 3: discovery roots are recommend-only + carry the suffix/fact_label.
# --------------------------------------------------------------------------
def test_discovery_roots_carry_suffix_and_recommend_only_fact(monkeypatch):
    _patch_leads(monkeypatch, _LEADS)
    profile = _rich_profile()
    on = IdeaSeeder("/repo").seed(profile, seed_discoveries=True)
    disc = [r for r in on if "::discovery-" in r.subject]
    assert disc, "expected appended discovery roots"
    for r in disc:
        # Subject suffix never collides with a bare module subject.
        assert "::discovery-" in r.subject
        # Fact label is discovery-<kind>; it is NOT an executable fact (the
        # bridge has no _FACT_ACTIONS entry, so it falls back to recommend-only
        # design_task) — assert it is absent from the executable mapping.
        label = r.source_facts[0].split(":")[0].strip()
        assert label.startswith("discovery-")
        assert label not in _FACT_ACTIONS
        # The fact value never carries the auto-promote token "untested".
        assert "untested" not in r.source_facts[0]
    # The label routes to a recommend-only design_task via the bridge fallback.
    from app.engine.idea_action_bridge import IdeaActionBridge
    for r in disc:
        action_type, _tmpl, executable = IdeaActionBridge._root_action(r)
        assert action_type == "design_task"
        assert executable is False


def test_discovery_subjects_never_collide_with_module_subjects(monkeypatch):
    # A discovery lead naming an already-seeded module must stay distinct.
    leads = [{
        "kind": "anomaly", "subject": "app/a.py", "score": 0.9,
        "source": "anomaly_discovery", "evidence": "x.", "corroborated_by": 1,
    }]
    _patch_leads(monkeypatch, leads)
    profile = _rich_profile()  # app/a.py is already a dependency hub
    on = IdeaSeeder("/repo").seed(profile, seed_discoveries=True)
    subjects = [r.subject for r in on]
    assert "app/a.py" in subjects                      # the budgeted hub root
    assert "app/a.py::discovery-anomaly" in subjects   # the distinct lead
    assert subjects.count("app/a.py") == 1             # not deduped/displaced


# --------------------------------------------------------------------------
# Best-effort + edge paths.
# --------------------------------------------------------------------------
def test_empty_synthesis_leaves_seeding_unchanged(monkeypatch):
    _patch_leads(monkeypatch, [])
    profile = _rich_profile()
    off = [r.model_dump() for r in IdeaSeeder("/repo").seed(profile)]
    on = [
        r.model_dump()
        for r in IdeaSeeder("/repo").seed(profile, seed_discoveries=True)
    ]
    assert off == on


def test_raising_synthesis_leaves_seeding_unchanged(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("discovery engine failure")

    import app.engine.discovery_synthesis as ds
    monkeypatch.setattr(ds, "synthesize_discoveries", _boom)
    profile = _rich_profile()
    off = [r.model_dump() for r in IdeaSeeder("/repo").seed(profile)]
    on = [
        r.model_dump()
        for r in IdeaSeeder("/repo").seed(profile, seed_discoveries=True)
    ]
    assert off == on


def test_no_project_root_skips_discovery_seeding(monkeypatch):
    # A bare seeder (no project_root) and a profile with no root cannot resolve
    # a discovery scan target, so the opt-in path is a no-op even when ON.
    _patch_leads(monkeypatch, _LEADS)
    profile = ProjectProfile(root="")
    on = IdeaSeeder("").seed(profile, seed_discoveries=True)
    assert not any("::discovery-" in r.subject for r in on)


def test_discovery_seeding_is_deterministic(monkeypatch):
    _patch_leads(monkeypatch, _LEADS)
    profile = _rich_profile()
    a = [r.model_dump() for r in IdeaSeeder("/repo").seed(profile, seed_discoveries=True)]
    b = [r.model_dump() for r in IdeaSeeder("/repo").seed(profile, seed_discoveries=True)]
    assert a == b
