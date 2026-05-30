from __future__ import annotations

from dataclasses import dataclass

from app.models.idea import IdeaNode
from app.tools.project_profile import ProjectProfile
from app.utils.branching import make_branch_path


@dataclass(frozen=True)
class Operator:
    """A development lens that turns an idea about ``{x}`` into a child idea.

    ``template`` is phrased so it reads naturally when appended to a parent
    direction; ``feasibility`` is a cheap 0..1 weight (cheaper lenses score
    higher) used by the engine's value function.
    """

    name: str
    template: str
    feasibility: float


# The fixed permutation alphabet — the "abc" applied to every branch "a".
# Data-driven so breadth is tunable and plugins can extend it later.
DEVELOPMENT_OPERATORS: list[Operator] = [
    Operator("extend", "Extend {x} with a new capability", 0.6),
    Operator("harden", "Harden {x} against failure and abuse", 0.6),
    Operator("test", "Raise test coverage and add property tests for {x}", 0.85),
    Operator("simplify", "Refactor {x} to reduce complexity", 0.5),
    Operator("document", "Document the contract and usage of {x}", 0.85),
    Operator("integrate", "Integrate {x} with another subsystem", 0.4),
    Operator("generalize", "Make {x} reusable and configurable", 0.45),
    Operator("observe", "Add metrics and logging around {x}", 0.7),
]


class IdeaSeeder:
    """Derive root development branches from a project's real structure.

    Each root is grounded in concrete profile facts (``source_facts``) so every
    downstream idea is traceable to actual code.
    """

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

    def seed(self, profile: ProjectProfile, objective: str | None = None) -> list[IdeaNode]:
        roots: list[IdeaNode] = []
        seen_subjects: set[str] = set()

        for attr, limit, title_tmpl, fact_label in self._RULES:
            values = getattr(profile, attr, []) or []
            for subject in values[:limit]:
                if subject in seen_subjects:
                    continue
                seen_subjects.add(subject)
                idx = len(roots)
                roots.append(
                    IdeaNode(
                        id=f"idea-{idx}",
                        title=title_tmpl.format(s=subject),
                        subject=subject,
                        rationale=f"Seeded from {fact_label}: {subject}",
                        branch_path=make_branch_path("x", idx),
                        depth=0,
                        operator="root",
                        source_facts=[f"{fact_label}: {subject}"],
                    )
                )

        # If the project has no CI, that itself is a development direction.
        if not getattr(profile, "ci_files", None):
            idx = len(roots)
            roots.append(
                IdeaNode(
                    id=f"idea-{idx}",
                    title="Add continuous-integration automation",
                    subject="CI pipeline",
                    rationale="Seeded from missing-ci: no CI workflow files detected",
                    branch_path=make_branch_path("x", idx),
                    depth=0,
                    operator="root",
                    source_facts=["missing-ci: no CI workflow files detected"],
                )
            )

        return roots
