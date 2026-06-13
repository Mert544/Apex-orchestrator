"""Mutation testing — a deterministic *test-strength* fitness signal.

This is a multi-oracle "definition-of-done" measure: instead of asking whether
the code passes its tests, it asks whether the *tests* would notice if the code
broke. We seed tiny artificial faults ("mutants") into one target module — flip
a ``==`` to ``!=``, a ``+`` to ``-``, ``and`` to ``or``, ``True`` to ``False``,
a number ``n`` to ``n + 1``, a ``return <expr>`` to ``return None``, or a
``+=`` to ``-=`` — then run the project's existing test suite against each
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
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Directories never worth copying into a mutant's throwaway sandbox.
_COPY_EXCLUDE = shutil.ignore_patterns(
    ".git", "__pycache__", ".apex", ".venv", "venv", "node_modules",
)

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

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "total": self.total,
            "killed": self.killed,
            "survived": self.survived,
            "score": self.score,
            "survivors": [m.to_dict() for m in self.survivors],
            "scoped_tests": list(self.scoped_tests),
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


def _collect_sites(tree: ast.Module, source_lines: list[str]) -> list[_Site]:
    """Enumerate every applicable mutation site in document order.

    Only single-line nodes/operators are mutated so the source-span splice
    stays exact (mirrors ``negated_comparison.py``). Each site flips exactly
    one operator/constant token.
    """
    sites: list[_Site] = []

    for node in ast.walk(tree):
        # Comparison flips — one site per operator in a (possibly chained)
        # Compare. We locate each operator token left-to-right across the
        # comparator spans so chained compares (a < b < c) work.
        if isinstance(node, ast.Compare):
            if node.lineno != node.end_lineno:
                continue
            line = source_lines[node.lineno - 1] if node.lineno - 1 < len(source_lines) else ""
            search_from = node.left.end_col_offset or 0
            for op, comparator in zip(node.ops, node.comparators):
                flip = _COMPARE_FLIPS.get(type(op))
                comp_end = comparator.col_offset
                if flip is not None:
                    written, replacement = flip
                    span = _op_span(line, search_from, written)
                    if span is not None and span[1] <= comp_end and span[1] <= len(line):
                        sites.append(_Site(
                            line=node.lineno, col=span[0], end_col=span[1],
                            operator=f"comparison:{written}>{replacement}",
                            original=written, mutated=replacement,
                        ))
                search_from = comparator.end_col_offset or comp_end

        elif isinstance(node, ast.BinOp):
            flip = _BINOP_FLIPS.get(type(node.op))
            if flip is None or node.lineno != node.end_lineno:
                continue
            line = source_lines[node.lineno - 1] if node.lineno - 1 < len(source_lines) else ""
            written, replacement = flip
            left_end = node.left.end_col_offset or 0
            right_start = node.right.col_offset
            span = _op_span(line, left_end, written)
            if span is not None and span[1] <= right_start and span[1] <= len(line):
                sites.append(_Site(
                    line=node.lineno, col=span[0], end_col=span[1],
                    operator=f"arithmetic:{written}>{replacement}",
                    original=written, mutated=replacement,
                ))

        elif isinstance(node, ast.BoolOp):
            flip = _BOOLOP_FLIPS.get(type(node.op))
            if flip is None or node.lineno != node.end_lineno:
                continue
            line = source_lines[node.lineno - 1] if node.lineno - 1 < len(source_lines) else ""
            written, replacement = flip
            # One mutant per connective occurrence between successive values.
            search_from = node.values[0].end_col_offset or 0
            for value in node.values[1:]:
                next_start = value.col_offset
                span = _op_span(line, search_from, written)
                if span is not None and span[1] <= next_start and span[1] <= len(line):
                    sites.append(_Site(
                        line=node.lineno, col=span[0], end_col=span[1],
                        operator=f"boolean:{written}>{replacement}",
                        original=written, mutated=replacement,
                    ))
                search_from = value.end_col_offset or next_start

        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            if node.lineno != node.end_lineno:
                continue
            line = source_lines[node.lineno - 1] if node.lineno - 1 < len(source_lines) else ""
            written, replacement = _BOOL_CONST_FLIPS[node.value]
            start = node.col_offset
            end = node.end_col_offset or 0
            if end <= len(line) and line[start:end] == written:
                sites.append(_Site(
                    line=node.lineno, col=start, end_col=end,
                    operator=f"constant:{written}>{replacement}",
                    original=written, mutated=replacement,
                ))

        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            # Number-constant flip (bools already handled above; exclude them).
            # Deterministic rule: ``n -> n + 1``. The original literal must be
            # spliced verbatim, so we only mutate when the source span matches
            # the exact text we expect to replace.
            if isinstance(node.value, bool) or node.lineno != node.end_lineno:
                continue
            line = source_lines[node.lineno - 1] if node.lineno - 1 < len(source_lines) else ""
            start = node.col_offset
            end = node.end_col_offset or 0
            if end > len(line):
                continue
            written = line[start:end]
            # Only handle plain numeric literals (no sign/whitespace inside the
            # span); a textual round-trip of ``n + 1`` keeps int/float type.
            replacement = _mutate_number(node.value, written)
            if replacement is None or replacement == written:
                continue
            sites.append(_Site(
                line=node.lineno, col=start, end_col=end,
                operator=f"number:{written}>{replacement}",
                original=written, mutated=replacement,
            ))

        elif isinstance(node, ast.Return) and node.value is not None:
            # Return-value flip: ``return <expr>`` -> ``return None``. We splice
            # just the value span (leaving the ``return`` keyword in place) so
            # the replacement stays single-line and exact.
            value = node.value
            if value.lineno != value.end_lineno:
                continue
            line = source_lines[value.lineno - 1] if value.lineno - 1 < len(source_lines) else ""
            start = value.col_offset
            end = value.end_col_offset or 0
            if end > len(line):
                continue
            written = line[start:end]
            if not written or written == "None":
                continue
            sites.append(_Site(
                line=value.lineno, col=start, end_col=end,
                operator="return:value>None",
                original=written, mutated="None",
            ))

        elif isinstance(node, ast.AugAssign):
            # Augmented-assign operator flip (``x += 1`` -> ``x -= 1``). We
            # splice just the operator token before the ``=``.
            flip = _AUGASSIGN_FLIPS.get(type(node.op))
            if flip is None or node.lineno != node.end_lineno:
                continue
            line = source_lines[node.lineno - 1] if node.lineno - 1 < len(source_lines) else ""
            written, replacement = flip
            # The ``<op>=`` token sits between the target and the value; search
            # for ``<op>=`` from the end of the target so we don't catch any
            # unrelated operator on the line.
            target_end = node.target.end_col_offset or 0
            value_start = node.value.col_offset
            span = _op_span(line, target_end, written + "=")
            if span is not None and span[1] <= value_start and span[1] <= len(line):
                # Mutate only the operator char, keeping the ``=`` intact.
                sites.append(_Site(
                    line=node.lineno, col=span[0], end_col=span[0] + len(written),
                    operator=f"augassign:{written}=>{replacement}=",
                    original=written, mutated=replacement,
                ))

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
    except SyntaxError:
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


def _is_test_file(rel: str) -> bool:
    """A path is a test file if it lives under ``tests/`` or its filename
    matches ``test_*.py`` — the same convention pytest discovers by default."""
    p = Path(rel)
    if p.suffix != ".py":
        return False
    if "tests" in p.parts:
        return True
    return p.name.startswith("test_")


def _imported_names(tree: ast.Module) -> set[str]:
    """All dotted names referenced by ``import`` / ``from ... import`` in a
    parsed module. For ``from a.b import c`` we record both ``a.b`` (the source
    package) and ``a.b.c`` (the imported member) so either can match a module's
    dotted path. Relative imports are ignored (no absolute path to match)."""
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
    return names


def covering_test_files(project_root, module_rel: str) -> list[str]:
    """Test files whose source imports the target module — a cheap, coverage-free
    scope for mutation testing.

    "Imports the module" is decided deterministically from each test file's AST:
    a test covers ``module_rel`` if any of its ``import`` / ``from ... import``
    statements references the module's dotted path (``app.engine.foo``) or a
    parent package of it (so ``from app.engine import foo`` and
    ``import app.engine`` both count). Files that fail to parse are skipped.

    Returns a sorted, de-duplicated list of test-file paths relative to
    ``project_root`` (so the result is deterministic across runs).
    """
    root = Path(project_root)
    dotted = _module_dotted_path(module_rel)
    if not dotted:
        return []
    leaf = dotted.split(".")[-1]
    # Every dotted prefix of the module path is an acceptable import target
    # (``app``, ``app.engine``, ``app.engine.foo``); an import of any of these
    # — or of the bare leaf name — means the test reaches the module.
    parts = dotted.split(".")
    targets = {".".join(parts[: i + 1]) for i in range(len(parts))}
    targets.add(leaf)

    matches: set[str] = set()
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if any(part in {".git", "__pycache__", ".apex", ".venv",
                        "venv", "node_modules"} for part in path.parts):
            continue
        if not _is_test_file(rel):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        imported = _imported_names(tree)
        if imported & targets:
            matches.add(rel)
    return sorted(matches)


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


def mutation_score(project_root, module_rel: str, max_mutants: int = 30,
                   verify_timeout: int = 120,
                   scope_tests: bool = True) -> MutationResult:
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

    The original project tree is read-only throughout (see ``_verify_killed``).
    """
    root = Path(project_root)
    module_path = root / module_rel
    try:
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return MutationResult(module=module_rel, total=0, killed=0,
                              survived=0, score=0.0, survivors=[],
                              scoped_tests=[])

    covering: list[str] = []
    if scope_tests:
        covering = covering_test_files(root, module_rel)

    source_lines = source.splitlines(keepends=True)
    sites = _collect_sites(tree, source_lines)

    # Build (Mutant, mutated source) pairs in document order, skipping any
    # splice that fails to re-parse, capped at max_mutants.
    pending: list[tuple[Mutant, str]] = []
    for site in sites:
        if len(pending) >= max_mutants:
            break
        mutated_source = _splice(source_lines, site)
        if mutated_source is None:
            continue
        mutant = Mutant(
            module=module_rel, line=site.line, operator=site.operator,
            original=site.original, mutated=site.mutated,
        )
        pending.append((mutant, mutated_source))

    killed = 0
    survivors: list[Mutant] = []
    mutants = [m for m, _ in pending]
    for mutant, mutated_source in pending:
        if _verify_killed(root, module_rel, mutated_source, verify_timeout,
                          covering=covering):
            mutant.killed = True
            killed += 1
        else:
            survivors.append(mutant)

    total = len(mutants)
    survived = total - killed
    score = killed / total if total else 0.0
    return MutationResult(
        module=module_rel, total=total, killed=killed,
        survived=survived, score=score, survivors=survivors,
        scoped_tests=list(covering),
    )
