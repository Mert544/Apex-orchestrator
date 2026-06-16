"""Characterization proof: the refactored ``dream`` is byte-identical to the
pre-refactor original across every branch.

The refactor touched ONLY ``dream`` itself (plus three new private helpers);
every review step (``_review_*``, ``_consolidate``, ``_promote``,
``render_dream_markdown``) is unchanged. So the original control flow is
reconstructed here verbatim — ``_dream_original`` is a byte-for-byte copy of
the pre-refactor function body, calling the same (unchanged) module helpers —
and its full output is compared against the live ``dream`` on the same seeded
store. Every scenario hits a distinct branch: write/no-write, curate/no-curate,
populated stores vs. empty root, and a deliberately corrupt store (the
exception-isolation path). Zero mismatches == byte-identical refactor.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.engine import dream as D
from app.engine.dream import (
    DreamReport,
    _consolidate,
    _promote,
    _review_briefs,
    _review_outcome_memory,
    _review_proof,
    _review_pulse,
    render_dream_markdown,
)


def _dream_original(project_root, write_digest=True, curate=False):
    """Verbatim copy of the pre-refactor ``dream`` body (HEAD snapshot)."""
    root = Path(project_root)
    report = DreamReport()
    for review in (_review_outcome_memory, _review_briefs):
        try:
            review(root, report, curate)
        except Exception:
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
    try:
        _promote(root, report, curate)
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


def _seed_full(root: Path) -> None:
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    cap = D.MEMORY_KEY_CAP
    mem = {"by_operator": {"document": {"applied": 6, "rolled_back": 0, "blocked": 0},
                           "harden": {"applied": 0, "rolled_back": 1, "blocked": 4}},
           "by_label": {f"label-{i}": {"applied": 1, "rolled_back": 0, "blocked": 0}
                        for i in range(cap + 5)}}
    (apex / "idea-memory.json").write_text(json.dumps(mem))
    (apex / "proof-of-fix.json").write_text(json.dumps({"fixes": [
        {"outcome": "rolled_back", "finding": {"target": "app/a.py"},
         "verification": {"failing_tests": ["tests/test_guard.py::test_g"]}},
        {"outcome": "rolled_back", "finding": {"target": "app/b.py"},
         "verification": {"failing_tests": ["tests/test_guard.py::test_g"]}},
        {"outcome": "blocked", "finding": {"target": "app/c.py"},
         "blocked_reason": "tier-1 fix requires a covering test"},
        {"outcome": "blocked", "finding": {"target": "app/d.py"},
         "blocked_reason": "tier-1 fix requires a covering test"},
    ]}))
    briefs = apex / "briefs"
    briefs.mkdir()
    (briefs / "feat-x.json").write_text(json.dumps(
        {"subject": "app/m.py :: refactor", "branch": "feat-x"}))


def _seed_app(root: Path) -> None:
    app = root / "app"
    app.mkdir(parents=True, exist_ok=True)
    (app / "m.py").write_text("def f():\n    return 1\n")


def _seed_corrupt(root: Path) -> None:
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "idea-memory.json").write_text("{ this is not json")
    (apex / "proof-of-fix.json").write_text("also broken][")


def _digest_bytes(root: Path):
    p = root / ".apex" / "dream-digest.md"
    return p.read_bytes() if p.exists() else None


def _snapshot(report) -> dict:
    d = report.to_dict()
    d["discovery_objs"] = report.discovery_objs
    d["_streaks"] = getattr(report, "_streaks", None)
    return d


_SCENARIOS = [
    ("full_write_curate", _seed_full, True, True),
    ("full_write_nocurate", _seed_full, True, False),
    ("full_nowrite_curate", _seed_full, False, True),
    ("full_nowrite_nocurate", _seed_full, False, False),
    ("app_only_write_nocurate", _seed_app, True, False),
    ("app_only_write_curate", _seed_app, True, True),
    ("empty_write_nocurate", lambda r: None, True, False),
    ("empty_write_curate", lambda r: None, True, True),
    ("empty_nowrite", lambda r: None, False, False),
    ("corrupt_write_curate", _seed_corrupt, True, True),
    ("corrupt_write_nocurate", _seed_corrupt, True, False),
    ("full_plus_app_write_curate",
     lambda r: (_seed_app(r), _seed_full(r)), True, True),
]


class _FrozenDatetime(datetime):
    """Pin the digest clock so the two runs can't straddle a minute boundary;
    determinism is what we're proving, not wall-clock drift."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 6, 16, 12, 0, 0, tzinfo=tz or timezone.utc)


@pytest.fixture(autouse=True)
def _freeze_clock(monkeypatch):
    monkeypatch.setattr(D, "datetime", _FrozenDatetime)


@pytest.mark.parametrize("name,seeder,write_digest,curate", _SCENARIOS,
                         ids=[s[0] for s in _SCENARIOS])
def test_byte_identical(tmp_path, name, seeder, write_digest, curate):
    orig_root = tmp_path / "orig"
    new_root = tmp_path / "new"
    orig_root.mkdir()
    new_root.mkdir()
    seeder(orig_root)
    seeder(new_root)

    orig_report = _dream_original(orig_root, write_digest=write_digest, curate=curate)
    new_report = D.dream(new_root, write_digest=write_digest, curate=curate)

    orig_snap = _snapshot(orig_report)
    new_snap = _snapshot(new_report)
    orig_rel = orig_snap.pop("digest_path")
    new_rel = new_snap.pop("digest_path")
    assert (orig_rel == "") == (new_rel == "")
    if orig_rel:
        assert Path(orig_rel).relative_to(orig_root) == Path(new_rel).relative_to(new_root)
    assert orig_snap == new_snap
    assert _digest_bytes(orig_root) == _digest_bytes(new_root)


def test_second_pass_consolidation_identical(tmp_path):
    """Two consecutive dreams on one root: the journal/streak path stays
    byte-identical too (streaks, new/resolved, persistence)."""
    orig_root = tmp_path / "orig"
    new_root = tmp_path / "new"
    orig_root.mkdir()
    new_root.mkdir()
    _seed_full(orig_root)
    _seed_full(new_root)

    _dream_original(orig_root, write_digest=True, curate=False)
    D.dream(new_root, write_digest=True, curate=False)
    orig2 = _dream_original(orig_root, write_digest=True, curate=True)
    new2 = D.dream(new_root, write_digest=True, curate=True)

    o = _snapshot(orig2)
    n = _snapshot(new2)
    o.pop("digest_path")
    n.pop("digest_path")
    assert o == n
    assert _digest_bytes(orig_root) == _digest_bytes(new_root)
