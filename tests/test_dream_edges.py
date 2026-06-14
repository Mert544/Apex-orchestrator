"""Edge and error paths for the dream curation pass.

Each test isolates one defensive branch: corrupt stores read silently,
I/O failures swallowed, boundary conditions in consolidation/promotion.
"""

from __future__ import annotations

import json
from pathlib import Path

import app.engine.dream as dm
from app.engine.dream import (
    DreamReport,
    _briefed_subjects,
    _consolidate,
    _materialize_briefs,
    _pattern_key,
    _promote,
    _review_pulse,
    dream,
    render_dream_markdown,
)


def _bare_project(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")


# -- DreamReport.to_dict ----------------------------------------------------

def test_report_to_dict_exposes_human_fields_only():
    report = DreamReport(patterns=["p"], discoveries=["d"], promoted=["g"],
                         curated=["c"], proposed=["x"], digest_path="/tmp/d.md")
    report.discovery_objs.append({"key": "k", "text": "d", "kind": "confluence",
                                  "confidence": 0.9})
    d = report.to_dict()
    assert d["patterns"] == ["p"]
    assert d["digest_path"] == "/tmp/d.md"
    # Structured discovery objects are deliberately NOT in the human dict.
    assert "discovery_objs" not in d


# -- _pattern_key normalization --------------------------------------------

def test_pattern_key_strips_at_first_separator():
    assert _pattern_key("`mod` is hot — keep an eye") == "`mod` is hot"
    assert _pattern_key("`mod` fixes land 90% (3 samples)") == "`mod` fixes land 90%"
    assert _pattern_key("subject: detail") == "subject"
    assert _pattern_key("no separators here") == "no separators here"


# -- corrupt store reads are silent ----------------------------------------

def test_corrupt_proof_store_is_ignored(tmp_path: Path):
    _bare_project(tmp_path)
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text("{not json", encoding="utf-8")
    report = dream(tmp_path, write_digest=False)
    # No proof-derived patterns, but the pass survived.
    assert not any("failed verification" in p for p in report.patterns)


def test_corrupt_promise_ledger_is_ignored(tmp_path: Path):
    _bare_project(tmp_path)
    (tmp_path / "README.md").write_text("See `app/ghost.py`.\n")
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "promise-ledger.json").write_text("[broken", encoding="utf-8")
    # Corrupt previous ledger -> treated as empty -> broken promise surfaces fresh.
    report = dream(tmp_path, write_digest=False)
    assert any("promise broken" in p and "app/ghost.py" in p for p in report.patterns)


def test_corrupt_dream_journal_resets(tmp_path: Path):
    _bare_project(tmp_path)
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "dream-journal.json").write_text("not json", encoding="utf-8")
    report = dream(tmp_path, write_digest=False)
    # With history reset to empty, everything present is "new", nothing resolved.
    assert report.resolved_since == []


# -- I/O failure swallow branches ------------------------------------------

def test_digest_write_oserror_leaves_digest_path_empty(tmp_path: Path, monkeypatch):
    _bare_project(tmp_path)
    real_write = Path.write_text

    def selective(self: Path, *a, **k):
        if self.name == "dream-digest.md":
            raise OSError("nope")
        return real_write(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", selective)
    report = dream(tmp_path, write_digest=True)
    assert report.digest_path == ""  # OSError swallowed, path stays unset


def test_promise_ledger_write_oserror_is_silent(tmp_path: Path, monkeypatch):
    _bare_project(tmp_path)
    (tmp_path / "README.md").write_text("See `app/ghost.py`.\n")
    real_write = Path.write_text

    def selective(self: Path, *a, **k):
        if self.name == "promise-ledger.json":
            raise OSError("nope")
        return real_write(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", selective)
    # Must not raise even though the ledger cannot be persisted.
    report = dream(tmp_path, write_digest=False)
    assert any("promise broken" in p for p in report.patterns)


def test_dream_journal_write_oserror_is_silent(tmp_path: Path, monkeypatch):
    _bare_project(tmp_path)
    real_write = Path.write_text

    def selective(self: Path, *a, **k):
        if self.name == "dream-journal.json":
            raise OSError("nope")
        return real_write(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", selective)
    report = dream(tmp_path, write_digest=False)
    # The pass still completes and produces a renderable report.
    assert "Dream digest" in render_dream_markdown(report)


# -- review-step exception isolation ---------------------------------------

def test_review_exception_does_not_break_dream(tmp_path: Path, monkeypatch):
    _bare_project(tmp_path)
    import app.engine.dream as dm

    def boom(*a, **k):
        raise RuntimeError("review blew up")

    # One review raising must be swallowed by the per-review try/except.
    monkeypatch.setattr(dm, "_review_proof", boom)
    report = dream(tmp_path, write_digest=False)
    assert isinstance(report, DreamReport)


# -- briefs curation -------------------------------------------------------

def test_in_progress_brief_reported_not_archived(tmp_path: Path):
    (tmp_path / "app").mkdir()
    # Subject still has an open bare-except finding -> brief is in progress.
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url):\n    try:\n        return url\n"
        "    except:\n        return None\n")
    briefs = tmp_path / ".apex" / "briefs"
    briefs.mkdir(parents=True)
    (briefs / "y.b.json").write_text(json.dumps({
        "branch_path": "y.b", "title": "Harden core", "subject": "app/core.py",
        "evidence": {"error handling": [[4, "bare except swallows errors"]]},
    }))
    report = dream(tmp_path, curate=True, write_digest=False)
    assert any("in progress" in p for p in report.patterns)
    # Still in place, not archived (work not landed).
    assert (briefs / "y.b.json").exists()
    assert not (briefs / "archive" / "y.b.json").exists()


# -- consolidation streaks across constructed history ----------------------

def test_consolidate_legacy_list_history_streak(tmp_path: Path):
    # Legacy bare-list journal entries must still feed the streak counter.
    apex = tmp_path / ".apex"
    apex.mkdir()
    key = "`mod` is hot"
    (apex / "dream-journal.json").write_text(
        json.dumps([[key], [key]]), encoding="utf-8")
    report = DreamReport(patterns=[f"{key} — keep watching"])
    _consolidate(tmp_path, report)
    # Present in two prior list entries + this one -> streak 3.
    assert "seen in 3 consecutive dreams" in report.patterns[0]


def test_consolidate_resolved_from_dict_history(tmp_path: Path):
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "dream-journal.json").write_text(
        json.dumps([{"gone-key": "the gone pattern text"}]), encoding="utf-8")
    report = DreamReport(patterns=["brand new pattern"])
    _consolidate(tmp_path, report)
    # The previous dict key, absent now, is reported resolved with its words.
    assert "the gone pattern text" in report.resolved_since
    assert "brand new pattern" in report.new_since


# -- fully-resolved brief, default (propose, not archive) ------------------

def test_fully_resolved_brief_proposed_when_not_curating(tmp_path: Path):
    # Subject file is clean -> the evidence phrase finds nothing -> resolved.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "clean.py").write_text("def f():\n    return 1\n")
    briefs = tmp_path / ".apex" / "briefs"
    briefs.mkdir(parents=True)
    (briefs / "z.b.json").write_text(json.dumps({
        "branch_path": "z.b", "title": "Tidy", "subject": "app/clean.py",
        "evidence": {"error handling": [[2, "bare except swallows errors"]]},
    }))
    report = dream(tmp_path, curate=False, write_digest=False)
    assert any("archive brief `z.b`" in p for p in report.proposed)
    # Default mode never moves the file.
    assert (briefs / "z.b.json").exists()
    assert not (briefs / "archive" / "z.b.json").exists()


# -- accelerating-trend pattern in _review_pulse (line 186) ----------------

def test_review_pulse_emits_accelerating_pattern(tmp_path: Path, monkeypatch):
    from app.engine.signal_trends import SignalTrends
    from app.tools.project_profile import ProjectProfile

    base = ProjectProfile(
        root=str(tmp_path),
        churn_hotspots=[{"module": "app/hot.py", "commits": 3}],
        debt_marker_ages={"app/hot.py": 120},
    )
    SignalTrends(tmp_path).record(base)  # baseline so a rise has a slope

    now = ProjectProfile(
        root=str(tmp_path),
        churn_hotspots=[{"module": "app/hot.py", "commits": 12}],
        debt_marker_ages={"app/hot.py": 130},
    )

    class _Profiler:
        def __init__(self, root):
            pass

        def profile(self):
            return now

    monkeypatch.setattr("app.tools.project_profile.ProjectProfiler", _Profiler)
    report = DreamReport()
    _review_pulse(tmp_path, report)
    assert any("is ACCELERATING" in p and "app/hot.py" in p for p in report.patterns)


# -- _promote write OSError swallowed (lines 248-249) ----------------------

def test_promote_curate_write_oserror_is_silent(tmp_path: Path, monkeypatch):
    report = DreamReport()
    report.discovery_objs = [{"key": "confluence:app/x.py", "text": "x travels with y",
                              "kind": "confluence", "confidence": 0.95}]
    report._streaks = {"confluence:app/x.py": 5}  # promotable: streak >= 3, conf >= 0.8

    real_write = Path.write_text

    def selective(self: Path, *a, **k):
        if self.name == "dream-promotions.json":
            raise OSError("nope")
        return real_write(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", selective)
    # Returns early on OSError; nothing promoted, no exception escapes.
    _promote(tmp_path, report, curate=True)
    assert report.promoted == []


# -- _briefed_subjects skips corrupt brief files (lines 273-274) -----------

def test_briefed_subjects_skips_corrupt_brief(tmp_path: Path):
    briefs = tmp_path / ".apex" / "briefs"
    briefs.mkdir(parents=True)
    (briefs / "good.json").write_text(json.dumps({"subject": "app/good.py"}))
    (briefs / "bad.json").write_text("{not json", encoding="utf-8")
    subjects = _briefed_subjects(tmp_path)
    assert "app/good.py" in subjects
    # The corrupt file is skipped without raising.
    assert "" not in subjects or "app/good.py" in subjects


# -- _materialize_briefs early/honest-skip branches ------------------------

def test_materialize_briefs_skips_already_briefed(tmp_path: Path):
    briefs = tmp_path / ".apex" / "briefs"
    briefs.mkdir(parents=True)
    (briefs / "existing.json").write_text(json.dumps({"subject": "app/x.py"}))
    report = DreamReport()
    # Subject already has a brief -> todo is empty -> early return, no engine run.
    _materialize_briefs(tmp_path, ["app/x.py"], report)
    assert report.curated == []


def test_materialize_briefs_skips_when_subject_not_surfaced(tmp_path: Path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    report = DreamReport()

    import app.engine.idea_brief as ib
    # Engine runs, but the subject never surfaces -> build_brief returns None ->
    # honest skip (no curated work order, no saved brief).
    monkeypatch.setattr(ib, "build_brief", lambda tree, subject="": None)
    _materialize_briefs(tmp_path, ["app/never-surfaces.py"], report)
    assert report.curated == []


def test_materialize_briefs_engine_exception_is_swallowed(tmp_path: Path, monkeypatch):
    report = DreamReport()

    def boom(*a, **k):
        raise RuntimeError("engine down")

    # IdeaPermutationEngine import path -> patch the run to blow up.
    import app.engine.idea_permutation as ip
    monkeypatch.setattr(ip.IdeaPermutationEngine, "run", boom)
    _materialize_briefs(tmp_path, ["app/never.py"], report)
    assert report.curated == []


# -- exception isolation in the dream() driver (lines 325-339) -------------

def test_outcome_review_exception_is_isolated(tmp_path: Path, monkeypatch):
    _bare_project(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("outcome blew up")

    monkeypatch.setattr(dm, "_review_outcome_memory", boom)
    report = dream(tmp_path, write_digest=False)
    assert isinstance(report, DreamReport)


def test_consolidate_exception_is_isolated(tmp_path: Path, monkeypatch):
    _bare_project(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("consolidate blew up")

    monkeypatch.setattr(dm, "_consolidate", boom)
    report = dream(tmp_path, write_digest=False)
    assert isinstance(report, DreamReport)


def test_promote_exception_is_isolated(tmp_path: Path, monkeypatch):
    _bare_project(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("promote blew up")

    monkeypatch.setattr(dm, "_promote", boom)
    report = dream(tmp_path, write_digest=False)
    assert isinstance(report, DreamReport)
