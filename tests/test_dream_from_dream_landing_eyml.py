"""The DREAM analysis→LANDING seam: `develop --from-dream` lands from the
DEFAULT dream.

Before this wave the seam was inert by default — the default dream only
*proposes* (it never writes `.apex/dream-promotions.json`), so
``dream_confluence_modules`` returned ``[]`` and ``compile_from_dream`` landed
nothing on a project that had never been ``--curate``-d. Two fixes close the
loop, both deterministic and offline:

  - **drives** — when the promotion store is absent/empty,
    ``dream_confluence_modules`` derives promotable confluences LIVE from a
    fully READ-ONLY dream (``persist=False``) under the EXISTING
    ``PROMOTE_STREAK`` / ``PROMOTE_CONFIDENCE`` gate (no lowered bar, no new
    threshold). The read-only dream READS the journal to compute the streak but
    NEVER advances it, so the derivation is deterministic, idempotent, and writes
    nothing — the streak is earned by the user's own prior ``apex dream`` runs;
  - **lands** — ``compile_from_dream(..., sweep=True)`` runs the
    ``rank_objectives``-ranked board of fitness-applicable objectives scoped to
    the flagged module, so the landing is no longer pinned to dead-params.

A non-empty stored store still wins byte-for-byte (a curated project is
unchanged), and a below-gate confluence still graduates nothing (no
over-promise). The seam lives in ``app/engine/dream_landing.py`` (one-way
imports), which is what this suite exercises."""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.dream import PROMOTE_STREAK
from app.tools.project_profile import ProjectProfile, ProjectProfiler


def _confluence_profile() -> ProjectProfile:
    # app/big.py carries FOUR signals while two leaf modules carry one each:
    # breadth 4 > typical 1 and confidence 4/5 = 0.80 — a promotable confluence
    # (the same crafted profile the promotion tests use; the gate is >= 0.80).
    return ProjectProfile(
        root=".",
        churn_hotspots=[{"module": "app/big.py", "commits": 9},
                        {"module": "app/small.py", "commits": 5},
                        {"module": "app/tiny.py", "commits": 4}],
        knowledge_risks=[{"module": "app/big.py", "share": 100, "commits": 9}],
        dependency_hubs=["app/big.py"],
        symbol_hubs=["app/big.py"],
    )


def _confluence_project(tmp_path: Path) -> Path:
    # A real module on the flagged path (so the live filter's existence check
    # passes) carrying a dead parameter the sweep can actually land on.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    # ``__all__ = []`` makes ``render`` non-public so the dead-params public-API
    # rail permits dropping its dead ``color`` (only the in-project test calls it).
    (tmp_path / "app" / "big.py").write_text(
        "__all__ = []\n\n\ndef render(text, color=None, width=80):\n"
        "    return text[:width]\n", encoding="utf-8")
    (tmp_path / "app" / "small.py").write_text(
        "def leaf():\n    return 2\n", encoding="utf-8")
    (tmp_path / "tests" / "test_big.py").write_text(
        "from app.big import render\n"
        "def test_render():\n    assert render('hi', width=2) == 'hi'\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _prime(tmp_path: Path, monkeypatch, prior_dreams: int) -> None:
    """Accrue the confluence's journal streak with ``prior_dreams`` PERSISTING
    dreams — the journal-writing runs a user/nightly ``apex dream`` performs.

    A subsequent READ-ONLY derivation then sees streak ``1 + prior_dreams`` (its
    own sighting plus the persisted history), so ``prior_dreams >= PROMOTE_STREAK
    - 1`` graduates the confluence and fewer does not. Priming is the ONLY writer
    of the journal in these tests; the derivation under test advances nothing."""
    from app.engine.dream import dream

    monkeypatch.setattr(ProjectProfiler, "profile",
                        lambda self: _confluence_profile())
    for _ in range(prior_dreams):
        dream(str(tmp_path), write_digest=False, curate=False, persist=True)


# --- (1) default dream above the gate now yields a module LIVE ---------------

def test_live_confluence_graduates_after_streak_without_a_stored_store(
        tmp_path, monkeypatch):
    from app.engine.dream_landing import dream_confluence_modules

    _confluence_project(tmp_path)
    # PROMOTE_STREAK - 1 persisting dreams accrue the streak; the read-only
    # derivation then sees the gate met and graduates LIVE — with NO
    # .apex/dream-promotions.json ever written (the default dream only proposes).
    _prime(tmp_path, monkeypatch, PROMOTE_STREAK - 1)
    assert dream_confluence_modules(str(tmp_path)) == ["app/big.py"]
    assert not (tmp_path / ".apex" / "dream-promotions.json").exists()


def test_read_only_derivation_writes_nothing_and_is_idempotent(
        tmp_path, monkeypatch):
    """The live derivation is FULLY read-only: it READS the journal to compute the
    streak but never advances it, so repeated calls return the same modules AND
    leave every ``.apex`` store byte-identical. Regression guard: an earlier draft
    routed this through a journal-WRITING dream, which made ``develop --from-dream``
    non-deterministic (same input → different output) and polluted the user repo."""
    from app.engine.dream_landing import dream_confluence_modules

    _confluence_project(tmp_path)
    _prime(tmp_path, monkeypatch, PROMOTE_STREAK - 1)

    journal = tmp_path / ".apex" / "dream-journal.json"
    ledger = tmp_path / ".apex" / "promise-ledger.json"
    before_j = journal.read_text(encoding="utf-8") if journal.exists() else None
    before_l = ledger.read_text(encoding="utf-8") if ledger.exists() else None

    first = dream_confluence_modules(str(tmp_path))
    second = dream_confluence_modules(str(tmp_path))

    assert first == ["app/big.py"]
    assert first == second  # deterministic / idempotent
    after_j = journal.read_text(encoding="utf-8") if journal.exists() else None
    after_l = ledger.read_text(encoding="utf-8") if ledger.exists() else None
    assert after_j == before_j  # journal byte-identical — never advanced
    assert after_l == before_l  # ledger byte-identical — never written
    assert not (tmp_path / ".apex" / "dream-promotions.json").exists()


def test_read_only_derivation_never_advances_a_sub_gate_streak(
        tmp_path, monkeypatch):
    """Anti-fake-green proof: a confluence ONE short of the gate must NEVER
    graduate, no matter how many times the read-only path runs — because it does
    not advance the streak. (An earlier determinism test passed only because the
    journal-WRITING path saturated the streak ABOVE the gate, masking the
    non-determinism; this pins the real invariant at the boundary.)"""
    from app.engine.dream_landing import dream_confluence_modules

    _confluence_project(tmp_path)
    _prime(tmp_path, monkeypatch, PROMOTE_STREAK - 2)  # one short of the gate
    for _ in range(5):
        assert dream_confluence_modules(str(tmp_path)) == []


# --- (2) compile_from_dream sweep: ranked multi-objective, scoped ------------

def test_sweep_lands_a_ranked_multi_objective_plan_scoped_to_the_module(
        tmp_path, monkeypatch):
    from app.engine.dream_landing import compile_from_dream

    _confluence_project(tmp_path)
    _prime(tmp_path, monkeypatch, PROMOTE_STREAK - 1)  # graduate the confluence LIVE

    results = compile_from_dream(str(tmp_path), apply=False, verify=False,
                                 sweep=True)
    # More than the single hard-coded objective, and dead-params is among them.
    objs = [r.objective for r in results]
    assert len(objs) >= 2
    assert "dead-params" in objs
    # Ranked order is deterministic (rank_objectives' own ordering).
    assert objs == [r.objective for r in compile_from_dream(
        str(tmp_path), apply=False, verify=False, sweep=True)]
    # Every landed step targets ONLY the flagged module — the sweep is scoped.
    targets = [s.target for r in results for s in r.steps]
    assert targets  # the dead-params move at least is composed
    assert all("app/big.py" in t for t in targets)


def test_sweep_actually_lands_a_verified_diff_on_the_flagged_module(
        tmp_path, monkeypatch):
    from app.engine.dream_landing import compile_from_dream

    _confluence_project(tmp_path)
    _prime(tmp_path, monkeypatch, PROMOTE_STREAK - 1)

    results = compile_from_dream(str(tmp_path), apply=True, verify=True,
                                 sweep=True)
    # The dead `color` parameter is dropped on the EXACT file the organism
    # flagged, every applied step suite-verified (never-fake-green).
    assert "color" not in (tmp_path / "app" / "big.py").read_text(encoding="utf-8")
    landed = [s for r in results for s in r.steps]
    assert landed
    assert all(s.verified for s in landed)


# --- (3) below the gate → nothing (honest under-claim, no over-promise) ------

def test_below_streak_confluence_yields_nothing(tmp_path, monkeypatch):
    from app.engine.dream_landing import dream_confluence_modules

    _confluence_project(tmp_path)
    # Only PROMOTE_STREAK - 2 prior dreams → the read-only derivation sees streak
    # PROMOTE_STREAK - 1, one short of the gate: the seam names no module and
    # lands nothing — an honest under-claim, not an over-promise.
    _prime(tmp_path, monkeypatch, PROMOTE_STREAK - 2)
    assert dream_confluence_modules(str(tmp_path)) == []


def test_sweep_lands_nothing_when_the_seam_names_no_module(tmp_path, monkeypatch):
    from app.engine import dream_landing as dl

    _confluence_project(tmp_path)
    # When the gate is unmet (no confluence graduates), compile_from_dream must
    # compose nothing rather than over-promising — pin the empty-modules contract
    # directly so it can't depend on journal-advancing side effects.
    monkeypatch.setattr(dl, "dream_confluence_modules", lambda _root: [])
    assert dl.compile_from_dream(str(tmp_path), apply=False, verify=False,
                                 sweep=True) == []


def test_bare_project_with_no_signals_lands_nothing(tmp_path):
    from app.engine.dream_landing import (
        compile_from_dream, dream_confluence_modules,
    )

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("x = 1\n", encoding="utf-8")
    # No git history / profile signals → the live dream surfaces no confluence.
    assert dream_confluence_modules(str(tmp_path)) == []
    assert compile_from_dream(str(tmp_path), apply=False, verify=False,
                              sweep=True) == []


# --- (4) stored-promotions path is unchanged (default byte-identical) --------

def _stored_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".apex").mkdir()
    # ``__all__ = []`` makes ``render``/``fetch`` non-public so the dead-params
    # public-API rail permits dropping their dead params (only the in-project
    # test imports them by name — that import ignores ``__all__`` and still works).
    (tmp_path / "app" / "hub.py").write_text(
        "__all__ = []\n\n\ndef render(text, color=None, width=80):\n"
        "    return text[:width]\n", encoding="utf-8")
    (tmp_path / "app" / "other.py").write_text(
        "__all__ = []\n\n\ndef fetch(url, retries=3):\n    return url\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.hub import render\nfrom app.other import fetch\n"
        "def test_all():\n    assert render('hi', width=2) == 'hi'\n"
        "    assert fetch('u') == 'u'\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (tmp_path / ".apex" / "dream-promotions.json").write_text(
        json.dumps([{"key": "confluence:app/hub.py", "kind": "confluence",
                     "streak": 20}]), encoding="utf-8")
    return tmp_path


def test_stored_promotions_win_and_never_trigger_live_derivation(
        tmp_path, monkeypatch):
    from app.engine import dream_landing as dl

    _stored_project(tmp_path)

    # If a non-empty store exists, the live path must NOT run at all.
    def _boom(_root):
        raise AssertionError("live derivation ran despite a non-empty store")

    monkeypatch.setattr(dl, "_live_confluence_modules", _boom)
    assert dl.dream_confluence_modules(str(tmp_path)) == ["app/hub.py"]


def test_stored_default_path_is_unchanged_single_objective(tmp_path):
    from app.engine.dream_landing import compile_from_dream

    _stored_project(tmp_path)
    # Default (sweep=False): exactly one CompileResult per confluence module,
    # the single dead-params objective — byte-for-byte the prior behavior.
    results = compile_from_dream(str(tmp_path), apply=True, verify=False)
    assert len(results) == 1
    assert results[0].objective == "dead-params"
    assert results[0].fitness_end == 0.0
    # hub.py cleaned; other.py (not a confluence) left untouched.
    assert "color" not in (tmp_path / "app" / "hub.py").read_text(encoding="utf-8")
    assert "retries" in (tmp_path / "app" / "other.py").read_text(encoding="utf-8")
