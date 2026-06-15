"""Natural-language intent vocabulary for the objective compiler.

These cover ``resolve_objective`` / ``objective_synonyms`` and the wiring into
``compile_objective``: a free-text goal ("clean up the imports", "lock down
auth", "speed up") resolves to the right registered objective, deterministically
and table-driven (no fuzzy/LLM matching). Construction style mirrors
``test_objective_compiler.py``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.objective_compiler import (
    available_objectives,
    compile_objective,
    objective_synonyms,
    resolve_objective,
)


def _project(tmp_path: Path, body: str) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(body, encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_import():\n    assert app.m is not None\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


# --- resolution: natural phrases reach the intended objective ----------------

@pytest.mark.parametrize("request_text,expected", [
    # tidy / quality surface verbs → modernize
    ("tidy up this module", "modernize"),
    ("clean up the code", "modernize"),
    ("refactor it", "modernize"),
    ("please optimize this", "modernize"),
    ("can we speed up the parser", "modernize"),
    ("harden the auth path", "modernize"),
    ("lock down the endpoint", "modernize"),
    ("sanitize the inputs", "modernize"),
    # imports
    ("sort import block", "sort-imports"),
    ("organize imports", "sort-imports"),
    ("clean up imports", "sort-imports"),       # more-specific phrase wins
    ("drop the unused imports", "remove-unused-imports"),
    # dead code / params
    ("remove dead code", "remove-dead-code"),
    ("strip unreachable branches", "remove-dead-code"),
    ("drop unused parameters", "dead-params"),
    # restructure
    ("shrink the long functions", "shrink-functions"),
    ("split function into helpers", "shrink-functions"),
    ("decouple these helpers", "shrink-functions"),
    ("untangle this", "shrink-functions"),
    ("inline that helper", "inline-helpers"),
    # dedup / constants / bools / comprehensions
    ("remove the duplicated blocks", "dedup"),
    ("copy-paste cleanup", "dedup"),
    ("name the magic numbers", "extract-constant"),
    ("simplify boolean return", "simplify-bool-return"),
    ("turn that loop into a comprehension", "simplify-comprehension"),
])
def test_natural_phrases_resolve_to_expected_objective(request_text, expected):
    assert resolve_objective(request_text) == expected
    # Every resolved target is a real, runnable objective.
    assert expected in available_objectives()


def test_exact_objective_name_resolves_to_itself_unchanged():
    # An exact registered name always wins — the synonym table NEVER redirects a
    # literal objective slug (the regression guard for existing behaviour).
    for name in available_objectives():
        assert resolve_objective(name) == name


def test_case_insensitive_exact_name():
    assert resolve_objective("DEAD-PARAMS") == "dead-params"
    assert resolve_objective("Modernize") == "modernize"


def test_unrecognized_request_returns_none():
    assert resolve_objective("make me a sandwich") is None
    assert resolve_objective("") is None
    assert resolve_objective(None) is None
    assert resolve_objective("   ") is None


def test_resolution_is_deterministic():
    # Same input → same output, twice, for a sample of phrases.
    for phrase in ("clean up imports", "harden auth", "speed up", "dead-params",
                   "untangle this", "make me a sandwich"):
        assert resolve_objective(phrase) == resolve_objective(phrase)


def test_synonyms_table_targets_are_all_real_objectives():
    known = set(available_objectives())
    table = objective_synonyms()
    assert table  # non-empty
    for objective, triggers in table.items():
        assert objective in known
        assert triggers and all(isinstance(t, str) and t for t in triggers)


# --- wiring: compile_objective accepts a free-text objective -----------------

_TIDY = (
    "def check(x):\n    if x == None:\n        return dict()\n"
    "    msg = f\"done\"\n    return msg\n"
)


def test_compile_objective_accepts_natural_language(tmp_path):
    _project(tmp_path, _TIDY)
    # "tidy up" routes to the modernize objective and actually clears the debt.
    r = compile_objective(str(tmp_path), objective="tidy up the module",
                          apply=True, verify=False)
    assert r.objective == "modernize"
    assert r.fitness_start == 3.0 and r.fitness_end == 0.0
    src = (tmp_path / "app" / "m.py").read_text()
    assert "is None" in src and "return {}" in src and 'msg = "done"' in src


def test_compile_objective_exact_slug_is_unchanged(tmp_path):
    # The already-supported literal objective still compiles exactly as before —
    # the result reports the slug verbatim, not a re-resolved name.
    _project(tmp_path, _TIDY)
    r = compile_objective(str(tmp_path), objective="modernize", apply=True, verify=False)
    assert r.objective == "modernize"
    assert r.fitness_start == 3.0 and r.fitness_end == 0.0


def test_compile_objective_unresolvable_is_still_blocked(tmp_path):
    _project(tmp_path, "def f(x):\n    return x\n")
    r = compile_objective(str(tmp_path), objective="make-coffee", apply=True)
    assert r.steps == []
    assert any("unknown objective" in b for b in r.blocked)
