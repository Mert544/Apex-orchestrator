"""`dream_develop` — the overnight, value-led, proof-carrying LANDING CHAIN.

The concrete-dev × dream fusion wired as ``apex dream --land``: in one motion it
derives the value-led concrete objective order (``ship-value``, concrete-first),
scopes it to the dream's confluence modules (or whole-tree when none), runs each
objective through the EXISTING verified-with-rollback compiler, and emits one
deterministic ``DreamChainReport`` — the ordered landed contributions, the
verified-move count, and a single before→after health grade.

These tests pin the soundness contract (verified-or-refused, never faked), the
off-by-default byte-identity of the chain's dry run, the value-led order, the
confluence-vs-whole-tree scoping, the hashseed-invariant determinism of the
report body, and the clock-free renderer. The chain registers NO new develop
objective (it COMPOSES ``ship-value``), so there is no Facet-parity obligation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.engine.dream_develop import (
    DreamChainReport,
    dream_develop,
    render_dream_chain_markdown,
)


# --- fixtures ----------------------------------------------------------------

def _stub_project(tmp_path: Path) -> Path:
    """A whole-tree project with a test-pinned fillable stub (implement-stub,
    buyer value 1.00) and a sort-imports candidate — so a value-led chain has
    BOTH a concrete-first move and a low-value tidy move to order."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "s.py").write_text(
        "import os\nimport collections\n\n\n"
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_s.py").write_text(
        "from app.s import add\ndef test_add():\n"
        "    assert add(1, 2) == 3\n    assert add(5, 7) == 12\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _confluence_stub_project(tmp_path: Path) -> Path:
    """A stored-promotion confluence (``app/hub.py``) carrying a fillable stub the
    ship-value chain can land, plus a NON-confluence module of already-green code
    — so a scoped chain must touch ONLY the flagged module."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".apex").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "hub.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "app" / "other.py").write_text(
        "def fetch(url):\n    return url\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.hub import add\nfrom app.other import fetch\n"
        "def test_all():\n    assert add(1, 2) == 3\n    assert fetch('u') == 'u'\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (tmp_path / ".apex" / "dream-promotions.json").write_text(
        json.dumps([{"key": "confluence:app/hub.py", "kind": "confluence",
                     "streak": 20}]), encoding="utf-8")
    return tmp_path


# --- 1. value-led order: concrete first --------------------------------------

def test_chain_orders_concrete_first(tmp_path):
    # The chain composes ``ship-value`` value-led: the highest-buyer-value
    # concrete objective (implement-stub, 1.00) is ordered BEFORE the low-value
    # tidy (sort-imports, 0.18) — a function body attempted before a sorted import.
    _stub_project(tmp_path)
    report = dream_develop(str(tmp_path), apply=False, verify=False)
    objs = report.objectives
    assert objs[0] == "implement-stub"
    assert "sort-imports" not in objs[0:1]
    # implement-stub (1.00) strictly precedes any sub-value-1.0 leaf.
    assert objs.index("implement-stub") < objs.index("dataclassify")


# --- 2. dry run is byte-identical (off by default) ---------------------------

def test_chain_dry_run_writes_nothing(tmp_path):
    _stub_project(tmp_path)
    before = {p: p.read_text(encoding="utf-8")
              for p in tmp_path.rglob("*.py")}
    report = dream_develop(str(tmp_path), apply=False, verify=False)
    after = {p: p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.py")}
    assert after == before  # the tree is byte-identical after a dry run
    assert not report.applied
    # A dry run STILL reports the moves it WOULD land — an honest preview.
    assert report.total_moves >= 1


# --- 3. verified-or-refused: a regression is rolled back, not counted ---------

def test_chain_lands_and_rolls_back_on_regression(tmp_path):
    # A stub whose test PINS a wrong contract: any synthesised body that passes
    # the recorded examples would still leave the suite red on apply, so the FILL
    # is rolled back — never a faked landing.
    #
    # never-fake-green under DELTA-GREEN: the unsatisfiable fill is STILL rolled
    # back (the moat), but harmless behaviour-preserving tidy moves (wire-exports'
    # ``__all__``, a defensible ``-> None`` hint) now correctly LAND on this red-
    # baseline module — they break no previously-green test (``test_add`` stays red
    # because the stub still raises). So the assertion is the STUB BODY is untouched
    # (still raising) and ``implement_stub`` never landed — NOT byte-identity, which
    # would re-assert the old absolute-green veto this whole change fixes.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    stub = "def add(a, b):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "s.py").write_text(stub, encoding="utf-8")
    # Self-contradictory pin: add(1, 2) must equal BOTH 3 and 4 — unsatisfiable,
    # so no synthesised body can keep the suite green; every fill is rolled back.
    (tmp_path / "tests" / "test_s.py").write_text(
        "from app.s import add\ndef test_add():\n"
        "    assert add(1, 2) == 3\n    assert add(1, 2) == 4\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")

    report = dream_develop(str(tmp_path), apply=True, verify=True)
    # The contradictory stub's BODY is NEVER filled (the fill rolled back); it still
    # raises — the never-fake-green moat (harmless hints/exports may wrap it).
    assert "raise NotImplementedError" in (tmp_path / "app" / "s.py").read_text(
        encoding="utf-8")
    # No move that touched s.py with a fill is counted as landed.
    filled = [s for r in report.results for s in r.steps
              if s.operator == "implement_stub"]
    assert not filled


# --- 4. confluence scoping: touch only the flagged module --------------------

def test_chain_scopes_to_confluence_when_present(tmp_path):
    _confluence_stub_project(tmp_path)
    other_before = (tmp_path / "app" / "other.py").read_text(encoding="utf-8")
    report = dream_develop(str(tmp_path), apply=True, verify=True)
    # The dream graduated app/hub.py as a confluence → the chain scopes to it.
    assert report.modules == ["app/hub.py"]
    assert not report.whole_tree
    # The flagged module's stub is filled; the non-confluence module is untouched.
    assert "NotImplementedError" not in (tmp_path / "app" / "hub.py").read_text(
        encoding="utf-8")
    assert (tmp_path / "app" / "other.py").read_text(encoding="utf-8") == other_before
    # Every landed move targets ONLY the flagged module.
    targets = [s.target for r in report.results for s in r.steps]
    assert targets
    assert all("app/hub.py" in t for t in targets)


# --- 5. whole-tree fallback when the dream names no confluence ---------------

def test_chain_whole_tree_when_no_confluence(tmp_path):
    # No promotion store and no git/profile signals → the dream graduates no
    # confluence, so the chain runs WHOLE-TREE and still lands the stub fill.
    _stub_project(tmp_path)
    report = dream_develop(str(tmp_path), apply=True, verify=True)
    assert report.modules == []
    assert report.whole_tree
    assert "NotImplementedError" not in (tmp_path / "app" / "s.py").read_text(
        encoding="utf-8")
    assert report.total_moves >= 1


# --- 6. determinism: hashseed-invariant report body --------------------------

def test_chain_report_deterministic_under_pythonhashseed(tmp_path):
    _stub_project(tmp_path)
    repo = str(Path(__file__).resolve().parents[1])
    src = ("import json,sys;from app.engine.dream_develop import dream_develop;"
           "print(json.dumps(dream_develop(sys.argv[1], apply=False, "
           "verify=False).to_dict(), sort_keys=True))")
    out0 = subprocess.run(
        [sys.executable, "-c", src, str(tmp_path)], capture_output=True, text=True,
        env={"PYTHONHASHSEED": "0", "PATH": "/usr/bin:/bin", "PYTHONPATH": repo},
        cwd=repo)
    out1 = subprocess.run(
        [sys.executable, "-c", src, str(tmp_path)], capture_output=True, text=True,
        env={"PYTHONHASHSEED": "12345", "PATH": "/usr/bin:/bin", "PYTHONPATH": repo},
        cwd=repo)
    assert out0.returncode == 0 and out1.returncode == 0, (out0.stderr, out1.stderr)
    assert out0.stdout == out1.stdout  # the report body is hashseed-invariant
    assert out0.stdout.strip()  # and non-empty (the chain actually reported)


# --- 7. grade proof: recorded on apply, -1 on a dry run ----------------------

def test_chain_grade_before_after_recorded(tmp_path):
    _stub_project(tmp_path)
    applied = dream_develop(str(tmp_path), apply=True, verify=True)
    # An applied chain records a real before→after grade (both >= 0).
    assert applied.grade_before >= 0 and applied.grade_after >= 0
    # Filling the stub can only help or hold the grade — never regress it.
    assert applied.grade_after >= applied.grade_before
    # A dry run measures nothing it would write → both grades are -1.
    fresh = dream_develop(str(tmp_path), apply=False, verify=False)
    assert fresh.grade_before == -1 and fresh.grade_after == -1
    assert fresh.grade_delta == 0


# --- 8. the renderer is CLOCK-FREE -------------------------------------------

def test_chain_render_has_no_clock(tmp_path):
    # The renderer must carry no wall-clock (unlike render_dream_markdown's
    # datetime.now() header), so two runs on the same tree render byte-identical.
    _stub_project(tmp_path)
    report = dream_develop(str(tmp_path), apply=False, verify=False)
    md = render_dream_chain_markdown(report)
    # No UTC stamp, no ISO date, no "Curated <ts>" header anywhere.
    assert "UTC" not in md
    assert "Curated" not in md
    import re
    assert not re.search(r"\d{4}-\d{2}-\d{2}", md)  # no YYYY-MM-DD timestamp
    # And byte-stable across renders of the same report.
    assert render_dream_chain_markdown(report) == md
    assert "Dream-develop" in md and "ship-value" in md


# --- 9. CLI dispatch: --land routes to the chain; bare dream is unchanged -----

def test_cmd_dream_land_dispatch(tmp_path, monkeypatch, capsys):
    import argparse

    from app import cli_insight

    _stub_project(tmp_path)
    # --land routes cmd_dream to _cmd_dream_land (the chain), NOT dream().
    def _no_dream(*a, **k):
        raise AssertionError("bare dream() ran despite --land")

    monkeypatch.setattr(cli_insight, "_cmd_dream_land",
                        lambda args: (print("LANDED-CHAIN"), 0)[1])
    rc = cli_insight.cmd_dream(argparse.Namespace(
        target=str(tmp_path), curate=False, land=True, apply=False, fast=False,
        json=False))
    assert rc == 0
    assert "LANDED-CHAIN" in capsys.readouterr().out

    # Bare dream (no --land) still calls dream() and renders the digest.
    called = {"dream": False}

    class _Rep:
        digest_path = ""

        def to_dict(self):
            return {}

    def _fake_dream(root, curate=False):
        called["dream"] = True
        return _Rep()

    monkeypatch.setattr("app.engine.dream.dream", _fake_dream)
    monkeypatch.setattr("app.engine.dream.render_dream_markdown", lambda r: "DIGEST")
    rc2 = cli_insight.cmd_dream(argparse.Namespace(
        target=str(tmp_path), curate=False, land=False, json=False))
    assert rc2 == 0
    assert called["dream"]  # bare dream took the unchanged path


# --- 10. empty project → honest empty refusal, exit 0 ------------------------

def test_chain_empty_project_is_clean_refusal(tmp_path):
    import argparse

    from app import cli_insight

    # A bare project with nothing landable: an empty package — no stubs, no
    # untested modules, no exportable surface, no confluence. The chain composes
    # nothing for ANY ship-value objective — an honest empty refusal.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")

    report = dream_develop(str(tmp_path), apply=True, verify=False)
    assert report.total_moves == 0
    assert report.verified_moves == 0
    assert not report.contributions
    # The renderer is HONEST about the empty chain — no faked move, clear wording.
    md = render_dream_chain_markdown(report)
    assert "Nothing landable" in md
    assert "refused honestly" in md
    # And the CLI exits 0 (an honest under-claim is not a failure).
    rc = cli_insight.cmd_dream(argparse.Namespace(
        target=str(tmp_path), curate=False, land=True, apply=False, fast=False,
        json=False))
    assert rc == 0


# --- DreamChainReport shape sanity (mirrors GoalResult.to_dict) --------------

def test_chain_report_to_dict_shape():
    report = DreamChainReport(goal="ship-value", objectives=["implement-stub"])
    d = report.to_dict()
    # Mirrors GoalResult.to_dict()'s familiar keys, plus the chain's scope view.
    for key in ("goal", "objectives", "results", "grade_before", "grade_after",
                "grade_delta", "total_moves", "applied"):
        assert key in d
    assert d["goal"] == "ship-value"
    assert d["modules"] == [] and d["whole_tree"] is True
    assert d["contributions"] == []


# --- the INTERACTIVITY BOUND (opt-in; default off = byte-identical) -----------
#
# ``apex assist "what should I build next?"`` calls ``dream_develop`` as a DRY-RUN
# preview with a human waiting; the unbounded chain's whole-tree mutation
# generation makes that ~7 min on a multi-module project. ``max_modules`` /
# ``preview_skip_mutation`` bound the preview deterministically WITHOUT touching
# the exhaustive ``apex dream --land`` path (both default off ⇒ byte-identical).

def test_bound_off_default_is_byte_identical(tmp_path):
    # The explicit bound-OFF call (None / False) must produce the IDENTICAL report
    # as the bare default — the round-21 trust property: the bound only exists when
    # a caller opts in, so ``apex dream --land`` (which passes neither) is unchanged.
    _stub_project(tmp_path)
    bare = dream_develop(str(tmp_path), apply=False, verify=False)
    off = dream_develop(str(tmp_path), apply=False, verify=False,
                        max_modules=None, preview_skip_mutation=False)
    assert off.to_dict() == bare.to_dict()
    # And the default chain still carries the full ship-value objective list.
    assert "strengthen-tests" in bare.objectives


def test_preview_skip_mutation_drops_strengthen_in_dry_run(tmp_path):
    # The bound drops ONLY the un-previewable mutation objective from the dry-run
    # preview; every other ship-value objective stays, and the move set is the
    # unbounded set minus any strengthen-tests move (an honest top-value subset).
    _stub_project(tmp_path)
    full = dream_develop(str(tmp_path), apply=False, verify=False)
    bounded = dream_develop(str(tmp_path), apply=False, verify=False,
                            preview_skip_mutation=True)
    assert "strengthen-tests" in full.objectives
    assert "strengthen-tests" not in bounded.objectives
    # Exactly that one objective is removed; the rest of the chain is unchanged.
    assert bounded.objectives == [o for o in full.objectives
                                  if o != "strengthen-tests"]
    # No bounded contribution comes from the skipped objective (never fabricated).
    assert all(c.objective != "strengthen-tests" for c in bounded.contributions)


def test_preview_skip_mutation_refused_on_apply(tmp_path):
    # The skip is PREVIEW-only: an apply run must still attempt every objective
    # (including strengthen-tests), so ``--land --apply`` lands the full chain —
    # only the interactive dry run trades the mutation direction for latency.
    _stub_project(tmp_path)
    applied = dream_develop(str(tmp_path), apply=True, verify=False,
                            preview_skip_mutation=True)
    assert "strengthen-tests" in applied.objectives


def test_preview_skip_mutation_dry_run_is_deterministic(tmp_path):
    # Same (project, bound) → byte-identical report body run to run (the bound
    # selects by a fixed name set, no clock/random enters the selection).
    _stub_project(tmp_path)
    a = dream_develop(str(tmp_path), apply=False, verify=False,
                      preview_skip_mutation=True)
    b = dream_develop(str(tmp_path), apply=False, verify=False,
                      preview_skip_mutation=True)
    assert a.to_dict() == b.to_dict()


def _multi_confluence_project(tmp_path: Path) -> Path:
    """Three stored confluences with DISTINCT fan-in (hub imported by two others,
    mid by one, leaf by none) — so the ``max_modules`` centrality cap has a real
    ranking to keep the highest-fan-in confluences first."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".apex").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "hub.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "app" / "mid.py").write_text(
        "from app.hub import add\ndef mid(x):\n    raise NotImplementedError\n",
        encoding="utf-8")
    (tmp_path / "app" / "leaf.py").write_text(
        "from app.hub import add\nfrom app.mid import mid\n"
        "def leaf(x):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.hub import add\ndef test_x():\n    assert True\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (tmp_path / ".apex" / "dream-promotions.json").write_text(
        json.dumps([{"key": f"confluence:app/{m}.py", "kind": "confluence",
                     "streak": 20} for m in ("hub", "mid", "leaf")]),
        encoding="utf-8")
    return tmp_path


def test_max_modules_caps_confluences_by_centrality(tmp_path):
    # With several graduated confluences, ``max_modules=2`` keeps the top-2 by
    # FAN-IN centrality (hub=2 importers, mid=1, leaf=0) — a deterministic SUBSET
    # of the dream's own confluences, highest blast-radius first.
    _multi_confluence_project(tmp_path)
    full = dream_develop(str(tmp_path), apply=False, verify=False)
    assert full.modules == ["app/hub.py", "app/leaf.py", "app/mid.py"]
    bounded = dream_develop(str(tmp_path), apply=False, verify=False, max_modules=2)
    assert bounded.modules == ["app/hub.py", "app/mid.py"]  # top-2 by fan-in
    # A real subset of the unbounded confluences — never a fabricated module.
    assert set(bounded.modules) <= set(full.modules)
    # Deterministic: the same cap keeps the same modules run to run.
    again = dream_develop(str(tmp_path), apply=False, verify=False, max_modules=2)
    assert again.modules == bounded.modules


def test_bounded_preview_deterministic_under_pythonhashseed(tmp_path):
    # The BOUNDED preview (both bounds on) is hashseed-invariant — the selection
    # keys are an integer fan-in + a path tiebreak and a fixed name set, so the
    # cut never depends on dict/set iteration order across processes.
    _multi_confluence_project(tmp_path)
    repo = str(Path(__file__).resolve().parents[1])
    src = ("import json,sys;from app.engine.dream_develop import dream_develop;"
           "print(json.dumps(dream_develop(sys.argv[1], apply=False, "
           "verify=False, max_modules=2, preview_skip_mutation=True).to_dict(), "
           "sort_keys=True))")
    out0 = subprocess.run(
        [sys.executable, "-c", src, str(tmp_path)], capture_output=True, text=True,
        env={"PYTHONHASHSEED": "0", "PATH": "/usr/bin:/bin", "PYTHONPATH": repo},
        cwd=repo)
    out1 = subprocess.run(
        [sys.executable, "-c", src, str(tmp_path)], capture_output=True, text=True,
        env={"PYTHONHASHSEED": "12345", "PATH": "/usr/bin:/bin", "PYTHONPATH": repo},
        cwd=repo)
    assert out0.returncode == 0 and out1.returncode == 0, (out0.stderr, out1.stderr)
    assert out0.stdout == out1.stdout  # the bounded report body is hashseed-invariant
    assert '"app/hub.py"' in out0.stdout  # and it actually applied the centrality cap


def test_max_modules_noop_when_at_or_under_cap(tmp_path):
    # A cap >= the confluence count (and the common whole-tree run) is a no-op —
    # the bound can only ever shrink a multi-confluence set, never grow/reorder one
    # that already fits.
    _multi_confluence_project(tmp_path)
    full = dream_develop(str(tmp_path), apply=False, verify=False)
    big = dream_develop(str(tmp_path), apply=False, verify=False, max_modules=9)
    assert big.modules == full.modules  # nothing to cap → unchanged order
    # Whole-tree (no confluence) is unaffected by max_modules.
    wt_root = tmp_path / "wt"
    wt_root.mkdir()
    _stub_project(wt_root)  # a fresh whole-tree project
    wt = dream_develop(str(wt_root), apply=False, verify=False, max_modules=1)
    assert wt.modules == [] and wt.whole_tree
