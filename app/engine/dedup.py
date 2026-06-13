"""Deterministic code-duplication detector — find copy-pasted blocks.

Duplication is a top maintainability signal: a bug fixed in one copy is silently
left unfixed in the other three. This module locates contiguous runs of identical
statements that appear in two or more distinct places across the project's own
modules (fixtures and tests excluded).

Normalization (v1, documented and intentionally simple): each statement is
structurally dumped with ``ast.dump(stmt, annotate_fields=False)`` — attributes
(line/column positions) are NOT included, so reformatting and re-indentation do
not defeat a match, but identifier names ARE part of the fingerprint. This
reliably catches true copy-paste. Renamed-local clones (same structure, different
variable names) are a deliberate future enhancement: canonicalizing names risks
false positives, so v1 stays honest about what it reports.

Scope: only the bodies of ``FunctionDef``/``AsyncFunctionDef`` are scanned — the
cleanest statement scope — using a sliding window of ``min_statements`` contiguous
statements. Scanning is bounded (a per-function window cap) so a pathologically
large file cannot explode. Deterministic, stdlib-only.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.engine.source_index import indexed_project


# Upper bound on windows examined per function body. A function with N statements
# yields at most (N - min_statements + 1) windows; this cap keeps a single
# generated/huge function from dominating the scan. Purely a safety rail.
_MAX_WINDOWS_PER_FUNCTION = 2000


@dataclass
class DuplicateBlock:
    """A run of statements that appears, identically, in several places."""

    fingerprint: str
    lines: int
    occurrences: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "lines": self.lines,
            "occurrences": list(self.occurrences),
        }


def _normalize_stmt(stmt: ast.stmt) -> str:
    """Structural fingerprint of one statement (positions stripped, names kept)."""
    return ast.dump(stmt, annotate_fields=False)


def _function_bodies(tree: ast.Module) -> list[list[ast.stmt]]:
    """Every function/async-function body in the module (in source order)."""
    bodies: list[list[ast.stmt]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body:
                bodies.append(node.body)
    return bodies


def find_duplicates(
    project_root: str | Path,
    min_statements: int = 5,
    min_occurrences: int = 2,
) -> list[DuplicateBlock]:
    """Find duplicated statement blocks across the project's own modules.

    For every non-fixture module, each function body is scanned with a sliding
    window of ``min_statements`` contiguous statements; identical windows
    (by normalized fingerprint) occurring in ``>= min_occurrences`` DISTINCT
    locations ("module:lineno") are reported. A window overlapping itself at the
    same location is counted once, never twice.

    Internally each candidate window is *bucketed* by its normalized fingerprint:
    grouping is a single dictionary insertion per window, so the dominant cost is
    O(windows) hashing rather than an O(windows²) pairwise comparison. The
    fingerprint string is built from a per-statement cache so each statement is
    structurally dumped exactly once, even though overlapping windows share most
    of their statements. Neither optimization changes the fingerprint a window
    maps to — output is byte-for-byte identical to the naive scan.

    Returns a deterministic list sorted by ``lines`` descending, then by
    ``fingerprint``.
    """
    min_statements = max(1, int(min_statements))
    min_occurrences = max(1, int(min_occurrences))

    # fingerprint -> ordered, de-duplicated list of "module:lineno" locations.
    groups: dict[str, list[str]] = {}

    # Reuse the parse-once index (fixtures/tests already excluded, broken modules
    # carry ``tree is None``); this avoids re-reading and re-parsing every module.
    for module in indexed_project(project_root).parsed_modules():
        rel = module.rel
        tree = module.tree
        assert tree is not None  # parsed_modules() guarantees this

        for body in _function_bodies(tree):
            limit = len(body) - min_statements + 1
            if limit <= 0:
                continue
            limit = min(limit, _MAX_WINDOWS_PER_FUNCTION)
            # Dump each statement once; overlapping windows reuse these parts so
            # the join below reproduces the exact "\n"-joined fingerprint without
            # re-dumping a statement for every window it participates in.
            window_count = limit + min_statements - 1
            dumps = [_normalize_stmt(s) for s in body[:window_count]]
            for start in range(limit):
                fingerprint = "\n".join(dumps[start:start + min_statements])
                location = f"{rel}:{body[start].lineno}"
                seen = groups.setdefault(fingerprint, [])
                if location not in seen:
                    seen.append(location)

    blocks = [
        DuplicateBlock(
            fingerprint=fingerprint,
            lines=min_statements,
            occurrences=sorted(locations),
        )
        for fingerprint, locations in groups.items()
        if len(locations) >= min_occurrences
    ]
    blocks.sort(key=lambda b: (-b.lines, b.fingerprint))
    return blocks


def render_duplicates_markdown(blocks: list[DuplicateBlock]) -> str:
    """A readable duplication report; empty input → a clean all-clear message."""
    if not blocks:
        return "# Code Duplication\n\nNo significant duplication detected."

    lines = [
        "# Code Duplication",
        "",
        f"{len(blocks)} duplicated block(s):",
        "",
    ]
    for i, block in enumerate(blocks, 1):
        lines.append(f"## Block {i} — {block.lines} statement(s), "
                     f"{len(block.occurrences)} occurrence(s)")
        for loc in block.occurrences:
            lines.append(f"- `{loc}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
