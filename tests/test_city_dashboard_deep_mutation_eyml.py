"""Deep-mutation hardening for ``app.reporting.city_dashboard``.

Characterization tests that kill mutation survivors the default 30-mutant cap
masks. The full site universe (101 single-token mutants, enumerated with
``mutation_tester._collect_sites``) was spliced one-by-one against the three
covering test files; 55 survived. The tests below pin the deterministic
behaviour of the surviving sites so the equivalent-or-real distinction is
documented and the real ones are caught.

These are pure-function characterizations: every helper under test
(``_findings_by_file``, ``_fan_in``, ``_coordinator_signals``, ``_rank_modules``,
``_building``, ``_workers``, ``_totals``) takes plain data, so the assertions are
fully deterministic (no timestamps, no set/dict-ordering reliance).

EQUIVALENT mutants (documented, NOT killed — they cannot change observable
behaviour, so no test can distinguish them):

* L105-L108 ``1 if m in <set> else 0`` -> ``2 if m in <set> else 0`` (the
  ``number:1>2`` mutants in the ``_rank`` tuple for fragile / hub / coordinator /
  untested). The rank tuple is compared lexicographically by POSITION, so within
  a tier the magnitude is irrelevant: any value ``> 0`` keeps a member ahead of a
  non-member, and ``1`` vs ``2`` never changes the ordering relative to the OTHER
  tiers (which occupy different tuple positions). These four are genuinely
  equivalent and unkillable; the membership tests and the ``else 0`` boundaries
  at the same sites ARE killable and are covered by
  ``test_rank_orders_by_signal_tier_priority``.
"""

from __future__ import annotations

import types

import app.agents.skills as skills

from app.reporting.city_dashboard import (
    _building,
    _coordinator_signals,
    _fan_in,
    _findings_by_file,
    _rank_modules,
    _totals,
    _workers,
    build_city_model,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _metric(loc: int = 1, complexity: int = 1):
    return types.SimpleNamespace(loc=loc, complexity=complexity)


def _bld(name: str, **kw):
    base = {
        "name": name,
        "findings": 0,
        "health": "ok",
        "fan_in": 0,
        "tests": 1,
        "complexity": 1,
        "coordinator": False,
        "loc": 1,
    }
    base.update(kw)
    return base


class _FakeProfile:
    def __init__(self, **kw):
        self.module_to_tests = kw.get("module_to_tests", {})
        self.dependency_hubs = kw.get("dependency_hubs", [])
        self.fragile_modules = kw.get("fragile_modules", [])
        self.untested_modules = kw.get("untested_modules", [])
        self.dependency_edges = kw.get("dependency_edges", [])
        self.coordinator_modules = kw.get("coordinator_modules", [])


class _FakeCodeMetrics:
    def __init__(self, project_root):
        pass

    def for_modules(self, modules):
        return {m: _metric() for m in modules}


class _NoFindings:
    def run(self, project_root):
        return {"findings": []}


def _patch_build(monkeypatch, profile, *, sec=None, grade=None):
    import app.engine.health_score as hs
    import app.tools.code_metrics as cm
    import app.tools.project_profile as pp

    monkeypatch.setattr(
        pp, "ProjectProfiler",
        lambda root: types.SimpleNamespace(profile=lambda: profile),
    )
    monkeypatch.setattr(cm, "CodeMetrics", _FakeCodeMetrics)
    monkeypatch.setattr(
        hs, "grade",
        grade or (lambda root: types.SimpleNamespace(score=80, letter="B")),
    )
    monkeypatch.setattr(skills, "SecurityAgent", sec or _NoFindings)


# ---------------------------------------------------------------------------
# _findings_by_file: the accumulator literals (L55) — '0' default and '+ 1'.
# ---------------------------------------------------------------------------
def test_findings_per_file_count_is_exact(monkeypatch):
    """Two findings on one file count as 2, one on another as 1 — pins the
    ``get(fp, 0) + 1`` accumulator (kills ``0->1``, ``1->2``, ``+->-``)."""

    class _Multi:
        def run(self, project_root):
            return {"findings": [{"file": "a.py"}, {"file": "a.py"},
                                 {"file": "b.py"}]}

    monkeypatch.setattr(skills, "SecurityAgent", _Multi)
    counts = _findings_by_file("/proj")
    assert counts == {"a.py": 2, "b.py": 1}


# ---------------------------------------------------------------------------
# _fan_in: the accumulator literals (L65) and the ``or []`` guard (L64).
# ---------------------------------------------------------------------------
def test_fan_in_counts_every_incoming_edge_including_duplicates():
    """fan-in tallies one per edge, dupes included — pins ``get(dst,0)+1``
    (kills ``0->1``, ``1->2``, ``+->-``)."""
    prof = _FakeProfile(dependency_edges=[
        ("a", "b"), ("c", "b"), ("a", "b"), ("d", "e"),
    ])
    assert _fan_in(prof) == {"b": 3, "e": 1}


def test_fan_in_handles_real_edge_list_via_or_guard():
    """A populated ``dependency_edges`` list flows through ``... or []`` (the
    list is truthy). Flipping ``or`` to ``and`` would short-circuit to ``[]``
    and yield an empty fan-in, so a non-empty result kills ``or->and`` (L64)."""
    prof = _FakeProfile(dependency_edges=[("a", "b")])
    assert _fan_in(prof) == {"b": 1}


# ---------------------------------------------------------------------------
# _coordinator_signals: fan_out parsing (L83) — defaults and ``or 0`` fold.
# ---------------------------------------------------------------------------
def test_coordinator_fan_out_defaults_and_falsy_fold_to_zero():
    """Missing or falsy ``fan_out`` becomes 0, a real value passes through —
    pins ``int(c.get("fan_out", 0) or 0)`` (kills both ``0`` literals)."""
    prof = _FakeProfile(coordinator_modules=[
        {"module": "app/g.py"},                 # no fan_out key -> default 0
        {"module": "app/h.py", "fan_out": 0},   # falsy -> ``or 0`` -> 0
        {"module": "app/k.py", "fan_out": 5},   # real value preserved
    ])
    fan_out, coord_imports = _coordinator_signals(prof)
    assert fan_out == {"app/g.py": 0, "app/h.py": 0, "app/k.py": 5}
    assert coord_imports == {"app/g.py": [], "app/h.py": [], "app/k.py": []}


# ---------------------------------------------------------------------------
# _rank_modules: the rank tuple (L104-111) and ``reverse=True`` (L114).
# Each module carries exactly ONE distinguishing signal at equal magnitude, so
# the truncation order reflects the tuple's tier priority precisely.
# ---------------------------------------------------------------------------
def _rank_fixture():
    mods = [
        "app/find.py", "app/frag.py", "app/hub.py", "app/coord.py",
        "app/unt.py", "app/fout.py", "app/fin.py", "app/loc.py",
        "app/plain.py",
    ]
    metrics = {m: _metric() for m in mods}
    metrics["app/loc.py"] = _metric(loc=99)
    return mods, metrics


def test_rank_orders_by_signal_tier_priority():
    """The rank tuple orders findings > fragile > hub > coordinator > untested
    > fan_out > fan_in > loc, highest first. Pins every tier literal and the
    membership tests (kills the L104-111 ``in->not in`` / ``else 0->1`` /
    ``1->2`` mutants) and ``reverse=True`` (L114)."""
    mods, metrics = _rank_fixture()
    ranked = _rank_modules(
        mods, 99,
        {"app/find.py": 1}, {"app/frag.py"}, {"app/hub.py"},
        {"app/coord.py"}, {"app/unt.py"},
        {"app/fout.py": 1}, {"app/fin.py": 1}, metrics,
    )
    assert ranked == [
        "app/find.py", "app/frag.py", "app/hub.py", "app/coord.py",
        "app/unt.py", "app/fout.py", "app/fin.py", "app/loc.py",
        "app/plain.py",
    ]


def test_rank_cap_keeps_highest_priority_drops_plain():
    """Capping to N keeps the top-N by tier and drops the plain module — pins
    that ``reverse=True`` sorts descending (``False`` would keep ``plain`` and
    drop ``find``) and that the slice truncates."""
    mods, metrics = _rank_fixture()
    ranked = _rank_modules(
        mods, 2,
        {"app/find.py": 1}, {"app/frag.py"}, {"app/hub.py"},
        {"app/coord.py"}, {"app/unt.py"},
        {"app/fout.py": 1}, {"app/fin.py": 1}, metrics,
    )
    assert ranked == ["app/find.py", "app/frag.py"]


def test_rank_loc_tiebreak_uses_membership_and_metric_value():
    """When two desks differ only in LOC, the higher-LOC one ranks first — pins
    the ``metrics[m].loc if m in metrics else 0`` tiebreaker (kills ``in->not
    in``: under ``not in`` both fall to the else value, tie, and the stable sort
    keeps the lower-LOC module first instead)."""
    mods = ["app/lo.py", "app/hi.py"]
    metrics = {"app/lo.py": _metric(loc=1), "app/hi.py": _metric(loc=50)}
    ranked = _rank_modules(
        mods, 1, {}, set(), set(), set(), set(), {}, {}, metrics,
    )
    assert ranked == ["app/hi.py"]


def test_rank_loc_else_default_is_zero_for_unmetered_module():
    """A module absent from ``metrics`` contributes loc 0 to the rank, NOT 1 —
    pins the ``else 0`` default (L111). ``inm`` (in metrics, loc 0) and ``absent``
    (no metrics) tie at 0, so the stable sort keeps ``inm`` first; the ``0->1``
    mutant would lift ``absent`` to 1 and reorder."""
    mods = ["app/inm.py", "app/absent.py"]
    metrics = {"app/inm.py": _metric(loc=0)}
    ranked = _rank_modules(
        mods, 1, {}, set(), set(), set(), set(), {}, {}, metrics,
    )
    assert ranked == ["app/inm.py"]


# ---------------------------------------------------------------------------
# _building: metric fallbacks (L132/133), dept split (L145),
# fan_in/fan_out defaults (L151/152).
# ---------------------------------------------------------------------------
def test_building_uses_zero_when_module_has_no_metrics():
    """A module absent from ``metrics`` reports loc=0 and complexity=0 — pins
    the ``mm.loc if mm else 0`` / ``mm.complexity if mm else 0`` fallbacks."""
    b = _building("app/x.py", {}, {}, set(), set(), set(), set(), {}, {}, {}, {})
    assert b["loc"] == 0
    assert b["complexity"] == 0


def test_building_dept_is_top_level_package_or_dot():
    """``app/x.py`` -> dept ``app`` (has ``/``); a top-level ``top.py`` -> ``.``.
    Pins the ``m.split("/")[0] if "/" in m else "."`` (kills ``[0]->[1]`` and
    ``in->not in``)."""
    nested = _building("app/x.py", {"app/x.py": _metric()}, {}, set(), set(),
                       set(), set(), {}, {}, {}, {})
    top = _building("top.py", {"top.py": _metric()}, {}, set(), set(),
                    set(), set(), {}, {}, {}, {})
    assert nested["dept"] == "app"
    assert top["dept"] == "."


def test_building_fan_in_and_fan_out_reflect_supplied_maps():
    """fan_in/fan_out come straight from the maps, defaulting to 0 when absent —
    pins both ``.get(m, 0)`` defaults (L151/152)."""
    metrics = {"app/x.py": _metric()}
    present = _building("app/x.py", metrics, {}, set(), set(), set(), set(),
                        {}, {"app/x.py": 3}, {"app/x.py": 7}, {})
    absent = _building("app/y.py", {"app/y.py": _metric()}, {}, set(), set(),
                       set(), set(), {}, {}, {}, {})
    assert present["fan_in"] == 3 and present["fan_out"] == 7
    assert absent["fan_in"] == 0 and absent["fan_out"] == 0


# ---------------------------------------------------------------------------
# _workers: target predicates and counts (L183-208).
# Each building carries one distinguishing signal so each worker's route pins
# exactly one predicate.
# ---------------------------------------------------------------------------
def _worker_fixture():
    return [
        _bld("sec", findings=1),                       # 0: security target
        _bld("unt", health="untested"),                # 1: untested target
        _bld("hub", health="hub"),                     # 2: architect (hub)
        _bld("fan", fan_in=2),                          # 3: architect (fan_in>=2)
        _bld("doc", tests=0),                          # 4: doc-writer target
        _bld("ref", complexity=12),                    # 5: refactorer target
        _bld("plain"),                                 # 6: nothing special
    ]


def _routes_by_role(workers):
    out: dict[str, list[list[int]]] = {}
    for w in workers:
        out.setdefault(w["role"], []).append(w["route"])
    return out


def test_worker_routes_pin_each_target_predicate():
    """Every specialist's route reflects exactly its predicate — pins the
    ``findings > 0`` (L185), ``health == "untested"`` (L186), the architect's
    ``health in (...) or fan_in >= 2`` (L187), ``tests == 0`` (L188), and the
    refactorer's ``complexity >= 12`` (L208)."""
    routes = _routes_by_role(_workers(_worker_fixture()))
    assert routes["Security Auditor"] == [[0]]
    assert routes["Test Engineer"] == [[1], [1]]
    assert routes["Architect"] == [[2, 3]]
    assert routes["Doc Writer"] == [[4]]
    assert routes["Refactorer"] == [[5]]


def test_security_target_excludes_zero_finding_desks():
    """A desk with findings==0 is NOT a security target — pins ``> 0`` strictly
    (``>= 0`` would sweep in every desk, ``> 1`` would drop the single finding)."""
    bs = [_bld("clean", findings=0), _bld("hit", findings=1)]
    routes = _routes_by_role(_workers(bs))
    assert routes["Security Auditor"] == [[1]]


def test_architect_targets_require_fan_in_at_least_two():
    """fan_in must reach 2 for the architect, fan_in==1 does not qualify — pins
    ``fan_in >= 2`` (kills ``>=->>`` boundary and ``2->3``)."""
    bs = [_bld("one", fan_in=1), _bld("two", fan_in=2)]
    routes = _routes_by_role(_workers(bs))
    assert routes["Architect"] == [[1]]


def test_doc_writer_falls_back_to_full_floor_when_no_target():
    """With every desk tested, doc-targets is empty so the route falls back to
    ALL desks via ``targets or all_idx`` — pins ``or`` (L194): ``and`` would
    short-circuit to ``[]`` and drop the worker entirely."""
    bs = [_bld("a", tests=1), _bld("b", tests=1)]
    routes = _routes_by_role(_workers(bs))
    # tests==0 nowhere -> doc route is the whole floor, not absent.
    assert routes["Doc Writer"] == [[0, 1]]


def _n_auditors(ws):
    return sum(1 for w in ws if w["role"] == "Security Auditor")


def test_auditor_count_scales_then_caps():
    """Auditor headcount is ``max(1, min(4, (n+3)//4))`` over finding sites:
    1 site -> 1, 5 -> 2, 20 -> 4 (capped at ``min(4, ...)``). Pins the cap and
    the floor-division shape."""
    assert _n_auditors(_workers([_bld("s", findings=1)])) == 1
    assert _n_auditors(_workers(
        [_bld(f"s{i}", findings=1) for i in range(5)])) == 2
    assert _n_auditors(_workers(
        [_bld(f"s{i}", findings=1) for i in range(20)])) == 4


def test_auditor_count_at_four_sites_is_one():
    """4 finding sites -> ``(4+3)//4 = 1`` auditor; the ``3->4`` mutant would
    compute ``(4+4)//4 = 2``. Pins the ``+ 3`` constant precisely (L201)."""
    assert _n_auditors(_workers(
        [_bld(f"s{i}", findings=1) for i in range(4)])) == 1


def test_single_auditor_when_no_findings():
    """No findings -> the ``... if sec_targets else 1`` branch yields exactly one
    auditor (who falls back to patrolling the whole floor). Pins the ``else 1``
    literal (``else 2`` would spawn a second auditor)."""
    ws = _workers([_bld("a", findings=0), _bld("b", findings=0)])
    auditors = [w for w in ws if w["role"] == "Security Auditor"]
    assert len(auditors) == 1
    # No finding sites -> the auditor patrols every desk (the all_idx fallback).
    assert auditors[0]["route"] == [0, 1]


# ---------------------------------------------------------------------------
# _totals: the untested tally predicate (L217).
# ---------------------------------------------------------------------------
def test_totals_untested_counts_only_untested_health():
    """``untested`` counts desks whose health is exactly ``"untested"`` — pins
    the ``== "untested"`` and the ``sum(1 ...)`` literal (L217)."""
    bs = [
        _bld("u", health="untested"),
        _bld("o", health="ok"),
        _bld("u2", health="untested"),
    ]
    totals = _totals(bs, [])
    assert totals["untested"] == 2
    assert totals["buildings"] == 3


# ---------------------------------------------------------------------------
# build_city_model: the default cap (L235, max_buildings=60).
# ---------------------------------------------------------------------------
def test_default_cap_limits_rendered_buildings_to_sixty(monkeypatch):
    """With 61 candidate modules and the default cap, exactly 60 are rendered —
    pins ``max_buildings: int = 60`` (``61`` would let all 61 through)."""
    profile = _FakeProfile(
        module_to_tests={f"app/m{i:03d}.py": [] for i in range(61)},
    )
    _patch_build(monkeypatch, profile, sec=_NoFindings)
    model = build_city_model("/proj")
    assert len(model["buildings"]) == 60
    assert model["totals"]["buildings"] == 60
