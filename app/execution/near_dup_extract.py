"""Near-Dup-Extract — lift a NEAR-duplicate group into ONE parameterized helper.

:mod:`app.execution.dedup_extract` turns the EXACT-duplicate detector into an
action: a run of byte-identical statements becomes one shared helper. But the
dominant remaining duplication on a mature codebase is the *near*-duplicate
shape that :mod:`app.engine.near_dup` reports — runs that are STRUCTURALLY
identical and differ only at a handful of leaf *values*. ``x = 1`` here and
``x = 2`` there are not byte-identical, so dedup-extract can't touch them, yet
they are the same logic and a bug fixed in one copy is silently left in the
others.

This module is the careful, conservative core of "parameterized dedup": it
consumes a :class:`~app.engine.near_dup.NearDuplicateGroup` and lifts the group
into a single module-level helper whose DIFFERING leaves become extra
PARAMETERS. It is, deliberately, "dedup_extract, but the differing constants are
extra parameters" — and it REUSES dedup_extract's proven machinery wherever it
can (occurrence parsing/resolution, the data-flow signature gate, the tail-return
handling, helper naming/placement, call-site rewriting, the gate-clean
strip-unused-imports step). This is the hardest, riskiest transform in the repo,
so the scope is the SIMPLEST safe shape and the safety bar is absolute.

STRICT CONSERVATIVE SCOPE — every one of these is a hard gate; the slightest
doubt is a BLOCKER with empty ``new_contents`` (correctness over coverage):

  * EVERY differing leaf, in EVERY occurrence, must be an :class:`ast.Constant`
    literal. If any differing position is a ``Name`` (or anything but a
    Constant) in any occurrence → BLOCK. A differing constant becomes a plain
    value parameter; a differing name would change what the block *reads* and is
    deferred to a later, more careful version.
  * Each occurrence must re-resolve EXACTLY as dedup_extract requires (reusing
    its ``_resolve_occurrence`` path verbatim): inside one top-level
    function/method body, a clean contiguous statement run, no relocate-unsafe
    control flow (tail-return is the one lifted shape, mirroring dedup_extract),
    and an IDENTICAL live-in/live-out signature across all occurrences.
  * The differing-constant positions are located STRUCTURALLY (by re-deriving
    near_dup's own template walk on each occurrence's AST, not by text
    matching), and the holes are spliced by source span. If a position cannot be
    unambiguously located in every occurrence → BLOCK.
  * The assembled new source for every changed file must ``ast.parse`` or the
    plan blocks. Apply is still suite-verified with rollback via
    :class:`RenamePlan` / ``apply_rename``, but the plan must be correct on its
    own — the suite is a backstop, never the logic check.

Deterministic, stdlib-only; no time, randomness, network, or identity strings.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.near_dup import _is_value_leaf
from app.execution.cross_file_rename import RenamePlan
from app.execution.dedup_extract import (
    _Occurrence,
    _free_helper_name,
    _import_insert_index,
    _module_dotted,
    _parse_occurrence,
    _resolve_occurrence,
)
from app.execution.extract_method import _reindent
from app.execution.unused_imports import strip_unused_imports

__all__ = ["plan_near_dup_extract"]


def _walk_value_leaves(
    node: ast.AST, path: str, out: list[tuple[str, ast.AST]]
) -> None:
    """Append ``(path, node)`` for every SAFE value leaf, in near_dup's order.

    This mirrors :func:`app.engine.near_dup._walk_template` EXACTLY in its
    traversal order and in its structural ``path`` construction, but instead of
    emitting a template string it records the concrete AST node at each
    wildcarded value-leaf position. Because the order and paths are identical to
    the detector's, the k-th value leaf here is the k-th wildcard column the
    group reasoned about — so a differing column maps back to a real node we can
    locate and splice."""
    if _is_value_leaf(node):
        out.append((path, node))
        return
    for fname in node._fields:
        value = getattr(node, fname, None)
        if isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, ast.AST):
                    _walk_value_leaves(item, f"{path}.{fname}[{i}]", out)
        elif isinstance(value, ast.AST):
            _walk_value_leaves(value, f"{path}.{fname}", out)


def _block_value_leaves(statements: list[ast.stmt]) -> list[tuple[str, ast.AST]]:
    """Sorted ``(path, node)`` value leaves for a run of statements.

    Sorted by ``path`` so the column order matches near_dup's
    ``_block_template`` (which sorts its wildcard dict the same way), making the
    columns line up with :attr:`NearDuplicateGroup.differences`."""
    out: list[tuple[str, ast.AST]] = []
    for i, stmt in enumerate(statements):
        _walk_value_leaves(stmt, f"s{i}", out)
    out.sort(key=lambda pair: pair[0])
    return out


def _segment(source: str, node: ast.AST) -> str:
    """Source text of a value-leaf ``node``; falls back to a stable rendering.

    Matches near_dup's ``_segment`` for the leaves we compare so the per-column
    values agree with the detector's recorded differences."""
    seg = ast.get_source_segment(source, node)
    if seg is not None:
        return seg
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.Name):
        return node.id
    return type(node).__name__


def plan_near_dup_extract(project_root: str | Path, group) -> RenamePlan:
    """Plan lifting a near-duplicate ``group`` into one parameterized helper.

    ``group`` is a :class:`~app.engine.near_dup.NearDuplicateGroup`: its
    ``occurrences`` are ``"module:lineno"`` of each block's first statement and
    its ``differences`` lists, per differing position, the source text each
    occurrence carries there. Returns a :class:`RenamePlan` ready for
    ``apply_rename`` (suite-verified, auto-rollback). On the slightest doubt the
    plan carries a blocker and empty ``new_contents``."""
    plan = RenamePlan(old="near_dup", new="_shared")
    root = Path(project_root)

    occurrences = list(getattr(group, "occurrences", []) or [])
    n_statements = int(getattr(group, "lines", 0) or 0)
    diff_count = int(getattr(group, "diff_count", 0) or 0)
    differences = [list(col) for col in getattr(group, "differences", []) or []]

    if len(occurrences) < 2:
        plan.blockers.append("a shared helper needs at least two occurrences")
        return plan
    if n_statements < 1:
        plan.blockers.append("block has no statements to extract")
        return plan
    if diff_count < 1 or not differences:
        plan.blockers.append(
            "a near-duplicate has >= 1 differing position — a zero-diff group is "
            "an exact duplicate (dedup_extract's job), nothing to parameterize")
        return plan
    if len(differences) != diff_count:
        plan.blockers.append("malformed group: diff_count disagrees with "
                             "the differences columns")
        return plan
    if any(len(col) != len(occurrences) for col in differences):
        plan.blockers.append("malformed group: a differences column is not "
                             "parallel to the occurrences")
        return plan

    parsed = [_parse_occurrence(o) for o in occurrences]
    if any(p is None for p in parsed):
        plan.blockers.append("malformed occurrence location(s)")
        return plan

    # Read & parse every involved module once (deterministic order).
    sources: dict[str, str] = {}
    trees: dict[str, ast.Module] = {}
    rels = sorted({rel for rel, _ in parsed})  # type: ignore[misc]
    for rel in rels:
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except OSError:
            plan.blockers.append(f"cannot read {rel}")
            return plan
        try:
            trees[rel] = ast.parse(text)
        except SyntaxError as e:
            plan.blockers.append(f"{rel} doesn't parse: {e}")
            return plan
        sources[rel] = text

    # Resolve each occurrence with dedup_extract's EXACT path — same contiguous-run
    # snapping, same control-flow blockers, same tail-return handling, same
    # live-in/live-out data flow. Any unsafe one blocks the whole plan. The
    # occurrences stay PARALLEL to the differences columns (same order).
    resolved: list[_Occurrence] = []
    for rel, line in parsed:  # type: ignore[misc]
        occ = _resolve_occurrence(root, rel, line, n_statements, sources,
                                  trees, plan)
        if occ is None:
            return plan
        resolved.append(occ)

    # ONE interface: require an identical live-in/live-out signature everywhere,
    # exactly as dedup_extract does — structurally-divergent copies are never a
    # guess. (We re-check it here rather than trust the detector's grouping.)
    sig0 = (resolved[0].live_in, resolved[0].live_out)
    for occ in resolved[1:]:
        if (occ.live_in, occ.live_out) != sig0:
            plan.blockers.append(
                "occurrences have different data-flow signatures "
                f"(params/returns differ: {sig0} vs "
                f"{(occ.live_in, occ.live_out)}) — not a clean shared helper")
            return plan
    live_in, live_out = sig0

    tail_return = resolved[0].tail_return
    if any(occ.tail_return != tail_return for occ in resolved[1:]):
        plan.blockers.append("occurrences disagree on tail-return shape — "
                             "not a clean shared helper")
        return plan

    # ── Locate the differing value leaves STRUCTURALLY in every occurrence. ──
    # Re-derive near_dup's value-leaf walk for each occurrence's run. The columns
    # (sorted by structural path) line up across occurrences and with the
    # detector's `differences`. A column DIFFERS iff its segment text varies.
    per_occ_leaves: list[list[tuple[str, ast.AST]]] = []
    n_cols = -1
    for occ in resolved:
        leaves = _block_value_leaves(occ.stmts)
        if n_cols == -1:
            n_cols = len(leaves)
        elif len(leaves) != n_cols:
            plan.blockers.append(
                "occurrences expose different value-leaf shapes — the structural "
                "templates disagree, so they can't be one parameterized helper")
            return plan
        per_occ_leaves.append(leaves)

    # The structural paths must be identical column-by-column across occurrences;
    # if not, the blocks aren't really the same template and we refuse to guess.
    base_paths = [p for p, _ in per_occ_leaves[0]]
    for leaves in per_occ_leaves[1:]:
        if [p for p, _ in leaves] != base_paths:
            plan.blockers.append(
                "occurrences expose different value-leaf paths — structural "
                "mismatch, refusing to parameterize")
            return plan

    # A column is a differing position iff its per-occurrence segment text varies.
    diff_cols: list[int] = []
    diff_segments: list[list[str]] = []
    for col in range(n_cols):
        segs = [_segment(occ.source, per_occ_leaves[i][col][1])
                for i, occ in enumerate(resolved)]
        if len(set(segs)) > 1:
            diff_cols.append(col)
            diff_segments.append(segs)

    # Re-deriving the diffs must agree with what the detector reported, else our
    # column mapping is unsound — block rather than risk splicing the wrong hole.
    if len(diff_cols) != diff_count:
        plan.blockers.append(
            f"re-derived {len(diff_cols)} differing position(s) but the group "
            f"reports {diff_count} — column mapping is unsound, refusing")
        return plan
    if [sorted(col) for col in diff_segments] != [sorted(col) for col in differences]:
        plan.blockers.append(
            "re-derived differing values disagree with the detector's report — "
            "column mapping is unsound, refusing")
        return plan

    # EVERY differing leaf, in EVERY occurrence, must be an ast.Constant. A
    # differing Name (or anything else) defers to a later version — BLOCK.
    for col in diff_cols:
        for i, occ in enumerate(resolved):
            node = per_occ_leaves[i][col][1]
            if not isinstance(node, ast.Constant):
                plan.blockers.append(
                    "a differing position is not a constant literal in every "
                    f"occurrence ({_segment(occ.source, node)!r} at "
                    f"{occ.rel}:{occ.span_lo}) — only differing CONSTANTS can "
                    "become value parameters in this version")
                return plan

    first = resolved[0]
    first_dotted = _module_dotted(first.rel)
    helper_name = _free_helper_name(trees, set(rels))
    if helper_name is None:
        plan.blockers.append("could not find a free `_shared_<n>` helper name")
        return plan

    # Fresh parameter names for the holes (p0, p1, …), not colliding with live_in.
    param_names: list[str] = []
    taken = set(live_in)
    n = 0
    for _ in diff_cols:
        while f"p{n}" in taken:
            n += 1
        name = f"p{n}"
        param_names.append(name)
        taken.add(name)
        n += 1

    # ── Splice the FIRST occurrence's source: replace each differing constant
    # with its parameter name, located by source span (structural, not textual).
    helper_body_text = _splice_first(first, diff_cols, per_occ_leaves[0],
                                     param_names, plan)
    if helper_body_text is None:
        return plan

    base_indent = (len(first.lines[first.span_lo - 1])
                   - len(first.lines[first.span_lo - 1].lstrip()))
    body_lines = _reindent(helper_body_text.splitlines(keepends=True), base_indent)
    if live_out:
        body_lines.append("    return " + ", ".join(live_out))
    sig_params = list(live_in) + param_names
    helper_src = [f"def {helper_name}({', '.join(sig_params)}):"] + body_lines
    helper_block = "\n".join(helper_src) + "\n\n\n"

    # ── Per-occurrence call site: its OWN live_in args plus its OWN constants. ──
    def _call_line(occ: _Occurrence, occ_index: int, indent: str) -> str:
        const_args = [_segment(occ.source, per_occ_leaves[occ_index][col][1])
                      for col in diff_cols]
        args = list(live_in) + const_args
        call_expr = f"{helper_name}({', '.join(args)})"
        if tail_return:
            return f"{indent}return {call_expr}\n"
        if live_out:
            return f"{indent}{', '.join(live_out)} = {call_expr}\n"
        return f"{indent}{call_expr}\n"

    # ── Group occurrences by file; rewrite bottom-up so spans stay valid. ──
    index_of = {id(occ): i for i, occ in enumerate(resolved)}
    by_file: dict[str, list[_Occurrence]] = {}
    for occ in resolved:
        by_file.setdefault(occ.rel, []).append(occ)

    new_contents: dict[str, str] = {}
    edits: dict[str, int] = {}
    for rel in sorted(by_file):
        occs = by_file[rel]
        lines = list(sources[rel].splitlines(keepends=True))
        for occ in sorted(occs, key=lambda o: o.span_lo, reverse=True):
            indent = " " * (len(occ.lines[occ.span_lo - 1])
                            - len(occ.lines[occ.span_lo - 1].lstrip()))
            lines[occ.span_lo - 1:occ.span_hi] = [
                _call_line(occ, index_of[id(occ)], indent)]

        if rel == first.rel:
            container = first.container
            insert_at = min(
                [container.lineno]
                + [d.lineno for d in getattr(container, "decorator_list", [])]
            ) - 1
            lines[insert_at:insert_at] = [helper_block]
        else:
            import_line = f"from {first_dotted} import {helper_name}\n"
            lines.insert(_import_insert_index(trees[rel]), import_line)

        new_source = "".join(lines)
        try:
            ast.parse(new_source)
        except SyntaxError as e:
            plan.blockers.append(f"{rel}: extraction would not parse ({e})")
            return plan

        # Gate-clean: lifting the block out can strand the imports it used.
        cleaned = strip_unused_imports(new_source)
        if cleaned is not None:
            new_source = cleaned

        new_contents[rel] = new_source
        edits[rel] = len(occs) + (1 if rel != first.rel else 0)

    plan.new = helper_name
    plan.defined_in = first.rel
    plan.originals = {rel: sources[rel] for rel in new_contents}
    plan.new_contents = new_contents
    plan.edits_by_file = edits
    return plan


def _splice_first(first: _Occurrence, diff_cols: list[int],
                  leaves: list[tuple[str, ast.AST]], param_names: list[str],
                  plan: RenamePlan) -> str | None:
    """Replace each differing constant in the FIRST occurrence's block source
    with its parameter name, by source span. Returns the spliced block text
    (the raw lines of the run, holes substituted), or ``None`` (recording a
    blocker) if any hole can't be unambiguously located and spliced.

    The block source is the raw text of the run; spans come from each constant
    node's own ``lineno``/``col_offset`` relative to that text, so comments and
    formatting elsewhere in the block survive untouched."""
    # The exact lines of the run, as a standalone snippet whose line 1 is the
    # run's first line (so a node's absolute lineno maps to a snippet index).
    block_lines = list(first.lines[first.span_lo - 1:first.span_hi])

    # Collect (line_idx, col_start, col_end, replacement) edits for each hole.
    edits: list[tuple[int, int, int, str]] = []
    for col, pname in zip(diff_cols, param_names):
        node = leaves[col][1]
        lineno = getattr(node, "lineno", None)
        col_off = getattr(node, "col_offset", None)
        end_lineno = getattr(node, "end_lineno", None)
        end_col = getattr(node, "end_col_offset", None)
        if (lineno is None or col_off is None or end_lineno is None
                or end_col is None):
            plan.blockers.append(
                "a differing constant lacks position info — can't splice it "
                "safely, refusing")
            return None
        if lineno != end_lineno:
            # A multi-line literal hole would span snippet rows — out of this
            # version's conservative scope.
            plan.blockers.append(
                "a differing constant spans multiple lines — refusing to splice "
                "a multi-line hole in this version")
            return None
        idx = lineno - first.span_lo
        if not (0 <= idx < len(block_lines)):
            plan.blockers.append(
                "a differing constant falls outside the located run — refusing")
            return None
        # Verify the span really is THIS constant's source (defence in depth),
        # reading against the FULL module source where the node's positions live.
        if ast.get_source_segment(first.source, node) is None:
            plan.blockers.append(
                "could not re-read a differing constant's source span — refusing")
            return None
        edits.append((idx, col_off, end_col, pname))

    # Apply per-line, right-to-left, so earlier columns stay valid.
    grouped: dict[int, list[tuple[int, int, str]]] = {}
    for idx, c0, c1, pname in edits:
        grouped.setdefault(idx, []).append((c0, c1, pname))
    for idx, holes in grouped.items():
        line = block_lines[idx]
        for c0, c1, pname in sorted(holes, key=lambda h: h[0], reverse=True):
            if c1 > len(line.rstrip("\n")) or c0 < 0 or c0 >= c1:
                plan.blockers.append(
                    "a differing constant's span is out of range — refusing")
                return None
            line = line[:c0] + pname + line[c1:]
        block_lines[idx] = line

    return "".join(block_lines)
