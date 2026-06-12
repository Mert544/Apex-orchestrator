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
        idx = len(roots)
        roots.append(
            IdeaNode(
                id=f"idea-{idx}",
                title=title,
                subject=subject,
                rationale=rationale or f"Seeded from {fact_label}: {fact_value}",
                branch_path=make_branch_path("x", idx),
                depth=0,
                operator="root",
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

        # Fragility first (highest priority): heavily-depended-on but thinly
        # tested modules — the biggest blast-radius risk.
        for module in (getattr(profile, "fragile_modules", []) or [])[:3]:
            self._append_root(
                roots, seen_subjects,
                title=f"Reduce fragility of the heavily-depended-on module {module}",
                subject=module,
                fact_label="fragile",
                fact_value=f"{module} (high in-degree, thin tests)",
            )

        for attr, limit, title_tmpl, fact_label in self._RULES:
            values = getattr(profile, attr, []) or []
            for subject in values[:limit]:
                self._append_root(
                    roots, seen_subjects,
                    title=title_tmpl.format(s=subject),
                    subject=subject,
                    fact_label=fact_label,
                    fact_value=subject,
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


