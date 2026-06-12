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

_SKIPPED_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules",
                 ".apex", ".epistemic", "dist", "build"}

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


def plan_rename(project_root: str | Path, old: str, new: str) -> RenamePlan:
    """Build the full multi-file rename plan, or its blockers."""
    plan = RenamePlan(old=old, new=new)
    for name in (old, new):
        if not name.isidentifier() or keyword.iskeyword(name):
            plan.blockers.append(f"'{name}' is not a valid identifier")
            return plan
    if old == new:
        plan.blockers.append("old and new names are identical")
        return plan

    root = Path(project_root)
    files = _py_files(root)
    trees: dict[str, ast.Module] = {}
    for rel, text in files:
        try:
            trees[rel] = ast.parse(text)
        except SyntaxError:
            continue

    # The symbol must be defined exactly once, at top level.
    definitions = [
        (rel, node) for rel, tree in trees.items() for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == old
    ]
    if not definitions:
        plan.blockers.append(f"no top-level definition of '{old}' found")
        return plan
    if len(definitions) > 1:
        where = ", ".join(rel for rel, _ in definitions)
        plan.blockers.append(f"'{old}' is defined in {len(definitions)} modules ({where}) — ambiguous")
        return plan

    defmod, def_node = definitions[0]
    plan.defined_in = defmod
    dotted = defmod[:-3].replace("/", ".")
    sources = dict(files)

    for rel, tree in trees.items():
        source = sources[rel]
        lines = source.splitlines(keepends=True)
        spans: list[Span] = []
        bare_rewrite = False
        module_aliases: set[str] = set()

        if rel == defmod:
            bare_rewrite = True
            header = _def_header_span(lines, def_node, old)
            if header is None:
                plan.blockers.append(f"{rel}: could not locate the definition header")
                continue
            spans.append(header)
        else:
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

        if bare_rewrite:
            if _local_shadow(tree, old):
                plan.blockers.append(
                    f"{rel}: '{old}' is shadowed by a parameter/local — rename there first")
                continue
            if new in _top_level_bindings(tree):
                plan.blockers.append(f"{rel}: '{new}' is already bound — collision")
                continue
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

        if not spans:
            continue
        rewritten = _apply_spans(source, spans, old, new)
        if rewritten is None:
            plan.blockers.append(f"{rel}: a located span no longer matches '{old}'")
            continue
        if rewritten != source:
            plan.originals[rel] = source
            plan.new_contents[rel] = rewritten
            plan.edits_by_file[rel] = len(set(spans))

    # Dynamic references can't be rewritten safely — surface them for a human.
    for rel, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == old:
                plan.warnings.append(
                    f"{rel}:{node.lineno}: string literal '{old}' — "
                    "dynamic reference? check manually")
    return plan


def apply_rename(project_root: str | Path, plan: RenamePlan, verify: bool = True) -> dict:
    """Write the plan, verify with the project's tests, roll back on failure."""
    if not plan.ok:
        return {"applied": False, "reason": "; ".join(plan.blockers) or "nothing to rename"}
    root = Path(project_root)
    for rel, content in plan.new_contents.items():
        (root / rel).write_text(content, encoding="utf-8")
    out: dict = {"applied": True, "changed_files": sorted(plan.new_contents),
                 "edits": sum(plan.edits_by_file.values()), "warnings": plan.warnings}
    if not verify:
        return out

    from app.engine.proof_of_fix import summarize_test_run
    from app.skills.execution.run_tests import RunTestsSkill

    summary = RunTestsSkill().run(str(root))
    out["verified"] = bool(summary.ok)
    out["test_evidence"] = summarize_test_run(summary)
    if summary.ok or not summary.commands:
        out["rolled_back"] = False
        return out
    for rel, original in plan.originals.items():
        (root / rel).write_text(original, encoding="utf-8")
    out.update(applied=False, rolled_back=True,
               reason="tests failed after rename; all files restored")
    return out
