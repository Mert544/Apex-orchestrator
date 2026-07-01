"""``JsProjectProfiler`` — the JS/TS project-SCOPE structural analyzer, the JS
sibling of :mod:`app.tools.project_profile`.

Apex's JS lane already LANDS verified code file-by-file (js-cover-gaps /
js-tdd-implement / js-wire-exports, each behind the forced jest gate + rollback),
but every JS objective is single-file: it sees ONE module at a time and has no
picture of how the modules relate. This profiler adds the missing PROJECT-SCOPE
knowledge — the import/module graph, per-module fan-in / fan-out, jest
test->module linkage, and the derived untested-module + dependency-hub signals —
the prerequisite for a future project-level JS objective (nothing here lands code
yet; it is READ-ONLY structural analysis, exactly like ``project_profile`` is for
Python).

It reuses the DETERMINISTIC ``ts_driver`` (via
:func:`app.execution.js.js_tool.module_imports`) to read each module's import
specifiers — NO new parser is written — and the shared JS walk / source-suffix /
jest-test-file machinery in :mod:`app.execution.lang.js_adapter`. Module
resolution is pure and offline: a RELATIVE specifier (``./x`` / ``../y``) is
resolved against the importer's directory to a real in-project module path (trying
the JS/TS source extensions and an ``index.*`` barrel); a BARE specifier (``fs`` /
``react``) is an external package and never an in-project edge. The test->module
linkage mirrors :mod:`app.tools.test_linker`'s import + reference approach at the
module level.

Graceful on a JS-less project: a missing/empty ``package.json`` or a tree with no
JS/TS sources yields an EMPTY profile (no crash, no driver spawn). Deterministic
(sorted walk, sorted edge/graph output, no clock/random), offline (the driver reads
bytes via the global TypeScript Compiler API; Apex installs nothing), zero-token,
and it NEVER runs the suite — it is structural analysis, not a landing objective.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.execution.js.js_tool import module_imports
from app.execution.lang.js_adapter import (
    JS_SOURCE_SUFFIXES,
    _is_js_test,
    _read,
    _walk_files,
)

__all__ = ["JsProjectProfile", "JsProjectProfiler", "profile_js_project"]

# The candidate extensions a bare relative specifier (``./util``) may resolve to,
# in the deterministic priority order Node/TS resolution uses (TS first so a
# ``.ts`` module wins over a co-located ``.js`` build artifact). A specifier that
# already carries a source suffix is tried verbatim first.
_RESOLVE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
# A directory specifier (``./foo`` where ``foo/`` is a package) resolves to its
# barrel entry — ``foo/index.<ext>`` — exactly as Node/TS does.
_INDEX_STEMS = ("index",)


@dataclass
class JsProjectProfile:
    """The JS/TS project-scope structural profile — the JS analogue of
    :class:`app.tools.project_profile.ProjectProfile`, carrying only the fields a
    project-level JS objective needs (import graph + fan-in/out + test linkage +
    derived signals). All list/dict outputs are sorted for byte-identical repeat
    runs; an empty (JS-less / no-``package.json``) project leaves every field at
    its default.

    - ``modules``: every own non-test JS/TS module (rel path, sorted) — the graph
      node set;
    - ``test_files``: every own jest test file (rel path, sorted);
    - ``dependency_edges``: the resolved INTERNAL (importer, imported) module-path
      pairs, sorted — an edge only exists when the specifier resolves to another
      in-project module (a bare/external package is never an edge);
    - ``external_dependencies``: the sorted, de-duplicated set of BARE specifiers
      (``react`` / ``fs`` / ``lodash/fp``) the project imports but does not define —
      the external surface, distinct from the internal graph;
    - ``module_fanin``: module path -> in-degree (how many project modules import
      it — its blast radius), populated only for modules with in-degree > 0;
    - ``module_fanout``: module path -> the modules IT imports, sorted, populated
      only for modules that import >= 1 internal module;
    - ``dependency_hubs``: the highest-fan-in modules (top 5, sorted by
      ``(-fan_in, path)``) — a regression in a hub ripples to every dependent;
    - ``module_to_tests``: module path -> the jest test files that link it
      (import + reference), sorted;
    - ``untested_modules``: modules with NO linked jest test (top 5 display);
    - ``untested_count``: the TRUE total of untested modules before the display
      truncation (so a repo with 40 untested modules is not scored as if only 5
      were);
    - ``hub_untested_modules``: the intersection worth the most — high-fan-in hubs
      that are ALSO untested (each ``{"module", "fan_in"}``), the highest-leverage
      place to add a project-level JS test.
    """

    root: str
    modules: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    dependency_edges: list[tuple[str, str]] = field(default_factory=list)
    external_dependencies: list[str] = field(default_factory=list)
    module_fanin: dict[str, int] = field(default_factory=dict)
    module_fanout: dict[str, list[str]] = field(default_factory=dict)
    dependency_hubs: list[str] = field(default_factory=list)
    module_to_tests: dict[str, list[str]] = field(default_factory=dict)
    untested_modules: list[str] = field(default_factory=list)
    untested_count: int = 0
    hub_untested_modules: list[dict] = field(default_factory=list)


class JsProjectProfiler:
    """Build a :class:`JsProjectProfile` for one JS/TS project root.

    Mirrors :class:`app.tools.project_profile.ProjectProfiler`'s public surface —
    construct with a root, call :meth:`profile` — but reads the import graph off the
    deterministic ``ts_driver`` instead of Python ``ast``. READ-ONLY: it never
    writes, never runs the suite, and consults no clock/random."""

    # A module needs at least this in-degree to count as a dependency HUB. >= 2
    # keeps the signal meaningful (a module one other file imports is not a hub);
    # a module several modules depend on is a real blast-radius risk. Mirrors the
    # Python profiler's ``in_degree >= 2`` fragility bar.
    HUB_FANIN_FLOOR = 2

    def __init__(self, root: str | Path, max_files: int = 2000) -> None:
        # ``root`` (as passed) is what the profile REPORTS, matching how
        # ``project_profile.ProjectProfiler`` stores it. All actual work uses the
        # ABSOLUTE resolution ``_root``: the ``ts_driver`` runs in a subprocess whose
        # ``cwd`` is the root, so a RELATIVE root + a relative file arg would double-
        # nest (``proj/proj/x.ts``) — the driver must be handed absolute paths.
        self.root = Path(root)
        self._root = self.root.resolve()
        self.max_files = max_files

    def profile(self) -> JsProjectProfile:
        """Build the full JS/TS project-scope profile.

        Graceful-empty by construction: a root that does not exist, carries no
        ``package.json`` (the single-project gate, the JS analogue of one Python
        project root — and what makes this a clean no-op on a Python tree), or holds
        no own non-test JS/TS module returns an EMPTY profile without ever spawning
        the driver."""
        profile = JsProjectProfile(root=str(self.root))
        if not self._root.exists() or not (self._root / "package.json").exists():
            return profile

        modules, tests = self._discover(profile)
        if not modules:
            return profile  # JS-less project -> empty profile, no driver spawn

        self._build_import_graph(profile, modules)
        self._link_tests(profile, modules, tests)
        self._derive_signals(profile)
        return profile

    def _discover(self, profile: JsProjectProfile) -> tuple[list[str], list[str]]:
        """Split the project's own JS/TS files into (non-test modules, jest tests).

        Reuses :func:`app.execution.lang.js_adapter._walk_files` (sorted, canonical
        skip-dirs + ``node_modules`` excluded) so the node set is deterministic and
        identical to what the JS objectives see; capped at ``max_files`` on the
        SORTED walk so a huge repo yields the same bounded prefix everywhere."""
        modules: list[str] = []
        tests: list[str] = []
        for rel in _walk_files(self._root, JS_SOURCE_SUFFIXES)[: self.max_files]:
            (tests if _is_js_test(rel) else modules).append(rel)
        profile.modules = modules
        profile.test_files = tests
        return modules, tests

    def _build_import_graph(self, profile: JsProjectProfile,
                            modules: list[str]) -> None:
        """Read each module's import specifiers off the driver and split them into
        INTERNAL edges (resolve to another project module) and EXTERNAL packages.

        The single driver-spawning pass. A relative specifier is resolved against
        the importer's directory (:meth:`_resolve_relative`); an unresolved relative
        specifier (a dangling ``./gone`` or a non-JS asset import) contributes no
        edge; a bare specifier is recorded as an external dependency. Fan-in / fan-
        out are read straight off the resolved edge set (no second graph)."""
        module_set = set(modules)
        edges: list[tuple[str, str]] = []
        externals: set[str] = set()
        fanin: Counter[str] = Counter()
        fanout: dict[str, set[str]] = {}
        for rel in modules:
            specs = module_imports(self._root, rel)
            if not specs:  # None (parse failure) or [] (no imports) -> no edges
                continue
            for spec in specs:
                target = self._resolve(rel, spec, module_set)
                if target is None:
                    if not self._is_relative(spec):
                        externals.add(spec)
                    continue  # unresolved relative import -> not a graph edge
                if target == rel:
                    continue  # a self-import is not a dependency edge
                edges.append((rel, target))
                fanin[target] += 1
                fanout.setdefault(rel, set()).add(target)

        profile.dependency_edges = sorted(set(edges))
        profile.external_dependencies = sorted(externals)
        profile.module_fanin = {m: fanin[m] for m in sorted(fanin)}
        profile.module_fanout = {
            m: sorted(fanout[m]) for m in sorted(fanout)
        }

    @staticmethod
    def _is_relative(spec: str) -> bool:
        """True when ``spec`` is a RELATIVE import (``./x`` / ``../y``) — the only
        shape that can resolve to an in-project module. A bare specifier (``react``,
        ``fs``, ``@scope/pkg``) names an external package, never a project edge."""
        return spec.startswith("./") or spec.startswith("../")

    def _resolve(self, importer: str, spec: str,
                 module_set: set[str]) -> str | None:
        """Resolve ``spec`` (as imported from ``importer``) to a project module path
        in ``module_set``, or ``None`` when it is external / unresolvable.

        Only RELATIVE specifiers resolve; a bare specifier returns ``None`` (it is an
        external package). Pure string/path arithmetic — no filesystem probe — so it
        is deterministic and offline: the candidate set is matched against the
        already-discovered module set, never against disk."""
        if not self._is_relative(spec):
            return None
        return self._resolve_relative(importer, spec, module_set)

    def _resolve_relative(self, importer: str, spec: str,
                          module_set: set[str]) -> str | None:
        """Resolve a RELATIVE ``spec`` against ``importer``'s directory to a member
        of ``module_set``, trying (in deterministic order) the specifier verbatim,
        then each source extension appended, then an ``index.<ext>`` barrel.

        Uses ``PurePosix``-style normalisation via :class:`pathlib.PurePosixPath`
        (the walk emits POSIX rel paths) so ``../`` segments collapse the same way on
        every OS. The first candidate that is a known module wins; ``None`` when none
        is (a dangling import or an import of a non-source asset)."""
        base = Path(importer).parent
        for candidate in self._resolution_candidates(base, spec):
            if candidate in module_set:
                return candidate
        return None

    @staticmethod
    def _resolution_candidates(base: Path, spec: str) -> list[str]:
        """The ordered candidate module paths a relative ``spec`` from ``base`` may
        name: the joined path verbatim, then with each source extension, then its
        ``index.<ext>`` barrel. Normalised to POSIX rel strings; a candidate that
        escapes the root (leading ``..``) is dropped (never a project module)."""
        joined = (base / spec).as_posix()
        candidates = [joined]
        for ext in _RESOLVE_EXTENSIONS:
            candidates.append(joined + ext)
        for stem in _INDEX_STEMS:
            for ext in _RESOLVE_EXTENSIONS:
                candidates.append((base / spec / f"{stem}{ext}").as_posix())
        # Collapse ``a/../b`` and drop any candidate that walks above the root; a
        # module path is always root-relative with no leading ``..``.
        out: list[str] = []
        for cand in candidates:
            norm = _norm_relposix(cand)
            if norm is not None and norm not in out:
                out.append(norm)
        return out

    def _link_tests(self, profile: JsProjectProfile, modules: list[str],
                    tests: list[str]) -> None:
        """Link each module to the jest tests that exercise it (import + reference).

        Mirrors :class:`app.tools.test_linker.TestLinker`: read + lower-case every
        test file ONCE (hoisted out of the per-module loop), then for each module
        keep a test that IMPORTS the module (by stem) AND references its stem. A
        module with no linked test is untested (the derived signal below). The
        per-test read is done once here, not once per (module, test) pair."""
        test_index = [(rel, _read(self._root / rel).lower()) for rel in tests]
        module_to_tests: dict[str, list[str]] = {}
        for module in modules:
            stem = Path(module).stem.lower()
            linked = sorted(
                rel for rel, text in test_index
                if _test_links_module(text, stem)
            )
            module_to_tests[module] = linked
        profile.module_to_tests = module_to_tests

    def _derive_signals(self, profile: JsProjectProfile) -> None:
        """Compute the derived project-scope signals off the now-built graph +
        linkage: dependency hubs (high fan-in), untested modules (no linked test,
        with the TRUE count kept separate from the capped display list), and the
        highest-leverage intersection — untested hubs."""
        # Dependency hubs: the highest-fan-in modules (a true hub, in-degree >= the
        # floor), ranked ``(-fan_in, path)`` and capped at 5 for display.
        hubs = sorted(
            (m for m, deg in profile.module_fanin.items()
             if deg >= self.HUB_FANIN_FLOOR),
            key=lambda m: (-profile.module_fanin[m], m),
        )
        profile.dependency_hubs = hubs[:5]

        # Untested modules: no linked jest test. TRUE total kept for the honest
        # count; the profile list keeps the sorted top-5 for display.
        untested = sorted(
            m for m, linked in profile.module_to_tests.items() if not linked
        )
        profile.untested_count = len(untested)
        profile.untested_modules = untested[:5]

        # The intersection worth the most: a high-fan-in hub with NO linked test —
        # a regression there breaks every dependent and nothing catches it.
        untested_set = set(untested)
        profile.hub_untested_modules = [
            {"module": m, "fan_in": profile.module_fanin[m]}
            for m in hubs if m in untested_set
        ]


def _norm_relposix(path: str) -> str | None:
    """Collapse ``a/./b`` and ``a/../b`` segments in a POSIX rel path, or ``None``
    when the result escapes the root (a leading ``..`` — never a project module).

    Pure segment arithmetic (no filesystem touch), so resolution stays deterministic
    and offline. Kept module-level so it needs no ``self`` and reads as the small
    pure helper it is."""
    parts: list[str] = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                return None  # escapes the root
            parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts) if parts else None


def _test_links_module(test_text_lower: str, module_stem: str) -> bool:
    """True when the (lower-cased) jest test source imports the module ``stem`` AND
    references it — the module-level analogue of
    :func:`app.execution.lang.js_adapter._test_links_stub`.

    A test qualifies when it both (a) IMPORTS the module by stem (a
    ``require("...stem")`` / ``from "...stem"`` / ``import "...stem"``, optionally
    with a source suffix) and (b) mentions the stem elsewhere as a word (so a test
    that only re-exports the path without using it does not falsely link). Word/
    boundary anchoring keeps ``math`` from matching ``mathutils``; pure regex, no
    filesystem touch, so the linkage is deterministic. An empty stem never links."""
    import re

    if not module_stem:
        return False
    stem = re.escape(module_stem)
    imports = re.search(
        r"""(?:require|from|import)\b[^\n]*['"][^'"\n]*/?"""
        + stem + r"""(?:\.[cm]?[jt]sx?)?['"]""",
        test_text_lower,
    )
    if not imports:
        return False
    return bool(re.search(r"(?<![\w$])" + stem + r"(?![\w$])", test_text_lower))


def profile_js_project(root: str | Path, max_files: int = 2000) -> JsProjectProfile:
    """Convenience: build the JS/TS project-scope profile for ``root``.

    The functional analogue of :class:`JsProjectProfiler` for callers that want the
    profile in one call (mirrors how ``project_profile`` is typically used). Returns
    an EMPTY :class:`JsProjectProfile` for a JS-less / no-``package.json`` tree."""
    return JsProjectProfiler(root, max_files=max_files).profile()
