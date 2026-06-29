"""Promote a class's SELF-FREE methods to ``@staticmethod`` — a behaviour-
preserving DECOUPLING step, not a decomposition.

A method that never touches ``self`` is not really an instance method: it is a
plain function that happens to live in the class body. Marking it
``@staticmethod`` and dropping the now-unused ``self`` parameter makes that
COUPLING surface honest — the reader sees at a glance that the method does not
read or mutate instance state — WITHOUT changing a single call site:

    class C:                         class C:
        def helper(self, x):    ->       @staticmethod
            return x + 1                  def helper(x):
                                              return x + 1

This is the SAFE structural move available on a METHOD-BAG god-class (many
methods, ~no shared instance fields): it reduces coupling but does NOT reduce
the method count or split responsibilities — that full decomposition stays a
DESIGN task. Honest by construction.

WHY NO CALL SITE CHANGES (the whole safety point). A ``@staticmethod`` is still a
class attribute, so every existing call keeps resolving and keeps its arguments:

  - ``self.helper(x)`` — ``self.helper`` looks the attribute up on the class via
    the instance; the staticmethod descriptor returns the plain function, so the
    call passes ``x`` and ``self`` is no longer threaded in. Identical result.
  - ``C.helper(x)`` / ``inst.helper(x)`` — same lookup, same args.
  - a SUBCLASS calling ``self.helper(x)`` / ``super().helper(x)`` — still resolves
    via the MRO to the (now static) attribute; ``super`` participation is REFUSED
    anyway (rule 6), as is any name an override could shadow (rule 7).

The ONLY two edits per promoted method are ``+    @staticmethod`` above the
``def`` and dropping the leading ``self`` / ``self, `` from the header — located
by the AST, applied bottom-up so earlier line numbers stay valid, and the whole
module is re-``ast.parse``d so a malformed splice is NEVER landed.

THE REFUSAL SET (the safety oracle — refuse ⇒ the method is skipped, never a
guess). A method is promoted ONLY when NONE of these hold:

  1. it references ``self`` anywhere in its body (any ``Name`` whose ``id`` is the
     first-param name) — the core eligibility gate;
  2. it is already ``@staticmethod`` or ``@classmethod``;
  3. it carries ANY decorator (``@property`` / ``@cached_property`` /
     ``@lru_cache`` / ``@abstractmethod`` / ``@override`` / a custom registrar) —
     a decorator can bind, register, or wrap, so the static rewrite is unsafe;
  4. it is a dunder (``__init__`` / ``__eq__`` / ``__enter__`` / …) — the data
     model calls these bound, by protocol;
  5. its first parameter is not the conventional ``self`` (``cls`` /
     positional-only / zero params) — not a plain instance method to begin with;
  6. it uses ``super`` (the bare name appears anywhere) — bound-method machinery;
  7. its NAME is defined by MORE THAN ONE class in the project — a conservative
     within-repo approximation of "is this polymorphic / an override / part of an
     MRO": promoting one branch of an override set would desynchronise the
     signatures, so refuse the whole name;
  8. its class is NOT top-level — a nested / method-local class is out of scope;
  9. its NAME appears as a bare STRING LITERAL anywhere in the repo
     (``getattr`` / ``setattr`` / ``hasattr`` / ``__all__`` /
     ``monkeypatch.setattr`` targets) — a dynamic reference static analysis can't
     follow, so the signature change might break a by-name call;
 10. its module is a test / fixture / example file or a non-library script
     (packaging / config / task / generated) — Apex never edits the suite it is
     gated by, nor a file nobody imports as an API.

Rules 1–6 and 8 are LOCAL AST facts; rules 7 and 9 need a ONE-PASS project-wide
index (method-name → count of distinct defining classes, and the set of every
string-literal value), built once per plan. The plan runs over the whole MODULE,
so it may promote SEVERAL eligible methods at once — broader but SAFE, exactly as
extract-guard-clause / seal-hashable-eq are: the plan lands through
``apply_rename(impact_scope=True)`` whose impacted-test gate auto-rolls-back on
ANY regression.

Deterministic (pure AST walk + line splice over the source bytes, candidates in
source order, no clock / random / network / LLM), stdlib-only, zero-token,
idempotent (a second run sees the ``@staticmethod`` it landed and refuses via
rule 2 — a byte-identical no-op).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import apply_line_rewrites, plan_single_module_rewrite
from app.execution.cross_file_rename import (
    RenamePlan,
    _is_non_library_file,
    _py_files,
)

__all__ = [
    "plan_promote_staticmethods",
    "promotable_methods",
]

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


class _ProjectIndex:
    """The one-pass project-wide facts rules 7 and 9 need, built once per plan.

    ``method_class_count`` maps a method NAME to the number of DISTINCT classes
    in the project that define a method of that name (a within-repo
    approximation of "is this polymorphic" — > 1 ⇒ a possible override / MRO
    participant, refuse). ``string_literals`` is the set of every bare
    ``str``-constant VALUE anywhere in the project (a name appearing here is a
    possible ``getattr`` / ``__all__`` / monkeypatch-by-name target — a dynamic
    reference, refuse)."""

    __slots__ = ("method_class_count", "string_literals")

    def __init__(self, method_class_count: dict[str, int],
                 string_literals: frozenset[str]) -> None:
        self.method_class_count = method_class_count
        self.string_literals = string_literals


def _methods_of_class(cls: ast.ClassDef) -> set[str]:
    """The set of method NAMES defined directly in ``cls``'s body (``def`` /
    ``async def``). A set, so one class declaring ``foo`` twice still counts as a
    single defining class for that name."""
    return {
        stmt.name for stmt in cls.body
        if isinstance(stmt, _FUNCTIONS)
    }


def _build_index(project_root: str | Path) -> _ProjectIndex:
    """Scan every project ``.py`` file ONCE and build the cross-file index.

    For each parseable module: every class (at ANY depth — an override can hide
    in a nested class too, so the polymorphism count is conservative) contributes
    its method names to ``method_class_count`` (one increment per DISTINCT
    defining class), and every ``str`` constant contributes its value to
    ``string_literals``. Unparseable files are skipped (invisible to static
    reasoning). Deterministic — a pure function of the tree's bytes."""
    counts: dict[str, int] = {}
    literals: set[str] = set()
    for _rel, text in _py_files(Path(project_root)):
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for name in _methods_of_class(node):
                    counts[name] = counts.get(name, 0) + 1
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
    return _ProjectIndex(counts, frozenset(literals))


def _is_dunder(name: str) -> bool:
    """True for a dunder method name (``__x__``) — called bound by the data model
    / protocol machinery, so never promoted (rule 4)."""
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _is_static_or_classmethod(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when ``method`` already carries a bare ``@staticmethod`` / ``@classmethod``
    decorator (rule 2). A plain ``Name`` decorator by id — the canonical spelling;
    a ``staticmethod(...)``-style call is still ANY decorator and is caught by
    rule 3."""
    for dec in method.decorator_list:
        if isinstance(dec, ast.Name) and dec.id in ("staticmethod", "classmethod"):
            return True
    return False


def _references_self(method: ast.FunctionDef | ast.AsyncFunctionDef,
                     self_name: str) -> bool:
    """True when any ``Name`` load/store of ``self_name`` appears anywhere in
    ``method`` (its body OR its own signature defaults/annotations) — the core
    eligibility gate (rule 1). Catches ``self.x`` reads/writes, ``self.m()``
    calls, and passing ``self`` along as an argument."""
    for node in ast.walk(method):
        if isinstance(node, ast.Name) and node.id == self_name:
            return True
    return False


def _uses_super(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when the bare name ``super`` appears anywhere in ``method`` (rule 6) —
    ``super()`` / ``super(C, self)`` bound-method machinery is out of scope."""
    for node in ast.walk(method):
        if isinstance(node, ast.Name) and node.id == "super":
            return True
    return False


def _first_param_is_self(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when ``method``'s FIRST positional parameter is exactly ``self`` and
    there is no positional-only parameter before it (rule 5). A ``cls`` first
    param, a zero-parameter method, or a positional-only leading parameter all
    fail — it is not a plain instance method whose ``self`` we can drop."""
    args = method.args
    if args.posonlyargs:
        return False  # a positional-only leading param — not a droppable self
    if not args.args:
        return False  # zero positional params — nothing to drop
    return args.args[0].arg == "self"


def _eligible(method: ast.FunctionDef | ast.AsyncFunctionDef,
              index: _ProjectIndex) -> bool:
    """True when ``method`` passes EVERY refusal rule (1–7, 9) that applies at the
    method level — so it is safe to promote to ``@staticmethod``.

    Rules 8 (top-level class) and 10 (file kind) are enforced by the caller
    BEFORE a method reaches here (the class walk only visits top-level classes;
    the file gate refuses the whole module up front)."""
    if _is_static_or_classmethod(method):
        return False  # rule 2: already static / classmethod
    if method.decorator_list:
        return False  # rule 3: any (other) decorator — bind / register / wrap risk
    if _is_dunder(method.name):
        return False  # rule 4: a dunder — called bound by protocol
    if not _first_param_is_self(method):
        return False  # rule 5: first param is not a droppable ``self``
    if _references_self(method, "self"):
        return False  # rule 1: uses instance state
    if _uses_super(method):
        return False  # rule 6: bound-method super machinery
    if index.method_class_count.get(method.name, 0) > 1:
        return False  # rule 7: name defined by >1 class — possible override / MRO
    if method.name in index.string_literals:
        return False  # rule 9: name referenced dynamically as a string anywhere
    return True


def _eligible_methods(cls: ast.ClassDef,
                      index: _ProjectIndex) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """The directly-defined methods of ``cls`` that pass the refusal set, in
    source order (a DIRECT body scan, never ``ast.walk`` — a method-local
    function or a nested class's method is NOT a method of ``cls``)."""
    return [
        stmt for stmt in cls.body
        if isinstance(stmt, _FUNCTIONS) and _eligible(stmt, index)
    ]


def _drop_self_from_header(line: str) -> str | None:
    """Drop the leading ``self`` / ``self, `` from a ``def`` header LINE, or
    ``None`` if the expected ``(self`` shape is not found verbatim.

    Located after the first ``(`` of the header: ``(self, x)`` -> ``(x)`` and
    ``(self)`` -> ``()``. The whitespace right after ``(`` is preserved; ``self``
    and a following ``,`` plus its trailing whitespace are removed, matching the
    conventional ``def f(self, x)`` -> ``def f(x)`` spelling; a sole ``self``
    leaves ``()``. Returns ``None`` (the caller skips the occurrence) on anything
    it does not recognise, so the edit is never a guess."""
    open_idx = line.find("(")
    if open_idx == -1:
        return None
    head, rest = line[: open_idx + 1], line[open_idx + 1:]
    stripped = rest.lstrip()
    lead = rest[: len(rest) - len(stripped)]  # whitespace right after "("
    if not stripped.startswith("self"):
        return None
    after = stripped[len("self"):]
    if after[:1] in (")", ":"):
        # sole ``self`` — drop it (and any leading space we consumed), so the
        # parameter list closes cleanly as ``()``.
        return head + after
    if after.startswith(","):
        # ``self, <more>`` — drop ``self`` and the comma + its trailing space,
        # keeping any whitespace that sat right after ``(``.
        tail = after[1:].lstrip()
        return head + lead + tail
    return None  # an unrecognised shape (e.g. ``self=...`` default) — skip


def _collect_rewrites(tree: ast.Module, source: str, lines: list[str],
                      index: _ProjectIndex) -> list[tuple[int, int, list[str]]]:
    """Every ``(lo, hi, new_lines)`` line-span rewrite for ``tree``: for each
    eligible method of each TOP-LEVEL class (rule 8), replace the ``def`` header
    line with two lines — ``    @staticmethod`` at the method's own indent, then
    the header with its leading ``self`` dropped.

    Located by the AST (the header is the line at ``method.lineno``); applied
    bottom-up by :func:`apply_line_rewrites` so earlier line numbers stay valid.
    A method whose header line does not match the expected ``(self`` shape is
    silently skipped (its rewrite is never emitted), so the splice is never a
    guess."""
    rewrites: list[tuple[int, int, list[str]]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for method in _eligible_methods(node, index):
            header_no = method.lineno
            header_line = lines[header_no - 1]
            new_header = _drop_self_from_header(header_line)
            if new_header is None:
                continue
            indent = " " * method.col_offset
            newline = "\n" if header_line.endswith("\n") else ""
            decorator = f"{indent}@staticmethod" + (newline or "\n")
            rewrites.append((header_no, header_no, [decorator, new_header]))
    return rewrites


def _apply(source: str, rewrites: list[tuple[int, int, list[str]]]) -> str:
    """Splice all ``(lo, hi, new_lines)`` rewrites into ``source`` bottom-up so
    earlier line numbers stay valid (delegates to the shared line-span helper)."""
    return apply_line_rewrites(source, rewrites)


def plan_promote_staticmethods(project_root: str | Path,
                               module_rel: str) -> RenamePlan:
    """Build the single-module promote-staticmethod plan, or its blockers.

    ``module_rel`` is a project-relative path. The plan promotes EVERY eligible
    self-free method (per the refusal set) of every top-level class in that module
    to ``@staticmethod`` — two AST-located line edits each (``+@staticmethod`` and
    a dropped leading ``self``). An empty plan means nothing was eligible — a
    no-op, not a failure (a class with no self-free method, an all-decorated /
    dunder / overridden / dynamically-referenced set, a test/fixture or
    non-library file).

    Rules 7 and 9 need a project-wide index, so it is built ONCE here and passed
    into the collector via the ``collect`` closure. A non-``.py`` / unreadable /
    unparseable target, or a result that won't re-parse, records a blocker through
    the shared scaffold (so the disclosed reason rides downstream)."""
    if _is_non_library_file(module_rel):
        # Packaging / config / task / generated script — nobody imports it as an
        # API (rule 10's non-library half; the fixture half is handled by the
        # shared scaffold's ``is_fixture_path`` gate). Return the same blocker-free
        # empty plan the shared scaffold would, without scanning the project.
        return RenamePlan(old=module_rel, new="promote-staticmethod")

    index = _build_index(project_root)
    return plan_single_module_rewrite(
        project_root, module_rel,
        plan_label="promote-staticmethod",
        collect=lambda tree, source: _collect_rewrites(
            tree, source, source.splitlines(keepends=True), index),
        apply=_apply,
        reparse_phrase="staticmethod promotion")


def promotable_methods(project_root: str | Path, module_rel: str) -> list[str]:
    """The names of methods in ``module_rel`` that would be promoted to
    ``@staticmethod``, in source order.

    Convenience for tests / single-file reasoning. Returns ``[]`` when nothing is
    eligible (or the module is a fixture / non-library / unreadable / unparseable
    file). A pure function of the project bytes — deterministic."""
    plan = plan_promote_staticmethods(project_root, module_rel)
    if not plan.new_contents:
        return []
    # Recover the promoted names by re-running the eligible gate against the index
    # (the same gate the plan used), so the list matches the plan exactly.
    index = _build_index(project_root)
    try:
        source = (Path(project_root) / module_rel).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    names: list[str] = []
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for method in _eligible_methods(node, index):
            if _drop_self_from_header(lines[method.lineno - 1]) is not None:
                names.append(method.name)
    return names
