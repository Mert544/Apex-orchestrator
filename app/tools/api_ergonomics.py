"""API-ergonomics smells in the project's OWN functions.

Where the complexity/risk analyzers ask "is this function hard to *implement*
well?", this asks "is this function painful to *call*?" — the friction lives at
the call site, not inside the body. It is a deterministic, AST-only sweep that
flags three signatures-level smells:

  - **LONG PARAMETER LIST** — more than ``max_params`` (default 5) caller-supplied
    parameters (``self``/``cls`` and ``*args``/``**kwargs`` excluded). Long
    parameter lists are the classic "this wants to be an object / config" tell:
    callers must remember an order, and every new arg ripples through call sites.

  - **BOOLEAN TRAP** — two or more boolean parameters (annotated ``bool`` and/or
    defaulting to a bool literal). Multiple booleans turn call sites into
    ``f(True, False, True)`` riddles that read nothing like intent; the cure is
    usually keyword-only flags or an enum. (A single boolean is common and not
    flagged — the trap is *ambiguity between* several.)

  - **POSITIONAL OVERLOAD** — more than ``max_params`` parameters that a caller
    can (or must) pass positionally, with NO keyword-only marker (``*``) at all.
    A long *purely positional* signature forces positional call sites; a single
    ``*`` would let callers name the tail. This complements the long-list smell:
    a function may have a reasonable count yet still be all-positional, or be
    long yet already protect its tail with keyword-only args.

Rules / conservatism (to keep false positives near zero):

  - **Dunders are excluded.** ``__init__``, ``__call__`` etc. have fixed,
    framework-dictated shapes and aren't ergonomics targets.
  - ``self``/``cls`` (the first positional of a method/classmethod, by name) do
    NOT count toward any threshold.
  - ``*args``/``**kwargs`` are never counted as parameters; a function that is
    *only* ``*args``/``**kwargs`` is never flagged (its arity is unbounded by
    design, not a fixed long list).
  - Keyword-only parameters (after ``*``) DO count toward the long-list and
    boolean-trap totals (they're still parameters a caller juggles) but a present
    ``*`` marker exempts the function from the positional-overload smell.
  - Both ``def`` and ``async def`` are analyzed; nested/local functions and
    methods are all in scope (methods qualified as ``Class.method``).

Public entry point: :func:`analyze_api_ergonomics`. Returns an
:class:`ApiErgonomics` with smell counts and a deterministically sorted,
capped list of offender dicts. Empty trees / unparseable files are safe (skipped,
never raised). Pure: no clock, no randomness, no network — same tree in, same
report out.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engine.skip_dirs import iter_source_files

__all__ = ["ApiErgonomics", "analyze_api_ergonomics"]

# How many offenders to surface (the rest are summarized by the counts only).
_OFFENDER_CAP = 15

# First-positional names that are the implicit receiver, not a caller parameter.
_RECEIVER_NAMES = frozenset({"self", "cls"})


@dataclass
class ApiErgonomics:
    """Aggregate API-ergonomics report over a project tree.

    ``files_analyzed`` / ``functions_analyzed`` give the denominator; the three
    ``*_count`` fields tally each smell across ALL functions (not just the
    surfaced ones); ``offenders`` is the capped, sorted detail list where each
    entry is ``{module, function, params, bool_params, reason}``.
    """

    files_analyzed: int = 0
    functions_analyzed: int = 0
    long_param_count: int = 0
    boolean_trap_count: int = 0
    positional_overload_count: int = 0
    offenders: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_analyzed": self.files_analyzed,
            "functions_analyzed": self.functions_analyzed,
            "long_param_count": self.long_param_count,
            "boolean_trap_count": self.boolean_trap_count,
            "positional_overload_count": self.positional_overload_count,
            "offenders": [dict(o) for o in self.offenders],
        }


def _is_dunder(name: str) -> bool:
    """True for ``__name__``-style dunders (fixed, framework shapes — skipped)."""
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _is_bool_arg(arg: ast.arg, default: ast.expr | None) -> bool:
    """A parameter is "boolean" if annotated ``bool`` or defaulting to a bool
    literal — the two AST-visible tells that a flag is being passed."""
    annotation = arg.annotation
    if isinstance(annotation, ast.Name) and annotation.id == "bool":
        return True
    # `typing.Optional[bool]` / `bool | None` aren't counted: those usually carry
    # a third "unset" meaning and read less like a raw on/off flag.
    if isinstance(default, ast.Constant) and isinstance(default.value, bool):
        return True
    return False


def _analyze_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    qualified: str,
    is_method: bool,
    max_params: int,
) -> tuple[dict[str, Any] | None, set[str]]:
    """Inspect one function node.

    Returns ``(offender_or_None, smells)`` where ``smells`` is the set of smell
    keys this function tripped (used for the aggregate counts even when the
    function isn't among the surfaced offenders).
    """
    args = node.args

    # Positional-or-keyword params, dropping the implicit receiver of a method.
    positional = list(args.posonlyargs) + list(args.args)
    if is_method and positional and positional[0].arg in _RECEIVER_NAMES:
        positional = positional[1:]

    keyword_only = list(args.kwonlyargs)
    counted = positional + keyword_only

    # A function that is *only* *args/**kwargs (no fixed params) has unbounded
    # arity by design — never a fixed long list, never flagged.
    if not counted:
        return None, set()

    # Align defaults with their parameters so bool-default detection is exact.
    # Positional defaults bind to the TAIL of the positional list; kw-only
    # defaults pair index-for-index with kwonlyargs.
    pos_defaults: list[ast.expr | None] = (
        [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    )
    if len(pos_defaults) < len(positional):  # defensive; shouldn't happen
        pos_defaults = [None] * len(positional)
    kw_defaults: list[ast.expr | None] = list(args.kw_defaults)
    if len(kw_defaults) < len(keyword_only):
        kw_defaults += [None] * (len(keyword_only) - len(kw_defaults))

    bool_params = sum(
        _is_bool_arg(a, d) for a, d in zip(positional, pos_defaults)
    ) + sum(
        _is_bool_arg(a, d) for a, d in zip(keyword_only, kw_defaults)
    )

    param_count = len(counted)
    # A `*` marker exists if there are kw-only args OR a bare/`*args` vararg.
    has_kw_only_marker = bool(keyword_only) or args.vararg is not None

    smells: set[str] = set()
    reasons: list[str] = []
    if param_count > max_params:
        smells.add("long_param")
        reasons.append(f"long parameter list ({param_count} > {max_params})")
    if bool_params >= 2:
        smells.add("boolean_trap")
        reasons.append(f"boolean trap ({bool_params} bool params)")
    if len(positional) > max_params and not has_kw_only_marker:
        smells.add("positional_overload")
        reasons.append(
            f"positional overload ({len(positional)} positional, no keyword-only marker)"
        )

    if not smells:
        return None, set()

    offender = {
        "module": "",  # filled in by the caller (has the path)
        "function": qualified,
        "params": param_count,
        "bool_params": bool_params,
        "reason": "; ".join(reasons),
    }
    return offender, smells


def _module_name(path: Path, root: Path) -> str:
    """Project-relative dotted module name, e.g. ``app/tools/x.py`` -> ``app.tools.x``."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    parts = rel.with_suffix("").parts
    return ".".join(parts)


def _walk_functions(tree: ast.Module):
    """Yield ``(node, qualified_name, is_method)`` for every function in the tree.

    Methods are qualified ``Class.method`` and flagged ``is_method=True`` so their
    receiver is dropped; nested defs extend the dotted chain.
    """

    def visit(body: list[ast.stmt], prefix: str, in_class: bool):
        for child in body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = f"{prefix}{child.name}"
                yield child, qualified, in_class
                # Nested functions are not methods of the enclosing class.
                yield from visit(child.body, f"{qualified}.", False)
            elif isinstance(child, ast.ClassDef):
                yield from visit(child.body, f"{prefix}{child.name}.", True)

    yield from visit(tree.body, "", False)


def analyze_api_ergonomics(
    root: str | Path,
    max_files: int = 500,
    max_params: int = 5,
) -> ApiErgonomics:
    """Scan ``root`` for API-ergonomics smells in its own Python functions.

    Walks every non-excluded ``*.py`` under ``root`` (capped at ``max_files``,
    deterministically ordered via :func:`iter_source_files`), parses each with
    ``ast``, and applies the three rules documented at module level. Unreadable or
    unparseable files are skipped silently. Offenders are sorted deterministically
    — most parameters first, then most bool params, then by ``(module, function)``
    — and capped at ~15; the ``*_count`` fields still reflect every offender.

    ``max_params`` is the inclusive ceiling: a function trips the long-list /
    positional-overload rules only when it has *strictly more* than ``max_params``
    counted / positional parameters. Pure and deterministic.
    """
    root = Path(root)
    report = ApiErgonomics()

    files = iter_source_files(root)
    if max_files and max_files > 0:
        files = files[:max_files]

    offenders: list[dict[str, Any]] = []
    for path in files:
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError):
            continue
        report.files_analyzed += 1
        module = _module_name(path, root)

        for node, qualified, is_method in _walk_functions(tree):
            report.functions_analyzed += 1
            if _is_dunder(node.name):
                continue
            offender, smells = _analyze_function(node, qualified, is_method, max_params)
            if "long_param" in smells:
                report.long_param_count += 1
            if "boolean_trap" in smells:
                report.boolean_trap_count += 1
            if "positional_overload" in smells:
                report.positional_overload_count += 1
            if offender is not None:
                offender["module"] = module
                offenders.append(offender)

    # Deterministic ordering: worst (most params, then most bool params) first,
    # tie-broken by (module, function) so the cap is reproducible.
    offenders.sort(
        key=lambda o: (-o["params"], -o["bool_params"], o["module"], o["function"])
    )
    report.offenders = offenders[:_OFFENDER_CAP]
    return report
