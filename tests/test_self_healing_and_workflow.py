from app.agents.skills.cross_repo_workflow import CrossRepoWorkflow, WorkflowResult
from app.agents.skills.self_healing_agent import HealingResult, SelfHealingAgent


def _proj(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "cfg.py").write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    return tmp_path


def test_self_heal_dry_run_changes_nothing(tmp_path):
    _proj(tmp_path)
    before = (tmp_path / "app" / "cfg.py").read_text()
    result = SelfHealingAgent(tmp_path).heal(dry_run=True)
    assert isinstance(result, HealingResult)
    assert result.success
    # Dry run never writes.
    assert (tmp_path / "app" / "cfg.py").read_text() == before


def test_self_heal_applies_yaml_fix(tmp_path):
    _proj(tmp_path)
    result = SelfHealingAgent(tmp_path).heal(dry_run=False)
    assert result.success
    # The yaml.load -> safe_load fix should have been applied and verified.
    if "app/cfg.py" in result.files_modified:
        assert "yaml.safe_load" in (tmp_path / "app" / "cfg.py").read_text()
        assert result.test_passed


def test_run_tests_helper(tmp_path):
    _proj(tmp_path)
    assert SelfHealingAgent(tmp_path)._run_tests() is True


def test_workflow_analysis_only(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "bad.py").write_text("def r(c):\n    return eval(c)\n")
    result = CrossRepoWorkflow(tmp_path).run(min_severity="low")
    assert isinstance(result, WorkflowResult)
    assert result.success
    assert len(result.findings) >= 1


def test_workflow_to_orchestrator_memory(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "bad.py").write_text("def r(c):\n    return eval(c)\n")
    wf = CrossRepoWorkflow(tmp_path)
    result = wf.run(min_severity="low")
    mem = wf.to_orchestrator_memory(result)
    assert mem["type"] == "apex_debug_workflow"
    assert mem["findings_count"] >= 1
    assert mem["critical_count"] >= 1
