"""Concrete create_test_stub proposals.

When an idea carries function-grain anchors, the bridge names the ACTUAL
function(s) + line(s) in the proposed action; with only a module known it falls
back to the existing module-level phrasing. Anchors are read defensively (the
field may not be present on IdeaNode yet), so tests inject them via a
SimpleNamespace-like stand-in. The bridge proposes only — it never executes.
"""

from types import SimpleNamespace

from app.engine.idea_action_bridge import IdeaActionBridge
from app.models.idea import IdeaNode


def _idea_stub(*, subject, source_facts, operator="root", anchors=None,
               branch_path="0", title="Test", value=0.5):
    """An IdeaNode-shaped stand-in carrying an (optional) anchors field.

    A real IdeaNode is a frozen-schema pydantic model with no `anchors` field
    yet, so the parallel-agent field is injected on a SimpleNamespace that
    quacks like the node the bridge reads (getattr-defensive on its side)."""
    return SimpleNamespace(
        id="i", title=title, subject=subject, rationale="", branch_path=branch_path,
        depth=0, parent_id=None, source_facts=list(source_facts), operator=operator,
        operator_chain=[], kind="permutation", relevance=1.0, novelty=1.0,
        feasibility=0.5, value=value, caveats=[],
        anchors=anchors if anchors is not None else [],
    )


def test_anchors_make_description_name_function_and_line():
    idea = _idea_stub(
        subject="app/tools/project_profile.py",
        source_facts=["untested: app/tools/project_profile.py"],
        anchors=[{"module": "app/tools/project_profile.py", "symbol": "_scan_churn",
                  "line": 550, "metric": "cyclomatic 18, no linked test"}],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "create_test_stub"
    assert "`_scan_churn`" in step.description
    assert "app/tools/project_profile.py:550" in step.description
    assert "cyclomatic 18, no linked test" in step.description
    # Still a real, patchable module target.
    assert step.target == "app/tools/project_profile.py"


def test_real_ideanode_without_anchors_falls_back_to_module_phrasing():
    # A genuine IdeaNode carries no anchors field at all -> defensive getattr.
    idea = IdeaNode(
        id="i", title="Test: app/main.py", subject="app/main.py", operator="test",
        operator_chain=["test"], source_facts=["untested: app/main.py"],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "create_test_stub"
    # Module-level template, unchanged — no fabricated function name.
    assert step.description == "Create a test stub covering app/main.py"
    assert step.patch_preview is None


def test_empty_anchors_list_falls_back():
    idea = _idea_stub(
        subject="app/main.py", operator="test",
        source_facts=["untested: app/main.py"], anchors=[],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.description == "Create a test stub covering app/main.py"
    assert step.patch_preview is None


def test_anchor_without_symbol_is_ignored():
    # An anchor that names no symbol can't make the text concrete -> fall back.
    idea = _idea_stub(
        subject="app/main.py", operator="test",
        source_facts=["untested: app/main.py"],
        anchors=[{"module": "app/main.py", "line": 10, "symbol": "  "}],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.description == "Create a test stub covering app/main.py"
    assert step.patch_preview is None


def test_multiple_anchors_named_in_stable_order():
    idea = _idea_stub(
        subject="app/svc.py", operator="test",
        source_facts=["untested: app/svc.py"],
        anchors=[
            {"module": "app/svc.py", "symbol": "alpha", "line": 5},
            {"module": "app/svc.py", "symbol": "beta", "line": 9},
        ],
    )
    step = IdeaActionBridge().plan_idea(idea)
    # Carried order is preserved (alpha before beta), both named.
    assert step.description.index("`alpha`") < step.description.index("`beta`")
    assert "app/svc.py:5" in step.description
    assert "app/svc.py:9" in step.description


def test_stub_body_preview_names_real_symbol_and_import_path():
    idea = _idea_stub(
        subject="app/tools/project_profile.py",
        source_facts=["hotspot-function: app/tools/project_profile.py::_scan_churn"],
        operator="test",
        anchors=[{"module": "app/tools/project_profile.py", "symbol": "_scan_churn",
                  "line": 550, "metric": "cyclomatic 18"}],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.patch_preview is not None
    body = step.patch_preview["stub_body"]
    # Real import path and real symbol, not a generic placeholder.
    assert "import app.tools.project_profile" in body
    assert "def test__scan_churn_behavior" in body
    assert "_scan_churn" in body
    assert step.patch_preview["applied"] is False


def test_anchor_metric_and_line_optional():
    idea = _idea_stub(
        subject="app/x.py", operator="test", source_facts=["untested: app/x.py"],
        anchors=[{"module": "app/x.py", "symbol": "do_thing"}],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert "`do_thing`" in step.description
    # No fabricated line/metric when the anchor omits them.
    assert ":" not in step.description.split("`do_thing`")[1].split(",")[0] or \
        "app/x.py" in step.description


def test_determinism_same_input_same_output():
    def build():
        idea = _idea_stub(
            subject="app/svc.py", operator="test",
            source_facts=["untested: app/svc.py"],
            anchors=[{"module": "app/svc.py", "symbol": "alpha", "line": 5,
                      "metric": "cyclomatic 9"},
                     {"module": "app/svc.py", "symbol": "beta", "line": 9}],
        )
        s = IdeaActionBridge().plan_idea(idea)
        return s.description, s.patch_preview["stub_body"]

    assert build() == build()


def test_plan_idea_does_not_execute_anything(tmp_path):
    # The bridge proposes; planning must not write or read the source tree.
    (tmp_path / "app").mkdir()
    target = tmp_path / "app" / "svc.py"
    target.write_text("def alpha():\n    return 1\n")
    before = target.read_text()
    idea = _idea_stub(
        subject="app/svc.py", operator="test",
        source_facts=["untested: app/svc.py"],
        anchors=[{"module": "app/svc.py", "symbol": "alpha", "line": 1}],
    )
    IdeaActionBridge().plan_idea(idea)
    assert target.read_text() == before
    assert not (tmp_path / "tests").exists()


def test_convergence_substep_is_concrete_with_anchors():
    # A convergence test sub-step also names the concrete function.
    idea = _idea_stub(
        subject="app/hub.py", operator="root",
        source_facts=["convergence: untested + security-sensitive"],
        anchors=[{"module": "app/hub.py", "symbol": "core", "line": 12}],
        branch_path="3",
    )
    steps = IdeaActionBridge().plan_convergence(idea)
    test_steps = [s for s in steps if s.action_type == "create_test_stub"]
    assert test_steps, "convergence should emit a test sub-step"
    assert "`core`" in test_steps[0].description
    assert "app/hub.py:12" in test_steps[0].description
