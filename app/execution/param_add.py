"""Add a parameter with a safe default — the signature family's third operation.

The usual first step of extending a feature: the function gains a new
parameter project-wide-safely, because the default keeps every existing
call site valid by construction. Placement is chosen so NO caller's
meaning can shift:

  - plain signatures: appended after the positional parameters
    (``def f(a)`` → ``def f(a, retries=3)``);
  - with ``*args`` or existing keyword-only params: appended keyword-only
    (``def f(a, *items)`` → ``def f(a, *items, retries=3)``) — a trailing
    positional default before ``*args`` would silently absorb arguments;
  - ``**kwargs`` stays last.

Same conservative creed as ``drop``: ambiguity is a **blocker**, never a
guess — the name must be genuinely new (not a parameter, not used anywhere
in the body, where adding it would change name resolution), the default
must parse as an expression, a call site already passing the keyword
blocks, ``f(**…)`` sites warn, and a comment inside the signature blocks
(comment-preservation promise). Reuses :class:`RenamePlan` /
:func:`apply_rename` — dry-run diffs, test verification and rollback come
for free. Deterministic, stdlib-only.
"""

from __future__ import annotations

import ast
import keyword as _kw
from pathlib import Path

from app.execution._transform_base import (
    parse_trees as _parse_trees,
    pin_signature_lines as _pin_signature_lines,
    resolve_sole_definition as _sole_definition,
)
from app.execution.cross_file_rename import RenamePlan, _py_files
from app.execution.param_drop import _segment, _signature_span
from app.execution.param_rename import _all_params

__all__ = ["plan_param_add"]


def _rebuild_with_param(source: str, fn: ast.FunctionDef | ast.AsyncFunctionDef,
                        name: str, default: str) -> str:
    """The new ``(...)`` interior with ``name=default`` inserted at the safe
    slot — every existing parameter's text is sliced verbatim from the
    source, so annotations and defaults keep their exact spelling."""
    a = fn.args
    parts: list[str] = []

    def pos_text(arg: ast.arg, dflt: ast.expr | None) -> str:
        text = _segment(source, arg)
        if dflt is not None:
            # PEP 8: spaces around "=" only when the parameter is annotated.
            eq = " = " if arg.annotation is not None else "="
            text += f"{eq}{_segment(source, dflt)}"
        return text

    positional = [*a.posonlyargs, *a.args]
    defaults: list[ast.expr | None] = (
        [None] * (len(positional) - len(a.defaults)) + list(a.defaults))
    for i, arg in enumerate(positional):
        parts.append(pos_text(arg, defaults[i]))
        if a.posonlyargs and i == len(a.posonlyargs) - 1:
            parts.append("/")

    if a.vararg:
        parts.append(f"*{_segment(source, a.vararg)}")
    elif a.kwonlyargs:
        parts.append("*")
    for arg, dflt in zip(a.kwonlyargs, a.kw_defaults):
        parts.append(pos_text(arg, dflt))
    # After *args / the keyword-only section the new param is keyword-only —
    # a trailing positional default there would absorb positional arguments.
    parts.append(f"{name}={default}")
    if a.kwarg:
        parts.append(f"**{_segment(source, a.kwarg)}")
    return ", ".join(parts)


def _check_inputs(plan: RenamePlan, param: str, default: str) -> bool:
    """True iff the new name is a fresh identifier and the default parses —
    appends the matching blocker and returns False otherwise."""
    if not param.isidentifier() or _kw.iskeyword(param):
        plan.blockers.append(f"'{param}' is not a valid identifier")
        return False
    try:
        ast.parse(default, mode="eval")
    except (SyntaxError, RecursionError, MemoryError):
        plan.blockers.append(f"default {default!r} is not a valid expression")
        return False
    return True


def _parse_project(root: Path) -> tuple[dict[str, str], dict[str, ast.Module]]:
    """Read every ``.py`` file once: its text and (when parseable) its tree."""
    files = _py_files(root)
    sources = dict(files)
    trees = _parse_trees(files)
    return sources, trees


def _check_name_clash(plan: RenamePlan, fn: ast.FunctionDef
                      | ast.AsyncFunctionDef, func_name: str,
                      param: str) -> bool:
    """True iff ``param`` is genuinely new — not an existing parameter and not
    a name already resolved inside the body."""
    if param in [p.arg for p in _all_params(fn)]:
        plan.blockers.append(f"{func_name}() already has a parameter '{param}'")
        return False
    if any(isinstance(n, ast.Name) and n.id == param for n in ast.walk(fn)):
        plan.blockers.append(
            f"'{param}' is already used inside {func_name}() — adding the "
            "parameter would change what that name means")
        return False
    return True


def _signature_lines(plan: RenamePlan, source: str, defmod: str,
                     fn: ast.FunctionDef | ast.AsyncFunctionDef
                     ) -> tuple[tuple[int, int, int, int], list[str]] | None:
    """The signature span plus the source lines — blocks (returns None) when
    the span cannot be pinned or the signature block carries a comment."""
    return _pin_signature_lines(plan, source, defmod, _signature_span(source, fn))


def _from_import_names(node: ast.ImportFrom, dotted: str,
                       func_name: str) -> set[str]:
    """The local names bound by ``from dotted import func_name [as …]``."""
    if node.module != dotted:
        return set()
    return {alias.asname or func_name
            for alias in node.names if alias.name == func_name}


def _module_alias_names(node: ast.Import, dotted: str) -> set[str]:
    """The local aliases bound by ``import dotted [as …]``."""
    return {alias.asname or alias.name
            for alias in node.names if alias.name == dotted}


def _resolve_call_names(tree: ast.Module, dotted: str, func_name: str,
                        is_defmod: bool) -> tuple[set[str], set[str]]:
    """The bare names and module aliases under which ``func_name`` is reachable
    in one module — ``from dotted import func_name`` names and ``import dotted``
    aliases for ``alias.func_name(...)`` calls."""
    from_names: set[str] = {func_name} if is_defmod else set()
    module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            from_names |= _from_import_names(node, dotted, func_name)
        elif isinstance(node, ast.Import):
            module_aliases |= _module_alias_names(node, dotted)
    return from_names, module_aliases


def _calls_func(call: ast.Call, func_name: str, from_names: set[str],
                module_aliases: set[str]) -> bool:
    """True iff this call targets ``func_name`` — a bare name imported via
    ``from``, or ``alias.func_name`` on an imported-module alias."""
    f = call.func
    return (isinstance(f, ast.Name) and f.id in from_names) or (
        isinstance(f, ast.Attribute) and f.attr == func_name
        and ast.unparse(f.value) in module_aliases)


def _inspect_call_keywords(plan: RenamePlan, rel: str, call: ast.Call,
                           func_name: str, param: str) -> None:
    """A call already passing ``param=`` blocks; an ``f(**…)`` site warns."""
    for kw in call.keywords:
        if kw.arg == param:
            plan.blockers.append(
                f"{rel}:{call.lineno}: a call already passes "
                f"'{param}=' — adding the parameter would rewire it")
        elif kw.arg is None:
            plan.warnings.append(
                f"{rel}:{call.lineno}: {func_name}(**…) may already "
                f"carry '{param}' at runtime; check manually")


def _scan_call_sites(plan: RenamePlan, trees: dict[str, ast.Module],
                     defmod: str, dotted: str, func_name: str,
                     param: str) -> None:
    """Walk every call of ``func_name``: a site already passing ``param=``
    blocks, an ``f(**…)`` site warns."""
    for rel, tree in trees.items():
        from_names, module_aliases = _resolve_call_names(
            tree, dotted, func_name, rel == defmod)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and _calls_func(node, func_name, from_names, module_aliases)):
                _inspect_call_keywords(plan, rel, node, func_name, param)


def plan_param_add(project_root: str | Path, func_name: str,
                   param: str, default: str) -> RenamePlan:
    """Build the project-wide plan that ADDS ``param=default`` to func_name."""
    plan = RenamePlan(old="", new=param)
    if not _check_inputs(plan, param, default):
        return plan

    sources, trees = _parse_project(Path(project_root))
    definition = _sole_definition(plan, trees, func_name)
    if definition is None:
        return plan
    defmod, fn = definition
    plan.defined_in = defmod
    dotted = defmod[:-3].replace("/", ".")
    source = sources[defmod]

    if not _check_name_clash(plan, fn, func_name, param):
        return plan

    lines = _signature_lines(plan, source, defmod, fn)
    if lines is None:
        return plan
    (sl, sc, el, ec), src_lines = lines

    # Call sites: one already passing the keyword means the addition would
    # rewire it (into **kwargs before, into the new param after) — blocked.
    _scan_call_sites(plan, trees, defmod, dotted, func_name, param)
    if plan.blockers:
        return plan

    new_sig = f"({_rebuild_with_param(source, fn, param, default)})"
    new_def = src_lines[sl - 1][:sc] + new_sig + src_lines[el - 1][ec:]
    plan.originals[defmod] = source
    plan.new_contents[defmod] = "".join([*src_lines[:sl - 1], new_def, *src_lines[el:]])
    plan.edits_by_file[defmod] = 1
    return plan
