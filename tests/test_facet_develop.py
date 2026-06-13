"""Tests for the facet -> develop objective bridge."""

from __future__ import annotations

import pytest

from app.engine.facet_develop import (
    FACET_OBJECTIVE_MAP,
    facet_to_objective,
    facets_to_objectives,
    render_facet_plan_markdown,
)
from app.engine.objective_compiler import available_objectives


@pytest.mark.parametrize(
    "phrase, objective",
    [
        ("extract a shared helper", "dedup"),
        ("single source of truth", "dedup"),
        ("duplicated logic", "dedup"),
        ("smaller unit", "shrink-functions"),
        ("extract inner", "shrink-functions"),
        ("parameterize", "dead-params"),
        ("api surface", "dead-params"),
        ("interface", "dead-params"),
        ("unused parameter", "dead-params"),
        ("modernize", "modernize"),
        ("none comparison", "modernize"),
        ("dead code", "remove-dead-code"),
        ("unreachable", "remove-dead-code"),
        ("inline", "inline-helpers"),
        ("indirection", "inline-helpers"),
    ],
)
def test_each_mapping(phrase: str, objective: str) -> None:
    assert facet_to_objective(phrase) == objective


def test_matching_is_case_insensitive_and_substring() -> None:
    assert facet_to_objective("We should MODERNIZE this") == "modernize"
    assert facet_to_objective("...extract a shared helper here...") == "dedup"


def test_unmapped_phrase_returns_none() -> None:
    assert facet_to_objective("write more documentation") is None
    assert facet_to_objective("") is None


def test_facets_to_objectives_dedups_and_preserves_order() -> None:
    phrases = [
        "modernize",            # modernize
        "extract a shared helper",  # dedup
        "duplicated logic",     # dedup (dup -> dropped)
        "parameterize",         # dead-params
        "single source of truth",   # dedup (dup -> dropped)
        "smaller unit",         # shrink-functions
    ]
    assert facets_to_objectives(phrases) == [
        "modernize",
        "dedup",
        "dead-params",
        "shrink-functions",
    ]


def test_facets_to_objectives_skips_unmapped() -> None:
    assert facets_to_objectives(["nonsense", "modernize", "also nonsense"]) == [
        "modernize"
    ]


def test_facets_to_objectives_empty() -> None:
    assert facets_to_objectives([]) == []


def test_integrity_every_value_is_a_real_objective() -> None:
    known = set(available_objectives())
    for phrase, objective in FACET_OBJECTIVE_MAP.items():
        assert objective in known, (
            f"facet {phrase!r} maps to unknown objective {objective!r}"
        )


def test_render_shows_mapping() -> None:
    md = render_facet_plan_markdown(["modernize", "extract a shared helper"])
    assert "Facet → develop plan" in md
    assert "`modernize`" in md
    assert "`dedup`" in md
    assert "| modernize |" in md


def test_render_empty_is_clean() -> None:
    md = render_facet_plan_markdown([])
    assert "No facet maps to a develop objective" in md
    assert "| --- |" not in md


def test_render_all_unmapped_is_clean() -> None:
    md = render_facet_plan_markdown(["nonsense", "more nonsense"])
    assert "No facet maps to a develop objective" in md
    assert "| --- |" not in md


def test_render_dedups_resolution_line() -> None:
    md = render_facet_plan_markdown(["duplicated logic", "single source of truth"])
    # Both rows shown, but the resolution line lists dedup once.
    assert md.count("| dedup ") == 0  # value is rendered as `dedup`, not bare
    assert "Resolves to: `dedup`." in md
