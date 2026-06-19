"""Magic-number / hardcoded-literal density — where a named constant would read clearer.

A deterministic, conservative analyzer for *unexplained* literals: numeric and
string constants sitting in code positions (a comparison, an arithmetic
expression, a call argument) where a named constant — ``TIMEOUT_SECONDS`` instead
of a bare ``3600`` — would tell the reader *what* the value means and let it be
changed in one place. The signal it cares most about is a **repeated** magic
number: the same literal written out three or more times across a module or the
project is a strong, mechanical "extract a constant" finding, free of taste.

Being conservative is the whole point — a noisy magic-number linter trains people
to ignore it. So the allow-list below is deliberately wide; a literal is only
flagged when it is genuinely *bare* and *meaningful*.

Allow-list (NEVER flagged), and why each is allowed:

  - the ubiquitous numerics ``0``, ``1``, ``-1`` and ``2`` — identity / empty /
    sentinel / off-by-one / halving values whose meaning is universal;
  - the empty string ``""`` — the canonical empty/default, never a magic value;
  - common dunder and metadata strings (``__main__``, ``__init__``, ``__name__``,
    ``__all__`` entries, …) — protocol identifiers, not configuration;
  - **docstrings** — module/class/function leading string statements carry prose,
    not values;
  - **type annotations** — ``Literal[...]`` and annotation positions describe a
    type, and a string there is a forward-ref, not a magic value;
  - **simple default arguments** — a default of a small int or a short string is a
    documented call-site default, already named by its parameter;
  - keyword-argument *names* and dict/`f-string` formatting are out of scope;
  - any literal inside a **test / fixture / example** file — fixtures are *built*
    from literals by design.

Public API: :func:`analyze_literal_density` returns a :class:`LiteralDensity`.

Deterministic (every collection sorted; no clock/random/network), stdlib-only
(``ast`` + path walking), offline, read-only, and empty-safe.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import is_skipped, iter_source_files

__all__ = [
    "LiteralDensity",
    "analyze_literal_density",
    "ALLOWED_NUMBERS",
    "ALLOWED_STRINGS",
    "REPEAT_THRESHOLD",
]

# ── allow-list ──────────────────────────────────────────────────────────────

# Bare numeric literals whose meaning is universal; never flagged. ``-1`` is
# matched specially (it parses as ``UnaryOp(USub, Constant(1))``, not a literal).
ALLOWED_NUMBERS: frozenset[int | float] = frozenset({0, 1, 2})

# Bare string literals that are protocol/metadata, not configuration values.
ALLOWED_STRINGS: frozenset[str] = frozenset({
    "", "__main__", "__init__", "__name__", "__all__", "__file__",
    "utf-8", "utf8", "ascii", "__doc__", "__module__",
})

# A literal repeated this many times (or more) across the analyzed set is a
# strong, taste-free "extract a constant" finding.
REPEAT_THRESHOLD = 3

# Most ``repeated`` entries any one report carries — keeps output bounded.
_MAX_REPEATED = 15


def _is_fixture_path(rel: str) -> bool:
    """True for test / fixture / example modules, whose literals are intentional.

    A pure path-name check (lower-cased, slash-normalised) so it is identical on
    any platform and never reads a file."""
    p = rel.replace("\\", "/").lower()
    return (
        p.startswith(("tests/", "test/", "fixtures/", "examples/", "example/"))
        or "/tests/" in p or "/test/" in p
        or "/fixtures/" in p or "/examples/" in p
        or Path(p).name.startswith("test_")
        or Path(p).name == "conftest.py"
    )


@dataclass
class LiteralDensity:
    """Project-wide magic-literal findings.

    ``total_magic`` is the count of flagged literal occurrences across every
    analyzed module. ``per_module`` maps each module's relative path to its
    ``(magic_count, code_lines)`` so a caller can rank by raw count or by
    *density* (magic per line). ``repeated`` lists the worst repeated literals —
    each ``{"literal": <repr>, "count": <int>, "modules": [<rel>, …]}`` — sorted
    by descending count then literal repr, capped at :data:`_MAX_REPEATED`.
    ``files_analyzed`` records how many modules were actually read.
    """

    total_magic: int = 0
    per_module: dict[str, tuple[int, int]] = field(default_factory=dict)
    repeated: list[dict] = field(default_factory=list)
    files_analyzed: int = 0

    @property
    def density(self) -> float:
        """Magic literals per code line across the whole analyzed set (0.0 when
        empty), rounded to four places for stable comparison."""
        lines = sum(loc for _, loc in self.per_module.values())
        if lines <= 0:
            return 0.0
        return round(self.total_magic / lines, 4)


# ── AST scoring ─────────────────────────────────────────────────────────────

def _docstring_nodes(tree: ast.AST) -> set[int]:
    """``id()`` of every Constant node that is a docstring (a leading string
    expression statement of a module / class / function body)."""
    out: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            out.add(id(first.value))
    return out


def _annotation_nodes(tree: ast.AST) -> set[int]:
    """``id()`` of every Constant node reachable from a type annotation — a
    string there is a forward-ref / ``Literal`` member, never a magic value."""
    out: set[int] = set()

    def collect(annotation: ast.AST | None) -> None:
        if annotation is None:
            return
        for sub in ast.walk(annotation):
            if isinstance(sub, ast.Constant):
                out.add(id(sub))

    for node in ast.walk(tree):
        if isinstance(node, (ast.AnnAssign,)):
            collect(node.annotation)
        elif isinstance(node, ast.arg):
            collect(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            collect(node.returns)
    return out


def _default_nodes(tree: ast.AST) -> set[int]:
    """``id()`` of every Constant that is a *simple* default argument value — a
    small int/float or a short string. Such a default is already named by its
    parameter, so it is not a bare magic literal."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.Lambda)):
            continue
        args = node.args
        defaults = list(args.defaults) + [
            d for d in args.kw_defaults if d is not None
        ]
        for default in defaults:
            if isinstance(default, ast.Constant):
                out.add(id(default))
            # ``-1`` style negative numeric default.
            elif (isinstance(default, ast.UnaryOp)
                  and isinstance(default.op, ast.USub)
                  and isinstance(default.operand, ast.Constant)):
                out.add(id(default.operand))
    return out


def _dunder_all_nodes(tree: ast.AST) -> set[int]:
    """``id()`` of every string Constant inside an ``__all__ = [...]`` assignment
    — those are export names, not values."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if "__all__" not in names:
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                out.add(id(sub))
    return out


def _is_allowed_value(value: object) -> bool:
    """True if the literal's *value* is on the universal allow-list."""
    if isinstance(value, bool):  # True/False are never magic.
        return True
    if isinstance(value, str):
        return value in ALLOWED_STRINGS
    if isinstance(value, (int, float)) and not isinstance(value, complex):
        return value in ALLOWED_NUMBERS
    # bytes / complex / None: out of scope, treat as allowed.
    return True


def _negative_one_nodes(tree: ast.AST) -> set[int]:
    """``id()`` of every Constant ``1`` that is the operand of a unary minus, so
    the value ``-1`` is allowed wherever it appears (not only as a default)."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.UnaryOp)
                and isinstance(node.op, ast.USub)
                and isinstance(node.operand, ast.Constant)
                and node.operand.value in (1,)):
            out.add(id(node.operand))
    return out


def _literal_key(value: object) -> str:
    """A stable, hashable display key for a literal value (its ``repr``)."""
    return repr(value)


def _module_literals(source: str) -> tuple[list[str], int]:
    """Flagged literals in one module's source and its code-line count.

    Returns ``(keys, code_lines)`` where ``keys`` are the ``repr`` of each
    flagged literal occurrence (so repeats appear multiple times). Unparseable
    source yields ``([], <line count>)`` — it is never counted as magic."""
    code_lines = sum(
        1 for line in source.splitlines()
        if (s := line.strip()) and not s.startswith("#")
    )
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return [], code_lines

    excluded = (
        _docstring_nodes(tree)
        | _annotation_nodes(tree)
        | _default_nodes(tree)
        | _dunder_all_nodes(tree)
        | _negative_one_nodes(tree)
    )

    keys: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if id(node) in excluded:
            continue
        value = node.value
        if not isinstance(value, (int, float, str)) or isinstance(value, bool):
            continue
        if _is_allowed_value(value):
            continue
        keys.append(_literal_key(value))
    return keys, code_lines


def analyze_literal_density(
    root: str | Path, max_files: int = 500
) -> LiteralDensity:
    """Magic-literal density across the Python modules under ``root``.

    Walks every ``*.py`` file that crosses no excluded directory
    (:func:`app.engine.skip_dirs.iter_source_files`), skips test / fixture /
    example modules, and flags each *bare, meaningful* literal per the module
    allow-list. A literal repeated :data:`REPEAT_THRESHOLD`+ times across the
    analyzed set is surfaced in ``repeated`` as a "extract a constant" finding.

    Deterministic and empty-safe: a missing root, an empty tree, or a tree of
    only fixtures all return a zero-valued :class:`LiteralDensity`.
    """
    root = Path(root)
    result = LiteralDensity()
    if not root.exists():
        return result

    # ``repr`` of a literal -> total occurrences, and -> set of modules using it.
    repeat_counts: dict[str, int] = {}
    repeat_modules: dict[str, set[str]] = {}

    files = list(iter_source_files(root))[:max(0, max_files)]
    for path in files:
        rel = path.relative_to(root).as_posix()
        if is_skipped(rel) or _is_fixture_path(rel):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        keys, code_lines = _module_literals(source)
        result.files_analyzed += 1
        result.per_module[rel] = (len(keys), code_lines)
        result.total_magic += len(keys)
        for key in keys:
            repeat_counts[key] = repeat_counts.get(key, 0) + 1
            repeat_modules.setdefault(key, set()).add(rel)

    repeated = [
        {
            "literal": key,
            "count": count,
            "modules": sorted(repeat_modules[key]),
        }
        for key, count in repeat_counts.items()
        if count >= REPEAT_THRESHOLD
    ]
    # Deterministic order: most-repeated first, ties broken by literal repr.
    repeated.sort(key=lambda d: (-d["count"], d["literal"]))
    result.repeated = repeated[:_MAX_REPEATED]
    return result
