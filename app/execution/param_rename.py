"""Parameter rename — the signature-refactor family's first safe operation.

Renames a parameter of a top-level function project-wide: the ``def`` site,
every use inside the function body, and every **keyword** call site
(``f(old=1)`` → ``f(new=1)``); positional calls are untouched by
construction. Same span-edit machinery as :mod:`cross_file_rename` —
comments and formatting survive.

Conservative blockers, honest warnings:
  - the function must be defined exactly once in the project, at top level;
  - the old name must be a parameter; the new name must not be one (nor
    shadow another binding used in the body);
  - a nested function/lambda re-binding the old name blocks (its scope owns
    that name, not the signature);
  - ``f(**kwargs)`` call sites can smuggle the old key at runtime — warned,
    not rewritten.

Reuses :class:`RenamePlan` / :func:`apply_rename`, so apply is test-verified
with rollback like every Apex change. Deterministic, stdlib-only.
"""

from __future__ import annotations

import ast
import keyword as _kw
from pathlib import Path

from app.execution.cross_file_rename import (
    RenamePlan,
    Span,
    _apply_spans,
    _py_files,
)

__all__ = ["plan_param_rename", "RenamePlan"]


def _function_defs(tree: ast.Module, name: str) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]


def _all_params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    a = fn.args
    out = [*a.posonlyargs, *a.args, *a.kwonlyargs]
    if a.vararg:
        out.append(a.vararg)
    if a.kwarg:
        out.append(a.kwarg)
    return out


def _nested_rebinds(fn: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """Does any *nested* function/lambda bind ``name`` itself (param or local)?
    Those inner scopes own the name — renaming the outer param must not touch
    them, so we conservatively block."""
    for node in ast.walk(fn):
        if node is fn or not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        inner_args = node.args
        every = [*inner_args.posonlyargs, *inner_args.args, *inner_args.kwonlyargs]
        if inner_args.vararg:
            every.append(inner_args.vararg)
        if inner_args.kwarg:
            every.append(inner_args.kwarg)
        if any(a.arg == name for a in every):
            return True
        if not isinstance(node, ast.Lambda):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id == name and isinstance(sub.ctx, ast.Store):
                    return True
    return False


def _body_spans(fn: ast.FunctionDef | ast.AsyncFunctionDef, old: str) -> list[Span]:
    """The def-site spans: the parameter itself + every use in the body."""
    spans: list[Span] = []
    for a in _all_params(fn):
        if a.arg == old:
            spans.append((a.lineno, a.col_offset, a.col_offset + len(old)))
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id == old:
            spans.append((node.lineno, node.col_offset, node.col_offset + len(old)))
    return spans


def _call_resolves(node: ast.Call, func_name: str, from_names: set[str], module_aliases: set[str]) -> bool:
    """Does this call target our function, given the file's imports?"""
    f = node.func
    if isinstance(f, ast.Name):
        return f.id in from_names
    if isinstance(f, ast.Attribute) and f.attr == func_name:
        try:
            return ast.unparse(f.value) in module_aliases
        except Exception:
            return False
    return False


def _name_blocker(old: str, new: str) -> str | None:
    """Up-front validity gate on the two names (or ``None`` if both are fine)."""
    for name in (old, new):
        if not name.isidentifier() or _kw.iskeyword(name):
            return f"'{name}' is not a valid identifier"
    if old == new:
        return "old and new names are identical"
    return None


def _parse_trees(files: list[tuple[str, str]]) -> dict[str, ast.Module]:
    """Parse every readable file; skip the ones that don't parse."""
    trees: dict[str, ast.Module] = {}
    for rel, text in files:
        try:
            trees[rel] = ast.parse(text)
        except SyntaxError:
            continue
    return trees


def _resolve_definition(
    trees: dict[str, ast.Module], func_name: str
) -> tuple[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef] | None, str | None]:
    """Find the single top-level ``func_name`` definition, or a blocker explaining why not."""
    definitions = [(rel, fn) for rel, tree in trees.items()
                   for fn in _function_defs(tree, func_name)]
    if not definitions:
        return None, f"no top-level function '{func_name}' found"
    if len(definitions) > 1:
        where = ", ".join(rel for rel, _ in definitions)
        return None, (f"'{func_name}' is defined in {len(definitions)} modules "
                      f"({where}) — ambiguous")
    return definitions[0], None


def _signature_blocker(fn: ast.FunctionDef | ast.AsyncFunctionDef, defmod: str,
                       func_name: str, old: str, new: str) -> str | None:
    """Per-signature safety gates on the resolved definition (or ``None`` if clear)."""
    param_names = [a.arg for a in _all_params(fn)]
    if old not in param_names:
        return (f"'{old}' is not a parameter of {func_name}() "
                f"(has: {', '.join(param_names) or 'none'})")
    if new in param_names:
        return f"{func_name}() already has a parameter '{new}'"
    if _nested_rebinds(fn, old):
        return (f"{defmod}: a nested function inside {func_name}() re-binds '{old}' — "
                "rename the inner one first")
    if any(isinstance(n, ast.Name) and n.id == new for n in ast.walk(fn)):
        return f"{defmod}: '{new}' is already used inside {func_name}() — collision"
    return None


def _reaching_names(tree: ast.Module, func_name: str, dotted: str,
                    is_defmod: bool) -> tuple[set[str], set[str]]:
    """Local names / module aliases in this file that reach our function."""
    from_names: set[str] = {func_name} if is_defmod else set()
    module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == dotted:
            for alias in node.names:
                if alias.name == func_name:
                    from_names.add(alias.asname or func_name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == dotted:
                    module_aliases.add(alias.asname or alias.name)
    return from_names, module_aliases


def _call_site_spans(plan: RenamePlan, rel: str, tree: ast.Module, func_name: str,
                     old: str, from_names: set[str], module_aliases: set[str]) -> list[Span]:
    """Keyword-call spans for this file; warn on ``f(**…)`` that may smuggle ``old``."""
    spans: list[Span] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and _call_resolves(node, func_name,
                                   from_names=from_names,
                                   module_aliases=module_aliases)):
            continue
        for kw in node.keywords:
            if kw.arg == old:
                # keyword nodes carry their own position (the arg name).
                spans.append((kw.lineno, kw.col_offset, kw.col_offset + len(old)))
            elif kw.arg is None:  # f(**something) may smuggle the old key
                plan.warnings.append(
                    f"{rel}:{node.lineno}: {func_name}(**…) call — a dict may still "
                    f"carry '{old}'; check manually")
    return spans


def _record_file_edit(plan: RenamePlan, rel: str, source: str,
                      spans: list[Span], old: str, new: str) -> None:
    """Apply the located spans to one file and record the edit (or its blocker)."""
    if not spans:
        return
    rewritten = _apply_spans(source, spans, old, new)
    if rewritten is None:
        plan.blockers.append(f"{rel}: a located span no longer matches '{old}'")
        return
    if rewritten != source:
        plan.originals[rel] = source
        plan.new_contents[rel] = rewritten
        plan.edits_by_file[rel] = len(set(spans))


def _warn_string_literals(plan: RenamePlan, trees: dict[str, ast.Module], old: str) -> None:
    """Flag string literals equal to ``old`` — they may be dynamic references."""
    for rel, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == old:
                plan.warnings.append(f"{rel}:{node.lineno}: string literal '{old}' — "
                                     "dynamic reference? check manually")


def plan_param_rename(project_root: str | Path, func_name: str,
                      old: str, new: str) -> RenamePlan:
    """Build the project-wide parameter-rename plan, or its blockers."""
    plan = RenamePlan(old=old, new=new)
    name_blocker = _name_blocker(old, new)
    if name_blocker is not None:
        plan.blockers.append(name_blocker)
        return plan

    root = Path(project_root)
    files = _py_files(root)
    sources = dict(files)
    trees = _parse_trees(files)

    definition, def_blocker = _resolve_definition(trees, func_name)
    if definition is None:
        plan.blockers.append(def_blocker)
        return plan

    defmod, fn = definition
    plan.defined_in = defmod
    dotted = defmod[:-3].replace("/", ".")
    sig_blocker = _signature_blocker(fn, defmod, func_name, old, new)
    if sig_blocker is not None:
        plan.blockers.append(sig_blocker)
        return plan

    for rel, tree in trees.items():
        source = sources[rel]
        spans: list[Span] = list(_body_spans(fn, old)) if rel == defmod else []
        from_names, module_aliases = _reaching_names(tree, func_name, dotted, rel == defmod)
        spans.extend(_call_site_spans(plan, rel, tree, func_name, old,
                                      from_names, module_aliases))
        _record_file_edit(plan, rel, source, spans, old, new)

    _warn_string_literals(plan, trees, old)
    return plan
