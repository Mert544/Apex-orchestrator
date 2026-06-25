"""`apex owner-report` — a plain-language trust summary for a NON-TECHNICAL owner.

This is the founder's owner-oversight "Layer-1": the single page a non-coder owner
reads to decide whether to trust the free agent that is touching their real project.
It is a thin **VIEW** that COMPOSES the existing deterministic audits — it is NOT a
new analysis engine and NOT a new develop objective (so it carries no Facet-parity
obligation and does not change ``available_objectives()``).

It reuses, verbatim, the three deterministic checks Apex already ships and renders
through ``apex self-audit`` / ``apex grade``:

* the North Star denetçi (:func:`app.engine.north_star_audit.north_star_report`) —
  the PASS/DRIFT verdict, the ``drift`` bool, and the CONCRETE/TIDY/SAFETY buckets
  (so "is Apex doing real development work or drifting into busywork?");
* the objective-soundness denetçi
  (:func:`app.engine.soundness_audit.soundness_report`) — the PASS/FAIL verdict, the
  N/N declared-proof-strategy count, the single-gated-writer (A1) assertion, and the
  ``scope_verify`` allow-list (A3) (so "does every ability carry an honest proof, and
  can anything fake a passing test?"). Resolved against Apex's OWN tree via
  :func:`app.engine.soundness_audit.repo_root`, exactly as the ``--soundness`` CLI does;
* the health grade (:func:`app.engine.health_score.grade`) — the letter + score.

Every technical verdict is folded into ONE owner-readable English sentence by
:func:`render_owner_report_markdown`. Like every audit it composes, this view is
**deterministic, zero-token, offline, and CLOCK-FREE**: no ``datetime.now``, no
timestamp, no randomness, no network, no LLM — the same repo state renders the same
bytes. It re-implements NO analysis; it only translates.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "owner_report",
    "render_owner_report_markdown",
]


# --- Deterministic plain-language helpers (pure functions of the manifest) ----
#
# The owner never sees an objective slug. These two tables turn the CONCRETE
# manifest into the two owner-facing facts a buyer asks: "what LANGUAGES can it work
# in?" and "name a few things it can BUILD for me." Both are pure functions of the
# objective NAMES (no clock, no I/O), so the view stays as deterministic as the
# audits it composes.

# A CONCRETE objective whose name starts with one of these tokens lands JavaScript /
# TypeScript code (the ESM/JSDoc objectives); every other CONCRETE objective lands
# Python. Prefix-matching the slug keeps this a stable, reviewable rule rather than a
# second hand-maintained list that could drift from the manifest.
_JS_NAME_PREFIXES: tuple[str, ...] = ("js-", "document-export-jsdoc")

# A FEW CONCRETE objectives rendered as the plain phrase an owner understands. Only
# names present in the live CONCRETE bucket are shown (sorted, then capped), so this
# never claims an ability Apex does not actually carry, and a removed objective drops
# out automatically. Names with no entry here simply do not appear among the examples.
_ABILITY_PHRASES: dict[str, str] = {
    "implement-stub": "filling in unfinished functions",
    "tdd-implement": "filling in unfinished functions from their tests",
    "strengthen-tests": "writing missing tests",
    "cover-gaps": "writing tests for untested code",
    "wire-exports": "wiring up a package's public exports",
    "infer-type-hints": "adding type hints",
    "document-signature": "adding documentation to functions",
    "generate-usage-doc": "writing a usage guide",
    "js-tdd-implement": "filling in unfinished JavaScript from its tests",
    "js-wire-exports": "wiring up JavaScript/TypeScript exports",
}

_MAX_EXAMPLE_ABILITIES = 4


def _languages_for(concrete_names) -> list[str]:
    """The owner-facing language list Apex can land CONCRETE code in.

    Pure function of the CONCRETE objective NAMES: any JS/TS-shaped slug (see
    :data:`_JS_NAME_PREFIXES`) contributes "JavaScript/TypeScript"; every other
    CONCRETE objective contributes "Python". Returned in a STABLE display order
    (Python first), de-duplicated, and only for languages actually represented — so
    a Python-only manifest reads "Python" alone."""
    names = list(concrete_names)
    has_js = any(
        n.startswith(prefix) for n in names for prefix in _JS_NAME_PREFIXES
    )
    has_python = any(
        not any(n.startswith(prefix) for prefix in _JS_NAME_PREFIXES) for n in names
    )
    languages: list[str] = []
    if has_python:
        languages.append("Python")
    if has_js:
        languages.append("JavaScript/TypeScript")
    return languages


def _example_abilities(concrete_names) -> list[str]:
    """A few plain-language example ability names from the live CONCRETE manifest.

    Intersects the live CONCRETE names with :data:`_ABILITY_PHRASES`, sorts for
    determinism, caps at :data:`_MAX_EXAMPLE_ABILITIES`, and returns the phrases. Only
    abilities Apex actually carries are shown, so the owner is never promised a
    capability that is not registered."""
    present = sorted(n for n in concrete_names if n in _ABILITY_PHRASES)
    return [_ABILITY_PHRASES[n] for n in present[:_MAX_EXAMPLE_ABILITIES]]


# --- The composed report ------------------------------------------------------

def owner_report(project_root: str | Path) -> dict:
    """Compose the EXISTING deterministic audits into one owner-facing dict.

    Reuses (never re-implements) :func:`north_star_report`, :func:`soundness_report`,
    and :func:`grade`. ``project_root`` feeds the North Star commit-window/drift read;
    the soundness check resolves Apex's OWN tree via
    :func:`app.engine.soundness_audit.repo_root` (the same subject the ``--soundness``
    CLI audits), and the grade is taken on ``project_root``.

    Returns a structured dict with stable keys:

    * ``trustworthy`` (bool) — True IFF North Star PASS **and** soundness PASS **and**
      no drift. The single headline an owner reads.
    * ``north_star`` — ``{verdict, drift, concrete_count, total_objectives, ratio}``.
    * ``soundness`` — ``{verdict, strategies "N/N", single_writer, scope_verify_ok}``.
    * ``grade`` — ``{letter, score}``.
    * ``capabilities`` — ``{concrete_count, languages, abilities}`` (a few example
      plain-language ability names).

    Pure, deterministic, zero-token, offline: no clock, no randomness, no LLM."""
    from app.engine.health_score import grade
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(str(project_root))
    sound = soundness_report(str(repo_root()))
    health = grade(str(project_root))

    concrete_count = ns["bucket_counts"]["CONCRETE"]
    concrete_names = ns["buckets"]["CONCRETE"]
    strategies = f"{len(sound['strategy_table'])}/{sound['total_objectives']}"
    trustworthy = (
        ns["verdict"] == "PASS"
        and sound["verdict"] == "PASS"
        and not ns["drift"]
    )
    return {
        "trustworthy": trustworthy,
        "north_star": {
            "verdict": ns["verdict"],
            "drift": ns["drift"],
            "concrete_count": concrete_count,
            "total_objectives": ns["total_objectives"],
            "ratio": ns["concrete_ratio"],
        },
        "soundness": {
            "verdict": sound["verdict"],
            "strategies": strategies,
            "single_writer": sound["single_writer_ok"],
            "scope_verify_ok": sound["scope_verify_ok"],
        },
        "grade": {"letter": health.letter, "score": health.score},
        "capabilities": {
            "concrete_count": concrete_count,
            "languages": _languages_for(concrete_names),
            "abilities": _example_abilities(concrete_names),
        },
    }


# --- Plain-language rendering -------------------------------------------------
#
# Each technical verdict becomes ONE sentence a non-coder owner understands. No
# slugs, no ratios-as-percentages, no jargon beyond a single bracketed
# evidence-stamp ([PASS, drift: no]) that lets a technical reader cross-check the
# claim against the underlying audit. CLOCK-FREE and deterministic by construction.

def _trust_headline(report: dict) -> list[str]:
    """The YES / NO headline line(s): the one answer the owner came for.

    On NOT-trustworthy it NAMES the reason (off-mission drift, a failed honesty
    check, or a failed soundness verdict) so the owner sees a clear NO + why."""
    if report["trustworthy"]:
        return ["# Is Apex's work trustworthy?  ->  YES", ""]
    reasons: list[str] = []
    ns = report["north_star"]
    sound = report["soundness"]
    if ns["drift"]:
        reasons.append("it has drifted away from real development work")
    if ns["verdict"] != "PASS":
        reasons.append("its on-mission check did not pass")
    if sound["verdict"] != "PASS":
        reasons.append("its honest-verification check did not pass")
    if not reasons:
        reasons.append("one of its trust checks did not pass")
    return [
        "# Is Apex's work trustworthy?  ->  NO",
        "",
        f"The reason: {'; '.join(reasons)}.",
        "",
    ]


def _mission_line(report: dict) -> str:
    """One sentence on the North Star / drift verdict, in owner language."""
    ns = report["north_star"]
    drift_word = "no" if not ns["drift"] else "YES"
    if ns["verdict"] == "PASS" and not ns["drift"]:
        body = ("Apex is doing real development work that lands working code — "
                "not drifting into busywork.")
    else:
        body = ("Apex has drifted toward busywork instead of landing real working "
                "code — this needs attention.")
    return f"- On-mission: {body}  [{ns['verdict']}, drift: {drift_word}]"


def _honesty_line(report: dict) -> str:
    """One sentence on the soundness verdict + N/N declared-proof-strategy count."""
    sound = report["soundness"]
    n_total = sound["strategies"].split("/")[-1]
    if sound["verdict"] == "PASS":
        body = (f"every one of Apex's {n_total} abilities carries a declared "
                "proof-strategy, and nothing is allowed to fake a passing test.")
    else:
        body = ("not every ability could prove how it stays safe — Apex's honesty "
                "check did not pass.")
    return f"- Honest verification: {body}  [{sound['verdict']}, {sound['strategies']}]"


def _quality_line(report: dict) -> str:
    """One sentence on the health grade (letter + score)."""
    g = report["grade"]
    return f"- Quality: grade {g['letter']} ({g['score']}/100)."


def _capabilities_line(report: dict) -> str:
    """One sentence on what Apex can BUILD: count, languages, and example abilities."""
    cap = report["capabilities"]
    languages = " and ".join(cap["languages"]) if cap["languages"] else "your code"
    abilities = cap["abilities"]
    examples = f" ({', '.join(abilities)}, ...)" if abilities else ""
    return (
        f"- What Apex can build for you: {cap['concrete_count']} kinds of verified "
        f"working-code contributions across {languages}{examples}."
    )


def render_owner_report_markdown(report: dict) -> str:
    """Render :func:`owner_report` as PLAIN, non-technical English for an owner.

    Each technical verdict becomes ONE owner-readable sentence; a single bracketed
    evidence-stamp per line lets a technical reader cross-check it. CLOCK-FREE (no
    ``datetime.now``, no timestamp, no "UTC") and deterministic — the same report
    dict renders byte-identical text every time."""
    lines = _trust_headline(report)
    lines.append(_mission_line(report))
    lines.append(_honesty_line(report))
    lines.append(_quality_line(report))
    lines.append(_capabilities_line(report))
    lines.append(
        "- The promise: every change is proven by your project's own tests or "
        "automatically undone — Apex never leaves your project worse."
    )
    lines.append("")
    return "\n".join(lines)
