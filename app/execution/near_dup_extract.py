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
    a plain :class:`ast.Constant` — never inside a ``match`` pattern, an
    f-string, or an annotation, and never spanning multiple lines. Name holes
    are DEFERRED (W99c): a differing loaded :class:`ast.Name` still BLOCKS
    today (see the pinned refusals in ``tests/test_near_dup_extract.py``) —
    the machinery that would restore descriptive param naming from a shared
    NAME affix token stays in-tree (``_common_affix_token`` /
    ``_hole_param_names``' Name branch), unit-pinned, ready for W99c's full
    binding/eval-order analysis. Anything else (a ``Store``/``Del`` target,
    an attribute) → BLOCK.
  * Each occurrence must re-resolve EXACTLY as dedup_extract requires (reusing
    its ``_resolve_occurrence`` path verbatim): inside one top-level
    function/method body, a clean contiguous statement run, no relocate-unsafe
    control flow (tail-return is the one lifted shape, mirroring dedup_extract),
    and an IDENTICAL live-in/live-out signature across all occurrences.
  * The differing-constant positions are located STRUCTURALLY: the FULL
    structural template (near_dup's own fragment walk — operators, attribute
    names, comparators and every primitive field encoded verbatim) is
    re-derived per occurrence and must be IDENTICAL across all of them (any
    divergence proves a stale/drifted group → BLOCK), then the value-leaf walk
    maps each differing column to a real node and the holes are spliced by
    source span. If a position cannot be unambiguously located in every
    occurrence → BLOCK.
  * Post-resolution soundness rails (shared with the exact-dup family where
    they apply): same-file occurrences whose spans OVERLAP → BLOCK (the
    bottom-up splice would corrupt); a ``global``/``nonlocal``-declared name
    the run binds or reads → BLOCK (scope-capture divergence); a run whose
    first statement is the enclosing function's docstring → BLOCK (the lift
    nulls ``__doc__``); a differing hole inside a ``match`` PATTERN → BLOCK
    (``case p0:`` is a capture pattern, not a value).
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

from app.engine.near_dup import (
    _is_value_leaf,
    _split_source_lines,
    _statement_fragment,
)
from app.execution._dedup_helpers import (
    _cross_module_rebind_blocker,
    _overlap_blocker,
    occurrence_rail_reason,
    stamp_multi_module_plan,
)
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
        except (SyntaxError, RecursionError, MemoryError) as e:
            plan.blockers.append(f"{rel} doesn't parse: {e}")
            return None
        sources[rel] = text
    return sources, trees, rels


def _docstring_span_blocker(resolved) -> str | None:
    """A run whose FIRST statement is the enclosing function's docstring
    (``fn.body[0]``, an ``Expr`` holding a ``str`` constant): the lift moves
    that statement into the helper, so the original function's ``__doc__``
    silently becomes ``None`` (help(), Sphinx, and doctest collection all
    observe it). Refuse-direction only."""
    for occ in resolved:
        first = occ.fn.body[0]
        if (occ.stmts and occ.stmts[0] is first
                and isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            return (f"{occ.rel}:{occ.span_lo}: the range starts at the "
                    "enclosing function's docstring — lifting it would null "
                    "the function's `__doc__`, refusing")
    return None


def _soundness_rails_blocker(resolved) -> str | None:
    """The near-dup lane's post-resolution soundness rails, in fixed order:
    overlapping same-file spans (the bottom-up splice would corrupt),
    cross-module free-global rebinds (fires only for multi-file groups), the
    family's FULL per-run rail set (:func:`occurrence_rail_reason` — async
    blocks, multi-line string/bytes/f-string constants, reflection, pre-run
    closures, invisible non-``Name`` bindings, ``global``/``nonlocal``-declared
    names, and a ``class`` statement anywhere in the run), and docstring-
    position runs (the lift nulls ``__doc__``). The exact-dup family runs the
    first two plus the per-run set via ``family_rail_blocker``; near-dup
    occurrences intentionally differ at value leaves, so the identity rail
    does not apply and the relevant rails are invoked directly here — the
    near-dup lane now inherits the family's per-run rails IN FULL, not just
    the global-decl/multi-line pair. Refuse-direction only."""
    blocker = _overlap_blocker(resolved) or _cross_module_rebind_blocker(resolved)
    if blocker is not None:
        return blocker
    for occ in resolved:
        reason = occurrence_rail_reason(occ.fn, occ.stmts)
        if reason is not None:
            return f"{occ.rel}:{occ.span_lo}: {reason}"
    return _docstring_span_blocker(resolved)


def _resolve_all_occurrences(root: Path, parsed, n_statements: int,
                             sources, trees, plan: RenamePlan, *,
                             resolver=_resolve_occurrence):
    """Resolve every occurrence via ``resolver`` (default: dedup_extract's
    ``_resolve_occurrence``; the total-return lane passes its own — same
    ``resolver(root, rel, line, n_statements, sources, trees, plan)`` shape
    dedup_total_return's ``_resolve_all`` established), run the lane's
    post-resolution soundness rails, then enforce a single live-in/live-out
    signature and a single tail-return shape across them all. Returns
    ``(resolved, live_in, live_out, tail_return)`` or ``None`` (recording a
    blocker) on any unsafe occurrence or divergence."""
    # Same contiguous-run snapping, same control-flow blockers, same tail-return
    # handling, same live-in/live-out data flow. Any unsafe one blocks the whole
    # plan. The occurrences stay PARALLEL to the differences columns (same order).
    resolved: list[_Occurrence] = []
    for rel, line in parsed:  # type: ignore[misc]
        occ = resolver(root, rel, line, n_statements, sources, trees, plan)
        if occ is None:
            return None
        resolved.append(occ)

    blocker = _soundness_rails_blocker(resolved)
    if blocker is not None:
        plan.blockers.append(blocker)
        return None

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


def _collect_per_occ_leaves(resolved, plan: RenamePlan):
    """Re-derive each occurrence's value-leaf walk, gating a uniform column
    count. Returns ``(per_occ_leaves, n_cols)`` or ``None`` (recording a
    blocker) when the structural templates expose different leaf shapes."""
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
    return per_occ_leaves, n_cols


def _paths_match(per_occ_leaves) -> bool:
    """Whether every occurrence exposes the SAME column-by-column leaf paths."""
    base_paths = [p for p, _ in per_occ_leaves[0]]
    return all([p for p, _ in leaves] == base_paths
               for leaves in per_occ_leaves[1:])


def _derive_diff_columns(resolved, per_occ_leaves, n_cols: int):
    """Per-column segment scan. Returns ``(diff_cols, diff_segments)`` — a column
    is differing iff its per-occurrence segment text varies."""
    diff_cols: list[int] = []
    diff_segments: list[list[str]] = []
    for col in range(n_cols):
        segs = [_segment(occ.source, per_occ_leaves[i][col][1])
                for i, occ in enumerate(resolved)]
        if len(set(segs)) > 1:
            diff_cols.append(col)
            diff_segments.append(segs)
    return diff_cols, diff_segments


def _occurrence_template(occ: _Occurrence) -> str:
    """The FULL structural template of one occurrence's run — near_dup's own
    fragment walk (:func:`app.engine.near_dup._statement_fragment`), which
    encodes operators, attribute names, comparators, ``ctx`` and every other
    primitive field verbatim while wildcarding exactly the value leaves —
    joined with the detector's ``|`` statement separator. Two occurrences of a
    genuine group share ONE template by construction, so any plan-time
    divergence proves the group is stale."""
    lines = _split_source_lines(occ.source)
    parts: list[str] = []
    for stmt in occ.stmts:
        parts.append(_statement_fragment(stmt, lines)[0])
        parts.append("|")
    return "".join(parts)


def _locate_diff_columns(resolved, diff_count: int, differences, plan: RenamePlan):
    """Locate the differing value leaves STRUCTURALLY in every occurrence.

    Re-derive near_dup's FULL structural template for each occurrence's run
    (any divergence proves a stale/drifted group), re-derive the value-leaf
    walk, check the leaf paths line up across occurrences, derive which columns
    differ, and gate that those differences match the detector's report.
    Returns ``(per_occ_leaves, diff_cols)`` or ``None`` (recording a
    blocker)."""
    collected = _collect_per_occ_leaves(resolved, plan)
    if collected is None:
        return None
    per_occ_leaves, n_cols = collected

    # A group only exists because every occurrence shared ONE detector
    # template, so re-derived templates that disagree prove staleness — an
    # operator/attribute/comparator drifted since the group was built, which
    # the leaf-path walk below cannot see (it never visits those fields).
    if len({_occurrence_template(occ) for occ in resolved}) > 1:
        plan.blockers.append(
            "occurrences no longer share one structural template — structural "
            "drift (stale group?), refusing to parameterize")
        return None

    # The structural paths must be identical column-by-column across occurrences;
    # if not, the blocks aren't really the same template and we refuse to guess.
    if not _paths_match(per_occ_leaves):
        plan.blockers.append(
            "occurrences expose different value-leaf paths — structural "
            "mismatch, refusing to parameterize")
        return None

    # A column is a differing position iff its per-occurrence segment text varies.
    diff_cols, diff_segments = _derive_diff_columns(
        resolved, per_occ_leaves, n_cols)

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


def _pattern_node_ids(statements: list) -> set[int]:
    """``id()`` of every AST node inside a ``match`` case PATTERN subtree of
    ``statements``. A constant there is NOT an expression: ``case 100:`` is a
    value pattern, but splicing a parameter name in its place yields
    ``case p0:`` — a CAPTURE pattern that always matches and binds — so a
    pattern-position hole can never become a value parameter. (Guards —
    ``case … if cond:`` — are ordinary expressions and are not collected.)"""
    out: set[int] = set()
    for stmt in statements:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Match):
                for mc in n.cases:
                    out.update(id(p) for p in ast.walk(mc.pattern))
    return out


def _fstring_node_ids(statements: list) -> set[int]:
    """``id()`` of every AST node inside any :class:`ast.JoinedStr` (f-string)
    subtree of ``statements``. ``ast.walk`` covers nested ``JoinedStr`` and
    ``FormattedValue.format_spec`` (itself a ``JoinedStr``), so a format-spec
    hole and 3.12's per-segment nesting are both covered STRUCTURALLY; sound
    on 3.11 (whole-f-string ``Constant`` spans) AND 3.12 (real per-segment
    spans) because the refusal is POSITIONAL (id-based), never span-based."""
    out: set[int] = set()
    for stmt in statements:
        for n in ast.walk(stmt):
            if isinstance(n, ast.JoinedStr):
                out.update(id(x) for x in ast.walk(n))
    return out


def _annotation_node_ids(statements: list) -> set[int]:
    """``id()`` of every AST node inside an ``AnnAssign.annotation`` subtree of
    ``statements``. Function/lambda argument and return annotations only occur
    inside a nested ``def``/``lambda``, which ``_NESTED_SCOPE_NODES`` already
    blocks upstream (and a ``ClassDef`` in the run is refused family-wide by
    ``_dedup_helpers._classdef_reason``) — so the reachable carrier is a plain
    top-level ``x: T = value`` inside the run. An annotation is a TYPE
    expression, not a runtime value; under ``from __future__ import
    annotations`` it is even a lazily-stringified one, so splicing a parameter
    there is never sound."""
    out: set[int] = set()
    for stmt in statements:
        for n in ast.walk(stmt):
            if isinstance(n, ast.AnnAssign) and n.annotation is not None:
                out.update(id(x) for x in ast.walk(n.annotation))
    return out


def _hole_blocker(node: ast.AST, occ: _Occurrence, pattern_ids: set[int],
                  fstring_ids: set[int], annotation_ids: set[int]) -> str | None:
    """The gate ladder for ONE differing leaf ``node`` in ONE occurrence, or
    ``None`` when it passes every gate: pattern -> f-string -> annotation ->
    Constant-only -> single-line. Name holes are DEFERRED (W99c)."""
    seg = _segment(occ.source, node)
    if id(node) in pattern_ids:
        return ("a differing position sits inside a `match` pattern "
                f"({seg!r} at {occ.rel}:{occ.span_lo}) — a parameter there "
                "would become a capture pattern, not a value, refusing")
    if id(node) in fstring_ids:
        return ("a differing position lies inside an f-string "
                f"({seg!r} at {occ.rel}:{occ.span_lo}) — splicing a "
                "parameter there would rewrite the f-string, refusing")
    if id(node) in annotation_ids:
        return ("a differing position sits inside an annotation "
                f"({seg!r} at {occ.rel}:{occ.span_lo}) — an annotation is "
                "not a runtime value, refusing")
    if not isinstance(node, ast.Constant):
        return ("a differing position is not a plain constant in every "
                f"occurrence ({seg!r} at {occ.rel}:{occ.span_lo}) — only "
                "constant holes are parameterized (name holes are deferred)")
    # Position info is checked defensively (as `_hole_edit` does downstream):
    # a node lacking it simply isn't caught by THIS gate — `_hole_edit`'s own
    # explicit "lacks position info" blocker is the load-bearing check for the
    # real splice path; every leaf reaching here from `ast.parse`d source
    # always carries both.
    lineno = getattr(node, "lineno", None)
    end_lineno = getattr(node, "end_lineno", lineno)
    if end_lineno != lineno:
        return ("a differing constant spans multiple lines in an "
                "occurrence — refusing to splice a multi-line hole")
    return None


def _gate_value_holes(resolved, per_occ_leaves, diff_cols,
                      plan: RenamePlan) -> bool:
    """EVERY differing leaf must be a plain CONSTANT in every occurrence, and
    must NOT sit inside a ``match`` PATTERN, an f-string, or an annotation.
    Returns ``True`` if all holes pass, else ``False`` (recording a blocker).

    Constant-only: Name holes are DEFERRED (W99c — see the module docstring).
    The single-line check runs for EVERY occurrence (defence-in-depth behind
    the family multi-line-string rail already wired into
    :func:`_soundness_rails_blocker`, which refuses any run carrying a
    multi-line str/bytes/f-string constant, differing or shared)."""
    pattern_ids = [_pattern_node_ids(occ.stmts) for occ in resolved]
    fstring_ids = [_fstring_node_ids(occ.stmts) for occ in resolved]
    annotation_ids = [_annotation_node_ids(occ.stmts) for occ in resolved]
    for col in diff_cols:
        for i, occ in enumerate(resolved):
            node = per_occ_leaves[i][col][1]
            blocker = _hole_blocker(node, occ, pattern_ids[i], fstring_ids[i],
                                    annotation_ids[i])
            if blocker is not None:
                plan.blockers.append(blocker)
                return False
    return True


def _call_line(occ: _Occurrence, const_args: list[str], helper_name: str,
               live_in, live_out, tail_return: bool, indent: str) -> str:
    """The ONE call line that replaces an occurrence's block: its OWN ``live_in``
    args plus its OWN per-column constants, in the tail-return / live-out / bare
    form. Pure."""
    args = list(live_in) + const_args
    call_expr = f"{helper_name}({', '.join(args)})"
    if tail_return:
        return f"{indent}return {call_expr}\n"
    if live_out:
        return f"{indent}{', '.join(live_out)} = {call_expr}\n"
    return f"{indent}{call_expr}\n"


def _rewrite_call_sites(lines: list[str], occs, index_of, per_occ_leaves,
                        diff_cols, helper_name, live_in, live_out,
                        tail_return: bool) -> None:
    """Replace every occurrence's block in ``lines`` with its single call line,
    bottom-up so spans stay valid. Mutates ``lines`` in place. Pure given inputs
    (no I/O)."""
    for occ in sorted(occs, key=lambda o: o.span_lo, reverse=True):
        const_args = [_segment(occ.source,
                               per_occ_leaves[index_of[id(occ)]][col][1])
                      for col in diff_cols]
        indent = " " * (len(occ.lines[occ.span_lo - 1])
                        - len(occ.lines[occ.span_lo - 1].lstrip()))
        lines[occ.span_lo - 1:occ.span_hi] = [
            _call_line(occ, const_args, helper_name, live_in, live_out,
                       tail_return, indent)]


def _helper_insert_index(first: _Occurrence, occs) -> int:
    """Where to splice the helper block: the first occurrence's container anchor
    (its def/decorator line) rebased by the net line-delta of every replacement
    whose span ends ABOVE it. Pure.

    The anchor is an ORIGINAL-tree line number, but the bottom-up call-site
    replacements collapsed each copy's span (hi-lo+1 lines) to ONE call line,
    shrinking the buffer. ``first`` is first in EMIT order, NOT topmost in the
    file, so a copy may sit above this container; rebasing keeps the def from
    landing inside an earlier function's body (the same above/below partition
    inline_function uses so splice and deletions don't interfere)."""
    container = first.container
    anchor = min(
        [container.lineno]
        + [d.lineno for d in getattr(container, "decorator_list", [])]
    )
    delta_above = sum(
        1 - (o.span_hi - o.span_lo + 1)
        for o in occs if o.span_hi < anchor
    )
    return anchor - 1 + delta_above


def _finalize_source(lines: list[str], rel: str,
                     plan: RenamePlan) -> str | None:
    """Join ``lines``, gate that the result parses, and strip imports stranded by
    lifting the block out. Returns the final source or ``None`` (recording a
    blocker) on a parse failure."""
    new_source = "".join(lines)
    try:
        ast.parse(new_source)
    except (SyntaxError, RecursionError, MemoryError) as e:
        plan.blockers.append(f"{rel}: extraction would not parse ({e})")
        return None
    cleaned = strip_unused_imports(new_source)
    if cleaned is not None:
        new_source = cleaned
    return new_source


def _emit_rewrites(resolved, sources, trees, rels, first, first_dotted,
                   helper_name, helper_block, per_occ_leaves, diff_cols,
                   live_in, live_out, tail_return, plan: RenamePlan):
    """Rewrite every involved file (helper insertion + call sites + imports),
    bottom-up so spans stay valid. Returns ``(new_contents, edits)`` or ``None``
    (recording a blocker) if any rewritten file fails to parse."""
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
        _rewrite_call_sites(lines, occs, index_of, per_occ_leaves, diff_cols,
                            helper_name, live_in, live_out, tail_return)

        if rel == first.rel:
            insert_at = _helper_insert_index(first, occs)
            lines[insert_at:insert_at] = [helper_block]
        else:
            import_line = f"from {first_dotted} import {helper_name}\n"
            lines.insert(_import_insert_index(trees[rel]), import_line)

        new_source = _finalize_source(lines, rel, plan)
        if new_source is None:
            return None
        new_contents[rel] = new_source
        edits[rel] = len(occs) + (1 if rel != first.rel else 0)
    return new_contents, edits


def _param_seed_names(first: _Occurrence, live_in, live_out) -> list[str]:
    """Every identifier the widened ``p<n>`` fallback must never reuse: the
    helper's own params (``live_in``/``live_out``) plus EVERY name referenced
    or bound anywhere in the FIRST occurrence's statements (H-B closure — a
    shipped bug where a fallback ``p0`` colliding with a local the run itself
    binds silently read the REBOUND local instead of the parameter, e.g. a run
    binding ``p0 = n + 1`` then using it made the constant-hole's ``p0``
    argument invisible). The first occurrence's seed suffices: the structural
    template pins every non-diff-leaf name identical across occurrences, and a
    Constant hole carries no name at all, so no OTHER occurrence can introduce
    a name this seed misses."""
    names = set(live_in) | set(live_out)
    for stmt in first.stmts:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Name):
                names.add(n.id)
            elif isinstance(n, ast.arg):
                names.add(n.arg)
    return sorted(names)


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
    # Never collide with each other, live_in, live_out, or any name the FIRST
    # occurrence's own statements already reference or bind (H-B closure).
    diff_node_segments = [
        [(per_occ_leaves[i][col][1], _segment(occ.source, per_occ_leaves[i][col][1]))
         for i, occ in enumerate(resolved)]
        for col in diff_cols
    ]
    param_names = _hole_param_names(
        diff_node_segments, _param_seed_names(first, live_in, live_out))

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


def _plan_parameterized(project_root: str | Path, group, *, resolver,
                        plan_label: str = "near_dup") -> RenamePlan:
    """The shared parameterized-dedup pipeline BOTH near-dup lanes run.

    ``group`` is a :class:`~app.engine.near_dup.NearDuplicateGroup`: its
    ``occurrences`` are ``"module:lineno"`` of each block's first statement and
    its ``differences`` lists, per differing position, the source text each
    occurrence carries there. ``resolver`` decides which control-flow SHAPE is
    admissible (``_resolve_occurrence`` for dedup-parameterized's plain/tail-
    return domain; ``near_dup_total_return._resolve_parameterized_total_return``
    for the always-returning domain) — everything else (shape validation,
    module reads, diff-column location, the value-hole gates, helper build,
    call-site/import rewrites, gate-clean imports, the finalise stamp) is
    lane-agnostic and byte-identical between the two. Returns a
    :class:`RenamePlan` ready for ``apply_rename`` (suite-verified,
    auto-rollback). On the slightest doubt the plan carries a blocker and
    empty ``new_contents``."""
    plan = RenamePlan(old=plan_label, new="_shared")
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
                                          trees, plan, resolver=resolver)
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

    stamp_multi_module_plan(plan, helper_name, first.rel, sources,
                            new_contents, edits)
    return plan


def plan_near_dup_extract(project_root: str | Path, group) -> RenamePlan:
    """Plan lifting a near-duplicate ``group`` into one parameterized helper.

    ``group`` is a :class:`~app.engine.near_dup.NearDuplicateGroup`: its
    ``occurrences`` are ``"module:lineno"`` of each block's first statement and
    its ``differences`` lists, per differing position, the source text each
    occurrence carries there. Returns a :class:`RenamePlan` ready for
    ``apply_rename`` (suite-verified, auto-rollback). On the slightest doubt the
    plan carries a blocker and empty ``new_contents``. Delegates to the shared
    :func:`_plan_parameterized` pipeline with dedup_extract's occurrence
    resolver — the plain/tail-return domain, byte-identical to before the
    share-in-place refactor (``plan.old`` stays ``"near_dup"``)."""
    return _plan_parameterized(project_root, group, resolver=_resolve_occurrence)


def _hole_edit(first: _Occurrence, node: ast.AST, n_block_lines: int,
               pname: str, plan: RenamePlan):
    """Locate ONE differing constant ``node`` and return its
    ``(line_idx, col_start, col_end, replacement)`` edit, or ``None`` (recording
    a blocker) if it lacks position info, spans rows, falls outside the run, or
    can't be re-read."""
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
    if not (0 <= idx < n_block_lines):
        plan.blockers.append(
            "a differing constant falls outside the located run — refusing")
        return None
    # Verify the span really is THIS constant's source (defence in depth),
    # reading against the FULL module source where the node's positions live.
    if ast.get_source_segment(first.source, node) is None:
        plan.blockers.append(
            "could not re-read a differing constant's source span — refusing")
        return None
    return idx, col_off, end_col, pname


def _overlapping_holes_reason(holes: list[tuple[int, int, str]]) -> str | None:
    """Two holes on ONE line whose byte spans OVERLAP, or ``None``. Sorted by
    start column; adjacent pairs suffice (non-adjacent overlap would imply an
    adjacent one too, since spans are gapless within a sorted run). Defence in
    depth: the f-string rail already removes the only known producer of
    identical/overlapping spans on this Python (3.11's whole-f-string
    ``Constant``), so this should never fire on a real plan — refuse-direction
    only, never widens what lands."""
    ordered = sorted(holes, key=lambda h: h[0])
    for a, b in zip(ordered, ordered[1:]):
        if b[0] < a[1]:
            return ("two differing positions splice overlapping spans on "
                    "one line — refusing")
    return None


def _apply_line_holes(line: str, holes: list[tuple[int, int, str]],
                      plan: RenamePlan) -> str | None:
    """Splice every ``(col_start, col_end, replacement)`` hole into ONE ``line``,
    right-to-left so earlier columns stay valid. AST column offsets are UTF-8
    BYTE offsets, so the splice works on the line's encoded bytes (exactly as
    ``near_dup._segment`` slices) and decodes once at the end — slicing
    characters would misplace every hole preceded by a multi-byte character on
    its line. Returns the new line or ``None`` (recording a blocker) if any
    span is out of range, two spans overlap, or a span splits a multi-byte
    character."""
    overlap = _overlapping_holes_reason(holes)
    if overlap is not None:
        plan.blockers.append(overlap)
        return None
    raw = line.encode("utf-8")
    for c0, c1, pname in sorted(holes, key=lambda h: h[0], reverse=True):
        if c1 > len(raw.rstrip(b"\n")) or c0 < 0 or c0 >= c1:
            plan.blockers.append(
                "a differing constant's span is out of range — refusing")
            return None
        raw = raw[:c0] + pname.encode("utf-8") + raw[c1:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        plan.blockers.append(
            "a differing constant's span splits a multi-byte character — "
            "refusing")
        return None


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
        edit = _hole_edit(first, leaves[col][1], len(block_lines), pname, plan)
        if edit is None:
            return None
        edits.append(edit)

    # Apply per-line, right-to-left, so earlier columns stay valid.
    grouped: dict[int, list[tuple[int, int, str]]] = {}
    for idx, c0, c1, pname in edits:
        grouped.setdefault(idx, []).append((c0, c1, pname))
    for idx, holes in grouped.items():
        line = _apply_line_holes(block_lines[idx], holes, plan)
        if line is None:
            return None
        block_lines[idx] = line

    return "".join(block_lines)
