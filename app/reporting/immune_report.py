"""Apex's IMMUNE posture — a proactive, project-wide view of where the suite is
blindest, so the immune system knows where to strike BEFORE a bug lands.

Apex already has a reactive immune response: the ``strengthen-tests`` objective
runs the mutation engine on ONE module, finds a surviving mutant (a seeded fault
the suite let through — a proven blind spot), and lands a double-gated assertion
that KILLS it. What this module adds is the PROACTIVE, whole-project half the
Dream layer's "immune agent" needs: a cheap, deterministic static rank of every
module by blind-spot RISK — many blindly-callable public functions, few covering
tests — so a bounded immune sweep spends its effort where a surviving mutant is
most likely to hide, instead of alphabetically.

Cheap by design: it reuses ``strengthen-tests``'s OWN static yield rank
(``_ranked_modules``) — a pure-AST signal (covering-test count, blindly-callable
public-function count), NOT the expensive per-mutant copytree+pytest — so the
posture is a fast, offline, deterministic read. The actual killing tests are
landed by the proven ``strengthen-tests`` lander (``apex immune --apply``); this
report only says WHERE. Zero-token.
"""

from __future__ import annotations

import ast
from pathlib import Path

__all__ = [
    "immune_posture",
    "render_immune_markdown",
]


def _has_linked_test(root: Path, rel: str) -> bool:
    """True when a test file named for this module exists (``tests/test_<stem>.py``
    or a ``tests/test_<stem>_*.py`` variant) — a cheap, deterministic coverage
    proxy: its absence is the single strongest signal the suite is blind here.

    A PRIVATE module (``_apply_verify.py``) is conventionally tested under a name
    WITHOUT the leading underscore (``test_apply_verify_shared.py``), so the raw
    ``test__apply_verify*`` glob would miss it and falsely report the module blind
    — an over-count that cries wolf on well-tested private helpers. So the
    underscore-stripped stem is tried too; ``lstrip('_')`` handles a dunder or
    multi-underscore prefix in one step."""
    stems = {Path(rel).stem}
    stems.add(next(iter(stems)).lstrip("_"))
    return any(
        s and (list(root.glob(f"tests/test_{s}.py"))
               or list(root.glob(f"tests/test_{s}_*.py")))
        for s in stems)


def immune_posture(root: str | Path, top: int = 20) -> dict:
    """A deterministic, CHEAP ranking of the project's own modules by blind-spot
    RISK — where a surviving mutant most likely hides, so an immune sweep strikes
    there first.

    Fast by design (O(modules), pure-AST + a filename glob, NO per-module
    cross-scan of the test corpus): each module's risk is its count of
    blindly-callable public functions (the mutation surface) weighed against
    whether a test file is named for it. A module with many callable functions and
    NO linked test sorts first. ``top_risk`` carries ``callable_funcs`` and
    ``has_linked_test`` per module, ranked most-exposed first. The precise
    per-mutant ranking still governs the actual ``strengthen-tests`` landing
    (``apex immune --apply``); this is the fast WHERE. Never raises; a project with
    no callable public function yields an empty list."""
    from app.engine.objective_compiler import _own_modules
    from app.execution.test_shield import _safe_functions

    root = Path(root)
    rows = []
    for rel, src in _own_modules(root):
        try:
            funcs = _safe_functions(ast.parse(src))
        except (SyntaxError, RecursionError, MemoryError):
            continue
        if not funcs:
            continue  # nothing blindly-callable -> the immune engine can't strike
        rows.append({
            "module": rel,
            "callable_funcs": len(funcs),
            "has_linked_test": _has_linked_test(root, rel),
        })
    # Untested-and-wide first: linked-test absent, then most callable functions,
    # then path — a total, deterministic order.
    rows.sort(key=lambda r: (r["has_linked_test"], -r["callable_funcs"], r["module"]))
    return {"candidates": len(rows), "top_risk": rows[:max(0, top)]}


def render_immune_markdown(posture: dict) -> str:
    """Render the immune posture as markdown for the CLI, foregrounding the modules
    with the widest mutation surface and the thinnest test net. An empty posture
    renders an honest "nothing to immunise" line."""
    rows = posture.get("top_risk") or []
    lines = ["# Immune posture — where the suite is blindest", ""]
    if not rows:
        lines.append(
            "No module has a blindly-callable public function the immune system "
            "could strengthen — nothing to immunise right now.")
        return "\n".join(lines) + "\n"
    lines.append(
        f"{posture.get('candidates', 0)} module(s) could be immunised. The most "
        "exposed first (many callable functions, no linked test — where a surviving "
        "mutant most likely hides). Run `apex immune --apply` to land double-gated "
        "mutant-killing assertions via the strengthen-tests engine.")
    lines += ["", "## Highest blind-spot risk", ""]
    for row in rows:
        note = "" if row["has_linked_test"] else " ⚠ no linked test"
        lines.append(
            f"- `{row['module']}` — {row['callable_funcs']} callable fn(s){note}")
    return "\n".join(lines) + "\n"
