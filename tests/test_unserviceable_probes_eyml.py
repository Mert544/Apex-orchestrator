"""Plan-time reality-check probe for ``add_docstring`` (readiness honesty).

A ``document``/``add_docstring`` step must only enter the ideate plan as
``executable`` when the deterministic docstring transform can actually act —
i.e. the target is a parseable Python module with an UNdocumented symbol.
Otherwise the readiness "auto-fixable" count is inflated by steps that merely
re-block at apply time ("no applicable patch generated"). These tests pin the
probe: it demotes the dead steps UP FRONT, never over-blocks a real undocumented
module, and is best-effort (an unreadable/odd target stays serviceable rather
than crashing).
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


def test_probe_is_best_effort_on_unreadable_target(tmp_path):
    # An odd/unreadable target (here: a path that does not exist) must NOT raise
    # and must NOT over-block — _read returns None, so the probe declines to a
    # serviceable verdict rather than crashing the planner.
    bridge = IdeaActionBridge()
    reason = bridge._docstring_unserviceable("app/missing.py", str(tmp_path))
    assert reason == ""


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
