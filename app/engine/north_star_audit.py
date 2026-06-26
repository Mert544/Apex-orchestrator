"""The durable mission-auditor ("denetçi") — `apex self-audit --north-star`.

CLAUDE.md names this module as "the preferred way to make the denetçi permanent
and automatic": a deterministic, zero-token, offline check that measures the
North Star and exits NON-ZERO on drift so a wave-gate or CI fails automatically.

It answers two questions about Apex's own state, both as a pure function of the
repo (no clock, no random, no network):

1. **Concrete-vs-advice ratio** — of every develop objective Apex can pursue,
   what fraction *lands working code* (CONCRETE) versus merely *tidies* existing
   code (TIDY) or hardens safety machinery (SAFETY)? CLAUDE.md's anti-drift rule
   is that capability investment must go to concrete project-development, so a
   low concrete ratio is the structural smell.

2. **Commit drift** — in the last N commit SUBJECTS (order/count only, never
   timestamps), did a window land ONLY safety/honesty work and ZERO concrete
   work? That is the exact failure mode the North Star guards against.

The objective taxonomy is an EXPLICIT manifest dict literal below (the registry
carries no category metadata), so it is reviewable and stable. TWO tripwires keep
the manifest and the live registry in lockstep, in BOTH directions:

* FORWARD — :func:`classify_objectives` RAISES on ANY registered name missing
  from the manifest, so a future self-registered objective must be categorised
  here before this check can pass (the manifest can't fall BEHIND the registry).
* REVERSE — :func:`manifest_subset_of_registry` flags any manifest name that is
  NOT a currently-registered objective (a renamed/removed objective left stale in
  the manifest), surfaced through :func:`north_star_report` as a drift finding the
  ``--north-star`` CLI exits non-zero on (the manifest can't drift AHEAD of the
  registry either).

Dependencies: stdlib + :mod:`app.engine.develop_registry` (cycle-free by design)
+ a LOCAL git-subprocess helper (the pattern from ``app/tools/git_history.py``),
so importing this module never forms an ``app`` import cycle.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

__all__ = [
    "OBJECTIVE_MANIFEST",
    "classify_objectives",
    "manifest_subset_of_registry",
    "commit_drift",
    "north_star_report",
]


# --- The explicit, reviewable taxonomy manifest ------------------------------
#
# Every develop objective Apex can pursue is partitioned here by what it DELIVERS
# (CLAUDE.md's "concrete contribution" lens), NOT by how it is implemented. The
# registry has no category metadata, so this manifest is the single hand-curated
# source of truth — and the completeness tripwire in `classify_objectives` makes
# it impossible to leave a registered objective out.
#
#   CONCRETE — LANDS working code that did not exist before: implements stubs,
#              writes tests for untested code, wires exports, infers type hints,
#              dataclassifies, generates docs. This is the product.
#   TIDY     — improves EXISTING code in place (idiom modernizers, dedup, dead
#              code/param removal, function shrinking). Valuable, but polish.
#   SAFETY   — hardens the trust foundation (proof/shield/grade machinery). The
#              moat, not the goal. Reserved — empty today; no develop objective
#              currently exists purely to build safety machinery.
OBJECTIVE_MANIFEST: dict[str, frozenset[str]] = {
    "CONCRETE": frozenset({
        "implement-stub",
        "tdd-implement",
        "implement-from-doctest",
        "js-tdd-implement",
        "js-implement-from-jsdoc",
        "strengthen-tests",
        "wire-exports",
        "js-wire-exports",
        "infer-type-hints",
        "annotate-self-returns",
        "dataclassify",
        "freeze-dataclass",
        "add-slots",
        "add-from-future-annotations",
        "generate-usage-doc",
        "document-signature",
        "document-raises",
        "pin-return-type",
        "document-export-jsdoc",
        "js-document-param-types",
        "document-raises-jsdoc",
        "pin-doctest",
        "cover-gaps",
        "scaffold-from-protocol",
        "add-final",
        "java-finalize-field",
        "java-document-throws",
        "seal-final-method",
        "enforce-enum-unique",
        "complete-match-exhaustiveness",
        "synthesize-dunders",
        "seal-total-ordering",
        "seal-hashable-eq",
        "add-dataclass-order",
        "wire-module-exports",
        "harden",
        "raise-from",
        # NOTE: "fix-docstrings" was REMOVED here — it is a standalone CLI
        # subcommand (`apex fix-docstrings`), NOT a registered develop objective,
        # so it never appears in ``available_objectives()``. Listing it left the
        # manifest reverse-stale (a name with no live objective behind it). The
        # reverse tripwire below now catches exactly this drift; this entry was
        # the one real stale name it surfaced, removed as part of that fix.
    }),
    "TIDY": frozenset({
        "modernize",
        "simplify-bool-return",
        "simplify-comprehension",
        "simplify-bool-comparison",
        "simplify-len-comparison",
        "simplify-negated-comparison",
        "simplify-ternary-bool",
        "simplify-dict-get",
        "extract-constant",
        "remove-unused-imports",
        "sort-imports",
        "sort-dunder-all",
        "remove-dead-code",
        "remove-double-negation",
        "remove-pointless-pass",
        "remove-redundant-else",
        "remove-redundant-fstring",
        "remove-unreachable-after-terminator",
        "dedup",
        "dedup-parameterized",
        "dedup-total-return",
        "dead-params",
        "shrink-functions",
        "inline-helpers",
        "chain-comparison",
        "collapse-startswith",
        "combine-augmented-assign",
        "combine-nested-with",
        "dict-comprehension",
        "extract-guard-clause",
        "guard-clause",
        "merge-isinstance",
        "merge-nested-if",
        "fix-assert-tuple",
        "fix-not-in-is",
        "fold-literal-string-concat",
        "format-to-fstring",
        "fstring-convert",
        "percent-to-fstring",
        "set-literal",
        "use-enumerate",
        "merge-duplicate-imports",
    }),
    "SAFETY": frozenset(),
}


def classify_objectives(names) -> dict[str, set[str]]:
    """Partition ``names`` into CONCRETE / TIDY / SAFETY per :data:`OBJECTIVE_MANIFEST`.

    HONESTY TRIPWIRE: raises :class:`ValueError` if ANY name is not in the
    manifest. Passing ``available_objectives()`` therefore fails loudly the
    moment a new objective self-registers without being categorised here — the
    manifest can never silently fall behind the registry.
    """
    buckets: dict[str, set[str]] = {"CONCRETE": set(), "TIDY": set(), "SAFETY": set()}
    unclassified: set[str] = set()
    for name in names:
        for category, members in OBJECTIVE_MANIFEST.items():
            if name in members:
                buckets[category].add(name)
                break
        else:
            unclassified.add(name)
    if unclassified:
        raise ValueError(
            "north-star manifest is stale: unclassified objective(s) "
            f"{sorted(unclassified)} — add them to OBJECTIVE_MANIFEST in "
            "app/engine/north_star_audit.py (CONCRETE / TIDY / SAFETY)."
        )
    return buckets


def _manifest_names() -> set[str]:
    """Every objective NAME the manifest lists, across all category buckets."""
    names: set[str] = set()
    for members in OBJECTIVE_MANIFEST.values():
        names |= set(members)
    return names


def manifest_subset_of_registry(registered=None) -> list[str]:
    """The REVERSE tripwire: manifest names with NO live objective behind them.

    The forward tripwire (:func:`classify_objectives`) catches a registered
    objective MISSING from the manifest. This catches the mirror drift — a
    manifest name that is NOT a currently-registered objective (a renamed/removed
    objective left stale in the manifest). Validates against the SAME live set the
    forward tripwire uses — the develop-objective registry via
    ``available_objectives()`` (built-in + discovered) — so the two tripwires
    agree on what "a real objective" is.

    Returns the sorted list of stale manifest names (empty == clean). A pure,
    deterministic function of the manifest + the registry: no clock, no random,
    no network. ``registered`` may be passed (any iterable of names) to check a
    manifest against a supplied registry — the seam tests use to inject a stale
    entry — otherwise the live registry is read.
    """
    if registered is None:
        from app.engine.objective_compiler import available_objectives

        registered = available_objectives()
    live = set(registered)
    return sorted(_manifest_names() - live)


# --- Commit-drift detection --------------------------------------------------
#
# Conventional-commit subjects only — order and count, NEVER timestamps — so the
# verdict is a pure function of repo state (determinism invariant).
_SUBJECT_RE = re.compile(r"^(\w+)\(([\w-]+)\):")

# A `feat`/`fix` whose scope names one of these is concrete development work.
#
# Two TIERS of scope name the same concrete-development core:
#   * the broad umbrella scopes the develop loop has historically committed under
#     (``develop``/``maintain``/``transforms``/``self-dev``); and
#   * the FINER per-capability scopes the develop CORE actually ships under, each
#     of which either LANDS working code or DIRECTLY GATES landed code:
#       - implement-stub / tdd-implement / stub-synthesis / stub  -> land function
#         bodies from signatures/tests (and their fake-green floors);
#       - wire-exports                                            -> land __all__;
#       - infer-type-hints / type-hints                           -> land hints;
#       - dataclassify                                            -> land @dataclass;
#       - strengthen-tests / cover-gaps                           -> land new tests;
#       - generate-usage-doc / usage-doc                          -> land USAGE.md;
#       - percent-to-fstring / format-to-fstring / fstring-convert-> land f-string
#         rewrites (the develop-core string-modernization transforms);
#       - develop-session                                         -> the loop that
#         orchestrates the above onto a project;
#       - test-shield / test_shield                               -> the synthesis
#         VALUE-ORACLE that gates implement-stub/cover-gaps (no landed fill is
#         stamped verified without it), so it is concrete-by-gating.
# Pure-meta scopes (``grade``/``ci``/``docs``/unscoped) and the trust-foundation
# scopes in ``_SAFETY_SCOPES`` are DELIBERATELY excluded so the concrete count
# reflects reality and cannot be inflated by housekeeping or safety commits.
_CONCRETE_SCOPES = frozenset({
    "develop", "maintain", "transforms", "self-dev",
    # develop-core capability scopes that LAND code ...
    "implement-stub", "tdd-implement", "stub-synthesis", "stub",
    "wire-exports", "infer-type-hints", "type-hints", "dataclassify",
    "strengthen-tests", "cover-gaps",
    "generate-usage-doc", "usage-doc",
    "percent-to-fstring", "format-to-fstring", "fstring-convert",
    "develop-session",
    # ... the value-oracle that DIRECTLY GATES those landed fills ...
    "test-shield", "test_shield",
    # ... and the overnight LANDING CHAIN (`apex dream --land`): pure orchestration
    # over the verified-with-rollback compiler that LANDS the value-led concrete
    # chain, so the chain's own commits count concrete in the drift check.
    "dream-develop",
})
# A `fix`/`feat` whose scope names one of these is trust-foundation/safety work.
_SAFETY_SCOPES = frozenset({
    "safety", "proof", "shield", "grade", "scope",
    "architecture", "intelligence", "fix-risk",
})


def _classify_subject(subject: str) -> str:
    """Classify one commit subject as ``concrete`` / ``safety`` / ``neutral``.

    Uses the conventional-commit ``type(scope):`` prefix only. A concrete scope
    on a feat/fix is concrete; a safety scope is safety; everything else
    (chore, docs, refactor, unscoped, off-list scopes) is neutral.
    """
    match = _SUBJECT_RE.match(subject)
    if not match:
        return "neutral"
    ctype, scope = match.group(1), match.group(2)
    if ctype in ("feat", "fix") and scope in _CONCRETE_SCOPES:
        return "concrete"
    if ctype in ("feat", "fix") and scope in _SAFETY_SCOPES:
        return "safety"
    return "neutral"


def _git_subjects(project_root: str | Path, n: int) -> list[str] | None:
    """The subjects of the last ``n`` commits (newest first), or ``None``.

    ``None`` for a non-git root (or any git failure) so the caller renders the
    drift section as 'unavailable' rather than crashing. Local subprocess helper
    mirroring ``app/tools/git_history.py`` — no ``app`` import, so no cycle.
    This is the single seam tests monkeypatch to feed canned subjects.
    """
    try:
        proc = subprocess.run(
            ["git", "log", "-n", str(n), "--format=%s"],
            cwd=project_root, capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return [line for line in proc.stdout.splitlines() if line.strip()]


def commit_drift(project_root: str | Path, n: int = 20) -> dict | None:
    """Classify the last ``n`` commit subjects and decide whether the window drifted.

    Returns ``{concrete, safety, neutral, total, drift}`` where ``drift`` is True
    iff the window landed safety work but ZERO concrete work (the exact North
    Star failure mode). Returns ``None`` for a non-git root so the report marks
    the drift section 'unavailable' and never crashes. Pure function of commit
    subjects + their count — no timestamps, no wall-clock.
    """
    subjects = _git_subjects(project_root, n)
    if subjects is None:
        return None
    counts = {"concrete": 0, "safety": 0, "neutral": 0}
    for subject in subjects:
        counts[_classify_subject(subject)] += 1
    drift = counts["concrete"] == 0 and counts["safety"] > 0
    return {
        "concrete": counts["concrete"],
        "safety": counts["safety"],
        "neutral": counts["neutral"],
        "total": len(subjects),
        "drift": drift,
    }


def north_star_report(project_root: str | Path, n: int = 20) -> dict:
    """Assemble the full North Star verdict for ``project_root``.

    Keys (stable, no wall-clock): ``concrete_ratio`` (|CONCRETE| / total
    registered objectives), ``buckets`` (sorted name lists per category),
    ``bucket_counts``, ``total_objectives``, ``commit_window`` (the
    :func:`commit_drift` dict, or ``None`` when unavailable), ``drift`` (bool),
    and ``verdict`` ("PASS" / "DRIFT"). The key SET is intentionally stable.

    ``classify_objectives`` is called on the live registry, so a stale manifest
    that has fallen BEHIND the registry raises here (forward tripwire). A manifest
    that has drifted AHEAD of the registry (a stale name with no live objective
    behind it, via :func:`manifest_subset_of_registry`) folds into ``drift`` — so
    the ``--north-star`` CLI exits non-zero on EITHER direction of manifest drift,
    consistent with the forward tripwire's severity. The stale NAMES are not a new
    report key (the key set stays stable); they are recomputed for display by
    :func:`render_markdown`, which calls the tripwire directly.
    """
    from app.engine.objective_compiler import available_objectives

    available = available_objectives()
    buckets = classify_objectives(available)
    total = sum(len(names) for names in buckets.values())
    concrete_ratio = len(buckets["CONCRETE"]) / total if total else 0.0
    stale = manifest_subset_of_registry(available)
    window = commit_drift(project_root, n)
    drift = bool(stale) or bool(window and window["drift"])
    return {
        "concrete_ratio": concrete_ratio,
        "buckets": {cat: sorted(names) for cat, names in buckets.items()},
        "bucket_counts": {cat: len(names) for cat, names in buckets.items()},
        "total_objectives": total,
        "commit_window": window,
        "drift": drift,
        "verdict": "DRIFT" if drift else "PASS",
    }


def render_markdown(report: dict, target: str | Path) -> str:
    """Render :func:`north_star_report` output as a deterministic markdown block."""
    lines = [
        "# Apex Self-Audit — North Star",
        f"**Target:** {target}",
        "",
        f"- Verdict: **{report['verdict']}**",
        f"- Concrete ratio: {report['concrete_ratio']:.2%} "
        f"({report['bucket_counts']['CONCRETE']}/{report['total_objectives']} objectives)",
        f"- Buckets: CONCRETE={report['bucket_counts']['CONCRETE']}, "
        f"TIDY={report['bucket_counts']['TIDY']}, "
        f"SAFETY={report['bucket_counts']['SAFETY']}",
    ]
    # Recompute the reverse-tripwire names for display (kept OUT of the report
    # dict to hold its key set stable). The manifest is read from module state, so
    # this is a pure function of the same inputs the verdict used.
    stale = manifest_subset_of_registry()
    if stale:
        lines.append(
            "- STALE MANIFEST ENTRIES (no live objective): " + ", ".join(stale)
        )
    window = report["commit_window"]
    if window is None:
        lines.append("- Commit window: unavailable (non-git target)")
    else:
        lines.append(
            f"- Commit window (last {window['total']}): "
            f"concrete={window['concrete']}, safety={window['safety']}, "
            f"neutral={window['neutral']} — drift={window['drift']}"
        )
    lines.append("")
    lines.append(
        "  CONCRETE: " + ", ".join(report["buckets"]["CONCRETE"])
    )
    return "\n".join(lines)
