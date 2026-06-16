"""Characterization harness proving the refactors of ``_trackrecord_section`` and
``_roadmap_changes_section`` are byte-identical to the originals at git HEAD.

Both functions (HTML section renderers) were decomposed into small pure helpers:
``_trackrecord_section`` now delegates de-dup/sort to ``_trackrecord_rates`` and
table markup to ``_trackrecord_table``; ``_roadmap_changes_section`` delegates
the snapshot load + diff to ``_roadmap_changes_diff``, the signal narration to
``_roadmap_changes_signals``, and the change-item list to ``_roadmap_changes_items``.

This test loads the *original* function bodies from ``git show HEAD:<file>`` into
an isolated module, then renders the FULL HTML string for a battery of
representative inputs through both the original and the refactored implementation
and asserts exact (byte-for-byte) equality. Coverage:

- track record: gated empty (no rates, no proof), proof-only, rates-only, both,
  the de-dup-across-lists case, sort order (rate desc then key), >0 rows table
  gate, HTML-special characters / XSS in the fix key, and float/missing-field
  edges.
- roadmap changes: None roadmap, empty phases, no snapshot, an identical snapshot
  (no new/dropped), a real cross-run diff with new + dropped changes (signal
  narration both present), grounded vs ungrounded changes, and the >6 truncation.

Offline, stdlib-only, deterministic — no network, no time/random assertions.
"""

import os
import subprocess
import sys
import types

import pytest

from app.reporting import dashboard_sections as REFACTORED

_REL = "app/reporting/dashboard_sections.py"
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_original():
    """Compile the HEAD version of the module under a throwaway module name."""
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{_REL}"], cwd=_REPO
    ).decode("utf-8")
    mod = types.ModuleType("_dashboard_sections_head_trackrecord_roadmap")
    mod.__file__ = os.path.join(_REPO, _REL)
    sys.modules["_dashboard_sections_head_trackrecord_roadmap"] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


ORIGINAL = _load_original()


# --- track record helpers ---------------------------------------------------

def _write_proof(tmp_path, applied):
    apex = tmp_path / ".apex"
    apex.mkdir(exist_ok=True)
    (apex / "proof-of-fix.json").write_text(
        '{"totals": {"applied": %d}, "fixes": []}' % applied, encoding="utf-8"
    )


def _learned_empty():
    return None


def _learned_empty_lists():
    return {"most_reliable": [], "least_reliable": []}


def _learned_basic():
    return {
        "most_reliable": [
            {"key": "harden", "success_rate": 0.8, "samples": 10},
        ],
        "least_reliable": [
            {"key": "modernize", "success_rate": 0.2, "samples": 10},
        ],
    }


def _learned_dedup():
    # Same key in both lists -> first occurrence wins, rendered once.
    return {
        "most_reliable": [{"key": "harden", "success_rate": 0.75, "samples": 4}],
        "least_reliable": [{"key": "harden", "success_rate": 0.75, "samples": 4}],
    }


def _learned_sort_ties():
    # alpha & beta tie at 50%; gamma higher -> gamma, alpha, beta.
    return {
        "most_reliable": [
            {"key": "beta", "success_rate": 0.5, "samples": 2},
            {"key": "gamma", "success_rate": 0.75, "samples": 4},
        ],
        "least_reliable": [
            {"key": "alpha", "success_rate": 0.5, "samples": 2},
        ],
    }


def _learned_xss():
    return {
        "most_reliable": [
            {"key": "<script>alert(1)</script>", "success_rate": 1.0, "samples": 2},
        ],
        "least_reliable": [],
    }


def _learned_edges():
    # Non-dict rows, blank/missing keys, missing success_rate/samples, None rate.
    return {
        "most_reliable": [
            "notadict",
            {"key": "", "success_rate": 0.9, "samples": 1},
            {"key": "  ", "success_rate": 0.9, "samples": 1},
            {"key": "ok", "success_rate": None, "samples": 0},
            {"key": "nosr"},
        ],
        "least_reliable": None,
    }


_LEARNED = [
    _learned_empty,
    _learned_empty_lists,
    _learned_basic,
    _learned_dedup,
    _learned_sort_ties,
    _learned_xss,
    _learned_edges,
]


@pytest.mark.parametrize("make", _LEARNED, ids=[f.__name__ for f in _LEARNED])
@pytest.mark.parametrize("applied", [None, 0, 3, 10], ids=["no_proof", "p0", "p3", "p10"])
def test_trackrecord_section_byte_identical(make, applied, tmp_path):
    if applied is not None:
        _write_proof(tmp_path, applied)
    learned = make()
    root = str(tmp_path)
    before = ORIGINAL._trackrecord_section(learned, root)
    after = REFACTORED._trackrecord_section(learned, root)
    assert before == after, "trackrecord HTML diverged from HEAD original"


def test_trackrecord_rates_pure_dedup_and_sort():
    rates = REFACTORED._trackrecord_rates(_learned_sort_ties())
    keys = [r["key"] for r in rates]
    assert keys == ["gamma", "alpha", "beta"]
    # Determinism.
    assert REFACTORED._trackrecord_rates(_learned_sort_ties()) == rates


def test_trackrecord_rates_empty_inputs():
    assert REFACTORED._trackrecord_rates(None) == []
    assert REFACTORED._trackrecord_rates({}) == []
    assert REFACTORED._trackrecord_rates({"most_reliable": [], "least_reliable": []}) == []


def test_trackrecord_table_empty_rows_gate():
    # No rates -> "" (no table markup at all).
    assert REFACTORED._trackrecord_table([]) == ""


def test_trackrecord_table_renders_and_escapes():
    table = REFACTORED._trackrecord_table(
        [{"key": "a<b>", "success_rate": 0.5, "samples": 3}]
    )
    assert table.startswith("<table>")
    assert "a&lt;b&gt;" in table
    assert "50%" in table


# --- roadmap changes fixtures -----------------------------------------------

def _roadmap(phase_name, title, fact):
    from app.engine.idea_roadmap import Roadmap, RoadmapItem, RoadmapPhase

    item = RoadmapItem(
        branch_path="x.a", title=title, subject="app/x.py", phase=phase_name,
        impact=0.8, effort=0.4, roi=2.0, value=0.6, kind="permutation",
        rationale="r", source_facts=[fact] if fact else [],
    )
    return Roadmap(objective="", project_root="", phases=[
        RoadmapPhase(name=phase_name, theme="t", items=[item])])


def _snapshot(tmp_path, roadmap):
    from app.engine.roadmap_history import snapshot_roadmap

    snapshot_roadmap(roadmap, tmp_path / ".apex" / "roadmap-snapshot.json")


def test_roadmap_changes_none_roadmap_byte_identical(tmp_path):
    root = str(tmp_path)
    assert ORIGINAL._roadmap_changes_section(root, None) == \
        REFACTORED._roadmap_changes_section(root, None) == ""


def test_roadmap_changes_empty_phases_byte_identical(tmp_path):
    from types import SimpleNamespace

    root = str(tmp_path)
    rm = SimpleNamespace(phases=[])
    assert ORIGINAL._roadmap_changes_section(root, rm) == \
        REFACTORED._roadmap_changes_section(root, rm) == ""


def test_roadmap_changes_no_snapshot_byte_identical(tmp_path):
    root = str(tmp_path)
    rm = _roadmap("Secure", "Harden app/a.py", "security-finding: app/a.py")
    assert ORIGINAL._roadmap_changes_section(root, rm) == \
        REFACTORED._roadmap_changes_section(root, rm) == ""


def test_roadmap_changes_identical_snapshot_byte_identical(tmp_path):
    root = str(tmp_path)
    rm = _roadmap("Secure", "Harden app/a.py", "security-finding: app/a.py")
    _snapshot(tmp_path, rm)
    # Same roadmap -> no new/dropped -> "".
    assert ORIGINAL._roadmap_changes_section(root, rm) == \
        REFACTORED._roadmap_changes_section(root, rm) == ""


def test_roadmap_changes_real_diff_byte_identical(tmp_path):
    root = str(tmp_path)
    prev = _roadmap("Secure", "Harden: app/a.py", "security-finding: app/a.py")
    _snapshot(tmp_path, prev)
    curr = _roadmap("Evolve", "Smooth the change path of app/b.py",
                    "churn-hotspot: app/b.py (12 commits)")
    before = ORIGINAL._roadmap_changes_section(root, curr)
    after = REFACTORED._roadmap_changes_section(root, curr)
    assert before == after
    # Sanity: this fixture actually exercises the narration + items branches.
    assert "Where the new work comes from:" in after
    assert "no longer fires" in after


def test_roadmap_changes_ungrounded_change_byte_identical(tmp_path):
    # New item with no source_facts -> no grounded_in suffix; dropped with no
    # signal -> no "signal no longer fires" suffix.
    root = str(tmp_path)
    prev = _roadmap("Secure", "Old idea", "")
    _snapshot(tmp_path, prev)
    curr = _roadmap("Evolve", "Brand new idea", "")
    before = ORIGINAL._roadmap_changes_section(root, curr)
    after = REFACTORED._roadmap_changes_section(root, curr)
    assert before == after


def test_roadmap_changes_truncation_byte_identical(tmp_path):
    from app.engine.idea_roadmap import Roadmap, RoadmapItem, RoadmapPhase

    root = str(tmp_path)

    def _many(prefix, fact_prefix):
        items = [
            RoadmapItem(
                branch_path="x.a", title=f"{prefix} idea {i}", subject="app/x.py",
                phase="Evolve", impact=0.8, effort=0.4, roi=2.0, value=0.6,
                kind="permutation", rationale="r",
                source_facts=[f"{fact_prefix}: app/m{i}.py"],
            )
            for i in range(10)
        ]
        return Roadmap(objective="", project_root="", phases=[
            RoadmapPhase(name="Evolve", theme="t", items=items)])

    _snapshot(tmp_path, _many("old", "security-finding"))
    curr = _many("new", "churn-hotspot")
    before = ORIGINAL._roadmap_changes_section(root, curr)
    after = REFACTORED._roadmap_changes_section(root, curr)
    assert before == after


def test_roadmap_changes_diff_failure_byte_identical(tmp_path, monkeypatch):
    # A raising diff is swallowed by both -> "".
    import app.engine.roadmap_history as rh

    root = str(tmp_path)
    rm = _roadmap("Secure", "Harden app/a.py", "security-finding: app/a.py")
    _snapshot(tmp_path, rm)

    def _boom(prev, curr):
        raise RuntimeError("diff blew up")

    monkeypatch.setattr(rh, "diff_roadmaps", _boom)
    before = ORIGINAL._roadmap_changes_section(root, rm)
    after = REFACTORED._roadmap_changes_section(root, rm)
    assert before == after == ""


def test_roadmap_changes_diff_helper_none_paths(tmp_path):
    # Helper returns None for every gated-absent case.
    root = str(tmp_path)
    from types import SimpleNamespace

    assert REFACTORED._roadmap_changes_diff(root, None) is None
    assert REFACTORED._roadmap_changes_diff(root, SimpleNamespace(phases=[])) is None
    rm = _roadmap("Secure", "Harden app/a.py", "security-finding: app/a.py")
    assert REFACTORED._roadmap_changes_diff(root, rm) is None  # no snapshot
