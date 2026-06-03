from __future__ import annotations

from app.agents.fractal_agents import FractalSecurityAgent
from app.engine.fractal_patch_generator import FractalPatch
from app.policies.mode_policy import ApexMode, ModePolicy
from app.policies.safety_gates import SafetyGates
from app.skills.safety.enhanced_safety_governor import EnhancedSafetyGovernor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sandboxed_agent(tmp_path, file_name="mod.py", content="x = old_value\n"):
    """Build a FractalSecurityAgent whose executor has a live sandbox.

    The fallback ladder operates on ``self.executor`` against a sandbox copy of
    a project, so we create one real file and a sandbox that contains it.
    """
    (tmp_path / file_name).write_text(content, encoding="utf-8")
    agent = FractalSecurityAgent()
    agent.executor.project_root = tmp_path.resolve()
    agent.executor.create_sandbox()
    gates = SafetyGates(project_root=str(tmp_path), max_changed_files=5)
    return agent, gates


# ---------------------------------------------------------------------------
# EnhancedSafetyGovernor — missing lines 118 (filename-only match) and compute_line_diffs
# ---------------------------------------------------------------------------

def test_is_restricted_matches_on_filename_only():
    governor = EnhancedSafetyGovernor()
    # A literal (wildcard-free) pattern matches the bare filename but not the
    # full path, so the first two fnmatch checks fail and the filename-only
    # branch is the one that returns True.
    assert governor._is_restricted("deep/nested/dir/id_rsa.pem", ["id_rsa.pem"]) is True
    assert governor._is_restricted("deep/nested/dir/notes.txt", ["id_rsa.pem"]) is False
    # A path-style glob still matches via the posix branch.
    assert governor._is_restricted("deep/nested/dir/key.pem", ["*.pem"]) is True


def test_compute_line_diffs_parses_git_diff(tmp_path, monkeypatch):
    diff_text = (
        "diff --git a/app/a.py b/app/a.py\n"
        "--- a/app/a.py\n"
        "+++ b/app/a.py\n"
        "+added one\n"
        "+added two\n"
        "-removed one\n"
        "diff --git a/app/b.py b/app/b.py\n"
        "--- a/app/b.py\n"
        "+++ b/app/b.py\n"
        "+only change\n"
    )

    class _FakeResult:
        stdout = diff_text

    class _FakeGit:
        def diff(self, project_root, changed_files):
            return _FakeResult()

    monkeypatch.setattr(
        "app.runtime.git_adapter.GitAdapter", lambda *a, **k: _FakeGit()
    )

    governor = EnhancedSafetyGovernor()
    diffs = governor.compute_line_diffs(tmp_path, ["app/a.py", "app/b.py"])
    # The +++/--- header lines are skipped; only +/- content lines counted.
    assert diffs["app/a.py"] == 3
    assert diffs["app/b.py"] == 1


def test_compute_line_diffs_empty_diff(tmp_path, monkeypatch):
    class _FakeResult:
        stdout = ""

    class _FakeGit:
        def diff(self, project_root, changed_files):
            return _FakeResult()

    monkeypatch.setattr(
        "app.runtime.git_adapter.GitAdapter", lambda *a, **k: _FakeGit()
    )
    governor = EnhancedSafetyGovernor()
    assert governor.compute_line_diffs(tmp_path, ["x.py"]) == {}


# ---------------------------------------------------------------------------
# set_mode_policy wiring (lines 78-81)
# ---------------------------------------------------------------------------

def test_set_mode_policy_propagates_flags():
    agent = FractalSecurityAgent()
    policy = ModePolicy(
        mode=ApexMode.AUTONOMOUS,
        auto_patch=True,
        auto_commit=True,
        max_fractal_budget=7,
    )
    agent.set_mode_policy(policy)
    assert agent.mode_policy is policy
    assert agent.max_fractal_budget == 7
    assert agent.auto_patch is True
    assert agent.auto_commit is True


# ---------------------------------------------------------------------------
# Fallback ladder — tier 1: scope_reduce
# ---------------------------------------------------------------------------

def test_fallback_scope_reduce_succeeds_on_eval(tmp_path):
    agent, gates = _make_sandboxed_agent(
        tmp_path, content="result = eval(data)  # TODO drop me\n"
    )
    patch = FractalPatch(
        file="mod.py",
        finding="eval usage",
        action="fix_eval",
        old_code="result = eval(data)  # TODO drop me",
        new_code="result = ast.literal_eval(data)  # TODO drop me",
        confidence=0.8,
    )
    outcome = agent._fallback_scope_reduce({"issue": "eval usage"}, patch, gates)
    assert outcome["strategy"] == "scope_reduce"
    assert outcome["success"] is True
    assert outcome["patch_applied"] is True
    assert outcome["feedback_score"] == 0.3


def test_fallback_scope_reduce_bare_except_branch(tmp_path):
    agent, gates = _make_sandboxed_agent(
        tmp_path, content="try:\n    pass\nexcept:\n    pass\n"
    )
    patch = FractalPatch(
        file="mod.py",
        finding="bare except",
        action="fix",
        old_code="except:",
        new_code="except ValueError:",
        confidence=0.8,
    )
    outcome = agent._fallback_scope_reduce({"issue": "bare except"}, patch, gates)
    assert outcome["strategy"] == "scope_reduce"
    assert outcome["patch_applied"] is True


def test_fallback_scope_reduce_failure_when_old_code_missing(tmp_path):
    agent, gates = _make_sandboxed_agent(tmp_path, content="a = 1\n")
    patch = FractalPatch(
        file="mod.py",
        finding="other",
        action="fix",
        old_code="does-not-exist",
        new_code="b = 2",
        confidence=0.8,
    )
    outcome = agent._fallback_scope_reduce({"issue": "other"}, patch, gates)
    assert outcome["success"] is False
    assert outcome["patch_applied"] is False
    assert outcome["feedback_score"] == -0.4


# ---------------------------------------------------------------------------
# Fallback ladder — tier 2: semantic_patch
# ---------------------------------------------------------------------------

def test_fallback_semantic_patch_no_strategy_returns_failure(tmp_path):
    agent, gates = _make_sandboxed_agent(tmp_path)
    patch = FractalPatch(
        file="mod.py",
        finding="unmapped issue",
        action="fix",
        old_code="x = old_value",
        new_code="x = new_value",
        confidence=0.8,
    )
    outcome = agent._fallback_semantic_patch({"issue": "unmapped issue"}, patch, gates)
    assert outcome == {"success": False}


def test_fallback_semantic_patch_missing_file_returns_failure(tmp_path):
    agent, gates = _make_sandboxed_agent(tmp_path)
    patch = FractalPatch(
        file="nonexistent.py",
        finding="eval",
        action="fix",
        old_code="x",
        new_code="y",
        confidence=0.8,
    )
    # _parse_file returns None for a non-existent path -> early failure.
    outcome = agent._fallback_semantic_patch({"issue": "eval"}, patch, gates)
    assert outcome["success"] is False


# ---------------------------------------------------------------------------
# Fallback ladder — tier 3: split_patches
# ---------------------------------------------------------------------------

def test_fallback_split_patches_empty_returns_failure(tmp_path):
    agent, gates = _make_sandboxed_agent(tmp_path)
    outcome = agent._fallback_split_patches({"issue": "x", "file": "mod.py"}, [], gates)
    assert outcome == {"success": False}


def test_fallback_split_patches_applies_first(tmp_path):
    agent, gates = _make_sandboxed_agent(tmp_path, content="x = old_value\n")
    all_patches = [
        {
            "action": "partial",
            "old_code": "x = old_value",
            "new_code": "x = new_value",
            "confidence": 0.6,
        }
    ]
    outcome = agent._fallback_split_patches(
        {"issue": "x", "file": "mod.py"}, all_patches, gates
    )
    assert outcome["strategy"] == "split_patches"
    assert outcome["patch_applied"] is True
    assert outcome["success"] is True


# ---------------------------------------------------------------------------
# Fallback ladder — tier 4: test_first
# ---------------------------------------------------------------------------

def test_fallback_test_first_baseline_failing(tmp_path, monkeypatch):
    from app.engine.action_executor import ActionResult

    agent, gates = _make_sandboxed_agent(tmp_path, content="x = old_value\n")
    patch = FractalPatch(
        file="mod.py",
        finding="x",
        action="fix",
        old_code="x = old_value",
        new_code="x = new_value",
        confidence=0.8,
    )

    def _failing_tests():
        return ActionResult(action_type="test", success=False, feedback_score=-0.5)

    monkeypatch.setattr(agent.executor, "_run_tests", _failing_tests)
    outcome = agent._fallback_test_first({"issue": "x"}, patch, gates)
    assert outcome["success"] is False
    assert outcome["reason"] == "baseline tests already failing"


def test_fallback_test_first_success(tmp_path, monkeypatch):
    from app.engine.action_executor import ActionResult

    agent, gates = _make_sandboxed_agent(tmp_path, content="x = old_value\n")
    patch = FractalPatch(
        file="mod.py",
        finding="x",
        action="fix",
        old_code="x = old_value",
        new_code="x = new_value",
        confidence=0.8,
    )

    calls = {"n": 0}

    def _passing(*args, **kwargs):
        calls["n"] += 1
        return ActionResult(
            action_type="test",
            success=True,
            changed_files=["mod.py"],
            feedback_score=1.0,
        )

    # Baseline test passes, then patch+test passes.
    monkeypatch.setattr(agent.executor, "_run_tests", _passing)
    monkeypatch.setattr(agent.executor, "execute_patch", _passing)
    outcome = agent._fallback_test_first({"issue": "x"}, patch, gates)
    assert outcome["success"] is True
    assert outcome["feedback_score"] == 0.5


# ---------------------------------------------------------------------------
# Fallback ladder — tier 5: review_only
# ---------------------------------------------------------------------------

def test_fallback_review_only_flags_for_review(tmp_path):
    agent, _ = _make_sandboxed_agent(tmp_path)
    patch = FractalPatch(
        file="mod.py",
        finding="x",
        action="fix",
        old_code="x",
        new_code="y",
        confidence=0.5,
    )
    outcome = agent._fallback_review_only({"issue": "x"}, patch)
    assert outcome["flagged_for_review"] is True
    assert outcome["success"] is False
    assert "mod.py" in outcome["review_note"]


# ---------------------------------------------------------------------------
# _run_fallback_ladder orchestration
# ---------------------------------------------------------------------------

def test_run_fallback_ladder_returns_first_success(tmp_path):
    agent, gates = _make_sandboxed_agent(
        tmp_path, content="result = eval(data)\n"
    )
    patch = FractalPatch(
        file="mod.py",
        finding="eval usage",
        action="fix_eval",
        old_code="result = eval(data)",
        new_code="result = ast.literal_eval(data)",
        confidence=0.8,
    )
    outcome = agent._run_fallback_ladder(
        {"issue": "eval usage"}, patch, gates, plan=object(), all_patches=[patch.to_dict()]
    )
    assert outcome["success"] is True
    # First successful tier is scope_reduce.
    assert outcome["strategy"] == "scope_reduce"


def test_run_fallback_ladder_exhausts_all(tmp_path, monkeypatch):
    agent, gates = _make_sandboxed_agent(tmp_path, content="a = 1\n")
    patch = FractalPatch(
        file="mod.py",
        finding="other",
        action="fix",
        old_code="missing",
        new_code="b = 2",
        confidence=0.5,
    )

    # Force every tier to raise so the except/continue path is exercised and the
    # ladder falls through to the "exhausted" terminal outcome.
    def _boom(*args, **kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(agent, "_fallback_scope_reduce", _boom)
    monkeypatch.setattr(agent, "_fallback_semantic_patch", _boom)
    monkeypatch.setattr(agent, "_fallback_split_patches", _boom)
    monkeypatch.setattr(agent, "_fallback_test_first", _boom)
    monkeypatch.setattr(agent, "_fallback_review_only", _boom)

    outcome = agent._run_fallback_ladder(
        {"issue": "other"}, patch, gates, plan=object(), all_patches=[patch.to_dict()]
    )
    assert outcome["strategy"] == "exhausted"
    assert outcome["success"] is False
    assert outcome["feedback_score"] == -0.6


def test_try_fallback_strategy_delegates_to_ladder(tmp_path):
    agent, gates = _make_sandboxed_agent(tmp_path, content="result = eval(data)\n")
    patch = FractalPatch(
        file="mod.py",
        finding="eval usage",
        action="fix_eval",
        old_code="result = eval(data)",
        new_code="result = ast.literal_eval(data)",
        confidence=0.8,
    )
    outcomes = agent._try_fallback_strategy("scope_reduce", {"issue": "eval usage"}, patch, gates)
    assert isinstance(outcomes, list)
    assert outcomes and outcomes[0]["success"] is True


# ---------------------------------------------------------------------------
# Helper methods: _parse_file / _read_file / _analyze_parallel
# ---------------------------------------------------------------------------

def test_parse_file_and_read_file(tmp_path):
    agent = FractalSecurityAgent()
    src = tmp_path / "src.py"
    src.write_text("def foo():\n    return 1\n", encoding="utf-8")
    tree = agent._parse_file(str(src))
    assert tree is not None
    assert agent._read_file(str(src)).startswith("def foo")
    # Missing file -> None / empty string, not an exception.
    assert agent._parse_file(str(tmp_path / "missing.py")) is None
    assert agent._read_file(str(tmp_path / "missing.py")) == ""


def test_parse_file_invalid_syntax_returns_none(tmp_path):
    agent = FractalSecurityAgent()
    bad = tmp_path / "bad.py"
    bad.write_text("def (:\n", encoding="utf-8")
    assert agent._parse_file(str(bad)) is None


def test_analyze_parallel_legacy(tmp_path):
    agent = FractalSecurityAgent()
    findings = [
        {"issue": "eval usage", "file": "a.py", "line": 1},
        {"issue": "os.system usage", "file": "b.py", "line": 2},
    ]
    results = agent._analyze_parallel(findings, max_depth=2)
    assert len(results) == 2
    for r in results:
        assert "tree" in r and "meta" in r and "patches" in r


# ---------------------------------------------------------------------------
# auto_patch full path: safety-blocked branch
# ---------------------------------------------------------------------------

def test_auto_patch_safety_blocked_on_sensitive_file(tmp_path, monkeypatch):
    # A restricted/sensitive file path makes SafetyGates block the patch, which
    # drives the safety_blocked accounting branch in _execute.
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "cfg.py").write_text(
        "import os\ndef purge(p):\n    os.system('rm ' + p)\n", encoding="utf-8"
    )
    agent = FractalSecurityAgent()
    agent.auto_patch = True
    agent.max_fractal_budget = 5
    result = agent.run(project_root=tmp_path)
    assert "action_results" in result
    # Any blocked patch is reported with safety_blocked True; if a patch was
    # generated for the sensitive file it must be flagged rather than applied.
    blocked = [ar for ar in result["action_results"] if ar.get("safety_blocked")]
    for ar in blocked:
        assert ar["success"] is False
        assert ar["patch_applied"] is False
