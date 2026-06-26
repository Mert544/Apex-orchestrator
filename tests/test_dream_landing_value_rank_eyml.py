"""Value-ranked confluence LANDING ORDER (the dream differentiator deepening).

When ``dream develop --land`` graduates MULTIPLE confluences it historically
worked them in ALPHABETICAL order (``dream_landing.dream_confluence_modules``
returned ``sorted(set(...))`` and ``dream_develop`` consumed that order). This
wave adds ``_rank_confluences`` — an OPT-IN re-ranking by EXPECTED LANDABLE
BUYER-VALUE so the overnight chain leads with the file where a buyer gets the
most concrete value, deterministically and for free.

The order is the sum of ``objective_value_weight`` over the fitness-applicable
objectives with pending work SCOPED to each module — the SAME ``move_value`` /
``rank_objectives`` math ``plan``/``ascend`` already trust — sorted DESCENDING,
ties broken by the existing alphabetical key. It is ORDERING ONLY: a permutation
of the same module set, never a different membership, so it can never change
WHICH suite-gated-with-rollback moves run.

These tests pin: (1) a multi-confluence order FLIPS by value (a higher-value
file leads despite sorting alphabetically LAST); (2) a single-confluence and an
empty project stay BYTE-IDENTICAL to the alphabetical default whether or not the
opt-in is set; (3) the ranking is DETERMINISTIC (two runs identical); (4) ties
fall back to alphabetical; (5) the default (opt-in OFF) is byte-identical
everywhere — it is a permutation of the same set; and (6) ``dream_develop``
consumes the ranked order end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.dream_landing import (
    _module_landable_value,
    _rank_confluences,
    dream_confluence_modules,
)


# --- fixtures ----------------------------------------------------------------

def _two_confluence_project(tmp_path: Path) -> Path:
    """Two STORED confluences with a deliberate value contrast, crafted so the
    alphabetically-LAST module carries the MOST landable buyer-value:

      - ``app/aaa.py`` (sorts FIRST): tested, only a low-value dead parameter
        (``dead-params`` 0.40) — a cheap tidy.
      - ``app/zzz.py`` (sorts LAST): an UNTESTED public library module, so
        ``cover-gaps`` (0.90, a flagship CONCRETE move) has pending work there.

    Under alphabetical order the chain would lead with ``app/aaa.py``; under the
    value-ranked order it must lead with ``app/zzz.py``."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".apex").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "aaa.py").write_text(
        "def render(text, color=None, width=80):\n    return text[:width]\n",
        encoding="utf-8")
    (tmp_path / "app" / "zzz.py").write_text(
        "def hub(a, b):\n    return a + b\n", encoding="utf-8")
    # Only aaa.py is referenced by a test → zzz.py is an uncovered gap.
    (tmp_path / "tests" / "test_aaa.py").write_text(
        "from app.aaa import render\n"
        "def test_render():\n    assert render('hi', width=2) == 'hi'\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (tmp_path / ".apex" / "dream-promotions.json").write_text(json.dumps([
        {"key": "confluence:app/aaa.py", "kind": "confluence"},
        {"key": "confluence:app/zzz.py", "kind": "confluence"},
    ]), encoding="utf-8")
    return tmp_path


def _single_confluence_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / ".apex").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "solo.py").write_text(
        "def hub(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (tmp_path / ".apex" / "dream-promotions.json").write_text(json.dumps([
        {"key": "confluence:app/solo.py", "kind": "confluence"}]),
        encoding="utf-8")
    return tmp_path


# --- 1. the multi-confluence order FLIPS by value ----------------------------

def test_multi_confluence_order_flips_by_value(tmp_path):
    _two_confluence_project(tmp_path)
    # Default: alphabetical (the historical order) — aaa before zzz.
    assert dream_confluence_modules(str(tmp_path)) == ["app/aaa.py", "app/zzz.py"]
    # Opted in: the higher-value module (zzz, the uncovered concrete gap) LEADS,
    # despite sorting alphabetically LAST — value beats name.
    ranked = dream_confluence_modules(str(tmp_path), value_ranked=True)
    assert ranked == ["app/zzz.py", "app/aaa.py"]
    # It is a PERMUTATION — the same set, only re-ordered (never a new membership).
    assert set(ranked) == {"app/aaa.py", "app/zzz.py"}


def test_landable_value_scores_credit_the_higher_value_module(tmp_path):
    _two_confluence_project(tmp_path)
    scores = _module_landable_value(str(tmp_path))
    # Both modules carry pending work, and the uncovered concrete gap (zzz) scores
    # STRICTLY higher than the cheap-tidy-only module (aaa) — so the flip is earned
    # by buyer-value, not an accident of iteration order.
    assert scores["app/zzz.py"] > scores["app/aaa.py"]
    assert scores["app/aaa.py"] > 0.0  # aaa still has landable (dead-param) value


# --- 2. single / empty stay BYTE-IDENTICAL whether or not opted in -----------

def test_single_confluence_is_byte_identical_regardless_of_opt_in(tmp_path):
    _single_confluence_project(tmp_path)
    default = dream_confluence_modules(str(tmp_path))
    ranked = dream_confluence_modules(str(tmp_path), value_ranked=True)
    # Nothing to reorder: one module is byte-identical under both orders.
    assert default == ["app/solo.py"]
    assert ranked == default


def test_empty_project_is_byte_identical_regardless_of_opt_in(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("x = 1\n", encoding="utf-8")
    # No promotion store and no signals → no confluence; both orders are [].
    assert dream_confluence_modules(str(tmp_path)) == []
    assert dream_confluence_modules(str(tmp_path), value_ranked=True) == []


def test_rank_confluences_returns_short_lists_unchanged(tmp_path):
    # The helper itself short-circuits 0/1-module lists (nothing to reorder),
    # so it never even consults the value model for them.
    assert _rank_confluences([], str(tmp_path)) == []
    assert _rank_confluences(["app/only.py"], str(tmp_path)) == ["app/only.py"]


# --- 3. the ranking is DETERMINISTIC -----------------------------------------

def test_value_rank_is_deterministic_across_runs(tmp_path):
    _two_confluence_project(tmp_path)
    first = dream_confluence_modules(str(tmp_path), value_ranked=True)
    second = dream_confluence_modules(str(tmp_path), value_ranked=True)
    third = _rank_confluences(["app/aaa.py", "app/zzz.py"], str(tmp_path))
    # No clock, no randomness: same input → same output, every time.
    assert first == second == third == ["app/zzz.py", "app/aaa.py"]


# --- 4. ties fall back to ALPHABETICAL ---------------------------------------

def test_ties_fall_back_to_alphabetical(tmp_path):
    # Two modules with IDENTICAL landable value (the value model cannot separate
    # them) MUST fall back to the existing alphabetical key — total determinism.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    # Identical-shaped dead-param modules → identical per-module value.
    (tmp_path / "app" / "m_b.py").write_text(
        "def f(text, dead=None, width=80):\n    return text[:width]\n",
        encoding="utf-8")
    (tmp_path / "app" / "m_a.py").write_text(
        "def g(text, dead=None, width=80):\n    return text[:width]\n",
        encoding="utf-8")
    scores = _module_landable_value(str(tmp_path))
    assert scores.get("app/m_a.py", 0.0) == scores.get("app/m_b.py", 0.0)
    # Passed in reverse-alphabetical order, the tie restores alphabetical order.
    ranked = _rank_confluences(["app/m_b.py", "app/m_a.py"], str(tmp_path))
    assert ranked == ["app/m_a.py", "app/m_b.py"]


def test_zero_value_modules_order_alphabetically(tmp_path):
    # Modules the value model scores at 0 (no pending landable work) are an
    # all-ties case → pure alphabetical, identical to the historical order.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "b.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "app" / "a.py").write_text("y = 1\n", encoding="utf-8")
    ranked = _rank_confluences(["app/b.py", "app/a.py"], str(tmp_path))
    assert ranked == ["app/a.py", "app/b.py"]


# --- 5. the OPT-IN default (OFF) is byte-identical everywhere -----------------

def test_default_off_is_a_pure_permutation_of_the_alphabetical_set(tmp_path):
    _two_confluence_project(tmp_path)
    # The DEFAULT (value_ranked omitted / False) is EXACTLY the historical
    # alphabetical order — opting in is the only way the order can change.
    assert dream_confluence_modules(str(tmp_path)) == ["app/aaa.py", "app/zzz.py"]
    # And the opted-in order is a permutation of that same set — never a different
    # membership, so it can never land a module the alphabetical order would not.
    assert (set(dream_confluence_modules(str(tmp_path), value_ranked=True))
            == set(dream_confluence_modules(str(tmp_path))))


# --- 6. dream_develop / compile_from_dream consume the ranked order ----------

def test_dream_develop_leads_with_the_highest_value_confluence(tmp_path):
    from app.engine.dream_develop import dream_develop

    _two_confluence_project(tmp_path)
    # Default chain: the modules scope is alphabetical (historical behaviour).
    base = dream_develop(str(tmp_path), apply=False, verify=False)
    assert base.modules == ["app/aaa.py", "app/zzz.py"]
    # Opted in: the chain's module scope leads with the highest-value confluence.
    ranked = dream_develop(str(tmp_path), apply=False, verify=False,
                           value_ranked=True)
    assert ranked.modules == ["app/zzz.py", "app/aaa.py"]
    # Same SET of modules — value re-orders WHICH file the chain visits first,
    # never WHICH files it visits (so it can never widen the landing scope).
    assert set(ranked.modules) == set(base.modules)


def test_compile_from_dream_consumes_ranked_order(tmp_path):
    from app.engine.dream_landing import compile_from_dream

    # Both modules carry a dead-param move, so each yields a non-empty campaign and
    # the per-module order is legible from the FIRST campaign's step target. zzz.py
    # is ALSO uncovered, so it still outscores aaa.py on landable buyer-value.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".apex").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "aaa.py").write_text(
        "def render(text, color=None, width=80):\n    return text[:width]\n",
        encoding="utf-8")
    (tmp_path / "app" / "zzz.py").write_text(
        "def hub(a, dead=None):\n    return a\n", encoding="utf-8")
    (tmp_path / "tests" / "test_aaa.py").write_text(
        "from app.aaa import render\n"
        "def test_render():\n    assert render('hi', width=2) == 'hi'\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (tmp_path / ".apex" / "dream-promotions.json").write_text(json.dumps([
        {"key": "confluence:app/aaa.py", "kind": "confluence"},
        {"key": "confluence:app/zzz.py", "kind": "confluence"},
    ]), encoding="utf-8")

    def _first_target(results):
        for r in results:
            for s in r.steps:
                return s.target
        return ""

    # Default: one dead-params CompileResult per module, ALPHABETICAL order — the
    # first landed step targets aaa.py (byte-identical to before this wave).
    base = compile_from_dream(str(tmp_path), apply=False, verify=False)
    assert _first_target(base).startswith("app/aaa.py")
    # Opted in: the per-module campaigns lead with the highest-value module, so the
    # first landed step targets zzz.py despite its alphabetical-last name.
    ranked = compile_from_dream(str(tmp_path), apply=False, verify=False,
                                value_ranked=True)
    assert _first_target(ranked).startswith("app/zzz.py")
