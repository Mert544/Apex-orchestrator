"""Characterization tests locking in the byte-identical consolidations that
drained two duplication clusters:

  - automation pair: ``_classify_error`` now lives once in ``runner`` and is
    re-imported by ``adaptive_runner`` under its private alias;
  - param pair: ``_signature_lines`` (param-add) / ``_pin_signature`` (param-drop)
    now delegate to the shared ``_transform_base.pin_signature_lines`` core.

These assert the public/observable outputs are unchanged across a spread of
inputs, including the empty / blocker / edge paths. Deterministic, stdlib-only.
"""
from __future__ import annotations

from pathlib import Path

from app.automation.adaptive_runner import _classify_error as _classify_adaptive
from app.automation.runner import _classify_error as _classify_runner
from app.execution.param_add import plan_param_add
from app.execution.param_drop import plan_param_drop


# --- automation pair: identical classification, single source of truth ---

_EXCEPTIONS = [
    ValueError("v"),
    TypeError("t"),
    AssertionError("a"),
    KeyError("k"),
    ConnectionError("c"),
    TimeoutError("to"),
    OSError("os"),
    RuntimeError("patch failed"),
    RuntimeError("a timeout occurred"),
    RuntimeError("PatchError raised"),
    Exception("plain runtime"),
    type("PatchFailed", (Exception,), {})("boom"),
]


def test_classify_error_is_the_same_object_after_consolidation():
    # adaptive_runner re-imports runner's _classify_error, so they are identical.
    assert _classify_adaptive is _classify_runner


def test_classify_error_outputs_unchanged():
    expected = [
        "validation", "validation", "validation", "validation",
        "network", "network", "network",
        "unknown", "timeout", "unknown", "unknown", "patch",
    ]
    assert [_classify_runner(e) for e in _EXCEPTIONS] == expected
    assert [_classify_adaptive(e) for e in _EXCEPTIONS] == expected


# --- param pair: shared signature-span core, behaviour preserved ---

def _plan_view(plan):
    return {
        "old": plan.old,
        "new": plan.new,
        "defined_in": getattr(plan, "defined_in", None),
        "blockers": list(plan.blockers),
        "warnings": list(plan.warnings),
        "originals": dict(plan.originals),
        "new_contents": dict(plan.new_contents),
        "edits_by_file": dict(plan.edits_by_file),
    }


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")


def test_param_add_plain_appends_keyword_default(tmp_path):
    _write(tmp_path, {"m.py": "def f(a, b):\n    return a\n"})
    plan = plan_param_add(str(tmp_path), "f", "retries", "3")
    assert plan.blockers == []
    assert plan.new_contents["m.py"] == "def f(a, b, retries=3):\n    return a\n"
    assert plan.edits_by_file == {"m.py": 1}


def test_param_add_comment_in_signature_blocks(tmp_path):
    # The shared pin core must still refuse a header carrying a comment.
    _write(tmp_path, {"m.py": "def f(a,  # note\n      b):\n    return a\n"})
    plan = plan_param_add(str(tmp_path), "f", "retries", "3")
    assert plan.new_contents == {}
    assert any("contains a comment" in b for b in plan.blockers)


def test_param_drop_unused_keyword(tmp_path):
    _write(tmp_path, {
        "m.py": "def f(a, b):\n    return a\n",
        "u.py": "from m import f\nf(1, b=2)\n",
    })
    plan = plan_param_drop(str(tmp_path), "f", "b")
    assert plan.blockers == []
    assert plan.new_contents["m.py"] == "def f(a):\n    return a\n"


def test_param_drop_comment_in_signature_blocks(tmp_path):
    _write(tmp_path, {"m.py": "def f(a,  # note\n      b):\n    return a\n"})
    plan = plan_param_drop(str(tmp_path), "f", "b")
    assert plan.new_contents == {}
    assert any("contains a comment" in b for b in plan.blockers)


def test_param_drop_used_param_is_blocked_no_span_work_leaks(tmp_path):
    # Edge: a read parameter blocks before any rewrite is recorded.
    _write(tmp_path, {"m.py": "def f(a, b):\n    return a + b\n"})
    plan = plan_param_drop(str(tmp_path), "f", "b")
    assert plan.new_contents == {}
    assert _plan_view(plan)["edits_by_file"] == {}
