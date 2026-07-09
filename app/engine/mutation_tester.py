"""Mutation testing — a deterministic *test-strength* fitness signal.

This is a multi-oracle "definition-of-done" measure: instead of asking whether
the code passes its tests, it asks whether the *tests* would notice if the code
broke. We seed tiny artificial faults ("mutants") into one target module — flip
a ``==`` to ``!=``, a ``+`` to ``-``, ``and`` to ``or``, ``True`` to ``False``,
a number ``n`` to ``n + 1``, a ``return <expr>`` to ``return None``, a
``+=`` to ``-=``, a membership ``in`` to ``not in``, or a relational boundary
``<`` to ``<=`` (off-by-one) — then run the project's
existing test suite against each
mutant in an isolated
copy of the tree. A mutant the suite FAILS on is *killed* (the tests caught the
bug); a mutant the suite still PASSES on *survived* (the tests are blind there).
The mutation **score** = killed / total is a deterministic lower bound on suite
strength, and the surviving mutants point at exactly *where* the tests are weak.

Determinism: there is no randomness anywhere. Operators are tried in a fixed
order and mutation sites are enumerated in document order (line, col), so the
same project always yields the same ``MutationResult``.

Caveat (theoretical): *equivalent mutants* — mutations that change the source
but not its behaviour, hence unkillable by any test — cannot be detected in
general (the problem is undecidable). They inflate the survivor count, so the
reported score is an APPROXIMATE LOWER BOUND on the true suite strength.

Safety: the real project tree is read-only throughout. Each mutant is verified
in a fresh ``shutil.copytree`` of the project (excluding VCS / cache / venv
dirs); the mutated file is written into the COPY, the suite runs in the COPY,
and the copy is discarded. Only the single target module is ever mutated.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
import shutil
import subprocess
import tempfile

# Project-layout source-root detection — shared with wire-exports so the ``src/``
# + pyproject root logic lives in exactly one place. Re-exported as ``_source_roots``
# (the historical private name :mod:`app.execution.stub_synthesis` imports) so the
# extraction is fully behaviour-preserving for existing callers.
from app.engine.source_roots import source_roots as _source_roots

# The canonical tree-walk exclusion (VCS, caches, venvs, build output, and
# Apex's own metadata/`.claude` worktree copies) — shared so the walk below and
# the mutant-sandbox copytree never drift from every other walker.
from app.engine.import_reach import reaching_import_names
from app.engine.skip_dirs import SKIPPED_DIRS as _SKIP_DIRS

# Directories never worth copying into a mutant's throwaway sandbox.
_COPY_EXCLUDE = shutil.ignore_patterns(*sorted(_SKIP_DIRS))

# Comparison-operator flips. Each maps an ``ast`` comparison op class to the
# literal it is written as and the literal it becomes.
_COMPARE_FLIPS: dict[type, tuple[str, str]] = {
    ast.Eq: ("==", "!="),
    ast.NotEq: ("!=", "=="),
    ast.Lt: ("<", ">="),
    ast.GtE: (">=", "<"),
    ast.Gt: (">", "<="),
    ast.LtE: ("<=", ">"),
    ast.Is: ("is", "is not"),
    ast.IsNot: ("is not", "is"),
    # Membership flips — catch tests blind to inclusion-vs-exclusion logic
    # (``x in allowed`` vs ``x not in allowed``). Both tokens live in the gap
    # between the left operand and the comparator, so the same gap-bounded
    # ``_op_span`` search that already handles ``is``/``is not`` locates them
    # exactly, never matching an ``in`` that sits inside an identifier (those
    # live inside operand spans, not the operator gap).
    ast.In: ("in", "not in"),
    ast.NotIn: ("not in", "in"),
}

# Comparison BOUNDARY flips — a *different fault class* from the negation flips
# above. Here we slide the relational operator across its boundary by one
# (``<`` <-> ``<=``, ``>`` <-> ``>=``) without negating it. This catches the
# classic off-by-one blind spot: a test that only exercises values strictly
# inside (or strictly outside) a range never notices whether the boundary value
# itself is included, so ``x < n`` vs ``x <= n`` looks identical to it. The
# negation flips above (``<`` -> ``>=``) do NOT cover this — they invert the
# relation, which a boundary value alone may still distinguish, whereas the
# boundary flip changes ONLY the inclusivity at the edge. Both sites are seeded
# for the same token; they carry distinct ``boundary:``/``comparison:`` labels
# so the operator set never collides and stays deterministic.
_COMPARE_BOUNDARY_FLIPS: dict[type, tuple[str, str]] = {
    ast.Lt: ("<", "<="),
    ast.LtE: ("<=", "<"),
    ast.Gt: (">", ">="),
    ast.GtE: (">=", ">"),
}

# Arithmetic-operator flips on ``ast.BinOp``.
_BINOP_FLIPS: dict[type, tuple[str, str]] = {
    ast.Add: ("+", "-"),
    ast.Sub: ("-", "+"),
    ast.Mult: ("*", "/"),
    ast.Div: ("/", "*"),
}

# Boolean-connective flips on ``ast.BoolOp``.
_BOOLOP_FLIPS: dict[type, tuple[str, str]] = {
    ast.And: ("and", "or"),
    ast.Or: ("or", "and"),
}

# Boolean-constant flips.
_BOOL_CONST_FLIPS: dict[bool, tuple[str, str]] = {
    True: ("True", "False"),
    False: ("False", "True"),
}

# Augmented-assignment operator flips on ``ast.AugAssign`` (``x += 1`` etc.).
# The written token excludes the trailing ``=`` (we splice just the operator
# part of the ``<op>=`` compound so the ``=`` stays put).
_AUGASSIGN_FLIPS: dict[type, tuple[str, str]] = {
    ast.Add: ("+", "-"),
    ast.Sub: ("-", "+"),
    ast.Mult: ("*", "/"),
    ast.Div: ("/", "*"),
}


@dataclass
class Mutant:
    """One seeded fault: a single source span swapped for an equivalent-shape
    alternative, leaving the rest of the module byte-for-byte identical."""

    module: str
    line: int
    operator: str
    original: str
    mutated: str
    killed: bool = False

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "line": self.line,
            "operator": self.operator,
            "original": self.original,
            "mutated": self.mutated,
            "killed": self.killed,
        }


@dataclass
class MutationResult:
    """The aggregate test-strength reading for one module."""

    module: str
    total: int
    killed: int
    survived: int
    score: float
    survivors: list[Mutant] = field(default_factory=list)
    scoped_tests: list[str] = field(default_factory=list)
    # False when the covering tests did NOT pass on the UNMUTATED module, so the
    # kill/survive split is meaningless (every mutant looks "killed" against an
    # already-red baseline). A sound score requires baseline_ok is True.
    baseline_ok: bool = True
    # True when a deterministic work budget (a mutant-RUN COUNT, never a clock)
    # ran out before every enumerated mutant was verified — so ``total`` covers
    # only the mutants ACTUALLY examined and the rest were left unvisited this
    # run. A distinct honest outcome (mirrors ``baseline_ok``): the score over the
    # examined mutants is still sound (no skip is folded into killed/survived),
    # but the caller must not read a budget-truncated scan as "module clean". The
    # default is False, so every unbudgeted run is byte-identical to before.
    budget_exhausted: bool = False

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "total": self.total,
            "killed": self.killed,
            "survived": self.survived,
            "score": self.score,
            "survivors": [m.to_dict() for m in self.survivors],
            "scoped_tests": list(self.scoped_tests),
            "baseline_ok": self.baseline_ok,
            "budget_exhausted": self.budget_exhausted,
        }


@dataclass
class _Site:
    """A located, single-line span to be replaced — the raw material of a
    mutant, before we splice the full module source."""

    line: int
    col: int
    end_col: int
    operator: str
    original: str
    mutated: str


def _op_span(line: str, start: int, token: str) -> tuple[int, int] | None:
    """Find the ``[start, end)`` span of ``token`` at or after ``start`` on a
    single source line, returning ``None`` if it isn't there as expected."""
    idx = line.find(token, start)
    if idx < 0:
        return None
    return idx, idx + len(token)


def _node_line(source_lines: list[str], lineno: int) -> str:
    """The 1-based source line ``lineno`` (``""`` if out of range) — the single
    place the per-kind collectors reach back into the source for splice bounds."""
    idx = lineno - 1
    return source_lines[idx] if idx < len(source_lines) else ""


def _is_single_line(node: ast.AST) -> bool:
    """True iff ``node`` occupies exactly one source line. Only single-line
    spans are mutated so the splice stays byte-exact (mirrors the original
    ``node.lineno != node.end_lineno`` guards)."""
    return node.lineno == node.end_lineno


def _relational_flip_site(
    node: ast.Compare, line: str, line_len: int, search_from: int,
    comp_end: int, label: str, flip: tuple[str, str] | None,
) -> _Site | None:
    """Locate one relational-operator token and, if found within its gap, build
    the mutation site for ``flip``. Shared by the comparison-negation and
    boundary families (``label`` is ``"comparison"`` or ``"boundary"``); returns
    ``None`` when this op has no flip of that family or the token isn't there."""
    if flip is None:
        return None
    written, replacement = flip
    span = _op_span(line, search_from, written)
    if span is None or span[1] > comp_end or span[1] > line_len:
        return None
    return _Site(
        line=node.lineno, col=span[0], end_col=span[1],
        operator=f"{label}:{written}>{replacement}",
        original=written, mutated=replacement,
    )


def _collect_compare_sites(node: ast.Compare, source_lines: list[str]) -> list[_Site]:
    """Comparison + boundary flips — one site per operator in a (possibly
    chained) ``Compare``. Operator tokens are located left-to-right across the
    comparator spans so chained compares (``a < b < c``) work. For each op the
    comparison (negation) flip is emitted before the boundary (off-by-one) flip
    so they share the same span without colliding."""
    if not _is_single_line(node):
        return []
    line = _node_line(source_lines, node.lineno)
    line_len = len(line)
    sites: list[_Site] = []
    search_from = node.left.end_col_offset or 0
    for op, comparator in zip(node.ops, node.comparators):
        comp_end = comparator.col_offset
        op_type = type(op)
        for label, flip in (
            ("comparison", _COMPARE_FLIPS.get(op_type)),
            ("boundary", _COMPARE_BOUNDARY_FLIPS.get(op_type)),
        ):
            site = _relational_flip_site(
                node, line, line_len, search_from, comp_end, label, flip,
            )
            if site is not None:
                sites.append(site)
        search_from = comparator.end_col_offset or comp_end
    return sites


def _collect_binop_sites(node: ast.BinOp, source_lines: list[str]) -> list[_Site]:
    """Arithmetic-operator flip on a single-line ``BinOp`` (``a + b`` etc.)."""
    flip = _BINOP_FLIPS.get(type(node.op))
    if flip is None or not _is_single_line(node):
        return []
    line = _node_line(source_lines, node.lineno)
    written, replacement = flip
    left_end = node.left.end_col_offset or 0
    right_start = node.right.col_offset
    span = _op_span(line, left_end, written)
    if span is None or span[1] > right_start or span[1] > len(line):
        return []
    return [_Site(
        line=node.lineno, col=span[0], end_col=span[1],
        operator=f"arithmetic:{written}>{replacement}",
        original=written, mutated=replacement,
    )]


def _collect_boolop_sites(node: ast.BoolOp, source_lines: list[str]) -> list[_Site]:
    """Boolean-connective flips on a single-line ``BoolOp`` — one mutant per
    connective occurrence between successive values."""
    flip = _BOOLOP_FLIPS.get(type(node.op))
    if flip is None or not _is_single_line(node):
        return []
    line = _node_line(source_lines, node.lineno)
    line_len = len(line)
    written, replacement = flip
    sites: list[_Site] = []
    search_from = node.values[0].end_col_offset or 0
    for value in node.values[1:]:
        next_start = value.col_offset
        span = _op_span(line, search_from, written)
        if span is not None and span[1] <= next_start and span[1] <= line_len:
            sites.append(_Site(
                line=node.lineno, col=span[0], end_col=span[1],
                operator=f"boolean:{written}>{replacement}",
                original=written, mutated=replacement,
            ))
        search_from = value.end_col_offset or next_start
    return sites


def _collect_bool_const_sites(node: ast.Constant, source_lines: list[str]) -> list[_Site]:
    """Boolean-constant flip (``True`` <-> ``False``) on a single-line span."""
    if not _is_single_line(node):
        return []
    line = _node_line(source_lines, node.lineno)
    written, replacement = _BOOL_CONST_FLIPS[node.value]
    start = node.col_offset
    end = node.end_col_offset or 0
    if end > len(line) or line[start:end] != written:
        return []
    return [_Site(
        line=node.lineno, col=start, end_col=end,
        operator=f"constant:{written}>{replacement}",
        original=written, mutated=replacement,
    )]


def _collect_number_sites(node: ast.Constant, source_lines: list[str]) -> list[_Site]:
    """Number-constant flip ``n -> n + 1`` on a single-line span. The literal is
    spliced verbatim, so we only mutate when the source text matches exactly."""
    if not _is_single_line(node):
        return []
    line = _node_line(source_lines, node.lineno)
    start = node.col_offset
    end = node.end_col_offset or 0
    if end > len(line):
        return []
    written = line[start:end]
    # Only handle plain numeric literals (no sign/whitespace inside the span);
    # a textual round-trip of ``n + 1`` keeps int/float type.
    replacement = _mutate_number(node.value, written)
    if replacement is None or replacement == written:
        return []
    return [_Site(
        line=node.lineno, col=start, end_col=end,
        operator=f"number:{written}>{replacement}",
        original=written, mutated=replacement,
    )]


def _collect_return_sites(node: ast.Return, source_lines: list[str]) -> list[_Site]:
    """Return-value flip ``return <expr>`` -> ``return None``. Only the value
    span is spliced (the ``return`` keyword stays), so it stays single-line."""
    value = node.value
    if value is None or not _is_single_line(value):
        return []
    line = _node_line(source_lines, value.lineno)
    start = value.col_offset
    end = value.end_col_offset or 0
    if end > len(line):
        return []
    written = line[start:end]
    if not written or written == "None":
        return []
    return [_Site(
        line=value.lineno, col=start, end_col=end,
        operator="return:value>None",
        original=written, mutated="None",
    )]


def _collect_augassign_sites(node: ast.AugAssign, source_lines: list[str]) -> list[_Site]:
    """Augmented-assign operator flip (``x += 1`` -> ``x -= 1``) — just the
    operator token before the ``=`` is spliced, leaving the ``=`` intact."""
    flip = _AUGASSIGN_FLIPS.get(type(node.op))
    if flip is None or not _is_single_line(node):
        return []
    line = _node_line(source_lines, node.lineno)
    written, replacement = flip
    # The ``<op>=`` token sits between the target and the value; search for
    # ``<op>=`` from the end of the target so we don't catch any unrelated
    # operator on the line.
    target_end = node.target.end_col_offset or 0
    value_start = node.value.col_offset
    span = _op_span(line, target_end, written + "=")
    if span is None or span[1] > value_start or span[1] > len(line):
        return []
    # Mutate only the operator char, keeping the ``=`` intact.
    return [_Site(
        line=node.lineno, col=span[0], end_col=span[0] + len(written),
        operator=f"augassign:{written}=>{replacement}=",
        original=written, mutated=replacement,
    )]


def _sites_for_node(node: ast.AST, source_lines: list[str]) -> list[_Site]:
    """Dispatch one AST node to its per-kind site collector, returning every
    mutation site it yields (``[]`` for an un-mutable node). Bool constants are
    routed before numeric ones because ``bool`` is a subclass of ``int``."""
    if isinstance(node, ast.Compare):
        return _collect_compare_sites(node, source_lines)
    if isinstance(node, ast.BinOp):
        return _collect_binop_sites(node, source_lines)
    if isinstance(node, ast.BoolOp):
        return _collect_boolop_sites(node, source_lines)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return _collect_bool_const_sites(node, source_lines)
        if isinstance(node.value, (int, float)):
            return _collect_number_sites(node, source_lines)
        return []
    if isinstance(node, ast.Return):
        return _collect_return_sites(node, source_lines)
    if isinstance(node, ast.AugAssign):
        return _collect_augassign_sites(node, source_lines)
    return []


def _collect_sites(tree: ast.Module, source_lines: list[str]) -> list[_Site]:
    """Enumerate every applicable mutation site in document order.

    Only single-line nodes/operators are mutated so the source-span splice
    stays exact (mirrors ``negated_comparison.py``). Each site flips exactly
    one operator/constant token. The per-kind logic lives in the
    ``_collect_*_sites`` helpers; this function only walks the tree, dispatches
    each node, and sorts the result into the deterministic document order.
    """
    sites: list[_Site] = []
    for node in ast.walk(tree):
        sites.extend(_sites_for_node(node, source_lines))
    sites.sort(key=lambda s: (s.line, s.col, s.operator))
    return sites


def _mutate_number(value: int | float, written: str) -> str | None:
    """Deterministic numeric-literal mutation ``n -> n + 1``.

    Returns the replacement text, or ``None`` when the source token is not a
    plain decimal literal we can safely rewrite (e.g. hex/binary/underscored
    forms, or a value carrying a sign that lives outside the constant span).
    The text is produced from ``value + 1`` so an int stays an int and a float
    stays a float, mirroring the literal's own kind.
    """
    # Refuse anything but the digits/dot Python would render for this value, so
    # the splice round-trips and never corrupts an exotic literal form.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        if written != str(value):
            return None
        return str(value + 1)
    if isinstance(value, float):
        if written != repr(value):
            return None
        return repr(value + 1.0)
    return None


def _splice(source_lines: list[str], site: _Site) -> str | None:
    """Build the full module source with just this one span replaced; returns
    ``None`` if the result fails to re-parse (a malformed/equivalent splice)."""
    li = site.line - 1
    if li >= len(source_lines):
        return None
    line = source_lines[li]
    if site.end_col > len(line) or line[site.col:site.end_col] != site.original:
        return None
    mutated_lines = list(source_lines)
    mutated_lines[li] = line[:site.col] + site.mutated + line[site.end_col:]
    mutated_source = "".join(mutated_lines)
    try:
        ast.parse(mutated_source)
    except (SyntaxError, RecursionError, MemoryError):
        return None
    return mutated_source


def _module_dotted_path(module_rel: str) -> str:
    """Convert a module's repo-relative path to its dotted import path.

    ``app/engine/foo.py`` -> ``app.engine.foo``; a bare ``mod.py`` -> ``mod``.
    Trailing ``__init__`` is collapsed to its package (``app/engine/__init__``
    -> ``app.engine``).
    """
    parts = list(Path(module_rel).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _dotted_prefixes(dotted: str) -> set[str]:
    """Every dotted prefix of ``dotted`` (``a.b.c`` -> ``{a, a.b, a.b.c}``), plus
    the bare leaf — the set of import targets that reach the module. ``""`` yields
    an empty set."""
    if not dotted:
        return set()
    parts = dotted.split(".")
    out = {".".join(parts[: i + 1]) for i in range(len(parts))}
    out.add(parts[-1])
    return out


def _import_targets(project_root: Path, module_rel: str) -> set[str]:
    """Every dotted import target that reaches ``module_rel`` — the raw dotted path
    AND each source-root-stripped dotted path, each expanded to all its prefixes
    plus the bare leaf.

    The root-stripped targets are what make a ``src/`` (or pyproject-declared)
    layout work: a test importing ``mylib.calc`` reaches ``src/mylib/calc.py``
    because the leading ``src`` root is stripped before the dotted path is formed.
    The raw path stays in the set, so a non-src project (and the rare test that
    imports ``src.mylib.calc`` literally) is byte-identical to before."""
    dotted = _module_dotted_path(module_rel)
    targets = _dotted_prefixes(dotted)
    posix = module_rel.replace("\\", "/")
    for root in _source_roots(project_root):
        prefix = root + "/"
        if posix.startswith(prefix):
            targets |= _dotted_prefixes(_module_dotted_path(posix[len(prefix):]))
    return targets


def _is_test_file(rel: str) -> bool:
    """A path is a test file if it lives under ``tests/`` or its filename
    matches ``test_*.py`` / ``*_test.py`` — the same conventions pytest's
    default ``python_files`` discovers. The suffix form is the COLOCATED
    layout (``pkg/calc_test.py`` beside ``pkg/calc.py``); missing it dropped
    every such test from the scoped gate (audit 2026-07-08, finding 11)."""
    p = Path(rel)
    if p.suffix != ".py":
        return False
    if "tests" in p.parts:
        return True
    return p.name.startswith("test_") or p.name.endswith("_test.py")


def _imported_names(tree: ast.Module) -> set[str]:
    """All dotted names referenced by ``import`` / ``from ... import`` in a
    parsed module. For ``from a.b import c`` we record both ``a.b`` (the source
    package) and ``a.b.c`` (the imported member) so either can match a module's
    dotted path. Relative imports are ignored (no absolute path to match).

    LITERAL dynamic imports count too (audit 2026-07-08, trust-chain finding
    5): ``importlib.import_module("pkg.mod")``, ``pytest.importorskip("pkg.mod")``
    (the standard optional-dependency pattern in real test suites) and
    ``__import__("pkg.mod")`` name their module in a string constant a static
    scan can read — missing them dropped genuinely-covering tests from the
    scope. Only a literal first argument counts; a COMPUTED name is honestly
    invisible to any deterministic AST scan (the pinned ``exec``-string blind
    spot stays a disclosed miss)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0 or not node.module:
                continue
            names.add(node.module)
            for alias in node.names:
                names.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Call):
            dynamic = _dynamic_import_arg(node)
            if dynamic:
                names.add(dynamic)
    return names


# The callable names whose LITERAL first argument is a module path. Both the
# attribute form (``importlib.import_module`` / ``pytest.importorskip``) and
# the bare imported form (``from importlib import import_module``) are common.
_DYNAMIC_IMPORTERS = frozenset({"import_module", "importorskip", "__import__"})


def _dynamic_import_arg(node: ast.Call) -> str | None:
    """The literal dotted module a dynamic-import call pulls in, or ``None``.

    Matches ``__import__(...)`` / ``import_module(...)`` / ``importorskip(...)``
    by callee name (bare or attribute form) with a string-constant first
    argument. A relative name (``import_module(".mod", package=...)``) is
    skipped — it has no absolute path to match."""
    func = node.func
    callee = func.id if isinstance(func, ast.Name) else (
        func.attr if isinstance(func, ast.Attribute) else None)
    if callee not in _DYNAMIC_IMPORTERS or not node.args:
        return None
    first = node.args[0]
    if (isinstance(first, ast.Constant) and isinstance(first.value, str)
            and first.value and not first.value.startswith(".")):
        return first.value
    return None


def covering_test_files(project_root, module_rel: str) -> list[str]:
    """Test files whose source imports the target module — a cheap, coverage-free
    scope for mutation testing and per-move impact verification.

    "Imports the module" is decided deterministically from each test file's AST,
    and a test covers ``module_rel`` when any of its ``import`` /
    ``from ... import`` statements would EXECUTE it:

    * it names the module's dotted path (``app.engine.foo``) or a parent
      package of it (``from app.engine import foo`` / ``import app.engine``);
    * it names a project module that imports the target, directly or
      transitively (a test importing ``pkg.api`` covers ``pkg/_impl.py`` when
      ``api`` does ``from pkg._impl import f``) — resolved through the cached
      project import graph (:mod:`app.engine.import_reach`);
    * it names ANYTHING under a covered package's prefix — importing
      ``pkg.sub._x`` executes ``pkg/sub/__init__.py`` on the way, so a change
      to that ``__init__`` is covered even when ``_x`` is not a parseable
      project module. (This exact shape produced a fake "verified" on the
      external ``packaging`` run; the prefix rule is the belt to the graph's
      suspenders.)

    Files that fail to parse are skipped. Returns a sorted, de-duplicated list
    of test-file paths relative to ``project_root`` (deterministic across runs).
    """
    root = Path(project_root)
    dotted = _module_dotted_path(module_rel)
    if not dotted:
        return []
    # Every dotted prefix of the module path is an acceptable import target
    # (``app``, ``app.engine``, ``app.engine.foo``); an import of any of these
    # — or of the bare leaf name — means the test reaches the module. On a
    # ``src/`` (or pyproject-declared) layout the source-root-stripped prefixes
    # (``mylib``, ``mylib.calc`` for ``src/mylib/calc.py``) are ALSO targets, so
    # a test importing ``mylib.calc`` is no longer missed (impact-scoping blind).
    targets = _import_targets(root, module_rel)
    # ... plus the import-reachability closure: the exact names of every project
    # module whose import executes the target, and the descendant prefixes of
    # every covered package __init__ (see the docstring's last two bullets).
    reached, pkg_prefixes = reaching_import_names(root, module_rel)
    targets |= reached

    matches: set[str] = set()
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if not _is_test_file(rel):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        imported = _imported_names(tree)
        if imported & targets or _under_any(imported, pkg_prefixes):
            matches.add(rel)
    return sorted(_expand_conftest_matches(root, matches))


def _expand_conftest_matches(root: Path, matches: set[str]) -> set[str]:
    """Replace a matched ``conftest.py`` with the test files its fixtures serve.

    A ``conftest.py`` that imports the target is a REAL linkage — its fixtures
    hand the target's objects to every test at or below its directory — but it
    cannot be RUN: passing it to pytest collects nothing (exit 5), so a scope
    of ``['tests/conftest.py']`` verifies nothing (audit 2026-07-08, trust-chain
    finding 2: a false red in absolute mode, a fail-closed rollback in delta).
    The honest runnable scope is the tests under the conftest's directory
    (``test_*.py`` / ``*_test.py``, pytest's own conventions) — an over-
    approximation in the safe direction (fixture-using tests run; unrelated
    siblings just cost time). A conftest with no tests below it expands to
    NOTHING, so the caller falls back to the full suite. (A repo-ROOT
    ``conftest.py`` outside ``tests/`` was never matched as a test file at
    all — that linkage stays a known, disclosed blind spot.)"""
    out: set[str] = set()
    for rel in matches:
        p = Path(rel)
        if p.name != "conftest.py":
            out.add(rel)
            continue
        for pattern in ("test_*.py", "*_test.py"):
            for path in sorted((root / p.parent).rglob(pattern)):
                if any(part in _SKIP_DIRS for part in path.parts):
                    continue
                out.add(path.relative_to(root).as_posix())
    return out


def _under_any(names: set[str], prefixes: tuple[str, ...]) -> bool:
    """True when any imported name sits strictly under one of the covered
    package prefixes (each ends with ``.``) — importing a descendant executes
    the package ``__init__`` on the way."""
    return any(name.startswith(prefix) for prefix in prefixes for name in names)


def _verify_killed(project_root: Path, module_rel: str,
                   mutated_source: str, verify_timeout: int,
                   covering: list[str] | None = None) -> bool:
    """Run the suite against a mutant in an isolated copy of the project.

    The real tree is never touched: we ``copytree`` the project (minus VCS /
    cache / venv dirs), overwrite the target module in the COPY, run pytest in
    the COPY, then discard it. Returns ``True`` if the suite FAILED (mutant
    killed), ``False`` if it passed (mutant survived). A timeout counts as a
    kill (the mutant broke the run).

    When ``covering`` is a non-empty list, only those test files are run (the
    deterministic scope from ``covering_test_files``) — this is what keeps the
    per-mutant run cheap on large repos. ``None`` / empty runs the whole suite.
    """
    tmp_dir = tempfile.mkdtemp(prefix="apex-mutant-")
    copy_root = Path(tmp_dir) / "project"
    try:
        shutil.copytree(project_root, copy_root, ignore=_COPY_EXCLUDE)
        (copy_root / module_rel).write_text(mutated_source, encoding="utf-8")
        cmd = ["python", "-m", "pytest", "-q", "-x"]
        if covering:
            cmd.extend(covering)
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(copy_root),
                timeout=verify_timeout,
                capture_output=True,
            )
        except subprocess.TimeoutExpired:
            return True  # mutant made the suite hang — counts as caught
        return proc.returncode != 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# Letter-grade cutoffs on the mutation score (killed / total), highest first.
# A+ is reserved for a near-perfect suite; F is the failing floor. The cutoffs
# are inclusive lower bounds (``score >= cutoff``) and are documented constants
# so the mapping is auditable and never drifts with the code.
_GRADE_CUTOFFS: tuple[tuple[float, str], ...] = (
    (0.97, "A+"),
    (0.90, "A"),
    (0.80, "B"),
    (0.70, "C"),
    (0.60, "D"),
)

# Emoji badge per letter — mirrors ``render_grade_markdown`` in health_score.
_GRADE_BADGES: dict[str, str] = {
    "A+": "🏆", "A": "🥇", "B": "🟢", "C": "🟡", "D": "🟠", "F": "🔴",
}


def test_strength_grade(score: float) -> str:
    """Map a mutation score (``killed / total``, in ``[0.0, 1.0]``) to a letter.

    The grade answers "how strong are the tests?" rather than "do they pass?":

    * ``>= 0.97`` -> ``A+`` (the suite catches essentially every seeded fault)
    * ``>= 0.90`` -> ``A``
    * ``>= 0.80`` -> ``B``
    * ``>= 0.70`` -> ``C``
    * ``>= 0.60`` -> ``D``
    * otherwise   -> ``F`` (more than 40% of seeded faults go unnoticed)

    Pure and deterministic: the cutoffs are fixed constants, so the same score
    always yields the same letter.
    """
    for cutoff, letter in _GRADE_CUTOFFS:
        if score >= cutoff:
            return letter
    return "F"


def render_mutation_markdown(result: MutationResult) -> str:
    """Render a ``MutationResult`` as a memorable test-strength report.

    Shows a badge + letter grade + the score as a percentage; the
    killed/survived/total split; whether the run was scoped (and to which test
    files) or fell back to the full suite; and — most usefully — the SURVIVORS
    listed as ``file:line — operator`` so the developer sees exactly which
    mutations the tests fail to catch (the test blind spots). The ``total == 0``
    case (no mutable sites, or a module that didn't parse) renders cleanly.

    Tone and shape mirror ``render_grade_markdown`` in ``health_score`` (badge
    header + table + a "where to look" section). Pure and deterministic.
    """
    if result.total == 0:
        return (
            f"# Test strength for {result.module}\n\n"
            "_No mutable sites found (or the module didn't parse) — "
            "nothing to grade._\n"
        )

    # Honesty guard (never fake a signal): when the baseline is red the
    # kill/survive split is MEANINGLESS — every mutant trivially "survives" a
    # suite that was already failing on the UNMUTATED module — so we must NOT
    # render a grade letter or a "blind spots" list (both would libel the tests
    # as weak when the measurement never actually ran). Report the void plainly
    # and name the common cause so the developer can fix the sandbox-hostile
    # covering test instead of chasing phantom survivors.
    if not result.baseline_ok:
        lines = [
            f"# Test strength: ⚪ **not measured** — {result.module}",
            "",
            "_Baseline not green: the covering tests already FAIL on the "
            "unmutated module inside the sandbox copy, so no mutation score can "
            "be computed (a red baseline makes every mutant look \"killed\" — a "
            "false 100% — so Apex refuses to score rather than fake one)._",
            "",
            "_Common cause: a covering test reconstructs source via "
            "`git show HEAD:<path>` (or otherwise needs VCS/network state) and "
            "errors in the `.git`-less sandbox. Fix or scope out that test, then "
            "re-run._",
            "",
        ]
        if result.scoped_tests:
            files = ", ".join(f"`{f}`" for f in result.scoped_tests)
            lines.append(f"_Covering scope ({len(result.scoped_tests)} file(s), "
                         f"one of which is red in the sandbox): {files}._")
            lines.append("")
        return "\n".join(lines)

    letter = test_strength_grade(result.score)
    badge = _GRADE_BADGES.get(letter, "🔴")
    pct = round(result.score * 100, 1)
    lines = [
        f"# Test strength: {badge} **{letter}**  "
        f"(Mutation score {pct}%)  —  {result.module}",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Mutants killed | {result.killed} |",
        f"| Mutants survived | {result.survived} |",
        f"| Total seeded | {result.total} |",
        "",
    ]

    # Scope provenance: did we run a focused set of covering tests, or fall back
    # to the full suite because nothing imports the module?
    if result.scoped_tests:
        files = ", ".join(f"`{f}`" for f in result.scoped_tests)
        lines.append(f"_Scoped to {len(result.scoped_tests)} covering "
                     f"test file(s): {files}._")
    else:
        lines.append("_No covering test imports this module — ran the full "
                     "suite._")
    lines.append("")

    # Partial-scan honesty: a budget-truncated run examined only ``total``
    # mutants, so "no survivors" means "none among those examined" — NOT "module
    # clean". Say so, or the reader over-reads an incomplete scan as a pass.
    if result.budget_exhausted:
        lines.append("_⚠ Budget exhausted: only the "
                     f"{result.total} examined mutant(s) were scored; the rest "
                     "were left unvisited this run, so this is a partial reading, "
                     "not a full one._")
        lines.append("")

    # Where to look: the survivors are the blind spots. List them
    # ``file:line — operator`` in document order (survivors are already ordered).
    if result.survivors:
        lines.append("## Blind spots — survivors the tests don't catch")
        for m in result.survivors:
            lines.append(f"- `{m.module}:{m.line}` — {m.operator} "
                         f"(`{m.original}` -> `{m.mutated}`)")
    else:
        lines.append("_No survivors — the suite caught every seeded fault._")
    lines.append("")
    return "\n".join(lines)


def _build_pending(source_lines: list[str], sites: list[_Site], module_rel: str,
                   max_mutants: int) -> list[tuple[Mutant, str]]:
    """``(Mutant, mutated source)`` pairs in document order, splices that fail to
    re-parse skipped, capped at ``max_mutants`` — the raw work list."""
    pending: list[tuple[Mutant, str]] = []
    for site in sites:
        if len(pending) >= max_mutants:
            break
        mutated_source = _splice(source_lines, site)
        if mutated_source is None:
            continue
        pending.append((Mutant(
            module=module_rel, line=site.line, operator=site.operator,
            original=site.original, mutated=site.mutated,
        ), mutated_source))
    return pending


def _verify_pending(root: Path, module_rel: str,
                    pending: list[tuple[Mutant, str]], verify_timeout: int,
                    covering: list[str], budget) -> tuple[int, list[Mutant], bool]:
    """Verify each pending mutant until the work budget runs out.

    Returns ``(killed, survivors, exhausted)``. With ``budget is None`` every
    pending mutant runs (today's behaviour, byte-identical). With a ``_Budget``
    the loop spends one run per mutant and STOPS the moment nothing is left — the
    unvisited mutants are simply not examined (never folded into killed/survived,
    so the score over the examined set stays sound). ``verify_timeout`` is passed
    through UNCHANGED on every call: the budget bounds the COUNT of runs, never
    the per-run time, so a mutant that runs gets the same fixed-timeout verdict on
    every machine (the TimeoutExpired→kill rule is untouched)."""
    killed = 0
    survivors: list[Mutant] = []
    for i, (mutant, mutated_source) in enumerate(pending):
        if budget is not None and budget.exhausted:
            # Out of allowance: every remaining mutant is left UNEXAMINED. We do
            # NOT count it as killed or survived — truncating ``total`` keeps the
            # examined-set score honest. The caller reports budget_exhausted.
            return killed, survivors, True
        if _verify_killed(root, module_rel, mutated_source, verify_timeout,
                          covering=covering):
            mutant.killed = True
            killed += 1
        else:
            survivors.append(mutant)
        if budget is not None:
            budget.spend(1)
    return killed, survivors, False


def mutation_score(project_root, module_rel: str, max_mutants: int = 30,
                   verify_timeout: int = 120,
                   scope_tests: bool = True, budget=None) -> MutationResult:
    """Measure how strongly the project's test suite constrains ``module_rel``.

    Seeds up to ``max_mutants`` deterministic single-token faults into the
    target module, verifies each against the existing suite in an isolated
    copy, and reports the kill/survive split. ``score`` is ``killed / total``
    (0.0 when there are no mutable sites). Survivors carry their line and
    operator so the caller learns exactly where the tests are blind.

    Test scoping (``scope_tests=True``, the default): rather than run the whole
    suite against every mutant — intractable on a large repo — we compute the
    covering test files ONCE up front (``covering_test_files``) and run only
    those per mutant. This is deterministic (the scope is sorted) and cheap. If
    NO test imports the module the scope is empty: we fall back to the full
    suite so correctness is never silently weakened (and ``scoped_tests`` stays
    empty to record that we fell back). A genuinely untested module therefore
    surfaces its survivors honestly. ``scope_tests=False`` keeps the original
    full-suite behaviour for back-compat.

    Work budget (``budget``, an :class:`app.execution._verify_budget._Budget` or
    ``None``): a DETERMINISTIC mutant-RUN COUNT — never a wall clock — bounding
    how many ``_verify_killed`` runs this scan may spend so a big real module
    can't fan out past the harness limit and land an honest no-op. Each run
    (baseline + per mutant) debits one. When it runs out mid-scan the remaining
    mutants are left UNEXAMINED (``total`` covers only those verified) and
    ``budget_exhausted=True`` is reported — a skip is NEVER folded into
    killed/survived, so the examined-set score stays sound. ``verify_timeout``
    is independent of the budget (it stays its fixed default), so a mutant that
    runs gets the same verdict everywhere — the TimeoutExpired→kill rule is
    untouched. ``budget is None`` (the default) is byte-identical to before.

    The original project tree is read-only throughout (see ``_verify_killed``).
    """
    root = Path(project_root)
    module_path = root / module_rel
    try:
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, RecursionError, MemoryError):
        return MutationResult(module=module_rel, total=0, killed=0,
                              survived=0, score=0.0, survivors=[],
                              scoped_tests=[])

    covering: list[str] = []
    if scope_tests:
        covering = covering_test_files(root, module_rel)

    source_lines = source.splitlines(keepends=True)
    sites = _collect_sites(tree, source_lines)
    pending = _build_pending(source_lines, sites, module_rel, max_mutants)
    mutants = [m for m, _ in pending]

    # Budget guard at the START: the baseline run below costs one mutant-run. If
    # there is work to do but the budget can't even pay for the baseline, examine
    # NOTHING this scan (total=0) and report budget_exhausted — a half-funded
    # module is never scored against a baseline-less (and so meaningless) split.
    if pending and budget is not None and not budget.can_afford(1):
        return MutationResult(
            module=module_rel, total=0, killed=0, survived=0, score=0.0,
            survivors=[], scoped_tests=list(covering), budget_exhausted=True,
        )

    # Baseline-green guard (measurement soundness): a kill/survive split is only
    # meaningful if the covering tests PASS on the UNMUTATED module. If they
    # don't — the classic vector is a covering test that reconstructs the source
    # via `git show HEAD:` and ERRORS uniformly in the sandbox copy (which has no
    # .git) — then EVERY mutant trivially looks "killed" and the score is a false
    # 100%. Run the original source through the same harness first; if the suite
    # is already red, report baseline_ok=False instead of a misleading score.
    if pending:
        baseline_red = _verify_killed(root, module_rel, source, verify_timeout,
                                      covering=covering)
        if budget is not None:
            budget.spend(1)  # the baseline run costs one unit of the budget
        if baseline_red:
            return MutationResult(
                module=module_rel, total=len(mutants), killed=0,
                survived=len(mutants), score=0.0, survivors=list(mutants),
                scoped_tests=list(covering), baseline_ok=False,
            )

    killed, survivors, exhausted = _verify_pending(
        root, module_rel, pending, verify_timeout, covering, budget)

    # ``total`` counts only the mutants ACTUALLY examined (killed + survived) — a
    # budget-truncated tail is excluded, so the score is honest over what ran.
    total = killed + len(survivors)
    survived = len(survivors)
    score = killed / total if total else 0.0
    return MutationResult(
        module=module_rel, total=total, killed=killed,
        survived=survived, score=score, survivors=survivors,
        scoped_tests=list(covering), budget_exhausted=exhausted,
    )
