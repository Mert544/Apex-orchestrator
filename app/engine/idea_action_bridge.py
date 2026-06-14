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
    "impure-untested": ("create_test_stub", "Cover the impure function {s} with tests (then isolate its side effects)", True),
    "hub-untested": ("create_test_stub", "Add a regression-net test for the dependency hub {s} (it has many dependents)", True),
    # A confluence is a "decouple/test before you change" signal, not a blind
    # auto-fix: recommend-only by default. The sole exception is an UNTESTED
    # confluence, where the grounded first move is the same as every other
    # untested high-leverage module — drop a safety-net test first (resolved in
    # _root_action, which can read the fact value's "untested" marker).
    "confluence": ("design_task", "Decouple and add tests to {s} before changing it — several independent pressures converge here", False),
    # Co-change test-gap: a PAIR that co-changes but no single test exercises
    # both. The grounded first move is to add a joint test, so route to the
    # existing create_test_stub action (it is a test gap), executable like the
    # other untested signals.
    "cochange-testgap": ("create_test_stub", "Add a test that exercises {s} together — they co-change but nothing tests them jointly", True),
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
    # The hands exist (apex signature drop/keywordify) but as supervised CLI
    # muscles, not unattended transforms — the work order carries the command.
    "dead-parameter": ("design_task",
                       "Drop the never-read parameter from {s} — the idea's fact "
                       "line carries the exact `apex signature drop` command "
                       "(chain `apex signature keywordify` first if a caller "
                       "passes it positionally)", False),
}


# Action types that are test gaps — for these, a function-grain anchor lets us
# name the actual symbol(s)/line(s) instead of only the module. Anything else
# (harden/imports/design) keeps its module-level phrasing.
_TEST_ACTIONS = frozenset({"create_test_stub"})


def _function_anchors(node) -> list[dict]:
    """The idea's function-grain anchors, read DEFENSIVELY.

    ``IdeaNode.anchors`` is an optional, parallel-agent field
    (``[{"module","symbol","line","metric"}]``). Read it via ``getattr`` so this
    code works whether or not it is present yet, and keep only anchors that name
    a concrete symbol. Stable order: anchors are returned exactly as carried (no
    sort, no time/random) so the same idea always yields the same description.
    """
    anchors = getattr(node, "anchors", []) or []
    out: list[dict] = []
    for a in anchors:
        if isinstance(a, dict) and str(a.get("symbol") or "").strip():
            out.append(a)
    return out


def _anchor_phrase(anchor: dict, module: str) -> str:
    """`symbol` (module:line) — metric  for one anchor (line/metric optional)."""
    symbol = str(anchor.get("symbol") or "").strip()
    loc = str(anchor.get("module") or module or "").strip()
    line = anchor.get("line")
    if loc and line:
        loc = f"{loc}:{line}"
    elif not loc:
        loc = str(line) if line else ""
    head = f"`{symbol}` ({loc})" if loc else f"`{symbol}`"
    metric = str(anchor.get("metric") or "").strip()
    return f"{head} — {metric}" if metric else head


def _concrete_test_description(node, fallback: str) -> str:
    """A function-grain test description when anchors name real symbols.

    e.g. "Add tests for `_scan_churn` (app/tools/project_profile.py:550) —
    cyclomatic 18, no linked test." Falls back to the module-level ``fallback``
    (the formatted operator/fact template) when no anchor carries a symbol.
    """
    module = str(getattr(node, "subject", "") or "").split("::", 1)[0]
    anchors = _function_anchors(node)
    if not anchors:
        return fallback
    phrases = [_anchor_phrase(a, module) for a in anchors]
    return f"Add tests for {', '.join(phrases)}"


def _test_stub_body(node, target: str) -> str:
    """A deterministic pytest stub naming the REAL symbol(s) and import path.

    When anchors carry symbols, emit one ``def test_<symbol>_...():`` skeleton
    per anchor referencing the actual module import path; otherwise a single
    module-level smoke stub. Pure text, recommend-only — never written here.
    """
    module = str(getattr(node, "subject", "") or "").split("::", 1)[0]
    mod_path = (target or module).removesuffix(".py").replace("/", ".")
    anchors = _function_anchors(node)
    header = [
        "# Apex-proposed test stub (recommend-only — not applied).",
        f"# Subject: {target or module}",
        f"import {mod_path}  # noqa: F401" if mod_path else "",
        "",
    ]
    bodies: list[str] = []
    if anchors:
        for a in anchors:
            symbol = str(a.get("symbol") or "").strip()
            # Keep the symbol's own underscores (a leading "_" is meaningful:
            # `_scan_churn` -> `test__scan_churn_behavior`); only non-identifier
            # characters become "_". Trailing junk is trimmed, never the symbol.
            slug = "".join(c if (c.isalnum() or c == "_") else "_"
                           for c in symbol).rstrip("_").lower() or "symbol"
            bodies.append(
                f"def test_{slug}_behavior():\n"
                f"    # TODO: exercise {symbol} in {mod_path or target}.\n"
                f"    assert False, \"write a real assertion for {symbol}\"\n"
            )
    else:
        stem = (target or module).rsplit("/", 1)[-1].removesuffix(".py") or "module"
        slug = "".join(c if (c.isalnum() or c == "_") else "_"
                       for c in stem).strip("_").lower() or "module"
        bodies.append(
            f"def test_{slug}_smoke():\n"
            f"    # TODO: cover {target or module}.\n"
            f"    assert False, \"write a real assertion\"\n"
        )
    return "\n".join([ln for ln in header if ln is not None]).rstrip() + "\n\n\n" + "\n\n".join(bodies)


class IdeaActionBridge:
    """Turn development ideas into a concrete, supervised action plan.

    Maps each idea's terminal development operator (or, for roots, its seeding
    fact) to a known action type, marking those a deterministic transform can
    already draft as ``executable``. This is the guarded link between the
    generative idea tree and the existing semantic-patch / agent executors — it
    proposes, it never applies.
    """

    def _convergence_step(self, idea: IdeaNode, step: dict, n: int,
                          target: str, project_root: str) -> ActionStep | None:
        """One mini-roadmap entry, reality-checked — or None when its
        precondition is already satisfied (a findingless harden)."""
        action = step["action_type"]
        executable = step["executable"] and bool(target)
        text = step["step"]
        if project_root and executable:
            reason = self._unserviceable_reason(action, target, project_root)
            if reason and action == "harden_security":
                return None  # nothing to harden — precondition satisfied
            if reason:
                executable = False
                text += f" — {reason}"
        # Test-gap sub-steps name the concrete function(s) when anchors exist,
        # so a convergence mini-roadmap's Stabilize step is as specific as a
        # standalone test idea; other actions keep their module phrasing.
        description = f"{text} ({idea.subject})"
        if action in _TEST_ACTIONS:
            description = _concrete_test_description(idea, description)
        return ActionStep(
            branch_path=f"{idea.branch_path}.{n}",
            title=f"{step['phase']}: {text} in {idea.subject}",
            operator="synthesis",
            subject=idea.subject,
            action_type=action,
            target=target,
            description=description,
            executable=executable,
            value=idea.value,
            source_facts=idea.source_facts,
            phase=step["phase"],
        )

    def plan_convergence(self, idea: IdeaNode,
                         project_root: str = "") -> list[ActionStep]:
        """Expand a convergence idea into an ordered, phased mini-roadmap.

        Returns one ActionStep per remediation phase (Stabilize before Secure
        before the rest), all targeting the converged module, executable where a
        deterministic transform exists. Empty for a non-convergence idea.

        With ``project_root``, each executable step is REALITY-CHECKED before
        it enters the plan (see ``_unserviceable_reason``) — a step whose
        precondition is already satisfied must not be re-attempted (and
        re-blocked) night after night.
        """
        from app.engine.idea_permutation import convergence_labels, convergence_plan

        labels = convergence_labels(idea)
        if not labels:
            return []
        target = idea.subject.split("::", 1)[0]
        target = target if "/" in target or target.endswith(".py") else ""
        steps: list[ActionStep] = []
        for spec in convergence_plan(labels):
            built = self._convergence_step(idea, spec, len(steps), target, project_root)
            if built is not None:
                steps.append(built)
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

    def _stub_unserviceable(self, target: str, project_root: str) -> str:
        from app.engine.verification_strength import module_referenced_by_suite

        # A stub can only ever be the FIRST test layer. On a module the suite
        # already references, generation either refuses (the test file
        # exists) or writes a redundant smoke stub.
        if module_referenced_by_suite(project_root, target):
            return "linked tests already exist; deepen them by hand"
        return ""

    def _harden_unserviceable(self, target: str, project_root: str) -> str:
        # The full ladder, not just security findings: harden also acts on
        # encodings/timeouts/etc. Only when NO rung fires is there truly
        # nothing for the hands to do.
        if self._harden_change_strategy(project_root, target) is None:
            return "no auto-fixable pattern found; human review"
        return ""

    def _imports_unserviceable(self, target: str, project_root: str) -> str:
        # Probe the transform pair _generate would run (imports tidy, or the
        # modernize swap): a file neither would change can only produce a
        # draft note — that is work-order territory.
        from app.execution.semantic.transforms import organize_imports as oi

        text = self._read(project_root, target)
        servable = text is not None and (
            self._detect_modernization(project_root, target)
            or oi.apply(target, text) is not None)
        return "" if servable else "imports already tidy; human review"

    def _unserviceable_reason(self, action_type: str, target: str,
                              project_root: str) -> str:
        """Why an executable step can't be served right now — "" when it can.

        THE single source of truth for plan-time reality checks: a step that
        enters the plan as executable must answer "can the hands act TODAY?"
        or it will simply re-block every night.
        """
        probe = {
            "create_test_stub": self._stub_unserviceable,
            "harden_security": self._harden_unserviceable,
            "organize_imports": self._imports_unserviceable,
        }.get(action_type)
        return probe(target, project_root) if probe else ""

    def _expand_idea(self, idea: IdeaNode, default_phase: str = "",
                     project_root: str = "") -> list[ActionStep]:
        """One idea -> one or more steps. A convergence idea becomes its phased
        mini-roadmap (executable test step before the harden step); every other
        idea is a single planned step."""
        conv = self.plan_convergence(idea, project_root=project_root)
        if conv:
            return conv
        step = self.plan_idea(idea)
        if default_phase:
            step.phase = default_phase
        if project_root and step.executable and step.target:
            reason = self._unserviceable_reason(step.action_type, step.target,
                                                project_root)
            if reason:
                step.executable = False
                step.description += f" — {reason}"
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
        target = file_part if "/" in file_part or file_part.endswith(".py") else ""
        # Test-gap actions get CONCRETE phrasing: when the idea carries
        # function-grain anchors, name the actual function(s) + line(s); else
        # fall back to the module-level template so existing ideas don't shift.
        description = desc_tmpl.format(s=idea.subject)
        patch_preview: dict | None = None
        if action_type in _TEST_ACTIONS:
            description = _concrete_test_description(idea, description)
            if _function_anchors(idea):
                patch_preview = {
                    "stub_body": _test_stub_body(idea, target),
                    "applied": False,
                }
        return ActionStep(
            branch_path=idea.branch_path,
            title=idea.title,
            operator=idea.operator,
            subject=idea.subject,
            action_type=action_type,
            target=target,
            description=description,
            # No file target = nothing a transform can patch: the step stays a
            # work order instead of becoming a guaranteed nightly "blocked".
            executable=executable and bool(target),
            value=idea.value,
            source_facts=idea.source_facts,
            patch_preview=patch_preview,
        )

    @staticmethod
    def _root_action(idea: IdeaNode) -> tuple[str, str, bool]:
        fact = idea.source_facts[0] if idea.source_facts else ""
        label = fact.split(":")[0].strip()
        # A confluence is recommend-only UNLESS the converging module is also
        # untested — then the grounded first move is a safety-net test stub, the
        # same action every other untested high-leverage module routes to. The
        # marker rides on the fact value the seeder wrote, so no new label/action
        # type is introduced.
        if label == "confluence" and "untested" in fact:
            return ("create_test_stub",
                    "Add a safety-net test for {s} before changing it "
                    "(several independent pressures converge, and it is untested)",
                    True)
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
    def _detect_fstring(cls, project_root: str, rel_path: str) -> bool:
        """True if the file has an f-string without placeholders (a dead `f`)."""
        from app.engine.detectors import has_fstring_no_placeholder

        text = cls._read(project_root, rel_path)
        return has_fstring_no_placeholder(text) if text is not None else False

    @classmethod
    def _detect_collection_literal(cls, project_root: str, rel_path: str) -> bool:
        """True if the file constructs an empty dict/list/tuple via a call."""
        from app.engine.detectors import has_collection_literal

        text = cls._read(project_root, rel_path)
        return has_collection_literal(text) if text is not None else False

    # The detection ladder, most-severe first — DATA, not branches: each rung
    # is (detector method, change strategy, title template). Adding a rung is
    # one line; the dispatch below never changes. (This function was the
    # brief's evidence pin: "8 branches" — the table dissolves them.)
    _HARDEN_LADDER: tuple[tuple[str, str, str], ...] = (
        ("_has_mutable_default", "mutable default argument",
         "Fix mutable default arguments in {t}"),
        ("_detect_modernization", "modernize none-comparison",
         "Modernize comparisons in {t}"),
        ("_detect_open_encoding", "open-encoding",
         "Add explicit open() encoding in {t}"),
        ("_detect_net_timeout", "net-timeout",
         "Add request timeouts in {t}"),
        ("_detect_identity_literal", "identity-literal",
         "Fix identity-vs-literal comparisons in {t}"),
        ("_detect_negated_comparison", "negated-comparison",
         "Simplify negated comparisons in {t}"),
        ("_detect_raise_from", "raise-from",
         "Chain re-raised exceptions to their cause in {t}"),
        ("_detect_fstring", "fstring-no-placeholder",
         "Drop dead f-string prefixes in {t}"),
        ("_detect_collection_literal", "collection-literal",
         "Use collection literals in {t}"),
    )

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
        for detector, strategy, title in cls._HARDEN_LADDER:
            if getattr(cls, detector)(project_root, target):
                return [strategy], title.format(t=target)
        return None

    def _stub_target(self, step: ActionStep, project_root: str) -> list[str] | None:
        """The test-file target list for a create_test_stub step, or None
        when stubbing is impossible (test files themselves; an existing
        test file must never be clobbered)."""
        stem = Path(step.target).stem
        if stem.startswith("test_") or "/tests/" in f"/{step.target}" or step.target.startswith("tests/"):
            return None
        stub = f"tests/test_{stem}.py"
        if (Path(project_root) / stub).exists():
            return None
        return [stub]

    def _change_strategy_for(self, step: ActionStep,
                             project_root: str) -> tuple[list[str], str] | None:
        """The (change_strategy, title) the generator should pursue.

        harden_security prefers a concrete AST security fix when the file
        has a known dangerous pattern (None when no rung fires — don't
        invent one); a "simplify" idea on a file with `== None` modernizes
        it instead of only touching imports.
        """
        change_strategy = self._ACTION_STRATEGY[step.action_type]
        title = step.description
        if step.action_type == "harden_security":
            return self._harden_change_strategy(project_root, step.target)
        if step.action_type == "organize_imports" and self._detect_modernization(project_root, step.target):
            return ["modernize none-comparison"], f"Modernize comparisons in {step.target}"
        return change_strategy, title

    def _step_targets(self, step: ActionStep,
                      project_root: str) -> list[str] | None:
        """The files the generator should write for this step, or None when
        the step has nothing a transform can act on."""
        if not step.executable or step.action_type not in self._ACTION_STRATEGY:
            return None
        if not step.target or not step.target.endswith(".py"):
            return None
        if step.action_type == "create_test_stub":
            return self._stub_target(step, project_root)
        return [step.target]

    @staticmethod
    def _vet_result(result):
        """Only a REAL patch counts. A draft note under .apex/ is not one:
        counting it as "applied" poisons the report, the proof record and
        outcome memory (found by dogfooding: four organize_imports steps
        "landed" by writing .md files — and the dream then praised
        simplify's fake 100%)."""
        if result is None or not result.patch_requests:
            return None
        if result.transform_type == "draft_fallback" or getattr(result, "mode", "") == "draft":
            return None
        return result

    def _generate(self, step: ActionStep, project_root: str):
        """Run the semantic generator for an executable step. Returns the
        SemanticPatchResult (proposed only) or None."""
        target_files = self._step_targets(step, project_root)
        if target_files is None:
            return None

        chosen = self._change_strategy_for(step, project_root)
        if chosen is None:
            return None  # no real, auto-fixable issue — don't invent one
        change_strategy, title = chosen

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
        return self._vet_result(result)

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

    # How many of the top runnable steps carry a generated proof diff. Bounded
    # so a plan with many executable steps stays cheap: only the first few
    # runnable steps actually run a transform; the rest keep their light preview.
    _MAX_PROOFS = 3

    @staticmethod
    def _diff_and_verdict(result, project_root: str) -> dict | None:
        """Turn an in-memory patch result into a PROOF: the exact draft diff
        (computed, not applied), its +added/−removed line stats, and a
        deterministic ``reparses`` verdict (the transformed source still
        parses with ``ast.parse``).

        Pure: parse + diff + count, no file writes, no subprocess. Returns
        None when the result carries nothing to draft.
        """
        import ast
        import difflib

        from app.engine.transform_impact import measure_impact, summarize

        requests = getattr(result, "patch_requests", None) or []
        if not requests:
            return None
        root = Path(project_root)
        diff_parts: list[str] = []
        impact_parts: list[str] = []
        added = removed = 0
        reparses = True
        for pr in requests:
            rel = pr.get("path", "")
            new = pr.get("new_content", "") or ""
            fp = root / rel
            try:
                old = fp.read_text(encoding="utf-8") if fp.exists() else ""
            except OSError:
                old = ""
            diff = "".join(difflib.unified_diff(
                old.splitlines(keepends=True), new.splitlines(keepends=True),
                fromfile=f"a/{rel}", tofile=f"b/{rel}",
            ))
            diff_parts.append(diff or f"(new file) b/{rel}")
            for ln in diff.splitlines():
                if ln.startswith("+") and not ln.startswith("+++"):
                    added += 1
                elif ln.startswith("-") and not ln.startswith("---"):
                    removed += 1
            # The honest, cheap safety proof: does the transformed source still
            # parse? Only .py content is parse-checked; anything else can't
            # claim a parse verdict, so it doesn't get to vouch "reparses".
            if rel.endswith(".py"):
                try:
                    ast.parse(new)
                except SyntaxError:
                    reparses = False
                else:
                    # Proof of VALUE: quantify the before→after improvement
                    # (max nesting / complexity / cognitive). Empty when the
                    # change doesn't move any metric.
                    summary = summarize(measure_impact(old, new))
                    if summary:
                        impact_parts.append(summary)
        diff_text = "\n".join(diff_parts)
        if not diff_text.strip():
            return None
        return {"diff": diff_text, "added": added, "removed": removed,
                "reparses": reparses, "impact": "; ".join(impact_parts)}

    def prove_step(self, step: ActionStep, project_root: str) -> dict | None:
        """The proof a runnable step carries: the EXACT draft diff it would make
        plus a deterministic safety verdict — recommend-only, never applied.

        Reuses the existing dry-run/draft generator (``_generate`` →
        ``SemanticPatchGenerator``, the same in-memory path ``dry_run_plan``
        uses) so the diff is the real one, computed against the current file
        without writing anything. Returns None when the generator finds nothing
        to change (or declines), so the step stays proofless and graceful.
        """
        try:
            result = self._generate(step, project_root)
        except Exception:
            return None
        if result is None:
            return None
        try:
            return self._diff_and_verdict(result, project_root)
        except Exception:
            return None

    def attach_proofs(self, plan: ActionPlan, project_root: str,
                      max_proofs: int | None = None) -> ActionPlan:
        """Make a plan's top runnable steps PROOF-CARRYING (recommend-only).

        For the first ``max_proofs`` executable steps with a real ``.py``
        target and a mapped transform objective, generate the actual draft diff
        in memory and merge its proof fields (``diff``/``added``/``removed``/
        ``reparses``) into ``patch_preview`` (existing shape preserved). Bounded
        so a large plan stays cheap; deterministic (same plan → same proof
        bytes). A step the generator can't serve is left exactly as-is. Mutates
        and returns the plan for convenience.
        """
        budget = self._MAX_PROOFS if max_proofs is None else max_proofs
        proven = 0
        for step in plan.steps:
            if proven >= budget:
                break
            if not (step.executable and step.target
                    and step.target.endswith(".py")
                    and step.action_type in self._ACTION_STRATEGY):
                continue
            proof = self.prove_step(step, project_root)
            if proof is None:
                continue
            base = dict(step.patch_preview) if step.patch_preview else {}
            base.update(proof)
            base.setdefault("applied", False)
            step.patch_preview = base
            proven += 1
        return plan

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
        gate_block = self._safety_gate_block(perms, patch_requests, project_root,
                                             run_tests)
        if gate_block is not None:
            return gate_block

        snapshot, applied = self._write_patches(project_root, patch_requests)
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
            impact = self._measure_applied_impact(snapshot, patch_requests,
                                                  applied.changed_files)
            if impact:
                out["impact"] = impact
        if not (verify and applied.ok and applied.changed_files):
            return out
        return self._verify_or_rollback(project_root, out, snapshot,
                                        patch_requests, applied)

    @staticmethod
    def _safety_gate_block(perms, patch_requests: list[dict], project_root: str,
                           run_tests: bool) -> dict | None:
        """The blocked-result dict when SafetyGates refuse, else None."""
        if not perms.requires_safety_gates:
            return None
        from app.policies.safety_gates import SafetyGates

        changed = [pr.get("path", "") for pr in patch_requests]
        new_code = "\n".join(pr.get("new_content", "") or "" for pr in patch_requests)
        old_code = "\n".join(pr.get("expected_old_content", "") or "" for pr in patch_requests)
        gates = SafetyGates(project_root, max_changed_files=perms.max_changed_files)
        report = gates.check_all(
            changed_files=changed, old_code=old_code, new_code=new_code, skip_test=not run_tests
        )
        if report.blocked:
            return {"applied": False, "reason": "blocked by safety gates", "summary": report.summary}
        return None

    @staticmethod
    def _write_patches(project_root: str, patch_requests: list[dict]):
        """Snapshot originals (for rollback), then write every patch."""
        from app.skills.execution.apply_patch import ApplyPatchSkill, FilePatch

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
        return snapshot, ApplyPatchSkill().run(project_root, patches)

    @staticmethod
    def _verify_or_rollback(project_root: str, out: dict,
                            snapshot: dict[str, str | None],
                            patch_requests: list[dict], applied) -> dict:
        """Run the suite; on red, restore every changed file to its snapshot."""
        from app.engine.proof_of_fix import summarize_test_run
        from app.engine.verification_strength import assess_strength
        from app.skills.execution.run_tests import RunTestsSkill

        summary = RunTestsSkill().run(project_root)
        out["verified"] = bool(summary.ok)
        out["test_commands"] = summary.commands
        out["test_evidence"] = summarize_test_run(summary)
        # How strongly does that green suite vouch for THESE changes?
        new_by_path = {pr.get("path", ""): pr.get("new_content", "") or "" for pr in patch_requests}
        out["verification_strength"] = assess_strength(
            project_root, applied.changed_files, snapshot, new_by_path
        )
        if summary.ok or not summary.commands:
            # Pass (or no test command detected -> nothing to verify against).
            out["rolled_back"] = False
            return out

        # Tests failed -> restore every changed file to its snapshot.
        root = Path(project_root)
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

    @staticmethod
    def _measure_applied_impact(snapshot: dict[str, str | None],
                                patch_requests: list[dict],
                                changed_files: list[str]) -> str:
        """Proof-of-VALUE: the measured before→after metric win of this apply.

        With the pre-patch snapshot and the written content both in hand,
        quantify the structural improvement (max nesting / cyclomatic /
        cognitive / lines) for each changed ``.py`` file and render it as e.g.
        ``"max nesting 3→1, cognitive 6→3"``. Empty string when no metric
        moves or sources are unmeasurable — so callers add nothing in that
        case (byte-identical evidence). Never raises: an impact-measurement
        slip must not break the apply/record.
        """
        try:
            from app.engine.transform_impact import measure_impact, summarize

            new_by_path = {pr.get("path", ""): pr.get("new_content", "") or ""
                           for pr in patch_requests}
            clauses: list[str] = []
            for rel in changed_files:
                if not rel.endswith(".py"):
                    continue
                before = snapshot.get(rel) or ""
                after = new_by_path.get(rel, "")
                clause = summarize(measure_impact(before, after))
                if clause:
                    clauses.append(clause)
            return "; ".join(clauses)
        except Exception:
            return ""

    def _step_preview(self, step: ActionStep, project_root: str) -> dict:
        """One step's dry-run row: a real unified diff, applied to nothing."""
        import difflib

        result = self._generate(step, project_root)
        if result is None:
            return {"branch": step.branch_path, "action": step.action_type,
                    "target": step.target, "applicable": False}
        root = Path(project_root)
        diffs: list[str] = []
        for pr in result.patch_requests:
            rel = pr.get("path", "")
            fp = root / rel
            old = fp.read_text(encoding="utf-8") if fp.exists() else ""
            new = pr.get("new_content", "") or ""
            diff = "".join(
                difflib.unified_diff(
                    old.splitlines(keepends=True), new.splitlines(keepends=True),
                    fromfile=f"a/{rel}", tofile=f"b/{rel}",
                )
            )
            diffs.append(diff or f"(new file) b/{rel}")
        return {
            "branch": step.branch_path, "action": step.action_type,
            "target": step.target, "applicable": True,
            "transform_type": result.transform_type,
            "files": [pr.get("path") for pr in result.patch_requests],
            "diff": "\n".join(diffs),
        }

    def dry_run_plan(self, plan: ActionPlan, project_root: str) -> dict:
        """Preview a maintenance pass without touching the tree.

        For each executable step, generate its patch and produce a real unified
        diff against the current file — so you can see exactly what
        `apply_plan` would change, applied to nothing.
        """
        previews = [self._step_preview(step, project_root)
                    for step in plan.executable_steps()]
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
        test_first: bool = True,
    ) -> dict:
        """Run a whole maintenance pass: apply each executable step in turn,
        verifying + rolling back individually, and return an aggregate summary.

        Steps are processed in plan order (already value-sorted). Each step is
        independent — a rolled-back step does not abort the run. Honors the
        same gating as apply_step (mode + safety + verify).

        TEST-FIRST SHIELD: when ``verify`` and ``test_first`` are on and a
        code fix targets a module NO test references, the pass first generates
        a characterization test for that module (itself verified), then applies
        the fix under its protection — so "verified" never silently means
        "the suite wasn't looking". The shield doesn't add a result row or
        consume ``max_apply``; it's tracked on the step's entry.

        When ``commit`` is set AND the mode permits committing (autonomous),
        each successfully-applied step is committed individually via
        GitAutoCommit, so every change is an isolated, revertible commit.
        """
        run = _MaintenancePass(self, project_root, mode=mode, verify=verify,
                               test_first=test_first, commit=commit)
        for step in plan.executable_steps():
            if max_apply is not None and run.applied >= max_apply:
                break
            run.run_step(step)
        return {
            "mode": mode,
            "verify": verify,
            "commit": run.can_commit,
            "total_executable": len(plan.executable_steps()),
            "applied": run.applied,
            "rolled_back": run.rolled_back,
            "blocked": run.blocked,
            "committed": run.committed,
            "results": run.results,
        }

    def plan_tree(
        self,
        report: IdeaTreeReport,
        mode: str = "supervised",
        top: int | None = None,
        draft: bool = False,
        project_root: str | None = None,
        proof: bool = False,
    ) -> ActionPlan:
        ideas = sorted(report.ideas, key=lambda i: i.value, reverse=True)
        if top is not None:
            ideas = ideas[:top]
        root_for_checks = project_root or report.project_root or ""
        steps: list[ActionStep] = []
        for i in ideas:
            steps.extend(self._expand_idea(i, project_root=root_for_checks))
        steps = self._dedupe_steps(steps)
        if draft:
            self._draft_previews(steps, project_root or report.project_root or ".")
        plan = ActionPlan(
            objective=report.objective,
            project_root=report.project_root,
            mode=mode,
            steps=steps,
            stats=self._plan_stats(steps),
        )
        # Proof-carrying is opt-in (default off) so existing idea sets and
        # plan bytes don't shift; when on, the top runnable steps gain the
        # exact draft diff + a re-parse verdict (recommend-only, bounded).
        if proof:
            self.attach_proofs(plan, root_for_checks or ".")
        return plan

    @staticmethod
    def _filter_steps(steps: list[ActionStep], phase: str | None,
                      top: int | None) -> list[ActionStep]:
        """The --phase / --top narrowing. The phase filter applies to each
        STEP'S own phase, so a convergence idea's Secure sub-step is kept
        under --phase=Secure even though its parent sat in Stabilize."""
        if phase:
            steps = [s for s in steps if s.phase.lower() == phase.lower()]
        if top is not None:
            steps = steps[:top]
        return steps

    @staticmethod
    def _plan_stats(steps: list[ActionStep]) -> dict:
        """The stats block both planners share (single source of truth)."""
        executable = sum(1 for s in steps if s.executable)
        return {
            "total_steps": len(steps),
            "executable_steps": executable,
            "design_tasks": len(steps) - executable,
            "drafted_patches": sum(1 for s in steps if s.patch_preview),
        }

    def _draft_previews(self, steps: list[ActionStep], root: str) -> None:
        """Attach patch previews to executable steps (shared by both planners)."""
        for step in steps:
            if step.executable:
                step.patch_preview = self.draft_patch(step, root)

    def _roadmap_steps(self, report: IdeaTreeReport, roadmap,
                       root_for_checks: str) -> list[ActionStep]:
        """Expand the roadmap's ideas into deduped, phase-ordered steps.

        Convergence ideas carry their own phased sub-steps (a Stabilize test
        before a Secure harden), so they may emit a phase other than where
        the parent idea was placed; other ideas inherit the roadmap phase.
        The final stable sort by canonical phase puts every step in its true
        phase group — preserving test-before-harden order for free, since
        Stabilize precedes Secure.
        """
        idea_by_path = {i.branch_path: i for i in report.ideas}
        steps: list[ActionStep] = []
        for ph in roadmap.phases:
            for item in ph.items:
                idea = idea_by_path.get(item.branch_path)
                if idea is None:
                    continue
                steps.extend(self._expand_idea(idea, default_phase=ph.name,
                                               project_root=root_for_checks))
        steps = self._dedupe_steps(steps)
        from app.engine.idea_roadmap import PHASE_ORDER
        phase_rank = {name: i for i, name in enumerate(PHASE_ORDER)}
        steps.sort(key=lambda s: phase_rank.get(s.phase, len(PHASE_ORDER)))
        return steps

    def plan_roadmap(
        self,
        report: IdeaTreeReport,
        roadmap=None,
        phase: str | None = None,
        mode: str = "supervised",
        top: int | None = None,
        draft: bool = False,
        project_root: str | None = None,
        proof: bool = False,
    ) -> ActionPlan:
        """Plan actions in roadmap order (Stabilize→Secure→Evolve→Refine).

        Unlike ``plan_tree`` (pure value ranking), this sequences steps by the
        roadmap's engineering phases so a guarded ``apply_plan`` builds the
        safety net before changing risky code. ``phase`` restricts the plan to a
        single phase; each step is tagged with the phase it came from.
        """
        from app.engine.idea_roadmap import RoadmapSynthesizer

        roadmap = roadmap or RoadmapSynthesizer().build(report)
        steps = self._roadmap_steps(report, roadmap,
                                    project_root or report.project_root or "")
        # The phase filter applies to each *step's own* phase, so a convergence
        # idea's Secure sub-step is kept under --phase=Secure even though its
        # parent sat in Stabilize (and vice-versa).
        steps = self._filter_steps(steps, phase, top)
        if draft:
            self._draft_previews(steps, project_root or report.project_root or ".")

        from collections import Counter
        phase_counts = dict(Counter(s.phase for s in steps))
        plan = ActionPlan(
            objective=report.objective,
            project_root=report.project_root,
            mode=mode,
            steps=steps,
            stats={
                **self._plan_stats(steps),
                "ordered_by": "roadmap",
                "phase_counts": phase_counts,
            },
        )
        if proof:
            self.attach_proofs(
                plan, project_root or report.project_root or ".")
        return plan


class _MaintenancePass:
    """One ``apply_plan`` run: counters, committer, shield memory, entries.

    Extracted from a 36-branch ``apply_plan`` — the engine's own brief on
    this module named it. Behavior is unchanged; each concern (shield, tier
    gate, convergence, commit bookkeeping) now reads on its own.
    """

    def __init__(self, bridge: IdeaActionBridge, project_root: str, *,
                 mode: str, verify: bool, test_first: bool, commit: bool) -> None:
        from app.policies.mode_policy import ModePolicy, mode_from_string

        self.bridge = bridge
        self.project_root = project_root
        self.mode = mode
        self.verify = verify
        self.test_first = test_first
        self.results: list[dict] = []
        self.applied = self.rolled_back = self.blocked = self.committed = 0
        self.can_commit = False
        self.committer = None
        if commit:
            perms = ModePolicy(mode=mode_from_string(mode)).permissions
            self.can_commit = bool(perms.can_commit)
            if self.can_commit:
                from app.engine.git_auto_commit import GitAutoCommit

                self.committer = GitAutoCommit(project_root)
        self._shield_attempted: set[str] = set()

    def _commit(self, r: dict, action_label: str) -> tuple[bool, str | None]:
        if self.committer is None or not r.get("changed_files"):
            return False, None
        cres = self.committer.commit(changed_files=r["changed_files"],
                                     finding=action_label, action="fix")
        return bool(cres.success), getattr(cres, "commit_hash", None)

    def _shield(self, step: ActionStep) -> dict | None:
        """Generate a characterization test for an unreferenced target
        before fixing it. Returns the shield's apply result, or None when
        no shield is needed/possible."""
        if not (self.test_first and self.verify):
            return None
        target = step.target
        if (step.action_type == "create_test_stub" or not target
                or target in self._shield_attempted):
            return None
        from app.engine.verification_strength import module_referenced_by_suite

        if module_referenced_by_suite(self.project_root, target):
            return None
        self._shield_attempted.add(target)
        shield_step = ActionStep(
            branch_path=f"{step.branch_path}.shield",
            title=f"Shield {target} with a characterization test before fixing it",
            operator="test", subject=target,
            action_type="create_test_stub", target=target, executable=True,
        )
        return self.bridge.apply_step(shield_step, self.project_root,
                                      mode=self.mode, verify=self.verify)

    def _tier_blocked(self, step: ActionStep, tier: int, label: str,
                      shield_result: dict | None) -> bool:
        """RISK TIER GATE: a Tier-1 (behavior-adjacent) fix is only applied
        when the suite actually covers its target — already referenced, or
        just shielded. No coverage and no shield -> blocked, not gambled."""
        if not (tier >= 1 and self.verify and step.target.endswith(".py")):
            return False
        if shield_result and shield_result.get("applied"):
            return False
        from app.engine.verification_strength import module_referenced_by_suite

        if module_referenced_by_suite(self.project_root, step.target):
            return False
        self.blocked += 1
        self.results.append({
            "branch": step.branch_path, "action": step.action_type,
            "operator": step.operator, "label": label,
            "target": step.target, "applied": False, "risk_tier": tier,
            "reason": ("tier-1 fix requires a covering test — none exists "
                       "and no shield test could be generated"),
        })
        return True

    def _converge_harden(self, step: ActionStep, entry: dict) -> None:
        """CONVERGENCE: a harden_security step then fixes EVERY remaining
        auto-fixable issue in the same file (the detection ladder advances
        as each is fixed). Extra verified fixes don't create new rows —
        they're tracked on the step's entry — so one maintenance pass
        cleans the file instead of one fix per pass."""
        extra = 0
        for _ in range(5):
            r2 = self.bridge.apply_step(step, self.project_root,
                                        mode=self.mode, verify=self.verify)
            if not (r2.get("applied") and step.target in (r2.get("changed_files") or [])):
                break
            extra += 1
            ok2, _h2 = self._commit(r2, step.action_type)
            if ok2:
                self.committed += 1
        if extra:
            entry["converged_fixes"] = extra

    def run_step(self, step: ActionStep) -> None:
        from app.execution.risk_tiers import tier_for

        shield_result = self._shield(step)
        tier = tier_for(step.action_type)
        label = step.source_facts[0].split(":")[0].strip() if step.source_facts else ""
        if self._tier_blocked(step, tier, label, shield_result):
            return

        # The first apply classifies the step (applied / rolled-back /
        # blocked), exactly one result row per step.
        r = self.bridge.apply_step(step, self.project_root, mode=self.mode,
                                   verify=self.verify)
        entry = {"branch": step.branch_path, "action": step.action_type,
                 "operator": step.operator, "label": label,
                 "target": step.target, "risk_tier": tier, **r}
        if shield_result is not None and shield_result.get("applied"):
            entry["shield_test"] = (shield_result.get("changed_files") or [""])[0]
            ok_s, _h = self._commit(shield_result, "create_test_stub")
            if ok_s:
                self.committed += 1
        self._record_outcome(step, r, entry)

    def _settle_applied(self, step: ActionStep, r: dict, entry: dict) -> None:
        """Bookkeeping for an applied fix: commit, then harden-converge."""
        self.applied += 1
        ok, h = self._commit(r, step.action_type)
        entry["committed"] = ok
        if ok:
            self.committed += 1
            entry["commit_hash"] = h
        real_fix = step.target in (r.get("changed_files") or [])
        if step.action_type == "harden_security" and real_fix:
            self._converge_harden(step, entry)

    def _record_outcome(self, step: ActionStep, r: dict, entry: dict) -> None:
        """Classify the apply result into exactly one counter + result row."""
        if r.get("rolled_back"):
            self.rolled_back += 1
        elif r.get("applied"):
            self._settle_applied(step, r, entry)
        else:
            self.blocked += 1
        self.results.append(entry)


def _proof_affordance(step: ActionStep) -> str:
    """The compact proof line for a proof-carrying runnable step, or "".

    When ``attach_proofs`` has loaded the step's ``patch_preview`` with the
    exact draft diff stats (``added``/``removed``/``reparses``), surface a
    short, deterministic affordance — the stat + re-parse verdict IS the
    proof; the full diff stays available via ``apex brief <branch>`` so the
    plan itself stays scannable. Steps without proof fields get no line.
    """
    pv = step.patch_preview or {}
    if "diff" not in pv or "added" not in pv or "removed" not in pv:
        return ""
    verdict = ("re-parses cleanly ✓" if pv.get("reparses")
               else "⚠️ re-parse check failed")
    # Proof of value, when the change measurably improves a metric.
    impact = pv.get("impact") or ""
    impact_clause = f", {impact}" if impact else ""
    return (f"    proof: +{pv.get('added', 0)} −{pv.get('removed', 0)}, "
            f"{verdict}{impact_clause} — `apex brief {step.branch_path}` for the full diff")


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
    # Lead with what Apex can concretely carry out vs. what's recommend-only,
    # so the user sees the executable contributions at a glance.
    runnable = sum(1 for s in plan.steps if s.executable)
    total = len(plan.steps)
    lines.append(f"**{runnable} of {total} steps are runnable now** "
                 "(▶ runnable = Apex can apply + test-verify; ✎ advisory = recommend-only)")
    lines.append("")
    for s in plan.steps:
        tag = "🛠️" if s.executable else "📐"
        marker = (
            "▶ runnable — Apex can apply this and verify with your tests "
            "(auto-rollback on failure)"
            if s.executable
            else "✎ advisory — recommend-only"
        )
        phase = f"[{s.phase}] " if s.phase else ""
        lines.append(
            f"- {tag} `{s.branch_path}` {phase}**{s.action_type}** — {s.description}  (v {s.value})"
        )
        lines.append(f"    {marker}")
        if s.patch_preview:
            proof = _proof_affordance(s)
            if proof:
                # A proof-carrying runnable step shows the EXACT change as a
                # compact stat + verdict (the proof); the full diff stays
                # available via the per-step brief, so the plan stays scannable.
                lines.append(proof)
            files = ", ".join(s.patch_preview.get("files", []))
            if files or "transform_type" in s.patch_preview:
                lines.append(
                    f"    ↳ draft `{s.patch_preview.get('transform_type')}` → {files} (preview, not applied)"
                )
        elif not s.executable:
            # Design work isn't a dead end: the brief turns it into a work order.
            lines.append(f"    ↳ work order: `apex brief {s.branch_path}`")
    return "\n".join(lines)


def _applied_fix_line(r: dict) -> str:
    """One applied-fix bullet: what the green suite proves, shield, commit."""
    extra = ""
    if r.get("verified") is True:
        # Say what the green suite actually proves about THIS change.
        level = (r.get("verification_strength") or {}).get("level", "")
        extra += {
            "function": " (tests pass — and name the changed function)",
            "module": " (tests pass — suite references this module)",
            "none": " (tests pass — ⚠️ no test references this module)",
            "test-change": " (tests pass)",
        }.get(level, " (tests pass)")
    if r.get("impact"):
        # Proof-of-value: the measured before→after structural win.
        extra += f" — {r['impact']}"
    if r.get("shield_test"):
        extra += f" 🛡️ shielded first by `{r['shield_test']}`"
    if r.get("committed"):
        extra += f" [commit {r.get('commit_hash', '')}]"
    files = ", ".join(r.get("changed_files", [])) or r.get("target", "")
    return f"- `{r['branch']}` **{r['action']}** — {files}{extra}"


def _result_sections(results: list[dict]) -> list[str]:
    """The Applied / Rolled back / Blocked sections, only when non-empty."""
    sections = (
        ("## ✅ Applied",
         [r for r in results if r.get("applied")],
         _applied_fix_line),
        ("## ↩️ Rolled back (tests failed)",
         [r for r in results if r.get("rolled_back")],
         lambda r: f"- `{r['branch']}` **{r['action']}** — {r.get('target', '')}"),
        ("## ⛔ Blocked / not applicable",
         [r for r in results if not r.get("applied") and not r.get("rolled_back")],
         lambda r: f"- `{r['branch']}` **{r['action']}** — {r.get('reason', '')}"),
    )
    lines: list[str] = []
    for title, rows, fmt in sections:
        if rows:
            lines += [title, *[fmt(r) for r in rows], ""]
    return lines


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
    lines += _result_sections(summary.get("results", []))
    return "\n".join(lines)
