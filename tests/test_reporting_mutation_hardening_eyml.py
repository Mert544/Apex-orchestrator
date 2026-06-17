"""Mutation-hardening tests for the reporting modules.

Each test here exists to KILL a specific surviving mutant in one of the four
assigned modules (``dashboard``, ``dashboard_sections``, ``deadcode``,
``idea_canvas``) — a mutation the prior suite did not catch. Every test names
the exact mutated token in its docstring so the blind spot it closes is
auditable. All are deterministic and hermetic: synthetic ``tmp_path``
projects, hand-built data objects / ``SimpleNamespace`` stand-ins, and (where
the engine would otherwise run) a monkeypatched constructor — never a clock,
network, or randomness.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.models.idea import IdeaNode
from app.reporting import dashboard as d
from app.reporting import idea_canvas as ic
from app.reporting.dashboard_sections import RenderedSections
from app.reporting.deadcode import find_dead_code, render_dead_code_markdown


def _pyproject(tmp) -> None:
    (tmp / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")


# --------------------------------------------------------------------------
# deadcode.py
# --------------------------------------------------------------------------


def test_dunder_guard_needs_both_ends_not_either(tmp_path):
    """Kills line 131 ``and``->``or`` in ``_candidates``' dunder guard.

    The exclusion is for true dunders (``__x__``: starts AND ends with ``__``).
    A name that only STARTS with ``__`` (``__leading``) is an ordinary private
    symbol and must still be reported dead. Flipping ``and`` to ``or`` would
    wrongly exclude it (the ``startswith`` alone would satisfy ``or``).
    """
    _pyproject(tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "m.py").write_text("def __leading(x):\n    return 1\n")

    names = {r["symbol"] for r in find_dead_code(str(tmp_path))}
    assert "__leading" in names  # starts-with-only -> not a dunder -> still dead


def test_default_limit_caps_results_at_forty(tmp_path):
    """Kills line 212 ``40``->``41`` in ``find_dead_code``'s default ``limit``.

    With 41 unreferenced private symbols and the default limit, exactly 40 rows
    come back. Bumping the default to 41 would return 41 instead.
    """
    _pyproject(tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    body = "".join(f"def _dead{i}():\n    return {i}\n\n" for i in range(41))
    (tmp_path / "pkg" / "m.py").write_text(body)

    rows = find_dead_code(str(tmp_path))
    assert len(rows) == 40  # default limit is 40, not 41


def test_render_summary_reports_exact_high_count(tmp_path):
    """Kills line 239 ``sum(1 ...)``->``sum(2 ...)`` counting high-confidence rows.

    A single private (high-confidence) finding must read "1 are private"; the
    ``2`` mutant would double the count to "2 are private".
    """
    rows = [{"module": "m.py", "symbol": "_a", "kind": "function",
             "line": 1, "confidence": "high"}]
    md = render_dead_code_markdown(rows)
    assert "1 are private" in md
    assert "2 are private" not in md


# --------------------------------------------------------------------------
# idea_canvas.py
# --------------------------------------------------------------------------


def test_node_id_prefers_id_over_branch_path(tmp_path):
    """Kills line 61 FIRST ``or``->``and`` in ``_node_id``.

    ``idea.id or idea.branch_path or idea.title`` must return the id when it is
    truthy. Flipping the first ``or`` to ``and`` yields
    ``(id and branch_path) or title`` -> the branch_path, so the node would
    carry the wrong id.
    """
    idea = IdeaNode(id="THE-ID", title="T", branch_path="THE-BRANCH")
    assert ic._node_id(idea) == "THE-ID"
    canvas = ic.canvas_from_ideas([idea])
    assert canvas["nodes"][0]["id"] == "THE-ID"


def test_node_id_falls_back_to_branch_path_before_title(tmp_path):
    """Kills line 61 SECOND ``or``->``and`` in ``_node_id``.

    With an empty id, ``"" or branch_path or title`` must return the
    branch_path. Flipping the second ``or`` to ``and`` gives
    ``"" or (branch_path and title)`` -> the title, so the fallback would skip
    branch_path entirely.
    """
    idea = IdeaNode(id="", title="THE-TITLE", branch_path="THE-BRANCH")
    assert ic._node_id(idea) == "THE-BRANCH"


def test_idea_canvas_forwards_config_not_none(monkeypatch, tmp_path):
    """Kills line 93 ``engine_config or None``->``and`` in ``idea_canvas``.

    A non-empty config must reach the engine unchanged. ``config and None``
    collapses any truthy config to ``None`` (engine defaults), so we capture the
    constructor's first argument and assert it is the dict we passed.
    """
    captured = {}

    class _FakeEngine:
        def __init__(self, config, project_root):
            captured["config"] = config

        def run(self, *a, **k):
            return SimpleNamespace(ideas=[])

    monkeypatch.setattr(ic, "IdeaPermutationEngine", _FakeEngine)
    ic.idea_canvas(str(tmp_path), max_total_ideas=7, breadth=2)
    assert captured["config"] == {"max_total_ideas": 7, "breadth": 2}


# --------------------------------------------------------------------------
# dashboard.py — pure hero-metric helpers
# --------------------------------------------------------------------------


def test_hero_coverage_pct_present_scales_ratio_to_percent():
    """Kills line 445 ``* 100`` (->``/``), the ``0`` default, and ``100``->``101``.

    A ratio of 0.5 must read 50, not 0.005, 51, or anything else.
    """
    assert d._hero_coverage_pct({"coverage": {"coverage_ratio": 0.5}}) == 50


def test_hero_coverage_pct_absent_is_minus_one_not_zero():
    """Kills line 443 ``not in``->``in`` and line 444 ``-1``->``None`` / ``1``->``2``.

    With no ``coverage_ratio`` key the sentinel is exactly ``-1`` (the caller
    distinguishes "unavailable" from a real 0%). ``in`` instead of ``not in``
    would invert the guard; ``-1``->``None`` / ``1``->``2`` would change the
    sentinel.
    """
    assert d._hero_coverage_pct({"coverage": {}}) == -1
    assert d._hero_coverage_pct({}) == -1


def test_hero_coverage_pct_or_guards_none_coverage_block():
    """Kills line 442 ``or``->``and`` in ``findings.get("coverage", {}) or {}``.

    A ``None`` coverage value must fall back to ``{}`` (then -1). ``and`` would
    keep the ``None`` and crash on ``in``.
    """
    assert d._hero_coverage_pct({"coverage": None}) == -1


def test_hero_security_count_returns_real_count():
    """Kills line 451 ``findings_count`` ``0`` default and the ``or 0`` tail.

    A present count of 3 must read 3; absent must read 0 (the ``or 0`` guard).
    """
    assert d._hero_security_count({"security": {"findings_count": 3}}) == 3
    assert d._hero_security_count({"security": {}}) == 0


def test_hero_security_count_or_guards_none_security_block():
    """Kills line 450 ``or``->``and`` in ``findings.get("security", {}) or {}``."""
    assert d._hero_security_count({"security": None}) == 0


def test_hero_scope_pct_scales_analyzed_ratio():
    """Kills line 456 ``* 100`` (->``/``) and ``100``->``101`` in ``_hero_scope_pct``."""
    from types import SimpleNamespace as NS
    assert d._hero_scope_pct(NS(analyzed_ratio=0.5)) == 50


def test_hero_scope_pct_defaults_to_full_when_absent():
    """Kills line 456 default ``1.0``->``2.0`` in the ``getattr`` fallback.

    A profile without ``analyzed_ratio`` is treated as fully in-scope (100%),
    not 200%.
    """
    from types import SimpleNamespace as NS
    assert d._hero_scope_pct(NS()) == 100


def test_hero_top_move_is_first_step_title_or_empty():
    """Kills line 462 ``steps[0]``->``steps[1]``-ish ``0``->``1`` and the empty path."""
    from types import SimpleNamespace as NS
    plan = NS(steps=[NS(title="FIRST"), NS(title="second")])
    assert d._hero_top_move(plan) == "FIRST"
    assert d._hero_top_move(NS(steps=[])) == ""


def test_hero_charts_html_omitted_when_score_negative_and_scope_negative():
    """Kills line 484/485 ``>= 0`` boundary/comparison and line 486 ``or`` guard.

    A negative grade score AND negative scope -> no chart strip at all.
    """
    assert d._hero_charts_html("", -1, -1) == ""


def test_hero_charts_html_present_when_scope_zero():
    """Kills line 485 ``scope_pct >= 0`` ->``>`` boundary slip.

    Scope of exactly 0 is valid (an all-non-Python repo) and must still render
    the scope bar; ``> 0`` would wrongly drop the boundary value.
    """
    out = d._hero_charts_html("", -1, 0)
    assert out.startswith("<div class='hero-charts'>")
    assert "svg" in out


def test_hero_top_move_html_wraps_or_blanks():
    """Kills line 491 ``if top_move`` empty-path and the return-value mutant."""
    assert d._hero_top_move_html("X") == "<p class='vital-top-move'>X</p>"
    assert d._hero_top_move_html("") == ""


# --------------------------------------------------------------------------
# dashboard.py — section-gating predicates
# --------------------------------------------------------------------------


def test_shape_has_ideas_requires_nonzero_total():
    """Kills line 539 ``is not``->``is``, ``and``->``or``, ``0``->``1``.

    A shape with 0 ideas is NOT renderable; only a positive total is.
    """
    from types import SimpleNamespace as NS
    assert d._shape_has_ideas(None) is False
    assert d._shape_has_ideas(NS(total_ideas=0)) is False
    assert d._shape_has_ideas(NS(total_ideas=3)) is True


def test_roadmap_has_phases_requires_phases():
    """Kills line 544 ``is not``->``is`` and ``and``->``or`` in the phases gate."""
    from types import SimpleNamespace as NS
    assert d._roadmap_has_phases(None) is False
    assert d._roadmap_has_phases(NS(phases=[])) is False
    assert d._roadmap_has_phases(NS(phases=[object()])) is True


def test_learned_has_entries_needs_either_reliability_list():
    """Kills line 549 ``and``->``or`` and ``or``->``and`` in the learned gate.

    Empty lists -> no card; either list non-empty -> card. ``or``->``and`` would
    require BOTH lists; ``and``->``or`` would render for empty learned.
    """
    assert d._learned_has_entries(None) is False
    assert d._learned_has_entries({"most_reliable": [], "least_reliable": []}) is False
    assert d._learned_has_entries({"most_reliable": [{"key": "k"}]}) is True
    assert d._learned_has_entries({"least_reliable": [{"key": "k"}]}) is True


def test_dream_exists_checks_digest_file(tmp_path):
    """Kills line 554 ``/`` path-join ->``*`` in ``_dream_exists``.

    The digest lives at ``.apex/dream-digest.md``; mutating the path division
    would look elsewhere and never find it.
    """
    assert d._dream_exists(str(tmp_path)) is False
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "dream-digest.md").write_text("- a dream\n")
    assert d._dream_exists(str(tmp_path)) is True


# --------------------------------------------------------------------------
# dashboard.py — _build_autonomy / _build_pareto
# --------------------------------------------------------------------------


def test_build_autonomy_acts_only_on_clean_tree():
    """Kills line 163 ``and``/``or`` flips and ``== 0``->``!= 0`` in tree_clean.

    A clean tree (dirty 0) with safe fixes -> act; a dirty tree -> recommend.
    """
    from types import SimpleNamespace as NS
    plan = NS(stats={"executable_steps": 4})
    clean = d._build_autonomy(plan, {"dirty": 0})
    dirty = d._build_autonomy(plan, {"dirty": 2})
    assert clean["act"] is True
    assert dirty["act"] is False
    # Empty git => not clean => recommend (kills the bool(git) and ... guard).
    assert d._build_autonomy(plan, {})["act"] is False


def test_build_autonomy_reports_executable_count():
    """Kills line 168 ``0`` default in the ``executable`` echo-back."""
    from types import SimpleNamespace as NS
    plan = NS(stats={"executable_steps": 4})
    assert d._build_autonomy(plan, {"dirty": 0})["executable"] == 4


def test_build_pareto_empty_when_roadmap_is_none():
    """Kills line 133 ``is not None``->``is None`` in ``_build_pareto``.

    With no roadmap the frontier is empty; flipping the ``is not`` guard would
    call ``frontier_from_roadmap(None)`` instead.
    """
    assert d._build_pareto(None) == []
