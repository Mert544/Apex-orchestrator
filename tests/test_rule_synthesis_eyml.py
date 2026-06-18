"""Rule synthesis — mining recurring AST micro-patterns into candidate rules.

Recommend-only discovery: Apex proposes candidate fix-rules from recurring code
shapes. Tests cover support counting, identifier-abstracted shape keys,
descriptor completeness, determinism, bounding, and empty/no-recurrence paths.
"""

from __future__ import annotations

from app.engine.rule_synthesis import (
    DEFAULT_MIN_SUPPORT,
    mine_recurring_patterns,
    propose_rules,
    synthesise_candidate_rule,
)

# A repeated ``x = x + 1``-style augment shape across several files. The names
# and the increment literal differ per site, so only an identifier/literal-
# abstracted key will collapse them into one pattern.
_AUGMENT_SOURCES = {
    "a.py": "a = a + 1\n",
    "b.py": "count = count + 5\n",
    "c.py": "total = total + 2\n",
    "d.py": "n = n + 1\n",
}

# A repeated ``if a: return b`` shape across several files.
_GUARD_SOURCES = {
    "p.py": "def f(x):\n    if x:\n        return x\n",
    "q.py": "def g(y):\n    if y:\n        return y\n",
    "r.py": "def h(z):\n    if z:\n        return z\n",
}

# No structural recurrence: each file is a distinct shape.
_DISTINCT_SOURCES = {
    "u.py": "x = 1\n",
    "v.py": "for i in range(3):\n    pass\n",
    "w.py": "while True:\n    break\n",
}


def _shapes(patterns):
    return {p["shape"] for p in patterns}


# --- mining: support + abstraction -----------------------------------------


def test_augment_pattern_mined_with_full_support():
    patterns = mine_recurring_patterns(_AUGMENT_SOURCES, min_support=3)
    assert patterns, "repeated assign shape should be mined"
    top = patterns[0]
    # All four assigns collapse to one identifier/literal-abstracted shape.
    assert top["support"] == 4
    assert len(top["example_sites"]) == 4


def test_literals_and_identifiers_are_abstracted():
    # The increment is 1, 5, 2, 1 across sites — different literals — yet they
    # share one shape key, proving literals (and names) are abstracted out.
    patterns = mine_recurring_patterns(_AUGMENT_SOURCES, min_support=3)
    assign_shapes = [s for s in _shapes(patterns) if s.startswith("Assign")]
    assert len(assign_shapes) == 1


def test_guard_pattern_mined():
    patterns = mine_recurring_patterns(_GUARD_SOURCES, min_support=3)
    if_shapes = [s for s in _shapes(patterns) if s.startswith("If")]
    assert if_shapes, "if-return guard shape should recur"
    by_shape = {p["shape"]: p for p in patterns}
    assert by_shape[if_shapes[0]]["support"] == 3


def test_example_sites_are_path_line_labels_and_sorted():
    patterns = mine_recurring_patterns(_AUGMENT_SOURCES, min_support=3)
    sites = patterns[0]["example_sites"]
    assert sites == sorted(sites)
    assert all(":" in s for s in sites)


# --- no recurrence / empty paths -------------------------------------------


def test_non_recurring_sources_yield_empty():
    assert mine_recurring_patterns(_DISTINCT_SOURCES, min_support=3) == []


def test_empty_sources_yield_empty():
    assert mine_recurring_patterns({}, min_support=3) == []
    assert propose_rules({}) == []


def test_unparseable_source_is_skipped_not_raised():
    bad = dict(_AUGMENT_SOURCES)
    bad["broken.py"] = "def (:\n"
    patterns = mine_recurring_patterns(bad, min_support=3)
    # Broken file ignored; the valid augment pattern still surfaces.
    assert any(p["support"] == 4 for p in patterns)


def test_support_below_threshold_filtered():
    two = {"a.py": "a = a + 1\n", "b.py": "b = b + 1\n"}
    assert mine_recurring_patterns(two, min_support=3) == []
    assert mine_recurring_patterns(two, min_support=2)


def test_min_support_below_one_yields_empty():
    assert mine_recurring_patterns(_AUGMENT_SOURCES, min_support=0) == []


# --- determinism + bounding ------------------------------------------------


def test_shape_keys_are_deterministic_across_runs():
    a = mine_recurring_patterns(_AUGMENT_SOURCES, min_support=3)
    b = mine_recurring_patterns(dict(reversed(list(_AUGMENT_SOURCES.items()))),
                                min_support=3)
    assert a == b


def test_output_sorted_by_descending_support():
    sources = dict(_AUGMENT_SOURCES)
    sources.update(_GUARD_SOURCES)
    patterns = mine_recurring_patterns(sources, min_support=3)
    supports = [p["support"] for p in patterns]
    assert supports == sorted(supports, reverse=True)


def test_example_sites_are_bounded():
    many = {f"f{i}.py": "v = v + 1\n" for i in range(20)}
    patterns = mine_recurring_patterns(many, min_support=3)
    assert patterns[0]["support"] == 20
    assert len(patterns[0]["example_sites"]) <= 5


# --- candidate descriptor ---------------------------------------------------


def test_synthesise_candidate_rule_has_all_keys():
    patterns = mine_recurring_patterns(_AUGMENT_SOURCES, min_support=3)
    rule = synthesise_candidate_rule(patterns[0])
    for key in ("shape", "support", "example_sites", "suggested_name",
                "rationale", "safety_note"):
        assert key in rule
    assert rule["support"] == 4
    assert rule["suggested_name"].startswith("synthesised_")
    # Recommend-only contract: descriptor must not claim safety.
    assert "NOT" in rule["safety_note"]


def test_descriptor_does_not_contain_executable_code():
    rule = synthesise_candidate_rule({"shape": "If[...]", "support": 3,
                                      "example_sites": []})
    # It is a proposal, not code: no def/import/lambda payload anywhere.
    blob = rule["rationale"] + rule["safety_note"] + rule["suggested_name"]
    assert "def " not in blob and "import " not in blob


def test_propose_rules_returns_top_by_support():
    sources = dict(_AUGMENT_SOURCES)
    sources.update(_GUARD_SOURCES)
    rules = propose_rules(sources, top=2)
    assert len(rules) <= 2
    if len(rules) == 2:
        assert rules[0]["support"] >= rules[1]["support"]
    assert all("safety_note" in r for r in rules)


def test_propose_rules_top_below_one_empty():
    assert propose_rules(_AUGMENT_SOURCES, top=0) == []


def test_default_min_support_is_conservative():
    assert DEFAULT_MIN_SUPPORT >= 3
    # At default threshold a 3-site guard pattern surfaces.
    assert propose_rules(_GUARD_SOURCES)
