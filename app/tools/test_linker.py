from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import iter_source_files


def count_test_functions(root: str | Path, test_files: list[str]) -> int:
    """Total ``test*`` functions/methods across the given linked test files.

    A depth-aware coverage proxy: one file with many real tests covers a module
    far better than a single thin one, so risk/fragility signals should weigh
    this, not the linked-*file* count (which a single stub would inflate).
    """
    root = Path(root)
    total = 0
    for rel in test_files:
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8", errors="ignore"))
        except (OSError, SyntaxError, RecursionError, MemoryError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                total += 1
    return total


@dataclass
class TestCoverageResult:
    module_to_tests: dict[str, list[str]] = field(default_factory=dict)
    untested_modules: list[str] = field(default_factory=list)
    critical_untested_modules: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _TestInfo:
    """Per-test-file values that are identical for every module we link.

    They depend only on the test file (its path and contents), never on the
    module being matched, so they are computed ONCE in
    :meth:`TestLinker._build_test_index` and reused across all modules. The
    expensive parts — reading the file from disk, lower-casing it, and parsing
    its imports — used to run once per (module, test) pair (or, for imports,
    not at all); the index collapses that to one read + one lower-case + one
    parse per test file, leaving the per-pair matching identical.
    """

    rel: str  # root-relative path, OS-native (the value emitted unchanged)
    stem: str  # lower-cased file stem
    text: str  # lower-cased file contents
    imports: frozenset[str] = field(default_factory=frozenset)  # lower-cased dotted names actually imported
    loaded_filenames: frozenset[str] = field(default_factory=frozenset)  # lower-cased bare "x.py" string literals


def _resolved_import_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    """Fully-dotted names an ``import``/``from ... import`` statement binds.

    ``import a.b.c`` yields ``["a.b.c"]``. ``from a.b import c, d`` yields
    ``["a.b.c", "a.b.d"]`` — this is what a flat text search cannot tell apart
    from an unrelated dotted-path mention, notably the multi-name parenthesized
    form (``from a.b import (\\n    c,\\n    d,\\n)``), which never places the
    package prefix and the submodule name next to each other in the source.
    A relative import (``node.level > 0``) is skipped: its target depends on
    the IMPORTING file's own package, which is never guessed at here (a link
    built on a guess is exactly the kind of claim this module must not make).
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level or not node.module:
        return []
    return [f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*"]


@dataclass(frozen=True)
class _TestReferences:
    """The two AST-derived reference sets a test file can carry, both lower-cased."""

    imports: frozenset[str] = frozenset()  # fully-dotted names actually imported
    loaded_filenames: frozenset[str] = frozenset()  # bare "x.py" names passed to a loader call


def _call_name(node: ast.Call) -> str:
    """The callee's own (unqualified) name, e.g. ``spec_from_file_location``
    for both ``spec_from_file_location(...)`` and ``importlib.util.
    spec_from_file_location(...)``. Empty for a called expression that is
    neither a bare name nor an attribute access (e.g. a call result)."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _loader_call_py_args(node: ast.Call) -> list[str]:
    """Bare ``"x.py"`` string arguments of a call that LOADS a module by
    filename, e.g. ``_load("preflight.py")`` or
    ``importlib.util.spec_from_file_location(name, "preflight.py")``.

    Restricted to calls whose own name contains "load" (``_load``,
    ``load_module``, ``spec_from_file_location``...): a bare ``"x.py"`` string
    literal is common in this project's OWN synthetic-project test builders
    for a completely different reason — writing a FIXTURE file
    (``(tmp_path / "app" / "core.py").write_text(...)``) — and is not, on its
    own, evidence that this test loads that filename as the module under
    test. Requiring the "load"-named call context is what tells the two apart.
    """
    if "load" not in _call_name(node).lower():
        return []
    args = list(node.args) + [kw.value for kw in node.keywords]
    return [
        arg.value for arg in args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        and arg.value.endswith(".py") and "/" not in arg.value and "\\" not in arg.value
    ]


def _parse_test_references(source: str) -> _TestReferences:
    """Every fully-dotted import AND every filename passed to a dynamic-load
    call in ``source``, best-effort + AST-based (one parse for both).

    Imports: AST-based rather than a text search so a string that merely LOOKS
    like an import — inside a docstring, or a fixture literal built to exercise
    some OTHER file's import-rewriting logic — is never mistaken for a real
    one, and a multi-name parenthesized import resolves correctly (see
    :func:`_resolved_import_names`).

    Loaded filenames: a module under a directory that is not an importable
    package (e.g. ``scripts/``) is often exercised by loading it dynamically —
    ``importlib.util.spec_from_file_location(name, root / "scripts" /
    "preflight.py")`` via a small ``_load(name)`` test helper — which is a
    plain string argument, not an import statement (see
    :func:`_loader_call_py_args`).

    Unparseable source contributes neither (never crash the scan; the caller
    falls back to its other, text-based signals).
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return _TestReferences()
    imports: set[str] = set()
    filenames: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.update(n.lower() for n in _resolved_import_names(node))
        elif isinstance(node, ast.Call):
            filenames.update(n.lower() for n in _loader_call_py_args(node))
    return _TestReferences(imports=frozenset(imports), loaded_filenames=frozenset(filenames))


def _stem_tokens(stem: str) -> list[str]:
    """Split a lower-cased file stem into its underscore-delimited word tokens.

    Empty tokens are dropped, so a leading/doubled underscore — the
    ``_private`` naming convention's ``test__private`` test file — never
    produces a spurious blank leading token.

    (Deliberately illustrated with a made-up ``_private``/``widget``-style name
    rather than a real module in this project: this module's OWN file is itself
    discovered as a "test file" by :meth:`TestLinker._discover_test_files`
    (its name starts with ``test_``), so any real project word used here in a
    docstring would be scanned as if it were test content and could feed a
    link back to that real module — exactly the false-claim failure mode this
    file exists to close.)
    """
    return [t for t in stem.split("_") if t]


def _stem_names_module(module_stem: str, test_stem: str) -> bool:
    """Whole-token containment: the module's own words, in order, must appear
    as a contiguous run inside the test file's tokens.

    A bare ``module_stem in test_stem`` substring check let a short stem like
    ``widget`` match inside an unrelated word that merely starts the same way
    (``widgetry``) — a different WORD, not a reference to it — so the raw
    substring check claimed a link there anyway: exactly a link that does not
    exist. Tokenizing both sides first means only a real, whole-word match
    counts.
    """
    module_tokens = _stem_tokens(module_stem)
    if not module_tokens:
        return False
    test_tokens = _stem_tokens(test_stem)
    n = len(module_tokens)
    return any(test_tokens[i:i + n] == module_tokens for i in range(len(test_tokens) - n + 1))


def _boundary_ok(text: str, index: int) -> bool:
    """True when ``index`` is NOT inside a longer identifier: out of range, or
    the character there is not alphanumeric/underscore."""
    return index < 0 or index >= len(text) or not (text[index].isalnum() or text[index] == "_")


def _contains_standalone(text: str, needle: str) -> bool:
    """``needle in text``, but guarded on both edges by an identifier boundary.

    A plain substring test lets a short module name match *inside* a longer
    identifier that merely starts the same way (a needle of ``import widget``
    is also a substring of the unrelated ``import widgetfactory``), or inside
    an unrelated identifier that happens to start with it (a fixture class
    named ``Widget`` is not a reference to a ``widget`` module). Guarding both
    edges means only a standalone occurrence of the whole needle counts.
    Returns ``False`` for an empty needle (nothing to claim).
    """
    if not needle:
        return False
    start = 0
    while True:
        idx = text.find(needle, start)
        if idx == -1:
            return False
        if _boundary_ok(text, idx - 1) and _boundary_ok(text, idx + len(needle)):
            return True
        start = idx + 1


class TestLinker:
    __test__ = False

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def analyze(self, critical_modules: list[str] | None = None) -> TestCoverageResult:
        critical_modules = critical_modules or []
        tests = self._discover_test_files()
        modules = self._discover_module_files()

        # Project-wide work hoisted out of the per-module loop: read + lower-case
        # every test file exactly ONCE (was re-read M times, once per module).
        # Each test contributes an immutable ``_TestInfo`` reused across modules.
        test_index = self._build_test_index(tests)

        module_to_tests: dict[str, list[str]] = {}
        untested_modules: list[str] = []

        for module in modules:
            linked_tests = self._find_linked_tests(module, test_index)
            module_to_tests[module] = linked_tests
            # `__init__.py` is packaging, not behavior — it must never surface
            # as "untested" (a stub for it would test nothing and its name
            # collides across every package).
            if not linked_tests and Path(module).name != "__init__.py":
                untested_modules.append(module)

        critical_untested_modules = [m for m in critical_modules if m in set(untested_modules)]

        return TestCoverageResult(
            module_to_tests=module_to_tests,
            untested_modules=untested_modules,
            critical_untested_modules=critical_untested_modules,
        )

    def _discover_test_files(self) -> list[Path]:
        tests: list[Path] = []
        for path in iter_source_files(self.root):
            rel = str(path.relative_to(self.root)).lower()
            if rel.startswith("tests/") or "/tests/" in f"/{rel}/" or path.stem.startswith("test_"):
                tests.append(path)
        return tests

    def _discover_module_files(self) -> list[str]:
        modules: list[str] = []
        for path in iter_source_files(self.root):
            rel = str(path.relative_to(self.root))
            rel_lower = rel.lower()
            if rel_lower.startswith("tests/") or "/tests/" in f"/{rel_lower}/" or path.stem.startswith("test_"):
                continue
            if path.stem == "__init__":
                continue
            modules.append(rel)
        return sorted(modules)

    def _build_test_index(self, tests: list[Path]) -> list[_TestInfo]:
        """Read + lower-case + parse-references of every test file ONCE,
        preserving discovery order.

        Order is kept identical to ``tests`` so that, after the per-module
        ``sorted(dict.fromkeys(...))``, the linked list is byte-for-byte what the
        old per-call scan produced. Each file is read (and its references
        parsed) a single time here instead of once per module. References are
        resolved from the RAW source (not the lower-cased copy): the AST does
        not care about case, and the resolved names are lower-cased once here
        so every downstream comparison stays a plain lower-case match.
        """
        indexed = []
        for test_path in tests:
            raw = self._safe_read(test_path)
            refs = _parse_test_references(raw)
            indexed.append(_TestInfo(
                rel=str(test_path.relative_to(self.root)),
                stem=test_path.stem.lower(),
                text=raw.lower(),
                imports=refs.imports,
                loaded_filenames=refs.loaded_filenames,
            ))
        return indexed

    def _find_linked_tests(self, module: str, tests: list[_TestInfo]) -> list[str]:
        module_path = Path(module)
        module_stem = module_path.stem.lower()
        module_dotted = ".".join(module_path.with_suffix("").parts).lower()
        expected_test_name = f"test_{module_stem}"
        parent_name = module_path.parent.name.lower()
        # A plausible QUALIFIED reference from a test to the module's own
        # package: dotted (pkg.mod), path-style (pkg/mod) or a flattened
        # identifier (pkg_mod) — each checked standalone below. This replaced
        # "the parent dir's name and the module's stem both appear SOMEWHERE,
        # INDEPENDENTLY, in the file": once the parent name was a common
        # package (e.g. a directory called "objectives") and the stem a common
        # short word (e.g. "base"), that pair showed up in almost every test in
        # the project for reasons that had nothing to do with this particular
        # module — the two words merely happening to both occur somewhere in
        # 100+ lines of unrelated source is not evidence they reference each
        # other.
        parent_refs = (
            (f"{parent_name}.{module_stem}", f"{parent_name}/{module_stem}", f"{parent_name}_{module_stem}")
            if parent_name else ()
        )

        linked: list[str] = []
        for test in tests:
            rel = test.rel
            test_stem = test.stem
            test_text = test.text

            if test_stem == expected_test_name or _stem_names_module(module_stem, test_stem):
                linked.append(rel)
                continue
            # The precise signal: an actual parsed import statement resolves to
            # this exact module, including ``from pkg import (a, b, c)`` — a
            # multi-name parenthesized import that never places the package
            # prefix and the submodule name next to each other in the source,
            # so a flat text search cannot see it (see _resolved_import_names).
            if module_dotted in test.imports:
                linked.append(rel)
                continue
            # A module under a directory that is not an importable package
            # (e.g. ``scripts/``) is often loaded dynamically by filename
            # instead — ``_load("preflight.py")`` via
            # ``importlib.util.spec_from_file_location`` — a real convention
            # in this project's own test suite (see _parse_test_references).
            if module_path.name.lower() in test.loaded_filenames:
                linked.append(rel)
                continue
            # Fallback text signals for what AST parsing does not cover (a
            # dynamic ``importlib.import_module("a.b.c")`` string built from an
            # f-string rather than a plain literal, a "# module: a.b.c" header
            # comment) — still boundary-safe, so a longer dotted name that
            # merely starts the same way is not mistaken for this one.
            if _contains_standalone(test_text, module_dotted):
                linked.append(rel)
                continue
            if any(_contains_standalone(test_text, ref) for ref in parent_refs):
                linked.append(rel)
                continue

        return sorted(dict.fromkeys(linked))

    def _safe_read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
