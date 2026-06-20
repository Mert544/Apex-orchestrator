"""Usage-doc synthesis — restate a package's PUBLIC API as a ``USAGE.md``.

The pure, deterministic engine behind the ``generate-usage-doc`` develop
objective (:mod:`app.execution.objectives.generate_usage_doc`). It reads ONLY
what a package's own code already declares — its public top-level functions and
classes, their SIGNATURES, the FIRST LINE of each docstring, and any ``>>>``
doctest examples already written in those docstrings — and renders a ``USAGE.md``
that lists them. Nothing is invented: every word in the doc is copied from the
source (zero-token, no LLM). A package with no public API yields ``None`` (the
objective refuses — there is nothing honest to document).

Determinism is the whole point: modules are scanned in SORTED relative-path
order, symbols are emitted in SORTED name order, and a name defined by more than
one module is attributed to the FIRST module (sorted) — the same package renders
byte-for-byte the same ``USAGE.md`` every run. A package that already carries the
generated ``USAGE.md`` renders identical bytes (an idempotent no-op). When a
package declares ``__all__`` in its ``__init__.py``, that list is the public
surface (restricted to names actually defined in the package's modules);
otherwise every public top-level symbol across the modules is the surface.

This module never writes and never executes anything. The objective's plan layer
owns the apply (suite-gated, auto-rolled-back) and the DOCTEST ORACLE
(:mod:`app.execution.doctest_oracle`) that proves every ``>>>`` example copied
into the doc actually runs green against the package before the doc is allowed to
stand. Stdlib-only, no clock, no random.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import doctest
from pathlib import Path

from app.engine.skip_dirs import is_test_or_fixture_path

__all__ = [
    "SymbolDoc",
    "collect_public_api",
    "render_usage_markdown",
    "plan_usage_text",
    "python_code_blocks",
]


@dataclass
class SymbolDoc:
    """One public symbol's documented surface, all of it copied from the source.

    ``name`` is the symbol; ``kind`` is ``"function"`` or ``"class"``; ``module``
    is the dotted-relative module stem it is defined in; ``signature`` is the
    rendered ``(...)`` parameter list (with return annotation for a function);
    ``summary`` is the docstring's first non-empty line (``""`` when undocumented);
    ``examples`` are the ``>>>`` doctest source lines extracted verbatim from the
    docstring (``[]`` when there are none)."""

    name: str
    kind: str
    module: str
    signature: str
    summary: str = ""
    examples: list[str] = field(default_factory=list)


def _is_public(name: str) -> bool:
    """A name is public when it is non-empty and does not start with ``_``
    (single-underscore privates and dunders are both excluded)."""
    return bool(name) and not name.startswith("_")


def _render_annotation(node: ast.expr | None) -> str:
    """The source text of a type annotation, or ``""`` when there is none.
    ``ast.unparse`` is deterministic, so the rendered hint is stable."""
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except (ValueError, AttributeError):
        return ""


def _render_default(node: ast.expr) -> str:
    """The source text of a default value, or ``"..."`` when it cannot be
    rendered — a placeholder that still reads as a default in the signature."""
    try:
        return ast.unparse(node)
    except (ValueError, AttributeError):
        return "..."


def _one_param(name: str, annotation: ast.expr | None,
               default: ast.expr | None) -> str:
    """Render a single parameter as ``name[: Ann][= default]`` (PEP-8 spacing:
    ``= `` around a default only when an annotation is present)."""
    ann = _render_annotation(annotation)
    text = f"{name}: {ann}" if ann else name
    if default is not None:
        rendered = _render_default(default)
        text += f" = {rendered}" if ann else f"={rendered}"
    return text


def _positional_params(args: ast.arguments) -> list[str]:
    """Render the positional (incl. positional-only) parameters, inserting the
    ``/`` marker after the positional-only group. Defaults align to the tail."""
    posonly = list(args.posonlyargs)
    positional = posonly + list(args.args)
    defaults = list(args.defaults)
    offset = len(positional) - len(defaults)
    parts: list[str] = []
    for i, arg in enumerate(positional):
        default = defaults[i - offset] if i >= offset else None
        parts.append(_one_param(arg.arg, arg.annotation, default))
        if posonly and i == len(posonly) - 1:
            parts.append("/")
    return parts


def _keyword_params(args: ast.arguments) -> list[str]:
    """Render the ``*``/``*args`` separator and any keyword-only parameters."""
    parts: list[str] = []
    if args.vararg:
        ann = _render_annotation(args.vararg.annotation)
        parts.append(f"*{args.vararg.arg}" + (f": {ann}" if ann else ""))
    elif args.kwonlyargs:
        parts.append("*")
    for kwarg, kwdefault in zip(args.kwonlyargs, args.kw_defaults):
        parts.append(_one_param(kwarg.arg, kwarg.annotation, kwdefault))
    return parts


def _format_args(args: ast.arguments) -> list[str]:
    """Render a function/method ``arguments`` node as a list of parameter
    strings, preserving order, annotations, and defaults (``self``/``cls`` and
    ``*args``/``**kwargs`` included). Deterministic — pure ``ast.unparse``."""
    parts = _positional_params(args) + _keyword_params(args)
    if args.kwarg:
        ann = _render_annotation(args.kwarg.annotation)
        parts.append(f"**{args.kwarg.arg}" + (f": {ann}" if ann else ""))
    return parts


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """The rendered ``(params) -> Return`` signature for a function/method."""
    params = ", ".join(_format_args(node.args))
    returns = _render_annotation(node.returns)
    sig = f"({params})"
    if returns:
        sig += f" -> {returns}"
    return sig


def _summary_line(docstring: str | None) -> str:
    """The docstring's first non-empty line, stripped — the one-line summary.
    ``""`` when the symbol carries no docstring."""
    if not docstring:
        return ""
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _example_lines(example: doctest.Example) -> list[str]:
    """Reconstruct one parsed doctest example as ``>>>``-prompted lines plus its
    expected-output lines — the verbatim runnable form for both the rendered doc
    and the doctest oracle (which re-parses these prompts)."""
    src = example.source.rstrip("\n").splitlines() or [""]
    lines = [f">>> {src[0]}"]
    lines.extend(f"... {cont}" for cont in src[1:])
    if example.want:
        lines.extend(example.want.rstrip("\n").splitlines())
    return lines


def _doctest_examples(docstring: str | None) -> list[str]:
    """The ``>>>`` doctest examples in a docstring, extracted with
    :class:`doctest.DocTestParser` (the canonical reader) and reconstructed in
    prompted form (``>>> src`` + expected output), one example per string, in
    document order. Keeping the expected output is what lets the oracle re-run and
    PROVE each example. ``[]`` when there are none or the docstring is malformed."""
    if not docstring:
        return []
    try:
        parsed = doctest.DocTestParser().get_examples(docstring)
    except ValueError:
        return []
    return [
        "\n".join(_example_lines(ex)) for ex in parsed if ex.source.strip()
    ]


def _symbol_for_node(node: ast.stmt, module: str) -> SymbolDoc | None:
    """Build a :class:`SymbolDoc` for one top-level node, or ``None`` when the
    node is not a public function/class. Class methods are not descended into —
    the doc lists the class's own signature and summary (the public unit)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if not _is_public(node.name):
            return None
        doc = ast.get_docstring(node)
        return SymbolDoc(
            name=node.name, kind="function", module=module,
            signature=_function_signature(node),
            summary=_summary_line(doc), examples=_doctest_examples(doc),
        )
    if isinstance(node, ast.ClassDef):
        if not _is_public(node.name):
            return None
        doc = ast.get_docstring(node)
        return SymbolDoc(
            name=node.name, kind="class", module=module,
            signature=_class_signature(node),
            summary=_summary_line(doc), examples=_doctest_examples(doc),
        )
    return None


def _class_signature(node: ast.ClassDef) -> str:
    """A class's constructor signature, taken from its ``__init__`` if present,
    else ``()``. ``self`` is dropped — a caller never passes it."""
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and item.name == "__init__":
            sig = _function_signature(item)
            # Drop a leading `self` parameter: callers never pass it.
            inner = sig[1:].split(")", 1)
            head = inner[0]
            params = [p.strip() for p in head.split(",") if p.strip()]
            if params and params[0].split(":")[0].split("=")[0].strip() == "self":
                params = params[1:]
            return "(" + ", ".join(params) + ")"
    return "()"


def _module_stems(package_dir: Path) -> list[str]:
    """The package's own non-``__init__`` module STEMS, sorted (deterministic).
    Only direct ``*.py`` children — a sub-package documents itself."""
    stems = [
        p.stem for p in package_dir.glob("*.py")
        if p.name != "__init__.py" and _is_public(p.stem)
    ]
    return sorted(stems)


def _declared_all(init_source: str) -> set[str] | None:
    """The names in a literal top-level ``__all__`` of an ``__init__.py``, or
    ``None`` when none is declared — the public surface the author pinned."""
    try:
        tree = ast.parse(init_source)
    except (SyntaxError, RecursionError, MemoryError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ) and isinstance(node.value, (ast.List, ast.Tuple)):
            return {
                el.value for el in node.value.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            }
    return None


def collect_public_api(package_dir: str | Path, init_source: str) -> list[SymbolDoc]:
    """Collect the public API of one package directory as :class:`SymbolDoc`s.

    Scans each sibling module in SORTED order; the FIRST module (sorted) to define
    a name owns it, and the same name from a later module is dropped (an honest,
    deterministic under-claim — never two entries for one name). When the
    package's ``__init__.py`` declares ``__all__``, the surface is restricted to
    those names (intersected with what the modules actually define); otherwise
    every public top-level function/class is included. Returns the symbols sorted
    by name (deterministic emission order)."""
    pkg = Path(package_dir)
    allow = _declared_all(init_source)
    by_name: dict[str, SymbolDoc] = {}
    for stem in _module_stems(pkg):
        try:
            tree = ast.parse((pkg / f"{stem}.py").read_text(encoding="utf-8"))
        except (OSError, SyntaxError, RecursionError, MemoryError):
            continue
        for node in tree.body:
            sym = _symbol_for_node(node, stem)
            if sym is None or sym.name in by_name:
                continue
            if allow is not None and sym.name not in allow:
                continue
            by_name[sym.name] = sym
    return [by_name[name] for name in sorted(by_name)]


def python_code_blocks(markdown: str) -> list[str]:
    """Extract the bodies of ```` ```python ```` fenced blocks from markdown,
    in document order. The verification layer parses each block to prove the doc's
    code is valid Python; here we just split the fences (deterministic)."""
    blocks: list[str] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip() == "```python":
            body: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != "```":
                body.append(lines[i])
                i += 1
            blocks.append("\n".join(body))
        i += 1
    return blocks


def _render_symbol(sym: SymbolDoc, keep_examples: bool) -> list[str]:
    """Render one symbol's section: a header, its summary, and (when kept) a
    runnable ``python`` doctest block. ``keep_examples`` is the oracle's verdict
    for this symbol — examples that did not run green are omitted honestly."""
    lines = [f"### `{sym.name}{sym.signature}`", ""]
    lines.append(f"*{sym.kind} in `{sym.module}`*")
    lines.append("")
    if sym.summary:
        lines.append(sym.summary)
        lines.append("")
    if keep_examples and sym.examples:
        lines.append("```python")
        lines.extend(sym.examples)
        lines.append("```")
        lines.append("")
    return lines


def render_usage_markdown(
    package_name: str, symbols: list[SymbolDoc],
    verified_examples: set[str] | None = None,
) -> str | None:
    """Render a package's ``USAGE.md`` from its collected public symbols.

    ``verified_examples`` is the set of symbol NAMES whose doctest examples ran
    green against the package; a symbol not in the set has its examples omitted
    (``None`` means "trust every example", used only when no oracle is available).
    Returns ``None`` when ``symbols`` is empty — there is no public API to
    document, so the objective refuses rather than emit an empty doc. The output
    is fully sorted and clock-free, so it is byte-for-byte stable."""
    if not symbols:
        return None
    lines = [f"# `{package_name}` — Usage", ""]
    lines.append(
        "Public API of this package, generated from its source "
        "(signatures, docstring summaries, and runnable examples)."
    )
    lines.append("")
    for sym in symbols:
        keep = verified_examples is None or sym.name in verified_examples
        lines.extend(_render_symbol(sym, keep))
    return "\n".join(lines).rstrip("\n") + "\n"


def plan_usage_text(
    project_root: str | Path, init_rel: str,
    verified_examples: set[str] | None = None,
) -> tuple[str | None, list[SymbolDoc]]:
    """Compute the candidate ``USAGE.md`` text for the package owning ``init_rel``.

    Returns ``(usage_md, symbols)``. ``usage_md`` is ``None`` when the package is
    refused (not a package ``__init__``, a test/fixture package) or has NO public
    API (nothing honest to document). ``verified_examples`` (the doctest oracle's
    verdict) is forwarded to the renderer so unproven examples are omitted."""
    root = Path(project_root)
    rel = Path(init_rel)
    if rel.name != "__init__.py" or is_test_or_fixture_path(rel.parent):
        return None, []
    package_dir = root / rel.parent
    try:
        existing_init = (root / rel).read_text(encoding="utf-8")
    except OSError:
        existing_init = ""
    symbols = collect_public_api(package_dir, existing_init)
    usage = render_usage_markdown(package_dir.name, symbols, verified_examples)
    return usage, symbols
