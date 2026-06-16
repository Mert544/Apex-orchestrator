"""Change blast-radius — what a diff could affect, and how cohesive its scope is.

``apex impact`` answers a *function*-scoped question (which symbols transitively
call this one). This module answers the *change*-scoped question: given the set
of modules a diff touches, what is the full set of modules that import them —
directly and transitively — which tests cover them, and is the change itself a
focused, related edit or a scattered one that smells of scope creep.

It reuses the existing dependency graph (:class:`DependencyGraphBuilder`) to read
the import structure, and the existing fuzzy test linker (:class:`TestLinker`) to
find covering tests. Worktree COPIES under ``.claude`` (agent git worktrees are
full repo copies) are excluded from every result so they never inflate the radius
or collide test basenames. Nothing here is guessed: an import that doesn't resolve
to a graph node is silently skipped, never assumed.

Deterministic (every collection is sorted; no time/random), stdlib-only (plus
``subprocess`` for the optional git helper), offline, and read-only — it changes
no files.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import SKIPPED_DIRS as _SKIPPED_DIRS
from app.tools.dependency_graph import DependencyGraphBuilder
from app.tools.test_linker import TestLinker

__all__ = [
    "Cohesion",
    "BlastRadius",
    "blast_radius",
    "render_blast_radius_markdown",
    "changed_from_git",
    "is_skipped",
]


# Excluded directory names come from the one canonical source (``.claude`` agent
# worktrees, caches, venvs, build output) so this analyzer never drifts from the
# rest of the engine's tree-walks.

# Score boundary between a "tight" (related) change and a "scattered" one. A
# change scores 1.0 when every module shares one package subtree OR the changed
# set is internally connected by direct import edges; it scores 0.0 when the
# modules share no common package prefix and touch one another not at all.
_TIGHT_THRESHOLD = 0.5


def is_skipped(path: str | Path) -> bool:
    """True if ANY path component is an excluded directory name.

    A pure name check over ``Path(path).parts``, so ``app/x.py`` is kept while
    ``.claude/worktrees/agent-1/app/x.py`` and ``app/__pycache__/x.py`` are
    skipped. Works on relative or absolute, file or directory paths."""
    return bool(set(Path(path).parts) & _SKIPPED_DIRS)


@dataclass
class Cohesion:
    """Whether the changed modules form a related, focused edit or a scattered one.

    ``score`` is in [0,1]; ``label`` is ``"tight"`` at/above
    :data:`_TIGHT_THRESHOLD`, else ``"scattered"``; ``reason`` states the exact
    signal that decided it.
    """

    score: float
    label: str
    reason: str

    def to_dict(self) -> dict:
        return {"score": self.score, "label": self.label, "reason": self.reason}


@dataclass
class BlastRadius:
    changed: list[str] = field(default_factory=list)
    direct_dependents: list[str] = field(default_factory=list)
    transitive_dependents: list[str] = field(default_factory=list)
    covering_tests: list[str] = field(default_factory=list)
    cohesion: Cohesion | None = None

    def to_dict(self) -> dict:
        return {
            "changed": self.changed,
            "direct_dependents": self.direct_dependents,
            "transitive_dependents": self.transitive_dependents,
            "covering_tests": self.covering_tests,
            "cohesion": self.cohesion.to_dict() if self.cohesion else None,
        }


def _norm(rel: str) -> str:
    """A changed-path string in the graph's key format (posix, no leading ./)."""
    return Path(rel).as_posix()


def _package(rel: str) -> str:
    """The package subtree a module lives in — its parent dir as a posix string.

    ``app/engine/foo.py`` -> ``app/engine``; a top-level ``mod.py`` -> ``""``.
    Used to decide whether two changed modules are "in the same place".
    """
    parent = Path(rel).parent.as_posix()
    return "" if parent == "." else parent


def _common_prefix(packages: list[str]) -> str:
    """The longest shared leading package path across every module's package.

    Operates on path COMPONENTS (not characters) so ``app/engine`` and
    ``app/engineering`` share only ``app``, never ``app/engine``.
    """
    if not packages:
        return ""
    split = [p.split("/") if p else [] for p in packages]
    shared: list[str] = []
    for parts in zip(*split):
        first = parts[0]
        if all(part == first for part in parts):
            shared.append(first)
        else:
            break
    return "/".join(shared)


def _reverse_map(graph: dict) -> dict[str, set[str]]:
    """module -> set of modules that import it (direct dependents).

    Built from the forward ``imports`` edges. Worktree-copy nodes are excluded on
    both ends so a ``.claude`` copy can neither be a dependent nor pull a real
    module into the radius.
    """
    # ``is_skipped`` is a pure path-component check, but the same path strings
    # recur as both nodes and import targets across the whole graph. Memoize it so
    # each distinct path is classified once instead of re-walking ``Path(..).parts``
    # for every node that mentions it, and fold the seed pass (the old dict
    # comprehension) into this single iteration. The produced reverse map is
    # byte-identical to building it in two passes.
    _skip_cache: dict[str, bool] = {}

    def _skip(path: str) -> bool:
        cached = _skip_cache.get(path)
        if cached is None:
            cached = is_skipped(path)
            _skip_cache[path] = cached
        return cached

    reverse: dict[str, set[str]] = {}
    for path, node in graph.items():
        if _skip(path):
            continue
        reverse.setdefault(path, set())
        for target in node.imports:
            if _skip(target):
                continue
            reverse.setdefault(target, set()).add(path)
    return reverse


def _compute_cohesion(changed: list[str], graph: dict) -> Cohesion:
    """Deterministic scope-cohesion signal for the changed set.

    The exact rule (no time/random; evaluated in this order):

      * 0 or 1 changed module -> a single edit is cohesive by definition:
        score 1.0, "tight".
      * Otherwise the modules are TIGHT (score 1.0) if EITHER
          (a) they all live in the same package subtree
              (identical :func:`_package`), OR
          (b) the changed set is internally connected through direct import
              edges — i.e. treating the changed modules as an undirected graph
              whose edges are import relations BETWEEN changed modules, every
              module is reachable from the first (one connected component).
        Such a change is a focused, related edit.
      * Else the score is the fraction of changed modules that share the set's
        longest common package prefix, in [0,1). A score >= 0.5 reads "tight",
        below it "scattered" (likely scope creep). With no common prefix and no
        connecting edges the score is 0.0.
    """
    n = len(changed)
    if n <= 1:
        return Cohesion(1.0, "tight", "single changed module is cohesive by definition")

    packages = [_package(c) for c in changed]
    if len(set(packages)) == 1:
        pkg = packages[0] or "(repo root)"
        return Cohesion(1.0, "tight", f"all {n} modules share package '{pkg}'")

    changed_set = set(changed)
    # Undirected adjacency among the CHANGED modules only (an edge exists if one
    # changed module imports another). Connectivity over this subgraph means the
    # change forms a single, related cluster.
    adj: dict[str, set[str]] = {c: set() for c in changed}
    for path in changed:
        node = graph.get(path)
        if node is None:
            continue
        for target in node.imports:
            if target in changed_set:
                adj[path].add(target)
                adj[target].add(path)

    start = min(changed)
    seen: set[str] = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(sorted(adj[cur]))
    if seen == changed_set:
        return Cohesion(1.0, "tight", f"all {n} changed modules are connected by direct imports")

    prefix = _common_prefix(packages)
    if not prefix:
        return Cohesion(
            0.0, "scattered",
            f"{n} modules share no common package and no import edges (possible scope creep)",
        )
    matching = sum(1 for pkg in packages if pkg == prefix or pkg.startswith(prefix + "/"))
    score = round(matching / n, 4)
    label = "tight" if score >= _TIGHT_THRESHOLD else "scattered"
    return Cohesion(
        score, label,
        f"{matching}/{n} modules under common prefix '{prefix}'",
    )


def _covering_tests(root: Path, changed: list[str]) -> list[str]:
    """Tests that exercise ``changed`` — deterministic, de-duplicated, sorted.

    A changed file that IS a test is included directly (its own change must run).
    For a changed source module, every test the linker associates with it is
    included. Worktree-copy tests are dropped so a ``.claude`` copy of
    ``test_foo.py`` is never reported.
    """
    coverage = TestLinker(root).analyze().module_to_tests
    # Index by posix path so a changed path matches the linker's OS-native keys.
    by_posix = {_norm(mod): tests for mod, tests in coverage.items()}

    impacted: set[str] = set()
    for rel in changed:
        name = Path(rel).name
        if name.startswith("test_") and name.endswith(".py"):
            impacted.add(rel)
            continue
        for test in by_posix.get(rel, []):
            impacted.add(_norm(test))
    return sorted(t for t in impacted if not is_skipped(t))


def blast_radius(project_root: str | Path, changed: list[str]) -> BlastRadius:
    """The full deterministic blast radius of a change.

    ``changed`` is a list of project-relative module paths (``app/engine/foo.py``).
    Returns a :class:`BlastRadius` with, all sorted:

      * ``direct_dependents`` — modules that import any changed module;
      * ``transitive_dependents`` — every module reachable from the changed set
        by following reverse-dependency edges (a deterministic BFS with a visited
        set), EXCLUDING the changed modules themselves;
      * ``covering_tests`` — tests that exercise the change (:class:`TestLinker`);
      * ``cohesion`` — the scope-cohesion verdict (:func:`_compute_cohesion`).

    Changed paths that aren't graph nodes (unresolvable / non-existent) simply
    contribute no dependents — they are skipped, never guessed. Worktree copies
    under ``.claude`` never appear in any result.
    """
    root = Path(project_root)
    graph = DependencyGraphBuilder(root).build()
    reverse = _reverse_map(graph)

    changed_norm = sorted({_norm(c) for c in changed if not is_skipped(c)})
    changed_set = set(changed_norm)

    direct: set[str] = set()
    for mod in changed_norm:
        direct |= reverse.get(mod, set())
    direct -= changed_set

    # Deterministic BFS over reverse edges for the full reachable affected set.
    # The next frontier is de-duplicated and sorted as a whole (``sorted(set(nxt))``),
    # so the per-node ``sorted()`` that fed it was pure overhead with no effect on
    # the final ordering — collect into a set directly instead.
    transitive: set[str] = set()
    visited: set[str] = set(changed_set)
    queue = sorted(direct)
    while queue:
        nxt: set[str] = set()
        for mod in queue:
            if mod in visited:
                continue
            visited.add(mod)
            transitive.add(mod)
            nxt |= reverse.get(mod, set())
        queue = sorted(nxt)
    transitive -= changed_set

    covering = _covering_tests(root, changed_norm)
    cohesion = _compute_cohesion(changed_norm, graph)

    return BlastRadius(
        changed=changed_norm,
        direct_dependents=sorted(direct),
        transitive_dependents=sorted(transitive),
        covering_tests=covering,
        cohesion=cohesion,
    )


def render_blast_radius_markdown(br: BlastRadius) -> str:
    """Human-readable summary — a small counts table, the lists, and the verdict."""
    lines: list[str] = ["# Change Blast Radius", ""]

    if not br.changed:
        lines.append("_No changed modules._")
        return "\n".join(lines)

    lines.append("| Dimension | Count |")
    lines.append("| --- | --- |")
    lines.append(f"| Changed modules | {len(br.changed)} |")
    lines.append(f"| Direct dependents | {len(br.direct_dependents)} |")
    lines.append(f"| Transitive dependents | {len(br.transitive_dependents)} |")
    lines.append(f"| Covering tests | {len(br.covering_tests)} |")
    lines.append("")

    def _section(title: str, items: list[str]) -> None:
        lines.append(f"## {title}")
        if items:
            lines.extend(f"- `{item}`" for item in items)
        else:
            lines.append("_none_")
        lines.append("")

    _section("Changed", br.changed)
    _section("Direct dependents", br.direct_dependents)
    _section("Transitive dependents", br.transitive_dependents)
    _section("Covering tests", br.covering_tests)

    if br.cohesion is not None:
        lines.append("## Scope cohesion")
        lines.append(
            f"**{br.cohesion.label}** (score {br.cohesion.score:.2f}) — {br.cohesion.reason}"
        )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def changed_from_git(project_root: str | Path, base: str = "HEAD") -> list[str]:
    """Project ``.py`` files changed since ``base``, via ``git diff --name-only``.

    Conservative: ANY git failure (not a repo, bad ref, git missing) yields ``[]``
    rather than raising. The result keeps only ``.py`` files that survive
    :func:`is_skipped` (so worktree copies, caches, and vendored trees are
    dropped), sorted and de-duplicated.
    """
    root = Path(project_root)
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", base],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return []
    if proc.returncode != 0:
        return []

    out: set[str] = set()
    for line in proc.stdout.splitlines():
        rel = line.strip()
        if not rel or not rel.endswith(".py"):
            continue
        if is_skipped(rel):
            continue
        out.add(Path(rel).as_posix())
    return sorted(out)
