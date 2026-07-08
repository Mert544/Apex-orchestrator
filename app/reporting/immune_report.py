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

Cheap by design: pure-AST signals only — the blindly-callable public-function
count (the mutation surface) and whether any test's imports actually REACH the
module (the same import-reachability rule ``covering_test_files`` scopes mutant
runs with, evaluated against a parse-once test-import index), NOT the expensive
per-mutant copytree+pytest — so the posture is a fast, offline, deterministic
read. The actual killing tests are landed by the proven ``strengthen-tests``
lander (``apex immune --apply``); this report only says WHERE. Zero-token.
"""

from __future__ import annotations

import ast
from pathlib import Path

__all__ = [
    "immune_posture",
    "render_immune_markdown",
]


def _test_import_index(root: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Every dotted name any test file imports, parsed ONCE per sweep, as
    ``(names, dotted_prefixes)``:

    * ``names`` — the union of all test files' imported names. Linkage only
      needs EXISTENCE (is there at least one test whose imports reach the
      module?), and an intersection with a union is non-empty iff it is
      non-empty with some member — so per-file sets can collapse to one set
      without changing any answer.
    * ``dotted_prefixes`` — every proper dotted prefix of those names with a
      trailing dot (``pkg.sub.x`` -> ``pkg.``, ``pkg.sub.``), precomputed so a
      package-``__init__`` prefix match is a set lookup, not a per-name
      ``startswith`` scan.

    Same corpus and honest degrade as ``covering_test_files``: sorted walk,
    skip-dirs skipped, a test file that fails to parse contributes nothing."""
    from app.engine.mutation_tester import _imported_names, _is_test_file
    from app.engine.skip_dirs import SKIPPED_DIRS

    names: set[str] = set()
    prefixes: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIPPED_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        if not _is_test_file(rel):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        for name in _imported_names(tree):
            names.add(name)
            parts = name.split(".")
            prefixes.update(f"{'.'.join(parts[:i])}." for i in range(1, len(parts)))
    return frozenset(names), frozenset(prefixes)


def _has_linked_test(
        root: Path, rel: str,
        index: tuple[frozenset[str], frozenset[str]] | None = None) -> bool:
    """True when at least one test file's imports would EXECUTE this module —
    directly, transitively through a project module, or via an ancestor-package
    ``__init__`` — the exact rule ``covering_test_files`` scopes mutant runs
    with, so ``_has_linked_test(root, rel) == bool(covering_test_files(root,
    rel))`` by construction (pinned in the tests).

    SEMANTIC UPGRADE (2026-07-08) from the old ``tests/test_<stem>*.py``
    filename glob, honest in both directions: a same-named test that never
    imports the module no longer masks a true blind spot, and a differently- or
    transitively-named test that DOES import it no longer cries wolf.

    Why not just call ``covering_test_files`` per module (one source of truth)?
    Its per-module cost is a full-tree walk + a parse of EVERY test file —
    measured ~5 s/module on Apex itself (643 modules => ~54 min/sweep),
    prohibitive for a posture read. Instead the test-import index is built ONCE
    per sweep (``_test_import_index``, ~4-5 s here) and each module pays:

    * a cheap direct check — its own dotted prefixes/leaf (``_import_targets``)
      against the index (string ops only; links 403/425 candidates here), and
    * only on a direct miss, one ``reaching_import_names`` query (~0.14 s,
      dominated by the graph cache's stat-fingerprint revalidation) for the
      transitive/ancestor-``__init__`` names — so the expensive path is paid
      only for the few modules that might be genuine blind spots.

    ``index`` is threaded in by ``immune_posture``; ``None`` builds a fresh one
    (single-module callers). Deterministic for a given tree state."""
    from app.engine.import_reach import reaching_import_names
    from app.engine.mutation_tester import _import_targets

    imported, imported_prefixes = (
        index if index is not None else _test_import_index(root))
    if imported & _import_targets(root, rel):
        return True
    reached, pkg_prefixes = reaching_import_names(root, rel)
    return bool(imported & reached) or any(
        p in imported_prefixes for p in pkg_prefixes)


def immune_posture(root: str | Path, top: int = 20) -> dict:
    """A deterministic, CHEAP ranking of the project's own modules by blind-spot
    RISK — where a surviving mutant most likely hides, so an immune sweep strikes
    there first.

    Fast by design (pure-AST; the test corpus is parsed ONCE into an import-name
    index, never re-scanned per module): each module's risk is its count of
    blindly-callable public functions (the mutation surface) weighed against
    whether any test file's imports actually REACH it (``_has_linked_test`` —
    import reachability, the same rule ``covering_test_files`` uses, not a
    filename convention). A module with many callable functions and NO linked
    test sorts first. ``top_risk`` carries ``callable_funcs`` and
    ``has_linked_test`` per module, ranked most-exposed first. The precise
    per-mutant ranking still governs the actual ``strengthen-tests`` landing
    (``apex immune --apply``); this is the fast WHERE. Never raises; a project with
    no callable public function yields an empty list."""
    from app.engine.objective_compiler import _own_modules
    from app.execution.test_shield import _safe_functions

    root = Path(root)
    # One parse of the test corpus, shared by every module's linkage check —
    # the hoist that keeps the sweep O(modules + test files), not O(m x t).
    test_imports = _test_import_index(root)
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
            "has_linked_test": _has_linked_test(root, rel, test_imports),
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
