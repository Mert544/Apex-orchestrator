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
  ``scope_verify`` allow-list (A3) (so "does every ABILITY Apex ships carry an honest
  proof, and can anything fake a passing test?"). This is necessarily resolved
  against Apex's OWN tree via :func:`app.engine.soundness_audit.repo_root` — it is a
  structural audit of Apex's ``app/`` package layout (the objective registry, the
  single gated-writer call-site, the adversarial corpus fixtures), not something that
  can be re-pointed at an arbitrary ``--target`` project. Rendered under the EXPLICIT
  label "Apex tool soundness (self-audit)" (see :func:`_honesty_line`) so it can never
  be misread as a claim about the buyer's OWN project — the load-bearing fix for a
  target-confusion an adversarial read of the earlier "Honest verification" wording
  surfaced;
* the health grade (:func:`app.engine.health_score.grade`) — the letter + score, taken
  on ``project_root`` (the buyer's own ``--target``);
* the buyer's OWN proof-of-fix track record
  (:func:`app.engine.proof_history.load_proof_history` +
  :func:`app.engine.proof_history.summarise_fix_track_record`), read from
  ``<project_root>/.apex/`` — so the closing "promise" sentence is evidence-derived
  ("Last N runs: ...") whenever this project has a history, instead of a static claim.
  When there is no history yet the closing line falls back to the original, generic,
  BYTE-IDENTICAL sentence (opt-in by evidence, neutral default).

Every technical verdict is folded into ONE owner-readable English sentence by
:func:`render_owner_report_markdown`. Like every audit it composes, this view is
**deterministic, zero-token, offline, and CLOCK-FREE**: no ``datetime.now``, no
timestamp, no randomness, no network, no LLM — the same repo state renders the same
bytes (the proof-history read is I/O over already-written JSON, not a clock). It
re-implements NO analysis; it only translates.
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
# TypeScript code (the ESM/JSDoc objectives); a ``java-`` slug lands Java; every other
# CONCRETE objective lands Python. Prefix-matching the slug keeps this a stable,
# reviewable rule rather than a second hand-maintained list that could drift from the
# manifest.
_JS_NAME_PREFIXES: tuple[str, ...] = ("js-", "document-export-jsdoc")

# A CONCRETE objective whose name starts with ``java-`` lands Java code (the JDK
# Compiler-Tree-API objectives). Kept SEPARATE from ``_JS_NAME_PREFIXES`` so a
# ``java-`` slug is neither mistaken for JS nor (the load-bearing fix) silently
# counted as Python by the "everything else is Python" rule below.
_JAVA_NAME_PREFIXES: tuple[str, ...] = ("java-",)

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
    "java-finalize-field": "marking Java fields final where they never change",
    "java-final-local": "marking Java local variables final where they never change",
    "java-document-param": "documenting Java method parameters",
    "java-document-returns": "documenting Java method return values",
}

_MAX_EXAMPLE_ABILITIES = 4


def _languages_for(concrete_names) -> list[str]:
    """The owner-facing language list Apex can land CONCRETE code in.

    Pure function of the CONCRETE objective NAMES: any JS/TS-shaped slug (see
    :data:`_JS_NAME_PREFIXES`) contributes "JavaScript/TypeScript"; a ``java-`` slug
    (see :data:`_JAVA_NAME_PREFIXES`) contributes "Java"; every OTHER CONCRETE
    objective (neither JS nor Java) contributes "Python". Returned in a STABLE display
    order (Python, then Java, then JavaScript/TypeScript), de-duplicated, and only for
    languages actually represented — so a Python-only manifest reads "Python" alone."""
    names = list(concrete_names)
    has_js = any(n.startswith(p) for n in names for p in _JS_NAME_PREFIXES)
    has_java = any(n.startswith(p) for n in names for p in _JAVA_NAME_PREFIXES)
    has_python = any(
        not any(n.startswith(p) for p in _JS_NAME_PREFIXES + _JAVA_NAME_PREFIXES)
        for n in names
    )
    languages: list[str] = []
    if has_python:
        languages.append("Python")
    if has_java:
        languages.append("Java")
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


def _track_record_for(project_root: str | Path) -> dict:
    """This project's OWN proof-of-fix track record, as an owner-facing dict.

    Reads ``<project_root>/.apex/`` via :func:`load_proof_history` and reduces it
    with :func:`summarise_fix_track_record` (both re-used verbatim — no new
    aggregation logic). Returns a stable-key dict:

    * ``has_history`` (bool) — False when this project has never run a proof-carrying
      apply yet (a fresh checkout, or ``.apex`` absent/empty); the caller falls back
      to the original generic promise sentence in that case.
    * ``runs`` — the number of proof records read (``summary["proofs"]``).
    * ``applied`` / ``rolled_back`` / ``blocked`` — the flat outcome totals across
      every recorded fix (``summary["totals"]``).

    Pure and deterministic: same ``.apex`` contents -> same dict; no clock, no
    randomness, no network. Never raises — an unreadable/absent ``.apex`` yields
    ``has_history: False`` (the neutral, opt-in-by-evidence default)."""
    from app.engine.proof_history import load_proof_history, summarise_fix_track_record

    history = load_proof_history(project_root)
    summary = summarise_fix_track_record(history)
    totals = summary["totals"]
    return {
        "has_history": summary["fixes"] > 0,
        "runs": summary["proofs"],
        "applied": totals["applied"],
        "rolled_back": totals["rolled_back"],
        "blocked": totals["blocked"],
    }


# --- The composed report ------------------------------------------------------

def owner_report(project_root: str | Path) -> dict:
    """Compose the EXISTING deterministic audits into one owner-facing dict.

    Reuses (never re-implements) :func:`north_star_report`, :func:`soundness_report`,
    :func:`grade`, :func:`load_proof_history`, and :func:`summarise_fix_track_record`.
    ``project_root`` feeds the North Star commit-window/drift read, the grade, AND the
    proof-history track record — all three are about the buyer's OWN ``--target``
    project. The soundness check is the one exception: it resolves Apex's OWN tree via
    :func:`app.engine.soundness_audit.repo_root` (the same subject the ``--soundness``
    CLI audits) because it is a structural audit of Apex's ``app/`` package layout
    (objective registry, single gated-writer, adversarial corpus) that cannot be
    re-pointed at an arbitrary project — see :func:`_honesty_line` for the explicit
    "Apex tool soundness (self-audit)" label this renders under, so it is never
    mistaken for a claim about the buyer's project.

    Returns a structured dict with stable keys:

    * ``trustworthy`` (bool) — True IFF North Star PASS **and** soundness PASS **and**
      no drift. The single headline an owner reads.
    * ``north_star`` — ``{verdict, drift, concrete_count, total_objectives, ratio}``.
    * ``soundness`` — ``{verdict, strategies "N/N", single_writer, scope_verify_ok}``
      (Apex tool self-audit — see above).
    * ``grade`` — ``{letter, score}`` (the buyer's OWN ``project_root``).
    * ``capabilities`` — ``{concrete_count, languages, abilities}`` (a few example
      plain-language ability names).
    * ``track_record`` — ``{has_history, runs, applied, rolled_back, blocked}``, the
      buyer's OWN ``.apex/`` proof-of-fix history (see :func:`_track_record_for`);
      ``has_history`` is False on a fresh project with no proof-carrying runs yet.

    Pure, deterministic, zero-token, offline: no clock, no randomness, no LLM (the
    proof-history read is file I/O over already-written JSON, not a clock)."""
    from app.engine.health_score import grade
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(str(project_root))
    sound = soundness_report(str(repo_root()))
    health = grade(str(project_root))
    track_record = _track_record_for(project_root)

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
        "track_record": track_record,
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
        reasons.append("Apex's own tool-soundness self-check did not pass")
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
    """One sentence on the soundness verdict + N/N declared-proof-strategy count.

    IMPORTANT FRAMING: this audits Apex the TOOL, not the owner's own project — the
    underlying check (:func:`app.engine.soundness_audit.soundness_report`) is a
    structural audit of Apex's OWN ``app/`` package layout (every ability Apex ships
    declares how it stays sound) and cannot be re-pointed at an arbitrary project. The
    label says "Apex tool soundness (self-audit)" explicitly, and the body speaks of
    "Apex's own abilities" rather than "your project", so a non-technical owner can
    never mistake this line for a claim about work done ON their project — that
    misread was the load-bearing bug this line fixes."""
    sound = report["soundness"]
    n_total = sound["strategies"].split("/")[-1]
    if sound["verdict"] == "PASS":
        body = (f"every one of Apex's {n_total} own abilities carries a declared "
                "proof-strategy, and nothing is allowed to fake a passing test.")
    else:
        body = ("not every one of Apex's own abilities could prove how it stays "
                "safe — Apex's self-check did not pass.")
    return (f"- Apex tool soundness (self-audit): {body}  "
            f"[{sound['verdict']}, {sound['strategies']}]")


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


# The ORIGINAL generic promise sentence — byte-identical to the pre-track-record
# text. Kept as a named constant so the neutral/no-evidence fallback in
# :func:`_promise_line` can never accidentally drift from it (both read the SAME
# string), and so a project with no ``.apex`` proof history yet renders exactly
# what it always has.
_GENERIC_PROMISE = (
    "- The promise: every change is proven by your project's own tests or "
    "automatically undone — Apex never leaves your project worse."
)


def _promise_line(report: dict) -> str:
    """The closing "promise" sentence — evidence-derived when a track record exists.

    With NO proof-of-fix history yet (a fresh project, or ``.apex`` absent/empty —
    ``track_record`` missing or ``has_history`` False), renders the original,
    static, BYTE-IDENTICAL generic sentence (:data:`_GENERIC_PROMISE`) — the neutral
    default an evidence-free project always saw. Once this project has recorded
    fixes, renders the REAL counts instead: how many proof-carrying runs, and how
    many of the fixes across them applied cleanly, were auto-rolled-back by the
    verify-or-revert gate, or were declined/blocked before ever touching the tree —
    so the "Apex never leaves your project worse" claim is backed by this project's
    own numbers rather than asserted in the abstract."""
    tr = report.get("track_record")
    if not tr or not tr.get("has_history"):
        return _GENERIC_PROMISE
    runs = tr["runs"]
    run_word = "run" if runs == 1 else "runs"
    return (
        f"- The promise, backed by evidence: last {runs} proof-carrying {run_word} "
        f"on your project — {tr['applied']} applied, {tr['rolled_back']} "
        f"auto-rolled-back, {tr['blocked']} declined before touching your code. "
        "Apex never leaves your project worse."
    )


def render_owner_report_markdown(report: dict) -> str:
    """Render :func:`owner_report` as PLAIN, non-technical English for an owner.

    Each technical verdict becomes ONE owner-readable sentence; a single bracketed
    evidence-stamp per line lets a technical reader cross-check it. CLOCK-FREE (no
    ``datetime.now``, no timestamp, no "UTC") and deterministic — the same report
    dict renders byte-identical text every time. The closing promise line is
    evidence-derived when ``report["track_record"]`` shows a real history (see
    :func:`_promise_line`); otherwise it is the original static sentence,
    byte-identical to every report rendered before that feature existed."""
    lines = _trust_headline(report)
    lines.append(_mission_line(report))
    lines.append(_honesty_line(report))
    lines.append(_quality_line(report))
    lines.append(_capabilities_line(report))
    lines.append(_promise_line(report))
    lines.append("")
    return "\n".join(lines)
