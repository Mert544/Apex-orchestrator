"""Return-consistency analyzer — flag functions that mix value returns with None.

A deterministic, stdlib-only AST analyzer that hunts a classic bug-prone smell:
a function in which *some* paths ``return <value>`` while *others* yield ``None``
— either via a bare ``return`` statement or via implicit fall-through off the end
of the body. Such a function silently hands back ``None`` on the forgotten path,
and a caller that always expects a value breaks far from the cause. We surface
these so a brief can point at the exact line.

Detection rule (applied in :func:`_classify_function`): a function is an
offender iff it has at least one ``return <expr>`` (a value-bearing return) AND
at least one of:

  - a **bare** ``return`` (or ``return None``) statement anywhere in its body,
    reachable on some path — reason ``"bare-return"``; OR
  - a reachable **implicit fall-through**: control can run off the end of the
    function body without hitting a ``return``/``raise``, so that path returns
    ``None`` — reason ``"implicit-fall-through"``.

Fall-through is judged structurally with a conservative "does this block
definitely exit?" check (see :func:`_block_always_exits`): a block exits if its
last statement is a value/bare ``return``, a ``raise``, or an ``if`` whose every
branch (including a present ``else``) exits, or a ``with``/``try`` whose relevant
body exits. Loops, ``match``, and ``else``-less ``if`` are treated as possibly
falling through — we never claim "always exits" unless we can prove it, so we err
toward NOT flagging on the fall-through path (bare returns are still caught).

Exclusions (conservative — we only flag a real, value-returning function):

  - **Generators**: any function containing ``yield`` / ``yield from`` returns a
    generator, where a bare ``return`` is normal control flow, not a None value.
  - **Dunders**: ``__init__``, ``__repr__``, … are protocol methods whose return
    contract is fixed; excluded by name (``__x__``).
  - **Consistently None-returning** functions: those with no value-bearing
    return at all never trip the rule (the "at least one ``return <expr>``"
    premise fails), so a pure side-effect function is never flagged.
  - **Tests / fixtures**: files under a ``tests``/``fixtures`` directory or named
    ``test_*.py`` / ``*_test.py`` / ``conftest.py`` are not shipped surface.

Directory-name skips (``.git``, ``.claude`` worktrees, …) come from the
canonical :func:`app.engine.skip_dirs.iter_source_files`. Deterministic: same
tree → same offenders, same order. No clock, randomness, or network. Unreadable
or unparseable files are silently skipped (they contribute nothing).
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.engine.skip_dirs import iter_source_files

__all__ = ["ReturnConsistency", "analyze_return_consistency"]

# How many offenders to surface in the report.
_OFFENDER_CAP = 15


@dataclass
class ReturnConsistency:
    """Project-level return-consistency report.

    ``offenders`` lists functions that mix value returns with None paths, each a
    dict of ``{module, function, line, reason}`` where ``reason`` is one of
    ``"bare-return"`` or ``"implicit-fall-through"``. The list is sorted by a
    total order (module, then line, then function) and capped at ~15.
    ``offender_count`` is the total number found before the cap.
    """

    offenders: list[dict[str, Any]] = field(default_factory=list)
    offender_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_test_or_fixture(rel: Path) -> bool:
    """True if a project-relative path is test/fixture code (not shipped surface).

    Pure name/component check, so it is deterministic. Covers ``tests`` /
    ``fixtures`` directories anywhere in the path, plus ``test_*.py`` /
    ``*_test.py`` / ``conftest.py`` filenames."""
    parts_lower = {part.lower() for part in rel.parts[:-1]}
    if "tests" in parts_lower or "fixtures" in parts_lower:
        return True
    stem = rel.stem.lower()
    name = rel.name.lower()
    return name == "conftest.py" or stem.startswith("test_") or stem.endswith("_test")


def _is_dunder(name: str) -> bool:
    """True for ``__x__`` protocol methods, whose return contract is fixed."""
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _own_returns(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Return]:
    """Every ``return`` belonging to ``fn`` itself — NOT those inside a nested
    ``def``/``lambda``, which are other functions' statements. We walk children
    but stop descending at a nested function boundary."""
    out: list[ast.Return] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Return):
                out.append(child)
            visit(child)

    visit(fn)
    return out


def _is_generator(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if ``fn`` contains a ``yield`` / ``yield from`` of its own (a
    nested generator def does not make the outer function a generator)."""

    found = False

    def visit(node: ast.AST) -> None:
        nonlocal found
        for child in ast.iter_child_nodes(node):
            if found:
                return
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, (ast.Yield, ast.YieldFrom)):
                found = True
                return
            visit(child)

    visit(fn)
    return found


def _is_bare_return(node: ast.Return) -> bool:
    """A bare ``return`` (no value) or an explicit ``return None`` — both hand
    back ``None`` and so count as a None-returning path."""
    if node.value is None:
        return True
    return isinstance(node.value, ast.Constant) and node.value.value is None


def _block_always_exits(body: list[ast.stmt]) -> bool:
    """Conservatively decide whether a statement block ALWAYS exits its function
    (so control cannot fall through off its end).

    Returns True only when we can prove it: the final statement is a ``return``
    or ``raise``; or an ``if`` whose body AND a present ``else`` both always
    exit; or a ``with`` whose body exits; or a ``try`` that exits via its
    ``finally`` or via all of {body-or-each-handler} plus ``else``. Anything we
    cannot prove (loops, ``match``, ``else``-less ``if``, empty block) is treated
    as possibly falling through — biasing toward NOT flagging."""
    if not body:
        return False
    last = body[-1]
    if isinstance(last, ast.Return):
        return True
    if isinstance(last, ast.Raise):
        return True
    if isinstance(last, ast.If):
        return bool(last.orelse) and _block_always_exits(last.body) and _block_always_exits(
            last.orelse
        )
    if isinstance(last, (ast.With, ast.AsyncWith)):
        return _block_always_exits(last.body)
    if isinstance(last, ast.Try):
        if last.finalbody and _block_always_exits(last.finalbody):
            return True
        # Otherwise every normal-completion path must exit: the try body (then
        # its else, if any) and every except handler.
        main = last.orelse if last.orelse else last.body
        if not _block_always_exits(main):
            return False
        return all(_block_always_exits(h.body) for h in last.handlers)
    return False


def _classify_function(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    """Return the offense reason for ``fn`` or ``None`` if it is consistent/excluded.

    Applies the documented rule: excludes generators and dunders, requires at
    least one value-bearing return, then reports ``"bare-return"`` if any bare /
    ``return None`` exists, else ``"implicit-fall-through"`` if control can run
    off the end of the body. A function whose body always exits via value
    returns is consistent and yields ``None``."""
    if _is_dunder(fn.name) or _is_generator(fn):
        return None

    returns = _own_returns(fn)
    has_value_return = any(not _is_bare_return(r) for r in returns)
    if not has_value_return:
        # No value-bearing return: consistently None-returning — never flagged.
        return None

    if any(_is_bare_return(r) for r in returns):
        return "bare-return"

    if not _block_always_exits(fn.body):
        return "implicit-fall-through"

    return None


def _iter_functions(tree: ast.Module):
    """Yield every function/method node in a module, including nested defs.

    Nested functions are real definitions with their own return contract, so
    they are classified too."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _module_offenders(source: str, module: str) -> list[dict[str, Any]]:
    """Offender dicts for one module's source. Unparseable source yields ``[]``."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    offenders: list[dict[str, Any]] = []
    for fn in _iter_functions(tree):
        reason = _classify_function(fn)
        if reason is not None:
            offenders.append(
                {
                    "module": module,
                    "function": fn.name,
                    "line": fn.lineno,
                    "reason": reason,
                }
            )
    return offenders


def analyze_return_consistency(
    root: str | Path, max_files: int = 500
) -> ReturnConsistency:
    """Scan a project's first-party Python under ``root`` for return-inconsistency.

    Walks at most ``max_files`` non-test, non-fixture ``*.py`` files (after the
    canonical directory skips) and collects functions that mix value returns
    with None paths (see the module docstring for the exact rule and
    exclusions). Empty or degenerate projects return safe empty defaults.

    Deterministic: ``iter_source_files`` yields a sorted, filtered list, the
    ``max_files`` cap is applied after filtering, and offenders are sorted by a
    total order (module, line, function) before the ~15-item cap.
    """
    root = Path(root)
    if not root.exists():
        return ReturnConsistency()

    all_offenders: list[dict[str, Any]] = []
    scanned = 0

    for path in iter_source_files(root):
        if scanned >= max_files:
            break
        rel = path.relative_to(root)
        if _is_test_or_fixture(rel):
            continue
        scanned += 1
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        all_offenders.extend(_module_offenders(source, str(rel)))

    all_offenders.sort(key=lambda o: (o["module"], o["line"], o["function"]))

    return ReturnConsistency(
        offenders=all_offenders[:_OFFENDER_CAP],
        offender_count=len(all_offenders),
    )
