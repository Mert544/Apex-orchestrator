"""Mutation-hardening tests for the agent modules.

These tests pin the exact numeric constants, boundary conditions, and branch
outcomes that mutation operators (arithmetic flips, boundary slides, ``and``/``or``
swaps, ``True``/``False`` flips, comparison negations) would otherwise silently
break.  Each test names the behavior it locks down and asserts a precise value so
a surviving mutant becomes a failing test.

Scope: app/agents/evaluator.py, app/agents/swarm_coordinator.py,
app/agents/skills/security_agent.py, app/agents/skills/self_audit_agent.py.
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import pytest

from app.agents.base import Agent, AgentMessage, AgentState
from app.agents.bus import AgentBus
from app.agents.consensus import Verdict
from app.agents.evaluator import ClaimEvaluator
from app.agents.skills.security_agent import (
    SecurityAgent,
    _call_is_false_positive,
    _call_pattern_matches,
    _has_shell_true,
    _line_suppresses,
)
from app.agents.skills.self_audit_agent import SelfAuditAgent
from app.agents.swarm_coordinator import SwarmCoordinator


# ---------------------------------------------------------------------------
# SecurityAgent._calc_score — exact severity weights and the /5 cap.
# ---------------------------------------------------------------------------
def _score(severities: list[str]) -> float:
    return SecurityAgent()._calc_score([{"severity": s} for s in severities])


def test_calc_score_weights_are_exact():
    # weights critical=1.0, high=0.7, medium=0.4, low=0.1 then /5, rounded 2dp.
    assert _score(["critical"]) == 0.2
    assert _score(["high"]) == 0.14
    assert _score(["medium"]) == 0.08
    assert _score(["low"]) == 0.02


def test_calc_score_unknown_and_missing_severity_default_low():
    # .get(severity, 0.1) default — an unknown or absent severity weighs 0.1.
    assert _score(["totally-unknown"]) == 0.02
    assert SecurityAgent()._calc_score([{}]) == 0.02


def test_calc_score_caps_at_one_not_above():
    # total/5 is min()-capped at 1.0: 6 critical -> 6/5 = 1.2 -> clamped to 1.0.
    assert _score(["critical"] * 6) == 1.0
    # exactly 5 critical reaches 1.0 right at the cap boundary.
    assert _score(["critical"] * 5) == 1.0


def test_calc_score_empty_is_zero():
    assert SecurityAgent()._calc_score([]) == 0.0


def test_calc_score_just_below_cap():
    # 4 critical -> 4/5 = 0.8, strictly below the 1.0 cap (kills min-vs-max flips).
    assert _score(["critical"] * 4) == 0.8


# ---------------------------------------------------------------------------
# SecurityAgent._line_suppresses — directive parsing branches.
# ---------------------------------------------------------------------------
def test_line_suppress_nosec_unconditional():
    assert _line_suppresses("x = eval(c)  # nosec", "eval_usage") is True


def test_line_suppress_bare_noqa_disables_all():
    assert _line_suppresses("x = eval(c)  # noqa", "eval_usage") is True


def test_line_suppress_security_code_S_prefix_with_digits():
    assert _line_suppresses("eval(c)  # noqa: S307", "eval_usage") is True


def test_line_suppress_S_without_digits_does_not_suppress():
    # "Shello" has S prefix but no trailing digits -> not a security code.
    assert _line_suppresses("eval(c)  # noqa: Shello", "eval_usage") is False


def test_line_suppress_unrelated_code_does_not_suppress():
    assert _line_suppresses("eval(c)  # noqa: E501", "eval_usage") is False


def test_line_suppress_e722_only_for_bare_except():
    assert _line_suppresses("except:  # noqa: E722", "bare_except") is True
    # E722 does NOT suppress a non-bare-except finding.
    assert _line_suppresses("eval(c)  # noqa: E722", "eval_usage") is False


def test_line_suppress_no_comment_returns_false():
    assert _line_suppresses("eval(c)", "eval_usage") is False


def test_line_suppress_multiple_codes_any_security_wins():
    # F401 alone would not suppress, but S301 present -> suppressed.
    assert _line_suppresses("eval(c)  # noqa: F401, S301", "eval_usage") is True


# ---------------------------------------------------------------------------
# SecurityAgent pure call helpers.
# ---------------------------------------------------------------------------
def test_call_pattern_matches_dotted_exact_and_endswith():
    assert _call_pattern_matches("os.system", "os.system") is True
    assert _call_pattern_matches("a.b.os.system", "os.system") is True
    # endswith must respect the dot boundary, not a bare suffix.
    assert _call_pattern_matches("frobos.system", "os.system") is False


def test_call_pattern_matches_bare_builtin_exact_only():
    assert _call_pattern_matches("eval", "eval") is True
    assert _call_pattern_matches("model.eval", "eval") is False


def test_has_shell_true_only_for_literal_true():
    true_call = ast.parse("subprocess.call(c, shell=True)").body[0].value
    false_call = ast.parse("subprocess.call(c, shell=False)").body[0].value
    none_call = ast.parse("subprocess.call(c, shell=None)").body[0].value
    no_kw = ast.parse("subprocess.call(c)").body[0].value
    assert _has_shell_true(true_call) is True
    assert _has_shell_true(false_call) is False
    assert _has_shell_true(none_call) is False
    assert _has_shell_true(no_kw) is False


def test_call_is_false_positive_branches():
    re_compile = ast.parse("re.compile(x)").body[0].value
    plain_compile = ast.parse("compile(x)").body[0].value
    literal_eval = ast.parse("ast.literal_eval(x)").body[0].value
    plain_eval = ast.parse("eval(x)").body[0].value
    sub_list = ast.parse("subprocess.call([x])").body[0].value
    sub_shell = ast.parse("subprocess.call(x, shell=True)").body[0].value

    assert _call_is_false_positive("compile", "re.compile", re_compile) is True
    assert _call_is_false_positive("compile", "compile", plain_compile) is False
    assert _call_is_false_positive("eval", "ast.literal_eval", literal_eval) is True
    assert _call_is_false_positive("eval", "eval", plain_eval) is False
    # subprocess.call without shell=True is a false positive (safe).
    assert _call_is_false_positive("subprocess.call", "subprocess.call", sub_list) is True
    # subprocess.call WITH shell=True is a real finding (not a false positive).
    assert _call_is_false_positive("subprocess.call", "subprocess.call", sub_shell) is False


# ---------------------------------------------------------------------------
# SecurityAgent secret-regex exclusion branches.
# ---------------------------------------------------------------------------
def _scan_src(src: str) -> list[dict]:
    d = tempfile.mkdtemp()
    Path(d, "m.py").write_text(src, encoding="utf-8")
    return SecurityAgent().run(project_root=d)["findings"]


def test_secret_excluded_placeholder_value_not_flagged():
    assert _scan_src('password = "test"') == []


def test_secret_os_environ_not_flagged():
    assert _scan_src('api_key = os.environ["X"]') == []


def test_secret_config_get_not_flagged():
    assert _scan_src('api_key = config.get("k")') == []


def test_secret_real_value_is_flagged():
    rts = [f["risk_type"] for f in _scan_src('api_key = "sk-live-9999abc"')]
    assert "hardcoded_secret" in rts


def test_secret_connection_string_is_medium_severity():
    findings = _scan_src('database_url = "postgres://u:p@host/db"')
    conn = [f for f in findings if f["risk_type"] == "hardcoded_connection"]
    assert conn and conn[0]["severity"] == "medium"


def test_secret_in_docstring_interior_is_skipped(tmp_path: Path):
    src = (
        "def f():\n"
        '    """Example::\n'
        "\n"
        "        password = 'realdocsecretvalue'\n"
        '    """\n'
        "    return 1\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    findings = SecurityAgent().run(project_root=str(tmp_path))["findings"]
    assert not any(f["risk_type"] == "hardcoded_password" for f in findings)


# ---------------------------------------------------------------------------
# SecurityAgent._discover_files — the test/validation dir skip.
# ---------------------------------------------------------------------------
def test_discover_files_skips_test_dirs(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("eval('x')\n", encoding="utf-8")
    files = SecurityAgent()._discover_files(tmp_path.resolve())
    assert any("real.py" in f for f in files)
    assert not any("tests" in f for f in files)


# ---------------------------------------------------------------------------
# SelfAuditAgent._analyze_complexity — the >50 line boundary.
# ---------------------------------------------------------------------------
def _long_func_count(body_lines: int, tmp_path: Path) -> int:
    lines = ["def f():"]
    lines += [f"    x = {i}" for i in range(body_lines)]
    f = tmp_path / "m.py"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(SelfAuditAgent()._analyze_complexity([f]))


def test_complexity_boundary_is_strictly_greater_than_50(tmp_path: Path):
    # A function spanning exactly 51 lines (length 50) is NOT long (length > 50).
    # def line + 50 body lines -> end-start == 50 -> not flagged.
    assert _long_func_count(50, tmp_path) == 0


def test_complexity_just_over_boundary_is_flagged(tmp_path: Path):
    # 51 body lines -> length 51 > 50 -> flagged.
    assert _long_func_count(51, tmp_path) == 1


def test_complexity_no_end_lineno_safe(tmp_path: Path):
    # Short function (length 0) never flagged; guards the `node.end_lineno else 0`.
    f = tmp_path / "tiny.py"
    f.write_text("def f(): pass\n", encoding="utf-8")
    assert SelfAuditAgent()._analyze_complexity([f]) == []


# ---------------------------------------------------------------------------
# SelfAuditAgent._coverage_gap — module extraction & set difference.
# ---------------------------------------------------------------------------
def test_coverage_gap_from_import_and_import_app(tmp_path: Path):
    app_a = tmp_path / "app" / "alpha.py"
    app_b = tmp_path / "app" / "beta.py"
    app_a.parent.mkdir(parents=True)
    app_a.write_text("def a(): pass\n", encoding="utf-8")
    app_b.write_text("def b(): pass\n", encoding="utf-8")
    t1 = tmp_path / "tests" / "test_a.py"
    t2 = tmp_path / "tests" / "test_b.py"
    t1.parent.mkdir(parents=True)
    t1.write_text("from app.alpha import a\n", encoding="utf-8")
    t2.write_text("import app.beta\n", encoding="utf-8")
    cov = SelfAuditAgent()._coverage_gap([app_a, app_b], [t1, t2])
    assert cov["tested_modules"] == ["alpha", "beta"]
    assert cov["untested_modules"] == []
    assert cov["total_app_modules"] == 2
    assert cov["total_test_files"] == 2


def test_coverage_gap_untested_module(tmp_path: Path):
    app_a = tmp_path / "app" / "alpha.py"
    app_b = tmp_path / "app" / "beta.py"
    app_a.parent.mkdir(parents=True)
    app_a.write_text("x = 1\n", encoding="utf-8")
    app_b.write_text("y = 1\n", encoding="utf-8")
    t1 = tmp_path / "tests" / "test_a.py"
    t1.parent.mkdir(parents=True)
    t1.write_text("from app.alpha import x\n", encoding="utf-8")
    cov = SelfAuditAgent()._coverage_gap([app_a, app_b], [t1])
    assert cov["tested_modules"] == ["alpha"]
    assert cov["untested_modules"] == ["beta"]


def test_coverage_gap_ignores_non_app_imports(tmp_path: Path):
    app_a = tmp_path / "app" / "alpha.py"
    app_a.parent.mkdir(parents=True)
    app_a.write_text("x = 1\n", encoding="utf-8")
    t1 = tmp_path / "tests" / "test_a.py"
    t1.parent.mkdir(parents=True)
    # A non-app import and a single-segment import must not pollute tested set.
    t1.write_text("import os\nfrom collections import abc\n", encoding="utf-8")
    cov = SelfAuditAgent()._coverage_gap([app_a], [t1])
    assert cov["tested_modules"] == []
    assert cov["untested_modules"] == ["alpha"]


# ---------------------------------------------------------------------------
# SelfAuditAgent._find_todos — keyword set and line numbering.
# ---------------------------------------------------------------------------
def test_find_todos_keywords_and_linenumbers(tmp_path: Path):
    f = tmp_path / "m.py"
    f.write_text(
        "x = 1\n"
        "# TODO: a\n"
        "# fixme: b\n"
        "# this is a HACK\n"
        "y = 2  # nothing here\n",
        encoding="utf-8",
    )
    todos = SelfAuditAgent()._find_todos([f])
    lines = sorted(t["line"] for t in todos)
    assert lines == [2, 3, 4]


def test_find_todos_empty_when_absent(tmp_path: Path):
    f = tmp_path / "m.py"
    f.write_text("def clean():\n    return 1\n", encoding="utf-8")
    assert SelfAuditAgent()._find_todos([f]) == []


# ---------------------------------------------------------------------------
# ClaimEvaluator — role weights, confidence averaging, verdict heuristics.
# ---------------------------------------------------------------------------
def test_role_weights_are_exact():
    assert ClaimEvaluator.ROLE_WEIGHTS == {
        "security_auditor": 1.5,
        "documentation_enforcer": 0.8,
        "test_coverage_analyst": 1.0,
        "architecture_analyst": 1.2,
    }


def test_review_security_hit_and_miss():
    hit = ClaimEvaluator._review_security("please use eval here")
    assert hit[0] == Verdict.REJECT and hit[1] == 0.85
    miss = ClaimEvaluator._review_security("a perfectly safe change")
    assert miss[0] == Verdict.APPROVE and miss[1] == 0.7


def test_review_keyword_hit_and_miss_confidence():
    hit = ClaimEvaluator._review_keyword("add docstring", ["docstring"], 0.8, "h", "m")
    assert hit == (Verdict.APPROVE, 0.8, "h")
    miss = ClaimEvaluator._review_keyword("unrelated", ["docstring"], 0.8, "h", "m")
    assert miss == (Verdict.ABSTAIN, 0.5, "m")


def test_review_outcome_unknown_role_abstains():
    assert ClaimEvaluator._review_outcome("mystery_role", "anything") == (
        Verdict.ABSTAIN,
        0.5,
        "No specific evaluation logic",
    )


def test_agent_review_applies_role_weight():
    ev = ClaimEvaluator()
    vote = ev._agent_review(ev.agents["security"], "use eval()", {})
    assert vote.weight == 1.5
    assert vote.agent_role == "security_auditor"
    assert vote.verdict == Verdict.REJECT


def test_evaluate_uses_memory_cache_on_second_call(tmp_path: Path):
    ev = ClaimEvaluator(memory_dir=str(tmp_path))
    claim = "Add docstrings to all public functions"
    first = ev.evaluate(claim)
    assert first.metadata.get("cached") is not True
    second = ev.evaluate(claim)
    assert second.metadata.get("cached") is True


def test_filter_approved_respects_min_confidence():
    ev = ClaimEvaluator()
    # A REJECT (eval) is excluded; APPROVEs above the threshold are kept.
    approved = ev.filter_approved(
        ["Add docstrings", "Use eval() now", "Add test coverage"], min_confidence=0.5
    )
    claims = [c for c, _ in approved]
    assert "Use eval() now" not in claims
    assert len(approved) == 2


def test_filter_approved_high_threshold_excludes_all():
    ev = ClaimEvaluator()
    approved = ev.filter_approved(["Add docstrings"], min_confidence=0.99)
    assert approved == []


def test_to_dict_panel_shape():
    info = ClaimEvaluator().to_dict()
    assert info["panel_size"] == 4
    assert info["strategy"] == "majority"
    assert info["quorum"] == 2
    assert set(info["agents"]) == {"security", "docstring", "test_stub", "dependency"}


# ---------------------------------------------------------------------------
# SwarmCoordinator.record_outcome — warmup gate and rate arithmetic.
# ---------------------------------------------------------------------------
def test_record_outcome_warmup_gate_no_change_before_five():
    coord = SwarmCoordinator()
    for _ in range(4):
        coord.record_outcome("scan", success=False)
    # total_ops < 5 -> early return, no rate change, no failure recorded.
    assert coord._total_ops == 4
    assert coord._success_rates["scan"] == 1.0
    assert coord._failure_count == 0


def test_record_outcome_fifth_op_applies_success_formula():
    coord = SwarmCoordinator()
    for _ in range(4):
        coord.record_outcome("scan", success=True)
    coord.record_outcome("scan", success=True)  # 5th: 1.0*0.95 + 0.05 == 1.0
    assert coord._total_ops == 5
    assert coord._success_rates["scan"] == pytest.approx(1.0)


def test_record_outcome_failure_formula_and_counter():
    coord = SwarmCoordinator()
    for _ in range(4):
        coord.record_outcome("scan", success=True)
    coord.record_outcome("scan", success=False)  # 5th: 1.0*0.95 - 0.05 == 0.9
    assert coord._success_rates["scan"] == pytest.approx(0.9)
    assert coord._failure_count == 1


def test_record_outcome_rate_floor_is_point_one():
    coord = SwarmCoordinator()
    for _ in range(60):
        coord.record_outcome("scan", success=False)
    # Rate is clamped to a 0.1 floor regardless of repeated failures.
    assert coord._success_rates["scan"] >= 0.1
    assert coord._success_rates["scan"] == pytest.approx(0.1, abs=1e-9)


def test_record_outcome_unknown_op_routed_to_patch_bucket():
    coord = SwarmCoordinator()
    for _ in range(5):
        coord.record_outcome("nonexistent-op", success=False)
    # Unknown ops fold into the "patch" bucket; scan stays pristine.
    assert coord._success_rates["patch"] < 1.0
    assert coord._success_rates["scan"] == 1.0


# ---------------------------------------------------------------------------
# SwarmCoordinator._adjust_timeouts — factor bands and clamps.
# ---------------------------------------------------------------------------
def test_adjust_timeouts_low_rate_factor_1_5():
    coord = SwarmCoordinator()
    base = coord._base_timeouts["patch"]
    coord._success_rates["patch"] = 0.4  # < 0.5
    coord._adjust_timeouts()
    assert coord._timeouts["patch"] == pytest.approx(base * 1.5)


def test_adjust_timeouts_boundary_half_uses_mid_factor():
    coord = SwarmCoordinator()
    base = coord._base_timeouts["scan"]
    coord._success_rates["scan"] = 0.5  # not < 0.5 -> 0.5<=rate<0.75 -> 1.2
    coord._adjust_timeouts()
    assert coord._timeouts["scan"] == pytest.approx(base * 1.2)


def test_adjust_timeouts_high_rate_shrinks_to_point_nine():
    coord = SwarmCoordinator()
    base = coord._base_timeouts["test"]
    coord._success_rates["test"] = 0.96  # > 0.95
    coord._adjust_timeouts()
    assert coord._timeouts["test"] == pytest.approx(base * 0.9)


def test_adjust_timeouts_exact_point_95_is_neutral():
    coord = SwarmCoordinator()
    base = coord._base_timeouts["analyze"]
    coord._success_rates["analyze"] = 0.95  # not > 0.95 -> neutral factor 1.0
    coord._adjust_timeouts()
    assert coord._timeouts["analyze"] == pytest.approx(base)


def test_adjust_timeouts_total_recomputed_from_average_factor():
    coord = SwarmCoordinator()
    # All scanners shrink (0.9 factor) -> avg_factor 0.9 -> total = 180*0.9 = 162,
    # within the [0.7x, 1.5x] band so it is taken as-is.
    for op in ("scan", "analyze", "patch", "test"):
        coord._success_rates[op] = 0.99
    coord._adjust_timeouts()
    assert coord._timeouts["total"] == pytest.approx(180.0 * 0.9)


# ---------------------------------------------------------------------------
# SwarmCoordinator pure helpers and routing branches.
# ---------------------------------------------------------------------------
def test_select_scan_trigger_priority_order():
    f = SwarmCoordinator._select_scan_trigger
    assert f(["security", "docstring"], "any goal") == "security"
    assert f([], "do a security review") == "security"
    assert f(["docstring"], "doc work") == "docstring"
    assert f(["test"], "testing") == "test"
    assert f(["other"], "generic goal") == "general"


def test_check_timeout_reflects_shutdown():
    coord = SwarmCoordinator()
    assert coord._check_timeout("scan") is False
    coord._shutdown()
    assert coord._check_timeout("scan") is True


def test_shutdown_sets_running_false_and_requests():
    coord = SwarmCoordinator()
    coord._running = True
    coord._shutdown()
    assert coord._running is False
    assert coord._graceful_shutdown.is_shutdown_requested() is True
    assert coord._stability.shutdown_manager.is_shutdown_requested() is True


class _FindingScanner(Agent):
    """Scanner agent emitting risks so scan.complete -> security.alert fires."""

    def __init__(self, bus=None):
        super().__init__(name="sec-find", role="security_auditor", bus=bus)

    def _execute(self, **kwargs):
        return {
            "findings_count": 1,
            "risks": [{"file": "a.py", "issue": "eval found"}],
        }


def test_handle_scan_complete_records_and_emits_alert():
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    agent = _FindingScanner(bus=bus)
    coord.register_agents([agent])
    seen = []
    bus.subscribe("_probe", "security.alert", lambda m: seen.append(m))
    msg = AgentMessage(
        sender="s", recipient=None, topic="scan.complete",
        payload={"project_root": "/proj"},
    )
    coord._handle_scan_complete(agent, msg)
    assert coord._results and coord._results[-1]["findings_count"] == 1
    assert len(seen) == 1
    assert seen[0].payload["risks"][0]["issue"] == "eval found"
    assert seen[0].payload["project_root"] == "/proj"


class _NoRiskScanner(Agent):
    def __init__(self, bus=None):
        super().__init__(name="sec-norisk", role="security_auditor", bus=bus)

    def _execute(self, **kwargs):
        return {"findings_count": 0, "risks": []}


def test_handle_scan_complete_no_risks_emits_nothing():
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    agent = _NoRiskScanner(bus=bus)
    coord.register_agents([agent])
    seen = []
    bus.subscribe("_probe", "security.alert", lambda m: seen.append(m))
    msg = AgentMessage(sender="s", recipient=None, topic="scan.complete", payload={})
    coord._handle_scan_complete(agent, msg)
    assert seen == []
    assert coord._results and coord._results[-1]["findings_count"] == 0


def test_handle_scan_complete_skips_non_idle():
    coord = SwarmCoordinator()
    agent = _FindingScanner()
    agent.state = AgentState.RUNNING
    coord._handle_scan_complete(
        agent,
        AgentMessage(sender="s", recipient=None, topic="scan.complete", payload={}),
    )
    assert coord._results == []


def test_route_to_evaluator_builds_claim_text():
    class _Eval(Agent):
        def __init__(self, bus=None):
            super().__init__(name="ev", role="claim_evaluator", bus=bus)
            self.seen_claims = None

        def run(self, **kwargs):
            self.seen_claims = kwargs.get("claims")
            return []

        def _execute(self, **kwargs):
            return []

    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)
    ev = _Eval(bus=bus)
    coord.register_agents([ev])
    msg = AgentMessage(
        sender="s", recipient=None, topic="security.alert",
        payload={"risks": [{"file": "x.py", "issue": "boom"}]},
    )
    coord._route_to_evaluator(msg)
    assert ev.seen_claims == ["Risk in x.py: boom"]


def test_handle_patch_request_marks_patched_and_records():
    bus = AgentBus()
    coord = SwarmCoordinator(bus=bus)

    class _Patcher(Agent):
        def __init__(self, bus=None):
            super().__init__(name="p", role="patcher", bus=bus)

        def _execute(self, **kwargs):
            return {}

    patcher = _Patcher(bus=bus)
    coord.register_agents([patcher])
    seen = []
    bus.subscribe("_probe", "patch.applied", lambda m: seen.append(m))
    coord._handle_patch_request(
        patcher,
        AgentMessage(sender="s", recipient=None, topic="patch.request",
                     payload={"claim": "c9"}),
    )
    assert patcher.results[-1] == {"claim": "c9", "patched": True, "agent": "p"}
    assert seen and seen[0].payload["patched"] is True


def test_handle_fractal_complete_collects_fields():
    coord = SwarmCoordinator()
    coord._handle_fractal_complete(
        AgentMessage(
            sender="f1", recipient=None, topic="fractal.analysis.complete",
            payload={"finding": "F", "tree_depth": 7},
        )
    )
    assert coord._results == [
        {"type": "fractal_analysis", "finding": "F", "tree_depth": 7, "agent": "f1"}
    ]


def test_get_stability_status_keys():
    coord = SwarmCoordinator()
    status = coord.get_stability_status()
    assert set(status) == {
        "shutdown_requested", "timeouts", "active_agents", "pending_results"
    }
    assert status["shutdown_requested"] is False


def test_run_autonomous_returns_empty_after_prior_shutdown():
    coord = SwarmCoordinator()
    coord._shutdown()
    assert coord.run_autonomous("any", target=".", mode="report") == []
