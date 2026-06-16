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

  * EVERY differing leaf, in EVERY occurrence, must be a parameterizable VALUE:
    an :class:`ast.Constant`, or an :class:`ast.Name` that is LOADED (read). Both
    become a value parameter the call site passes. A differing loaded name is
    safe precisely because a name BOUND inside the block is a ``Store`` (structure
    the detector requires to match), so any differing loaded name is a FREE name
    (global/builtin/outer scope) — passing its value is identical to reading it
    inline. Anything else (a ``Store``/``Del`` target, an attribute) → BLOCK.
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

import keyword

from app.engine.near_dup import _is_value_leaf
from app.execution.cross_file_rename import RenamePlan
from app.execution.dedup_extract import (
    _Occurrence,
    _descriptive_helper_name,
    _free_helper_name,
    _import_insert_index,
    _module_dotted,
    _parse_occurrence,
    _resolve_occurrence,
    _split_identifier_tokens,
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

    Sorted by ``path`` so the column order matches near_dup's statement-fragment
    templating (which sorts its wildcard leaves the same way), making the columns
    line up with :attr:`NearDuplicateGroup.differences`."""
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


def _common_affix_token(names: list[str]) -> str | None:
    """A descriptive param base from a SHARED token suffix or prefix of NAME
    holes, or ``None`` when there's no good common token.

    Each value is tokenized like an identifier (on ``_`` and CamelCase, lowered);
    if every value shares the SAME LAST token (suffix), that token is the base —
    e.g. ``PatchRequestGenerator``/``SemanticPatchGenerator`` share ``generator``.
    Otherwise a shared FIRST token (prefix) is tried. The base must be a valid
    identifier and not a keyword. Deterministic."""
    if len(names) < 2:
        return None
    token_lists = [_split_identifier_tokens(n) for n in names]
    if any(not toks for toks in token_lists):
        return None
    # Require the values to actually DIFFER (a column only reaches here when its
    # segments vary), and share a single affix token to name the parameter after.
    suffix = {toks[-1] for toks in token_lists}
    prefix = {toks[0] for toks in token_lists}
    base: str | None = None
    if len(suffix) == 1:
        base = next(iter(suffix))
    elif len(prefix) == 1:
        base = next(iter(prefix))
    if base is None or not base.isidentifier() or keyword.iskeyword(base):
        return None
    return base


def _hole_param_names(diff_node_segments: list[list[tuple[ast.AST, str]]],
                      live_in: list[str]) -> list[str]:
    """Deterministic param names for the holes: a descriptive name from a common
    NAME affix token where one exists, else the neutral ``p<n>`` fallback.

    ``diff_node_segments[k]`` is the per-occurrence ``(node, segment)`` for the
    k-th differing column. A descriptive name is used only when EVERY occurrence's
    leaf at that column is an ``ast.Name`` and they share an affix token. Names
    never collide with each other or with the helper's ``live_in`` params and are
    never keywords; on any clash (or no good token) we fall back to ``p<n>``.
    Order is preserved so the result is fully deterministic."""
    taken = set(live_in)
    names: list[str] = []
    fallback_n = 0
    for col_nodes in diff_node_segments:
        nodes = [node for node, _ in col_nodes]
        chosen: str | None = None
        if all(isinstance(node, ast.Name) for node in nodes):
            base = _common_affix_token([node.id for node in nodes])  # type: ignore[union-attr]
            if base is not None and base not in taken:
                chosen = base
            elif base is not None:
                for suffix in range(2, 100):
                    candidate = f"{base}_{suffix}"
                    if candidate not in taken:
                        chosen = candidate
                        break
        if chosen is None:
            while f"p{fallback_n}" in taken:
                fallback_n += 1
            chosen = f"p{fallback_n}"
            fallback_n += 1
        taken.add(chosen)
        names.append(chosen)
    return names


def _validate_group_shape(group, plan: RenamePlan):
    """Read the group's fields and gate its shape. Returns
    ``(occurrences, n_statements, diff_count, differences)`` on success, or
    ``None`` (recording a blocker) on any malformed shape — same checks and
    messages as the inline version, in the same order."""
    occurrences = list(getattr(group, "occurrences", []) or [])
    n_statements = int(getattr(group, "lines", 0) or 0)
    diff_count = int(getattr(group, "diff_count", 0) or 0)
    differences = [list(col) for col in getattr(group, "differences", []) or []]

    if len(occurrences) < 2:
        plan.blockers.append("a shared helper needs at least two occurrences")
        return None
    if n_statements < 1:
        plan.blockers.append("block has no statements to extract")
        return None
    if diff_count < 1 or not differences:
        plan.blockers.append(
            "a near-duplicate has >= 1 differing position — a zero-diff group is "
            "an exact duplicate (dedup_extract's job), nothing to parameterize")
        return None
    if len(differences) != diff_count:
        plan.blockers.append("malformed group: diff_count disagrees with "
                             "the differences columns")
        return None
    if any(len(col) != len(occurrences) for col in differences):
        plan.blockers.append("malformed group: a differences column is not "
                             "parallel to the occurrences")
        return None
    return occurrences, n_statements, diff_count, differences


def _read_modules(root: Path, parsed, plan: RenamePlan):
    """Read & parse every involved module once (deterministic order). Returns
    ``(sources, trees, rels)`` or ``None`` (recording a blocker) on a read or
    parse failure."""
    sources: dict[str, str] = {}
    trees: dict[str, ast.Module] = {}
    rels = sorted({rel for rel, _ in parsed})  # type: ignore[misc]
    for rel in rels:
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except OSError:
            plan.blockers.append(f"cannot read {rel}")
            return None
        try:
            trees[rel] = ast.parse(text)
        except SyntaxError as e:
            plan.blockers.append(f"{rel} doesn't parse: {e}")
            return None
        sources[rel] = text
    return sources, trees, rels


def _resolve_all_occurrences(root: Path, parsed, n_statements: int,
                             sources, trees, plan: RenamePlan):
    """Resolve every occurrence with dedup_extract's EXACT path, then enforce a
    single live-in/live-out signature and a single tail-return shape across them
    all. Returns ``(resolved, live_in, live_out, tail_return)`` or ``None``
    (recording a blocker) on any unsafe occurrence or divergence."""
    # Same contiguous-run snapping, same control-flow blockers, same tail-return
    # handling, same live-in/live-out data flow. Any unsafe one blocks the whole
    # plan. The occurrences stay PARALLEL to the differences columns (same order).
    resolved: list[_Occurrence] = []
    for rel, line in parsed:  # type: ignore[misc]
        occ = _resolve_occurrence(root, rel, line, n_statements, sources,
                                  trees, plan)
        if occ is None:
            return None
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
            return None
    live_in, live_out = sig0

    tail_return = resolved[0].tail_return
    if any(occ.tail_return != tail_return for occ in resolved[1:]):
        plan.blockers.append("occurrences disagree on tail-return shape — "
                             "not a clean shared helper")
        return None
    return resolved, live_in, live_out, tail_return


def _locate_diff_columns(resolved, diff_count: int, differences, plan: RenamePlan):
    """Locate the differing value leaves STRUCTURALLY in every occurrence.

    Re-derive near_dup's value-leaf walk for each occurrence's run, check the
    templates line up across occurrences, derive which columns differ, and gate
    that those differences match the detector's report. Returns
    ``(per_occ_leaves, diff_cols)`` or ``None`` (recording a blocker)."""
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
            return None
        per_occ_leaves.append(leaves)

    # The structural paths must be identical column-by-column across occurrences;
    # if not, the blocks aren't really the same template and we refuse to guess.
    base_paths = [p for p, _ in per_occ_leaves[0]]
    for leaves in per_occ_leaves[1:]:
        if [p for p, _ in leaves] != base_paths:
            plan.blockers.append(
                "occurrences expose different value-leaf paths — structural "
                "mismatch, refusing to parameterize")
            return None

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
        return None
    if [sorted(col) for col in diff_segments] != [sorted(col) for col in differences]:
        plan.blockers.append(
            "re-derived differing values disagree with the detector's report — "
            "column mapping is unsound, refusing")
        return None
    return per_occ_leaves, diff_cols


def _gate_value_holes(resolved, per_occ_leaves, diff_cols,
                      plan: RenamePlan) -> bool:
    """EVERY differing leaf must be a parameterizable VALUE in every occurrence:
    an ast.Constant, or an ast.Name LOADED (read). Returns ``True`` if all holes
    pass, else ``False`` (recording a blocker).

    A differing loaded Name is provably safe — because the detector only
    wildcards value leaves and a name BOUND inside the block is a Store
    (structure that must match to group), any differing loaded Name is a FREE
    name (global/builtin/outer), so passing its value as an argument is identical
    to reading it inline. Anything else (a Store/Del target, an attribute —
    neither is a value leaf) blocks."""
    for col in diff_cols:
        for i, occ in enumerate(resolved):
            node = per_occ_leaves[i][col][1]
            is_value = isinstance(node, ast.Constant) or (
                isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load))
            if not is_value:
                plan.blockers.append(
                    "a differing position is not a value (constant or loaded "
                    f"name) in every occurrence ({_segment(occ.source, node)!r} "
                    f"at {occ.rel}:{occ.span_lo}) — can't become a value parameter")
                return False
    return True


def _emit_rewrites(resolved, sources, trees, rels, first, first_dotted,
                   helper_name, helper_block, per_occ_leaves, diff_cols,
                   live_in, live_out, tail_return, plan: RenamePlan):
    """Rewrite every involved file (helper insertion + call sites + imports),
    bottom-up so spans stay valid. Returns ``(new_contents, edits)`` or ``None``
    (recording a blocker) if any rewritten file fails to parse."""
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
            # Insert the helper above the first occurrence's container. The
            # anchor is an ORIGINAL-tree line number, but the bottom-up
            # replacements above just collapsed each copy's span (hi-lo+1 lines)
            # to ONE call line, shrinking the buffer. `first` is first in EMIT
            # order, NOT topmost in the file, so a copy may sit ABOVE this
            # container; rebase the anchor by the net line-delta of every
            # replacement whose span ends above it, or the def lands inside an
            # earlier function's body (the same above/below partition
            # inline_function uses so splice and deletions don't interfere).
            container = first.container
            anchor = min(
                [container.lineno]
                + [d.lineno for d in getattr(container, "decorator_list", [])]
            )
            delta_above = sum(
                1 - (o.span_hi - o.span_lo + 1)
                for o in occs if o.span_hi < anchor
            )
            insert_at = anchor - 1 + delta_above
            lines[insert_at:insert_at] = [helper_block]
        else:
            import_line = f"from {first_dotted} import {helper_name}\n"
            lines.insert(_import_insert_index(trees[rel]), import_line)

        new_source = "".join(lines)
        try:
            ast.parse(new_source)
        except SyntaxError as e:
            plan.blockers.append(f"{rel}: extraction would not parse ({e})")
            return None

        # Gate-clean: lifting the block out can strand the imports it used.
        cleaned = strip_unused_imports(new_source)
        if cleaned is not None:
            new_source = cleaned

        new_contents[rel] = new_source
        edits[rel] = len(occs) + (1 if rel != first.rel else 0)
    return new_contents, edits


def _build_helper_block(resolved, trees, rels, first, per_occ_leaves,
                        diff_cols, live_in, live_out, plan: RenamePlan):
    """Choose the helper name and param names, splice the first occurrence's
    source, and assemble the ``def ...:`` helper block text. Returns
    ``(helper_name, helper_block)`` or ``None`` (recording a blocker) when no
    free name exists or a hole can't be spliced."""
    # Human-readable helper name from the common tokens of the enclosing function
    # names, falling back to the machine `_shared_<n>` scheme when none is free.
    fn_names = [occ.fn.name for occ in resolved]
    helper_name = (_descriptive_helper_name(fn_names, trees, set(rels))
                   or _free_helper_name(trees, set(rels)))
    if helper_name is None:
        plan.blockers.append("could not find a free `_shared_<n>` helper name")
        return None

    # Parameter names for the holes: a descriptive name from a common NAME affix
    # token where every occurrence's leaf agrees, else the neutral `p<n>` fallback.
    # Never collide with each other or with live_in (which seeds `taken`).
    diff_node_segments = [
        [(per_occ_leaves[i][col][1], _segment(occ.source, per_occ_leaves[i][col][1]))
         for i, occ in enumerate(resolved)]
        for col in diff_cols
    ]
    param_names = _hole_param_names(diff_node_segments, live_in)

    # ── Splice the FIRST occurrence's source: replace each differing constant
    # with its parameter name, located by source span (structural, not textual).
    helper_body_text = _splice_first(first, diff_cols, per_occ_leaves[0],
                                     param_names, plan)
    if helper_body_text is None:
        return None

    base_indent = (len(first.lines[first.span_lo - 1])
                   - len(first.lines[first.span_lo - 1].lstrip()))
    body_lines = _reindent(helper_body_text.splitlines(keepends=True), base_indent)
    if live_out:
        body_lines.append("    return " + ", ".join(live_out))
    sig_params = list(live_in) + param_names
    helper_src = [f"def {helper_name}({', '.join(sig_params)}):"] + body_lines
    helper_block = "\n".join(helper_src) + "\n\n\n"
    return helper_name, helper_block


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

    shape = _validate_group_shape(group, plan)
    if shape is None:
        return plan
    occurrences, n_statements, diff_count, differences = shape

    parsed = [_parse_occurrence(o) for o in occurrences]
    if any(p is None for p in parsed):
        plan.blockers.append("malformed occurrence location(s)")
        return plan

    read = _read_modules(root, parsed, plan)
    if read is None:
        return plan
    sources, trees, rels = read

    occ_result = _resolve_all_occurrences(root, parsed, n_statements, sources,
                                          trees, plan)
    if occ_result is None:
        return plan
    resolved, live_in, live_out, tail_return = occ_result

    located = _locate_diff_columns(resolved, diff_count, differences, plan)
    if located is None:
        return plan
    per_occ_leaves, diff_cols = located

    if not _gate_value_holes(resolved, per_occ_leaves, diff_cols, plan):
        return plan

    first = resolved[0]
    first_dotted = _module_dotted(first.rel)
    built = _build_helper_block(resolved, trees, rels, first, per_occ_leaves,
                                diff_cols, live_in, live_out, plan)
    if built is None:
        return plan
    helper_name, helper_block = built

    emitted = _emit_rewrites(resolved, sources, trees, rels, first, first_dotted,
                             helper_name, helper_block, per_occ_leaves, diff_cols,
                             live_in, live_out, tail_return, plan)
    if emitted is None:
        return plan
    new_contents, edits = emitted

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
