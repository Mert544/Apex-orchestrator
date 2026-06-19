"""Rule synthesis — Apex proposes its OWN candidate fix-rules.

Apex ships ~39 hand-written behaviour-preserving transforms.  This module is
the generation leap: instead of only *running* hand-written rules, it MINES a
set of Python sources' ASTs for a recurring, mechanically-rewritable micro-
pattern that no existing transform necessarily covers, and emits a candidate
rewrite-rule *descriptor* — a grounded PROPOSAL a human could turn into a real
transform.

It is **recommend-only by design**: it never generates executable code and
never applies anything.  Every descriptor carries a ``safety_note`` reminding a
human to verify behaviour-preservation before acting.  Pure AST, deterministic
(canonical shape keys, fixed thresholds, sorted output — no time/random),
stdlib-only.
"""

from __future__ import annotations

import ast

# A pattern must recur at this many sites before we surface it.  Conservative:
# two occurrences is coincidence, three is a habit worth a human's attention.
DEFAULT_MIN_SUPPORT = 3

# Cap on distinct shapes we retain, so output stays bounded on huge inputs.
_MAX_SHAPES = 64

# Cap on example sites recorded per shape, so descriptors stay small.
_MAX_EXAMPLES = 5

# Statement node types whose structural shape we mine.  Restricted to small,
# self-contained micro-patterns that are plausibly mechanically rewritable.
_MINED_STMTS: tuple[type[ast.stmt], ...] = (ast.If, ast.Assign, ast.Return)


def _shape_key(node: ast.AST) -> str:
    """Canonical, identifier/literal-abstracted structural key for ``node``.

    Names become ``N``, attribute accesses ``A``, constants their type tag
    (``C:int``); structural keywords (operators, ``if``/``return``) are kept
    verbatim.  Two subtrees that differ only in which identifiers or literal
    values they use therefore collapse to the same key — that is what makes a
    *pattern* rather than a *snippet*.  The walk is ordered by AST field order,
    so the key is deterministic.
    """
    if isinstance(node, ast.Name):
        return "N"
    if isinstance(node, ast.Attribute):
        return f"A({_shape_key(node.value)})"
    if isinstance(node, ast.Constant):
        return f"C:{type(node.value).__name__}"
    tag = type(node).__name__
    parts = [_shape_key(c) for c in ast.iter_child_nodes(node)]
    if not parts:
        return tag
    return f"{tag}[{','.join(parts)}]"


def _is_mined(node: ast.AST) -> bool:
    """True if ``node`` is a statement type we mine."""
    return isinstance(node, _MINED_STMTS)


def _site_label(path: str, node: ast.stmt) -> str:
    """Human-readable ``path:lineno`` label for an example site."""
    line = getattr(node, "lineno", 0)
    return f"{path}:{line}"


def _accumulate(sources: dict[str, str]) -> dict[str, list[str]]:
    """Map each shape key to the sorted list of sites where it occurs.

    Unparseable sources are skipped (never raise).  Sites are collected in a
    stable order and sorted, so the mapping is deterministic regardless of dict
    iteration order across runs.
    """
    sites: dict[str, list[str]] = {}
    for path in sorted(sources):
        try:
            tree = ast.parse(sources[path])
        except (SyntaxError, RecursionError, MemoryError):
            continue
        for node in ast.walk(tree):
            if not _is_mined(node):
                continue
            key = _shape_key(node)
            sites.setdefault(key, []).append(_site_label(path, node))
    return {k: sorted(v) for k, v in sites.items()}


def _support_sort_key(pattern: dict) -> tuple:
    """Sort patterns by descending support, then shape key for a stable tie-break."""
    return (-pattern["support"], pattern["shape"])


def mine_recurring_patterns(
    sources: dict[str, str], min_support: int = DEFAULT_MIN_SUPPORT
) -> list[dict]:
    """Find syntactic micro-patterns recurring across >= ``min_support`` sites.

    Each returned pattern is ``{"shape", "support", "example_sites"}`` where
    ``shape`` is the identifier-abstracted structural key, ``support`` the
    occurrence count, and ``example_sites`` a bounded, sorted sample of
    ``path:lineno`` labels.  Output is sorted by descending support (shape key
    breaking ties) and capped at ``_MAX_SHAPES``.  Empty or non-recurring input
    yields ``[]`` and never raises.
    """
    if not sources or min_support < 1:
        return []
    sites = _accumulate(sources)
    patterns: list[dict] = []
    for shape, where in sites.items():
        if len(where) < min_support:
            continue
        patterns.append(
            {
                "shape": shape,
                "support": len(where),
                "example_sites": where[:_MAX_EXAMPLES],
            }
        )
    patterns.sort(key=_support_sort_key)
    return patterns[:_MAX_SHAPES]


def _suggested_name(shape: str) -> str:
    """Deterministic, file-safe suggested transform name from a shape key.

    Derives a short slug from the leading structural tag so a human gets a
    stable starting handle (e.g. ``If[...]`` -> ``synthesised_if_rule``).
    """
    head = shape.split("[", 1)[0].split("(", 1)[0]
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in head)
    slug = slug.strip("_") or "pattern"
    return f"synthesised_{slug}_rule"


def synthesise_candidate_rule(pattern: dict) -> dict:
    """Emit a candidate rewrite-rule *descriptor* for a high-support pattern.

    Returns ``{"shape", "support", "example_sites", "suggested_name",
    "rationale", "safety_note"}``.  This describes what a transform for the
    pattern WOULD address; it generates no executable code and applies nothing.
    The ``safety_note`` is mandatory: behaviour-preservation is NOT claimed and
    must be verified by a human before any transform is written.
    """
    shape = pattern.get("shape", "")
    support = int(pattern.get("support", 0))
    examples = list(pattern.get("example_sites", []))
    rationale = (
        f"Structural shape {shape!r} recurs across {support} sites "
        "(identifiers and literals abstracted), suggesting a mechanical "
        "micro-pattern a single transform could normalise."
    )
    safety_note = (
        "RECOMMEND-ONLY: behaviour-preservation is NOT verified. A human must "
        "confirm the rewrite is semantics-preserving across all sites before "
        "implementing a transform; Apex proposes, it does not apply."
    )
    return {
        "shape": shape,
        "support": support,
        "example_sites": examples,
        "suggested_name": _suggested_name(shape),
        "rationale": rationale,
        "safety_note": safety_note,
    }


def propose_rules(sources: dict[str, str], top: int = 3) -> list[dict]:
    """Top ``top`` candidate rule descriptors by support, deterministically.

    Mines ``sources`` at the default support threshold and wraps the strongest
    patterns as candidate descriptors.  Recommend-only: nothing is applied.
    Empty / non-recurring input yields ``[]`` and never raises.
    """
    if top < 1:
        return []
    patterns = mine_recurring_patterns(sources)
    return [synthesise_candidate_rule(p) for p in patterns[:top]]
