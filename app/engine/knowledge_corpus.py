"""Cross-project knowledge corpus — Apex learns GLOBALLY, not just per-project.

``proof_history.py`` learns what fixes land on *one* project from its proof
artifacts; ``idea_memory.py`` learns per-project lens/characteristic reliability.
Both are scoped to a single repository. This module is the layer *above* them: a
persistent, deterministic store that accumulates fix-outcome evidence across many
projects and runs, keyed not by a module path or a lens name (which are
project-local) but by a coarse, language-agnostic **code-shape signature** — a
canonical description of the *kind* of code a fix touched (a hub? untested?
large? carrying a security finding? what action type?). Two different projects
that both harden an untested hub contribute to the SAME signature, so Apex's
reliability read for "harden an untested hub" grows wiser the more projects it
sees.

Everything here is **pure and deterministic**: the signature is a sorted,
canonical key; folding outcomes and merging runs are commutative count
accumulations; ``consult`` is a bounded [0, 1] ratio with no time/random in any
value that affects it. Persistence is tolerant JSON: a missing or malformed file
yields an empty corpus and never raises, and ``save`` emits ``sort_keys`` output
so the same corpus is byte-identical on disk every time. An empty corpus gives
neutral (zero-evidence) results. Counts are bounded so a long-lived corpus can
never overflow or let one runaway signature dominate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Schema tag + version stamped into the persisted file so a reader can validate
# what it loaded (mirrors proof_of_fix.SCHEMA/SCHEMA_VERSION). A file whose
# schema does not match is treated as malformed → empty corpus.
SCHEMA = "apex-knowledge-corpus"
SCHEMA_VERSION = "1.0"

# Default on-disk location. Tests ALWAYS pass an explicit path (a tmp_path) so we
# never read or write a real user home.
DEFAULT_CORPUS_PATH = "~/.apex/knowledge-corpus.json"

# The three terminal outcomes a fix can have — identical vocabulary to
# proof_of_fix / proof_history / idea_memory, so ingestion is a direct fold.
_OUTCOMES = ("applied", "rolled_back", "blocked")

# Upper bound on any single stored count. Accumulating across unbounded runs
# could otherwise grow without limit; clamping keeps the JSON small and bounded
# while preserving the reliability RATIO (each outcome is clamped identically, so
# the ratio is stable once a signature is well-attested). Deterministic.
_MAX_COUNT = 1_000_000

# Boolean shape features (coarse, language-agnostic) emitted into the signature
# only when TRUE — so the key lists exactly the shape traits a fix touched, in a
# fixed order, and absent/false traits never appear. Already available on a
# profile or fix record. Ordered so the canonical key is stable.
_SHAPE_FLAGS = (
    "is_hub",
    "is_untested",
    "is_large",
    "has_security_finding",
)

# A stable placeholder for a missing action type, so an action-less record still
# produces a deterministic signature rather than a different key shape.
_UNKNOWN_ACTION = "unknown"

# Separator between the action token and the sorted shape tokens in a signature.
_FIELD_SEP = "|"
# Separator between individual shape tokens.
_TOKEN_SEP = ","


def _as_bool(value: Any) -> bool:
    """Coerce a feature value to a plain bool. Tolerates the loose truthiness a
    profile/fix record might carry (1/0, "true"/"false", None) deterministically."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _action_token(features: dict) -> str:
    """The normalised action-type token for the signature, or a stable
    placeholder. Lower-cased and stripped so ``"Harden"`` and ``"harden "`` fold
    to one key — canonicalisation, not new information."""
    raw = features.get("action_type")
    token = str(raw).strip().lower() if raw is not None else ""
    return token or _UNKNOWN_ACTION


def code_shape_signature(features: dict) -> str:
    """A deterministic, stable key describing the SHAPE of code a fix touched.

    Built from a small set of coarse, language-agnostic features already present
    on a profile or fix record: the ``action_type`` and the boolean shape flags
    in ``_SHAPE_FLAGS`` (``is_hub``, ``is_untested``, ``is_large``,
    ``has_security_finding``). The key is canonical — the action token, then a
    SORTED list of exactly the true shape tokens — so feature-dict ordering,
    truthiness spelling, and casing never change the result. Same features →
    same signature, byte-for-byte. A record with no shape flags set yields a
    pure ``"action|"`` key (action-only), still deterministic."""
    feats = features or {}
    present = sorted(flag for flag in _SHAPE_FLAGS if _as_bool(feats.get(flag)))
    return f"{_action_token(feats)}{_FIELD_SEP}{_TOKEN_SEP.join(present)}"


def _blank_tally() -> dict[str, int]:
    """A fresh per-signature counter with one slot per terminal outcome."""
    return {outcome: 0 for outcome in _OUTCOMES}


def new_corpus() -> dict[str, Any]:
    """A fresh, empty corpus dict (schema-tagged, no signatures)."""
    return {"schema": SCHEMA, "version": SCHEMA_VERSION, "signatures": {}}


def _signatures(corpus: dict) -> dict[str, dict[str, int]]:
    """The signature→tally sub-map of a corpus, created on first access. Tolerant
    of a corpus that lost (or never had) the key."""
    sigs = corpus.get("signatures")
    if not isinstance(sigs, dict):
        sigs = {}
        corpus["signatures"] = sigs
    return sigs


def _clamp_count(value: int) -> int:
    """Clamp one outcome count into ``[0, _MAX_COUNT]`` — bounded accumulation."""
    if value < 0:
        return 0
    if value > _MAX_COUNT:
        return _MAX_COUNT
    return value


def _add_counts(target: dict[str, int], counts: dict[str, int]) -> None:
    """Fold ``counts`` into ``target`` in place, per outcome, clamped bounded.

    Only the three terminal outcomes are read, so an unexpected key in ``counts``
    is ignored rather than polluting the tally. Deterministic and commutative."""
    for outcome in _OUTCOMES:
        added = counts.get(outcome, 0)
        added = added if isinstance(added, int) and added > 0 else 0
        target[outcome] = _clamp_count(target.get(outcome, 0) + added)


def record_outcome(corpus: dict, signature: str, outcome: str) -> dict:
    """Fold a single fix ``outcome`` for ``signature`` into the corpus in place.

    An out-of-vocabulary outcome is folded into ``blocked`` (same convention as
    proof_history) so it still counts as a non-landing rather than vanishing.
    Counts are bounded by ``_MAX_COUNT``. Returns the corpus for chaining."""
    bucket = outcome if outcome in _OUTCOMES else "blocked"
    tally = _signatures(corpus).setdefault(signature, _blank_tally())
    tally[bucket] = _clamp_count(tally.get(bucket, 0) + 1)
    return corpus


def _ingest_group(corpus: dict, group: Any) -> None:
    """Merge one proof-history breakdown group (e.g. ``by_action``) into the
    corpus. Each group is ``{key: {applied, rolled_back, blocked, ...}}``; the
    breakdown KEY is reused verbatim as the signature so cross-run aggregation is
    keyed consistently. Non-dict groups/rows are skipped — tolerant."""
    if not isinstance(group, dict):
        return
    sigs = _signatures(corpus)
    for signature, counts in group.items():
        if isinstance(counts, dict):
            _add_counts(sigs.setdefault(str(signature), _blank_tally()), counts)


def merge_run(corpus: dict, proof_history_summary: dict) -> dict:
    """Ingest one project's proof-history summary into the corpus, keyed by
    signature. Reads the ``by_action`` breakdown produced by
    ``proof_history.summarise_fix_track_record`` — each action key is a coarse,
    project-independent signature, and its applied/rolled_back/blocked counts are
    folded in. Missing or malformed summaries contribute nothing (tolerant), and
    the fold is commutative so merge order never changes the result. Returns the
    corpus for chaining."""
    summary = proof_history_summary or {}
    _ingest_group(corpus, summary.get("by_action"))
    return corpus


def _reliability(tally: dict[str, int]) -> float:
    """Share of decided outcomes that LANDED — applied / total, bounded [0, 1].

    Zero total is a neutral ``0.0`` (no global evidence yet), never a division
    error. Rounded for a stable, comparable value."""
    total = sum(_clamp_count(tally.get(o, 0)) for o in _OUTCOMES)
    if total <= 0:
        return 0.0
    return round(_clamp_count(tally.get("applied", 0)) / total, 4)


def consult(corpus: dict, signature: str) -> dict:
    """What Apex has learned GLOBALLY about fixing this shape of code.

    Returns the accumulated, bounded ``reliability`` in [0, 1] and the
    ``samples`` size (total decided outcomes) for ``signature``, plus the raw
    per-outcome counts. An unknown signature (or an empty corpus) yields a
    neutral zero-evidence result — ``reliability 0.0``, ``samples 0`` — never
    raising. No time/random influences the output, so it is deterministic."""
    tally = _signatures(corpus).get(signature) or _blank_tally()
    counts = {o: _clamp_count(tally.get(o, 0)) for o in _OUTCOMES}
    return {
        "signature": signature,
        "reliability": _reliability(counts),
        "samples": sum(counts.values()),
        **counts,
    }


def _normalise(corpus: Any) -> dict:
    """Coerce a loaded object into a well-formed corpus, clamping every count and
    dropping malformed rows. Anything unrecognised collapses to an empty corpus —
    so a tampered or partial file is tolerated, not propagated."""
    out = new_corpus()
    if not isinstance(corpus, dict) or corpus.get("schema") != SCHEMA:
        return out
    sigs = out["signatures"]
    for signature, counts in (corpus.get("signatures") or {}).items():
        if isinstance(counts, dict):
            tally = _blank_tally()
            _add_counts(tally, counts)
            sigs[str(signature)] = tally
    return out


def load_corpus(path: str | Path = DEFAULT_CORPUS_PATH) -> dict:
    """Read a corpus from ``path``, tolerating every failure. A missing file,
    unreadable file, malformed JSON, or wrong/absent schema all yield a fresh
    empty corpus — never raises. ``~`` is expanded so the default home path
    works. Loaded counts are clamped/normalised so a hand-edited file cannot push
    a value out of bounds."""
    p = Path(path).expanduser()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return new_corpus()
    return _normalise(data)


def save_corpus(corpus: dict, path: str | Path = DEFAULT_CORPUS_PATH) -> Path:
    """Persist ``corpus`` to ``path`` as deterministic JSON. The corpus is
    normalised first (schema-tagged, clamped) and written with ``sort_keys`` so
    the same logical corpus is BYTE-IDENTICAL on disk every time — no time/random
    in the file. Creates parent directories. Returns the written path."""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_normalise(corpus), indent=2, sort_keys=True)
    p.write_text(text + "\n", encoding="utf-8")
    return p
