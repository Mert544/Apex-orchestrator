"""Deterministic scanner for safe-simplification opportunities.

Apex already owns 20 behaviour-preserving AST simplification transforms in
``app/execution/semantic/transforms/`` and the idea action bridge already makes
them EXECUTABLE (each carries the same refuse-on-unsafe, self-reparsing,
test-verified, auto-rollback apply path). What was missing is the discovery
end: nothing tells the seeder WHICH modules a transform would actually fire on,
so ``apex develop`` / ``maintain`` never got those fact-labels.

:func:`scan_simplifications` closes that gap. It runs every safe transform in
DRY-RUN over each in-scope ``.py`` file (the transform's own ``apply`` returns a
non-``None`` result exactly when it WOULD act, and ``None`` when it can't act
safely), and records one opportunity per (module, transform) hit using the EXACT
fact-label the bridge's ``_FACT_ACTIONS`` expects.

Properties:

  - Pure: no writes, no clock, no randomness, no network. Same tree in → same
    list out.
  - Honest: an opportunity is recorded ONLY when the real transform returns a
    patch, so the seeder never emits a fact for a transform that would refuse.
  - Scoped: fixtures and test files are excluded (they exist to TRIGGER the
    transforms, not to be cleaned), and the directory walk reuses Apex's
    canonical skip-set via ``iter_source_files``.
  - Capped + sorted: results are sorted by ``(module, fact_label)`` and capped,
    so the downstream idea budget sees a stable, reproducible slice.

The profiler hook that stores this list on ``ProjectProfile`` is live:
``project_profile.py`` calls :func:`scan_simplifications` and populates
``ProjectProfile.simplification_opportunities``, which ``IdeaSeeder`` reads to
emit one executable root per opportunity. This module is the pure producer at
the head of that chain.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.engine.skip_dirs import iter_source_files

# Deterministic top-N cap on the emitted opportunity list. Kept small so the
# simplification family never floods the shared idea budget.
_MAX_OPPORTUNITIES = 8

# Title handed to each transform's ``apply``. The transforms use it only for the
# proof/preview row, never for the decision to act, so a fixed neutral string
# keeps the scan pure (no per-file text that could perturb the result).
_DRY_RUN_TITLE = "simplification scan (dry-run)"


def plan_to_apply(plan_fn: Callable[..., object]):
    """Adapt a ``plan_<name>(project_root, module_rel) -> RenamePlan`` transform
    to the uniform ``apply(rel_path, source, title)`` shape every other safe
    transform exposes — so the family of ``app/execution/`` source rewrites
    (``nested_with``, ``comprehension``, ``use_enumerate``,
    ``simplify_len_comparison``) plugs into the SAME dry-run scan and the SAME
    ``_simplify_dispatch`` apply path as the ``semantic/transforms/`` rewrites.

    Those ``plan_*`` transforms read their input from disk (they take a
    project root and a relative path, not a source string), so the adapter feeds
    ``source`` to the real ``plan_fn`` IN MEMORY via
    ``_plan_transforms.plan_from_source`` (no temp dir, no disk write, no
    re-read), and translates the resulting ``RenamePlan`` back into a
    :class:`SemanticPatchResult`:

      - a plan with no rewrite (``not plan.ok`` — empty ``new_contents`` or a
        recorded blocker) → ``None``, the exact refuse-on-unsafe contract the
        dispatch already relies on (an unsafe input fabricates nothing);
      - otherwise a single patch request carrying the original source as
        ``expected_old_content`` and the transform's rewritten text as
        ``new_content`` — the same shape the in-place transforms emit, so the
        guarded ``apply_step`` gate (snapshot → write → verify → auto-rollback)
        treats it identically.

    Pure and deterministic: the transform keys off ``rel_path`` + source only,
    nothing under the real project tree is read or written, and no filesystem is
    touched at all (the source is supplied in memory). Never raises — a transform
    that errors on exotic input is treated as "would not safely act" (``None``),
    matching the scan's own guard.
    """

    def _apply(rel_path: str, source: str, _title: str):
        from app.execution._plan_transforms import plan_from_source
        from app.execution.semantic.result import SemanticPatchResult

        # Normalise to a forward-slash relative path — the exact ``module_rel``
        # spelling the on-disk ``plan_*`` transform keys ``is_fixture_path`` and
        # its file-keyed plan mappings off — then run the transform against the
        # in-memory source (no temp dir, no disk write, no re-read). The result
        # is byte-identical to mirroring ``source`` to a temp ``droot / rel`` and
        # running ``plan_fn(droot, rel)`` against it.
        rel = Path(rel_path).as_posix()
        try:
            plan = plan_from_source(plan_fn, rel, source)
        except Exception:
            return None
        if not getattr(plan, "ok", False):
            return None  # no rewrite / blocked → refuse, fabricate nothing
        new_content = plan.new_contents.get(rel)
        if new_content is None or new_content == source:
            return None
        edits = plan.edits_by_file.get(rel, 1)
        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": new_content,
                "expected_old_content": source,
            }],
            transform_type=plan.new,
            rationale=[
                f"Applied {edits} behaviour-preserving {plan.new} "
                f"simplification(s) in {rel_path}."
            ],
        )

    return _apply


def _transforms() -> list[tuple[str, Callable[[str, str, str], object]]]:
    """The safe transforms as ``(fact_label, apply)`` pairs.

    Each ``apply(rel_path, source, title)`` is the transform's own pure entry
    point: it returns a patch result when it WOULD act and ``None`` otherwise.
    ``augmented_assign.apply`` is the lone 2-arg signature, so it is adapted to
    the uniform 3-arg shape (mirroring the bridge's ``_simplify_dispatch``).

    The ``fact_label`` is the EXACT key the bridge's ``_FACT_ACTIONS`` maps to an
    executable action — emitting any other spelling would route the seeded idea
    to the generic recommend-only fallback instead of the real transform.
    """
    # All on-disk ``plan_<name>`` transforms come from the single shared binding
    # module (``app.execution._plan_transforms``), referenced as
    # ``_pt.plan_<name>``. This replaces the former per-transform import list
    # (consolidated here and in the bridge's ``_simplify_dispatch`` to drain the
    # duplicate-window metric); the callables are the SAME function objects.
    from app.execution import _plan_transforms as _pt
    # One namespace import of the transforms package replaces the former
    # per-transform import list (consolidated here and in the bridge's
    # ``_simplify_dispatch`` to drain the duplicate-window metric). The package
    # ``__init__`` eagerly binds each submodule, so ``_t.<name>`` resolves; the
    # pairs below reference the exact same callables as before.
    from app.execution.semantic import transforms as _t

    return [
        ("merge-nested-if", _t.merge_nested_if.apply),
        ("redundant-else", _t.redundant_else.apply),
        ("dict-get-default", _t.dict_get_default.apply),
        ("isinstance-merge", _t.isinstance_merge.apply),
        ("none-compare", _t.simplify_comparison.apply),
        ("unreachable-code", _t.unreachable_cleanup.apply),
        ("chained-comparison", _t.chained_comparison.apply),
        ("redundant-lambda", _t.redundant_lambda.apply),
        ("set-literal", _t.set_literal.apply),
        ("startswith-tuple", _t.startswith_tuple.apply),
        ("not-in-simplify", _t.not_in_simplify.apply),
        ("tuple-membership", _t.tuple_membership.apply),
        ("dict-literal", _t.dict_literal.apply),
        ("double-not", _t.double_not.apply),
        ("swap-via-tuple", _t.swap_via_tuple.apply),
        ("membership-set", _t.membership_set.apply),
        ("percent-string-concat", _t.percent_string_concat.apply),
        # Two more behaviour-preserving readability transforms, each a pure 3-arg
        # ``apply`` that validates its own output and refuses (None) when it can't
        # act safely — both distinct from every transform above (collection_literal
        # rewrites empty constructors; fstring drops a dead `f` prefix and proves
        # the result parses to the same string).
        ("collection-literal", _t.collection_literal.apply),
        ("fstring-no-placeholder", _t.fstring.apply),
        # ``a if a else b`` -> ``a or b``, but ONLY when the test and the
        # true-branch are the SAME side-effect-free expression (a Name or an
        # attribute chain). ``a or b`` evaluates ``a`` once where the ternary
        # evaluates it twice, so the rewrite is value-identical only for a pure
        # ``a``; a call/subscript/bool-op test is refused (None). Distinct from
        # ``ternary-bool`` (which matches ``True if c else False`` bool literals).
        ("or-default", _t.or_default.apply),
        # A correctness-preserving fix the bridge ALSO makes executable (its
        # ``mutable-default`` fact routes to ``fix_mutable_defaults`` via the
        # same SemanticPatchGenerator + guarded apply_step path). The classic
        # ``def f(x=[])`` footgun: the transform rewrites it to the sentinel
        # ``def f(x=None): if x is None: x = []`` form, is idempotent (a None
        # default is no longer flagged), and refuses via None on any function
        # without a mutable default — so it never fabricates an opportunity. It
        # is distinct from every readability transform above (none of which
        # touches default arguments) and overlaps none of them.
        ("mutable-default", _t.mutable_defaults.apply),
        # 2-arg signature → adapt to the uniform 3-arg dry-run call.
        ("augmented-assign", lambda rel, src, _title: _t.augmented_assign.apply(rel, src)),
        # Four more behaviour-preserving rewrites that live under
        # ``app/execution/`` as on-disk ``plan_<name>(root, rel) -> RenamePlan``
        # transforms rather than in-memory ``apply``. ``plan_to_apply`` adapts
        # each to the uniform 3-arg dry-run shape (materialise source → run the
        # real plan → translate the RenamePlan), so they dry-run and apply
        # through the SAME refuse-on-unsafe, re-parsing, auto-rollback path as
        # every transform above. Each is strictly guarded and distinct:
        #   - nested-with collapses ``with A:\n with B:`` → ``with A, B:``;
        #   - comprehension folds ``out=[]`` + ``for ...: out.append(x)`` into a
        #     list comprehension;
        #   - use-enumerate rewrites ``for i in range(len(seq)): seq[i]`` into
        #     ``for _, item in enumerate(seq)`` (``i`` proven used only as the
        #     index, ``seq`` proven not rebound);
        #   - len-comparison rewrites ``len(x) == 0`` / ``!= 0`` / ``> 0`` /
        #     ``>= 1`` into ``not x`` / ``bool(x)`` ONLY in a boolean context.
        # ``merge_isinstance`` (also a ``plan_*`` transform) is deliberately
        # EXCLUDED here — it is the exact duplicate of the already-wired
        # ``isinstance-merge`` in-memory transform above.
        ("nested-with", plan_to_apply(_pt.plan_combine_nested_with)),
        ("comprehension", plan_to_apply(_pt.plan_simplify_comprehension)),
        ("use-enumerate", plan_to_apply(_pt.plan_use_enumerate)),
        ("len-comparison", plan_to_apply(_pt.plan_simplify_len_comparison)),
        # Seven more on-disk ``plan_<name>(root, rel) -> RenamePlan`` rewrites
        # under ``app/execution/``, each adapted by ``plan_to_apply`` to the same
        # uniform 3-arg dry-run shape as the four above, so they dry-run and
        # apply through the IDENTICAL refuse-on-unsafe, re-parsing, auto-rollback
        # path. Each is strictly guarded, distinct from every transform above,
        # and NOT one of the audit's DO-NOT-WIRE duplicates:
        #   - bool-return collapses ``if c: return True / else: return False``
        #     into ``return bool(c)``;
        #   - ternary-bool rewrites ``True if c else False`` -> ``bool(c)``;
        #   - dict-get-ternary rewrites ``x[k] if k in x else d`` ->
        #     ``x.get(k, d)`` (pure container + key only);
        #   - dict-comprehension folds an ``out = {}`` + ``for ...: out[k] = v``
        #     accumulator into a dict comprehension;
        #   - ordering-negation rewrites ``not a < b`` -> ``a >= b`` for ORDERING
        #     ops only (Eq/membership/identity are left to their owning
        #     transforms, so it does not duplicate double_not / fix_not_in_is);
        #   - pointless-pass deletes a redundant ``pass`` that is not the lone
        #     statement of its block;
        #   - assert-tuple is a CORRECTNESS fix: ``assert (cond, "msg")`` (an
        #     always-true tuple) -> ``assert cond, "msg"``.
        ("simplify-bool-return", plan_to_apply(_pt.plan_simplify_bool_return)),
        ("ternary-bool", plan_to_apply(_pt.plan_simplify_ternary_bool)),
        ("dict-get-ternary", plan_to_apply(_pt.plan_simplify_dict_get)),
        ("dict-comprehension", plan_to_apply(_pt.plan_dict_comprehension)),
        ("ordering-negation", plan_to_apply(_pt.plan_simplify_negated_comparison)),
        ("pointless-pass", plan_to_apply(_pt.plan_remove_pointless_pass)),
        ("assert-tuple", plan_to_apply(_pt.plan_fix_assert_tuple)),
        # One more on-disk ``plan_simplify_bool_comparison(root, rel) ->
        # RenamePlan`` rewrite under ``app/execution/``, adapted by the SAME
        # ``plan_to_apply`` so it dry-runs and applies through the IDENTICAL
        # refuse-on-unsafe, re-parsing, auto-rollback path. It drops a redundant
        # equality/identity comparison against a ``True``/``False`` literal, but
        # ONLY when the other operand is SYNTACTICALLY provably-bool (a ``not ...``
        # or a ``Compare``) — a bare name/call is left untouched, so the scan
        # never fabricates an unsound opportunity. Distinct from ``none-compare``
        # (which only handles ``== None``); NOT a DO-NOT-WIRE duplicate.
        ("bool-comparison", plan_to_apply(_pt.plan_simplify_bool_comparison)),
    ]


def _is_excluded(rel_path: str) -> bool:
    """True for fixtures and test files — they exist to TRIGGER transforms.

    A pure path-name check (the directory walk already drops worktrees/caches via
    ``iter_source_files``): we additionally skip anything under a ``fixtures`` or
    ``tests`` directory and any ``test_*.py`` / ``*_test.py`` file, so the scan
    only ever proposes cleaning real source.
    """
    parts = Path(rel_path).parts
    if "fixtures" in parts or "tests" in parts:
        return True
    name = Path(rel_path).name
    return name.startswith("test_") or name.endswith("_test.py")


def scan_simplifications(root: str | Path, max_files: int = 500) -> list[dict]:
    """Find files where a safe simplification transform WOULD fire.

    Walks up to ``max_files`` in-scope ``.py`` files under ``root`` (fixtures and
    tests excluded), runs every safe transform in DRY-RUN over each, and records
    ``{"module", "transform", "fact_label"}`` for each (file, transform) where the
    transform returns a non-``None`` patch (i.e. it would act).

    Returns the top ``_MAX_OPPORTUNITIES`` opportunities, deterministically
    sorted by ``(module, fact_label)``. Pure: no writes, no clock, no randomness.
    """
    root = Path(root)
    transforms = _transforms()

    files = [
        p for p in iter_source_files(root, "*.py")
        if not _is_excluded(str(p.relative_to(root)))
    ][:max_files]

    opportunities: list[dict] = []
    for path in files:
        rel = str(path.relative_to(root))
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # A non-UTF-8 / near-binary .py (generated, vendored, mis-encoded)
            # is unanalysable, not a crash: skip it rather than letting the
            # decode error abort the whole scan.
            continue
        for fact_label, apply in transforms:
            try:
                result = apply(rel, source, _DRY_RUN_TITLE)
            except Exception:
                # A transform that raises on some exotic input is treated as
                # "would not safely act" — never a fabricated opportunity.
                result = None
            if result is not None:
                opportunities.append({
                    "module": rel,
                    "transform": fact_label.replace("-", "_"),
                    "fact_label": fact_label,
                })

    opportunities.sort(key=lambda o: (o["module"], o["fact_label"]))
    return opportunities[:_MAX_OPPORTUNITIES]
