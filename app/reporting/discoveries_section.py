"""Emergent discoveries — a non-competing surface for what Apex *found*.

The dream's open-ended discovery (``app/engine/dream_discovery``) answers the
question nobody coded a rule for: *what travels with what on THIS codebase?* Its
associations, triples, confluences and clique bundles were deliberately kept out
of the bounded idea tree — seeding them displaced budgeted synthesis. This module
gives those discoveries their own home: a self-contained, deterministic Markdown
section that reports every emergent pattern without touching a single idea.

Purely a *view*. It reuses ``discover_emergent`` (the richer four-kind discovery)
for the pattern text + confidence/support, and ``discovered_idea_seeds`` only to
name the concrete module a module-bound discovery points at — no new analysis,
no scoring, no time/random. Same profile → byte-identical Markdown. An empty or
below-threshold profile renders a short, honest "no emergent patterns" section
and never raises.
"""

from __future__ import annotations

from typing import Any

from app.engine.dream_discovery import discover_emergent, discovered_idea_seeds

_HEADING = "# Emergent discoveries"
_MAX_BULLETS = 12  # keep the section bounded regardless of project size


def _seed_modules(profile: Any) -> set[str]:
    """The concrete modules ``discovered_idea_seeds`` grounded a discovery in.

    A module-bound discovery (association, confluence, clique) graduates into a
    seed pointing at one real module; triples are project-wide and carry none.
    We reuse the seeder's own grounding so a bullet can name *where* a pattern
    lives, without re-deriving it. Returned as a set for membership checks.
    """
    return {seed["module"] for seed in discovered_idea_seeds(profile)
            if seed.get("module")}


def _where(disc: Any, modules: set[str]) -> str:
    """The ` — in \\`module\\`` suffix when this discovery is bound to a module.

    Only confluences embed their module directly in the stable key
    (``confluence:app/x.py``); for those we surface the module when the seeder
    also grounded it. Other kinds key on tags, not modules, so they stay
    project-wide here.
    """
    if disc.kind != "confluence":
        return ""
    module = disc.key.split(":", 1)[1] if ":" in disc.key else ""
    return f" — in `{module}`" if module in modules else ""


def _bullet(disc: Any, modules: set[str]) -> str:
    """One Markdown bullet: kind, where-it-lives, human text, confidence/support."""
    confidence = int(round(disc.confidence * 100))
    return (f"- **{disc.kind}**{_where(disc, modules)}: {disc.text} "
            f"_(confidence {confidence}%, support {disc.support})_")


def _bullets(profile: Any) -> list[str]:
    """Deterministic, capped bullets — one per discovery, in discovery order."""
    modules = _seed_modules(profile)
    out: list[str] = []
    for disc in discover_emergent(profile):
        out.append(_bullet(disc, modules))
        if len(out) >= _MAX_BULLETS:
            break
    return out


def _empty_section() -> str:
    """The honest below-threshold state — never an error, always valid Markdown."""
    return (f"{_HEADING}\n\n"
            "_No emergent patterns found — too few co-occurring signals on this "
            "codebase for a discovered law to hold._\n")


def render_discoveries_markdown(profile: Any) -> str:
    """Render the project's emergent discoveries as a self-contained Markdown section.

    A heading followed by one bullet per discovered pattern (association, triple,
    confluence or clique), each naming the kind, the human-readable pattern, the
    module it lives in where one is known, and its confidence/support. Empty or
    below-threshold profile → a short "no emergent patterns found" section. Pure,
    deterministic, capped at ``_MAX_BULLETS``, and never raises.
    """
    bullets = _bullets(profile)
    if not bullets:
        return _empty_section()
    lines = [_HEADING, "",
             f"{len(bullets)} pattern(s) Apex found, not pre-named — what travels "
             "with what on this codebase.", ""]
    lines.extend(bullets)
    lines.append("")
    return "\n".join(lines)
