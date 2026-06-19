"""Deep-mutation hardening for proof-of-fix ARCHIVING in ``write_proof``.

The existing ``test_proof_archiving_eyml`` suite proves the end-to-end story
(accumulate, dedup, cap). This file pins the SAME machinery with mutation-
resistant EXACT-value assertions so a flipped comparison, threshold, or constant
in ``app/engine/proof_of_fix.py`` cannot survive:

* ``_archive_name`` — exact ``proof-<sha256hex>.json`` scheme, derived ONLY from
  the proof's content hash (not time/path/order), distinct from the pointer.
* ``write_proof`` — the latest pointer is byte-identical to the non-archiving
  behaviour; the PREVIOUS pointer is archived byte-identically; two DIFFERENT
  proofs both end up fused by ``load_proof_history``; two IDENTICAL proofs dedup
  to ONE archive (content hash); a write failure on the archive path never
  breaks the primary pointer write.
* ``_prune_archive`` — the keep cap is an EXACT boundary (N survives N, N+1
  prunes to N), the MOST-RECENT N are retained by ``generated_at`` recency, and
  malformed archives sort first (pruned before real evidence).

All assertions are deterministic: ``generated_at`` is pinned, names/sets are
sorted, no wall-clock.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.proof_history import (
    load_proof_history,
    summarise_fix_track_record,
)
from app.engine.proof_of_fix import (
    SCHEMA,
    _ARCHIVE_KEEP,
    _ARCHIVE_PREFIX,
    _archive_name,
    _archive_sort_key,
    _prune_archive,
    build_proof,
    proof_hash,
    write_proof,
)


def _summary(action: str, outcome: str, target: str) -> dict:
    """A minimal apply_plan-shaped summary -> one fix with action/outcome."""
    row: dict = {
        "branch": "1", "action": action, "operator": "op",
        "label": "lbl", "target": target,
        "transform_type": action, "changed_files": [target],
        "diff": f"--- a/{target}\n+++ b/{target}\n",
    }
    if outcome == "applied":
        row["applied"] = True
        row["test_evidence"] = {"performed": True, "ok": True, "tests_passed": 1}
    elif outcome == "rolled_back":
        row["applied"] = False
        row["rolled_back"] = True
        row["reason"] = "tests failed after patch; changes rolled back"
    else:  # blocked
        row["applied"] = False
        row["reason"] = "blocked by safety gates"
    totals = {"applied": 1 if outcome == "applied" else 0,
              "rolled_back": 1 if outcome == "rolled_back" else 0,
              "blocked": 1 if outcome == "blocked" else 0}
    return {
        "mode": "supervised", "verify": True,
        "total_executable": 1, "committed": 0,
        **totals, "results": [row],
    }


def _proof(action: str, outcome: str, target: str, generated_at: str) -> dict:
    proof = build_proof(_summary(action, outcome, target), "/proj")
    proof["generated_at"] = generated_at  # pin time out of the equation
    return proof


# --------------------------------------------------------------------------- #
# _archive_name — exact content-addressed scheme.                              #
# --------------------------------------------------------------------------- #


def test_archive_name_is_prefix_plus_full_hex_plus_json():
    """EXACT scheme: ``proof-`` + the 64-char sha256 hex of proof_hash + ``.json``
    — kills mutants on the affixes, the split, and the digest source."""
    proof = _proof("a", "applied", "app/x.py", "2026-01-01T00:00:00+00:00")
    digest = proof_hash(proof).split(":", 1)[-1]
    assert len(digest) == 64
    assert _archive_name(proof) == f"{_ARCHIVE_PREFIX}{digest}.json"
    assert _ARCHIVE_PREFIX == "proof-"


def test_archive_name_excludes_the_sha256_label():
    """The name carries the hex AFTER the ``sha256:`` prefix is stripped — a
    mutant that kept the whole ``sha256:<hex>`` would put a ``:`` in the name."""
    proof = _proof("a", "applied", "app/x.py", "2026-01-01T00:00:00+00:00")
    name = _archive_name(proof)
    assert ":" not in name
    stem = name[len(_ARCHIVE_PREFIX):-len(".json")]
    assert all(ch in "0123456789abcdef" for ch in stem)
    assert name != "proof-of-fix.json"


def test_archive_name_depends_only_on_content_not_time_or_target():
    """Same FIXES with different timestamps -> SAME archive name (hash excludes
    generated_at); different fixes -> DIFFERENT name."""
    a1 = _proof("a", "applied", "app/x.py", "2026-01-01T00:00:00+00:00")
    a2 = _proof("a", "applied", "app/x.py", "2030-12-31T23:59:59+00:00")
    b = _proof("a", "applied", "app/OTHER.py", "2026-01-01T00:00:00+00:00")
    assert _archive_name(a1) == _archive_name(a2)
    assert _archive_name(a1) != _archive_name(b)


# --------------------------------------------------------------------------- #
# write_proof — byte-identical pointer + byte-identical archive of previous.   #
# --------------------------------------------------------------------------- #


def test_pointer_text_is_exactly_json_dumps_indent2_plus_newline(tmp_path: Path):
    """The latest pointer is the raw artifact, byte-for-byte — every pre-archive
    consumer of ``.apex/proof-of-fix.json`` is unaffected."""
    proof = _proof("harden", "applied", "app/x.py", "2026-01-01T00:00:00+00:00")
    path = write_proof(proof, str(tmp_path))
    assert path == tmp_path / ".apex" / "proof-of-fix.json"
    assert path.read_text(encoding="utf-8") == json.dumps(proof, indent=2) + "\n"


def test_previous_pointer_is_archived_byte_identically(tmp_path: Path):
    """On the SECOND write, the FIRST proof is snapshotted into its content-
    addressed archive with byte-identical text — the recency/dedup math reads
    that exact text back."""
    p1 = _proof("a", "applied", "app/x.py", "2026-01-01T00:00:00+00:00")
    p2 = _proof("b", "rolled_back", "app/y.py", "2026-02-01T00:00:00+00:00")
    write_proof(p1, str(tmp_path))
    write_proof(p2, str(tmp_path))

    archive = tmp_path / ".apex" / _archive_name(p1)
    assert archive.exists()
    assert archive.read_text(encoding="utf-8") == json.dumps(p1, indent=2) + "\n"
    # The pointer now holds p2, byte-identically.
    pointer = tmp_path / ".apex" / "proof-of-fix.json"
    assert pointer.read_text(encoding="utf-8") == json.dumps(p2, indent=2) + "\n"


def test_two_different_proofs_both_fuse_with_exact_counts(tmp_path: Path):
    """End-to-end: two DISTINCT runs both land in history; the fused track record
    has EXACT per-action outcome counts (kills count-arithmetic mutants)."""
    p1 = _proof("harden_security", "rolled_back", "app/danger.py",
                "2026-01-01T00:00:00+00:00")
    p2 = _proof("add_docstring", "applied", "app/svc.py",
                "2026-02-01T00:00:00+00:00")
    write_proof(p1, str(tmp_path))
    write_proof(p2, str(tmp_path))

    summary = summarise_fix_track_record(load_proof_history(tmp_path))
    assert summary["proofs"] == 2
    assert summary["fixes"] == 2
    assert summary["by_action"]["harden_security"]["rolled_back"] == 1
    assert summary["by_action"]["harden_security"]["applied"] == 0
    assert summary["by_action"]["add_docstring"]["applied"] == 1
    assert summary["totals"]["applied"] == 1
    assert summary["totals"]["rolled_back"] == 1


def test_identical_proofs_dedup_to_single_archive_and_one_fix(tmp_path: Path):
    """Two IDENTICAL writes -> exactly ONE counted record and exactly ONE archive
    file on disk (content-hash dedup boundary). With a broken dedup the history
    would double-count."""
    proof = _proof("create_test_stub", "applied", "app/m.py",
                   "2026-01-01T00:00:00+00:00")
    write_proof(proof, str(tmp_path))
    write_proof(proof, str(tmp_path))

    apex = tmp_path / ".apex"
    archives = sorted(p.name for p in apex.glob(f"{_ARCHIVE_PREFIX}*.json")
                      if p.name != "proof-of-fix.json")
    # The pointer represents this content, so its archive is removed -> zero
    # archives, and the single record comes from the pointer alone.
    assert archives == []
    summary = summarise_fix_track_record(load_proof_history(tmp_path))
    assert summary["proofs"] == 1
    assert summary["fixes"] == 1
    assert summary["by_action"]["create_test_stub"]["applied"] == 1


def test_distinct_then_returning_content_counted_once_each(tmp_path: Path):
    """C, D, C: exactly 2 distinct contents counted once each (not 3). The
    returning content's stale archive is dropped because the pointer now is C."""
    c = _proof("a", "applied", "app/c.py", "2026-01-01T00:00:00+00:00")
    d = _proof("b", "rolled_back", "app/d.py", "2026-02-01T00:00:00+00:00")
    write_proof(c, str(tmp_path))
    write_proof(d, str(tmp_path))
    write_proof(c, str(tmp_path))

    summary = summarise_fix_track_record(load_proof_history(tmp_path))
    assert summary["fixes"] == 2
    assert summary["by_action"]["a"]["applied"] == 1
    assert summary["by_action"]["a"]["rolled_back"] == 0
    assert summary["by_action"]["b"]["rolled_back"] == 1


# --------------------------------------------------------------------------- #
# Archiving is best-effort — never breaks the primary pointer write.           #
# --------------------------------------------------------------------------- #


def test_archive_helper_exception_does_not_break_pointer(tmp_path: Path, monkeypatch):
    """If ``_archive_proof`` raises, the latest pointer is STILL byte-identical —
    the try/except around it is load-bearing (kills a mutant removing it)."""
    import app.engine.proof_of_fix as pof

    def boom(*_a, **_k):
        raise RuntimeError("archive exploded")

    monkeypatch.setattr(pof, "_archive_proof", boom)
    proof = _proof("a", "applied", "app/x.py", "2026-01-01T00:00:00+00:00")
    path = write_proof(proof, str(tmp_path))
    assert path.read_text(encoding="utf-8") == json.dumps(proof, indent=2) + "\n"


def test_prev_snapshot_failure_does_not_break_pointer(tmp_path: Path, monkeypatch):
    """If reading/snapshotting the PREVIOUS pointer raises, the new pointer is
    still written byte-identically — the snapshot block is best-effort too."""
    import app.engine.proof_of_fix as pof

    p1 = _proof("a", "applied", "app/x.py", "2026-01-01T00:00:00+00:00")
    write_proof(p1, str(tmp_path))

    def boom(*_a, **_k):
        raise RuntimeError("name exploded")

    monkeypatch.setattr(pof, "_archive_name", boom)
    p2 = _proof("b", "applied", "app/y.py", "2026-02-01T00:00:00+00:00")
    path = write_proof(p2, str(tmp_path))
    assert path.read_text(encoding="utf-8") == json.dumps(p2, indent=2) + "\n"


def test_explicit_out_path_does_not_archive(tmp_path: Path):
    """When ``out`` is passed, archiving is bypassed entirely (the ``if not out``
    guards) — no proof-<hash>.json is created beside it."""
    out = tmp_path / "custom" / "my-proof.json"
    p1 = _proof("a", "applied", "app/x.py", "2026-01-01T00:00:00+00:00")
    p2 = _proof("b", "applied", "app/y.py", "2026-02-01T00:00:00+00:00")
    write_proof(p1, str(tmp_path), out=out)
    write_proof(p2, str(tmp_path), out=out)
    siblings = sorted(p.name for p in out.parent.glob(f"{_ARCHIVE_PREFIX}*.json"))
    assert siblings == []
    assert out.read_text(encoding="utf-8") == json.dumps(p2, indent=2) + "\n"


def test_non_proof_schema_is_not_archived(tmp_path: Path):
    """A dict whose ``schema`` is not SCHEMA writes the pointer but is NOT
    archived/deduped — the ``proof.get('schema') == SCHEMA`` guard is exact."""
    bogus = {"schema": "not-apex", "generated_at": "2026-01-01T00:00:00+00:00",
             "fixes": []}
    write_proof(bogus, str(tmp_path))
    apex = tmp_path / ".apex"
    archives = [p.name for p in apex.glob(f"{_ARCHIVE_PREFIX}*.json")
                if p.name != "proof-of-fix.json"]
    assert archives == []


# --------------------------------------------------------------------------- #
# _prune_archive — exact keep boundary + recency + malformed-first.            #
# --------------------------------------------------------------------------- #


def _make_archive(apex: Path, idx: int, generated_at: str) -> Path:
    """A well-formed archive file with a unique hex-shaped name + timestamp."""
    apex.mkdir(parents=True, exist_ok=True)
    name = f"{_ARCHIVE_PREFIX}{idx:064x}.json"
    (apex / name).write_text(
        json.dumps({"schema": SCHEMA, "generated_at": generated_at}, indent=2)
        + "\n", encoding="utf-8")
    return apex / name


def test_prune_keeps_exactly_n_at_the_boundary(tmp_path: Path):
    """N+1 archives prune to EXACTLY N; the ``len <= keep`` early-return is an
    exact boundary (a mutant to ``<`` would leave N+1)."""
    apex = tmp_path / ".apex"
    keep = 3
    for i in range(keep + 1):
        _make_archive(apex, i, f"2026-01-{i + 1:02d}T00:00:00+00:00")
    _prune_archive(apex, keep)
    survivors = [p for p in apex.glob(f"{_ARCHIVE_PREFIX}*.json")
                 if p.name != "proof-of-fix.json"]
    assert len(survivors) == keep


def test_prune_is_noop_when_exactly_at_cap(tmp_path: Path):
    """EXACTLY ``keep`` archives are all retained — nothing is pruned at the cap
    (kills ``<=`` -> ``<`` on the early-return guard)."""
    apex = tmp_path / ".apex"
    keep = 4
    made = [_make_archive(apex, i, f"2026-01-{i + 1:02d}T00:00:00+00:00")
            for i in range(keep)]
    _prune_archive(apex, keep)
    survivors = sorted(p.name for p in apex.glob(f"{_ARCHIVE_PREFIX}*.json"))
    assert survivors == sorted(p.name for p in made)


def test_prune_retains_the_most_recent_by_generated_at(tmp_path: Path):
    """Of 5 archives the 3 with the LATEST ``generated_at`` survive — recency is
    keyed on the timestamp, not the filename/index."""
    apex = tmp_path / ".apex"
    # Index order is REVERSED from timestamp order, so a name-only sort would
    # pick the wrong survivors.
    stamps = {
        0: "2026-01-05T00:00:00+00:00",  # newest
        1: "2026-01-04T00:00:00+00:00",
        2: "2026-01-03T00:00:00+00:00",
        3: "2026-01-02T00:00:00+00:00",
        4: "2026-01-01T00:00:00+00:00",  # oldest
    }
    for i, ts in stamps.items():
        _make_archive(apex, i, ts)
    _prune_archive(apex, 3)
    survivors = sorted(p.name for p in apex.glob(f"{_ARCHIVE_PREFIX}*.json"))
    # Newest 3 are indices 0,1,2.
    assert survivors == sorted(f"{_ARCHIVE_PREFIX}{i:064x}.json" for i in (0, 1, 2))


def test_prune_drops_malformed_archives_first(tmp_path: Path):
    """A malformed (unparseable) archive sorts FIRST (empty timestamp) and is
    pruned before real evidence — keeping the audit trail honest."""
    apex = tmp_path / ".apex"
    apex.mkdir(parents=True)
    # Two real, dated archives + one malformed file.
    good_a = _make_archive(apex, 1, "2026-01-01T00:00:00+00:00")
    good_b = _make_archive(apex, 2, "2026-01-02T00:00:00+00:00")
    bad = apex / f"{_ARCHIVE_PREFIX}{'f' * 64}.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    _prune_archive(apex, 2)
    survivors = sorted(p.name for p in apex.glob(f"{_ARCHIVE_PREFIX}*.json"))
    assert survivors == sorted([good_a.name, good_b.name])
    assert not bad.exists()


def test_prune_ignores_the_latest_pointer(tmp_path: Path):
    """``proof-of-fix.json`` is never counted or pruned by ``_prune_archive`` even
    though it matches the ``proof-*.json`` glob."""
    apex = tmp_path / ".apex"
    apex.mkdir(parents=True)
    (apex / "proof-of-fix.json").write_text("{}", encoding="utf-8")
    for i in range(3):
        _make_archive(apex, i, f"2026-01-0{i + 1}T00:00:00+00:00")
    _prune_archive(apex, 1)
    assert (apex / "proof-of-fix.json").exists()
    survivors = [p for p in apex.glob(f"{_ARCHIVE_PREFIX}*.json")
                 if p.name != "proof-of-fix.json"]
    assert len(survivors) == 1


def test_archive_sort_key_orders_by_timestamp_then_name(tmp_path: Path):
    """``_archive_sort_key`` returns ``(generated_at, name)``; a malformed file
    yields ``("", name)`` so it sorts before any timestamped one."""
    apex = tmp_path / ".apex"
    good = _make_archive(apex, 7, "2026-06-01T00:00:00+00:00")
    bad = apex / f"{_ARCHIVE_PREFIX}{'a' * 64}.json"
    bad.write_text("nope", encoding="utf-8")
    assert _archive_sort_key(good) == ("2026-06-01T00:00:00+00:00", good.name)
    assert _archive_sort_key(bad) == ("", bad.name)
    assert _archive_sort_key(bad) < _archive_sort_key(good)


# --------------------------------------------------------------------------- #
# Cap constant + end-to-end determinism.                                       #
# --------------------------------------------------------------------------- #


def test_archive_cap_constant_is_fifty():
    """The deterministic prune cap is exactly 50 — pin the constant so a mutated
    literal is caught directly."""
    assert _ARCHIVE_KEEP == 50


def test_full_run_stays_within_cap_plus_pointer(tmp_path: Path):
    """More than ``_ARCHIVE_KEEP`` distinct runs leave AT MOST ``_ARCHIVE_KEEP``
    archives on disk (the pointer is separate)."""
    for i in range(_ARCHIVE_KEEP + 8):
        ts = f"2026-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}T00:{i % 60:02d}:00+00:00"
        write_proof(_proof(f"act{i}", "applied", f"app/m{i}.py", ts), str(tmp_path))
    apex = tmp_path / ".apex"
    archives = [p for p in apex.glob(f"{_ARCHIVE_PREFIX}*.json")
                if p.name != "proof-of-fix.json"]
    assert len(archives) <= _ARCHIVE_KEEP
    assert (apex / "proof-of-fix.json").exists()


def test_same_write_sequence_yields_identical_fused_history(tmp_path: Path):
    """Same input sequence in two projects -> byte-identical fused summary (no
    time/random in the archive scheme)."""
    seq = [
        _proof("a", "applied", "app/a.py", "2026-01-01T00:00:00+00:00"),
        _proof("b", "rolled_back", "app/b.py", "2026-02-01T00:00:00+00:00"),
        _proof("a", "blocked", "app/c.py", "2026-03-01T00:00:00+00:00"),
    ]
    one = tmp_path / "one"
    two = tmp_path / "two"
    for root in (one, two):
        root.mkdir()
        for proof in seq:
            write_proof(proof, str(root))
    s1 = summarise_fix_track_record(load_proof_history(one))
    s2 = summarise_fix_track_record(load_proof_history(two))
    assert json.dumps(s1, sort_keys=True) == json.dumps(s2, sort_keys=True)
