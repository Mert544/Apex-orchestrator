"""Recipes — the transform catalog, declarative and composable.

Adopted from the OpenRewrite model (human-authored recipes with metadata,
composable into larger migrations; "correctness over completeness"): every
executable action Apex can take is now *described* — what it does, what it
touches, its risk tier — and recipes compose into named plans, so a
maintenance pass can be scoped to an intent ("modernize", "safety-net")
instead of all-or-nothing.

Deterministic and data-only: a recipe never adds capability, it *names and
groups* capability that already exists, so the safety story (tiers, shields,
verification) applies unchanged to every composition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.execution.risk_tiers import tier_for


@dataclass(frozen=True)
class Recipe:
    name: str                 # the action_type it runs
    description: str
    tags: tuple[str, ...] = ()

    @property
    def tier(self) -> int:
        return tier_for(self.name)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "tags": list(self.tags), "tier": self.tier}


RECIPES: dict[str, Recipe] = {
    r.name: r for r in (
        Recipe("create_test_stub",
               "Generate a characterization test for an untested module",
               ("testing", "safety-net")),
        Recipe("add_docstring",
               "Add docstrings to undocumented public symbols",
               ("docs", "polish")),
        Recipe("organize_imports",
               "Tidy and deduplicate the import block",
               ("cleanup", "polish")),
        Recipe("modernize_comparisons",
               "Rewrite `== None` / `!= None` to `is` / `is not`",
               ("cleanup", "modernize")),
        Recipe("fix_mutable_defaults",
               "Replace mutable default arguments with the None idiom",
               ("correctness", "modernize")),
        Recipe("harden_security",
               "Run the detection ladder: eval, os.system, bare except, …",
               ("security", "reliability")),
    )
}

# Named compositions — an intent, not a mechanism. Order is execution order
# preference inside the value-sorted plan (filtering only; never reordering).
COMPOSITES: dict[str, tuple[str, ...]] = {
    "safety-net": ("create_test_stub", "add_docstring"),
    "modernize": ("modernize_comparisons", "organize_imports", "fix_mutable_defaults"),
    "reliability": ("harden_security", "fix_mutable_defaults"),
    "polish": ("add_docstring", "organize_imports"),
}


def recipe_actions(name: str) -> set[str] | None:
    """The action types a recipe (single or composite) runs; None = unknown."""
    if name in RECIPES:
        return {name}
    if name in COMPOSITES:
        return set(COMPOSITES[name])
    return None


def filter_plan(plan: Any, recipe: str) -> int:
    """Scope a plan's EXECUTABLE steps to one recipe (in place).

    Design tasks are kept — scoping an intent shouldn't hide the thinking.
    Returns how many executable steps remain; raises ValueError on an
    unknown recipe so a typo fails loudly instead of running everything.
    """
    allowed = recipe_actions(recipe)
    if allowed is None:
        known = ", ".join(sorted([*RECIPES, *COMPOSITES]))
        raise ValueError(f"unknown recipe '{recipe}' — known: {known}")
    plan.steps = [s for s in plan.steps
                  if not s.executable or s.action_type in allowed]
    return sum(1 for s in plan.steps if s.executable)


@dataclass
class _Row:
    name: str
    kind: str
    tier: str
    description: str
    parts: tuple[str, ...] = field(default_factory=tuple)


def render_recipes_markdown() -> str:
    lines = ["# Recipes — the catalog, named and composable", "",
             "| Recipe | Kind | Tier | What it does |", "|---|---|---|---|"]
    for r in RECIPES.values():
        lines.append(f"| `{r.name}` | single | {r.tier} | {r.description} "
                     f"({', '.join(r.tags)}) |")
    for name, parts in COMPOSITES.items():
        top_tier = max(tier_for(p) for p in parts)
        lines.append(f"| `{name}` | composite | {top_tier} | runs: "
                     f"{', '.join(f'`{p}`' for p in parts)} |")
    lines += ["",
              "_Composites NAME existing capability; tiers, shields and "
              "verification apply unchanged. Run one: "
              "`apex maintain --recipe modernize`._", ""]
    return "\n".join(lines)
