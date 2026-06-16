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

The profiler hook that stores this list on ``ProjectProfile`` is a separate
owner's follow-up; this module is the pure producer.
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
    from app.execution.semantic.transforms import augmented_assign
    from app.execution.semantic.transforms import chained_comparison
    from app.execution.semantic.transforms import collection_literal
    from app.execution.semantic.transforms import dict_get_default
    from app.execution.semantic.transforms import dict_literal
    from app.execution.semantic.transforms import double_not
    from app.execution.semantic.transforms import fstring
    from app.execution.semantic.transforms import isinstance_merge
    from app.execution.semantic.transforms import membership_set
    from app.execution.semantic.transforms import merge_nested_if
    from app.execution.semantic.transforms import mutable_defaults
    from app.execution.semantic.transforms import not_in_simplify
    from app.execution.semantic.transforms import percent_string_concat
    from app.execution.semantic.transforms import redundant_else
    from app.execution.semantic.transforms import redundant_lambda
    from app.execution.semantic.transforms import set_literal
    from app.execution.semantic.transforms import simplify_comparison
    from app.execution.semantic.transforms import startswith_tuple
    from app.execution.semantic.transforms import swap_via_tuple
    from app.execution.semantic.transforms import tuple_membership
    from app.execution.semantic.transforms import unreachable_cleanup

    return [
        ("merge-nested-if", merge_nested_if.apply),
        ("redundant-else", redundant_else.apply),
        ("dict-get-default", dict_get_default.apply),
        ("isinstance-merge", isinstance_merge.apply),
        ("none-compare", simplify_comparison.apply),
        ("unreachable-code", unreachable_cleanup.apply),
        ("chained-comparison", chained_comparison.apply),
        ("redundant-lambda", redundant_lambda.apply),
        ("set-literal", set_literal.apply),
        ("startswith-tuple", startswith_tuple.apply),
        ("not-in-simplify", not_in_simplify.apply),
        ("tuple-membership", tuple_membership.apply),
        ("dict-literal", dict_literal.apply),
        ("double-not", double_not.apply),
        ("swap-via-tuple", swap_via_tuple.apply),
        ("membership-set", membership_set.apply),
        ("percent-string-concat", percent_string_concat.apply),
        # Two more behaviour-preserving readability transforms, each a pure 3-arg
        # ``apply`` that validates its own output and refuses (None) when it can't
        # act safely — both distinct from every transform above (collection_literal
        # rewrites empty constructors; fstring drops a dead `f` prefix and proves
        # the result parses to the same string).
        ("collection-literal", collection_literal.apply),
        ("fstring-no-placeholder", fstring.apply),
        # A correctness-preserving fix the bridge ALSO makes executable (its
        # ``mutable-default`` fact routes to ``fix_mutable_defaults`` via the
        # same SemanticPatchGenerator + guarded apply_step path). The classic
        # ``def f(x=[])`` footgun: the transform rewrites it to the sentinel
        # ``def f(x=None): if x is None: x = []`` form, is idempotent (a None
        # default is no longer flagged), and refuses via None on any function
        # without a mutable default — so it never fabricates an opportunity. It
        # is distinct from every readability transform above (none of which
        # touches default arguments) and overlaps none of them.
        ("mutable-default", mutable_defaults.apply),
        # 2-arg signature → adapt to the uniform 3-arg dry-run call.
        ("augmented-assign", lambda rel, src, _title: augmented_assign.apply(rel, src)),
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
        except OSError:
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
