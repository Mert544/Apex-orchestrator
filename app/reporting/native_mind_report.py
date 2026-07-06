"""Make the native intelligence VISIBLE — a deterministic report of what Apex has
learned from the project's OWN code.

The native intelligence (:mod:`app.engine.native_synth`) mines the project's
functions into reusable return-body exemplars it can transplant onto an
unfinished stub (opt-in ``APEX_NATIVE_MIND``, gated by the never-fake-green
verifier). That "brain" is otherwise invisible — nothing shows a buyer WHAT it
learned. This module summarises the learned library into the project's dominant
idioms so a person can SEE the intelligence: "your codebase teaches Apex ``p0 +
p1`` in 12 functions, ``p0 if p0 > p1 else p1`` in 4, …".

Pure and deterministic: same project sources -> same summary (no clock/random),
reading only the same corpus the live lane learns from (via
``stub_synthesis``'s own loader), so the report reflects EXACTLY what Apex would
propose. Zero-token, offline.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.native_synth import adapt_expr_to_params, learn_return_exemplars
from app.execution.stub_synthesis import _native_mind_sources

__all__ = [
    "summarize_native_mind",
    "render_native_mind_markdown",
]


def _canonical_shape(params: tuple[str, ...], expr: str) -> str:
    """The exemplar's return expression with its params renamed to positional
    placeholders ``p0, p1, …`` — so ``a + b`` (learned from ``add(a, b)``) and
    ``m + n`` (from ``plus(m, n)``) collapse to the SAME idiom ``p0 + p1``. This is
    the grouping key that turns a raw exemplar list into "the project's idioms"."""
    canon = tuple(f"p{i}" for i in range(len(params)))
    adapted = adapt_expr_to_params(params, expr, canon)
    return adapted if adapted is not None else expr


def summarize_native_mind(root: str | Path, top: int = 20) -> dict:
    """A deterministic summary of the native intelligence's learned library.

    Returns ``exemplars`` (total bodies mined), ``distinct_shapes`` (idioms after
    positional canonicalisation), ``by_arity`` (how many distinct idioms per
    parameter count), and ``top_idioms`` — the most frequent idiom shapes, each
    with its ``count`` (how many of the project's own functions exhibit it),
    ``arity``, and one ``example`` source function. Ranked by descending count,
    then arity, then shape text (a total, hash-seed-independent order). An empty
    or source-less project yields zeroed counts and an empty idiom list; never
    raises."""
    sources = list(_native_mind_sources(str(Path(root))))
    exemplars = learn_return_exemplars(sources)
    shapes: dict[str, dict] = {}
    for ex in exemplars:
        shape = _canonical_shape(ex.params, ex.expr)
        slot = shapes.setdefault(
            shape, {"count": 0, "arity": len(ex.params), "example": ex.name})
        slot["count"] += 1
    ranked = sorted(
        shapes.items(), key=lambda kv: (-kv[1]["count"], kv[1]["arity"], kv[0]))
    by_arity: dict[int, int] = {}
    for meta in shapes.values():
        by_arity[meta["arity"]] = by_arity.get(meta["arity"], 0) + 1
    return {
        "exemplars": len(exemplars),
        "distinct_shapes": len(shapes),
        "by_arity": {a: by_arity[a] for a in sorted(by_arity)},
        "top_idioms": [
            {"shape": shape, "count": meta["count"], "arity": meta["arity"],
             "example": meta["example"]}
            for shape, meta in ranked[:max(0, top)]
        ],
    }


def render_native_mind_markdown(summary: dict) -> str:
    """Render :func:`summarize_native_mind`'s summary as plain markdown for the CLI.

    An empty library renders an honest "learned nothing yet" line (no functions in
    the project match the self-contained single/guarded-return shape), never a
    blank or a crash."""
    lines = ["# Native intelligence — learned from this project", ""]
    exemplars = summary.get("exemplars", 0)
    if not exemplars:
        lines.append(
            "Apex has learned **no** transplantable bodies from this project yet "
            "(no function matches the self-contained single/guarded-return shape).")
        return "\n".join(lines) + "\n"
    shapes = summary.get("distinct_shapes", 0)
    lines.append(
        f"Apex mined **{exemplars}** reusable return-bodies from your code, "
        f"forming **{shapes}** distinct idioms. With `APEX_NATIVE_MIND=1`, "
        "`apex develop --objective implement-stub --apply` can finish a stub by "
        "transplanting one of these — verified by the same never-fake-green gate.")
    by_arity = summary.get("by_arity") or {}
    if by_arity:
        parts = ", ".join(f"{n} at arity {a}" for a, n in by_arity.items())
        lines += ["", f"**Idioms by parameter count:** {parts}."]
    top = summary.get("top_idioms") or []
    if top:
        lines += ["", "## Dominant idioms (most-used shapes)", ""]
        for row in top:
            lines.append(
                f"- `{row['shape']}` — **{row['count']}**× "
                f"(arity {row['arity']}, e.g. `{row['example']}`)")
    return "\n".join(lines) + "\n"
