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
import difflib
import keyword
import re
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


def _rollback(root: Path, plan: RenamePlan, created: list[str]) -> None:
    """Restore edited files to their originals and delete files the plan created
    (a never-existed file has no original, so it must be removed, not rewritten)."""
    for rel, original in plan.originals.items():
        (root / rel).write_text(original, encoding="utf-8")
    for rel in created:
        if rel not in plan.originals:
            try:
                (root / rel).unlink()
            except OSError:
                pass


def _verify_scoped(root: Path, plan: RenamePlan) -> tuple[bool, dict] | None:
    """Verify a change by running ONLY the tests that exercise its changed files.

    Returns ``(ok, evidence)`` when an impacted-test scope exists, or ``None``
    when nothing covers the change (so the caller falls back to the full suite —
    an unreferenced change can't be impact-verified). Deterministic: the scope
    comes from AST import linkage, and the tests run in a fresh process."""
    import os
    import subprocess
    import sys

    from app.engine.test_impact import impacted_test_files

    impacted = impacted_test_files(root, list(plan.new_contents))
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
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
         *deselect, *impacted],
        cwd=str(root), capture_output=True, text=True, env={
            **os.environ,
            "PYTHONPATH": str(root) + os.pathsep + os.environ.get("PYTHONPATH", "")})
    ok = proc.returncode == 0
    return ok, {"scoped": True, "tests": impacted,
                "deselected": sorted(plan.scoped_excluded_nodes), "passed": ok}


def apply_rename(project_root: str | Path, plan: RenamePlan, verify: bool = True,
                 impact_scope: bool = False) -> dict:
    """Write the plan, verify with the project's tests, roll back on failure.

    With ``impact_scope`` the per-move gate runs only the tests that exercise the
    changed files (seconds, not the whole suite) — the speed that lets the
    organism develop its own large body. The full suite stays the backstop, and
    is used automatically when nothing covers the change."""
    if not plan.ok:
        return {"applied": False, "reason": "; ".join(plan.blockers) or "nothing to rename"}
    root = Path(project_root)
    # A plan may CREATE files (e.g. a generated test) as well as rewrite them.
    # Note which targets did not exist before writing, so a rollback can delete
    # them — restoring `originals` only un-edits files that were already there;
    # a never-existed file has no original to restore and must be removed.
    created = [rel for rel in plan.new_contents if not (root / rel).exists()]
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

    # Fast path: verify against just the impacted tests. Falls through to the
    # full suite when nothing covers the change (scoped result is None).
    if impact_scope:
        scoped = _verify_scoped(root, plan)
        if scoped is not None:
            ok, evidence = scoped
            out["verified"] = ok
            out["test_evidence"] = evidence
            if ok:
                # The scoped run executed the tests that IMPORT the changed
                # files, so the suite genuinely exercised them — grade exactly
                # how strongly (function vs. module) with the same machinery.
                stamp_coverage_strength(root, out, *strength_inputs)
                out["rolled_back"] = False
                return out
            _rollback(root, plan, created)
            out.update(applied=False, rolled_back=True,
                       reason="impacted tests failed after change; files restored")
            return out

    if run_full_suite_verification(root, out, strength_inputs=strength_inputs):
        return out
    _rollback(root, plan, created)
    out.update(applied=False, rolled_back=True,
               reason="tests failed after rename; all files restored")
    return out
