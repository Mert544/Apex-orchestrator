"""Decide, autonomously, whether Apex should apply fixes or just recommend.

`apex auto` shouldn't make the user pass `--apply` every time — where a fix is
clearly *safe and needed*, Apex should act on its own. But "safe by default"
still matters, so this policy gates unattended application behind concrete
conditions rather than blanket auto-applying.

The decision is pure (no I/O) so it's easy to test; the caller supplies the
observed facts (clean working tree? how many safe executable fixes? explicit
flags?). Deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AutonomyDecision:
    act: bool          # apply fixes now (vs. recommend only)?
    mode: str          # "report" | "supervised" | "autonomous"
    reason: str        # human-readable why

    def to_dict(self) -> dict:
        return {"act": self.act, "mode": self.mode, "reason": self.reason}


class AutonomyPolicy:
    """Decide the disposition of an autonomous run from observed facts.

    Order of precedence:
      1. An explicit ``--recommend`` always wins → never touch the tree.
      2. An explicit ``--apply`` always applies (autonomous if committing).
      3. ``require_explicit_apply`` (the PREVIEW-by-default safety) → recommend
         unless ``--apply`` was passed. This is the footgun fix: a bare ``apex
         auto`` must PREVIEW, never silently edit a clean tree (it once edited
         Apex's own repo). Off by default, so the unattended daemon / dashboard
         decision is byte-identical.
      4. Nothing safe to do → recommend.
      5. A dirty working tree → recommend (don't mix Apex's edits into a WIP
         tree the user can't cleanly review/undo); tell them how to proceed.
      6. Otherwise (clean tree + safe verified fixes) → apply autonomously,
         supervised (apply but don't commit) so the user reviews via ``git diff``.
    """

    def decide(
        self,
        *,
        executable_steps: int,
        working_tree_clean: bool,
        explicit_apply: bool = False,
        explicit_recommend: bool = False,
        commit: bool = False,
        require_explicit_apply: bool = False,
    ) -> AutonomyDecision:
        if explicit_recommend:
            return AutonomyDecision(False, "report", "recommend-only requested")
        if explicit_apply:
            mode = "autonomous" if commit else "supervised"
            return AutonomyDecision(True, mode, "apply explicitly requested")
        if executable_steps <= 0:
            return AutonomyDecision(False, "report", "no safe, auto-applicable fixes found")
        # PREVIEW-BY-DEFAULT (opt-in): with safe work available but no explicit
        # ``--apply`` we never touch the tree — we surface the fixes for the user
        # to apply on purpose. Checked AFTER "nothing to do" so a clean, debt-free
        # project still reads honestly. Default off ⇒ the historical clean-tree
        # auto-apply is unchanged (the unattended daemon/dashboard path).
        if require_explicit_apply:
            return AutonomyDecision(
                False, "report",
                "preview only — re-run with --apply to land the safe, "
                "test-verified fixes (Apex never edits without --apply)",
            )
        if not working_tree_clean:
            return AutonomyDecision(
                False, "report",
                "working tree has uncommitted changes — commit or stash first, "
                "then re-run (or pass --apply to override)",
            )
        return AutonomyDecision(
            True, "supervised",
            f"clean tree + {executable_steps} safe, test-verified fix(es) — applying "
            "autonomously (not committed; review with `git diff`)",
        )

    @staticmethod
    def resolve_covered_only(*, allow_weak: bool, unattended: bool) -> bool:
        """Alias so callers can reach the rule as
        ``AutonomyPolicy.resolve_covered_only`` (the policy OWNS it). Delegates to
        the module-level :func:`resolve_covered_only`, which the CLI act path
        calls directly so the gate is NOT coupled to the ``AutonomyPolicy`` class
        symbol some tests monkeypatch to stub ``decide``."""
        return resolve_covered_only(allow_weak=allow_weak, unattended=unattended)


def resolve_covered_only(*, allow_weak: bool, unattended: bool) -> bool:
    """The effective ``covered_only`` verification gate for an apply.

    COVERED-ONLY lands only moves a test actually EXERCISES (covered ⇒ verified)
    and PREVIEWS a green-but-unreferencing (WEAK) move — a green suite that merely
    IMPORTS a module can't vouch for a behaviour change there. ``--allow-weak`` is
    the risk-explicit opt-out that lands weak moves too.

    UNATTENDED (daemon / ``--evolve`` loop) forces covered-only UNCONDITIONALLY
    and REFUSES ``--allow-weak``: weak verification is exactly where an unattended
    loop turns into a SILENT regression risk (a Tier-1 behaviour change landed on
    a suite that never ran the code), so the opt-out is honoured ONLY in ATTENDED
    CLI mode, where a human is reviewing the diff. Pure (no I/O) so the caller
    supplies ``unattended``; ATTENDED is ``not allow_weak`` — byte-identical to
    the historical gate."""
    if unattended:
        return True
    return not allow_weak
