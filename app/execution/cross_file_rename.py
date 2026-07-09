"""Cross-file rename — Apex's first multi-file refactoring operation.

Renames a top-level function or class ACROSS the project: the definition,
the import statements, and the call sites. Edits are precise text spans
located by the AST (no unparse round-trip), so comments and formatting
survive untouched.

Conservative by design — any ambiguity is a **blocker**, never a guess:
  - the symbol must be defined exactly once in the project;
  - the new name must not already be bound in any file that gets a bare-name
    rewrite;
  - a local shadow of the old name (a parameter or local assignment inside a
    function) blocks that file's rewrite;
  - dynamic references (string literals equal to the symbol) are surfaced as
    warnings for a human to check.

Apply is test-verified with automatic rollback, like every Apex change.
Deterministic, stdlib-only.
"""

from __future__ import annotations

import ast
import base64
import difflib
import json
import keyword
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# The canonical tree-walk exclusion (`.claude` worktrees, caches, venvs, build
# output). Kept as a module alias so the many importers of this name — and
# `_py_files` below — stay on the single source of truth in app.engine.skip_dirs.
from app.engine.skip_dirs import SKIPPED_DIRS as _SKIPPED_DIRS
from app.execution._apply_verify import (
    run_full_suite_verification,
    stamp_coverage_strength,
)

# A rename span: (line, col_start, col_end) — 1-based line, 0-based cols.
Span = tuple[int, int, int]


@dataclass
class RenamePlan:
    old: str
    new: str
    defined_in: str = ""
    originals: dict[str, str] = field(default_factory=dict)
    new_contents: dict[str, str] = field(default_factory=dict)
    edits_by_file: dict[str, int] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Optional pinned pytest node IDs (``file::test_name``) this change makes
    # green — the specific tests the planner KNOWS its fill satisfies (e.g.
    # implement-stub's per-symbol pinned tests for the stubs it filled). When
    # set, the impact-scoped apply gate still runs the whole impacted test FILES
    # (so a currently-green test the change would regress is caught), but it
    # DESELECTS ``scoped_excluded_nodes`` — the pre-existing-red nodes of any
    # unsynthesizable sibling — so they don't veto the landable change. Empty →
    # whole-file behavior, byte-identical to before. Sorted/deterministic.
    scoped_test_nodes: list[str] = field(default_factory=list)
    scoped_excluded_nodes: list[str] = field(default_factory=list)
    # The EXISTING source files this plan's CREATED files are DERIVED FROM — used
    # ONLY to seed the impact scope when a created file has no importing test yet.
    # A brand-new file (e.g. scaffold-from-protocol's ``<stem>_impl.py``) is not
    # imported by any test, so ``impacted_test_files(new_contents)`` is empty and
    # the impact-scope gate degrades to the FULL suite — re-introducing the very
    # cross-module deadlock ``scope_verify`` exists to kill. The correct proof
    # scope for a created file is the impacted tests of the file(s) it derives from
    # (for scaffold-from-protocol, the PROTOCOL module: any test that exercises it
    # exercises the concrete implementer too). Default ``[]`` => the scope seed
    # ``list(new_contents) + []`` is identical to today for every other plan, so
    # ``_verify_scoped`` is byte-for-byte unchanged. Sorted/deterministic.
    derived_from: list[str] = field(default_factory=list)
    # The canonical native-intelligence idiom shapes (``p0 + p1`` …) this plan
    # LANDED that ONLY a project-learned body supplied (no fixed template fit) —
    # pure metadata the apply engine forwards to the experience memory
    # (``native_proof_memory``) ONLY after the plan verifies and lands, so a
    # proven idiom is remembered and ranked first next time. Empty for every plan
    # that didn't land a native-only body (the common case), so this is inert for
    # all existing objectives; never affects what the plan writes or how it gates.
    native_shapes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers and bool(self.new_contents)

    def render_diff(self) -> str:
        parts = []
        for rel in sorted(self.new_contents):
            parts.append("".join(difflib.unified_diff(
                self.originals[rel].splitlines(keepends=True),
                self.new_contents[rel].splitlines(keepends=True),
                fromfile=f"a/{rel}", tofile=f"b/{rel}",
            )))
        return "\n".join(p for p in parts if p)


def bind_resolved_definition(
    plan: "RenamePlan",
    definition: "tuple[str, ast.FunctionDef] | None",
    sources: dict[str, str],
) -> "tuple[str, ast.FunctionDef, str, str] | None":
    """Unpack a resolved ``(defmod, fn)`` definition into the caller's working
    set — stamping ``plan.defined_in`` and deriving the dotted module path and
    source text — or ``None`` when resolution failed (the caller returns its
    plan unchanged, blockers already recorded by the resolver). The shared
    seam of every project-wide signature planner (param-add, param-drop):
    behaviour-identical to the four lines each used to inline."""
    if definition is None:
        return None
    defmod, fn = definition
    plan.defined_in = defmod
    dotted = defmod[:-3].replace("/", ".")
    return defmod, fn, dotted, sources[defmod]


def _is_fixture_path(path: str) -> bool:
    """Test / fixture / example files are REFUSED — Apex never edits the suite it
    is gated by. Shared by the single-file-rewrite objective plans."""
    p = path.replace("\\", "/").lower()
    name = Path(p).name
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or name.startswith("test_") or name.endswith("_test.py")
        or name == "conftest.py"
    )


# Known NON-LIBRARY scripts, by BASENAME at ANY path: packaging / Sphinx /
# task-runner / framework-manage / generated version files. Nobody ``import``s them
# for an API — a single-file rewrite there (``@final``, ``__all__``, ``@dataclass``,
# …) is config / side-effect / generated-file noise (round-19 re-audit F4: ``@final``
# landed on a class in ``docs/conf.py``). The CANONICAL copy lives here, on the
# shared single-file path, so EVERY single-file objective skips them; the round-19
# ``objectives/wire_module_exports.py`` (``_is_library_module`` + ``_SCRIPT_DENYLIST``)
# carries its own copy of the same names (it cannot import from here without a cycle
# — that objective imports ``plan_source_rewrite`` FROM this module). Kept
# deliberately small and explicit.
#
# DELIBERATELY DENYLIST-ONLY (a documented NARROWING of the auditor's proposed
# ``_is_library_module``): the auditor also proposed gating on "the containing dir
# has an ``__init__.py``". That over-excludes in THIS repo — Apex ships many real,
# imported PEP-420 NAMESPACE packages with NO ``__init__.py`` (``app/intent/``,
# ``app/k8s/``, ``app/metrics/``, ``app/plugins/``, ``app/benchmarking/``,
# ``app/validation/``, ``app/integrations/``, plus every ``scripts/*.py``). The
# ``__init__.py`` test would (1) make the broad-land family REFUSE ~21 genuine
# library modules it can and should rewrite, and (2) drop those same modules from
# the quality-scan index (dedup / complexity / dead-code — the grader's backbone),
# HIDING real findings in them. Every CONFIRMED F4 case (``docs/conf.py``,
# ``setup.py``, ``noxfile.py``, ``conftest.py``) is a denylisted BASENAME, so the
# denylist closes the proven hole with ZERO collateral damage; the ``__init__.py``
# heuristic is the part that was too broad, so it is dropped.
_SCRIPT_DENYLIST = frozenset({
    "setup.py", "conf.py", "conftest.py", "manage.py",
    "noxfile.py", "tasks.py", "_version.py", "version.py",
})


def _is_non_library_file(module_rel: str) -> bool:
    """True when ``module_rel`` is a NON-LIBRARY file a single-file objective must
    skip — a packaging / config / task / generated script nobody imports as an API.

    Pure BASENAME test against :data:`_SCRIPT_DENYLIST` (``setup.py``, ``conf.py``,
    ``conftest.py``, ``manage.py``, ``noxfile.py``, ``tasks.py``, ``_version.py``,
    ``version.py``) at ANY path — so ``docs/conf.py`` (the confirmed round-19 F4
    bug), a root ``setup.py``, and a ``noxfile.py`` are all refused, while a genuine
    ``app/intent/parser.py`` (a real PEP-420 namespace-package module with no
    ``__init__.py``) is KEPT. Deterministic, no filesystem touch. See the
    ``_SCRIPT_DENYLIST`` note for why this is intentionally denylist-only rather than
    also requiring an ``__init__.py``."""
    return Path(module_rel.replace("\\", "/")).name in _SCRIPT_DENYLIST


def plan_source_rewrite(
    project_root: str | Path, module_rel: str, operator: str,
    transform: Callable[[str], str | None],
) -> RenamePlan:
    """A :class:`RenamePlan` that applies a whole-module SOURCE ``transform``.

    The shared shape of every single-file develop objective (infer-type-hints,
    document-signature, …): refuse a test/fixture file AND a non-library file
    (packaging / config / task / generated script — ``setup.py``, ``docs/conf.py``,
    ``noxfile.py``, ``conftest.py``, …), read the module, run ``transform(source)``,
    and record the single rewrite with its original (so the verified-apply engine
    can roll it back if the suite fails) when it changes something — otherwise an
    empty no-op plan (``None``/unchanged ⇒ nothing provable to do). One source of
    truth, so a new single-file objective is a one-liner and the boilerplate is
    never re-copied.

    The non-library gate (alongside the test/fixture refusal) is what stops the
    WHOLE broad-land single-file family — add-final, freeze-dataclass,
    document-signature, … — from firing on files nobody imports as an API (the
    round-19 re-audit caught ``@final`` landing on a class in ``docs/conf.py``). A
    skipped non-library file is an honest no-op, not a failure."""
    plan = RenamePlan(old=module_rel, new=operator)
    if _is_fixture_path(module_rel):
        return plan  # never touch a test/fixture file
    if _is_non_library_file(module_rel):
        return plan  # packaging / config / task script — nobody imports it as an API
    try:
        source = (Path(project_root) / module_rel).read_text(encoding="utf-8")
    except OSError:
        return plan  # unreadable — no-op
    new_source = transform(source)
    if new_source is None or new_source == source:
        return plan  # nothing provable to do — no-op
    plan.originals[module_rel] = source
    plan.new_contents[module_rel] = new_source
    plan.edits_by_file[module_rel] = 1
    return plan


def _py_files(root: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if any(part in _SKIPPED_DIRS for part in Path(rel).parts):
            continue
        try:
            out.append((rel, path.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    return out


def _top_level_bindings(tree: ast.Module) -> set[str]:
    """Names bound at module top level (defs, classes, imports, assignments)."""
    bound: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for t in ast.walk(node):
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                    bound.add(t.id)
    return bound


def _local_shadow(tree: ast.Module, name: str) -> bool:
    """Is ``name`` ever a parameter or a local (in-function) assignment?
    If so, bare-name rewriting in this file would touch a DIFFERENT symbol."""
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        args = fn.args
        every = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        if args.vararg:
            every.append(args.vararg)
        if args.kwarg:
            every.append(args.kwarg)
        if any(a.arg == name for a in every):
            return True
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Name) and sub.id == name and isinstance(sub.ctx, ast.Store):
                return True
    return False


def _def_header_span(source_lines: list[str], node: ast.AST, name: str) -> Span | None:
    """The span of the name token in a ``def``/``class`` header line."""
    line = source_lines[node.lineno - 1]
    m = re.search(rf"\b{re.escape(name)}\b", line[node.col_offset:])
    if not m:
        return None
    start = node.col_offset + m.start()
    return (node.lineno, start, start + len(name))


def _apply_spans(source: str, spans: list[Span], old: str, new: str) -> str | None:
    """Replace each span (verified to equal ``old``) with ``new``.
    Returns None when any span doesn't match — the caller treats it as a blocker."""
    lines = source.splitlines(keepends=True)
    for line_no, start, end in sorted(set(spans), reverse=True):
        text = lines[line_no - 1]
        if text[start:end] != old:
            return None
        lines[line_no - 1] = text[:start] + new + text[end:]
    return "".join(lines)


def _invalid_name_blocker(old: str, new: str) -> str | None:
    """The first refusal reason among the up-front name checks, or None.
    A bad identifier/keyword (either side) or a no-op rename refuses before any
    file is touched — same ordering as inline checks (old, then new, then equality)."""
    for name in (old, new):
        if not name.isidentifier() or keyword.iskeyword(name):
            return f"'{name}' is not a valid identifier"
    if old == new:
        return "old and new names are identical"
    return None


def _parse_trees(files: list[tuple[str, str]]) -> dict[str, ast.Module]:
    """Parse each readable source; files that don't parse are silently skipped
    (a rename can't reason about a syntactically broken module)."""
    trees: dict[str, ast.Module] = {}
    for rel, text in files:
        try:
            trees[rel] = ast.parse(text)
        except (SyntaxError, RecursionError, MemoryError):
            continue
    return trees


def _find_unique_definition(
    trees: dict[str, ast.Module], old: str,
) -> tuple[tuple[str, ast.AST] | None, str | None]:
    """Locate the single top-level def/class of ``old``.

    Returns ``((rel, node), None)`` on success, or ``(None, blocker)`` when the
    symbol is missing or ambiguously defined in more than one module."""
    definitions = [
        (rel, node) for rel, tree in trees.items() for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == old
    ]
    if not definitions:
        return None, f"no top-level definition of '{old}' found"
    if len(definitions) > 1:
        where = ", ".join(rel for rel, _ in definitions)
        return None, f"'{old}' is defined in {len(definitions)} modules ({where}) — ambiguous"
    return definitions[0], None


def _import_spans(tree: ast.Module, dotted: str, old: str) -> tuple[list[Span], bool, set[str]]:
    """Spans for the import statements that bring ``old`` into a non-def file.

    Returns ``(spans, bare_rewrite, module_aliases)``: ``from … import old`` adds
    a span and (when unaliased) requests a bare-name rewrite of call sites;
    ``import pkg.mod`` records the binding so ``pkg.mod.old`` attributes are caught."""
    spans: list[Span] = []
    bare_rewrite = False
    module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == dotted:
            for alias in node.names:
                if alias.name == old:
                    spans.append((alias.lineno, alias.col_offset,
                                  alias.col_offset + len(old)))
                    if alias.asname is None:
                        bare_rewrite = True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == dotted:
                    module_aliases.add(alias.asname or alias.name)
    return spans, bare_rewrite, module_aliases


def _collect_file_spans(
    plan: RenamePlan, rel: str, tree: ast.Module, lines: list[str],
    defmod: str, def_node: ast.AST, dotted: str, old: str, new: str,
) -> list[Span] | None:
    """Every rename span in one file, or None when the file is to be skipped.

    Mirrors the per-file branch logic exactly: the def file contributes its
    header; other files contribute import spans. A bare-name rewrite adds the
    call sites unless a local shadow or new-name collision blocks the file; a
    module alias adds the matching attribute spans. Blockers/skips append to
    ``plan`` and return None so the caller drops the file."""
    spans: list[Span] = []
    bare_rewrite = False
    module_aliases: set[str] = set()

    if rel == defmod:
        bare_rewrite = True
        header = _def_header_span(lines, def_node, old)
        if header is None:
            plan.blockers.append(f"{rel}: could not locate the definition header")
            return None
        spans.append(header)
    else:
        spans, bare_rewrite, module_aliases = _import_spans(tree, dotted, old)

    if bare_rewrite:
        if _local_shadow(tree, old):
            plan.blockers.append(
                f"{rel}: '{old}' is shadowed by a parameter/local — rename there first")
            return None
        if new in _top_level_bindings(tree):
            plan.blockers.append(f"{rel}: '{new}' is already bound — collision")
            return None
        spans += [
            (n.lineno, n.col_offset, n.col_offset + len(old))
            for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == old
        ]
    if module_aliases:
        for n in ast.walk(tree):
            if (isinstance(n, ast.Attribute) and n.attr == old
                    and ast.unparse(n.value) in module_aliases):
                spans.append((n.end_lineno, n.end_col_offset - len(old), n.end_col_offset))

    return spans


def _plan_file_rewrite(
    plan: RenamePlan, rel: str, tree: ast.Module, source: str,
    defmod: str, def_node: ast.AST, dotted: str, old: str, new: str,
) -> None:
    """Record one file's edit on ``plan`` (or its blocker), if it changes."""
    lines = source.splitlines(keepends=True)
    spans = _collect_file_spans(plan, rel, tree, lines, defmod, def_node, dotted, old, new)
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


def _warn_dynamic_references(plan: RenamePlan, trees: dict[str, ast.Module], old: str) -> None:
    """Surface string literals equal to ``old`` — dynamic references a span
    rewrite can't safely touch, so a human checks them. Never blocks."""
    for rel, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == old:
                plan.warnings.append(
                    f"{rel}:{node.lineno}: string literal '{old}' — "
                    "dynamic reference? check manually")


def plan_rename(project_root: str | Path, old: str, new: str) -> RenamePlan:
    """Build the full multi-file rename plan, or its blockers."""
    plan = RenamePlan(old=old, new=new)
    name_blocker = _invalid_name_blocker(old, new)
    if name_blocker is not None:
        plan.blockers.append(name_blocker)
        return plan

    root = Path(project_root)
    files = _py_files(root)
    trees = _parse_trees(files)

    # The symbol must be defined exactly once, at top level.
    definition, def_blocker = _find_unique_definition(trees, old)
    if definition is None:
        plan.blockers.append(def_blocker)
        return plan

    defmod, def_node = definition
    plan.defined_in = defmod
    dotted = defmod[:-3].replace("/", ".")
    sources = dict(files)

    for rel, tree in trees.items():
        _plan_file_rewrite(
            plan, rel, tree, sources[rel], defmod, def_node, dotted, old, new)

    # Dynamic references can't be rewritten safely — surface them for a human.
    _warn_dynamic_references(plan, trees, old)
    return plan


def _capture_raw_originals(root: Path, plan: RenamePlan,
                           created: list[str]) -> dict[str, bytes]:
    """Every pre-existing target's CURRENT on-disk bytes, for byte-exact
    rollback — captured once, immediately after ``created`` is known, before
    the journal write and before any tree write (the narrowest possible
    window; no wider than the text-mode design already tolerated, see the
    module's rollback risk notes).

    Iterates ``plan.originals`` (the same domain :func:`_rollback` restores)
    so a created-but-double-tracked file (``plan.originals[rel] == ""``) is
    naturally excluded via ``created``, never desynced. A created file (no
    original to restore) or an unreadable path is simply omitted — the
    caller then falls back to ``plan.originals`` text for that file
    (fail-closed: absence here never crashes a rollback)."""
    made = set(created)
    out: dict[str, bytes] = {}
    for rel in plan.originals:
        if rel in made:
            continue
        try:
            out[rel] = (root / rel).read_bytes()
        except OSError:
            continue
    return out


def _rollback(root: Path, plan: RenamePlan, created: list[str],
             raw_originals: dict[str, bytes] | None = None) -> None:
    """Restore edited files to their originals and delete files the plan created
    (a never-existed file has no original, so it must be removed, not rewritten).

    A created file is DOUBLE-TRACKED: several planners record its ``originals``
    entry as ``""`` (generate_usage_doc, scaffold_from_protocol, wire_exports,
    pin_doctest, …). So restore ONLY pre-existing files — those in ``originals``
    but NOT ``created`` — and delete EVERY created file regardless of its
    ``originals`` membership; otherwise a created file would be rewritten empty
    (step 1) and then skipped by the delete (step 2), leaking a 0-byte artifact.

    ``raw_originals`` (default ``None`` ⇒ byte-identical to before) is the
    :func:`_capture_raw_originals` map of exact pre-apply bytes; when a
    file's raw bytes were captured, restore writes THOSE bytes
    (``write_bytes``) so CRLF/BOM/no-trailing-newline originals come back
    exactly instead of being normalized through ``plan.originals`` text. A
    file absent from ``raw_originals`` (never captured, or capture failed)
    degrades to the original text-mode restore — never a crash."""
    made = set(created)
    for rel, original in plan.originals.items():
        if rel not in made:  # only un-edit files that existed before the plan
            raw_bytes = (raw_originals or {}).get(rel)
            if raw_bytes is not None:
                (root / rel).write_bytes(raw_bytes)
            else:
                (root / rel).write_text(original, encoding="utf-8")
    for rel in created:
        if (root / rel).exists():
            try:
                (root / rel).unlink()
            except OSError:
                pass


def _baseline_for_files(baseline_failing: frozenset[str], files: list[str]) -> frozenset[str]:
    """The baseline failing-node set RESTRICTED to the impacted ``files``.

    The delta-green scoped gate diffs against ONLY the pre-existing reds that live
    in the test files it actually runs (a node in some other file is irrelevant to
    a scoped run that never executes it), so the baseline is scoped to the SAME
    node set the verify uses. A node id's file is everything before ``::``; a bare
    collection-error file node (no ``::``) is matched by its own path. Deterministic
    sorted-stable ``frozenset`` — no clock/random."""
    wanted = set(files)
    return frozenset(n for n in baseline_failing if n.split("::", 1)[0] in wanted)


def _verify_scoped(root: Path, plan: RenamePlan,
                   baseline_failing: frozenset[str] | None = None,
                   ) -> tuple[bool, dict] | None:
    """Verify a change by running ONLY the tests that exercise its changed files.

    Returns ``(ok, evidence)`` when an impacted-test scope exists, or ``None``
    when nothing covers the change (so the caller falls back to the full suite —
    an unreferenced change can't be impact-verified). Deterministic: the scope
    comes from AST import linkage, and the tests run in a fresh process.

    DELTA-GREEN (``baseline_failing`` not None ⇒ a RED baseline): the impacted
    files may themselves carry a pre-existing failure unrelated to the change, so
    an absolute-green scoped gate would veto a correct fill. In that mode the
    scoped run drops ``-x`` (so EVERY failure surfaces, not just the first) and
    threads ``--continue-on-collection-errors`` (so its node ids are byte-comparable
    to the baseline capture), the after-failing nodes are parsed, and the verdict is
    ``regressed_functions`` over the baseline RESTRICTED to the impacted files
    (:func:`_baseline_for_files`) — keep iff NO previously-green test broke.
    ``baseline_failing=None`` (the default, and the ONLY state on a green baseline)
    is the established ``-x`` command, byte-identical to before."""
    import os
    from app.execution.target_env import inherited_pythonpath
    import subprocess

    from app.engine.test_impact import impacted_test_files
    from app.skills.execution.run_tests import RunTestsSkill

    impacted = impacted_test_files(root, list(plan.new_contents) + plan.derived_from)
    if not impacted:
        return None
    # Default scope: the whole impacted test files, byte-identical to before. When
    # the plan names the pre-existing-red nodes of an unsynthesizable sibling
    # (``scoped_excluded_nodes``), DESELECT exactly those — a node red BEFORE the
    # change isn't made worse by it, so it must not veto the landable fill — while
    # the rest of each impacted file still runs, so a currently-green test the
    # change would REGRESS is still caught (never-fake-green). Deselects are sorted
    # for a deterministic command; empty → command shape unchanged.
    deselect: list[str] = []
    for node in sorted(plan.scoped_excluded_nodes):
        deselect += ["--deselect", node]
    delta = baseline_failing is not None
    # DELTA-GREEN drops ``-x`` (run ALL impacted tests, so the full after-failing
    # set is observable, not just the first failure) and threads the collection-
    # error flag so its node ids match the baseline capture. Absolute-green keeps
    # the exact established ``-x`` shape — green baseline is byte-identical.
    flags = ["-p", "no:cacheprovider"]
    flags = (["--continue-on-collection-errors", *flags] if delta
             else ["-x", *flags])
    # INTERPRETER + PATH PARITY with the full-suite runner (audit 2026-07-08,
    # finding 3): this gate used to run ``sys.executable`` — Apex's OWN Python —
    # while the baseline capture, the full-suite gate, and the pytest-missing
    # probe all use the TARGET's ``.venv`` when present. On an external project
    # whose deps live only in its venv, the impacted tests would then SKIP
    # (``importorskip``) or collection-error under Apex's interpreter: a fake
    # green or a false red the other gates would never produce. Same for the
    # PYTHONPATH: the runner also serves a genuine separated ``src``/``lib``
    # flat-module dir (``_import_roots``); with only ``root`` on the path a
    # scoped run on that layout collection-errors and every landing is vetoed.
    runner = RunTestsSkill()
    proc = subprocess.run(
        [runner._python_for(root), "-m", "pytest", "-q",
         *flags, *deselect, *impacted],
        cwd=str(root), capture_output=True, text=True, env={
            **os.environ,
            # Never write ``.pyc`` for the project under test. CPython's default
            # bytecode invalidation is whole-SECOND granular, so a module this gate
            # imports while still at its pre-change bytes, then rewritten and
            # re-tested within the same second, can be served STALE on the next
            # run — making the end-of-session regression backstop read pre-change
            # behaviour and miss a real regression NON-deterministically. Mirrors
            # the import-oracle / test-shield probes, which already set this.
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join(
                p for p in [*runner._import_roots(root), inherited_pythonpath()]
                if p)})
    if not delta:
        ok = proc.returncode == 0
        return ok, {"scoped": True, "tests": impacted,
                    "deselected": sorted(plan.scoped_excluded_nodes), "passed": ok}
    return _scoped_delta_verdict(proc, impacted, plan, baseline_failing)


def _scoped_delta_verdict(proc: object, impacted: list[str], plan: RenamePlan,
                          baseline_failing: frozenset[str],
                          ) -> tuple[bool, dict]:
    """The DELTA-GREEN verdict for a scoped run: keep iff no previously-green test
    broke, tolerating the impacted files' pre-existing reds.

    Parses the after-failing nodes from the scoped output, restricts the cached
    baseline to the impacted files, and diffs at TEST-FUNCTION granularity via
    ``regressed_functions``. ``ok`` is True iff that diff is empty (never-fake-green:
    a baseline-green test now red — including a NEW collection error — still blocks).
    The evidence discloses, honestly, how many pre-existing failures it tolerated
    and what (if anything) the change introduced.

    VALIDITY guard first: the diff is only sound when pytest genuinely reached
    its per-test summary — exit 0, or exit 1 WITH at least one parsed node line.
    A collapsed run (usage error 4, nothing collected 5, interrupted 2, internal
    error 3, or an interpreter whose ``-m pytest`` never launched: exit 1 with
    zero node lines) yields an empty after-set for the WRONG reason, and diffing
    it would read as "no regressions" — fake green. Such a run FAILS the move
    (fail closed, honest ``delta_run_invalid`` evidence), never verifies it."""
    from app.execution._apply_verify import (
        _NODE_LINE,
        delta_green_disclosure,
        regressed_functions,
    )

    text = (getattr(proc, "stdout", "") or "") + (getattr(proc, "stderr", "") or "")
    after = frozenset(_NODE_LINE.findall(text))
    rc = getattr(proc, "returncode", None)
    if rc not in (0, 1) or (rc == 1 and not after):
        return False, {
            "scoped": True, "tests": impacted,
            "deselected": sorted(plan.scoped_excluded_nodes), "passed": False,
            "delta_run_invalid": True, "returncode": rc,
        }
    scoped_baseline = _baseline_for_files(baseline_failing, impacted)
    introduced = regressed_functions(scoped_baseline, after)
    ok = not introduced
    return ok, {
        "scoped": True, "tests": impacted,
        "deselected": sorted(plan.scoped_excluded_nodes), "passed": ok,
        "delta_green": delta_green_disclosure(scoped_baseline, after),
    }


def _withhold_uncovered(root: Path, plan: RenamePlan, created: list[str],
                        out: dict, tier: int = 0,
                        raw_originals: dict[str, bytes] | None = None) -> bool:
    """COVERED-ONLY gate (opt-in): roll back a move whose green suite cannot
    actually VOUCH for the change at its risk ``tier``, and report it as withheld
    — not failed. True when the move was withheld (so the caller returns the
    withheld result), False otherwise (the move stands, byte-identical to a run
    without the gate).

    The verdict is the SHARED ``risk_tiers.coverage_verifies`` — the SAME one the
    bridge's ``apply_step`` uses, so the two sweep paths can never disagree: for a
    Tier-1 behaviour change a mere module import (``coverage == "module"``) is a
    FALSE green and is withheld (only a test that names the changed function
    vouches); for a Tier-0 semantics-preserving move ``module`` is sound proof and
    lands. ``none`` (no test references the change at all) never verifies and is
    always withheld. Deterministic + static: it only reads the stamped coverage."""
    from app.execution.risk_tiers import coverage_verifies

    if coverage_verifies(tier, str(out.get("coverage") or "none")):
        return False
    _rollback(root, plan, created, raw_originals)
    out.update(applied=False, rolled_back=True, withheld_uncovered=True,
               reason="withheld (covered-only): no test exercises this change at "
                      "the level its risk needs — previewed, not landed "
                      "(use --allow-weak to land)")
    return True


def _write_pending_journal(root: Path, plan: RenamePlan, created: list[str],
                           raw_originals: dict[str, bytes] | None = None) -> Path:
    """Persist an on-disk intent record BEFORE the tree is touched.

    A per-move apply writes the planned files and only then verifies — a hard
    kill (OOM, SIGKILL, a dropped container) in that window used to leave the
    target tree MODIFIED with no record of what changed or how to undo it
    (observed live: the interrupted ``pyparsing`` campaign). The journal holds
    every planned file's pre-apply text (``null`` for a created file) so a
    human — or a future reconcile pass — can restore byte-exactly. It is
    written to ``.apex/`` (already scan-excluded), cleared the moment the move
    SETTLES (kept, rolled back, or declined), and deterministic (sorted keys,
    no clock).

    ``changed`` stays exactly as before (universal-newline TEXT, ``null`` for
    a created file) so a naive/future reader that only understands this key
    degrades to today's behaviour, never worse. When ``raw_originals`` (the
    :func:`_capture_raw_originals` map) holds a file whose captured bytes
    differ from ``plan.originals[rel]`` re-encoded as UTF-8 — i.e. a CRLF/BOM/
    no-trailing-newline original that ``changed``'s text form would lose — an
    ADDITIVE sibling key ``changed_b64`` records that file's exact bytes,
    base64-encoded (ASCII-safe for JSON), keyed by the same relative path.
    ``changed_b64`` takes PRECEDENCE over ``changed`` for a reconcile reader
    that understands it; omitted entirely when empty, so a plain-LF apply's
    journal is byte-identical to before this field existed."""
    path = root / ".apex" / "pending-apply.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    changed_b64 = {
        rel: base64.b64encode(raw).decode("ascii")
        for rel, raw in (raw_originals or {}).items()
        if raw != (plan.originals.get(rel) or "").encode("utf-8")
    }
    payload = {
        "schema": "apex-pending-apply/1",
        "changed": {rel: plan.originals.get(rel)
                    for rel in sorted(plan.new_contents)},
        "created": sorted(created),
    }
    if changed_b64:
        payload["changed_b64"] = changed_b64
    path.write_text(json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8")
    return path


def _clear_pending_journal(path: Path) -> None:
    """Remove the settled move's intent record (missing is fine — a plan that
    never reached the write phase has nothing to clear)."""
    try:
        path.unlink()
    except OSError:
        pass


def _stale_plan_reason(root: Path, plan: RenamePlan) -> str | None:
    """The STALENESS PRECONDITION check for :func:`apply_rename`, extracted to
    keep that function under the complexity ceiling.

    A plan snapshots each target file's pre-edit text into ``plan.originals``
    at PLAN time; if the file on disk no longer matches that snapshot,
    something (a prior apply in the same composed campaign, a concurrent
    edit) changed it since planning — applying this plan would silently
    discard that change or splice against stale line/column offsets. Returns
    a refusal reason, or ``None`` when every target's on-disk text still
    matches its snapshot. A plan with no ``originals`` entry for a target (or
    the target not yet existing — a plan that CREATES a file) is unaffected:
    the guard only fires when there is a snapshot to compare against.
    Deterministic order (sorted) so the reported ``rel`` never varies."""
    for rel in sorted(plan.new_contents):
        if rel not in plan.originals or not (root / rel).exists():
            continue
        if (root / rel).read_text(encoding="utf-8") != plan.originals[rel]:
            return (f"stale plan: {rel} changed on disk since planning — "
                    "replan before applying")
    return None


def apply_rename(project_root: str | Path, plan: RenamePlan, verify: bool = True,
                 impact_scope: bool = False, covered_only: bool = False,
                 tier: int = 0,
                 baseline_failing: frozenset[str] | None = None) -> dict:
    """Write the plan, verify with the project's tests, roll back on failure.

    With ``impact_scope`` the per-move gate runs only the tests that exercise the
    changed files (seconds, not the whole suite) — the speed that lets the
    organism develop its own large body. The full suite stays the backstop, and
    is used automatically when nothing covers the change.

    With ``covered_only`` (opt-in, default off ⇒ byte-identical to today) a move
    whose green suite cannot VOUCH for the change at its risk ``tier`` — the
    false-green blind spot — is ROLLED BACK and reported as ``withheld_uncovered``,
    not landed. ``tier`` (default 0, so every non-covered_only caller is
    byte-identical) is the move's behaviour-change risk: a Tier-1 rewrite needs a
    test that NAMES the changed function (a mere module import is a false green),
    while a Tier-0 semantics-preserving move is soundly proven by module coverage.
    This is the SAFE-by-default autonomous sweep policy: a broad ``develop --auto
    --apply`` never silently lands a move a green suite can't vouch for.

    ``baseline_failing`` is the DELTA-GREEN gate (default None ⇒ byte-identical to
    today). The caller captures, ONCE per campaign and caches, the SET of test
    node ids that already FAIL at baseline; when it is non-None (the campaign saw a
    RED baseline) the change VERIFIES iff it broke no previously-green test
    (tolerating the pre-existing reds it did not cause), so a correct, harmless
    contribution lands on a project that wasn't 100% green on checkout. A fully-
    green baseline passes None here, so the gate is unchanged and never-fake-green
    holds: delta-green forgives ONLY tests already red at baseline; a regression is
    still rolled back."""
    if not plan.ok:
        return {"applied": False, "reason": "; ".join(plan.blockers) or "nothing to rename"}
    root = Path(project_root)
    stale = _stale_plan_reason(root, plan)
    if stale is not None:
        return {"applied": False, "reason": stale}
    # A plan may CREATE files (e.g. a generated test) as well as rewrite them.
    # Note which targets did not exist before writing, so a rollback can delete
    # them — restoring `originals` only un-edits files that were already there;
    # a never-existed file has no original to restore and must be removed.
    created = [rel for rel in plan.new_contents if not (root / rel).exists()]
    # BYTE-EXACT ROLLBACK CAPTURE: raw originals are read as bytes immediately
    # after ``created`` is known — before the journal write and before any
    # tree write — so a later rollback restores CRLF/BOM/no-trailing-newline
    # originals exactly instead of losing them through universal-newline text
    # (:func:`_capture_raw_originals`). Fail-closed: a file that can't be read
    # as bytes here is simply absent, and every downstream rollback path
    # degrades to the existing ``plan.originals`` text restore for it.
    raw_originals = _capture_raw_originals(root, plan, created)
    # INTERRUPT SAFETY (audit 2026-07-08): the intent journal lands on disk
    # BEFORE the tree is touched, and the write+verify window is guarded so a
    # KeyboardInterrupt/SIGTERM mid-verify rolls the move back byte-exactly and
    # re-raises — the tree is never left silently modified by a cancelled run.
    # Only a hard kill (SIGKILL/OOM) can escape the guard, and then the journal
    # remains as the honest, reconcilable record of exactly what was in flight.
    journal = _write_pending_journal(root, plan, created, raw_originals)
    try:
        return _write_verify_settle(root, plan, created, verify, impact_scope,
                                    covered_only, tier, baseline_failing,
                                    raw_originals)
    except BaseException:
        _rollback(root, plan, created, raw_originals)
        raise
    finally:
        _clear_pending_journal(journal)


def _write_verify_settle(root: Path, plan: RenamePlan, created: list[str],
                         verify: bool, impact_scope: bool, covered_only: bool,
                         tier: int,
                         baseline_failing: frozenset[str] | None,
                         raw_originals: dict[str, bytes] | None = None) -> dict:
    """The write→verify→settle body of :func:`apply_rename`, extracted so the
    caller can wrap it in the interrupt guard (and stay under the complexity
    ceiling). Behaviour byte-identical to the previously-inline tail (the APPLY
    write below stays text — only rollback of ORIGINALS needs to be byte-exact,
    via ``raw_originals`` threaded to every rollback call)."""
    for rel, content in plan.new_contents.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content, encoding="utf-8")
    out: dict = {"applied": True, "changed_files": sorted(plan.new_contents),
                 "edits": sum(plan.edits_by_file.values()), "warnings": plan.warnings}
    if not verify:
        return out

    # Coverage inputs for the maintain-path strength grader: the plan already
    # carries each changed file's before (``originals``) and after
    # (``new_contents``) text, so a green suite can be graded function/module/none
    # honestly instead of stamped a bare ``verified`` (the hardening maintain got).
    strength_inputs = (
        sorted(plan.new_contents),
        {rel: plan.originals.get(rel) for rel in plan.new_contents},
        dict(plan.new_contents),
    )

    # Fast path: verify against just the impacted tests. Falls through to the full
    # suite when nothing covers the change (scoped result is None). The impacted
    # run can still stamp only ``module`` (a smoke import that names the module but
    # not the changed function), which is a FALSE green for a Tier-1 move — so the
    # covered-only gate is applied on this path too, not just the full-suite tail.
    if impact_scope:
        scoped = _verify_impact_scope(root, plan, created, out, strength_inputs,
                                      covered_only, tier, baseline_failing,
                                      raw_originals)
        if scoped is not None:
            return scoped

    if run_full_suite_verification(root, out, strength_inputs=strength_inputs,
                                   baseline_failing=baseline_failing):
        # COVERED-ONLY (opt-in): the full suite went green, but if it can't vouch
        # for the change at its tier (``none`` for any tier; ``module`` for Tier 1)
        # it is the false-green blind spot — withhold it (roll back, report
        # ``withheld_uncovered``) rather than land it. Off ⇒ byte-identical.
        if covered_only:
            _withhold_uncovered(root, plan, created, out, tier, raw_originals)
        return out
    _rollback(root, plan, created, raw_originals)
    out.update(applied=False, rolled_back=True,
               reason="tests failed after rename; all files restored")
    return out


def _verify_impact_scope(root: Path, plan: RenamePlan, created: list[str],
                         out: dict, strength_inputs, covered_only: bool = False,
                         tier: int = 0,
                         baseline_failing: frozenset[str] | None = None,
                         raw_originals: dict[str, bytes] | None = None,
                         ) -> dict | None:
    """The impact-scoped verification tail of :func:`apply_rename`, extracted to
    keep that function under the complexity ceiling (behaviour byte-identical when
    ``covered_only`` is off and no ``baseline_failing`` is threaded).

    Runs ONLY the tests that import the changed files. Returns the finished result
    dict when an impacted scope existed (green ⇒ kept + coverage-graded, then the
    covered-only gate may withhold a tier-unvouched move; red ⇒ rolled back), or
    ``None`` when nothing covers the change so the caller falls through to the
    full-suite backstop. ``baseline_failing`` is forwarded to :func:`_verify_scoped`
    for the DELTA-GREEN scoped gate (tolerate the impacted files' pre-existing reds,
    block a true regression); None ⇒ the established absolute-green scoped run."""
    scoped = _verify_scoped(root, plan, baseline_failing)
    if scoped is None:
        return None
    ok, evidence = scoped
    out["verified"] = ok
    out["test_evidence"] = evidence
    # Surface the delta-green disclosure (P5 honesty) when the scoped run ran in
    # that mode — additive: absolute-green evidence has no such key, so a green
    # baseline's result is byte-identical.
    if isinstance(evidence, dict) and "delta_green" in evidence:
        out["delta_green"] = evidence["delta_green"]
    if ok:
        # The scoped run executed the tests that IMPORT the changed files, so the
        # suite genuinely exercised them — grade exactly how strongly
        # (function vs. module) with the same machinery.
        stamp_coverage_strength(root, out, *strength_inputs)
        out["rolled_back"] = False
        # COVERED-ONLY: a smoke-only import stamps ``module``, a false green for a
        # Tier-1 behaviour change — withhold it here too. Off ⇒ byte-identical.
        if covered_only:
            _withhold_uncovered(root, plan, created, out, tier, raw_originals)
        return out
    _rollback(root, plan, created, raw_originals)
    out.update(applied=False, rolled_back=True,
               reason="impacted tests failed after change; files restored")
    return out
