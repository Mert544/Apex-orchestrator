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

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Outcome-memory tables are trimmed to this many keys (by evidence volume):
# memory should stay high-signal, not become a landfill of one-off keys.
MEMORY_KEY_CAP = 20


@dataclass
class DreamReport:
    patterns: list[str] = field(default_factory=list)   # what the dream noticed
    curated: list[str] = field(default_factory=list)    # what it tidied (--curate)
    proposed: list[str] = field(default_factory=list)   # what it WOULD tidy (default)
    digest_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"patterns": self.patterns, "curated": self.curated,
                "proposed": self.proposed, "digest_path": self.digest_path}


def _review_outcome_memory(root: Path, report: DreamReport, curate: bool) -> None:
    from app.engine.idea_memory import IdeaMemory

    mem = IdeaMemory.load(root)
    info = mem.summary()
    for row in info.get("most_reliable", [])[:2]:
        report.patterns.append(
            f"`{row['key']}` fixes land {int(row['success_rate'] * 100)}% of the time "
            f"({row['samples']} samples) — keep leading with them.")
    for row in info.get("least_reliable", [])[:2]:
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


def _review_proof(root: Path, report: DreamReport) -> None:
    proof_path = root / ".apex" / "proof-of-fix.json"
    if not proof_path.exists():
        return
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    failing: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for fix in proof.get("fixes", []) or []:
        for test in (fix.get("verification") or {}).get("failing_tests", []) or []:
            failing[test] = failing.get(test, 0) + 1
        reason = fix.get("blocked_reason") or ""
        if reason:
            key = reason.split("—")[0].strip()[:80]
            reasons[key] = reasons.get(key, 0) + 1
    for test, n in sorted(failing.items(), key=lambda kv: (-kv[1], kv[0]))[:2]:
        report.patterns.append(
            f"`{test}` failed verification {n}× in the last pass — it guards "
            "whatever keeps being touched; look there first.")
    for reason, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:2]:
        if n >= 2:
            report.patterns.append(f"{n} steps blocked for the same reason: {reason}.")


def _review_pulse(root: Path, report: DreamReport) -> None:
    """Where the project is alive — churn, trends, knowledge, promises."""
    from app.engine.signal_trends import SignalTrends
    from app.tools.project_profile import ProjectProfiler

    profile = ProjectProfiler(root).profile()
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
    if profile.doc_drift:
        report.patterns.append(
            f"{len(profile.doc_drift)} documentation promise(s) point at files "
            "that don't exist — the docs drifted.")


def dream(project_root: str | Path, write_digest: bool = True,
          curate: bool = False) -> DreamReport:
    """Run the full pass; returns what was noticed (and, with ``curate``, tidied).

    Like the real Dreams API, the default NEVER modifies the input stores —
    it reports what it would curate; ``curate=True`` applies it (the mode
    automation like the nightly dogfood runs in).
    """
    root = Path(project_root)
    report = DreamReport()
    for review in (_review_outcome_memory, _review_briefs):
        try:
            review(root, report, curate)
        except Exception:  # a missing/corrupt store must never break the dream
            continue
    for review in (_review_proof, _review_pulse):
        try:
            review(root, report)
        except Exception:
            continue
    try:
        _consolidate(root, report)
    except Exception:
        pass
    if write_digest:
        path = root / ".apex" / "dream-digest.md"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_dream_markdown(report), encoding="utf-8")
            report.digest_path = str(path)
        except OSError:
            pass
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


def _consolidate(root: Path, report: DreamReport) -> None:
    journal_path = root / ".apex" / "dream-journal.json"
    history: list[list[str]] = []
    if journal_path.exists():
        try:
            history = json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            history = []
    keys = [_pattern_key(p) for p in report.patterns]
    # Streak per key: how many consecutive past dreams (newest first) saw it.
    for i, key in enumerate(keys):
        streak = 1
        for past in reversed(history):
            if key in past:
                streak += 1
            else:
                break
        if streak >= 2:
            report.patterns[i] += f"  ⟲ seen in {streak} consecutive dreams"
    history.append(keys)
    try:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path.write_text(json.dumps(history[-_JOURNAL_CAP:], indent=1),
                                encoding="utf-8")
    except OSError:
        pass


def render_dream_markdown(report: DreamReport) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = ["# Dream digest — what the organism learned while you were away",
             "", f"_Curated {ts} · deterministic · zero tokens_", ""]
    if report.patterns:
        lines.append("## Patterns")
        lines += [f"- {p}" for p in report.patterns]
        lines.append("")
    else:
        lines += ["_No artifacts to learn from yet — run `apex maintain` or save "
                  "a brief, then dream again._", ""]
    if report.curated:
        lines.append("## Curated")
        lines += [f"- 🧹 {c}" for c in report.curated]
        lines.append("")
    if report.proposed:
        lines.append("## Proposed curation — inputs untouched (apply with `apex dream --curate`)")
        lines += [f"- 💤 {p}" for p in report.proposed]
        lines.append("")
    return "\n".join(lines)
