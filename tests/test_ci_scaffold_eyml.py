"""End-to-end proof for the ``add_ci`` project-development capability.

A project with no CI has no automated gate; scaffolding one is a genuine,
ADDITIVE develop-loop action (a brand-new ``.github/workflows`` file, no
existing source touched). These tests prove the whole wiring:

  profiler sees no CI → seeder emits a ``missing-ci`` root → bridge plans an
  EXECUTABLE ``add_ci`` step whose target is the workflow path → the step runs
  through the SAME guarded apply gate (mode policy → snapshot → write → verify →
  auto-rollback) as every transform → the scaffolder refuses (returns nothing)
  when the project already has CI or isn't Python.

Mirrors the ``test_simplification_widening`` pattern. Deterministic: fixed
sources, no time/random; the emitted YAML is a pure function of a few boolean
facts about the tree, so it is byte-identical across runs.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_action_bridge import _FACT_ACTIONS, IdeaActionBridge
from app.engine.idea_permutation import IdeaSeeder
from app.execution.ci_scaffold import (
    CI_WORKFLOW_PATH,
    generate_ci_workflow,
    has_ci,
)
from app.execution.risk_tiers import tier_for
from app.models.idea import ActionStep
from app.tools.project_profile import ProjectProfile


def _python_project(tmp_path: Path, *, packaging: str = "pyproject.toml",
                    body: str = "", with_tests: bool = True) -> Path:
    """A minimal Python project tree with no CI."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    if packaging:
        (tmp_path / packaging).write_text(body, encoding="utf-8")
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    if with_tests:
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_ok.py").write_text(
            "def test_ok():\n    assert True\n", encoding="utf-8")
    return tmp_path


def _step() -> ActionStep:
    return ActionStep(
        branch_path="x.0", title="t", operator="root", subject="CI pipeline",
        action_type="add_ci", target=CI_WORKFLOW_PATH, executable=True,
    )


# --- has_ci detection ------------------------------------------------------

def test_has_ci_false_on_empty(tmp_path: Path) -> None:
    assert has_ci(str(tmp_path)) is False


def test_has_ci_true_with_github_workflow(tmp_path: Path) -> None:
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "anything.yml").write_text("name: x\n", encoding="utf-8")
    assert has_ci(str(tmp_path)) is True


def test_has_ci_true_with_other_markers(tmp_path: Path) -> None:
    for marker in (".gitlab-ci.yml", "Jenkinsfile", ".travis.yml"):
        d = tmp_path / marker.replace("/", "_")
        d.mkdir()
        (d / marker).write_text("ci\n", encoding="utf-8")
        assert has_ci(str(d)) is True


def test_has_ci_false_when_workflows_dir_empty(tmp_path: Path) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    assert has_ci(str(tmp_path)) is False


# --- generator: refuse vs fire --------------------------------------------

def test_generate_refuses_when_ci_present(tmp_path: Path) -> None:
    _python_project(tmp_path)
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("name: x\n", encoding="utf-8")
    assert generate_ci_workflow(str(tmp_path)) is None


def test_generate_refuses_non_python(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hi\n", encoding="utf-8")
    (tmp_path / "main.js").write_text("console.log(1)\n", encoding="utf-8")
    assert generate_ci_workflow(str(tmp_path)) is None


def test_generate_fires_for_python_project(tmp_path: Path) -> None:
    _python_project(tmp_path)
    result = generate_ci_workflow(str(tmp_path))
    assert result is not None
    assert result.transform_type == "add_ci_workflow"
    pr = result.patch_requests[0]
    assert pr["path"] == CI_WORKFLOW_PATH
    assert pr["expected_old_content"] is None  # brand-new file marker
    content = pr["new_content"]
    # A valid, minimal GitHub Actions workflow.
    for needle in ("name: CI", "actions/checkout@v4", "actions/setup-python@v5",
                   'python-version: "3.11"', "python -m pytest"):
        assert needle in content, needle


def test_generated_yaml_is_byte_identical(tmp_path: Path) -> None:
    _python_project(tmp_path)
    a = generate_ci_workflow(str(tmp_path)).patch_requests[0]["new_content"]
    b = generate_ci_workflow(str(tmp_path)).patch_requests[0]["new_content"]
    assert a == b


# --- install-line + ruff variants (deterministic by tree shape) -----------

def test_install_line_pyproject(tmp_path: Path) -> None:
    _python_project(tmp_path, packaging="pyproject.toml")
    content = generate_ci_workflow(str(tmp_path)).patch_requests[0]["new_content"]
    assert "pip install -e ." in content


def test_install_line_requirements(tmp_path: Path) -> None:
    _python_project(tmp_path, packaging="requirements.txt", body="pytest\n")
    content = generate_ci_workflow(str(tmp_path)).patch_requests[0]["new_content"]
    assert "pip install -r requirements.txt" in content


def test_install_line_bare_python(tmp_path: Path) -> None:
    # No packaging/requirements file, but .py present -> a Python project that
    # falls back to installing pytest.
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    content = generate_ci_workflow(str(tmp_path)).patch_requests[0]["new_content"]
    assert "pip install pytest" in content


def test_ruff_step_only_when_configured(tmp_path: Path) -> None:
    _python_project(tmp_path, packaging="pyproject.toml", body="[tool.ruff]\n")
    with_ruff = generate_ci_workflow(str(tmp_path)).patch_requests[0]["new_content"]
    assert "python -m ruff check ." in with_ruff

    other = _python_project(tmp_path / "no_ruff", packaging="pyproject.toml",
                            body="[project]\nname='x'\n")
    no_ruff = generate_ci_workflow(str(other)).patch_requests[0]["new_content"]
    assert "ruff" not in no_ruff


# --- bridge wiring: missing-ci is executable ------------------------------

def test_missing_ci_fact_is_executable() -> None:
    action, _desc, executable = _FACT_ACTIONS["missing-ci"]
    assert action == "add_ci"
    assert executable is True


def test_add_ci_is_tier0() -> None:
    assert tier_for("add_ci") == 0


def test_seeder_root_plans_executable_add_ci_step() -> None:
    profile = ProjectProfile(root=".", ci_files=[])
    roots = IdeaSeeder().seed(profile)
    ci_root = next(r for r in roots
                   if any("missing-ci" in f for f in r.source_facts))
    assert ci_root.subject == "CI pipeline"
    step = IdeaActionBridge().plan_idea(ci_root)
    assert step.action_type == "add_ci"
    assert step.executable is True
    assert step.target == CI_WORKFLOW_PATH


# --- the guarded apply gate, end-to-end -----------------------------------

def test_add_ci_applies_through_guarded_gate(tmp_path: Path) -> None:
    _python_project(tmp_path, packaging="pyproject.toml", body="[tool.ruff]\n")
    out = IdeaActionBridge().apply_step(_step(), str(tmp_path),
                                        mode="autonomous")
    assert out["applied"] is True
    assert out["transform_type"] == "add_ci_workflow"
    assert (tmp_path / CI_WORKFLOW_PATH).exists()
    assert has_ci(str(tmp_path)) is True


def test_add_ci_verifies_and_keeps_on_green(tmp_path: Path) -> None:
    _python_project(tmp_path, packaging="pyproject.toml")
    out = IdeaActionBridge().apply_step(_step(), str(tmp_path),
                                        mode="autonomous", verify=True,
                                        run_tests=False)
    assert out["applied"] is True
    assert out.get("verified") is True
    assert out.get("rolled_back") is False
    assert (tmp_path / CI_WORKFLOW_PATH).exists()


def test_add_ci_is_idempotent(tmp_path: Path) -> None:
    _python_project(tmp_path, packaging="pyproject.toml")
    bridge = IdeaActionBridge()
    first = bridge.apply_step(_step(), str(tmp_path), mode="autonomous")
    assert first["applied"] is True
    second = bridge.apply_step(_step(), str(tmp_path), mode="autonomous")
    assert second["applied"] is False
    assert second["reason"] == "no applicable patch generated"


def test_add_ci_report_mode_never_applies(tmp_path: Path) -> None:
    _python_project(tmp_path, packaging="pyproject.toml")
    out = IdeaActionBridge().apply_step(_step(), str(tmp_path), mode="report")
    assert out["applied"] is False
    assert not (tmp_path / CI_WORKFLOW_PATH).exists()


def test_add_ci_declines_non_python_through_gate(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hi\n", encoding="utf-8")
    out = IdeaActionBridge().apply_step(_step(), str(tmp_path),
                                        mode="autonomous")
    assert out["applied"] is False
    assert out["reason"] == "no applicable patch generated"
    assert not (tmp_path / CI_WORKFLOW_PATH).exists()
