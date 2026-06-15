"""IdeaSeeder — root development branches from a project's real structure.

Extracted from idea_permutation.py, the engine's own top confluence target
(4 signals: hub, high-churn, co-change, single-author). Mechanical move:
idea_permutation re-exports IdeaSeeder, so the import surface is unchanged.
"""

from __future__ import annotations

from app.models.idea import IdeaNode
from app.tools.project_profile import ProjectProfile
from app.utils.branching import make_branch_path

class IdeaSeeder:
    """Derive root development branches from a project's real structure.

    Each root is grounded in concrete profile facts (``source_facts``) so every
    downstream idea is traceable to actual code.
    """

    def __init__(self, project_root: str = "") -> None:
        # Empty by default ON PURPOSE: a bare seeder must be hermetic — it
        # reads no cwd-relative state (a real .apex/dream-promotions.json in
        # the working directory leaked into "empty profile" tests). Promotions
        # are only read when the engine wires an explicit root.
        self.project_root = str(project_root)

    # (profile attribute, max seeds, subject label, title template, fact label)
    _RULES = [
        ("dependency_hubs", 3, "Evolve the central module {s}", "dependency-hub"),
        ("critical_untested_modules", 3, "Establish a safety net around {s}", "critical-untested"),
        ("untested_modules", 2, "Add a first test layer for {s}", "untested"),
        ("sensitive_paths", 3, "Harden the sensitive path {s}", "sensitive-path"),
        ("entrypoints", 2, "Grow capability behind the entrypoint {s}", "entrypoint"),
        ("symbol_hubs", 2, "Generalize the symbol-rich module {s}", "symbol-hub"),
        ("config_files", 1, "Make configuration {s} environment-aware", "config"),
    ]

    def _module_anchors(self, profile: ProjectProfile, module: str) -> list[dict]:
        """The riskiest function(s) WITHIN ``module``, as concrete anchors.

        Looks up ``profile.hotspot_functions`` (and ``impure_untested_functions``
        as a fallback) for entries whose ``module`` matches, takes the top 1-3 by
        complexity, and returns anchors shaped
        ``{"module", "symbol", "line", "metric}``. Order is deterministic:
        complexity descending, then line ascending. When the module has no
        function-grain data, returns an empty list (the anchors stay a no-op).
        """
        candidates: list[dict] = []
        seen: set[tuple[str, int]] = set()
        for fn in (getattr(profile, "hotspot_functions", []) or []):
            if fn.get("module") != module:
                continue
            symbol = fn.get("function", "")
            line = int(fn.get("line", 0) or 0)
            complexity = int(fn.get("complexity", 0) or 0)
            key = (symbol, line)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                "module": module,
                "symbol": symbol,
                "line": line,
                "metric": f"cyclomatic {complexity}",
                "_complexity": complexity,
            })
        # Impure-untested functions carry no cyclomatic count, so they only fill
        # in when the module has no complexity hotspot (they still ground the
        # idea on a real, named function + line).
        if not candidates:
            for fn in (getattr(profile, "impure_untested_functions", []) or []):
                if fn.get("module") != module:
                    continue
                symbol = fn.get("function", "")
                line = int(fn.get("line", 0) or 0)
                key = (symbol, line)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({
                    "module": module,
                    "symbol": symbol,
                    "line": line,
                    "metric": "impure, untested",
                    "_complexity": 0,
                })
        # Well-tested-repo fallback: hotspot_functions only lists complex
        # *untested* functions, so on a well-covered codebase it is empty even
        # though a confluence/hub/simplify recommendation still has a concrete
        # locus. Parse the module for its most complex functions directly, so
        # the "focus" anchor fires by complexity regardless of test status.
        if not candidates:
            candidates.extend(self._complexity_anchors(module, seen))
        candidates.sort(key=lambda a: (-a["_complexity"], a["line"], a["symbol"]))
        return [
            {"module": a["module"], "symbol": a["symbol"],
             "line": a["line"], "metric": a["metric"]}
            for a in candidates[:3]
        ]

    # Cyclomatic threshold for naming a function as the concrete locus when no
    # untested hotspot exists — branchy enough to be worth pointing at.
    _ANCHOR_MIN_COMPLEXITY = 6

    # The concrete, developer-facing consequence of each half-built protocol —
    # appended to the incomplete-protocol idea title so it reads as a real
    # development task, not a lint note. Deliberately free of the token
    # "untested" (which would auto-promote the fact to an executable test).
    _PROTOCOL_CONSEQUENCE = {
        "equality/hash": "(instances can't be set/dict keys)",
        "context-manager": "(it can't be used in a `with` block)",
        "async-context-manager": "(it can't be used in an `async with` block)",
    }

    def _complexity_anchors(self, module: str, seen: set[tuple[str, int]]) -> list[dict]:
        """Top complex functions in ``module`` by cyclomatic complexity, parsed
        directly — the test-status-independent anchor source. Deterministic;
        returns [] when the module can't be read/parsed."""
        from pathlib import Path

        from app.tools.code_metrics import function_complexities

        if not self.project_root:
            return []
        try:
            source = (Path(self.project_root) / module).read_text(
                encoding="utf-8", errors="ignore")
        except OSError:
            return []
        out: list[dict] = []
        for name, line, complexity in function_complexities(source):
            if int(complexity) < self._ANCHOR_MIN_COMPLEXITY:
                continue
            simple = name.rsplit(".", 1)[-1]
            if simple.startswith("__") and simple.endswith("__"):
                continue
            key = (name, int(line))
            if key in seen:
                continue
            seen.add(key)
            out.append({"module": module, "symbol": name, "line": int(line),
                        "metric": f"cyclomatic {int(complexity)}",
                        "_complexity": int(complexity)})
        return out

    @staticmethod
    def _cochange_link_phrase(links: list[dict]) -> str:
        """A concrete clause naming the symbol(s) one module imports from the other.

        ``links`` is the profile's sorted, capped ``[{"from","to","symbol"}, ...]``.
        Produces e.g. ``app/b.py imports `foo` from app/a.py`` — one clause per
        (from, to) direction, symbols joined with ``/``, directions joined with
        ``; ``. Deterministic (the list is already sorted).
        """
        grouped: dict[tuple[str, str], list[str]] = {}
        for link in links:
            key = (link.get("from", ""), link.get("to", ""))
            grouped.setdefault(key, []).append(link.get("symbol", ""))
        parts = []
        for (frm, to), symbols in grouped.items():
            names = "/".join(f"`{s}`" for s in symbols if s)
            parts.append(f"{frm} imports {names} from {to}")
        return "; ".join(parts)

    def _cochange_anchors(self, links: list[dict], cochanges: int) -> list[dict]:
        """Anchors pointing at the linking symbol(s) in their defining module.

        Each anchor is ``{"module","symbol","line","metric"}`` where ``module`` is
        the symbol's DEFINING module (``link["to"]``, since ``from to import sym``),
        ``line`` is its ``def``/``class``/assignment line when resolvable from
        ``project_root`` (0 otherwise), and ``metric`` is ``"co-changes N"``.
        Deterministic: links are pre-sorted; capped at 3; de-duped by (module,
        symbol).
        """
        anchors: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for link in links:
            module = link.get("to", "")
            symbol = link.get("symbol", "")
            if not module or not symbol:
                continue
            key = (module, symbol)
            if key in seen:
                continue
            seen.add(key)
            anchors.append({
                "module": module,
                "symbol": symbol,
                "line": self._symbol_def_line(module, symbol),
                "metric": f"co-changes {cochanges}",
            })
        return anchors[:3]

    def _symbol_def_line(self, module: str, symbol: str) -> int:
        """The definition line of ``symbol`` in ``module``, or 0 when unresolvable.

        Parses ``module`` (under ``project_root``) and returns the line of the
        top-level ``def``/``class``/assignment named ``symbol``. Returns 0 when no
        root is wired, the file can't be parsed, or the symbol isn't defined there
        — anchors stay valid ("where resolvable").
        """
        import ast
        from pathlib import Path

        root = getattr(self, "project_root", "")
        if not root:
            return 0
        try:
            tree = ast.parse((Path(root) / module).read_text(encoding="utf-8", errors="ignore"))
        except (OSError, SyntaxError, ValueError):
            return 0
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == symbol:
                    return node.lineno
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == symbol:
                        return node.lineno
        return 0

    @staticmethod
    def _fanin_fanout_from_edges(
        edges: list[tuple[str, str]], module: str
    ) -> tuple[int, list[str]]:
        """Fan-in count and heaviest fan-out targets for ``module`` from edges.

        ``edges`` is ``ProjectProfile.dependency_edges`` (``[(source, target)]``)
        — the SAME graph the profiler already built, counted here (no second
        graph). Fan-in is the number of DISTINCT modules importing ``module``
        (edges whose target is ``module``). Fan-out targets are ``module``'s own
        DISTINCT dependencies (edges whose source is ``module``), ranked by each
        target's own fan-in (the most-depended-on dependency first — shedding it
        cuts the most convergence), tie-broken by path, capped at 3. Deterministic
        for a given edge list.
        """
        importers: dict[str, set[str]] = {}
        deps: set[str] = set()
        for source, target in edges:
            if source == target:
                continue
            importers.setdefault(target, set()).add(source)
            if source == module:
                deps.add(target)
        fanin = len(importers.get(module, set()))
        targets = sorted(deps, key=lambda t: (-len(importers.get(t, set())), t))[:3]
        return fanin, targets

    def _quantified_clause(self, profile: ProjectProfile, module: str,
                           *, name_targets: bool) -> str:
        """A grounded clause quantifying a module-level root's concrete payoff.

        Pulls fan-in/fan-out from the SAME dependency data already on the profile:
        the precomputed ``module_fanin`` / ``module_fanout`` (built off the one
        graph the profiler builds), falling back to counting ``dependency_edges``
        directly when those dicts aren't populated (a synthetic profile that wires
        only edges still gets real numbers — no second graph either way). Two
        parts, each emitted only when the data backs it, so the result degrades to
        ``""`` (a byte-identical fallback) for any module the dependency scan
        didn't reach:

        - **fan-in** (always, when known): ``Imported by N modules — a change here
          ripples to all of them``, the literal blast radius;
        - **decoupling targets** (only when ``name_targets`` — hub/confluence
          roots, where shedding a dependency is the move): names this module's
          heaviest fan-out targets (its most-depended-on dependencies), e.g.
          ``Its 3 heaviest dependencies are app/x.py, app/y.py, app/z.py —
          decoupling one cuts the convergence``.

        Numbers are real and the target list is deterministic (pre-sorted).
        """
        fanin = (getattr(profile, "module_fanin", {}) or {}).get(module)
        targets = (getattr(profile, "module_fanout", {}) or {}).get(module)
        # Fall back to the raw edge list when the precomputed dicts are absent.
        if fanin is None or (name_targets and targets is None):
            edges = getattr(profile, "dependency_edges", []) or []
            edge_fanin, edge_targets = self._fanin_fanout_from_edges(edges, module)
            if fanin is None:
                fanin = edge_fanin
            if targets is None:
                targets = edge_targets
        parts: list[str] = []
        if fanin:
            noun = "module" if fanin == 1 else "modules"
            parts.append(
                f"Imported by {fanin} {noun} — a change here ripples to all of them."
            )
        if name_targets and targets:
            listed = ", ".join(targets)
            n = len(targets)
            noun = "dependency" if n == 1 else "dependencies"
            verb = "is" if n == 1 else "are"
            parts.append(
                f"Its {n} heaviest {noun} {verb} {listed} "
                f"— decoupling one cuts the convergence."
            )
        return " ".join(parts)

    @staticmethod
    def _anchor_phrase(anchors: list[dict]) -> str:
        """A concise concrete sentence naming the anchored function(s)."""
        parts = []
        for a in anchors:
            simple = a["symbol"].rsplit(".", 1)[-1]
            parts.append(f"`{simple}` ({a['metric']}, line {a['line']})")
        joined = " and ".join(parts)
        return f"Centers on {joined} — decouple/test these first."

    def _append_root(
        self,
        roots: list[IdeaNode],
        seen_subjects: set,
        *,
        title: str,
        subject: str,
        fact_label: str,
        fact_value: str,
        rationale: str | None = None,
        anchors: list[dict] | None = None,
        quantified: str | None = None,
    ) -> None:
        """Append a traceable root idea unless its subject was already seeded."""
        if subject in seen_subjects:
            return
        seen_subjects.add(subject)
        # Temporal annotation rides on WHICHEVER root claims the subject:
        # rising churn while a risk ages is part of the fact, not a separate
        # idea competing for the same module.
        trend = getattr(self, "_accel", {}).get(subject)
        if trend:
            risks = "/".join(trend["aging"])
            title += (f" — accelerating: {trend['churn_before']}→{trend['churn_now']} "
                      f"commits while its {risks} risk ages")
            fact_value += f" (accelerating {trend['churn_before']}→{trend['churn_now']})"
        anchors = anchors or []
        base_rationale = rationale or f"Seeded from {fact_label}: {fact_value}"
        # Fold the concrete locus into the rationale so the abstract module-level
        # idea names a real function + line, while title/subject stay unchanged.
        if anchors:
            base_rationale = f"{base_rationale} {self._anchor_phrase(anchors)}"
        # Quantified payoff (fan-in blast radius + named decoupling targets) rides
        # AFTER the anchor phrase. Empty string when the dependency data isn't
        # available for this module, so the rationale is byte-identical to before.
        if quantified:
            base_rationale = f"{base_rationale} {quantified}"
        idx = len(roots)
        roots.append(
            IdeaNode(
                id=f"idea-{idx}",
                title=title,
                subject=subject,
                rationale=base_rationale,
                branch_path=make_branch_path("x", idx),
                depth=0,
                operator="root",
                anchors=anchors,
                source_facts=[f"{fact_label}: {fact_value}"],
            )
        )

    def _dream_promotions(self) -> list[dict]:
        """Confirmed, graduated dream discoveries (empty without the store)."""
        import json
        from pathlib import Path

        root = getattr(self, "project_root", "")
        if not root:
            return []  # hermetic without an explicit root — never read cwd
        path = Path(root) / ".apex" / "dream-promotions.json"
        if not path.exists():
            return []
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out: list[dict] = []
        for it in items if isinstance(items, list) else []:
            key = it.get("key", "")
            # A confluence names a module; bind the idea to it. Associations
            # are project-wide structure, so they keep the abstract subject.
            subject = ""
            if key.startswith("confluence:"):
                subject = key.split(":", 1)[1]
            out.append({**it, "subject": subject})
        return out

    def seed(self, profile: ProjectProfile, objective: str | None = None,
             accelerating: dict[str, dict] | None = None) -> list[IdeaNode]:
        roots: list[IdeaNode] = []
        seen_subjects: set[str] = set()
        self._accel = accelerating or {}

        # High-severity content signals claim their subject first: a guaranteed
        # crash or a real vulnerability is more urgent than "this file is a hub"
        # or "untested", so they are framed by the bug/finding, not the generic
        # rule. (A module flagged by several signals still converges below.)
        for module in (getattr(profile, "correctness_bug_modules", []) or [])[:3]:
            self._append_root(
                roots, seen_subjects,
                title=f"Fix the likely crash/logic bug in {module}",
                subject=module,
                fact_label="correctness-bug",
                fact_value=f"{module} (high-severity logic bug detected)",
            )
        # Content-based security findings: the file actually contains eval/
        # os.system/pickle/... — point harden straight at it, regardless of
        # whether its *name* matched a sensitive hint. When git blame shows
        # the finding has been sitting in the code for months, the idea says
        # so: the EXPOSURE WINDOW is part of the fact, not editorializing.
        sec_ages = getattr(profile, "security_finding_ages", {}) or {}
        for module in (getattr(profile, "security_finding_modules", []) or [])[:3]:
            title = f"Fix the security findings in {module}"
            fact_value = f"{module} (eval/os.system/pickle/... detected)"
            age_days = sec_ages.get(module, 0)
            if age_days >= 90:
                months = age_days // 30
                title += f" — exposed for ~{months} months"
                fact_value = f"{module} (security finding, in the code ~{months} months)"
            self._append_root(
                roots, seen_subjects,
                title=title,
                subject=module,
                fact_label="security-finding",
                fact_value=fact_value,
            )

        # Confluences (signal convergence): modules named by >= 3 DISTINCT signal
        # families at once — no single lens names them, yet a module under
        # several independent pressures is the highest-leverage development
        # target ("decouple/test before you change"). Framed BEFORE the generic
        # per-family signals so the convergence is the headline, not any one
        # pressure; security stays a SUPPORTING family in the list, never the
        # title. Claiming the subject here dedups it out of fragile/hub-untested/
        # complexity below, so a confluence module is seeded once.
        for conv in (getattr(profile, "confluence_modules", []) or [])[:3]:
            module = conv["module"]
            families = conv.get("families", ()) or ()
            count = conv.get("family_count", len(families))
            shown = ", ".join(families)
            untested = "untested" in families
            self._append_root(
                roots, seen_subjects,
                title=(f"Untangle {module} — {count} independent pressures "
                       f"converge ({shown})"),
                subject=module,
                fact_label="confluence",
                fact_value=(f"{module} ({count} signal families converge: {shown}"
                            + ("; untested" if untested else "")
                            + ")"),
                anchors=self._module_anchors(profile, module),
                quantified=self._quantified_clause(profile, module, name_targets=True),
            )

        # Fragility first (highest priority): heavily-depended-on but thinly
        # tested modules — the biggest blast-radius risk.
        for module in (getattr(profile, "fragile_modules", []) or [])[:3]:
            self._append_root(
                roots, seen_subjects,
                title=f"Reduce fragility of the heavily-depended-on module {module}",
                subject=module,
                fact_label="fragile",
                fact_value=f"{module} (high in-degree, thin tests)",
                anchors=self._module_anchors(profile, module),
                quantified=self._quantified_clause(profile, module, name_targets=False),
            )

        for attr, limit, title_tmpl, fact_label in self._RULES:
            values = getattr(profile, attr, []) or []
            for subject in values[:limit]:
                # The "evolve central module" (dependency-hub) root is module-
                # level — anchor it at the riskiest function within. Other rules
                # (sensitive paths, config, entrypoints) are module-or-file
                # subjects too; anchors are looked up by name and stay empty when
                # there is no function-grain data, so this is a safe no-op there.
                self._append_root(
                    roots, seen_subjects,
                    title=title_tmpl.format(s=subject),
                    subject=subject,
                    fact_label=fact_label,
                    fact_value=subject,
                    anchors=(self._module_anchors(profile, subject)
                             if fact_label == "dependency-hub" else None),
                    # The dependency-hub root is a true hub: quantify its blast
                    # radius (fan-in) AND name the specific decoupling targets
                    # (its heaviest dependencies). Other rules (sensitive paths,
                    # config, entrypoints) are not hubs, so they carry no clause.
                    quantified=(self._quantified_clause(profile, subject, name_targets=True)
                                if fact_label == "dependency-hub" else None),
                )

        # Coverage DEPTH is handled by the substance-based shallow-coverage signal
        # below (tests that assert no behaviour), not by counting test files: a
        # module with a single *substantive* test is adequately covered, so the
        # old "1 test file = thin" heuristic only produced noise and is dropped.

        # Shallow coverage: modules "covered" only by characterization stubs
        # (import-smoke + isinstance), which prove shape, not correctness — so the
        # engine asks for real behavioural assertions instead of calling it done.
        for module in (getattr(profile, "shallow_tested_modules", []) or [])[:3]:
            self._append_root(
                roots, seen_subjects,
                title=f"Deepen the shallow tests of {module} (assert real behaviour, not just types)",
                subject=module,
                fact_label="shallow-coverage",
                fact_value=f"{module} (only smoke/type assertions)",
            )

        # Complexity hotspots: modules combining high cyclomatic complexity with
        # blast radius and thin tests — the riskiest places to change, so derisk
        # them with tests/simplification before they cause incidents.
        for module in (getattr(profile, "hotspot_modules", []) or [])[:3]:
            self._append_root(
                roots, seen_subjects,
                title=f"De-risk the complexity hotspot {module} (simplify and add tests)",
                subject=module,
                fact_label="complexity-hotspot",
                fact_value=f"{module} (high complexity x fan-in, thin tests)",
                anchors=self._module_anchors(profile, module),
                quantified=self._quantified_clause(profile, module, name_targets=False),
            )

        # Symbol granularity: the riskiest *functions* — heavy branching that no
        # linked test ever names. A subject like ``mod.py::func`` keeps the idea
        # distinct from its module's, so both levels can coexist in the tree.
        for fn in (getattr(profile, "hotspot_functions", []) or [])[:3]:
            simple = fn["function"].rsplit(".", 1)[-1]
            self._append_root(
                roots, seen_subjects,
                title=(f"Write behavioral tests for {simple}() in {fn['module']} "
                       f"(complexity {fn['complexity']}, never named by a test)"),
                subject=f"{fn['module']}::{fn['function']}",
                fact_label="hotspot-function",
                fact_value=(f"{fn['module']}::{fn['function']} "
                            f"(complexity {fn['complexity']}"
                            + (f", cognitive {fn['cognitive']}" if fn.get("cognitive") else "")
                            + f", line {fn['line']}, no direct tests)"),
            )

        # Purity violation: functions that mix observable side effects (I/O,
        # global state, os/subprocess/logging calls) with logic AND that no test
        # exercises. The development move is to isolate the effect so the core
        # becomes pure and testable — so this biases the test/verify/decouple
        # lenses (it is in _SECURITY_LABELS) toward the now-testable seam. A
        # subject like ``mod.py::func`` keeps it distinct from its module's idea;
        # if the same function is also a complexity hotspot, that more-severe
        # root claimed the subject first and this one dedups under it.
        for fn in (getattr(profile, "impure_untested_functions", []) or [])[:3]:
            simple = fn["function"].rsplit(".", 1)[-1]
            effects = fn.get("side_effects", []) or []
            shown = ", ".join(effects[:3])
            more = f" +{len(effects) - 3} more" if len(effects) > 3 else ""
            self._append_root(
                roots, seen_subjects,
                title=(f"Isolate the side effects of {simple}() in {fn['module']} "
                       f"and cover the core with tests"),
                subject=f"{fn['module']}::{fn['function']}",
                fact_label="impure-untested",
                fact_value=(f"{fn['module']}::{fn['function']} (impure"
                            + (f": {shown}{more}" if shown else "")
                            + f", line {fn['line']}, no direct tests)"),
            )

        # Dependency hubs (high fan-in: many modules import them) that are also
        # untested or shallow-tested — the highest-leverage place to add a
        # regression net, because a break in a hub propagates to every dependent.
        # The Stabilize move is to cover it first (it is in _STABILIZE_LABELS).
        # The fact carries the dependent count so the rationale is concrete. If a
        # hub is also fragile/a complexity hotspot, that more-severe root claimed
        # the module subject first (and the profiler already deduped it out), so
        # this one only fires for hubs the other module-level signals missed.
        for hub in (getattr(profile, "hub_untested_modules", []) or [])[:3]:
            module = hub["module"]
            fan_in = hub.get("fan_in", 0)
            self._append_root(
                roots, seen_subjects,
                title=(f"Cover the dependency hub {module} first "
                       f"({fan_in} modules import it, no/shallow tests)"),
                subject=module,
                fact_label="hub-untested",
                fact_value=(f"{module} (dependency hub: {fan_in} dependents, "
                            f"untested or shallow — a regression here breaks all "
                            f"{fan_in})"),
                anchors=self._module_anchors(profile, module),
            )

        # Co-change test-gap: module PAIRS that frequently change together (from
        # git co-change) yet NO single test exercises BOTH — a change to one can
        # silently break the other with nothing to catch it. The development move
        # is to add a joint test, so this is framed as a DEVELOPMENT idea. The
        # subject is the PAIR (so it never collides with a single-module subject)
        # and the fact carries the co-change count so the rationale is concrete.
        # Git-only, so light mode yields nothing (the family is simply empty).
        for gap in (getattr(profile, "cochange_test_gaps", []) or [])[:3]:
            a, b = gap["a"], gap["b"]
            cochanges = gap.get("cochanges", 0)
            links = gap.get("links") or []
            if links:
                # Concrete: name the ACTUAL symbol(s) that link the two modules,
                # so the test recommendation targets the real interface instead
                # of an abstract "exercise A and B together".
                phrase = self._cochange_link_phrase(links)
                anchors = self._cochange_anchors(links, cochanges)
                self._append_root(
                    roots, seen_subjects,
                    title=(f"Add a test exercising the {a} ↔ {b} interaction "
                           f"({phrase}) — they co-change but nothing tests them "
                           f"jointly"),
                    subject=f"{a} + {b}",
                    fact_label="cochange-testgap",
                    fact_value=(f"{a} & {b} (co-change {cochanges}x via {phrase}, "
                                f"but no single test exercises both — a change to "
                                f"one can silently break the other)"),
                    anchors=anchors,
                )
            else:
                # Fallback — byte-identical to the original module-pair phrasing
                # when no direct import links the two modules.
                self._append_root(
                    roots, seen_subjects,
                    title=(f"Add a test that exercises {a} and {b} together — they "
                           f"co-change but nothing tests them jointly"),
                    subject=f"{a} + {b}",
                    fact_label="cochange-testgap",
                    fact_value=(f"{a} & {b} (co-change {cochanges}x but no single test "
                                f"exercises both — a change to one can silently break "
                                f"the other)"),
                )

        # Technical-debt markers: modules carrying a cluster of TODO/FIXME/XXX/
        # HACK comments are concrete, traceable pockets of deferred work. When
        # git blame shows the oldest marker has waited months, the idea says so
        # — a 3-year-old FIXME is a different fact than one written yesterday.
        debt_ages = getattr(profile, "debt_marker_ages", {}) or {}
        for module in (getattr(profile, "debt_marker_modules", []) or [])[:3]:
            title = f"Address the TODO/FIXME debt markers in {module}"
            fact_value = f"{module} (clustered TODO/FIXME/XXX/HACK comments)"
            age_days = debt_ages.get(module, 0)
            if age_days >= 90:
                months = age_days // 30
                title += f" — the oldest has waited {months} months"
                fact_value = f"{module} (clustered debt markers; oldest ~{months} months old)"
            self._append_root(
                roots, seen_subjects,
                title=title,
                subject=module,
                fact_label="debt-markers",
                fact_value=fact_value,
            )

        # Change-frequency hotspots (git churn): the modules recent commits
        # touch most. Where change concentrates is where the project is alive —
        # evolve its change path (interfaces, coupling, simplification) instead
        # of letting the busiest module calcify.
        for spot in (getattr(profile, "churn_hotspots", []) or [])[:3]:
            self._append_root(
                roots, seen_subjects,
                title=(f"Smooth the change path of {spot['module']} "
                       f"(touched by {spot['commits']} recent commits)"),
                subject=spot["module"],
                fact_label="churn-hotspot",
                fact_value=f"{spot['module']} ({spot['commits']} commits in recent history)",
            )

        # Polyglot hotspots: the biggest / most-churned NON-Python source files.
        # Apex deep-analyses only Python, so these are framed as honest AWARENESS,
        # not an executable fix — the largest active surface outside analysis
        # scope, where the non-Python risk concentrates. The subject is the file
        # path (deduped through the same chokepoint). Git-only churn, so an
        # all-Python repo yields nothing here and seeding stays byte-identical.
        for hot in (getattr(profile, "polyglot_hotspots", []) or [])[:3]:
            path = hot["path"]
            loc = hot.get("loc", 0)
            churn = hot.get("churn", 0)
            language = hot.get("language", "")
            commit_word = "commit" if churn == 1 else "commits"
            # Debt clause: additive, READY for when the profile's hotspot dict
            # carries a TODO/FIXME count. The field isn't on the profile yet, so
            # an absent/zero ``debt_markers`` leaves title + fact byte-identical.
            # Stays recommend-only: never the token "untested" — "TODO/FIXME".
            debt = hot.get("debt_markers") or 0
            title_debt = f", {debt} TODO/FIXME marker(s)" if debt else ""
            fact_debt = f", {debt} TODO/FIXME" if debt else ""
            self._append_root(
                roots, seen_subjects,
                title=(f"Review `{path}` — {loc} LOC, {churn} recent {commit_word}, "
                       f"the largest active surface outside Python analysis scope "
                       f"(Apex can't deep-analyse it, but it concentrates "
                       f"non-Python risk){title_debt}"),
                subject=path,
                fact_label="polyglot-hotspot",
                fact_value=(f"{path} ({language}, {loc} LOC, {churn} recent "
                            f"{commit_word}{fact_debt} — biggest/most-active file "
                            f"outside Apex's Python analysis scope)"),
            )

        # Incomplete protocols (CONSTRUCTIVE — "you started a protocol, finish
        # it"): classes that began a Python contract pair without completing it.
        # The essence of a DEVELOPMENT assistant — point at where the project is
        # half-built, not just where it smells. Recommend-only: Apex names the
        # gap and the exact class/line; it does NOT auto-write the missing method.
        # The subject is ``module::Class`` so it never collides with a module-
        # level subject. Pure AST, so an all-clean repo yields nothing here and
        # seeding stays byte-identical. The fact value deliberately avoids the
        # token "untested" (which would auto-promote it to an executable test).
        for proto in (getattr(profile, "incomplete_protocols", []) or [])[:3]:
            module = proto["module"]
            cls = proto["class"]
            line = proto.get("line", 0)
            have = proto.get("have", "")
            missing = proto.get("missing", "")
            protocol = proto.get("protocol", "")
            locus = f"{module}:{line}"
            consequence = self._PROTOCOL_CONSEQUENCE.get(protocol, "")
            tail = f" {consequence}" if consequence else ""
            self._append_root(
                roots, seen_subjects,
                title=(f"Complete the {protocol} protocol on `{cls}` ({locus}) — "
                       f"defines {have} but no {missing}{tail}"),
                subject=f"{module}::{cls}",
                fact_label="incomplete-protocol",
                fact_value=(f"{cls} in {module} ({protocol}: has {have}, missing "
                            f"{missing} — a half-built contract to finish)"),
            )

        # Dream insights: discoveries the nightly dream CONFIRMED across multiple
        # dreams and graduated (high confidence + persistence). The organism
        # acting on what it learned while you were away — guarded so only a
        # repeatedly-confirmed law ever becomes a development idea.
        for insight in self._dream_promotions()[:2]:
            subject = insight.get("subject") or "project structure"
            self._append_root(
                roots, seen_subjects,
                title=f"Act on a confirmed pattern — {insight['text']}",
                subject=subject,
                fact_label="dream-insight",
                fact_value=(f"{insight['key']} ({int(insight.get('confidence', 0) * 100)}% "
                            f"confidence, confirmed {insight.get('streak', 0)} dreams)"),
            )

        # Knowledge concentration (bus-factor): a module whose recent changes
        # come overwhelmingly from one author is a stability risk the moment
        # that author is unavailable — spread it via docs, tests and pairing.
        for kr in (getattr(profile, "knowledge_risks", []) or [])[:2]:
            self._append_root(
                roots, seen_subjects,
                title=(f"Spread the knowledge of {kr['module']} — "
                       f"{kr['share']}% of its recent changes come from one author"),
                subject=kr["module"],
                fact_label="knowledge-risk",
                fact_value=(f"{kr['module']} ({kr['share']}% single-author "
                            f"across {kr['commits']} commits)"),
            )

        # Documentation drift: the README/docs promise files that don't exist.
        # One root per doc file — you fix the doc (or build the promise), not
        # chase scattered references.
        drift_by_doc: dict[str, list[str]] = {}
        for d in (getattr(profile, "doc_drift", []) or []):
            drift_by_doc.setdefault(d["doc"], []).append(d["reference"])
        for doc, refs in drift_by_doc.items():
            more = f" (+{len(refs) - 1} more)" if len(refs) > 1 else ""
            self._append_root(
                roots, seen_subjects,
                title=f"True up {doc}: it references `{refs[0]}`, which doesn't exist{more}",
                subject=doc,
                fact_label="doc-drift",
                fact_value=f"{doc} -> {', '.join(refs[:3])} (missing)",
            )

        # Dominant language → tooling idea (type hints / lint config).
        exts = getattr(profile, "extension_counts", {}) or {}
        if exts.get(".py", 0) >= 1:
            self._append_root(
                roots, seen_subjects,
                title="Add type hints and a lint/type-check config",
                subject="Python type coverage",
                fact_label="extension-py",
                fact_value=f".py x{exts['.py']}",
            )

        # Mutable default arguments → a real bug class with a safe verified fix.
        for module in (getattr(profile, "mutable_default_modules", []) or [])[:2]:
            self._append_root(
                roots, seen_subjects,
                title=f"Fix mutable default arguments in {module}",
                subject=module,
                fact_label="mutable-default",
                fact_value=f"{module} (def f(x=[]))",
            )

        # Dead parameters: a knob every caller must know about that does
        # nothing. The hands for this already exist — the fact carries the
        # exact `apex signature drop` command, verified with rollback.
        for dp in (getattr(profile, "dead_params", []) or [])[:2]:
            self._append_root(
                roots, seen_subjects,
                title=(f"Drop the dead parameter `{dp['param']}` from "
                       f"{dp['function']}() in {dp['module']}"),
                subject=dp["module"],
                fact_label="dead-parameter",
                fact_value=(f"{dp['module']}:{dp['line']} {dp['function']}({dp['param']}) "
                            f"never read — `apex signature drop {dp['function']} {dp['param']}`"),
            )

        # Extractable seam: a long function with a clean block to lift into a
        # helper. The "extract a shared helper" recommendation, now carrying the
        # exact `apex extract` command (computed params/returns), verified.
        for eb in (getattr(profile, "extractable_blocks", []) or [])[:2]:
            iface = (f"{len(eb['params'])} param(s) in, "
                     f"{len(eb['returns'])} value(s) out")
            self._append_root(
                roots, seen_subjects,
                title=(f"Extract a helper from {eb['function']}() in {eb['module']} "
                       f"(saves {eb['lines_saved']} lines)"),
                subject=eb["module"],
                fact_label="extractable-block",
                fact_value=(f"{eb['module']}:{eb['line']} {eb['function']}() has a "
                            f"clean seam at lines {eb['start']}-{eb['end']} ({iface}) "
                            f"— `apex extract {eb['module']} {eb['start']} "
                            f"{eb['end']} {eb['name']}`"),
            )

        # Inlinable helper: a tiny single-use helper that's a hop the reader has
        # to follow, not a clean abstraction. The "fold it back into its call
        # site" recommendation, now carrying the exact `apex inline` command,
        # verified with rollback.
        for ih in (getattr(profile, "inlinable_helpers", []) or [])[:2]:
            self._append_root(
                roots, seen_subjects,
                title=(f"Inline the single-use helper {ih['function']}() "
                       f"in {ih['module']}"),
                subject=ih["module"],
                fact_label="inlinable-helper",
                fact_value=(f"{ih['module']}:{ih['line']} {ih['function']}() is a "
                            f"single-use helper — `apex inline {ih['function']}`"),
            )

        # Modernization debt → a safe, behavior-preserving cleanup direction.
        for module in (getattr(profile, "modernizable_modules", []) or [])[:2]:
            self._append_root(
                roots, seen_subjects,
                title=f"Modernize comparisons in {module}",
                subject=module,
                fact_label="modernization",
                fact_value=f"{module} (== None / != None)",
            )

        # Dominant top-level directory → structure/boundaries idea.
        for directory in (getattr(profile, "top_directories", []) or [])[:1]:
            self._append_root(
                roots, seen_subjects,
                title=f"Clarify the structure and boundaries of `{directory}/`",
                subject=f"{directory}/ package",
                fact_label="top-directory",
                fact_value=directory,
            )

        # If the project has no CI, that itself is a development direction.
        if not getattr(profile, "ci_files", None):
            self._append_root(
                roots, seen_subjects,
                title="Add continuous-integration automation",
                subject="CI pipeline",
                fact_label="missing-ci",
                fact_value="no CI workflow files detected",
            )

        return roots


