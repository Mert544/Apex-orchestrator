"""Native intelligence — EXPERIENCE memory: which learned idioms have actually
landed real code here, recency-weighted, so the native lane ranks by proof, not
just by how common a shape is in the corpus.

The native intelligence (:mod:`app.engine.native_synth`) proposes candidate
bodies learned from the project's own functions; the develop loop lands the ones
that pass the never-fake-green gate. THIS module remembers those landings — per
canonical idiom shape (``p0 + p1``, ``max(p1, min(p0, p2))`` …) — so a shape that
has repeatedly, RECENTLY finished real stubs here is preferred next time. It is
the "experience" layer on top of the "knowledge" the corpus already gives.

Two guards keep old experience from misleading new decisions (the reason a raw
running tally would rot):

* **Generational decay** — each landing carries a monotonically increasing
  ``gen``. Scoring weights a record by ``_DECAY ** (rank_from_newest)`` over the
  distinct generations in play, so the newest generation weighs ``1.0`` and older
  ones fade geometrically (mirrors ``proof_history.learned_reliability_decayed``).
  A shape that stopped landing several generations ago fades on its own.
* **Version boundary** — ``set_baseline`` records a ``baseline`` generation below
  which every record is IGNORED. After a real architectural change (a refactor
  that invalidates old proofs), one ``set_baseline`` call retires the whole prior
  experience without deleting the audit trail — so a body that was reliable under
  the old design can never mislead the new one.

Pure and deterministic: same JSON → same scores (no clock/random; ``gen`` is a
stored counter, not a timestamp). Missing dir / unreadable / malformed / wrong
schema are tolerated by treating the memory as empty; never raises. Zero-token.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "apex-native-mind-experience/v1"
_REL = ".apex/native-mind-experience.json"

# Rank-based generational forgetting — identical constant/rationale to
# ``proof_history._DECAY``: the newest generation weighs 1.0, each older one
# discounts by this factor (0.85**5 ≈ 0.44 keeps ~5 generations materially live).
_DECAY = 0.85

__all__ = [
    "load_experience",
    "record_native_landing",
    "set_baseline",
    "decayed_reliability",
]


def _path(root: str | Path) -> Path:
    return Path(root) / _REL


def load_experience(root: str | Path) -> dict:
    """The stored experience, or a fresh empty one. Tolerates a missing file,
    unreadable bytes, malformed JSON, or a wrong/absent schema by returning the
    empty shape ``{"schema", "baseline": 0, "records": []}`` — never raises."""
    empty = {"schema": SCHEMA, "baseline": 0, "records": []}
    try:
        data = json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return empty
    records = data.get("records")
    baseline = data.get("baseline")
    if not isinstance(records, list) or not isinstance(baseline, int):
        return empty
    clean = [
        {"shape": r["shape"], "gen": r["gen"]}
        for r in records
        if isinstance(r, dict) and isinstance(r.get("shape"), str)
        and isinstance(r.get("gen"), int)
    ]
    return {"schema": SCHEMA, "baseline": baseline, "records": clean}


def _max_gen(mem: dict) -> int:
    """The highest generation recorded so far (``baseline`` when there are no
    records), so a new landing and a new baseline both advance monotonically."""
    return max((r["gen"] for r in mem["records"]), default=mem["baseline"])


def _write(root: str | Path, mem: dict) -> None:
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA, "baseline": mem["baseline"],
                    "records": mem["records"]}, indent=2, sort_keys=True),
        encoding="utf-8")


def record_native_landing(root: str | Path, shapes: list[str]) -> None:
    """Remember that ``shapes`` (canonical idiom shapes) each landed real code in
    ONE apply — a single new generation, so this apply's shapes share a ``gen``
    and later fade together. A no-op for an empty ``shapes`` (nothing to record),
    so the store only grows on a genuine native-only landing. Deterministic: the
    new generation is ``_max_gen + 1`` (a stored counter, never a clock)."""
    if not shapes:
        return
    mem = load_experience(root)
    gen = _max_gen(mem) + 1
    for shape in shapes:
        mem["records"].append({"shape": shape, "gen": gen})
    _write(root, mem)


def set_baseline(root: str | Path) -> int:
    """Retire ALL current experience from future scoring: set ``baseline`` to just
    past the newest generation, so every existing record is ignored by
    :func:`decayed_reliability` (the version boundary for a post-architectural
    change). The records are kept for audit — only their influence is dropped.
    Returns the new baseline generation."""
    mem = load_experience(root)
    mem["baseline"] = _max_gen(mem) + 1
    _write(root, mem)
    return mem["baseline"]


def decayed_reliability(root: str | Path) -> dict[str, float]:
    """Recency-weighted landing score per canonical idiom shape, in shape order.

    Records with ``gen < baseline`` are dropped (the version boundary). The
    remaining distinct generations are ranked oldest→newest; a record at rank
    ``i`` of ``n`` weighs ``_DECAY ** (n-1-i)`` (newest = ``1.0``). A shape's score
    is the sum of its records' weights — so a shape that landed often and recently
    outranks one that landed long ago. Empty/missing memory → ``{}``; never
    raises. Pure rank arithmetic, so identical content yields an identical map."""
    mem = load_experience(root)
    live = [r for r in mem["records"] if r["gen"] >= mem["baseline"]]
    if not live:
        return {}
    gens = sorted({r["gen"] for r in live})
    n = len(gens)
    weight_of = {g: _DECAY ** (n - 1 - i) for i, g in enumerate(gens)}
    scores: dict[str, float] = {}
    for r in live:
        scores[r["shape"]] = scores.get(r["shape"], 0.0) + weight_of[r["gen"]]
    return {shape: round(scores[shape], 6) for shape in sorted(scores)}
