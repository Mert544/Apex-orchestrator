"""Proof-replay — a second, independent honesty check on a proof artifact.

``proof_of_fix.py`` already content-addresses every proof and seals it with a
tamper hash: it proves a record is IMMUTABLE (no byte moved since it was
written). It does NOT check whether a record's own recorded claims actually
*agree with each other*. A forged-but-internally-inconsistent proof — a diff
whose file headers name files that aren't in ``changed_files``, a risk tier that
doesn't match what the risk-tier policy would assign, a hunk header that doesn't
parse — would still carry a perfectly valid tamper hash, because the hash only
guarantees the lie wasn't edited *after* it was sealed.

This module is the complement: given a proof artifact (the kind ``write_proof``
emits and archives under ``.apex/``), it REPLAYS each record's internal claims
and confirms they are mutually consistent, raising the cost of faking a green
proof. It is a pure, read-only side-car:

  - it never writes a file and never touches the target repo's working tree;
  - it reuses the EXISTING archive loader (``proof_history.load_proof_history``)
    and the EXISTING tier policy (``app.execution.risk_tiers.tier_for``) rather
    than reimplementing either;
  - it is byte-deterministic — sorted outputs, no wall-clock, no randomness;
  - it never raises: a malformed record yields a discrepancy descriptor, exactly
    as the rest of the proof layer is best-effort per record.

The output is a small verdict dict per record — an overall ``replay_ok: bool``
plus a deterministically sorted list of ``{"kind", "detail"}`` discrepancy
descriptors — so a CI gate or a buyer can pin a *second* signal that is
independent of the tamper hash.
"""

from __future__ import annotations

from typing import Any

from app.engine.proof_history import load_proof_history
from app.execution.risk_tiers import tier_for

# The discrepancy ``kind`` vocabulary, fixed so callers can match on stable
# tokens. Each is raised by exactly one consistency check below.
DIFF_FILE_MISMATCH = "diff_file_mismatch"      # diff headers ≠ changed_files
TIER_MISMATCH = "tier_mismatch"                # recorded tier ≠ policy tier
MALFORMED_HUNK = "malformed_hunk"              # @@ header that doesn't parse
MALFORMED_RECORD = "malformed_record"          # the record isn't a usable dict


def _discrepancy(kind: str, detail: str) -> dict[str, str]:
    """One discrepancy descriptor — a stable two-field dict."""
    return {"kind": kind, "detail": detail}


def _sorted_discrepancies(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """Deterministically order discrepancies by ``(kind, detail)``.

    Two checks can fire on one record; sorting by the descriptor's own fields
    makes the result byte-identical regardless of the order the checks ran."""
    return sorted(items, key=lambda d: (d.get("kind", ""), d.get("detail", "")))


def _diff_header_files(diff: str) -> list[str]:
    """The set of files a unified diff CLAIMS to touch, as a sorted list.

    Recognises the two header forms ``proof_of_fix`` / the apply path emit:
      - ``--- a/<rel>`` / ``+++ b/<rel>`` (the ``difflib.unified_diff`` headers);
      - ``(new file) b/<rel>`` (the placeholder used when an old side is empty).
    The ``a/`` / ``b/`` prefix is stripped so the name compares against the bare
    relative path recorded in ``changed_files``. The ``+++`` side is the
    authoritative post-change name (a rename would differ from ``---``); we read
    both and union them so neither side can hide a file. A trailing tab-delimited
    timestamp (``\\t...``) is dropped. Deduped + sorted: deterministic."""
    files: set[str] = set()
    for raw in (diff or "").splitlines():
        line = raw.rstrip("\n")
        rel: str | None = None
        if line.startswith("--- ") or line.startswith("+++ "):
            rel = line[4:]
        elif line.startswith("(new file) "):
            rel = line[len("(new file) "):]
        if rel is None:
            continue
        # difflib appends an optional ``\t<meta>`` after the path; drop it.
        rel = rel.split("\t", 1)[0].strip()
        if rel in ("", "/dev/null"):
            continue
        if rel.startswith("a/") or rel.startswith("b/"):
            rel = rel[2:]
        if rel:
            files.add(rel)
    return sorted(files)


def _check_diff_files(record: dict) -> list[dict[str, str]]:
    """The diff's header files must MATCH the recorded ``changed_files``.

    If a record carries no diff (an annotation-only or blocked record may not),
    there is nothing to cross-check and no discrepancy. When a diff IS present,
    every file it names must appear in ``changed_files`` and vice-versa — a
    forged diff that quietly references an unlisted file (or omits a listed one)
    is flagged. Comparison is over sorted, deduped sets so order never matters."""
    diff = record.get("diff")
    if not isinstance(diff, str) or not diff.strip():
        return []
    header_files = _diff_header_files(diff)
    if not header_files:
        # A diff with body lines but no recognisable file header is itself a
        # consistency failure: we cannot prove it touches what it claims.
        return [_discrepancy(
            DIFF_FILE_MISMATCH,
            "diff carries no recognisable file header")]
    changed = record.get("changed_files") or []
    recorded = sorted({str(f) for f in changed if isinstance(f, str)})
    out: list[dict[str, str]] = []
    for f in header_files:
        if f not in recorded:
            out.append(_discrepancy(
                DIFF_FILE_MISMATCH,
                f"diff touches {f} not in changed_files"))
    for f in recorded:
        if f not in header_files:
            out.append(_discrepancy(
                DIFF_FILE_MISMATCH,
                f"changed_files lists {f} not in diff"))
    return out


def _check_tier(record: dict) -> list[dict[str, str]]:
    """The recorded ``risk_tier`` must MATCH what the tier policy assigns.

    The proof records both the action it cited (``finding.action``) and a
    ``risk_tier`` integer. The authoritative tier for that action is whatever
    ``risk_tiers.tier_for`` returns — the single source of truth, reused here so
    the check can never drift from the policy. A record whose stored tier
    disagrees with the policy (a forged "this risky rewrite was actually Tier 0")
    is flagged. A record with no recorded tier is not cross-checked (nothing was
    claimed)."""
    if record.get("risk_tier") is None:
        return []
    recorded_tier = record.get("risk_tier")
    if not isinstance(recorded_tier, int) or isinstance(recorded_tier, bool):
        return [_discrepancy(
            TIER_MISMATCH,
            f"risk_tier is not an integer: {recorded_tier!r}")]
    finding = record.get("finding")
    action = ""
    if isinstance(finding, dict):
        action = str(finding.get("action") or "")
    policy_tier = tier_for(action)
    if recorded_tier != policy_tier:
        return [_discrepancy(
            TIER_MISMATCH,
            f"action {action or '<none>'} recorded tier {recorded_tier} "
            f"but policy tier is {policy_tier}")]
    return []


def _check_hunks(record: dict) -> list[dict[str, str]]:
    """Every ``@@ ... @@`` hunk header in the diff must parse cleanly.

    A unified-diff hunk header is ``@@ -<start>[,<len>] +<start>[,<len>] @@``.
    A record that claims a diff but carries a hunk header that doesn't match this
    grammar is internally malformed — its own evidence can't be replayed — so it
    is flagged. No diff, or a diff with no hunk headers, raises nothing."""
    diff = record.get("diff")
    if not isinstance(diff, str) or not diff.strip():
        return []
    out: list[dict[str, str]] = []
    for raw in diff.splitlines():
        line = raw.rstrip("\n")
        if not line.startswith("@@"):
            continue
        if not _hunk_header_ok(line):
            out.append(_discrepancy(
                MALFORMED_HUNK,
                f"unparseable hunk header: {line.strip()}"))
    return out


def _hunk_header_ok(line: str) -> bool:
    """True iff ``line`` is a well-formed ``@@ -a,b +c,d @@`` hunk header.

    Parsed by hand (no regex) so the grammar is explicit: between the opening
    and closing ``@@`` there must be exactly a ``-`` range and a ``+`` range,
    each ``<int>`` or ``<int>,<int>``. Anything else is malformed."""
    body = line.strip()
    if not body.startswith("@@"):
        return False
    body = body[2:]
    close = body.find("@@")
    if close < 0:
        return False
    inner = body[:close].strip()
    parts = inner.split()
    if len(parts) != 2:
        return False
    minus, plus = parts
    return _range_ok(minus, "-") and _range_ok(plus, "+")


def _range_ok(token: str, sign: str) -> bool:
    """True iff ``token`` is ``<sign><int>`` or ``<sign><int>,<int>``."""
    if not token.startswith(sign):
        return False
    nums = token[1:]
    if not nums:
        return False
    for piece in nums.split(",", 1):
        if not piece.isdigit():
            return False
    return True


def replay_proof(proof: dict) -> dict:
    """Replay one proof artifact's internal claims and report consistency.

    Returns a deterministic verdict dict::

        {"replay_ok": bool,
         "records": int,            # how many fix records were checked
         "discrepancies": [{"kind": ..., "detail": ...}, ...]}

    ``replay_ok`` is ``True`` exactly when no discrepancy was found across every
    record. The ``discrepancies`` list is sorted by ``(kind, detail)`` so the
    output is byte-identical for identical input. Read-only and total: a proof
    that isn't a dict, or a record that isn't a dict, yields a ``MALFORMED_*``
    discrepancy rather than raising — best-effort per record, like the rest of
    the proof layer."""
    discrepancies: list[dict[str, str]] = []
    records: list[Any]
    if not isinstance(proof, dict):
        return {
            "replay_ok": False,
            "records": 0,
            "discrepancies": [_discrepancy(
                MALFORMED_RECORD, "proof is not a dict")],
        }
    raw_records = proof.get("fixes")
    records = list(raw_records) if isinstance(raw_records, list) else []
    checked = 0
    for record in records:
        if not isinstance(record, dict):
            discrepancies.append(_discrepancy(
                MALFORMED_RECORD, "fix record is not a dict"))
            continue
        checked += 1
        discrepancies.extend(_check_diff_files(record))
        discrepancies.extend(_check_tier(record))
        discrepancies.extend(_check_hunks(record))
    sorted_discrepancies = _sorted_discrepancies(discrepancies)
    return {
        "replay_ok": not sorted_discrepancies,
        "records": checked,
        "discrepancies": sorted_discrepancies,
    }


def replay_history(root: str) -> list[dict]:
    """Replay every archived proof under ``<root>/.apex/`` — a batch verdict.

    Loads the proof artifacts via the EXISTING deterministic loader
    (``proof_history.load_proof_history``: sorted by ``generated_at`` then
    filename, schema-validated, deduped, malformed files skipped) and runs
    :func:`replay_proof` on each, preserving the loader's order. A missing or
    empty ``.apex`` directory yields ``[]``. Read-only and never raises: the
    loader already tolerates unreadable/malformed files, and each per-proof
    replay is itself total."""
    try:
        history = load_proof_history(root)
    except Exception:
        return []
    return [replay_proof(proof) for proof in history]
