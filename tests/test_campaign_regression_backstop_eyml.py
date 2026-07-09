"""FIX: standalone applied campaigns get the end-of-campaign regression backstop.

The 2026-07-08 adversarial audit finding: the transitive-regression full-suite
backstop existed ONLY in ``run_develop_session``. A standalone applied campaign —
``compile_objective(..., apply=True, verify=True)`` called directly (``apex
develop --objective X --apply``, the ``--auto`` sweep) or ``run_moves`` — ended
with NO re-verification, so a move whose impact-scoped per-move gate missed a
TRANSITIVELY-reachable previously-GREEN test landed and nothing ever re-checked.

The fix: when (and only when) the campaign OWNS its gate (``apply and verify``
and no caller-supplied ``baseline_failing`` — the develop session supplies one
and runs its OWN backstop), capture the before-snapshot + baseline failing-node
set up front; after the campaign, if files changed, re-run the suite ONCE, diff
failing nodes at TEST-FUNCTION granularity (``regressed_functions`` — a
pre-existing red is tolerated, never charged), and restore ALL changed files on
a regression. A COLLAPSED re-run (``suite_failing_nodes_checked`` invalid) fails
CLOSED: restore + honest disclosure, never "no regressions". The verdict is
disclosed on ``CompileResult.regression_backstop``.

Red-first: ``test_standalone_transitive_regression_rolled_back`` and
``test_run_moves_transitive_regression_rolled_back`` FAIL on the pre-fix code
(the regression landed and stayed — the exact hole
``test_transitive_regression_actually_lands_without_the_backstop`` used to pin
as the session-level violation witness). The additive-field pins cannot be
red-first (the field is new); they pin the contract end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.objective_compiler import (
    BACKSTOP_CLEAN,
    BACKSTOP_INVALID,
    BACKSTOP_REGRESSED,
    CompileResult,
    CompileStep,
    Move,
    compile_objective,
    render_compile_markdown,
    run_moves,
)
from app.execution.cross_file_rename import RenamePlan

_WRAPPER_NODE = "tests/test_wrapper.py::test_missing_is_blank"


def _transitive_regression_project(root: Path) -> Path:
    """The proven transitive-regression shape (mirrors the develop-session
    fixture): a RED baseline forces impact-scoped thinking, ``modernize``'s
    ``== None`` -> ``is None`` rewrite passes its OWN in-scope test, and the
    previously-GREEN ``test_wrapper`` — reachable only through an exec-string
    dynamic import the scope scan cannot see — breaks."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("__all__ = []\n", encoding="utf-8")
    (root / "pkg" / "sentinel.py").write_text(
        "class Missing:\n"
        "    def __eq__(self, other):\n"
        "        return other is None or isinstance(other, Missing)\n"
        "    def __hash__(self):\n        return 0\n\n\n"
        "MISSING = Missing()\n", encoding="utf-8")
    (root / "pkg" / "check.py").write_text(
        "def is_blank(value):\n    return value == None\n", encoding="utf-8")
    (root / "pkg" / "wrapper.py").write_text(
        "from pkg.check import is_blank\n\n\n"
        "def blank_via_wrapper(value):\n    return is_blank(value)\n",
        encoding="utf-8")
    (root / "tests" / "test_check.py").write_text(
        "from pkg.check import is_blank\n"
        "def test_blank_none():\n    assert is_blank(None) is True\n"
        "def test_blank_value():\n    assert is_blank(7) is False\n",
        encoding="utf-8")
    (root / "tests" / "test_wrapper.py").write_text(
        "from pkg.sentinel import MISSING\n"
        "def _wrapper():\n"
        "    ns = {}\n"
        "    exec('from pkg.wrapper import blank_via_wrapper', ns)\n"
        "    return ns['blank_via_wrapper']\n"
        "def test_missing_is_blank():\n"
        "    assert _wrapper()(MISSING) is True\n", encoding="utf-8")
    (root / "tests" / "test_unrelated_red.py").write_text(
        "def test_preexisting_failure():\n    assert 1 == 2\n", encoding="utf-8")
    return root


def _dead_param_project(root: Path) -> Path:
    """A green-baseline project with one droppable (harmless) dead parameter."""
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "m.py").write_text(
        "__all__ = ['use']\n\n\n"
        "def render(text, color=None, width=80):\n"
        "    return text[:width]\n\n\n"
        "def use():\n"
        "    return render('hi', width=10)\n", encoding="utf-8")
    (root / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_import():\n    assert app.m is not None\n",
        encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return root


# --- THE fix, end-to-end: compile_objective ------------------------------------

def test_standalone_transitive_regression_rolled_back(tmp_path: Path):
    # RED-FIRST: pre-fix this exact campaign LANDED the behaviour-changing move
    # (its own in-scope test passes) and the previously-GREEN transitive test
    # stayed broken forever — nothing ever re-checked.
    _transitive_regression_project(tmp_path)
    check_before = (tmp_path / "pkg" / "check.py").read_text()

    result = compile_objective(str(tmp_path), objective="modernize",
                               apply=True, verify=True, scope_verify=True)

    # The backstop caught the transitive regression and restored EVERY file.
    assert result.regression_backstop == BACKSTOP_REGRESSED
    assert result.backstop_regressed_nodes == [_WRAPPER_NODE]
    assert result.steps == []  # nothing stands — no phantom contributions
    assert result.fitness_end == result.fitness_start
    assert (tmp_path / "pkg" / "check.py").read_text() == check_before
    assert "== None" in (tmp_path / "pkg" / "check.py").read_text()

    # Honest disclosure: rendered loudly, and on the dict artifact.
    md = render_compile_markdown(result)
    assert "backstop" in md
    assert "ROLLED BACK" in md or "restored" in md
    assert _WRAPPER_NODE in md
    d = result.to_dict()
    assert d["regression_backstop"] == BACKSTOP_REGRESSED
    assert d["backstop_regressed_nodes"] == [_WRAPPER_NODE]


def test_backstop_rollback_is_deterministic(tmp_path: Path):
    # Same fixture twice -> identical verdict, nodes, and report bytes.
    a = _transitive_regression_project(tmp_path / "a")
    b = _transitive_regression_project(tmp_path / "b")
    ra = compile_objective(str(a), objective="modernize", apply=True,
                           verify=True, scope_verify=True)
    rb = compile_objective(str(b), objective="modernize", apply=True,
                           verify=True, scope_verify=True)
    assert ra.regression_backstop == rb.regression_backstop == BACKSTOP_REGRESSED
    assert ra.backstop_regressed_nodes == rb.backstop_regressed_nodes
    assert render_compile_markdown(ra) == render_compile_markdown(rb)
    assert (a / "pkg" / "check.py").read_text() == (
        b / "pkg" / "check.py").read_text()


def test_clean_apply_keeps_changes_and_discloses_clean(tmp_path: Path):
    # NO-OVER-ROLLBACK: a green-baseline campaign whose changes break nothing
    # keeps its moves; the backstop verdict is the honest "clean".
    _dead_param_project(tmp_path)
    result = compile_objective(str(tmp_path), objective="dead-params",
                               apply=True, verify=True)
    assert result.steps  # the move stands
    assert "color" not in (tmp_path / "app" / "m.py").read_text()
    assert result.regression_backstop == BACKSTOP_CLEAN
    assert result.backstop_regressed_nodes == []
    # Disclosed on the dict; the markdown carries NO rollback banner.
    assert result.to_dict()["regression_backstop"] == BACKSTOP_CLEAN
    assert "restored to its pre-campaign bytes" not in render_compile_markdown(result)


def test_pre_existing_red_is_tolerated_never_charged(tmp_path: Path):
    # RED BASELINE TOLERANCE: a pre-existing failing test (red at baseline and
    # still red after) never triggers the backstop rollback — the diff is at
    # test-function granularity against the captured baseline set.
    _dead_param_project(tmp_path)
    (tmp_path / "tests" / "test_red.py").write_text(
        "def test_fail():\n    assert False\n", encoding="utf-8")
    result = compile_objective(str(tmp_path), objective="dead-params",
                               apply=True, verify=True)
    assert result.steps  # the harmless move still lands
    assert "color" not in (tmp_path / "app" / "m.py").read_text()
    assert result.regression_backstop == BACKSTOP_CLEAN
    assert result.backstop_regressed_nodes == []


def test_backstop_fails_closed_on_collapsed_rerun(tmp_path: Path, monkeypatch):
    # FAIL-CLOSED: a re-run that collapsed before its per-test summary measured
    # NOTHING — reading it as "no regressions" would be the exact fake green the
    # backstop exists to prevent. The campaign is restored and the collapse
    # disclosed. (Baseline capture is the first checked call; the re-run the
    # second — the fake collapses only the re-run.)
    from app.execution import _apply_verify as av

    _dead_param_project(tmp_path)
    before = (tmp_path / "app" / "m.py").read_text()
    calls = {"n": 0}

    def fake_checked(root):
        calls["n"] += 1
        if calls["n"] == 1:
            return True, True, frozenset()  # baseline: available, valid, green
        return True, False, frozenset()     # re-run: collapsed — NOT comparable

    monkeypatch.setattr(av, "suite_failing_nodes_checked", fake_checked)
    result = compile_objective(str(tmp_path), objective="dead-params",
                               apply=True, verify=True)
    assert calls["n"] >= 2  # the re-run genuinely happened
    assert result.regression_backstop == BACKSTOP_INVALID
    assert result.steps == []
    assert (tmp_path / "app" / "m.py").read_text() == before  # restored
    md = render_compile_markdown(result)
    assert "could not vouch" in md or "fail closed" in md
    assert result.regression_backstop != BACKSTOP_CLEAN


# --- run_moves gets the same backstop -------------------------------------------

def _modernize_check_move(root: Path) -> Move:
    """A ready-built move that lands the behaviour-changing rewrite directly —
    the ``run_moves`` shape of the same transitive hole."""
    rel = "pkg/check.py"

    def _plan() -> RenamePlan:
        src = (root / rel).read_text(encoding="utf-8")
        plan = RenamePlan(old=rel, new="modernize None comparisons")
        plan.originals[rel] = src
        plan.new_contents[rel] = src.replace("value == None", "value is None")
        plan.edits_by_file[rel] = 1
        return plan

    return Move(operator="modernize", target=f"{rel}:modernize",
                description="modernize None comparisons in pkg/check.py",
                build_plan=_plan)


def test_run_moves_transitive_regression_rolled_back(tmp_path: Path):
    # RED-FIRST: pre-fix ``run_moves(apply=True)`` ended with no re-verification
    # at all — the impact-scoped gate let the move land and the broken
    # previously-GREEN transitive test was silently kept.
    _transitive_regression_project(tmp_path)
    check_before = (tmp_path / "pkg" / "check.py").read_text()

    result = run_moves(str(tmp_path), [_modernize_check_move(tmp_path)],
                       label="multifile-landing", apply=True, verify=True,
                       scope_verify=True)

    assert result.regression_backstop == BACKSTOP_REGRESSED
    assert result.backstop_regressed_nodes == [_WRAPPER_NODE]
    assert result.steps == []
    assert (tmp_path / "pkg" / "check.py").read_text() == check_before


def test_run_moves_suiteless_project_backstop_not_armed(tmp_path: Path):
    # Empty edge: with NO detectable suite there is no baseline to diff — the
    # backstop stays un-armed ("" verdict, additive key absent) and the honest
    # no-suite tier carries the disclosure, exactly as before.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "check.py").write_text(
        "def is_blank(value):\n    return value == None\n", encoding="utf-8")
    result = run_moves(str(tmp_path), [_modernize_check_move(tmp_path)],
                       label="x", apply=True, verify=True)
    assert result.steps  # landed (no-suite tier), not rolled back
    assert result.regression_backstop == ""
    assert "regression_backstop" not in result.to_dict()


# --- the backstop must NOT double up or fire off the gated path ------------------

def test_dry_run_and_no_verify_never_arm_backstop(tmp_path: Path, monkeypatch):
    # A dry run gates nothing and a --no-verify apply is unverified by choice:
    # neither may pay a probe/snapshot. The arm helper exploding proves it is
    # never consulted.
    from app.engine import objective_compiler as oc

    _dead_param_project(tmp_path)

    def _boom(root):
        raise AssertionError("backstop armed off the gated-apply path")

    monkeypatch.setattr(oc, "_arm_backstop", _boom)
    dry = compile_objective(str(tmp_path), objective="dead-params", apply=False)
    assert dry.steps and dry.regression_backstop == ""
    unverified = compile_objective(str(tmp_path), objective="dead-params",
                                   apply=True, verify=False)
    assert unverified.steps and unverified.regression_backstop == ""
    assert "regression_backstop" not in unverified.to_dict()


def test_caller_supplied_baseline_skips_standalone_backstop(tmp_path: Path,
                                                            monkeypatch):
    # The develop session supplies ``baseline_failing`` and runs its OWN
    # end-of-session backstop — the standalone one must stand down (no double
    # suite runs, no double rollback authority).
    from app.engine import objective_compiler as oc

    _dead_param_project(tmp_path)

    def _boom(root):
        raise AssertionError("standalone backstop armed under a session baseline")

    monkeypatch.setattr(oc, "_arm_backstop", _boom)
    result = compile_objective(str(tmp_path), objective="dead-params",
                               apply=True, verify=True,
                               baseline_failing=frozenset())
    assert result.steps  # the campaign itself is unaffected
    assert result.regression_backstop == ""


# --- additive-field contract (cannot be red-first: the field is new) ------------

def test_backstop_field_default_keeps_existing_constructions_valid():
    r = CompileResult(objective="x", fitness_start=1.0, fitness_end=1.0)
    assert r.regression_backstop == ""
    assert r.backstop_regressed_nodes == []
    d = r.to_dict()
    assert "regression_backstop" not in d
    assert "backstop_regressed_nodes" not in d


def test_compile_step_native_shapes_field_default():
    # ADDITIVE-FIELD CONTRACT (cannot be red-first: the field is new) — mirrors
    # test_backstop_field_default_keeps_existing_constructions_valid above.
    step = CompileStep(operator="x", target="y", description="d",
                       fitness_before=1.0, fitness_after=0.0)
    assert step.native_shapes == ()
    d = step.to_dict()
    assert "native_shapes" not in d  # internal bookkeeping, never serialized


# --- W3A-L4: backstop rollbacks feed the proof-of-fix experience memory --------
#
# A per-move rollback in the maintain path already gets recorded with
# ``outcome: "rolled_back"`` (feeding should_avoid/fragility via
# ``counterfactual_learning``/``proof_history``). A CAMPAIGN-LEVEL backstop
# rollback used to write NO record at all — the swept moves were correctly
# excluded from ever being claimed "applied" (never-fake-green intact), but the
# honest INVERSE ("this was tried here and it broke something") never reached
# the ledger either, so the organism could never learn from it. These tests pin
# the fix: a fail-closed correction writer (``_record_backstop_ledger_correction``)
# that ``_backstop_restore`` now calls before returning.

def test_standalone_backstop_rollback_writes_rolled_back_proof(tmp_path: Path):
    # RED-FIRST: pre-fix a rolled-back standalone campaign left NO
    # .apex/proof-of-fix.json at all — nothing to assert on.
    _transitive_regression_project(tmp_path)
    result = compile_objective(str(tmp_path), objective="modernize",
                               apply=True, verify=True, scope_verify=True)
    assert result.regression_backstop == BACKSTOP_REGRESSED

    proof_path = tmp_path / ".apex" / "proof-of-fix.json"
    assert proof_path.exists()
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["mode"] == "develop-backstop"
    assert proof["fixes"]
    for rec in proof["fixes"]:
        assert rec["outcome"] == "rolled_back"
        assert rec["finding"]["action"] == "modernize"
        assert rec["finding"]["target"]  # non-empty: names the swept module
        assert rec["rollback"]["occurred"] is True
        assert rec["rollback"]["reason"] == BACKSTOP_REGRESSED
    assert proof["totals"]["applied"] == 0
    assert proof["totals"]["rolled_back"] == len(proof["fixes"])


def test_standalone_backstop_correction_feeds_should_avoid(tmp_path: Path):
    # RED-FIRST (replaces an OVERCLAIMING version of this same test — CRITICAL
    # soundness, W3A-L4 finding 1). The original body only checked
    # ``summarise_fix_track_record``'s ``by_action["modernize"]`` tally — but
    # that tally reads whatever key ``finding.action`` happens to hold, and for
    # the `modernize` objective the operator ALSO happens to be literally
    # `"modernize"` (see ``_tidy_transforms``), so the assertion passed whether
    # the writer stamped the objective name OR the operator. It could never
    # distinguish a correctly-keyed correction from a mis-keyed one, despite its
    # name claiming to prove the should_avoid wiring.
    #
    # The REAL consumer is ``_avoid_flagged_targets`` ->
    # ``should_avoid(signatures, mv.operator, module_traits(...))`` — it is
    # queried by OPERATOR, never by objective name. This version uses the
    # `dead-params` objective, whose real operator is `drop_param` — genuinely
    # DIFFERENT from the objective name — and calls the unit
    # ``_record_backstop_ledger_correction`` writer directly (the reviewer's
    # exact repro: >= 3 corrections against the SAME (operator, module)
    # signature), then calls ``should_avoid`` itself, exactly as
    # ``_avoid_flagged_targets`` does. Pre-fix (``finding.action = objective``)
    # this is RED: ``should_avoid`` queried by operator sees NO matching
    # signature at all.
    from app.engine import objective_compiler as oc
    from app.engine.counterfactual_learning import (
        failure_signatures,
        module_traits,
        should_avoid,
    )
    from app.engine.proof_history import load_proof_history

    objective, operator = "dead-params", "drop_param"
    # Three DISTINCT targets (same trait bucket: none is a test/init/deep/
    # entrypoint path, so ``module_traits`` maps all three to ``{"generic"}``)
    # so each of the 3 corrections is a content-DISTINCT proof — writing the
    # byte-identical proof 3 times over would content-hash-dedupe into a single
    # archived entry (``proof_of_fix._archive_proof``), understating attempts.
    targets = ["app/m1.py:use(width)", "app/m2.py:use(width)",
              "app/m3.py:use(width)"]
    for target in targets:
        assert oc._record_backstop_ledger_correction(
            tmp_path, [(objective, operator, target, "function")],
            BACKSTOP_REGRESSED, "develop-backstop") is True

    signatures = failure_signatures(load_proof_history(tmp_path))
    traits = module_traits(targets[0])
    assert traits == module_traits(targets[1]) == module_traits(targets[2])
    # THE reviewer's exact repro: the runtime avoid-guard queries by OPERATOR.
    assert should_avoid(signatures, operator, traits) is True
    # ...and NEVER by the objective name — the exact mismatch this fix corrects.
    assert should_avoid(signatures, objective, traits) is False


def test_backstop_invalid_rerun_also_writes_rolled_back_proof(
        tmp_path: Path, monkeypatch):
    # RED-FIRST: pre-fix a collapsed-rerun (fail-closed) restore ALSO wrote no
    # correction proof.
    from app.execution import _apply_verify as av

    _dead_param_project(tmp_path)
    calls = {"n": 0}

    def fake_checked(root):
        calls["n"] += 1
        if calls["n"] == 1:
            return True, True, frozenset()  # baseline: available, valid, green
        return True, False, frozenset()     # re-run: collapsed — NOT comparable

    monkeypatch.setattr(av, "suite_failing_nodes_checked", fake_checked)
    result = compile_objective(str(tmp_path), objective="dead-params",
                               apply=True, verify=True)
    assert result.regression_backstop == BACKSTOP_INVALID

    proof_path = tmp_path / ".apex" / "proof-of-fix.json"
    assert proof_path.exists()
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["fixes"]
    for rec in proof["fixes"]:
        assert rec["outcome"] == "rolled_back"
        # CONSUMER-CORRECT KEY (W3A-L4 finding 1): action is the OPERATOR
        # (`drop_param`), not the objective name (`dead-params`) — the label
        # keeps the objective for human attribution.
        assert rec["finding"]["action"] == "drop_param"
        assert rec["finding"]["label"] == "dead-params"
        assert rec["rollback"]["reason"] == BACKSTOP_INVALID
    assert proof["totals"]["applied"] == 0


def test_backstop_clean_writes_no_correction_proof(tmp_path: Path):
    # NON-REGRESSION PIN (not red-first — must already pass and keep passing): a
    # clean campaign (nothing swept) never touches the ledger.
    _dead_param_project(tmp_path)
    result = compile_objective(str(tmp_path), objective="dead-params",
                               apply=True, verify=True)
    assert result.regression_backstop == BACKSTOP_CLEAN
    assert not (tmp_path / ".apex" / "proof-of-fix.json").exists()


def test_ledger_correction_writer_is_fail_closed(tmp_path: Path, monkeypatch):
    # A pure unit test of the writer's own contract (design PLAN item 1): never
    # raises, no-ops on an empty sweep, and returns False (never an exception)
    # when the underlying write fails.
    from app.engine import objective_compiler as oc
    from app.engine import proof_of_fix

    # No-op on an empty sweep.
    assert oc._record_backstop_ledger_correction(tmp_path, [], "x", "develop-backstop") is True
    assert not (tmp_path / ".apex").exists()

    # A genuine write succeeds and is discoverable by load_proof_history.
    swept = [("modernize", "modernize", "pkg/check.py", "function")]
    assert oc._record_backstop_ledger_correction(
        tmp_path, swept, BACKSTOP_REGRESSED, "develop-backstop") is True
    proof_path = tmp_path / ".apex" / "proof-of-fix.json"
    assert proof_path.exists()

    # FAIL-CLOSED: a raising write_proof never propagates — the writer swallows
    # it and reports False instead of crashing the restore it is correcting for.
    def _boom(proof, project_root, out=None):
        raise OSError("disk full")

    monkeypatch.setattr(proof_of_fix, "write_proof", _boom)
    assert oc._record_backstop_ledger_correction(
        tmp_path, swept, BACKSTOP_REGRESSED, "develop-backstop") is False


def test_backstop_restore_discloses_when_ledger_write_fails(
        tmp_path: Path, monkeypatch):
    # PRE-FIX: the disclosure function doesn't exist yet, so this pins the
    # fail-closed contract going forward — a ledger-write failure must never
    # silently swallow itself; it is disclosed loudly on ``result.blocked``, and
    # the tree is STILL restored (the write failure never blocks the rollback).
    from app.engine import objective_compiler as oc

    _transitive_regression_project(tmp_path)
    check_before = (tmp_path / "pkg" / "check.py").read_text(encoding="utf-8")

    monkeypatch.setattr(oc, "_record_backstop_ledger_correction",
                        lambda *a, **kw: False)
    result = compile_objective(str(tmp_path), objective="modernize",
                               apply=True, verify=True, scope_verify=True)

    assert result.regression_backstop == BACKSTOP_REGRESSED
    assert result.steps == []  # the restore itself is unaffected
    assert (tmp_path / "pkg" / "check.py").read_text(encoding="utf-8") == check_before
    assert any("could not correct the proof ledger" in b for b in result.blocked)
    # No proof was actually written (the forced failure never touched disk).
    assert not (tmp_path / ".apex" / "proof-of-fix.json").exists()


def test_backstop_restore_withholds_correction_when_tree_restore_incomplete(
        tmp_path: Path, monkeypatch):
    # RED-FIRST (LOW but never-fake-green, W3A-L4 finding 5): pre-fix
    # ``restore_py_tree``'s per-path write failures were silently swallowed
    # (best-effort, no return value) and ``_backstop_restore`` STILL
    # unconditionally wrote a "rolled_back" ledger correction — a DURABLE
    # false-negative: the ledger would claim the tree is safely back at
    # baseline (something should_avoid/fragility could learn "avoid this"
    # from) even though a file write genuinely failed and the tree is NOT
    # actually restored. FIX: the caller now trusts ``restore_py_tree``'s
    # reported failures and WITHHOLDS the ledger correction entirely on ANY
    # failure — saying nothing true beats saying something false.
    from app.engine import tree_snapshot as ts

    _transitive_regression_project(tmp_path)
    real_restore = ts.restore_py_tree

    def _flaky_restore(root, before, after):
        # The genuine restore still runs (so the fixture stays realistic); we
        # only inject one path into its reported failure list, exactly as a
        # real ``OSError`` on that path's write would.
        failed = real_restore(root, before, after)
        return sorted({*failed, "pkg/check.py"})

    monkeypatch.setattr(ts, "restore_py_tree", _flaky_restore)
    result = compile_objective(str(tmp_path), objective="modernize",
                               apply=True, verify=True, scope_verify=True)

    assert result.regression_backstop == BACKSTOP_REGRESSED
    # The ledger correction was WITHHELD — never a false "rolled_back" claim.
    assert not (tmp_path / ".apex" / "proof-of-fix.json").exists()
    assert any(
        "restore incomplete" in b and "ledger correction withheld" in b
        for b in result.blocked)


def test_backstop_disclosures_survive_blocked_truncation(
        tmp_path: Path, monkeypatch):
    # RED-FIRST (MEDIUM, W3A-L4 finding 4): pre-fix the backstop disclosures
    # (the ledger-correction-failure message and the native-experience
    # pollution message) were APPENDED to ``result.blocked`` — so a busy
    # campaign that already accumulated >=10 ordinary blocked entries pushed
    # them past ``render_compile_markdown``'s ``blocked[:10]`` window, and the
    # campaign-verdict-critical rollback disclosure silently vanished from the
    # rendered report. FIX: ``_backstop_restore`` now INSERTS its disclosures
    # at position 0.
    from app.engine import objective_compiler as oc

    result = CompileResult(objective="modernize", fitness_start=1.0,
                           fitness_end=0.0)
    result.steps = [CompileStep(
        operator="modernize", target="pkg/x.py:modernize", description="d",
        fitness_before=1.0, fitness_after=0.0, verified=True, coverage="module",
        native_shapes=("2:p0 + p1",))]
    # 12 ordinary blocked entries accumulated EARLIER in the same campaign —
    # more than ``blocked[:10]`` can hold on its own.
    result.blocked = [f"ordinary blocked reason #{i}" for i in range(12)]
    backstop = oc._BackstopState(baseline_failing=frozenset(), before={})
    monkeypatch.setattr(oc, "_record_backstop_ledger_correction",
                        lambda *a, **kw: False)

    oc._backstop_restore(
        result, str(tmp_path), backstop, {}, BACKSTOP_REGRESSED,
        "W3A-L4-UNIT-TEST-MARKER: end-of-campaign backstop restored the tree")

    md = render_compile_markdown(result)
    assert "could not correct the proof ledger" in md
    assert "native-experience memory" in md and "2:p0 + p1" in md
    assert "W3A-L4-UNIT-TEST-MARKER" in md


def _native_stub_move(root: Path) -> Move:
    """A ready-built move that lands a NATIVE-ONLY idiom body directly (the same
    ``plan.native_shapes`` tagging a real native-mind fill sets), bypassing
    candidate generation so the fixture stays deterministic and small."""
    rel = "pkg/native_stub.py"

    def _plan() -> RenamePlan:
        src = (root / rel).read_text(encoding="utf-8")
        plan = RenamePlan(old=rel, new="native fill addf")
        plan.originals[rel] = src
        plan.new_contents[rel] = "def addf(a, b):\n    return a + b\n"
        plan.edits_by_file[rel] = 1
        plan.native_shapes = ["2:p0 + p1"]
        return plan

    return Move(operator="implement_stub", target=f"{rel}:addf",
                description="fill addf natively", build_plan=_plan)


def test_backstop_restore_discloses_unrecorded_native_experience(tmp_path: Path):
    # PRE-FIX: no such disclosure exists — the native-experience pollution was
    # silent. A native-only fill LANDS and VERIFIES (its own scoped test passes)
    # in the SAME campaign a transitive regression later sweeps away. Native
    # experience recording is EAGER (fires the instant the move verifies, well
    # before the end-of-campaign backstop reruns the suite) and
    # ``native_proof_memory`` is APPEND-ONLY — there is no way to un-record it —
    # so the backstop restore must disclose the pollution it cannot retract.
    from app.engine.native_proof_memory import decayed_reliability

    _transitive_regression_project(tmp_path)
    (tmp_path / "pkg" / "native_stub.py").write_text(
        "def addf(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_native_stub.py").write_text(
        "from pkg.native_stub import addf\n"
        "def test_addf():\n    assert addf(2, 3) == 5\n", encoding="utf-8")

    result = run_moves(
        str(tmp_path),
        [_native_stub_move(tmp_path), _modernize_check_move(tmp_path)],
        label="native-then-regress", apply=True, verify=True, scope_verify=True)

    # The campaign was fully rolled back...
    assert result.regression_backstop == BACKSTOP_REGRESSED
    assert result.steps == []
    assert (tmp_path / "pkg" / "native_stub.py").read_text(encoding="utf-8") == (
        "def addf(a, b):\n    raise NotImplementedError\n")
    # ...but the native-only fill DID land and verify before the sweep, so its
    # experience is unretractably recorded — the disclosure names it explicitly.
    assert "2:p0 + p1" in decayed_reliability(tmp_path)
    assert any(
        "native-experience" in b and "2:p0 + p1" in b for b in result.blocked)


def test_native_experience_stays_eager_not_deferred_in_a_clean_campaign(
        tmp_path: Path, monkeypatch):
    # NON-REGRESSION PIN (must already pass and stay passing): eager per-move
    # native-experience recording (fires inside ``_apply_one_move`` the instant
    # EACH move verifies) must NOT have silently become deferred/batched plumbing
    # — a later stub target's candidate ranking legitimately depends on an
    # EARLIER target's landing THIS SAME campaign (see
    # ``stub_synthesis._native_mind_candidates``), and deferring would change
    # that ordering on the non-backstop happy path.
    from app.engine import native_proof_memory as npm
    from app.execution.stub_synthesis import _native_mind_sources

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "lib.py").write_text(
        "def clamp(v, lo, hi):\n    return max(lo, min(v, hi))\n",
        encoding="utf-8")
    (tmp_path / "app" / "first.py").write_text(
        "def bound_a(a, b, c):\n    raise NotImplementedError\n",
        encoding="utf-8")
    (tmp_path / "app" / "second.py").write_text(
        "def bound_b(a, b, c):\n    raise NotImplementedError\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_first.py").write_text(
        "from app.first import bound_a\n"
        "def test_bound_a():\n"
        "    assert bound_a(5, 0, 10) == 5\n"
        "    assert bound_a(-3, 0, 10) == 0\n"
        "    assert bound_a(99, 0, 10) == 10\n", encoding="utf-8")
    (tmp_path / "tests" / "test_second.py").write_text(
        "from app.second import bound_b\n"
        "def test_bound_b():\n"
        "    assert bound_b(5, 0, 10) == 5\n"
        "    assert bound_b(-3, 0, 10) == 0\n"
        "    assert bound_b(99, 0, 10) == 10\n", encoding="utf-8")
    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _native_mind_sources.cache_clear()

    calls: list[int] = []
    real_record = npm.record_native_landing

    def _spy(root, shapes):
        calls.append(len(calls))
        real_record(root, shapes)

    monkeypatch.setattr(npm, "record_native_landing", _spy)
    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)

    assert len(result.steps) == 2
    assert result.regression_backstop == BACKSTOP_CLEAN
    # EAGER: one record_native_landing call per move as it verifies — not one
    # batched call after the whole campaign (which would be a single [0]).
    assert calls == [0, 1]
    assert all(s.native_shapes for s in result.steps)
