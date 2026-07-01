"""Dreaming — the scheduled curation pass over Apex's own memory stores.

Inspired by Claude Managed Agents' *dreaming* (a scheduled process that
reviews agent sessions and memory stores, extracts patterns, and curates
memories so agents improve over time) — rebuilt the Apex way: deterministic,
offline, zero tokens. One pass reviews every artifact the organism left
behind and does three things:

  1. **extract patterns** — what lands and what rolls back (outcome memory),
     which tests keep failing (proof-of-fix), which briefs actually
     progressed (evidence burndown), where the project is alive and what is
     accelerating (signal trends);
  2. **curate** — archive fully-resolved briefs, trim the outcome memory to
     its highest-signal keys so it never grows into noise;
  3. **digest** — write one page (``.apex/dream-digest.md``) the next
     session, human or agent, can absorb in thirty seconds.

Same stores in, same dream out: the pass is reproducible like everything
else in the organism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

# Outcome-memory tables are trimmed to this many keys (by evidence volume):
# memory should stay high-signal, not become a landfill of one-off keys.
MEMORY_KEY_CAP = 20


@dataclass
class DreamReport:
    patterns: list[str] = field(default_factory=list)     # what the dream noticed
    discoveries: list[str] = field(default_factory=list)  # open-ended associations
    new_since: list[str] = field(default_factory=list)    # surfaced this dream, not last
    resolved_since: list[str] = field(default_factory=list)  # in last dream, gone now
    promoted: list[str] = field(default_factory=list)     # confirmed laws → waking ideas
    forecast: list[str] = field(default_factory=list)     # near-miss: one more dream graduates
    curated: list[str] = field(default_factory=list)      # what it tidied (--curate)
    proposed: list[str] = field(default_factory=list)     # what it WOULD tidy (default)
    digest_path: str = ""
    # Structured discoveries (key/confidence) kept for journaling + promotion;
    # not part of the human dict but exposed for callers that need the scores.
    discovery_objs: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"patterns": self.patterns, "discoveries": self.discoveries,
                "new_since": self.new_since, "resolved_since": self.resolved_since,
                "promoted": self.promoted, "forecast": self.forecast,
                "curated": self.curated, "proposed": self.proposed,
                "digest_path": self.digest_path}


def _review_outcome_memory(root: Path, report: DreamReport, curate: bool) -> None:
    from app.engine.idea_memory import IdeaMemory

    mem = IdeaMemory.load(root)
    info = mem.summary()
    # Prefer the evidence-aware ranking (Wilson lower bound) over the raw rate
    # when it's available: a lucky 1-of-1 (rate 100%) shouldn't headline over a
    # well-attested 9-of-10. Falls back to the raw rate so an older memory store
    # (no confidence keys) still reads — and the wording is identical, so a key
    # that tops both rankings keeps a byte-stable digest.
    reliable = info.get("most_confident") or info.get("most_reliable", [])
    for row in reliable[:2]:
        # "Most reliable" is relative — with few lenses a 0% one can top the
        # list, and telling the reader to "keep leading" with it is a lie.
        if row["success_rate"] >= 0.5:
            report.patterns.append(
                f"`{row['key']}` fixes land {int(row['success_rate'] * 100)}% of the time "
                f"({row['samples']} samples) — keep leading with them.")
    unreliable = info.get("least_confident") or info.get("least_reliable", [])
    for row in unreliable[:2]:
        if row["success_rate"] < 0.5:
            report.patterns.append(
                f"`{row['key']}` lands only {int(row['success_rate'] * 100)}% "
                f"({row['samples']} samples) — expect blocks/rollbacks there.")
    # Curate: trim each table to its highest-evidence keys.
    trimmed = 0
    for table in (mem.by_operator, mem.by_label):
        if len(table) > MEMORY_KEY_CAP:
            keep = sorted(table.items(), key=lambda kv: (-kv[1].total, kv[0]))[:MEMORY_KEY_CAP]
            trimmed += len(table) - len(keep)
            table.clear()
            table.update(keep)
    if trimmed:
        if curate:
            mem.save(root)
            report.curated.append(
                f"outcome memory trimmed: {trimmed} low-evidence key(s) dropped")
        else:
            report.proposed.append(
                f"trim outcome memory: {trimmed} low-evidence key(s) would drop")


def _review_briefs(root: Path, report: DreamReport, curate: bool) -> None:
    from app.engine.idea_brief import check_brief

    briefs_dir = root / ".apex" / "briefs"
    if not briefs_dir.exists():
        return
    archive = briefs_dir / "archive"
    for path in sorted(briefs_dir.glob("*.json")):
        branch = path.stem
        check = check_brief(root, branch)
        if check is None or check["measured_total"] == 0:
            continue
        done, total = len(check["resolved"]), check["measured_total"]
        if not check["open"]:
            report.patterns.append(
                f"brief `{branch}` fully resolved ({done}/{total} evidence gone).")
            if curate:
                archive.mkdir(parents=True, exist_ok=True)
                path.rename(archive / path.name)
                report.curated.append(f"brief `{branch}` → archive (work landed)")
            else:
                report.proposed.append(f"archive brief `{branch}` (work landed)")
        else:
            report.patterns.append(
                f"brief `{branch}` in progress: {done}/{total} measured item(s) resolved.")


def _tally_proof(proof: dict) -> tuple[dict[str, int], dict[str, int]]:
    """Count repeat failing tests and repeated block reasons across all fixes."""
    failing: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for fix in proof.get("fixes", []) or []:
        for test in (fix.get("verification") or {}).get("failing_tests", []) or []:
            failing[test] = failing.get(test, 0) + 1
        reason = fix.get("blocked_reason") or ""
        if reason:
            key = reason.split("—")[0].strip()[:80]
            reasons[key] = reasons.get(key, 0) + 1
    return failing, reasons


def _review_proof(root: Path, report: DreamReport) -> None:
    proof_path = root / ".apex" / "proof-of-fix.json"
    if not proof_path.exists():
        return
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    failing, reasons = _tally_proof(proof)
    for test, n in sorted(failing.items(), key=lambda kv: (-kv[1], kv[0]))[:2]:
        report.patterns.append(
            f"`{test}` failed verification {n}× in the last pass — it guards "
            "whatever keeps being touched; look there first.")
    for reason, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:2]:
        if n >= 2:
            report.patterns.append(f"{n} steps blocked for the same reason: {reason}.")


def _review_promises(root: Path, profile: Any, report: DreamReport,
                     persist: bool = True) -> None:
    """The promise ledger — doc-drift, stretched across time (an Apex original).

    Doc-drift says whether the docs lie TODAY; the ledger remembers, so each
    dream can say which promise was KEPT (a broken reference fixed since the
    last dream) and which was newly BROKEN. The ledger is the dream's own
    memory (like the journal), normally written every run; nothing user-owned
    is touched. With ``persist=False`` the ledger is READ but never written, so
    a read-only dream computes the kept/broken patterns without mutating it.
    """
    ledger_path = root / ".apex" / "promise-ledger.json"
    previous: list[dict] = []
    if ledger_path.exists():
        try:
            previous = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = []
    current = [{"doc": d["doc"], "reference": d["reference"]}
               for d in (profile.doc_drift or [])]
    prev_keys = {(p["doc"], p["reference"]) for p in previous}
    curr_keys = {(c["doc"], c["reference"]) for c in current}
    for doc, ref in sorted(prev_keys - curr_keys):
        report.patterns.append(
            f"🤝 promise kept: `{doc}` no longer points at the missing `{ref}` "
            "— the doc and the code agree again.")
    for doc, ref in sorted(curr_keys - prev_keys):
        report.patterns.append(
            f"💔 promise broken: `{doc}` now references `{ref}`, which doesn't "
            "exist — fix the doc or build the promise.")
    if not persist:
        return  # read-only pass: patterns are computed above; never write the ledger
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(json.dumps(current, indent=1), encoding="utf-8")
    except OSError:
        pass


def _review_pulse_signals(root: Path, profile: Any, report: DreamReport) -> None:
    """Emit the where-the-project-is-alive patterns: trends, churn, knowledge.

    High-fan-OUT god-modules are gated on availability (older profiles / repos
    with no god-module yield []), so the digest stays byte-identical when the
    signal is absent. The profile already orders these (-fan_out, module).
    """
    from app.engine.signal_trends import SignalTrends

    for trend in SignalTrends(root).accelerating(profile)[:2]:
        report.patterns.append(
            f"`{trend['module']}` is ACCELERATING: {trend['churn_before']}→"
            f"{trend['churn_now']} commits while its {'/'.join(trend['aging'])} "
            "risk ages — intervene while the trend is young.")
    hot = (profile.churn_hotspots or [None])[0]
    if hot:
        report.patterns.append(
            f"development energy concentrates in `{hot['module']}` "
            f"({hot['commits']} recent commits).")
    for kr in (profile.knowledge_risks or [])[:1]:
        report.patterns.append(
            f"`{kr['module']}` is {kr['share']}% single-author across "
            f"{kr['commits']} commits — a bus-factor seam.")
    for coord in (profile.coordinator_modules or [])[:1]:
        wires = ", ".join(f"`{m}`" for m in (coord.get("imports") or [])[:3])
        tail = f" wiring together {wires}" if wires else ""
        report.patterns.append(
            f"`{coord['module']}` coordinates {coord['fan_out']} internal "
            f"modules{tail} — a decoupling candidate: a change anywhere it "
            "connects can ripple back through it.")
    if profile.doc_drift:
        report.patterns.append(
            f"{len(profile.doc_drift)} documentation promise(s) point at files "
            "that don't exist — the docs drifted.")


def _review_discoveries(profile: Any, report: DreamReport) -> None:
    """Open-ended discovery: what travels with what on THIS codebase.

    No combination is named in advance — the data decides.
    """
    from app.engine.dream_discovery import discover_structured

    for d in discover_structured(profile):
        report.discoveries.append(d.text)
        report.discovery_objs.append(d.to_dict())


def _review_pulse(root: Path, report: DreamReport, persist: bool = True) -> None:
    """Where the project is alive — churn, trends, knowledge, promises."""
    from app.tools.project_profile import ProjectProfiler

    profile = ProjectProfiler(root).profile()
    _review_pulse_signals(root, profile, report)
    _review_promises(root, profile, report, persist)
    _review_discoveries(profile, report)


# A discovery graduates into a waking idea only when it is BOTH strong and
# repeatedly confirmed: high confidence AND seen in this many consecutive
# dreams. Persistence is the anti-oscillation guard — a one-off never seeds.
PROMOTE_STREAK = 3
PROMOTE_CONFIDENCE = 0.80
PROMOTIONS_REL = ".apex/dream-promotions.json"

# The PER-MODULE Tier-1 landable signals a below-confidence confluence is probed
# against to decide whether it carries a VERIFIED-LANDABLE move, in fixed
# descending-buyer-value order — the SAME signals (and the same honest, real-
# lander-grounded probes) the seeder's ``_landable_reroute`` consults, so a
# value-aware graduation promises exactly what ``apex develop`` could land on the
# module. Each pair is ``(synthesis-signal function name, develop objective)``;
# the first signal that claims the module wins. ``tdd-implement`` is excluded for
# the same reason the seeder excludes it (per-symbol target, not a bare module).
_LANDABLE_PROMOTE_SIGNALS: tuple[tuple[str, str], ...] = (
    ("fillable_stub_modules", "implement-stub"),
    ("cover_gaps_modules", "cover-gaps"),
    ("wire_export_packages", "wire-exports"),
)


def _module_landable_objective(root: Path, module: str) -> str | None:
    """The highest-buyer-value EXECUTABLE objective a confluence ``module`` carries,
    or ``None`` when none honestly holds.

    Reuses the same real-lander-grounded synthesis probes as the seeder's
    ``_landable_reroute`` (``fillable_stub_modules`` / ``cover_gaps_modules`` /
    ``wire_export_packages``), so a returned objective is one ``apex develop``
    could ACTUALLY land a diff on this exact module — never an over-promise.
    Best-effort + deterministic: a non-``.py`` subject, an import failure, or a
    probe that raises all yield ``None`` (the module simply graduates by the
    confidence gate or not at all). No clock, no randomness — same module → same
    verdict."""
    if not module.endswith(".py"):
        return None
    try:
        from app.engine import idea_synthesis_signals as sigs
    except Exception:
        return None
    for signal_name, objective in _LANDABLE_PROMOTE_SIGNALS:
        try:
            hits = getattr(sigs, signal_name)(root, [module], limit=1)
        except Exception:
            continue
        if module in hits:
            return objective
    return None


def _is_value_landable_confluence(root: Path, d: dict) -> bool:
    """A discovery graduates on VALUE (below the confidence gate) only when it is a
    confluence whose module carries a verified-landable move.

    The value-aware second promote path: a confluence that sits BELOW
    ``PROMOTE_CONFIDENCE`` (the common case on a real project, where confluences
    confirm at ~0.60) still graduates IF the dream can PROVE a concrete landing
    exists on its module — so the curated ``dream --land`` scope is no longer
    permanently empty. Design-level confluences (no landable move) keep the
    existing 0.80 bar. Pure read over the discovery + a real-lander probe; the
    STREAK requirement is applied by the caller, so this is never a one-off."""
    if d.get("kind") != "confluence":
        return False
    if d.get("confidence", 0.0) >= PROMOTE_CONFIDENCE:
        return False  # already graduates by the design-level confidence path
    module = d["key"].split(":", 1)[1]
    return _module_landable_objective(root, module) is not None


def _promotable_discoveries(root: Path, report: DreamReport,
                            streaks: dict[str, int],
                            gate_factors: dict[str, float] | None = None) -> list[dict]:
    """The confirmed discoveries that graduate this dream — TWO promote paths,
    both still streak-gated (never a one-off).

    1. **design-level** (unchanged): ``confidence >= PROMOTE_CONFIDENCE`` —
       a strong, broadly-confirmed law.
    2. **value-aware** (new): a confluence BELOW that confidence whose module
       carries a verified-landable move (:func:`_is_value_landable_confluence`)
       — the dream graduates a discovery it can PROVE it can act on.

    Discovery order is preserved (the source ``discovery_objs`` order), so the
    digest stays byte-stable; a discovery never appears twice (the two predicates
    are mutually exclusive — path 2 requires confidence < the gate path 1 needs).

    ``gate_factors`` (opt-in, default ``None``) is a precomputed
    ``dream_gate_learn.gate_tighten_factors`` map: when supplied, the per-key
    effective gate (:func:`app.engine.dream_gate_learn.effective_promote_gate`)
    replaces the bare ``PROMOTE_STREAK``/``PROMOTE_CONFIDENCE`` constants for
    BOTH the streak check and the design-level confidence check. Tighten-only —
    with ``gate_factors`` empty/``None`` (the default caller) the effective gate
    is the static constants exactly, so this stays byte-identical."""
    from app.engine.dream_gate_learn import effective_promote_gate

    promotable: list[dict] = []
    for d in report.discovery_objs:
        eff_streak, eff_confidence = effective_promote_gate(
            gate_factors, d["key"], PROMOTE_STREAK, PROMOTE_CONFIDENCE)
        if streaks.get(d["key"], 1) < eff_streak:
            continue
        if (d.get("confidence", 0.0) >= eff_confidence
                or _is_value_landable_confluence(root, d)):
            promotable.append(d)
    return promotable


def _promote(root: Path, report: DreamReport, curate: bool,
            learn_gates: bool = False) -> None:
    """Graduate confirmed discoveries into a seed store the waking engine reads.

    Default mode only proposes (inputs untouched, like the rest of the dream);
    ``--curate`` rewrites the promotions store FRESH each run — so a law that
    stops holding simply drops out, never leaving a stale idea behind.

    Two streak-gated promote paths feed it (:func:`_promotable_discoveries`): the
    design-level confidence gate, and a value-aware gate that graduates a
    below-confidence confluence ONLY when it carries a verified-landable move — so
    the dream can act on what it can prove it can fix, while a default run with no
    prior journal (streak 1) graduates nothing either way (byte-identical).

    ``learn_gates`` (opt-in, default ``False``) computes
    ``dream_gate_learn.gate_tighten_factors`` ONCE and threads it into
    :func:`_promotable_discoveries` so a confluence key whose past promotions
    never realized a held-and-verified fix needs a stricter streak/confidence to
    graduate again — tighten-only, never loosens. ``False`` (the default) passes
    no factors, so the gate reads the static constants — byte-identical."""
    streaks: dict[str, int] = getattr(report, "_streaks", {}) or {}
    gate_factors: dict[str, float] | None = None
    if learn_gates:
        from app.engine.dream_gate_learn import gate_tighten_factors

        gate_factors = gate_tighten_factors(root, PROMOTE_STREAK)
    promotable = _promotable_discoveries(root, report, streaks, gate_factors)
    if not curate:
        for d in promotable:
            report.proposed.append(
                f"promote to the idea engine: {d['text']} "
                f"(confirmed {streaks.get(d['key'], 1)} dreams)")
        return
    # curate: rewrite the store fresh (even empty → clears stale promotions).
    payload = [{"key": d["key"], "text": d["text"], "kind": d["kind"],
                "confidence": d["confidence"],
                "streak": streaks.get(d["key"], 1)} for d in promotable]
    path = root / PROMOTIONS_REL
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        return
    for d in promotable:
        report.promoted.append(d["text"])
        report.curated.append(
            f"promoted to the idea engine: {d['key']} "
            f"(confirmed {streaks.get(d['key'], 1)} dreams, "
            f"{int(d['confidence'] * 100)}% confidence)")
    confluence_subjects = [d["key"].split(":", 1)[1] for d in promotable
                           if d["kind"] == "confluence"]
    _materialize_briefs(root, confluence_subjects, report)


def _briefed_subjects(root: Path) -> set[str]:
    """Module subjects that already have a saved OR archived brief.

    Archived counts too: a just-resolved confluence keeps firing in the
    churn window for a while, and re-materializing its work order the next
    night would be exactly the cyclic noise the dream exists to prevent.
    """
    out: set[str] = set()
    briefs = root / ".apex" / "briefs"
    for path in [*briefs.glob("*.json"), *(briefs / "archive").glob("*.json")]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.add(data.get("subject", "").split(" :: ", 1)[0].split("::", 1)[0].strip())
    return out


def _materialize_briefs(root: Path, subjects: list[str],
                        report: DreamReport) -> None:
    """A promoted confluence becomes a SAVED work order, automatically.

    The discovery loop used to stop at "promoted to the idea engine" — the
    last step was always a human running ``apex brief --subject … --save``.
    Now the dream closes it: each promoted confluence whose module has no
    saved (or archived) brief gets one built from a fresh engine run, with
    its evidence baseline snapshotted — the next morning starts with a
    measurable order, not a hint.
    """
    todo = [s for s in subjects if s and s not in _briefed_subjects(root)]
    if not todo:
        return
    try:
        from app.engine.idea_brief import build_brief, save_brief
        from app.engine.idea_permutation import IdeaPermutationEngine

        # A BUYER ENTRY POINT (the dream closes the loop into a SAVED work order):
        # opt into value-aware idea generation so the materialized brief leads with
        # the highest concrete-value work — the graded landability bonus and the
        # deep cost-tier signals (incl. the value-led ``::landable-*`` family). The
        # engine default stays OFF, so only this development surface opts in.
        tree = IdeaPermutationEngine(
            {"max_total_ideas": 40, "max_idea_depth": 2, "breadth": 4,
             "landability_aware": True, "landability_deep": True},
            project_root=str(root)).run()
    except Exception:
        return
    for subject in todo:
        brief = build_brief(tree, subject=subject)
        if brief is None or not brief.subject.startswith(subject):
            continue  # the tree didn't surface this subject this run — skip honestly
        save_brief(brief, str(root))
        report.curated.append(
            f"work order materialized for the standing confluence: "
            f"`apex brief {brief.branch_path} --check` ({subject})")


def _forecast(report: DreamReport) -> None:
    """Turn the BACKWARD streak count into a FORWARD signal: what graduates next.

    A pure read over the data ``_promote`` already trusts — ``report._streaks``
    (set in ``_consolidate``, byte-identical under ``persist=False``) and the
    same ``PROMOTE_STREAK``/``PROMOTE_CONFIDENCE`` constants that gate promotion.
    A discovery already strong enough (``confidence >= PROMOTE_CONFIDENCE``) but
    still UNDER the streak gate (``2 <= streak < PROMOTE_STREAK``) is a near-miss:
    one (or a few) more dream(s) and the existing gate graduates it into a work
    order. Forecasting ONLY what the same gate would promote keeps it honest —
    the forecast and the next night's actual graduation can never disagree.

    The exactly-at-streak set stays in "Graduated" (``_promote``), never here, so
    a discovery is never double-reported. Emits nothing when no discovery sits in
    the near-miss band, so the digest is byte-identical when the signal is absent.
    """
    streaks: dict[str, int] = getattr(report, "_streaks", {}) or {}
    for d in report.discovery_objs:
        streak = streaks.get(d["key"], 1)
        if not (PROMOTE_CONFIDENCE <= d.get("confidence", 0.0)
                and 2 <= streak < PROMOTE_STREAK):
            continue
        remaining = PROMOTE_STREAK - streak
        more = "one more dream" if remaining == 1 else f"{remaining} more dreams"
        report.forecast.append(
            f"{d['text']}  → confirmed {streak}/{PROMOTE_STREAK} dreams; "
            f"{more} graduates it into a work order.")


def _safe(call) -> None:
    """Run one review step; a missing/corrupt store must never break the dream."""
    try:
        call()
    except Exception:
        pass


def _run_reviews(root: Path, report: DreamReport, curate: bool,
                 persist: bool = True, learn_gates: bool = False) -> None:
    """The full review sweep, each step isolated so one failure can't abort it."""
    _safe(lambda: _review_outcome_memory(root, report, curate))
    _safe(lambda: _review_briefs(root, report, curate))
    _safe(lambda: _review_proof(root, report))
    _safe(lambda: _review_pulse(root, report, persist))
    _safe(lambda: _consolidate(root, report, persist))
    _safe(lambda: _promote(root, report, curate, learn_gates))
    _safe(lambda: _forecast(report))


def _write_digest(root: Path, report: DreamReport) -> None:
    """Write the one-page digest, recording its path; an unwritable store is fine."""
    path = root / ".apex" / "dream-digest.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_dream_markdown(report), encoding="utf-8")
        report.digest_path = str(path)
    except OSError:
        pass


def dream(project_root: str | Path, write_digest: bool = True,
          curate: bool = False, persist: bool = True,
          learn_gates: bool = False) -> DreamReport:
    """Run the full pass; returns what was noticed (and, with ``curate``, tidied).

    Like the real Dreams API, the default NEVER modifies the input stores —
    it reports what it would curate; ``curate=True`` applies it (the mode
    automation like the nightly dogfood runs in).

    ``persist`` (default ``True``) controls the dream's OWN memory stores — the
    append-only journal and the promise ledger, normally written every run so
    streaks accumulate. With ``persist=False`` the pass is fully READ-ONLY: it
    still computes the streaks from the on-disk journal (so ``report._streaks`` is
    byte-for-byte what a persisting run would compute), but writes NOTHING — so a
    caller can derive promotable confluences deterministically and idempotently,
    without advancing the streak or touching any store.

    ``learn_gates`` (opt-in, default ``False``) folds
    ``dream_gate_learn.gate_tighten_factors`` into the promote gate
    (:func:`_promote`/:func:`_promotable_discoveries`): a confluence key whose
    past promotions never realized a held-and-verified fix needs a stricter
    streak/confidence to graduate again — TIGHTEN-ONLY, it can never loosen the
    gate below ``PROMOTE_STREAK``/``PROMOTE_CONFIDENCE``. ``False`` (the
    default) computes no factors, so the gate is the static constants —
    byte-identical to before this parameter existed."""
    root = Path(project_root)
    report = DreamReport()
    _run_reviews(root, report, curate, persist, learn_gates)
    if write_digest:
        _write_digest(root, report)
    return report


# --- cross-dream consolidation -------------------------------------------
# The real Dreams pipeline reads up to 100 past sessions so "the same mistake,
# 12 times" becomes visible. Our deterministic analogue: an append-only dream
# journal — a pattern that keeps appearing dream after dream is consolidated
# ("seen in N consecutive dreams"), because persistence IS the signal.
_JOURNAL_CAP = 30


def _pattern_key(text: str) -> str:
    """A stable identity for a pattern across dreams (magnitudes change,
    the subject doesn't): the text up to the first em-dash/colon/paren."""
    for sep in (" — ", " (", ":"):
        if sep in text:
            text = text.split(sep, 1)[0]
    return text.strip()


def _load_journal(journal_path: Path) -> list[Any]:
    """Read the append-only dream journal, tolerating a missing/corrupt file."""
    if journal_path.exists():
        try:
            return json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    return []


def _consecutive_streak(history: list[Any], key: str) -> int:
    """How many consecutive past dreams (plus this one) carried ``key``.

    Entries are ``{key: text}`` maps or legacy bare lists; ``in`` works on
    both, so a standing observation accumulates a streak either way.
    """
    streak = 1
    for past in reversed(history):
        if key in past:
            streak += 1
        else:
            break
    return streak


def _annotate_streaks(history: list[Any], report: DreamReport) -> tuple[
        dict[str, str], dict[str, int]]:
    """Tag every pattern/discovery with its streak; return the current map.

    Mutates ``report.patterns``/``report.discoveries`` in place to append the
    "seen in N consecutive dreams" suffix, and returns ``(current, streaks)``
    where ``current`` is the ``{key: text}`` snapshot this dream records.
    """
    current: dict[str, str] = {}
    streaks: dict[str, int] = {}
    disc_key_by_index = {i: d["key"] for i, d in enumerate(report.discovery_objs)}
    for i, text in enumerate(report.patterns):
        key = _pattern_key(text)
        current[key] = text
        streaks[key] = _consecutive_streak(history, key)
        if streaks[key] >= 2:
            report.patterns[i] += f"  ⟲ seen in {streaks[key]} consecutive dreams"
    for i, text in enumerate(report.discoveries):
        key = disc_key_by_index.get(i) or _pattern_key(text)
        current[key] = text
        streaks[key] = _consecutive_streak(history, key)
        if streaks[key] >= 2:
            report.discoveries[i] += f"  ⟲ seen in {streaks[key]} consecutive dreams"
    return current, streaks


def _diff_since_last(history: list[Any], current: dict[str, str],
                     report: DreamReport) -> None:
    """Record what surfaced this dream and what stopped surfacing since the last.

    "New" means *absent from the previous dream*; a standing item is by
    definition present in it, so it can never be re-announced as new.
    """
    prev = history[-1] if history else {}
    prev_keys = set(prev.keys()) if isinstance(prev, dict) else set(prev)
    for key, text in current.items():
        if key not in prev_keys:
            report.new_since.append(text)
    for key in sorted(prev_keys - set(current)):
        report.resolved_since.append(prev[key] if isinstance(prev, dict) else key)


def _consolidate(root: Path, report: DreamReport, persist: bool = True) -> None:
    """One journal, three jobs — streaks, the new/resolved flow, persistence.

    A single source of truth (the dream journal) drives everything, so a
    standing observation can never be re-announced as "new" (the root of
    cyclic-repetition bugs): "new" means *absent from the previous dream*,
    and a standing item is by definition present in it. Entries are
    ``{key: text}`` maps so a resolved item can be shown with the words it
    had; legacy bare-list entries are still read.

    The streak is computed from the on-disk history BEFORE this dream is appended,
    so ``persist=False`` yields the identical ``report._streaks`` while writing
    nothing — a read-only pass that never advances the journal.
    """
    journal_path = root / ".apex" / "dream-journal.json"
    history = _load_journal(journal_path)
    current, streaks = _annotate_streaks(history, report)
    report._streaks = streaks  # for promotion
    _diff_since_last(history, current, report)

    if not persist:
        return  # read-only pass: streaks/new-resolved are set above; never write
    history.append(current)
    try:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path.write_text(json.dumps(history[-_JOURNAL_CAP:], indent=1),
                                encoding="utf-8")
    except OSError:
        pass


def _emit_section(lines: list[str], heading: str, items: list[str],
                  prefix: str) -> None:
    """Append a ``## heading`` block plus a blank line when ``items`` is non-empty.

    Each item is rendered as ``{prefix}{item}``; an empty ``items`` emits
    nothing, keeping the digest byte-identical when a section is absent.
    """
    if not items:
        return
    lines.append(heading)
    lines += [f"{prefix}{item}" for item in items]
    lines.append("")


def _render_since_last(lines: list[str], report: DreamReport) -> None:
    """The combined new/resolved block — two prefixes under one heading."""
    if not (report.new_since or report.resolved_since):
        return
    lines.append("## Since the last dream")
    lines += [f"- 🆕 {t}" for t in report.new_since]
    lines += [f"- ✅ no longer surfaces: {t}" for t in report.resolved_since]
    lines.append("")


def render_dream_markdown(report: DreamReport) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = ["# Dream digest — what the organism learned while you were away",
             "", f"_Curated {ts} · deterministic · zero tokens · signed by barzeuss_", ""]
    _render_since_last(lines, report)
    _emit_section(lines, "## ⬆️ Graduated to the idea engine (confirmed across dreams)",
                  report.promoted, "- ")
    _emit_section(lines, "## 🔮 Next to graduate (one more dream away)",
                  report.forecast, "- ")
    if report.patterns:
        _emit_section(lines, "## Patterns", report.patterns, "- ")
    else:
        lines += ["_No artifacts to learn from yet — run `apex maintain` or save "
                  "a brief, then dream again._", ""]
    _emit_section(lines, "## Discoveries — open-ended, found in the data (not coded rules)",
                  report.discoveries, "- 🔍 ")
    _emit_section(lines, "## Curated", report.curated, "- 🧹 ")
    _emit_section(lines, "## Proposed curation — inputs untouched (apply with `apex dream --curate`)",
                  report.proposed, "- 💤 ")
    return "\n".join(lines)
