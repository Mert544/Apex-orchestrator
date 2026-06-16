"""Characterization harness proving the refactored RetryEngine.run is
byte-identical (observably) to the pre-refactor snapshot.

The original implementation is imported from app.execution._retry_orig_char_eyml
(an exact copy of the HEAD blob taken before refactoring). For a wide matrix of
scripted inputs covering every branch, we drive both engines with identical
deterministic fakes and assert the returned RetryEngineResult.to_dict() is equal.
"""

from __future__ import annotations

import subprocess
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import app.execution.retry_engine as new_mod


def _load_original_module() -> types.ModuleType:
    """Materialize the pre-refactor HEAD blob of retry_engine.py as a module.

    This keeps the proof self-contained: no extra source file is committed; the
    baseline is read straight from git so the comparison cannot silently drift.
    """
    repo_root = Path(__file__).resolve().parents[1]
    blob = subprocess.run(
        ["git", "show", "HEAD:app/execution/retry_engine.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    mod_name = "_retry_engine_head_baseline_eyml"
    module = types.ModuleType(mod_name)
    module.__file__ = "<git:HEAD:app/execution/retry_engine.py>"
    sys.modules[mod_name] = module
    code = compile(blob, module.__file__, "exec")
    exec(code, module.__dict__)
    return module


orig_mod = _load_original_module()


# ---------------------------------------------------------------------------
# Deterministic fakes (duck-typed; mirror the real collaborators' surface used
# by run()).
# ---------------------------------------------------------------------------


@dataclass
class _DictWrap:
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)


class _ScriptedAnalyzer:
    """Returns successive analysis dicts; repeats the last one."""

    def __init__(self, scripts: list[dict[str, Any]]) -> None:
        self._scripts = scripts
        self.calls: list[dict[str, Any]] = []

    def run(self, verification: dict[str, Any]) -> _DictWrap:
        self.calls.append(verification)
        idx = min(len(self.calls) - 1, len(self._scripts) - 1)
        return _DictWrap(self._scripts[idx])


class _ScriptedPlanner:
    def __init__(self, scripts: list[dict[str, Any]]) -> None:
        self._scripts = scripts
        self.calls: list[tuple[Any, Any]] = []

    def run(self, analysis: dict[str, Any], patch_plan: dict[str, Any]) -> _DictWrap:
        self.calls.append((analysis, patch_plan))
        idx = min(len(self.calls) - 1, len(self._scripts) - 1)
        return _DictWrap(self._scripts[idx])


@dataclass
class _GenResult:
    patch_requests: list[dict[str, Any]]
    rationale: list[str] = field(default_factory=list)


class _ScriptedGenerator:
    def __init__(self, scripts: list[_GenResult]) -> None:
        self._scripts = scripts
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> _GenResult:
        self.calls.append(kwargs)
        idx = min(len(self.calls) - 1, len(self._scripts) - 1)
        return self._scripts[idx]


@dataclass
class _ApplyResult:
    ok: bool
    changed_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    error: Any = None


class _ScriptedApplier:
    def __init__(self, scripts: list[_ApplyResult]) -> None:
        self._scripts = scripts
        self.calls: list[Any] = []

    def run(self, root: Any, patches: Any) -> _ApplyResult:
        self.calls.append((root, patches))
        idx = min(len(self.calls) - 1, len(self._scripts) - 1)
        return self._scripts[idx]


class _ScriptedVerifier:
    def __init__(self, scripts: list[dict[str, Any]]) -> None:
        self._scripts = scripts
        self.calls: list[Any] = []

    def verify(self, **kwargs: Any) -> _DictWrap:
        self.calls.append(kwargs)
        idx = min(len(self.calls) - 1, len(self._scripts) - 1)
        return _DictWrap(self._scripts[idx])


def _build(engine_cls, scenario: dict[str, Any]):
    eng = engine_cls(
        max_retries=scenario["max_retries"],
        base_delay=scenario.get("base_delay", 1.0),
        max_delay=scenario.get("max_delay", 30.0),
        semantic_generator=_ScriptedGenerator(scenario["gen"]),
        verifier=_ScriptedVerifier(scenario["verify"]),
        patch_applier=_ScriptedApplier(scenario["apply"]),
    )
    eng.failure_analyzer = _ScriptedAnalyzer(scenario["analysis"])
    eng.repair_planner = _ScriptedPlanner(scenario["suggestion"])
    return eng


# A docstring-free patch request item (only the keys run() reads).
def _pr(path="app/m.py", new="x\n", old="y\n"):
    return {"path": path, "new_content": new, "expected_old_content": old}


def _pr_no_old(path="app/m.py", new="x\n"):
    # exercises item.get("expected_old_content") -> None
    return {"path": path, "new_content": new}


# ---------------------------------------------------------------------------
# Scenario matrix — each covers one or more branches of run().
# ---------------------------------------------------------------------------

_VER = {"ok": False, "test_summary": {"ok": False}}
_VER_OK = {"ok": True, "test_summary": {"ok": True}}


def _scenarios() -> list[dict[str, Any]]:
    scens: list[dict[str, Any]] = []

    # 1. no_failure_detected -> no_retry_needed
    scens.append({
        "name": "no_failure",
        "max_retries": 1,
        "verification": dict(_VER_OK),
        "patch_plan": {"target_files": ["a.py"]},
        "task": {"id": 1},
        "analysis": [{"primary_failure_type": "no_failure_detected", "summary": ["s"]}],
        "suggestion": [{"retry_recommended": True}],
        "gen": [_GenResult([_pr()])],
        "verify": [dict(_VER_OK)],
        "apply": [_ApplyResult(ok=True, changed_files=["a.py"])],
    })

    # 2. sensitive_edit -> human_review_required
    scens.append({
        "name": "sensitive",
        "max_retries": 2,
        "verification": dict(_VER),
        "patch_plan": {},
        "task": None,
        "analysis": [{"primary_failure_type": "sensitive_edit", "summary": []}],
        "suggestion": [{"retry_recommended": True}],
        "gen": [_GenResult([_pr()])],
        "verify": [dict(_VER_OK)],
        "apply": [_ApplyResult(ok=True)],
    })

    # 3. retry not recommended -> human_review_required
    scens.append({
        "name": "no_retry_recommended",
        "max_retries": 1,
        "verification": dict(_VER),
        "patch_plan": {"target_files": ["a.py"]},
        "task": {},
        "analysis": [{"primary_failure_type": "test_failure", "summary": ["x"]}],
        "suggestion": [{"retry_recommended": False, "suggested_actions": ["a"]}],
        "gen": [_GenResult([_pr()])],
        "verify": [dict(_VER_OK)],
        "apply": [_ApplyResult(ok=True)],
    })

    # 4. recommended, no patch generated -> exhausted (break, attempts=1)
    scens.append({
        "name": "no_patch",
        "max_retries": 2,
        "verification": dict(_VER),
        "patch_plan": {"target_files": ["a.py"]},
        "task": {},
        "analysis": [{"primary_failure_type": "test_failure", "summary": ["s"]}],
        "suggestion": [{"retry_recommended": True, "suggested_actions": ["fix"]}],
        "gen": [_GenResult([])],  # empty -> stop
        "verify": [dict(_VER_OK)],
        "apply": [_ApplyResult(ok=True)],
    })

    # 5. apply, verify success -> success on attempt 1
    scens.append({
        "name": "success_first",
        "max_retries": 1,
        "verification": dict(_VER),
        "patch_plan": {"target_files": ["a.py"]},
        "task": {"t": 1},
        "analysis": [{"primary_failure_type": "test_failure", "summary": ["s"]}],
        "suggestion": [{"retry_recommended": True, "suggested_actions": ["fix"]}],
        "gen": [_GenResult([_pr()], rationale=["gen-r"])],
        "verify": [dict(_VER_OK)],
        "apply": [_ApplyResult(ok=True, changed_files=["a.py"], skipped_files=["s.py"])],
    })

    # 6. patch_scope_failure -> scope reduction branch, then success
    scens.append({
        "name": "scope_reduction_success",
        "max_retries": 1,
        "verification": dict(_VER),
        "patch_plan": {"target_files": ["a.py", "b.py", "c.py", "d.py", "e.py"]},
        "task": {},
        "analysis": [{"primary_failure_type": "patch_scope_failure", "summary": ["scope"]}],
        "suggestion": [{"retry_recommended": True, "suggested_actions": []}],
        "gen": [_GenResult([_pr_no_old()], rationale=["r"])],
        "verify": [dict(_VER_OK)],
        "apply": [_ApplyResult(ok=True, changed_files=["a.py"])],
    })

    # 7. apply fails -> re-analyze -> continue -> budget exhausted (max_retries=1)
    scens.append({
        "name": "apply_fail_exhaust",
        "max_retries": 1,
        "verification": dict(_VER),
        "patch_plan": {"target_files": ["a.py"]},
        "task": {},
        "analysis": [
            {"primary_failure_type": "test_failure", "summary": ["s"]},
            {"primary_failure_type": "test_failure", "summary": ["s2"]},
        ],
        "suggestion": [{"retry_recommended": True, "suggested_actions": ["fix"]}],
        "gen": [_GenResult([_pr()], rationale=["r"])],
        "verify": [dict(_VER)],
        "apply": [_ApplyResult(ok=False, error="boom", changed_files=["a.py"], skipped_files=["b.py"])],
    })

    # 8. verify fails, re-plan still recommends -> second attempt success
    scens.append({
        "name": "persist_then_success",
        "max_retries": 3,
        "base_delay": 0.0,  # keep deterministic & fast
        "verification": dict(_VER),
        "patch_plan": {"target_files": ["a.py"]},
        "task": {},
        "analysis": [
            {"primary_failure_type": "test_failure", "summary": ["s1"]},
            {"primary_failure_type": "test_failure", "summary": ["s2"]},
        ],
        "suggestion": [
            {"retry_recommended": True, "suggested_actions": ["a"]},
            {"retry_recommended": True, "suggested_actions": ["b"]},
        ],
        "gen": [
            _GenResult([_pr(new="v1\n")], rationale=["r1"]),
            _GenResult([_pr(new="v2\n")], rationale=["r2"]),
        ],
        "verify": [dict(_VER), dict(_VER_OK)],
        "apply": [
            _ApplyResult(ok=True, changed_files=["a.py"]),
            _ApplyResult(ok=True, changed_files=["a.py"]),
        ],
    })

    # 9. verify fails, re-plan stops recommending -> break -> exhausted
    scens.append({
        "name": "persist_then_stop",
        "max_retries": 3,
        "base_delay": 0.0,
        "verification": dict(_VER),
        "patch_plan": {"target_files": ["a.py"]},
        "task": {},
        "analysis": [
            {"primary_failure_type": "test_failure", "summary": ["s1"]},
            {"primary_failure_type": "test_failure", "summary": ["s2"]},
        ],
        "suggestion": [
            {"retry_recommended": True, "suggested_actions": ["a"]},
            {"retry_recommended": False, "suggested_actions": ["b"]},
        ],
        "gen": [_GenResult([_pr()], rationale=["r1"])],
        "verify": [dict(_VER)],
        "apply": [_ApplyResult(ok=True, changed_files=["a.py"])],
    })

    # 10. verify keeps failing but re-plan keeps recommending across all retries -> exhausted
    scens.append({
        "name": "always_fail_exhaust",
        "max_retries": 3,
        "base_delay": 0.0,
        "verification": dict(_VER),
        "patch_plan": {"target_files": ["a.py", "b.py"]},
        "task": {},
        "analysis": [{"primary_failure_type": "test_failure", "summary": ["s"]}],
        "suggestion": [{"retry_recommended": True, "suggested_actions": ["a"]}],
        "gen": [_GenResult([_pr()], rationale=["r"])],
        "verify": [dict(_VER)],
        "apply": [_ApplyResult(ok=True, changed_files=["a.py"])],
    })

    # 11. unknown failure type but recommended -> proceeds; verify ok -> success
    scens.append({
        "name": "unknown_recommended_success",
        "max_retries": 2,
        "base_delay": 0.0,
        "verification": dict(_VER),
        "patch_plan": {},
        "task": {},
        "analysis": [{"primary_failure_type": "unknown", "summary": []}],
        "suggestion": [{"retry_recommended": True}],
        "gen": [_GenResult([_pr()])],
        "verify": [dict(_VER_OK)],
        "apply": [_ApplyResult(ok=True, changed_files=["a.py"])],
    })

    # 12. apply-fail continue then a later attempt succeeds (multi-attempt mix)
    scens.append({
        "name": "applyfail_then_success",
        "max_retries": 3,
        "base_delay": 0.0,
        "verification": dict(_VER),
        "patch_plan": {"target_files": ["a.py"]},
        "task": {},
        "analysis": [
            {"primary_failure_type": "test_failure", "summary": ["s1"]},
            {"primary_failure_type": "patch_scope_failure", "summary": ["s2"]},
        ],
        "suggestion": [{"retry_recommended": True, "suggested_actions": ["a"]}],
        "gen": [
            _GenResult([_pr(new="v1\n")], rationale=["r1"]),
            _GenResult([_pr(new="v2\n")], rationale=["r2"]),
        ],
        "verify": [dict(_VER_OK)],
        "apply": [
            _ApplyResult(ok=False, error="e1", changed_files=["a.py"], skipped_files=[]),
            _ApplyResult(ok=True, changed_files=["a.py"]),
        ],
    })

    # 13. default failure_type (missing key) -> "unknown", recommended, success
    scens.append({
        "name": "missing_failure_key",
        "max_retries": 1,
        "verification": dict(_VER),
        "patch_plan": {"target_files": ["a.py"]},
        "task": {},
        "analysis": [{"summary": ["s"]}],  # no primary_failure_type
        "suggestion": [{"retry_recommended": True}],
        "gen": [_GenResult([_pr()])],
        "verify": [dict(_VER_OK)],
        "apply": [_ApplyResult(ok=True, changed_files=["a.py"])],
    })

    # 14. zero retries -> loop never runs -> exhausted with attempts 0
    scens.append({
        "name": "zero_retries",
        "max_retries": 0,
        "verification": dict(_VER),
        "patch_plan": {"target_files": ["a.py"]},
        "task": {},
        "analysis": [{"primary_failure_type": "test_failure", "summary": ["s"]}],
        "suggestion": [{"retry_recommended": True}],
        "gen": [_GenResult([_pr()])],
        "verify": [dict(_VER_OK)],
        "apply": [_ApplyResult(ok=True)],
    })

    return scens


@pytest.fixture(autouse=True)
def _freeze_time_and_random(monkeypatch):
    # Make backoff fully deterministic and instantaneous in both modules.
    for mod in (orig_mod, new_mod):
        monkeypatch.setattr(mod.time, "sleep", lambda *_a, **_k: None)
        monkeypatch.setattr(mod.random, "random", lambda: 0.5)


@pytest.mark.parametrize("scenario", _scenarios(), ids=lambda s: s["name"])
def test_refactor_is_observably_byte_identical(scenario):
    eng_orig = _build(orig_mod.RetryEngine, scenario)
    eng_new = _build(new_mod.RetryEngine, scenario)

    common = dict(
        project_root=".",
        verification=dict(scenario["verification"]),
        patch_plan=None if scenario["patch_plan"] is None else dict(scenario["patch_plan"]),
        task=scenario["task"],
    )

    out_orig = eng_orig.run(**common).to_dict()
    out_new = eng_new.run(**common).to_dict()

    assert out_orig == out_new, scenario["name"]

    # Also assert collaborators were driven identically (call counts match),
    # proving the control flow itself is identical, not just the final dict.
    assert eng_orig.failure_analyzer.calls == eng_new.failure_analyzer.calls
    assert eng_orig.repair_planner.calls == eng_new.repair_planner.calls
    assert len(eng_orig.semantic_generator.calls) == len(eng_new.semantic_generator.calls)
    assert len(eng_orig.patch_applier.calls) == len(eng_new.patch_applier.calls)
    assert len(eng_orig.verifier.calls) == len(eng_new.verifier.calls)


def test_default_patch_plan_and_task_none():
    # Covers patch_plan=None / task=None defaulting path in both impls.
    scenario = {
        "max_retries": 1,
        "verification": dict(_VER),
        "patch_plan": None,
        "task": None,
        "analysis": [{"primary_failure_type": "test_failure", "summary": ["s"]}],
        "suggestion": [{"retry_recommended": True}],
        "gen": [_GenResult([_pr()])],
        "verify": [dict(_VER_OK)],
        "apply": [_ApplyResult(ok=True, changed_files=["a.py"])],
    }
    eng_orig = _build(orig_mod.RetryEngine, scenario)
    eng_new = _build(new_mod.RetryEngine, scenario)
    out_orig = eng_orig.run(project_root=".", verification=dict(_VER)).to_dict()
    out_new = eng_new.run(project_root=".", verification=dict(_VER)).to_dict()
    assert out_orig == out_new
