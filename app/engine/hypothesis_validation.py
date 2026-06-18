"""Self-validating discovery — a discovered pattern becomes a FALSIFIABLE claim.

``dream_discovery`` answers *what travels with what on this codebase?* — but a
discovery like "``src``>``dst`` association" is, underneath, a universally
quantified **hypothesis**: *every module that carries ``src`` also carries
``dst``*. That sentence is the kind science prizes: it can be wrong, and the
codebase itself decides. This module closes the loop — it turns each discovery
into a structured, falsifiable hypothesis and then VALIDATES it deterministically
against every module in the profile, returning a verdict that is either
**confirmed** (the rule held, with the count behind it) or **refuted** (here are
the concrete modules that break it).

The leap past plain discovery is *self-validation*: discovery proposes, this
module disposes. A discovery's own confidence is computed only over the modules
the pattern was mined from; re-deriving the antecedent/consequent and re-checking
against the FULL module population is an independent test that can disagree —
catching a pattern that looked strong on its support set but fails project-wide.

Three deterministic moves per hypothesis:

  - **antecedent / consequent** — re-extracted from the discovery's stable key
    (``assoc:src>dst`` -> if ``src`` then ``dst``; ``triple:a&b>c`` -> if ``a``
    and ``b`` then ``c``; ``clique:t1&t2&t3`` -> if any of the bundle then all),
    so the claim is grounded in the same key the journal already tracks and never
    in a magnitude that drifts;
  - **support / counter-examples** — counted over ALL modules: a module that
    satisfies the antecedent either confirms (also satisfies the consequent) or
    refutes (does not), with refuters listed as concrete evidence;
  - **verdict** — a fixed-threshold reading of confidence and support, so the same
    profile always yields the same confirmed/weak/refuted call.

Deterministic: sorted iteration, fixed thresholds, no time/random. Consumes
``discover_emergent`` only — ``dream_discovery``'s public surface is untouched.
"""

from __future__ import annotations

from typing import Any

from app.engine.dream_discovery import _module_tags, discover_emergent

# A hypothesis is CONFIRMED when it holds at this confidence on at least this
# many antecedent modules; REFUTED when confidence drops below the weak floor;
# anything between is WEAK (supported but with live counter-examples).
CONFIRM_CONFIDENCE = 0.90
WEAK_CONFIDENCE = 0.60
MIN_ANTECEDENT = 2        # below this the population is too thin to confirm
MAX_EVIDENCE = 5          # at most this many counter-example modules are listed


def _split_key(key: str) -> tuple[str, str]:
    """``prefix:body`` -> ``(prefix, body)``; a keyless string is all-body."""
    if ":" not in key:
        return "", key
    prefix, body = key.split(":", 1)
    return prefix, body


def _assoc_hypothesis(body: str) -> dict[str, Any] | None:
    """``src>dst`` -> *if a module carries ``src`` it also carries ``dst``*."""
    if ">" not in body:
        return None
    src, dst = body.split(">", 1)
    if not src or not dst:
        return None
    return {
        "kind": "association",
        "antecedent": [src],
        "consequent": [dst],
        "claim": f"every module carrying `{src}` also carries `{dst}`",
    }


def _triple_hypothesis(body: str) -> dict[str, Any] | None:
    """``a&b>c`` -> *if a module carries ``a`` and ``b`` it also carries ``c``*."""
    if ">" not in body:
        return None
    pair, c = body.split(">", 1)
    antecedent = [t for t in pair.split("&") if t]
    if len(antecedent) < 2 or not c:
        return None
    joined = "` and `".join(antecedent)
    return {
        "kind": "triple",
        "antecedent": antecedent,
        "consequent": [c],
        "claim": f"every module carrying `{joined}` also carries `{c}`",
    }


def _clique_hypothesis(body: str) -> dict[str, Any] | None:
    """``t1&t2&t3`` -> *a module carrying any bundle tag carries the whole bundle*.

    The antecedent is "carries at least one bundle tag" and the consequent is
    "carries all of them": a module that holds part of the fingerprint but not
    the rest is a counter-example to the bundle travelling as a unit.
    """
    members = [t for t in body.split("&") if t]
    if len(members) < 3:
        return None
    joined = "`, `".join(members)
    return {
        "kind": "clique",
        "antecedent": members,        # ANY member satisfies the antecedent
        "consequent": members,        # ALL members satisfy the consequent
        "claim": f"any module carrying one of `{joined}` carries them all",
        "antecedent_any": True,
    }


def discovery_to_hypothesis(discovery: Any) -> dict[str, Any] | None:
    """Turn one discovery (``Discovery`` or its ``to_dict``) into a falsifiable hypothesis.

    Returns ``{"claim", "antecedent", "consequent", "kind", ...}`` or ``None`` for
    a discovery whose key carries no directional rule (a bare confluence names a
    single broad module, not an *if/then*, so it has no antecedent to test).
    Accepts either a ``Discovery`` instance or its dict form; reads only ``key``.
    """
    key = discovery.get("key") if isinstance(discovery, dict) else getattr(discovery, "key", "")
    prefix, body = _split_key(str(key or ""))
    builders = {
        "assoc": _assoc_hypothesis,
        "triple": _triple_hypothesis,
        "clique": _clique_hypothesis,
    }
    builder = builders.get(prefix)
    if builder is None:
        return None
    hypothesis = builder(body)
    if hypothesis is not None:
        hypothesis["key"] = str(key)
    return hypothesis


def _antecedent_holds(tags: set[str], antecedent: list[str], any_mode: bool) -> bool:
    """Does this module's tag-set satisfy the antecedent (ALL, or ANY for cliques)?"""
    if any_mode:
        return any(t in tags for t in antecedent)
    return all(t in tags for t in antecedent)


def _consequent_holds(tags: set[str], consequent: list[str]) -> bool:
    """The consequent always requires the module to carry ALL consequent tags."""
    return all(t in tags for t in consequent)


def _verdict(confidence: float, antecedent_n: int) -> str:
    """Fixed-threshold reading: confirmed / weak / refuted (never time/random)."""
    if antecedent_n < MIN_ANTECEDENT or confidence < WEAK_CONFIDENCE:
        return "refuted"
    if confidence >= CONFIRM_CONFIDENCE:
        return "confirmed"
    return "weak"


def validate_hypothesis(hypothesis: dict[str, Any], profile: Any) -> dict[str, Any]:
    """Deterministically test a hypothesis against EVERY module in the profile.

    Counts antecedent modules, splits them into supporters (antecedent ∧
    consequent) and counter-examples (antecedent ∧ ¬consequent), derives support
    (antecedent population) and confidence (supporters / antecedent, in [0,1]),
    and reads a fixed-threshold verdict. Up to ``MAX_EVIDENCE`` counter-example
    modules are listed, sorted, as concrete evidence. A hypothesis no module's
    antecedent matches is ``refuted`` with confidence ``0.0`` (vacuous, untestable
    here), never an exception.
    """
    antecedent = list(hypothesis.get("antecedent", []))
    consequent = list(hypothesis.get("consequent", []))
    any_mode = bool(hypothesis.get("antecedent_any", False))
    tags = _module_tags(profile)

    supporters: list[str] = []
    counter: list[str] = []
    for module in sorted(tags):
        ts = tags[module]
        if not _antecedent_holds(ts, antecedent, any_mode):
            continue
        if _consequent_holds(ts, consequent):
            supporters.append(module)
        else:
            counter.append(module)

    antecedent_n = len(supporters) + len(counter)
    confidence = len(supporters) / antecedent_n if antecedent_n else 0.0
    return {
        "key": hypothesis.get("key", ""),
        "kind": hypothesis.get("kind", ""),
        "claim": hypothesis.get("claim", ""),
        "support": len(supporters),
        "antecedent_modules": antecedent_n,
        "counter_examples": len(counter),
        "confidence": round(confidence, 3),
        "verdict": _verdict(confidence, antecedent_n),
        "evidence": counter[:MAX_EVIDENCE],
    }


def _rank_key(result: dict[str, Any]) -> tuple[int, float, int, str]:
    """Rank: confirmed first, then by confidence, then by support, then stable key."""
    order = {"confirmed": 0, "weak": 1, "refuted": 2}
    return (
        order.get(result["verdict"], 3),
        -float(result["confidence"]),
        -int(result["support"]),
        str(result["key"]),
    )


def validate_discoveries(profile: Any, top: int = 5) -> list[dict[str, Any]]:
    """Discover -> hypothesise -> validate, returning ranked, evidenced verdicts.

    Runs ``discover_emergent`` once, turns each directional discovery into a
    hypothesis (confluences carry no if/then and are skipped), validates each
    against the full module population, and returns the ``top`` strongest results
    ranked confirmed-before-weak-before-refuted. Empty or pattern-free profile ->
    ``[]`` (never raises); ``top <= 0`` -> ``[]``.
    """
    if top <= 0:
        return []
    results: list[dict[str, Any]] = []
    for discovery in discover_emergent(profile):
        hypothesis = discovery_to_hypothesis(discovery)
        if hypothesis is None:
            continue
        results.append(validate_hypothesis(hypothesis, profile))
    results.sort(key=_rank_key)
    return results[:top]
