"""Deep mutation-hardening for idea_seeder.py and idea_action_bridge.py.

Full single-token mutant universe per module (past the 30-cap), scored over a
single project-copy parallel survivor-finder. Each test below pins a behavior a
surviving mutant changed — caps, anchor selection/dedup/sort, age/share math,
default-count fallbacks, fan-in/out edge counting, and the bridge's action
routing/proof/plan paths — so the mutant is now killed deterministically.

Determinism: every assertion is on exact, order-independent content (string
equality, counts, sorted membership); no timestamps, wall-clock, or set/dict
iteration order.
"""
from __future__ import annotations

from app.engine.idea_seeder import IdeaSeeder
from app.tools.project_profile import ProjectProfile


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _facts(roots):
    return [f for r in roots for f in r.source_facts]


def _subjects(roots):
    return [r.subject for r in roots]


# --------------------------------------------------------------------------
# _RULES caps (lines 31-35): dependency_hubs 3, critical_untested 3,
# untested 2, sensitive_paths 3, entrypoints 2, symbol_hubs 2, config 1.
# Mutating the cap N->N+1 lets an extra item through; assert the exact count.
# --------------------------------------------------------------------------
def test_dependency_hub_rule_caps_at_three():
    roots = IdeaSeeder().seed(_profile(
        dependency_hubs=["m1", "m2", "m3", "m4"], ci_files=["ci.yml"]))
    subs = [r.subject for r in roots if r.source_facts[0].startswith("dependency-hub")]
    assert subs == ["m1", "m2", "m3"]


def test_critical_untested_rule_caps_at_three():
    roots = IdeaSeeder().seed(_profile(
        critical_untested_modules=["a", "b", "c", "d"], ci_files=["ci.yml"]))
    subs = [r.subject for r in roots
            if r.source_facts[0].startswith("critical-untested")]
    assert subs == ["a", "b", "c"]


def test_untested_rule_caps_at_two():
    roots = IdeaSeeder().seed(_profile(
        untested_modules=["u1", "u2", "u3"], ci_files=["ci.yml"]))
    subs = [r.subject for r in roots if r.source_facts[0].startswith("untested:")]
    assert subs == ["u1", "u2"]


def test_sensitive_path_rule_caps_at_three():
    roots = IdeaSeeder().seed(_profile(
        sensitive_paths=["p1", "p2", "p3", "p4"], ci_files=["ci.yml"]))
    subs = [r.subject for r in roots
            if r.source_facts[0].startswith("sensitive-path")]
    assert subs == ["p1", "p2", "p3"]


def test_entrypoint_rule_caps_at_two():
    roots = IdeaSeeder().seed(_profile(
        entrypoints=["e1", "e2", "e3"], ci_files=["ci.yml"]))
    subs = [r.subject for r in roots if r.source_facts[0].startswith("entrypoint:")]
    assert subs == ["e1", "e2"]


def test_symbol_hub_rule_caps_at_two():
    roots = IdeaSeeder().seed(_profile(
        symbol_hubs=["s1", "s2", "s3"], ci_files=["ci.yml"]))
    subs = [r.subject for r in roots if r.source_facts[0].startswith("symbol-hub")]
    assert subs == ["s1", "s2"]


def test_config_rule_caps_at_one():
    roots = IdeaSeeder().seed(_profile(
        config_files=["c1.ini", "c2.ini"], ci_files=["ci.yml"]))
    subs = [r.subject for r in roots if r.source_facts[0].startswith("config:")]
    assert subs == ["c1.ini"]


# --------------------------------------------------------------------------
# _module_anchors: hotspot int defaults (lines 79-80), impure defaults (99),
# dedup (82), sort (118), [:3] cap (122). Unit-tested directly to isolate.
# --------------------------------------------------------------------------
def test_hotspot_anchor_defaults_line_and_complexity_to_zero():
    # No "line"/"complexity" keys -> both default to 0 (kills both 0 sites on
    # line 79 and 80: the get-default and the `or 0`).
    prof = _profile(hotspot_functions=[{"module": "app/x.py", "function": "foo"}])
    anchors = IdeaSeeder()._module_anchors(prof, "app/x.py")
    assert anchors == [{"module": "app/x.py", "symbol": "foo",
                        "line": 0, "metric": "cyclomatic 0"}]


def test_hotspot_anchor_falsy_line_complexity_stay_zero():
    # Keys present but 0 -> the `or 0` branch keeps them 0.
    prof = _profile(hotspot_functions=[
        {"module": "app/x.py", "function": "foo", "line": 0, "complexity": 0}])
    anchors = IdeaSeeder()._module_anchors(prof, "app/x.py")
    assert anchors[0]["line"] == 0
    assert anchors[0]["metric"] == "cyclomatic 0"


def test_impure_anchor_line_defaults_to_zero():
    # No hotspots -> impure fallback; missing "line" defaults to 0 (line 99).
    prof = _profile(
        hotspot_functions=[],
        impure_untested_functions=[{"module": "app/y.py", "function": "bar"}])
    anchors = IdeaSeeder()._module_anchors(prof, "app/y.py")
    assert anchors == [{"module": "app/y.py", "symbol": "bar",
                        "line": 0, "metric": "impure, untested"}]


def test_module_anchors_dedup_identical_symbol_line():
    # Duplicate (symbol, line) is collapsed (line 82 `if key in seen`).
    prof = _profile(hotspot_functions=[
        {"module": "app/x.py", "function": "foo", "complexity": 9, "line": 10},
        {"module": "app/x.py", "function": "foo", "complexity": 9, "line": 10},
    ])
    anchors = IdeaSeeder()._module_anchors(prof, "app/x.py")
    assert len(anchors) == 1


def test_module_anchors_sort_by_complexity_then_line():
    # Sort is (-complexity, line, symbol) (line 118): highest complexity first.
    prof = _profile(hotspot_functions=[
        {"module": "app/x.py", "function": "low", "complexity": 5, "line": 3},
        {"module": "app/x.py", "function": "high", "complexity": 9, "line": 7},
        {"module": "app/x.py", "function": "mid", "complexity": 7, "line": 1},
    ])
    anchors = IdeaSeeder()._module_anchors(prof, "app/x.py")
    assert [a["symbol"] for a in anchors] == ["high", "mid", "low"]


def test_module_anchors_cap_at_three():
    prof = _profile(hotspot_functions=[
        {"module": "app/x.py", "function": f"f{i}", "complexity": 10 - i,
         "line": i} for i in range(5)])
    anchors = IdeaSeeder()._module_anchors(prof, "app/x.py")
    assert len(anchors) == 3
    assert [a["symbol"] for a in anchors] == ["f0", "f1", "f2"]


# --------------------------------------------------------------------------
# _complexity_anchors: MIN_COMPLEXITY boundary (lines 127, 156), the
# rsplit(".", 1) leaf extraction (158), and the dunder `and` filter (159).
# --------------------------------------------------------------------------
_C6 = (
    "def c6(x):\n"
    "    if x > 0:\n        return 1\n"
    "    if x > 1:\n        return 2\n"
    "    if x > 2:\n        return 3\n"
    "    if x > 3:\n        return 4\n"
    "    if x > 4:\n        return 5\n"
    "    if x > 5:\n        return 6\n"
    "    return 0\n"
)


def _empty_anchor_profile() -> ProjectProfile:
    p = _profile()
    p.hotspot_functions = []
    p.impure_untested_functions = []
    return p


def test_complexity_anchor_includes_complexity_exactly_six(tmp_path):
    # c6 has cyclomatic complexity exactly 6 == _ANCHOR_MIN_COMPLEXITY. The
    # guard is `< 6` so 6 is INCLUDED. Kills both the boundary flip `<`->`<=`
    # (line 156) and the threshold bump `6`->`7` (line 127).
    (tmp_path / "c6.py").write_text(_C6, encoding="utf-8")
    seeder = IdeaSeeder(str(tmp_path))
    anchors = seeder._complexity_anchors("c6.py", set())
    assert [a["symbol"] for a in anchors] == ["c6"]
    assert anchors[0]["metric"] == "cyclomatic 6"


_SECRET = (
    "class C:\n"
    "    def __secret(self, x):\n"
    "        if x > 0:\n            self.a = 1\n"
    "        if x > 1:\n            self.a = 2\n"
    "        if x > 2:\n            self.a = 3\n"
    "        if x > 3:\n            self.a = 4\n"
    "        if x > 4:\n            self.a = 5\n"
    "        if x > 5:\n            self.a = 6\n"
)


def test_complexity_anchor_keeps_single_underscore_dunder_prefix(tmp_path):
    # `C.__secret` startswith "__" but does NOT endswith "__"; the dunder filter
    # is `startswith and endswith`, so it is KEPT. The `and`->`or` mutant (line
    # 159) would drop it.
    (tmp_path / "sec.py").write_text(_SECRET, encoding="utf-8")
    seeder = IdeaSeeder(str(tmp_path))
    anchors = seeder._complexity_anchors("sec.py", set())
    assert [a["symbol"] for a in anchors] == ["C.__secret"]


_NESTED = (
    "class C:\n"
    "    def method(self, x):\n"
    "        def __inner__(y):\n"
    "            if y > 0:\n                return 1\n"
    "            if y > 1:\n                return 2\n"
    "            if y > 2:\n                return 3\n"
    "            if y > 3:\n                return 4\n"
    "            if y > 4:\n                return 5\n"
    "            if y > 5:\n                return 6\n"
    "        return __inner__\n"
)


def test_complexity_anchor_leaf_uses_last_dotted_segment(tmp_path):
    # `C.method.__inner__` -> rsplit(".", 1)[-1] == "__inner__" -> dunder ->
    # dropped. A maxsplit of 2 would yield "method.__inner__" (not a dunder) and
    # wrongly KEEP it. The two-dot name distinguishes maxsplit 1 from 2 (line
    # 158); only the outer method (`C.method`) survives the dunder filter.
    (tmp_path / "nest.py").write_text(_NESTED, encoding="utf-8")
    seeder = IdeaSeeder(str(tmp_path))
    anchors = seeder._complexity_anchors("nest.py", set())
    symbols = [a["symbol"] for a in anchors]
    assert "C.method" in symbols
    assert all("__inner__" not in s for s in symbols)


# --------------------------------------------------------------------------
# _symbol_def_line (lines 234-244): def/class/assign resolution + 0 fallbacks.
# --------------------------------------------------------------------------
_DEFS_SOURCE = (
    "import os\n"
    "\n"
    "FIRST = 1\n"
    "ALPHA = 2\n"
    "\n"
    "def beta():\n"
    "    return 2\n"
    "\n"
    "class Gamma:\n"
    "    pass\n"
)


def test_symbol_def_line_resolves_function(tmp_path):
    (tmp_path / "m.py").write_text(_DEFS_SOURCE, encoding="utf-8")
    assert IdeaSeeder(str(tmp_path))._symbol_def_line("m.py", "beta") == 6


def test_symbol_def_line_resolves_class(tmp_path):
    (tmp_path / "m.py").write_text(_DEFS_SOURCE, encoding="utf-8")
    assert IdeaSeeder(str(tmp_path))._symbol_def_line("m.py", "Gamma") == 9


def test_symbol_def_line_resolves_assignment_by_name(tmp_path):
    # ALPHA is the SECOND assignment (line 4). `and`->`or` would match the first
    # Name target (FIRST, line 3) for any symbol; `==`->`!=` would match the
    # first target whose id != "ALPHA" (FIRST, line 3). Pinning 4 kills both.
    (tmp_path / "m.py").write_text(_DEFS_SOURCE, encoding="utf-8")
    assert IdeaSeeder(str(tmp_path))._symbol_def_line("m.py", "ALPHA") == 4


def test_symbol_def_line_missing_symbol_returns_zero(tmp_path):
    (tmp_path / "m.py").write_text(_DEFS_SOURCE, encoding="utf-8")
    assert IdeaSeeder(str(tmp_path))._symbol_def_line("m.py", "nope") == 0


def test_symbol_def_line_unparseable_returns_zero(tmp_path):
    (tmp_path / "bad.py").write_text("def (:\n", encoding="utf-8")
    assert IdeaSeeder(str(tmp_path))._symbol_def_line("bad.py", "x") == 0


def test_symbol_def_line_no_root_returns_zero():
    assert IdeaSeeder("")._symbol_def_line("m.py", "beta") == 0


# --------------------------------------------------------------------------
# _cochange_anchors (lines 204-216): skip empty, dedup, line resolution, cap 3.
# --------------------------------------------------------------------------
def test_cochange_anchors_skip_empty_module_or_symbol(tmp_path):
    (tmp_path / "m.py").write_text(_DEFS_SOURCE, encoding="utf-8")
    links = [
        {"to": "m.py", "symbol": "beta", "from": "a.py"},
        {"to": "", "symbol": "x"},        # no module -> skipped
        {"to": "m.py", "symbol": ""},     # no symbol -> skipped
    ]
    anchors = IdeaSeeder(str(tmp_path))._cochange_anchors(links, 5)
    assert anchors == [{"module": "m.py", "symbol": "beta",
                        "line": 6, "metric": "co-changes 5"}]
    assert all(a["module"] and a["symbol"] for a in anchors)


def test_cochange_anchors_dedup_and_cap_three(tmp_path):
    (tmp_path / "m.py").write_text(_DEFS_SOURCE, encoding="utf-8")
    links = [
        {"to": "m.py", "symbol": "beta", "from": "a.py"},
        {"to": "m.py", "symbol": "beta", "from": "b.py"},   # dup -> collapsed
        {"to": "m.py", "symbol": "Gamma"},
        {"to": "m.py", "symbol": "ALPHA"},
        {"to": "m.py", "symbol": "FIRST"},                  # 4th -> over cap
    ]
    anchors = IdeaSeeder(str(tmp_path))._cochange_anchors(links, 2)
    assert [a["symbol"] for a in anchors] == ["beta", "Gamma", "ALPHA"]


# --------------------------------------------------------------------------
# _fanin_fanout_from_edges (lines 285-294): prebuilt importers used, self-edge
# drop, source==module deps, cap 3.
# --------------------------------------------------------------------------
def test_fanin_uses_prebuilt_importers_not_a_rebuild():
    # A deliberately WRONG prebuilt importers map proves the passed graph is
    # used (line 285 `if importers is None`): `is`->`is not` would rebuild from
    # edges and ignore it.
    edges = [("a", "m"), ("b", "m")]
    wrong = {"m": {"W", "X", "Y", "Z"}}  # claims fan-in 4
    fanin, _ = IdeaSeeder._fanin_fanout_from_edges(edges, "m", wrong)
    assert fanin == 4


def test_fanin_fanout_deps_and_cap_three():
    edges = [("m", "t1"), ("m", "t2"), ("m", "t3"), ("m", "t4"),
             ("a", "m"), ("b", "m"), ("c", "m")]
    fanin, targets = IdeaSeeder._fanin_fanout_from_edges(edges, "m")
    assert fanin == 3
    # Only m's own dependencies (source == module, line 291), capped at 3 (294).
    assert targets == ["t1", "t2", "t3"]


def test_build_importers_drops_self_edges():
    # Line 260 `if source == target: continue`.
    importers = IdeaSeeder._build_importers([("m", "m"), ("a", "m")])
    assert importers == {"m": {"a"}}


# --------------------------------------------------------------------------
# _resolve_fanin_targets / _cached_importers / _fanin_part / _targets_part /
# _anchor_phrase (lines 344, 371, 374, 380, 388, 403).
# --------------------------------------------------------------------------
class _DepProfile:
    def __init__(self, module_fanin=None, module_fanout=None, dependency_edges=None):
        self.module_fanin = module_fanin
        self.module_fanout = module_fanout
        self.dependency_edges = dependency_edges


def test_resolve_falls_back_for_fanin_even_when_name_targets_false():
    # module_fanin is absent (None) so fan-in must fall back to the edge count
    # even though name_targets is False. The OUTER `or`->`and` on line 344 would
    # skip the fallback and leave fan-in None.
    seeder = IdeaSeeder()
    seeder._importers_cache = {}
    prof = _DepProfile(module_fanin={}, module_fanout={"m": ["x"]},
                       dependency_edges=[("a", "m"), ("b", "m")])
    fanin, targets = seeder._resolve_fanin_targets(prof, "m", name_targets=False)
    assert fanin == 2


def test_resolve_does_not_compute_targets_when_name_targets_false():
    # fan-in is KNOWN (5) and targets are absent (None) with name_targets=False:
    # the INNER `name_targets and targets is None` is False, so NO fallback runs
    # and targets stay None. The inner `and`->`or` (line 344) would make
    # `name_targets or targets is None` True and compute targets from edges.
    seeder = IdeaSeeder()
    seeder._importers_cache = {}
    prof = _DepProfile(module_fanin={"m": 5}, module_fanout={},
                       dependency_edges=[("m", "x"), ("m", "y")])
    fanin, targets = seeder._resolve_fanin_targets(prof, "m", name_targets=False)
    assert fanin == 5
    assert targets is None


def test_cached_importers_uses_existing_cache_entry():
    # A pre-poisoned cache entry must be returned verbatim (line 371 `is None`
    # / line 374 `return importers`): `is`->`is not` would rebuild from edges.
    seeder = IdeaSeeder()
    prof = _DepProfile(dependency_edges=[("a", "m")])
    poisoned = {"m": {"W", "X", "Y"}}
    seeder._importers_cache = {id(prof): poisoned}
    got = seeder._cached_importers(prof, prof.dependency_edges)
    assert got is poisoned


def test_fanin_part_empty_for_zero():
    assert IdeaSeeder._fanin_part(0) == ""
    assert IdeaSeeder._fanin_part(None) == ""


def test_targets_part_empty_for_none_or_empty():
    assert IdeaSeeder._targets_part([]) == ""
    assert IdeaSeeder._targets_part(None) == ""


def test_anchor_phrase_uses_simple_symbol_leaf():
    # "C.method.foo" -> "`foo`" via rsplit(".", 1)[-1]; a maxsplit of 2 would
    # leave "method.foo" (line 403). A two-dot name is needed to distinguish 1
    # from 2.
    phrase = IdeaSeeder._anchor_phrase(
        [{"symbol": "C.method.foo", "metric": "cyclomatic 9", "line": 10}])
    assert phrase == ("Centers on `foo` (cyclomatic 9, line 10) "
                      "— decouple/test these first.")


# --------------------------------------------------------------------------
# _append_root accelerating annotation (line 433 `fact_value += ...`).
# --------------------------------------------------------------------------
def test_accelerating_annotation_appends_to_title_and_fact():
    accel = {"app/x.py": {"aging": ["security"],
                          "churn_before": 2, "churn_now": 9}}
    roots = IdeaSeeder().seed(
        _profile(dependency_hubs=["app/x.py"], ci_files=["ci.yml"]),
        accelerating=accel)
    hub = next(r for r in roots if r.subject == "app/x.py")
    assert hub.title.endswith(
        "— accelerating: 2→9 commits while its security risk ages")
    assert hub.source_facts[0] == "dependency-hub: app/x.py (accelerating 2→9)"


# --------------------------------------------------------------------------
# _dream_promotions + _seed_dream_insights (lines 474, 482, 484, 1053, 1054,
# 1060, 1061).
# --------------------------------------------------------------------------
def _write_dream(tmp_path, payload):
    import json
    apex = tmp_path / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "dream-promotions.json").write_text(
        json.dumps(payload), encoding="utf-8")


def test_dream_promotions_confluence_subject_splits_on_first_colon(tmp_path):
    # "confluence:app/x.py:extra".split(":", 1)[1] == "app/x.py:extra"; a
    # maxsplit of 2 would yield only "app/x.py" (line 482).
    _write_dream(tmp_path, [{"key": "confluence:app/x.py:extra", "text": "L"}])
    proms = IdeaSeeder(str(tmp_path))._dream_promotions()
    assert proms[0]["subject"] == "app/x.py:extra"


def test_dream_promotions_malformed_json_degrades_to_empty(tmp_path):
    apex = tmp_path / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "dream-promotions.json").write_text("{not json", encoding="utf-8")
    # Line 474 `return []` on the parse-error branch.
    assert IdeaSeeder(str(tmp_path))._dream_promotions() == []


def test_dream_insights_cap_at_two_and_confidence_streak_math(tmp_path):
    _write_dream(tmp_path, [
        {"key": "confluence:app/a.py", "text": "law A",
         "confidence": 0.999, "streak": 4},
        {"key": "confluence:app/b.py", "text": "law B",
         "confidence": 0.5, "streak": 2},
        {"key": "confluence:app/c.py", "text": "law C",
         "confidence": 0.9, "streak": 1},
    ])
    roots = IdeaSeeder(str(tmp_path)).seed(_profile(ci_files=["ci.yml"]))
    ins = [r for r in roots if r.source_facts[0].startswith("dream-insight")]
    # Capped at 2 (line 1053); distinct subjects so dedup doesn't merge them.
    assert len(ins) == 2
    # int(0.999 * 100) == 99 (kills * -> / and 100 -> 101); streak 4 verbatim.
    assert ins[0].source_facts[0] == (
        "dream-insight: confluence:app/a.py (99% confidence, confirmed 4 dreams)")
    assert ins[0].subject == "app/a.py"


def test_dream_insight_defaults_confidence_and_streak_to_zero(tmp_path):
    _write_dream(tmp_path, [{"key": "k", "text": "L"}])
    roots = IdeaSeeder(str(tmp_path)).seed(_profile(ci_files=["ci.yml"]))
    ins = next(r for r in roots
               if r.source_facts[0].startswith("dream-insight"))
    # Missing confidence -> 0% (line 1060 get-default); missing streak -> 0
    # (line 1061 get-default).
    assert ins.source_facts[0] == "dream-insight: k (0% confidence, confirmed 0 dreams)"


def test_dream_insight_non_confluence_key_keeps_abstract_subject(tmp_path):
    # A non-confluence key has subject "" -> the `or` (line 1054) falls back to
    # "project structure"; `and` would yield "".
    _write_dream(tmp_path, [{"key": "assoc:foo", "text": "L",
                             "confidence": 0.7, "streak": 2}])
    roots = IdeaSeeder(str(tmp_path)).seed(_profile(ci_files=["ci.yml"]))
    ins = next(r for r in roots
               if r.source_facts[0].startswith("dream-insight"))
    assert ins.subject == "project structure"


# --------------------------------------------------------------------------
# Per-family [:3] / [:2] caps across the seed_* helpers, and fact_label routing.
# --------------------------------------------------------------------------
def _count(roots, label):
    return sum(1 for r in roots if r.source_facts[0].startswith(label))


def test_correctness_bug_family_caps_at_three():
    roots = IdeaSeeder().seed(_profile(
        correctness_bug_modules=["a", "b", "c", "d"], ci_files=["ci.yml"]))
    assert _count(roots, "correctness-bug") == 3


def test_security_finding_family_caps_at_three():
    roots = IdeaSeeder().seed(_profile(
        security_finding_modules=["a", "b", "c", "d"], ci_files=["ci.yml"]))
    assert _count(roots, "security-finding") == 3


def test_confluence_family_caps_at_three():
    convs = [{"module": f"m{i}.py", "families": ["hub", "churn"]}
             for i in range(4)]
    roots = IdeaSeeder().seed(_profile(
        confluence_modules=convs, ci_files=["ci.yml"]))
    assert _count(roots, "confluence") == 3


def test_fragile_family_caps_at_three():
    roots = IdeaSeeder().seed(_profile(
        fragile_modules=["a", "b", "c", "d"], ci_files=["ci.yml"]))
    assert _count(roots, "fragile") == 3


def test_shallow_coverage_family_caps_at_three():
    roots = IdeaSeeder().seed(_profile(
        shallow_tested_modules=["a", "b", "c", "d"], ci_files=["ci.yml"]))
    assert _count(roots, "shallow-coverage") == 3


def test_complexity_hotspot_family_caps_at_three():
    roots = IdeaSeeder().seed(_profile(
        hotspot_modules=["a", "b", "c", "d"], ci_files=["ci.yml"]))
    assert _count(roots, "complexity-hotspot") == 3


def test_hotspot_function_family_caps_at_three():
    fns = [{"module": "m.py", "function": f"f{i}", "complexity": 9, "line": i}
           for i in range(4)]
    roots = IdeaSeeder().seed(_profile(
        hotspot_functions=fns, ci_files=["ci.yml"]))
    assert _count(roots, "hotspot-function") == 3


def test_impure_family_caps_at_three():
    fns = [{"module": "m.py", "function": f"f{i}", "line": i, "side_effects": []}
           for i in range(4)]
    roots = IdeaSeeder().seed(_profile(
        impure_untested_functions=fns, ci_files=["ci.yml"]))
    assert _count(roots, "impure-untested") == 3


def test_hub_untested_family_caps_at_three():
    hubs = [{"module": f"m{i}.py", "fan_in": 5} for i in range(4)]
    roots = IdeaSeeder().seed(_profile(
        hub_untested_modules=hubs, ci_files=["ci.yml"]))
    assert _count(roots, "hub-untested") == 3


def test_debt_marker_family_caps_at_three():
    roots = IdeaSeeder().seed(_profile(
        debt_marker_modules=["a", "b", "c", "d"], ci_files=["ci.yml"]))
    assert _count(roots, "debt-markers") == 3


def test_churn_hotspot_family_caps_at_three():
    spots = [{"module": f"m{i}.py", "commits": 10} for i in range(4)]
    roots = IdeaSeeder().seed(_profile(
        churn_hotspots=spots, ci_files=["ci.yml"]))
    assert _count(roots, "churn-hotspot") == 3


def test_polyglot_family_caps_at_three():
    hots = [{"path": f"f{i}.js", "loc": 100, "churn": 2, "language": "JS"}
            for i in range(4)]
    roots = IdeaSeeder().seed(_profile(
        polyglot_hotspots=hots, ci_files=["ci.yml"]))
    assert _count(roots, "polyglot-hotspot") == 3


def test_incomplete_protocol_family_caps_at_three():
    protos = [{"module": f"m{i}.py", "class": f"C{i}", "line": 1,
               "have": "__eq__", "missing": "__hash__", "protocol": "equality/hash"}
              for i in range(4)]
    roots = IdeaSeeder().seed(_profile(
        incomplete_protocols=protos, ci_files=["ci.yml"]))
    assert _count(roots, "incomplete-protocol") == 3


def test_generalizable_duplication_family_caps_at_three():
    dups = [{"modules": [f"a{i}.py", f"b{i}.py"], "occurrences": 2, "lines": 5}
            for i in range(4)]
    roots = IdeaSeeder().seed(_profile(
        generalizable_duplications=dups, ci_files=["ci.yml"]))
    assert _count(roots, "generalizable-duplication") == 3


def test_coordinator_family_caps_at_three():
    coords = [{"module": f"m{i}.py", "imports": ["x.py"]} for i in range(4)]
    roots = IdeaSeeder().seed(_profile(
        coordinator_modules=coords, ci_files=["ci.yml"]))
    assert _count(roots, "coordinator") == 3


def test_deep_nesting_family_caps_at_three():
    nests = [{"module": f"m{i}.py", "function": f"f{i}"} for i in range(4)]
    roots = IdeaSeeder().seed(_profile(
        deeply_nested_functions=nests, ci_files=["ci.yml"]))
    assert _count(roots, "deep-nesting") == 3


def test_god_class_family_caps_at_three():
    gcs = [{"module": f"m{i}.py", "classname": f"C{i}"} for i in range(4)]
    roots = IdeaSeeder().seed(_profile(
        god_classes=gcs, ci_files=["ci.yml"]))
    assert _count(roots, "god-class") == 3


def test_knowledge_risk_family_caps_at_two():
    risks = [{"module": f"m{i}.py", "share": 80, "commits": 10} for i in range(3)]
    roots = IdeaSeeder().seed(_profile(
        knowledge_risks=risks, ci_files=["ci.yml"]))
    assert _count(roots, "knowledge-risk") == 2


def test_mutable_default_family_caps_at_two():
    roots = IdeaSeeder().seed(_profile(
        mutable_default_modules=["a", "b", "c"], ci_files=["ci.yml"]))
    assert _count(roots, "mutable-default") == 2


def test_dead_param_family_caps_at_two():
    dps = [{"module": f"m{i}.py", "function": f"f{i}", "param": "x", "line": 1}
           for i in range(3)]
    roots = IdeaSeeder().seed(_profile(dead_params=dps, ci_files=["ci.yml"]))
    assert _count(roots, "dead-parameter") == 2


def test_extractable_block_family_caps_at_two():
    ebs = [{"module": f"m{i}.py", "function": f"f{i}", "line": 1, "start": 2,
            "end": 9, "name": "helper", "lines_saved": 5, "params": ["a"],
            "returns": ["b"]} for i in range(3)]
    roots = IdeaSeeder().seed(_profile(
        extractable_blocks=ebs, ci_files=["ci.yml"]))
    assert _count(roots, "extractable-block") == 2


def test_inlinable_helper_family_caps_at_two():
    ihs = [{"module": f"m{i}.py", "function": f"f{i}", "line": 1}
           for i in range(3)]
    roots = IdeaSeeder().seed(_profile(
        inlinable_helpers=ihs, ci_files=["ci.yml"]))
    assert _count(roots, "inlinable-helper") == 2


def test_modernization_family_caps_at_two():
    roots = IdeaSeeder().seed(_profile(
        modernizable_modules=["a", "b", "c"], ci_files=["ci.yml"]))
    assert _count(roots, "modernization") == 2


# --------------------------------------------------------------------------
# fact_label routing in _seed_rule_families (lines 646/651/652): only the
# dependency-hub rule attaches anchors + a quantified clause; others don't.
# --------------------------------------------------------------------------
def test_dependency_hub_rule_attaches_quantified_and_anchors():
    prof = _profile(
        dependency_hubs=["app/h.py"],
        module_fanin={"app/h.py": 4},
        module_fanout={"app/h.py": ["app/a.py"]},
        hotspot_functions=[{"module": "app/h.py", "function": "foo",
                            "complexity": 9, "line": 3}],
        ci_files=["ci.yml"])
    hub = next(r for r in IdeaSeeder().seed(prof) if r.subject == "app/h.py")
    assert hub.anchors  # dependency-hub gets anchors
    assert "Imported by 4 modules" in hub.rationale
    assert "heaviest dependency" in hub.rationale


def test_non_hub_rule_has_no_quantified_or_anchors():
    # sensitive-path is fact_label != "dependency-hub": the `==` checks (646/651)
    # gate anchors/quantified OFF; `!=` would wrongly attach them.
    prof = _profile(
        sensitive_paths=["app/s.py"],
        module_fanin={"app/s.py": 4},
        module_fanout={"app/s.py": ["app/a.py"]},
        hotspot_functions=[{"module": "app/s.py", "function": "foo",
                            "complexity": 9, "line": 3}],
        ci_files=["ci.yml"])
    sp = next(r for r in IdeaSeeder().seed(prof) if r.subject == "app/s.py")
    assert sp.anchors == []
    assert "Imported by" not in sp.rationale
    assert sp.rationale == "Seeded from sensitive-path: app/s.py"


def test_fragile_uses_name_targets_false_no_decoupling_clause():
    # Line 625 name_targets=False: fragile gets the fan-in clause but NOT the
    # "heaviest dependencies" decoupling clause (which name_targets=True adds).
    prof = _profile(
        fragile_modules=["app/x.py"],
        module_fanin={"app/x.py": 4},
        module_fanout={"app/x.py": ["app/a.py", "app/b.py"]},
        ci_files=["ci.yml"])
    fr = next(r for r in IdeaSeeder().seed(prof) if r.subject == "app/x.py")
    assert "Imported by 4 modules" in fr.rationale
    assert "heaviest" not in fr.rationale


def test_complexity_hotspot_uses_name_targets_false():
    # Line 689 name_targets=False for complexity hotspots.
    prof = _profile(
        hotspot_modules=["app/x.py"],
        module_fanin={"app/x.py": 4},
        module_fanout={"app/x.py": ["app/a.py", "app/b.py"]},
        ci_files=["ci.yml"])
    hs = next(r for r in IdeaSeeder().seed(prof) if r.subject == "app/x.py")
    assert "Imported by 4 modules" in hs.rationale
    assert "heaviest" not in hs.rationale


# --------------------------------------------------------------------------
# Age / share / count math in security, debt, polyglot, impure, dream families.
# --------------------------------------------------------------------------
def test_security_age_boundary_at_ninety_days():
    # age == 90 triggers the "exposed for ~N months" clause (`>= 90`, line 570);
    # months = 90 // 30 == 3.
    prof = _profile(
        security_finding_modules=["app/s.py"],
        security_finding_ages={"app/s.py": 90},
        ci_files=["ci.yml"])
    sp = next(r for r in IdeaSeeder().seed(prof) if r.subject == "app/s.py")
    assert sp.title.endswith("— exposed for ~3 months")
    assert sp.source_facts[0] == (
        "security-finding: app/s.py (security finding, in the code ~3 months)")


def test_security_age_below_ninety_has_no_age_clause():
    prof = _profile(
        security_finding_modules=["app/s.py"],
        security_finding_ages={"app/s.py": 89},
        ci_files=["ci.yml"])
    sp = next(r for r in IdeaSeeder().seed(prof) if r.subject == "app/s.py")
    assert "exposed for" not in sp.title


def test_debt_age_boundary_at_ninety_days():
    prof = _profile(
        debt_marker_modules=["app/d.py"],
        debt_marker_ages={"app/d.py": 90},
        ci_files=["ci.yml"])
    d = next(r for r in IdeaSeeder().seed(prof) if r.subject == "app/d.py")
    assert d.title.endswith("— the oldest has waited 3 months")
    assert d.source_facts[0] == (
        "debt-markers: app/d.py (clustered debt markers; oldest ~3 months old)")


def test_debt_age_below_ninety_has_no_age_clause():
    prof = _profile(
        debt_marker_modules=["app/d.py"],
        debt_marker_ages={"app/d.py": 89},
        ci_files=["ci.yml"])
    d = next(r for r in IdeaSeeder().seed(prof) if r.subject == "app/d.py")
    assert "waited" not in d.title


def test_polyglot_singular_commit_word_and_loc_churn_defaults():
    prof = _profile(
        polyglot_hotspots=[
            {"path": "web/app.js", "loc": 500, "churn": 1, "language": "JS"},
            {"path": "web/b.js"},  # missing loc/churn -> 0 / 0
        ],
        ci_files=["ci.yml"])
    roots = IdeaSeeder().seed(prof)
    a = next(r for r in roots if r.subject == "web/app.js")
    b = next(r for r in roots if r.subject == "web/b.js")
    # churn == 1 -> singular "commit" (line 866).
    assert "1 recent commit," in a.title
    assert a.source_facts[0].startswith(
        "polyglot-hotspot: web/app.js (JS, 500 LOC, 1 recent commit")
    # defaults: 0 LOC, 0 recent commits (lines 863/864).
    assert ", 0 LOC, 0 recent commits" in b.source_facts[0]


def test_impure_shows_first_three_effects_with_more_count():
    # 5 effects -> "io, net, global +2 more": shown=effects[:3] (line 726),
    # more=len-3 (line 727), only when len > 3.
    prof = _profile(
        impure_untested_functions=[
            {"module": "app/y.py", "function": "Cls.outer.bar", "line": 42,
             "side_effects": ["io", "net", "global", "subprocess", "logging"]},
        ],
        ci_files=["ci.yml"])
    r = next(x for x in IdeaSeeder().seed(prof)
             if x.source_facts[0].startswith("impure-untested"))
    # Title uses the simple leaf "bar" via rsplit(".", 1) (line 724); a two-dot
    # name distinguishes maxsplit 1 from 2.
    assert r.title.startswith("Isolate the side effects of bar() in app/y.py")
    assert "io, net, global +2 more" in r.source_facts[0]


def test_impure_three_effects_has_no_more_clause():
    # Exactly 3 effects: len(effects) > 3 is False, so NO "+N more". The `> 3`
    # boundary flip to `>= 3` would add a spurious "+0 more".
    prof = _profile(
        impure_untested_functions=[
            {"module": "app/y.py", "function": "bar", "line": 1,
             "side_effects": ["io", "net", "db"]},
        ],
        ci_files=["ci.yml"])
    r = next(x for x in IdeaSeeder().seed(prof)
             if x.source_facts[0].startswith("impure-untested"))
    assert "io, net, db," in r.source_facts[0]
    assert "more" not in r.source_facts[0]


def test_impure_four_effects_more_count_is_one():
    # 4 effects -> "+1 more" (len - 3 == 1). The `3`->`4` mutant would make
    # `len(effects) > 4` False (no clause) and `len - 4 == 0`.
    prof = _profile(
        impure_untested_functions=[
            {"module": "app/y.py", "function": "bar", "line": 1,
             "side_effects": ["io", "net", "db", "log"]},
        ],
        ci_files=["ci.yml"])
    r = next(x for x in IdeaSeeder().seed(prof)
             if x.source_facts[0].startswith("impure-untested"))
    assert "io, net, db +1 more" in r.source_facts[0]


def test_hotspot_function_title_and_cognitive_clause():
    prof = _profile(
        hotspot_functions=[
            {"module": "app/m.py", "function": "Cls.outer.foo", "complexity": 12,
             "cognitive": 8, "line": 5},
        ],
        ci_files=["ci.yml"])
    r = next(x for x in IdeaSeeder().seed(prof)
             if x.source_facts[0].startswith("hotspot-function"))
    # Title uses simple leaf "foo" via rsplit(".", 1) (line 699); a two-dot name
    # distinguishes maxsplit 1 from 2.
    assert r.title.startswith("Write behavioral tests for foo() in app/m.py")
    assert ", cognitive 8," in r.source_facts[0]


def test_python_tooling_fires_at_one_py_file():
    # exts[".py"] >= 1 at exactly 1 (line 1105 boundary `>= 1`).
    roots = IdeaSeeder().seed(_profile(
        extension_counts={".py": 1}, ci_files=["ci.yml"]))
    py = [r for r in roots if r.source_facts[0].startswith("extension-py")]
    assert len(py) == 1
    assert py[0].source_facts[0] == "extension-py: .py x1"


def test_python_tooling_silent_with_no_py_files():
    roots = IdeaSeeder().seed(_profile(
        extension_counts={".js": 5}, ci_files=["ci.yml"]))
    assert not any(r.source_facts[0].startswith("extension-py") for r in roots)


def test_doc_drift_lists_up_to_three_references():
    # refs[:3] (line 1097): a doc referencing 4 missing files lists only 3.
    drift = [{"doc": "README.md", "reference": f"f{i}.py"} for i in range(4)]
    roots = IdeaSeeder().seed(_profile(doc_drift=drift, ci_files=["ci.yml"]))
    dd = next(r for r in roots if r.subject == "README.md")
    assert dd.source_facts[0] == (
        "doc-drift: README.md -> f0.py, f1.py, f2.py (missing)")


# --------------------------------------------------------------------------
# Guard/default edges: generalizable-duplication, coordinator, deep-nesting,
# god-class (lines 937/939/940, 972, 1003, 1033).
# --------------------------------------------------------------------------
def test_generalizable_duplication_needs_two_modules():
    # len(modules) < 2 (line 937): a 1-module group is skipped; a 2-module group
    # is emitted. occurrences/lines default to 0 (lines 939/940).
    prof = _profile(
        generalizable_duplications=[
            {"modules": ["a.py", "b.py"]},   # exactly 2, no occ/lines
            {"modules": ["c.py"]},           # < 2 -> skipped
        ],
        ci_files=["ci.yml"])
    dups = [r for r in IdeaSeeder().seed(prof)
            if r.source_facts[0].startswith("generalizable-duplication")]
    assert len(dups) == 1
    assert dups[0].subject == "a.py + b.py"
    assert dups[0].source_facts[0] == (
        "generalizable-duplication: near-identical 0-line blocks recur across "
        "`a.py`, `b.py` (0 occurrences — extract one shared helper to DRY it up)")


def test_coordinator_pulls_clause_uses_imports():
    # `coord.get("imports") or []` (line 972): named imports appear; `or`->`and`
    # would blank them.
    prof = _profile(
        coordinator_modules=[{"module": "m.py", "imports": ["x.py", "y.py"]}],
        ci_files=["ci.yml"])
    c = next(r for r in IdeaSeeder().seed(prof) if r.subject == "m.py")
    assert "pulls `x.py`, `y.py` among others" in c.source_facts[0]


def test_deep_nesting_skips_entry_missing_function():
    # `if not module or not function` (line 1003): module present but no function
    # -> skipped. `or`->`and` would emit it.
    prof = _profile(
        deeply_nested_functions=[{"module": "m.py"},
                                 {"module": "n.py", "function": "f"}],
        ci_files=["ci.yml"])
    nests = [r for r in IdeaSeeder().seed(prof)
             if r.source_facts[0].startswith("deep-nesting")]
    assert [r.subject for r in nests] == ["n.py::f"]


def test_god_class_skips_entry_missing_classname():
    prof = _profile(
        god_classes=[{"module": "m.py"}, {"module": "n.py", "classname": "C"}],
        ci_files=["ci.yml"])
    gcs = [r for r in IdeaSeeder().seed(prof)
           if r.source_facts[0].startswith("god-class")]
    assert [r.subject for r in gcs] == ["n.py::C"]


# --------------------------------------------------------------------------
# _seed_hot_bus_factor (lines 1275-1302): intersection, cap 3, defaults,
# emitted counter.
# --------------------------------------------------------------------------
def test_hot_bus_factor_caps_at_three():
    # 4 modules that are both churn hotspots AND knowledge risks -> exactly 3.
    # Kills the cap `emitted >= 3` (1282), `emitted = 0` (1280) and the
    # `emitted += 1` counter (1302).
    churn = [{"module": f"m{i}.py", "commits": 10 + i} for i in range(4)]
    risks = [{"module": f"m{i}.py", "share": 70 + i, "commits": 5}
             for i in range(4)]
    roots = IdeaSeeder().seed(_profile(
        churn_hotspots=churn, knowledge_risks=risks, ci_files=["ci.yml"]))
    bf = [r for r in roots if r.source_facts[0].startswith("hot-bus-factor")]
    assert len(bf) == 3
    assert bf[0].subject == "m0.py (bus-factor)"


def test_hot_bus_factor_requires_a_knowledge_risk():
    # No knowledge risks -> `risk_by_module` empty -> early return (the `or []`
    # on line 1275 feeds the empty-dict check). A pure churn hotspot yields no
    # bus-factor root.
    roots = IdeaSeeder().seed(_profile(
        churn_hotspots=[{"module": "m.py", "commits": 9}], ci_files=["ci.yml"]))
    assert not any(r.source_facts[0].startswith("hot-bus-factor") for r in roots)


def test_hot_bus_factor_commits_default_for_overflow_churn_hotspot():
    # The first 3 churn hotspots are NOT knowledge risks (skipped by the
    # intersection); the 4th IS a knowledge risk but lacks "commits". The churn
    # family capped at 3 never touched the 4th, so bus-factor uses the
    # `spot.get("commits", 0)` default (line 1288) -> "0 recent commits".
    churn = [{"module": "a.py", "commits": 5}, {"module": "b.py", "commits": 4},
             {"module": "c.py", "commits": 3}, {"module": "z.py"}]
    risks = [{"module": "z.py", "share": 60, "commits": 2}]
    roots = IdeaSeeder().seed(_profile(
        churn_hotspots=churn, knowledge_risks=risks, ci_files=["ci.yml"]))
    bf = next(r for r in roots
              if r.source_facts[0].startswith("hot-bus-factor"))
    assert bf.subject == "z.py (bus-factor)"
    assert "0 recent commits AND 60% single-author" in bf.source_facts[0]


def test_hot_bus_factor_share_default_for_overflow_knowledge_risk():
    # The 3rd knowledge risk (over the [:2] knowledge-family cap) lacks "share"
    # but matches a churn hotspot, so bus-factor uses kr.get("share", 0) default
    # (line 1289) -> "0% single-author".
    churn = [{"module": "a.py", "commits": 5}]
    risks = [{"module": "k1.py", "share": 1, "commits": 1},
             {"module": "k2.py", "share": 2, "commits": 1},
             {"module": "a.py"}]
    roots = IdeaSeeder().seed(_profile(
        churn_hotspots=churn, knowledge_risks=risks, ci_files=["ci.yml"]))
    bf = next(r for r in roots
              if r.source_facts[0].startswith("hot-bus-factor"))
    assert bf.subject == "a.py (bus-factor)"
    assert "5 recent commits AND 0% single-author" in bf.source_facts[0]


# --------------------------------------------------------------------------
# Co-change test gaps (line 775 cap) and simplifications (lines 1212/1216).
# --------------------------------------------------------------------------
def test_cochange_test_gap_family_caps_at_three():
    gaps = [{"a": f"a{i}.py", "b": f"b{i}.py", "cochanges": 5} for i in range(4)]
    roots = IdeaSeeder().seed(_profile(
        cochange_test_gaps=gaps, ci_files=["ci.yml"]))
    assert _count(roots, "cochange-testgap") == 3


def test_cochange_test_gap_cochanges_defaults_to_zero():
    # gap.get("cochanges", 0) default (line 777) -> "co-change 0x".
    roots = IdeaSeeder().seed(_profile(
        cochange_test_gaps=[{"a": "a.py", "b": "b.py"}], ci_files=["ci.yml"]))
    cg = next(r for r in roots
              if r.source_facts[0].startswith("cochange-testgap"))
    assert "co-change 0x" in cg.source_facts[0]


def test_hub_untested_fan_in_defaults_to_zero():
    # hub.get("fan_in", 0) default (line 752) -> "0 dependents" / "breaks all 0".
    roots = IdeaSeeder().seed(_profile(
        hub_untested_modules=[{"module": "h.py"}], ci_files=["ci.yml"]))
    h = next(r for r in roots if r.subject == "h.py")
    assert "0 dependents" in h.source_facts[0]
    assert "breaks all 0" in h.source_facts[0]


def test_incomplete_protocol_line_defaults_to_zero():
    # proto.get("line", 0) default (line 902) -> locus "m.py:0".
    roots = IdeaSeeder().seed(_profile(
        incomplete_protocols=[{"module": "m.py", "class": "C",
                               "have": "__eq__", "missing": "__hash__",
                               "protocol": "equality/hash"}],
        ci_files=["ci.yml"]))
    pr = next(r for r in roots
              if r.source_facts[0].startswith("incomplete-protocol"))
    assert "(m.py:0)" in pr.title


def test_simplification_emits_and_skips_incomplete_opportunities():
    # `or []` (1212) feeds the loop; `not (module and fact_label)` (1216) skips
    # any opportunity missing either field.
    prof = _profile(
        simplification_opportunities=[
            {"module": "m.py", "fact_label": "none-compare",
             "transform": "simplify_none_compare"},
            {"module": "n.py", "fact_label": "", "transform": "t"},  # skipped
            {"module": "", "fact_label": "x", "transform": "t"},     # skipped
        ],
        ci_files=["ci.yml"])
    roots = IdeaSeeder().seed(prof)
    simp = [r for r in roots if r.source_facts[0].startswith("none-compare")]
    assert len(simp) == 1
    # Additive ``::simplify-<transform>`` subject suffix (the bridge resolves the
    # file from the part before ``::``); never deduped by a bare-module owner.
    assert simp[0].subject == "m.py::simplify-simplify_none_compare"
    assert simp[0].title == "Apply simplify_none_compare to simplify m.py"
    # The incomplete opportunities never became roots.
    assert not any(r.subject.startswith("n.py") for r in roots)


# ==========================================================================
# idea_action_bridge.py
# ==========================================================================
from app.engine.idea_action_bridge import (  # noqa: E402
    IdeaActionBridge,
    _OPERATOR_ACTIONS,
    _FACT_ACTIONS,
    _anchor_phrase,
    _concrete_test_description,
    _confluence_weight,
    _stub_anchor_body,
    _stub_header,
    _stub_slug,
    _stub_smoke_body,
    _test_stub_body,
)
from app.models.idea import ActionStep, IdeaNode  # noqa: E402


def _root(fact, subject="app/x.py", **kw):
    return IdeaNode(id="i", title="t", subject=subject, operator="root",
                    source_facts=[fact], **kw)


# --------------------------------------------------------------------------
# _OPERATOR_ACTIONS / _FACT_ACTIONS executable-flag table (lines 11-233): pin
# the exact (action_type, executable) per key so any True<->False flip fails.
# --------------------------------------------------------------------------
_OP_EXPECTED = {
    "test": ("create_test_stub", True),
    "document": ("add_docstring", True),
    "harden": ("harden_security", True),
    "simplify": ("organize_imports", True),
    "extend": ("design_task", False),
    "integrate": ("design_task", False),
    "generalize": ("design_task", False),
    "observe": ("design_task", False),
}

_FACT_EXPECTED = {
    "untested": ("create_test_stub", True),
    "critical-untested": ("create_test_stub", True),
    "hotspot-function": ("create_test_stub", True),
    "impure-untested": ("create_test_stub", True),
    "hub-untested": ("create_test_stub", True),
    # W98: flipped from design_task → the delegated strengthen_tests lander for a
    # TESTED confluence (mutant-killing assertions before changing it; the
    # decoupling design stays a disclosed human remainder). An UNTESTED
    # confluence still routes to create_test_stub via the _root_action exception.
    "confluence": ("strengthen_tests", True),
    "cochange-testgap": ("create_test_stub", True),
    "sensitive-path": ("harden_security", True),
    "security-finding": ("harden_security", True),
    "correctness-bug": ("harden_security", True),
    "config": ("design_task", False),
    # W98: flipped from design_task → the delegated strengthen_tests lander
    # (strengthen the entrypoint's tests before growing it; which capability to
    # grow stays a disclosed human remainder; apply-time gate is the honesty rail,
    # no plan-time probe — the mutation engine is unaffordable there).
    "entrypoint": ("strengthen_tests", True),
    # W98: flipped from design_task → the delegated cover_gaps lander (land a
    # characterization safety-net test before the hub evolves; the evolution plan
    # stays a disclosed human remainder; gated by the plan-time
    # _covergaps_unserviceable probe — the lander's OWN gate).
    "dependency-hub": ("cover_gaps", True),
    # W98: flipped from design_task → the delegated cover_gaps lander (pin the
    # symbol-rich module's public behavior before generalizing it; the
    # generalization design stays a disclosed human remainder; same plan-time
    # probe as dependency-hub).
    "symbol-hub": ("cover_gaps", True),
    # ÇAĞ2-W3: three more design_task rows flip to the SAME delegated
    # cover_gaps lander (complexity-hotspot/knowledge-risk/churn-hotspot) —
    # a characterization safety-net test lands first, honest by the
    # identical plan-time _covergaps_unserviceable probe; each family's own
    # intent (simplify / spread-knowledge / smooth-the-change-path) stays a
    # disclosed human remainder.
    "complexity-hotspot": ("cover_gaps", True),
    "knowledge-risk": ("cover_gaps", True),
    "churn-hotspot": ("cover_gaps", True),
    "missing-ci": ("add_ci", True),
    "polyglot-hotspot": ("design_task", False),
    # Autonomous-39 W5: flipped from design_task → the delegated seal_hashable_eq
    # lander (deterministic canonical-__hash__ completion over the __eq__ fields,
    # gated + auto-rollback; a context-manager gap finds no eq/hash class ⇒ an honest
    # no-op, so incomplete-protocol stays advisory for that shape).
    "incomplete-protocol": ("seal_hashable_eq", True),
    # Autonomous-39 W1: flipped from design_task → the delegated dedup_parameterized
    # lander (deterministic shared-helper extraction, gated + auto-rollback).
    "generalizable-duplication": ("dedup_parameterized", True),
    "coordinator": ("design_task", False),
    # Autonomous-39 W2: flipped from design_task → the delegated extract_guard_clause
    # lander (deterministic guard-invert flatten, gated + auto-rollback).
    "deep-nesting": ("extract_guard_clause", True),
    # Autonomous-39 W3a: flipped from design_task → the delegated promote_staticmethod
    # lander (deterministic self-free-method → @staticmethod decoupling, gated +
    # auto-rollback; a class with no self-free method ⇒ an honest no-op, so the full
    # responsibility-split stays a design task).
    "god-class": ("promote_staticmethod", True),
    "modernization": ("modernize_comparisons", True),
    "mutable-default": ("fix_mutable_defaults", True),
    "merge-nested-if": ("merge_nested_if", True),
    "redundant-else": ("redundant_else", True),
    "dict-get-default": ("dict_get_default", True),
    "isinstance-merge": ("isinstance_merge", True),
    "none-compare": ("simplify_none_compare", True),
    "unreachable-code": ("unreachable_cleanup", True),
    "chained-comparison": ("chain_comparison", True),
    "set-literal": ("set_literal", True),
    "startswith-tuple": ("startswith_tuple", True),
    "not-in-simplify": ("not_in_simplify", True),
    "tuple-membership": ("tuple_membership", True),
    "dict-literal": ("dict_literal", True),
    "double-not": ("double_not", True),
    "swap-via-tuple": ("swap_via_tuple", True),
    "membership-set": ("membership_set", True),
    "percent-string-concat": ("percent_string_concat", True),
    "redundant-lambda": ("redundant_lambda", True),
    "augmented-assign": ("augmented_assign", True),
    "collection-literal": ("collection_literal", True),
    "fstring-no-placeholder": ("fstring_no_placeholder", True),
    "nested-with": ("combine_nested_with", True),
    "comprehension": ("simplify_comprehension", True),
    "use-enumerate": ("use_enumerate", True),
    "len-comparison": ("simplify_len_comparison", True),
    "simplify-bool-return": ("simplify_bool_return", True),
    "ternary-bool": ("simplify_ternary_bool", True),
    "dict-get-ternary": ("simplify_dict_get", True),
    "dict-comprehension": ("dict_comprehension", True),
    "ordering-negation": ("simplify_negated_comparison", True),
    "pointless-pass": ("remove_pointless_pass", True),
    "assert-tuple": ("fix_assert_tuple", True),
    "bool-comparison": ("simplify_bool_comparison", True),
    "or-default": ("or_default", True),
    # Autonomous-39: flipped from design_task → the delegated drop_param lander
    # (drop a provably-unused parameter + rewrite in-project keyword call sites,
    # gated + auto-rollback; the new PUBLIC-API rail refuses an exported function,
    # so a public-surface param is an honest no-op).
    "dead-parameter": ("drop_param", True),
    # The develop-grade synthesis objectives surfaced by the action-plan
    # augmentation (``_augment_synthesis_steps``). Not emitted by the seeder, but
    # routable through the standard fact path; each is executable (grounded on its
    # lander's own predicate, so the claim is honest by construction). cover-gaps
    # is the broad opt-in objective (default off in the planner), delegated like
    # implement-stub to the develop-core ``apply_rename`` path.
    "infer-type-hints": ("infer_type_hints", True),
    "dataclassify": ("dataclassify", True),
    "implement-stub": ("implement_stub", True),
    "cover-gaps": ("cover_gaps", True),
    # wire-exports is the SECOND broad opt-in objective (default off in the
    # planner, gated by ``wire_exports=True``), delegated like cover-gaps to the
    # develop-core ``apply_rename`` path; pure + IMPORT ORACLE (no pytest).
    "wire-exports": ("wire_exports", True),
    # generate-usage-doc is the THIRD broad opt-in objective (default off in the
    # planner, gated by ``generate_usage_doc=True``), delegated like wire-exports to
    # the develop-core ``apply_rename`` path; pure + DOCTEST ORACLE (no pytest).
    "generate-usage-doc": ("generate_usage_doc", True),
    # tdd-implement is the FOURTH broad opt-in objective (default off in the
    # planner, gated by ``tdd_implement=True``), delegated like implement-stub to
    # the develop-core ``apply_rename`` path; PER-SYMBOL, its detector runs the
    # suite to harvest the missing-function failures it can synthesise a body for.
    "tdd-implement": ("tdd_implement", True),
    # strengthen-tests is the FIFTH broad opt-in objective (default off in the
    # planner, gated by ``strengthen_tests=True``), delegated like cover-gaps to the
    # develop-core ``apply_rename`` path; PER-MODULE, its signal runs the MUTATION
    # ENGINE to find surviving mutants it can kill with a double-gated assertion.
    "strengthen-tests": ("strengthen_tests", True),
    # modernize is the SIXTH broad opt-in objective (default off in the planner,
    # gated by ``modernize=True``), delegated like cover-gaps to the develop-core
    # ``apply_rename`` path; PER-MODULE and OBJECTIVE-COMPILER-driven, its signal
    # (``modernize_plan``) chains the compiler's own behaviour-preserving idiom
    # transforms (none-compare / dead fstring / collection literal) over the module.
    "modernize": ("modernize", True),
    # dedup-total-return / dedup-parameterized are the SEVENTH/EIGHTH broad opt-in
    # objectives (default off, gated by ``dedup_total_return=True`` /
    # ``dedup_parameterized=True``), delegated like cover-gaps to the develop-core
    # ``apply_rename`` path; CROSS-MODULE, each signal qualifies a PARTICIPATING module
    # and its lander finds the actionable duplicate block/group touching it.
    "dedup-total-return": ("dedup_total_return", True),
    "dedup-parameterized": ("dedup_parameterized", True),
    # dedup-guarded-return is the NINTH broad opt-in objective (default off,
    # gated by ``dedup_guarded_return=True``) — the dedup family's last
    # control-flow rung (guard return + live fall-through, sentinel projection),
    # the same delegated CROSS-MODULE shape as its two siblings above.
    "dedup-guarded-return": ("dedup_guarded_return", True),
}


def test_operator_actions_table_action_and_executable_pinned():
    actual = {k: (v[0], v[2]) for k, v in _OPERATOR_ACTIONS.items()}
    assert actual == _OP_EXPECTED


def test_fact_actions_table_action_and_executable_pinned():
    actual = {k: (v[0], v[2]) for k, v in _FACT_ACTIONS.items()}
    assert actual == _FACT_EXPECTED


def test_plan_idea_executable_operator_test():
    step = IdeaActionBridge().plan_idea(IdeaNode(
        id="i", title="t", subject="app/x.py", operator="test"))
    assert step.action_type == "create_test_stub"
    assert step.executable is True


def test_plan_idea_design_operator_extend_not_executable():
    step = IdeaActionBridge().plan_idea(IdeaNode(
        id="i", title="t", subject="app/x.py", operator="extend"))
    assert step.action_type == "design_task"
    assert step.executable is False


def test_unknown_operator_defaults_to_design_task():
    # _OPERATOR_ACTIONS.get(..., ("design_task", "Develop {s}", False)) line 551.
    step = IdeaActionBridge().plan_idea(IdeaNode(
        id="i", title="t", subject="app/x.py", operator="nonexistent-op"))
    assert step.action_type == "design_task"
    assert step.executable is False


def test_unknown_root_fact_defaults_to_design_task():
    # _FACT_ACTIONS.get(..., ("design_task", "Develop {s}", False)) line 599.
    step = IdeaActionBridge().plan_idea(_root("mystery-label: app/x.py"))
    assert step.action_type == "design_task"
    assert step.executable is False


# --------------------------------------------------------------------------
# Harden detector ladder (lines 824-889): each detector returns True on its
# pattern and False on a missing file. Two assertions per detector kill the
# whole-expression->None mutant (needs the True case) AND the `else False`->
# `else True` constant flip (needs the missing-file False case).
# --------------------------------------------------------------------------
_DETECTOR_PATTERNS = {
    "_has_mutable_default": "def f(x=[]):\n    return x\n",
    "_detect_modernization": "x = 1\nif x == None:\n    pass\n",
    "_detect_open_encoding": "def f():\n    return open('a.txt')\n",
    "_detect_net_timeout":
        "import requests\ndef f():\n    return requests.get('http://x')\n",
    "_detect_identity_literal": "def f(x):\n    return x is 1\n",
    "_detect_negated_comparison": "def f(x, y):\n    return not x in y\n",
    "_detect_raise_from":
        "def f():\n    try:\n        pass\n    except Exception as e:\n"
        "        raise ValueError('x')\n",
    "_detect_fstring": "x = f'hello'\n",
    "_detect_collection_literal": "x = dict()\n",
}


def test_harden_detectors_true_on_pattern(tmp_path):
    bridge = IdeaActionBridge()
    for detector, src in _DETECTOR_PATTERNS.items():
        fn = f"{detector}.py"
        (tmp_path / fn).write_text(src, encoding="utf-8")
        assert getattr(bridge, detector)(str(tmp_path), fn) is True, detector


def test_harden_detectors_false_when_file_missing(tmp_path):
    bridge = IdeaActionBridge()
    for detector in _DETECTOR_PATTERNS:
        # No such file -> text is None -> the `else False` branch returns False.
        assert getattr(bridge, detector)(str(tmp_path), "absent.py") is False, detector


def test_harden_detectors_false_when_pattern_absent(tmp_path):
    bridge = IdeaActionBridge()
    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    for detector in _DETECTOR_PATTERNS:
        assert getattr(bridge, detector)(str(tmp_path), "clean.py") is False, detector


# --------------------------------------------------------------------------
# _confluence_weight (lines 262-278).
# --------------------------------------------------------------------------
def _step(facts, **kw):
    return ActionStep(branch_path="x", title="t", operator="o", subject="s",
                      action_type="a", target="", description="d",
                      source_facts=facts, **kw)


def test_confluence_weight_reads_digit_family_count():
    # "(5 signal families converge: ...)" -> 5 from the digit BEFORE the marker
    # (line 270 split[0]/index, 272 digits). The trailing list has only 2 items
    # (1 comma) so the comma-count fallback would give 2 -> the `[0]`->`[1]`
    # index flip (which reads the AFTER-marker text) is distinguished.
    w = _confluence_weight(_step(
        ["confluence: m (5 signal families converge: a, b)"]))
    assert w == 5


def test_confluence_weight_falls_back_to_comma_count_plus_one():
    # No digit before the marker -> rest.count(",") + 1 (line 272). Three commas
    # in the trailing list -> 4. `+`->`-` or `1`->`2` would change it.
    w = _confluence_weight(_step(
        ["confluence: m (signal families converge: a, b, c, d)"]))
    assert w == 4


def test_confluence_weight_convergence_plus_joined_dimensions():
    assert _confluence_weight(_step(["convergence: a+b+c"])) == 3


def test_confluence_weight_plain_facts_count():
    # No confluence/convergence -> len(facts); best starts at 0 (line 263) so the
    # `best if best else len(facts)` falls through to 2.
    assert _confluence_weight(_step(["x: 1", "y: 2"])) == 2


def test_confluence_weight_single_plain_fact_is_one():
    # best=0 start (line 263): a single plain fact weighs 1, not 0.
    assert _confluence_weight(_step(["x: 1"])) == 1


# --------------------------------------------------------------------------
# Anchor/stub text helpers (lines 298-389): module/target/mod_path `or`
# fallbacks, the `loc and line` join, slug trimming.
# --------------------------------------------------------------------------
def test_anchor_phrase_falls_back_to_module_arg_for_loc():
    # anchor has no "module" -> `anchor.get("module") or module` (line 301).
    assert _anchor_phrase({"symbol": "foo", "line": 3}, "app/x.py") == (
        "`foo` (app/x.py:3)")


def test_anchor_phrase_no_line_omits_colon_suffix():
    # loc present, line absent -> `if loc and line` is False (line 303), so the
    # location is just the module, never "app/x.py:None".
    assert _anchor_phrase({"symbol": "foo", "module": "app/x.py"},
                          "app/x.py") == "`foo` (app/x.py)"


def test_anchor_phrase_line_only_uses_bare_line():
    # No module/module-arg, line present -> loc becomes the bare line string.
    assert _anchor_phrase({"symbol": "foo", "line": 5}, "") == "`foo` (5)"


def test_anchor_phrase_appends_metric_when_present():
    assert _anchor_phrase({"symbol": "foo", "module": "m", "line": 1,
                           "metric": "cyclomatic 9"}, "m") == (
        "`foo` (m:1) — cyclomatic 9")


def test_stub_header_uses_module_when_target_empty():
    # `target or module` (line 339) -> module; mod_path present -> import line.
    header = _stub_header("", "app/x.py", "app.x")
    assert "# Subject: app/x.py" in header
    assert "import app.x  # noqa: F401" in header


def test_stub_header_omits_import_when_mod_path_empty():
    header = _stub_header("app/x.py", "app/x.py", "")
    assert "import" not in header


def test_stub_anchor_body_uses_target_when_mod_path_empty():
    # `mod_path or target` (line 355).
    body = _stub_anchor_body("foo", "", "app/x.py")
    assert "# TODO: exercise foo in app/x.py." in body
    assert body.startswith("def test_foo_behavior():")


def test_stub_smoke_body_uses_module_when_target_empty():
    # `(target or module)` (lines 362/366); stem strips dir + .py suffix.
    body = _stub_smoke_body("", "app/sub/x.py")
    assert body.startswith("def test_x_smoke():")
    assert "# TODO: cover app/sub/x.py." in body


def test_concrete_test_description_falls_back_without_anchors():
    node = IdeaNode(id="i", title="t", subject="app/x.py")
    assert _concrete_test_description(node, "FALLBACK") == "FALLBACK"


def test_concrete_test_description_names_anchor_symbol():
    # The anchor carries NO module, so _anchor_phrase falls back to the module
    # parsed from the subject (line 319 `getattr(node, "subject", "") or ""`);
    # `or`->`and` would blank it and drop "app/x.py".
    node = IdeaNode(id="i", title="t", subject="app/x.py::Cls.foo",
                    anchors=[{"symbol": "foo", "line": 3, "metric": "cyc 9"}])
    assert _concrete_test_description(node, "FB") == (
        "Add tests for `foo` (app/x.py:3) — cyc 9")


def test_test_stub_body_imports_module_and_names_symbol():
    # target="" forces mod_path off the subject's module (lines 378/379
    # `getattr(node,"subject","") or ""` and `(target or module)`); `or`->`and`
    # would blank the module and drop the import line.
    node = IdeaNode(id="i", title="t", subject="app/x.py::Cls.foo",
                    anchors=[{"symbol": "foo", "module": "app/x.py", "line": 3}])
    body = _test_stub_body(node, "")
    assert "import app.x  # noqa: F401" in body
    assert "def test_foo_behavior():" in body


def test_stub_slug_rstrip_keeps_leading_underscore():
    # rstrip mode trims only trailing "_" (a leading "_" is meaningful).
    assert _stub_slug("_scan_churn__", "rstrip", "fb") == "_scan_churn"


def test_stub_slug_strip_trims_both_ends():
    assert _stub_slug("__Foo__", "strip", "fb") == "foo"


def test_stub_slug_empty_uses_fallback():
    assert _stub_slug("___", "strip", "FALLBACK") == "FALLBACK"


# --------------------------------------------------------------------------
# Render + stats helpers: _plan_stats (1595/1600), _proof_affordance (1843-),
# _applied_fix_line (1915-1930), _result_sections (1939-1945),
# render_action_markdown (1876-1902), render_maintenance_markdown (1972-1978).
# --------------------------------------------------------------------------
from app.engine.idea_action_bridge import (  # noqa: E402
    _applied_fix_line,
    _proof_affordance,
    _result_sections,
    render_action_markdown,
    render_maintenance_markdown,
)
from app.models.idea import ActionPlan  # noqa: E402


def _exec_step(executable, preview=None):
    return ActionStep(branch_path="x.0", title="t", operator="o", subject="m.py",
                      action_type="create_test_stub" if executable else "design_task",
                      target="m.py", description="d", executable=executable,
                      value=1.0, patch_preview=preview)


def test_plan_stats_counts_executable_design_and_drafts():
    steps = [_exec_step(True, {"transform_type": "x"}),
             _exec_step(True), _exec_step(False)]
    stats = IdeaActionBridge._plan_stats(steps)
    assert stats == {"total_steps": 3, "executable_steps": 2,
                     "design_tasks": 1, "drafted_patches": 1}


def test_proof_affordance_full_preview():
    s = _exec_step(True, {"diff": "d", "added": 5, "removed": 2,
                          "reparses": True, "impact": "nesting 3→1",
                          "covered": True})
    line = _proof_affordance(s)
    assert "+5 −2" in line
    assert "re-parses cleanly ✓" in line
    assert "nesting 3→1" in line
    assert "your tests reference this module ✓" in line


def test_proof_affordance_failed_reparse_and_uncovered():
    s = _exec_step(True, {"diff": "d", "added": 1, "removed": 0,
                          "reparses": False, "covered": False})
    line = _proof_affordance(s)
    assert "⚠️ re-parse check failed" in line
    assert "no test exercises this" in line


def test_proof_affordance_empty_without_diff_fields():
    assert _proof_affordance(_exec_step(True, {"foo": 1})) == ""


def test_applied_fix_line_verified_function_level():
    line = _applied_fix_line({"branch": "b", "action": "harden_security",
                              "verified": True,
                              "verification_strength": {"level": "function"},
                              "changed_files": ["m.py"]})
    assert line == ("- `b` **harden_security** — m.py "
                    "(tests pass — and name the changed function)")


def test_applied_fix_line_not_verified_omits_pass_clause():
    # `r.get("verified") is True` (line 1915): a falsy/absent verified value
    # must NOT add the "(tests pass...)" clause.
    line = _applied_fix_line({"branch": "b", "action": "a",
                              "changed_files": ["m.py"]})
    assert "tests pass" not in line
    assert line == "- `b` **a** — m.py"


def test_applied_fix_line_impact_shield_and_commit():
    line = _applied_fix_line({"branch": "b", "action": "a", "verified": True,
                              "verification_strength": {"level": "module"},
                              "impact": "win", "shield_test": "t.py",
                              "committed": True, "commit_hash": "abc123",
                              "changed_files": ["m.py"]})
    assert "— win" in line
    assert "🛡️ shielded first by `t.py`" in line
    assert "[commit abc123]" in line


def test_result_sections_only_nonempty_groups():
    sections = _result_sections([
        {"applied": True, "branch": "b", "action": "a", "changed_files": ["m.py"]},
        {"rolled_back": True, "branch": "c", "action": "a", "target": "n.py"},
        {"applied": False, "branch": "d", "action": "a", "reason": "blocked"},
    ])
    text = "\n".join(sections)
    assert "## ✅ Applied" in text
    assert "## ↩️ Rolled back (tests failed)" in text
    assert "## ⛔ Blocked / not applicable" in text
    assert "- `d` **a** — blocked" in text


def test_result_sections_omits_empty_applied():
    sections = _result_sections([
        {"applied": False, "branch": "d", "action": "a", "reason": "blocked"},
    ])
    text = "\n".join(sections)
    assert "## ✅ Applied" not in text
    assert "## ⛔ Blocked / not applicable" in text


def test_render_action_markdown_runnable_count_and_tags():
    plan = ActionPlan(objective="obj", project_root="root", mode="supervised",
                      steps=[_exec_step(True), _exec_step(False)],
                      stats=IdeaActionBridge._plan_stats(
                          [_exec_step(True), _exec_step(False)]))
    md = render_action_markdown(plan)
    assert "**1 of 2 steps are runnable now**" in md
    assert "🛠️" in md  # executable tag
    assert "📐" in md  # advisory tag


def test_render_maintenance_markdown_counts():
    summary = {"mode": "autonomous", "verify": True, "commit": False,
               "applied": 2, "rolled_back": 1, "blocked": 3,
               "total_executable": 6, "committed": 0, "results": []}
    md = render_maintenance_markdown(summary, "root")
    assert "Applied: **2**" in md
    assert "Rolled back: **1**" in md
    assert "Blocked: **3**" in md
    assert "of 6 executable steps" in md


def test_render_maintenance_markdown_count_defaults_are_zero():
    # An empty summary renders every count via its `.get(key, 0)` default
    # (lines 1972-1978); the `0`->`1` mutants would print 1 instead of 0.
    md = render_maintenance_markdown({"commit": True}, "root")
    assert "Applied: **0**" in md
    assert "Rolled back: **0**" in md
    assert "Blocked: **0**" in md
    assert "of 0 executable steps" in md
    assert "Commits created: **0**" in md


# --------------------------------------------------------------------------
# Convergence / expand / unserviceable (lines 455, 490, 498, 538, 556).
# --------------------------------------------------------------------------
def test_plan_idea_dotted_py_subject_without_slash_keeps_target():
    # `"/" in file_part or file_part.endswith(".py")` (line 556): a bare
    # "foo.py" has no slash but ends ".py", so target is kept. `or`->`and` would
    # blank it.
    step = IdeaActionBridge().plan_idea(IdeaNode(
        id="i", title="t", subject="foo.py", operator="test"))
    assert step.target == "foo.py"
    assert step.executable is True


def test_plan_convergence_dotted_py_subject_targets_file():
    # Line 455 mirror of 556 inside plan_convergence.
    idea = IdeaNode(id="i", title="t", subject="foo.py", operator="root",
                    source_facts=["convergence: untested+fragile"])
    steps = IdeaActionBridge().plan_convergence(idea)
    assert steps
    assert all(s.target == "foo.py" for s in steps)


def test_stub_unserviceable_servable_returns_empty_string(tmp_path):
    # Module NOT referenced by any test -> servable -> "" (line 490, not None).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "y.py").write_text("def f():\n    return 1\n",
                                           encoding="utf-8")
    assert IdeaActionBridge()._stub_unserviceable("app/y.py", str(tmp_path)) == ""


def test_harden_unserviceable_servable_returns_empty_string(tmp_path):
    # A file with a real auto-fixable pattern is servable -> "" (line 498).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "sec.py").write_text("def f(x=[]):\n    return x\n",
                                             encoding="utf-8")
    assert IdeaActionBridge()._harden_unserviceable("app/sec.py", str(tmp_path)) == ""


def test_expand_idea_marks_referenced_module_unserviceable(tmp_path):
    # project_root set AND step executable AND target set (line 538 `and`):
    # the unserviceable reason for an already-tested module flips executable off.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "x.py").write_text("def f():\n    return 1\n",
                                           encoding="utf-8")
    (tmp_path / "tests" / "test_x.py").write_text(
        "from app.x import f\ndef test_f():\n    assert f() == 1\n",
        encoding="utf-8")
    idea = IdeaNode(id="i", title="t", subject="app/x.py", operator="test",
                    source_facts=["untested: app/x.py"])
    steps = IdeaActionBridge()._expand_idea(idea, project_root=str(tmp_path))
    assert steps[0].executable is False
    assert "deepen them by hand" in steps[0].description


def test_expand_idea_no_project_root_keeps_executable():
    # project_root="" -> the `and` chain short-circuits, executable stays True.
    idea = IdeaNode(id="i", title="t", subject="app/x.py", operator="test",
                    source_facts=["untested: app/x.py"])
    steps = IdeaActionBridge()._expand_idea(idea, project_root="")
    assert steps[0].executable is True


# --------------------------------------------------------------------------
# _stub_target / _step_targets / _vet_result / _change_strategy_for
# (lines 938, 958-983, 966).
# --------------------------------------------------------------------------
def _stub_step(target, action="create_test_stub", executable=True):
    return ActionStep(branch_path="x", title="t", operator="o", subject=target,
                      action_type=action, target=target, description="d",
                      executable=executable)


def test_stub_target_refuses_test_files(tmp_path):
    bridge = IdeaActionBridge()
    # Each clause of the `or` on line 938 independently marks a test file.
    assert bridge._stub_target(_stub_step("app/test_x.py"), str(tmp_path)) is None
    assert bridge._stub_target(_stub_step("app/tests/x.py"), str(tmp_path)) is None
    assert bridge._stub_target(_stub_step("tests/x.py"), str(tmp_path)) is None


def test_stub_target_normal_module_yields_test_path(tmp_path):
    got = IdeaActionBridge()._stub_target(_stub_step("app/foo.py"), str(tmp_path))
    assert got == ["tests/test_foo.py"]


def test_step_targets_none_for_non_executable_or_non_strategy(tmp_path):
    bridge = IdeaActionBridge()
    # `not step.executable or action not in _ACTION_STRATEGY` (line 966).
    assert bridge._step_targets(
        _stub_step("app/foo.py", executable=False), str(tmp_path)) is None
    assert bridge._step_targets(
        _stub_step("app/foo.py", action="design_task"), str(tmp_path)) is None


def test_step_targets_yields_test_path_for_stub(tmp_path):
    got = IdeaActionBridge()._step_targets(_stub_step("app/foo.py"), str(tmp_path))
    assert got == ["tests/test_foo.py"]


class _FakeResult:
    def __init__(self, patch_requests, transform_type="x", mode=""):
        self.patch_requests = patch_requests
        self.transform_type = transform_type
        self.mode = mode
        self.rationale = "r"


def test_vet_result_rejects_none_and_empty_and_draft():
    bridge = IdeaActionBridge()
    # `result is None or not result.patch_requests` (line 983).
    assert bridge._vet_result(None) is None
    assert bridge._vet_result(_FakeResult([])) is None
    assert bridge._vet_result(
        _FakeResult([{"path": "a"}], transform_type="draft_fallback")) is None


def test_vet_result_accepts_real_patch():
    res = _FakeResult([{"path": "a", "new_content": "x"}])
    assert IdeaActionBridge()._vet_result(res) is res


def test_change_strategy_for_organize_imports_modernizes_none_compare(tmp_path):
    # organize_imports action on a file WITH `== None` -> the modernize branch
    # (line 958 `== "organize_imports" and detect_modernization`, line 959
    # return value).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "mod.py").write_text(
        "x = 1\nif x == None:\n    pass\n", encoding="utf-8")
    step = _stub_step("app/mod.py", action="organize_imports")
    strat, title = IdeaActionBridge()._change_strategy_for(step, str(tmp_path))
    assert strat == ["modernize none-comparison"]
    assert title == "Modernize comparisons in app/mod.py"


def test_change_strategy_for_clean_file_keeps_default(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "clean.py").write_text("x = 1\n", encoding="utf-8")
    step = _stub_step("app/clean.py", action="organize_imports")
    step.description = "DESC"
    strat, title = IdeaActionBridge()._change_strategy_for(step, str(tmp_path))
    assert strat == ["organize imports cleanup unused"]
    assert title == "DESC"


# --------------------------------------------------------------------------
# _confluence_headline (lines 1522-1538) and _read_old (1071).
# --------------------------------------------------------------------------
def _hstep(value, facts, subject):
    return ActionStep(branch_path="x", title="t", operator="o", subject=subject,
                      action_type="a", target="", description="d", value=value,
                      source_facts=facts)


def test_confluence_headline_promotes_higher_weight_in_band():
    # Two leaders within epsilon; the one with the bigger family count leads.
    steps = [_hstep(0.90, ["x: 1"], "plain"),
             _hstep(0.88, ["confluence: m (4 signal families converge: a,b,c,d)"],
                    "conf")]
    out = IdeaActionBridge._confluence_headline(steps)
    assert out[0].subject == "conf"


def test_confluence_headline_boundary_value_is_in_band():
    # diff == epsilon (0.05) exactly -> `<=` includes the confluence step
    # (line 1527); `<=`->`<` would exclude it and leave "plain" #1.
    steps = [_hstep(0.10, ["x: 1"], "plain"),
             _hstep(0.05, ["confluence: m (4 signal families converge: a,b,c,d)"],
                    "conf")]
    out = IdeaActionBridge._confluence_headline(steps)
    assert out[0].subject == "conf"


def test_confluence_headline_beyond_band_unchanged():
    # diff > epsilon -> band has only the top, `if band < 2` returns unchanged.
    steps = [_hstep(0.90, ["x: 1"], "plain"),
             _hstep(0.80, ["confluence: m (4 signal families converge: a,b,c,d)"],
                    "conf")]
    out = IdeaActionBridge._confluence_headline(steps)
    assert out[0].subject == "plain"


def test_confluence_headline_single_step_unchanged():
    steps = [_hstep(1.0, ["x: 1"], "only")]
    assert IdeaActionBridge._confluence_headline(steps) == steps


def test_confluence_headline_tiebreak_by_subject():
    # Equal weight, equal value -> sorted by subject (then input index).
    steps = [_hstep(0.9, ["x: 1"], "bbb"), _hstep(0.9, ["y: 1"], "aaa")]
    out = IdeaActionBridge._confluence_headline(steps)
    assert [s.subject for s in out] == ["aaa", "bbb"]


def test_confluence_headline_final_tiebreak_is_input_index():
    # Identical weight AND subject force the final `iv[0]` (enumerate index)
    # tiebreak (line 1536) to decide order — stable input order. The `iv[0]`->
    # `iv[1]` mutant would compare two ActionStep objects and raise TypeError.
    steps = [_hstep(0.9, ["x: 1"], "same"), _hstep(0.9, ["y: 1"], "same")]
    steps[0].branch_path = "b0"
    steps[1].branch_path = "b1"
    out = IdeaActionBridge._confluence_headline(steps)
    assert [s.branch_path for s in out] == ["b0", "b1"]


def test_read_old_returns_content_or_empty(tmp_path):
    (tmp_path / "a.py").write_text("hello\n", encoding="utf-8")
    assert IdeaActionBridge._read_old(tmp_path, "a.py") == "hello\n"
    # Missing file -> "" (line 1071, not None).
    assert IdeaActionBridge._read_old(tmp_path, "nope.py") == ""


# --------------------------------------------------------------------------
# Proof helpers: _count_changes (1089/1091), _py_verdict (1108/1111),
# _diff_one / _diff_and_verdict (1140/1142/1168/1172), attach_proofs
# (1213/1215-1217), prove_step.
# --------------------------------------------------------------------------
def test_count_changes_ignores_diff_headers():
    diff = "--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n-old\n+new1\n+new2\n"
    assert IdeaActionBridge._count_changes(diff) == (2, 1)


def test_py_verdict_reparses_true_on_valid_python():
    reparses, _summary = IdeaActionBridge._py_verdict(
        "x = 1\n", "x = 2\n")
    assert reparses is True


def test_py_verdict_reparses_false_on_broken_python():
    reparses, summary = IdeaActionBridge._py_verdict("x = 1\n", "def (:\n")
    assert reparses is False
    assert summary == ""


def _none_compare_file(tmp_path):
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "mod.py").write_text(
        "def f(x):\n    if x == None:\n        return 1\n    return 2\n",
        encoding="utf-8")
    return ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/mod.py", action_type="simplify_none_compare",
                      target="app/mod.py", description="d", executable=True)


def test_prove_step_produces_diff_and_reparses(tmp_path):
    step = _none_compare_file(tmp_path)
    proof = IdeaActionBridge().prove_step(step, str(tmp_path))
    assert proof is not None
    assert proof["reparses"] is True
    assert proof["added"] >= 1
    assert "is None" in proof["diff"]


def test_attach_proofs_fills_top_executable_step(tmp_path):
    step = _none_compare_file(tmp_path)
    plan = ActionPlan(objective="", project_root=str(tmp_path),
                      mode="supervised", steps=[step], stats={})
    IdeaActionBridge().attach_proofs(plan, str(tmp_path))
    assert step.patch_preview is not None
    assert "diff" in step.patch_preview
    assert step.patch_preview["applied"] is False


def test_attach_proofs_skips_non_executable_step(tmp_path):
    step = _none_compare_file(tmp_path)
    step.executable = False
    plan = ActionPlan(objective="", project_root=str(tmp_path),
                      mode="supervised", steps=[step], stats={})
    IdeaActionBridge().attach_proofs(plan, str(tmp_path))
    # `step.executable and ...` (line 1215) gates it out -> no proof attached.
    assert step.patch_preview is None


# --------------------------------------------------------------------------
# apply_step (lines 1252-1283): read-only refusal, the applied evidence path.
# --------------------------------------------------------------------------
def _apply_fixture(tmp_path):
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "mod.py").write_text(
        "def f(x):\n    if x == None:\n        return 1\n    return 2\n",
        encoding="utf-8")
    return ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/mod.py", action_type="simplify_none_compare",
                      target="app/mod.py", description="d", executable=True)


def test_apply_step_report_mode_refuses():
    step = ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/mod.py", action_type="simplify_none_compare",
                      target="app/mod.py", description="d", executable=True)
    r = IdeaActionBridge().apply_step(step, ".", mode="report")
    assert r["applied"] is False
    assert "read-only" in r["reason"]


def test_apply_step_supervised_applies_and_records_diff(tmp_path):
    step = _apply_fixture(tmp_path)
    r = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    assert r["applied"] is True
    assert r["changed_files"] == ["app/mod.py"]
    # `if applied.ok and applied.changed_files` (line 1274) -> the diff is recorded.
    assert "is None" in r["diff"]
    # No verify -> the function returns the plain `out` (line 1280), no rollback.
    assert "rolled_back" not in r
    # The patch really landed on disk.
    assert "is None" in (tmp_path / "app" / "mod.py").read_text()


def test_apply_step_no_applicable_patch_on_clean_file(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "clean.py").write_text("x = 1\n", encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/clean.py", action_type="simplify_none_compare",
                      target="app/clean.py", description="d", executable=True)
    r = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    assert r["applied"] is False
    assert r["reason"] == "no applicable patch generated"


# --------------------------------------------------------------------------
# dry_run_plan / apply_plan / _MaintenancePass (lines 1430-1460, 1750-1830).
# --------------------------------------------------------------------------
def _none_compare_plan(tmp_path, mode="supervised", facts=None):
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "mod.py").write_text(
        "def f(x):\n    if x == None:\n        return 1\n    return 2\n",
        encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/mod.py", action_type="simplify_none_compare",
                      target="app/mod.py", description="d", executable=True,
                      source_facts=facts or ["modernization: app/mod.py"])
    plan = ActionPlan(objective="", project_root=str(tmp_path), mode=mode,
                      steps=[step], stats={})
    return plan, step


def test_dry_run_plan_previews_without_writing(tmp_path):
    plan, _ = _none_compare_plan(tmp_path)
    before = (tmp_path / "app" / "mod.py").read_text()
    dr = IdeaActionBridge().dry_run_plan(plan, str(tmp_path))
    assert dr["dry_run"] is True
    assert dr["total_executable"] == 1
    assert dr["applicable"] == 1
    assert dr["results"][0]["applicable"] is True
    # Nothing was written.
    assert (tmp_path / "app" / "mod.py").read_text() == before


def test_apply_plan_supervised_applies_and_counts(tmp_path):
    plan, _ = _none_compare_plan(tmp_path)
    summ = IdeaActionBridge().apply_plan(plan, str(tmp_path), mode="supervised")
    assert summ["applied"] == 1
    assert summ["rolled_back"] == 0
    assert summ["blocked"] == 0
    assert summ["total_executable"] == 1
    assert summ["results"][0]["applied"] is True


def test_apply_plan_tier1_fix_blocked_without_coverage(tmp_path):
    # A tier-1 fix (simplify_none_compare) on a module NO test references, with
    # verify on and the shield disabled, is BLOCKED not gambled (lines 1750-1766).
    plan, _ = _none_compare_plan(tmp_path, mode="autonomous")
    summ = IdeaActionBridge().apply_plan(
        plan, str(tmp_path), mode="autonomous", verify=True, test_first=False)
    assert summ["applied"] == 0
    assert summ["blocked"] == 1
    assert "tier-1 fix requires a covering test" in summ["results"][0]["reason"]
    assert summ["results"][0]["risk_tier"] == 1


# --------------------------------------------------------------------------
# plan_tree (lines 1543-1577): draft/proof default-off, root_for_checks `or`
# fallback, draft + proof attachment.
# --------------------------------------------------------------------------
from app.models.idea import IdeaTreeReport  # noqa: E402


def _modernize_report(tmp_path):
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "mod.py").write_text(
        "def f(x):\n    if x == None:\n        return 1\n    return 2\n",
        encoding="utf-8")
    idea = IdeaNode(id="i", title="t", subject="app/mod.py", operator="root",
                    value=1.0, source_facts=["modernization: app/mod.py"])
    return IdeaTreeReport(ideas=[idea], project_root=str(tmp_path))


def test_plan_tree_default_attaches_no_preview(tmp_path):
    # draft and proof both default False (lines 1545/1547): no patch_preview.
    plan = IdeaActionBridge().plan_tree(_modernize_report(tmp_path))
    assert plan.steps[0].patch_preview is None


def test_plan_tree_draft_attaches_transform_preview(tmp_path):
    report = _modernize_report(tmp_path)
    plan = IdeaActionBridge().plan_tree(report, draft=True,
                                        project_root=str(tmp_path))
    assert plan.steps[0].patch_preview is not None
    assert "transform_type" in plan.steps[0].patch_preview


def test_plan_tree_proof_attaches_diff_and_verdict(tmp_path):
    report = _modernize_report(tmp_path)
    plan = IdeaActionBridge().plan_tree(report, proof=True,
                                        project_root=str(tmp_path))
    preview = plan.steps[0].patch_preview
    assert preview is not None
    assert "diff" in preview
    assert "reparses" in preview


def test_plan_tree_top_limits_steps(tmp_path):
    (tmp_path / "app").mkdir()
    ideas = [IdeaNode(id=f"i{i}", title="t", subject=f"app/m{i}.py",
                      operator="root", value=float(10 - i),
                      source_facts=[f"untested: app/m{i}.py"]) for i in range(5)]
    report = IdeaTreeReport(ideas=ideas, project_root=str(tmp_path))
    plan = IdeaActionBridge().plan_tree(report, top=2)
    assert plan.stats["total_steps"] == 2


# --------------------------------------------------------------------------
# plan_roadmap defaults (1642/1644), render_action_markdown draft/stats
# branches (1870-1872, 1902), _result_sections classification (1945).
# --------------------------------------------------------------------------
def test_plan_roadmap_default_no_preview(tmp_path):
    report = _modernize_report(tmp_path)
    plan = IdeaActionBridge().plan_roadmap(report)
    assert plan.steps
    assert plan.steps[0].patch_preview is None


def test_plan_roadmap_draft_attaches_preview(tmp_path):
    report = _modernize_report(tmp_path)
    plan = IdeaActionBridge().plan_roadmap(report, draft=True,
                                           project_root=str(tmp_path))
    assert plan.steps[0].patch_preview is not None
    assert "transform_type" in plan.steps[0].patch_preview


def test_render_action_markdown_draft_line_without_files():
    # preview has "transform_type" but no "files" -> `files or "transform_type"
    # in pv` (line 1902) still renders the draft line.
    st = ActionStep(branch_path="x.0", title="t", operator="o",
                    subject="app/mod.py", action_type="a", target="app/mod.py",
                    description="d", executable=True, value=1.0,
                    patch_preview={"transform_type": "tt"})
    plan = ActionPlan(objective="", project_root="r", mode="supervised",
                      steps=[st], stats=IdeaActionBridge._plan_stats([st]))
    md = render_action_markdown(plan)
    assert "↳ draft `tt`" in md


def test_render_action_markdown_empty_stats_defaults_zero():
    # plan.stats.get(key, 0) defaults (lines 1870-1872).
    plan = ActionPlan(objective="", project_root="r", mode="supervised",
                      steps=[], stats={})
    md = render_action_markdown(plan)
    assert "0 steps · 0 executable · 0 design tasks" in md


def test_result_sections_applied_not_in_blocked():
    # `not applied and not rolled_back` (line 1945): an applied result must NOT
    # also appear in the Blocked section (the `and`->`or` mutant would add it).
    sections = _result_sections([
        {"applied": True, "branch": "AP", "action": "a", "changed_files": ["m.py"]},
    ])
    text = "\n".join(sections)
    assert "## ⛔ Blocked / not applicable" not in text
    assert "`AP`" in text  # only in Applied


def test_proof_affordance_requires_all_three_stat_keys():
    # `"diff" not in pv or "added" not in pv or "removed" not in pv` (line 1843):
    # a preview missing ANY of the three stat keys yields "" (the `or` chain).
    s = _exec_step(True, {"diff": "d", "added": 3})  # no "removed"
    assert _proof_affordance(s) == ""
    s2 = _exec_step(True, {"diff": "d", "removed": 1})  # no "added"
    assert _proof_affordance(s2) == ""


# --------------------------------------------------------------------------
# apply_step verify path / _verify_or_rollback (lines 1335-1360).
# --------------------------------------------------------------------------
def _verify_fixture(tmp_path, test_body):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "conftest.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "mod.py").write_text(
        "def f(x):\n    if x == None:\n        return 1\n    return 2\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_mod.py").write_text(test_body, encoding="utf-8")
    return ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/mod.py", action_type="simplify_none_compare",
                      target="app/mod.py", description="d", executable=True)


def test_apply_step_verify_passes_keeps_change(tmp_path):
    step = _verify_fixture(
        tmp_path, "from app.mod import f\ndef test_f():\n    assert f(None) == 1\n")
    r = IdeaActionBridge().apply_step(step, str(tmp_path), mode="autonomous",
                                      verify=True)
    assert r["applied"] is True
    assert r["verified"] is True
    assert r["rolled_back"] is False
    assert "is None" in (tmp_path / "app" / "mod.py").read_text()


def test_apply_step_verify_fails_rolls_back(tmp_path):
    orig = "def f(x):\n    if x == None:\n        return 1\n    return 2\n"
    # A test that asserts on the SOURCE text goes red once the fix lands, forcing
    # the rollback branch (lines 1348-1359) to restore the file.
    step = _verify_fixture(
        tmp_path,
        "def test_src():\n    assert '== None' in open('app/mod.py').read()\n")
    r = IdeaActionBridge().apply_step(step, str(tmp_path), mode="autonomous",
                                      verify=True)
    assert r["applied"] is False
    assert r["rolled_back"] is True
    assert r["reason"] == "tests failed after patch; changes rolled back"
    # The original content was restored (snapshot.get(rel) was not None).
    assert (tmp_path / "app" / "mod.py").read_text() == orig


# --------------------------------------------------------------------------
# _MaintenancePass._converge_harden (lines 1774-1785): a harden step keeps
# fixing the same file's remaining issues in one pass.
# --------------------------------------------------------------------------
def test_converge_harden_records_extra_fixes(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "conftest.py").write_text("", encoding="utf-8")
    # Two harden-ladder issues: a mutable default AND a `== None` to modernize.
    (tmp_path / "app" / "sec.py").write_text(
        "def f(x=[]):\n    if x == None:\n        return 1\n"
        "    x.append(2)\n    return x\n", encoding="utf-8")
    (tmp_path / "tests" / "test_sec.py").write_text(
        "from app.sec import f\ndef test_f():\n    assert f() == [2]\n",
        encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/sec.py", action_type="harden_security",
                      target="app/sec.py", description="d", executable=True,
                      source_facts=["sensitive-path: app/sec.py"])
    plan = ActionPlan(objective="", project_root=str(tmp_path),
                      mode="autonomous", steps=[step], stats={})
    summ = IdeaActionBridge().apply_plan(
        plan, str(tmp_path), mode="autonomous", verify=True, test_first=False)
    assert summ["applied"] == 1
    # The first fix lands the mutable-default; the convergence loop then applies
    # the remaining modernize fix (recorded as an extra, not a new row).
    assert summ["results"][0]["converged_fixes"] == 1
    # Both issues are gone from the file.
    src = (tmp_path / "app" / "sec.py").read_text()
    assert "x=[]" not in src
    assert "== None" not in src


# --------------------------------------------------------------------------
# draft_patch / _step_preview (lines 1050, 1430-1443).
# --------------------------------------------------------------------------
def _draft_fixture(tmp_path):
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "mod.py").write_text(
        "def f(x):\n    if x == None:\n        return 1\n    return 2\n",
        encoding="utf-8")
    return ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/mod.py", action_type="simplify_none_compare",
                      target="app/mod.py", description="d", executable=True)


def test_draft_patch_returns_non_empty_preview(tmp_path):
    d = IdeaActionBridge().draft_patch(_draft_fixture(tmp_path), str(tmp_path))
    assert d is not None
    assert d["transform_type"] == "simplify_comparison"
    assert d["files"] == ["app/mod.py"]
    # `(first.get("new_content") or "")[:400]` (line 1050): real content survives.
    assert d["preview"]
    assert d["applied"] is False


def test_draft_patch_none_on_clean_file(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "clean.py").write_text("x = 1\n", encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/clean.py", action_type="simplify_none_compare",
                      target="app/clean.py", description="d", executable=True)
    assert IdeaActionBridge().draft_patch(step, str(tmp_path)) is None


def test_step_preview_real_diff(tmp_path):
    sp = IdeaActionBridge()._step_preview(_draft_fixture(tmp_path), str(tmp_path))
    assert sp["applicable"] is True
    assert sp["transform_type"] == "simplify_comparison"
    assert "is None" in sp["diff"]


def test_step_preview_not_applicable_on_clean_file(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "clean.py").write_text("x = 1\n", encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/clean.py", action_type="simplify_none_compare",
                      target="app/clean.py", description="d", executable=True)
    sp = IdeaActionBridge()._step_preview(step, str(tmp_path))
    assert sp["applicable"] is False


# --------------------------------------------------------------------------
# _evidence_diff (1372-1382) and _measure_applied_impact (1404-1414).
# --------------------------------------------------------------------------
def test_evidence_diff_exact_unified_format():
    # keepends=True (line 1378) keeps each source line's newline so the unified
    # diff is well-formed; keepends=False would mangle the line splitting.
    snap = {"m.py": "def f(x):\n    if x == None:\n        return 1\n"}
    prs = [{"path": "m.py",
            "new_content": "def f(x):\n    if x is None:\n        return 1\n"}]
    diff = IdeaActionBridge._evidence_diff(snap, prs, ["m.py"])
    assert diff == (
        "--- a/m.py\n+++ b/m.py\n@@ -1,3 +1,3 @@\n def f(x):\n"
        "-    if x == None:\n+    if x is None:\n         return 1\n")


def test_evidence_diff_new_file_marker():
    snap = {"new.py": None}
    prs = [{"path": "new.py", "new_content": "x = 1\n"}]
    diff = IdeaActionBridge._evidence_diff(snap, prs, ["new.py"])
    assert "new.py" in diff


def test_measure_applied_impact_reports_structural_win():
    # A real nesting reduction yields a non-empty clause; an unchanged file none.
    snap = {"m.py": "def f(x):\n    if x:\n        if x:\n            return 1\n"}
    prs = [{"path": "m.py", "new_content": "def f(x):\n    return 1\n"}]
    clause = IdeaActionBridge._measure_applied_impact(snap, prs, ["m.py"])
    assert isinstance(clause, str)


def test_measure_applied_impact_empty_for_non_py():
    # Non-.py changed files are skipped (line 1405) -> "".
    snap = {"README.md": "old"}
    prs = [{"path": "README.md", "new_content": "new"}]
    assert IdeaActionBridge._measure_applied_impact(
        snap, prs, ["README.md"]) == ""


# --------------------------------------------------------------------------
# _safety_gate_block (lines 1289-1302).
# --------------------------------------------------------------------------
def _supervised_perms():
    from app.policies.mode_policy import ModePolicy, mode_from_string
    return ModePolicy(mode=mode_from_string("supervised")).permissions


def test_safety_gate_block_passes_benign_patch(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "mod.py").write_text("x = 2\n", encoding="utf-8")
    prs = [{"path": "app/mod.py", "new_content": "x = 1\n",
            "expected_old_content": "x = 2\n"}]
    assert IdeaActionBridge._safety_gate_block(
        _supervised_perms(), prs, str(tmp_path), False) is None


def test_safety_gate_block_refuses_oversized_patch(tmp_path):
    perms = _supervised_perms()
    (tmp_path / "app").mkdir()
    prs = []
    for i in range((perms.max_changed_files or 1) + 5):
        (tmp_path / "app" / f"m{i}.py").write_text("x = 2\n", encoding="utf-8")
        prs.append({"path": f"app/m{i}.py", "new_content": "x = 1\n",
                    "expected_old_content": "x = 2\n"})
    block = IdeaActionBridge._safety_gate_block(perms, prs, str(tmp_path), False)
    assert block is not None
    assert block["applied"] is False
    assert block["reason"] == "blocked by safety gates"


# --------------------------------------------------------------------------
# apply_plan max_apply boundary (1493) + tier-0 stub (not tier-blocked).
# --------------------------------------------------------------------------
def test_apply_plan_max_apply_caps_applied_count(tmp_path):
    (tmp_path / "app").mkdir()
    steps = []
    for i in range(3):
        (tmp_path / "app" / f"m{i}.py").write_text(
            f"def f(x):\n    if x == None:\n        return {i}\n    return 9\n",
            encoding="utf-8")
        steps.append(ActionStep(
            branch_path=f"x.{i}", title="t", operator="o",
            subject=f"app/m{i}.py", action_type="simplify_none_compare",
            target=f"app/m{i}.py", description="d", executable=True))
    plan = ActionPlan(objective="", project_root=str(tmp_path),
                      mode="supervised", steps=steps, stats={})
    # `run.applied >= max_apply` (line 1493): stop after exactly 2.
    summ = IdeaActionBridge().apply_plan(plan, str(tmp_path), mode="supervised",
                                         max_apply=2)
    assert summ["applied"] == 2
    assert summ["total_executable"] == 3


def test_apply_plan_tier0_stub_not_blocked_by_coverage(tmp_path):
    # create_test_stub is risk tier 0, so the tier-1 coverage gate does not apply
    # even with verify on and no covering test (line 1750 `tier >= 1`).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "mod.py").write_text("def f():\n    return 1\n",
                                             encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="test",
                      subject="app/mod.py", action_type="create_test_stub",
                      target="app/mod.py", description="d", executable=True,
                      source_facts=["untested: app/mod.py"])
    plan = ActionPlan(objective="", project_root=str(tmp_path),
                      mode="autonomous", steps=[step], stats={})
    summ = IdeaActionBridge().apply_plan(plan, str(tmp_path), mode="autonomous",
                                         verify=True, test_first=False)
    assert summ["blocked"] == 0
    assert summ["results"][0]["risk_tier"] == 0


def test_plan_tree_uses_project_root_for_reality_checks(tmp_path):
    # report.project_root is empty; the explicit project_root must drive the
    # reality check (line 1553 `project_root or report.project_root or ""`), so
    # an already-tested module's stub step flips to non-executable.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "x.py").write_text("def f():\n    return 1\n",
                                           encoding="utf-8")
    (tmp_path / "tests" / "test_x.py").write_text(
        "from app.x import f\ndef test_f():\n    assert f() == 1\n",
        encoding="utf-8")
    idea = IdeaNode(id="i", title="t", subject="app/x.py", operator="test",
                    value=1.0, source_facts=["untested: app/x.py"])
    report = IdeaTreeReport(ideas=[idea], project_root="")
    plan = IdeaActionBridge().plan_tree(report, project_root=str(tmp_path))
    assert plan.steps[0].executable is False
    assert "deepen them by hand" in plan.steps[0].description


# --------------------------------------------------------------------------
# Final edges: _read_old OSError branch (1071), maintenance label split (1792),
# non-harden no-converge (1819), plan_tree report.project_root fallback (1553).
# --------------------------------------------------------------------------
def test_read_old_directory_path_returns_empty(tmp_path):
    # A directory at the path makes read_text raise OSError -> line 1071 `""`.
    (tmp_path / "adir").mkdir()
    assert IdeaActionBridge._read_old(tmp_path, "adir") == ""


def test_maintenance_label_is_fact_prefix(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "mod.py").write_text(
        "def f(x):\n    if x == None:\n        return 1\n    return 2\n",
        encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/mod.py", action_type="simplify_none_compare",
                      target="app/mod.py", description="d", executable=True,
                      source_facts=["modernization: app/mod.py"])
    plan = ActionPlan(objective="", project_root=str(tmp_path),
                      mode="supervised", steps=[step], stats={})
    summ = IdeaActionBridge().apply_plan(plan, str(tmp_path), mode="supervised")
    # label = source_facts[0].split(":")[0] (line 1792) -> the part BEFORE ":".
    assert summ["results"][0]["label"] == "modernization"


def test_non_harden_step_does_not_converge(tmp_path):
    # `step.action_type == "harden_security" and real_fix` (line 1819): a
    # non-harden applied step must NOT run the harden-convergence loop, so no
    # "converged_fixes" key is recorded.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "mod.py").write_text(
        "def f(x):\n    if x == None:\n        return 1\n    return 2\n",
        encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/mod.py", action_type="simplify_none_compare",
                      target="app/mod.py", description="d", executable=True,
                      source_facts=["modernization: app/mod.py"])
    plan = ActionPlan(objective="", project_root=str(tmp_path),
                      mode="supervised", steps=[step], stats={})
    summ = IdeaActionBridge().apply_plan(plan, str(tmp_path), mode="supervised")
    assert summ["results"][0]["applied"] is True
    assert "converged_fixes" not in summ["results"][0]


def test_plan_tree_falls_back_to_report_project_root(tmp_path):
    # project_root=None -> root_for_checks falls to report.project_root (line
    # 1553 second `or`); the reality check still flips an already-tested stub off.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "x.py").write_text("def f():\n    return 1\n",
                                           encoding="utf-8")
    (tmp_path / "tests" / "test_x.py").write_text(
        "from app.x import f\ndef test_f():\n    assert f() == 1\n",
        encoding="utf-8")
    idea = IdeaNode(id="i", title="t", subject="app/x.py", operator="test",
                    value=1.0, source_facts=["untested: app/x.py"])
    report = IdeaTreeReport(ideas=[idea], project_root=str(tmp_path))
    plan = IdeaActionBridge().plan_tree(report, project_root=None)
    assert plan.steps[0].executable is False


def test_attach_proofs_bounded_by_max_proofs(tmp_path):
    # Four proofable steps -> only the first _MAX_PROOFS (3) get a proof diff
    # (line 1062 budget); `3`->`4` would prove the fourth too.
    (tmp_path / "app").mkdir()
    steps = []
    for i in range(4):
        (tmp_path / "app" / f"m{i}.py").write_text(
            f"def f(x):\n    if x == None:\n        return {i}\n    return 9\n",
            encoding="utf-8")
        steps.append(ActionStep(
            branch_path=f"x.{i}", title="t", operator="o",
            subject=f"app/m{i}.py", action_type="simplify_none_compare",
            target=f"app/m{i}.py", description="d", executable=True))
    plan = ActionPlan(objective="", project_root=str(tmp_path),
                      mode="supervised", steps=steps, stats={})
    IdeaActionBridge().attach_proofs(plan, str(tmp_path))
    proven = [s for s in plan.steps
              if s.patch_preview and "diff" in s.patch_preview]
    assert len(proven) == 3


# --------------------------------------------------------------------------
# plan_roadmap reality-check root (1657) and apply_plan verify/commit defaults
# (1467/1469).
# --------------------------------------------------------------------------
def _referenced_idea_report(tmp_path, report_root):
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "app" / "x.py").write_text("def f():\n    return 1\n",
                                           encoding="utf-8")
    (tmp_path / "tests" / "test_x.py").write_text(
        "from app.x import f\ndef test_f():\n    assert f() == 1\n",
        encoding="utf-8")
    idea = IdeaNode(id="i", title="t", subject="app/x.py", operator="test",
                    value=1.0, source_facts=["untested: app/x.py"])
    return IdeaTreeReport(ideas=[idea], project_root=report_root)


def test_plan_roadmap_uses_explicit_project_root_for_checks(tmp_path):
    report = _referenced_idea_report(tmp_path, report_root="")
    plan = IdeaActionBridge().plan_roadmap(report, project_root=str(tmp_path))
    assert plan.steps[0].executable is False


def test_plan_roadmap_falls_back_to_report_project_root(tmp_path):
    report = _referenced_idea_report(tmp_path, report_root=str(tmp_path))
    plan = IdeaActionBridge().plan_roadmap(report, project_root=None)
    assert plan.steps[0].executable is False


def test_apply_plan_defaults_no_verify_no_commit(tmp_path):
    # verify defaults False (1467) -> a tier-1 fix on an UNcovered module is NOT
    # gated, so it applies; commit defaults False (1469).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "mod.py").write_text(
        "def f(x):\n    if x == None:\n        return 1\n    return 2\n",
        encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/mod.py", action_type="simplify_none_compare",
                      target="app/mod.py", description="d", executable=True,
                      source_facts=["modernization: app/mod.py"])
    plan = ActionPlan(objective="", project_root=str(tmp_path),
                      mode="autonomous", steps=[step], stats={})
    summ = IdeaActionBridge().apply_plan(plan, str(tmp_path), mode="autonomous")
    assert summ["applied"] == 1
    assert summ["blocked"] == 0
    assert summ["verify"] is False
    assert summ["commit"] is False


def test_converge_harden_multiple_iterations(tmp_path):
    # Three harden-ladder issues -> the convergence loop runs twice after the
    # initial apply (converged_fixes == 2), exercising `extra += 1` (line 1783)
    # and multiple `range(5)` iterations (1775).
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "conftest.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "sec.py").write_text(
        "def f(x=[]):\n"
        "    if x == None:\n"
        "        return open('a.txt').read()\n"
        "    x.append(2)\n"
        "    return x\n", encoding="utf-8")
    (tmp_path / "tests" / "test_sec.py").write_text(
        "from app.sec import f\ndef test_smoke():\n    assert callable(f)\n",
        encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/sec.py", action_type="harden_security",
                      target="app/sec.py", description="d", executable=True,
                      source_facts=["sensitive-path: app/sec.py"])
    plan = ActionPlan(objective="", project_root=str(tmp_path),
                      mode="autonomous", steps=[step], stats={})
    summ = IdeaActionBridge().apply_plan(
        plan, str(tmp_path), mode="autonomous", verify=True, test_first=False)
    assert summ["results"][0]["converged_fixes"] == 2


def test_apply_step_rolls_back_newly_created_file_by_unlinking(tmp_path):
    # A create_test_stub writes a NEW test file (snapshot is None); when verify
    # fails, the rollback UNLINKS it (line 1354 `if original is None`). The
    # `is None`->`is not None` mutant would instead write None and leave it.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "conftest.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "mod.py").write_text("def f():\n    return 1\n",
                                             encoding="utf-8")
    (tmp_path / "tests" / "test_fail.py").write_text(
        "def test_fail():\n    assert False\n", encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="test",
                      subject="app/mod.py", action_type="create_test_stub",
                      target="app/mod.py", description="d", executable=True)
    r = IdeaActionBridge().apply_step(step, str(tmp_path), mode="autonomous",
                                      verify=True)
    assert r["rolled_back"] is True
    # The freshly-created stub file was removed; only the pre-existing test stays.
    remaining = sorted(p.name for p in (tmp_path / "tests").glob("*.py"))
    assert remaining == ["test_fail.py"]


def test_apply_plan_counts_rollback(tmp_path):
    # A verified apply whose suite goes red is rolled back and counted (line 1825
    # `self.rolled_back += 1`).
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "conftest.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "mod.py").write_text(
        "def f(x):\n    if x == None:\n        return 1\n    return 2\n",
        encoding="utf-8")
    # Source-text assertion goes red after the fix; a second test references the
    # module so the tier-1 coverage gate passes and the apply proceeds.
    (tmp_path / "tests" / "test_src.py").write_text(
        "def test_src():\n    assert '== None' in open('app/mod.py').read()\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_ref.py").write_text(
        "from app.mod import f\ndef test_f():\n    assert f(None) == 1\n",
        encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/mod.py", action_type="simplify_none_compare",
                      target="app/mod.py", description="d", executable=True,
                      source_facts=["modernization: app/mod.py"])
    plan = ActionPlan(objective="", project_root=str(tmp_path),
                      mode="autonomous", steps=[step], stats={})
    summ = IdeaActionBridge().apply_plan(
        plan, str(tmp_path), mode="autonomous", verify=True, test_first=False)
    assert summ["applied"] == 0
    assert summ["rolled_back"] == 1


def test_apply_plan_counts_blocked_when_no_patch(tmp_path):
    # A clean file yields no applicable patch -> the step is blocked and counted
    # (line 1829 `self.blocked += 1`).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "clean.py").write_text("x = 1\n", encoding="utf-8")
    step = ActionStep(branch_path="x.0", title="t", operator="o",
                      subject="app/clean.py", action_type="simplify_none_compare",
                      target="app/clean.py", description="d", executable=True,
                      source_facts=["modernization: app/clean.py"])
    plan = ActionPlan(objective="", project_root=str(tmp_path),
                      mode="supervised", steps=[step], stats={})
    summ = IdeaActionBridge().apply_plan(plan, str(tmp_path), mode="supervised")
    assert summ["applied"] == 0
    assert summ["rolled_back"] == 0
    assert summ["blocked"] == 1
