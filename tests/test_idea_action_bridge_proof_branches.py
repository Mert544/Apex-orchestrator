"""Edge/branch coverage for the proof paths of IdeaActionBridge.

Focus: _diff_and_verdict, prove_step, attach_proofs, _proof_affordance, the
covered/uncovered clause, the impact-empty path, and the recommend-only
fallbacks in the markdown renderers. All deterministic; recommend-only — no
apply/run is ever triggered.
"""
from types import SimpleNamespace

from app.engine.idea_action_bridge import (
    IdeaActionBridge,
    _applied_fix_line,
    _proof_affordance,
    _result_sections,
    render_action_markdown,
    render_maintenance_markdown,
)
from app.models.idea import ActionPlan, ActionStep, IdeaNode


def _result(patch_requests, transform_type="security", rationale=""):
    """A minimal stand-in for a SemanticPatchResult."""
    return SimpleNamespace(patch_requests=patch_requests,
                           transform_type=transform_type, rationale=rationale)


# --------------------------------------------------------------------------
# _diff_and_verdict
# --------------------------------------------------------------------------

def test_diff_and_verdict_none_when_no_requests(tmp_path):
    assert IdeaActionBridge._diff_and_verdict(_result([]), str(tmp_path)) is None
    assert IdeaActionBridge._diff_and_verdict(_result(None), str(tmp_path)) is None


def test_diff_and_verdict_clean_reparse_and_added_removed(tmp_path):
    (tmp_path / "app").mkdir()
    f = tmp_path / "app" / "m.py"
    f.write_text("x = 1\nold = 2\n", encoding="utf-8")
    result = _result([{"path": "app/m.py", "new_content": "x = 1\nnew = 3\n"}])
    proof = IdeaActionBridge._diff_and_verdict(result, str(tmp_path))
    assert proof is not None
    assert proof["reparses"] is True
    assert proof["added"] >= 1 and proof["removed"] >= 1
    assert "app/m.py" in proof["diff"]
    # Source tree untouched (recommend-only).
    assert f.read_text(encoding="utf-8") == "x = 1\nold = 2\n"


def test_diff_and_verdict_reparse_fails_on_broken_python(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("x = 1\n", encoding="utf-8")
    result = _result([{"path": "app/m.py", "new_content": "def broken(:\n"}])
    proof = IdeaActionBridge._diff_and_verdict(result, str(tmp_path))
    assert proof is not None
    assert proof["reparses"] is False
    # Broken source moves no metric -> empty impact.
    assert proof["impact"] == ""


def test_diff_and_verdict_new_file_diff_for_created_path(tmp_path):
    # A path that does not exist (old="") yields a real unified diff that
    # adds every line of the new content.
    result = _result([{"path": "tests/test_new.py", "new_content": "def test_x():\n    assert True\n"}])
    proof = IdeaActionBridge._diff_and_verdict(result, str(tmp_path))
    assert proof is not None
    assert "+++ b/tests/test_new.py" in proof["diff"]
    assert proof["added"] == 2 and proof["removed"] == 0


def test_diff_and_verdict_non_python_skips_parse_verdict(tmp_path):
    # A non-.py change is never parse-checked: reparses stays True, no impact.
    (tmp_path / "README.md").write_text("old\n", encoding="utf-8")
    result = _result([{"path": "README.md", "new_content": "new content\n"}])
    proof = IdeaActionBridge._diff_and_verdict(result, str(tmp_path))
    assert proof is not None
    assert proof["reparses"] is True
    assert proof["covered"] is False


def test_diff_and_verdict_impact_populated_when_metric_moves(tmp_path):
    # Flattening nesting moves a structural metric -> impact is non-empty.
    (tmp_path / "app").mkdir()
    old = (
        "def f(a):\n"
        "    if a:\n"
        "        if a > 1:\n"
        "            if a > 2:\n"
        "                return a\n"
        "    return 0\n"
    )
    new = "def f(a):\n    return a\n"
    (tmp_path / "app" / "m.py").write_text(old, encoding="utf-8")
    result = _result([{"path": "app/m.py", "new_content": new}])
    proof = IdeaActionBridge._diff_and_verdict(result, str(tmp_path))
    assert proof is not None
    assert proof["impact"]  # a metric moved


def test_diff_and_verdict_covered_true_when_test_references_module(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "widget.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_widget.py").write_text(
        "from app.widget import x\n\n\ndef test_x():\n    assert x == 1\n",
        encoding="utf-8",
    )
    result = _result([{"path": "app/widget.py", "new_content": "x = 2\n"}])
    proof = IdeaActionBridge._diff_and_verdict(result, str(tmp_path))
    assert proof is not None
    assert proof["covered"] is True


def test_diff_and_verdict_identical_content_yields_zero_stats(tmp_path):
    # Identical old/new content produces an empty unified diff; the per-file
    # "(new file)" placeholder still records the change, but +/- are both 0.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("same\n", encoding="utf-8")
    result = _result([{"path": "app/m.py", "new_content": "same\n"}])
    proof = IdeaActionBridge._diff_and_verdict(result, str(tmp_path))
    assert proof is not None
    assert proof["added"] == 0 and proof["removed"] == 0
    assert proof["reparses"] is True


# --------------------------------------------------------------------------
# prove_step / attach_proofs  (recommend-only)
# --------------------------------------------------------------------------

def test_prove_step_none_when_generator_returns_none(tmp_path, monkeypatch):
    bridge = IdeaActionBridge()
    monkeypatch.setattr(bridge, "_generate", lambda step, root: None)
    step = ActionStep(branch_path="b", title="t", operator="test",
                      subject="app/m.py", action_type="create_test_stub",
                      target="app/m.py", executable=True)
    assert bridge.prove_step(step, str(tmp_path)) is None


def test_prove_step_swallows_generator_exception(tmp_path, monkeypatch):
    bridge = IdeaActionBridge()

    def boom(step, root):
        raise RuntimeError("nope")

    monkeypatch.setattr(bridge, "_generate", boom)
    step = ActionStep(branch_path="b", title="t", operator="test",
                      subject="app/m.py", action_type="create_test_stub",
                      target="app/m.py", executable=True)
    assert bridge.prove_step(step, str(tmp_path)) is None


def test_prove_step_returns_proof_from_fake_result(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("x = 1\n", encoding="utf-8")
    bridge = IdeaActionBridge()
    monkeypatch.setattr(
        bridge, "_generate",
        lambda step, root: _result([{"path": "app/m.py", "new_content": "x = 2\n"}]),
    )
    step = ActionStep(branch_path="b", title="t", operator="harden",
                      subject="app/m.py", action_type="harden_security",
                      target="app/m.py", executable=True)
    proof = bridge.prove_step(step, str(tmp_path))
    assert proof is not None and proof["reparses"] is True


def test_attach_proofs_merges_into_preview_and_respects_budget(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("x = 1\n", encoding="utf-8")
    bridge = IdeaActionBridge()
    monkeypatch.setattr(
        bridge, "prove_step",
        lambda step, root: {"diff": "d", "added": 1, "removed": 0,
                            "reparses": True, "impact": "", "covered": False},
    )
    steps = [
        ActionStep(branch_path=f"b{i}", title="t", operator="harden",
                   subject="app/m.py", action_type="harden_security",
                   target="app/m.py", executable=True)
        for i in range(3)
    ]
    plan = ActionPlan(steps=steps)
    out = bridge.attach_proofs(plan, str(tmp_path), max_proofs=2)
    assert out is plan
    assert out.steps[0].patch_preview["added"] == 1
    assert out.steps[0].patch_preview["applied"] is False
    assert out.steps[1].patch_preview is not None
    # Budget of 2 -> the third step is left proofless.
    assert out.steps[2].patch_preview is None


def test_attach_proofs_skips_non_executable_and_non_py_and_unmapped(tmp_path, monkeypatch):
    bridge = IdeaActionBridge()
    monkeypatch.setattr(
        bridge, "prove_step",
        lambda step, root: {"diff": "d", "added": 1, "removed": 0, "reparses": True},
    )
    steps = [
        ActionStep(branch_path="a", title="t", operator="extend",
                   subject="app/m.py", action_type="design_task",
                   target="app/m.py", executable=False),
        ActionStep(branch_path="b", title="t", operator="test",
                   subject="docs/x.md", action_type="create_test_stub",
                   target="docs/x.md", executable=True),
        ActionStep(branch_path="c", title="t", operator="x",
                   subject="app/m.py", action_type="unknown_action",
                   target="app/m.py", executable=True),
    ]
    plan = ActionPlan(steps=steps)
    bridge.attach_proofs(plan, str(tmp_path))
    assert all(s.patch_preview is None for s in plan.steps)


def test_attach_proofs_leaves_step_when_proof_is_none(tmp_path, monkeypatch):
    bridge = IdeaActionBridge()
    monkeypatch.setattr(bridge, "prove_step", lambda step, root: None)
    step = ActionStep(branch_path="b", title="t", operator="harden",
                      subject="app/m.py", action_type="harden_security",
                      target="app/m.py", executable=True)
    plan = ActionPlan(steps=[step])
    bridge.attach_proofs(plan, str(tmp_path))
    assert plan.steps[0].patch_preview is None


def test_attach_proofs_preserves_existing_preview_fields(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("x = 1\n", encoding="utf-8")
    bridge = IdeaActionBridge()
    monkeypatch.setattr(
        bridge, "prove_step",
        lambda step, root: {"diff": "d", "added": 2, "removed": 1, "reparses": True},
    )
    step = ActionStep(branch_path="b", title="t", operator="harden",
                      subject="app/m.py", action_type="harden_security",
                      target="app/m.py", executable=True,
                      patch_preview={"transform_type": "security", "files": ["app/m.py"]})
    bridge.attach_proofs(ActionPlan(steps=[step]), str(tmp_path))
    assert step.patch_preview["transform_type"] == "security"
    assert step.patch_preview["added"] == 2


# --------------------------------------------------------------------------
# _proof_affordance
# --------------------------------------------------------------------------

def _proof_step(**preview):
    return ActionStep(branch_path="root.1", title="t", operator="harden",
                      subject="app/m.py", action_type="harden_security",
                      target="app/m.py", executable=True, patch_preview=preview or None)


def test_proof_affordance_empty_without_proof_fields():
    assert _proof_affordance(_proof_step()) == ""
    assert _proof_affordance(_proof_step(files=["app/m.py"])) == ""


def test_proof_affordance_clean_reparse_line():
    line = _proof_affordance(_proof_step(diff="d", added=3, removed=1, reparses=True))
    assert "+3 −1" in line
    assert "re-parses cleanly ✓" in line
    assert "apex brief root.1" in line


def test_proof_affordance_reparse_failed_line():
    line = _proof_affordance(_proof_step(diff="d", added=1, removed=0, reparses=False))
    assert "⚠️ re-parse check failed" in line


def test_proof_affordance_impact_clause():
    line = _proof_affordance(_proof_step(diff="d", added=1, removed=0, reparses=True,
                                         impact="cognitive 6→3"))
    assert ", cognitive 6→3" in line


def test_proof_affordance_covered_true_and_false_clauses():
    on = _proof_affordance(_proof_step(diff="d", added=1, removed=0, reparses=True,
                                       covered=True))
    assert "your tests reference this module ✓" in on
    off = _proof_affordance(_proof_step(diff="d", added=1, removed=0, reparses=True,
                                        covered=False))
    assert "no test exercises this — add one first" in off


def test_proof_affordance_omits_coverage_clause_when_signal_absent():
    line = _proof_affordance(_proof_step(diff="d", added=1, removed=0, reparses=True))
    assert "tests reference this module" not in line
    assert "no test exercises this" not in line


# --------------------------------------------------------------------------
# render_action_markdown — proof line + advisory work-order fallback
# --------------------------------------------------------------------------

def test_render_action_markdown_includes_proof_line_for_runnable_step():
    step = _proof_step(diff="d", added=2, removed=0, reparses=True, covered=True,
                       transform_type="security", files=["app/m.py"])
    plan = ActionPlan(project_root="/p", steps=[step],
                      stats={"total_steps": 1, "executable_steps": 1, "design_tasks": 0})
    md = render_action_markdown(plan)
    assert "proof: +2 −0" in md
    assert "draft `security`" in md
    assert "1 of 1 steps are runnable now" in md


def test_render_action_markdown_advisory_step_gets_work_order():
    step = ActionStep(branch_path="root.2", title="t", operator="extend",
                      subject="app/m.py", action_type="design_task",
                      target="app/m.py", executable=False, phase="Evolve")
    plan = ActionPlan(project_root="/p", steps=[step],
                      stats={"total_steps": 1, "executable_steps": 0, "design_tasks": 1})
    md = render_action_markdown(plan)
    assert "work order: `apex brief root.2`" in md
    assert "[Evolve]" in md


# --------------------------------------------------------------------------
# _applied_fix_line — verification-strength clause variants
# --------------------------------------------------------------------------

def test_applied_fix_line_function_level_strength():
    r = {"branch": "b", "action": "harden_security", "verified": True,
         "verification_strength": {"level": "function"}, "changed_files": ["app/m.py"]}
    assert "name the changed function" in _applied_fix_line(r)


def test_applied_fix_line_module_level_strength():
    r = {"branch": "b", "action": "harden_security", "verified": True,
         "verification_strength": {"level": "module"}, "changed_files": ["app/m.py"]}
    assert "suite references this module" in _applied_fix_line(r)


def test_applied_fix_line_none_level_strength_warns():
    r = {"branch": "b", "action": "harden_security", "verified": True,
         "verification_strength": {"level": "none"}, "changed_files": ["app/m.py"]}
    assert "⚠️ no test references this module" in _applied_fix_line(r)


def test_applied_fix_line_unknown_level_falls_back():
    r = {"branch": "b", "action": "harden_security", "verified": True,
         "verification_strength": {"level": "mystery"}, "changed_files": ["app/m.py"]}
    assert "(tests pass)" in _applied_fix_line(r)


def test_applied_fix_line_impact_shield_and_commit_clauses():
    r = {"branch": "b", "action": "harden_security",
         "impact": "max nesting 3→1", "shield_test": "tests/test_m.py",
         "committed": True, "commit_hash": "abc123",
         "changed_files": ["app/m.py"]}
    line = _applied_fix_line(r)
    assert "max nesting 3→1" in line
    assert "🛡️ shielded first by `tests/test_m.py`" in line
    assert "[commit abc123]" in line


def test_applied_fix_line_falls_back_to_target_when_no_changed_files():
    r = {"branch": "b", "action": "create_test_stub", "target": "app/m.py"}
    assert "app/m.py" in _applied_fix_line(r)


# --------------------------------------------------------------------------
# _result_sections / render_maintenance_markdown
# --------------------------------------------------------------------------

def test_result_sections_only_non_empty_sections():
    results = [
        {"branch": "a", "action": "harden_security", "applied": True,
         "changed_files": ["app/a.py"]},
        {"branch": "b", "action": "create_test_stub", "rolled_back": True,
         "target": "app/b.py"},
        {"branch": "c", "action": "organize_imports", "applied": False,
         "reason": "blocked by safety gates"},
    ]
    lines = _result_sections(results)
    text = "\n".join(lines)
    assert "## ✅ Applied" in text
    assert "## ↩️ Rolled back (tests failed)" in text
    assert "## ⛔ Blocked / not applicable" in text
    assert "blocked by safety gates" in text


def test_result_sections_empty_when_no_results():
    assert _result_sections([]) == []


def test_render_maintenance_markdown_with_commit_and_objective(tmp_path):
    summary = {
        "mode": "supervised", "verify": True, "commit": True, "committed": 2,
        "applied": 1, "rolled_back": 0, "blocked": 1, "total_executable": 2,
        "results": [
            {"branch": "a", "action": "harden_security", "applied": True,
             "changed_files": ["app/a.py"], "committed": True, "commit_hash": "h1"},
            {"branch": "c", "action": "organize_imports", "applied": False,
             "reason": "no auto-fixable pattern found"},
        ],
    }
    md = render_maintenance_markdown(summary, str(tmp_path), objective="Stabilize")
    assert "Apex Maintenance Report" in md
    assert "_Objective: Stabilize_" in md
    assert "· verified" in md and "· committed" in md
    assert "Commits created: **2**" in md
    assert "no auto-fixable pattern found" in md


def test_render_maintenance_markdown_no_commit_no_objective(tmp_path):
    summary = {"mode": "report", "verify": False, "commit": False,
               "applied": 0, "rolled_back": 0, "blocked": 0,
               "total_executable": 0, "results": []}
    md = render_maintenance_markdown(summary, str(tmp_path))
    assert "Mode: **report**" in md
    assert "Commits created" not in md
    assert "_Objective:" not in md


# --------------------------------------------------------------------------
# anchor-grain test description / stub body  (_concrete_test_description /
# _test_stub_body)
# --------------------------------------------------------------------------

def test_plan_idea_uses_anchor_phrasing_and_stub_body():
    idea = IdeaNode(
        id="i", title="Test: app/mod.py", subject="app/mod.py", operator="test",
        operator_chain=["test"], source_facts=["untested: app/mod.py"],
        anchors=[{"module": "app/mod.py", "symbol": "_scan", "line": 12,
                  "metric": "cyclomatic 18"}],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert "Add tests for" in step.description
    assert "`_scan`" in step.description
    assert "app/mod.py:12" in step.description
    assert "cyclomatic 18" in step.description
    assert step.patch_preview is not None
    body = step.patch_preview["stub_body"]
    assert "import app.mod" in body
    assert "def test__scan_behavior():" in body
    assert step.patch_preview["applied"] is False


def test_plan_idea_smoke_stub_when_no_anchors_with_symbol():
    # An anchor without a symbol is dropped -> module-level fallback (no preview).
    idea = IdeaNode(
        id="i", title="Test: app/mod.py", subject="app/mod.py", operator="test",
        operator_chain=["test"], source_facts=["untested: app/mod.py"],
        anchors=[{"module": "app/mod.py", "line": 4}],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.patch_preview is None
    # Falls back to the module-level template.
    assert "app/mod.py" in step.description


def test_root_action_untested_confluence_routes_to_test_stub():
    idea = IdeaNode(
        id="i", title="Confluence app/hub.py", subject="app/hub.py",
        operator="root", source_facts=["confluence: app/hub.py (untested)"],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "create_test_stub"
    assert step.executable is True


def test_root_action_plain_confluence_is_recommend_only():
    idea = IdeaNode(
        id="i", title="Confluence app/hub.py", subject="app/hub.py",
        operator="root", source_facts=["confluence: app/hub.py"],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "design_task"
    assert step.executable is False


def test_test_stub_body_smoke_path_when_no_anchors():
    from app.engine.idea_action_bridge import _test_stub_body

    node = IdeaNode(id="i", title="t", subject="app/mod.py", operator="test")
    body = _test_stub_body(node, "app/mod.py")
    assert "import app.mod" in body
    assert "def test_mod_smoke():" in body
    assert "recommend-only" in body


def test_test_stub_body_anchor_path_slugifies_symbols():
    from app.engine.idea_action_bridge import _test_stub_body

    node = IdeaNode(id="i", title="t", subject="app/mod.py", operator="test",
                    anchors=[{"symbol": "Foo.bar", "module": "app/mod.py"}])
    body = _test_stub_body(node, "app/mod.py")
    # Non-identifier chars become "_"; underscores preserved.
    assert "def test_foo_bar_behavior():" in body


# --------------------------------------------------------------------------
# dry_run_plan / _step_preview — recommend-only preview (no apply)
# --------------------------------------------------------------------------

def test_dry_run_plan_is_preview_only_and_counts_applicable(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "m.py"
    src.write_text("x = 1\n", encoding="utf-8")
    bridge = IdeaActionBridge()

    applicable = ActionStep(branch_path="ok", title="t", operator="harden",
                            subject="app/m.py", action_type="harden_security",
                            target="app/m.py", executable=True)
    inapplicable = ActionStep(branch_path="no", title="t", operator="harden",
                              subject="app/m.py", action_type="harden_security",
                              target="app/m.py", executable=True)

    def fake_generate(step, root):
        if step.branch_path == "ok":
            return _result([{"path": "app/m.py", "new_content": "x = 2\n"}])
        return None

    monkeypatch.setattr(bridge, "_generate", fake_generate)
    plan = ActionPlan(steps=[applicable, inapplicable])
    out = bridge.dry_run_plan(plan, str(tmp_path))
    assert out["dry_run"] is True
    assert out["total_executable"] == 2
    assert out["applicable"] == 1
    # Preview only — the source file is never written.
    assert src.read_text(encoding="utf-8") == "x = 1\n"
    ok_row = next(r for r in out["results"] if r["branch"] == "ok")
    assert ok_row["applicable"] is True
    assert "app/m.py" in ok_row["diff"]
    no_row = next(r for r in out["results"] if r["branch"] == "no")
    assert no_row["applicable"] is False
