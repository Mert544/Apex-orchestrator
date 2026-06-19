"""Conservative cross-file dead-code analyzer — top-level defs nothing uses.

A deterministic, stdlib-only, zero-token analyzer that reasons across the WHOLE
project (not one file at a time): it builds a single project-wide *use* set —
every ``Name`` load, every ``Attribute`` access, and every imported alias seen
anywhere — and then flags top-level functions/classes whose name never appears
in that set. The intent is a *surfaced* "verify before removing" signal, never
an auto-removal and never a grade input, so the bias is firmly toward silence:
when a symbol *might* be reachable, it is NOT flagged.

Why a fresh self-contained module (alongside ``app.reporting.deadcode``): this
one is tuned for the lowest possible false-positive rate. It layers extra
conservative guards on top of the basic "name never referenced" check, each
documented below, and reports through a small :class:`DeadCodeReport` dataclass
with counts so callers can see how aggressively it pruned.

Exclusion rules — a symbol is NEVER flagged when ANY of these hold:

  1. **Referenced anywhere.** Its name appears as a ``Name``-load, an
     ``Attribute`` ``.attr``, or an imported alias in *any* project file,
     including the file that defines it (the definition file's other code may
     use it) and the test suite.
  2. **Dunder.** ``__name__``-style names (``__init__``, ``__repr__``, …) are
     called implicitly by the runtime/protocols and can't be seen as static
     references.
  3. **`__all__`-exported.** A name listed in any module's ``__all__`` is a
     declared public export; downstream consumers this scan can't see may
     ``from mod import *`` it.
  4. **Entrypoints.** ``main`` and CLI command handlers (``cmd_*``) are invoked
     by a runner / argparse dispatch, not by an in-tree call.
  5. **Test functions.** ``test_*`` are collected and called by pytest, not by
     project code.
  6. **String-referenced.** A name that appears verbatim as a string *constant*
     anywhere (dispatch tables, plugin registries, ``getattr(obj, "name")``)
     is assumed to be reached dynamically.
  7. **Dynamic access present.** If a module contains a ``getattr``/``setattr``/
     ``hasattr`` call, the symbols defined *in that module* are not flagged — they
     may be resolved by string. And any module that is the target of a
     ``from pkg.mod import *`` star-import anywhere has ALL of its top-level
     symbols treated as live (a star-import re-exports them wholesale to a
     consumer this scan can't follow).
  8. **Decorated.** A decorated def is frequently registered with an external
     framework (routes, fixtures, click commands) by the decorator itself, so a
     missing in-tree call proves nothing.
  9. **Underscore-private convention is NOT used to flag.** This module reports
     both public and private candidates the same way (and caps the list); it
     does not special-case ``_name`` as higher-confidence.
 10. **Excluded definition sites.** Symbols defined in ``__init__.py`` (re-export
     surfaces) and in test files (``test_*.py`` / ``tests/`` / ``conftest.py``)
     are never reported — those files legitimately carry unreferenced names.

Empty-safe (no files → empty report), pure (no clock / random / network /
mutation of inputs), and deterministic (sorted file walk, sorted output).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import is_skipped, iter_source_files

__all__ = ["DeadCodeReport", "analyze_dead_code"]

# Cap on reported candidates: this is a "verify before removing" nudge, not an
# exhaustive list, so a short, stable head is more useful than a long tail.
_MAX_CANDIDATES = 20

# Names that are reached by a runner / framework, never by an in-tree call.
_ENTRYPOINT_NAMES = frozenset({"main"})

# Dynamic-access builtins: their presence in a module means symbols in that
# module may be resolved by string, so we stop flagging that module's defs.
_DYNAMIC_BUILTINS = frozenset({"getattr", "setattr", "hasattr", "delattr"})


def _is_dunder(name: str) -> bool:
    """True for ``__x__`` names — implicitly invoked, never statically referenced."""
    return name.startswith("__") and name.endswith("__") and len(name) > 4


def _is_entrypoint(name: str) -> bool:
    """``main`` and CLI command handlers (``cmd_*``) are dispatched externally."""
    return name in _ENTRYPOINT_NAMES or name.startswith("cmd_")


def _is_test_name(name: str) -> bool:
    """``test_*`` functions are collected and called by pytest, not by code."""
    return name.startswith("test_")


def _is_test_path(rel: str) -> bool:
    """A test definition site: ``tests/`` dir, ``test_*.py``, or ``conftest.py``."""
    r = rel.replace("\\", "/").lower()
    name = r.rsplit("/", 1)[-1]
    return (
        r.startswith(("tests/", "test/"))
        or "/tests/" in f"/{r}"
        or "/test/" in f"/{r}"
        or name.startswith("test_")
        or name == "conftest.py"
    )


def _is_excluded_definition_site(rel: str) -> bool:
    """Files we never report dead symbols *in*: tests and ``__init__`` surfaces."""
    name = rel.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return _is_test_path(rel) or name == "__init__.py"


@dataclass(frozen=True)
class _ModuleFacts:
    """Everything one parsed module contributes, computed in a single AST walk."""

    rel: str
    uses: frozenset[str]              # Name-loads, Attribute attrs, import aliases
    string_constants: frozenset[str]  # every str constant value (dynamic dispatch)
    exports: frozenset[str]           # names listed in __all__
    has_dynamic_access: bool          # getattr/setattr/... call present
    star_targets: frozenset[str]      # dotted modules star-imported here (`X.*`)
    # (name, kind, lineno) for each top-level function/class that *could* be dead
    definitions: tuple[tuple[str, str, int], ...]


def _uses_from_node(node: ast.AST) -> tuple[str, ...]:
    """Names a single node contributes to the project *use* set (rules 1, 7).

    A ``Name``-load yields its ``id``; an ``Attribute`` its ``.attr``; an
    ``import``/``from import`` its bound aliases. Any other node yields nothing.
    """
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (node.attr,)
    if isinstance(node, ast.ImportFrom):
        return tuple(a.asname or a.name for a in node.names)
    if isinstance(node, ast.Import):
        return tuple((a.asname or a.name).split(".")[0] for a in node.names)
    return ()


def _star_target_of(node: ast.AST) -> str | None:
    """The dotted module of a ``from X import *`` node, else ``None`` (rule 7)."""
    if isinstance(node, ast.ImportFrom) and node.module:
        if any(a.name == "*" for a in node.names):
            return node.module
    return None


def _string_constant_of(node: ast.AST) -> str | None:
    """The value of a string ``Constant`` node, else ``None`` (rule 6)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_dynamic_access_call(node: ast.AST) -> bool:
    """True for a ``getattr``/``setattr``/... call — dynamic resolution (rule 7)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _DYNAMIC_BUILTINS
    )


def _exports_from_node(node: ast.AST) -> tuple[str, ...]:
    """Names declared by an ``__all__ = [...]``/``(...)`` assignment (rule 3)."""
    if not isinstance(node, ast.Assign):
        return ()
    if not isinstance(node.value, (ast.List, ast.Tuple)):
        return ()
    if not any(
        isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
    ):
        return ()
    return tuple(
        e.value
        for e in node.value.elts
        if isinstance(e, ast.Constant) and isinstance(e.value, str)
    )


def _is_dead_candidate_def(node: ast.AST) -> bool:
    """True for a top-level def that survives the per-def exclusions (rules 2,4,5,8)."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return False
    if node.decorator_list:  # rule 8: decorator may register the symbol externally
        return False
    name = node.name
    return not (_is_dunder(name) or _is_entrypoint(name) or _is_test_name(name))


def _collect_definitions(tree: ast.Module) -> tuple[tuple[str, str, int], ...]:
    """``(name, kind, lineno)`` for each top-level def that *could* be dead."""
    definitions: list[tuple[str, str, int]] = []
    for node in tree.body:  # top-level definitions only
        if not _is_dead_candidate_def(node):
            continue
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        definitions.append((node.name, kind, node.lineno))
    return tuple(definitions)


def _collect_module_facts(rel: str, tree: ast.Module) -> _ModuleFacts:
    """One pass over a module's AST producing every fact the scan needs."""
    uses: set[str] = set()
    string_constants: set[str] = set()
    exports: set[str] = set()
    star_targets: set[str] = set()
    has_dynamic_access = False

    for node in ast.walk(tree):
        uses.update(_uses_from_node(node))
        exports.update(_exports_from_node(node))
        star = _star_target_of(node)
        if star is not None:
            star_targets.add(star)
        text = _string_constant_of(node)
        if text is not None:
            string_constants.add(text)
        if _is_dynamic_access_call(node):
            has_dynamic_access = True

    return _ModuleFacts(
        rel=rel,
        uses=frozenset(uses),
        string_constants=frozenset(string_constants),
        exports=frozenset(exports),
        has_dynamic_access=has_dynamic_access,
        star_targets=frozenset(star_targets),
        definitions=_collect_definitions(tree),
    )


def _module_name(rel: str) -> str:
    """The dotted import name a ``root``-relative ``.py`` path is reached by.

    ``pkg/sub/mod.py`` -> ``pkg.sub.mod``; ``pkg/__init__.py`` -> ``pkg``. Used to
    match a definition file against ``from X import *`` star-import targets.
    """
    parts = rel[:-3].split("/") if rel.endswith(".py") else rel.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


@dataclass
class DeadCodeReport:
    """Result of :func:`analyze_dead_code`.

    ``candidates`` holds at most ``_MAX_CANDIDATES`` dicts shaped
    ``{"module": str, "symbol": str, "kind": str, "line": int}``, sorted
    deterministically by ``(module, line, symbol)``. The counts describe the run:

      - ``files_scanned``    — project ``.py`` files parsed (skip-dirs excluded);
      - ``definitions_seen`` — top-level defs considered after per-def exclusions;
      - ``candidate_count``  — defs that survived every guard (may exceed the cap);
      - ``reported_count``   — ``len(candidates)`` (after the cap);
      - ``truncated``        — True when ``candidate_count > reported_count``.
    """

    candidates: list[dict] = field(default_factory=list)
    files_scanned: int = 0
    definitions_seen: int = 0
    candidate_count: int = 0
    reported_count: int = 0
    truncated: bool = False


def _gather_facts(root: Path, max_files: int) -> list[_ModuleFacts]:
    """Parse up to ``max_files`` project modules into ``_ModuleFacts`` (skip-dirs
    excluded); unreadable/unparsable files contribute nothing, conservatively."""
    files = [p for p in iter_source_files(root) if not is_skipped(p.relative_to(root))]
    files = files[: max(0, max_files)]

    facts: list[_ModuleFacts] = []
    for path in files:
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        rel = path.relative_to(root).as_posix()
        facts.append(_collect_module_facts(rel, tree))
    return facts


def _live_names(facts: list[_ModuleFacts]) -> frozenset[str]:
    """Project-wide "live" name universe (rules 1, 3, 6): every name used,
    exported, or appearing as a string constant anywhere in the project."""
    live: set[str] = set()
    for fact in facts:
        live |= fact.uses
        live |= fact.exports
        live |= fact.string_constants
    return frozenset(live)


def _star_targets(facts: list[_ModuleFacts]) -> frozenset[str]:
    """Whole modules star-imported anywhere — their defs are re-exported (rule 7)."""
    targets: set[str] = set()
    for fact in facts:
        targets |= fact.star_targets
    return frozenset(targets)


def _is_excluded_definition_module(fact: _ModuleFacts, star_targets: frozenset[str]) -> bool:
    """Whether a whole module's defs are exempt: a test/``__init__`` site (rule
    10), a module with dynamic access (rule 7), or a star-import target (rule 7)."""
    return (
        _is_excluded_definition_site(fact.rel)
        or fact.has_dynamic_access
        or _module_name(fact.rel) in star_targets
    )


def _collect_candidates(
    facts: list[_ModuleFacts], live_names: frozenset[str], star_targets: frozenset[str]
) -> tuple[list[dict], int]:
    """Surviving dead-code candidates and the count of definitions considered."""
    definitions_seen = 0
    candidates: list[dict] = []
    for fact in facts:
        if _is_excluded_definition_module(fact, star_targets):
            continue
        for name, kind, line in fact.definitions:
            definitions_seen += 1
            if name in live_names:  # rules 1, 3, 6
                continue
            candidates.append(
                {"module": fact.rel, "symbol": name, "kind": kind, "line": line}
            )
    candidates.sort(key=lambda c: (c["module"], c["line"], c["symbol"]))
    return candidates, definitions_seen


def analyze_dead_code(root: str | Path, max_files: int = 500) -> DeadCodeReport:
    """Flag top-level functions/classes that nothing in the project references.

    Parses up to ``max_files`` project ``.py`` files (skip-dirs — incl. ``.git``,
    ``__pycache__`` and ``.claude`` worktrees — excluded by
    :func:`app.engine.skip_dirs.iter_source_files`), unions every static *use*
    across all of them, then reports each surviving candidate. The result is
    deterministic, empty-safe, and pure: it reads files but mutates nothing and
    uses no clock/random/network. See the module docstring for every exclusion
    rule applied.
    """
    root = Path(root)
    if not root.exists():
        return DeadCodeReport()

    facts = _gather_facts(root, max_files)
    star_targets = _star_targets(facts)
    candidates, definitions_seen = _collect_candidates(
        facts, _live_names(facts), star_targets
    )

    candidate_count = len(candidates)
    reported = candidates[:_MAX_CANDIDATES]

    return DeadCodeReport(
        candidates=reported,
        files_scanned=len(facts),
        definitions_seen=definitions_seen,
        candidate_count=candidate_count,
        reported_count=len(reported),
        truncated=candidate_count > len(reported),
    )
