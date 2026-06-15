"""apex changelog: uncovered error/empty/section paths.

Targets the lines the existing changelog tests don't reach: the _git exception
swallow, the proof-of-fix JSON-error and no-applied early returns, the whole
_resolved_section body (snapshot present, diff with dropped ideas), the
_health_section exception fallback, and build_changelog's per-section
exception-continue plus the empty-body calm fallback.
"""

from __future__ import annotations

import json

import app.reporting.changelog as cl


# --- _git: any subprocess failure is swallowed to "" (26-27) -----------------

def test_git_swallows_exception(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("git missing")

    monkeypatch.setattr(cl.subprocess, "run", boom)
    assert cl._git(tmp_path, "log") == ""


# --- _fixes_section: malformed proof JSON returns [] (53-54) -----------------

def test_fixes_section_malformed_json_returns_empty(tmp_path):
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text("{not valid json", encoding="utf-8")
    assert cl._fixes_section(tmp_path) == []


# --- _fixes_section: file present but no applied fixes returns [] (57) --------

def test_fixes_section_no_applied_returns_empty(tmp_path):
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text(
        json.dumps({"fixes": [{"outcome": "rolled_back"}, {"outcome": "blocked"}]}),
        encoding="utf-8")
    assert cl._fixes_section(tmp_path) == []


# --- _resolved_section: full body when a snapshot exists and ideas dropped ----

class _FakeChange:
    def __init__(self, title, signal):
        self.title = title
        self.signal = signal


class _FakeDiff:
    def __init__(self, dropped):
        self.dropped = dropped


def _patch_resolved(monkeypatch, *, snapshot, diff):
    """Inject the locally-imported symbols _resolved_section uses."""
    import app.engine.idea_permutation as ip
    import app.engine.idea_roadmap as ir
    import app.engine.roadmap_history as rh

    class _FakeEngine:
        def __init__(self, *a, **k):
            pass

        def run(self, *a, **k):
            return object()

    class _FakeSynth:
        def build(self, report):
            return object()

    monkeypatch.setattr(ip, "IdeaPermutationEngine", _FakeEngine)
    monkeypatch.setattr(ir, "RoadmapSynthesizer", _FakeSynth)
    monkeypatch.setattr(rh, "load_snapshot", lambda p: snapshot)
    monkeypatch.setattr(rh, "diff_roadmaps", lambda a, b: diff)


def test_resolved_section_lists_dropped_ideas_with_signal(monkeypatch, tmp_path):
    dropped = [_FakeChange("Harden the auth flow", "churn-hotspot"),
               _FakeChange("Trim dead code", "")]
    _patch_resolved(monkeypatch, snapshot={"ideas": []}, diff=_FakeDiff(dropped))
    lines = cl._resolved_section(tmp_path)
    assert lines[0] == "## Planned work that landed (no longer surfaces on the roadmap)"
    assert any("Harden the auth flow — its `churn-hotspot` signal no longer fires" in ln
               for ln in lines)
    # The signal-less change gets no suffix.
    assert "- Trim dead code" in lines


def test_resolved_section_caps_at_eight(monkeypatch, tmp_path):
    dropped = [_FakeChange(f"Idea {i}", "") for i in range(20)]
    _patch_resolved(monkeypatch, snapshot={"ideas": []}, diff=_FakeDiff(dropped))
    lines = cl._resolved_section(tmp_path)
    bullets = [ln for ln in lines if ln.startswith("- ")]
    assert len(bullets) == 8


def test_resolved_section_no_snapshot_returns_empty(monkeypatch, tmp_path):
    import app.engine.roadmap_history as rh
    monkeypatch.setattr(rh, "load_snapshot", lambda p: None)
    assert cl._resolved_section(tmp_path) == []


def test_resolved_section_no_dropped_returns_empty(monkeypatch, tmp_path):
    _patch_resolved(monkeypatch, snapshot={"ideas": []}, diff=_FakeDiff([]))
    assert cl._resolved_section(tmp_path) == []


def test_resolved_section_swallows_engine_exception(monkeypatch, tmp_path):
    """If the roadmap rebuild/diff raises, the section degrades to [] (91-92)."""
    import app.engine.idea_permutation as ip
    import app.engine.idea_roadmap as ir
    import app.engine.roadmap_history as rh

    class _FakeEngine:
        def __init__(self, *a, **k):
            pass

        def run(self, *a, **k):
            return object()

    monkeypatch.setattr(ip, "IdeaPermutationEngine", _FakeEngine)
    monkeypatch.setattr(ir, "RoadmapSynthesizer", lambda: (_ for _ in ()).throw(
        RuntimeError("synth boom")))
    monkeypatch.setattr(rh, "load_snapshot", lambda p: {"ideas": []})

    def boom(a, b):
        raise RuntimeError("diff boom")

    monkeypatch.setattr(rh, "diff_roadmaps", boom)
    assert cl._resolved_section(tmp_path) == []


# --- _health_section: grade() raising falls back to [] (108-109) --------------

def test_health_section_exception_returns_empty(monkeypatch, tmp_path):
    import app.engine.health_score as hs

    def boom(root):
        raise RuntimeError("cannot grade")

    monkeypatch.setattr(hs, "grade", boom)
    assert cl._health_section(tmp_path) == []


# --- build_changelog: a section raising is skipped via continue (123-124) -----

def test_build_changelog_section_exception_is_skipped(monkeypatch, tmp_path):
    def boom(root):
        raise RuntimeError("section blew up")

    # Make every section raise; the loop must continue past each one and then
    # fall through to the empty-body calm fallback (125-127).
    monkeypatch.setattr(cl, "_commits_section", boom)
    monkeypatch.setattr(cl, "_fixes_section", boom)
    monkeypatch.setattr(cl, "_resolved_section", boom)
    monkeypatch.setattr(cl, "_health_section", boom)
    out = cl.build_changelog(tmp_path)
    assert "Nothing to report yet" in out
    assert out.startswith("# Release notes")
