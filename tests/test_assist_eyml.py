"""Tests for ``apex assist`` — the conversational UNDERSTAND→PLAN→ACT→EXPLAIN loop.

These exercise the LOOP WIRING: that each understood intent routes to the right
shipped organ, that the read-only routes write NOTHING, that a develop request
previews-then-lands through the existing gated compiler, that the proactive
"what should I build next?" reaches the DREAM core, and that an unmappable request
gets an honest no-capability answer (never a fabricated action). Comprehend's
vocabulary accuracy is Wave-2b's concern; here we assume comprehend returns what
it returns and verify the loop around it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.agent.assist import (
    COUPLING_PHRASES,
    NEXT_WORK_PHRASES,
    _commit_result,
    _resolve_commit,
    _working_tree_clean,
    assist,
    is_coupling_question,
    is_next_work_question,
    render_assist_markdown,
)
from app.engine.objective_compiler import CompileResult, CompileStep
from app.intent.comprehension import comprehend


# --- fixtures ---------------------------------------------------------------

def _init_git(root: Path) -> None:
    """Init a git repo at ``root`` with an initial commit — the AUTO-COMMIT
    precondition fixtures need a real repo with a clean tree to start from."""
    subprocess.run(["git", "init", "-q"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=root,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root,
                   capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m",
                    "init"], cwd=root, capture_output=True)


def _git_log_hashes(root: Path) -> list[str]:
    out = subprocess.run(["git", "log", "--format=%H"], cwd=root,
                         capture_output=True, text=True)
    return out.stdout.split()


def _git_changed_files(root: Path, commit_hash: str) -> set[str]:
    out = subprocess.run(
        ["git", "show", "--name-only", "--format=", commit_hash],
        cwd=root, capture_output=True, text=True)
    return {line for line in out.stdout.splitlines() if line}


def _modernize_project(tmp_path: Path) -> Path:
    """A tiny project with a ``== None`` the modernizer rewrites, covered by a
    test that exercises the function (so the move lands VERIFIED)."""
    (tmp_path / "mod.py").write_text(
        "def greet(name):\n"
        "    if name == None:\n"
        "        return 'hi'\n"
        "    return 'hi ' + name\n",
        encoding="utf-8")
    (tmp_path / "test_mod.py").write_text(
        "from mod import greet\n"
        "def test_greet():\n"
        "    assert greet('a') == 'hi a'\n"
        "    assert greet(None) == 'hi'\n",
        encoding="utf-8")
    return tmp_path


def _stub_project(tmp_path: Path) -> Path:
    """A tiny project with an unimplemented stub + an un-hinted function — the
    concrete ``ship-value`` work the DREAM core surfaces as directions."""
    (tmp_path / "calc.py").write_text(
        '"""A tiny library."""\n\n\n'
        "def add(a, b):\n"
        '    """Return the sum."""\n'
        "    return a + b\n\n\n"
        "def multiply(a, b):\n"
        '    """Return the product."""\n'
        "    raise NotImplementedError\n",
        encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(
        "from calc import add, multiply\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
        "def test_multiply():\n"
        "    assert multiply(2, 3) == 6\n",
        encoding="utf-8")
    return tmp_path


def _coupled_project(tmp_path: Path) -> Path:
    """A tiny project with a real import CYCLE (``a`` <-> ``b``) and a fan-in HUB
    (``a`` is imported by both ``b`` and ``c``) — the dependency shape the DEPS
    route narrates from the real import graph."""
    (tmp_path / "a.py").write_text(
        "import b\n\n\ndef fa():\n    return b.fb()\n", encoding="utf-8")
    (tmp_path / "b.py").write_text(
        "import a\n\n\ndef fb():\n    return 1\n", encoding="utf-8")
    (tmp_path / "c.py").write_text(
        "import a\nimport b\n\n\ndef fc():\n    return a.fa() + b.fb()\n",
        encoding="utf-8")
    return tmp_path


def _tree_snapshot(root: Path) -> dict[str, str]:
    """Every .py file's content — to assert a read-only route changed nothing."""
    return {str(p): p.read_text(encoding="utf-8") for p in root.rglob("*.py")}


# --- the next-work self-classifier ------------------------------------------

def test_next_work_classifier_matches_the_phrase_set():
    assert is_next_work_question("what should I build next?")
    assert is_next_work_question("What's next?")
    assert is_next_work_question("Tell me the highest value work")
    # Turkish surface (the loop is its own EN+TR classifier, not a comprehend field)
    assert is_next_work_question("sırada ne var")
    assert is_next_work_question("ne geliştirmeli")


def test_next_work_classifier_rejects_plain_questions_and_commands():
    assert not is_next_work_question("is this well tested?")
    assert not is_next_work_question("add type hints to the auth module")
    assert not is_next_work_question("")
    # every table phrase is non-empty and lowercase (deterministic substring match)
    assert all(p and p == p.lower() for p in NEXT_WORK_PHRASES)


# --- the coupling/cycle/dependency self-classifier --------------------------

def test_coupling_classifier_matches_the_phrase_set():
    assert is_coupling_question("why is this module so coupled?")
    assert is_coupling_question("are there circular imports?")
    assert is_coupling_question("what are the dependencies?")
    assert is_coupling_question("show me the fan-in")
    assert is_coupling_question("is this tightly coupled?")
    # Turkish surface (the loop is its own EN+TR classifier, not a comprehend field)
    assert is_coupling_question("bağımlılık var mı")
    assert is_coupling_question("döngü var mı")


def test_coupling_classifier_rejects_plain_questions_and_commands():
    # A plain health question is NOT a coupling question — it must fall through to
    # the grade (the load-bearing regression-lock for the existing route).
    assert not is_coupling_question("is this well tested?")
    assert not is_coupling_question("is the security ok?")
    assert not is_coupling_question("add type hints to the auth module")
    assert not is_coupling_question("")
    # every table phrase is non-empty and lowercase (deterministic substring match)
    assert all(p and p == p.lower() for p in COUPLING_PHRASES)


# --- the DREAM ROUTE: "what should I build next?" ---------------------------

def test_next_work_question_routes_to_dream_core(tmp_path):
    root = _stub_project(tmp_path)
    before = _tree_snapshot(root)

    result = assist("what should I build next?", target=str(root))

    assert result.route == "dream"
    assert result.applied is False
    # Ranked, value-led concrete directions, each carrying objective + target.
    directions = result.payload["directions"]
    assert directions, "the stub project should surface at least one direction"
    objectives = [d["objective"] for d in directions]
    assert "implement-stub" in objectives
    for d in directions:
        assert d["objective"] and d["target"]
    # Highest buyer-value first (value-led order is preserved into the payload).
    values = [d["value"] for d in directions]
    assert values == sorted(values, reverse=True)
    # The narrative offers the one-command follow-ups.
    assert "apex dream --land --apply" in result.narrative
    assert "apex develop" in result.narrative
    # READ-ONLY: nothing was written.
    assert _tree_snapshot(root) == before


def test_dream_route_narrates_grounded_directions(tmp_path):
    root = _stub_project(tmp_path)
    md = assist("what next?", target=str(root)).narrative
    assert "You asked:" in md
    assert "DREAM core" in md
    # The objective + a buyer-value number appear, grounded in the real chain.
    assert "implement-stub" in md
    assert "buyer-value" in md


# --- the DREAM ROUTE is BOUNDED for interactivity (opt-in, honest) -----------

def test_dream_route_is_bounded_for_interactivity(tmp_path):
    """The proactive preview passes the interactivity bound to ``dream_develop``
    (``max_modules`` + ``preview_skip_mutation``) so a multi-module project answers
    in seconds — the un-previewable mutation objective is SKIPPED (and disclosed),
    while the leading value-led directions are preserved. Here we pin the bound's
    CONTRACT on a tiny project: the skip is recorded, never silent."""
    from app.engine.dream_develop import _PREVIEW_SKIP_OBJECTIVES

    root = _stub_project(tmp_path)
    result = assist("what should I build next?", target=str(root))

    assert result.route == "dream"
    # The skipped mutation objective(s) are disclosed in the payload AND narrative —
    # the bound is transparent (an honest preview, not a silent omission).
    assert result.payload["skipped"] == sorted(_PREVIEW_SKIP_OBJECTIVES)
    assert "strengthen-tests" in result.payload["skipped"]
    assert "Bounded for an interactive answer" in result.narrative
    assert "apex dream --land" in result.narrative
    # No surfaced direction comes from a skipped objective (a real top-value subset).
    objectives = [d["objective"] for d in result.payload["directions"]]
    assert "strengthen-tests" not in objectives
    # The stub project's highest-value direction (implement-stub, 1.00) survives the
    # bound — the leading direction is preserved, never dropped.
    assert "implement-stub" in objectives


def test_dream_route_bounded_directions_capped_and_deterministic(tmp_path):
    """The displayed directions are capped (a stable head, never a flood) and the
    whole bounded answer is deterministic — the same request renders byte-identical
    run to run (the bound selects by a fixed key, no clock/random)."""
    root = _stub_project(tmp_path)
    a = assist("what should I build next?", target=str(root))
    b = assist("what should I build next?", target=str(root))
    # Deterministic narrative AND payload.
    assert a.narrative == b.narrative
    assert a.payload["directions"] == b.payload["directions"]
    # The rendered list is capped to a stable head; the rest is an honest "+N more".
    shown = a.narrative.count("buyer-value")
    assert shown <= 5
    if a.payload["total"] > shown:
        assert "more." in a.narrative


# --- the QUESTION route: grade ----------------------------------------------

def test_plain_question_routes_to_grade(tmp_path):
    root = _modernize_project(tmp_path)
    before = _tree_snapshot(root)

    result = assist("is this well tested?", target=str(root))

    assert result.route == "grade"
    assert result.applied is False
    # Real grade numbers, not advice.
    assert isinstance(result.payload["score"], int)
    assert 0 <= result.payload["score"] <= 100
    assert result.payload["letter"]
    assert "components" in result.payload
    # The narrative echoes the question and shows the grounded breakdown.
    assert "is this well tested?" in result.narrative
    assert "/100" in result.narrative
    # READ-ONLY.
    assert _tree_snapshot(root) == before


# --- the DEPS route: real import cycles + fan-in hubs ------------------------

def test_coupling_question_routes_to_deps_with_grounded_numbers(tmp_path):
    root = _coupled_project(tmp_path)
    before = _tree_snapshot(root)

    result = assist("why is this module so coupled?", target=str(root))

    assert result.route == "deps"
    assert result.applied is False
    # GROUNDED: the real import cycle (a <-> b) is detected off the import graph.
    assert result.payload["cycle_count"] == 1
    cyc = result.payload["cycles"][0]
    assert cyc[0] == cyc[-1]                  # a cycle ends back at its start
    assert set(cyc) == {"a.py", "b.py"}
    # GROUNDED: the top fan-in hub is `a.py` (imported by both b and c).
    hubs = result.payload["hubs"]
    assert hubs, "the coupled project should surface fan-in hubs"
    assert hubs[0]["module"] == "a.py"
    assert hubs[0]["fan_in"] == 2
    # Hubs ranked by fan-in descending (deterministic order into the payload).
    fan_ins = [h["fan_in"] for h in hubs]
    assert fan_ins == sorted(fan_ins, reverse=True)
    # The narrative echoes the question and narrates the grounded shape + NEXT.
    md = result.narrative
    assert "why is this module so coupled?" in md
    assert "Import cycles: 1" in md
    assert "`a.py` → `b.py` → `a.py`" in md
    assert "2 dependent module(s)" in md
    assert "regression test" in md  # the highest-fan-in-hub NEXT suggestion
    assert "Break a cycle" in md    # the cycle-breaking NEXT suggestion
    # READ-ONLY: nothing was written.
    assert _tree_snapshot(root) == before


def test_cycle_question_routes_to_deps(tmp_path):
    """A "are there circular imports?" question is a coupling question → DEPS."""
    root = _coupled_project(tmp_path)
    result = assist("are there circular imports?", target=str(root))
    assert result.route == "deps"
    assert result.payload["cycle_count"] == 1


def test_deps_route_narrates_clean_when_no_cycles(tmp_path):
    """A flat, acyclic project narrates "0 cycles — clean" honestly (no cycle is
    invented) while still surfacing the fan-in hubs."""
    (tmp_path / "leaf.py").write_text("def g():\n    return 1\n", encoding="utf-8")
    (tmp_path / "top.py").write_text(
        "import leaf\ndef f():\n    return leaf.g()\n", encoding="utf-8")
    before = _tree_snapshot(tmp_path)

    result = assist("what does this depend on?", target=str(tmp_path))

    assert result.route == "deps"
    assert result.payload["cycle_count"] == 0
    assert "0 — clean" in result.narrative
    # leaf.py is a (single-dependent) fan-in hub.
    assert result.payload["hubs"][0]["module"] == "leaf.py"
    assert _tree_snapshot(tmp_path) == before


def test_deps_route_is_deterministic(tmp_path):
    root = _coupled_project(tmp_path)
    a = assist("why is this module so coupled?", target=str(root))
    b = assist("why is this module so coupled?", target=str(root))
    # Deterministic narrative AND payload (no clock/random; sorted organ output).
    assert a.narrative == b.narrative
    assert a.payload == b.payload


def test_plain_non_coupling_question_still_routes_to_grade(tmp_path):
    """REGRESSION-LOCK: a plain, non-coupling question is unchanged — it still
    routes to the grade, byte-identically to before the deps route existed."""
    root = _coupled_project(tmp_path)
    result = assist("is this well tested?", target=str(root))
    assert result.route == "grade"
    assert isinstance(result.payload["score"], int)
    assert "/100" in result.narrative


# --- the DEVELOP route: preview then land -----------------------------------

def test_develop_request_previews_without_writing(tmp_path):
    root = _modernize_project(tmp_path)
    before = _tree_snapshot(root)

    result = assist("modernize the code", target=str(root), apply=False)

    assert result.route == "develop"
    assert result.applied is False
    # PLAN: the right objective is named and value-led.
    assert "modernize" in result.payload["objectives"]
    assert result.comprehension.action == "develop"
    # The narrative echoes the understanding and grounds the preview.
    assert "I understood a **develop** request" in result.narrative
    assert "Preview" in result.narrative
    # PREVIEW writes nothing.
    assert _tree_snapshot(root) == before


def test_develop_request_apply_lands_covered_move_suite_green(tmp_path):
    root = _modernize_project(tmp_path)

    result = assist("modernize the code", target=str(root), apply=True)

    assert result.route == "develop"
    assert result.applied is True
    # The covered move actually landed and is VERIFIED (a test exercises greet()).
    after = (root / "mod.py").read_text(encoding="utf-8")
    assert "if name is None" in after
    assert "== None" not in after
    assert "verified move(s)" in result.narrative
    # A verified move proves the suite ran green through the gated compiler.
    verified = sum(
        1 for r in result._results for s in r.steps if s.coverage_verified)
    assert verified >= 1


def test_report_mode_pins_preview_even_with_apply(tmp_path):
    """An explicit "just show me" (report mode) previews even with apply=True —
    SAFE by default; the resolved write gate honors comprehend's mode."""
    root = _modernize_project(tmp_path)
    before = _tree_snapshot(root)

    result = assist("just show me how you would modernize the code",
                    target=str(root), apply=True)

    assert result.route == "develop"
    assert result.comprehension.mode == "report"
    assert result.applied is False
    assert result.payload["write"] is False
    assert _tree_snapshot(root) == before


# --- LEVEL 3: autonomous APPLY + AUTO-COMMIT (covered-verified-only) --------

def test_resolve_commit_gate_requires_apply_commit_and_autonomous_mode():
    """The pure gate: only ``commit and apply and mode == "autonomous"``."""
    autonomous = comprehend("automatically modernize the code")
    supervised = comprehend("modernize the code")
    report = comprehend("just show me how you would modernize the code")
    assert autonomous.mode == "autonomous"
    assert supervised.mode == "supervised"
    assert report.mode == "report"

    assert _resolve_commit(autonomous, True, True) is True
    # Missing any one of the three inputs refuses the commit.
    assert _resolve_commit(autonomous, True, False) is False   # no --commit
    assert _resolve_commit(autonomous, False, True) is False   # apply resolved off
    assert _resolve_commit(supervised, True, True) is False    # not autonomous
    assert _resolve_commit(report, True, True) is False        # report never commits


def test_working_tree_clean_reports_clean_and_dirty(tmp_path):
    _init_git(tmp_path)
    assert _working_tree_clean(str(tmp_path)) is True
    (tmp_path / "untracked.py").write_text("x = 1\n", encoding="utf-8")
    assert _working_tree_clean(str(tmp_path)) is False


def test_working_tree_clean_is_false_for_a_non_repo(tmp_path):
    assert _working_tree_clean(str(tmp_path)) is False


def test_supervised_apply_commit_lands_but_does_not_commit(tmp_path):
    """REGRESSION GUARD: a supervised-phrased request with --apply --commit must
    NOT auto-commit — it lands exactly like a bare --apply (applied-uncommitted).
    This is the human-gated default the design pins: only an EXPLICITLY
    autonomous request may auto-commit."""
    root = _modernize_project(tmp_path)
    _init_git(root)
    before_head = _git_log_hashes(root)

    result = assist("modernize the code", target=str(root), apply=True, commit=True)

    assert result.comprehension.mode == "supervised"
    assert result.payload["write"] is True
    assert result.payload["commit"] is False
    assert result.applied is True
    # The move actually landed on disk (write did happen) …
    after = (root / "mod.py").read_text(encoding="utf-8")
    assert "is None" in after
    # … but NOTHING was committed: no new commit, and no result claims one.
    assert _git_log_hashes(root) == before_head
    assert all(not r.committed for r in result._results)
    assert "committed" not in result.narrative.split("## Next")[0].lower() \
        or "not committed" in result.narrative.lower()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                            capture_output=True, text=True)
    assert status.stdout.strip()  # the applied change is still sitting uncommitted


def test_autonomous_apply_commit_lands_and_commits_covered_move(tmp_path):
    """The LEVEL 3 happy path: an explicitly autonomous request + a covered move
    auto-commits — a real new git commit touching exactly the changed file(s)."""
    root = _modernize_project(tmp_path)
    _init_git(root)
    before_head = _git_log_hashes(root)

    result = assist("automatically modernize the code", target=str(root),
                    apply=True, commit=True)

    assert result.comprehension.mode == "autonomous"
    assert result.payload["write"] is True
    assert result.payload["commit"] is True
    # A real NEW commit landed.
    after_head = _git_log_hashes(root)
    assert after_head != before_head
    assert after_head[0] not in before_head
    # Exactly the changed file(s) were committed — nothing extra swept in.
    changed = _git_changed_files(root, after_head[0])
    assert changed == {"mod.py"}
    # The tree is clean of the CHANGED source afterward (the commit landed
    # everything the move touched); the only leftover untracked entry is the
    # organism's own ``.apex/`` idea-memory side-artifact, not part of the move.
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                            capture_output=True, text=True)
    remaining = {line for line in status.stdout.splitlines() if ".apex" not in line}
    assert not remaining
    # The result discloses the real commit.
    committed_results = [r for r in result._results if r.committed]
    assert committed_results
    assert committed_results[0].commit_hash
    assert committed_results[0].commit_hash in after_head[0]
    assert "auto-committed" in result.narrative
    assert committed_results[0].commit_hash in result.narrative


def test_autonomous_apply_commit_uncovered_move_rolls_back_nothing_to_commit(
        tmp_path):
    """An autonomous request whose only candidate move is UNCOVERED: the
    covered-only sweep (already armed by ``apply=True``) rolls it back before it
    ever reaches ``result.steps`` — nothing lands, so nothing commits."""
    (tmp_path / "mod.py").write_text(
        "def greet(name):\n"
        "    if name == None:\n"
        "        return 'hi'\n"
        "    return 'hi ' + name\n",
        encoding="utf-8")
    # No test references mod.py at all — coverage == "none".
    (tmp_path / "test_other.py").write_text(
        "def test_trivial():\n    assert True\n", encoding="utf-8")
    _init_git(tmp_path)
    before_head = _git_log_hashes(tmp_path)

    result = assist("automatically modernize the code", target=str(tmp_path),
                    apply=True, commit=True)

    assert result.comprehension.mode == "autonomous"
    # The covered-only gate withheld the move: nothing landed as a step.
    modernize_results = [r for r in result._results if r.objective == "modernize"]
    assert modernize_results
    assert modernize_results[0].steps == []
    assert modernize_results[0].withheld
    assert modernize_results[0].committed is False
    # No new commit — nothing to commit.
    assert _git_log_hashes(tmp_path) == before_head


def test_commit_result_withholds_tier1_move_verified_only_at_module_coverage():
    """THE CRITICAL SOUNDNESS TEST: a Tier-1 (behaviour-adjacent) step whose green
    suite proves only ``module`` coverage (a smoke import, not a test that names
    the changed function) is NOT ``coverage_verified`` — so ``_commit_result``
    must WITHHOLD the commit even though the step is present in ``result.steps``
    and even though ``covered_only`` alone (module-coverage passes it for a
    Tier-0 move) would have let it through. This is the extra, stricter,
    per-step gate ``_commit_result`` adds on top of ``covered_only``."""
    tier1_module_only = CompileStep(
        operator="harden", target="risky.py:harden", description="harden risky.py",
        fitness_before=1.0, fitness_after=0.0,
        verified=True, coverage="module", tier=1)
    assert tier1_module_only.coverage_verified is False  # the tier-aware verdict

    result = CompileResult(objective="harden-security", fitness_start=1.0,
                           fitness_end=0.0, steps=[tier1_module_only], applied=True)

    _commit_result("/nonexistent/does/not/matter", result)

    assert result.committed is False
    assert result.commit_hash == ""


def test_commit_result_commits_when_every_step_is_coverage_verified(tmp_path):
    """A direct unit test of ``_commit_result``'s happy path, isolated from the
    develop route: every step verified at its tier → a real commit."""
    root = tmp_path
    (root / "mod.py").write_text("x = 1\n", encoding="utf-8")
    _init_git(root)
    (root / "mod.py").write_text("x = 2\n", encoding="utf-8")
    before_head = _git_log_hashes(root)

    tier0_ok = CompileStep(
        operator="modernize", target="mod.py:modernize", description="tidy mod.py",
        fitness_before=1.0, fitness_after=0.0,
        verified=True, coverage="module", tier=0)
    result = CompileResult(objective="modernize", fitness_start=1.0, fitness_end=0.0,
                           steps=[tier0_ok], applied=True)

    _commit_result(str(root), result)

    assert result.committed is True
    assert result.commit_hash
    assert _git_log_hashes(root) != before_head


def test_commit_result_is_a_noop_when_nothing_landed():
    """No steps -> no commit, no crash, no git call needed."""
    result = CompileResult(objective="modernize", fitness_start=0.0, fitness_end=0.0,
                           steps=[], applied=False)
    _commit_result("/nonexistent/does/not/matter", result)
    assert result.committed is False
    assert result.commit_hash == ""


def test_commit_true_but_apply_false_never_writes_or_commits(tmp_path):
    """``commit=True`` with ``apply=False`` (the caller's own resolved-apply
    still gates on comprehend's mode/apply arg) must not write OR commit —
    apply is the write gate; commit can never fire without it."""
    root = _modernize_project(tmp_path)
    _init_git(root)
    before = _tree_snapshot(root)
    before_head = _git_log_hashes(root)

    result = assist("automatically modernize the code", target=str(root),
                    apply=False, commit=True)

    assert result.payload["write"] is False
    assert result.payload["commit"] is False
    assert result.applied is False
    assert _tree_snapshot(root) == before
    assert _git_log_hashes(root) == before_head


def test_dirty_working_tree_refuses_commit_and_leaves_preexisting_change(tmp_path):
    """A dirty tree at the START of the run refuses the commit gate entirely (the
    develop write still lands — apply already resolved) and the PRE-EXISTING
    uncommitted change is left completely untouched (never swept into a commit,
    never reverted)."""
    root = _modernize_project(tmp_path)
    _init_git(root)
    # A pre-existing, unrelated uncommitted change — must survive untouched.
    unrelated = root / "unrelated.py"
    unrelated.write_text("# a pre-existing WIP change\nvalue = 1\n", encoding="utf-8")
    before_unrelated = unrelated.read_text(encoding="utf-8")
    before_head = _git_log_hashes(root)

    result = assist("automatically modernize the code", target=str(root),
                    apply=True, commit=True)

    assert result.comprehension.mode == "autonomous"
    assert result.payload["write"] is True
    # The dirty precondition refused the commit gate even though mode is autonomous.
    assert result.payload["commit"] is False
    assert all(not r.committed for r in result._results)
    # No new commit landed.
    assert _git_log_hashes(root) == before_head
    # The pre-existing unrelated change is untouched (still there, still uncommitted).
    assert unrelated.exists()
    assert unrelated.read_text(encoding="utf-8") == before_unrelated
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                            capture_output=True, text=True)
    assert "unrelated.py" in status.stdout


def test_narrative_discloses_applied_not_committed_distinctly(tmp_path):
    """The narrative must never blur "applied" and "committed" — a supervised
    landed move states plainly that it applied but did not commit."""
    root = _modernize_project(tmp_path)
    _init_git(root)

    result = assist("modernize the code", target=str(root), apply=True, commit=True)

    assert "applied — not committed" in result.narrative
    assert "auto-committed" not in result.narrative


def test_narrative_discloses_committed_hash_distinctly(tmp_path):
    root = _modernize_project(tmp_path)
    _init_git(root)

    result = assist("automatically modernize the code", target=str(root),
                    apply=True, commit=True)

    committed = [r for r in result._results if r.committed]
    assert committed
    assert f"committed `{committed[0].commit_hash}`" in result.narrative
    assert "applied — not committed" not in result.narrative


def test_cli_assist_apply_commit_end_to_end(tmp_path, monkeypatch, capsys):
    """CLI end-to-end: ``apex assist "automatically…" --apply --commit`` on a tmp
    git fixture lands a real commit and discloses it in ``--json``."""
    import json

    import app.cli as cli

    root = _modernize_project(tmp_path)
    _init_git(root)
    before_head = _git_log_hashes(root)

    monkeypatch.setattr("sys.argv", [
        "apex", "assist", "automatically modernize the code",
        "--target", str(root), "--apply", "--commit", "--json"])

    exit_code = cli.main()

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["route"] == "develop"
    dev_results = payload["payload"]["results"]
    committed_results = [r for r in dev_results if r.get("committed")]
    assert committed_results
    assert committed_results[0]["commit_hash"]
    after_head = _git_log_hashes(root)
    assert after_head != before_head


# --- scope restriction ------------------------------------------------------

def test_scope_request_restricts_to_the_named_module(tmp_path):
    """A request naming a module scopes the campaign to it (the compiler's
    ``scope_module``). Two modules, only one named — only it is targeted."""
    (tmp_path / "alpha.py").write_text(
        "def f(name):\n    if name == None:\n        return 1\n    return 2\n",
        encoding="utf-8")
    (tmp_path / "beta.py").write_text(
        "def g(name):\n    if name == None:\n        return 3\n    return 4\n",
        encoding="utf-8")
    (tmp_path / "test_both.py").write_text(
        "from alpha import f\nfrom beta import g\n"
        "def test_f():\n    assert f('x') == 2\n"
        "def test_g():\n    assert g('x') == 4\n",
        encoding="utf-8")

    result = assist("modernize the alpha module", target=str(tmp_path))

    assert result.comprehension.scope == "alpha"
    assert result.payload["scope"] == "alpha"
    # The bare hint resolved to the real module path the compiler scopes to.
    assert result.payload["scope_module"] == "alpha.py"
    # Every previewed step targets the scoped module only.
    targets = [s.target for r in result._results for s in r.steps]
    assert targets, "alpha has a modernizable line, so a move is previewed"
    assert all(t.startswith("alpha.py") for t in targets)


# --- the HONEST fallback: no matching capability ----------------------------

def test_unmappable_request_is_honest_and_recommends(tmp_path):
    root = _modernize_project(tmp_path)
    before = _tree_snapshot(root)

    result = assist("xyzzy foobar", target=str(root))

    assert result.route == "recommend"
    assert result.applied is False
    # HONEST: it says plainly it has no capability — never fabricates an action.
    assert "couldn't map this to a capability" in result.narrative
    assert "no matching capability" in result.narrative.lower()
    assert "don't have a capability that matches" in result.narrative
    assert result.comprehension.objectives == []
    # It still routes to a grounded recommend (the roadmap's best next moves).
    assert "quick_wins" in result.payload
    assert "apex auto" in result.narrative
    # READ-ONLY.
    assert _tree_snapshot(root) == before


def test_removal_of_additive_is_refused_not_inverted(tmp_path):
    """A removal-framed request that only matches ADD lenses must NOT invert intent
    — comprehend suppresses it (low confidence, no objectives), so assist routes to
    the honest recommend, never to a develop run that ADDS what was asked removed."""
    root = _modernize_project(tmp_path)
    before = _tree_snapshot(root)

    result = assist("remove the docstrings", target=str(root))

    assert result.route == "recommend"
    assert result.applied is False
    assert _tree_snapshot(root) == before


# --- determinism ------------------------------------------------------------

def test_dream_route_is_deterministic(tmp_path):
    root = _stub_project(tmp_path)
    a = assist("what should I build next?", target=str(root)).narrative
    b = assist("what should I build next?", target=str(root)).narrative
    assert a == b


def test_grade_route_is_deterministic(tmp_path):
    root = _modernize_project(tmp_path)
    a = assist("is this well tested?", target=str(root)).narrative
    b = assist("is this well tested?", target=str(root)).narrative
    assert a == b


def test_develop_preview_is_deterministic(tmp_path):
    root = _modernize_project(tmp_path)
    a = assist("modernize the code", target=str(root), apply=False).narrative
    b = assist("modernize the code", target=str(root), apply=False).narrative
    assert a == b


# --- the renderer ECHOES the understanding ----------------------------------

def test_render_echoes_request_and_understanding(tmp_path):
    root = _modernize_project(tmp_path)
    result = assist("add type hints to mod.py", target=str(root), apply=False)
    md = render_assist_markdown(result)
    # The echo block quotes the request and states the understood action + mode.
    assert "**You asked:** «add type hints to mod.py»" in md
    assert "I understood a **develop** request" in md
    assert "Confidence:" in md


def test_to_dict_is_json_safe(tmp_path):
    import json

    root = _stub_project(tmp_path)
    result = assist("what should I build next?", target=str(root))
    payload = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "dream" in payload
    assert "implement-stub" in payload
