"""User-defined structural rewrite — the codemod the neighbors don't verify.

``apex rewrite 'len($x) == 0' 'not $x'`` rewrites every structural match of
the PATTERN expression, project-wide. ``$name`` metavariables match any
expression; the same metavariable appearing twice must capture the same
source text. The replacement template reuses captures verbatim, so the
matched code's own spelling survives.

The neighbors (ast-grep, Comby, GritQL) pioneered this shape; Apex's
addition is the family creed they don't have: every apply is **suite-
verified with automatic rollback**, every ambiguity is a blocker or an
honest skip:

  - patterns and replacements must parse as Python expressions;
  - a replacement metavariable not bound by the pattern blocks;
  - a match that spans lines is SKIPPED with a warning (the splice is
    intra-line by design, so comments and formatting survive);
  - a match nested inside an already-rewritten match is skipped (no
    overlapping edits, outermost wins).

Deterministic, stdlib-only; reuses :class:`RenamePlan` / ``apply_rename``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, _py_files

__all__ = ["plan_pattern_rewrite"]

_MV_PREFIX = "__apex_mv_"
_MV_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


def _encode_metavars(text: str) -> str:
    """``$x`` → a parseable placeholder identifier."""
    return _MV_RE.sub(lambda m: f"{_MV_PREFIX}{m.group(1)}", text)


def _parse_expr(text: str, what: str, plan: RenamePlan) -> ast.expr | None:
    try:
        return ast.parse(_encode_metavars(text), mode="eval").body
    except SyntaxError:
        plan.blockers.append(f"the {what} is not a valid Python expression: {text!r}")
        return None


def _metavar(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name) and node.id.startswith(_MV_PREFIX):
        return node.id[len(_MV_PREFIX):]
    return None


_SKIP_FIELDS = {"ctx", "type_comment"}


def _match(node: ast.AST, pattern: ast.AST, source: str,
           bindings: dict[str, str]) -> bool:
    """Structural match with capture; bindings hold each metavar's source text."""
    mv = _metavar(pattern)
    if mv is not None:
        if not isinstance(node, ast.expr):
            return False
        seg = ast.get_source_segment(source, node)
        if seg is None:
            return False
        if mv in bindings:
            return bindings[mv] == seg  # the same $x must capture the same text
        bindings[mv] = seg
        return True
    if type(node) is not type(pattern):
        return False
    for field, pvalue in ast.iter_fields(pattern):
        if field in _SKIP_FIELDS:
            continue
        nvalue = getattr(node, field, None)
        if isinstance(pvalue, list):
            if not isinstance(nvalue, list) or len(nvalue) != len(pvalue):
                return False
            for n_item, p_item in zip(nvalue, pvalue):
                if isinstance(p_item, ast.AST):
                    if not isinstance(n_item, ast.AST) or not _match(n_item, p_item, source, bindings):
                        return False
                elif n_item != p_item:
                    return False
        elif isinstance(pvalue, ast.AST):
            if not isinstance(nvalue, ast.AST) or not _match(nvalue, pvalue, source, bindings):
                return False
        elif nvalue != pvalue:
            return False
    return True


def _render(template: str, bindings: dict[str, str]) -> str:
    """The replacement text with every ``$x`` swapped for its capture."""
    return _MV_RE.sub(lambda m: bindings[m.group(1)], template)


def plan_pattern_rewrite(project_root: str | Path, pattern: str,
                         replacement: str) -> RenamePlan:
    """Build the project-wide structural-rewrite plan."""
    plan = RenamePlan(old=pattern, new=replacement)
    p_tree = _parse_expr(pattern, "pattern", plan)
    if p_tree is None:
        return plan
    if _metavar(p_tree) is not None:
        plan.blockers.append("the pattern can't be a bare metavariable — "
                             "that would match every expression in the project")
        return plan
    r_tree = _parse_expr(replacement, "replacement", plan)
    if r_tree is None:
        return plan
    pattern_vars = {_metavar(n) for n in ast.walk(p_tree) if _metavar(n)}
    unbound = {_metavar(n) for n in ast.walk(r_tree) if _metavar(n)} - pattern_vars
    if unbound:
        plan.blockers.append(
            f"replacement metavariable(s) not bound by the pattern: "
            f"{', '.join(sorted('$' + v for v in unbound))}")
        return plan

    for rel, source in _py_files(Path(project_root)):
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        lines = source.splitlines(keepends=True)
        consumed: list[tuple[int, int, int]] = []   # (line, start, end)
        edits: list[tuple[int, int, int, str, str]] = []  # (+ old, new)
        for node in ast.walk(tree):  # parents before children: outermost wins
            if not isinstance(node, ast.expr):
                continue
            bindings: dict[str, str] = {}
            if not _match(node, p_tree, source, bindings):
                continue
            if node.lineno != node.end_lineno:
                plan.warnings.append(
                    f"{rel}:{node.lineno}: match spans lines — skipped "
                    "(rewrites stay intra-line so formatting survives)")
                continue
            span = (node.lineno, node.col_offset, node.end_col_offset)
            if any(line == span[0] and start <= span[1] and span[2] <= end
                   for line, start, end in consumed):
                continue  # nested inside an already-rewritten match
            consumed.append(span)
            old = lines[span[0] - 1][span[1]:span[2]]
            edits.append((*span, old, _render(replacement, bindings)))

        if not edits:
            continue
        for line_no, start, end, old, new in sorted(edits, reverse=True):
            row = lines[line_no - 1]
            if row[start:end] != old:  # paranoia: the span must still match
                plan.blockers.append(f"{rel}:{line_no}: span drifted during edit")
                break
            lines[line_no - 1] = row[:start] + new + row[end:]
        else:
            plan.originals[rel] = source
            plan.new_contents[rel] = "".join(lines)
            plan.edits_by_file[rel] = len(edits)

    if plan.blockers:
        plan.new_contents.clear()
        plan.originals.clear()
        plan.edits_by_file.clear()
    return plan
