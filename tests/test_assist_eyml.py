"""Tests for ``apex assist`` — the conversational UNDERSTAND→PLAN→ACT→EXPLAIN loop.

These exercise the LOOP WIRING: that each understood intent routes to the right
shipped organ, that the read-only routes write NOTHING, that a develop request
previews-then-lands through the existing gated compiler, that the proactive
"what should I build next?" reaches the DREAM core, and that an unmappable request
gets an honest no-capability answer (never a fabricated action). Comprehend's
vocabulary accuracy is Wave-2b's concern; here we assume comprehend returns what
it returns and verify the loop around it.
"""

from __future__ import annotations

from pathlib import Path

from app.agent.assist import (
    NEXT_WORK_PHRASES,
    assist,
    is_next_work_question,
    render_assist_markdown,
)


# --- fixtures ---------------------------------------------------------------

def _modernize_project(tmp_path: Path) -> Path:
    """A tiny project with a ``== None`` the modernizer rewrites, covered by a
    test that exercises the function (so the move lands VERIFIED)."""
    (tmp_path / "mod.py").write_text(
        "def greet(name):\n"
        "    if name == None:\n"
        "        return 'hi'\n"
        "    return 'hi ' + name\n",
        encoding="utf-8")
    (tmp_path / "test_mod.py").write_text(
        "from mod import greet\n"
        "def test_greet():\n"
        "    assert greet('a') == 'hi a'\n"
        "    assert greet(None) == 'hi'\n",
        encoding="utf-8")
    return tmp_path


def _stub_project(tmp_path: Path) -> Path:
    """A tiny project with an unimplemented stub + an un-hinted function — the
    concrete ``ship-value`` work the DREAM core surfaces as directions."""
    (tmp_path / "calc.py").write_text(
        '"""A tiny library."""\n\n\n'
        "def add(a, b):\n"
        '    """Return the sum."""\n'
        "    return a + b\n\n\n"
        "def multiply(a, b):\n"
        '    """Return the product."""\n'
        "    raise NotImplementedError\n",
        encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(
        "from calc import add, multiply\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
        "def test_multiply():\n"
        "    assert multiply(2, 3) == 6\n",
        encoding="utf-8")
    return tmp_path


def _tree_snapshot(root: Path) -> dict[str, str]:
    """Every .py file's content — to assert a read-only route changed nothing."""
    return {str(p): p.read_text(encoding="utf-8") for p in root.rglob("*.py")}


# --- the next-work self-classifier ------------------------------------------

def test_next_work_classifier_matches_the_phrase_set():
    assert is_next_work_question("what should I build next?")
    assert is_next_work_question("What's next?")
    assert is_next_work_question("Tell me the highest value work")
    # Turkish surface (the loop is its own EN+TR classifier, not a comprehend field)
    assert is_next_work_question("sırada ne var")
    assert is_next_work_question("ne geliştirmeli")


def test_next_work_classifier_rejects_plain_questions_and_commands():
    assert not is_next_work_question("is this well tested?")
    assert not is_next_work_question("add type hints to the auth module")
    assert not is_next_work_question("")
    # every table phrase is non-empty and lowercase (deterministic substring match)
    assert all(p and p == p.lower() for p in NEXT_WORK_PHRASES)


# --- the DREAM ROUTE: "what should I build next?" ---------------------------

def test_next_work_question_routes_to_dream_core(tmp_path):
    root = _stub_project(tmp_path)
    before = _tree_snapshot(root)

    result = assist("what should I build next?", target=str(root))

    assert result.route == "dream"
    assert result.applied is False
    # Ranked, value-led concrete directions, each carrying objective + target.
    directions = result.payload["directions"]
    assert directions, "the stub project should surface at least one direction"
    objectives = [d["objective"] for d in directions]
    assert "implement-stub" in objectives
    for d in directions:
        assert d["objective"] and d["target"]
    # Highest buyer-value first (value-led order is preserved into the payload).
    values = [d["value"] for d in directions]
    assert values == sorted(values, reverse=True)
    # The narrative offers the one-command follow-ups.
    assert "apex dream --land --apply" in result.narrative
    assert "apex develop" in result.narrative
    # READ-ONLY: nothing was written.
    assert _tree_snapshot(root) == before


def test_dream_route_narrates_grounded_directions(tmp_path):
    root = _stub_project(tmp_path)
    md = assist("what next?", target=str(root)).narrative
    assert "You asked:" in md
    assert "DREAM core" in md
    # The objective + a buyer-value number appear, grounded in the real chain.
    assert "implement-stub" in md
    assert "buyer-value" in md


# --- the QUESTION route: grade ----------------------------------------------

def test_plain_question_routes_to_grade(tmp_path):
    root = _modernize_project(tmp_path)
    before = _tree_snapshot(root)

    result = assist("is this well tested?", target=str(root))

    assert result.route == "grade"
    assert result.applied is False
    # Real grade numbers, not advice.
    assert isinstance(result.payload["score"], int)
    assert 0 <= result.payload["score"] <= 100
    assert result.payload["letter"]
    assert "components" in result.payload
    # The narrative echoes the question and shows the grounded breakdown.
    assert "is this well tested?" in result.narrative
    assert "/100" in result.narrative
    # READ-ONLY.
    assert _tree_snapshot(root) == before


# --- the DEVELOP route: preview then land -----------------------------------

def test_develop_request_previews_without_writing(tmp_path):
    root = _modernize_project(tmp_path)
    before = _tree_snapshot(root)

    result = assist("modernize the code", target=str(root), apply=False)

    assert result.route == "develop"
    assert result.applied is False
    # PLAN: the right objective is named and value-led.
    assert "modernize" in result.payload["objectives"]
    assert result.comprehension.action == "develop"
    # The narrative echoes the understanding and grounds the preview.
    assert "I understood a **develop** request" in result.narrative
    assert "Preview" in result.narrative
    # PREVIEW writes nothing.
    assert _tree_snapshot(root) == before


def test_develop_request_apply_lands_covered_move_suite_green(tmp_path):
    root = _modernize_project(tmp_path)

    result = assist("modernize the code", target=str(root), apply=True)

    assert result.route == "develop"
    assert result.applied is True
    # The covered move actually landed and is VERIFIED (a test exercises greet()).
    after = (root / "mod.py").read_text(encoding="utf-8")
    assert "if name is None" in after
    assert "== None" not in after
    assert "verified move(s)" in result.narrative
    # A verified move proves the suite ran green through the gated compiler.
    verified = sum(
        1 for r in result._results for s in r.steps if s.coverage_verified)
    assert verified >= 1


def test_report_mode_pins_preview_even_with_apply(tmp_path):
    """An explicit "just show me" (report mode) previews even with apply=True —
    SAFE by default; the resolved write gate honors comprehend's mode."""
    root = _modernize_project(tmp_path)
    before = _tree_snapshot(root)

    result = assist("just show me how you would modernize the code",
                    target=str(root), apply=True)

    assert result.route == "develop"
    assert result.comprehension.mode == "report"
    assert result.applied is False
    assert result.payload["write"] is False
    assert _tree_snapshot(root) == before


# --- scope restriction ------------------------------------------------------

def test_scope_request_restricts_to_the_named_module(tmp_path):
    """A request naming a module scopes the campaign to it (the compiler's
    ``scope_module``). Two modules, only one named — only it is targeted."""
    (tmp_path / "alpha.py").write_text(
        "def f(name):\n    if name == None:\n        return 1\n    return 2\n",
        encoding="utf-8")
    (tmp_path / "beta.py").write_text(
        "def g(name):\n    if name == None:\n        return 3\n    return 4\n",
        encoding="utf-8")
    (tmp_path / "test_both.py").write_text(
        "from alpha import f\nfrom beta import g\n"
        "def test_f():\n    assert f('x') == 2\n"
        "def test_g():\n    assert g('x') == 4\n",
        encoding="utf-8")

    result = assist("modernize the alpha module", target=str(tmp_path))

    assert result.comprehension.scope == "alpha"
    assert result.payload["scope"] == "alpha"
    # The bare hint resolved to the real module path the compiler scopes to.
    assert result.payload["scope_module"] == "alpha.py"
    # Every previewed step targets the scoped module only.
    targets = [s.target for r in result._results for s in r.steps]
    assert targets, "alpha has a modernizable line, so a move is previewed"
    assert all(t.startswith("alpha.py") for t in targets)


# --- the HONEST fallback: no matching capability ----------------------------

def test_unmappable_request_is_honest_and_recommends(tmp_path):
    root = _modernize_project(tmp_path)
    before = _tree_snapshot(root)

    result = assist("xyzzy foobar", target=str(root))

    assert result.route == "recommend"
    assert result.applied is False
    # HONEST: it says plainly it has no capability — never fabricates an action.
    assert "couldn't map this to a capability" in result.narrative
    assert "no matching capability" in result.narrative.lower()
    assert "don't have a capability that matches" in result.narrative
    assert result.comprehension.objectives == []
    # It still routes to a grounded recommend (the roadmap's best next moves).
    assert "quick_wins" in result.payload
    assert "apex auto" in result.narrative
    # READ-ONLY.
    assert _tree_snapshot(root) == before


def test_removal_of_additive_is_refused_not_inverted(tmp_path):
    """A removal-framed request that only matches ADD lenses must NOT invert intent
    — comprehend suppresses it (low confidence, no objectives), so assist routes to
    the honest recommend, never to a develop run that ADDS what was asked removed."""
    root = _modernize_project(tmp_path)
    before = _tree_snapshot(root)

    result = assist("remove the docstrings", target=str(root))

    assert result.route == "recommend"
    assert result.applied is False
    assert _tree_snapshot(root) == before


# --- determinism ------------------------------------------------------------

def test_dream_route_is_deterministic(tmp_path):
    root = _stub_project(tmp_path)
    a = assist("what should I build next?", target=str(root)).narrative
    b = assist("what should I build next?", target=str(root)).narrative
    assert a == b


def test_grade_route_is_deterministic(tmp_path):
    root = _modernize_project(tmp_path)
    a = assist("is this well tested?", target=str(root)).narrative
    b = assist("is this well tested?", target=str(root)).narrative
    assert a == b


def test_develop_preview_is_deterministic(tmp_path):
    root = _modernize_project(tmp_path)
    a = assist("modernize the code", target=str(root), apply=False).narrative
    b = assist("modernize the code", target=str(root), apply=False).narrative
    assert a == b


# --- the renderer ECHOES the understanding ----------------------------------

def test_render_echoes_request_and_understanding(tmp_path):
    root = _modernize_project(tmp_path)
    result = assist("add type hints to mod.py", target=str(root), apply=False)
    md = render_assist_markdown(result)
    # The echo block quotes the request and states the understood action + mode.
    assert "**You asked:** «add type hints to mod.py»" in md
    assert "I understood a **develop** request" in md
    assert "Confidence:" in md


def test_to_dict_is_json_safe(tmp_path):
    import json

    root = _stub_project(tmp_path)
    result = assist("what should I build next?", target=str(root))
    payload = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "dream" in payload
    assert "implement-stub" in payload
