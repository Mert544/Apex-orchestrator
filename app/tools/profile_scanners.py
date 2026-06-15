"""Code-quality / refactor-candidate scans for :class:`ProjectProfiler`.

A behavior-preserving extraction of the cohesive cluster of CONSTRUCTIVE
refactor scans out of the ``app/tools/project_profile.py`` god-module — the
within-module and cross-module "where to refactor" signals the idea engine
turns into concrete ``apex extract`` / ``apex inline`` / ``apex signature drop``
recommendations, plus the structural decouple/finish-the-protocol signals.

The scans live here as :class:`_CodeQualityScansMixin`, which
:class:`ProjectProfiler` inherits — every call site stays ``self._scan_x(...)``
and the public ``profile()`` API, ordering and ``light`` gating are unchanged.
Because it is a mixin, the methods keep reading ``self.root``,
``self.max_files``, ``self._is_fixture_path``, ``self._dependency_graph`` etc.
untouched. This is a pure structural move: no scan logic, threshold, field name,
ordering or gating is altered, so every profile/idea output is byte-identical.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from app.engine.skip_dirs import is_skipped

if TYPE_CHECKING:  # pragma: no cover - import only for type hints
    from app.tools.project_profile import ProjectProfile


class _CodeQualityScansMixin:
    """The code-quality / refactor-candidate scans, mixed into ProjectProfiler.

    Owns only the scans (and the one private helper + the constants) that form a
    cohesive refactor-signal cluster:

    - ``_scan_extractable_blocks`` / ``_scan_inlinable_helpers`` — within-module
      "extract a seam" / "inline a thin helper" signals;
    - ``_scan_dead_params`` — never-read parameters on the API surface;
    - ``_scan_generalizable_duplications`` (+ ``_is_execution_scaffold_module``)
      — cross-module DRY/"generalize one shared helper" signal;
    - ``_scan_coordinator_modules`` — high-fan-OUT god-modules to decouple;
    - ``_scan_god_classes`` — top-level classes with too many methods (a
      Single-Responsibility violation / decompose candidate);
    - ``_scan_incomplete_protocols`` — half-built Python contract pairs.

    All other ``self.*`` attributes (``root``, ``max_files``, ``_is_fixture_path``,
    ``_dependency_graph``, ...) are supplied by ``ProjectProfiler`` itself.
    """

    # generalizable-duplication: only a SMALL set of modules sharing a block is
    # actionable copy-paste ("extract one helper"). A wider span is an intentional
    # framework/template pattern, not duplication to DRY (dogfood finding).
    _GENERALIZE_MAX_MODULES = 4
    # The ``app/execution/*`` transform family DELIBERATELY shares one isolated
    # skeleton per transform (read -> ``ast.parse`` -> collect rewrites -> apply ->
    # re-parse -> append a blocker -> return a ``RenamePlan``). That isolation is BY
    # DESIGN — extracting the shared shell fights the surgical-per-transform
    # architecture — so a near-duplicate group whose modules are ALL this scaffold
    # is NOT actionable cross-module duplication. A module is recognised as scaffold
    # by its directory prefix PLUS importing one of the scaffold markers below: the
    # common ``_transform_base`` helpers and/or the ``RenamePlan`` plan type every
    # transform returns (some transforms predate ``_transform_base`` and import the
    # plan straight from ``cross_file_rename`` — both are the same skeleton). The
    # ``_GENERALIZE_MAX_MODULES`` cap does NOT catch the 2-module scaffold pairs the
    # scan also raises (e.g. ``bool_return.py`` + ``comprehension.py``). Scoped to
    # the flat execution-scaffold template only — genuine app-code duplication
    # elsewhere is untouched, and a mixed group (a scaffold module plus a real app
    # module) is still flagged.
    _EXECUTION_SCAFFOLD_DIR = "app/execution/"
    _EXECUTION_SCAFFOLD_IMPORTS = (
        "app.execution._transform_base",
        "app.execution.cross_file_rename import RenamePlan",
    )

    # Fan-OUT bar for a *coordinator* (god-module): a module importing at least
    # this many internal modules is a coordination chokepoint — it knows about
    # too much of the system and is a decoupling candidate. The opposite edge
    # direction from ``_HUB_FAN_IN_FLOOR`` (fan-in). Set high (12) so only
    # genuine god-modules surface, not every file with a handful of imports:
    # tuned against Apex itself, which has a small number of real coordinator
    # modules (CLI/engine wirers) and many ordinary modules well below this bar.
    _COORDINATOR_FAN_OUT_FLOOR = 12

    # Maximum block-nesting depth at or above which a top-level function is a
    # guard-clause / extract refactor candidate. Each nested compound statement
    # (If/For/While/With/Try and their async variants) adds one level, so depth
    # 5 means five compound statements deep — a control-flow staircase that is
    # hard to read and a prime "invert the condition / early-return / extract the
    # inner block" target. Set high enough (5) that ordinary two/three-level
    # functions never surface; tuned against Apex itself so only the genuinely
    # deep functions are flagged. Maintainability signal, recommend-only.
    _DEEP_NESTING_FLOOR = 5

    # Method-count bar at or above which a top-level class is a god-class — a
    # Single-Responsibility violation and a decomposition candidate. A class
    # body declaring this many methods (``def``/``async def`` direct children)
    # is doing too much: too many behaviours have accreted onto one type, so it
    # is a prime "split into smaller, cohesive collaborators" target. Set high
    # enough (15) that ordinary classes never surface; tuned against Apex itself
    # so only the genuinely over-loaded classes are flagged. The attribute count
    # (distinct ``self.X =`` assignment targets) rides along as a second SRP
    # signal but does NOT lower the bar — methods alone decide the flag.
    # Maintainability / structural signal, recommend-only.
    _GOD_CLASS_METHOD_FLOOR = 15

    def _scan_god_classes(self, profile: ProjectProfile) -> None:
        """Name top-level classes doing too much — a Single-Responsibility
        violation and a decomposition candidate (a structural signal).

        Walks each in-scope, non-fixture module's TOP-LEVEL classes and counts,
        per class, its METHODS (``FunctionDef``/``AsyncFunctionDef`` direct
        children of the class body) and its distinct ATTRIBUTES (the set of
        ``self.X`` targets ever assigned anywhere in the class — ``self.x = ...``,
        tuple/star targets, and augmented assignments all contribute). A class
        whose method count reaches ``_GOD_CLASS_METHOD_FLOOR`` is flagged: too
        many behaviours have accreted onto one type, so it is a prime "split into
        smaller, cohesive collaborators" target. Only the class's OWN body counts
        — a nested class starts its own tally (its members are its problem, not
        the enclosing class's). Recommend-only: HOW to decompose the class is a
        DESIGN call, Apex names it but does not auto-write the split. Sorted
        ``(-methods, module, classname)`` and capped to 5; a repo with no
        god-class yields [] so seeding stays byte-identical. Each entry:
        ``{"module", "classname", "methods", "attributes"}``.
        """

        def _attr_targets(node: ast.AST, attrs: set[str]) -> None:
            """Collect every ``self.X`` assignment target in ``node``'s body,
            without descending into a nested class (its attributes are its own)."""
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    continue  # a nested class owns its own attributes
                if isinstance(child, ast.Attribute) and isinstance(
                    child.ctx, ast.Store
                ) and isinstance(child.value, ast.Name) and child.value.id == "self":
                    attrs.add(child.attr)
                _attr_targets(child, attrs)

        found: list[dict] = []
        scanned = 0
        for path in sorted(self.root.rglob("*.py")):
            if scanned >= self.max_files:
                break
            rel = path.relative_to(self.root)
            rel_str = rel.as_posix()
            if is_skipped(rel) or self._is_fixture_path(rel_str):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError):
                continue
            scanned += 1
            for cls in tree.body:
                if not isinstance(cls, ast.ClassDef):
                    continue
                methods = sum(
                    1 for member in cls.body
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
                if methods < self._GOD_CLASS_METHOD_FLOOR:
                    continue  # ordinary class — too few methods to be a god-class
                attrs: set[str] = set()
                _attr_targets(cls, attrs)
                found.append({"module": rel_str, "classname": cls.name,
                              "methods": methods, "attributes": len(attrs)})
        found.sort(key=lambda d: (-d["methods"], d["module"], d["classname"]))
        profile.god_classes = found[:5]

    def _scan_deeply_nested_functions(self, profile: ProjectProfile) -> None:
        """Name top-level functions whose control flow nests too deeply — a
        guard-clause / extract refactor candidate (a maintainability signal).

        Walks each in-scope, non-fixture module's TOP-LEVEL functions and
        computes each function's MAXIMUM block-nesting depth: every nested
        compound statement (``If``/``For``/``While``/``With``/``Try`` and the
        ``AsyncFor``/``AsyncWith`` async variants) deepens the staircase by one.
        Functions whose depth reaches ``_DEEP_NESTING_FLOOR`` are flagged — deep
        nesting is hard to read and a prime "invert the guard / early-return /
        extract the inner block" target. Nested ``def``/``class`` bodies start a
        fresh depth count of their own (an inner function's nesting is its own
        problem, not the enclosing one's). Recommend-only: HOW to flatten the
        staircase is a DESIGN call, Apex names the function but does not
        auto-write it. Sorted ``(-depth, module, function)`` and capped to 5; an
        all-flat repo yields [] so seeding stays byte-identical. Each entry:
        ``{"module", "function", "depth"}``.
        """
        _NESTERS = (ast.If, ast.For, ast.While, ast.With, ast.Try,
                    ast.AsyncFor, ast.AsyncWith)

        def _max_depth(node: ast.AST, depth: int) -> int:
            """Deepest nesting reached within ``node``'s OWN body (a nested
            function/class starts its own count, so we do not recurse into it)."""
            best = depth
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.ClassDef)):
                    continue  # inner scope owns its own nesting
                step = 1 if isinstance(child, _NESTERS) else 0
                best = max(best, _max_depth(child, depth + step))
            return best

        found: list[dict] = []
        scanned = 0
        for path in sorted(self.root.rglob("*.py")):
            if scanned >= self.max_files:
                break
            rel = path.relative_to(self.root)
            rel_str = rel.as_posix()
            if is_skipped(rel) or self._is_fixture_path(rel_str):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError):
                continue
            scanned += 1
            for fn in tree.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                depth = _max_depth(fn, 0)
                if depth >= self._DEEP_NESTING_FLOOR:
                    found.append({"module": rel_str, "function": fn.name,
                                  "depth": depth})
        found.sort(key=lambda d: (-d["depth"], d["module"], d["function"]))
        profile.deeply_nested_functions = found[:5]

    def _scan_incomplete_protocols(self, profile: ProjectProfile) -> None:
        """Name the half-built Python contract pairs — "finish what you started".

        Delegates to the pure-AST :func:`app.engine.completeness.incomplete_protocols`,
        which walks the same source tree through the canonical skip-dir exclusion,
        excludes test/example/fixture files, and is conservative by construction
        (only unambiguous gaps: ``__eq__`` without ``__hash__``, and the
        sync/async context-manager pairs). Deterministic and capped so a single
        signal never floods the idea set; an all-clean repo yields [] so seeding
        stays byte-identical.
        """
        from app.engine.completeness import incomplete_protocols

        profile.incomplete_protocols = incomplete_protocols(str(self.root))[:5]

    def _is_execution_scaffold_module(self, module: str) -> bool:
        """True if ``module`` is one of the ``app/execution/*`` transform-scaffold
        files — directly under ``app/execution/`` AND importing a scaffold marker
        (the common ``_transform_base`` helpers and/or the ``RenamePlan`` plan type
        every transform returns).

        Every such module DELIBERATELY repeats the same isolated transform shell
        (read -> ``ast.parse`` -> collect rewrites -> apply -> re-parse -> append a
        blocker -> return a ``RenamePlan``); that per-transform isolation is the
        architecture, not copy-paste to DRY. The directory check restricts to the
        family's own top level (a nested ``app/execution/objectives/...`` module is
        NOT scaffold), and the import marker confirms it actually shares the
        transform skeleton — so genuine duplication elsewhere is never matched.
        Conservative: a file we cannot read is treated as NOT scaffold, so real
        duplication is never silently dropped on an I/O error.
        """
        norm = module.replace("\\", "/")
        if not norm.startswith(self._EXECUTION_SCAFFOLD_DIR):
            return False
        # Only the family's own top level — not a nested subpackage like
        # ``app/execution/objectives/...`` — counts as the flat transform scaffold.
        if "/" in norm[len(self._EXECUTION_SCAFFOLD_DIR):]:
            return False
        try:
            text = (self.root / norm).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        return any(marker in text for marker in self._EXECUTION_SCAFFOLD_IMPORTS)

    def _scan_generalizable_duplications(self, profile: ProjectProfile) -> None:
        """Name near-identical blocks that recur ACROSS modules — "extract one
        shared helper" (the DRY/generalize case).

        Delegates to the deterministic :func:`app.engine.near_dup.find_near_duplicates`,
        which already enumerates structurally near-identical statement windows
        across the project (its own min thresholds bound the scan) and excludes
        test/example/fixture files via the source index. We keep ONLY groups whose
        occurrences span 2+ DISTINCT modules — that is the cross-module
        "generalize" case, deliberately DISTINCT from the within-module
        ``extractable-block``/``inlinable-helper`` signals, so a single-module
        group is never flagged here (no double-flagging). Each occurrence is a
        ``"module:lineno"`` string; the module is the text before the LAST colon.
        Sorted ``(-occurrences, -lines, modules)`` and capped so a single signal
        never floods the idea set; an all-clean repo yields [] so seeding stays
        byte-identical.
        """
        from app.engine.near_dup import find_near_duplicates

        entries: list[dict] = []
        for group in find_near_duplicates(str(self.root)):
            modules = set()
            for occ in group.occurrences:
                # Occurrence is "module:lineno"; the lineno is the final field, so
                # split on the LAST colon to recover the (possibly path-bearing)
                # module string. Re-filter fixtures so the predicate is the single
                # source of truth even if the engine let a path through.
                module = occ.rsplit(":", 1)[0]
                if module and not self._is_fixture_path(module):
                    modules.add(module)
            # Cross-module ONLY (2..MAX), but NOT framework-wide: a group in one
            # module is the existing extractable-block case; a group spanning
            # MANY modules (e.g. every transform in a plugin family sharing the
            # same boilerplate skeleton) is an intentional *template/pattern* whose
            # shared abstraction already exists as the framework — "extract one
            # helper across 31 files" is noise. The actionable case is a SMALL
            # number of places that duplicated the same logic (dogfood finding).
            if not (2 <= len(modules) <= self._GENERALIZE_MAX_MODULES):
                continue
            # Down-weight/exclude the intentional ``app/execution/*`` transform
            # scaffold: when EVERY module in the group is an execution-scaffold
            # file sharing the ``_transform_base`` skeleton, the shared block is the
            # BY-DESIGN per-transform shell, not copy-paste to generalize. A mixed
            # group (one scaffold module + one genuine app module) is still kept —
            # only an all-scaffold group is the false positive.
            if all(self._is_execution_scaffold_module(m) for m in modules):
                continue
            entries.append({
                "modules": sorted(modules),
                "occurrences": len(group.occurrences),
                "lines": group.lines,
            })
        entries.sort(key=lambda e: (-e["occurrences"], -e["lines"], e["modules"]))
        profile.generalizable_duplications = entries[:5]

    def _scan_coordinator_modules(self, profile: ProjectProfile) -> None:
        """Name high-fan-OUT modules — god-modules that are decoupling candidates.

        A module that IMPORTS many internal modules (fan-out =
        ``len(node.imports)`` >= ``_COORDINATOR_FAN_OUT_FLOOR``) is a coordination
        chokepoint: it knows about too much of the system, so a change anywhere it
        wires together can ripple back through it. This is the OPPOSITE edge
        direction from the ``dependency_hubs`` (fan-IN) signal — a hub is depended
        ON by many, a coordinator depends ON many — so the two never restate each
        other. Reads fan-out off the import graph ``_populate_python_structure``
        already built (``self._dependency_graph``), so no second graph is built;
        the node's ``imports`` are already resolved INTERNAL modules. Test/example/
        fixture files are excluded (their wiring is throwaway). For each flagged
        module the ``imports`` field names the top few internal modules it pulls,
        ordered by how depended-on each is (the target's own fan-in, the most-
        central first — the heaviest convergence to shed), then path for
        determinism. Sorted ``(-fan_out, module)`` and capped to 5; a repo with no
        god-module yields [] so seeding stays byte-identical.
        """
        graph = getattr(self, "_dependency_graph", None) or {}
        entries: list[dict] = []
        for node in graph.values():
            path = node.path
            if self._is_fixture_path(path):
                continue  # fixture/test wiring is throwaway, never a real subject
            fan_out = len(node.imports)
            if fan_out < self._COORDINATOR_FAN_OUT_FLOOR:
                continue  # not a god-module — ordinary import footprint
            top_imports = sorted(
                node.imports,
                key=lambda t: (-(graph[t].in_degree if t in graph else 0), t),
            )[:3]
            entries.append({
                "module": path,
                "fan_out": fan_out,
                "imports": top_imports,
            })
        # Widest fan-out first (the heaviest coordinator), then stable by module
        # so the ordering is deterministic.
        entries.sort(key=lambda e: (-e["fan_out"], e["module"]))
        profile.coordinator_modules = entries[:5]

    def _scan_extractable_blocks(self, profile: ProjectProfile) -> None:
        """Long functions with a clean seam to extract — turns the engine's
        "extract a shared helper" recommendation into a concrete, copy-pasteable
        ``apex extract`` command (mirrors the dead-parameter signal). Only the
        project's own non-fixture modules; the single best seam per file."""
        from app.execution.extract_method import suggest_extractions

        found: list[dict] = []
        scanned = 0
        for path in sorted(self.root.rglob("*.py")):
            if scanned >= self.max_files:
                break
            rel = path.relative_to(self.root)
            rel_str = rel.as_posix()
            # Use the canonical skip set (it knows about ``.claude`` agent
            # worktrees — FULL repo copies); a hand-rolled set used to omit it and
            # leaked self-referential ideas about throwaway worktree modules.
            if is_skipped(rel) or self._is_fixture_path(rel_str):
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned += 1
            suggestions = suggest_extractions(source)
            if suggestions:
                best = suggestions[0]  # already sorted: most lines saved first
                found.append({"module": rel_str, **best})
        found.sort(key=lambda d: (-d["lines_saved"], d["module"]))
        profile.extractable_blocks = found[:5]

    def _scan_inlinable_helpers(self, profile: ProjectProfile) -> None:
        """Tiny single-use helpers ``apex inline`` would cleanly accept — turns
        the "fold a thin helper back into its call site" recommendation into a
        concrete, copy-pasteable ``apex inline FUNC`` command (mirrors the
        extractable-block signal). The analyzer is conservative by construction
        (see ``suggest_inlines``); here we just exclude fixture/test paths and
        keep the strongest few (fewest call sites first, then module)."""
        from app.execution.inline_function import suggest_inlines

        found = [
            h for h in suggest_inlines(self.root)
            if not self._is_fixture_path(h["module"])
        ]
        found.sort(key=lambda d: (d["call_sites"], d["module"], d["function"]))
        profile.inlinable_helpers = found[:5]

    def _scan_dead_params(self, profile: ProjectProfile) -> None:
        """Parameters no statement in the function body ever reads.

        Dead weight on the API surface — every caller is forced to know about
        a knob that does nothing. Conservative by construction, each rule a
        real false-positive class:
          - only top-level functions whose NAME is unique project-wide
            (interface families — many modules defining the same ``apply()`` —
            conform to a shared signature, not their own needs);
          - never referenced as a bare object anywhere (callbacks, dispatch
            tables and ``set_defaults(func=...)`` impose their signature);
          - no decorators (frameworks impose signatures too);
          - a real body (stubs/protocol methods keep their params);
          - the parameter isn't ``_``-prefixed (already declared intentional)
            and isn't ``*args``/``**kwargs``.
        """
        skipped_dirs = {".git", "__pycache__", ".apex", ".epistemic", "node_modules",
                        ".venv", "venv", "dist", "build", ".turbo", ".next"}
        defs_by_name: dict[str, list[tuple[str, ast.AST]]] = {}
        object_refs: set[str] = set()
        scanned = 0
        for path in sorted(self.root.rglob("*.py")):
            if scanned >= self.max_files:
                break
            rel = path.relative_to(self.root)
            rel_str = rel.as_posix()
            if any(part in skipped_dirs for part in rel.parts):
                continue
            if self._is_fixture_path(rel_str):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError):
                continue
            scanned += 1
            call_funcs = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
            for node in ast.walk(tree):
                # Any non-call reference means the function travels as an
                # object — its signature belongs to whoever receives it.
                if isinstance(node, ast.Name) and id(node) not in call_funcs:
                    object_refs.add(node.id)
                elif isinstance(node, ast.Attribute) and id(node) not in call_funcs:
                    object_refs.add(node.attr)
            for fn in tree.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs_by_name.setdefault(fn.name, []).append((rel_str, fn))

        found: list[dict] = []
        for name, defs in defs_by_name.items():
            if len(defs) != 1 or name in object_refs:
                continue
            rel_str, fn = defs[0]
            if fn.decorator_list:
                continue
            body = [s for s in fn.body
                    if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
            if all(isinstance(s, (ast.Pass, ast.Raise)) for s in body):
                continue  # stub / protocol shape — params are the contract
            read = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
            a = fn.args
            for p in [*a.posonlyargs, *a.args, *a.kwonlyargs]:
                if p.arg.startswith("_") or p.arg in ("self", "cls"):
                    continue
                if p.arg not in read:
                    found.append({"module": rel_str, "function": name,
                                  "param": p.arg, "line": fn.lineno})
        found.sort(key=lambda d: (d["module"], d["line"], d["param"]))
        profile.dead_params = found[:5]
