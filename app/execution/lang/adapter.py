"""The ``LanguageAdapter`` seam — the ONE structural interface that names the
per-language realisation of Apex's four develop verbs.

Apex's apply/verify SPINE is already language-agnostic: ``apply_rename``
(:mod:`app.execution.cross_file_rename`) just writes a :class:`RenamePlan`'s
``new_contents`` bytes, runs the project's OWN suite, and rolls back
byte-for-byte on regression; the ``RenamePlan``/``Move`` currency carries no
language field; and the test COMMAND (pytest vs ``npm test``) already lives in
the runner. The ONLY place a language is hard-coded is the per-language
realisation of FOUR verbs — **enumerate own sources, parse, locate the target,
produce edited TEXT** — plus the cheap post-edit well-formedness proof. This
module names that as a :class:`typing.Protocol` so a language is a STRUCTURAL
plug-in (no inheritance, no import cycle), exactly the discipline
``ObjectiveSpec``/``RenamePlan`` already follow.

The four methods are each a PURE function of source bytes (deterministic,
zero-token, offline):

* ``owns(rel)`` — the FILE GATE: is ``rel`` a non-test SOURCE this language may
  write? (Generalises ``js_tdd_implement.is_js_source`` and the Python
  ``.py``-plus-fixture filter.)
* ``parse(source)`` — a :class:`ParseTree` wrapper, or ``None`` when the source
  does not parse (the caller then REFUSES — Apex never guesses).
* ``locate(tree, source, query)`` — the :class:`Target` (a byte ``span``) the
  ``query`` names, or ``None`` when it is absent/ambiguous (refuse).
* ``apply(source, target, edit)`` — the edited source as a pure byte-span
  splice, or ``None`` when the recorded span is stale (refuse rather than
  corrupt the file).
* ``reparses(new_source)`` — the post-edit well-formedness proof a planner uses
  to refuse a malformed splice WITHOUT a test run (the cheap pre-gate).

VERIFY is deliberately NOT an adapter method: it is already language-agnostic
(write text -> run the project's suite -> roll back), so the seam only exposes
``reparses`` as the static proof. The frozen dataclasses below carry the
common denominator — a ``span: (start, end)`` byte range, which JS already has
as ``JsStub.body_start``/``body_end`` and Python can derive from ``ast``
offsets — so ``apply`` is a pure byte splice for EVERY language.

This module imports nothing from ``objective_compiler``/``cross_file_rename``
(not even under ``TYPE_CHECKING``): a ``Move`` is left unannotated and the span
is a plain tuple, so the seam stays cycle-free, the same decoupling
``develop_registry`` documents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "Span",
    "ParseTree",
    "TargetQuery",
    "Target",
    "Edit",
    "LanguageAdapter",
]

# A byte range ``(start, end)`` into a source string — the common denominator
# every language's ``locate`` returns and every ``apply`` splices. A plain tuple
# (not a class) keeps the seam dependency-free and trivially comparable.
Span = tuple[int, int]


@dataclass(frozen=True)
class ParseTree:
    """A parsed source, wrapped so the Protocol has a single opaque tree type
    across languages. ``tree`` is the language's native parse result (a Python
    ``ast.Module``, or any token the JS driver hands back); the seam never
    inspects it — only the owning adapter does. ``None`` is never wrapped: a
    failed parse is the bare ``None`` :meth:`LanguageAdapter.parse` returns."""

    tree: Any


@dataclass(frozen=True)
class TargetQuery:
    """What to locate in a parsed source — a symbol ``name`` (the function whose
    body to fill), the most common query. Extra hints ride in ``extra`` so a new
    capability can ask for more without changing the Protocol signature."""

    name: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Target:
    """A located edit site: the byte ``span`` to splice plus the symbol ``name``
    it belongs to. The span is the body-block range (``span[0]`` = the ``{`` /
    first body byte, ``span[1]`` = just past the ``}`` / last body byte) so
    :meth:`LanguageAdapter.apply` is a precise splice, not an unparse."""

    name: str
    span: Span


@dataclass(frozen=True)
class Edit:
    """The replacement text for a :class:`Target`'s span — the synthesised body
    the language's ``apply`` splices in. ``body`` is the raw inner text; the
    adapter wraps it in the language's block syntax (JS: ``{ <body> }``)."""

    body: str


@runtime_checkable
class LanguageAdapter(Protocol):
    """The structural contract a language plugs into. Implementers are plain
    objects (no base class); ``isinstance(obj, LanguageAdapter)`` works because
    the Protocol is ``runtime_checkable``, which the registry uses to validate a
    registration. Every method is a pure, deterministic function of bytes."""

    name: str

    def owns(self, rel: str) -> bool:
        """True when ``rel`` is a non-test SOURCE file this language may write."""
        ...

    def parse(self, source: str) -> ParseTree | None:
        """The parsed ``source``, or ``None`` when it does not parse (refuse)."""
        ...

    def locate(self, tree: ParseTree, source: str,
               query: TargetQuery) -> Target | None:
        """The :class:`Target` ``query`` names, or ``None`` if absent/ambiguous."""
        ...

    def apply(self, source: str, target: Target, edit: Edit) -> str | None:
        """``source`` with ``target``'s span replaced by ``edit``, or ``None``
        when the span is stale (refuse rather than corrupt the file)."""
        ...

    def reparses(self, new_source: str) -> bool:
        """True when ``new_source`` is well-formed — the cheap post-edit proof a
        planner uses to refuse a malformed splice without a test run."""
        ...
