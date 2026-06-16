"""Characterization harness: prove the refactors of ``run_plan`` and
``plan_extract_constant`` are byte-identical to their pre-refactor originals.

Each original is loaded from ``git show HEAD:<file>`` into a throwaway module and
driven against the current (refactored) implementation over a battery of inputs.
Any observable divergence — returned plan/result fields, hook-call order,
blockers, edits, raised errors, stdout — fails the test. Offline, stdlib-only.
"""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import types
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from app.automation.models import AutomationContext, AutomationStep
from app.automation.registry import SkillAutomationRegistry

_REPO = Path(__file__).resolve().parent.parent


def _load_original(rel_path: str, mod_name: str) -> types.ModuleType:
    """Load the HEAD version of ``rel_path`` as a standalone module ``mod_name``."""
    src = subprocess.run(
        ["git", "show", f"HEAD:{rel_path}"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    spec = importlib.util.spec_from_loader(mod_name, loader=None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    exec(compile(src, f"<HEAD:{rel_path}>", "exec"), module.__dict__)
    return module


_orig_runner = _load_original("app/automation/runner.py", "_charz_orig_runner")
_orig_extract = _load_original(
    "app/execution/extract_constant.py", "_charz_orig_extract"
)

from app.automation.runner import SkillAutomationRunner  # noqa: E402
from app.execution.extract_constant import plan_extract_constant  # noqa: E402


# ---------------------------------------------------------------------------
# run_plan harness
# ---------------------------------------------------------------------------


class _RecordingPlugins:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def run_hook(self, hook_name: str, context: dict) -> dict:
        # Record name plus stable context keys (objects differ across runs).
        self.calls.append((hook_name, sorted(context.keys())))
        return context


def _make_skills():
    reg = SkillAutomationRegistry()
    for name in (
        "profile_project",
        "decompose_objective",
        "run_research",
        "generate_patch_requests",
        "generate_semantic_patch",
        "apply_patch",
        "run_tests",
        "verify_changes",
        "plan_tasks",
    ):
        reg.register(name, lambda ctx, n=name: {"skill": n, "ok": True})
    reg.register("enhanced_safety_check_pass", lambda ctx: {"ok": True})
    reg.register("safety_block", lambda ctx: {"ok": False})

    def boom(ctx):
        raise ValueError("kaboom")

    reg.register("boom", boom)
    return reg


def _S(name, skill):
    return AutomationStep(name=name, skill_name=skill)


_PLANS = {
    "scan_only": [_S("a", "profile_project")],
    "all_scan": [
        _S("a", "profile_project"),
        _S("b", "decompose_objective"),
        _S("c", "run_research"),
    ],
    "patch_test": [
        _S("p", "apply_patch"),
        _S("t", "run_tests"),
    ],
    "full": [
        _S("a", "profile_project"),
        _S("b", "decompose_objective"),
        _S("pr", "generate_patch_requests"),
        _S("sp", "generate_semantic_patch"),
        _S("ap", "apply_patch"),
        _S("rt", "run_tests"),
        _S("vc", "verify_changes"),
    ],
    "interleaved": [
        _S("a", "profile_project"),
        _S("ap", "apply_patch"),
        _S("c", "run_research"),
        _S("rt", "run_tests"),
    ],
    "safety_pass": [
        _S("s", "enhanced_safety_check"),
        _S("ap", "apply_patch"),
    ],
    "safety_block": [
        _S("s", "enhanced_safety_check"),
        _S("ap", "apply_patch"),
    ],
    "error_break": [
        _S("x", "boom"),
        _S("rt", "run_tests"),
    ],
}


def _registry_for(plan_name):
    reg = _make_skills()
    if plan_name == "safety_pass":
        reg.register("enhanced_safety_check", lambda ctx: {"ok": True})
    elif plan_name == "safety_block":
        reg.register("enhanced_safety_check", lambda ctx: {"ok": False})
    return reg


def _run(runner_cls, plan_name):
    plugins = _RecordingPlugins()
    runner = runner_cls(
        _registry_for(plan_name), plans={plan_name: _PLANS[plan_name]}, plugins=plugins
    )
    ctx = AutomationContext(project_root=Path("."), objective="o", config={})
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = runner.run_plan(plan_name, ctx)
    return result.to_dict(), plugins.calls, buf.getvalue()


@pytest.mark.parametrize("plan_name", sorted(_PLANS))
def test_run_plan_byte_identical(plan_name):
    orig = _run(_orig_runner.SkillAutomationRunner, plan_name)
    new = _run(SkillAutomationRunner, plan_name)
    assert orig == new


def test_run_plan_unknown_plan_identical():
    for cls in (_orig_runner.SkillAutomationRunner, SkillAutomationRunner):
        runner = cls(SkillAutomationRegistry(), plans={})
        with pytest.raises(KeyError, match="Unknown automation plan"):
            runner.run_plan("nope", AutomationContext(Path("."), "o", {}))


# ---------------------------------------------------------------------------
# plan_extract_constant harness
# ---------------------------------------------------------------------------


_SNIPPETS = {
    "simple_string": (
        "x = 'content-type'\n"
        "y = 'content-type'\n"
        "z = 'content-type'\n"
    ),
    "number": (
        "a = 86400\n"
        "b = 86400\n"
        "c = 86400\n"
        "d = 86400\n"
    ),
    "float": "p = 3.14\nq = 3.14\nr = 3.14\n",
    "below_threshold": "x = 'foobar'\ny = 'foobar'\n",
    "idioms_only": (
        "a = 'utf-8'\nb = 'utf-8'\nc = 'utf-8'\n"
        "d = open(p, 'r')\ne = open(q, 'r')\nf = open(s, 'r')\n"
    ),
    "with_docstring": (
        '"""Module."""\n'
        "import os\n"
        "x = 'route-key'\n"
        "y = 'route-key'\n"
        "z = 'route-key'\n"
    ),
    "const_rhs_excluded": (
        "ROUTE = 'route-key'\n"
        "x = 'route-key'\n"
        "y = 'route-key'\n"
    ),
    "kwarg_defaults_excluded": (
        "def f(a='mode-x'):\n    return a\n"
        "p = 'mode-x'\nq = 'mode-x'\nr = 'mode-x'\n"
    ),
    "dict_keys_excluded": (
        "d = {'header': 1}\n"
        "x = 'header'\ny = 'header'\nz = 'header'\n"
    ),
    "name_collision": (
        "CONTENT_TYPE = 1\n"
        "x = 'content-type'\ny = 'content-type'\nz = 'content-type'\n"
    ),
    "tie_break": (
        "a = 'aaa'\nb = 'aaa'\nc = 'aaa'\n"
        "d = 'bbb'\ne = 'bbb'\nf = 'bbb'\n"
    ),
    "crlf": "x = 'route-key'\r\ny = 'route-key'\r\nz = 'route-key'\r\n",
    "syntax_error": "def f(:\n    pass\n",
    "leading_digit_value": (
        "x = '404-not-found'\ny = '404-not-found'\nz = '404-not-found'\n"
    ),
    "multiline_skip": (
        "x = '''abc'''\ny = '''abc'''\nz = '''abc'''\n"
    ),
    "empty": "",
}


def _plan_to_tuple(plan):
    return (
        plan.old,
        plan.new,
        plan.defined_in,
        sorted(plan.blockers),
        sorted(plan.originals.items()),
        sorted(plan.new_contents.items()),
        sorted(plan.edits_by_file.items()),
    )


@pytest.mark.parametrize("key", sorted(_SNIPPETS))
@pytest.mark.parametrize("min_occ", [2, 3, 4])
def test_plan_extract_constant_byte_identical(key, min_occ):
    src = _SNIPPETS[key]
    rel = "app/sample.py"
    orig = _orig_extract.plan_extract_constant(
        "/proj", rel, min_occurrences=min_occ, source=src
    )
    new = plan_extract_constant("/proj", rel, min_occurrences=min_occ, source=src)
    assert _plan_to_tuple(orig) == _plan_to_tuple(new)


def test_plan_extract_constant_edge_inputs_identical():
    rel = "app/sample.py"
    src = _SNIPPETS["simple_string"]
    cases = [
        ("/proj", rel, 1, src),                       # min_occurrences < 2
        ("/proj", "tests/test_x.py", 3, src),         # fixture path
        ("/proj", "app/missing.py", 3, None),         # not found, no source
    ]
    for root, mod, mo, source in cases:
        orig = _orig_extract.plan_extract_constant(
            root, mod, min_occurrences=mo, source=source
        )
        new = plan_extract_constant(root, mod, min_occurrences=mo, source=source)
        assert _plan_to_tuple(orig) == _plan_to_tuple(new)
