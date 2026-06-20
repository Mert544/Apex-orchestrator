"""Proof-artifact honesty: a withheld behaviour change must be DISCLOSED.

The proof JSON is the moat's machine-readable evidence. Before this fix, an
applied-but-WITHHELD-for-review fix was recorded with ``outcome:"applied"`` and
its full unified diff but carried NO commit-disposition — no ``committed`` /
``commit_withheld`` / ``fenced`` / ``baseline_red`` / reason. A buyer auditing
the artifact therefore could not tell a committed fix from a never-committed
behaviour-change diff dressed up as a plain "fix" (the maintain MARKDOWN report
DID disclose the withhold; only the proof JSON omitted it).

The fix propagates the result row's commit-disposition onto the proof record,
ADDITIVELY and only on WITHHELD records, so a committed/supervised record is
byte-identical to before. These pins exercise all three withhold gates on real
autonomous runs:

  * baseline-red  (f2b0030): the suite was already RED -> verification
    inconclusive -> withheld with ``baseline_red`` + reason.
  * tier-1 unverified (b5f8241): a Tier-1 behaviour change covered only by a
    smoke shield -> withheld with ``commit_withheld`` + reason.
  * withhold-fence (c16625b): a later same-file step over an unreviewed withheld
    change -> withheld with ``fenced`` + reason.

Plus: a COMMITTED fix's proof record is byte-identical to before (no new keys),
the proof_replay verifier still passes on the new records, and two runs produce
identical proof bytes/hash. Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.proof_of_fix import (
    build_proof,
    proof_bundle,
    proof_hash,
    proof_manifest,
)
from app.engine.proof_replay import replay_proof
from app.models.idea import ActionPlan, ActionStep


# --- helpers -----------------------------------------------------------------

def _git_init(root: Path) -> None:
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t.com"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "-A"],
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"],
    ):
        subprocess.run(cmd, cwd=root, capture_output=True)


def _harden_step(target: str, branch: str = "x.1") -> ActionStep:
    return ActionStep(
        branch_path=branch, title=f"harden {target}", operator="harden",
        subject=target, action_type="harden_security", target=target,
        executable=True, source_facts=[f"security-finding: {target}"],
    )


def _docstring_step(target: str, branch: str = "x.2") -> ActionStep:
    return ActionStep(
        branch_path=branch, title=f"document {target}", operator="document",
        subject=target, action_type="add_docstring", target=target,
        executable=True, source_facts=[f"missing-docstring: {target}"],
    )


def _run(root: Path, steps: list[ActionStep], *, mode: str = "autonomous",
         commit: bool = True) -> dict:
    plan = ActionPlan(steps=steps, mode=mode)
    return IdeaActionBridge().apply_plan(
        plan, str(root), mode=mode, verify=True, commit=commit,
        test_first=True, max_apply=5,
    )


# A module with a Tier-1 fixable vuln (bare ``yaml.load``). A function test
# NAMES ``load`` (coverage "function"). On a RED baseline the function test
# RAISES "missing Loader" before the fix, so the suite is already failing.
_CFG_SRC = "import yaml\ndef load(s):\n    return yaml.load(s)\n"
_CFG_TEST = ('from app.cfg import load\n'
             'def test_load():\n    assert load("a: 1") == {"a": 1}\n')


def _build_red(root: Path) -> None:
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "cfg.py").write_text(_CFG_SRC)
    (root / "tests" / "test_cfg.py").write_text(_CFG_TEST)
    _git_init(root)


def _build_green(root: Path) -> None:
    """GREEN baseline (the common, committed case): a Tier-1 ``eval`` ->
    ``ast.literal_eval`` harden whose behaviour the rewrite PRESERVES and whose
    function test passes before AND after — it verifies and commits."""
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "cfg.py").write_text("def load(s):\n    return eval(s)\n")
    (root / "tests" / "test_cfg.py").write_text(
        'from app.cfg import load\n'
        'def test_load():\n    assert load("{\'a\': 1}") == {"a": 1}\n')
    _git_init(root)


# An untested module (no test references it -> coverage none/module) carrying a
# Tier-1 fixable vuln: the harden is a behaviour change the suite never exercises
# -> the tier-1 unverified gate withholds it.
_UNCOVERED_SRC = "import yaml\ndef parse(s):\n    return yaml.load(s)\n"


def _build_uncovered(root: Path) -> None:
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "cfg.py").write_text(_UNCOVERED_SRC)
    (root / "tests" / "test_unrelated.py").write_text(
        "def test_ok():\n    assert True\n")
    _git_init(root)


# A multi-vuln untested module: convergence STOPS at the first behaviour change
# and withholds it, fencing the file for a later same-file step.
_FENCE_SRC = (
    "import pickle\n"
    "import subprocess\n"
    "import yaml\n"
    "\n\n"
    "def load(b):\n"
    "    return pickle.loads(b)\n"
    "\n\n"
    "def run():\n"
    '    return subprocess.run("ls", shell=True)\n'
    "\n\n"
    "def parse(text):\n"
    "    return yaml.load(text)\n"
)


def _build_fence(root: Path) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "vuln.py").write_text(_FENCE_SRC)
    (root / "tests" / "test_unrelated.py").write_text(
        "def test_ok():\n    assert True\n")
    _git_init(root)


def _withheld_fix(proof: dict) -> dict:
    """The first applied fix in the proof whose row was withheld."""
    return next(f for f in proof["fixes"]
                if f["outcome"] == "applied" and f.get("commit_withheld"))


# --- PIN 1: baseline-red withhold is disclosed in the proof JSON -------------

def test_baseline_red_withhold_disclosed_in_proof(tmp_path):
    _build_red(tmp_path)
    summary = _run(tmp_path, [_harden_step("app/cfg.py")])
    proof = build_proof(summary, str(tmp_path))

    fix = _withheld_fix(proof)
    # It IS applied (full diff present) but the proof now states it was NOT
    # committed and WHY — it is no longer indistinguishable from a real fix.
    assert fix["outcome"] == "applied"
    assert fix["diff"]
    assert fix["committed"] is False
    assert fix["commit_withheld"] is True
    assert fix["baseline_red"] is True
    assert "already failing" in fix["withheld_reason"]
    assert "fenced" not in fix          # this gate is baseline-red, not fence
    assert "commit_hash" not in fix     # a withheld fix never reached git


# --- PIN 2: tier-1 unverified withhold is disclosed --------------------------

def test_tier1_unverified_withhold_disclosed_in_proof(tmp_path):
    _build_uncovered(tmp_path)
    summary = _run(tmp_path, [_harden_step("app/cfg.py")])
    proof = build_proof(summary, str(tmp_path))

    fix = _withheld_fix(proof)
    assert fix["outcome"] == "applied"
    assert fix["committed"] is False
    assert fix["commit_withheld"] is True
    # The tier-1 gate is neither baseline-red nor fence — only the bare
    # commit_withheld disposition + reason are surfaced.
    assert "baseline_red" not in fix
    assert "fenced" not in fix
    assert "unverified behaviour change" in fix["withheld_reason"]
    assert "commit_hash" not in fix


# --- PIN 3: withhold-fence is disclosed on the later same-file fix -----------

def test_fenced_withhold_disclosed_in_proof(tmp_path):
    _build_fence(tmp_path)
    summary = _run(tmp_path, [
        _harden_step("pkg/vuln.py"),
        _docstring_step("pkg/vuln.py"),
    ])
    proof = build_proof(summary, str(tmp_path))

    doc = next(f for f in proof["fixes"]
               if f["finding"]["action"] == "add_docstring")
    assert doc["outcome"] == "applied"
    assert doc["committed"] is False
    assert doc["commit_withheld"] is True
    assert doc["fenced"] is True
    assert "unreviewed withheld change" in doc["withheld_reason"]
    assert "commit_hash" not in doc


# --- PIN 4: a COMMITTED fix's proof record is byte-identical to before -------

def test_committed_fix_record_is_byte_identical(tmp_path):
    _build_green(tmp_path)
    summary = _run(tmp_path, [_harden_step("app/cfg.py")])
    proof = build_proof(summary, str(tmp_path))

    fix = next(f for f in proof["fixes"]
               if f["finding"]["action"] == "harden_security")
    assert fix["outcome"] == "applied"
    assert fix.get("commit_hash")               # it really committed

    # NONE of the disclosure fields may appear on a committed record — they are
    # the exact keys characterization tests pin as absent. A committed record's
    # bytes must be unchanged from the pre-fix schema.
    for key in ("committed", "commit_withheld", "fenced", "baseline_red",
                "withheld_reason"):
        assert key not in fix, f"committed record gained {key!r}"

    # The committed record's key set is exactly the pre-fix schema (plus the
    # always-optional commit_hash) — no disclosure leak.
    expected = {"finding", "transform_type", "risk_tier", "outcome",
                "changed_files", "diff", "verification", "rollback",
                "commit_hash"}
    assert set(fix) <= expected


def test_supervised_record_has_no_disclosure_fields(tmp_path):
    # Supervised mode never sets a committer, so there is no commit and no
    # withhold-gate — the record must NOT gain a misleading commit_withheld.
    _build_green(tmp_path)
    summary = _run(tmp_path, [_harden_step("app/cfg.py")],
                   mode="supervised", commit=False)
    proof = build_proof(summary, str(tmp_path))
    fix = next(f for f in proof["fixes"]
               if f["finding"]["action"] == "harden_security")
    for key in ("committed", "commit_withheld", "fenced", "baseline_red",
                "withheld_reason"):
        assert key not in fix


# --- PIN 5: manifest + bundle tally a withheld fix honestly ------------------

def test_manifest_does_not_count_withheld_as_auto_fixed(tmp_path):
    _build_red(tmp_path)
    summary = _run(tmp_path, [_harden_step("app/cfg.py")])
    proof = build_proof(summary, str(tmp_path))
    manifest = proof_manifest(proof)

    # The withheld fix is applied-on-disk, NOT auto-fixed-and-recorded.
    assert manifest["auto_fixed"] == 0
    assert manifest["withheld"] == 1
    assert manifest["flagged"] >= 1
    assert "withheld for review" in manifest["verdict"]
    assert "auto-fixed & recorded" not in manifest["verdict"]


def test_committed_manifest_has_no_withheld_key(tmp_path):
    # A run with no withholds keeps the original manifest keys byte-identical.
    _build_green(tmp_path)
    summary = _run(tmp_path, [_harden_step("app/cfg.py")])
    proof = build_proof(summary, str(tmp_path))
    manifest = proof_manifest(proof)
    assert "withheld" not in manifest
    assert manifest["auto_fixed"] == 1
    assert manifest["verdict"] == "1 auto-fixed & recorded"


# --- PIN 6: proof_replay still passes on the disclosed records ---------------

def test_proof_replay_passes_on_withheld_records(tmp_path):
    _build_red(tmp_path)
    summary = _run(tmp_path, [_harden_step("app/cfg.py")])
    proof = build_proof(summary, str(tmp_path))

    verdict = replay_proof(proof)
    assert verdict["replay_ok"] is True, verdict["discrepancies"]
    assert verdict["records"] >= 1


# --- PIN 7: determinism — two runs produce identical proof bytes/hash --------

def test_two_withhold_runs_produce_identical_proof_bytes(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    for root in (root_a, root_b):
        root.mkdir()
        _build_red(root)
    proof_a = build_proof(_run(root_a, [_harden_step("app/cfg.py")]),
                          str(root_a))
    proof_b = build_proof(_run(root_b, [_harden_step("app/cfg.py")]),
                          str(root_b))

    nondet = {"generated_at", "project_root", "duration_seconds",
              "commit_hash", "tool", "commands"}

    def strip(obj):
        if isinstance(obj, dict):
            return {k: strip(v) for k, v in sorted(obj.items())
                    if k not in nondet}
        if isinstance(obj, list):
            return [strip(v) for v in obj]
        return obj

    assert strip(proof_a) == strip(proof_b)

    # The disclosure fields are part of the recorded facts and are byte-identical
    # across runs (no clock/random in the disposition).
    fa = _withheld_fix(proof_a)
    fb = _withheld_fix(proof_b)
    for key in ("committed", "commit_withheld", "baseline_red", "withheld_reason"):
        assert fa.get(key) == fb.get(key)

    # The tamper hash already excludes the artifact's volatile envelope; the only
    # remaining per-run jitter is the MEASURED suite duration inside each
    # verification (a pre-existing fact in the seal, not a disclosure field). Pin
    # both verifications to the same measured duration and the hashes — including
    # the disclosure fields now folded into the seal — are byte-identical.
    for proof in (proof_a, proof_b):
        for fix in proof["fixes"]:
            fix.get("verification", {})["duration_seconds"] = 0.0
    assert proof_hash(proof_a) == proof_hash(proof_b)
    assert proof_bundle(proof_a)["proof_hash"] == proof_bundle(proof_b)["proof_hash"]


def test_withheld_fields_are_inside_the_tamper_seal(tmp_path):
    # The disclosure is auditable evidence, so it must be SEALED: editing the
    # withheld disposition must move the proof hash (a forger can't quietly flip
    # a withheld fix to look committed without breaking the seal).
    _build_red(tmp_path)
    summary = _run(tmp_path, [_harden_step("app/cfg.py")])
    proof = build_proof(summary, str(tmp_path))
    base = proof_hash(proof)

    tampered = json.loads(json.dumps(proof))
    fix = _withheld_fix(tampered)
    del fix["commit_withheld"]
    del fix["committed"]
    assert proof_hash(tampered) != base
