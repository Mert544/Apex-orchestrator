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
from app.reporting import dashboard_sections as s
from app.reporting import idea_canvas as ic
from app.reporting.deadcode import find_dead_code, render_dead_code_markdown


def _ns(**kw):
    return SimpleNamespace(**kw)


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
    # ratio 1.0 distinguishes ``* 100`` (->100) from ``* 101`` (->101).
    assert d._hero_coverage_pct({"coverage": {"coverage_ratio": 1.0}}) == 100


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
    # ratio 1.0 distinguishes ``* 100`` (->100) from ``* 101`` (->101).
    assert d._hero_scope_pct(NS(analyzed_ratio=1.0)) == 100


def test_hero_scope_pct_zero_ratio_stays_zero():
    """Kills line 456 ``or 0.0``->``or 1.0`` fallback in ``_hero_scope_pct``.

    An analyzed_ratio of exactly 0 is falsy, so the ``or 0.0`` tail keeps it 0
    (0% in scope). Mutating the fallback to 1.0 would read it as 100%.
    """
    from types import SimpleNamespace as NS
    assert d._hero_scope_pct(NS(analyzed_ratio=0.0)) == 0


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


def test_build_autonomy_missing_dirty_key_defaults_to_clean():
    """Kills line 163 ``git.get("dirty", 0)`` default ``0``->``1``.

    A git dict with no ``dirty`` key is treated as a clean tree (default 0), so
    with safe fixes it acts. Defaulting to 1 would read the tree as dirty.
    """
    from types import SimpleNamespace as NS
    plan = NS(stats={"executable_steps": 4})
    assert d._build_autonomy(plan, {"branch": "main"})["act"] is True


def test_build_autonomy_missing_executable_steps_defaults_to_zero():
    """Kills line 165 + 168 ``executable_steps`` default ``0``->``1``.

    With a clean tree but NO executable steps recorded (default 0), the policy
    must NOT act and the echoed count must be 0. Defaulting to 1 would flip both
    (act -> True, executable -> 1).
    """
    from types import SimpleNamespace as NS
    plan = NS(stats={})
    out = d._build_autonomy(plan, {"dirty": 0})
    assert out["act"] is False
    assert out["executable"] == 0


def test_build_pareto_uses_roadmap_when_present(monkeypatch):
    """Kills line 133 ``roadmap is not None``->``is None`` in ``_build_pareto``.

    A non-None roadmap must be forwarded to ``frontier_from_roadmap`` and its
    result returned; flipping ``is not`` to ``is`` would pass ``None`` instead
    and return ``[]``. We patch the frontier so the test is hermetic.
    """
    import app.engine.idea_pareto as pareto_mod
    sentinel = [object()]
    captured = {}

    def _fake(roadmap):
        captured["roadmap"] = roadmap
        return sentinel

    monkeypatch.setattr(pareto_mod, "frontier_from_roadmap", _fake)
    roadmap = object()
    assert d._build_pareto(roadmap) is sentinel
    assert captured["roadmap"] is roadmap


def test_build_pareto_empty_when_roadmap_is_none():
    """Kills line 133 ``is not None``->``is None`` in ``_build_pareto``.

    With no roadmap the frontier is empty; flipping the ``is not`` guard would
    call ``frontier_from_roadmap(None)`` instead.
    """
    assert d._build_pareto(None) == []


def test_git_info_non_repo_is_empty_dict(tmp_path):
    """Kills line 85 ``!=``->``==`` and line 86 ``return {}``->``None``.

    A directory that is not a git work tree yields an empty dict (not ``None``,
    not a populated dict). ``rev-parse --is-inside-work-tree`` returns ""
    (not "true") here, so the early ``return {}`` fires.
    """
    assert d._git_info(str(tmp_path)) == {}


def test_git_info_real_repo_is_populated(tmp_path):
    """Kills line 85 ``!=``->``==`` from the other side: a real work tree is
    detected ("true") and yields a populated dict, never the early ``{}``."""
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), capture_output=True)
    info = d._git_info(str(tmp_path))
    assert info != {}
    assert "branch" in info


# --------------------------------------------------------------------------
# dashboard_sections.py — pure section renderers
# --------------------------------------------------------------------------


def test_coverage_bar_tone_boundaries():
    """Kills line 218/219 ``* 100``, ``>= 70`` and ``>= 30`` boundary/comparison.

    Coverage tone buckets are good >=70, warn >=30, bad below — and the percent
    is the ratio times 100. We pin each boundary value's bucket and the percent.
    """
    assert "70%" in s._coverage_bar({"coverage_ratio": 0.70})
    assert "bar-good" in s._coverage_bar({"coverage_ratio": 0.70})
    assert "bar-warn" in s._coverage_bar({"coverage_ratio": 0.69})
    assert "bar-warn" in s._coverage_bar({"coverage_ratio": 0.30})
    assert "bar-bad" in s._coverage_bar({"coverage_ratio": 0.29})
    # ratio 1.0 distinguishes ``* 100`` (->100%) from ``* 101`` (->101%).
    assert "100%" in s._coverage_bar({"coverage_ratio": 1.0})


def test_coverage_bar_absent_is_blank():
    """Kills line 216 ``not in``->``in`` and line 217 ``return ""``->``None``."""
    assert s._coverage_bar({}) == ""


def test_quality_pct_bar_tone_and_clamp():
    """Kills line 957/958 ``* 100``, clamp ``min(100,...)``, ``>= 70``/``>= 30``.

    A ratio of 0.7 reads exactly 70% with the good tone; >1.0 clamps to 100%;
    <0 clamps to 0%.
    """
    assert "70%" in s._quality_pct_bar("L", 0.70)
    assert "bar-good" in s._quality_pct_bar("L", 0.70)
    assert "bar-warn" in s._quality_pct_bar("L", 0.69)
    # Exactly the warn boundary (kills ``>= 30``->``> 30`` and ``30``->``31``).
    assert "bar-warn" in s._quality_pct_bar("L", 0.30)
    assert "bar-bad" in s._quality_pct_bar("L", 0.29)
    assert "100%" in s._quality_pct_bar("L", 1.5)   # clamp high
    assert "0%" in s._quality_pct_bar("L", -0.3)    # clamp low


def test_overview_kpis_carry_exact_values():
    """Kills line 83 ``* 100``/``in`` and the security accent toggle.

    The overview KPI grid reflects the real numbers; we assert each appears and
    the coverage percent is the ratio*100 (40%, not 0.4% or 41%). Coverage 1.0
    distinguishes ``* 100`` from ``* 101``.
    """
    prof = _ns(total_files=11, import_cycles=["c1"], analyzed_ratio=0.5)
    findings = {"security": {"findings_count": 2},
                "coverage": {"coverage_ratio": 1.0},
                "docstring": {"gaps_found": 3}}
    out = s._overview(prof, findings, _ns(stats={"total_ideas": 5}),
                      _ns(stats={"total_steps": 8, "executable_steps": 4}), {})
    assert ">11<" in out          # files
    assert "100%" in out          # coverage 1.0 * 100 (kills *101)
    assert "a-red" in out         # security findings present -> red accent
    assert "8 executable" not in out  # sub is "4 executable"
    assert "4 executable" in out


def test_overview_defaults_when_findings_and_stats_empty():
    """Kills line 84/92/93/94 ``.get(..., 0)`` defaults and ``or 0`` tails.

    With every metric key absent, the KPIs read 0 — Security findings shows 0
    with the GREEN accent (no findings), Ideas/Action steps show 0. Bumping any
    default to 1 (or flipping ``or 0``) would change a value or the accent.
    """
    prof = _ns(total_files=0, import_cycles=[], analyzed_ratio=1.0)
    out = s._overview(prof, {"security": {}, "coverage": {}, "docstring": {}},
                      _ns(stats={}), _ns(stats={}), {})
    assert "<div class='kpi-val a-green'>0</div><div class='kpi-label'>Security findings</div>" in out
    assert "<div class='kpi-val a-green'>0</div><div class='kpi-label'>Import cycles</div>" in out
    assert "<div class='kpi-val a-violet'>0</div><div class='kpi-label'>Ideas</div>" in out


def test_overview_coverage_dash_when_absent():
    """Kills line 83 ``"coverage_ratio" in cov`` ->``not in``.

    With no coverage_ratio the KPI shows an em dash, not a percent.
    """
    prof = _ns(total_files=1, import_cycles=[], analyzed_ratio=1.0)
    out = s._overview(prof, {"coverage": {}}, _ns(stats={}),
                      _ns(stats={}), {})
    assert "<div class='kpi-val a-amber'>—</div><div class='kpi-label'>Coverage</div>" in out


def test_overview_git_uncommitted_defaults():
    """Kills line 97 ``git.get("dirty", 0)`` default ``0``->``1`` in the git KPI.

    A git dict lacking ``dirty`` shows 0 uncommitted; defaulting to 1 would lie.
    """
    prof = _ns(total_files=0, import_cycles=[], analyzed_ratio=1.0)
    out = s._overview(prof, {"security": {}, "coverage": {}, "docstring": {}},
                      _ns(stats={}), _ns(stats={}), {"branch": "main"})
    assert "<div class='kpi-val a-amber'>0</div><div class='kpi-label'>Uncommitted</div>" in out


def test_health_bars_security_monotonic_and_present():
    """Kills line 126 ``1.0 / (1.0 + findings)`` arithmetic (``/``->``*``, ``+``->``-``).

    Zero findings -> a full security bar (ratio 1.0). The renderer must emit the
    health-bars block whenever a security row exists.
    """
    out = s._health_bars(_ns(analyzed_ratio=0.5),
                         {"coverage": {"coverage_ratio": 0.5},
                          "security": {"findings_count": 0}})
    assert "Health bars" in out
    assert "Security" in out


def test_repo_section_empty_is_blank_and_populated_renders():
    """Kills line 137 ``return ""``->``None`` and the chip values."""
    assert s._repo_section({}) == ""
    out = s._repo_section({"branch": "main", "total_commits": "7",
                           "dirty": 3, "commits": ["abc fix"]})
    assert "main" in out and "7" in out and "abc fix" in out


def test_debug_section_empty_error_and_populated():
    """Kills line 152 ``return ""``->``None``, line 153 ``in``->``not in`` (error),
    and the anomalies/patterns counting."""
    assert s._debug_section({}) == ""
    assert "unavailable" in s._debug_section({"error": "boom"})
    out = s._debug_section({"trace_count": 5, "anomalies": ["a"],
                            "pattern_issues": ["p1", "p2"], "total_time_sec": 2})
    assert "5" in out          # traces
    assert "boom" not in out   # not the error path


def test_actions_section_executable_pill_and_value():
    """Kills the executable/design pill branch and the value cell in _actions_section."""
    plan = _ns(steps=[_ns(executable=True, patch_preview={"transform_type": "X"},
                          branch_path="b", action_type="at",
                          description="desc", value=9)],
               stats={"total_steps": 1, "executable_steps": 1, "design_tasks": 0})
    out = s._actions_section(plan)
    assert "pill exec" in out
    assert "executable" in out
    assert "desc" in out
    assert ">9<" in out


def test_actions_section_design_pill_when_not_executable():
    """Kills the ``s.executable`` ternary -> design pill branch."""
    plan = _ns(steps=[_ns(executable=False, patch_preview=None,
                          branch_path="b", action_type="at",
                          description="d", value=1)],
               stats={"total_steps": 1, "executable_steps": 0, "design_tasks": 1})
    out = s._actions_section(plan)
    assert "pill design" in out


def test_pareto_section_empty_and_dominated_count():
    """Kills line 683 ``return ""``->``None`` and line 684 ``total - len(points)``.

    With 1 frontier point out of 10 ideas, 9 are dominated.
    """
    assert s._pareto_section([], 5) == ""
    pts = [_ns(branch_path="bp", title="t", reasons=["r1", "r2"],
               impact=5, effort=2, roi=2.5)]
    out = s._pareto_section(pts, 10)
    assert "bp" in out
    assert "r1, r2" in out
    assert ">9<" in out          # dominated = 10 - 1


def test_autonomy_section_act_vs_recommend():
    """Kills the ``act`` truthiness branch in _autonomy_section."""
    yes = s._autonomy_section({"act": True, "mode": "supervised",
                               "executable": 3, "reason": "r"})
    no = s._autonomy_section({"act": False, "mode": "report",
                              "executable": 0, "reason": "r"})
    assert "would apply autonomously" in yes
    assert "apply" in yes
    assert "would recommend only" in no
    assert s._autonomy_section(None) == ""


def test_trackrecord_rates_dedup_and_sort():
    """Kills the dedup ``key in by_key`` and the ``-success_rate`` sort key.

    A key appearing in both lists is kept once (first wins); rows sort by rate
    descending, then key.
    """
    learned = {
        "most_reliable": [{"key": "b", "success_rate": 0.9, "samples": 10},
                          {"key": "a", "success_rate": 0.5, "samples": 4}],
        "least_reliable": [{"key": "a", "success_rate": 0.1, "samples": 9}],
    }
    rates = s._trackrecord_rates(learned)
    keys = [r["key"] for r in rates]
    assert keys == ["b", "a"]                 # rate desc; 'a' deduped to first (0.5)
    assert rates[1]["success_rate"] == 0.5    # first occurrence of 'a' won


def test_reasoning_section_error_path_and_chips():
    """Kills the ``"error" in r`` guard in _reasoning_section."""
    assert "unavailable" in s._reasoning_section({"error": "x"})
    out = s._reasoning_section({"mode": "fractal", "confidence_map": {"c": 0.5},
                                "debug_stats": {}, "estimated_total_tokens": 12})
    assert "fractal" in out
    assert "unavailable" not in out


def test_health_bars_or_guards_tolerate_none_blocks():
    """Kills line 117/118 ``or {}``->``and {}`` in _health_bars.

    ``None`` coverage/security blocks must coerce to ``{}`` (no crash); ``and``
    would keep ``None`` and raise on ``.get``/``in``.
    """
    out = s._health_bars(_ns(analyzed_ratio=0.5),
                         {"coverage": None, "security": None})
    assert "Health bars" in out


def test_health_bars_coverage_row_gated_by_key():
    """Kills line 120 ``"coverage_ratio" in cov``->``not in``.

    A coverage block lacking the ratio adds no coverage row (but the security
    row still renders). Inverting the guard would add a bogus row / drop the
    real one.
    """
    out = s._health_bars(_ns(analyzed_ratio=0.5),
                         {"coverage": {}, "security": {"findings_count": 0}})
    assert "Test coverage" not in out
    assert "Security" in out


def test_debug_section_counts_anomalies_and_patterns():
    """Kills line 159/162 ``len(anomalies)``/``len(patterns)`` chip values and the
    ``or []`` guards (lines 155/156)."""
    out = s._debug_section({"trace_count": 5, "anomalies": ["a", "b"],
                            "pattern_issues": ["p"], "total_time_sec": 2})
    assert "<b>2</b> anomalies" in out
    assert "<b>1</b> pattern issues" in out
    assert "<b>5</b> traces" in out


def test_debug_section_none_lists_default_to_empty():
    """Kills line 155/156 ``or []``->``and []`` (None anomalies/patterns).

    With ``None`` lists the section must show "No anomalies" (the empty path),
    not crash.
    """
    out = s._debug_section({"trace_count": 1, "anomalies": None,
                            "pattern_issues": None, "total_time_sec": 0})
    assert "No anomalies detected" in out


def test_repo_section_dirty_defaults_to_zero():
    """Kills line 142 ``git.get("dirty", 0)``->``1`` in the repo chip."""
    out = s._repo_section({"branch": "m", "total_commits": "1"})
    assert "<b>0</b> uncommitted files" in out


def test_autonomy_section_executable_defaults_to_zero():
    """Kills line 668 ``autonomy.get("executable", 0)``->``1`` in the safe-fixes chip."""
    out = s._autonomy_section({"act": True, "mode": "x", "reason": "r"})
    assert "<b>0</b> safe fixes" in out


def test_pareto_section_dominated_floor_is_zero():
    """Kills line 684 ``max(0, total - len(points))`` ``0``->``1``.

    With more frontier points than the (stale/under-counted) total, dominated
    floors at 0 — never negative, never 1.
    """
    pts = [_ns(branch_path="b", title="t", reasons=["x"], impact=1, effort=1, roi=1)]
    out = s._pareto_section(pts, 0)
    assert "<b>0</b> dominated" in out


def test_reasoning_section_rounds_confidence_to_three_places():
    """Kills line 1120 ``round(v, 3)`` ``3``->``4`` in the confidence cell."""
    out = s._reasoning_section({"mode": "m", "confidence_map": {"c": 0.123456},
                                "debug_stats": {}, "estimated_total_tokens": 1})
    assert "0.123" in out
    assert "0.1235" not in out


def test_reasoning_section_or_guards_none_debug_stats():
    """Kills line 1108 ``r.get("debug_stats", {}) or {}``->``and {}``.

    A ``None`` debug_stats must coerce to ``{}``; ``and`` would keep ``None`` and
    crash on ``.get``.
    """
    out = s._reasoning_section({"mode": "m", "confidence_map": {},
                                "debug_stats": None, "estimated_total_tokens": 1})
    assert "Reasoning" in out
