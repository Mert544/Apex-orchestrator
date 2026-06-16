"""Deterministic NEAR-duplicate detector — structurally identical, leaf-different blocks.

:mod:`app.engine.dedup` (``find_duplicates``) catches only BYTE-identical statement
blocks: its fingerprint, ``ast.dump(stmt, annotate_fields=False)``, keeps every
identifier and literal, so ``x = 1`` and ``x = 2`` are different blocks. On a mature
codebase the dominant remaining duplication is exactly that shape — runs of statements
that are STRUCTURALLY identical and differ only at a handful of leaf *values* (a
constant, a Load name). A bug fixed in one copy is silently left unfixed in the others.

This module finds those NEAR-duplicates and REPORTS them — it is analysis only. It
performs no rewrite; it produces the data a future, careful parameterized-extraction
step will consume: "these N blocks are identical except at positions P1..Pk, where
occurrence i carries values V_i" so a generated helper can take those as parameters.

How a near-duplicate group is decided (deterministic, conservative):

- Candidate blocks are enumerated exactly as :func:`find_duplicates`: sliding windows
  of ``min_statements`` contiguous statements over each ``FunctionDef``/
  ``AsyncFunctionDef`` body, bounded by ``_MAX_WINDOWS_PER_FUNCTION``, fixtures/tests
  excluded (via :func:`app.engine.source_index.indexed_project`).
- Each window is reduced to a *structural template*: a synchronized AST walk that
  records every node's type and field shape. At a leaf that is in a SAFE value
  position — an :class:`ast.Constant`, or an :class:`ast.Name` loaded (``Load``) —
  the concrete value is WILDCARDED in the template and its source text is recorded by
  structural path. Any OTHER difference (node type, child count, an operator, a
  keyword, a ``Store``/``Del`` target name, an attribute name) is part of the template
  and so cannot differ between members of a group: the structure must match exactly.
- Windows are bucketed by their template string. Members of one bucket share the same
  wildcard paths by construction; a path is a *differing position* when its recorded
  source text is not identical across all occurrences. A group is reported only when
  it has ``>= min_occurrences`` occurrences and ``1 <= diff_count <= max_diffs`` — zero
  differences would be an EXACT duplicate (``find_duplicates``' job) and is excluded.

Determinism, stdlib-only: groups are sorted by ``(-lines, -occurrences, template)`` and
occurrences are sorted; no time, randomness, network, git, or identity strings.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.engine.source_index import indexed_project

# Mirror dedup.py's safety rail: at most this many sliding windows per function body,
# so a single pathologically large/generated function cannot dominate the scan.
_MAX_WINDOWS_PER_FUNCTION = 2000

# Sentinel emitted into a template string at a wildcarded (safe value) leaf. It is
# distinct from any real ``ast.dump`` text so a template can never collide with a
# structurally different window that merely happens to contain this literal.
_WILDCARD = "\x00WILD\x00"


@dataclass
class NearDuplicateGroup:
    """A set of structurally identical blocks differing only at safe value leaves.

    ``occurrences`` are ``"module:lineno"`` for each block's first statement (sorted).
    ``lines`` is the statement count of the block. ``diff_count`` is the number of leaf
    positions that actually differ across the occurrences. ``differences`` is parallel
    to ``occurrences`` per differing position: ``differences[k]`` lists the source text
    each occurrence carries at the k-th differing position (same order as
    ``occurrences``)."""

    occurrences: list[str]
    lines: int
    diff_count: int
    differences: list[list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "occurrences": list(self.occurrences),
            "lines": self.lines,
            "diff_count": self.diff_count,
            "differences": [list(d) for d in self.differences],
        }


def _function_bodies(tree: ast.Module) -> list[list[ast.stmt]]:
    """Every function/async-function body in the module (in source order)."""
    bodies: list[list[ast.stmt]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            bodies.append(node.body)
    return bodies


def _is_value_leaf(node: ast.AST) -> bool:
    """Is ``node`` a SAFE, value-position leaf whose value may differ between clones?

    Only two kinds qualify — and only these are allowed to vary within a group:

    * an :class:`ast.Constant` (a literal value), and
    * an :class:`ast.Name` in a ``Load`` context (reading a value).

    A ``Name`` in ``Store``/``Del`` context (a binding target) is deliberately NOT a
    value leaf: differing there changes what the block *binds*, not just a value it
    reads, so such blocks are not interchangeable and must not be grouped."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return isinstance(node.ctx, ast.Load)
    return False


def _split_source_lines(source: str) -> list[str]:
    """Split ``source`` into lines EXACTLY as :func:`ast.get_source_segment` does
    (via the stdlib ``_splitlines_no_ff``), computed ONCE per module so segment
    extraction becomes O(1) slicing instead of re-splitting the whole source on
    every value leaf. The split is byte-for-byte identical to the stdlib's, so the
    extracted segments are unchanged."""
    return ast._splitlines_no_ff(source)  # type: ignore[attr-defined]


def _segment(lines: list[str], node: ast.AST) -> str:
    """Source text of ``node``, computed by slicing pre-split ``lines`` — an O(1)
    re-implementation of :func:`ast.get_source_segment` (non-padded) that reuses a
    per-module line split instead of re-splitting the source on every call.

    The slicing logic mirrors ``get_source_segment`` byte-for-byte (same
    ``.encode()[…].decode()`` byte-offset handling for multi-byte source), so the
    returned segment is identical to the stdlib's. The fallback only fires for nodes
    lacking position info; for the Constant/Name leaves we wildcard, positions are
    always present, so it stays deterministic."""
    end_lineno = getattr(node, "end_lineno", None)
    end_col_offset = getattr(node, "end_col_offset", None)
    if end_lineno is not None and end_col_offset is not None:
        lineno = node.lineno - 1
        end_lineno -= 1
        col_offset = node.col_offset
        if end_lineno == lineno:
            return lines[lineno].encode()[col_offset:end_col_offset].decode()
        first = lines[lineno].encode()[col_offset:].decode()
        last = lines[end_lineno].encode()[:end_col_offset].decode()
        middle = lines[lineno + 1:end_lineno]
        return first + "".join(middle) + last
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.Name):
        return node.id
    return type(node).__name__


def _walk_template(
    node: ast.AST,
    lines: list[str],
    path: str,
    out: list[str],
    wildcards: dict[str, str],
) -> None:
    """Append ``node``'s structural template to ``out``; record value-leaf segments.

    The template is a fully bracketed pre-order encoding of node TYPES and field
    SHAPE (which fields are present and, for list fields, their lengths). Concrete
    values that live at safe value leaves are replaced by ``_WILDCARD`` in the
    template and stored in ``wildcards`` keyed by a deterministic structural ``path``;
    everything else (operators, ``Store`` target names, attribute names, keywords,
    non-value constants' containers, …) is encoded verbatim into the template, so two
    windows share a template only when they are identical apart from value leaves.
    """
    if _is_value_leaf(node):
        # Wildcard the value; the surrounding structure (that this position holds a
        # Constant vs a loaded Name) IS still part of the template, so a Constant and
        # a Name never share a template even though both are wildcarded here.
        out.append(f"{type(node).__name__}({_WILDCARD})")
        wildcards[path] = _segment(lines, node)
        return

    out.append(type(node).__name__)
    out.append("(")
    # ``_fields`` is a fixed, ordered tuple per node type — deterministic iteration.
    for fname in node._fields:
        value = getattr(node, fname, None)
        out.append(f"{fname}=")
        if isinstance(value, list):
            out.append(f"[{len(value)}:")
            for i, item in enumerate(value):
                if isinstance(item, ast.AST):
                    _walk_template(item, lines, f"{path}.{fname}[{i}]", out, wildcards)
                else:
                    # Primitive list element (rare) — encode by repr.
                    out.append(repr(item))
                out.append(",")
            out.append("]")
        elif isinstance(value, ast.AST):
            _walk_template(value, lines, f"{path}.{fname}", out, wildcards)
        else:
            # A primitive field: an operator class is identity-bearing structure, a
            # Store/Load ctx, an attribute/identifier name, a non-leaf constant, etc.
            # Encode it verbatim so any difference splits the template.
            out.append(repr(value))
        out.append(";")
    out.append(")")


def _statement_fragment(
    stmt: ast.stmt, lines: list[str]
) -> tuple[str, list[tuple[str, str]]]:
    """One statement's structural template fragment and its value-leaf
    ``(subpath, segment)`` list — computed ONCE, so overlapping windows reuse it
    instead of re-walking shared statements.

    The walk uses an empty root path, so subpaths are relative to the statement
    (``.field[i]…``, or ``""`` for a root leaf). A window at index ``i`` prefixes
    them with ``s{i}`` to recover the exact per-window wildcard path — and the
    fragment STRING is path-independent (``_walk_template`` never writes the path
    into the template), so concatenating fragments is identical to templating the
    whole window."""
    out: list[str] = []
    wildcards: dict[str, str] = {}
    _walk_template(stmt, lines, "", out, wildcards)
    return "".join(out), list(wildcards.items())


def _window_template(
    frags: list[tuple[str, list[tuple[str, str]]]],
    start: int,
    min_statements: int,
) -> tuple[str, list[tuple[str, str]]]:
    """The template string and sorted wildcard ``(path, segment)`` list for the window
    of ``min_statements`` statements starting at ``frags[start]``.

    Fragments overlap between windows, so they are pre-computed once per body and only
    concatenated here. Statement ``i`` in the window prefixes its subpaths with ``s{i}``
    to recover the exact per-window wildcard path; the fragment STRING is
    path-independent, so concatenating fragments equals templating the whole window."""
    parts: list[str] = []
    wc_items: list[tuple[str, str]] = []
    for i in range(min_statements):
        frag_t, frag_wc = frags[start + i]
        parts.append(frag_t)
        parts.append("|")
        for subpath, seg in frag_wc:
            wc_items.append((f"s{i}{subpath}", seg))
    return "".join(parts), sorted(wc_items)


def _index_body(
    rel: str,
    body: list[ast.stmt],
    lines: list[str],
    min_statements: int,
    buckets: dict[str, dict[str, tuple[str, ...]]],
    bucket_paths: dict[str, tuple[str, ...]],
) -> None:
    """Bucket every sliding window of one function body into ``buckets``/``bucket_paths``.

    ``buckets`` maps template -> { ``"module:lineno"`` -> per-path segment tuple };
    ``bucket_paths`` records each template's sorted wildcard paths once. Windows are
    bounded by :data:`_MAX_WINDOWS_PER_FUNCTION`; a location reached twice (overlapping
    self) is counted once. Mutates the two dicts in place; returns nothing."""
    limit = len(body) - min_statements + 1
    if limit <= 0:
        return
    limit = min(limit, _MAX_WINDOWS_PER_FUNCTION)
    # Template each statement that appears in any window ONCE; windows
    # then concatenate fragments (they overlap by min_statements - 1).
    needed = limit + min_statements - 1
    frags = [_statement_fragment(body[k], lines) for k in range(needed)]
    for start in range(limit):
        template, wildcards = _window_template(frags, start, min_statements)
        location = f"{rel}:{body[start].lineno}"
        occ = buckets.setdefault(template, {})
        if location in occ:
            # Same location reached twice (overlapping self) — count once.
            continue
        occ[location] = tuple(seg for _, seg in wildcards)
        bucket_paths.setdefault(template, tuple(p for p, _ in wildcards))


def _diff_columns(
    occ_map: dict[str, tuple[str, ...]],
    locations: list[str],
    n_paths: int,
) -> list[list[str]]:
    """Per-wildcard-path columns whose recorded segments are NOT identical across
    ``locations`` (path order is deterministic). Each returned column lists the segment
    each location carries, in ``locations`` order."""
    columns: list[list[str]] = []
    for col in range(n_paths):
        values = [occ_map[loc][col] for loc in locations]
        if len(set(values)) > 1:
            columns.append(values)
    return columns


def _build_group(
    occ_map: dict[str, tuple[str, ...]],
    paths: tuple[str, ...],
    min_statements: int,
    min_occurrences: int,
    max_diffs: int,
) -> NearDuplicateGroup | None:
    """The :class:`NearDuplicateGroup` for one template bucket, or ``None`` if it fails
    a threshold: fewer than ``min_occurrences`` occurrences, or a differing-position
    count outside ``1..max_diffs`` (0 == exact duplicate, dedup's job)."""
    if len(occ_map) < min_occurrences:
        return None
    locations = sorted(occ_map)
    diff_columns = _diff_columns(occ_map, locations, len(paths))
    diff_count = len(diff_columns)
    if diff_count < 1 or diff_count > max_diffs:
        return None
    return NearDuplicateGroup(
        occurrences=locations,
        lines=min_statements,
        diff_count=diff_count,
        differences=diff_columns,
    )


def find_near_duplicates(
    project_root: str | Path,
    *,
    min_statements: int = 5,
    min_occurrences: int = 2,
    max_diffs: int = 3,
) -> list[NearDuplicateGroup]:
    """Find near-duplicate statement blocks across the project's own modules.

    A near-duplicate group is a set of ``>= min_occurrences`` statement windows that
    are STRUCTURALLY identical (same tree of node types and field shape) and differ
    only at safe value leaves (:class:`ast.Constant`, loaded :class:`ast.Name`), with
    between 1 and ``max_diffs`` differing leaf positions. Zero-difference (exact)
    duplicates are excluded — those belong to :func:`find_duplicates`.

    Returns a deterministic list sorted by ``lines`` desc, then occurrence count desc,
    then the structural template; occurrences within a group are sorted.
    """
    min_statements = max(1, int(min_statements))
    min_occurrences = max(1, int(min_occurrences))
    max_diffs = max(1, int(max_diffs))

    # template -> { location -> tuple(segment per wildcard path) }. The wildcard paths
    # are identical for every member of a template bucket (they ARE encoded into the
    # template), so we store the per-occurrence segment tuple in path-sorted order.
    buckets: dict[str, dict[str, tuple[str, ...]]] = {}
    # template -> the sorted wildcard paths (recorded once per template, for ordering).
    bucket_paths: dict[str, tuple[str, ...]] = {}

    for module in indexed_project(project_root).parsed_modules():
        tree = module.tree
        assert tree is not None  # parsed_modules() guarantees this
        # Pre-split the source ONCE per module so each value-leaf's segment is an
        # O(1) slice of these lines, not a fresh re-split of the whole source.
        lines = _split_source_lines(module.source)
        for body in _function_bodies(tree):
            _index_body(module.rel, body, lines, min_statements, buckets, bucket_paths)

    groups: list[NearDuplicateGroup] = []
    for template, occ_map in buckets.items():
        group = _build_group(
            occ_map, bucket_paths[template], min_statements, min_occurrences, max_diffs
        )
        if group is not None:
            groups.append(group)

    groups.sort(key=lambda g: (-g.lines, -len(g.occurrences), _group_key(g)))
    return groups


# Memoize by tree fingerprint so an objective's fitness AND moves share ONE
# (~100s) scan instead of running the heavyweight detector twice.
_NEAR_DUP_CACHE: dict[tuple, tuple] = {}


def near_duplicates(project_root: str | Path, *, min_statements: int = 5,
                    min_occurrences: int = 2, max_diffs: int = 3,
                    fresh: bool = False) -> list[NearDuplicateGroup]:
    """:func:`find_near_duplicates`, memoized by the project's ``(path, mtime)``
    fingerprint (reusing the source index's staleness check). Rebuilds only when
    files change or ``fresh`` is set — so the parameterized-dedup objective pays
    the heavy scan once per tree state, not once per fitness/moves call."""
    from app.engine.source_index import _fingerprint

    root = Path(project_root).resolve()
    key = (str(root), min_statements, min_occurrences, max_diffs)
    fp = _fingerprint(root)
    if not fresh:
        cached = _NEAR_DUP_CACHE.get(key)
        if cached is not None and cached[0] == fp:
            return cached[1]
    groups = find_near_duplicates(root, min_statements=min_statements,
                                  min_occurrences=min_occurrences, max_diffs=max_diffs)
    _NEAR_DUP_CACHE[key] = (fp, groups)
    return groups


def _group_key(group: NearDuplicateGroup) -> tuple[str, ...]:
    """A stable, template-free tie-breaker for two groups with equal size/occurrences.

    Built from the sorted occurrences plus a flattened view of the differences so the
    ordering is fully determined by reportable data (the raw template string carries a
    sentinel byte and is an internal detail)."""
    flat = tuple(v for column in group.differences for v in column)
    return tuple(group.occurrences) + flat


def render_near_duplicates_markdown(groups: list[NearDuplicateGroup]) -> str:
    """A readable near-duplication report; empty input → a clean all-clear message."""
    if not groups:
        return "# Near-Duplication\n\nNo near-duplicate blocks detected."

    lines = [
        "# Near-Duplication",
        "",
        f"{len(groups)} near-duplicate group(s) "
        "(structurally identical, differing only at value leaves):",
        "",
    ]
    for i, group in enumerate(groups, 1):
        lines.append(
            f"## Group {i} — {group.lines} statement(s), "
            f"{len(group.occurrences)} occurrence(s), "
            f"{group.diff_count} differing position(s)"
        )
        for loc in group.occurrences:
            lines.append(f"- `{loc}`")
        for p, column in enumerate(group.differences, 1):
            rendered = " | ".join(f"`{v}`" for v in column)
            lines.append(f"  - position {p}: {rendered}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
