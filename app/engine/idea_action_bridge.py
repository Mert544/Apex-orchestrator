from __future__ import annotations

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

    def plan_tree(
        self, report: IdeaTreeReport, mode: str = "supervised", top: int | None = None
    ) -> ActionPlan:
        ideas = sorted(report.ideas, key=lambda i: i.value, reverse=True)
        if top is not None:
            ideas = ideas[:top]
        steps = [self.plan_idea(i) for i in ideas]
        executable = sum(1 for s in steps if s.executable)
        return ActionPlan(
            objective=report.objective,
            project_root=report.project_root,
            mode=mode,
            steps=steps,
            stats={
                "total_steps": len(steps),
                "executable_steps": executable,
                "design_tasks": len(steps) - executable,
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
    return "\n".join(lines)
