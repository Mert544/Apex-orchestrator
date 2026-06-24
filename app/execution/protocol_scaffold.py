"""Scaffold a concrete implementer for a ``typing.Protocol``.

The boilerplate every student and team writes by hand: a project declares a
``Protocol`` — the shared interface a function depends on — but no concrete class
that satisfies it exists yet, so ``from pkg import P; PImpl()`` is impossible and
the interface is shelf-ware. ``scaffold-from-protocol`` LANDS that missing
implementer: a NEW file ``<pkgdir>/<stem>_impl.py`` holding ``class PImpl(P):``
with one ``...``-bodied override per FILLABLE member (the abstract / unimplemented
ones), decorators preserved (``@property`` / ``@classmethod`` / ``@staticmethod``,
with ``@abstractmethod`` dropped), parameter and return annotations STRIPPED so the
override never raises ``NameError`` on an unimported name. It is the runnable
skeleton a person then fills in — created for free, deterministically, no LLM.

The pure analysis (AST detect + render) lives here; the objective module
:mod:`app.execution.objectives.scaffold_from_protocol` names it as a develop
objective and registers it. Two gates keep it never-fake-green, mirrored on
:mod:`app.execution.import_oracle` (``wire-exports``):

  1. an INSTANTIATION ORACLE (:func:`scaffold_instantiates`) — the candidate file
     is written to a throwaway copy, the package imported in a CLEAN subprocess,
     and ``PImpl()`` constructed. If ANY abstract member was missed, Python raises
     ``TypeError: Can't instantiate abstract class`` and the oracle refuses —
     so a partial scaffold is never landed (the empirical refusal signal);
  2. ``apply_rename``'s full-suite gate + byte-for-byte rollback (a CREATED file is
     deleted on rollback via ``originals[rel] == ""``) compose on top.

It REFUSES (an honest under-claim, lands nothing) when: the class is not a
Protocol; it is a MARKER protocol (zero fillable members — nothing to scaffold);
a concrete implementer already exists (an explicit ``class C(P)`` subclass in the
project, or ``PImpl`` already present — the "no implementer" check is deliberately
CONSERVATIVE: only an explicit subclass counts, so a duck-typed implementer leads
to a benign additive over-offer, never a fake-green); the Protocol base is
alias-imported (a conservative miss); the target is a test/fixture file; or the
source is unreadable / unparseable.

Deterministic (members in SOURCE order, pure AST → text, no clock/random),
stdlib-only, zero-token, idempotent (once ``<stem>_impl.py`` exists with the
explicit subclass, a second run sees the implementer and is a byte-identical
no-op).
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

__all__ = [
    "protocol_scaffolds",
    "render_protocol_impl",
    "scaffold_instantiates",
]


# --- detection ---------------------------------------------------------------

def _base_names_protocol(base: ast.expr) -> bool:
    """True when a class base expression names ``Protocol`` directly: a bare
    ``Protocol`` (:class:`ast.Name`), a ``typing.Protocol`` attribute access, or a
    parameterised ``Protocol[T]`` (:class:`ast.Subscript`). An alias-imported
    Protocol (``from typing import Protocol as P``) is deliberately NOT matched —
    a conservative miss, never a wrong scaffold."""
    if isinstance(base, ast.Subscript):
        base = base.value
    if isinstance(base, ast.Name):
        return base.id == "Protocol"
    if isinstance(base, ast.Attribute):
        return base.attr == "Protocol"
    return False


def _is_protocol_class(node: ast.ClassDef) -> bool:
    """True when any base of ``node`` names ``Protocol`` (scanning every base)."""
    return any(_base_names_protocol(base) for base in node.bases)


def _is_fillable_member(node: ast.stmt) -> bool:
    """True when ``node`` is a method an implementer must override: a function whose
    body is unimplemented (``...`` / ``pass`` / docstring-only / docstring + ``...``
    / ``raise NotImplementedError``) OR which carries ``@abstractmethod``. A method
    with a real concrete default body is NOT fillable — overriding it would clobber
    behaviour, so it is left alone."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    if any(_decorator_name(d) == "abstractmethod" for d in node.decorator_list):
        return True
    return _body_is_unimplemented(node.body)


def _body_is_unimplemented(body: list[ast.stmt]) -> bool:
    """True when ``body`` carries no real statement: only ``...`` / ``pass`` /
    docstring / ``raise NotImplementedError`` (in any combination)."""
    return all(_stmt_is_placeholder(stmt) for stmt in body)


def _stmt_is_placeholder(stmt: ast.stmt) -> bool:
    """True for a single non-substantive statement: ``pass``, a ``...`` expression,
    a string-literal docstring expression, or ``raise NotImplementedError``."""
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return stmt.value.value is ... or isinstance(stmt.value.value, str)
    if isinstance(stmt, ast.Raise):
        return _raises_not_implemented(stmt)
    return False


def _raises_not_implemented(stmt: ast.Raise) -> bool:
    """True for ``raise NotImplementedError`` / ``raise NotImplementedError(...)``."""
    exc = stmt.exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id == "NotImplementedError"


def _decorator_name(dec: ast.expr) -> str:
    """The trailing identifier of a decorator expression (``property``,
    ``abstractmethod``, ``classmethod``, ...); ``""`` for a shape we don't name."""
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    if isinstance(dec, ast.Call):
        return _decorator_name(dec.func)
    return ""


def _fillable_members(node: ast.ClassDef) -> list[ast.FunctionDef]:
    """Every fillable method of ``node`` in SOURCE order (deterministic)."""
    return [m for m in node.body if _is_fillable_member(m)]


def _has_explicit_subclass(tree: ast.AST, protocol: str) -> bool:
    """True when the project source ``tree`` already declares an explicit
    ``class C(<protocol>)`` (a real, named implementer). Conservative on purpose:
    only an explicit base-name subclass counts — a duck-typed implementer is not
    detected, so the scaffold may additively over-offer but never fakes green."""
    for sub in ast.walk(tree):
        if isinstance(sub, ast.ClassDef):
            for base in sub.bases:
                b = base.value if isinstance(base, ast.Subscript) else base
                if isinstance(b, ast.Name) and b.id == protocol:
                    return True
    return False


def _implementer_exists(root: Path, module_rel: str, protocol: str,
                        impl_name: str) -> bool:
    """True when a concrete implementer for ``protocol`` already exists anywhere in
    the project: an explicit ``class C(protocol)`` subclass in any own module, or a
    class literally named ``impl_name`` (the scaffold's own output — idempotency).
    Unreadable/unparseable modules are skipped (best-effort, deterministic)."""
    from app.engine.objective_compiler import _own_modules

    for _rel, src in _own_modules(root):
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        if _has_explicit_subclass(tree, protocol):
            return True
        if any(isinstance(n, ast.ClassDef) and n.name == impl_name
               for n in ast.walk(tree)):
            return True
    return False


def protocol_scaffolds(root: Path, module_rel: str,
                       source: str) -> list[tuple[str, list[ast.FunctionDef]]]:
    """Every ``(protocol_name, fillable_members)`` in ``source`` that
    ``scaffold-from-protocol`` would offer to implement: a top-level Protocol
    subclass with >=1 fillable member and NO existing concrete implementer in the
    project. Source-ordered and deterministic; ``[]`` on a syntax error or when
    nothing qualifies."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    out: list[tuple[str, list[ast.FunctionDef]]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not _is_protocol_class(node):
            continue
        members = _fillable_members(node)
        if not members:
            continue  # marker protocol — nothing to scaffold
        if _implementer_exists(root, module_rel, node.name, f"{node.name}Impl"):
            continue  # already implemented — honest no-op
        out.append((node.name, members))
    return out


# --- rendering ---------------------------------------------------------------

def _kept_decorators(member: ast.FunctionDef) -> list[str]:
    """The decorator source lines to PRESERVE on an override, in order, with
    ``abstractmethod`` dropped (the override is concrete) — every other decorator
    (``property`` / ``classmethod`` / ``staticmethod`` / ...) is kept verbatim so
    the override matches the member's kind."""
    out: list[str] = []
    for dec in member.decorator_list:
        if _decorator_name(dec) == "abstractmethod":
            continue
        out.append("@" + ast.unparse(dec))
    return out


def _stripped_arguments(member: ast.FunctionDef) -> str:
    """The member's parameter list with ALL annotations + defaults stripped, ready
    to drop into ``def name(<here>): ...``. Annotations are removed so the override
    never references an unimported name (a ``NameError`` at class-creation). If the
    arguments cannot be cleanly unparsed, the caller falls back to
    ``self, *args, **kwargs``."""
    bare = ast.arguments(
        posonlyargs=[ast.arg(arg=a.arg) for a in member.args.posonlyargs],
        args=[ast.arg(arg=a.arg) for a in member.args.args],
        vararg=ast.arg(arg=member.args.vararg.arg) if member.args.vararg else None,
        kwonlyargs=[ast.arg(arg=a.arg) for a in member.args.kwonlyargs],
        kw_defaults=[None] * len(member.args.kwonlyargs),
        kwarg=ast.arg(arg=member.args.kwarg.arg) if member.args.kwarg else None,
        defaults=[],
    )
    return ast.unparse(bare)


def _override_params(member: ast.FunctionDef) -> str:
    """The override's parameter source: the member's params with annotations and
    defaults stripped, or the ``self, *args, **kwargs`` fallback if they will not
    cleanly unparse (the conservative path the spec mandates)."""
    try:
        params = _stripped_arguments(member)
        ast.parse(f"def _p({params}): ...")  # the override must parse
    except (ValueError, SyntaxError, RecursionError, AttributeError):
        return "self, *args, **kwargs"
    return params or "self, *args, **kwargs"


def _render_override(member: ast.FunctionDef) -> list[str]:
    """The source lines for one ``...``-bodied override of ``member``: its kept
    decorators (``abstractmethod`` dropped), the ``def``/``async def`` header with
    stripped params, and a ``...`` body — indented one class level."""
    lines = ["    " + dec for dec in _kept_decorators(member)]
    kw = "async def" if isinstance(member, ast.AsyncFunctionDef) else "def"
    lines.append(f"    {kw} {member.name}({_override_params(member)}): ...")
    return lines


def render_protocol_impl(dotted: str, protocol: str,
                         members: list[ast.FunctionDef]) -> str:
    """Render ``<pkgdir>/<stem>_impl.py``: ``from <dotted> import <protocol>`` then
    ``class <protocol>Impl(<protocol>):`` with one ``...``-bodied override per
    fillable ``member`` (decorators preserved, annotations stripped), in the given
    SOURCE order. Deterministic; no clock/random. The body is never empty —
    ``members`` is guaranteed non-empty by the caller."""
    lines = [
        '"""Auto-generated by Apex scaffold-from-protocol: a concrete skeleton',
        f"implementing the {protocol} protocol from {dotted}.",
        "",
        "Apex generated this runnable stub so the project's Protocol has a concrete",
        f"implementer to fill in. Each {protocol} member is redeclared with a ``...``",
        "body and its decorator kind preserved; fill in the bodies.",
        '"""',
        "",
        f"from {dotted} import {protocol}",
        "",
        "",
        f"class {protocol}Impl({protocol}):",
    ]
    for member in members:
        lines += _render_override(member)
    return "\n".join(lines) + "\n"


# --- the instantiation oracle ------------------------------------------------
#
# A tiny, fixed probe: write nothing (the candidate is already in place), import
# the impl module in a CLEAN subprocess, and CONSTRUCT ``<protocol>Impl()``. If a
# fillable member was missed, Python raises ``TypeError: Can't instantiate
# abstract class`` and the probe reports failure — the empirical refusal signal.
# Read via argv: project root, dotted impl module, the impl class name.
_PROBE = r"""
import importlib, json, sys
root, dotted, cls_name = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
try:
    mod = importlib.import_module(dotted)
    getattr(mod, cls_name)()
except BaseException as exc:  # noqa: BLE001 - any failure means refuse
    print(json.dumps({"ok": False, "error": repr(exc)}))
    sys.exit(0)
print(json.dumps({"ok": True}))
"""


def scaffold_instantiates(project_root: str | Path, impl_rel: str,
                          candidate_source: str, dotted: str,
                          impl_name: str) -> bool:
    """True iff writing ``candidate_source`` as ``impl_rel`` lets a clean subprocess
    import it and CONSTRUCT ``impl_name()`` with no exception.

    Writes the candidate, imports the impl module under ``dotted`` in a fresh
    interpreter (project root on ``sys.path``, bytecode off), instantiates the
    class, and restores the prior on-disk state afterwards (whether the import
    succeeded, failed, or raised) — side-effect-free, it never lands the candidate
    itself; the apply layer does, gated by this. Returns ``False`` on any
    subprocess error, import failure, or a ``TypeError`` from a still-abstract
    class — the caller refuses (never a partial scaffold)."""
    root = Path(project_root)
    impl_path = root / impl_rel
    try:
        original = impl_path.read_text(encoding="utf-8")
        had_file = True
    except OSError:
        original, had_file = "", impl_path.exists()
    try:
        impl_path.parent.mkdir(parents=True, exist_ok=True)
        impl_path.write_text(candidate_source, encoding="utf-8")
        return _run_probe(root, dotted, impl_name)
    finally:
        if had_file:
            impl_path.write_text(original, encoding="utf-8")
        else:
            try:
                impl_path.unlink()
            except OSError:
                pass


def _run_probe(root: Path, dotted: str, impl_name: str) -> bool:
    """Run the instantiation probe in a clean subprocess; True iff it constructed
    ``impl_name()`` without raising."""
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE, str(root), dotted, impl_name],
            cwd=str(root), capture_output=True, text=True, env=env, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False
    return bool(result.get("ok"))
