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
    "modernization": ("modernize_comparisons", "Modernize None comparisons in {s}", True),
    "mutable-default": ("fix_mutable_defaults", "Fix mutable default arguments in {s}", True),
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
        "modernize_comparisons": ["modernize none-comparison"],
        "fix_mutable_defaults": ["mutable default argument"],
    }

    @staticmethod
    def _detect_security_issue(project_root: str, rel_path: str) -> str | None:
        """Return the concrete security pattern present in a file, if any, so
        harden_security can pick the real AST fix (eval / os.system / pickle /
        yaml / sql / bare-except) instead of a generic guard clause.

        AST-based (single parse) so it ignores matches inside comments/strings —
        e.g. ``# don't use eval()`` no longer triggers an eval fix. Falls back to
        a substring scan only if the file can't be parsed.
        """
        import ast

        try:
            text = (Path(project_root) / rel_path).read_text(encoding="utf-8")
        except OSError:
            return None

        try:
            tree = ast.parse(text)
        except SyntaxError:
            # Unparseable: conservative substring fallback (order = severity).
            for needle, label in (
                ("eval(", "eval"), ("os.system(", "os.system"),
                ("pickle.loads(", "pickle"), ("yaml.load(", "yaml"),
                ("except:", "bare except"),
            ):
                if needle in text:
                    return label
            return None

        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                found.add("bare except")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "eval":
                    found.add("eval")
                elif isinstance(func, ast.Attribute):
                    owner = func.value.id if isinstance(func.value, ast.Name) else ""
                    if owner == "os" and func.attr == "system":
                        found.add("os.system")
                    elif owner == "pickle" and func.attr == "loads":
                        found.add("pickle")
                    elif owner == "yaml" and func.attr == "load":
                        found.add("yaml")
                    elif func.attr in ("execute", "cursor", "executemany") and any(
                        isinstance(a, ast.JoinedStr) for a in node.args
                    ):
                        found.add("sql")
        # Most dangerous first.
        for label in ("eval", "os.system", "pickle", "yaml", "sql", "bare except"):
            if label in found:
                return label
        return None

    @staticmethod
    def _has_mutable_default(project_root: str, rel_path: str) -> bool:
        """True if the file has a function with a mutable default argument."""
        import ast

        try:
            tree = ast.parse((Path(project_root) / rel_path).read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            return False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in list(node.args.defaults) + [k for k in node.args.kw_defaults if k]:
                    if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                        return True
                    if (isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                            and d.func.id in ("list", "dict", "set")
                            and not d.args and not d.keywords):
                        return True
        return False

    @staticmethod
    def _detect_modernization(project_root: str, rel_path: str) -> bool:
        """True if the file has a real ``== None`` / ``!= None`` comparison that a
        behavior-preserving modernization could clean up (AST-based)."""
        import ast

        try:
            tree = ast.parse((Path(project_root) / rel_path).read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                ops = node.ops
                if any(isinstance(o, (ast.Eq, ast.NotEq)) for o in ops) and any(
                    isinstance(x, ast.Constant) and x.value is None for x in operands
                ):
                    return True
        return False

    def _generate(self, step: ActionStep, project_root: str):
        """Run the semantic generator for an executable step. Returns the
        SemanticPatchResult (proposed only) or None."""
        if not step.executable or step.action_type not in self._ACTION_STRATEGY:
            return None
        if not step.target or not step.target.endswith(".py"):
            return None
        if step.action_type == "create_test_stub":
            # Don't generate tests *for* test files, and never overwrite an
            # existing test file (that would clobber real tests).
            stem = Path(step.target).stem
            if stem.startswith("test_") or "/tests/" in f"/{step.target}" or step.target.startswith("tests/"):
                return None
            stub = f"tests/test_{stem}.py"
            if (Path(project_root) / stub).exists():
                return None
            target_files = [stub]
        else:
            target_files = [step.target]

        # harden_security: prefer a concrete AST security fix when the file has
        # a known dangerous pattern; fall back to the generic guard-clause hint.
        change_strategy = self._ACTION_STRATEGY[step.action_type]
        title = step.description
        if step.action_type == "harden_security":
            # Detection ladder: fix the most important *real* issue the file has,
            # falling back to a generic guard clause only when none is present.
            issue = self._detect_security_issue(project_root, step.target)
            if issue:
                change_strategy = [f"fix {issue} security"]
                title = f"Fix {issue} in {step.target}"
            elif self._has_mutable_default(project_root, step.target):
                change_strategy = ["mutable default argument"]
                title = f"Fix mutable default arguments in {step.target}"
            elif self._detect_modernization(project_root, step.target):
                change_strategy = ["modernize none-comparison"]
                title = f"Modernize comparisons in {step.target}"
        elif step.action_type == "organize_imports" and self._detect_modernization(project_root, step.target):
            # A "simplify" idea on a file with `== None` modernizes it (a safe,
            # behavior-preserving cleanup) instead of only touching imports.
            change_strategy = ["modernize none-comparison"]
            title = f"Modernize comparisons in {step.target}"

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
        self,
        step: ActionStep,
        project_root: str,
        mode: str = "supervised",
        run_tests: bool = False,
        verify: bool = False,
    ) -> dict:
        """Apply an executable step's patch — strictly gated, opt-in.

        Enforces ModePolicy (must allow patching) and SafetyGates (scope,
        sensitive paths, secrets) before writing anything. Report mode can
        never apply.

        When ``verify`` is set, the original file contents are snapshotted
        before writing; after applying, the test suite is run and — if it
        fails — every changed file is restored to its pre-patch content
        (automatic rollback). Returns a result dict describing what happened.
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

        # Snapshot originals for rollback before touching the tree.
        root = Path(project_root)
        snapshot: dict[str, str | None] = {}
        for pr in patch_requests:
            fp = root / pr["path"]
            snapshot[pr["path"]] = fp.read_text(encoding="utf-8") if fp.exists() else None

        patches = [
            FilePatch(
                path=pr["path"],
                new_content=pr["new_content"],
                expected_old_content=pr.get("expected_old_content"),
            )
            for pr in patch_requests
        ]
        applied = ApplyPatchSkill().run(project_root, patches)

        out = {
            "applied": applied.ok,
            "mode": mode,
            "transform_type": result.transform_type,
            "changed_files": applied.changed_files,
            "skipped_files": applied.skipped_files,
            "error": applied.error,
        }
        if not (verify and applied.ok and applied.changed_files):
            return out

        # Verify: run tests; roll back the changed files if they fail.
        from app.skills.execution.run_tests import RunTestsSkill

        summary = RunTestsSkill().run(project_root)
        out["verified"] = bool(summary.ok)
        out["test_commands"] = summary.commands
        if summary.ok or not summary.commands:
            # Pass (or no test command detected -> nothing to verify against).
            out["rolled_back"] = False
            return out

        # Tests failed -> restore every changed file to its snapshot.
        for rel in applied.changed_files:
            original = snapshot.get(rel)
            fp = root / rel
            if original is None:
                fp.unlink(missing_ok=True)  # file was newly created
            else:
                fp.write_text(original, encoding="utf-8")
        out["applied"] = False
        out["rolled_back"] = True
        out["reason"] = "tests failed after patch; changes rolled back"
        return out

    def dry_run_plan(self, plan: ActionPlan, project_root: str) -> dict:
        """Preview a maintenance pass without touching the tree.

        For each executable step, generate its patch and produce a real unified
        diff against the current file — so you can see exactly what
        `apply_plan` would change, applied to nothing.
        """
        import difflib

        root = Path(project_root)
        previews: list[dict] = []
        for step in plan.executable_steps():
            result = self._generate(step, project_root)
            if result is None:
                previews.append({"branch": step.branch_path, "action": step.action_type,
                                 "target": step.target, "applicable": False})
                continue
            diffs: list[str] = []
            for pr in result.patch_requests:
                rel = pr.get("path", "")
                old = ""
                fp = root / rel
                if fp.exists():
                    old = fp.read_text(encoding="utf-8")
                new = pr.get("new_content", "") or ""
                diff = "".join(
                    difflib.unified_diff(
                        old.splitlines(keepends=True), new.splitlines(keepends=True),
                        fromfile=f"a/{rel}", tofile=f"b/{rel}",
                    )
                )
                diffs.append(diff or f"(new file) b/{rel}")
            previews.append({
                "branch": step.branch_path, "action": step.action_type,
                "target": step.target, "applicable": True,
                "transform_type": result.transform_type,
                "files": [pr.get("path") for pr in result.patch_requests],
                "diff": "\n".join(diffs),
            })
        return {
            "dry_run": True,
            "total_executable": len(plan.executable_steps()),
            "applicable": sum(1 for p in previews if p["applicable"]),
            "results": previews,
        }

    def apply_plan(
        self,
        plan: ActionPlan,
        project_root: str,
        mode: str = "supervised",
        verify: bool = False,
        max_apply: int | None = None,
        commit: bool = False,
    ) -> dict:
        """Run a whole maintenance pass: apply each executable step in turn,
        verifying + rolling back individually, and return an aggregate summary.

        Steps are processed in plan order (already value-sorted). Each step is
        independent — a rolled-back step does not abort the run. Honors the
        same gating as apply_step (mode + safety + verify).

        When ``commit`` is set AND the mode permits committing (autonomous),
        each successfully-applied step is committed individually via
        GitAutoCommit, so every change is an isolated, revertible commit.
        """
        from app.policies.mode_policy import ModePolicy, mode_from_string

        can_commit = False
        committer = None
        if commit:
            perms = ModePolicy(mode=mode_from_string(mode)).permissions
            can_commit = bool(perms.can_commit)
            if can_commit:
                from app.engine.git_auto_commit import GitAutoCommit

                committer = GitAutoCommit(project_root)

        results: list[dict] = []
        applied = rolled_back = blocked = committed = 0
        for step in plan.executable_steps():
            if max_apply is not None and applied >= max_apply:
                break
            r = self.apply_step(step, project_root, mode=mode, verify=verify)
            label = step.source_facts[0].split(":")[0].strip() if step.source_facts else ""
            entry = {"branch": step.branch_path, "action": step.action_type,
                     "operator": step.operator, "label": label,
                     "target": step.target, **r}
            if r.get("rolled_back"):
                rolled_back += 1
            elif r.get("applied"):
                applied += 1
                if committer is not None and r.get("changed_files"):
                    commit_res = committer.commit(
                        changed_files=r["changed_files"],
                        finding=step.action_type,
                        action="fix",
                    )
                    entry["committed"] = bool(commit_res.success)
                    if commit_res.success:
                        committed += 1
                        entry["commit_hash"] = commit_res.commit_hash
            else:
                blocked += 1
            results.append(entry)
        return {
            "mode": mode,
            "verify": verify,
            "commit": can_commit,
            "total_executable": len(plan.executable_steps()),
            "applied": applied,
            "rolled_back": rolled_back,
            "blocked": blocked,
            "committed": committed,
            "results": results,
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

    def plan_roadmap(
        self,
        report: IdeaTreeReport,
        roadmap=None,
        phase: str | None = None,
        mode: str = "supervised",
        top: int | None = None,
        draft: bool = False,
        project_root: str | None = None,
    ) -> ActionPlan:
        """Plan actions in roadmap order (Stabilize→Secure→Evolve→Refine).

        Unlike ``plan_tree`` (pure value ranking), this sequences steps by the
        roadmap's engineering phases so a guarded ``apply_plan`` builds the
        safety net before changing risky code. ``phase`` restricts the plan to a
        single phase; each step is tagged with the phase it came from.
        """
        from app.engine.idea_roadmap import RoadmapSynthesizer

        roadmap = roadmap or RoadmapSynthesizer().build(report)
        idea_by_path = {i.branch_path: i for i in report.ideas}

        steps: list[ActionStep] = []
        for ph in roadmap.phases:
            if phase and ph.name.lower() != phase.lower():
                continue
            for item in ph.items:
                idea = idea_by_path.get(item.branch_path)
                if idea is None:
                    continue
                step = self.plan_idea(idea)
                step.phase = ph.name
                steps.append(step)

        if top is not None:
            steps = steps[:top]
        if draft:
            root = project_root or report.project_root or "."
            for step in steps:
                if step.executable:
                    step.patch_preview = self.draft_patch(step, root)

        executable = sum(1 for s in steps if s.executable)
        drafted = sum(1 for s in steps if s.patch_preview)
        phase_counts: dict[str, int] = {}
        for s in steps:
            phase_counts[s.phase] = phase_counts.get(s.phase, 0) + 1
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
                "ordered_by": "roadmap",
                "phase_counts": phase_counts,
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
        phase = f"[{s.phase}] " if s.phase else ""
        lines.append(
            f"- {tag} `{s.branch_path}` {phase}**{s.action_type}** — {s.description}  (v {s.value})"
        )
        if s.patch_preview:
            files = ", ".join(s.patch_preview.get("files", []))
            lines.append(
                f"    ↳ draft `{s.patch_preview.get('transform_type')}` → {files} (preview, not applied)"
            )
    return "\n".join(lines)


def render_maintenance_markdown(summary: dict, project_root: str, objective: str = "") -> str:
    """Render an end-to-end maintenance run as a Markdown report."""
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Apex Maintenance Report — `{project_root}`",
        "",
        f"_Generated {ts}_",
    ]
    if objective:
        lines.append(f"_Objective: {objective}_")
    lines += [
        "",
        f"- Mode: **{summary.get('mode')}**"
        + ("  · verified" if summary.get("verify") else "")
        + ("  · committed" if summary.get("commit") else ""),
        f"- Applied: **{summary.get('applied', 0)}** · "
        f"Rolled back: **{summary.get('rolled_back', 0)}** · "
        f"Blocked: **{summary.get('blocked', 0)}** "
        f"of {summary.get('total_executable', 0)} executable steps",
    ]
    if summary.get("commit"):
        lines.append(f"- Commits created: **{summary.get('committed', 0)}**")
    lines.append("")

    applied = [r for r in summary.get("results", []) if r.get("applied")]
    rolled = [r for r in summary.get("results", []) if r.get("rolled_back")]
    blocked = [r for r in summary.get("results", []) if not r.get("applied") and not r.get("rolled_back")]

    if applied:
        lines.append("## ✅ Applied")
        for r in applied:
            extra = ""
            if r.get("verified") is True:
                extra += " (tests pass)"
            if r.get("committed"):
                extra += f" [commit {r.get('commit_hash', '')}]"
            files = ", ".join(r.get("changed_files", [])) or r.get("target", "")
            lines.append(f"- `{r['branch']}` **{r['action']}** — {files}{extra}")
        lines.append("")
    if rolled:
        lines.append("## ↩️ Rolled back (tests failed)")
        for r in rolled:
            lines.append(f"- `{r['branch']}` **{r['action']}** — {r.get('target', '')}")
        lines.append("")
    if blocked:
        lines.append("## ⛔ Blocked / not applicable")
        for r in blocked:
            lines.append(f"- `{r['branch']}` **{r['action']}** — {r.get('reason', '')}")
        lines.append("")
    return "\n".join(lines)
