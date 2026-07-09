"""Gap-closing tests for develop_readiness's best-effort / weighting branches.

The existing suite (test_develop_readiness_eyml.py) covers the happy classify /
partition / render paths. This wave exercises the defensive and opt-in branches
the profile promises but never demonstrates:

  * an undecodable source file is SKIPPED (not raised) during the scan;
  * a detector / file-walker / proof loader that BLOWS UP degrades to a safe empty
    result rather than crashing (best-effort);
  * a path outside the scan root recovers its own posix key (relative_to fallback);
  * the opt-in reliability weighting actually FOLDS the learned track record —
    ``weighted`` flips True and a recorded action's finding is discounted;
  * ``_profile_root`` recovers a repo path from a profile object (and returns "" for
    a profile carrying none of the known attributes).

Deterministic, stdlib-only, no LLM. The ``_eyml`` house suffix.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.engine.proof_of_fix import SCHEMA
from app.engine.develop_readiness import develop_readiness


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _write_proof(root: Path, action: str, applied: int, blocked: int) -> None:
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    fixes = [{"finding": {"action": action}, "outcome": "applied"}
             for _ in range(applied)]
    fixes += [{"finding": {"action": action}, "outcome": "blocked"}
              for _ in range(blocked)]
    (apex / "proof-0001.json").write_text(
        json.dumps({"schema": SCHEMA, "generated_at": "2026-01-01T00:00:00Z",
                    "fixes": fixes}), encoding="utf-8")


# --- best-effort file scan -----------------------------------------------------

def test_undecodable_source_file_is_skipped(tmp_path):
    # A .py file with invalid UTF-8 raises UnicodeDecodeError on read and must be
    # skipped, not crash the scan.
    (tmp_path / "bad.py").write_bytes(b"\xff\xfe eval(x)\n")
    out = develop_readiness(root=str(tmp_path))
    assert out["total"] == 0
    assert out["score"] == 0.0


def test_detector_exception_is_swallowed(tmp_path, monkeypatch):
    # A detector that raises on a file contributes nothing rather than propagating.
    _write(tmp_path, "a.py", "eval(x)\n")

    def _boom(_source):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr("app.engine.detectors.detect", _boom)
    out = develop_readiness(root=str(tmp_path))
    assert out["total"] == 0


def test_source_walk_exception_is_safe(tmp_path, monkeypatch):
    # iter_source_files blowing up degrades to an empty finding list, safe zero.
    _write(tmp_path, "a.py", "eval(x)\n")

    def _boom(_root, pattern="*.py"):
        raise OSError("walk failed")

    monkeypatch.setattr("app.engine.skip_dirs.iter_source_files", _boom)
    out = develop_readiness(root=str(tmp_path))
    assert out["total"] == 0


def test_detectors_import_failure_is_safe(tmp_path, monkeypatch):
    # If the detector module cannot be imported the scan yields nothing, no crash.
    _write(tmp_path, "a.py", "eval(x)\n")
    monkeypatch.setitem(sys.modules, "app.engine.detectors", None)
    out = develop_readiness(root=str(tmp_path))
    assert out["total"] == 0


def test_file_outside_root_uses_absolute_key(tmp_path, monkeypatch):
    # A scanned file that is not relative_to the root falls back to its own posix
    # path for the record key (the ValueError branch).
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "z.py"
    target.write_text("eval(x)\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.setattr("app.engine.skip_dirs.iter_source_files",
                        lambda _root, pattern="*.py": [target])
    out = develop_readiness(root=str(repo))
    assert out["total"] >= 1
    files = {f["file"] for items in out["buckets"].values() for f in items}
    assert target.as_posix() in files


# --- opt-in reliability weighting ----------------------------------------------

def test_weighting_folds_recorded_track_record(tmp_path):
    # eval -> harden_security (recorded, reliability 0.5) is discounted; exec -> no
    # fix_kind (weight 1.0). The reliability map is non-empty so weighted flips True.
    _write(tmp_path, "a.py", "eval(x)\nexec(y)\n")
    _write_proof(tmp_path, "harden_security", applied=1, blocked=1)
    out = develop_readiness(root=str(tmp_path), weight_by_reliability=True)
    assert out["weighted"] is True
    # fixable weight 0.5 over total 1.5 -> below the unweighted 1/2 share.
    assert out["score"] == round(0.5 / 1.5, 6)


def test_weighting_proof_loader_failure_falls_back(tmp_path, monkeypatch):
    # load_proof_history raising leaves the reliability map empty -> unweighted count.
    _write(tmp_path, "a.py", "eval(x)\n")

    def _boom(_root):
        raise RuntimeError("bad store")

    monkeypatch.setattr("app.engine.proof_history.load_proof_history", _boom)
    out = develop_readiness(root=str(tmp_path), weight_by_reliability=True)
    assert out["weighted"] is False
    assert out["score"] == 1.0


def test_weighting_learned_reliability_failure_falls_back(tmp_path, monkeypatch):
    # learned_reliability raising is tolerated -> empty map -> unweighted count.
    _write(tmp_path, "a.py", "eval(x)\n")
    _write_proof(tmp_path, "harden_security", applied=1, blocked=1)

    def _boom(_history):
        raise RuntimeError("bad rel")

    monkeypatch.setattr("app.engine.proof_history.learned_reliability", _boom)
    out = develop_readiness(root=str(tmp_path), weight_by_reliability=True)
    assert out["weighted"] is False


def test_weighting_proof_history_import_failure_falls_back(tmp_path, monkeypatch):
    # proof_history unimportable -> reliability map empty -> unweighted, no crash.
    _write(tmp_path, "a.py", "eval(x)\n")
    monkeypatch.setitem(sys.modules, "app.engine.proof_history", None)
    out = develop_readiness(root=str(tmp_path), weight_by_reliability=True)
    assert out["weighted"] is False


# --- profile-root recovery -----------------------------------------------------

def test_profile_root_recovered_from_object(tmp_path):
    # A profile object carrying a .root is used when no explicit root is given.
    _write(tmp_path, "a.py", "eval(x)\n")

    class _Profile:
        root = str(tmp_path)

    out = develop_readiness(profile=_Profile(), root="")
    assert out["total"] >= 1


def test_profile_without_known_attrs_is_safe_zero():
    # A profile with none of the known path attributes yields "" -> safe zero.
    class _Bare:
        pass

    out = develop_readiness(profile=_Bare(), root="")
    assert out["total"] == 0
    assert out["score"] == 0.0


def test_profile_alternate_attr_name(tmp_path):
    # The recovery tries several attribute names — project_root is honoured too.
    _write(tmp_path, "a.py", "eval(x)\n")

    class _Profile:
        project_root = str(tmp_path)

    out = develop_readiness(profile=_Profile(), root="")
    assert out["total"] >= 1
