"""The brief→develop narrative weaves signal convergence ADDITIVELY.

When the engine's profile names a confluence module (>= 3 distinct signal
families pile up on one module), the rendered brief adds a short grounded line
naming that module and exactly which families converge. With no confluence the
brief is byte-identical to before — the feature is opt-in by the data.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.engine.brief_develop import (
    BriefDevelopResult,
    _confluences_from_profile,
    render_brief_develop_markdown,
)


def _result(confluences=None, objectives=("remove-dead-code",), **kw) -> BriefDevelopResult:
    return BriefDevelopResult(
        branch_path="x.o", title="T", subject="app/m.py",
        objectives=list(objectives), applied=False,
        confluences=list(confluences or []),
        check={"branch_path": "x.o", "title": "T", "subject": "app/m.py",
               "resolved": [], "open": [], "measured_total": 0},
        **kw)


_CONV = {"module": "app/core/router.py", "family_count": 3,
         "families": ("complex-function", "high-churn", "hub")}


# --- the grounded line names module + families -------------------------------

def test_confluence_line_names_module_and_families():
    md = render_brief_develop_markdown(_result(confluences=[_CONV]))
    assert "**Convergence:**" in md
    assert "`app/core/router.py`" in md
    assert "complex-function, high-churn, hub" in md
    assert "3 independent signal families" in md
    # Framed as the next move, calm and grounded.
    assert "highest-leverage next move" in md
    assert "decouple" in md and "test it before changing it" in md


def test_confluence_line_appears_even_without_objectives():
    md = render_brief_develop_markdown(_result(confluences=[_CONV], objectives=[]))
    assert "**Convergence:**" in md
    assert "`app/core/router.py`" in md
    # The manual fallback narrative still renders alongside it.
    assert "Carry it out by hand" in md


def test_confluence_uses_top_target_first():
    second = {"module": "app/util/io.py", "family_count": 4,
              "families": ("hub", "untested", "high-churn", "mutable-default")}
    md = render_brief_develop_markdown(_result(confluences=[_CONV, second]))
    # The first (most-converged) entry is the named target.
    assert "`app/core/router.py`" in md
    assert "`app/util/io.py`" not in md
    assert md.count("**Convergence:**") == 1


# --- byte-identical when nothing converges -----------------------------------

def test_no_confluence_is_byte_identical_with_objectives():
    base = render_brief_develop_markdown(_result(confluences=[]))
    # The pre-feature output never carried a Convergence note.
    assert "Convergence" not in base
    assert base == render_brief_develop_markdown(_result(confluences=None))


def test_no_confluence_is_byte_identical_no_objectives():
    base = render_brief_develop_markdown(_result(confluences=[], objectives=[]))
    assert "Convergence" not in base
    assert "Carry it out by hand" in base


# --- determinism --------------------------------------------------------------

def test_render_is_deterministic():
    a = render_brief_develop_markdown(_result(confluences=[_CONV]))
    b = render_brief_develop_markdown(_result(confluences=[_CONV]))
    assert a == b


# --- _confluences_from_profile helper ----------------------------------------

def test_confluences_from_profile_reads_field():
    profile = SimpleNamespace(confluence_modules=[_CONV])
    assert _confluences_from_profile(profile) == [_CONV]


def test_confluences_from_profile_none_profile_is_empty():
    assert _confluences_from_profile(None) == []


def test_confluences_from_profile_missing_field_is_empty():
    assert _confluences_from_profile(SimpleNamespace()) == []


def test_confluences_from_profile_drops_malformed_entries():
    profile = SimpleNamespace(confluence_modules=[
        {"module": "", "families": ("hub",)},          # no module
        {"module": "app/a.py", "families": ()},          # no families
        _CONV,                                            # kept
    ])
    assert _confluences_from_profile(profile) == [_CONV]


# --- to_dict carries the signal ----------------------------------------------

def test_to_dict_includes_confluences():
    d = _result(confluences=[_CONV]).to_dict()
    assert d["confluences"] == [_CONV]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
