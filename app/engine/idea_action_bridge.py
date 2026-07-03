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
    # W98: the confluence FAMILY SPLIT. A confluence is a "decouple/test before
    # you change" signal, and its two halves route differently: an UNTESTED
    # confluence takes the same grounded first move as every other untested
    # high-leverage module — a safety-net test stub (resolved in _root_action,
    # which reads the fact value's "untested" marker and fires BEFORE this table);
    # a TESTED confluence routes to the proven delegated ``strengthen_tests``
    # lander (its template literally prescribed "add tests"), whose OWN apply-time
    # gate (mutation engine + double-gated oracle; saturated / no killable
    # survivor / red baseline / test-fixture target ⇒ empty plan, disclosed
    # reason) keeps it honest — never a fake-green. The DECOUPLING itself stays a
    # disclosed human design remainder in the description.
    "confluence": ("strengthen_tests",
                   "Strengthen the thin tests on {s} before changing it — several "
                   "independent pressures converge here (the decoupling design "
                   "itself stays a human decision)", True),
    # Co-change test-gap: a PAIR that co-changes but no single test exercises
    # both. The grounded first move is to add a joint test, so route to the
    # existing create_test_stub action (it is a test gap), executable like the
    # other untested signals.
    "cochange-testgap": ("create_test_stub", "Add a test that exercises {s} together — they co-change but nothing tests them jointly", True),
    "sensitive-path": ("harden_security", "Harden the sensitive path {s}", True),
    "security-finding": ("harden_security", "Fix the security findings in {s}", True),
    "correctness-bug": ("harden_security", "Fix the likely logic bug in {s}", True),
    "config": ("design_task", "Make configuration {s} environment-aware", False),
    # W98: flipped from design_task → the delegated ``strengthen_tests`` lander.
    # "Grow capability" is behavior invention (a human design decision — disclosed
    # in the description), but the grounded FIRST move on an entrypoint is to
    # strengthen its tests with mutant-killing assertions before it grows. The
    # lander's OWN apply-time gate (saturated / no killable survivor / no linked
    # test / red baseline / test-fixture target ⇒ empty plan, disclosed reason)
    # is the honesty rail — deliberately NO plan-time probe, because the mutation
    # engine is unaffordable at plan time (matches the A39 deep-nesting /
    # god-class / dead-parameter precedent).
    "entrypoint": ("strengthen_tests",
                   "Strengthen the tests behind entrypoint {s} with mutant-killing "
                   "assertions before growing it (which capability to grow stays a "
                   "human design decision)", True),
    # W98: flipped from design_task → the delegated ``cover_gaps`` lander — the
    # same first move as ``hub-untested`` above: a central module gets a
    # characterization safety-net test BEFORE it evolves (the evolution plan
    # itself stays a disclosed human design remainder). Honest by construction:
    # the plan-time ``_covergaps_unserviceable`` probe calls the lander's OWN
    # gate (existing linked ``tests/test_<stem>.py``, fixture/dunder, nothing
    # honestly characterizable ⇒ empty plan ⇒ executable=False with the disclosed
    # reason), and a qualifying module lands via ``apply_rename``
    # (``impact_scope=True``) + auto-rollback.
    "dependency-hub": ("cover_gaps",
                       "Land a characterization safety-net test for the central "
                       "module {s} — a regression net before it evolves (the "
                       "evolution plan itself stays a human design decision)", True),
    # W98: flipped from design_task → the delegated ``cover_gaps`` lander, same
    # shape as dependency-hub above: pin the symbol-rich module's public behavior
    # with a characterization test before generalizing it (the generalization
    # design itself stays a disclosed human remainder); gated by the same
    # plan-time ``_covergaps_unserviceable`` probe + apply-time auto-rollback.
    "symbol-hub": ("cover_gaps",
                   "Land a characterization test pinning the public behavior of "
                   "the symbol-rich module {s} before generalizing it (the "
                   "generalization design itself stays a human decision)", True),
    # ÇAĞ2-W3: three more design_task rows flip to the SAME delegated
    # ``cover_gaps`` lander as dependency-hub/symbol-hub above — a
    # characterization safety-net test lands FIRST, honest by the IDENTICAL
    # mechanism (the plan-time ``_covergaps_unserviceable`` probe calls the
    # lander's OWN gate; a module it can't characterize downgrades to an
    # honest ``executable=False`` with the disclosed blocker, never a fake
    # claim — ZERO new probe code). Each description NAMES the landed slice
    # (the characterization test) and DISCLOSES the family-specific
    # human-remaining design slice in parentheses — the signal's OWN intent
    # (simplify / spread-knowledge / smooth-the-change-path) is NOT something
    # ``cover_gaps`` performs, so it is never claimed as delivered.
    "complexity-hotspot": ("cover_gaps",
                           "Land a characterization safety-net test for the "
                           "complexity hotspot {s} before it's simplified — a "
                           "regression net for the riskiest place to change "
                           "(the simplification itself stays a human design "
                           "decision)", True),
    # Bus-factor / knowledge concentration: the same safety net is the FIRST
    # honest move — whoever inherits the module (not just its one author)
    # gets a pinned behavior to change against; the actual knowledge-spread
    # (docs, pairing, review) has no deterministic transform and stays a
    # disclosed human remainder.
    "knowledge-risk": ("cover_gaps",
                       "Land a characterization safety-net test for the "
                       "knowledge-risk module {s} — a regression net so it "
                       "isn't understood by one author alone (spreading "
                       "the knowledge itself, via docs and pairing, stays "
                       "a human task)", True),
    # Change-frequency hotspot: the busiest module benefits most from a
    # regression net before its NEXT commit; evolving its change path
    # (interfaces, coupling, simplification) is a design judgment with no
    # deterministic transform and stays a disclosed human remainder.
    "churn-hotspot": ("cover_gaps",
                      "Land a characterization safety-net test for the "
                      "churn hotspot {s} — a regression net for the module "
                      "changing most before its next commit (smoothing "
                      "the change path itself — interfaces, coupling — "
                      "stays a human design decision)", True),
    "missing-ci": ("add_ci", "Add a CI workflow that runs the test suite", True),
    # Polyglot hotspot: a large, active NON-Python file. Apex has NO deterministic
    # transform for non-Python source, so this is strictly recommend-only — it must
    # NOT claim to be executable.
    "polyglot-hotspot": ("design_task",
                         "Review/cover {s} in your stack — it's outside Apex's "
                         "Python analysis but it's a large, active file", False),
    # Incomplete protocol: a half-built Python contract. The signal covers TWO
    # gap shapes and only ONE is deterministically completable, so this is a
    # SPLIT-honesty flip: (a) an ``__eq__``-without-``__hash__`` class is the
    # CANONICAL, deterministically-completable gap — ``seal_hashable_eq`` restores
    # the canonical ``__hash__`` over the SAME pure-copy field set ``__eq__`` ranges
    # over (re-enabling set/dict-key use that currently raises ``TypeError``), and
    # its refusal set already blocks anything ambiguous (a ``@dataclass``, a
    # ``__hash__ = None`` deliberate-unhashable, a non-``object`` base, an
    # assignment-bound ``__eq__``, an unenumerable field set) — so this is
    # EXECUTABLE: the delegated ``seal_hashable_eq`` lander strips the ``::Class``
    # suffix to the module rel and lands through ``apply_rename(impact_scope=True)``
    # with auto-rollback. (b) A ``__enter__``/``__exit__`` (or async) context-manager
    # gap has NO deterministic completion (what does ``__exit__`` release? = a DESIGN
    # decision), so it routes to ``seal_hashable_eq``, finds NO eligible eq/hash
    # class, and stays an HONEST no-op (empty plan, disclosed reason) — never a
    # fabricated ``__exit__`` body. So incomplete-protocol becomes autonomous for the
    # eq/hash gap and stays honest (advisory) for context-manager gaps; the lander
    # runs over the MODULE so it may seal another eligible eq/hash class in the same
    # module too — broader but SAFE (suite-gated + rolled back on any regression).
    "incomplete-protocol": ("seal_hashable_eq",
                            "Complete the eq/hash contract on {s} — synthesize the "
                            "canonical __hash__ over the __eq__ fields", True),
    # Generalizable duplication: near-identical blocks recurring across DISTINCT
    # modules. The parameterization decision is now DETERMINISTIC —
    # ``plan_near_dup_extract`` lifts a constant-/free-name-only-differing group
    # into ONE shared helper (differing leaves become parameters) and BLOCKS with
    # an empty plan on the slightest doubt — so this is EXECUTABLE: the delegated
    # ``dedup_parameterized`` lander runs the objective's own actionable-group gate
    # and lands through ``apply_rename(impact_scope=True)`` with auto-rollback. The
    # ``A + B`` subject is a joined module pair; the lander splits it and matches a
    # group touching EITHER module (an unactionable signal ⇒ honest no-op, never a
    # fake-green).
    "generalizable-duplication": ("dedup_parameterized",
                                  "Extract one shared helper for the cross-module "
                                  "duplication in {s} — parameterize the differing "
                                  "constants/free names into a single function", True),
    # Coordinator (god-module): a module with high fan-OUT (it imports many
    # internal modules) is a coordination chokepoint. Strictly recommend-only
    # (executable False) — and this is PROVEN, not provisional (the Autonomous-39
    # W4 design pass; docs/PROGRESS.md). Unlike god-class (W3a — a single-module
    # @staticmethod promotion that changes NO call site), reducing fan-out means
    # moving code OUT to another module: an inherently CROSS-MODULE move that
    # rewires importers, and on the real flagged coordinators that is not
    # deterministically safe — there is no move-a-FUNCTION primitive (only
    # whole-module ``move_module`` / within-file ``extract_method``); the targets
    # carry many names referenced as bare STRING LITERALS (getattr/monkeypatch,
    # unfollowable once a name changes module) plus dense test-by-path import pins;
    # a cluster extraction risks an import CYCLE the "0 cycles" gate forbids; and
    # WHICH responsibilities to split is a design judgment, not a graph cut. So
    # Apex RECOMMENDS the split and names the module; it must NOT auto-write it
    # (like ``polyglot-hotspot``). Becoming executable would require a cross-module
    # function-move primitive + a whole-program import/usage acyclicity oracle + a
    # deterministic cohesion partition — net-new whole-program analysis, on-mission
    # only if it then LANDS a verified decouple on a real project.
    "coordinator": ("design_task",
                    "Decouple the coordinator module {s} — it imports many "
                    "internal modules; split its responsibilities (Apex names "
                    "the god-module, you design the seams)", False),
    # Deep-nesting: a top-level function whose control flow nests several levels.
    # The COMMON staircase is a leading guard — a function whose whole body is one
    # else-less ``if`` — and inverting that into an early-return is now DETERMINISTIC
    # (``plan_extract_guard_clause`` rewrites only that exact shape and BLOCKS with
    # an empty plan on anything ambiguous), so this is EXECUTABLE: the delegated
    # ``extract_guard_clause`` lander strips the ``::function`` suffix to the module
    # rel and lands through ``apply_rename(impact_scope=True)`` with auto-rollback. A
    # non-guard nesting (loops/conditionals needing inner-block extraction) matches
    # nothing ⇒ honest no-op (never a fake-green); the lander runs over the MODULE so
    # it may flatten guard shapes in its other functions too — broader but SAFE
    # (suite-gated + rolled back on any regression, exactly like W1).
    "deep-nesting": ("extract_guard_clause",
                     "Flatten the deeply-nested function {s} — invert a leading "
                     "guard into an early return", True),
    # God-class: a top-level class with too many methods is a Single-
    # Responsibility violation. The HONEST EXECUTABLE move (Autonomous-39 W3a) is
    # ``promote_staticmethod``: it promotes the class's SELF-FREE methods (those
    # that provably never touch ``self``) to ``@staticmethod`` — a real DECOUPLING
    # step that makes the coupling surface honest WITHOUT changing any call site (a
    # ``@staticmethod`` is still a class attribute, so ``self.m()``/``Cls.m()``/
    # ``inst.m()`` all keep resolving). THE OVER-CLAIM GUARD (the load-bearing
    # honesty): this does NOT reduce the method count or split responsibilities, so
    # the description must NOT claim "decompose into collaborators" — it states what
    # the action DELIVERS (self-free-method promotion, executable now) AND that the
    # full responsibility-split into cohesive collaborators stays a DESIGN task. A
    # god-class with NO self-free method ⇒ an HONEST no-op (the delegated lander
    # finds nothing eligible and yields an empty plan with a disclosed reason —
    # never a fabricated decomposition). The lander runs over the MODULE so it may
    # promote eligible methods in OTHER classes there too — broader but SAFE
    # (suite-gated + rolled back on any regression), and its refusal set blocks
    # override/MRO/dunder/decorated/dynamic methods.
    "god-class": ("promote_staticmethod",
                  "Decouple the god-class {s} — promote its self-free methods to "
                  "@staticmethod (executable now); the full responsibility-split "
                  "into cohesive collaborators remains a design task", True),
    "modernization": ("modernize_comparisons", "Modernize None comparisons in {s}", True),
    "mutable-default": ("fix_mutable_defaults", "Fix mutable default arguments in {s}", True),
    # Behaviour-preserving readability simplifications (pure AST, each re-parses
    # its own output, refuses via None when it can't act safely). They share the
    # idea budget, so they are opt-in seeding signals — but once a seeder emits
    # them, the resulting action is executable: the same guarded, test-verified,
    # auto-rollback apply path as every other transform.
    "merge-nested-if": ("merge_nested_if",
                        "Collapse a redundant nested `if` into one `and` guard in {s}", True),
    "redundant-else": ("redundant_else",
                       "Remove a redundant `else` after a terminating branch in {s}", True),
    "dict-get-default": ("dict_get_default",
                         "Replace `if k in d: ... else:` with `d.get(k, default)` in {s}", True),
    "isinstance-merge": ("isinstance_merge",
                         "Merge consecutive `isinstance` checks into one call in {s}", True),
    "none-compare": ("simplify_none_compare",
                     "Rewrite `== None` / `!= None` to `is` / `is not` in {s}", True),
    "unreachable-code": ("unreachable_cleanup",
                         "Drop statically-unreachable code after return/raise/break in {s}", True),
    # More behaviour-preserving readability simplifications, each backed by a
    # safe, refuse-on-unsafe, self-reparsing AST transform already in the repo
    # (app/execution/semantic/transforms/). They share the idea budget, so a
    # seeder emitting them is opt-in — but once emitted the action is executable
    # through the SAME guarded, test-verified, auto-rollback apply path: the
    # transform returns None when it can't act safely (so an unsafe input simply
    # produces "no applicable patch", never a fabricated change). NONE of these
    # touches logic/correctness — they only spell an equivalent expression more
    # idiomatically.
    "chained-comparison": ("chain_comparison",
                           "Chain `a < b and b < c` into `a < b < c` in {s}", True),
    "set-literal": ("set_literal",
                    "Rewrite `set([...])` as a set literal `{{...}}` in {s}", True),
    "startswith-tuple": ("startswith_tuple",
                         "Collapse an `or`-chain of `startswith`/`endswith` into a "
                         "single tuple call in {s}", True),
    "not-in-simplify": ("not_in_simplify",
                        "Rewrite `not a in b` / `not a is b` to `a not in b` / "
                        "`a is not b` in {s}", True),
    "tuple-membership": ("tuple_membership",
                         "Use a tuple/set membership test instead of an `or`-chain "
                         "of equalities in {s}", True),
    "dict-literal": ("dict_literal",
                     "Rewrite `dict(a=1, b=2)` as a dict literal `{{...}}` in {s}", True),
    "double-not": ("double_not",
                   "Collapse a redundant double negation `not not x` into `bool(x)` "
                   "in {s}", True),
    "swap-via-tuple": ("swap_via_tuple",
                       "Collapse the three-statement temp-variable swap into a "
                       "tuple swap `a, b = b, a` in {s}", True),
    "membership-set": ("membership_set",
                       "Use a set literal for a constant membership test "
                       "`x in {{...}}` in {s}", True),
    "percent-string-concat": ("percent_string_concat",
                              "Constant-fold an adjacent string-literal "
                              "concatenation `\"a\" + \"b\"` in {s}", True),
    "redundant-lambda": ("redundant_lambda",
                         "Drop a trivial forwarding lambda "
                         "`lambda a, b: f(a, b)` -> `f` in {s}", True),
    "augmented-assign": ("augmented_assign",
                         "Combine a self-referential assignment `x = x + 1` into "
                         "`x += 1` in {s}", True),
    "collection-literal": ("collection_literal",
                           "Replace an empty `dict()` / `list()` / `tuple()` "
                           "constructor with its literal `{{}}` / `[]` / `()` "
                           "in {s}", True),
    "fstring-no-placeholder": ("fstring_no_placeholder",
                               "Drop the dead `f` prefix from a placeholder-less "
                               "f-string `f\"text\"` -> `\"text\"` in {s}", True),
    # ``a if a else b`` -> ``a or b`` (the `or`-default idiom), fired ONLY when
    # the ternary's test and true-branch are the SAME side-effect-free expression
    # (Name or attribute chain). The rewrite collapses a double evaluation of
    # ``a`` to a single one, so it is value-identical only for a pure ``a``; the
    # transform refuses (None) on a call/subscript/bool-op test. Distinct from
    # ``ternary-bool`` (bool-literal branches) and every other wired transform.
    "or-default": ("or_default",
                   "Collapse a self-defaulting ternary `a if a else b` into "
                   "`a or b` in {s}", True),
    # Four more behaviour-preserving simplifications, each backed by an on-disk
    # ``plan_<name>(root, rel) -> RenamePlan`` rewrite under ``app/execution/``
    # (rather than an in-memory ``apply``). The bridge adapts them to the SAME
    # refuse-on-unsafe, self-reparsing, test-verified, auto-rollback apply path
    # via ``plan_to_apply`` in ``_simplify_dispatch`` — so once a seeder emits
    # one, the action is genuinely executable, never a recommend-only stub. Each
    # is strictly guarded (an unsafe input yields no patch) and behaviour-
    # preserving; ``merge_isinstance`` is intentionally NOT among them (it is the
    # duplicate of the already-wired ``isinstance-merge``).
    "nested-with": ("combine_nested_with",
                    "Collapse nested `with A:`/`with B:` into one `with A, B:` "
                    "in {s}", True),
    "comprehension": ("simplify_comprehension",
                      "Fold an `out = []` + `for ...: out.append(x)` accumulator "
                      "loop into a list comprehension in {s}", True),
    "use-enumerate": ("use_enumerate",
                      "Rewrite `for i in range(len(seq)): ... seq[i]` to "
                      "`for _, item in enumerate(seq)` in {s}", True),
    "len-comparison": ("simplify_len_comparison",
                       "Rewrite a boolean-context `len(x) == 0` / `> 0` to "
                       "`not x` / `bool(x)` in {s}", True),
    # Seven more on-disk ``plan_<name>(root, rel) -> RenamePlan`` rewrites under
    # ``app/execution/``, adapted by the same ``plan_to_apply`` in
    # ``_simplify_dispatch`` and routed through the IDENTICAL guarded apply path
    # (snapshot → write → verify → auto-rollback). Each is strictly guarded,
    # behaviour-preserving (assert-tuple is a correctness fix), and distinct from
    # every transform above and from the audit's DO-NOT-WIRE duplicates.
    "simplify-bool-return": ("simplify_bool_return",
                             "Collapse `if c: return True / else: return False` "
                             "into `return bool(c)` in {s}", True),
    "ternary-bool": ("simplify_ternary_bool",
                     "Rewrite a `True if c else False` ternary into `bool(c)` "
                     "in {s}", True),
    "dict-get-ternary": ("simplify_dict_get",
                         "Rewrite `x[k] if k in x else d` into `x.get(k, d)` "
                         "in {s}", True),
    "dict-comprehension": ("dict_comprehension",
                           "Fold an `out = {{}}` + `for ...: out[k] = v` "
                           "accumulator loop into a dict comprehension in {s}",
                           True),
    "ordering-negation": ("simplify_negated_comparison",
                          "Rewrite a negated ordering comparison `not a < b` "
                          "into `a >= b` in {s}", True),
    "pointless-pass": ("remove_pointless_pass",
                       "Delete a redundant `pass` statement in {s}", True),
    "assert-tuple": ("fix_assert_tuple",
                     "Fix the always-true `assert (cond, \"msg\")` tuple into "
                     "`assert cond, \"msg\"` in {s}", True),
    # One more on-disk ``plan_simplify_bool_comparison(root, rel) -> RenamePlan``
    # rewrite under ``app/execution/``, adapted by the same ``plan_to_apply`` in
    # ``_simplify_dispatch`` and routed through the IDENTICAL guarded apply path.
    # It drops a redundant equality/identity comparison against a ``True`` /
    # ``False`` literal — but ONLY when the OTHER operand is SYNTACTICALLY
    # guaranteed to evaluate to a real ``bool`` (a ``not ...`` UnaryOp or a
    # ``Compare``), so the ``(a < b) == True`` -> ``a < b`` rewrite is
    # value-preserving. A bare name/attr/call/bool-op is NOT provably bool and is
    # left untouched (``x == True`` -> ``x`` would be unsound for a general ``x``).
    # Distinct from ``none-compare`` (which rewrites ``== None`` -> ``is None`` and
    # never touches bool literals) and from every other wired transform; NOT on
    # the audit's DO-NOT-WIRE list.
    "bool-comparison": ("simplify_bool_comparison",
                        "Drop a redundant `== True` / `is False` comparison "
                        "against a bool literal (provably-bool operand only) "
                        "in {s}", True),
    # Dead-parameter: the transform hands ALREADY EXIST (``plan_param_drop`` via
    # ``apply_rename`` — dry-run/suite-verify/auto-rollback) and were only a
    # supervised CLI muscle (``apex signature drop``). Autonomous-39: flipped from
    # design_task → the delegated ``drop_param`` lander, which rewrites the def
    # WITHOUT the provably-unused parameter AND every in-project KEYWORD call site,
    # gated + auto-rolled-back. The description states EXACTLY what lands (it does
    # NOT over-claim a redesign): drop a provably-unused parameter and rewrite all
    # IN-PROJECT call sites. THE AUTONOMY SOUNDNESS RAIL (the supervised CLI relied
    # on a human to judge external impact): the lander REFUSES a PUBLIC-API function
    # — an external (out-of-project) caller can pass the dead param BY KEYWORD
    # (``lib.func(x, dead=1)``), invisible to the in-project scan and unexercised by
    # the suite (positional + ``**kwargs`` are already blocked, so external-keyword
    # is the residual hole) — so it drops ONLY from a provably NON-public function
    # (private/underscore, or not in ``__all__``), an HONEST no-op otherwise. param
    # _drop's own refuse-set (dead-in-body / positional-block / ``**kwargs``-block /
    # comment-block / sole-top-level) rides through unchanged. SCOPE: top-level
    # functions ONLY (``resolve_sole_definition`` — the dead-param scan keys on a
    # name UNIQUE project-wide), so no method-override/Protocol/ABC LSP hazard
    # arises; the lander runs over the named module, broader-but-safe (suite-gated +
    # auto-rollback) exactly like the W1/W2/W3a/W5 landers.
    "dead-parameter": ("drop_param",
                       "Drop a provably-unused parameter from {s} and rewrite all "
                       "in-project call sites (refuses a public-API function — an "
                       "external caller could still pass it by keyword)", True),
    # The three DEVELOP-GRADE synthesis objectives ``apex plan --concrete`` can
    # already LAND. Unlike the readability simplifications above, these are NOT
    # emitted by the seeder — the bridge augments the action plan with them
    # (``_augment_synthesis_steps``) ONLY for the modules whose own lander
    # predicate proves a change is producible, so the executable claim is honest
    # by construction. These fact labels make the same (action_type, executable)
    # routing testable through the standard ``_FACT_ACTIONS`` path; emitting one
    # from a seeder would also yield a genuinely-executable step.
    #
    # infer-type-hints / dataclassify are pure (no pytest): they dispatch
    # straight to their adapter in ``_simplify_dispatch`` and flow through the
    # SAME guarded apply_step gate (snapshot → write → verify → auto-rollback) as
    # every other transform; each adapter returns None when the real lander would
    # not change the source, so an unsafe/no-op input simply produces no patch.
    "infer-type-hints": ("infer_type_hints",
                         "Add PROVABLE return-type hints to unannotated functions "
                         "in {s} (only types the AST proves; never a guess)", True),
    "dataclassify": ("dataclassify",
                     "Convert a pure boilerplate-`__init__` class in {s} to a "
                     "`@dataclass` (behaviour-equivalent; real `__init__` logic "
                     "is refused)", True),
    # implement-stub is DIFFERENT: its synthesis runs pytest internally and its
    # verify MUST be impact-scoped, so the bridge does NOT route it through the
    # SemanticPatchResult gate — ``apply_step`` delegates it to the proven
    # develop-core apply path (``plan_implement_stub`` + ``apply_rename`` with
    # ``impact_scope=True``). It is surfaced executable ONLY for a module with a
    # genuinely fillable stub (``fillable_stub_modules``), so the claim is honest.
    "implement-stub": ("implement_stub",
                       "Implement the test-pinned stub(s) in {s} — synthesise a "
                       "body that makes their pinned tests pass (refuses ambiguous "
                       "/ unpinned stubs)", True),
    # cover-gaps is the SAME shape as implement-stub: NOT a SemanticPatchResult
    # transform (it writes a brand-new ``tests/test_<stem>.py`` and its verify is
    # impact-scoped), so ``apply_step`` delegates it to the develop-core
    # ``apply_rename`` path (``plan_cover_gaps`` + ``apply_rename`` with
    # ``impact_scope=True``). It is surfaced executable ONLY for a module whose own
    # ``plan_cover_gaps`` produces a non-empty ``new_contents`` (``cover_gaps_modules``),
    # so the claim is honest by construction.
    "cover-gaps": ("cover_gaps",
                   "Write a characterization test for the untested module {s} — "
                   "pins its CURRENT behaviour as a safety net (refuses a module "
                   "that already has a linked test)", True),
    # wire-exports is the SAME shape as cover-gaps: NOT a SemanticPatchResult
    # transform (it rewrites a package ``__init__.py`` and its verify is
    # impact-scoped), so ``apply_step`` delegates it to the develop-core
    # ``apply_rename`` path (``plan_wire_exports`` + ``apply_rename`` with
    # ``impact_scope=True``). It is PURE + an IMPORT ORACLE (no pytest): the real
    # gate is that the candidate ``__init__.py`` subprocess-imports cleanly and
    # every emitted ``__all__`` name resolves. Surfaced executable ONLY for a
    # package whose own ``plan_wire_exports`` produces a non-empty ``new_contents``
    # (``wire_export_packages``), so the claim is honest by construction.
    "wire-exports": ("wire_exports",
                     "Wire the public re-export surface (`__all__` + "
                     "`from .module import Name`) for the package {s} — emits "
                     "exactly the names a clean subprocess import proves resolve "
                     "(refuses an already-wired or namespace package)", True),
    # generate-usage-doc is the SAME shape as wire-exports: NOT a
    # SemanticPatchResult transform (it writes a package's sibling ``USAGE.md`` and
    # its verify is impact-scoped), so ``apply_step`` delegates it to the
    # develop-core ``apply_rename`` path (``plan_generate_usage_doc`` +
    # ``apply_rename`` with ``impact_scope=True``). It is PURE + a DOCTEST ORACLE
    # (no pytest): the real gate is that every ``>>>`` example copied from a
    # docstring runs green against the imported package (an unproven example is
    # omitted, never faked) and the rendered doc's code blocks parse. Surfaced
    # executable ONLY for a package whose own ``plan_generate_usage_doc`` produces a
    # non-empty ``new_contents`` (``generate_usage_doc_packages``), so the claim is
    # honest by construction.
    "generate-usage-doc": ("generate_usage_doc",
                           "Generate USAGE.md from the public API of {s} — "
                           "restates exactly the package's public functions/"
                           "classes, their signatures, docstring summaries, and "
                           "oracle-proven `>>>` examples (refuses a package with "
                           "no public API or an already-current doc)", True),
    # tdd-implement is the SAME delegated shape as implement-stub (its synthesis
    # runs pytest internally and its verify MUST be impact-scoped), so the bridge
    # does NOT route it through the SemanticPatchResult gate — ``apply_step``
    # delegates it to the proven develop-core ``apply_rename`` path
    # (``plan_tdd_implement`` + ``apply_rename`` with ``impact_scope=True``). It is
    # PER-SYMBOL: the subject/target is ``"<module>:<name>"`` for ONE missing
    # function a RED test demands, and it is surfaced executable ONLY for a symbol
    # the lander can actually synthesise a passing function for
    # (``tdd_implementable_symbols``), so the claim is honest by construction.
    "tdd-implement": ("tdd_implement",
                      "Implement the missing function {s} that a RED test calls "
                      "— synthesise a `def` that flips its failing test green "
                      "(refuses an assertion failure or a contract no fixed "
                      "template satisfies)", True),
    # strengthen-tests is the SAME delegated shape as cover-gaps (PER-MODULE): NOT a
    # SemanticPatchResult transform (it writes/extends a module's
    # ``tests/test_<stem>.py`` with a mutant-killing assertion and its verify MUST
    # be impact-scoped), so ``apply_step`` delegates it to the develop-core
    # ``apply_rename`` path (``plan_strengthen_tests`` + ``apply_rename`` with
    # ``impact_scope=True``). Its synthesis runs the MUTATION ENGINE + a DOUBLE-GATE
    # oracle (the appended assertion must pass on the real code AND fail against the
    # specific surviving mutant it kills), so it is surfaced executable ONLY for a
    # module whose own ``plan_strengthen_tests`` produces a non-empty ``new_contents``
    # (``strengthenable_modules``), so the claim is honest by construction.
    "strengthen-tests": ("strengthen_tests",
                         "Strengthen the thin tests for {s} — append a "
                         "double-gated assertion that KILLS a surviving mutant the "
                         "current suite misses (refuses a saturated module or a "
                         "survivor no honest literal oracle can kill)", True),
    # modernize is the SAME delegated shape as cover-gaps (PER-MODULE): it rewrites
    # the module's OWN source with behaviour-preserving idiom modernizations
    # (``== None`` → ``is None``, dead ``f`` prefixes, empty-constructor →
    # collection literal). Unlike the single-plan landers it is OBJECTIVE-COMPILER
    # -driven — a campaign of the compiler's tidy transforms — so the bridge
    # delegates it to the develop-core ``apply_rename`` path (``modernize_plan`` +
    # ``apply_rename`` with ``impact_scope=True``): ``modernize_plan`` chains those
    # exact transforms over the module and lands the combined diff. It is surfaced
    # executable ONLY for a module whose own ``modernize_plan`` produces a non-empty
    # ``new_contents`` (``modernizable_modules``), so the claim is honest by
    # construction — an already-modern module yields an empty no-op plan.
    "modernize": ("modernize",
                  "Modernize the idioms in {s} — rewrite `== None`/`!= None` to "
                  "`is`/`is not`, drop dead `f` prefixes, and replace empty "
                  "`dict()`/`list()`/`tuple()` with their literals "
                  "(behaviour-preserving; refuses an already-modern module)", True),
    # dedup-total-return is the SAME delegated shape as cover-gaps (it rewrites the
    # modules carrying an exact-duplicate block whose EVERY exit path returns, lifting
    # it verbatim into one returning helper and replacing each copy with ``return
    # _shared_n(...)``). Its verify MUST be impact-scoped, so ``apply_step`` delegates
    # it to the develop-core ``apply_rename`` path (its lander wrapper +
    # ``apply_rename`` with ``impact_scope=True``). CROSS-MODULE: the target a surfaced
    # step carries is a participating module, and the lander finds the actionable block
    # touching it. Surfaced executable ONLY for a module the objective's OWN gate
    # (``dedup_total_return_modules``) proves participates in a LANDABLE lift, so the
    # claim is honest by construction.
    "dedup-total-return": ("dedup_total_return",
                           "Lift the always-returning exact-duplicate block "
                           "touching {s} into one shared returning helper — each "
                           "copy becomes `return _shared_n(...)` (refuses a "
                           "non-total-return or unsafe block)", True),
    # dedup-parameterized is the SAME delegated shape as dedup-total-return: it
    # rewrites the modules carrying a NEAR-duplicate group (structurally identical,
    # differing only at constant/free-name leaves) into one PARAMETERIZED helper. Its
    # verify MUST be impact-scoped, so ``apply_step`` delegates it to the develop-core
    # ``apply_rename`` path. CROSS-MODULE like dedup-total-return; surfaced executable
    # ONLY for a module the objective's OWN gate (``dedup_parameterizable_modules``)
    # proves participates in a LANDABLE lift, so the claim is honest by construction.
    "dedup-parameterized": ("dedup_parameterized",
                            "Parameterize the near-duplicate group touching {s} "
                            "into one shared helper — its differing constant/name "
                            "leaves become parameters (refuses a group no honest "
                            "parameterization fits)", True),
    # dedup-guarded-return is the SAME delegated shape as dedup-total-return: it
    # rewrites the modules carrying an exact-duplicate block with a guard return
    # AND a live fall-through (the shape both dedup siblings refuse), lifting it
    # verbatim into a sentinel-projecting helper. Its verify MUST be
    # impact-scoped, so ``apply_step`` delegates it to the develop-core
    # ``apply_rename`` path. CROSS-MODULE like its siblings; surfaced executable
    # ONLY for a module the objective's OWN gate (``dedup_guarded_return_modules``)
    # proves participates in a LANDABLE lift, so the claim is honest by
    # construction.
    "dedup-guarded-return": ("dedup_guarded_return",
                             "Lift the guard-returning exact-duplicate block "
                             "touching {s} into one shared helper — fall-through "
                             "is marked by an unforgeable sentinel and each copy "
                             "becomes a call + guard (refuses an unsafe or "
                             "sibling-shaped block)", True),
}


# Action types that are test gaps — for these, a function-grain anchor lets us
# name the actual symbol(s)/line(s) instead of only the module. Anything else
# (harden/imports/design) keeps its module-level phrasing.
_TEST_ACTIONS = frozenset({"create_test_stub"})


# When two candidate steps are within this much value of each other they are a
# near-tie, and the headline tiebreaker (most converging confluence signals
# first) applies. Kept small so only genuinely co-leading steps reorder; the
# surrounding value ranking is otherwise untouched.
_CONFLUENCE_TIE_EPSILON = 0.05


def _confluence_weight(step: ActionStep) -> int:
    """How many independent confluence signals back this step (its "family
    count"). Higher = the dream/confluence lens converges harder on this subject.

    Deterministic and side-effect-free. Reads the step's grounding facts only:

    - a seeder ``confluence:`` root carries ``"… (N signal families converge: …)"``
      — the parsed ``N`` is the family count;
    - a synthesis ``convergence:`` fact carries ``"a+b+c+d"`` — the number of
      ``+``-joined risk dimensions is the family count;
    - any other step's weight is just the number of grounding ``source_facts``
      (usually 1), so a plain idea never out-ranks a real confluence on the tie.
    """
    facts = step.source_facts or []
    best = 0
    for fact in facts:
        label, _, rest = fact.partition(":")
        label = label.strip()
        if label == "confluence":
            # "module (N signal families converge: a, b, c)" -> N
            marker = "signal families converge"
            head = rest.split(marker, 1)[0] if marker in rest else ""
            digits = "".join(ch for ch in head if ch.isdigit())
            best = max(best, int(digits) if digits else rest.count(",") + 1)
        elif label == "convergence":
            # "a+b+c+d" -> 4
            dims = [p for p in rest.split("+") if p.strip()]
            best = max(best, len(dims))
    # No confluence/convergence fact: weight is the count of grounding facts.
    return best if best else len(facts)


def _dream_step_boost(step: ActionStep, dream_boost: dict[str, float] | None) -> float:
    """The dream-confluence priority boost a step earns, by its target MODULE.

    ``dream_boost`` maps a module path → a positive boost for the modules the
    dream has graduated as CONFLUENCES (see ``dream_landing.dream_signal_weight``).
    A step's target is ``module`` or ``module:symbol``, so the module key is the
    part before the first ``:`` — the same split ``objective_compiler`` uses.

    Returns 0.0 for every step when ``dream_boost`` is None/empty (no dream, or a
    step whose module the dream never flagged), so a caller that sorts on this as
    a secondary key leaves the order byte-identical with no dream. Pure, no
    clock/random — a frozen-map lookup."""
    if not dream_boost:
        return 0.0
    module = (step.target or "").split(":", 1)[0]
    return dream_boost.get(module, 0.0)


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


def _stub_slug(raw: str, trim: str, fallback: str) -> str:
    """Identifier-safe slug for a symbol/stem: non-identifier chars -> ``_``,
    edge ``_`` trimmed via ``trim`` (``rstrip``/``strip``), lowercased."""
    cleaned = "".join(c if (c.isalnum() or c == "_") else "_" for c in raw)
    cleaned = cleaned.rstrip("_") if trim == "rstrip" else cleaned.strip("_")
    return cleaned.lower() or fallback


def _stub_header(target: str, module: str, mod_path: str) -> str:
    """The recommend-only stub preamble (subject comment + optional import)."""
    lines = [
        "# Apex-proposed test stub (recommend-only — not applied).",
        f"# Subject: {target or module}",
        f"import {mod_path}  # noqa: F401" if mod_path else "",
        "",
    ]
    return "\n".join([ln for ln in lines if ln is not None]).rstrip()


def _stub_anchor_body(symbol: str, mod_path: str, target: str) -> str:
    """One ``def test_<symbol>_behavior():`` skeleton for a named anchor.

    Keeps the symbol's own underscores (a leading ``_`` is meaningful:
    ``_scan_churn`` -> ``test__scan_churn_behavior``); trailing junk is trimmed.
    """
    slug = _stub_slug(symbol, "rstrip", "symbol")
    return (
        f"def test_{slug}_behavior():\n"
        f"    # TODO: exercise {symbol} in {mod_path or target}.\n"
        f"    assert False, \"write a real assertion for {symbol}\"\n"
    )


def _stub_smoke_body(target: str, module: str) -> str:
    """A single module-level smoke skeleton when no anchor names a symbol."""
    stem = (target or module).rsplit("/", 1)[-1].removesuffix(".py") or "module"
    slug = _stub_slug(stem, "strip", "module")
    return (
        f"def test_{slug}_smoke():\n"
        f"    # TODO: cover {target or module}.\n"
        f"    assert False, \"write a real assertion\"\n"
    )


def _test_stub_body(node, target: str) -> str:
    """A deterministic pytest stub naming the REAL symbol(s) and import path.

    When anchors carry symbols, emit one ``def test_<symbol>_...():`` skeleton
    per anchor referencing the actual module import path; otherwise a single
    module-level smoke stub. Pure text, recommend-only — never written here.
    """
    module = str(getattr(node, "subject", "") or "").split("::", 1)[0]
    mod_path = (target or module).removesuffix(".py").replace("/", ".")
    anchors = _function_anchors(node)
    header = _stub_header(target, module, mod_path)
    if anchors:
        bodies = [
            _stub_anchor_body(str(a.get("symbol") or "").strip(), mod_path, target)
            for a in anchors
        ]
    else:
        bodies = [_stub_smoke_body(target, module)]
    return header + "\n\n\n" + "\n\n".join(bodies)


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

        # Fail CLOSED on a missing/unreadable target: a stub for a module that
        # does not exist would scaffold a test for nothing. The engine only
        # seeds real profiled files, so this never blocks the normal flow.
        if self._read(project_root, target) is None:
            return "target file not found; cannot scaffold"
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

    def _docstring_unserviceable(self, target: str, project_root: str) -> str:
        # Probe the exact transform _generate would run: add_docstring only acts
        # on a parseable Python file that has an UNdocumented function/class/
        # method. A non-.py target, an unparseable file, or a module where every
        # symbol is already documented yields no patch — that is human-review
        # territory, so block it UP FRONT instead of at apply time. Fail CLOSED:
        # a missing/unreadable target (None text) is BLOCKED, never treated as
        # serviceable — otherwise we would scaffold docstrings for a file that
        # does not exist.
        from app.execution.semantic.transforms import docstring as ds

        text = self._read(project_root, target)
        if text is None:
            return "unreadable target; cannot document"
        if ds.apply(target, text, "Document this symbol") is not None:
            return ""
        return "no undocumented Python symbol to document; human review"

    def _covergaps_unserviceable(self, target: str, project_root: str) -> str:
        """Why a characterization test can't land here — "" when it can.

        W98: the plan-time reality probe for the flipped dependency-hub /
        symbol-hub rows. Calls the cover-gaps lander itself (its OWN gate),
        never re-derives it: an empty ``plan_cover_gaps`` plan (already linked
        test / fixture / dunder / nothing honestly characterizable) means the
        step downgrades to an honest ``executable=False`` with the disclosed
        reason. ``plan_cover_gaps`` is the exact per-candidate call
        ``cover_gaps_modules`` makes, so the plan-time cost is bounded and
        already accepted in the synthesis augmentation."""
        from app.execution.cover_gaps import plan_cover_gaps

        plan = plan_cover_gaps(project_root, target)
        if plan.new_contents:
            return ""
        return ("; ".join(plan.blockers)
                or "no cover-gap (already linked test / not characterizable); human review")

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
            "add_docstring": self._docstring_unserviceable,
            "add_ci": self._ci_unserviceable,
            # W98: the cheap delegated lander gets a plan-time probe too — the
            # lander's OWN gate decides (NO probe for strengthen_tests: its
            # mutation engine is unaffordable at plan time; the apply-time gate
            # is the rail there, per the A39 precedent).
            "cover_gaps": self._covergaps_unserviceable,
        }.get(action_type)
        return probe(target, project_root) if probe else ""

    @staticmethod
    def _ci_unserviceable(target: str, project_root: str) -> str:
        """Why a CI cannot be scaffolded right now — "" when it can."""
        from app.execution.ci_scaffold import has_ci

        if has_ci(project_root):
            return "CI already present; nothing to add"
        from app.execution.ci_scaffold import generate_ci_workflow

        if generate_ci_workflow(project_root) is None:
            return "not a recognisably Python project; human review"
        return ""

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
        # Discovery leads are HEURISTIC structural observations, not concrete
        # fixable findings — keep them recommend-only end-to-end so a permuted
        # harden/test operator can never make a structural anomaly masquerade as a
        # real security/coverage fix. The ``::discovery-`` subject suffix marks them.
        if "::discovery-" in idea.subject:
            action_type, executable = "design_task", False
        # Symbol-granular subjects ("mod.py::Class.func") act on the module file;
        # the function name stays in the title/description for the test author.
        file_part = idea.subject.split("::", 1)[0]
        target = file_part if "/" in file_part or file_part.endswith(".py") else ""
        # ``add_ci`` acts on the project, not a source file: its subject is
        # "CI pipeline" (no path), so give it the fixed workflow path as target
        # — keeping the step executable (``bool(target)``) while the actual file
        # is (re)resolved against the real tree in ``_step_targets``.
        if action_type == "add_ci":
            from app.execution.ci_scaffold import CI_WORKFLOW_PATH
            target = CI_WORKFLOW_PATH
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
        # Additive project scaffolding: build a CI gate a project lacks. Like
        # create_test_stub it writes a brand-new file (resolved in
        # ``_step_targets``/``_generate``, not from ``step.target``); listed
        # here so ``_step_targets`` recognises it as a real transform objective.
        "add_ci": ["scaffold continuous integration"],
        "modernize_comparisons": ["modernize none-comparison"],
        "fix_mutable_defaults": ["mutable default argument"],
        "merge_nested_if": ["merge nested if flatten guard"],
        "redundant_else": ["remove redundant else"],
        "dict_get_default": ["dict get default"],
        "isinstance_merge": ["merge isinstance"],
        "simplify_none_compare": ["simplify none-compare"],
        "unreachable_cleanup": ["remove unreachable code"],
        # Newly promoted behaviour-preserving simplifications. Each routes
        # straight to its AST transform via _simplify_dispatch (the strategy
        # hint is only a label for proof/preview rows); listing them here lets
        # _step_targets recognise the action as a real transform objective.
        "chain_comparison": ["chain comparison"],
        "set_literal": ["set literal"],
        "startswith_tuple": ["startswith endswith tuple"],
        "not_in_simplify": ["simplify negated membership"],
        "tuple_membership": ["tuple membership"],
        "dict_literal": ["dict literal"],
        "double_not": ["remove double negation"],
        "swap_via_tuple": ["tuple swap"],
        "membership_set": ["membership set literal"],
        "percent_string_concat": ["fold string literal concat"],
        "redundant_lambda": ["drop forwarding lambda"],
        "augmented_assign": ["combine augmented assignment"],
        "collection_literal": ["empty collection literal"],
        "fstring_no_placeholder": ["drop dead fstring prefix"],
        "or_default": ["self-defaulting ternary to or"],
        # On-disk ``plan_*`` simplifications, adapted to the in-memory dispatch
        # by ``plan_to_apply``. Listed here (like the transforms above) only so
        # ``_step_targets`` recognises the action as a real transform objective;
        # the actual rewrite is chosen in ``_simplify_dispatch``.
        "combine_nested_with": ["combine nested with"],
        "simplify_comprehension": ["accumulator loop to comprehension"],
        "use_enumerate": ["range len index to enumerate"],
        "simplify_len_comparison": ["len comparison to truthiness"],
        # Seven more on-disk ``plan_*`` simplifications, adapted to the in-memory
        # dispatch by ``plan_to_apply``. Listed here (like the transforms above)
        # only so ``_step_targets`` recognises the action as a real transform
        # objective; the actual rewrite is chosen in ``_simplify_dispatch``.
        "simplify_bool_return": ["bool return simplification"],
        "simplify_ternary_bool": ["ternary bool to bool call"],
        "simplify_dict_get": ["dict get ternary"],
        "dict_comprehension": ["accumulator loop to dict comprehension"],
        "simplify_negated_comparison": ["negated ordering comparison"],
        "remove_pointless_pass": ["remove redundant pass"],
        "fix_assert_tuple": ["fix always-true assert tuple"],
        # One more on-disk ``plan_*`` simplification, adapted to the in-memory
        # dispatch by ``plan_to_apply``. Listed here (like the transforms above)
        # only so ``_step_targets`` recognises the action as a real transform
        # objective; the actual rewrite is chosen in ``_simplify_dispatch``.
        "simplify_bool_comparison": ["drop bool-literal comparison"],
        # The three develop-grade synthesis objectives. ``infer_type_hints`` and
        # ``dataclassify`` are pure: each dispatches to its adapter in
        # ``_simplify_dispatch`` (the strategy hint is only a proof/preview
        # label). ``implement_stub`` is NOT a SemanticPatchResult transform —
        # ``apply_step`` delegates it to the develop-core ``apply_rename`` path —
        # but it is listed here so ``_step_targets`` recognises it as a real
        # transform objective (a .py target → ``[step.target]``).
        "infer_type_hints": ["infer provable return type hints"],
        "dataclassify": ["convert boilerplate init to dataclass"],
        "implement_stub": ["implement test-pinned stub body"],
        # cover-gaps, like implement_stub, is NOT a SemanticPatchResult transform
        # — ``apply_step`` delegates it to the develop-core ``apply_rename`` path.
        # Listed here so ``_step_targets`` recognises it as a real transform
        # objective (a ``.py`` target → ``[step.target]``); the new test file the
        # plan writes is resolved by ``plan_cover_gaps`` itself, not from here.
        "cover_gaps": ["write characterization test for untested module"],
        # wire-exports, like cover_gaps, is NOT a SemanticPatchResult transform —
        # ``apply_step`` delegates it to the develop-core ``apply_rename`` path.
        # Listed here so ``_step_targets`` recognises it as a real transform
        # objective (the package ``__init__.py`` IS a ``.py`` target →
        # ``[step.target]``); the rewritten ``__init__.py`` is produced by
        # ``plan_wire_exports`` itself, not from here.
        "wire_exports": ["wire package public re-exports and __all__"],
        # generate_usage_doc, like wire_exports, is NOT a SemanticPatchResult
        # transform — ``apply_step`` delegates it to the develop-core
        # ``apply_rename`` path. Listed here so ``_step_targets`` recognises it as a
        # real transform objective (the package ``__init__.py`` IS a ``.py`` target
        # → ``[step.target]``); the sibling ``USAGE.md`` the plan writes is produced
        # by ``plan_generate_usage_doc`` itself, not from here.
        "generate_usage_doc": ["generate USAGE.md from the public API"],
        # tdd_implement, like implement_stub, is NOT a SemanticPatchResult transform
        # — ``apply_step`` delegates it to the develop-core ``apply_rename`` path.
        # Its target is ``"<module>:<name>"`` (a missing symbol, not a ``.py`` path),
        # so ``_step_targets`` returns None for it anyway; it is listed here only so
        # the action is recognised as a real (delegated) transform objective. The
        # synthesised module source is produced by ``plan_tdd_implement`` itself.
        "tdd_implement": ["implement the missing function a RED test calls"],
        # strengthen_tests, like cover_gaps, is NOT a SemanticPatchResult transform
        # — ``apply_step`` delegates it to the develop-core ``apply_rename`` path.
        # Listed here so ``_step_targets`` recognises it as a real transform
        # objective (a ``.py`` target → ``[step.target]``); the extended
        # ``tests/test_<stem>.py`` the plan writes is produced by
        # ``plan_strengthen_tests`` itself, not from here.
        "strengthen_tests": ["strengthen thin tests with mutant-killing assertions"],
        # modernize, like strengthen_tests, is NOT a SemanticPatchResult transform
        # — ``apply_step`` delegates it to the develop-core ``apply_rename`` path
        # (it is a campaign of the objective compiler's tidy idiom transforms).
        # Listed here so ``_step_targets`` recognises it as a real transform
        # objective (a ``.py`` target → ``[step.target]``); the modernized module
        # source is produced by ``modernize_plan`` itself, not from here.
        "modernize": ["modernize idioms (none-compare / dead fstring / collection literal)"],
        # dedup-total-return / dedup-parameterized, like modernize, are NOT
        # SemanticPatchResult transforms — ``apply_step`` delegates each to the
        # develop-core ``apply_rename`` path. Listed here so ``_step_targets``
        # recognises each as a real transform objective (a ``.py`` target →
        # ``[step.target]``); the multi-module rewrite is produced by the objective's
        # own lander (``plan_dedup_total_return`` / ``plan_near_dup_extract``), not
        # from here.
        "dedup_total_return": ["lift always-returning exact-duplicate block to shared helper"],
        "dedup_guarded_return": ["lift guard-return+fall-through exact-duplicate block to sentinel-projecting helper"],
        "dedup_parameterized": ["parameterize near-duplicate group into shared helper"],
        # promote_staticmethod (Autonomous-39 W3a, the honest god-class flip), like
        # the dedup landers above, is NOT a SemanticPatchResult transform —
        # ``apply_step`` delegates it to the develop-core ``apply_rename`` path.
        # Listed here so ``_step_targets`` recognises it as a real transform
        # objective (a ``.py`` target → ``[step.target]``); the module rewrite is
        # produced by the objective's own lander (``plan_promote_staticmethods``),
        # not from here.
        "promote_staticmethod": ["promote self-free method to staticmethod"],
        # drop_param (Autonomous-39, the honest dead-parameter flip), like the
        # landers above, is NOT a SemanticPatchResult transform — ``apply_step``
        # delegates it to the develop-core ``apply_rename`` path. Listed here so
        # ``_step_targets`` recognises it as a real transform objective (a ``.py``
        # target → ``[step.target]``); the project-wide drop (def header + every
        # in-project keyword call site) is produced by the lander's own
        # ``plan_param_drop`` (with the public-API refusal), not from here.
        "drop_param": ["drop a provably-unused parameter project-wide"],
    }

    # Behaviour-preserving readability simplifications dispatched STRAIGHT to
    # their AST transform module: action_type -> transform.apply.
    #
    # Each transform is a pure ``apply(rel_path, source, title)`` that re-parses
    # its own output and returns ``None`` when it cannot act safely — exactly the
    # refuse-on-unsafe contract the existing transforms use. They run through the
    # SAME ``apply_step`` gate (mode policy, SafetyGates, snapshot + verify +
    # auto-rollback) as every other transform; the bridge only chooses *which*
    # transform to invoke, it never bypasses the safety path. These are
    # registered as executable because every one is a behaviour-preserving,
    # self-verifying simplification.
    @classmethod
    def _simplify_dispatch(cls):
        # All on-disk ``plan_<name>`` transforms come from the single shared
        # binding module (``app.execution._plan_transforms``), referenced as
        # ``_pt.plan_<name>``. This replaces the former per-transform import list
        # (consolidated here and in ``simplification_scan`` to drain the
        # duplicate-window metric); the callables are the SAME function objects.
        from app.execution import _plan_transforms as _pt
        from app.tools.simplification_scan import plan_to_apply
        # One namespace import of the transforms package replaces the former
        # per-transform import list (consolidated here and in
        # ``simplification_scan`` to drain the duplicate-window metric). The
        # package ``__init__`` eagerly binds each submodule, so ``_t.<name>``
        # resolves; the dispatch below references the exact same callables.
        from app.execution.semantic import transforms as _t

        return {
            "merge_nested_if": _t.merge_nested_if.apply,
            "redundant_else": _t.redundant_else.apply,
            "dict_get_default": _t.dict_get_default.apply,
            "isinstance_merge": _t.isinstance_merge.apply,
            "simplify_none_compare": _t.simplify_comparison.apply,
            "unreachable_cleanup": _t.unreachable_cleanup.apply,
            # Newly promoted: each carries the SAME refuse-on-unsafe,
            # self-reparsing, behaviour-preserving contract as the six above.
            # Dispatched straight to its AST transform and vetted through the
            # IDENTICAL apply_step gate (mode policy -> SafetyGates -> snapshot
            # -> write -> test-verify -> auto-rollback); the bridge only chooses
            # WHICH transform, it never bypasses the safety path.
            "chain_comparison": _t.chained_comparison.apply,
            "set_literal": _t.set_literal.apply,
            "startswith_tuple": _t.startswith_tuple.apply,
            "not_in_simplify": _t.not_in_simplify.apply,
            "tuple_membership": _t.tuple_membership.apply,
            "dict_literal": _t.dict_literal.apply,
            "double_not": _t.double_not.apply,
            "swap_via_tuple": _t.swap_via_tuple.apply,
            "membership_set": _t.membership_set.apply,
            "percent_string_concat": _t.percent_string_concat.apply,
            "redundant_lambda": _t.redundant_lambda.apply,
            # Two more pure 3-arg ``apply(rel, src, title)`` transforms (no
            # adapter needed): collection_literal rewrites an empty
            # constructor to its literal; fstring drops a placeholder-less
            # `f` prefix only after proving the result parses to the same
            # string. Both refuse via None on anything they can't act on.
            "collection_literal": _t.collection_literal.apply,
            "fstring_no_placeholder": _t.fstring.apply,
            # ``a if a else b`` -> ``a or b`` (pure self-defaulting ternary only):
            # a pure 3-arg ``apply`` that re-parses its own output and refuses via
            # None on any non-pure test. Same guarded apply_step gate as the rest.
            "or_default": _t.or_default.apply,
            # ``augmented_assign.apply`` has a 2-arg signature (no ``title``);
            # adapt it so the dispatch stays uniform. Without this the 3-arg
            # call in _simplify_generate would raise TypeError (swallowed to
            # None), making the step silently un-runnable — exactly the hollow
            # "executable" the brief forbids.
            "augmented_assign": (lambda rel, src, _title:
                                 _t.augmented_assign.apply(rel, src)),
            # Two develop-grade PURE synthesis transforms, adapted to the uniform
            # 3-arg ``apply(rel, src, title)`` shape. Each calls the lander's OWN
            # pure source→source function and builds a SemanticPatchResult only on
            # a CHANGED source (None on unchanged/refused), so the executable
            # claim is honest and the step flows through the IDENTICAL guarded
            # apply_step gate (snapshot → write → verify → auto-rollback).
            #
            # infer_type_hints drives ``infer_annotations`` — the DEVELOP-GRADE
            # provable-return inference (NOT the shallow ``type_annotations.apply``
            # that only stamps ``-> None`` on the first function).
            "infer_type_hints": cls._infer_type_hints_apply,
            # dataclassify drives ``rewrite_dataclasses``, with the develop loop's
            # fixture-path guard ported in so the bridge never offers to rewrite a
            # test/fixture file the lander would itself refuse.
            "dataclassify": cls._dataclassify_apply,
            # Four on-disk ``plan_<name>(root, rel) -> RenamePlan`` rewrites
            # under ``app/execution/``, adapted by ``plan_to_apply`` to the same
            # ``apply(rel, src, title) -> SemanticPatchResult | None`` shape (it
            # materialises the source, runs the real plan, and translates the
            # RenamePlan; a no-op/blocked plan → None). Each then flows into the
            # IDENTICAL guarded apply_step gate (mode policy → SafetyGates →
            # snapshot → write → test-verify → auto-rollback). All four are
            # strictly guarded, behaviour-preserving simplifications;
            # ``merge_isinstance`` is excluded as a duplicate of the already-
            # wired ``isinstance-merge`` above.
            "combine_nested_with": plan_to_apply(_pt.plan_combine_nested_with),
            "simplify_comprehension": plan_to_apply(_pt.plan_simplify_comprehension),
            "use_enumerate": plan_to_apply(_pt.plan_use_enumerate),
            "simplify_len_comparison": plan_to_apply(_pt.plan_simplify_len_comparison),
            # Seven more on-disk ``plan_<name>(root, rel) -> RenamePlan``
            # rewrites under ``app/execution/``, each adapted by the SAME
            # ``plan_to_apply`` (materialise source → run real plan → translate
            # the RenamePlan; a no-op/blocked plan → None) and flowed through the
            # IDENTICAL guarded apply_step gate. Each is strictly guarded and
            # distinct: bool-return / ternary-bool collapse boolean if/ternary
            # forms to ``bool(c)``; dict-get-ternary → ``x.get(k, d)``;
            # dict-comprehension folds a dict accumulator; negated-comparison
            # inverts ORDERING ops only (not equality/membership/identity, so it
            # is not a duplicate of double_not / fix_not_in_is);
            # remove_pointless_pass deletes a redundant ``pass``; fix_assert_tuple
            # is a correctness fix for the always-true ``assert (cond, "msg")``.
            "simplify_bool_return": plan_to_apply(_pt.plan_simplify_bool_return),
            "simplify_ternary_bool": plan_to_apply(_pt.plan_simplify_ternary_bool),
            "simplify_dict_get": plan_to_apply(_pt.plan_simplify_dict_get),
            "dict_comprehension": plan_to_apply(_pt.plan_dict_comprehension),
            "simplify_negated_comparison":
                plan_to_apply(_pt.plan_simplify_negated_comparison),
            "remove_pointless_pass": plan_to_apply(_pt.plan_remove_pointless_pass),
            "fix_assert_tuple": plan_to_apply(_pt.plan_fix_assert_tuple),
            # One more on-disk ``plan_simplify_bool_comparison(root, rel) ->
            # RenamePlan`` rewrite, adapted by the SAME ``plan_to_apply``
            # (materialise source → run real plan → translate the RenamePlan; a
            # no-op/blocked plan → None) and flowed through the IDENTICAL guarded
            # apply_step gate. It drops a redundant ``== True`` / ``is False``
            # comparison against a bool literal ONLY when the other operand is
            # syntactically provably-bool (a ``not ...`` or a ``Compare``), so the
            # rewrite is value-preserving; it is distinct from ``simplify_none_compare``
            # (which never touches bool literals).
            "simplify_bool_comparison": plan_to_apply(_pt.plan_simplify_bool_comparison),
        }

    @staticmethod
    def _synthesis_result(rel_path: str, source: str, new_source: str | None,
                          transform_type: str, rationale: str):
        """A ``SemanticPatchResult`` for a develop-grade pure transform, or None.

        The shared honesty spine of the two pure synthesis adapters: build a
        result ONLY when the lander's own source→source function returned a
        CHANGED source (``new_source`` is not None and differs). An unchanged /
        refused source yields None, so the apply gate's ``_vet_result`` drops it
        and the step never claims a patch it cannot produce."""
        if new_source is None or new_source == source:
            return None
        from app.execution.semantic.result import SemanticPatchResult

        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": new_source,
                "expected_old_content": source,
            }],
            transform_type=transform_type,
            rationale=[rationale.format(rel=rel_path)],
        )

    @classmethod
    def _infer_type_hints_apply(cls, rel_path: str, source: str, _title: str):
        """Adapter: the DEVELOP-GRADE provable-return inference as a uniform
        ``apply(rel, src, title)`` transform.

        Calls :func:`infer_annotations` (the pure source→source inference the
        ``infer-type-hints`` objective composes — NOT the shallow ``-> None``
        ``type_annotations.apply``) and returns its real patch only on a changed
        source. ``infer_annotations`` itself returns None on a syntax error or
        when nothing provable changes, so an unsafe/no-op input yields no patch."""
        from app.execution.semantic.transforms.type_annotations import (
            infer_annotations,
        )
        return cls._synthesis_result(
            rel_path, source, infer_annotations(source), "infer-type-hints",
            "Added provable return-type annotation(s) in {rel}.")

    @classmethod
    def _dataclassify_apply(cls, rel_path: str, source: str, _title: str):
        """Adapter: the boilerplate-``__init__`` → ``@dataclass`` rewrite as a
        uniform ``apply(rel, src, title)`` transform.

        Calls :func:`rewrite_dataclasses` and returns its real patch only on a
        changed source. The pure ``rewrite_dataclasses`` does NOT refuse
        test/fixture files, so the develop loop's fixture-path guard is ported in
        here (mirroring ``app/execution/objectives/dataclassify._is_fixture_path``)
        — the bridge must never offer to rewrite a file the develop loop would
        itself refuse."""
        if cls._is_fixture_path(rel_path):
            return None  # never offer to rewrite a test/fixture file
        from app.execution.dataclass_rewrite import rewrite_dataclasses
        return cls._synthesis_result(
            rel_path, source, rewrite_dataclasses(source), "dataclassify",
            "Converted a boilerplate-`__init__` class to `@dataclass` in {rel}.")

    @staticmethod
    def _is_fixture_path(path: str) -> bool:
        """Example/test/fixture files are REFUSED — a faithful local copy of the
        develop loop's own guard (``objectives/dataclassify._is_fixture_path``)
        so the bridge's dataclassify adapter refuses exactly what the lander
        would, never offering a rewrite the develop loop would decline."""
        p = path.replace("\\", "/").lower()
        name = Path(p).name
        return (
            p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
            or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
            or name.startswith("test_") or name.endswith("_test.py")
            or name == "conftest.py"
        )

    @staticmethod
    def _read(project_root: str, rel_path: str) -> str | None:
        try:
            return (Path(project_root) / rel_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # A non-UTF-8 / near-binary file is unreadable as source, not a
            # crash: decline (None) so the caller skips it gracefully.
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
        "os.popen": "Apex: os.popen",
        "tls-verify": "Apex: TLS verification",
        "zip-slip": "Apex: Zip-Slip",
    }

    # The three pure-ANNOTATION security findings (security label -> the
    # comment-only transform_type the harden ladder emits for it). Each only
    # inserts a ``# SECURITY`` comment and leaves the dangerous call intact, so
    # the fix is Tier 0 (see ``risk_tiers.ANNOTATION_FLAG_TRANSFORMS``). The tier
    # gate reads this to give a comment-only harden the additive treatment while
    # a behaviour-CHANGING harden (eval/yaml) on the same action stays Tier 1.
    _ANNOTATION_FLAG_BY_LABEL = {
        "tls-verify": "flag_tls_verify",
        "pickle": "flag_pickle_loads",
        "sql": "flag_sql_injection",
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
    def _prospective_transform_type(cls, project_root: str,
                                    step: ActionStep) -> str | None:
        """The concrete transform_type a ``harden_security`` step will emit next,
        when that fix is a pure-annotation security flag (else None).

        Lets the tier gate price a comment-only harden (``flag_tls_verify`` /
        ``flag_pickle_loads`` / ``flag_sql_injection``) as the Tier-0 additive
        change it is — WITHOUT running the apply. A behaviour-changing harden
        (eval/yaml) resolves to None here and keeps its Tier-1 coverage gate.
        Cheap and read-only: it reuses ``_detect_security_issue`` (which already
        runs as part of strategy selection) and a static label map.
        """
        if step.action_type != "harden_security" or not step.target.endswith(".py"):
            return None
        label = cls._detect_security_issue(project_root, step.target)
        return cls._ANNOTATION_FLAG_BY_LABEL.get(label or "")

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
        # ``add_ci`` scaffolds a non-``.py`` project file, so it is resolved
        # before the Python-target guard: the workflow path when the project
        # can take one, else None (already has CI / not a Python project).
        if step.action_type == "add_ci":
            return self._ci_target(project_root)
        if not step.target or not step.target.endswith(".py"):
            return None
        if step.action_type == "create_test_stub":
            return self._stub_target(step, project_root)
        return [step.target]

    @staticmethod
    def _ci_target(project_root: str) -> list[str] | None:
        """The CI workflow path to create, or None when none should be added
        (the project already has CI, or does not look like Python)."""
        from app.execution.ci_scaffold import CI_WORKFLOW_PATH, generate_ci_workflow

        return [CI_WORKFLOW_PATH] if generate_ci_workflow(project_root) else None

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

        # ``implement_stub`` / ``cover_gaps`` do NOT fit the SemanticPatchResult
        # gate: each is delegated to the develop-core ``apply_rename`` path instead
        # (implement_stub's synthesis runs pytest and its verify must be
        # impact-scoped; cover_gaps writes a brand-new test file with an
        # impact-scoped verify). The SemanticPatchResult-based ``_generate`` (used
        # by draft_patch / attach_proofs) has no patch to offer here — return None
        # so those preview surfaces show nothing rather than fabricating one.
        if step.action_type in self._DELEGATED_ACTIONS:
            return None

        # ``add_ci`` is not an AST rewrite of an existing file — it scaffolds a
        # new workflow file. Route it to its dedicated additive generator, which
        # returns into the IDENTICAL guarded apply gate as any other patch.
        if step.action_type == "add_ci":
            from app.execution.ci_scaffold import generate_ci_workflow

            return self._vet_result(generate_ci_workflow(project_root))

        # Behaviour-preserving simplifications dispatch straight to their AST
        # transform (the generator's EditStrategy doesn't route them), then
        # return into the IDENTICAL apply_step gate as any other transform.
        simplify = self._simplify_dispatch().get(step.action_type)
        if simplify is not None:
            return self._simplify_generate(simplify, target_files[0], project_root)

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

    def _simplify_generate(self, apply, rel_path: str, project_root: str):
        """Run a behaviour-preserving simplification transform on ``rel_path``.

        Reads the current file, calls the transform's ``apply(rel_path, source,
        title)`` (which re-parses its own output and returns ``None`` when it
        cannot act safely), and vets the result through the same gate every
        generated patch passes. Returns a ``SemanticPatchResult`` or ``None`` —
        never raises, never writes (the caller's ``apply_step`` does the guarded
        write + verify + rollback)."""
        source = self._read(project_root, rel_path)
        if source is None:
            return None
        try:
            result = apply(rel_path, source, f"Simplify {rel_path}")
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
    def _read_old(root: Path, rel: str) -> str:
        """The current on-disk source for ``rel`` ("" when absent/unreadable)."""
        fp = root / rel
        try:
            return fp.read_text(encoding="utf-8") if fp.exists() else ""
        except OSError:
            return ""

    @staticmethod
    def _unified_diff(old: str, new: str, rel: str) -> str:
        """The computed (never applied) unified diff for one changed file."""
        import difflib

        diff = "".join(difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f"a/{rel}", tofile=f"b/{rel}",
        ))
        return diff

    @staticmethod
    def _count_changes(diff: str) -> tuple[int, int]:
        """(+added, -removed) hunk lines, ignoring the ``+++``/``---`` headers."""
        added = removed = 0
        for ln in diff.splitlines():
            if ln.startswith("+") and not ln.startswith("+++"):
                added += 1
            elif ln.startswith("-") and not ln.startswith("---"):
                removed += 1
        return added, removed

    @staticmethod
    def _py_verdict(old: str, new: str) -> tuple[bool, str]:
        """(reparses, impact-summary) for transformed ``.py`` content.

        The honest, cheap safety proof: does the source still ``ast.parse``?
        When it does, quantify the before→after improvement (empty if no metric
        moved); a parse failure yields no impact and a False verdict.
        """
        import ast

        from app.engine.transform_impact import measure_impact, summarize

        try:
            ast.parse(new)
        except (SyntaxError, RecursionError, MemoryError):
            return False, ""
        return True, summarize(measure_impact(old, new))

    @staticmethod
    def _diff_and_verdict(result, project_root: str) -> dict | None:
        """Turn an in-memory patch result into a PROOF: the exact draft diff
        (computed, not applied), its +added/−removed line stats, and a
        deterministic ``reparses`` verdict (the transformed source still
        parses with ``ast.parse``).

        Pure: parse + diff + count, no file writes, no subprocess. Returns
        None when the result carries nothing to draft.
        """
        requests = getattr(result, "patch_requests", None) or []
        if not requests:
            return None
        root = Path(project_root)
        diff_parts: list[str] = []
        impact_parts: list[str] = []
        added = removed = 0
        reparses = True
        # Does the green suite actually EXERCISE this change? A passing run on a
        # module no test references is a hollow guarantee — record whether ANY
        # changed .py module is named by a test (pure file scan, no execution).
        covered = False
        for pr in requests:
            part = IdeaActionBridge._diff_one(root, project_root, pr)
            diff_parts.append(part["diff_part"])
            added += part["added"]
            removed += part["removed"]
            reparses = reparses and part["reparses"]
            impact_parts.extend(part["impact_parts"])
            covered = covered or part["covered"]
        diff_text = "\n".join(diff_parts)
        if not diff_text.strip():
            return None
        return {"diff": diff_text, "added": added, "removed": removed,
                "reparses": reparses, "impact": "; ".join(impact_parts),
                "covered": covered}

    @staticmethod
    def _diff_one(root: Path, project_root: str, pr: dict) -> dict:
        """The proof contribution of ONE patch request: its rendered diff part,
        +/- counts, parse verdict, any impact summary, and whether the changed
        ``.py`` module is referenced by the suite. Pure; non-``.py`` files stay
        inert (reparses True, no impact, not covered)."""
        from app.engine.verification_strength import module_referenced_by_suite

        rel = pr.get("path", "")
        new = pr.get("new_content", "") or ""
        old = IdeaActionBridge._read_old(root, rel)
        diff = IdeaActionBridge._unified_diff(old, new, rel)
        added, removed = IdeaActionBridge._count_changes(diff)
        reparses = True
        impact_parts: list[str] = []
        covered = False
        # Only .py content is parse-checked; anything else can't claim a parse
        # verdict or be referenced-by-suite, so it stays inert here.
        if rel.endswith(".py"):
            reparses, summary = IdeaActionBridge._py_verdict(old, new)
            if summary:
                impact_parts.append(summary)
            covered = module_referenced_by_suite(project_root, rel)
        return {"diff_part": diff or f"(new file) b/{rel}",
                "added": added, "removed": removed, "reparses": reparses,
                "impact_parts": impact_parts, "covered": covered}

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
        covered_only: bool = False,
        baseline_failing: frozenset[str] | None = None,
    ) -> dict:
        """Apply an executable step's patch — strictly gated, opt-in.

        Enforces ModePolicy (must allow patching) and SafetyGates (scope,
        sensitive paths, secrets) before writing anything. Report mode can
        never apply.

        When ``verify`` is set, the original file contents are snapshotted
        before writing; after applying, the test suite is run and — if it
        fails — every changed file is restored to its pre-patch content
        (automatic rollback). Returns a result dict describing what happened.

        When ``covered_only`` (the SAFE-by-default autonomous SWEEP, default off
        ⇒ byte-identical), a move whose green suite NO test exercises (``coverage
        == "none"``) is ROLLED BACK and reported ``withheld_uncovered`` instead of
        landed — so a broad sweep never silently lands a change a green suite can't
        vouch for. An explicitly-chosen objective leaves it off.

        ``baseline_failing`` (DEFAULT None ⇒ ABSOLUTE-green, byte-identical) is the
        DELTA-GREEN baseline: the SET of test node ids already RED before this
        maintenance pass touched anything. When threaded (a RED-baseline pass), the
        verified-apply gate KEEPS a fix iff it broke NO previously-green test —
        tolerating the pre-existing reds it did not cause — and DISCLOSES the
        ``delta_green`` narrative; a fix that turns a green test red is STILL rolled
        back (never-fake-green). This is the SAME gate develop threads, so the
        maintain/auto front door lands on a red-baseline repo exactly as develop
        does. ``None`` (a green / suite-less baseline) keeps absolute-green.

        ``implement_stub`` and ``cover_gaps`` are the actions NOT routed through
        the SemanticPatchResult gate (``_DELEGATED_ACTIONS``): implement_stub's
        synthesis runs pytest internally and cover_gaps writes a brand-new test
        file, and both need impact-scoped verify, so each is DELEGATED to the
        proven develop-core ``apply_rename`` path (the same one
        ``objective_compiler`` uses), which restores the tree itself and never
        double-applies.
        """
        from app.policies.mode_policy import ModePolicy, mode_from_string

        policy = ModePolicy(mode=mode_from_string(mode))
        perms = policy.permissions
        if not perms.can_patch:
            return {"applied": False, "reason": f"mode '{mode}' is read-only (cannot patch)"}

        # ``implement_stub`` / ``cover_gaps`` do not fit the in-memory patch gate
        # (implement_stub runs pytest during synthesis; cover_gaps writes a
        # brand-new test file — both need impact-scoped verify); delegate to the
        # develop-core apply path, which owns its own snapshot/verify/rollback.
        if step.action_type in self._DELEGATED_ACTIONS:
            return self._apply_delegated_synthesis(step, project_root, verify,
                                                   covered_only, baseline_failing)

        result = self._generate(step, project_root)
        if result is None:
            return {"applied": False, "reason": "no applicable patch generated"}

        patch_requests = result.patch_requests
        gate_block = self._safety_gate_block(perms, patch_requests, project_root,
                                             run_tests)
        if gate_block is not None:
            return gate_block

        snapshot, applied = self._write_patches(project_root, patch_requests)
        honest_block = self._partial_or_noop_block(
            project_root, snapshot, applied, patch_requests, result.transform_type, mode)
        if honest_block is not None:
            return honest_block
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
        from app.execution.risk_tiers import tier_for
        return self._verify_or_rollback(project_root, out, snapshot,
                                        patch_requests, applied,
                                        tier_for(step.action_type), covered_only,
                                        baseline_failing)

    # The develop-core synthesis objectives that do NOT fit the in-memory
    # SemanticPatchResult gate and are DELEGATED to the proven ``apply_rename``
    # path (the one ``objective_compiler`` uses), keyed by action_type ->
    # (``plan_*`` importer, empty-plan reason). Each importer returns the public
    # ``plan_<name>(project_root, target) -> RenamePlan`` lander; the bridge lands
    # the plan with ``impact_scope=True`` and stamps the action as transform_type.
    # implement_stub's synthesis runs pytest and needs impact-scoped verify;
    # cover_gaps writes a brand-new ``tests/test_<stem>.py`` (purely additive) and
    # its impact-scoped verify runs exactly that new characterization test.
    # wire_exports rewrites a package ``__init__.py``; it is PURE + an IMPORT
    # ORACLE (no pytest), and its register spec is ``scope_verify=True``, so it
    # likewise lands through ``apply_rename`` with ``impact_scope=True`` — the
    # oracle (already run inside ``plan_wire_exports``) is its real gate, and the
    # impact-scoped suite catches collateral breakage in tests that import the
    # wired package (falling back to the full suite when none do).
    # generate_usage_doc is the SAME shape as wire_exports: it writes a package's
    # sibling ``USAGE.md``; it is PURE + a DOCTEST ORACLE (no pytest), so it
    # likewise lands through ``apply_rename`` with ``impact_scope=True`` — the
    # oracle (already run inside ``plan_generate_usage_doc``) is its real gate, and
    # the impact-scoped suite catches collateral breakage in tests that touch the
    # package (falling back to the full suite when none do).
    @staticmethod
    def _plan_implement_stub_lander():
        from app.execution.objectives.implement_stub import plan_implement_stub
        return plan_implement_stub

    @staticmethod
    def _plan_cover_gaps_lander():
        from app.execution.cover_gaps import plan_cover_gaps
        return plan_cover_gaps

    @staticmethod
    def _plan_wire_exports_lander():
        from app.execution.objectives.wire_exports import plan_wire_exports
        return plan_wire_exports

    @staticmethod
    def _plan_generate_usage_doc_lander():
        from app.execution.objectives.generate_usage_doc import (
            plan_generate_usage_doc,
        )
        return plan_generate_usage_doc

    @staticmethod
    def _plan_tdd_implement_lander():
        """The tdd-implement lander adapted to the delegated ``(project_root,
        target)`` shape every other delegated synthesis uses.

        tdd-implement is PER-SYMBOL — its real lander is
        ``plan_tdd_implement(root, missing: MissingSymbol)``, not
        ``(root, rel_path)``. The target carried by the surfaced step is
        ``"<module_rel>:<name>"`` (exactly what the objective's ``moves`` emits and
        what ``tdd_implementable_symbols`` returns), so this wrapper re-runs the
        lander's OWN detector :func:`detect_missing_symbols`, matches the symbol by
        that target, and DELEGATES to the real ``plan_tdd_implement``. An unmatched
        target (the symbol is no longer missing — e.g. already landed in a prior
        step) yields an empty no-op :class:`RenamePlan`, so the delegated apply path
        honestly no-ops rather than fakes a change."""
        from app.execution.cross_file_rename import RenamePlan
        from app.execution.objectives.tdd_implement import (
            detect_missing_symbols,
            plan_tdd_implement,
        )

        def _plan(project_root: str, target: str) -> RenamePlan:
            module_rel, _, name = target.rpartition(":")
            for ms in detect_missing_symbols(project_root):
                if ms.module_rel == module_rel and ms.name == name:
                    return plan_tdd_implement(project_root, ms)
            return RenamePlan(old=module_rel or target, new="tdd-implement")

        return _plan

    @staticmethod
    def _plan_strengthen_tests_lander():
        """The strengthen-tests lander adapted to the delegated ``(project_root,
        target)`` shape every delegated synthesis uses.

        strengthen-tests is PER-MODULE — its real lander is already
        ``plan_strengthen_tests(root, module_rel) -> RenamePlan``, so the target a
        surfaced step carries IS the module rel-path (exactly what the objective's
        ``moves`` emits and what ``strengthenable_modules`` returns), and the lander
        passes straight through. An unmatched / refused target — a non-``.py`` path,
        a test/fixture, a dunder, a module whose tests already kill every mutant
        (saturated), or one whose survivors can't be killed with an honest oracle —
        is REFUSED by the lander itself with an empty no-op :class:`RenamePlan`
        (``new_contents`` is ``{}``), so the delegated apply path honestly no-ops
        rather than fakes a change (never a fake-green)."""
        from app.execution.strengthen_tests import plan_strengthen_tests
        return plan_strengthen_tests

    @staticmethod
    def _plan_modernize_lander():
        """The modernize lander adapted to the delegated ``(project_root, target)``
        shape every delegated synthesis uses.

        modernize is PER-MODULE but OBJECTIVE-COMPILER-driven — it has no single
        ``plan_modernize`` lander; it is a campaign of the objective compiler's tidy
        idiom transforms (``== None`` → ``is None``, dead ``f`` prefixes,
        empty-constructor → collection literal). The grounding layer's
        :func:`idea_synthesis_signals.modernize_plan` DELEGATES to those exact
        transforms — chaining each over the module's own source — and returns a
        :class:`RenamePlan` carrying the combined rewrite. The target a surfaced step
        carries IS the module rel-path (exactly what ``modernizable_modules``
        returns), so it passes straight through. An unmatched / already-modern /
        unreadable target yields an empty no-op :class:`RenamePlan` (``new_contents``
        is ``{}``), so the delegated apply path honestly no-ops rather than fakes a
        change (never a fake-green)."""
        from app.engine.idea_synthesis_signals import modernize_plan
        return modernize_plan

    @staticmethod
    def _unit_touches(unit, target: str) -> bool:
        """True when a dedup unit (a ``DuplicateBlock`` / ``NearDuplicateGroup``)
        has an occurrence in ``target`` — i.e. the module rel-path is the module half
        (``"module:lineno"``) of one of its occurrences. The shared occurrence-matcher
        of the two CROSS-MODULE dedup lander wrappers."""
        return any(
            occ.split(":", 1)[0] == target
            for occ in getattr(unit, "occurrences", []) or []
        )

    @classmethod
    def _plan_dedup_total_return_lander(cls):
        """The dedup-total-return lander adapted to the delegated ``(project_root,
        target)`` shape every delegated synthesis uses.

        dedup-total-return is CROSS-MODULE — its real lander is
        ``plan_dedup_total_return(root, block: DuplicateBlock)``, not
        ``(root, rel_path)`` (a duplicate spans several modules). The target a
        surfaced step carries is a PARTICIPATING module (exactly what
        ``dedup_total_return_modules`` returns), so this wrapper re-runs the objective's
        OWN gate :func:`dedup_total_return._actionable_blocks`, matches the FIRST
        actionable block whose occurrences touch that module, and DELEGATES to the real
        ``plan_dedup_total_return``. An unmatched target (no actionable block touches
        it — e.g. already lifted in a prior step) yields an empty no-op
        :class:`RenamePlan`, so the delegated apply path honestly no-ops rather than
        fakes a change (never a fake-green)."""
        from app.execution.cross_file_rename import RenamePlan
        from app.execution.dedup_total_return import plan_dedup_total_return
        from app.execution.objectives.dedup_total_return import _actionable_blocks

        def _plan(project_root: str, target: str) -> RenamePlan:
            for block in _actionable_blocks(project_root):
                if cls._unit_touches(block, target):
                    return plan_dedup_total_return(project_root, block)
            return RenamePlan(old=target, new="dedup-total-return")

        return _plan

    @classmethod
    def _plan_dedup_guarded_return_lander(cls):
        """The dedup-guarded-return lander adapted to the delegated
        ``(project_root, target)`` shape every delegated synthesis uses.

        dedup-guarded-return is CROSS-MODULE — its real lander is
        ``plan_dedup_guarded_return(root, block: DuplicateBlock)``, not
        ``(root, rel_path)``. The target a surfaced step carries is a
        PARTICIPATING module (exactly what ``dedup_guarded_return_modules``
        returns), so this wrapper re-runs the objective's OWN gate
        :func:`dedup_guarded_return._actionable_blocks`, matches the FIRST
        actionable block whose occurrences touch that module, and DELEGATES to
        the real ``plan_dedup_guarded_return``. An unmatched target (no
        actionable block touches it — e.g. already lifted in a prior step)
        yields an empty no-op :class:`RenamePlan`, so the delegated apply path
        honestly no-ops rather than fakes a change (never a fake-green)."""
        from app.execution.cross_file_rename import RenamePlan
        from app.execution.dedup_guarded_return import plan_dedup_guarded_return
        from app.execution.objectives.dedup_guarded_return import _actionable_blocks

        def _plan(project_root: str, target: str) -> RenamePlan:
            for block in _actionable_blocks(project_root):
                if cls._unit_touches(block, target):
                    return plan_dedup_guarded_return(project_root, block)
            return RenamePlan(old=target, new="dedup-guarded-return")

        return _plan

    @classmethod
    def _plan_dedup_parameterized_lander(cls):
        """The dedup-parameterized lander adapted to the delegated ``(project_root,
        target)`` shape every delegated synthesis uses.

        dedup-parameterized is CROSS-MODULE — its real lander is
        ``plan_near_dup_extract(root, group: NearDuplicateGroup)``, not
        ``(root, rel_path)``. The target a surfaced step carries is a PARTICIPATING
        module (exactly what ``dedup_parameterizable_modules`` returns), so this wrapper
        re-runs the objective's OWN gate :func:`dedup_parameterized._actionable_groups`,
        matches the FIRST actionable group whose occurrences touch that module, and
        DELEGATES to the real ``plan_near_dup_extract``. An unmatched target (no
        actionable group touches it) yields an empty no-op :class:`RenamePlan`, so the
        delegated apply path honestly no-ops rather than fakes a change (never a
        fake-green).

        The PRIMARY-discovery seeder fact ``generalizable-duplication`` names its
        idea with the JOINED pair ``"{modules[0]} + {modules[1]}"`` (kept human-
        readable), so the surfaced step's target can be an ``"A + B"`` string rather
        than a single module. When the target carries that ``" + "`` join we try EACH
        side and return the first actionable group whose occurrences touch EITHER
        module — so the joined subject still lands. A single-module target splits to a
        one-element list, so the non-joined path stays byte-identical."""
        from app.execution.cross_file_rename import RenamePlan
        from app.execution.near_dup_extract import plan_near_dup_extract
        from app.execution.objectives.dedup_parameterized import _actionable_groups

        def _plan(project_root: str, target: str) -> RenamePlan:
            # A joined "A + B" subject (the seeder's human-readable module pair)
            # splits into its participating modules; a single-module target is just a
            # one-element list, so this stays byte-identical for the non-joined case.
            modules = [m.strip() for m in target.split(" + ")]
            for group in _actionable_groups(project_root):
                if any(cls._unit_touches(group, mod) for mod in modules):
                    return plan_near_dup_extract(project_root, group)
            return RenamePlan(old=target, new="dedup-parameterized")

        return _plan

    @staticmethod
    def _plan_extract_guard_clause_lander():
        """The extract-guard-clause lander adapted to the delegated ``(project_root,
        target)`` shape every delegated synthesis uses.

        extract-guard-clause is SINGLE-MODULE — its real lander is already
        ``plan_extract_guard_clause(root, module_rel) -> RenamePlan``, so (unlike the
        CROSS-MODULE dedup landers) there is NO actionable-group gate to re-run and NO
        joined "A + B" subject to split. The ``deep-nesting`` seeder subject is
        ``"<module_rel>::<function>"``, so this wrapper strips any trailing
        ``::function`` to recover the module rel and DELEGATES straight to
        ``plan_extract_guard_clause``. A non-``.py`` / unreadable / unparseable target
        yields an empty no-op :class:`RenamePlan` from the real lander, so the
        delegated apply path honestly no-ops rather than fakes a change.

        HONESTY — what this flattens and what it does NOT: extract-guard-clause only
        rewrites the GUARD-INVERTIBLE shape (a function whose WHOLE body is a single
        else-less ``if`` — it inverts that into an early-return guard, dropping one
        nesting level). A deeply-nested function whose staircase is NOT a leading
        guard (genuinely nested loops/conditionals needing inner-block extraction)
        matches nothing and yields an empty plan ⇒ an honest no-op (never a
        fake-green). So deep-nesting becomes autonomous for the common guard case and
        stays honest for the rest.

        SCOPE — broader but SAFE: ``plan_extract_guard_clause`` runs over the whole
        MODULE (it takes a rel, not a function), so it may also flatten guard shapes
        in OTHER functions of that module, not just the named one. This is SAFE
        exactly as W1's cross-module lift is: the plan lands through
        ``apply_rename(impact_scope=True)``, whose impacted-test gate auto-rolls-back
        on ANY regression — so a broader-than-named but behaviour-preserving flatten
        either verifies green or is reverted, never a silent overreach."""
        from app.execution.extract_guard_clause import plan_extract_guard_clause

        def _plan(project_root: str, target: str):
            # The deep-nesting subject is "<module_rel>::<function>"; strip any
            # "::function" suffix to recover the own-module rel (a plain module
            # target — no "::" — is unchanged). plan_extract_guard_clause runs over
            # that module and no-ops with an empty plan on a non-.py / unreadable rel.
            module_rel = target.split("::", 1)[0]
            return plan_extract_guard_clause(project_root, module_rel)

        return _plan

    @staticmethod
    def _plan_seal_hashable_eq_lander():
        """The seal-hashable-eq lander adapted to the delegated ``(project_root,
        target)`` shape every delegated synthesis uses.

        seal-hashable-eq is SINGLE-MODULE — its real lander is already
        ``plan_seal_hashable_eq(root, module_rel) -> RenamePlan``, so (unlike the
        CROSS-MODULE dedup landers) there is NO actionable-group gate to re-run and NO
        joined "A + B" subject to split. The ``incomplete-protocol`` seeder subject is
        ``"<module_rel>::<Class>"`` (``idea_seeder._seed_incomplete_protocols``), so
        this wrapper strips any trailing ``::Class`` to recover the module rel and
        DELEGATES straight to ``plan_seal_hashable_eq``. A non-``.py`` / unreadable /
        unparseable target yields an empty no-op :class:`RenamePlan` from the real
        lander, so the delegated apply path honestly no-ops rather than fakes a change.

        HONESTY — the eq/hash-ONLY boundary: the ``incomplete-protocol`` signal covers
        TWO gap shapes, and only ONE is deterministically completable. (a) An
        ``__eq__``-WITHOUT-``__hash__`` class is the CANONICAL gap — defining
        ``__eq__`` implicitly sets ``__hash__ = None`` (instances raise
        ``TypeError: unhashable`` as a ``set`` member / ``dict`` key), and
        ``seal_hashable_eq`` restores the canonical ``def __hash__`` over the SAME
        pure-copy field set ``__eq__`` ranges over — a RUNTIME-ADDITIVE completion that
        re-enables what currently raises, never a contract the ``__eq__`` disagrees
        with. (b) A ``__enter__``/``__exit__`` (or async) CONTEXT-MANAGER gap has NO
        deterministic completion (what should ``__exit__`` release / suppress? = a
        DESIGN decision), so it routes here, finds NO eligible eq/hash class, and
        yields an EMPTY plan ⇒ an HONEST no-op (the disclosed reason rides through),
        NEVER a fabricated ``__exit__`` body. So incomplete-protocol becomes autonomous
        for the eq/hash gap and stays honest (advisory) for context-manager gaps.

        SOUNDNESS — seal-hashable-eq's refusal set is the guarantee it only ever
        COMPLETES (never CHANGES) the contract: it seals ONLY a plain class with a
        body-``def __eq__`` and NO ``__hash__`` at all, refusing a ``@dataclass`` (its
        own ``eq=``/hash story), a ``__hash__ = None`` (a deliberate-unhashable choice),
        a hand-written ``__hash__``, a non-``object`` base (an inherited-hash contract),
        an assignment-/lambda-bound ``__eq__``, and an unenumerable / empty field set —
        and it hashes EXACTLY the ``__init__`` copy fields ``__eq__`` is built over, so
        the landed ``__hash__`` can never disagree with ``__eq__``.

        SCOPE — broader but SAFE: ``plan_seal_hashable_eq`` runs over the whole MODULE
        (it takes a rel, not a class), so it may also seal ANOTHER eligible eq/hash
        class in that module, not just the named one. This is SAFE exactly as W1's
        cross-module lift is: the plan lands through ``apply_rename(impact_scope=True)``,
        whose impacted-test gate auto-rolls-back on ANY regression — so a
        broader-than-named but runtime-additive seal either verifies green or is
        reverted, never a silent overreach."""
        from app.execution.objectives.seal_hashable_eq import plan_seal_hashable_eq

        def _plan(project_root: str, target: str):
            # The incomplete-protocol subject is "<module_rel>::<Class>"; strip any
            # "::Class" suffix to recover the own-module rel (a plain module target —
            # no "::" — is unchanged). plan_seal_hashable_eq runs over that module and
            # no-ops with an empty plan on a non-.py / unreadable / no-eligible-class rel.
            module_rel = target.split("::", 1)[0]
            return plan_seal_hashable_eq(project_root, module_rel)

        return _plan

    @staticmethod
    def _plan_promote_staticmethod_lander():
        """The promote-staticmethod lander adapted to the delegated ``(project_root,
        target)`` shape every delegated synthesis uses.

        promote-staticmethod is SINGLE-MODULE — its real lander is already
        ``plan_promote_staticmethods(root, module_rel) -> RenamePlan``, so (unlike
        the CROSS-MODULE dedup landers) there is NO actionable-group gate to re-run
        and NO joined "A + B" subject to split. The ``god-class`` seeder subject is
        ``"<module_rel>::<Class>"`` (``idea_seeder._seed_god_classes``), so this
        wrapper strips any trailing ``::Class`` to recover the module rel and
        DELEGATES straight to ``plan_promote_staticmethods``. A non-``.py`` /
        unreadable / unparseable target yields an empty no-op :class:`RenamePlan`
        from the real lander, so the delegated apply path honestly no-ops rather
        than fakes a change.

        HONESTY — the DECOUPLING-not-DECOMPOSITION boundary (the over-claim guard):
        promote-staticmethod promotes a god-class's SELF-FREE methods (those that
        provably never touch ``self``) to ``@staticmethod`` — a real coupling-surface
        reduction — but it does NOT reduce the method count or split
        responsibilities, so the FULL decomposition into cohesive collaborators
        stays a DESIGN task. The god-class fact row says exactly this; it must NEVER
        claim the executable action "decomposes into collaborators". A god-class with
        NO self-free method (e.g. a method-bag whose every method reads ``self``, or
        all are decorated / dunder / overridden / dynamically referenced) routes
        here, finds nothing eligible, and yields an EMPTY plan ⇒ an HONEST no-op (the
        disclosed reason rides through), NEVER a fabricated decomposition.

        SOUNDNESS — promote-staticmethod's refusal set is the guarantee it only ever
        DECOUPLES (never CHANGES behaviour): it promotes ONLY a method that uses no
        ``self``, is not already static/classmethod, carries NO decorator, is not a
        dunder, leads with ``self``, uses no ``super``, whose NAME is defined by a
        SINGLE class in the repo (no override / MRO branch to desync), whose class is
        top-level, and whose NAME is NOT referenced as a bare string literal anywhere
        (no dynamic getattr / monkeypatch-by-name target). The only edits are
        ``+@staticmethod`` and a dropped leading ``self`` — a ``@staticmethod`` stays
        a class attribute, so ``self.m()``/``Cls.m()``/``inst.m()`` all keep
        resolving with the same arguments.

        SCOPE — broader but SAFE: ``plan_promote_staticmethods`` runs over the whole
        MODULE (it takes a rel, not a class), so it may also promote eligible
        self-free methods in OTHER classes of that module, not just the named one.
        This is SAFE exactly as W1's cross-module lift is: the plan lands through
        ``apply_rename(impact_scope=True)``, whose impacted-test gate auto-rolls-back
        on ANY regression — so a broader-than-named but behaviour-preserving promotion
        either verifies green or is reverted, never a silent overreach."""
        from app.execution.promote_staticmethods import plan_promote_staticmethods

        def _plan(project_root: str, target: str):
            # The god-class subject is "<module_rel>::<Class>"; strip any "::Class"
            # suffix to recover the own-module rel (a plain module target — no "::" —
            # is unchanged). plan_promote_staticmethods runs over that module and
            # no-ops with an empty plan on a non-.py / unreadable / no-eligible rel.
            module_rel = target.split("::", 1)[0]
            return plan_promote_staticmethods(project_root, module_rel)

        return _plan

    @staticmethod
    def _plan_drop_param_lander():
        """The dead-parameter lander adapted to the delegated ``(project_root,
        target)`` shape every delegated synthesis uses — PLUS the new autonomy
        soundness rail (public-API refusal).

        dead-parameter is PER-PARAMETER, but the ``dead-parameter`` seeder subject
        is the MODULE rel only (``idea_seeder._seed_dead_params``: ``subject =
        dp["module"]``; the function/param live in the fact line, not the subject),
        so — exactly like the tdd-implement lander re-runs ``detect_missing_symbols``
        — this wrapper RE-RUNS the dead-parameter detector
        (``objective_compiler._dead_params``, the SAME scan the seeder and the
        objective compiler use) for the target module, recovers each ``(function,
        param)`` there, and DELEGATES to ``plan_param_drop`` for the first one a
        sound drop is producible for. A non-``.py`` / unreadable target, or a module
        with no droppable dead parameter, yields an empty no-op :class:`RenamePlan`
        with a disclosed blocker, so the delegated apply path honestly no-ops rather
        than fakes a change (never a fake-green).

        THE AUTONOMY SOUNDNESS RAIL — PUBLIC-API REFUSAL (the crux): the supervised
        ``apex signature drop`` muscle relied on a HUMAN to judge external impact.
        Autonomy removes the human, so an external (out-of-project) caller could pass
        the provably-dead parameter BY KEYWORD (``lib.func(x, dead=1)``) — a call the
        in-project scan cannot see and the suite-gate cannot exercise; dropping the
        parameter would raise ``TypeError`` for that caller. (param_drop already
        BLOCKS a POSITIONAL pass and a ``f(**mapping)`` splat, so external-keyword is
        the one residual hole autonomy opens.) So this lander REFUSES to drop a
        parameter from a function on the module's PUBLIC SURFACE, reusing the SAME
        default-public ``is_public_name`` predicate add-final / freeze-dataclass use:
        a name in ``__all__`` (or, with no ``__all__``, a top-level non-underscore
        name) is public ⇒ REFUSE; only a provably NON-public function
        (underscore-prefixed, or absent from a declared ``__all__``) is dropped, where
        ALL callers are necessarily in-project and the suite-gate + impact-scope +
        auto-rollback is the proof. Cannot prove non-public ⇒ honest no-op — the same
        creed the round-20 public-API rails shipped.

        SCOPE — top-level functions ONLY: ``plan_param_drop`` resolves the definition
        via ``resolve_sole_definition`` (a top-level ``def`` whose name is UNIQUE
        project-wide; the dead-param scan additionally refuses a name defined by 2+
        modules, a bare-object reference, a decorated def, and a stub body). So NO
        method-override / Protocol / ABC LSP hazard arises here — a parameter unused
        in an override that a base contract requires is simply never in scope.
        ``plan_param_drop`` keeps its full refuse-set (param read in body, ``*args`` /
        ``**kwargs``, a POSITIONAL call site, a ``f(**mapping)`` splat that could
        smuggle the key, a comment inside the signature span), so each is an honest
        no-op through the autonomous path too.

        SCOPE — broader but SAFE: the detector may surface SEVERAL dead parameters in
        the module; this lander tries them in the detector's deterministic order and
        returns the FIRST landable, non-public drop. Like the W1/W2/W3a/W5 landers it
        lands through ``apply_rename(impact_scope=True)``, whose impacted-test gate
        auto-rolls-back on ANY regression — so a broader-than-named but
        behaviour-preserving drop either verifies green or is reverted, never a silent
        overreach."""
        from app.execution.cross_file_rename import RenamePlan
        from app.execution.freeze_dataclass import is_public_name
        from app.execution.param_drop import plan_param_drop

        def _read(root: Path, rel: str) -> str | None:
            fp = root / rel
            try:
                return fp.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return None

        def _plan(project_root: str, target: str) -> RenamePlan:
            # The dead-parameter subject is the module rel; strip any "::suffix"
            # defensively so a future symbol-grain subject still resolves the module.
            module_rel = target.split("::", 1)[0]
            root = Path(project_root)
            source = _read(root, module_rel)
            if source is None:
                return RenamePlan(
                    old=module_rel, new="drop-param",
                    blockers=[f"{module_rel}: cannot read module — no drop"])

            from app.engine.objective_compiler import _dead_params

            # The detector is project-wide (it needs project-wide name-uniqueness
            # + bare-object refs); filter its deterministic, sorted output to this
            # module. Each entry is ``{module, function, param, line}``.
            dead = [d for d in _dead_params(project_root)
                    if d.get("module") == module_rel]

            public_refused: list[str] = []
            blockers: list[str] = []
            for d in dead:
                func, param = d["function"], d["param"]
                # THE PUBLIC-API RAIL: refuse a public-surface function — an external
                # caller could pass the dead param by keyword (unseen, unexercised).
                if is_public_name(func, source):
                    public_refused.append(
                        f"{module_rel}: {func}() is public API (an external caller "
                        f"could pass '{param}' by keyword) — refused")
                    continue
                plan = plan_param_drop(project_root, func, param)
                if plan.new_contents:
                    return plan  # the first landable, provably-non-public drop
                blockers.extend(plan.blockers)

            # Nothing landable here: carry the most informative disclosed reason.
            reason = (blockers or public_refused
                      or [f"{module_rel}: no droppable dead parameter"])
            return RenamePlan(old=module_rel, new="drop-param",
                              blockers=list(reason))

        return _plan

    _DELEGATED_SYNTHESIS = {
        "implement_stub": (
            "_plan_implement_stub_lander",
            "no synthesizable stub (unpinned / ambiguous / non-stub)"),
        "cover_gaps": (
            "_plan_cover_gaps_lander",
            "no cover-gap (already linked test / not characterizable)"),
        "wire_exports": (
            "_plan_wire_exports_lander",
            "no wire-export (already wired / namespace / oracle refused)"),
        "generate_usage_doc": (
            "_plan_generate_usage_doc_lander",
            "no usage-doc (no public API / already current / oracle refused)"),
        "tdd_implement": (
            "_plan_tdd_implement_lander",
            "no tdd-implement (no missing symbol / assertion failure / "
            "no template fits the RED test)"),
        "strengthen_tests": (
            "_plan_strengthen_tests_lander",
            "no strengthen-tests (saturated / no killable survivor / "
            "red baseline / test or fixture target)"),
        "modernize": (
            "_plan_modernize_lander",
            "no modernize (already modern / unreadable / unparseable module)"),
        "dedup_total_return": (
            "_plan_dedup_total_return_lander",
            "no dedup-total-return (no always-returning exact-duplicate block "
            "touches this module / unsafe block)"),
        "dedup_parameterized": (
            "_plan_dedup_parameterized_lander",
            "no dedup-parameterized (no parameterizable near-duplicate group "
            "touches this module)"),
        "dedup_guarded_return": (
            "_plan_dedup_guarded_return_lander",
            "no dedup-guarded-return (no guard-return+fall-through "
            "exact-duplicate block touches this module / unsafe block)"),
        "extract_guard_clause": (
            "_plan_extract_guard_clause_lander",
            "no flatten (no guard-invertible nesting in this function/module)"),
        "seal_hashable_eq": (
            "_plan_seal_hashable_eq_lander",
            "no protocol completion (no eq-without-hash class / a context-manager "
            "gap needs design / not eligible)"),
        "promote_staticmethod": (
            "_plan_promote_staticmethod_lander",
            "no promotion (no self-free method / all decorated, dunder, overridden, "
            "or dynamically referenced)"),
        "drop_param": (
            "_plan_drop_param_lander",
            "no drop (no dead parameter / public-API function / positional or "
            "**kwargs call site / param read in body / comment in signature)"),
    }

    # The action types ``apply_step`` / ``_generate`` route to the develop-core
    # delegation instead of the SemanticPatchResult gate (the table's keys).
    _DELEGATED_ACTIONS = frozenset(_DELEGATED_SYNTHESIS)

    def _apply_delegated_synthesis(self, step: ActionStep, project_root: str,
                                   verify: bool, covered_only: bool = False,
                                   baseline_failing: frozenset[str] | None = None,
                                   ) -> dict:
        """Delegate a develop-core synthesis step to the ``apply_rename`` path.

        Shared by ``implement_stub`` / ``cover_gaps`` / ``wire_exports`` (see
        ``_DELEGATED_SYNTHESIS``).
        Mirrors ``objective_compiler._apply_one_move``: build the one-module plan
        with the objective's own ``plan_<name>(project_root, target)`` lander, then
        land it through :func:`apply_rename` with ``impact_scope=True`` (the gate
        runs the impacted tests and rolls back on any regression). The result is
        translated into the bridge's ``apply_step`` result shape.

        ``covered_only`` is forwarded to ``apply_rename`` so the SAFE-by-default
        sweep withholds a green-but-unreferencing synthesis move (off ⇒ unchanged).

        ``baseline_failing`` (DEFAULT None ⇒ byte-identical) is the DELTA-GREEN
        baseline forwarded to :func:`apply_rename` — the SAME gate develop's
        ``_apply_one_move`` threads — so a delegated synthesis move LANDS (and is
        ``verified`` + discloses ``delta_green``) on a red-baseline repo when it
        broke no previously-green test in the impacted set, instead of landing only
        to be downgraded to ``baseline-red``. A true regression is still rolled
        back. ``None`` keeps the impact-scoped absolute-green path unchanged.

        Honesty: an EMPTY plan (``not plan.new_contents``) means nothing here is
        producible — never a fake-green — so it returns a non-applied result
        (carrying any disclosed blocker reason) and writes nothing.
        """
        from app.execution.cross_file_rename import apply_rename
        from app.execution.risk_tiers import tier_for

        lander_name, default_reason = self._DELEGATED_SYNTHESIS[step.action_type]
        plan = getattr(self, lander_name)()(project_root, step.target)
        if not plan.new_contents:
            reason = "; ".join(plan.blockers) or default_reason
            return {"applied": False, "transform_type": step.action_type,
                    "reason": reason}
        # Tier-aware covered-only: pass the action's risk tier so a behaviour-
        # introducing delegated synthesis (implement_stub/tdd_implement) needs
        # function-level coverage, exactly like the compiler path (one verdict).
        res = apply_rename(project_root, plan, verify=verify, impact_scope=True,
                           covered_only=covered_only, tier=tier_for(step.action_type),
                           baseline_failing=baseline_failing)
        return self._delegated_synthesis_result(step.action_type, res)

    @staticmethod
    def _delegated_synthesis_result(transform_type: str, res: dict) -> dict:
        """Translate an ``apply_rename`` result into the ``apply_step`` shape.

        Carries ``applied``/``rolled_back``/``changed_files``/``verified``/
        ``coverage``/``reason`` through verbatim where present so the maintenance
        report and the autonomous-commit gate read it exactly like any other
        applied/rolled-back step. ``transform_type`` names the synthesis that
        landed (``implement_stub`` / ``cover_gaps``)."""
        out: dict = {"transform_type": transform_type, **res}
        out["applied"] = bool(res.get("applied"))
        if "verified" in res:
            out["suite_green"] = bool(res.get("verified"))
        return out

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
    def _coverage_verifies(tier: int, coverage: str) -> bool:
        """Does ``coverage`` let a green suite actually VOUCH for a tier-``tier``
        change? Delegates to the SHARED ``risk_tiers.coverage_verifies`` so the
        bridge and the develop-core apply path enforce ONE identical verdict (the
        covered-only matrix invariant — no copy-paste, no drift)."""
        from app.execution.risk_tiers import coverage_verifies

        return coverage_verifies(tier, coverage)

    @staticmethod
    def _run_gate_suite(project_root: str, out: dict,
                        baseline_failing: frozenset[str] | None,
                        ) -> tuple[object, bool]:
        """Run the gate's suite and return ``(summary, suite_ok)`` — the single
        seam where ABSOLUTE-green and DELTA-GREEN differ.

        ``baseline_failing is None`` (the default, and a GREEN / suite-less
        baseline): the plain full-suite run, ``suite_ok = summary.ok`` — BYTE-
        IDENTICAL to the historical gate (same runner, same command, same verdict).

        ``baseline_failing`` not None (a RED-baseline pass): the BASELINE-COMPARABLE
        run (:func:`suite_after_failing` → pytest ``--continue-on-collection-errors``),
        and ``suite_ok = no previously-green test broke`` — the SET diff
        :func:`regressed_functions` charges, NOT a count, so a fix that turns ANY
        green test red is rejected even while an unrelated pre-existing red happens
        to recover (never-fake-green). The honest ``delta_green`` narrative (how
        many pre-existing reds were tolerated, what — if anything — was introduced)
        is stamped onto ``out`` so the proof trail discloses the red-baseline gate.
        Pre-existing failures are TOLERATED, never papered over or claimed-fixed.

        Deterministic — one suite run, parsed into a sorted set; no clock/random."""
        from app.skills.execution.run_tests import RunTestsSkill

        if baseline_failing is None:
            return RunTestsSkill().run(project_root), None  # type: ignore[return-value]
        from app.execution._apply_verify import (
            delta_green_disclosure,
            regressed_functions,
            suite_after_failing,
        )

        summary, after_failing = suite_after_failing(Path(project_root))
        introduced = regressed_functions(baseline_failing, after_failing)
        out["delta_green"] = delta_green_disclosure(baseline_failing, after_failing)
        return summary, not introduced

    @staticmethod
    def _verify_or_rollback(project_root: str, out: dict,
                            snapshot: dict[str, str | None],
                            patch_requests: list[dict], applied,
                            tier: int = 0, covered_only: bool = False,
                            baseline_failing: frozenset[str] | None = None) -> dict:
        """Run the suite; on red, restore every changed file to its snapshot.

        ``baseline_failing`` (DEFAULT None ⇒ ABSOLUTE-green, byte-identical) is the
        DELTA-GREEN baseline: the SET of node ids already RED before this pass. When
        threaded, the LANDING decision keys off "broke no previously-green test"
        instead of "whole suite green", so a correct fix LANDS on a red-baseline
        repo while a regression is STILL rolled back — every downstream gate
        (coverage-aware ``verified``, covered-only withhold, no-suite, rollback) is
        unchanged, just keyed on the delta-green verdict. The raw ``suite_green``
        stays the honest absolute result. ``None`` is byte-identical to before."""
        from app.engine.proof_of_fix import summarize_test_run
        from app.engine.verification_strength import assess_strength

        summary, delta_ok = IdeaActionBridge._run_gate_suite(
            project_root, out, baseline_failing)
        # ``suite_ok`` is the LANDING signal: the absolute-green ``summary.ok`` on a
        # green baseline, or the delta-green "no previously-green test broke" verdict
        # on a red baseline. ``suite_green`` below stays the raw absolute result.
        suite_ok = bool(summary.ok) if delta_ok is None else delta_ok
        out["test_commands"] = summary.commands
        out["test_evidence"] = summarize_test_run(summary)
        # How strongly does that green suite vouch for THESE changes?
        new_by_path = {pr.get("path", ""): pr.get("new_content", "") or "" for pr in patch_requests}
        out["verification_strength"] = assess_strength(
            project_root, applied.changed_files, snapshot, new_by_path
        )
        # Coverage-aware honesty. ``suite_green`` is the raw suite result;
        # ``coverage`` is what that green suite actually exercised. ``verified``
        # is True ONLY when the gate passed (absolute-green, or delta-green's
        # no-new-failure) AND a test genuinely vouches for the change at a level
        # appropriate to its risk tier — never when the suite passed but never
        # looked at what changed (which is how a smoke-import shield used to fake a
        # green on a real behaviour change).
        out["suite_green"] = bool(summary.ok)
        coverage = out["verification_strength"].get("level", "none")
        out["coverage"] = coverage
        out["verified"] = (suite_ok
                           and IdeaActionBridge._coverage_verifies(tier, coverage))
        if not summary.commands:
            # No test command detected -> NOTHING ran. The change is kept (many
            # legitimate develop objectives apply pure/additive changes on
            # suite-less projects), but it is NOT verified and auto-rollback could
            # not have protected it. Mark that absence loudly and unmistakably
            # rather than leaving an ambiguous ``verified: False`` that looks like
            # a run happened. Additive: a project WITH a suite is byte-identical.
            from app.execution._apply_verify import mark_no_suite
            mark_no_suite(out)
            out["rolled_back"] = False
            return out
        if suite_ok:
            # COVERED-ONLY (opt-in): the broad autonomous sweep lands ONLY moves a
            # green suite GENUINELY vouches for (``out["verified"]`` — a test
            # exercises the change at a level appropriate to its risk tier). A
            # green-but-unreferencing move (``coverage == "none"``, or a tier-1
            # behaviour change a mere import can't vouch for) is the false-green
            # blind spot — withhold it (restore + report ``withheld_uncovered``)
            # rather than land it. A test-only change (``test-change`` — the tests
            # ARE the suite) is never withheld. Off ⇒ byte-identical to today.
            if (covered_only and not out["verified"]
                    and coverage != "test-change"):
                IdeaActionBridge._restore_snapshot(
                    project_root, snapshot, applied.changed_files)
                out["applied"] = False
                out["rolled_back"] = True
                out["withheld_uncovered"] = True
                out["reason"] = ("withheld (covered-only): suite green but no test "
                                 "exercises this change — previewed, not landed "
                                 "(use --allow-weak to land)")
                return out
            # The gate passed (absolute-green, or delta-green's no-new-failure)
            # -> nothing to roll back.
            out["rolled_back"] = False
            return out

        # The gate FAILED — the whole suite went red (absolute-green) or this
        # change broke a previously-green test (delta-green) -> restore every
        # changed file to its snapshot. A pre-existing red alone never reaches
        # here under delta-green (it is tolerated, not charged).
        IdeaActionBridge._restore_snapshot(project_root, snapshot, applied.changed_files)
        out["applied"] = False
        out["rolled_back"] = True
        out["reason"] = "tests failed after patch; changes rolled back"
        return out

    @classmethod
    def _partial_or_noop_block(cls, project_root: str,
                              snapshot: dict[str, str | None], applied,
                              patch_requests: list[dict], transform_type: str,
                              mode: str) -> dict | None:
        """Honest early-exit for two write outcomes that must NOT count as a fix,
        else ``None`` (the apply proceeds):

          * PARTIAL — some patches were skipped (an ``expected_old_content``
            mismatch): a half-applied multi-file state is not a success;
          * NO-OP — every written file's content equals what was already there:
            an empty diff is not a fix (mirrors the proof path's empty-diff guard).

        In either case any file we did write is restored to its snapshot first.
        """
        reason = ""
        if applied.skipped_files:
            reason = "partial apply (expected_old_content mismatch)"
        else:
            new_by_path = {pr["path"]: (pr.get("new_content") or "") for pr in patch_requests}
            no_change = not any((snapshot.get(rel) or "") != new_by_path.get(rel, "")
                                for rel in applied.changed_files)
            if applied.ok and no_change:
                reason = "no change (patch is a no-op)"
        if not reason:
            return None
        cls._restore_snapshot(project_root, snapshot, applied.changed_files)
        block = {"applied": False, "mode": mode,
                 "transform_type": transform_type, "reason": reason}
        if applied.skipped_files:
            block["skipped_files"] = applied.skipped_files
        return block

    @staticmethod
    def _restore_snapshot(project_root: str, snapshot: dict[str, str | None],
                          changed_files: list[str]) -> None:
        """Restore each changed file to its pre-patch snapshot (a ``None``
        snapshot means the file was newly created, so it is removed)."""
        root = Path(project_root)
        for rel in changed_files:
            original = snapshot.get(rel)
            fp = root / rel
            if original is None:
                fp.unlink(missing_ok=True)
            else:
                fp.write_text(original, encoding="utf-8")

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

    @staticmethod
    def _rerank_by_fix_risk(
        steps: list[ActionStep], project_root: str
    ) -> list[ActionStep]:
        """Stably re-order executable steps by ascending fix-risk (opt-in).

        Reads each step's forward-looking rollback risk from the proof history
        (``fix_risk(root, action_type, target)``) and sorts low-risk-first with
        a STABLE sort, so steps that tie on risk keep their incoming roadmap
        order. Pure reorder: the returned list is a permutation of ``steps``
        with nothing added or dropped. Best-effort and deterministic — if the
        model raises or has no data, the original order is returned unchanged
        (and an empty history scores every step the neutral baseline, leaving
        the order identical anyway), so a reliability pass never crashes a
        maintain run."""
        if len(steps) < 2:
            return list(steps)
        try:
            from app.engine.fix_risk_model import fix_risk

            risks = [
                float(fix_risk(project_root, step.action_type, step.target))
                for step in steps
            ]
        except Exception:
            return list(steps)
        # Stable ascending sort on risk alone; Python's sort is stable, so
        # equal-risk steps keep their existing (phase/value-ordered) position.
        return [
            step for _, step in sorted(
                enumerate(steps), key=lambda iv: risks[iv[0]]
            )
        ]

    @staticmethod
    def _verification_unavailable_summary(
        project_root: str, mode: str
    ) -> dict | None:
        """An apply-summary that DECLINES because pytest is not importable, or
        ``None`` to proceed normally.

        Consults the shared entry-guard
        (:func:`app.execution._apply_verify.verification_unavailable_interpreter`):
        when the project has a pytest suite Apex cannot run, returns a summary with
        zero applied/rolled-back/blocked counts and the LOUD, actionable message
        (reusing the develop session's single source of truth so the wording is
        identical everywhere). ``verification_unavailable``/``pytest_interpreter``
        are additive keys the renderers surface. Returns ``None`` — the common,
        byte-identical path — for a suite-less / non-pytest project or when pytest
        IS importable. Deterministic + offline; the helpers are imported lazily."""
        from app.engine.develop_session import _verification_unavailable_message
        from app.execution._apply_verify import (
            verification_unavailable_interpreter,
        )

        interp = verification_unavailable_interpreter(Path(project_root))
        if interp is None:
            return None
        return {
            "mode": mode,
            "verify": True,
            "commit": False,
            "total_executable": 0,
            "applied": 0,
            "rolled_back": 0,
            "blocked": 0,
            "committed": 0,
            "results": [],
            "verification_unavailable": _verification_unavailable_message(interp),
            "pytest_interpreter": interp,
        }

    def apply_plan(
        self,
        plan: ActionPlan,
        project_root: str,
        mode: str = "supervised",
        verify: bool = False,
        max_apply: int | None = None,
        max_attempts: int | None = None,
        commit: bool = False,
        test_first: bool = True,
        avoid_signatures: dict | None = None,
        prefer_reliable: bool = False,
        drain: bool = False,
        max_rounds: int = 8,
        replan=None,
        covered_only: bool = False,
    ) -> dict:
        """Run a whole maintenance pass: apply each executable step in turn,
        verifying + rolling back individually, and return an aggregate summary.

        Steps are processed in plan order (already value-sorted). Each step is
        independent — a rolled-back step does not abort the run. Honors the
        same gating as apply_step (mode + safety + verify).

        CASCADE-DRAIN (opt-in, default off): when ``drain`` is set, the single
        apply pass is wrapped in a bounded re-detect → re-plan → apply OUTER loop,
        so the loop becomes detect → fix → RE-DETECT → prove and converges to a
        true fixpoint — landing fix A then re-examining only the files it changed
        to catch a fix B that A exposed but the single pass never re-looked at.
        Each round re-detects over ONLY the sorted set of files earlier fixes
        touched (via ``replan(changed_files)`` — defaults to re-running the idea
        engine on the project, filtered to that set), de-dups against every
        already-attempted ``(action, target)`` signature (so a withheld/fenced
        fix is NEVER re-attempted — no infinite loop), and draws from the SAME
        ``max_apply`` budget (never reset per round, so total applied across all
        rounds can't exceed it). It stops when a round applies zero new fixes or
        ``max_rounds`` is reached; the round count is recorded additively under
        ``drain_rounds``/``converged``. ``drain=False`` -> the apply path is
        byte-identical to today (single pass, same results/counters/keys).

        ATTEMPTS BUDGET (opt-in, default off): ``max_apply`` bounds the number of
        APPLIED fixes, but a run can still burn many apply+rollback cycles getting
        there — every step that reaches the apply stage runs the transform + verify
        whether it lands (applied) or is rolled back. ``max_attempts`` caps that
        total: an ATTEMPT is any step that reaches apply and is applied OR
        rolled_back (it ran the transform + verify, regardless of outcome). The
        single pass AND every drain round break once ``self.attempted >=
        max_attempts`` (the counter accumulates across rounds, never resets), so a
        run can't spend unbounded compute on rolled-back fixes. ``max_attempts=None``
        (the default) -> no cap and the summary keys are byte-identical to today; the
        ``attempted`` tally and ``attempts_exhausted`` flag appear ONLY when the
        budget is armed.

        RELIABILITY RE-RANK (opt-in, default off): when ``prefer_reliable`` is
        set, the executable steps are stably re-ordered by ascending fix-risk
        (read from the proof history via ``fix_risk``) BEFORE the apply loop, so
        a ``max_apply`` budget spends on the historically-most-reliable fixes
        first. It is purely a reorder — never adds/drops a step — and on a
        project with no proof history every step scores the neutral baseline, so
        the order (and thus the applied set) is byte-identical to the default.

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
        # VERIFICATION-UNAVAILABLE short-circuit. BEFORE applying any step, decline
        # if the project HAS a pytest suite but pytest is not importable under the
        # interpreter Apex would invoke: nothing could be verified, so applying +
        # reading the (necessarily failing) suite as RED would roll every fix back
        # — a silent, total under-delivery. Decline up front instead (proof-
        # carrying: can't verify => don't touch), counting nothing applied/verified
        # and surfacing the SAME loud, actionable message the develop session does.
        # Gated on ``verify`` so a ``--no-verify`` run (already unverified by
        # choice) is byte-identical. Deterministic + memoized — at most one probe.
        if verify:
            decline = self._verification_unavailable_summary(project_root, mode)
            if decline is not None:
                return decline

        run = _MaintenancePass(self, project_root, mode=mode, verify=verify,
                               test_first=test_first, commit=commit,
                               avoid_signatures=avoid_signatures,
                               covered_only=covered_only)
        steps = plan.executable_steps()
        if prefer_reliable:
            steps = self._rerank_by_fix_risk(steps, project_root)
        run._apply_steps(steps, max_apply, max_attempts)
        # CASCADE-DRAIN outer loop (opt-in): re-detect over only the changed set
        # and re-apply to a fixpoint. The first pass above already ran exactly as
        # before; this only ADDS further rounds, sharing the same budget/counters.
        drain_rounds = 0
        if drain:
            rp = replan if replan is not None else self._default_replan(
                project_root, mode)
            drain_rounds = run._drain_rounds(rp, max_apply, max_attempts,
                                             max(0, max_rounds))
        summary = {
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
        # Additive + opt-in: the skipped-learned tally appears ONLY when the
        # guard was armed (a non-empty avoid-map was passed), so an ordinary
        # run's summary keys are byte-identical to before.
        if run.avoid_signatures:
            summary["skipped_learned"] = run.skipped_learned
        # Additive + opt-in: the attempts tally + "did the budget stop the run"
        # flag appear ONLY when ``max_attempts`` was armed, so a default run's
        # summary keys are byte-identical to before. ``attempted`` counts every
        # step that reached the apply stage (applied OR rolled_back) across the
        # single pass and all drain rounds; ``attempts_exhausted`` is True iff the
        # budget was reached (and so capped the run).
        if max_attempts is not None:
            summary["attempted"] = run.attempted
            summary["attempts_exhausted"] = run.attempted >= max_attempts
        # Additive + opt-in: the convergence proof appears ONLY when the drain was
        # armed, so a default run's summary keys are byte-identical to before.
        if drain:
            summary["drain_rounds"] = drain_rounds
            summary["converged"] = drain_rounds < max(0, max_rounds)
        # Additive + opt-in: the covered-only sweep's withheld tally appears ONLY
        # when at least one move was withheld (a green-but-unreferencing move
        # PREVIEWED, not landed), so a default run's keys are byte-identical.
        if run.withheld_uncovered:
            summary["withheld_uncovered"] = run.withheld_uncovered
        return summary

    def _default_replan(self, project_root: str, mode: str):
        """The default re-detection used by the cascade-drain when no ``replan``
        is supplied: re-run the idea engine on ``project_root`` and rebuild a
        plan, narrowed to the steps whose target is in the changed set.

        Returns a callable ``changed -> ActionPlan`` so re-detection re-runs the
        SAME deterministic seed → permute → plan pipeline that produced the first
        plan, then keeps only the steps that touch a file an earlier fix changed
        (re-detection over the sorted changed set). Pure of clock/random; offline
        by default (the engine's security scan is local), so the drain stays
        deterministic and offline."""
        def _replan(changed: list[str]) -> ActionPlan:
            from app.engine.idea_permutation import IdeaPermutationEngine

            report = IdeaPermutationEngine(project_root=project_root).run()
            plan = self.plan_tree(report, mode=mode, project_root=project_root)
            wanted = {self._norm_changed(c) for c in changed}
            plan.steps = [
                s for s in plan.steps
                if s.executable and self._norm_changed(s.target) in wanted
            ]
            return plan
        return _replan

    @staticmethod
    def _norm_changed(path: str) -> str:
        """Normalize a path for changed-set membership (POSIX, deterministic)."""
        return Path(path).as_posix() if path else ""

    @staticmethod
    def _confluence_headline(steps: list[ActionStep]) -> list[ActionStep]:
        """Make the #1 step the most-converging confluence subject, when the
        leaders are a near-tie.

        Among the leading band — steps whose value is within
        ``_CONFLUENCE_TIE_EPSILON`` of the current top step's value — promote the
        one backed by the MOST converging confluence signals (its family count),
        breaking any remaining tie by subject. Only this leading band is touched;
        every later step keeps its exact value order. The reorder is stable and
        deterministic (no time/random), and ``ActionStep.value`` is never mutated
        — only the band's order changes, so the headline matches the dream's #1
        while the rest of the plan is preserved.
        """
        if len(steps) < 2:
            return steps
        top_value = steps[0].value
        band = 0
        while (band < len(steps)
               and top_value - steps[band].value <= _CONFLUENCE_TIE_EPSILON):
            band += 1
        if band < 2:
            return steps
        leaders = steps[:band]
        # Stable: enumerate index ties subject ties to keep input order as the
        # final, fully-deterministic fallback.
        leaders = sorted(
            enumerate(leaders),
            key=lambda iv: (-_confluence_weight(iv[1]), iv[1].subject, iv[0]),
        )
        return [s for _, s in leaders] + steps[band:]

    # The develop-grade synthesis objectives the action plan is augmented with,
    # one per honest grounding signal. Each tuple is
    # ``(signal_fn, action_type, fact_label, phase)``: the signal returns the
    # subset of candidate modules for which the real lander would land a change
    # (so the step is executable by construction); ``fact_label`` reuses the
    # ``_FACT_ACTIONS`` description template; ``phase`` is the roadmap phase
    # (implement-stub builds new code → Evolve; the two pure refactors → Refine).
    # Order is fixed for determinism.
    _SYNTHESIS_OBJECTIVES = (
        ("fillable_stub_modules", "implement_stub", "implement-stub", "Evolve"),
        ("inferable_return_modules", "infer_type_hints", "infer-type-hints", "Refine"),
        ("dataclassifiable_modules", "dataclassify", "dataclassify", "Refine"),
    )

    # OPT-IN synthesis objectives (default OFF): these share the idea budget but
    # qualify a BROAD set of modules, so enabling them by default would shift
    # existing idea sets. Each runs only when its own caller flag is passed True
    # (threaded ``plan_tree``/``plan_roadmap`` → ``_augment_synthesis_steps``), so
    # a default plan stays byte-identical to before these objectives existed. The
    # table is keyed by that flag name → the objectives it enables, so adding an
    # opt-in objective is one row and the assembly stays data-driven (no per-flag
    # branch in ``_augment_synthesis_steps``).
    #
    # cover-gaps writes a brand-new safety-net characterization test for ANY
    # untested module — the same "build the net first" move as create_test_stub —
    # so it belongs in Stabilize.
    #
    # wire-exports rewrites a package ``__init__.py`` to declare its public
    # re-export surface (``__all__`` + ``from .module import Name``). It targets
    # PACKAGES broadly (every wireable ``__init__.py`` in the candidate set), so —
    # like cover-gaps — it is opt-in lest it shift the default idea set. It is a
    # structure/clarity contribution that makes the package importable as designed,
    # so it sits in Refine. All three are delegated (like implement_stub) to the
    # develop-core ``apply_rename`` path, not the SemanticPatchResult gate.
    #
    # generate-usage-doc writes a package's sibling ``USAGE.md`` from its PUBLIC
    # API. Like wire-exports it targets PACKAGES broadly (every documentable
    # ``__init__.py`` in the candidate set), so it is opt-in lest it shift the
    # default idea set. It is a documentation/clarity contribution (it restates,
    # zero-token, exactly what the code declares), so it too sits in Refine.
    #
    # tdd-implement synthesises the missing function a RED test calls (PER-SYMBOL).
    # Like implement-stub it LANDS a real function body, so it belongs in Evolve;
    # but its detector runs the whole suite to harvest failures, so — like every
    # broad objective here — it is opt-in (default off) lest it both shift the
    # default idea set and add suite-run cost to a plain plan. Its signal returns
    # ``"<module>:<name>"`` symbol targets (not ``.py`` module paths), so its rows
    # are distinct from the package/module objectives above.
    #
    # strengthen-tests HARDENS an existing-but-thin test by appending a double-gated
    # assertion that kills a surviving mutant the current suite misses. Like
    # cover-gaps it is a test/safety-net contribution that targets MODULES broadly,
    # so it belongs in Stabilize; and like every broad objective here it is opt-in
    # (default off) lest it shift the default idea set — and its signal runs the
    # MUTATION ENGINE per candidate (expensive), so a plain plan must not pay that
    # cost. Its ``register`` spec is ``expensive=True, scope_verify=True``, so — like
    # cover-gaps — it lands through ``apply_rename`` with ``impact_scope=True``.
    #
    # modernize REWRITES a module's OWN source with behaviour-preserving idiom
    # modernizations (``== None`` → ``is None``, dead ``f`` prefixes,
    # empty-constructor → collection literal). It targets MODULES broadly (every
    # module carrying a stale idiom in the candidate set), so — like cover-gaps — it
    # is opt-in lest it shift the default idea set. It is a readability REFINEMENT
    # (it spells the same behaviour more idiomatically), so it sits in Refine; and
    # like the other delegated synthesis objectives it lands through ``apply_rename``
    # with ``impact_scope=True`` (its grounding ``modernize_plan`` chains the
    # objective compiler's own tidy transforms over the module).
    #
    # dedup-total-return / dedup-parameterized REDUCE cross-module DUPLICATION: each
    # lifts a duplicate (an always-returning exact block / a near-duplicate group)
    # into one shared helper. They are CROSS-MODULE — their grounding signals qualify a
    # PARTICIPATING module, and their lander wrappers find the actionable block/group
    # touching it — and target modules broadly, so — like cover-gaps — each is opt-in
    # (default off) lest it shift the default idea set. Both are a structural REFINEMENT
    # (they DRY up duplication while preserving behaviour), so each sits in Refine; and
    # like every delegated synthesis objective each lands through ``apply_rename`` with
    # ``impact_scope=True``. Their flags (``dedup_total_return`` / ``dedup_parameterized``)
    # are INDEPENDENT of each other and of every other opt-in flag.
    _OPTIN_SYNTHESIS_OBJECTIVES: dict[str, tuple[tuple[str, str, str, str], ...]] = {
        "cover_gaps": (
            ("cover_gaps_modules", "cover_gaps", "cover-gaps", "Stabilize"),
        ),
        "wire_exports": (
            ("wire_export_packages", "wire_exports", "wire-exports", "Refine"),
        ),
        "generate_usage_doc": (
            ("generate_usage_doc_packages", "generate_usage_doc",
             "generate-usage-doc", "Refine"),
        ),
        "tdd_implement": (
            ("tdd_implementable_symbols", "tdd_implement", "tdd-implement",
             "Evolve"),
        ),
        "strengthen_tests": (
            ("strengthenable_modules", "strengthen_tests", "strengthen-tests",
             "Stabilize"),
        ),
        "modernize": (
            ("modernizable_modules", "modernize", "modernize", "Refine"),
        ),
        "dedup_total_return": (
            ("dedup_total_return_modules", "dedup_total_return",
             "dedup-total-return", "Refine"),
        ),
        "dedup_guarded_return": (
            ("dedup_guarded_return_modules", "dedup_guarded_return",
             "dedup-guarded-return", "Refine"),
        ),
        "dedup_parameterized": (
            ("dedup_parameterizable_modules", "dedup_parameterized",
             "dedup-parameterized", "Refine"),
        ),
    }

    # Cost ceiling: at most this many candidate modules are probed per signal
    # (the signals each read + parse a file), keeping augmentation cheap on a
    # large plan. Deterministic — the sorted candidate prefix is used.
    _SYNTHESIS_CANDIDATE_LIMIT = 40

    @classmethod
    def _synthesis_candidates(cls, steps: list[ActionStep]) -> list[str]:
        """The distinct ``.py`` module targets already present in ``steps``,
        sorted and capped — the bounded candidate set the synthesis signals probe.

        These modules are already surfaced as ideas, so probing them adds no new
        discovery cost and keeps the augmentation tied to what the plan already
        deems relevant. Sorted for determinism, capped for cost."""
        mods = {
            s.target for s in steps
            if s.target and s.target.endswith(".py")
        }
        return sorted(mods)[:cls._SYNTHESIS_CANDIDATE_LIMIT]

    @classmethod
    def _enabled_objectives(
        cls, cover_gaps: bool, wire_exports: bool,
        generate_usage_doc: bool = False,
        tdd_implement: bool = False,
        strengthen_tests: bool = False,
        modernize: bool = False,
        dedup_total_return: bool = False,
        dedup_guarded_return: bool = False,
        dedup_parameterized: bool = False,
        auto: bool = False,
    ) -> tuple[tuple[str, str, str, str], ...]:
        """The default synthesis objectives plus each opt-in objective whose flag
        is True, assembled data-driven from ``_OPTIN_SYNTHESIS_OBJECTIVES``.

        Order is fixed (defaults first, then the opt-in table's insertion order),
        so the augmented plan is deterministic. With every flag False (and
        ``auto`` False) this is exactly ``_SYNTHESIS_OBJECTIVES`` — the default
        plan never shifts. The opt-in flags are INDEPENDENT: enabling one never
        pulls in another. ``auto`` enables EVERY opt-in objective (a union over
        the whole table) so a user need not name each flag — and because each
        objective's grounding signal still filters to qualifying targets, "enable
        all" surfaces exactly the objectives that apply to this project. ``auto``
        is idempotent with the individual flags (their union is still "all")."""
        flags = {"cover_gaps": cover_gaps, "wire_exports": wire_exports,
                 "generate_usage_doc": generate_usage_doc,
                 "tdd_implement": tdd_implement,
                 "strengthen_tests": strengthen_tests,
                 "modernize": modernize,
                 "dedup_total_return": dedup_total_return,
                 "dedup_guarded_return": dedup_guarded_return,
                 "dedup_parameterized": dedup_parameterized}
        objectives = cls._SYNTHESIS_OBJECTIVES
        for flag, rows in cls._OPTIN_SYNTHESIS_OBJECTIVES.items():
            if auto or flags.get(flag):
                objectives = objectives + rows
        return objectives

    def _augment_synthesis_steps(self, steps: list[ActionStep],
                                 project_root: str,
                                 cover_gaps: bool = False,
                                 wire_exports: bool = False,
                                 generate_usage_doc: bool = False,
                                 tdd_implement: bool = False,
                                 strengthen_tests: bool = False,
                                 modernize: bool = False,
                                 dedup_total_return: bool = False,
                                 dedup_guarded_return: bool = False,
                                 dedup_parameterized: bool = False,
                                 auto: bool = False) -> None:
        """Append executable develop-grade synthesis steps for the qualifying
        candidate modules, in place (the caller then de-dups).

        For each synthesis objective, run its honest grounding signal over the
        candidate modules (the ``.py`` targets already in ``steps`` — a package's
        ``__init__.py`` IS a ``.py`` target, so wire-exports candidates are
        included) and append one executable :class:`ActionStep` per qualifying
        ``(module, objective)`` whose ``(target, action_type)`` is not already
        present. The signal only returns a module when the REAL lander would land a
        change, so every appended step is genuinely executable — never a fake-green.

        The three default objectives qualify a narrow set; the BROAD opt-in
        objectives in ``_OPTIN_SYNTHESIS_OBJECTIVES`` (cover-gaps, wire-exports,
        generate-usage-doc, tdd-implement, strengthen-tests, modernize) run only when
        their own flag (``cover_gaps`` / ``wire_exports`` / ``generate_usage_doc`` /
        ``tdd_implement`` / ``strengthen_tests`` / ``modernize``) is True, so a
        default plan never shifts its existing idea set. The opt-in flags are
        INDEPENDENT. ``auto`` enables EVERY opt-in objective at once (so a user
        need not name each flag); the grounding signals still filter to
        qualifying targets, so it stays honest — only objectives that apply
        surface.

        Determinism / opt-in safety: on a project with NO synthesis-eligible
        module (or no ``project_root``), nothing is appended and the plan stays
        byte-identical to before this augmentation. Never raises — the signals
        themselves swallow per-module errors, and an unexpected failure here
        leaves the plan untouched."""
        if not project_root:
            return
        candidates = self._synthesis_candidates(steps)
        if not candidates:
            return
        present = {(s.target, s.action_type) for s in steps}
        try:
            from app.engine import idea_synthesis_signals as sigs
        except Exception:  # pragma: no cover - defensive import guard
            return
        objectives = self._enabled_objectives(cover_gaps, wire_exports,
                                              generate_usage_doc, tdd_implement,
                                              strengthen_tests, modernize,
                                              dedup_total_return,
                                              dedup_guarded_return,
                                              dedup_parameterized, auto)
        for signal_name, action_type, fact, phase in objectives:
            signal = getattr(sigs, signal_name)
            for module in signal(project_root, candidates,
                                 limit=self._SYNTHESIS_CANDIDATE_LIMIT):
                key = (module, action_type)
                if key in present:
                    continue
                present.add(key)
                steps.append(self._synthesis_step(module, action_type, fact, phase))

    @staticmethod
    def _synthesis_step(module: str, action_type: str, fact: str,
                        phase: str) -> ActionStep:
        """Build one executable synthesis :class:`ActionStep` for ``module``.

        The ``(action_type, description, executable)`` comes from the objective's
        ``_FACT_ACTIONS`` row (single source of truth for phrasing), and the
        branch_path is a stable, deterministic ``x.syn.<action>.<module>`` so the
        same plan renders identically run-to-run. Marked executable because the
        grounding signal already proved a patch is producible for this module."""
        _action, desc_tmpl, executable = _FACT_ACTIONS[fact]
        return ActionStep(
            branch_path=f"x.syn.{action_type}.{module}",
            title=f"Synthesis: {action_type} {module}",
            operator="synthesis",
            subject=module,
            action_type=action_type,
            target=module,
            description=desc_tmpl.format(s=module),
            executable=executable,
            phase=phase,
        )

    def plan_tree(
        self,
        report: IdeaTreeReport,
        mode: str = "supervised",
        top: int | None = None,
        draft: bool = False,
        project_root: str | None = None,
        proof: bool = False,
        confluence_first: bool = False,
        cover_gaps: bool = False,
        wire_exports: bool = False,
        generate_usage_doc: bool = False,
        tdd_implement: bool = False,
        strengthen_tests: bool = False,
        modernize: bool = False,
        dedup_total_return: bool = False,
        dedup_guarded_return: bool = False,
        dedup_parameterized: bool = False,
        auto: bool = False,
    ) -> ActionPlan:
        ideas = sorted(report.ideas, key=lambda i: i.value, reverse=True)
        if top is not None:
            ideas = ideas[:top]
        root_for_checks = project_root or report.project_root or ""
        steps: list[ActionStep] = []
        for i in ideas:
            steps.extend(self._expand_idea(i, project_root=root_for_checks))
        self._augment_synthesis_steps(steps, root_for_checks,
                                      cover_gaps=cover_gaps,
                                      wire_exports=wire_exports,
                                      generate_usage_doc=generate_usage_doc,
                                      tdd_implement=tdd_implement,
                                      strengthen_tests=strengthen_tests,
                                      modernize=modernize,
                                      dedup_total_return=dedup_total_return,
                                      dedup_guarded_return=dedup_guarded_return,
                                      dedup_parameterized=dedup_parameterized,
                                      auto=auto)
        steps = self._dedupe_steps(steps)
        # Opt-in (default off, so existing plans are byte-identical): when the
        # top steps are a value near-tie, surface the subject with the most
        # converging confluence signals as the #1 action — keeping the headline
        # consistent with the dream/confluence lens's family count.
        if confluence_first:
            steps = self._confluence_headline(steps)
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
                       root_for_checks: str,
                       cover_gaps: bool = False,
                       wire_exports: bool = False,
                       generate_usage_doc: bool = False,
                       tdd_implement: bool = False,
                       strengthen_tests: bool = False,
                       modernize: bool = False,
                       dedup_total_return: bool = False,
                       dedup_guarded_return: bool = False,
                       dedup_parameterized: bool = False,
                       auto: bool = False,
                       dream_boost: dict[str, float] | None = None) -> list[ActionStep]:
        """Expand the roadmap's ideas into deduped, phase-ordered steps.

        Convergence ideas carry their own phased sub-steps (a Stabilize test
        before a Secure harden), so they may emit a phase other than where
        the parent idea was placed; other ideas inherit the roadmap phase.
        The final stable sort by canonical phase puts every step in its true
        phase group — preserving test-before-harden order for free, since
        Stabilize precedes Secure. ``cover_gaps`` / ``wire_exports`` /
        ``generate_usage_doc`` / ``tdd_implement`` / ``strengthen_tests`` /
        ``modernize`` opt their broad synthesis objective in (default off,
        independent — see ``_augment_synthesis_steps``).

        ``dream_boost`` (default None/empty ⇒ byte-identical) maps a module path
        to a positive priority boost for the modules the dream graduated as
        CONFLUENCES: within each phase group a boosted step sorts ahead of its
        unboosted peers, so ``apex auto`` leads with the organism's own overnight
        discovery. It is applied as a SECONDARY sort key AFTER the phase rank, so
        the phase order (test-before-harden) is preserved, and when the map is
        empty every step's boost is 0.0 — the sort key degenerates to the phase
        rank alone and a stable sort reproduces the pre-dream order byte-for-byte.
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
        self._augment_synthesis_steps(steps, root_for_checks,
                                      cover_gaps=cover_gaps,
                                      wire_exports=wire_exports,
                                      generate_usage_doc=generate_usage_doc,
                                      tdd_implement=tdd_implement,
                                      strengthen_tests=strengthen_tests,
                                      modernize=modernize,
                                      dedup_total_return=dedup_total_return,
                                      dedup_guarded_return=dedup_guarded_return,
                                      dedup_parameterized=dedup_parameterized,
                                      auto=auto)
        steps = self._dedupe_steps(steps)
        from app.engine.idea_roadmap import PHASE_ORDER
        phase_rank = {name: i for i, name in enumerate(PHASE_ORDER)}
        # Phase first (test-before-harden), then the dream-confluence boost as a
        # STABLE secondary key: a boosted step leads WITHIN its phase, while an
        # empty ``dream_boost`` makes every boost 0.0 ⇒ the key is the phase rank
        # alone ⇒ the stable sort reproduces the pre-dream order byte-for-byte.
        steps.sort(key=lambda s: (phase_rank.get(s.phase, len(PHASE_ORDER)),
                                  -_dream_step_boost(s, dream_boost)))
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
        cover_gaps: bool = False,
        wire_exports: bool = False,
        generate_usage_doc: bool = False,
        tdd_implement: bool = False,
        strengthen_tests: bool = False,
        modernize: bool = False,
        dedup_total_return: bool = False,
        dedup_guarded_return: bool = False,
        dedup_parameterized: bool = False,
        auto: bool = False,
        dream_boost: dict[str, float] | None = None,
    ) -> ActionPlan:
        """Plan actions in roadmap order (Stabilize→Secure→Evolve→Refine).

        Unlike ``plan_tree`` (pure value ranking), this sequences steps by the
        roadmap's engineering phases so a guarded ``apply_plan`` builds the
        safety net before changing risky code. ``phase`` restricts the plan to a
        single phase; each step is tagged with the phase it came from.
        ``cover_gaps`` / ``wire_exports`` / ``generate_usage_doc`` /
        ``tdd_implement`` / ``strengthen_tests`` / ``modernize`` opt their broad
        synthesis objective in (default off, independent, so the default plan's idea
        set is unchanged).

        ``dream_boost`` (default None/empty ⇒ byte-identical) amplifies the
        modules the dream graduated as CONFLUENCES: within a phase a boosted step
        leads its peers, so ``apex auto`` prioritizes the organism's own overnight
        discovery. An empty map (no dream / unreadable / below-gate) leaves the
        plan byte-for-byte unchanged — the refusal-safe fallback.
        """
        from app.engine.idea_roadmap import RoadmapSynthesizer

        roadmap = roadmap or RoadmapSynthesizer().build(report)
        steps = self._roadmap_steps(report, roadmap,
                                    project_root or report.project_root or "",
                                    cover_gaps=cover_gaps,
                                    wire_exports=wire_exports,
                                    generate_usage_doc=generate_usage_doc,
                                    tdd_implement=tdd_implement,
                                    strengthen_tests=strengthen_tests,
                                    modernize=modernize,
                                    dedup_total_return=dedup_total_return,
                                    dedup_guarded_return=dedup_guarded_return,
                                    dedup_parameterized=dedup_parameterized,
                                    auto=auto,
                                    dream_boost=dream_boost)
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


def _learned_skip_reason(signatures: dict, step: ActionStep) -> str:
    """The human-readable reason a fix was skipped by the learned-failure guard.

    Cites the worst avoid-flagged signature for this step (the one that drove
    the skip): its rolled-back-N-of-M tally on that module-trait. Deterministic,
    never raises — falls back to a generic note if no flagged stat is found."""
    from app.engine.counterfactual_learning import module_traits, _signature_keys

    for key in _signature_keys(step.action_type or "<unknown>",
                               module_traits(step.target)):
        stat = signatures.get(key)
        if isinstance(stat, dict) and stat.get("avoid"):
            _, _, trait = key.partition(" | ")
            return (f"history predicts failure: rolled back "
                    f"{stat.get('failures', 0)}/{stat.get('attempts', 0)} on "
                    f"`{trait}` modules for this action")
    return "history predicts failure for this action on this module-trait"


class _MaintenancePass:
    """One ``apply_plan`` run: counters, committer, shield memory, entries.

    Extracted from a 36-branch ``apply_plan`` — the engine's own brief on
    this module named it. Behavior is unchanged; each concern (shield, tier
    gate, convergence, commit bookkeeping) now reads on its own.
    """

    def __init__(self, bridge: IdeaActionBridge, project_root: str, *,
                 mode: str, verify: bool, test_first: bool, commit: bool,
                 avoid_signatures: dict | None = None,
                 covered_only: bool = False) -> None:
        from app.policies.mode_policy import ModePolicy, mode_from_string

        self.bridge = bridge
        self.project_root = project_root
        self.mode = mode
        self.verify = verify
        self.test_first = test_first
        # COVERED-ONLY sweep (opt-in, default off ⇒ byte-identical): when set, an
        # APPLIED step a green suite couldn't vouch for (no test exercises the
        # change — ``coverage == "none"``) is RESTORED from its pre-apply snapshot
        # and recorded as ``withheld_uncovered`` instead of landed, so the broad
        # autonomous ``auto --apply`` sweep never silently lands a weak move.
        self.covered_only = covered_only
        self.withheld_uncovered = 0
        # Opt-in closed-loop guard: when non-empty, a fix the proof history
        # predicts will fail is skipped BEFORE its wasted apply+rollback. An
        # empty/None map (the default) means the guard never fires, so the run
        # is byte-identical to one that never learned anything.
        self.avoid_signatures = avoid_signatures or None
        self.results: list[dict] = []
        self.applied = self.rolled_back = self.blocked = 0
        self.committed = self.skipped_learned = 0
        # ATTEMPTS BUDGET: every step that reaches the apply stage and is APPLIED
        # OR ROLLED_BACK is one attempt (it ran the transform + verify, whatever
        # the outcome). Accumulated across the single pass AND all drain rounds
        # (never reset), so ``max_attempts`` bounds total apply+rollback cycles, a
        # separate ceiling from ``max_apply`` (which counts only landed fixes).
        # A blocked/safety-gated step never reached apply, so it is NOT an attempt.
        self.attempted = 0
        self.can_commit = False
        self.committer = None
        if commit:
            perms = ModePolicy(mode=mode_from_string(mode)).permissions
            self.can_commit = bool(perms.can_commit)
            if self.can_commit:
                from app.engine.git_auto_commit import GitAutoCommit

                self.committer = GitAutoCommit(project_root)
        self._shield_attempted: set[str] = set()
        # BASELINE pre-flight (lazy, computed ONCE before the first apply and
        # cached for the whole pass — never re-run per step). ``_baseline_green``
        # is ``None`` until probed, then a bool: ``True`` when the suite was green
        # before any fix (the common case — behaviour is byte-identical), ``False``
        # when the suite was ALREADY failing. ``_baseline_failing`` is the SET of
        # test node ids already RED at baseline (empty on a green / suite-less
        # baseline), captured from the SAME single probe — the DELTA-GREEN baseline
        # the verified-apply gate threads so a correct, harmless fix LANDS on a
        # project red on checkout while a true regression is still rolled back
        # (front-door parity with develop's ``_campaign_baseline``). On a green
        # baseline the set is empty ⇒ the gate stays absolute-green ⇒ byte-identical.
        self._baseline_green: bool | None = None
        self._baseline_failing: frozenset[str] = frozenset()
        # WITHHELD-CHANGE FENCE: files carrying an uncommitted, withheld
        # behaviour change (left applied-on-disk for review). Once a file is
        # fenced, NO later auto-commit in this pass may touch it — a sibling
        # step (e.g. a Tier-0 ``add_docstring`` on the SAME file) must not sweep
        # the still-on-disk withheld hunk into git via whole-file staging. The
        # fence is keyed on normalized paths so membership is byte-deterministic.
        self._fenced_files: set[str] = set()
        # CASCADE-DRAIN bookkeeping (only consulted when ``apply_plan`` runs the
        # outer drain loop; for an ordinary single pass these stay empty/None and
        # change nothing). ``_handled`` is the dedup skip-set of already-attempted
        # ``(action_type, target)`` signatures — a withheld/fenced fix lands here
        # too, so the next drain round NEVER re-attempts it (no infinite loop on a
        # withheld fix). ``_changed_files`` accumulates every file a fix actually
        # touched, so re-detection re-runs over ONLY the sorted changed set.
        self._handled: set[tuple[str, str]] = set()
        self._changed_files: set[str] = set()
        # When the drain is armed, ``run_step`` honours ``_handled`` so a re-built
        # plan that re-surfaces an already-attempted step is skipped silently
        # (no row, no counter) — off by default so a single pass is byte-identical.
        self._drain_active = False

    @staticmethod
    def _norm_path(path: str) -> str:
        """Normalize a changed-file path for fence membership (deterministic,
        no clock/random — pure string normalization)."""
        return Path(path).as_posix()

    def _fence_files(self, *paths: str) -> None:
        """Add the given file path(s) to the withheld-change fence."""
        for p in paths:
            if p:
                self._fenced_files.add(self._norm_path(p))

    def _is_fenced(self, path: str) -> bool:
        return bool(path) and self._norm_path(path) in self._fenced_files

    def _commit_touches_fenced(self, r: dict, step: ActionStep) -> bool:
        """True when ANY file this commit would stage is fenced.

        ``_commit`` stages every path in ``r["changed_files"]`` (falling back to
        ``[step.target]`` when the result carries none), so the fence gate must
        check the WHOLE staged set, not just ``step.target``. A future cross-file
        transform whose ``changed_files`` includes a fenced sibling would
        otherwise bypass the per-target gate and sweep the withheld hunk into git
        via whole-file staging. The fenced-``step.target`` case stays a subset
        (it is in the fallback list). Uses the same normalized-path comparison as
        ``_is_fenced``/``_norm_path`` — pure string work, deterministic, and a
        no-op (``any(...)`` is ``False``) whenever nothing is fenced, so the
        common no-withhold path stays byte-identical."""
        staged = r.get("changed_files") or [step.target]
        return any(self._is_fenced(f) for f in staged)

    def _ensure_baseline(self) -> bool:
        """ONE-TIME baseline pre-flight, cached for the whole pass.

        Runs the verification command ONCE, before the first apply, to record
        whether the suite was already green. The result is cached on the pass, so
        later steps read the bool and NEVER re-run the suite — there is exactly
        one extra full-suite run for the pre-flight, regardless of step count.

        Only meaningful when ``self.verify`` is on (no verify -> nothing to
        verify against, so no baseline is probed and the run is byte-identical to
        today). Returns the cached ``baseline_green`` bool.

        The SAME single probe also caches ``_baseline_failing`` — the SET of node
        ids already RED at baseline — so the DELTA-GREEN gate has a baseline to
        diff against WITHOUT a second suite run. ``suite_baseline_state`` runs the
        suite once and derives both facts; the green bool is identical to the old
        ``suite_baseline_green`` on every project (clean ⇒ green, any red ⇒ not),
        so the cached value and the ``baseline-red`` attribution are unchanged."""
        if self._baseline_green is None:
            from app.execution._apply_verify import suite_baseline_state

            self._baseline_green, self._baseline_failing = suite_baseline_state(
                Path(self.project_root))
        return self._baseline_green

    def _delta_baseline(self) -> frozenset[str] | None:
        """The DELTA-GREEN baseline to thread into the verified-apply gate.

        Resolves EXACTLY as develop's :func:`_campaign_baseline`: a non-empty
        RED-baseline failing set engages delta-green (a correct move lands while a
        true regression is still rolled back); ``None`` keeps the gate
        ABSOLUTE-green, byte-identical to today. Returns ``None`` whenever the pass
        is not verifying (no gate to thread), the baseline was never probed, or the
        baseline was GREEN (empty failing set — the common case, and Apex's own
        suite). Pure read of the cached probe — no clock/random, no extra run."""
        if not self.verify:
            return None
        return self._baseline_failing or None

    def _settle_baseline_red(self, r: dict) -> None:
        """Record the RED-baseline outcome of a step on a project red on checkout.

        Two cases, deciding whether the fix's verdict is SOUND or inconclusive:

          * DELTA-GREEN owned the verdict (``r`` carries a ``delta_green``
            disclosure — the gate ran in delta-green mode and KEPT the fix because
            it broke no previously-green test): the ``verified``/``coverage`` the
            delta-green gate stamped is HONEST and attributable (a regression would
            have rolled the fix back), so it is left untouched. Only the
            ``baseline_green=False`` disclosure is stamped — so the proof tells the
            full story AND the auto-commit is still WITHHELD on a red baseline
            (``_baseline_red_withheld`` keys on it — conservative, unchanged).
          * No delta-green disclosure (a covered-only WITHHELD move, a no-suite
            short-circuit, or a non-applied row): fall back to the original
            ``_apply_baseline_red`` downgrade (``verified=False``,
            ``coverage=baseline-red``) — the absolute-green attribution, unchanged.

        Mutates ``r`` in place. A no-op-shaped disclosure on a non-applied row
        (just ``baseline_green=False``), exactly as ``_apply_baseline_red`` did."""
        if "delta_green" in r and r.get("applied"):
            r["baseline_green"] = False
            return
        self._apply_baseline_red(r)

    def _apply_baseline_red(self, r: dict) -> None:
        """Downgrade an applied step's verification because the suite was already
        RED before any fix (cached ``_baseline_green is False``).

        A fix can't claim a green-after when the suite was failing first: the
        post-apply suite result — green or still-red — cannot be attributed to
        THIS fix. So the step is recorded INCONCLUSIVE, not verified:
          * ``verified`` -> False (the autonomous-commit gate then WITHHOLDS it);
          * ``coverage``/``verification_strength.level`` -> ``baseline-red`` (the
            weakest tier), so the proof manifest tallies it honestly;
          * ``baseline_green`` -> False on the result, carried into the proof.

        Mutates ``r`` in place. A no-op when ``r`` did not apply/verify (a
        rolled-back or blocked row carries no verification claim to downgrade).
        The raw ``suite_green`` / ``test_evidence`` are left untouched — they
        record what the post-apply run actually observed; only the *attribution*
        (``verified``/``coverage``) is corrected."""
        from app.engine.verification_strength import BASELINE_RED

        r["baseline_green"] = False
        if not r.get("applied"):
            return
        if "verified" in r or "verification_strength" in r:
            r["verified"] = False
            r["coverage"] = BASELINE_RED
            strength = dict(r.get("verification_strength") or {})
            strength["level"] = BASELINE_RED
            r["verification_strength"] = strength

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
        # DELTA-GREEN: the shield's own characterization test is verified against
        # the SAME red-baseline tolerance — so a shield can be generated on a
        # project red on checkout (a new passing test that breaks nothing) instead
        # of being rolled back by an unrelated pre-existing failure. None on a green
        # baseline ⇒ absolute-green, byte-identical.
        return self.bridge.apply_step(shield_step, self.project_root,
                                      mode=self.mode, verify=self.verify,
                                      baseline_failing=self._delta_baseline())

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
        cleans the file instead of one fix per pass.

        AUTONOMOUS-COMMIT GATE (per converged fix): each iteration is re-priced
        and re-gated EXACTLY as the primary step is — the loop must never bypass
        the moat the first fix enforces. The tier is read from the ACTUAL
        transform the apply emitted (``_converged_fix_tier``), so the detection
        ladder advancing fix-to-fix is honoured: a pure-annotation flag
        (``flag_*`` — a ``# SECURITY``/``# RELIABILITY`` comment) is Tier 0, a
        behaviour-CHANGING rewrite keeps the action's Tier 1. After applying, the
        change is routed through the SAME ``_unverified_behaviour_change`` gate:
        a behaviour-changing converged fix (e.g. ``subprocess shell=True`` ->
        ``shlex.split``, ``yaml.load`` -> ``safe_load``) on an uncovered module
        is left APPLIED on disk but WITHHELD from the auto-commit, and
        convergence STOPS — the file now carries an uncommitted change, so
        compounding further fixes on top of it is unsafe. A Tier-0 converged
        fix (another annotation/additive comment) still commits freely,
        preserving genuinely-safe convergence."""
        extra = 0
        for _ in range(5):
            # DELTA-GREEN: each converged fix is gated with the SAME red-baseline
            # tolerance as the primary step, so convergence keeps cleaning a file
            # on a red-baseline repo (each fix charged only for NEW regressions).
            # None on a green baseline ⇒ absolute-green, byte-identical.
            r2 = self.bridge.apply_step(step, self.project_root,
                                        mode=self.mode, verify=self.verify,
                                        baseline_failing=self._delta_baseline())
            if not (r2.get("applied") and step.target in (r2.get("changed_files") or [])):
                break
            extra += 1
            if not self._converge_commit_or_stop(r2, step, entry):
                break
        if extra:
            entry["converged_fixes"] = extra

    def _converge_commit_or_stop(self, r2: dict, step: ActionStep,
                                 entry: dict) -> bool:
        """Decide a converged fix's commit, returning True to keep converging.

        The per-iteration commit gate of :meth:`_converge_harden`, extracted to
        keep that loop under the complexity ceiling — behaviour is unchanged. In
        order, each gate that fires WITHHOLDS the auto-commit (leaving the fix on
        disk), fences its files so no later same-file step sweeps the hunk into
        git, and returns False to STOP converging on an uncommitted file:

          * RED-BASELINE — the suite was already failing on checkout, so a
            green-after cannot be attributed move-by-move (the SAME conservative
            posture ``_settle_applied`` takes for the primary step). Delta-green
            verified the fix, but the COMMIT is still withheld. (Before delta-green
            the absolute-green gate rolled the second fix back immediately, so this
            path was never reached on a red baseline — no byte-identity to keep.)
          * UNVERIFIED BEHAVIOUR CHANGE — a Tier-1 rewrite on a module no test
            exercises (the moat the primary fix enforces, never bypassed here).
          * FENCED FILE — an earlier withheld hunk is still on disk; whole-file
            staging would sweep it into git.

        Otherwise the fix commits freely (a genuinely-safe Tier-0 converged fix)
        and convergence continues. The committer is ``None`` outside autonomous
        mode, so every gate is inert there and the path is byte-identical."""
        if self.committer is not None and self._baseline_green is False:
            entry["converged_withheld"] = True
            entry["baseline_red"] = True
            entry["reason"] = (
                "converged fix applied, NOT committed — the suite was already "
                "failing before this pass, so a green run cannot be attributed "
                "to it (verification inconclusive); review manually"
            )
            self._fence_files(*(r2.get("changed_files") or []), step.target)
            return False
        # Price the fix that ACTUALLY landed (authoritative post-apply), then
        # apply the same withhold semantics as ``_settle_applied``: never
        # auto-commit an unverified behaviour change.
        tier2 = self._converged_fix_tier(r2, step.action_type)
        if (self.committer is not None
                and self._unverified_behaviour_change(r2, tier2)):
            entry["converged_withheld"] = True
            entry["reason"] = (
                "converged fix applied, NOT committed — unverified "
                "behaviour change (tier-1 rewrite on a module with no "
                "covering test); review before committing"
            )
            self._fence_files(*(r2.get("changed_files") or []), step.target)
            return False
        # A fenced file (an earlier withheld change still on disk) must not be
        # auto-committed even by a safe converged fix — whole-file staging would
        # sweep the withheld hunk into git. Check EVERY file this commit would
        # stage, not just ``step.target``, so a cross-file converged result can't
        # bypass the fence on a sibling path.
        if (self.committer is not None
                and self._commit_touches_fenced(r2, step)):
            return False
        ok2, _h2 = self._commit(r2, step.action_type)
        if ok2:
            self.committed += 1
        return True

    @staticmethod
    def _converged_fix_tier(r: dict, action_type: str) -> int:
        """The risk tier of the fix a convergence pass ACTUALLY emitted.

        Read from the result's concrete ``transform_type`` (authoritative after
        the apply, where ``_prospective_transform_type`` — a pre-apply, security-
        only probe — cannot see the advanced ladder). Every ``flag_*`` transform
        is a pure-annotation comment (``# SECURITY``/``# RELIABILITY``): it leaves
        the runnable AST byte-identical, so it is Tier 0 / additive exactly like
        the three registered annotation security flags. Any other transform falls
        back to ``tier_for_transform`` — so a behaviour-CHANGING rewrite keeps the
        carrying action's Tier 1 and its coverage gate."""
        from app.execution.risk_tiers import tier_for_transform

        transform_type = r.get("transform_type")
        if isinstance(transform_type, str) and transform_type.startswith("flag_"):
            return 0
        return tier_for_transform(transform_type, action_type)

    def _learned_skip(self, step: ActionStep) -> bool:
        """OPT-IN closed loop: skip a fix the proof history predicts will fail.

        Returns True (and records a ``skipped_learned`` row) when the avoid-map
        flags this step's ``(action_type, module-trait)`` signature — saving the
        wasted apply+rollback. With no avoid-map (default) this is a no-op and
        always returns False, so the run stays byte-identical."""
        if not self.avoid_signatures:
            return False
        from app.engine.counterfactual_learning import module_traits, should_avoid

        if not should_avoid(self.avoid_signatures, step.action_type,
                            module_traits(step.target)):
            return False
        self.skipped_learned += 1
        self.results.append({
            "branch": step.branch_path, "action": step.action_type,
            "operator": step.operator, "target": step.target,
            "applied": False, "skipped_learned": True,
            "reason": _learned_skip_reason(self.avoid_signatures, step),
        })
        return True

    def _effective_tier(self, step: ActionStep) -> int:
        """The risk tier of the fix this step will actually emit.

        For a ``harden_security`` step whose next fix is a pure-annotation flag,
        this is Tier 0 (a ``# SECURITY`` comment changes no behaviour); every
        other fix keeps its action's tier — so a behaviour-changing harden stays
        Tier 1 with its coverage gate intact."""
        from app.execution.risk_tiers import tier_for_transform

        transform_type = self.bridge._prospective_transform_type(
            self.project_root, step)
        return tier_for_transform(transform_type, step.action_type)

    def run_step(self, step: ActionStep) -> None:
        # CASCADE-DRAIN dedup: when the outer drain loop is active, a step whose
        # ``(action, target)`` signature was already attempted in an earlier round
        # (applied, withheld, fenced, or blocked) is skipped silently — no row, no
        # counter, no re-apply. This is what stops the drain from looping forever
        # re-attempting a withheld/fenced fix. Default single pass never arms the
        # flag, so this guard is inert and the path stays byte-identical.
        if self._drain_active and self._signature(step) in self._handled:
            return
        if self._learned_skip(step):
            return
        # ONE-TIME baseline pre-flight: probe (and cache) whether the suite was
        # green BEFORE this pass touched anything — done before the first apply
        # (and before any shield apply), so the recorded baseline reflects the
        # untouched tree. Only when verifying; the result is cached, so later
        # steps never re-run the suite.
        if self.verify:
            self._ensure_baseline()
        tier = self._effective_tier(step)
        # A Tier-0 (additive / comment-only) fix needs no characterization
        # shield: it changes no executable code, so there is nothing for a
        # network-calling contract test to protect — generating one would only
        # fail and roll the comment back. Shield only the behaviour-adjacent fixes.
        shield_result = self._shield(step) if tier >= 1 else None
        label = step.source_facts[0].split(":")[0].strip() if step.source_facts else ""
        if self._tier_blocked(step, tier, label, shield_result):
            return

        # The first apply classifies the step (applied / rolled-back /
        # blocked), exactly one result row per step. COVERED-ONLY (the SAFE-by-
        # default sweep) is forwarded so a green-but-unreferencing move is
        # withheld (rolled back, reported) rather than landed; off ⇒ unchanged.
        # DELTA-GREEN: the cached RED-baseline failing set (``None`` when green ⇒
        # ABSOLUTE-green, byte-identical) is threaded so a correct fix LANDS on a
        # red-baseline repo while a regression is still rolled back — front-door
        # parity with develop, the SAME gate ``apply_rename`` uses.
        r = self.bridge.apply_step(step, self.project_root, mode=self.mode,
                                   verify=self.verify,
                                   covered_only=self.covered_only,
                                   baseline_failing=self._delta_baseline())
        # BASELINE-RED disclosure: when the suite was already failing before any
        # fix, stamp that fact (and, where delta-green did NOT own the verdict,
        # downgrade the attribution to inconclusive). The green-baseline path
        # leaves ``r`` untouched, so it stays byte-identical to today.
        if self.verify and self._baseline_green is False:
            self._settle_baseline_red(r)
        entry = {"branch": step.branch_path, "action": step.action_type,
                 "operator": step.operator, "label": label,
                 "target": step.target, "risk_tier": tier, **r}
        self._record_shield_commit(entry, shield_result)
        self._record_outcome(step, r, entry)

    def _record_shield_commit(self, entry: dict, shield_result: dict | None) -> None:
        """Stamp the applied shield test onto ``entry`` and commit it.

        Extracted verbatim from :meth:`run_step` to keep that method under the
        complexity ceiling; behaviour is byte-identical — only an applied shield
        records a ``shield_test`` file and bumps ``committed`` on a successful
        ``create_test_stub`` commit. A ``None`` / non-applied shield is a no-op.
        """
        if shield_result is not None and shield_result.get("applied"):
            entry["shield_test"] = (shield_result.get("changed_files") or [""])[0]
            ok_s, _h = self._commit(shield_result, "create_test_stub")
            if ok_s:
                self.committed += 1

    @staticmethod
    def _unverified_behaviour_change(r: dict, tier: int) -> bool:
        """AUTONOMOUS-COMMIT GATE: should this applied step be withheld from
        the auto-commit because it is an unverified behaviour change?

        True only when BOTH hold:
          (a) ``tier >= 1`` — the action is behaviour-adjacent (a Tier-1
              security rewrite like ``eval`` → ``literal_eval``); Tier-0
              fixes are semantics-preserving/additive and commit freely.
          (b) the coverage-aware ``verified`` is False — i.e. no test
              actually exercises the changed function. A green suite whose
              only cover is the test-first smoke-import shield reports
              ``coverage`` in {"none", "module"} and ``verified=False``;
              a real function-level test reports ``verified=True``.

        Such a step stays APPLIED on disk but is NOT committed: a buyer must
        never get an unverified behaviour change silently auto-committed.
        """
        if tier < 1:
            return False
        if r.get("verified") is True:
            return False
        return r.get("coverage") in (None, "none", "module")

    @staticmethod
    def _baseline_red_withheld(r: dict) -> bool:
        """Should this applied step be WITHHELD because the suite was already RED
        before any fix? True when the baseline pre-flight recorded a non-green
        baseline (``baseline_green is False`` was stamped onto the result): the
        post-apply suite — green or still-red — cannot vouch for this fix, so no
        applied fix (any tier) auto-commits. False otherwise (the common
        green-baseline case carries no ``baseline_green`` key, so this is a
        no-op and the commit path is byte-identical)."""
        return r.get("baseline_green") is False

    def _settle_applied(self, step: ActionStep, r: dict, entry: dict) -> None:
        """Bookkeeping for an applied fix: commit, then harden-converge."""
        self.applied += 1
        tier = entry.get("risk_tier", 0)
        # BASELINE-RED gate (composes with the tier-1 and fence gates below):
        # the suite was already failing before this pass, so a green-after cannot
        # be attributed to this fix. Keep it applied on disk for review but never
        # auto-commit it, and fence its files so a later same-file step can't
        # sweep the un-attributable hunk into git either.
        if self.committer is not None and self._baseline_red_withheld(r):
            entry["committed"] = False
            entry["commit_withheld"] = True
            entry["baseline_red"] = True
            entry["reason"] = (
                "applied, NOT committed — the test suite was already failing "
                "before this fix, so a green run cannot be attributed to it "
                "(verification inconclusive); review manually"
            )
            self._fence_files(*(r.get("changed_files") or []), step.target)
            return
        # Autonomous mode (the only mode where ``committer`` is set) must never
        # auto-commit an unverified behaviour change. Keep it applied on disk —
        # supervised/dry-run never reach here with a committer, so their apply
        # behaviour is unchanged — but withhold the commit and say so.
        if self.committer is not None and self._unverified_behaviour_change(r, tier):
            entry["committed"] = False
            entry["commit_withheld"] = True
            entry["reason"] = (
                "applied, NOT committed — unverified behaviour change "
                "(tier-1 fix covered only by a smoke shield, no function-level "
                "test); review before committing"
            )
            # Fence every file this withheld change touched: a later same-file
            # step must not sweep the still-on-disk hunk into git.
            self._fence_files(*(r.get("changed_files") or []), step.target)
            return
        # FENCE GATE: even a genuinely-safe (Tier-0) fix must NOT auto-commit a
        # file that already carries an earlier, unreviewed withheld change —
        # whole-file staging would sweep that hunk into git unreviewed. Leave
        # this fix applied-on-disk too, record it as fenced, and do not commit.
        # Gate on EVERY file the commit would stage (not just ``step.target``),
        # so a cross-file result whose ``changed_files`` includes a fenced
        # sibling is blocked too.
        if self.committer is not None and self._commit_touches_fenced(r, step):
            entry["committed"] = False
            entry["commit_withheld"] = True
            entry["fenced"] = True
            entry["reason"] = (
                "not committed — file carries an unreviewed withheld change "
                "from an earlier fix in this pass; review the file before "
                "committing"
            )
            return
        ok, h = self._commit(r, step.action_type)
        entry["committed"] = ok
        if ok:
            self.committed += 1
            entry["commit_hash"] = h
        real_fix = step.target in (r.get("changed_files") or [])
        if step.action_type == "harden_security" and real_fix:
            self._converge_harden(step, entry)

    @staticmethod
    def _signature(step: ActionStep) -> tuple[str, str]:
        """The dedup key for the cascade-drain skip-set: ``(action, target)``.

        Deterministic and pure (no clock/random) — two steps that propose the
        same action on the same module collapse to one handled signature, so a
        re-built plan never re-attempts a fix an earlier round already settled
        (applied, withheld, fenced, or blocked)."""
        return (step.action_type, step.target)

    def _record_outcome(self, step: ActionStep, r: dict, entry: dict) -> None:
        """Classify the apply result into exactly one counter + result row."""
        if r.get("rolled_back"):
            self.rolled_back += 1
            # ATTEMPTS BUDGET: a rolled-back step DID reach apply (transform +
            # verify ran) — it counts as one attempt.
            self.attempted += 1
            # COVERED-ONLY: a move the sweep PREVIEWED but withheld (green suite,
            # no test exercises it) is a distinct, reportable outcome — counted so
            # the run can say how many + that ``--allow-weak`` lands them. Inert
            # without the gate (the key is never set), so byte-identical.
            if r.get("withheld_uncovered"):
                self.withheld_uncovered += 1
        elif r.get("applied"):
            # ATTEMPTS BUDGET: an applied step also reached apply — one attempt.
            self.attempted += 1
            self._settle_applied(step, r, entry)
        else:
            self.blocked += 1
        # CASCADE-DRAIN: mark this signature handled (whatever the outcome) and
        # remember every file the fix actually touched, so a later drain round
        # re-detects over only the changed set and never re-attempts this step.
        # Inert in a single pass (the sets are never read), so byte-identical.
        self._handled.add(self._signature(step))
        for f in (r.get("changed_files") or []):
            if f:
                self._changed_files.add(self._norm_path(f))
        self.results.append(entry)

    def _apply_steps(self, steps, max_apply: int | None,
                     max_attempts: int | None = None) -> None:
        """Apply a list of executable steps under the SHARED ``max_apply`` and
        ``max_attempts`` budgets. Both are read from the live ``self.applied`` /
        ``self.attempted`` counters, so neither is reset between drain rounds —
        total applied across ALL rounds can never exceed ``max_apply``, and total
        attempts (applied OR rolled_back) can never exceed ``max_attempts``."""
        for step in steps:
            if max_apply is not None and self.applied >= max_apply:
                break
            # ATTEMPTS BUDGET: stop once we've spent the attempt ceiling, even if
            # ``max_apply`` still has room — this is the cost ceiling on
            # apply+rollback cycles. ``None`` -> no cap, byte-identical to today.
            if max_attempts is not None and self.attempted >= max_attempts:
                break
            self.run_step(step)

    def _drain_rounds(self, replan, max_apply: int | None,
                      max_attempts: int | None, max_rounds: int) -> int:
        """OUTER convergence loop: re-detect → re-plan → apply, until a round
        applies ZERO new fixes or ``max_rounds`` is reached.

        Runs AFTER the first (single) pass has applied its steps. Each round:
          1. snapshot the sorted changed set + the applied count;
          2. call ``replan(changed_files)`` for a freshly-detected plan over only
             those files (re-detection sees fixes that earlier fixes exposed);
          3. apply its executable steps — ``run_step`` drops any signature already
             in ``_handled`` (so a withheld/fenced fix is never re-attempted), and
             the SHARED ``max_apply`` budget is honoured across rounds;
          4. stop when no NEW signature applied a real change this round, or the
             cap is hit, or the apply/attempts budget is exhausted, or ``replan``
             yields nothing.

        Determinism: the changed set is sorted before re-plan; rounds are capped;
        no clock/random. Returns the number of extra rounds executed (0 when the
        first pass already converged)."""
        self._drain_active = True
        rounds = 0
        while rounds < max_rounds:
            before_applied = self.applied
            before_handled = len(self._handled)
            steps = self._next_round_steps(replan, max_apply, max_attempts)
            if steps is None:
                break
            self._apply_steps(steps, max_apply, max_attempts)
            rounds += 1
            # Progress = a NEW signature actually APPLIED a fix this round. A round
            # that only re-surfaced already-handled steps, or whose new steps all
            # blocked/withheld without applying, makes no progress -> converged.
            if self.applied <= before_applied or len(self._handled) <= before_handled:
                break
        self._drain_active = False
        return rounds

    def _next_round_steps(self, replan, max_apply: int | None,
                          max_attempts: int | None) -> list[ActionStep] | None:
        """The fresh, not-yet-handled steps for the next drain round, or ``None``.

        Extracted verbatim from :meth:`_drain_rounds` to keep that loop under the
        complexity ceiling; behaviour is byte-identical. Returns ``None`` (the
        loop's ``break`` signal) when any stop condition holds — the shared
        apply/attempts budget is exhausted, no files changed, ``replan`` raises,
        or it yields no unhandled executable steps — otherwise the filtered list.
        """
        if max_apply is not None and self.applied >= max_apply:
            return None
        # ATTEMPTS BUDGET: the attempt ceiling is SHARED across drain rounds —
        # once total attempts (applied + rolled_back, accumulated since the
        # single pass) reach it, no further round runs. Inert when None.
        if max_attempts is not None and self.attempted >= max_attempts:
            return None
        changed = sorted(self._changed_files)
        if not changed:
            return None
        try:
            plan = replan(changed)
        except Exception:
            # A re-plan that raises ends the drain cleanly — the single-pass
            # results already recorded stand; the drain never crashes a run.
            return None
        steps = list(plan.executable_steps()) if plan is not None else []
        steps = [s for s in steps if self._signature(s) not in self._handled]
        if not steps:
            return None
        return steps


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
    # Proof of coverage — separates a strong "verified" (a test names this
    # module) from a hollow "applied blind" (no test ever looks at it). Only
    # rendered when attach_proofs recorded the signal; older previews omit it.
    if "covered" in pv:
        coverage_clause = (" · your tests reference this module ✓"
                           if pv.get("covered")
                           else " · ⚠️ no test exercises this — add one first")
    else:
        coverage_clause = ""
    return (f"    proof: +{pv.get('added', 0)} −{pv.get('removed', 0)}, "
            f"{verdict}{impact_clause}{coverage_clause} "
            f"— `apex brief {step.branch_path}` for the full diff")


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
    elif r.get("suite_available") is False:
        # HONEST no-suite disclosure: the change was kept but NOTHING ran — no
        # test command was detected, so it is NOT verified and auto-rollback
        # could not have protected it. Never blend this with a verified fix.
        extra += (" (⚠️ NOT verified — no test suite detected to run; "
                  "auto-rollback could not protect this change)")
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
        ("## ⏭️ Skipped (learned failure)",
         [r for r in results if r.get("skipped_learned")],
         lambda r: f"- `{r['branch']}` **{r['action']}** — {r.get('reason', '')}"),
        ("## ⛔ Blocked / not applicable",
         [r for r in results if not r.get("applied")
          and not r.get("rolled_back") and not r.get("skipped_learned")],
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
    if summary.get("verification_unavailable"):
        # VERIFICATION UNAVAILABLE — pytest is not importable under the interpreter
        # Apex would invoke, so the pass DECLINED before applying anything (nothing
        # verified, nothing rolled back). Lead with the loud, actionable message so
        # the user sees the real, fixable cause — never a silent "0 applied".
        lines += [
            "",
            f"⚠️ **{summary['verification_unavailable']}**",
            "",
        ]
        return "\n".join(lines)
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
