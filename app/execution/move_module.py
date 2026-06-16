"""Move/rename a module across the project — BS-5's second operation.

Moves ``app/old.py`` to ``app/sub/new.py`` and rewrites every import and
module-qualified usage in the project: ``import app.old [as m]``,
``from app.old import X``, ``from app import old [as m]``, and bare
``app.old.X`` attribute chains. Same span-edit machinery as
:mod:`cross_file_rename` — AST-located text edits, comments untouched.

Conservative blockers, never guesses:
  - destination already exists / source missing / dunder modules;
  - relative imports that reference the moved module (convert to absolute
    first — rewriting them correctly is context-dependent);
  - the moved file itself using relative imports while changing directory;
  - a multi-alias ``from pkg import old, other`` when the parent package
    changes (splitting one statement into two is a human's call);
  - bare-name rewrites guarded against local shadows and collisions.

Apply is test-verified with full rollback. Deterministic, stdlib-only.
"""

from __future__ import annotations

import ast
import difflib
import keyword
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.execution.cross_file_rename import (
    Span,
    _apply_spans,
    _local_shadow,
    _py_files,
    _top_level_bindings,
)


@dataclass
class MovePlan:
    src: str
    dst: str
    originals: dict[str, str] = field(default_factory=dict)   # rel -> old content
    new_contents: dict[str, str] = field(default_factory=dict)  # rel -> new content (same path)
    moved_content: str = ""                                    # content to write at dst
    init_files: list[str] = field(default_factory=list)       # __init__.py to create
    edits_by_file: dict[str, int] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers and bool(self.moved_content)

    def render_diff(self) -> str:
        parts = [f"rename {self.src} -> {self.dst}"]
        for rel in sorted(self.new_contents):
            parts.append("".join(difflib.unified_diff(
                self.originals[rel].splitlines(keepends=True),
                self.new_contents[rel].splitlines(keepends=True),
                fromfile=f"a/{rel}", tofile=f"b/{rel}",
            )))
        for init in self.init_files:
            parts.append(f"create {init}")
        return "\n".join(p for p in parts if p)


def _dotted(rel: str) -> str:
    return rel[:-3].replace("/", ".")


def _module_expr_spans(tree: ast.Module, dotted: str) -> list[Span] | None:
    """Spans of every expression whose source is exactly ``dotted``
    (the value side of ``app.old.X`` chains and bare module references).
    Returns None when one spans multiple lines (we won't guess)."""
    spans: list[Span] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Attribute, ast.Name)):
            try:
                if ast.unparse(node) != dotted:
                    continue
            except Exception:
                continue
            if node.end_lineno != node.lineno:
                return None
            spans.append((node.lineno, node.col_offset, node.end_col_offset))
    return spans


def _from_module_span(lines: list[str], node: ast.ImportFrom, dotted: str) -> Span | None:
    """The span of the module path in a ``from <dotted> import …`` line."""
    line = lines[node.lineno - 1]
    m = re.search(rf"\b{re.escape(dotted)}\b", line[node.col_offset:])
    if not m:
        return None
    start = node.col_offset + m.start()
    return (node.lineno, start, start + len(dotted))


def _resolves_to(importer_rel: str, node: ast.ImportFrom, target_dotted: str) -> bool:
    """Does this *relative* import resolve to the moved module (or pull the
    module name out of its parent package)?"""
    if node.level == 0:
        return False
    pkg_parts = importer_rel.split("/")[:-1]
    if node.level - 1 > len(pkg_parts):
        return False
    base = pkg_parts[: len(pkg_parts) - (node.level - 1)]
    module_parts = (node.module or "").split(".") if node.module else []
    resolved = ".".join([*base, *module_parts])
    if resolved == target_dotted:
        return True
    target_parent, _, target_stem = target_dotted.rpartition(".")
    return resolved == target_parent and any(a.name == target_stem for a in node.names)


@dataclass
class _Names:
    """The dotted forms and parent/stem splits the rewriters need."""
    old_dotted: str
    new_dotted: str
    old_parent: str
    old_stem: str
    new_parent: str
    new_stem: str


def _validate_move_paths(plan: MovePlan, root: Path, src_rel: str, dst_rel: str) -> bool:
    """Append any path blockers; return True when planning may continue."""
    for rel, label in ((src_rel, "source"), (dst_rel, "destination")):
        if not rel.endswith(".py") or Path(rel).name.startswith("__"):
            plan.blockers.append(f"{label} must be a regular .py module: {rel}")
    if plan.blockers:
        return False
    if not (root / src_rel).exists():
        plan.blockers.append(f"source not found: {src_rel}")
    if (root / dst_rel).exists():
        plan.blockers.append(f"destination already exists: {dst_rel}")
    for part in _dotted(dst_rel).split("."):
        if not part.isidentifier() or keyword.iskeyword(part):
            plan.blockers.append(f"destination path component '{part}' is not importable")
    return not plan.blockers


def _parse_trees(files: list[tuple[str, str]]) -> dict[str, ast.Module]:
    """Parse each (rel, text) pair, skipping files that don't parse."""
    trees: dict[str, ast.Module] = {}
    for rel, text in files:
        try:
            trees[rel] = ast.parse(text)
        except SyntaxError:
            continue
    return trees


def _moved_file_blocks_on_dir_change(src_rel: str, dst_rel: str, tree: ast.Module) -> bool:
    """The moved file itself: relative imports break when the directory changes."""
    same_dir = Path(src_rel).parent == Path(dst_rel).parent
    return not same_dir and any(
        isinstance(n, ast.ImportFrom) and n.level >= 1 for n in ast.walk(tree)
    )


def _import_node_spans(
    plan: MovePlan, rel: str, tree: ast.Module, node: ast.Import, names: _Names,
    spans: list[tuple[Span, str, str]],
) -> None:
    """Handle a plain ``import app.old [as m]`` node, appending its edits.

    On a multi-line reference it records a blocker and empties ``spans`` (in
    place), mirroring the original ``spans = []; break`` of the inner loop."""
    for alias in node.names:
        if alias.name == names.old_dotted:
            spans.append(((alias.lineno, alias.col_offset,
                           alias.col_offset + len(names.old_dotted)),
                          names.old_dotted, names.new_dotted))
            if alias.asname is None:
                expr = _module_expr_spans(tree, names.old_dotted)
                if expr is None:
                    plan.blockers.append(
                        f"{rel}: a `{names.old_dotted}` reference spans multiple lines")
                    spans.clear()
                    break
                spans += [(s, names.old_dotted, names.new_dotted) for s in expr]


def _from_pkg_import_spans(
    plan: MovePlan, rel: str, lines: list[str], node: ast.ImportFrom, names: _Names,
    spans: list[tuple[Span, str, str]],
) -> bool:
    """Handle ``from <old_parent> import <old_stem> [as m]``: the module
    imported by name. Return whether a bare stem rename was triggered."""
    if names.new_parent != names.old_parent and len(node.names) > 1:
        plan.blockers.append(
            f"{rel}:{node.lineno}: `from {names.old_parent} import …` lists several "
            "names and the parent package changes — split it manually")
        return False
    if names.new_parent != names.old_parent:
        span = _from_module_span(lines, node, names.old_parent)
        if span is None:
            plan.blockers.append(f"{rel}:{node.lineno}: could not locate "
                                 f"`{names.old_parent}` in the from-import")
            return False
        spans.append((span, names.old_parent, names.new_parent))
    stem_rename = False
    for alias in node.names:
        if alias.name == names.old_stem:
            spans.append(((alias.lineno, alias.col_offset,
                           alias.col_offset + len(names.old_stem)),
                          names.old_stem, names.new_stem))
            if alias.asname is None and names.old_stem != names.new_stem:
                stem_rename = True
    return stem_rename


def _from_import_node_spans(
    plan: MovePlan, rel: str, lines: list[str], node: ast.ImportFrom, names: _Names,
    spans: list[tuple[Span, str, str]],
) -> bool:
    """Handle a ``from … import …`` node. Return whether it triggered a bare
    stem rename (name-usage rewrites)."""
    if node.level >= 1:
        if _resolves_to(rel, node, names.old_dotted):
            plan.blockers.append(
                f"{rel}:{node.lineno}: relative import of the moved module — "
                "convert to absolute first")
        return False
    if node.module == names.old_dotted:
        span = _from_module_span(lines, node, names.old_dotted)
        if span is None:
            plan.blockers.append(f"{rel}:{node.lineno}: could not locate "
                                 f"`{names.old_dotted}` in the from-import")
            return False
        spans.append((span, names.old_dotted, names.new_dotted))
    elif node.module == names.old_parent and any(
            a.name == names.old_stem for a in node.names):
        return _from_pkg_import_spans(plan, rel, lines, node, names, spans)
    return False


def _collect_import_spans(
    plan: MovePlan, rel: str, tree: ast.Module, lines: list[str], names: _Names,
) -> tuple[list[tuple[Span, str, str]], bool]:
    """Collect (span, old, new) edits for every import form in one file.

    Returns the spans and whether a bare ``from pkg import stem`` rename was
    seen (which pulls in name-usage rewrites). Appends blockers as found."""
    spans: list[tuple[Span, str, str]] = []  # (span, old_text, new_text)
    stem_rename = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            _import_node_spans(plan, rel, tree, node, names, spans)
        elif isinstance(node, ast.ImportFrom):
            if _from_import_node_spans(plan, rel, lines, node, names, spans):
                stem_rename = True

    return spans, stem_rename


def _append_stem_rename_spans(
    plan: MovePlan, rel: str, tree: ast.Module, names: _Names,
    spans: list[tuple[Span, str, str]],
) -> bool:
    """Add name-usage rewrites for a stem rename; return False to skip the file."""
    if _local_shadow(tree, names.old_stem):
        plan.blockers.append(
            f"{rel}: '{names.old_stem}' is shadowed by a parameter/local — rename there first")
        return False
    if names.new_stem in _top_level_bindings(tree):
        plan.blockers.append(f"{rel}: '{names.new_stem}' is already bound — collision")
        return False
    spans += [
        ((n.lineno, n.col_offset, n.col_offset + len(names.old_stem)),
         names.old_stem, names.new_stem)
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id == names.old_stem
    ]
    return True


def _rewrite_source(
    plan: MovePlan, rel: str, source: str, spans: list[tuple[Span, str, str]],
) -> str:
    """Apply per-text span groups so the shared helper's single old->new
    contract holds for each group. Returns the rewritten text (== source on
    failure, after appending a blocker)."""
    rewritten = source
    for old_text in sorted({o for _, o, _ in spans}, key=len, reverse=True):
        group = [s for s, o, _ in spans if o == old_text]
        new_text = next(n for _, o, n in spans if o == old_text)
        result = _apply_spans(rewritten, group, old_text, new_text)
        if result is None:
            plan.blockers.append(f"{rel}: a located span no longer matches `{old_text}`")
            rewritten = source
            break
        rewritten = result
    return rewritten


def _plan_file_rewrite(
    plan: MovePlan, rel: str, source: str, tree: ast.Module, names: _Names,
) -> None:
    """Locate edits in one file and record its rewrite on the plan."""
    lines = source.splitlines(keepends=True)
    spans, stem_rename = _collect_import_spans(plan, rel, tree, lines, names)

    if stem_rename and not _append_stem_rename_spans(plan, rel, tree, names, spans):
        return

    if not spans:
        return
    rewritten = _rewrite_source(plan, rel, source, spans)
    if rewritten != source:
        plan.originals[rel] = source
        plan.new_contents[rel] = rewritten
        plan.edits_by_file[rel] = len(spans)


def _warn_string_literals(plan: MovePlan, trees: dict[str, ast.Module], old_dotted: str) -> None:
    """String literals naming the module are dynamic references — warn only."""
    for rel, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == old_dotted:
                plan.warnings.append(f"{rel}:{node.lineno}: string literal '{old_dotted}' — "
                                     "dynamic reference? check manually")


def _destination_init_files(root: Path, dst_rel: str) -> list[str]:
    """Every package directory on the destination path must be importable."""
    init_files: list[str] = []
    parent = Path(dst_rel).parent
    while str(parent) not in (".", ""):
        init = (parent / "__init__.py").as_posix()
        if not (root / init).exists():
            init_files.append(init)
        parent = parent.parent
    return init_files


def plan_move(project_root: str | Path, src_rel: str, dst_rel: str) -> MovePlan:
    """Build the full module-move plan, or its blockers."""
    src_rel = src_rel.replace("\\", "/")
    dst_rel = dst_rel.replace("\\", "/")
    plan = MovePlan(src=src_rel, dst=dst_rel)
    root = Path(project_root)

    if not _validate_move_paths(plan, root, src_rel, dst_rel):
        return plan

    old_dotted, new_dotted = _dotted(src_rel), _dotted(dst_rel)
    old_parent, _, old_stem = old_dotted.rpartition(".")
    new_parent, _, new_stem = new_dotted.rpartition(".")
    names = _Names(old_dotted, new_dotted, old_parent, old_stem, new_parent, new_stem)

    files = _py_files(root)
    sources = dict(files)
    trees = _parse_trees(files)
    if src_rel not in trees:
        plan.blockers.append(f"{src_rel}: does not parse — fix it before moving")
        return plan

    if _moved_file_blocks_on_dir_change(src_rel, dst_rel, trees[src_rel]):
        plan.blockers.append(
            f"{src_rel}: uses relative imports and changes directory — make them absolute first")

    for rel, tree in trees.items():
        _plan_file_rewrite(plan, rel, sources[rel], tree, names)

    _warn_string_literals(plan, trees, old_dotted)

    # The moved file's own (possibly rewritten) content lands at dst.
    plan.moved_content = plan.new_contents.pop(src_rel, sources[src_rel])
    plan.originals.setdefault(src_rel, sources[src_rel])
    plan.edits_by_file.pop(src_rel, None)

    plan.init_files = _destination_init_files(root, dst_rel)
    return plan


def apply_move(project_root: str | Path, plan: MovePlan, verify: bool = True) -> dict:
    """Execute the move, verify with the project's tests, roll back on failure."""
    if not plan.ok:
        return {"applied": False, "reason": "; ".join(plan.blockers) or "nothing to move"}
    root = Path(project_root)

    (root / plan.dst).parent.mkdir(parents=True, exist_ok=True)
    for init in plan.init_files:
        (root / init).write_text("", encoding="utf-8")
    (root / plan.dst).write_text(plan.moved_content, encoding="utf-8")
    (root / plan.src).unlink()
    for rel, content in plan.new_contents.items():
        (root / rel).write_text(content, encoding="utf-8")

    out: dict = {"applied": True, "moved": f"{plan.src} -> {plan.dst}",
                 "changed_files": sorted(plan.new_contents),
                 "created": list(plan.init_files),
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

    # Tests failed -> restore everything exactly as it was.
    for rel, original in plan.originals.items():
        (root / rel).write_text(original, encoding="utf-8")
    (root / plan.dst).unlink(missing_ok=True)
    for init in plan.init_files:
        (root / init).unlink(missing_ok=True)
    out.update(applied=False, rolled_back=True,
               reason="tests failed after move; all files restored")
    return out
