"""Abductive root-cause explanations on converging (confluence) ideas.

Wires the previously-isolated ``app/engine/abductive_reasoning.py`` into the
idea pipeline: a confluence idea (a module where >= 2 independent, mappable
signals converge) now carries a grounded causal "why" — a primary root cause
plus a confidence — so Apex's development ideas read as REASONED, not mechanical.

The enrichment is a strict additive SUPERSET: it appends a clause to the idea's
rationale and an ``abductive: ...`` source_fact AFTER ``source_facts[0]`` (the
develop-loop's routing key), never reordering or replacing existing facts. Ideas
with < 2 mappable converging signals are byte-identical to before.
"""

from app.engine.abductive_reasoning import (
    SIGNAL_OBSERVATION_MAP,
    AbductionResult,
    explain_signals,
    explanation_clause,
    signals_to_observations,
)
from app.engine.idea_seeder import IdeaSeeder
from app.tools.project_profile import ProjectProfile


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _confluence_root(profile: ProjectProfile):
    roots = IdeaSeeder().seed(profile)
    conv = [r for r in roots if r.source_facts
            and r.source_facts[0].startswith("confluence:")]
    assert len(conv) == 1
    return conv[0]


def _hub_symbolhub_confluence() -> ProjectProfile:
    # hub + symbol-hub both map to ``high_import_count`` -> 2 observations.
    return _profile(
        confluence_modules=[{
            "module": "app/engine/objective_compiler.py",
            "family_count": 3,
            "families": ("high-churn", "hub", "symbol-hub"),
        }],
        ci_files=["ci.yml"],
    )


# --------------------------------------------------------------------------- #
# signal -> observation translation.
# --------------------------------------------------------------------------- #

def test_each_mapped_label_translates_to_its_observation():
    expected = {
        "hub": "high_import_count",
        "dependency-hub": "high_import_count",
        "symbol-hub": "high_import_count",
        "god-class": "high_import_count",
        "deep-nesting": "deep_nesting",
        "base-exception": "bare_except",
        "bare except": "bare_except",
        "eval": "eval_usage",
        "security-eval": "eval_usage",
        "complexity-hotspot": "long_function",
        "complex-function": "long_function",
        "hotspot-function": "long_function",
        "mutable-default": "mutable_default_arg",
        "dead-parameter": "many_arguments",
        "doc-drift": "missing_docstring",
        "missing-docstring": "missing_docstring",
        "unused-import": "unused_import",
        "modernization-imports": "unused_import",
    }
    assert SIGNAL_OBSERVATION_MAP == expected
    for label, obs_type in expected.items():
        assert signals_to_observations([label]) == [{"type": obs_type}]


def test_unmapped_labels_are_skipped():
    # "untested" / "high-churn" / "fragile" carry no anti-pattern observation.
    assert signals_to_observations(["untested", "high-churn", "fragile"]) == []
    # Mapped labels are kept, in order; unmapped ones drop out.
    assert signals_to_observations(["untested", "hub", "deep-nesting"]) == [
        {"type": "high_import_count"},
        {"type": "deep_nesting"},
    ]


def test_empty_or_none_signals_yield_no_observations():
    assert signals_to_observations([]) == []
    assert signals_to_observations(None) == []


# --------------------------------------------------------------------------- #
# explain_signals: needs >= 2 mappable observations.
# --------------------------------------------------------------------------- #

def test_fewer_than_two_mappable_signals_returns_none():
    assert explain_signals(["hub"]) is None              # 1 mappable
    assert explain_signals(["hub", "untested"]) is None  # still 1 mappable
    assert explain_signals([]) is None


def test_two_mappable_signals_yield_a_result_with_confidence():
    result = explain_signals(["hub", "symbol-hub"])
    assert isinstance(result, AbductionResult)
    assert result.root_causes
    assert result.root_causes[0] == "Module is a 'god module' with too many concerns"
    assert 0.0 < result.confidence <= 1.0


def test_explanation_is_deterministic():
    a = explain_signals(["hub", "symbol-hub", "deep-nesting"])
    b = explain_signals(["hub", "symbol-hub", "deep-nesting"])
    assert a is not None and b is not None
    assert a.root_causes == b.root_causes
    assert a.confidence == b.confidence
    assert explanation_clause(a) == explanation_clause(b)


# --------------------------------------------------------------------------- #
# Confluence idea now carries the root-cause explanation.
# --------------------------------------------------------------------------- #

def test_confluence_idea_carries_root_cause_and_confidence():
    idea = _confluence_root(_hub_symbolhub_confluence())
    # source_facts[0] (the routing key) is untouched...
    assert idea.source_facts[0].startswith("confluence:")
    # ...and a NEW abductive fact rides after it.
    assert len(idea.source_facts) == 2
    assert idea.source_facts[1].startswith("abductive: root cause:")
    assert "god module" in idea.source_facts[1]
    assert "confidence 0.9" in idea.source_facts[1]
    # The rationale surfaces the same grounded clause.
    assert "root cause:" in idea.rationale
    assert "confidence 0.9" in idea.rationale


def test_confluence_explanation_is_deterministic_end_to_end():
    a = _confluence_root(_hub_symbolhub_confluence())
    b = _confluence_root(_hub_symbolhub_confluence())
    assert a.source_facts == b.source_facts
    assert a.rationale == b.rationale


# --------------------------------------------------------------------------- #
# Superset: an idea with < 2 mappable signals is byte-identical to before.
# --------------------------------------------------------------------------- #

def _seed_without_enrichment(profile: ProjectProfile):
    seeder = IdeaSeeder()
    seeder._abductive_enrichment = staticmethod(lambda labels: (None, None))
    return seeder.seed(profile)


def test_confluence_with_under_two_mappable_signals_is_byte_identical():
    # families = high-churn + untested + fragile -> ZERO mappable signals, so
    # the idea must be identical to the un-enriched seed.
    profile = _profile(
        confluence_modules=[{
            "module": "app/m.py",
            "family_count": 3,
            "families": ("fragile", "high-churn", "untested"),
        }],
        ci_files=["ci.yml"],
    )
    enriched = IdeaSeeder().seed(profile)
    plain = _seed_without_enrichment(profile)
    assert [i.model_dump() for i in enriched] == [i.model_dump() for i in plain]
    conv = [r for r in enriched
            if r.source_facts and r.source_facts[0].startswith("confluence:")][0]
    assert len(conv.source_facts) == 1  # no abductive fact appended


def test_single_mappable_signal_leaves_idea_identity_intact():
    # hub + untested + high-churn -> exactly 1 mappable (hub) -> no enrichment.
    profile = _profile(
        confluence_modules=[{
            "module": "app/h.py",
            "family_count": 3,
            "families": ("high-churn", "hub", "untested"),
        }],
        ci_files=["ci.yml"],
    )
    enriched = _confluence_root(profile)
    plain = [r for r in _seed_without_enrichment(profile)
             if r.source_facts and r.source_facts[0].startswith("confluence:")][0]
    assert enriched.subject == plain.subject
    assert enriched.title == plain.title
    assert enriched.branch_path == plain.branch_path
    assert enriched.source_facts == plain.source_facts
    assert enriched.rationale == plain.rationale
    assert len(enriched.source_facts) == 1


def test_enrichment_preserves_first_source_fact_and_order():
    # The full enriched confluence idea must keep source_facts[0] first and only
    # ever APPEND — never reorder.
    idea = _confluence_root(_hub_symbolhub_confluence())
    assert idea.source_facts[0].split(":", 1)[0] == "confluence"
    # Everything after index 0 is purely additive enrichment.
    assert all(f.startswith("abductive:") for f in idea.source_facts[1:])
