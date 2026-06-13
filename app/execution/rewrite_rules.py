"""The project-local rewrite rule book — recipes with one-line contribution cost.

OpenRewrite proved the catalog model (deterministic recipes, run anywhere);
its contribution cost is a compiler-grade visitor. Apex's book keeps the
model and drops the cost: a rule is a name plus one ``$``-pattern and one
replacement, saved in ``.apex/rewrite-rules.json``, runnable one-by-one or
as a whole book — every application suite-verified with rollback. Paired
with the nightly run, saved rules become fitness functions that fix
themselves: drift that re-enters the codebase gets rewritten back out.
"""

from __future__ import annotations

import json
from pathlib import Path

RULES_REL = ".apex/rewrite-rules.json"

__all__ = ["load_rules", "save_rule", "RULES_REL"]


def load_rules(project_root: str | Path) -> list[dict]:
    path = Path(project_root) / RULES_REL
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in rules
            if isinstance(r, dict) and r.get("name") and r.get("pattern")]


def save_rule(project_root: str | Path, name: str, pattern: str,
              replacement: str) -> str | None:
    """Append a rule; returns an error string instead of overwriting a name."""
    rules = load_rules(project_root)
    if any(r["name"] == name for r in rules):
        return f"a rule named '{name}' already exists — pick another name"
    rules.append({"name": name, "pattern": pattern, "replacement": replacement})
    path = Path(project_root) / RULES_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rules, indent=2), encoding="utf-8")
    return None
