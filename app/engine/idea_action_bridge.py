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
    "hotspot-function": ("create_test_stub", "Write behavioral tests for the complex function {s}", True),
    "sensitive-path": ("harden_security", "Harden the sensitive path {s}", True),
    "security-finding": ("harden_security", "Fix the security findings in {s}", True),
    "correctness-bug": ("harden_security", "Fix the likely logic bug in {s}", True),
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

    def plan_convergence(self, idea: IdeaNode) -> list[ActionStep]:
        """Expand a convergence idea into an ordered, phased mini-roadmap.

        Returns one ActionStep per remediation phase (Stabilize before Secure
        before the rest), all targeting the converged module, executable where a
        deterministic transform exists. Empty for a non-convergence idea.
        """
        from app.engine.idea_permutation import convergence_labels, convergence_plan

        labels = convergence_labels(idea)
        if not labels:
            return []
        target = idea.subject.split("::", 1)[0]
        target = target if "/" in target or target.endswith(".py") else ""
        steps: list[ActionStep] = []
        for n, step in enumerate(convergence_plan(labels)):
            steps.append(ActionStep(
                branch_path=f"{idea.branch_path}.{n}",
                title=f"{step['phase']}: {step['step']} in {idea.subject}",
                operator="synthesis",
                subject=idea.subject,
                action_type=step["action_type"],
                target=target,
                description=f"{step['step']} ({idea.subject})",
                executable=step["executable"],
                value=idea.value,
                source_facts=idea.source_facts,
                phase=step["phase"],
            ))
        return steps

    @staticmethod
    def _dedupe_steps(steps: list[ActionStep]) -> list[ActionStep]:
        """Drop a later executable step that repeats an earlier one's
        (module, action) — e.g. a convergence test sub-step and a separate
        'Test: that module' root idea are the same work. Keeps the first
        (so the higher-ranked / phased one wins); design tasks pass through."""
        seen: set[tuple[str, str]] = set()
        out: list[ActionStep] = []
        for s in steps:
            if not s.executable:
                out.append(s)
                continue
            key = (s.subject.split("::", 1)[0], s.action_type)
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    def _expand_idea(self, idea: IdeaNode, default_phase: str = "") -> list[ActionStep]:
        """One idea -> one or more steps. A convergence idea becomes its phased
        mini-roadmap (executable test step before the harden step); every other
        idea is a single planned step."""
        conv = self.plan_convergence(idea)
        if conv:
            return conv
        step = self.plan_idea(idea)
        if default_phase:
            step.phase = default_phase
        return [step]

    def plan_idea(self, idea: IdeaNode) -> ActionStep:
        if idea.operator == "root":
            action_type, desc_tmpl, executable = self._root_action(idea)
        else:
            action_type, desc_tmpl, executable = _OPERATOR_ACTIONS.get(
                idea.operator, ("design_task", "Develop {s}", False)
            )
        # Symbol-granular subjects ("mod.py::Class.func") act on the module file;
        # the function name stays in the title/description for the test author.
        file_part = idea.subject.split("::", 1)[0]
        return ActionStep(
            branch_path=idea.branch_path,
            title=idea.title,
            operator=idea.operator,
            subject=idea.subject,
            action_type=action_type,
            target=file_part if "/" in file_part or file_part.endswith(".py") else "",
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
    def _read(project_root: str, rel_path: str) -> str | None:
        try:
            return (Path(project_root) / rel_path).read_text(encoding="utf-8")
        except OSError:
            return None

    # Flag-only fixes annotate the call site but leave the pattern in place, so
    # the finding persists after fixing. Their marker comment lets the ladder
    # know an already-handled finding should be skipped (so convergence advances
    # to the next real issue instead of stalling on a flagged-but-present one).
    _FLAG_MARKERS = {
        "pickle": "Apex: untrusted pickle",
        "sql": "Apex: SQL injection",
        "tempfile": "Apex: insecure temp file",
        "weak-hash": "Apex: weak hash",
    }

    @classmethod
    def _detect_security_issue(cls, project_root: str, rel_path: str) -> str | None:
        """The concrete security pattern to fix next in a file, most severe first.

        Rewrite fixes (eval/os.system/bare-except/yaml) remove the pattern, so
        they self-clear. Flag-only fixes (pickle/sql/tempfile/weak-hash) don't —
        so a label whose marker comment is already present is skipped, letting
        the harden ladder converge through every issue instead of looping on the
        top flagged one. Delegates to the canonical detector.

        Returns the most-severe label whose transform *can actually act* on this
        file: an unfixable finding (e.g. an eval of a non-literal expression that
        the transform soundly declines) must not block hardening a fixable
        os.system/pickle later in the same file."""
        from app.engine.detectors import security_labels
        from app.execution.semantic.transforms import security as security_transforms

        text = cls._read(project_root, rel_path)
        if text is None:
            return None
        for label in security_labels(text):
            marker = cls._FLAG_MARKERS.get(label)
            if marker and marker in text:
                continue  # already annotated — move on to the next real issue
            if security_transforms.apply(rel_path, text, f"fix {label}") is None:
                continue  # transform declines this one — try the next real issue
            return label
        return None

    @classmethod
    def _has_mutable_default(cls, project_root: str, rel_path: str) -> bool:
        """True if the file has a function with a mutable default argument."""
        from app.engine.detectors import has_mutable_default

        text = cls._read(project_root, rel_path)
        return has_mutable_default(text) if text is not None else False

    @classmethod
    def _detect_modernization(cls, project_root: str, rel_path: str) -> bool:
        """True if the file has a real ``== None`` / ``!= None`` comparison."""
        from app.engine.detectors import has_none_comparison

        text = cls._read(project_root, rel_path)
        return has_none_comparison(text) if text is not None else False

    @classmethod
    def _detect_open_encoding(cls, project_root: str, rel_path: str) -> bool:
        """True if the file opens text without an explicit ``encoding=``."""
        from app.engine.detectors import has_open_without_encoding

        text = cls._read(project_root, rel_path)
        return has_open_without_encoding(text) if text is not None else False

    @classmethod
    def _detect_net_timeout(cls, project_root: str, rel_path: str) -> bool:
        """True if the file makes a network call without an explicit ``timeout=``."""
        from app.engine.detectors import has_network_call_without_timeout

        text = cls._read(project_root, rel_path)
        return has_network_call_without_timeout(text) if text is not None else False

    @classmethod
    def _detect_identity_literal(cls, project_root: str, rel_path: str) -> bool:
        """True if the file compares with ``is``/``is not`` against a literal (a bug)."""
        from app.engine.detectors import has_identity_literal

        text = cls._read(project_root, rel_path)
        return has_identity_literal(text) if text is not None else False

    @classmethod
    def _detect_raise_from(cls, project_root: str, rel_path: str) -> bool:
        """True if the file re-raises a new exception without `from` in a handler
        that binds the caught exception (the auto-fixable B904 shape)."""
        from app.engine.detectors import has_fixable_raise_without_from

        text = cls._read(project_root, rel_path)
        return has_fixable_raise_without_from(text) if text is not None else False

    @classmethod
    def _detect_negated_comparison(cls, project_root: str, rel_path: str) -> bool:
        """True if the file has a `not x in y` / `not x is y` to simplify."""
        from app.engine.detectors import has_negated_comparison

        text = cls._read(project_root, rel_path)
        return has_negated_comparison(text) if text is not None else False

    @classmethod
    def _harden_change_strategy(cls, project_root: str, target: str) -> tuple[list[str], str] | None:
        """Pick the harden fix for the most important *real* issue in ``target``.

        Detection ladder, most-severe first. Returns ``(change_strategy, title)``
        for the issue found, or ``None`` when the file has no real, auto-fixable
        issue — in which case harden makes no change rather than fabricating a
        speculative guard (trust over activity).
        """
        issue = cls._detect_security_issue(project_root, target)
        if issue:
            return [f"fix {issue} security"], f"Fix {issue} in {target}"
        if cls._has_mutable_default(project_root, target):
            return ["mutable default argument"], f"Fix mutable default arguments in {target}"
        if cls._detect_modernization(project_root, target):
            return ["modernize none-comparison"], f"Modernize comparisons in {target}"
        if cls._detect_open_encoding(project_root, target):
            return ["open-encoding"], f"Add explicit open() encoding in {target}"
        if cls._detect_net_timeout(project_root, target):
            return ["net-timeout"], f"Add request timeouts in {target}"
        if cls._detect_identity_literal(project_root, target):
            return ["identity-literal"], f"Fix identity-vs-literal comparisons in {target}"
        if cls._detect_negated_comparison(project_root, target):
            return ["negated-comparison"], f"Simplify negated comparisons in {target}"
        if cls._detect_raise_from(project_root, target):
            return ["raise-from"], f"Chain re-raised exceptions to their cause in {target}"
        return None

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
            ladder = self._harden_change_strategy(project_root, step.target)
            if ladder is None:
                return None  # no real, auto-fixable issue — don't invent one
            change_strategy, title = ladder
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
        if applied.ok and applied.changed_files:
            out["diff"] = self._evidence_diff(snapshot, patch_requests, applied.changed_files)
        if not (verify and applied.ok and applied.changed_files):
            return out

        # Verify: run tests; roll back the changed files if they fail.
        from app.engine.proof_of_fix import summarize_test_run
        from app.skills.execution.run_tests import RunTestsSkill

        summary = RunTestsSkill().run(project_root)
        out["verified"] = bool(summary.ok)
        out["test_commands"] = summary.commands
        out["test_evidence"] = summarize_test_run(summary)
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

    @staticmethod
    def _evidence_diff(snapshot: dict[str, str | None], patch_requests: list[dict],
                       changed_files: list[str]) -> str:
        """Unified diff of what was just applied (snapshot → written content).

        This is the evidence trail for the proof-of-fix artifact: the exact
        change, recorded even if the step is later rolled back.
        """
        import difflib

        new_by_path = {pr.get("path", ""): pr.get("new_content", "") or "" for pr in patch_requests}
        parts: list[str] = []
        for rel in changed_files:
            old = snapshot.get(rel) or ""
            new = new_by_path.get(rel, "")
            diff = "".join(difflib.unified_diff(
                old.splitlines(keepends=True), new.splitlines(keepends=True),
                fromfile=f"a/{rel}", tofile=f"b/{rel}",
            ))
            parts.append(diff or f"(new file) b/{rel}")
        return "\n".join(parts)

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
        def _commit(r: dict) -> tuple[bool, str | None]:
            if committer is None or not r.get("changed_files"):
                return False, None
            cres = committer.commit(changed_files=r["changed_files"], finding=step.action_type, action="fix")
            return bool(cres.success), getattr(cres, "commit_hash", None)

        for step in plan.executable_steps():
            if max_apply is not None and applied >= max_apply:
                break
            # The first apply classifies the step (applied / rolled-back / blocked),
            # exactly one result row per step.
            r = self.apply_step(step, project_root, mode=mode, verify=verify)
            label = step.source_facts[0].split(":")[0].strip() if step.source_facts else ""
            entry = {"branch": step.branch_path, "action": step.action_type,
                     "operator": step.operator, "label": label,
                     "target": step.target, **r}
            real_fix = bool(r.get("applied")) and step.target in (r.get("changed_files") or [])
            if r.get("rolled_back"):
                rolled_back += 1
            elif r.get("applied"):
                applied += 1
                ok, h = _commit(r)
                entry["committed"] = ok
                if ok:
                    committed += 1
                    entry["commit_hash"] = h
                # CONVERGENCE: a harden_security step then fixes EVERY remaining
                # auto-fixable issue in the same file (the detection ladder
                # advances as each is fixed). These extra verified fixes don't
                # create new rows — they're tracked on the step's entry — so one
                # maintenance pass cleans the file instead of one fix per pass.
                if step.action_type == "harden_security" and real_fix:
                    extra = 0
                    for _ in range(5):
                        r2 = self.apply_step(step, project_root, mode=mode, verify=verify)
                        if not (r2.get("applied") and step.target in (r2.get("changed_files") or [])):
                            break
                        extra += 1
                        ok2, _h2 = _commit(r2)
                        if ok2:
                            committed += 1
                    if extra:
                        entry["converged_fixes"] = extra
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
        steps: list[ActionStep] = []
        for i in ideas:
            steps.extend(self._expand_idea(i))
        steps = self._dedupe_steps(steps)
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
            for item in ph.items:
                idea = idea_by_path.get(item.branch_path)
                if idea is None:
                    continue
                # Convergence ideas carry their own phased sub-steps (a Stabilize
                # test before a Secure harden), so they may emit a phase other
                # than where the parent idea was placed; other ideas inherit this
                # roadmap phase.
                steps.extend(self._expand_idea(idea, default_phase=ph.name))

        steps = self._dedupe_steps(steps)
        # A convergence idea sits in one phase but emits sub-steps in others (a
        # Stabilize test then a Secure harden). Stable-sort by canonical phase so
        # every step joins its true phase group — which also preserves the
        # test-before-harden order for free, since Stabilize precedes Secure.
        from app.engine.idea_roadmap import PHASE_ORDER
        phase_rank = {name: i for i, name in enumerate(PHASE_ORDER)}
        steps.sort(key=lambda s: phase_rank.get(s.phase, len(PHASE_ORDER)))
        # The phase filter applies to each *step's own* phase, so a convergence
        # idea's Secure sub-step is kept under --phase=Secure even though its
        # parent sat in Stabilize (and vice-versa).
        if phase:
            steps = [s for s in steps if s.phase.lower() == phase.lower()]
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
