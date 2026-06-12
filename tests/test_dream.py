"""Dreaming: the deterministic curation pass over the organism's memory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.engine.dream import MEMORY_KEY_CAP, dream, render_dream_markdown


def _seed_stores(tmp_path: Path) -> None:
    apex = tmp_path / ".apex"
    apex.mkdir()
    # Outcome memory: one reliable key, one unreliable, plus key overflow.
    mem = {"by_operator": {"document": {"applied": 6, "rolled_back": 0, "blocked": 0},
                           "harden": {"applied": 0, "rolled_back": 1, "blocked": 4}},
           "by_label": {f"label-{i}": {"applied": 1, "rolled_back": 0, "blocked": 0}
                        for i in range(MEMORY_KEY_CAP + 5)}}
    (apex / "idea-memory.json").write_text(json.dumps(mem))
    # Proof: a repeatedly failing guard test + repeated block reason.
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


def test_dream_extracts_patterns_and_curates_memory(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    _seed_stores(tmp_path)

    report = dream(tmp_path, curate=True)
    text = " | ".join(report.patterns)
    assert "`document` fixes land 100%" in text
    assert "`harden` lands only 0%" in text
    assert "tests/test_guard.py::test_g" in text and "2×" in text
    assert "2 steps blocked for the same reason: tier-1 fix requires" in text
    # Curation: the overflowing label table was trimmed and persisted.
    assert any("trimmed: 5" in c for c in report.curated)
    saved = json.loads((tmp_path / ".apex" / "idea-memory.json").read_text())
    assert len(saved["by_label"]) == MEMORY_KEY_CAP
    # Digest written and readable.
    digest = Path(report.digest_path).read_text(encoding="utf-8")
    assert digest.startswith("# Dream digest")
    assert "zero tokens" in digest


def test_default_dream_proposes_but_never_touches_inputs(tmp_path):
    # Parity with the real Dreams API: the input stores are never modified by
    # default — curation is reported as a proposal until --curate.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    _seed_stores(tmp_path)
    before = (tmp_path / ".apex" / "idea-memory.json").read_text()

    report = dream(tmp_path)
    assert report.curated == []
    assert any("would drop" in p for p in report.proposed)
    assert (tmp_path / ".apex" / "idea-memory.json").read_text() == before
    assert "Proposed curation" in render_dream_markdown(report)


def test_recurring_patterns_consolidate_across_dreams(tmp_path):
    # The deterministic analogue of reading 100 sessions: a pattern that
    # appears dream after dream is annotated with its streak.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    _seed_stores(tmp_path)
    first = dream(tmp_path)
    assert not any("consecutive dreams" in p for p in first.patterns)
    second = dream(tmp_path)
    assert any("seen in 2 consecutive dreams" in p for p in second.patterns)
    third = dream(tmp_path)
    assert any("seen in 3 consecutive dreams" in p for p in third.patterns)


def test_dream_archives_fully_resolved_briefs(tmp_path):
    (tmp_path / "app").mkdir()
    # Subject is clean NOW; the saved brief remembers old evidence -> resolved.
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url):\n    try:\n        return url\n"
        "    except ValueError:\n        return None\n")
    briefs = tmp_path / ".apex" / "briefs"
    briefs.mkdir(parents=True)
    (briefs / "x.a.json").write_text(json.dumps({
        "branch_path": "x.a", "title": "Harden core", "subject": "app/core.py",
        "evidence": {"error handling": [[4, "bare except swallows errors"]]},
    }))
    report = dream(tmp_path, curate=True)
    assert any("fully resolved (1/1" in p for p in report.patterns)
    assert not (briefs / "x.a.json").exists()
    assert (briefs / "archive" / "x.a.json").exists()


def test_dream_on_empty_project_is_calm(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    report = dream(tmp_path)
    md = render_dream_markdown(report)
    assert "Dream digest" in md  # never crashes, always renders


def test_cli_dream(tmp_path, capsys):
    from app.cli import cmd_dream

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    _seed_stores(tmp_path)
    rc = cmd_dream(argparse.Namespace(target=str(tmp_path), json=False, curate=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Dream digest" in out and "Digest written to" in out


def test_dream_flow_new_then_standing_no_cyclic_repetition(tmp_path):
    # The core anti-bug guarantee: a standing observation is announced 'new'
    # exactly once, never re-announced dream after dream.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    _seed_stores(tmp_path)

    first = dream(tmp_path, curate=True)
    assert first.new_since, "first dream should surface everything as new"
    assert first.resolved_since == []

    # Second dream, same stores -> nothing new, nothing resolved (stable).
    second = dream(tmp_path, curate=True)
    assert second.new_since == []
    assert second.resolved_since == []
    # And the standing items now carry the streak annotation.
    assert any("consecutive dreams" in p for p in second.patterns)


def test_dream_flow_reports_resolved_once(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    _seed_stores(tmp_path)
    dream(tmp_path, curate=True)  # establishes baseline (proof patterns present)

    # Remove the proof store -> its patterns vanish -> resolved exactly once.
    (tmp_path / ".apex" / "proof-of-fix.json").unlink()
    after = dream(tmp_path, curate=True)
    assert any("blocked for the same reason" in t for t in after.resolved_since)
    md = render_dream_markdown(after)
    assert "no longer surfaces" in md

    # Next dream: it's already gone from the baseline -> NOT resolved again.
    again = dream(tmp_path, curate=True)
    assert not any("blocked for the same reason" in t for t in again.resolved_since)


def test_dashboard_pins_the_last_dream(tmp_path):
    from app.reporting.dashboard import _dream_section

    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "dream-digest.md").write_text(
        "# Dream digest\n\n## Since the last dream\n"
        "- 🆕 `app/x.py` is a confluence — 4 distinct signals\n"
        "## Discoveries\n- 🔍 80% of high-churn modules are also co-change\n")
    html_doc = _dream_section(str(tmp_path))
    assert "Last dream" in html_doc
    assert "confluence" in html_doc and "co-change" in html_doc


def test_dashboard_dream_section_empty_without_digest(tmp_path):
    from app.reporting.dashboard import _dream_section

    assert _dream_section(str(tmp_path)) == ""
