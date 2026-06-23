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
from app.execution.semantic.transforms.type_annotations import infer_annotations
from app.execution.stub_synthesis import module_has_fillable_stub

__all__ = [
    "fillable_stub_modules",
    "dataclassifiable_modules",
    "inferable_return_modules",
    "cover_gaps_modules",
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
