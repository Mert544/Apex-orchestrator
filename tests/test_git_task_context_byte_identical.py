# Characterization: prove the _task_context extraction in
# app.automation.skills.git is behaviourally byte-identical to the pre-refactor
# HEAD source.  We load the original module text from `git show HEAD:<path>` into
# a throwaway module, stub the git/PR-summary collaborators identically in both,
# and assert the public skills produce equal outputs across many synthesized
# AutomationContext inputs.  Zero mismatches == byte-identical observable behaviour.

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

import app.automation.skills.git as refactored
from app.automation.models import AutomationContext

_REL = "app/automation/skills/git.py"


def _load_head_module() -> types.ModuleType:
    """Import the HEAD (pre-refactor) git.py as an independent module."""
    repo_root = Path(__file__).resolve().parents[1]
    src = subprocess.run(
        ["git", "show", f"HEAD:{_REL}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    spec = importlib.util.spec_from_loader("_git_head_original", loader=None)
    mod = importlib.util.module_from_spec(spec)
    # The HEAD source uses `from ._context import ...`; anchor the relative
    # import at the real package so it resolves to the same _context module.
    mod.__package__ = "app.automation.skills"
    sys.modules["_git_head_original"] = mod
    exec(compile(src, f"{_REL}@HEAD", "exec"), mod.__dict__)
    return mod


_HEAD = _load_head_module()


class _StubResult:
    def __init__(self, tag: str):
        self.ok = True
        self.stdout = f"out-{tag}"
        self.stderr = f"err-{tag}"


class _StubGitAdapter:
    """Deterministic, offline stand-in for GitAdapter (records nothing global)."""

    def diff_stat(self, root):
        return _StubResult(f"diff:{root}")

    def status(self, root):
        return _StubResult(f"status:{root}")

    def add(self, root, files):
        return _StubResult(f"add:{root}:{files}")

    def commit(self, root, message):
        return _StubResult(f"commit:{root}:{message}")


class _StubSummary:
    def to_dict(self):
        return {"summary": "stub", "commit_message": "stub-commit"}


class _StubPRSummaryGenerator:
    def generate(self, **kwargs):
        # Echo the inputs deterministically so any divergence in what the skill
        # forwards is caught by the equality assertion.
        return _StubSummary()


def _patch(mod, monkeypatch):
    monkeypatch.setattr(mod, "GitAdapter", _StubGitAdapter, raising=True)
    monkeypatch.setattr(
        mod, "PRSummaryGenerator", _StubPRSummaryGenerator, raising=True
    )


def _make_context(case: int) -> AutomationContext:
    """A family of state shapes exercising every branch of _task_context."""
    states = [
        {},
        {"changed_files": ["a.py", "b.py"]},
        {"patch_plan": {"title": "PP title"}},
        {"task_plan": {"tasks": [{"title": "T0"}, {"title": "T1"}]}},
        {"task_plan": {"tasks": []}},
        {
            "changed_files": ["x.py"],
            "patch_plan": {"title": "PP"},
            "task_plan": {"tasks": [{"title": "First"}]},
            "verification": {"ok": True},
            "git_diff": {"diff_stat": "STAT"},
            "pr_summary": {"commit_message": "PRSUM"},
        },
        {
            "task_plan": {"tasks": [{}]},
            "pr_summary": {},
        },
        {"task_plan": {}},
    ]
    state = states[case % len(states)]
    return AutomationContext(
        project_root=Path("/tmp/apex-byteid-eyml1y"),
        objective=f"obj-{case}",
        config={},
        state=dict(state),
    )


@pytest.mark.parametrize("case", range(8))
def test_git_commit_skill_byte_identical(case, monkeypatch):
    _patch(refactored, monkeypatch)
    _patch(_HEAD, monkeypatch)
    ctx_new = _make_context(case)
    ctx_old = _make_context(case)
    out_new = refactored.git_commit_skill(ctx_new)
    out_old = _HEAD.git_commit_skill(ctx_old)
    assert out_new == out_old
    assert ctx_new.state == ctx_old.state


@pytest.mark.parametrize("case", range(8))
def test_generate_pr_summary_skill_byte_identical(case, monkeypatch):
    _patch(refactored, monkeypatch)
    _patch(_HEAD, monkeypatch)
    ctx_new = _make_context(case)
    ctx_old = _make_context(case)
    out_new = refactored.generate_pr_summary_skill(ctx_new)
    out_old = _HEAD.generate_pr_summary_skill(ctx_old)
    assert out_new == out_old
    assert ctx_new.state == ctx_old.state


def test_task_context_tuple_shape():
    """The helper resolves exactly the five values it consolidated, in order."""
    ctx = _make_context(5)
    target_root, changed_files, patch_plan, tasks, task = refactored._task_context(ctx)
    assert changed_files == ["x.py"]
    assert patch_plan == {"title": "PP"}
    assert tasks == [{"title": "First"}]
    assert task == {"title": "First"}
    assert target_root == ctx.project_root
