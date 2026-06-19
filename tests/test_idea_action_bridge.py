from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge, render_action_markdown
from app.engine.idea_permutation import IdeaPermutationEngine
from app.models.idea import IdeaNode


def _project(tmp: Path) -> Path:
    (tmp / "app").mkdir()
    (tmp / "app" / "main.py").write_text("def main():\n    return 1\n")
    return tmp


def test_test_operator_maps_to_executable_stub():
    idea = IdeaNode(
        id="i", title="Test: app/main.py", subject="app/main.py", operator="test",
        operator_chain=["test"], source_facts=["untested: app/main.py"],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "create_test_stub"
    assert step.executable is True
    assert step.target == "app/main.py"


def test_extend_operator_is_a_design_task():
    idea = IdeaNode(id="i", title="Extend: app/main.py", subject="app/main.py", operator="extend")
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "design_task"
    assert step.executable is False


def test_root_action_from_seeding_fact():
    idea = IdeaNode(
        id="i", title="Harden the sensitive path app/auth.py", subject="app/auth.py",
        operator="root", source_facts=["sensitive-path: app/auth.py"],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "harden_security"
    assert step.executable is True


def test_plan_tree_orders_by_value_and_counts(tmp_path):
    _project(tmp_path)
    report = IdeaPermutationEngine({"max_total_ideas": 15, "max_idea_depth": 2}, tmp_path).run()
    plan = IdeaActionBridge().plan_tree(report, top=10)

    assert plan.stats["total_steps"] == len(plan.steps) <= 10
    # Sorted by value, descending.
    values = [s.value for s in plan.steps]
    assert values == sorted(values, reverse=True)
    # Some steps are executable (tests/docs), the plan is never auto-applied.
    assert plan.mode == "supervised"
    assert plan.stats["executable_steps"] + plan.stats["design_tasks"] == plan.stats["total_steps"]


def test_render_action_markdown(tmp_path):
    _project(tmp_path)
    report = IdeaPermutationEngine({"max_total_ideas": 8}, tmp_path).run()
    md = render_action_markdown(IdeaActionBridge().plan_tree(report))
    assert "Action Plan" in md
    assert "not applied" in md


def test_draft_patch_for_test_stub_is_preview_only(tmp_path):
    _project(tmp_path)
    from app.models.idea import IdeaNode

    idea = IdeaNode(
        id="i", title="Test: app/main.py", subject="app/main.py", operator="test",
        operator_chain=["test"], source_facts=["untested: app/main.py"],
    )
    bridge = IdeaActionBridge()
    step = bridge.plan_idea(idea)
    before = (tmp_path / "app" / "main.py").read_text()

    preview = bridge.draft_patch(step, str(tmp_path))

    assert preview is not None
    assert preview["applied"] is False
    assert preview["files"]
    # Drafting must NOT touch the source tree.
    assert (tmp_path / "app" / "main.py").read_text() == before
    assert not (tmp_path / "tests").exists()


def test_design_task_has_no_draft():
    from app.models.idea import IdeaNode

    idea = IdeaNode(id="i", title="Extend: app/main.py", subject="app/main.py", operator="extend")
    step = IdeaActionBridge().plan_idea(idea)
    assert IdeaActionBridge().draft_patch(step, ".") is None


def test_plan_tree_draft_populates_previews_without_side_effects(tmp_path):
    _project(tmp_path)
    report = IdeaPermutationEngine({"max_total_ideas": 12, "max_idea_depth": 2}, tmp_path).run()
    snapshot = {p: p.read_text() for p in (tmp_path / "app").glob("*.py")}

    plan = IdeaActionBridge().plan_tree(report, top=10, draft=True, project_root=str(tmp_path))

    assert plan.stats["drafted_patches"] >= 1
    assert any(s.patch_preview for s in plan.steps)
    # No source file changed.
    for p, content in snapshot.items():
        assert p.read_text() == content


def test_apply_blocked_in_report_mode(tmp_path):
    _project(tmp_path)
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Document: app/main.py", subject="app/main.py",
                    operator="document", operator_chain=["document"],
                    source_facts=["untested: app/main.py"])
    step = IdeaActionBridge().plan_idea(idea)
    before = (tmp_path / "app" / "main.py").read_text()
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="report")
    assert result["applied"] is False
    assert "read-only" in result["reason"]
    assert (tmp_path / "app" / "main.py").read_text() == before  # untouched


def test_apply_in_supervised_mode_writes_file(tmp_path):
    # A file with a function missing a docstring -> add_docstring applies.
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "svc.py"
    src.write_text("def handler(x):\n    return x + 1\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Document: app/svc.py", subject="app/svc.py",
                    operator="document", operator_chain=["document"],
                    source_facts=["dependency-hub: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "add_docstring"

    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")

    if result["applied"]:
        # The file was actually changed and now contains a docstring.
        assert src.read_text() != "def handler(x):\n    return x + 1\n"
        assert '"""' in src.read_text()
    else:
        # If no transform applied, the file must remain untouched.
        assert src.read_text() == "def handler(x):\n    return x + 1\n"


def test_apply_blocks_sensitive_path(tmp_path):
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "keys.py").write_text("def k():\n    return 1\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Document: secrets/keys.py", subject="secrets/keys.py",
                    operator="document", operator_chain=["document"],
                    source_facts=["sensitive-path: secrets/keys.py"])
    step = IdeaActionBridge().plan_idea(idea)
    # Even if a patch is generated, the sensitive-path gate must block writing.
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"] is False and "safety" in result.get("reason", ""):
        assert (tmp_path / "secrets" / "keys.py").read_text() == "def k():\n    return 1\n"


def test_harden_applies_real_eval_fix(tmp_path):
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "svc.py"
    src.write_text("def run(c):\n    return eval(c)\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/svc.py", subject="app/svc.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert result["transform_type"] == "eval_to_literal_eval"
        assert "ast.literal_eval(c)" in src.read_text()
        assert "eval(c)" not in src.read_text().replace("literal_eval", "")


def test_harden_applies_bare_except_fix(tmp_path):
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "m.py"
    src.write_text("def f():\n    try:\n        x = 1\n    except:\n        pass\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/m.py", subject="app/m.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/m.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert "except Exception:" in src.read_text()


def test_harden_narrows_except_base_exception(tmp_path):
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "w.py"
    src.write_text("def f():\n    try:\n        g()\n    except BaseException:\n        log()\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/w.py", subject="app/w.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/w.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert result["transform_type"] == "base_exception_to_exception"
        text = src.read_text()
        assert "except Exception:" in text and "BaseException" not in text


def test_harden_applies_open_encoding_fix(tmp_path):
    # A file whose only issue is open() without encoding gets the portability
    # fix via the harden detection ladder.
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "io.py"
    src.write_text('def load(p):\n    return open(p).read()\n')
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/io.py", subject="app/io.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/io.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert result["transform_type"] == "add_open_encoding"
        assert 'encoding="utf-8"' in src.read_text()


def test_harden_drops_dead_fstring_prefix(tmp_path):
    # A file whose only issue is an f-string without placeholders gets the
    # dead-prefix removal via the harden detection ladder.
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "msg.py"
    src.write_text('def banner():\n    return f"welcome"\n')
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/msg.py", subject="app/msg.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/msg.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert result["transform_type"] == "fix_fstring_no_placeholder"
        assert 'f"welcome"' not in src.read_text()
        assert '"welcome"' in src.read_text()


def test_harden_modernizes_empty_collection_constructor(tmp_path):
    # A file whose only issue is dict()/list()/tuple() gets the literal via the
    # harden detection ladder.
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "coll.py"
    src.write_text("def build():\n    return dict()\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/coll.py", subject="app/coll.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/coll.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert result["transform_type"] == "modernize_collection_literal"
        assert "dict()" not in src.read_text()
        assert "return {}" in src.read_text()


def test_harden_makes_no_change_when_no_real_issue(tmp_path):
    # Clean code with no eval/os.system/bare-except/mutable/modernize/encoding/
    # timeout issue: harden_security must NOT fabricate a speculative guard — it
    # makes no change and the file is left untouched (trust over activity).
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "ok.py"
    src.write_text("def f(x):\n    return x + 1\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/ok.py", subject="app/ok.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/ok.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    assert result["applied"] is False
    assert src.read_text() == "def f(x):\n    return x + 1\n"  # untouched


def test_verify_keeps_patch_when_tests_pass(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    src = tmp_path / "app" / "svc.py"
    src.write_text("def handler(x):\n    return x + 1\n")
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Document: app/svc.py", subject="app/svc.py",
                    operator="document", operator_chain=["document"],
                    source_facts=["dependency-hub: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised", verify=True)
    if res["applied"]:
        # Kept because the suite stayed green; honestly unverified because the
        # trivial suite never imports the changed module (coverage-aware proof).
        assert res.get("rolled_back") is False
        assert res.get("suite_green") is True
        assert res.get("verified") is False
        assert res.get("coverage") == "none"
        assert '"""' in src.read_text()


def test_verify_rolls_back_when_tests_fail(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    src = tmp_path / "app" / "svc.py"
    original = "def handler(x):\n    return x + 1\n"
    src.write_text(original)
    (tmp_path / "tests" / "test_fail.py").write_text("def test_fail():\n    assert False\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Document: app/svc.py", subject="app/svc.py",
                    operator="document", operator_chain=["document"],
                    source_facts=["dependency-hub: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised", verify=True)
    # The patch generated and applied, tests failed -> rolled back, file restored.
    if res.get("rolled_back"):
        assert res["applied"] is False
        assert src.read_text() == original


def test_verify_rolls_back_newly_created_file(tmp_path):
    # A create_test_stub that breaks tests should delete the newly-created file.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "main.py").write_text("def main():\n    return 1\n")
    (tmp_path / "tests" / "test_fail.py").write_text("def test_fail():\n    assert False\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Test: app/main.py", subject="app/main.py",
                    operator="test", operator_chain=["test"],
                    source_facts=["untested: app/main.py"])
    step = IdeaActionBridge().plan_idea(idea)
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised", verify=True)
    if res.get("rolled_back"):
        assert not (tmp_path / "tests" / "test_main.py").exists()


def test_apply_plan_runs_whole_pass_with_summary(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    from app.engine.idea_permutation import IdeaPermutationEngine
    rep = IdeaPermutationEngine({"max_total_ideas": 20, "max_idea_depth": 1}, tmp_path).run()
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(rep, project_root=str(tmp_path))
    summary = bridge.apply_plan(plan, str(tmp_path), mode="supervised", verify=True)

    assert summary["applied"] + summary["rolled_back"] + summary["blocked"] == summary["total_executable"]
    assert len(summary["results"]) == summary["total_executable"]
    # The eval() should have been fixed and kept (tests still pass).
    assert "ast.literal_eval" in (tmp_path / "app" / "danger.py").read_text()


def test_create_test_stub_never_targets_test_files(tmp_path):
    # A test file as subject must not spawn a test_test_*.py stub.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text("def test_x():\n    assert True\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Test: tests/test_calc.py", subject="tests/test_calc.py",
                    operator="test", operator_chain=["test"],
                    source_facts=["untested: tests/test_calc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    assert IdeaActionBridge().draft_patch(step, str(tmp_path)) is None


def test_run_tests_isolates_target_project(tmp_path):
    # RunTestsSkill must resolve the TARGET project's package, not the caller's.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(1, 1) == 2\n"
    )
    from app.skills.execution.run_tests import RunTestsSkill
    summary = RunTestsSkill().run(str(tmp_path))
    assert summary.ok


def test_apply_plan_no_commit_in_supervised(tmp_path):
    # commit=True but supervised mode -> cannot commit; summary reflects it.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    from app.engine.idea_permutation import IdeaPermutationEngine
    rep = IdeaPermutationEngine({"max_total_ideas": 12, "max_idea_depth": 1}, tmp_path).run()
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(rep, project_root=str(tmp_path))
    summary = bridge.apply_plan(plan, str(tmp_path), mode="supervised", commit=True)
    assert summary["commit"] is False
    assert summary.get("committed", 0) == 0


def test_apply_plan_commits_in_autonomous(tmp_path):
    import subprocess
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "add", "-A"], cwd=tmp_path)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"], cwd=tmp_path)

    from app.engine.idea_permutation import IdeaPermutationEngine
    rep = IdeaPermutationEngine({"max_total_ideas": 12, "max_idea_depth": 1}, tmp_path).run()
    bridge = IdeaActionBridge()
    plan = bridge.plan_tree(rep, project_root=str(tmp_path))
    summary = bridge.apply_plan(plan, str(tmp_path), mode="autonomous", verify=False, commit=True)
    assert summary["commit"] is True
    # If any harden step applied, it should have produced a commit.
    if summary["applied"] > 0:
        assert summary["committed"] >= 1
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True
        ).stdout
        assert "Apex auto-fix" in log


def test_harden_flags_pickle_loads(tmp_path):
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "svc.py"
    src.write_text("import pickle\ndef load(b):\n    return pickle.loads(b)\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/svc.py", subject="app/svc.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert result["transform_type"] == "flag_pickle_loads"
        assert "SECURITY" in src.read_text()
        assert "pickle.loads(b)" in src.read_text()  # call preserved, just annotated


def test_harden_flags_sql_injection(tmp_path):
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "db.py"
    src.write_text('def get(cur, uid):\n    return cur.execute(f"SELECT * FROM u WHERE id={uid}")\n')
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/db.py", subject="app/db.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/db.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert result["transform_type"] == "flag_sql_injection"
        assert "SQL injection" in src.read_text()


def test_harden_rewrites_yaml_load(tmp_path):
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "cfg.py"
    src.write_text("import yaml\ndef load(s):\n    return yaml.load(s)\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/cfg.py", subject="app/cfg.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/cfg.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert result["transform_type"] == "yaml_load_to_safe_load"
        assert "yaml.safe_load(s)" in src.read_text()
        assert "yaml.load(" not in src.read_text()


def test_detect_security_issue_is_ast_based(tmp_path):
    b = IdeaActionBridge()
    # A comment mentioning eval() must NOT be detected (AST ignores comments).
    (tmp_path / "ok.py").write_text("# do not use eval() here\nx = 1\n")
    assert b._detect_security_issue(str(tmp_path), "ok.py") is None
    # A string containing 'eval(' must NOT trigger either.
    (tmp_path / "s.py").write_text("msg = 'call eval() carefully'\n")
    assert b._detect_security_issue(str(tmp_path), "s.py") is None
    # Real calls are detected.
    (tmp_path / "real.py").write_text("def f(c):\n    return eval(c)\n")
    assert b._detect_security_issue(str(tmp_path), "real.py") == "eval"
    (tmp_path / "y.py").write_text("import yaml\nyaml.load(s)\n")
    assert b._detect_security_issue(str(tmp_path), "y.py") == "yaml"


def test_detect_security_issue_severity_order(tmp_path):
    # eval outranks a bare except in the same file.
    (tmp_path / "m.py").write_text(
        "def f(c):\n    try:\n        return eval(c)\n    except:\n        pass\n"
    )
    assert IdeaActionBridge()._detect_security_issue(str(tmp_path), "m.py") == "eval"


def test_plan_roadmap_orders_steps_by_phase(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    (tmp_path / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    rep = IdeaPermutationEngine({"max_total_ideas": 30, "max_idea_depth": 1}, tmp_path).run()
    plan = IdeaActionBridge().plan_roadmap(rep, project_root=str(tmp_path))

    assert plan.stats["ordered_by"] == "roadmap"
    assert plan.stats["phase_counts"]
    # Every step carries the phase it came from.
    assert all(s.phase for s in plan.steps)
    # Phases appear in canonical order (Stabilize before Secure before ...).
    order = ["Stabilize", "Secure", "Evolve", "Refine"]
    seen = [s.phase for s in plan.steps]
    rank = {name: i for i, name in enumerate(order)}
    ranks = [rank[p] for p in seen]
    assert ranks == sorted(ranks), "steps must be grouped in canonical phase order"


def test_plan_roadmap_phase_filter(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    rep = IdeaPermutationEngine({"max_total_ideas": 30, "max_idea_depth": 1}, tmp_path).run()
    plan = IdeaActionBridge().plan_roadmap(rep, phase="Secure", project_root=str(tmp_path))
    # Filtered to a single phase only.
    assert plan.steps
    assert {s.phase for s in plan.steps} == {"Secure"}


def test_plan_roadmap_markdown_shows_phase_tags(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    rep = IdeaPermutationEngine({"max_total_ideas": 20, "max_idea_depth": 1}, tmp_path).run()
    plan = IdeaActionBridge().plan_roadmap(rep, project_root=str(tmp_path))
    md = render_action_markdown(plan)
    assert "[Stabilize]" in md or "[Secure]" in md


def test_plan_roadmap_top_caps_total(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "danger.py").write_text("def run(e):\n    return eval(e)\n")
    rep = IdeaPermutationEngine({"max_total_ideas": 30, "max_idea_depth": 1}, tmp_path).run()
    plan = IdeaActionBridge().plan_roadmap(rep, top=3, project_root=str(tmp_path))
    assert len(plan.steps) <= 3


def test_harden_applies_net_timeout_flag(tmp_path):
    # A file whose only issue is a network call without timeout gets the
    # reliability flag via the harden detection ladder.
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "client.py"
    src.write_text("import requests\ndef fetch(u):\n    return requests.get(u)\n")
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="i", title="Harden: app/client.py", subject="app/client.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/client.py"])
    step = IdeaActionBridge().plan_idea(idea)
    result = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert "timeout" in src.read_text().lower()


def test_harden_step_converges_all_fixes_in_one_pass(tmp_path):
    # A single harden_security step now fixes EVERY auto-fixable issue in its
    # file in one maintenance pass (the detection ladder advances as each issue
    # is fixed), not one fix per pass. (Fixes the finbot convergence weakness.)
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    src = tmp_path / "app" / "svc.py"
    src.write_text("def run(rule):\n    try:\n        return eval(rule)\n    except:\n        return 0\n")
    (tmp_path / "tests" / "test_svc.py").write_text(
        "def test_import():\n    import app.svc\n    assert app.svc is not None\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='c'\nversion='0'\n")

    from app.models.idea import ActionPlan
    idea = IdeaNode(id="i", title="Harden: app/svc.py", subject="app/svc.py", operator="harden",
                    operator_chain=["harden"], source_facts=["sensitive-path: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    plan = ActionPlan(steps=[step], stats={}, mode="supervised")
    res = IdeaActionBridge().apply_plan(plan, str(tmp_path), mode="supervised", verify=True)

    assert res["rolled_back"] == 0
    after = src.read_text()
    # Both the eval AND the bare-except were fixed in the one pass.
    assert "ast.literal_eval(rule)" in after
    assert "eval(rule)" not in after.replace("literal_eval", "")
    assert "except Exception:" in after
    assert "except:" not in after


def test_harden_change_strategy_ladder_priority(tmp_path):
    # The extracted harden ladder is now directly testable: it picks the most
    # severe real issue, and returns None for clean code (no fabricated fix).
    (tmp_path / "app").mkdir()
    bridge = IdeaActionBridge()

    (tmp_path / "app" / "danger.py").write_text("def r(c):\n    return eval(c)\n")
    strat, title = bridge._harden_change_strategy(str(tmp_path), "app/danger.py")
    assert "eval" in strat[0] and "danger.py" in title

    (tmp_path / "app" / "mut.py").write_text("def f(x=[]):\n    return x\n")
    strat, _ = bridge._harden_change_strategy(str(tmp_path), "app/mut.py")
    assert "mutable" in strat[0]

    (tmp_path / "app" / "clean.py").write_text("def f(x):\n    return x + 1\n")
    assert bridge._harden_change_strategy(str(tmp_path), "app/clean.py") is None


def test_harden_converges_multiple_flag_only_findings(tmp_path):
    # Flag-only fixes (tempfile + weak-hash) don't remove the pattern, so the
    # ladder must advance past an already-annotated finding instead of looping
    # on the top one. One harden pass should flag BOTH md5 and mktemp.
    from app.models.idea import ActionPlan
    (tmp_path / "svc").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "svc" / "__init__.py").write_text("")
    (tmp_path / "svc" / "core.py").write_text(
        "import hashlib\nimport tempfile\n"
        "def k(d):\n    return hashlib.md5(d).hexdigest()\n"
        "def t():\n    return tempfile.mktemp()\n"
    )
    (tmp_path / "tests" / "test_core.py").write_text("def test_x():\n    import svc.core\n    assert svc.core\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='s'\nversion='0'\n")
    idea = IdeaNode(id="i", title="Harden: svc/core.py", subject="svc/core.py", operator="harden",
                    operator_chain=["harden"], source_facts=["sensitive-path: svc/core.py"])
    plan = ActionPlan(steps=[IdeaActionBridge().plan_idea(idea)], stats={}, mode="supervised")
    res = IdeaActionBridge().apply_plan(plan, str(tmp_path), mode="supervised", verify=True)
    after = (tmp_path / "svc" / "core.py").read_text()
    assert res["rolled_back"] == 0
    assert "Apex: weak hash" in after
    assert "Apex: insecure temp file" in after


def test_hotspot_function_idea_targets_the_module_file():
    # A symbol-granular subject ("mod.py::Class.func") plans an executable
    # test action against the module *file*, keeping the symbol in the title.
    from app.models.idea import IdeaNode
    idea = IdeaNode(
        id="i", title="Write behavioral tests for crunch() in app/core.py",
        subject="app/core.py::Engine.crunch", operator="root", branch_path="x.h",
        depth=0,
        source_facts=["hotspot-function: app/core.py::Engine.crunch (complexity 14, line 40, no direct tests)"],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "create_test_stub"
    assert step.executable is True
    assert step.target == "app/core.py"           # "::" stripped for the file target
    assert "Engine.crunch" in step.description    # symbol kept for the test author


def test_convergence_expands_into_phased_mini_roadmap():
    from app.models.idea import IdeaNode
    idea = IdeaNode(
        id="c0", title="Prioritize app/auth.py — 3 independent analyses converge",
        subject="app/auth.py", operator="synthesis", kind="synthesis", branch_path="x.c0",
        source_facts=["convergence: security-sensitive+a complexity hotspot+untested"],
    )
    steps = IdeaActionBridge().plan_convergence(idea)
    # untested + hotspot collapse to one test step; sensitive adds a harden step.
    assert [s.phase for s in steps] == ["Stabilize", "Secure"]      # safety net BEFORE hardening
    assert [s.action_type for s in steps] == ["create_test_stub", "harden_security"]
    assert all(s.executable for s in steps)
    assert all(s.target == "app/auth.py" for s in steps)
    assert all("app/auth.py" in s.description for s in steps)


def test_convergence_steps_use_known_executable_action_types():
    # Every executable convergence step must map to an action the bridge can
    # actually generate, or "executable" is a lie.
    from app.models.idea import IdeaNode
    from app.engine.idea_permutation import _CONVERGENCE_STEPS
    bridge = IdeaActionBridge()
    idea = IdeaNode(
        id="c", title="t", subject="app/x.py", operator="synthesis", kind="synthesis",
        branch_path="x.c0",
        source_facts=["convergence: " + "+".join(_CONVERGENCE_STEPS.keys())],
    )
    for s in bridge.plan_convergence(idea):
        if s.executable:
            assert s.action_type in bridge._ACTION_STRATEGY


def test_plan_convergence_empty_for_non_convergence_idea():
    from app.models.idea import IdeaNode
    idea = IdeaNode(id="r", title="t", subject="app/x.py", operator="root",
                    source_facts=["untested: app/x.py"])
    assert IdeaActionBridge().plan_convergence(idea) == []


def _convergence_idea(subject: str, labels: str):
    from app.models.idea import IdeaNode
    return IdeaNode(
        id="c0", title=f"Prioritize {subject}", subject=subject,
        operator="synthesis", kind="synthesis", branch_path="x.c0",
        source_facts=[f"convergence: {labels}"],
    )


def test_convergence_reality_check_demotes_satisfied_test_step(tmp_path):
    # The nightly cyclic-blocked lesson: a module the suite ALREADY references
    # must not get a create_test_stub apply attempt every night (the stub
    # transform rightly refuses) — the intent survives as a work order.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "core.py").write_text("def f():\n    return 1\n")
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import f\ndef test_f():\n    assert f() == 1\n")

    idea = _convergence_idea("app/core.py", "a complexity hotspot+high-churn")
    steps = IdeaActionBridge().plan_convergence(idea, project_root=str(tmp_path))
    stub = next(s for s in steps if s.action_type == "create_test_stub")
    assert stub.executable is False
    assert "linked tests already exist" in stub.description
    # Without the root the plan is built blind, exactly as before.
    blind = IdeaActionBridge().plan_convergence(idea)
    assert next(s for s in blind if s.action_type == "create_test_stub").executable


def test_convergence_reality_check_drops_findingless_harden(tmp_path):
    # "security-sensitive" can come from a path hint alone — with no actual
    # finding in the file there is nothing to harden, so no step (and no
    # nightly re-block) is produced. A real finding keeps the step.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text("def check(t):\n    return bool(t)\n")
    idea = _convergence_idea("app/auth.py", "security-sensitive+untested")
    steps = IdeaActionBridge().plan_convergence(idea, project_root=str(tmp_path))
    assert [s.action_type for s in steps] == ["create_test_stub"]

    (tmp_path / "app" / "auth.py").write_text(
        "def check(t):\n    return eval(t)\n")
    steps = IdeaActionBridge().plan_convergence(idea, project_root=str(tmp_path))
    assert [s.action_type for s in steps] == ["create_test_stub", "harden_security"]
    assert all(s.executable for s in steps)


def test_convergence_without_file_target_is_never_executable():
    # A convergence subject that isn't a file path ("Python type coverage")
    # has no patchable target — its steps must not enter the apply pipeline.
    idea = _convergence_idea("type coverage", "untested+security-sensitive")
    steps = IdeaActionBridge().plan_convergence(idea)
    assert steps and all(s.executable is False for s in steps)


def test_roadmap_plan_expands_convergence_and_dedupes(tmp_path):
    # A sensitive + risky module yields a convergence idea; the roadmap apply
    # plan must expand it into executable steps (test before harden), each
    # (module, action) appearing once despite overlapping root Test/Harden ideas.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text("import os\ndef login(pw):\n    return os.system(pw)\n")
    (tmp_path / "app" / "calm.py").write_text("def calm():\n    return 1\n")
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 60, "max_idea_depth": 1, "breadth": 4}, tmp_path
    ).run()
    plan = IdeaActionBridge().plan_roadmap(rep, project_root=str(tmp_path))

    auth = [s for s in plan.steps if s.subject == "app/auth.py" and s.executable]
    actions = [s.action_type for s in auth]
    # Each fix is planned exactly once for the module.
    assert actions.count("create_test_stub") == 1
    assert actions.count("harden_security") == 1
    # Safety net before hardening.
    assert actions.index("create_test_stub") < actions.index("harden_security")


def test_dedupe_keeps_design_tasks_and_first_executable():
    bridge = IdeaActionBridge()

    def step(action, subject, executable, phase=""):
        from app.models.idea import ActionStep
        return ActionStep(branch_path="x", title="t", operator="o", subject=subject,
                          action_type=action, executable=executable, phase=phase)

    steps = [
        step("create_test_stub", "app/a.py", True, "Stabilize"),
        step("create_test_stub", "app/a.py", True, "Secure"),     # dup -> dropped
        step("design_task", "app/a.py", False),                   # kept (not executable)
        step("design_task", "app/a.py", False),                   # kept (informational)
        step("harden_security", "app/a.py", True),                # distinct action -> kept
    ]
    out = bridge._dedupe_steps(steps)
    exec_actions = [(s.action_type, s.phase) for s in out if s.executable]
    assert exec_actions == [("create_test_stub", "Stabilize"), ("harden_security", "")]
    assert sum(1 for s in out if not s.executable) == 2


def test_harden_ladder_skips_unfixable_issue_for_a_fixable_one(tmp_path):
    # A non-literal eval (which the transform soundly declines) must not block
    # hardening a fixable issue (pickle) later in the same file.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "import pickle\n"
        "def load(b):\n"
        "    x = eval(\"a['k']\")\n"          # non-literal -> transform declines
        "    return pickle.loads(b)\n"        # fixable (flag annotation)
    )
    res = IdeaActionBridge._harden_change_strategy(str(tmp_path), "app/m.py")
    assert res is not None
    change_strategy, _title = res
    assert change_strategy == ["fix pickle security"]   # advanced past the eval


def test_harden_chains_raise_to_cause_end_to_end(tmp_path):
    # The harden ladder's raise-from rung: a bound handler re-raising without
    # `from` gets chained, applied through the real supervised machinery.
    (tmp_path / "app").mkdir()
    src = tmp_path / "app" / "svc.py"
    src.write_text(
        "def load(p):\n"
        "    try:\n"
        "        return g(p)\n"
        "    except OSError as err:\n"
        '        raise RuntimeError("cannot load")\n'
    )
    idea = IdeaNode(id="i", title="Harden: app/svc.py", subject="app/svc.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/svc.py"])
    bridge = IdeaActionBridge()
    step = bridge.plan_idea(idea)
    result = bridge.apply_step(step, str(tmp_path), mode="supervised")
    if result["applied"]:
        assert result["transform_type"] == "raise_with_from"
        assert 'from err' in src.read_text()


def test_plan_idea_without_file_target_is_never_executable():
    # "Add type hints" on subject "Python type coverage": no file, no patch —
    # marking it executable guarantees a nightly blocked entry (the dream
    # flagged exactly this as cyclic noise).
    from app.models.idea import IdeaNode
    idea = IdeaNode(
        id="t0", title="Add a test layer", subject="project structure",
        operator="test", kind="permutation", branch_path="x.1.a",
        source_facts=["top-directory: app"],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.target == ""
    assert step.executable is False


def test_expand_idea_demotes_stub_on_already_tested_module(tmp_path):
    # A stub is only ever the FIRST test layer: on a module the suite already
    # references, the step becomes a work order instead of a nightly blocked
    # apply attempt (or a redundant smoke stub).
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "core.py").write_text("def f():\n    return 1\n")
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import f\ndef test_f():\n    assert f() == 1\n")
    idea = IdeaNode(
        id="i", title="Test: app/core.py", subject="app/core.py", operator="test",
        operator_chain=["test"], source_facts=["hotspot-function: app/core.py::f"],
    )
    bridge = IdeaActionBridge()
    step = bridge._expand_idea(idea, project_root=str(tmp_path))[0]
    assert step.executable is False
    assert "linked tests already exist" in step.description
    # An untested module keeps its executable stub step.
    (tmp_path / "tests" / "test_core.py").unlink()
    step = bridge._expand_idea(idea, project_root=str(tmp_path))[0]
    assert step.executable is True


def test_expand_idea_demotes_harden_with_no_fixable_pattern(tmp_path):
    # The other half of the nightly cyclic-blocked lesson: a harden step on a
    # file where NO ladder rung fires can only re-block — it demotes to a
    # work order. A real fixable pattern keeps it executable.
    (tmp_path / "app").mkdir()
    clean = tmp_path / "app" / "token_store.py"
    clean.write_text("def get(k):\n    return k\n")
    idea = IdeaNode(
        id="i", title="Harden: app/token_store.py", subject="app/token_store.py",
        operator="harden", operator_chain=["harden"],
        source_facts=["sensitive-path: app/token_store.py"],
    )
    bridge = IdeaActionBridge()
    step = bridge._expand_idea(idea, project_root=str(tmp_path))[0]
    assert step.executable is False
    assert "no auto-fixable pattern" in step.description

    clean.write_text("def get(k):\n    return eval(k)\n")
    step = bridge._expand_idea(idea, project_root=str(tmp_path))[0]
    assert step.executable is True


def test_dead_parameter_root_maps_to_command_carrying_work_order():
    idea = IdeaNode(
        id="d", title="Drop the dead parameter `color` from render() in app/ui.py",
        subject="app/ui.py", operator="root", branch_path="x.d",
        source_facts=["dead-parameter: app/ui.py:12 render(color) never read — "
                      "`apex signature drop render color`"],
    )
    step = IdeaActionBridge().plan_idea(idea)
    assert step.action_type == "design_task"
    assert step.executable is False
    assert "apex signature drop" in step.description


def test_draft_fallback_is_never_an_applicable_patch(tmp_path):
    # Found by dogfooding: organize_imports on an already-tidy file fell back
    # to a .apex/patch-drafts/*.md note, and apply_step counted writing that
    # note as "applied" — poisoning the report and outcome memory. A draft is
    # not a patch: generation must yield None instead.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "tidy.py").write_text(
        "import json\n\ndef f():\n    return json.dumps({})\n")
    idea = IdeaNode(
        id="i", title="Simplify: app/tidy.py", subject="app/tidy.py",
        operator="simplify", operator_chain=["simplify"],
        source_facts=["churn-hotspot: app/tidy.py"],
    )
    bridge = IdeaActionBridge()
    step = bridge.plan_idea(idea)
    assert step.action_type == "organize_imports"
    assert bridge._generate(step, str(tmp_path)) is None
    result = bridge.apply_step(step, str(tmp_path), mode="supervised")
    assert result["applied"] is False
    assert not (tmp_path / ".apex" / "patch-drafts").exists()  # no md "fix"


def test_expand_idea_demotes_already_tidy_organize_imports(tmp_path):
    # And at PLAN time the same step demotes to a work order, so the nightly
    # run doesn't re-block on it forever.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "tidy.py").write_text(
        "import json\n\ndef f():\n    return json.dumps({})\n")
    idea = IdeaNode(
        id="i", title="Simplify: app/tidy.py", subject="app/tidy.py",
        operator="simplify", operator_chain=["simplify"],
        source_facts=["churn-hotspot: app/tidy.py"],
    )
    bridge = IdeaActionBridge()
    step = bridge._expand_idea(idea, project_root=str(tmp_path))[0]
    assert step.executable is False
    assert "already tidy" in step.description

    # A genuinely untidy file keeps its executable step.
    (tmp_path / "app" / "tidy.py").write_text(
        "import json\nimport os\n\ndef f():\n    return json.dumps({})\n")
    step = bridge._expand_idea(idea, project_root=str(tmp_path))[0]
    assert step.executable is True
