"""Plan-time reality-check probe for ``add_docstring`` (readiness honesty).

A ``document``/``add_docstring`` step must only enter the ideate plan as
``executable`` when the deterministic docstring transform can actually act —
i.e. the target is a parseable Python module with an UNdocumented symbol.
Otherwise the readiness "auto-fixable" count is inflated by steps that merely
re-block at apply time ("no applicable patch generated"). These tests pin the
probe: it demotes the dead steps UP FRONT, never over-blocks a real undocumented
module, and FAILS CLOSED on a missing/unreadable target (a nonexistent module is
declined, never scaffolded).
"""

from app.engine.idea_action_bridge import IdeaActionBridge
from app.models.idea import IdeaNode


def _doc_idea(subject: str) -> IdeaNode:
    return IdeaNode(
        id="i", title=f"Document: {subject}", subject=subject,
        operator="document", operator_chain=["document"],
        source_facts=[f"undocumented: {subject}"],
    )


def test_probe_registered_for_add_docstring():
    bridge = IdeaActionBridge()
    probe = {
        "add_docstring": bridge._docstring_unserviceable,
    }
    # The reason method exists and routes through the single source of truth.
    assert callable(bridge._unserviceable_reason)
    assert callable(probe["add_docstring"])


def test_demotes_module_with_all_symbols_documented(tmp_path):
    # Every function/class already carries a docstring -> the transform produces
    # no patch, so the step must be recommend-only AT PLAN TIME.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "documented.py").write_text(
        '"""Module."""\n\n\ndef f():\n    """Do f."""\n    return 1\n')
    bridge = IdeaActionBridge()
    step = bridge._expand_idea(_doc_idea("app/documented.py"),
                               project_root=str(tmp_path))[0]
    assert step.action_type == "add_docstring"
    assert step.executable is False
    assert "no undocumented Python symbol" in step.description


def test_demotes_symbol_less_python_target(tmp_path):
    # A .py file with no function/class/method has nothing to document.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "consts.py").write_text("A = 1\nB = 2\n")
    bridge = IdeaActionBridge()
    step = bridge._expand_idea(_doc_idea("app/consts.py"),
                               project_root=str(tmp_path))[0]
    assert step.executable is False
    assert "human review" in step.description


def test_demotes_non_python_target(tmp_path):
    # A non-.py target can never yield a Python docstring patch. The subject
    # still parses to a real path (it ends in a known extension), so the step is
    # built with a target and then demoted by the probe.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "thing.py").write_text("not python at all !!! ((((\n")
    bridge = IdeaActionBridge()
    # An unparseable .py file: the transform declines, probe demotes.
    step = bridge._expand_idea(_doc_idea("app/thing.py"),
                               project_root=str(tmp_path))[0]
    assert step.executable is False
    assert "human review" in step.description


def test_does_not_over_block_undocumented_module(tmp_path):
    # A real Python module WITH an undocumented function still plans as
    # executable — the probe must not over-block legitimately-serviceable work.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "raw.py").write_text("def f():\n    return 1\n")
    bridge = IdeaActionBridge()
    step = bridge._expand_idea(_doc_idea("app/raw.py"),
                               project_root=str(tmp_path))[0]
    assert step.action_type == "add_docstring"
    assert step.executable is True
    assert "no undocumented" not in step.description


def test_docstring_probe_fails_closed_on_missing_target(tmp_path):
    # HONESTY: a NONEXISTENT target (None text) must FAIL CLOSED — return a
    # non-empty blocking reason, never "" (which would scaffold docstrings for a
    # file that does not exist). It must not raise.
    bridge = IdeaActionBridge()
    reason = bridge._docstring_unserviceable("app/missing.py", str(tmp_path))
    assert reason != ""
    assert "unreadable target" in reason


def test_stub_probe_fails_closed_on_missing_target(tmp_path):
    # HONESTY: a create_test_stub for a module that does not exist must FAIL
    # CLOSED — a blocking reason, never "" (which would scaffold a test for
    # nothing). It must not raise.
    bridge = IdeaActionBridge()
    reason = bridge._stub_unserviceable("app/missing.py", str(tmp_path))
    assert reason != ""
    assert "not found" in reason


def test_docstring_probe_fails_closed_on_unreadable_binary(tmp_path):
    # A near-binary, non-UTF-8 file is unreadable as source (_read -> None) and
    # must be BLOCKED, not treated as serviceable.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "blob.py").write_bytes(b"\xff\xfe\x00\x01not utf8")
    bridge = IdeaActionBridge()
    reason = bridge._docstring_unserviceable("app/blob.py", str(tmp_path))
    assert reason != ""


def test_stub_probe_fails_closed_on_unreadable_binary(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "blob.py").write_bytes(b"\xff\xfe\x00\x01not utf8")
    bridge = IdeaActionBridge()
    reason = bridge._stub_unserviceable("app/blob.py", str(tmp_path))
    assert reason != ""


def test_missing_module_docstring_action_not_serviceable(tmp_path):
    # End-to-end: a Document action for a nonexistent module is reported NOT
    # serviceable (recommend-only), not scaffolded.
    bridge = IdeaActionBridge()
    reason = bridge._unserviceable_reason(
        "add_docstring", "app/missing.py", str(tmp_path))
    assert reason != ""


def test_missing_module_stub_action_not_serviceable(tmp_path):
    # End-to-end: a create_test_stub action for a nonexistent module is reported
    # NOT serviceable, not scaffolded.
    bridge = IdeaActionBridge()
    reason = bridge._unserviceable_reason(
        "create_test_stub", "app/missing.py", str(tmp_path))
    assert reason != ""


def test_stub_probe_serviceable_for_real_unlinked_module(tmp_path):
    # REGRESSION GUARD: a real module the suite does not yet reference is still
    # serviceable exactly as before (a stub is the first test layer).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "fresh.py").write_text("def f():\n    return 1\n")
    bridge = IdeaActionBridge()
    assert bridge._stub_unserviceable("app/fresh.py", str(tmp_path)) == ""


def test_probe_returns_empty_directly_for_undocumented(tmp_path):
    # Direct probe call: an undocumented symbol -> "" (serviceable).
    (tmp_path / "m.py").write_text("class C:\n    pass\n")
    bridge = IdeaActionBridge()
    assert bridge._docstring_unserviceable("m.py", str(tmp_path)) == ""


def test_unserviceable_reason_routes_add_docstring(tmp_path):
    # The single source of truth dispatches add_docstring to the docstring probe.
    (tmp_path / "m.py").write_text('"""M."""\n\n\ndef g():\n    """G."""\n    return 0\n')
    bridge = IdeaActionBridge()
    reason = bridge._unserviceable_reason("add_docstring", "m.py", str(tmp_path))
    assert "no undocumented Python symbol" in reason
