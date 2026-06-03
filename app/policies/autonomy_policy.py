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
      3. Nothing safe to do → recommend.
      4. A dirty working tree → recommend (don't mix Apex's edits into a WIP
         tree the user can't cleanly review/undo); tell them how to proceed.
      5. Otherwise (clean tree + safe verified fixes) → apply autonomously,
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
    ) -> AutonomyDecision:
        if explicit_recommend:
            return AutonomyDecision(False, "report", "recommend-only requested")
        if explicit_apply:
            mode = "autonomous" if commit else "supervised"
            return AutonomyDecision(True, mode, "apply explicitly requested")
        if executable_steps <= 0:
            return AutonomyDecision(False, "report", "no safe, auto-applicable fixes found")
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
