"""Naming-convention audit — does the project's OWN code follow PEP 8 casing?

A deterministic, stdlib-only analyzer that reads each source file with
``ast`` and checks the three casing rules every PEP 8 codebase agrees on:

  - **functions / methods / variables** → ``snake_case``
    (lowercase words joined by underscores: ``run_step``, ``count``);
  - **classes** → ``PascalCase`` (a.k.a. CapWords: ``ProjectProfile``);
  - **module-level constants** → ``UPPER_SNAKE`` (``MAX_FILES``) — but a
    module-level *assignment* is only treated as a constant when its name is
    already all-caps, so ordinary lowercase module variables are still graded
    as ``snake_case`` (we never demand a name BE a constant).

It is deliberately **CONSERVATIVE**: it flags only names that are clearly in
the wrong style and never anything ambiguous, so a clean run means real
violations, not style nags. A name is flagged only when both (a) it breaks its
rule and (b) it does not match any exclusion below.

Style rules (the regexes, all anchored, ASCII-only):

  - ``snake_case``  → ``^[a-z_][a-z0-9_]*$``  (lowercase, digits, underscores;
    a leading underscore for "private" is fine: ``_helper``).
  - ``PascalCase``  → ``^[A-Z][a-zA-Z0-9]*$`` AND contains at least one
    lowercase letter, so a class can't masquerade as a constant
    (``HTTPServer`` is accepted — it starts upper and has lowercase; ``HTTP``
    is treated as acronym-ish and NOT flagged, see below).
  - ``UPPER_SNAKE`` → ``^[A-Z_][A-Z0-9_]*$``  (all-caps words + underscores).

Exclusions (never flagged — these are the "ambiguous / conventional" cases):

  - **dunders**: any ``__name__`` (``__init__``, ``__all__``, …);
  - **single characters**: loop / math vars (``i``, ``x``, ``T``) — too short
    to carry a convention;
  - **test files & fixtures**: paths whose parts include ``tests`` /
    ``fixtures`` / ``examples``, or whose filename starts with ``test_`` or
    ends ``_test.py`` (pytest helpers freely use ``setUp``-style names);
  - **known framework / stdlib-protocol names**: camelCase methods every
    Python author is expected to spell exactly (``setUp``, ``tearDown``,
    ``maxDiff``, ``assertEqual``-style, ``addCleanup``, ``do_GET``, …);
  - **all-caps "function/variable" names** (would-be constants): a function or
    variable named ``FOO`` is left alone — it's plausibly an intended constant
    or alias, which is ambiguous, not a clear camelCase slip;
  - **class names that are all-caps acronyms** (``HTTP``, ``XML``): ambiguous
    between an acronym class and a constant, so never flagged.

Public API: :func:`analyze_naming(root, max_files=500) -> NamingAudit`.

Pure and deterministic — no clock, no randomness, no network, no I/O beyond
reading the source files under ``root``. Empty / missing roots return an empty,
all-zero :class:`NamingAudit`. Same tree in → byte-identical audit out.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import iter_source_files

__all__ = ["NamingAudit", "analyze_naming"]

# ── style regexes (anchored, ASCII) ─────────────────────────────────────────
_SNAKE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_PASCAL_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
_UPPER_SNAKE_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_HAS_LOWER_RE = re.compile(r"[a-z]")

# Maximum number of violations reported, to keep output bounded and readable.
_MAX_VIOLATIONS = 20

# camelCase / mixedCase names that are stdlib- or framework-mandated spellings.
# Flagging these would be a false positive: the author has no choice.
_FRAMEWORK_NAMES = frozenset({
    # unittest.TestCase protocol
    "setUp", "tearDown", "setUpClass", "tearDownClass",
    "setUpModule", "tearDownModule", "addCleanup", "addTypeEqualityFunc",
    "maxDiff", "longMessage",
    # http.server / BaseHTTPRequestHandler dispatch
    "do_GET", "do_POST", "do_PUT", "do_DELETE", "do_HEAD",
    # common asyncio / protocol callbacks that are stdlib-cased
    "connectionMade", "connectionLost", "dataReceived",
})


def _is_dunder(name: str) -> bool:
    """A ``__name__`` magic identifier — never graded (convention, not choice)."""
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _is_excluded_name(name: str) -> bool:
    """Names excluded regardless of declaration kind: dunders, single chars,
    and framework-mandated spellings."""
    if _is_dunder(name):
        return True
    if len(name) <= 1:
        return True
    return name in _FRAMEWORK_NAMES


def _is_test_or_fixture(rel_path: str) -> bool:
    """True for test files and fixture/example trees, which freely use
    non-PEP 8 names (``setUp``, ``CamelCaseFixture``) by design."""
    parts = Path(rel_path).parts
    if any(part in ("tests", "fixtures", "examples") for part in parts):
        return True
    name = Path(rel_path).name
    return name.startswith("test_") or name.endswith("_test.py")


def _is_snake(name: str) -> bool:
    return bool(_SNAKE_RE.match(name))


def _is_pascal(name: str) -> bool:
    # Must start uppercase, be alnum, AND carry a lowercase letter — so an
    # all-caps acronym (``HTTP``) is NOT accepted as Pascal (it's ambiguous
    # with a constant and handled by the caller, which simply skips it).
    return bool(_PASCAL_RE.match(name)) and bool(_HAS_LOWER_RE.search(name))


def _is_upper_snake(name: str) -> bool:
    return bool(_UPPER_SNAKE_RE.match(name))


@dataclass
class NamingAudit:
    """Result of a naming-convention audit over a source tree.

    ``functions`` / ``classes`` / ``variables`` count how many *graded*
    declarations of each kind were seen (after exclusions); ``violations``
    lists the clear breaches, capped at ~20 and deterministically sorted by
    ``(module, kind, name)``. ``files_scanned`` is the number of source files
    actually parsed."""

    files_scanned: int = 0
    functions: int = 0
    classes: int = 0
    variables: int = 0
    violations: list[dict] = field(default_factory=list)


def _check_function(name: str) -> str | None:
    """Return ``"snake_case"`` if a function/method name clearly breaks snake
    case, else ``None``. All-caps names are left alone (ambiguous constant)."""
    if _is_snake(name) or _is_upper_snake(name):
        return None
    return "snake_case"


def _check_class(name: str) -> str | None:
    """Return ``"PascalCase"`` if a class name clearly breaks Pascal case,
    else ``None``. All-caps acronym names (``HTTP``) are left alone."""
    if _is_pascal(name) or _is_upper_snake(name):
        return None
    return "PascalCase"


def _check_assignment(name: str) -> str | None:
    """Grade a module-level assignment target.

    An all-caps name is treated as a constant and must be valid
    ``UPPER_SNAKE``; otherwise the name is graded as a ``snake_case`` variable.
    We never *require* a name to be a constant, so a lowercase module variable
    is only flagged when it isn't snake_case (e.g. ``myVar``)."""
    if _is_upper_snake(name):
        return None  # already a well-formed constant
    if name.isupper():
        # all-caps but with illegal characters for a constant — clear breach
        return "UPPER_SNAKE"
    if _is_snake(name):
        return None
    return "snake_case"


class _Collector(ast.NodeVisitor):
    """Walks one module's AST, counting graded declarations and recording
    violations. Module-level assignments are graded as constants/variables;
    function/class defs are graded wherever they appear (top level or nested,
    method or inner function)."""

    def __init__(self, module: str) -> None:
        self.module = module
        self.functions = 0
        self.classes = 0
        self.variables = 0
        self.violations: list[dict] = []
        self._depth = 0  # statement nesting; 0 == module body

    def _record(self, name: str, kind: str, expected: str) -> None:
        self.violations.append({
            "module": self.module,
            "name": name,
            "kind": kind,
            "expected_style": expected,
        })

    def _visit_def(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.functions += 1
        name = node.name
        if not _is_excluded_name(name):
            expected = _check_function(name)
            if expected is not None:
                self._record(name, "function", expected)
        self._descend(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_def(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_def(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes += 1
        name = node.name
        if not _is_excluded_name(name):
            expected = _check_class(name)
            if expected is not None:
                self._record(name, "class", expected)
        self._descend(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # Only module-level (depth 0) simple-name targets are graded as
        # variables/constants. Inside functions/classes the casing intent is
        # too varied (locals, attributes) to flag conservatively.
        if self._depth == 0:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._grade_var(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self._depth == 0 and isinstance(node.target, ast.Name):
            self._grade_var(node.target.id)
        self.generic_visit(node)

    def _grade_var(self, name: str) -> None:
        if _is_excluded_name(name):
            return
        self.variables += 1
        expected = _check_assignment(name)
        if expected is not None:
            self._record(name, "variable", expected)

    def _descend(self, node: ast.AST) -> None:
        """Recurse into a def/class body with the nesting depth raised, so
        assignments inside it are not graded as module constants."""
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1


def _analyze_source(module: str, source: str) -> _Collector | None:
    """Parse one module's source and collect its declarations. Unparsable
    source returns ``None`` (the file is skipped, not counted)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    collector = _Collector(module)
    collector.generic_visit(tree)
    return collector


def analyze_naming(root: str | Path, max_files: int = 500) -> NamingAudit:
    """Audit naming-convention consistency under ``root`` against PEP 8 casing.

    Walks at most ``max_files`` source files (sorted, worktree-pruned via
    :func:`iter_source_files`, so the cap is deterministic), grading each
    function/method, class, and module-level variable/constant. Returns a
    :class:`NamingAudit` with per-kind counts and up to ~20 clear violations,
    sorted by ``(module, kind, name)``.

    Empty-safe: a missing or empty ``root`` yields an all-zero audit. Pure and
    deterministic — no clock, randomness, or network."""
    audit = NamingAudit()
    root = Path(root)
    if not root.exists():
        return audit

    scanned = 0
    all_violations: list[dict] = []
    for path in iter_source_files(root):
        if scanned >= max_files:
            break
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            continue
        rel = str(path.relative_to(root))
        if _is_test_or_fixture(rel):
            # Still count it as scanned so callers can reason about coverage,
            # but never grade test/fixture names.
            scanned += 1
            continue
        collector = _analyze_source(rel, source)
        if collector is None:
            continue
        scanned += 1
        audit.files_scanned += 1
        audit.functions += collector.functions
        audit.classes += collector.classes
        audit.variables += collector.variables
        all_violations.extend(collector.violations)

    # Deterministic order, then cap. Sorting BEFORE the cap guarantees the same
    # 20 are reported regardless of file-walk order within a build.
    all_violations.sort(key=lambda v: (v["module"], v["kind"], v["name"]))
    audit.violations = all_violations[:_MAX_VIOLATIONS]
    return audit
