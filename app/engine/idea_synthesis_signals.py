"""Grounding layer for the Idea Engine — which modules have a LANDABLE synthesis.

The Idea Engine proposes development ideas; this module answers the honest
question behind each synthesis idea: *for THIS module, would ``apex develop``
actually land a change?* It must never over-promise — an idea is only worth
surfacing when the real lander would act — so every signal here is computed by
CALLING the lander's own public predicate/transform, never by re-deriving or
approximating its logic. The signal is, by construction, EXACTLY the set the
lander would touch (or a safe subset of it): if the lander refuses (ambiguous
stub, non-boilerplate class, unprovable return), this layer refuses too.

Four signals, one per synthesis objective Apex offers:

  - :func:`fillable_stub_modules` — implement-stub. Calls
    :func:`app.execution.stub_synthesis.module_has_fillable_stub`, the lander's
    OWN cheap in-process oracle (no pytest). It already self-excludes ambiguous
    stubs, test/fixture files and unreadable modules, so a module qualifies here
    precisely when the implement-stub apply path could land a body.
  - :func:`dataclassifiable_modules` — boilerplate-``__init__`` → ``@dataclass``.
    Calls :func:`app.execution.dataclass_rewrite.rewrite_dataclasses` on the
    module source and keeps it only when the rewrite returns a CHANGED source
    (the exact gate the lander uses to decide it has work to do).
  - :func:`inferable_return_modules` — provable return-type hints. Calls
    :func:`app.execution.semantic.transforms.type_annotations.infer_annotations`
    (the pure-source inference the ``infer-type-hints`` objective composes via
    ``plan_type_annotations``) and keeps a module only when it returns a CHANGED
    source — i.e. at least one function currently lacks a return annotation AND
    that return type is provable from the AST (the lander annotates no
    parameters, so a changed source always carries >=1 added ``-> T``).
  - :func:`cover_gaps_modules` — cover-gaps. Calls
    :func:`app.execution.cover_gaps.plan_cover_gaps` (the lander itself) and keeps
    a module only when the plan has a non-empty ``new_contents`` — i.e. the lander
    would actually write a brand-new characterization test for it. That is the
    lander's OWN gate (an existing ``tests/test_<stem>.py``, a fixture/dunder
    subject, or a module nothing can be honestly characterized in all yield an
    empty no-op plan), so the signal equals exactly the modules ``apex develop``'s
    cover-gaps objective would touch — never an over-promise.
  - :func:`wire_export_packages` — wire-exports. Calls
    :func:`app.execution.objectives.wire_exports.plan_wire_exports` (the lander
    itself) on a candidate package ``__init__.py`` and keeps it only when the plan
    has a non-empty ``new_contents`` — i.e. the lander would actually rewrite that
    ``__init__.py`` with a re-export surface + ``__all__``. That gate composes the
    lander's IMPORT ORACLE (the candidate is subprocess-imported and every export
    must resolve), so a refused test/fixture or namespace package, an already-fully
    -wired package, or a candidate that fails the oracle all yield an empty no-op
    plan and do not qualify — exactly the packages ``apex develop``'s wire-exports
    objective would touch, never an over-promise.
  - :func:`generate_usage_doc_packages` — generate-usage-doc. Calls
    :func:`app.execution.objectives.generate_usage_doc.plan_generate_usage_doc`
    (the lander itself) on a candidate package ``__init__.py`` and keeps it only
    when the plan has a non-empty ``new_contents`` — i.e. the lander would actually
    write/refresh that package's sibling ``USAGE.md`` from its PUBLIC API. That gate
    composes the lander's DOCTEST ORACLE (every ``>>>`` example is executed against
    the imported package before it may stand) and the renderer's code-block parse
    check, so a package with no public API, a refused test/fixture package, an
    already-current ``USAGE.md`` (byte-identical idempotent no-op), or a doc whose
    examples fail the oracle all yield an empty no-op plan and do not qualify —
    exactly the packages ``apex develop``'s generate-usage-doc objective would
    touch, never an over-promise.
  - :func:`tdd_implementable_symbols` — tdd-implement. The one PER-SYMBOL signal:
    a symbol target is ``"<module_rel>:<name>"`` (the same shape the objective's
    ``moves`` emits). It runs the lander's OWN detector
    :func:`app.execution.objectives.tdd_implement.detect_missing_symbols` once (the
    project suite is harvested for deterministically-attributable missing-function
    failures), then keeps a symbol only when
    :func:`app.execution.objectives.tdd_implement.plan_tdd_implement` produces a
    non-empty ``new_contents`` for it — the lander's OWN gate (``plan_tdd_implement``
    synthesises a body that flips the RED test green, landing nothing when no fixed
    template fits). This is exactly the objective's own ``_missing`` spine, so the
    signal equals the set of symbols ``apex develop``'s tdd-implement objective would
    land a function for — a fully-tested symbol, an assertion-failure (not a missing
    symbol), or a symbol whose contract no template satisfies all yield no plan and
    do not qualify, never an over-promise. Only symbols whose module is in the
    candidate ``modules`` set are considered, so the signal stays tied to the plan's
    own candidates.
  - :func:`strengthenable_modules` — strengthen-tests. Calls
    :func:`app.execution.strengthen_tests.plan_strengthen_tests` (the lander
    itself) and keeps a module only when the plan has a non-empty ``new_contents``
    — i.e. the lander would actually write/extend its ``tests/test_<stem>.py`` with
    a mutant-killing assertion. That gate composes the lander's MUTATION ENGINE +
    DOUBLE-GATE oracle (a survivor must exist and an assertion that passes on the
    real code AND fails against that survivor must be synthesizable), so a module
    whose tests already kill every mutant (saturated), one whose survivors can't be
    killed with an honest literal oracle, a packaging ``__init__``/``__main__``, an
    unsound (red) baseline, or a test/fixture target all yield an empty no-op plan
    and do not qualify — exactly the modules ``apex develop``'s strengthen-tests
    objective would touch, never an over-promise.
  - :func:`modernizable_modules` — modernize. The one OBJECTIVE-COMPILER-driven
    signal: ``modernize`` is not a single ``plan_*`` lander but a campaign of the
    objective compiler's behaviour-preserving idiom transforms (``== None`` →
    ``is None``, dead ``f`` prefixes, empty-constructor → collection literal).
    :func:`modernize_plan` DELEGATES to those exact transforms
    (``objective_compiler._tidy_transforms``) — chaining each over the module's own
    source — and a module is kept only when the resulting plan has a non-empty
    ``new_contents`` (the same "would this change anything?" gate the objective's
    ``_modernize_candidates`` uses). So an already-modern module (every idiom
    already in its tidy form), an unreadable file, or a syntax error all yield an
    empty no-op plan and do not qualify — exactly the modules ``apex develop``'s
    modernize objective would touch, never an over-promise.
  - :func:`dedup_total_return_modules` — dedup-total-return. The first of two
    CROSS-MODULE signals (a duplicate spans several modules, so the unit is a
    duplicate BLOCK, not a lone module). It DELEGATES wholesale to the objective's
    OWN gate :func:`app.execution.objectives.dedup_total_return._actionable_blocks`
    (which pairs the exact-duplicate detector with the real
    :func:`app.execution.dedup_total_return.plan_dedup_total_return` and keeps only
    blocks whose plan produces a non-empty ``new_contents``), then keeps a module
    precisely when it PARTICIPATES in one of those actionable blocks. So a project
    with no provably-safe always-returning duplicate, or a module that touches no
    actionable block, yields nothing — exactly the modules ``apex develop``'s
    dedup-total-return objective would rewrite, never an over-promise.
  - :func:`dedup_parameterizable_modules` — dedup-parameterized. The second
    CROSS-MODULE signal. It DELEGATES wholesale to the objective's OWN gate
    :func:`app.execution.objectives.dedup_parameterized._actionable_groups` (which
    pairs the near-duplicate detector with the real
    :func:`app.execution.near_dup_extract.plan_near_dup_extract` and keeps only
    groups whose plan produces a non-empty ``new_contents``), then keeps a module
    precisely when it PARTICIPATES in one of those actionable near-duplicate groups.
    So a project with no parameterizable near-duplicate, or a module that touches no
    actionable group, yields nothing — exactly the modules ``apex develop``'s
    dedup-parameterized objective would rewrite, never an over-promise.
  - :func:`dedup_parameterized_total_return_modules` — dedup-parameterized-
    total-return, the near-dup family's SECOND control-flow rung (the same
    CROSS-MODULE shape as its sibling above, for the ALWAYS-RETURNING
    complement). It DELEGATES wholesale to the objective's OWN gate
    :func:`app.execution.objectives.dedup_parameterized_total_return
    ._actionable_groups` (which pairs the SAME near-duplicate detector with the
    real :func:`app.execution.near_dup_total_return.plan_near_dup_total_return`
    and keeps only a total-return group whose plan produces a non-empty
    ``new_contents``), then keeps a module precisely when it PARTICIPATES in one
    of those actionable groups. So a project with no parameterizable
    always-returning near-duplicate, or a module that touches no actionable
    group, yields nothing — exactly the modules ``apex develop``'s
    dedup-parameterized-total-return objective would rewrite, never an
    over-promise.
  - :func:`dedup_parameterized_guarded_return_modules` — dedup-parameterized-
    guarded-return, the near-dup family's THIRD control-flow rung (the same
    CROSS-MODULE shape as its two siblings above, for the GUARD-RETURN
    complement: a guard ``return`` on some path AND a live fall-through). It
    DELEGATES wholesale to the objective's OWN gate
    :func:`app.execution.objectives.dedup_parameterized_guarded_return
    ._actionable_groups` (which pairs the SAME near-duplicate detector with the
    real :func:`app.execution.near_dup_guarded_return
    .plan_near_dup_guarded_return` and keeps only a guard-return group whose
    plan produces a non-empty ``new_contents``), then keeps a module precisely
    when it PARTICIPATES in one of those actionable groups. So a project with
    no parameterizable guard-return near-duplicate, or a module that touches no
    actionable group, yields nothing — exactly the modules ``apex develop``'s
    dedup-parameterized-guarded-return objective would rewrite, never an
    over-promise.

Pure: no writes, no pytest, no network. Deterministic: every result is sorted.
Defensive: a missing / unreadable / syntactically-broken module, or a
test/fixture file, simply does not qualify — it never raises. The rel-paths in
``modules`` are kept verbatim (as given) in the output.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from app.execution.cover_gaps import plan_cover_gaps
from app.execution.dataclass_rewrite import rewrite_dataclasses
from app.execution.objectives.generate_usage_doc import plan_generate_usage_doc
from app.execution.objectives.tdd_implement import (
    detect_missing_symbols,
    plan_tdd_implement,
)
from app.execution.objectives.wire_exports import plan_wire_exports
from app.execution.semantic.transforms.type_annotations import infer_annotations
from app.execution.strengthen_tests import plan_strengthen_tests
from app.execution.stub_synthesis import module_has_fillable_stub

__all__ = [
    "fillable_stub_modules",
    "dataclassifiable_modules",
    "inferable_return_modules",
    "cover_gaps_modules",
    "wire_export_packages",
    "generate_usage_doc_packages",
    "tdd_implementable_symbols",
    "strengthenable_modules",
    "modernizable_modules",
    "dedup_total_return_modules",
    "dedup_guarded_return_modules",
    "dedup_parameterizable_modules",
    "dedup_parameterized_total_return_modules",
    "dedup_parameterized_guarded_return_modules",
]


def _qualifying(
    root: str | Path,
    modules: Iterable[str],
    predicate: Callable[[Path, str], bool],
    limit: int | None,
) -> list[str]:
    """The subset of ``modules`` for which ``predicate(root_path, rel)`` holds, in
    deterministic sorted order and capped to ``limit`` when given.

    The shared spine of all three signals: it owns the determinism (sort), the
    de-duplication (a rel-path repeated in the input appears once), the ``limit``
    cap and the never-raise guarantee. ``predicate`` decides membership by
    CALLING the real lander; any exception it leaks is swallowed so an unreadable
    or broken module simply does not qualify rather than crashing the engine."""
    root_path = Path(root)
    kept: set[str] = set()
    for rel in modules:
        if rel in kept:
            continue
        try:
            if predicate(root_path, rel):
                kept.add(rel)
        except Exception:
            continue  # unreadable / broken module → simply does not qualify
    ordered = sorted(kept)
    return ordered if limit is None else ordered[:limit]


def fillable_stub_modules(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The modules with a LANDABLE implement-stub opportunity, sorted, capped.

    Grounded on the lander's OWN cheap oracle
    :func:`app.execution.stub_synthesis.module_has_fillable_stub`: a module
    qualifies only when it holds a stub whose pinned tests an in-process template
    can satisfy. That oracle already excludes ambiguous stubs, test/fixture files
    and unreadable modules, so the signal equals what the implement-stub apply
    path would land — never an over-promise."""
    return _qualifying(root, modules, module_has_fillable_stub, limit)


def _is_dataclassifiable(root_path: Path, rel: str) -> bool:
    """True when :func:`rewrite_dataclasses` would CHANGE ``rel``'s source — the
    exact gate the lander uses to decide it has a boilerplate-``__init__`` class
    to convert. The source is read defensively (an ``OSError`` / unreadable file
    yields ``False``); ``rewrite_dataclasses`` itself returns ``None`` for a
    syntax error or a no-op, so neither qualifies."""
    try:
        source = (root_path / rel).read_text(encoding="utf-8")
    except OSError:
        return False
    result = rewrite_dataclasses(source)
    return result is not None and result != source


def dataclassifiable_modules(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The modules with a LANDABLE ``@dataclass`` conversion, sorted, capped.

    Grounded on :func:`app.execution.dataclass_rewrite.rewrite_dataclasses`: a
    module qualifies only when running the real rewrite returns a source that
    differs from the original (the lander's own definition of "there is a pure
    boilerplate-``__init__`` class here to convert"). A class with real
    ``__init__`` logic, an already-``@dataclass`` class, an unreadable file or a
    syntax error all yield no change, so none over-promise."""
    return _qualifying(root, modules, _is_dataclassifiable, limit)


def _has_inferable_return(root_path: Path, rel: str) -> bool:
    """True when :func:`infer_annotations` would CHANGE ``rel``'s source — i.e. at
    least one function currently lacks a return annotation AND its return type is
    provable from the AST. This MIRRORS the ``infer-type-hints`` lander EXACTLY:
    ``plan_type_annotations`` lands precisely the diff ``infer_annotations``
    produces, and that transform annotates NO parameters, so a changed source
    always carries >=1 added ``-> T`` and we never report a module the lander
    would leave untouched. The source is read defensively (unreadable → ``False``);
    ``infer_annotations`` returns ``None`` for a syntax error or a no-op."""
    try:
        source = (root_path / rel).read_text(encoding="utf-8")
    except OSError:
        return False
    result = infer_annotations(source)
    return result is not None and result != source


def inferable_return_modules(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The modules with a LANDABLE provable-return-type hint, sorted, capped.

    Grounded on :func:`app.execution.semantic.transforms.type_annotations.infer_annotations`
    — the pure, source-only inference the ``infer-type-hints`` develop objective
    composes through ``plan_type_annotations`` (which lands exactly that diff). A
    module qualifies only when the real inference returns a CHANGED source: a
    return type the lander can PROVE for a function that currently lacks one. A
    fully-annotated module, an all-unprovable module, an unreadable file or a
    syntax error all yield no change, so none over-promise.

    NOTE for the next engineer: the exact lander function mirrored here is
    ``infer_annotations(source) -> str | None`` (the cheapest sound, pure-source
    check). ``plan_type_annotations(root, module_rel)`` is the path/plan wrapper
    around it and would yield an identical decision on a readable module; the
    pure-source form is used so this layer stays a no-IO-beyond-read predicate."""
    return _qualifying(root, modules, _has_inferable_return, limit)


def _has_cover_gap(root_path: Path, rel: str) -> bool:
    """True when :func:`plan_cover_gaps` would WRITE a characterization test for
    ``rel`` — i.e. the lander's own plan has a non-empty ``new_contents``. This
    calls the REAL lander, so it is honest by construction: a fixture/dunder
    subject, a module already covered by a ``tests/test_<stem>.py``, an
    un-characterizable module, or a generated test that would not parse all yield
    an empty no-op plan (``new_contents`` is ``{}``) and do not qualify.
    ``plan_cover_gaps`` reads the source itself and never raises on a bad subject
    (it records a blocker instead), so no extra guard is needed here."""
    return bool(plan_cover_gaps(root_path, rel).new_contents)


def cover_gaps_modules(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The modules with a LANDABLE cover-gaps characterization test, sorted, capped.

    Grounded on :func:`app.execution.cover_gaps.plan_cover_gaps` — the lander
    itself: a module qualifies only when running the real plan yields a non-empty
    ``new_contents`` (the lander's own definition of "there is an untested module
    here I can write a brand-new characterization test for"). A module that
    already has a linked ``tests/test_<stem>.py``, a fixture/test/dunder subject,
    or one nothing can be honestly characterized in all produce an empty no-op
    plan, so none over-promise. This is exactly the set ``apex develop``'s
    cover-gaps objective would touch."""
    return _qualifying(root, modules, _has_cover_gap, limit)


def _has_wire_export(root_path: Path, rel: str) -> bool:
    """True when :func:`plan_wire_exports` would REWRITE the package ``__init__.py``
    at ``rel`` — i.e. the lander's own plan has a non-empty ``new_contents``. This
    calls the REAL lander, so it is honest by construction: a non-``__init__.py``
    target, a refused test/fixture or PEP 420 namespace package, an already-fully
    -wired package, or a candidate that fails the lander's IMPORT ORACLE (a name in
    the emitted ``__all__`` that does not resolve when the package is
    subprocess-imported) all yield an empty no-op plan (``new_contents`` is ``{}``)
    and do not qualify. ``plan_wire_exports`` reads the source itself and never
    raises on a bad subject (it returns an empty plan instead), so no extra guard
    is needed here — the shared ``_qualifying`` spine swallows any leak anyway."""
    return bool(plan_wire_exports(root_path, rel).new_contents)


def wire_export_packages(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The package ``__init__.py`` paths with a LANDABLE wire-exports surface,
    sorted, capped.

    Grounded on :func:`app.execution.objectives.wire_exports.plan_wire_exports` —
    the lander itself: a package's ``__init__.py`` qualifies only when running the
    real plan yields a non-empty ``new_contents`` (the lander's own definition of
    "there is an unwired public surface here I can re-export + ``__all__``"). That
    gate already composes the IMPORT ORACLE — the candidate ``__init__.py`` is
    written to a throwaway copy and imported in a clean subprocess, and every name
    in the new ``__all__`` must resolve — so an already-wired package, a refused
    test/fixture or namespace package, or a candidate that fails the oracle all
    produce an empty no-op plan and do not qualify. This is exactly the set
    ``apex develop``'s wire-exports objective would touch — never an over-promise.

    ``modules`` may freely mix non-``__init__.py`` paths in (the synthesis
    augmentation feeds it every ``.py`` target in the plan); a non-package target
    simply yields an empty plan and is dropped, so callers need not pre-filter."""
    return _qualifying(root, modules, _has_wire_export, limit)


def _has_usage_doc(root_path: Path, rel: str) -> bool:
    """True when :func:`plan_generate_usage_doc` would WRITE/REFRESH the package's
    sibling ``USAGE.md`` for the ``__init__.py`` at ``rel`` — i.e. the lander's own
    plan has a non-empty ``new_contents``. This calls the REAL lander, so it is
    honest by construction: a non-``__init__.py`` target, a refused test/fixture
    package, a package with no public API, an already-current ``USAGE.md``
    (byte-identical idempotent no-op), or a doc whose ``>>>`` examples fail the
    DOCTEST ORACLE / whose code blocks fail to parse all yield an empty no-op plan
    (``new_contents`` is ``{}``) and do not qualify. ``plan_generate_usage_doc``
    reads the source itself and returns an empty plan rather than raising on a bad
    subject, so no extra guard is needed here — the shared ``_qualifying`` spine
    swallows any leak anyway."""
    return bool(plan_generate_usage_doc(root_path, rel).new_contents)


def generate_usage_doc_packages(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The package ``__init__.py`` paths with a LANDABLE generate-usage-doc, sorted,
    capped.

    Grounded on
    :func:`app.execution.objectives.generate_usage_doc.plan_generate_usage_doc` —
    the lander itself: a package's ``__init__.py`` qualifies only when running the
    real plan yields a non-empty ``new_contents`` (the lander's own definition of
    "there is a public API here whose ``USAGE.md`` I can generate/refresh"). That
    gate already composes the DOCTEST ORACLE — every ``>>>`` example copied from a
    docstring is executed against the imported package in a clean subprocess, and an
    example that does not run green is omitted — plus the renderer's code-block parse
    check, so a package with no public API, a refused test/fixture package, an
    already-current ``USAGE.md`` (byte-identical idempotent no-op), or a doc whose
    examples fail the oracle all produce an empty no-op plan and do not qualify.
    This is exactly the set ``apex develop``'s generate-usage-doc objective would
    touch — never an over-promise.

    ``modules`` may freely mix non-``__init__.py`` paths in (the synthesis
    augmentation feeds it every ``.py`` target in the plan); a non-package target
    simply yields an empty plan and is dropped, so callers need not pre-filter."""
    return _qualifying(root, modules, _has_usage_doc, limit)


def _symbol_target(name: str, module_rel: str) -> str:
    """The ``"<module_rel>:<name>"`` target for one missing symbol — the SAME
    shape the tdd-implement objective's ``moves`` emits, so a surfaced idea's
    target round-trips back to its ``MissingSymbol`` for the delegated apply."""
    return f"{module_rel}:{name}"


def tdd_implementable_symbols(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The ``"<module_rel>:<name>"`` symbol targets with a LANDABLE tdd-implement,
    restricted to symbols whose module is in ``modules``, sorted, capped.

    Grounded on the tdd-implement objective's OWN spine: run its real detector
    :func:`detect_missing_symbols` once (the project suite is harvested for
    deterministically-attributable missing-function failures), then keep a symbol
    only when :func:`plan_tdd_implement` produces a non-empty ``new_contents`` for
    it — i.e. a fixed template makes its RED test green and the lander would land a
    real ``def`` (never a fake-green). This is exactly the objective's own
    ``_missing`` predicate, so the signal equals the symbols ``apex develop``'s
    tdd-implement objective would implement: a fully-tested symbol, an
    assertion-failure (not a missing symbol), or a symbol whose contract no template
    satisfies all yield an empty plan and do not qualify — never an over-promise.

    ``modules`` is the plan's candidate ``.py`` targets; only a detected symbol
    whose ``module_rel`` is in that set is considered, keeping the signal tied to
    the plan's own candidates. The shared :func:`_qualifying` spine owns the sort,
    de-duplication, ``limit`` cap and never-raise guarantee; the predicate
    DELEGATES the membership decision to ``plan_tdd_implement`` (no copy of its
    logic), keyed off the symbol re-derived once into ``by_target``."""
    root_path = Path(root)
    wanted = set(modules)
    try:
        detected = detect_missing_symbols(root_path)
    except Exception:
        return []  # detector failure (no suite, broken project) → nothing qualifies
    by_target = {
        _symbol_target(ms.name, ms.module_rel): ms
        for ms in detected
        if ms.module_rel in wanted
    }

    def _landable(rp: Path, target: str) -> bool:
        ms = by_target[target]
        return bool(plan_tdd_implement(rp, ms).new_contents)

    return _qualifying(root_path, by_target.keys(), _landable, limit)


def _is_strengthenable(root_path: Path, rel: str) -> bool:
    """True when :func:`plan_strengthen_tests` would WRITE/EXTEND a mutant-killing
    test for ``rel`` — i.e. the lander's own plan has a non-empty ``new_contents``.
    This calls the REAL lander, so it is honest by construction: a module whose
    tests already kill every mutant (saturated), one whose surviving mutants can't
    be killed with an honest literal oracle, a packaging ``__init__``/``__main__``,
    an unsound (red) mutation baseline, a non-``.py`` / test / fixture target, or a
    degenerate render that would not re-parse all yield an empty no-op plan
    (``new_contents`` is ``{}``) and do not qualify. ``plan_strengthen_tests`` reads
    the source itself and returns an empty plan rather than raising on a bad
    subject, so no extra guard is needed here — the shared ``_qualifying`` spine
    swallows any leak anyway."""
    return bool(plan_strengthen_tests(root_path, rel).new_contents)


def strengthenable_modules(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The modules with a LANDABLE strengthen-tests mutant-killing assertion,
    sorted, capped.

    Grounded on :func:`app.execution.strengthen_tests.plan_strengthen_tests` — the
    lander itself: a module qualifies only when running the real plan yields a
    non-empty ``new_contents`` (the lander's own definition of "there is a surviving
    mutant here whose blind spot I can close with a double-gated assertion"). That
    gate already composes the MUTATION ENGINE + DOUBLE-GATE oracle — a survivor must
    exist and an assertion that PASSES on the real code AND FAILS against that
    survivor must be synthesizable (never a fake-green) — so a module whose tests
    already kill every mutant (saturated), one whose survivors can't be killed with
    an honest literal oracle, a packaging ``__init__``/``__main__``, an unsound (red)
    baseline, or a test/fixture target all produce an empty no-op plan and do not
    qualify. This is exactly the set ``apex develop``'s strengthen-tests objective
    would touch — never an over-promise.

    Like every other per-module signal here, ``modules`` may freely mix paths the
    lander refuses (a test file, a dunder, a non-``.py`` target); each simply yields
    an empty plan and is dropped, so callers need not pre-filter."""
    return _qualifying(root, modules, _is_strengthenable, limit)


def modernize_plan(root: str | Path, rel: str):
    """The per-module ``modernize`` plan as a :class:`RenamePlan`, DELEGATING to the
    objective compiler's OWN behaviour-preserving idiom transforms.

    ``modernize`` is not a single ``plan_*`` lander; it is a campaign the objective
    compiler composes from :func:`objective_compiler._tidy_transforms` (``== None`` →
    ``is None``, dead ``f`` prefixes, empty-constructor → collection literal). This
    chains those exact transforms over ``rel``'s own source — each transform re-reads
    the accumulated text, so a module carrying several idioms is fully modernized in
    one plan — and returns a plan whose ``new_contents`` holds the combined rewrite
    ONLY when it differs from the original. A module the transforms would not change
    (already modern), an unreadable file, or a syntax error (each transform returns
    ``None``) all yield an empty no-op plan, so this is honest by construction — the
    SAME "would this change anything?" gate the objective's ``_modernize_candidates``
    uses. No transform logic is copied: the real ``apply`` functions decide the diff.

    Shared by the grounding signal (:func:`modernizable_modules`) and the bridge's
    delegated modernize lander, so the signal qualifies a module precisely when the
    lander would land a change."""
    from app.engine.objective_compiler import _tidy_transforms
    from app.execution.cross_file_rename import RenamePlan

    plan = RenamePlan(old=rel, new="modernize")
    try:
        source = (Path(root) / rel).read_text(encoding="utf-8")
    except OSError:
        return plan
    current = source
    edits = 0
    for _op, label, apply_fn in _tidy_transforms():
        try:
            res = apply_fn(rel, current, label)
        except Exception:
            res = None
        new = res.patch_requests[0].get("new_content", "") if (
            res and getattr(res, "patch_requests", None)) else ""
        if new and new != current:
            current = new
            edits += 1
    if current != source:
        plan.originals[rel] = source
        plan.new_contents[rel] = current
        plan.edits_by_file[rel] = edits
    return plan


def _is_modernizable(root_path: Path, rel: str) -> bool:
    """True when :func:`modernize_plan` would REWRITE ``rel`` — i.e. the delegated
    modernize plan has a non-empty ``new_contents``. This composes the objective
    compiler's OWN idiom transforms (see :func:`modernize_plan`), so it is honest by
    construction: an already-modern module, an unreadable file, or a syntax error all
    yield an empty no-op plan and do not qualify, never an over-promise."""
    return bool(modernize_plan(root_path, rel).new_contents)


def modernizable_modules(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The modules with a LANDABLE modernize idiom rewrite, sorted, capped.

    Grounded on :func:`modernize_plan`, which DELEGATES to the objective compiler's
    OWN behaviour-preserving tidy transforms (``objective_compiler._tidy_transforms``:
    ``== None`` → ``is None``, dead ``f`` prefixes, empty-constructor → collection
    literal): a module qualifies only when chaining the real transforms over its own
    source yields a CHANGED result (the objective's own definition of "there is a
    non-idiomatic construct here I can modernize"). An already-modern module, an
    unreadable file, or a syntax error all produce an empty no-op plan and do not
    qualify. This is exactly the set ``apex develop``'s modernize objective would
    touch — never an over-promise.

    Like every other per-module signal here, ``modules`` may freely mix paths the
    objective refuses (a non-``.py`` target, a fixture); each simply yields an empty
    plan and is dropped, so callers need not pre-filter."""
    return _qualifying(root, modules, _is_modernizable, limit)


def _modules_in_actionable_units(root: str | Path,
                                 actionable_units: Callable[[Path], list]) -> set[str]:
    """The set of module rel-paths that PARTICIPATE in one of the objective's own
    actionable units (a :class:`~app.engine.dedup.DuplicateBlock` /
    :class:`~app.engine.near_dup.NearDuplicateGroup`).

    The cross-module dedup spine: a duplicate spans several modules, so the unit is
    the BLOCK/GROUP, not a lone module. ``actionable_units(root_path)`` is the
    objective's OWN gate (it already filters to units whose real plan would land a
    change), and each unit's ``occurrences`` are ``"module:lineno"`` of every copy's
    first statement — this peels off the module half of each occurrence. Run ONCE per
    signal call (the detector is the expensive step), so the per-module predicate is a
    cheap set membership. Defensive: any leak yields the empty set rather than
    crashing the engine."""
    touched: set[str] = set()
    try:
        for unit in actionable_units(Path(root)):
            for occ in getattr(unit, "occurrences", []) or []:
                module = occ.split(":", 1)[0]
                if module:
                    touched.add(module)
    except Exception:
        return set()  # broken/unreadable project → nothing actionable
    return touched


def dedup_total_return_modules(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The modules participating in a LANDABLE dedup-total-return lift, sorted, capped.

    Grounded on the objective's OWN gate
    :func:`app.execution.objectives.dedup_total_return._actionable_blocks` — which
    pairs the exact-duplicate detector with the real
    :func:`app.execution.dedup_total_return.plan_dedup_total_return` and keeps only an
    always-returning block whose plan produces a non-empty ``new_contents``. A module
    qualifies only when it PARTICIPATES in one of those actionable blocks (its
    rel-path is the module half of a block occurrence), so a project with no
    provably-safe total-return duplicate, or a module touching no actionable block,
    does not qualify — exactly the modules ``apex develop``'s dedup-total-return
    objective would rewrite, never an over-promise.

    The expensive detector runs ONCE (membership is delegated to the objective's gate,
    never re-derived); ``modules`` may freely mix paths the objective never touches,
    each simply absent from the participating set."""
    from app.execution.objectives.dedup_total_return import _actionable_blocks

    touched = _modules_in_actionable_units(root, _actionable_blocks)
    return _qualifying(root, modules, lambda _rp, rel: rel in touched, limit)


def dedup_guarded_return_modules(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The modules participating in a LANDABLE dedup-guarded-return lift, sorted,
    capped.

    Grounded on the objective's OWN gate
    :func:`app.execution.objectives.dedup_guarded_return._actionable_blocks` —
    which pairs the exact-duplicate detector with the real
    :func:`app.execution.dedup_guarded_return.plan_dedup_guarded_return` (sentinel
    projection) and keeps only a guard-return-with-fall-through block whose plan
    produces a non-empty ``new_contents``. A module qualifies only when it
    PARTICIPATES in one of those actionable blocks (its rel-path is the module
    half of a block occurrence), so a project with no provably-safe guarded-return
    duplicate, or a module touching no actionable block, does not qualify —
    exactly the modules ``apex develop``'s dedup-guarded-return objective would
    rewrite, never an over-promise.

    The expensive detector runs ONCE (membership is delegated to the objective's
    gate, never re-derived); ``modules`` may freely mix paths the objective never
    touches, each simply absent from the participating set."""
    from app.execution.objectives.dedup_guarded_return import _actionable_blocks

    touched = _modules_in_actionable_units(root, _actionable_blocks)
    return _qualifying(root, modules, lambda _rp, rel: rel in touched, limit)


def dedup_parameterizable_modules(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The modules participating in a LANDABLE dedup-parameterized lift, sorted, capped.

    Grounded on the objective's OWN gate
    :func:`app.execution.objectives.dedup_parameterized._actionable_groups` — which
    pairs the near-duplicate detector with the real
    :func:`app.execution.near_dup_extract.plan_near_dup_extract` and keeps only a
    constant-only, signature-clean group whose plan produces a non-empty
    ``new_contents``. A module qualifies only when it PARTICIPATES in one of those
    actionable near-duplicate groups (its rel-path is the module half of a group
    occurrence), so a project with no parameterizable near-duplicate, or a module
    touching no actionable group, does not qualify — exactly the modules ``apex
    develop``'s dedup-parameterized objective would rewrite, never an over-promise.

    The expensive (memoized) detector runs ONCE (membership is delegated to the
    objective's gate, never re-derived); ``modules`` may freely mix paths the
    objective never touches, each simply absent from the participating set."""
    from app.execution.objectives.dedup_parameterized import _actionable_groups

    touched = _modules_in_actionable_units(root, _actionable_groups)
    return _qualifying(root, modules, lambda _rp, rel: rel in touched, limit)


def dedup_parameterized_total_return_modules(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The modules participating in a LANDABLE dedup-parameterized-total-return
    lift, sorted, capped.

    Grounded on the objective's OWN gate
    :func:`app.execution.objectives.dedup_parameterized_total_return
    ._actionable_groups` — which pairs the SAME (memoized) near-duplicate
    detector with the real :func:`app.execution.near_dup_total_return
    .plan_near_dup_total_return` and keeps only an ALWAYS-RETURNING,
    Constant-only, signature-clean group whose plan produces a non-empty
    ``new_contents``. A module qualifies only when it PARTICIPATES in one of
    those actionable groups (its rel-path is the module half of a group
    occurrence), so a project with no parameterizable always-returning
    near-duplicate, or a module touching no actionable group, does not qualify
    — exactly the modules ``apex develop``'s dedup-parameterized-total-return
    objective would rewrite, never an over-promise.

    The expensive (memoized) detector runs ONCE (membership is delegated to the
    objective's gate, never re-derived); ``modules`` may freely mix paths the
    objective never touches, each simply absent from the participating set."""
    from app.execution.objectives.dedup_parameterized_total_return import (
        _actionable_groups,
    )

    touched = _modules_in_actionable_units(root, _actionable_groups)
    return _qualifying(root, modules, lambda _rp, rel: rel in touched, limit)


def dedup_parameterized_guarded_return_modules(
    root: str | Path, modules: Iterable[str], limit: int | None = None
) -> list[str]:
    """The modules participating in a LANDABLE dedup-parameterized-guarded-
    return lift, sorted, capped.

    Grounded on the objective's OWN gate
    :func:`app.execution.objectives.dedup_parameterized_guarded_return
    ._actionable_groups` — which pairs the SAME (memoized) near-duplicate
    detector with the real :func:`app.execution.near_dup_guarded_return
    .plan_near_dup_guarded_return` and keeps only a GUARD-RETURN (a guard
    ``return`` on some path AND a live fall-through), Constant-only,
    signature-clean group whose plan produces a non-empty ``new_contents``. A
    module qualifies only when it PARTICIPATES in one of those actionable
    groups (its rel-path is the module half of a group occurrence), so a
    project with no parameterizable guard-return near-duplicate, or a module
    touching no actionable group, does not qualify — exactly the modules
    ``apex develop``'s dedup-parameterized-guarded-return objective would
    rewrite, never an over-promise.

    The expensive (memoized) detector runs ONCE (membership is delegated to the
    objective's gate, never re-derived); ``modules`` may freely mix paths the
    objective never touches, each simply absent from the participating set."""
    from app.execution.objectives.dedup_parameterized_guarded_return import (
        _actionable_groups,
    )

    touched = _modules_in_actionable_units(root, _actionable_groups)
    return _qualifying(root, modules, lambda _rp, rel: rel in touched, limit)
