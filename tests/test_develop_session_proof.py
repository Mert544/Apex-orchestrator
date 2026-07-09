"""`apex develop session --apply` -> the SHARED proof-of-fix trail.

A landed-and-held develop-session move is a verified-with-rollback fix, so its
realized buyer value belongs on the SAME ``.apex/proof-of-fix.json`` artifact
that value-landed / the owner-report / the tamper-seal already consume — making
the session's realized value legible cross-run. This module pins that wiring
(the develop-side analog of the dream chain's ``build_dream_proof``):

  * the happy path: a ``session --apply`` on a foreign fixture leaves a
    ``.apex/proof-of-fix.json`` that ``value_landed`` reads with verified value
    >= 1.00 and an ``implement_stub`` / verified top contribution;
  * the record contract: every ``fixes[i]`` matches ``_fix_record``'s output
    (applied, not rolled back, non-empty finding operator/target, a known
    coverage level, the ``apex-proof-of-fix`` schema);
  * OFF-BY-DEFAULT byte-identity: a dry run (``apply`` off) writes NO proof —
    the tree is byte-identical and no ``.apex`` dir is created;
  * NEVER-FAKE-GREEN: a session that REGRESSED and fully rolled back writes NO
    proof (the moves were emptied, so ``total_moves == 0``);
  * PARITY: ``value_landed(build_session_proof(report))`` agrees with the
    in-memory ``value_landed_from_session(report)`` — the persisted bucket can
    never diverge from the session's own scorecard;
  * DETERMINISM + the empty-report shell: ``proof_hash`` is stable; an empty
    report builds a clean, schema-valid proof.

The pure helpers (``_session_proof_records`` / ``build_session_proof``) are
read-only over the report; ``run_develop_session`` itself is untouched.
Deterministic, stdlib-only, no LLM — the only clock is ``build_proof``'s
``generated_at``, OUTSIDE the tamper seal.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.engine.develop_session import (
    SessionReport,
    build_session_proof,
    render_session_markdown,
    run_develop_session,
)
from app.engine.proof_of_fix import (
    SCHEMA,
    proof_hash,
    proof_manifest,
)
from app.engine.value_landed import value_landed, value_landed_from_session


# --- fixtures ----------------------------------------------------------------

def _foreign_project(root: Path) -> Path:
    """A partially-built foreign package with: a tested NotImplementedError stub
    (implement-stub, buyer value 1.00), an empty/under-exported ``__init__.py``,
    a boilerplate ``__init__`` class, a modernizable ``== None`` idiom, and a
    passing-once-implemented suite. Mirrors the _eyml fixture so a ``--apply``
    session has real verified moves to record."""
    (root / "widgets").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='widgets'\nversion='0'\n", encoding="utf-8")
    (root / "widgets" / "__init__.py").write_text("", encoding="utf-8")
    (root / "widgets" / "mathlib.py").write_text(
        'def add(a, b):\n    """Return the sum of a and b."""\n'
        "    raise NotImplementedError\n", encoding="utf-8")
    (root / "widgets" / "models.py").write_text(
        "class Point:\n    def __init__(self, x, y):\n"
        "        self.x = x\n        self.y = y\n", encoding="utf-8")
    (root / "widgets" / "util.py").write_text(
        "def is_missing(value):\n    return value == None\n", encoding="utf-8")
    (root / "tests" / "test_widgets.py").write_text(
        "from widgets.mathlib import add\n"
        "from widgets.models import Point\n"
        "from widgets.util import is_missing\n"
        "def test_add():\n    assert add(2, 3) == 5\n"
        "def test_point():\n    p = Point(1, 2)\n    assert (p.x, p.y) == (1, 2)\n"
        "def test_missing():\n"
        "    assert is_missing(None) is True\n"
        "    assert is_missing(7) is False\n", encoding="utf-8")
    return root


def _transitive_regression_project(root: Path) -> Path:
    """A RED-baseline fixture whose session REGRESSES and fully rolls back.

    ``pkg/check.py`` (``value == None``) is modernizable; its own in-scope test
    passes both before and after, so the impact-scoped gate lets the move LAND.
    But ``pkg/wrapper.py`` — whose test reaches it only through an exec-string
    DYNAMIC import, the one linkage the AST scope scan legitimately cannot see
    even with import-graph reachability (``app.engine.import_reach``) — feeds a
    ``Missing`` sentinel that is GREEN at baseline (``MISSING == None``) and RED
    after (``MISSING is None`` is False) — the transitive regression. A
    pre-existing failing test forces the impact-scoped path. The end-of-session
    backstop catches the regression and rolls the WHOLE session back, emptying
    ``obj.moves`` (``total_moves == 0``). ``pkg/__init__.py`` carries a curated
    empty ``__all__`` so wire-exports leaves it alone — a wired re-export would
    let the reachability closure pull ``test_wrapper`` into the per-move scope
    and catch the break before the backstop ever gets to prove itself."""
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


def _session_namespace(root: Path, *, apply: bool) -> argparse.Namespace:
    """The ``apex develop session`` CLI namespace (matches ``cmd_develop``'s
    dispatch + the flags ``_develop_session`` reads)."""
    return argparse.Namespace(
        target=str(root), session=True, mode_word="session", apply=apply,
        json=False, no_verify=False, fast=False, max_steps=25,
        objective="dead-params", goal="", auto=False, all_objectives=False,
        playbook=False, history=False, top=False, grade=False, multifile=False,
        from_dream=False, deep=False)


def _run_session_cli(root: Path, *, apply: bool) -> int:
    """Run ``apex develop session`` (optionally ``--apply``) through the CLI."""
    from app import cli_autonomy

    return cli_autonomy.cmd_develop(_session_namespace(root, apply=apply))


_KNOWN_LEVELS = {"function", "module", "test-change", "none", "no-suite"}


# --- 1. value_landed reads the session proof: verified value lands -----------

def test_session_apply_writes_proof_value_landed_reads(tmp_path):
    _foreign_project(tmp_path)
    rc = _run_session_cli(tmp_path, apply=True)
    assert rc == 0
    proof_path = tmp_path / ".apex" / "proof-of-fix.json"
    assert proof_path.exists()  # --apply wrote the shared trail
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["schema"] == SCHEMA
    assert proof["mode"] == "develop-session"

    # value_landed consumes the session proof UNCHANGED — the realized buyer value.
    metric = value_landed(proof)
    assert metric["value_landed_verified"] >= 1.0  # the stub fill (value 1.00)
    assert metric["moves_verified"] >= 1
    top = metric["top_contributions"]
    assert top  # at least one contribution surfaced
    # The headline contribution is the verified stub fill.
    assert any(c["operator"] == "implement_stub" and c["bucket"] == "verified"
               for c in top)


# --- 2. record contract: every fix matches _fix_record's output --------------

def test_session_proof_records_match_fix_record_contract(tmp_path):
    _foreign_project(tmp_path)
    _run_session_cli(tmp_path, apply=True)
    proof = json.loads(
        (tmp_path / ".apex" / "proof-of-fix.json").read_text(encoding="utf-8"))
    assert proof["fixes"]  # the session landed at least one move
    for rec in proof["fixes"]:
        assert rec["outcome"] == "applied"
        assert rec["rollback"]["occurred"] is False
        finding = rec["finding"]
        assert finding["operator"]            # non-empty operator
        assert finding["target"]              # non-empty target
        # finding mirrors _fix_record: label/branch/action/operator/target keys.
        for key in ("label", "branch", "action", "operator", "target"):
            assert key in finding
        level = rec["verification"]["strength"]["level"]
        assert level in _KNOWN_LEVELS  # the value-landed coverage vocabulary
        # The honestly-omitted fields are present-but-empty (never faked).
        assert rec["changed_files"] == []
        assert rec["diff"] == ""
        assert rec["transform_type"] == ""
        assert rec["risk_tier"] is None
    # The proof's totals agree with its records (applied == len(fixes)).
    assert proof["totals"]["applied"] == len(proof["fixes"])
    assert proof["totals"]["rolled_back"] == 0


# --- 3. off-by-default: a dry run writes NO proof (byte-identical tree) -------

def test_session_dry_run_writes_no_proof(tmp_path):
    _foreign_project(tmp_path)
    # Source bytes the dry run must not touch (a transient cache the dry
    # measurement may create is not part of the project — scoped to *.py).
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.py")}
    rc = _run_session_cli(tmp_path, apply=False)
    assert rc == 0
    # No proof-of-fix.json — and no .apex directory was created at all.
    assert not (tmp_path / ".apex" / "proof-of-fix.json").exists()
    assert not (tmp_path / ".apex").exists()
    after = {p: p.read_bytes() for p in tmp_path.rglob("*.py")}
    assert after == before  # the source tree is byte-identical after a dry run


# --- 4. never-fake-green: a fully-rolled-back session RECORDS the rollback ----
#
# CONTRACT CHANGE (W3A-L4, "Rüya/bağışıklık — backstop rollbacks feed the
# experience memory"): this test USED TO pin that a rolled-back session writes
# NO proof-of-fix.json at all. That literal assertion is DELIBERATELY inverted
# here, on purpose, in this same wave. The gap it exposed: a per-move rollback in
# the maintain path already gets recorded with ``outcome: "rolled_back"`` (feeding
# ``should_avoid``/fragility via ``counterfactual_learning``/``proof_history``),
# but a CAMPAIGN-LEVEL backstop rollback wrote NOTHING — positive or negative —
# so the organism could never learn "this was tried here and it broke something."
# The FIX (``develop_session._restore_and_zero`` -> the shared, fail-closed
# ``objective_compiler._record_backstop_ledger_correction`` writer) makes the
# session's OWN rollback feed that same ledger. The INTENT the old assertion
# protected — never falsely claim a fake landing — is the one invariant that
# still matters and is now the LOAD-BEARING check: every record's ``outcome`` is
# ``rolled_back`` (never ``applied``), ``totals.applied == 0``, and
# ``value_landed`` still reads "no value landed". Never-fake-green is
# STRENGTHENED (the rollback is now honestly disclosed to the ledger), not
# violated (nothing is claimed to have landed).
def test_session_rolled_back_writes_no_proof(tmp_path):
    _transitive_regression_project(tmp_path)
    check_before = (tmp_path / "pkg" / "check.py").read_text(encoding="utf-8")

    rc = _run_session_cli(tmp_path, apply=True)
    assert rc == 0
    # The session detected a transitive regression and rolled the WHOLE thing
    # back: nothing held, so total_moves is 0 — and the CLI's own proof writer
    # (gated on total_moves) writes nothing new — but the ENGINE's backstop
    # correction DOES leave a ledger entry, honestly recording the swept, reverted
    # move as ``rolled_back`` (never as a fake "applied" landing).
    proof_path = tmp_path / ".apex" / "proof-of-fix.json"
    assert proof_path.exists()
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["schema"] == SCHEMA
    assert proof["mode"] == "develop-session-backstop"
    assert proof["fixes"]
    assert all(f["outcome"] == "rolled_back" for f in proof["fixes"])
    assert proof["totals"]["applied"] == 0
    assert proof["totals"]["rolled_back"] == len(proof["fixes"])
    # NEVER-FAKE-GREEN preserved: a proof now exists, but it still scores zero
    # landed value — the honest inverse of "applied", not a disguised landing.
    assert value_landed(proof)["verdict"] == "no value landed"
    # The modernize change was UN-landed: check.py is byte-for-byte its baseline.
    assert (tmp_path / "pkg" / "check.py").read_text(encoding="utf-8") == check_before


def test_session_rolled_back_report_emits_no_records(tmp_path):
    # The pure level: a regressed-and-rolled-back report carries zero held moves,
    # so build_session_proof emits an empty fixes list (the guard's precondition).
    report = run_develop_session(
        str(_transitive_regression_project(tmp_path)), apply=True, verify=True)
    assert report.regression_rolled_back is True
    assert report.total_moves == 0
    proof = build_session_proof(report, str(tmp_path))
    assert proof["fixes"] == []
    assert proof["totals"]["applied"] == 0
    assert value_landed(proof)["verdict"] == "no value landed"


def test_session_backstop_correction_write_failure_discloses(tmp_path, monkeypatch):
    # PRE-FIX: the disclosure function doesn't exist yet, so this pins the
    # fail-closed contract going forward (W3A-L4's ``_record_backstop_ledger_
    # correction``, mirroring the standalone-campaign version in
    # test_campaign_regression_backstop_eyml.py). A ledger-write failure must
    # never block the session-level restore itself — the rollback still happens,
    # and the failure is disclosed loudly via the EXISTING ``obj.blocked`` channel
    # (no new ``SessionReport``/``SessionObjective`` field).
    from app.engine import develop_session as ds

    _transitive_regression_project(tmp_path)
    monkeypatch.setattr(ds, "_record_backstop_ledger_correction",
                        lambda *a, **kw: False)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)

    assert report.regression_rolled_back is True
    assert report.total_moves == 0  # the restore itself is unaffected
    assert not (tmp_path / ".apex" / "proof-of-fix.json").exists()
    assert any(
        "could not correct the proof ledger" in b
        for obj in report.objectives for b in obj.blocked)


def test_render_session_markdown_surfaces_backstop_correction_failure(
        tmp_path, monkeypatch):
    # RED-FIRST (CRITICAL disclosure, W3A-L4 finding 2) — the reviewer's exact
    # repro: monkeypatch the ledger-correction writer to fail, run the SAME
    # transitive-regression session fixture that genuinely rolls back, and
    # confirm the failure — which lands on ``obj.blocked`` — actually reaches
    # the rendered buyer artifact. Pre-fix, ``render_session_markdown`` never
    # read ``.blocked`` at all, so this failure was silently invisible even
    # though the session correctly rolled the tree back.
    from app.engine import develop_session as ds

    _transitive_regression_project(tmp_path)
    monkeypatch.setattr(ds, "_record_backstop_ledger_correction",
                        lambda *a, **kw: False)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)

    assert report.regression_rolled_back is True
    md = render_session_markdown(report)
    assert "correct the proof ledger" in md


def test_restore_and_zero_discloses_unrecorded_native_experience(tmp_path):
    # RED-FIRST (HIGH, W3A-L4 finding 3): the native-experience pollution
    # disclosure existed only at the CAMPAIGN level
    # (``objective_compiler._backstop_restore``) with no session-path
    # counterpart — a native-only fill landed and verified through
    # ``run_develop_session`` (recording into the append-only
    # ``native_proof_memory``) before a LATER objective's regression rolled the
    # whole session back, and the swept native experience went undisclosed.
    # This drives ``_restore_and_zero`` directly (deterministic, no need to
    # reverse-engineer the native-mind discovery heuristics) with a synthetic
    # held move that already carries ``native_shapes`` — exactly what
    # ``_collect_objective`` threads from a real ``CompileStep``.
    from app.engine.develop_session import (
        SessionMove,
        SessionObjective,
        SessionReport,
        TIER_VERIFIED,
        _restore_and_zero,
        _snapshot,
    )

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    before = _snapshot(tmp_path)
    (tmp_path / "pkg" / "a.py").write_text("x = 2\n", encoding="utf-8")
    after = _snapshot(tmp_path)

    report = SessionReport(applied=True)
    obj = SessionObjective(objective="implement-stub", moves=[
        SessionMove("implement-stub", "implement_stub", "pkg/a.py:f",
                   "fill f natively", TIER_VERIFIED,
                   native_shapes=("2:p0 + p1",)),
    ])
    report.objectives = [obj]

    _restore_and_zero(report, tmp_path, before, after)

    assert report.regression_rolled_back is True
    assert obj.moves == []  # the tree is back at baseline: no phantom holds
    assert (tmp_path / "pkg" / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert any(
        "native-experience" in b and "2:p0 + p1" in b for b in obj.blocked)


def test_session_restore_withholds_correction_when_tree_restore_incomplete(
        tmp_path, monkeypatch):
    # RED-FIRST (LOW but never-fake-green, W3A-L4 finding 5): a byte-restore
    # failure reported by ``restore_py_tree`` must WITHHOLD the session-level
    # ledger correction entirely (never write a "rolled_back" record for a tree
    # that is not provably back at baseline) and disclose the incompleteness
    # instead. Mirrors the campaign-level pin in
    # test_campaign_regression_backstop_eyml.py.
    from app.engine import develop_session as ds

    _transitive_regression_project(tmp_path)
    real_restore = ds.restore_py_tree

    def _flaky_restore(root, before, after):
        failed = real_restore(root, before, after)
        return sorted({*failed, "pkg/check.py"})

    monkeypatch.setattr(ds, "restore_py_tree", _flaky_restore)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)

    assert report.regression_rolled_back is True
    assert not (tmp_path / ".apex" / "proof-of-fix.json").exists()
    assert any(
        "restore incomplete" in b and "ledger correction withheld" in b
        for obj in report.objectives for b in obj.blocked)


# --- 5. parity: persisted value_landed == in-memory value_landed_from_session -

def test_session_proof_value_landed_matches_in_memory(tmp_path):
    _foreign_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)
    assert report.total_moves >= 1  # the fixture lands real work
    persisted = value_landed(build_session_proof(report, str(tmp_path)))
    in_memory = value_landed_from_session(report)
    # The persisted proof's value buckets agree with the session's own scorecard —
    # _SESSION_TIER_LEVEL is the honest inverse of value_landed's _SESSION_TIER_BUCKET.
    for key in ("value_landed_verified", "value_landed_weak",
                "value_landed_unverified", "moves_verified", "moves_weak",
                "moves_unverified"):
        assert persisted[key] == in_memory[key], key


# --- 6. build_session_proof over an empty report: a clean, schema-valid shell -

def test_build_session_proof_empty_report_is_clean():
    report = SessionReport(applied=True)
    proof = build_session_proof(report, "/nowhere")
    assert proof["schema"] == SCHEMA
    assert proof["mode"] == "develop-session"
    assert proof["fixes"] == []
    assert proof["totals"]["applied"] == 0
    # The downstream consumers handle the empty proof without crashing.
    assert value_landed(proof)["verdict"] == "no value landed"
    assert proof_manifest(proof)["verdict"] == "no fixes recorded"
    assert proof_hash(proof)  # a stable hash over the empty record set


# --- 7. determinism: proof_hash equal across two builds of the same report ----

def test_session_proof_hash_deterministic_same_tree(tmp_path):
    # build_session_proof over the SAME landed report yields a byte-identical
    # proof_hash — the seal excludes generated_at, so two builds tie.
    _foreign_project(tmp_path)
    report = run_develop_session(str(tmp_path), apply=True, verify=True)
    a = build_session_proof(report, str(tmp_path))
    b = build_session_proof(report, str(tmp_path))
    assert proof_hash(a) == proof_hash(b)
    # value_landed over the same proof is also byte-identical.
    assert value_landed(a) == value_landed(b)


# --- 8. CONSUMER-CORRECT KEY (W4B): finding.action is the OPERATOR, not the ---
#        session objective — the pre-existing half of the W3A-L4 finding.
#
# Wave 3 fixed ``objective_compiler._record_backstop_ledger_correction``'s
# action key (``finding.action = operator``, ``finding.label = objective``) but
# explicitly named THIS writer's mismatch as an out-of-fence follow-up (see
# that function's docstring). Before this fix, ``_session_proof_records``
# stamped ``finding.action`` with the session OBJECTIVE name (e.g.
# ``"dead-params"``), but the runtime avoid-guard
# (``objective_compiler._avoid_flagged_targets``) queries
# ``should_avoid(signatures, mv.operator, ...)`` by OPERATOR (e.g.
# ``"drop_param"``) — so a landed session move could never season the
# avoid-guard for its own operator.

def test_session_proof_records_action_is_operator_not_objective():
    # RED-FIRST, direct record-contract check: mirrors the maintain-path
    # convention (``idea_action_bridge``'s ``action_type`` is operator-derived)
    # and the wave-3 writer's ``finding.action``/``finding.label`` split.
    from app.engine.develop_session import (
        TIER_VERIFIED,
        SessionMove,
        SessionObjective,
        _session_proof_records,
    )

    objective, operator = "dead-params", "drop_param"
    report = SessionReport(applied=True)
    obj = SessionObjective(objective=objective, moves=[
        SessionMove(objective, operator, "app/m.py:f", "drop unused param",
                   TIER_VERIFIED),
    ])
    report.objectives = [obj]

    records = _session_proof_records(report)
    assert len(records) == 1
    finding = records[0]["finding"]
    assert finding["action"] == operator     # CONSUMER-CORRECT key
    assert finding["label"] == objective     # human attribution preserved
    assert finding["operator"] == operator
    assert finding["target"] == "app/m.py:f"


def test_session_applied_record_feeds_should_avoid_by_operator(tmp_path):
    # RED-FIRST: the reviewer's exact repro (mirrors
    # test_standalone_backstop_correction_feeds_should_avoid in
    # test_campaign_regression_backstop_eyml.py, and the dream-chain twin
    # test_dream_land_applied_record_feeds_should_avoid_by_operator), adapted
    # for a genuine "applied" session landing record.
    #
    # Seed TWO prior rolled_back attempts under the operator key — below
    # ``_MIN_ATTEMPTS`` (3), so ``should_avoid`` is honestly False on that
    # evidence alone. Then land ONE session move on the SAME (operator, trait)
    # signature via the real writer: if ``finding.action`` is correctly keyed
    # by OPERATOR, this is the THIRD attempt against the shared signature (2
    # failures / 3 attempts = 66.7% >= the 60% avoid threshold) and
    # ``should_avoid`` flips True — proving the record reaches the exact
    # signature space ``_avoid_flagged_targets`` queries. Pre-fix
    # (``finding.action = objective``) the landing would silently form its own
    # orphan bucket under "dead-params" that no operator-keyed query ever
    # reaches, leaving the operator stuck at 2 attempts (still False).
    from app.engine.counterfactual_learning import (
        failure_signatures,
        module_traits,
        should_avoid,
    )
    from app.engine.develop_session import (
        TIER_VERIFIED,
        SessionMove,
        SessionObjective,
    )
    from app.engine.proof_history import load_proof_history
    from app.engine.proof_of_fix import write_proof

    objective, operator = "dead-params", "drop_param"
    (tmp_path / ".apex").mkdir(parents=True)
    (tmp_path / ".apex" / "proof-of-fix.json").write_text(json.dumps({
        "schema": SCHEMA, "generated_at": "2026-01-01",
        "fixes": [
            {"outcome": "rolled_back",
             "finding": {"action": operator, "label": "prior",
                        "target": "app/m1.py:f"},
             "changed_files": ["app/m1.py:f"]},
            {"outcome": "rolled_back",
             "finding": {"action": operator, "label": "prior",
                        "target": "app/m2.py:f"},
             "changed_files": ["app/m2.py:f"]},
        ],
    }), encoding="utf-8")
    traits = module_traits("app/m1.py:f")
    assert traits == module_traits("app/m2.py:f") == module_traits("app/m3.py:f")
    pre = failure_signatures(load_proof_history(tmp_path))
    assert should_avoid(pre, operator, traits) is False  # only 2 attempts yet

    report = SessionReport(applied=True)
    obj = SessionObjective(objective=objective, moves=[
        SessionMove(objective, operator, "app/m3.py:f", "drop unused param",
                   TIER_VERIFIED),
    ])
    report.objectives = [obj]
    write_proof(build_session_proof(report, str(tmp_path)), str(tmp_path))

    signatures = failure_signatures(load_proof_history(tmp_path))
    # THE reviewer's exact repro: the runtime avoid-guard queries by OPERATOR.
    assert should_avoid(signatures, operator, traits) is True
    # ...and NEVER by the objective name — the exact mismatch this fix corrects.
    assert should_avoid(signatures, objective, traits) is False
