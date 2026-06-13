"""Extract a repeated "magic" literal into a named module-level constant.

A detection -> action refactor: find a literal value (a non-trivial int, a
float, or a short string) that appears many times in ONE module as a bare
standalone literal, name it once at the top of the file, and replace every
occurrence with that name. The reader gains a meaning ("86400" becomes
``SECONDS_PER_DAY``-shaped ``CONSTANT_86400``) and the editor gains a single
place to change the value.

Conservative by design, like its neighbors — every ambiguity is a **blocker**,
never a guess. Only literals that can be safely named and spliced are touched:

  - docstrings, the value of an existing module-level constant assignment, and
    keyword-default / annotation positions are left alone (renaming them would
    change meaning or break the splice);
  - f-strings, bytes, and any multi-line literal are skipped (the splice is
    intra-line by design, so comments and formatting survive);
  - trivial literals (-1, 0, 1, 2, the empty/one-char string) are never named;
  - a literal seen fewer than ``min_occurrences`` times is not worth a name.

Exactly ONE constant — the most-repeated qualifying literal — is extracted per
call. Edits are precise AST text spans (no unparse round-trip), spliced
bottom-up / right-to-left so earlier offsets stay valid. The result must
re-parse or the plan blocks.

Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
import keyword
import re
from pathlib import Path

from app.execution.cross_file_rename import (
    RenamePlan,
    _py_files,
    _top_level_bindings,
)

__all__ = ["plan_extract_constant"]

# Integers so common they read as structure, not magic — naming them adds noise.
_TRIVIAL_INTS = {-1, 0, 1, 2}


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code is excluded (its repetition is often deliberate
    boilerplate). A local copy — mirrors ``app/engine/dedup.py`` to avoid an
    import dependency on the health/dedup layer from a pure transform."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def _qualifies(value: object) -> bool:
    """Is ``value`` a literal worth extracting into a named constant?"""
    # bool is an int subclass — True/False are already named, never extract.
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value not in _TRIVIAL_INTS
    if isinstance(value, float):
        return True
    if isinstance(value, str):
        return len(value) >= 2
    return False


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """``id()`` of every Constant that is a module/class/function docstring."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def _module_const_value_nodes(tree: ast.Module) -> set[int]:
    """``id()`` of Constants that are the RHS of a top-level constant
    assignment (``NAME = <const>``). Those literals already have a name."""
    out: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            value = node.value
        else:
            continue
        if isinstance(value, ast.Constant):
            out.add(id(value))
    return out


def _unsafe_parent_constants(tree: ast.Module) -> set[int]:
    """``id()`` of Constants in positions a bare-name swap would corrupt:
    keyword-argument / signature defaults and dict keys. Replacing those with a
    forward module name is risky or changes a data surface, so leave them."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.arguments):
            for default in (*node.defaults, *node.kw_defaults):
                if isinstance(default, ast.Constant):
                    out.add(id(default))
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant):
                    out.add(id(key))
    return out


def _collect_occurrences(tree: ast.Module) -> dict[object, list[ast.Constant]]:
    """Map each qualifying literal value to the standalone, single-line,
    splice-safe Constant nodes that hold it."""
    skip = (_docstring_nodes(tree)
            | _module_const_value_nodes(tree)
            | _unsafe_parent_constants(tree))
    by_value: dict[object, list[ast.Constant]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if id(node) in skip:
            continue
        value = node.value
        if not _qualifies(value):
            continue
        # Intra-line splice only — a multi-line literal (triple-quoted string)
        # can't be replaced without disturbing surrounding lines.
        if node.lineno != node.end_lineno:
            continue
        by_value.setdefault(value, []).append(node)
    return by_value


def _slugify_string(value: str) -> str:
    """An UPPER_SNAKE identifier core from a string's content."""
    return re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_").upper()


def _base_name(value: object) -> str:
    """A deterministic constant-name base for ``value`` (no collision suffix)."""
    if isinstance(value, str):
        core = _slugify_string(value)
        if not core or not (core[0].isalpha() or core[0] == "_"):
            core = f"STR_{core}" if core else "STR"
        name = f"CONST_{core}"
    elif isinstance(value, int):
        sign = "NEG_" if value < 0 else ""
        name = f"CONSTANT_{sign}{abs(value)}"
    else:  # float
        text = repr(value).replace("-", "NEG_").replace(".", "_").replace("+", "")
        text = re.sub(r"[^0-9A-Za-z_]+", "_", text).strip("_").upper()
        name = f"CONSTANT_{text}"
    if not name.isidentifier() or keyword.iskeyword(name):
        name = "CONSTANT"
    return name


def _free_name(base: str, taken: set[str]) -> str:
    """``base`` if unused, else ``base_2``, ``base_3``, … — always free."""
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def _insert_index(tree: ast.Module) -> int:
    """The 0-based line index at which to insert the new ``NAME = <literal>``:
    after the module docstring, ``__future__`` imports, and the leading import
    block, but before the first real statement."""
    idx = 0
    for node in tree.body:
        is_docstring = (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        if is_docstring or isinstance(node, (ast.Import, ast.ImportFrom)):
            idx = node.end_lineno  # 1-based end line -> 0-based "next line"
        else:
            break
    return idx


def plan_extract_constant(
    project_root: str | Path,
    module_rel: str,
    min_occurrences: int = 3,
    source: str | None = None,
) -> RenamePlan:
    """Plan extracting the most-repeated magic literal in ``module_rel`` into a
    named module-level constant, or surface the blockers that stop it.

    ``source`` lets a caller that already has the module's text in hand (Apex's
    mtime-fingerprinted source index) pass it straight in, skipping the
    project-wide ``_py_files`` walk this otherwise does on every call. Left
    ``None`` the text is read from disk exactly as before, so every existing
    caller is unchanged; a supplied ``source`` is the same bytes the walk would
    have read, so the resulting plan is byte-for-byte identical."""
    plan = RenamePlan(old=module_rel, new="extract-constant")
    root = Path(project_root)

    if min_occurrences < 2:
        plan.blockers.append("min_occurrences must be at least 2")
        return plan

    rel = module_rel.replace("\\", "/")
    if _is_fixture_path(rel):
        plan.blockers.append(f"{rel}: fixture/test/example module — skipped")
        return plan

    if source is None:
        sources = dict(_py_files(root))
        if rel not in sources:
            plan.blockers.append(f"{rel}: module not found under project root")
            return plan
        source = sources[rel]
    try:
        tree = ast.parse(source)
    except SyntaxError:
        plan.blockers.append(f"{rel}: module does not parse")
        return plan

    by_value = _collect_occurrences(tree)
    candidates = [
        (value, nodes) for value, nodes in by_value.items()
        if len(nodes) >= min_occurrences
    ]
    if not candidates:
        # No qualifying literal — an empty, non-blocking plan (nothing to do).
        return plan

    # Most-repeated wins; deterministic tie-break on the value's repr.
    best = max(len(ns) for _, ns in candidates)
    value, nodes = min(
        ((v, ns) for v, ns in candidates if len(ns) == best),
        key=lambda c: repr(c[0]),
    )

    taken = _top_level_bindings(tree)
    name = _free_name(_base_name(value), taken)
    if not name.isidentifier() or keyword.iskeyword(name):
        plan.blockers.append(f"{rel}: could not synthesize a valid constant name")
        return plan

    lines = source.splitlines(keepends=True)

    # Splice every occurrence, bottom-up / right-to-left, so earlier spans stay
    # valid as we edit. Each span must still hold the literal's exact source.
    spans: list[tuple[int, int, int]] = [
        (n.lineno, n.col_offset, n.end_col_offset) for n in nodes
    ]
    for line_no, start, end in sorted(set(spans), reverse=True):
        row = lines[line_no - 1]
        segment = row[start:end]
        try:
            parsed = ast.literal_eval(segment)
        except (ValueError, SyntaxError):
            plan.blockers.append(
                f"{rel}:{line_no}: span is not a re-readable literal")
            return plan
        if parsed != value or type(parsed) is not type(value):
            plan.blockers.append(
                f"{rel}:{line_no}: span no longer holds the literal")
            return plan
        lines[line_no - 1] = row[:start] + name + row[end:]

    # Insert `NAME = <literal>` after the import/docstring prologue. The literal
    # text is the canonical repr so the assignment re-parses to the same value.
    insert_at = _insert_index(tree)
    newline = "\n"
    for ln in lines:
        if ln.endswith("\r\n"):
            newline = "\r\n"
            break
    assign = f"{name} = {repr(value)}{newline}"
    lines.insert(insert_at, assign)

    new_content = "".join(lines)
    try:
        ast.parse(new_content)
    except SyntaxError:
        plan.blockers.append(f"{rel}: result does not re-parse — aborting")
        return plan

    plan.defined_in = rel
    plan.originals[rel] = source
    plan.new_contents[rel] = new_content
    plan.edits_by_file[rel] = len(set(spans))
    return plan
