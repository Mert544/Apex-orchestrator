from __future__ import annotations

from pathlib import Path

from app.models.idea import ActionPlan, ActionStep, IdeaNode, IdeaTreeReport

# Terminal-operator -> (action_type, description template, executable).
# "executable" means a deterministic transform/agent already exists to draft it;
# the others are higher-level design tasks surfaced for a human/agent to take on.
_OPERATOR_ACTIONS: dict[str, tuple[str, str, bool]] = {
    "test": ("create_test_stub", "Create a test stub covering {s}", True),
    "document": ("add_docstring", "Add docstrings to undocumented symbols in {s}", True),
    "harden": ("harden_security", "Add guard clauses and fix risky patterns in {s}", True),
    "simplify": ("organize_imports", "Tidy imports and reduce complexity in {s}", True),
    "extend": ("design_task", "Design and implement a new capability in {s}", False),
    "integrate": ("design_task", "Connect {s} to a related subsystem", False),
    "generalize": ("design_task", "Parameterize {s} for reuse", False),
    "observe": ("design_task", "Add metrics and logging around {s}", False),
}

# Root ideas have no operator yet; map their seeding fact to a first action.
_FACT_ACTIONS: dict[str, tuple[str, str, bool]] = {
    "untested": ("create_test_stub", "Create a first test stub for {s}", True),
    "critical-untested": ("create_test_stub", "Create a safety-net test for {s}", True),
    "sensitive-path": ("harden_security", "Harden the sensitive path {s}", True),
    "config": ("design_task", "Make configuration {s} environment-aware", False),
    "entrypoint": ("design_task", "Grow capability behind entrypoint {s}", False),
    "dependency-hub": ("design_task", "Plan an evolution of central module {s}", False),
    "symbol-hub": ("design_task", "Generalize the symbol-rich module {s}", False),
    "missing-ci": ("add_ci", "Add a CI workflow that runs the test suite", False),
}


class IdeaActionBridge:
    """Turn development ideas into a concrete, supervised action plan.

    Maps each idea's terminal development operator (or, for roots, its seeding
    fact) to a known action type, marking those a deterministic transform can
    already draft as ``executable``. This is the guarded link between the
    generative idea tree and the existing semantic-patch / agent executors — it
    proposes, it never applies.
    """

    def plan_idea(self, idea: IdeaNode) -> ActionStep:
        if idea.operator == "root":
            action_type, desc_tmpl, executable = self._root_action(idea)
        else:
            action_type, desc_tmpl, executable = _OPERATOR_ACTIONS.get(
                idea.operator, ("design_task", "Develop {s}", False)
            )
        return ActionStep(
            branch_path=idea.branch_path,
            title=idea.title,
            operator=idea.operator,
            subject=idea.subject,
            action_type=action_type,
            target=idea.subject if "/" in idea.subject or idea.subject.endswith(".py") else "",
            description=desc_tmpl.format(s=idea.subject),
            executable=executable,
            value=idea.value,
            source_facts=idea.source_facts,
        )

    @staticmethod
    def _root_action(idea: IdeaNode) -> tuple[str, str, bool]:
        label = idea.source_facts[0].split(":")[0].strip() if idea.source_facts else ""
        return _FACT_ACTIONS.get(label, ("design_task", "Develop {s}", False))

    # action_type -> change_strategy hint that steers EditStrategy to the
    # matching deterministic transform.
    _ACTION_STRATEGY = {
        "add_docstring": ["add docstring document"],
        "organize_imports": ["organize imports cleanup unused"],
        "harden_security": ["add guard clause input validation security"],
        "create_test_stub": ["test coverage"],
    }

    @staticmethod
    def _detect_security_issue(project_root: str, rel_path: str) -> str | None:
        """Return the concrete security pattern present in a file, if any, so
        harden_security can pick the real AST fix (eval / os.system / bare
        except) instead of a generic guard clause."""
        try:
            text = (Path(project_root) / rel_path).read_text(encoding="utf-8")
        except OSError:
            return None
        # Order matters: most dangerous first.
        if "eval(" in text:
            return "eval"
        if "os.system(" in text:
            return "os.system"
        if "except:" in text:
            return "bare except"
        return None

    def _generate(self, step: ActionStep, project_root: str):
        """Run the semantic generator for an executable step. Returns the
        SemanticPatchResult (proposed only) or None."""
        if not step.executable or step.action_type not in self._ACTION_STRATEGY:
            return None
        if not step.target or not step.target.endswith(".py"):
            return None
        if step.action_type == "create_test_stub":
            target_files = [f"tests/test_{Path(step.target).stem}.py"]
        else:
            target_files = [step.target]

        # harden_security: prefer a concrete AST security fix when the file has
        # a known dangerous pattern; fall back to the generic guard-clause hint.
        change_strategy = self._ACTION_STRATEGY[step.action_type]
        title = step.description
        if step.action_type == "harden_security":
            issue = self._detect_security_issue(project_root, step.target)
            if issue:
                change_strategy = [f"fix {issue} security"]
                title = f"Fix {issue} in {step.target}"

        from app.execution.semantic_patch_generator import SemanticPatchGenerator

        patch_plan = {
            "target_files": target_files,
            "title": title,
            "task_id": f"idea-{step.branch_path}",
            "branch": step.branch_path,
            "change_strategy": change_strategy,
        }
        try:
            result = SemanticPatchGenerator().generate(project_root, patch_plan)
        except Exception:
            return None
        return result if result.patch_requests else None

    def draft_patch(self, step: ActionStep, project_root: str) -> dict | None:
        """Draft a real patch *preview* for an executable step — never applied.

        Uses the existing SemanticPatchGenerator with a change-strategy hint that
        selects the matching transform. Returns a compact preview (transform,
        files, rationale, truncated new content) or None if nothing applies.
        """
        result = self._generate(step, project_root)
        if result is None:
            return None
        first = result.patch_requests[0]
        new_content = (first.get("new_content") or "")[:400]
        return {
            "transform_type": result.transform_type,
            "files": [pr.get("path") for pr in result.patch_requests],
            "rationale": result.rationale,
            "preview": new_content,
            "applied": False,
        }

    def apply_step(
        self, step: ActionStep, project_root: str, mode: str = "supervised", run_tests: bool = False
    ) -> dict:
        """Apply an executable step's patch — strictly gated, opt-in.

        Enforces ModePolicy (must allow patching) and SafetyGates (scope,
        sensitive paths, secrets) before writing anything. Report mode can
        never apply. Returns a result dict describing what happened.
        """
        from app.policies.mode_policy import ModePolicy, mode_from_string

        policy = ModePolicy(mode=mode_from_string(mode))
        perms = policy.permissions
        if not perms.can_patch:
            return {"applied": False, "reason": f"mode '{mode}' is read-only (cannot patch)"}

        result = self._generate(step, project_root)
        if result is None:
            return {"applied": False, "reason": "no applicable patch generated"}

        patch_requests = result.patch_requests
        changed = [pr.get("path", "") for pr in patch_requests]

        if perms.requires_safety_gates:
            from app.policies.safety_gates import SafetyGates

            new_code = "\n".join(pr.get("new_content", "") or "" for pr in patch_requests)
            old_code = "\n".join(pr.get("expected_old_content", "") or "" for pr in patch_requests)
            gates = SafetyGates(project_root, max_changed_files=perms.max_changed_files)
            report = gates.check_all(
                changed_files=changed, old_code=old_code, new_code=new_code, skip_test=not run_tests
            )
            if report.blocked:
                return {"applied": False, "reason": "blocked by safety gates", "summary": report.summary}

        from app.skills.execution.apply_patch import ApplyPatchSkill, FilePatch

        patches = [
            FilePatch(
                path=pr["path"],
                new_content=pr["new_content"],
                expected_old_content=pr.get("expected_old_content"),
            )
            for pr in patch_requests
        ]
        applied = ApplyPatchSkill().run(project_root, patches)
        return {
            "applied": applied.ok,
            "mode": mode,
            "transform_type": result.transform_type,
            "changed_files": applied.changed_files,
            "skipped_files": applied.skipped_files,
            "error": applied.error,
        }

    def plan_tree(
        self,
        report: IdeaTreeReport,
        mode: str = "supervised",
        top: int | None = None,
        draft: bool = False,
        project_root: str | None = None,
    ) -> ActionPlan:
        ideas = sorted(report.ideas, key=lambda i: i.value, reverse=True)
        if top is not None:
            ideas = ideas[:top]
        steps = [self.plan_idea(i) for i in ideas]
        if draft:
            root = project_root or report.project_root or "."
            for step in steps:
                if step.executable:
                    step.patch_preview = self.draft_patch(step, root)
        executable = sum(1 for s in steps if s.executable)
        drafted = sum(1 for s in steps if s.patch_preview)
        return ActionPlan(
            objective=report.objective,
            project_root=report.project_root,
            mode=mode,
            steps=steps,
            stats={
                "total_steps": len(steps),
                "executable_steps": executable,
                "design_tasks": len(steps) - executable,
                "drafted_patches": drafted,
            },
        )


def render_action_markdown(plan: ActionPlan) -> str:
    """Render an action plan as reviewable markdown (supervised — not applied)."""
    lines = [f"# Action Plan for `{plan.project_root}`  _(mode: {plan.mode}, not applied)_", ""]
    if plan.objective:
        lines.append(f"objective: _{plan.objective}_")
    lines.append(
        f"{plan.stats.get('total_steps', 0)} steps · "
        f"{plan.stats.get('executable_steps', 0)} executable · "
        f"{plan.stats.get('design_tasks', 0)} design tasks"
    )
    lines.append("")
    for s in plan.steps:
        tag = "🛠️" if s.executable else "📐"
        lines.append(f"- {tag} `{s.branch_path}` **{s.action_type}** — {s.description}  (v {s.value})")
        if s.patch_preview:
            files = ", ".join(s.patch_preview.get("files", []))
            lines.append(
                f"    ↳ draft `{s.patch_preview.get('transform_type')}` → {files} (preview, not applied)"
            )
    return "\n".join(lines)
