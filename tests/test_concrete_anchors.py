"""Concrete anchors: module-level ideas name a function + line + metric.

The seeder folds the riskiest function(s) WITHIN a module-level root into the
idea's ``anchors`` and ``rationale``, so "Untangle module X" points at a real
locus. These tests pin the anchor shape, determinism, backward-compatibility
(empty anchors render byte-identically), and the [0,1] value invariants.
"""

from app.engine.idea_permutation import IdeaSeeder, render_markdown
from app.models.idea import IdeaNode, IdeaTreeReport
from app.tools.project_profile import ProjectProfile


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _hotspot(module, function, line, complexity, cognitive=0) -> dict:
    return {"module": module, "function": function, "line": line,
            "complexity": complexity, "cognitive": cognitive}


def _confluence(module, families=("complex-function", "high-churn", "hub")) -> dict:
    fams = tuple(sorted(families))
    return {"module": module, "family_count": len(fams), "families": fams}


# --- field is additive / backward-compatible -------------------------------

def test_anchors_field_defaults_empty_and_is_additive():
    # A plain IdeaNode (no anchors arg) still constructs and carries [].
    node = IdeaNode(id="idea-0", title="t", depth=0)
    assert node.anchors == []
    # round-trips through model_dump
    assert node.to_dict()["anchors"] == []


def test_anchors_field_accepts_dicts():
    a = {"module": "m.py", "symbol": "f", "line": 5, "metric": "cyclomatic 9"}
    node = IdeaNode(id="idea-0", title="t", depth=0, anchors=[a])
    assert node.anchors == [a]


# --- confluence module gets anchored at its riskiest function ---------------

def test_confluence_idea_anchors_name_the_function_with_line():
    module = "app/tools/project_profile.py"
    profile = _profile(
        confluence_modules=[_confluence(module)],
        hotspot_functions=[_hotspot(module, "_scan_churn", 550, 18)],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    root = next(r for r in roots if r.subject == module)
    assert root.anchors, "confluence module should carry concrete anchors"
    anchor = root.anchors[0]
    assert anchor == {"module": module, "symbol": "_scan_churn",
                      "line": 550, "metric": "cyclomatic 18"}
    # The concrete locus also rides in the rationale.
    assert "_scan_churn" in root.rationale
    assert "line 550" in root.rationale
    assert "cyclomatic 18" in root.rationale
    # title/subject stay module-level (existing tests unaffected).
    assert root.subject == module
    assert "Untangle" in root.title


def test_anchors_take_top_three_by_complexity_then_line():
    module = "app/big.py"
    profile = _profile(
        confluence_modules=[_confluence(module)],
        hotspot_functions=[
            _hotspot(module, "low", 10, 9),
            _hotspot(module, "high", 200, 30),
            _hotspot(module, "mid_a", 80, 15),
            _hotspot(module, "mid_b", 40, 15),  # same complexity -> line breaks tie
        ],
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == module)
    symbols = [a["symbol"] for a in root.anchors]
    # complexity desc, then line asc: high(30), mid_b(15,line40), mid_a(15,line80)
    assert symbols == ["high", "mid_b", "mid_a"]
    assert len(root.anchors) == 3  # capped at 3


def test_anchors_only_pull_from_the_roots_own_module():
    module = "app/target.py"
    other = "app/other.py"
    profile = _profile(
        confluence_modules=[_confluence(module)],
        hotspot_functions=[
            _hotspot(other, "wrong", 1, 99),
            _hotspot(module, "right", 12, 11),
        ],
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == module)
    assert [a["symbol"] for a in root.anchors] == ["right"]
    assert all(a["module"] == module for a in root.anchors)


def test_impure_untested_fills_in_when_no_complexity_hotspot():
    module = "app/io.py"
    profile = _profile(
        confluence_modules=[_confluence(module)],
        impure_untested_functions=[
            {"module": module, "function": "write_cfg", "line": 33,
             "side_effects": ["os"], "complexity": 0},
        ],
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == module)
    assert root.anchors == [{"module": module, "symbol": "write_cfg",
                             "line": 33, "metric": "impure, untested"}]


# --- other module-level roots also anchor -----------------------------------

def test_fragile_and_hub_untested_roots_anchor():
    fragile = "app/frag.py"
    hub = "app/hub.py"
    profile = _profile(
        fragile_modules=[fragile],
        hub_untested_modules=[{"module": hub, "fan_in": 6}],
        hotspot_functions=[
            _hotspot(fragile, "frag_fn", 70, 12),
            _hotspot(hub, "hub_fn", 90, 14),
        ],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    frag_root = next(r for r in roots if r.subject == fragile)
    hub_root = next(r for r in roots if r.subject == hub)
    assert [a["symbol"] for a in frag_root.anchors] == ["frag_fn"]
    assert [a["symbol"] for a in hub_root.anchors] == ["hub_fn"]


def test_dependency_hub_root_anchors_but_other_rules_do_not():
    hub = "app/central.py"
    sens = "app/auth.py"
    profile = _profile(
        dependency_hubs=[hub],
        sensitive_paths=[sens],
        hotspot_functions=[
            _hotspot(hub, "dispatch", 200, 16),
            # a hotspot in the sensitive path: the sensitive-path rule must NOT
            # anchor (only dependency-hub among _RULES anchors).
            _hotspot(sens, "login", 40, 13),
        ],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    hub_root = next(r for r in roots if r.subject == hub)
    sens_root = next(r for r in roots if r.subject == sens)
    assert [a["symbol"] for a in hub_root.anchors] == ["dispatch"]
    assert sens_root.anchors == []


# --- no function-grain data -> empty anchors, no-op --------------------------

def test_module_with_no_function_grain_data_has_empty_anchors():
    module = "app/plain.py"
    profile = _profile(
        confluence_modules=[_confluence(module)],
        ci_files=["ci.yml"],
    )
    root = next(r for r in IdeaSeeder().seed(profile) if r.subject == module)
    assert root.anchors == []
    # rationale carries no anchor phrase when empty.
    assert "Centers on" not in root.rationale


def test_module_anchors_helper_returns_empty_for_unknown_module():
    profile = _profile(hotspot_functions=[_hotspot("a.py", "f", 1, 9)])
    assert IdeaSeeder()._module_anchors(profile, "nonexistent.py") == []


# --- determinism -------------------------------------------------------------

def test_seeding_is_deterministic_across_two_runs():
    module = "app/det.py"
    profile = _profile(
        confluence_modules=[_confluence(module)],
        hotspot_functions=[
            _hotspot(module, "b", 30, 12),
            _hotspot(module, "a", 10, 12),
        ],
        ci_files=["ci.yml"],
    )
    first = IdeaSeeder().seed(profile)
    second = IdeaSeeder().seed(profile)
    assert [r.to_dict() for r in first] == [r.to_dict() for r in second]
    root = next(r for r in first if r.subject == module)
    # stable anchor order (same complexity -> line asc).
    assert [a["symbol"] for a in root.anchors] == ["a", "b"]


# --- value/feasibility/novelty invariants -----------------------------------

def test_node_value_invariants_hold_with_anchors():
    module = "app/inv.py"
    profile = _profile(
        confluence_modules=[_confluence(module)],
        hotspot_functions=[_hotspot(module, "fn", 22, 20)],
        ci_files=["ci.yml"],
    )
    for r in IdeaSeeder().seed(profile):
        assert 0.0 <= r.value <= 1.0
        assert 0.0 <= r.feasibility <= 1.0
        assert 0.0 <= r.novelty <= 1.0
        assert r.novelty == 1.0  # roots keep novelty == 1.0


# --- render: focus line for anchors, byte-identical without ------------------

def _report(idea: IdeaNode) -> IdeaTreeReport:
    return IdeaTreeReport(objective="o", project_root=".", ideas=[idea])


def test_render_shows_focus_line_for_anchored_idea():
    idea = IdeaNode(
        id="idea-0", title="Untangle app/x.py", subject="app/x.py", depth=0,
        branch_path="x.0", source_facts=["confluence: app/x.py"],
        anchors=[{"module": "app/x.py", "symbol": "pkg._scan_churn",
                  "line": 550, "metric": "cyclomatic 18"}],
    )
    md = render_markdown(_report(idea))
    assert "→ focus:" in md
    assert "`_scan_churn` (cyclomatic 18, line 550)" in md


def test_render_is_byte_identical_without_anchors():
    base = dict(id="idea-0", title="Untangle app/x.py", subject="app/x.py",
                depth=0, branch_path="x.0",
                source_facts=["confluence: app/x.py"])
    no_anchors = IdeaNode(**base)
    # An identical idea that merely carries an explicit empty-anchor list must
    # render the same bytes as the default, and neither may emit a focus line.
    explicit_empty = IdeaNode(**base, anchors=[])
    md_default = render_markdown(_report(no_anchors))
    md_empty = render_markdown(_report(explicit_empty))
    assert md_default == md_empty
    assert "→ focus:" not in md_default


def test_render_multiple_anchors_joined():
    idea = IdeaNode(
        id="idea-0", title="Untangle app/x.py", subject="app/x.py", depth=0,
        branch_path="x.0",
        anchors=[
            {"module": "app/x.py", "symbol": "high", "line": 200, "metric": "cyclomatic 30"},
            {"module": "app/x.py", "symbol": "mid", "line": 80, "metric": "cyclomatic 15"},
        ],
    )
    md = render_markdown(_report(idea))
    assert "`high` (cyclomatic 30, line 200), `mid` (cyclomatic 15, line 80)" in md
