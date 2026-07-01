"""Idea learning memory — the engine grows wiser about *this* project over time.

The permutation engine is deterministic, but it need not be amnesiac. Each time
Apex applies fixes, the outcomes (which kinds of ideas actually landed cleanly vs.
rolled back vs. couldn't be applied) are recorded here, keyed by the development
lens (`operator`) or root seeding fact (`label`). On the next run the engine
consults this memory and gives a small, bounded feasibility nudge: lenses with a
strong track record on this codebase rise; ones that keep failing recede.

It is **opt-in by construction**: with no memory file, scoring is byte-identical
to a fresh engine (so determinism and every existing test are unaffected). The
nudge is bounded to ±10% and clamped, so memory shapes priorities without ever
overriding the grounded scores. Persisted to ``.apex/idea-memory.json``.

Beyond per-operator and per-label tallies, the memory also learns which
operator **sequences** work — credit assignment over compositions, not just
single steps. When operator B is applied right after operator A *landed* in the
same plan, the pair ``A>B`` records B's outcome; over time the engine learns
that ``test>harden`` tends to land (a stub shields the module, then the harden
sticks) while a different order blocks. This is the deterministic core that the
search/composition literature (GenProg's edit-list credit assignment,
MAP-Elites' per-cell archive) identifies as the missing piece for an agent that
already owns safe operators and a test oracle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any

MEMORY_REL = ".apex/idea-memory.json"

# z-score for the Wilson score interval used by the confidence-aware ranking.
# 1.96 ≈ a 95% two-sided normal quantile — a fixed constant (no scipy/statistics
# dependency), so the lower bound is fully deterministic. The lower bound of the
# interval is what we rank by: it shrinks toward 0 as samples shrink, so a
# 1-of-1 (rate 1.0, lb≈0.21) cannot outrank a 9-of-10 (rate 0.9, lb≈0.61).
_WILSON_Z = 1.96

# Bounded nudge: a perfect track record multiplies feasibility by at most this;
# a poor one divides by it. Small on purpose — memory tilts, never dictates.
_MAX_NUDGE = 0.10
# Don't trust a key until it has at least this many recorded outcomes.
_MIN_SAMPLES = 2
# Separator for a composition key "operatorA>operatorB" (ASCII, JSON-safe).
_SEQ_SEP = ">"
# Separator for a characteristic key "operator@trait" (ASCII, JSON-safe).
_CHAR_SEP = "@"

# Coarse, deterministic module-characteristic buckets. The trait key is derived
# from data the recorded outcome ALREADY carries — the seeding ``label`` (which
# encodes why the module was flagged: hub / untested / security / complexity)
# and the ``target`` path (a test file vs. app code). No new analysis, no new
# required inputs: the same lens that lands 9/10 on small leaf modules but rolls
# back 4/5 on hubs becomes learnable per-trait, not just per-lens.
#
# Ordered most-specific first; the FIRST matching substring wins so the bucket
# is a single deterministic value (a module is read as one coarse trait). A
# label that matches nothing maps to "" (no trait) and records/consults nothing
# extra — preserving the opt-in/byte-identical invariant.
_TRAIT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hub", ("hub", "fragile", "confluence", "convergence", "central")),
    ("security", ("security", "sensitive", "secret", "correctness")),
    ("untested", ("untested", "coverage", "shallow")),
    ("complex", ("hotspot", "complex", "churn", "debt")),
)


def _trait_key(label: str, target: str = "") -> str:
    """A coarse deterministic module-characteristic bucket, or "" for none.

    Derived purely from already-recorded context: the seeding ``label`` (why the
    module was flagged) and the ``target`` path. No time/random, no new inputs.
    A test-file target is a stable structural trait even without a label."""
    low = (label or "").lower()
    for trait, needles in _TRAIT_RULES:
        if any(n in low for n in needles):
            return trait
    tgt = (target or "").replace("\\", "/").lower()
    if "/tests/" in tgt or tgt.startswith("tests/") or "/test_" in tgt or "test_" in tgt.rsplit("/", 1)[-1]:
        return "testfile"
    return ""


@dataclass
class _Stat:
    applied: int = 0
    rolled_back: int = 0
    blocked: int = 0

    @property
    def total(self) -> int:
        return self.applied + self.rolled_back + self.blocked

    @property
    def success_rate(self) -> float:
        return self.applied / self.total if self.total else 0.0

    @property
    def confidence(self) -> float:
        """Wilson score interval lower bound on the success rate — an
        evidence-aware reliability read in [0, 1].

        Unlike the raw ``success_rate``, this discounts small samples: a lucky
        1-of-1 yields a low bound (≈0.21) while a well-attested 9-of-10 keeps a
        high one (≈0.61). Pure-stdlib (``math`` only), deterministic, and safe
        on zero samples (returns 0.0). More samples at the same rate strictly
        raise the bound, so it never penalises accumulated evidence."""
        n = self.total
        if n == 0:
            return 0.0
        z = _WILSON_Z
        phat = self.applied / n
        denom = 1.0 + z * z / n
        center = phat + z * z / (2.0 * n)
        margin = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n)
        return (center - margin) / denom

    def to_dict(self) -> dict[str, int]:
        return {"applied": self.applied, "rolled_back": self.rolled_back, "blocked": self.blocked}


@dataclass
class IdeaMemory:
    """Per-key outcome tallies that bias future feasibility scoring."""

    by_operator: dict[str, _Stat] = field(default_factory=dict)
    by_label: dict[str, _Stat] = field(default_factory=dict)
    # Composition credit: key "A>B" = operator B's outcome when applied right
    # after operator A landed in the same plan. Sequence-level learning.
    by_sequence: dict[str, _Stat] = field(default_factory=dict)
    # Characteristic credit: key "operator@trait" = a lens's outcome on a coarse
    # MODULE characteristic (hub / untested / security / complex / testfile). A
    # finer, additive learning dimension — "harden lands on leaves but rolls
    # back on hubs" — derived from already-recorded context (label/target).
    by_characteristic: dict[str, _Stat] = field(default_factory=dict)
    # Chain credit: key "chain:a>b>c" = the realized outcome of running an
    # EXPLICIT, ordered objective SEQUENCE (a ``chain_compiler`` campaign) — one
    # level above the adjacent-pair ``by_sequence`` signal. The key is the SAME
    # ordered signature ``chain_compiler`` archives under, so a whole ordered
    # recipe becomes learnable: "the chain ``implement-stub>cover-gaps`` held
    # 9-of-10 here". Populated ONLY by landed/halted chain runs (opt-in): with no
    # chain history this table is empty and every ranking is byte-identical.
    by_chain: dict[str, _Stat] = field(default_factory=dict)

    # --- persistence ---------------------------------------------------------

    @staticmethod
    def _load_table(data: dict[str, Any], key: str) -> dict[str, _Stat]:
        """Decode one persisted stat table by name. Backward-compatible: a missing
        (or null) key — an OLD file that predates ``by_sequence`` /
        ``by_characteristic`` / ``by_chain`` — decodes to an empty table."""
        return {k: _Stat(**v) for k, v in (data.get(key) or {}).items()}

    @classmethod
    def load(cls, project_root: str | Path, path: str | Path | None = None) -> IdeaMemory:
        p = Path(path) if path else Path(project_root) / MEMORY_REL
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls(
            by_operator=cls._load_table(data, "by_operator"),
            by_label=cls._load_table(data, "by_label"),
            by_sequence=cls._load_table(data, "by_sequence"),
            by_characteristic=cls._load_table(data, "by_characteristic"),
            by_chain=cls._load_table(data, "by_chain"),
        )

    def save(self, project_root: str | Path, path: str | Path | None = None) -> Path:
        p = Path(path) if path else Path(project_root) / MEMORY_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p

    def to_dict(self) -> dict[str, Any]:
        return {
            "by_operator": {k: v.to_dict() for k, v in sorted(self.by_operator.items())},
            "by_label": {k: v.to_dict() for k, v in sorted(self.by_label.items())},
            "by_sequence": {k: v.to_dict() for k, v in sorted(self.by_sequence.items())},
            "by_characteristic": {k: v.to_dict() for k, v in sorted(self.by_characteristic.items())},
            "by_chain": {k: v.to_dict() for k, v in sorted(self.by_chain.items())},
        }

    # --- recording -----------------------------------------------------------

    def record_outcomes(self, summary: dict[str, Any]) -> None:
        """Tally the results of an apply_plan/maintenance summary.

        Single-step credit goes to ``by_operator``/``by_label`` as before. A
        SEQUENCE credit ``A>B`` is recorded for each adjacent pair of
        development-operator steps in the plan's order, but only when the first
        step actually LANDED — so the pair captures "after A changed the code,
        did B stick?", the composition signal (not a coincidence of ordering)."""
        prev_op = ""           # last development operator seen
        prev_applied = False   # ...and whether it landed
        for r in summary.get("results", []) or []:
            outcome = "applied" if r.get("applied") else ("rolled_back" if r.get("rolled_back") else "blocked")
            op = r.get("operator") or ""
            label = r.get("label") or ""
            if op and op != "root":
                self._bump(self.by_operator, op, outcome)
                if prev_op and prev_applied:
                    self._bump(self.by_sequence, f"{prev_op}{_SEQ_SEP}{op}", outcome)
                self._record_characteristic(op, label, r.get("target") or "", outcome)
                prev_op = op
                prev_applied = outcome == "applied"
            if label:
                self._bump(self.by_label, label, outcome)

    def _record_characteristic(self, operator: str, label: str, target: str, outcome: str) -> None:
        """Credit a lens's outcome to the coarse module characteristic it acted
        on. Records nothing when no trait can be derived, so a run that carries
        no module context leaves ``by_characteristic`` empty (opt-in)."""
        trait = _trait_key(label, target)
        if trait:
            self._bump(self.by_characteristic, f"{operator}{_CHAR_SEP}{trait}", outcome)

    @staticmethod
    def _bump(table: dict[str, _Stat], key: str, outcome: str) -> None:
        stat = table.setdefault(key, _Stat())
        setattr(stat, outcome, getattr(stat, outcome) + 1)

    def record_chain_outcome(self, signature: str, outcome: str) -> None:
        """Tally ONE realized chain-campaign outcome under its ordered signature.

        ``signature`` is the SAME ``chain:a>b>c`` key ``chain_compiler`` archives
        under (the objective sequence, in source order); ``outcome`` is one of
        ``"applied"`` (the whole ordered chain HELD — every landed step's suite
        stayed green and nothing rolled back), ``"rolled_back"`` (a step's move
        regressed and was auto-rolled-back, halting the chain), or ``"blocked"``
        (the chain stopped for a non-regression reason, e.g. an opted-in
        precondition halt). Only a genuinely-held chain is an ``applied`` success,
        so a halted/rolled-back chain contributes as a NON-success and can never
        fake a win.

        A no-op on an empty ``signature`` or an unrecognised ``outcome`` (so a
        malformed call cannot silently miscredit), which — with the caller
        recording nothing for a dry run or an all-empty chain — keeps ``by_chain``
        empty and every ranking byte-identical until real chain history exists."""
        if not signature or outcome not in ("applied", "rolled_back", "blocked"):
            return
        self._bump(self.by_chain, signature, outcome)

    # --- influence on scoring ------------------------------------------------

    @staticmethod
    def _nudge_from(stat: _Stat | None) -> float:
        """The bounded nudge ``delta`` in [-_MAX_NUDGE, +_MAX_NUDGE] a stat
        implies (0.0 = neutral). Too few samples → 0.0 (no opinion yet)."""
        if stat is None or stat.total < _MIN_SAMPLES:
            return 0.0
        # success_rate 0.5 → 0; 1.0 → +_MAX_NUDGE; 0.0 → -_MAX_NUDGE.
        return (stat.success_rate - 0.5) * 2.0 * _MAX_NUDGE

    def feasibility_factor(self, operator: str, label: str = "",
                           target: str = "", characteristic: str | None = None) -> float:
        """A bounded multiplier in [1-_MAX_NUDGE, 1+_MAX_NUDGE] from track record.

        Roots are keyed by their seeding ``label``; other ideas by ``operator``.
        Keys with too few samples contribute nothing (no opinion yet).

        Additive finer dimension (opt-in): when a coarse module characteristic
        can be derived (from ``characteristic`` if given, else from
        ``label``/``target``) AND the ``operator@trait`` cell has enough samples,
        its nudge is BLENDED with the lens/label nudge by averaging the two
        deltas. Averaging keeps the combined nudge inside the SAME bounded
        ±_MAX_NUDGE range the lens nudge already used, so scores never leave
        [0,1] and ordering stays stable. With no characteristic cell recorded,
        the average is over a single delta — byte-identical to before."""
        base = None
        if operator and operator != "root" and operator in self.by_operator:
            base = self.by_operator[operator]
        elif label and label in self.by_label:
            base = self.by_label[label]
        deltas = [self._nudge_from(base)]
        char_delta = self._characteristic_nudge(operator, label, target, characteristic)
        if char_delta is not None:
            deltas.append(char_delta)
        combined = sum(deltas) / len(deltas)
        return round(1.0 + combined, 4)

    def _characteristic_nudge(self, operator: str, label: str, target: str,
                              characteristic: str | None) -> float | None:
        """The characteristic cell's bounded delta, or ``None`` when there is no
        trait to read or its cell lacks samples — so it contributes nothing and
        the combined nudge collapses to the lens-only behaviour (opt-in)."""
        if not operator or operator == "root":
            return None
        trait = characteristic if characteristic is not None else _trait_key(label, target)
        if not trait:
            return None
        stat = self.by_characteristic.get(f"{operator}{_CHAR_SEP}{trait}")
        if stat is None or stat.total < _MIN_SAMPLES:
            return None
        return self._nudge_from(stat)

    def sequence_factor(self, prev_operator: str, operator: str) -> float:
        """A bounded multiplier from the track record of running ``operator``
        right after ``prev_operator`` landed — composition-level credit. Neutral
        1.0 when there is no prior operator or too few samples for the pair.

        A future composition planner consults this to prefer orderings the
        engine has *seen work* on this codebase (e.g. test>harden over
        harden>test), exactly as ``feasibility_factor`` biases single steps."""
        if not prev_operator or not operator:
            return 1.0
        stat = self.by_sequence.get(f"{prev_operator}{_SEQ_SEP}{operator}")
        if stat is None or stat.total < _MIN_SAMPLES:
            return 1.0
        return round(1.0 + (stat.success_rate - 0.5) * 2.0 * _MAX_NUDGE, 4)

    @classmethod
    def learn_from(cls, summary: dict[str, Any], project_root: str | Path,
                   path: str | Path | None = None) -> IdeaMemory:
        """Load → record this run's outcomes → save. The full learning step."""
        mem = cls.load(project_root, path)
        mem.record_outcomes(summary)
        mem.save(project_root, path)
        return mem

    def confident_ranking(self, table: str = "operator", *, best: bool = True,
                          limit: int = 5) -> list[dict[str, Any]]:
        """Rank tracked keys by evidence-aware reliability (Wilson lower bound).

        Unlike the raw-rate ordering in ``summary``'s ``most_reliable``, this
        accounts for sample size: a 9-of-10 (90%, lb≈0.61) outranks a lucky
        1-of-1 (100%, lb≈0.21). ``table`` is ``"operator"`` (default),
        ``"label"``, ``"sequence"``, ``"characteristic"``, or ``"chain"`` (whole
        ordered objective-sequence recipes). ``best=False`` returns the least
        reliable. Empty/zero-sample tables are safe (return ``[]``) — so a fresh
        project with no chain history ranks nothing here (byte-identical).

        Deterministic ordering: by confidence, then sample count, then key as a
        stable tiebreak. Stdlib-only math; no time/random."""
        tables = {"operator": self.by_operator, "label": self.by_label,
                  "sequence": self.by_sequence, "characteristic": self.by_characteristic,
                  "chain": self.by_chain}
        src = tables.get(table, self.by_operator)
        seen = [(k, s) for k, s in src.items() if s.total >= _MIN_SAMPLES]
        # Confidence and sample count descend for `best`; key always ascends as a
        # stable final tiebreak so ordering is fully deterministic either way.
        seen.sort(key=lambda kv: kv[0])
        seen.sort(key=lambda kv: (kv[1].confidence, kv[1].total), reverse=best)
        out = seen if limit is None or limit < 0 else seen[:limit]
        return [{"key": k, "confidence": round(s.confidence, 4),
                 "success_rate": round(s.success_rate, 3), "samples": s.total}
                for k, s in out]

    def summary(self) -> dict[str, Any]:
        """A compact, human-facing view of what the engine has learned."""
        def _top(table: dict[str, _Stat], best: bool) -> list[dict[str, Any]]:
            seen = [(k, s) for k, s in table.items() if s.total >= _MIN_SAMPLES]
            seen.sort(key=lambda kv: (kv[1].success_rate, kv[1].total), reverse=best)
            return [{"key": k, "success_rate": round(s.success_rate, 3), "samples": s.total}
                    for k, s in seen[:5]]

        return {
            "operators_tracked": len(self.by_operator),
            "labels_tracked": len(self.by_label),
            "sequences_tracked": len(self.by_sequence),
            "characteristics_tracked": len(self.by_characteristic),
            "chains_tracked": len(self.by_chain),
            "most_reliable": _top(self.by_operator, best=True),
            "least_reliable": _top(self.by_operator, best=False),
            "reliable_sequences": _top(self.by_sequence, best=True),
            "reliable_characteristics": _top(self.by_characteristic, best=True),
            "reliable_chains": _top(self.by_chain, best=True),
            # Evidence-aware view (Wilson lower bound) — new, additive keys; the
            # raw-rate keys above are unchanged so existing callers/tests hold.
            "most_confident": self.confident_ranking("operator", best=True),
            "least_confident": self.confident_ranking("operator", best=False),
        }
