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


def _collect_module_facts(rel: str, tree: ast.Module) -> _ModuleFacts:
    """One pass over a module's AST producing every fact the scan needs."""
    uses: set[str] = set()
    string_constants: set[str] = set()
    exports: set[str] = set()
    star_targets: set[str] = set()
    has_dynamic_access = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            uses.add(node.id)
        elif isinstance(node, ast.Attribute):
            uses.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            if node.module and any(a.name == "*" for a in node.names):
                star_targets.add(node.module)  # `from X import *` re-exports X
            for a in node.names:
                uses.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                uses.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            string_constants.add(node.value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _DYNAMIC_BUILTINS
        ):
            has_dynamic_access = True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__all__"
                    and isinstance(node.value, (ast.List, ast.Tuple))
                ):
                    exports.update(
                        e.value
                        for e in node.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    )

    definitions: list[tuple[str, str, int]] = []
    for node in tree.body:  # top-level definitions only
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.decorator_list:  # rule 8: decorator may register the symbol externally
            continue
        name = node.name
        if _is_dunder(name) or _is_entrypoint(name) or _is_test_name(name):
            continue  # rules 2, 4, 5
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        definitions.append((name, kind, node.lineno))

    return _ModuleFacts(
        rel=rel,
        uses=frozenset(uses),
        string_constants=frozenset(string_constants),
        exports=frozenset(exports),
        has_dynamic_access=has_dynamic_access,
        star_targets=frozenset(star_targets),
        definitions=tuple(definitions),
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

    files = [p for p in iter_source_files(root) if not is_skipped(p.relative_to(root))]
    files = files[: max(0, max_files)]

    facts: list[_ModuleFacts] = []
    for path in files:
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError):
            continue  # unreadable/unparsable files contribute nothing, conservatively
        rel = path.relative_to(root).as_posix()
        facts.append(_collect_module_facts(rel, tree))

    files_scanned = len(facts)

    # Project-wide use universe (rules 1, 3, 6): a name is "live" if it is used,
    # exported, or appears as a string constant anywhere in the project. Star
    # targets (rule 7) name whole modules whose defs are re-exported wholesale.
    used_names: set[str] = set()
    exported_names: set[str] = set()
    string_names: set[str] = set()
    star_targets: set[str] = set()
    for fact in facts:
        used_names |= fact.uses
        exported_names |= fact.exports
        string_names |= fact.string_constants
        star_targets |= fact.star_targets

    definitions_seen = 0
    candidates: list[dict] = []
    for fact in facts:
        if _is_excluded_definition_site(fact.rel):  # rule 10
            continue
        if fact.has_dynamic_access:  # rule 7: dynamic resolution in this module
            continue
        if _module_name(fact.rel) in star_targets:  # rule 7: re-exported via `*`
            continue
        for name, kind, line in fact.definitions:
            definitions_seen += 1
            if name in used_names or name in exported_names or name in string_names:
                continue  # rules 1, 3, 6
            candidates.append(
                {"module": fact.rel, "symbol": name, "kind": kind, "line": line}
            )

    candidates.sort(key=lambda c: (c["module"], c["line"], c["symbol"]))
    candidate_count = len(candidates)
    reported = candidates[:_MAX_CANDIDATES]

    return DeadCodeReport(
        candidates=reported,
        files_scanned=files_scanned,
        definitions_seen=definitions_seen,
        candidate_count=candidate_count,
        reported_count=len(reported),
        truncated=candidate_count > len(reported),
    )
