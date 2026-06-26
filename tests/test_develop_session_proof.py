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
    But ``pkg/wrapper.py`` (tested via the WRAPPER, outside scope) feeds a
    ``Missing`` sentinel that is GREEN at baseline (``MISSING == None``) and RED
    after (``MISSING is None`` is False) — the transitive regression. A
    pre-existing failing test forces the impact-scoped path. The end-of-session
    backstop catches the regression and rolls the WHOLE session back, emptying
    ``obj.moves`` (``total_moves == 0``)."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
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
        "from pkg.wrapper import blank_via_wrapper\n"
        "from pkg.sentinel import MISSING\n"
        "def test_missing_is_blank():\n"
        "    assert blank_via_wrapper(MISSING) is True\n", encoding="utf-8")
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


# --- 4. never-fake-green: a fully-rolled-back session writes NO proof ---------

def test_session_rolled_back_writes_no_proof(tmp_path):
    _transitive_regression_project(tmp_path)
    check_before = (tmp_path / "pkg" / "check.py").read_text(encoding="utf-8")

    rc = _run_session_cli(tmp_path, apply=True)
    assert rc == 0
    # The session detected a transitive regression and rolled the WHOLE thing
    # back: nothing held, so total_moves is 0 and NO proof was written — even
    # though a behaviour-changing move DID momentarily apply (not an empty repo).
    assert not (tmp_path / ".apex" / "proof-of-fix.json").exists()
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
