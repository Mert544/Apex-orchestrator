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

Two honesty guards keep a "validated discovery" from over-claiming:

  - **structural tautologies are not findings.** Some tags are SUPERSETS of others
    *by construction* — ``critical-untested`` is, by how ``project_profile`` /
    ``test_linker`` build the lists, a SUBSET of ``untested`` (a critical-untested
    module is exactly "an untested module that is also a dependency hub", see
    ``TestLinker.analyze``: ``critical_untested = [m for m in critical if m in
    untested]``). So "every ``critical-untested`` module is also ``untested``" is
    TRUE BY DEFINITION, not a law the codebase decided — a confirmed-at-1.0 reading
    of it would be dressing up an identity as empirical science. Such hypotheses
    (antecedent ⊆ consequent is STRUCTURAL) are SUPPRESSED entirely, never emitted.
  - **low support is a candidate, not a confirmation.** A clean directional rule
    that holds on only a handful of modules is a *candidate pattern* worth a look,
    not a project-wide law; it is labelled ``candidate`` (low support) rather than
    ``confirmed`` until enough modules stand behind it.

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
# A directional rule may HOLD on a thin population, but a single-digit handful of
# modules is a candidate to watch, not a project-wide law we stamp "confirmed".
# Below MIN_ANTECEDENT the population is too thin to read at all (refuted); a
# population that clears MIN_ANTECEDENT but stays under CONFIRM_ANTECEDENT can only
# rise to "candidate" — never "confirmed", no matter how clean the confidence.
MIN_ANTECEDENT = 2        # below this the population is too thin to read
CONFIRM_ANTECEDENT = 5    # …and below THIS, "confirmed" is downgraded to "candidate"
MAX_EVIDENCE = 5          # at most this many counter-example modules are listed

# STRUCTURAL superset map: consequent tag -> the set of tags that are its SUBSET
# *by construction* (every module carrying the subset tag carries the superset tag
# because of how ``project_profile`` builds the lists, NOT because of any property
# of this codebase). A hypothesis whose ``antecedent ⊆ consequent`` is structural is
# a definitional tautology, not a discovery, and is suppressed.
#
#   - ``critical-untested`` ⊆ ``untested`` — ``TestLinker.analyze`` builds
#     ``critical_untested = [m for m in critical_modules if m in untested]``: a
#     critical-untested module is by definition an untested one.
#   - ``hub-untested`` / ``impure-untested`` ⊆ ``untested`` — same "X-AND-untested"
#     construction in ``project_profile`` (``hub_untested_modules`` /
#     ``impure_untested_functions`` are the untested subset of hubs / impure fns).
#     Listed for completeness/future-proofing; these tags are not currently emitted
#     into the discovery tag-set, so they never reach a hypothesis today, but if a
#     row is ever added to ``_module_tags`` for them the guard already covers it.
_STRUCTURAL_SUPERSETS: dict[str, frozenset[str]] = {
    "untested": frozenset({"critical-untested", "hub-untested", "impure-untested"}),
}


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


def _is_structural_tautology(hypothesis: dict[str, Any]) -> bool:
    """True if ``antecedent ⊆ consequent`` holds BY CONSTRUCTION (a tautology).

    A hypothesis whose every consequent tag is a known structural superset of
    every antecedent tag asserts a definitional identity, not a property this
    codebase happens to have — confirming it would over-claim. Clique hypotheses
    (``antecedent_any``) are bidirectional bundle claims, never a one-directional
    subset, so they are never treated as structural tautologies.
    """
    if hypothesis.get("antecedent_any"):
        return False
    antecedent = hypothesis.get("antecedent", [])
    consequent = hypothesis.get("consequent", [])
    if not antecedent or not consequent:
        return False
    # Every consequent tag must be a by-construction superset of every antecedent
    # tag for the WHOLE implication to be a tautology.
    for cons in consequent:
        subsets = _STRUCTURAL_SUPERSETS.get(cons, frozenset())
        if not all(ant in subsets for ant in antecedent):
            return False
    return True


def _verdict(confidence: float, antecedent_n: int) -> str:
    """Fixed-threshold reading: confirmed / candidate / weak / refuted (no time/random).

    ``candidate`` is a clean rule (confidence at the confirm bar) that simply does
    not yet have enough modules behind it (``< CONFIRM_ANTECEDENT``) to be called a
    project-wide law — an honest "low support" label, not a confirmation.
    """
    if antecedent_n < MIN_ANTECEDENT or confidence < WEAK_CONFIDENCE:
        return "refuted"
    if confidence >= CONFIRM_CONFIDENCE:
        return "confirmed" if antecedent_n >= CONFIRM_ANTECEDENT else "candidate"
    return "weak"


def validate_hypothesis(hypothesis: dict[str, Any], profile: Any) -> dict[str, Any]:
    """Deterministically test a hypothesis against EVERY module in the profile.

    Counts antecedent modules, splits them into supporters (antecedent ∧
    consequent) and counter-examples (antecedent ∧ ¬consequent), derives support
    (antecedent population) and confidence (supporters / antecedent, in [0,1]),
    and reads a fixed-threshold verdict. Up to ``MAX_EVIDENCE`` counter-example
    modules are listed, sorted, as concrete evidence. A hypothesis no module's
    antecedent matches is ``refuted`` with confidence ``0.0`` (vacuous, untestable
    here), never an exception. A STRUCTURAL tautology (``antecedent ⊆ consequent``
    by construction) is reported with verdict ``tautology`` and never "confirmed",
    so even a direct caller (not just ``validate_discoveries``, which drops it)
    cannot mistake a definitional identity for a validated discovery.
    """
    antecedent = list(hypothesis.get("antecedent", []))
    consequent = list(hypothesis.get("consequent", []))
    any_mode = bool(hypothesis.get("antecedent_any", False))
    tautology = _is_structural_tautology(hypothesis)
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
        "verdict": "tautology" if tautology else _verdict(confidence, antecedent_n),
        "tautology": tautology,
        "evidence": counter[:MAX_EVIDENCE],
    }


def _rank_key(result: dict[str, Any]) -> tuple[int, float, int, str]:
    """Rank: confirmed first, then by confidence, then by support, then stable key.

    A ``candidate`` (clean but low-support) ranks below ``confirmed`` and above the
    counter-exampled ``weak``: it is a clean rule, just thinly supported.
    """
    order = {"confirmed": 0, "candidate": 1, "weak": 2, "refuted": 3}
    return (
        order.get(result["verdict"], 4),
        -float(result["confidence"]),
        -int(result["support"]),
        str(result["key"]),
    )


def validate_discoveries(profile: Any, top: int = 5) -> list[dict[str, Any]]:
    """Discover -> hypothesise -> validate, returning ranked, evidenced verdicts.

    Runs ``discover_emergent`` once, turns each directional discovery into a
    hypothesis (confluences carry no if/then and are skipped), validates each
    against the full module population, and returns the ``top`` strongest results
    ranked confirmed-before-candidate-before-weak-before-refuted. STRUCTURAL
    tautologies (``antecedent ⊆ consequent`` by construction, e.g.
    ``critical-untested ⇒ untested``) are dropped entirely — they are definitional,
    not discoveries. Empty or pattern-free profile -> ``[]`` (never raises);
    ``top <= 0`` -> ``[]``.
    """
    if top <= 0:
        return []
    results: list[dict[str, Any]] = []
    for discovery in discover_emergent(profile):
        hypothesis = discovery_to_hypothesis(discovery)
        if hypothesis is None:
            continue
        if _is_structural_tautology(hypothesis):
            continue
        results.append(validate_hypothesis(hypothesis, profile))
    results.sort(key=_rank_key)
    return results[:top]
