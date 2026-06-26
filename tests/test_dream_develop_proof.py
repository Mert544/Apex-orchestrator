"""`apex dream --land --apply` -> the SHARED proof-of-fix trail.

A landed overnight-chain move is a verified-with-rollback fix, so its realized
buyer value belongs on the SAME ``.apex/proof-of-fix.json`` artifact that
value-landed / the owner-report / the tamper-seal already consume — making the
dream differentiator's value legible cross-run. This module pins that wiring:

  * the happy path: ``--land --apply`` on a test-pinned stub fixture leaves a
    ``.apex/proof-of-fix.json`` that ``value_landed`` reads with verified value
    >= 1.00 and an ``implement_stub`` / verified top contribution;
  * the record contract: every ``fixes[i]`` matches ``_fix_record``'s output
    (applied, not rolled back, non-empty finding operator/target, a known
    coverage level, the ``apex-proof-of-fix`` schema);
  * OFF-BY-DEFAULT byte-identity: a dry run (``apply`` off) writes NO proof —
    the tree is byte-identical;
  * DETERMINISM: ``proof_hash`` is byte-identical across two runs / two
    ``PYTHONHASHSEED`` s (the seal excludes ``generated_at``);
  * NEVER-FAKE-GREEN: a rolled-back / contradictory move produces NO applied
    record for the unfilled target;
  * the history layer: a prior maintain proof is archived, not clobbered.

The pure helpers (``_dream_proof_records`` / ``build_dream_proof``) are read-only
over the report; ``dream_develop`` itself is untouched. Deterministic,
stdlib-only, no LLM — the only clock is ``build_proof``'s ``generated_at``,
OUTSIDE the tamper seal. The ``_eyml`` house suffix is reserved for the existing
file; this companion uses the plain ``_proof`` name the spec names.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from app.engine.dream_develop import (
    build_dream_proof,
    dream_develop,
)
from app.engine.proof_of_fix import (
    SCHEMA,
    proof_hash,
    proof_manifest,
)
from app.engine.value_landed import value_landed


# --- fixtures ----------------------------------------------------------------

def _stub_project(tmp_path: Path) -> Path:
    """A whole-tree project with a test-pinned fillable stub (implement-stub,
    buyer value 1.00) the ship-value chain lands — so an applied chain has a
    real, verified move to record. Mirrors the existing _eyml fixture."""
    tmp_path.mkdir(parents=True, exist_ok=True)
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


def _dream_land_apply(tmp_path: Path):
    """Run ``apex dream --land --apply`` through the CLI on ``tmp_path``."""
    from app import cli_insight

    rc = cli_insight.cmd_dream(argparse.Namespace(
        target=str(tmp_path), curate=False, land=True, apply=True, fast=False,
        json=False))
    return rc


_KNOWN_LEVELS = {"function", "module", "test-change", "none"}


# --- 1. value_landed reads the dream proof: verified value lands -------------

def test_dream_land_apply_writes_proof_value_landed_reads(tmp_path):
    _stub_project(tmp_path)
    rc = _dream_land_apply(tmp_path)
    assert rc == 0
    proof_path = tmp_path / ".apex" / "proof-of-fix.json"
    assert proof_path.exists()  # --land --apply wrote the shared trail
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["schema"] == SCHEMA
    assert proof["mode"] == "dream-land"

    # value_landed consumes the dream proof UNCHANGED — the realized buyer value.
    metric = value_landed(proof)
    assert metric["value_landed_verified"] >= 1.0  # the stub fill (value 1.00)
    assert metric["moves_verified"] >= 1
    top = metric["top_contributions"]
    assert top  # at least one contribution surfaced
    # The headline contribution is the verified stub fill.
    assert any(c["operator"] == "implement_stub" and c["bucket"] == "verified"
               for c in top)


# --- 2. record contract: every fix matches _fix_record's output --------------

def test_dream_proof_records_match_fix_record_contract(tmp_path):
    _stub_project(tmp_path)
    _dream_land_apply(tmp_path)
    proof = json.loads(
        (tmp_path / ".apex" / "proof-of-fix.json").read_text(encoding="utf-8"))
    assert proof["fixes"]  # the chain landed at least one move
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

def test_dream_dry_run_writes_no_proof(tmp_path):
    _stub_project(tmp_path)
    # Source bytes the dry run must not touch (a transient .pytest_cache the dry
    # measurement may create is not part of the project — the existing _eyml dry
    # run check is likewise scoped to *.py).
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.py")}
    from app import cli_insight

    rc = cli_insight.cmd_dream(argparse.Namespace(
        target=str(tmp_path), curate=False, land=True, apply=False, fast=False,
        json=False))
    assert rc == 0
    # No proof-of-fix.json — and no .apex directory was created at all.
    assert not (tmp_path / ".apex" / "proof-of-fix.json").exists()
    assert not (tmp_path / ".apex").exists()
    after = {p: p.read_bytes() for p in tmp_path.rglob("*.py")}
    assert after == before  # the source tree is byte-identical after a dry run


# --- 4. determinism: proof_hash equal across runs / hashseeds ----------------

def test_dream_proof_hash_deterministic_same_tree(tmp_path):
    # build_dream_proof over the SAME landed report yields a byte-identical
    # proof_hash — the seal excludes generated_at, so two builds tie.
    _stub_project(tmp_path)
    report = dream_develop(str(tmp_path), apply=True, verify=True)
    a = build_dream_proof(report, str(tmp_path))
    b = build_dream_proof(report, str(tmp_path))
    assert proof_hash(a) == proof_hash(b)
    # value_landed over the same proof is also byte-identical.
    assert value_landed(a) == value_landed(b)


def test_dream_proof_hash_deterministic_under_pythonhashseed(tmp_path):
    _stub_project(tmp_path)
    repo = str(Path(__file__).resolve().parents[1])
    src = (
        "import sys;"
        "from app.engine.dream_develop import dream_develop, build_dream_proof;"
        "from app.engine.proof_of_fix import proof_hash;"
        "r=dream_develop(sys.argv[1], apply=True, verify=True);"
        "print(proof_hash(build_dream_proof(r, sys.argv[1])))")

    def _run(seed: str, root: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", src, str(root)], capture_output=True, text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin",
                 "PYTHONPATH": repo}, cwd=repo)

    # Two fresh trees (apply mutates the tree), one per seed, identical content.
    t0 = _stub_project(tmp_path / "a")
    t1 = _stub_project(tmp_path / "b")
    out0 = _run("0", t0)
    out1 = _run("12345", t1)
    assert out0.returncode == 0 and out1.returncode == 0, (out0.stderr, out1.stderr)
    assert out0.stdout.strip()  # a real proof_hash was produced
    assert out0.stdout == out1.stdout  # hashseed-invariant


# --- 5. never-fake-green: a contradictory move yields NO applied record ------

def test_contradictory_stub_produces_no_applied_record(tmp_path):
    # A stub whose test PINS an unsatisfiable contract: any synthesised body is
    # rolled back, so the move never reaches report.results and NO applied record
    # for that target is ever written.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    stub = "def add(a, b):\n    raise NotImplementedError\n"
    (tmp_path / "app" / "s.py").write_text(stub, encoding="utf-8")
    (tmp_path / "tests" / "test_s.py").write_text(
        "from app.s import add\ndef test_add():\n"
        "    assert add(1, 2) == 3\n    assert add(1, 2) == 4\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")

    rc = _dream_land_apply(tmp_path)
    assert rc == 0
    # The unfilled stub stays byte-identical (rolled back, never faked).
    assert (tmp_path / "app" / "s.py").read_text(encoding="utf-8") == stub

    proof_path = tmp_path / ".apex" / "proof-of-fix.json"
    if proof_path.exists():
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        # No applied record fills app/s.py — the never-fake-green guarantee.
        bad = [rec for rec in proof["fixes"]
               if rec["finding"]["operator"] == "implement_stub"
               and "app/s.py" in rec["finding"]["target"]]
        assert not bad
        # And value_landed credits NOTHING for the contradictory stub.
        metric = value_landed(proof)
        assert all(c["operator"] != "implement_stub"
                   for c in metric["top_contributions"])


# --- 6. history layer: a prior maintain proof is archived, not clobbered ------

def test_prior_maintain_proof_archived(tmp_path):
    _stub_project(tmp_path)
    # Seed a PRIOR maintain proof at the latest pointer (a distinct record so it
    # gets its own content-addressed archive name).
    apex = tmp_path / ".apex"
    apex.mkdir(exist_ok=True)
    from app.engine.proof_of_fix import build_proof, write_proof

    prior = build_proof({
        "mode": "supervised", "verify": True, "total_executable": 1,
        "applied": 1, "rolled_back": 0, "blocked": 0, "committed": 0,
        "results": [{
            "label": "smell", "branch": "1", "action": "modernize",
            "operator": "modernize", "target": "app/legacy.py", "applied": True,
            "verified": True, "rolled_back": False,
            "verification_strength": {"level": "module"},
            "test_evidence": {"performed": True, "ok": True},
            "changed_files": ["app/legacy.py"],
            "diff": "--- a/app/legacy.py\n+++ b/app/legacy.py\n",
        }],
    }, str(tmp_path))
    write_proof(prior, str(tmp_path))
    prior_hash = proof_hash(prior)

    # Now land the dream chain — it supersedes the pointer and archives the prior.
    rc = _dream_land_apply(tmp_path)
    assert rc == 0
    # The latest pointer is now the dream proof.
    latest = json.loads(
        (apex / "proof-of-fix.json").read_text(encoding="utf-8"))
    assert latest["mode"] == "dream-land"
    # The prior maintain proof survives as a content-addressed archive.
    archives = list(apex.glob("proof-*.json"))
    archived = [json.loads(p.read_text(encoding="utf-8")) for p in archives]
    assert any(proof_hash(a) == prior_hash for a in archived)


# --- 7. empty chain writes NO proof (honest under-claim) ---------------------

def test_empty_chain_writes_no_proof(tmp_path):
    # A bare package with nothing landable: the chain composes no move, so even
    # with --apply NO proof is written (the guard mirrors _maintain_write_proof).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")

    rc = _dream_land_apply(tmp_path)
    assert rc == 0
    assert not (tmp_path / ".apex" / "proof-of-fix.json").exists()


# --- 8. build_dream_proof over an empty report: a clean, schema-valid shell ---

def test_build_dream_proof_empty_report_is_clean():
    from app.engine.dream_develop import DreamChainReport

    report = DreamChainReport(goal="ship-value", objectives=["implement-stub"])
    proof = build_dream_proof(report, "/nowhere")
    assert proof["schema"] == SCHEMA
    assert proof["mode"] == "dream-land"
    assert proof["fixes"] == []
    assert proof["totals"]["applied"] == 0
    # The downstream consumers handle the empty proof without crashing.
    assert value_landed(proof)["verdict"] == "no value landed"
    assert proof_manifest(proof)["verdict"] == "no fixes recorded"
    assert proof_hash(proof)  # a stable hash over the empty record set
