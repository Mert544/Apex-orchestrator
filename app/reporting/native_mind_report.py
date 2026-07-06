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

import os
from contextlib import contextmanager
from pathlib import Path

from app.engine.native_synth import adapt_expr_to_params, learn_return_exemplars
from app.execution.stub_synthesis import _native_mind_sources

__all__ = [
    "summarize_native_mind",
    "render_native_mind_markdown",
    "finishable_stubs",
    "render_finishable_stubs_markdown",
    "render_experience_markdown",
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


@contextmanager
def _lane(enabled: bool):
    """Force the ``APEX_NATIVE_MIND`` lane on/off for the duration, restoring the
    prior environment afterwards (even on error) — so a dry-run never leaks the
    toggle into the caller's process."""
    key = "APEX_NATIVE_MIND"
    prior = os.environ.get(key)
    os.environ[key] = "1" if enabled else "0"
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prior


def finishable_stubs(root: str | Path, limit: int = 200) -> list[dict]:
    """The project's OWN unfinished stubs the native intelligence could finish —
    a dry-run of the concrete capability, no writes.

    For every own module, each stub whose contract is pinned by tests is probed
    twice: once with the lane OFF (fixed templates only) and once ON (templates +
    project-learned bodies). A stub the ON pass can finish is reported, flagged
    ``native_only`` when the OFF pass could NOT — i.e. a body only the native
    intelligence supplies, learned from the project's own code. Every proposal is
    gate-checked in-process (``synthesize_expr_from_witnesses``), so a reported
    body genuinely satisfies the stub's pinned witnesses (never a fake-green).

    Deterministic (own modules and stubs in fixed order); bounded by ``limit`` so a
    huge repo cannot make the dry-run unbounded. Returns ``[{module, stub, params,
    body, native_only}]`` sorted by (module, stub)."""
    from app.engine.objective_compiler import _own_modules
    from app.execution.stub_synthesis import (
        find_stub_functions,
        pinned_test_files,
        synthesize_expr_from_witnesses,
    )

    root = Path(root)
    probes: list[tuple[str, object, list[str]]] = []
    # Sort modules before probing so the ``limit`` boundary keeps the SAME stubs
    # regardless of the source index's iteration order (determinism at the cap).
    for rel, src in sorted(_own_modules(root)):
        for stub in find_stub_functions(src):
            tests = pinned_test_files(root, rel, stub.name)
            if tests:
                probes.append((rel, stub, tests))
            if len(probes) >= limit:
                break
        if len(probes) >= limit:
            break

    def _synth(enabled: bool) -> dict[tuple[str, str], str | None]:
        out: dict[tuple[str, str], str | None] = {}
        with _lane(enabled):
            _native_mind_sources.cache_clear()
            for rel, stub, tests in probes:
                out[(rel, stub.name)] = synthesize_expr_from_witnesses(
                    root, tests, stub)
        _native_mind_sources.cache_clear()
        return out

    off = _synth(False)
    on = _synth(True)
    results = []
    for rel, stub, _tests in probes:
        body = on[(rel, stub.name)]
        if body is None:
            continue
        results.append({
            "module": rel, "stub": stub.name, "params": list(stub.params),
            "body": body, "native_only": off[(rel, stub.name)] is None,
        })
    return sorted(results, key=lambda r: (r["module"], r["stub"]))


def render_finishable_stubs_markdown(rows: list[dict]) -> str:
    """Render :func:`finishable_stubs` as markdown, foregrounding the NATIVE-ONLY
    wins (stubs no fixed template could finish) — the concrete "what Apex can do
    for you from your own code" surface."""
    native = [r for r in rows if r["native_only"]]
    lines = ["# Stubs the native intelligence can finish", ""]
    if not rows:
        lines.append(
            "No pinned, unfinished stub in this project is finishable right now "
            "(nothing to demonstrate — a fully-implemented or untested codebase).")
        return "\n".join(lines) + "\n"
    lines.append(
        f"Apex can finish **{len(rows)}** pinned stub(s) here; **{len(native)}** "
        "of them ONLY via a body learned from your own code (no fixed template "
        "fits). Run `APEX_NATIVE_MIND=1 apex develop --objective implement-stub "
        "--apply` to land them — each verified by the never-fake-green gate.")
    if native:
        lines += ["", "## Native-only (learned from your code)", ""]
        for r in native:
            params = ", ".join(r["params"])
            lines.append(
                f"- `{r['module']}` :: `{r['stub']}({params})` → `{r['body']}`")
    template = [r for r in rows if not r["native_only"]]
    if template:
        lines += ["", f"## Also finishable by a fixed template ({len(template)})", ""]
        for r in template:
            lines.append(f"- `{r['module']}` :: `{r['stub']}` → `{r['body']}`")
    return "\n".join(lines) + "\n"


def render_experience_markdown(reliability: dict[str, float]) -> str:
    """Render the native intelligence's learned EXPERIENCE — the idiom shapes it
    has actually landed here, ranked by recency-weighted, version-bounded score
    (:mod:`app.engine.native_proof_memory`). This is the "wisdom" view: not what
    the corpus contains, but what has PROVEN to finish real code on this project.
    An empty history renders an honest "no experience yet" line."""
    lines = ["# Native intelligence — proven experience", ""]
    if not reliability:
        lines.append(
            "Apex has landed no native-only bodies here yet, so it has no proven "
            "experience to rank by — the native lane still orders by corpus "
            "frequency until it earns some.")
        return "\n".join(lines) + "\n"
    ranked = sorted(reliability.items(), key=lambda kv: (-kv[1], kv[0]))
    lines.append(
        "Idiom shapes Apex has proven it can land here, most-reliable first "
        "(recency-weighted; a shape retired by a `set_baseline` architectural "
        "reset never appears):")
    lines.append("")
    for shape, score in ranked:
        lines.append(f"- `{shape}` — score **{score:g}**")
    return "\n".join(lines) + "\n"
