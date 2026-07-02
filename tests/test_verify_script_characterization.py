"""Characterization of scripts/verify.py main() — pins exact stdout + exit code.

This locks the project's green-gate CLI behaviour so a refactor of ``main`` cannot
drift: it drives ``main`` with the step-runners (discover/run_chunk/run_ruff) and
the clock mocked, across every branch (all-pass, a failing chunk, ruff fail,
--chunk in/out of range, --lint-only, --no-lint, pytest passthrough), and asserts
the printed text and the return code byte-for-byte. Deterministic, offline,
stdlib-only.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
from pathlib import Path
from unittest import mock

import pytest

VERIFY_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify.py"


def _load_verify():
    spec = importlib.util.spec_from_file_location("apex_verify_script", VERIFY_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


verify = _load_verify()

# A fixed, fake test corpus so chunking is deterministic and independent of the
# real tests/ directory contents.
FAKE_FILES = [
    Path(VERIFY_PATH).resolve().parents[1] / "tests" / f"test_{i:02d}.py"
    for i in range(10)
]


def _drive(argv, chunk_codes, ruff_code, north_star_code=0):
    """Run verify.main(argv) with step-runners + clock mocked.

    chunk_codes is consumed in order (cycled) for each run_chunk call; ruff_code
    is the run_ruff return; north_star_code is the run_north_star_audit return
    (defaults to 0 = PASS/no drift, the current-tree posture). The clock yields a
    fixed 42s elapsed. Returns (stdout, exit_code)."""
    state = {"i": 0}

    def fake_run_chunk(files, extra):
        code = chunk_codes[state["i"] % len(chunk_codes)]
        state["i"] += 1
        return code

    buf = io.StringIO()
    with mock.patch.object(verify, "discover_tests", return_value=list(FAKE_FILES)), \
         mock.patch.object(verify, "run_chunk", side_effect=fake_run_chunk), \
         mock.patch.object(verify, "run_ruff", return_value=ruff_code), \
         mock.patch.object(verify, "run_north_star_audit", return_value=north_star_code), \
         mock.patch.object(verify.time, "time", side_effect=[100.0, 142.7]), \
         contextlib.redirect_stdout(buf):
        rc = verify.main(argv)
    return buf.getvalue(), rc


def test_all_pass_with_ruff():
    out, rc = _drive([], [0], 0)
    assert rc == 0
    assert out == (
        "\n===== chunk 1/4 — 3 file(s) =====\n"
        "\n===== chunk 2/4 — 3 file(s) =====\n"
        "\n===== chunk 3/4 — 2 file(s) =====\n"
        "\n===== chunk 4/4 — 2 file(s) =====\n"
        "\n===== ruff check app/ =====\n"
        "\n===== self-audit --north-star =====\n"
        "\n" + "=" * 48 + "\n"
        "  PASS  chunk 1/4\n"
        "  PASS  chunk 2/4\n"
        "  PASS  chunk 3/4\n"
        "  PASS  chunk 4/4\n"
        "  PASS  ruff\n"
        "  PASS  north-star\n"
        f"  {'─' * 44}\n"
        "  ✅ all green (6 step(s), 43s)\n"
    )


def test_north_star_drift_fails_gate():
    # The North-Star denetçi wired as a peer of ruff: a non-zero self-audit
    # (drift detected) fails the gate, printed like the ruff FAIL line.
    out, rc = _drive([], [0], 0, north_star_code=1)
    assert rc == 1
    assert "  FAIL  north-star\n" in out
    assert "  ❌ 1 step(s) failed: north-star  (43s)\n" in out


def test_ruff_failure_returns_one():
    out, rc = _drive([], [0], 1)
    assert rc == 1
    assert "  FAIL  ruff\n" in out
    assert "  ❌ 1 step(s) failed: ruff  (43s)\n" in out


def test_failing_chunk_returns_one():
    out, rc = _drive([], [0, 1, 0, 0], 0)
    assert rc == 1
    assert "  FAIL  chunk 2/4\n" in out
    assert "  ❌ 1 step(s) failed: chunk 2/4  (43s)\n" in out


def test_single_chunk_in_range_label_pinned():
    out, rc = _drive(["--chunk", "2", "--no-lint"], [0], 0)
    assert rc == 0
    assert out == (
        "\n===== chunk 2/4 — 3 file(s) =====\n"
        "\n" + "=" * 48 + "\n"
        "  PASS  chunk 2/4\n"
        f"  {'─' * 44}\n"
        "  ✅ all green (1 step(s), 43s)\n"
    )


def test_single_chunk_failure():
    out, rc = _drive(["--chunk", "2"], [1], 0)
    assert rc == 1
    assert "  FAIL  chunk 2/4\n" in out


def test_chunk_out_of_range_returns_two():
    out, rc = _drive(["--chunk", "99"], [0], 0)
    assert rc == 2
    assert out == "⛔ --chunk 99 out of range (1..4)\n"


def test_no_lint_skips_ruff():
    out, rc = _drive(["--no-lint"], [0], 0)
    assert rc == 0
    # --no-lint drops the whole static-gate group (ruff AND its north-star peer).
    assert "ruff" not in out
    assert "north-star" not in out
    assert "  ✅ all green (4 step(s), 43s)\n" in out


def test_lint_only_runs_ruff_and_north_star():
    out, rc = _drive(["--lint-only"], [0], 0)
    assert rc == 0
    assert "chunk" not in out
    assert "===== ruff check app/ =====" in out
    assert "===== self-audit --north-star =====" in out
    # --lint-only runs the static-gate group: ruff + north-star, no tests.
    assert "  ✅ all green (2 step(s), 43s)\n" in out


def test_pytest_passthrough_disables_ruff():
    out, rc = _drive(["--", "-x", "-k", "foo"], [0], 0)
    assert rc == 0
    # A pytest passthrough disables the whole static-gate group (ruff + north-star).
    assert "ruff" not in out
    assert "north-star" not in out
    assert "  ✅ all green (4 step(s), 43s)\n" in out


def test_more_chunks_than_files_drops_empty():
    out, rc = _drive(["--chunks", "20"], [0], 0)
    assert rc == 0
    # 10 files -> 10 non-empty chunks even though 20 were requested.
    for n in range(1, 11):
        assert f"===== chunk {n}/10 — 1 file(s) =====" in out
    # 10 chunk steps + ruff + north-star = 12 steps.
    assert "  ✅ all green (12 step(s), 43s)\n" in out


@pytest.mark.parametrize("chunks", [1, 3, 4, 6])
def test_chunk_count_total_files_preserved(chunks):
    out, _ = _drive(["--chunks", str(chunks), "--no-lint"], [0], 0)
    total = sum(int(line.split("—")[1].split("file")[0])
                for line in out.splitlines() if line.startswith("\n=====") is False and "file(s)" in line)
    assert total == len(FAKE_FILES)


# --- parallel mode (--jobs/-j): opt-in, deterministic transcript -------------

def _drive_parallel(argv, fail_file=None, ruff_code=0):
    """Run main(argv) with the CAPTURED chunk-runner + ruff + clock mocked.

    ``fail_file`` (a test_NN.py name) makes exactly the chunk containing it exit
    1 — keyed on file CONTENT, not a shared counter, so the result is
    deterministic regardless of thread completion order."""
    def fake_captured(files, extra):
        names = {f.name for f in files}
        code = 1 if (fail_file and fail_file in names) else 0
        return code, f"captured {len(files)} file(s)\n"

    buf = io.StringIO()
    with mock.patch.object(verify, "discover_tests", return_value=list(FAKE_FILES)), \
         mock.patch.object(verify, "run_chunk_captured", side_effect=fake_captured), \
         mock.patch.object(verify, "run_ruff", return_value=ruff_code), \
         mock.patch.object(verify, "run_north_star_audit", return_value=0), \
         mock.patch.object(verify.time, "time", side_effect=[100.0, 142.7]), \
         contextlib.redirect_stdout(buf):
        rc = verify.main(argv)
    return buf.getvalue(), rc


def test_default_jobs_is_sequential_unchanged():
    # jobs defaults to 1 -> the sequential path is taken byte-for-byte (the
    # captured runner must NOT be consulted), so the canonical transcript holds.
    with mock.patch.object(verify, "run_chunk_captured",
                           side_effect=AssertionError("parallel path must not run")):
        out, rc = _drive([], [0], 0)
    assert rc == 0 and "  ✅ all green (6 step(s), 43s)\n" in out


def test_parallel_all_pass_orders_chunks_and_is_green():
    out, rc = _drive_parallel(["--chunks", "4", "-j", "4"])
    assert rc == 0
    # Headers appear in CHUNK ORDER despite concurrent execution.
    pos = [out.index(f"===== chunk {n}/4 ") for n in range(1, 5)]
    assert pos == sorted(pos)
    # 4 chunk steps + ruff + north-star = 6 steps.
    assert "  ✅ all green (6 step(s), 43s)\n" in out
    assert out.count("captured ") == 4  # every chunk's buffered block replayed


def test_parallel_failing_chunk_reported_deterministically():
    # FAKE_FILES[3] = test_03.py lands in chunk 2 of 4 (files 3-4, 0-based 2-3).
    out, rc = _drive_parallel(["--chunks", "4", "-j", "4"], fail_file="test_03.py")
    assert rc == 1
    assert "  FAIL  chunk 2/4\n" in out
    assert "  ❌ 1 step(s) failed: chunk 2/4  (43s)\n" in out


def test_parallel_with_single_chunk_falls_back_to_sequential():
    # --chunk 2 selects ONE chunk; even with -j 8 the live (sequential) path is
    # used (len(labelled) == 1), so run_chunk_captured is never called.
    with mock.patch.object(verify, "run_chunk_captured",
                           side_effect=AssertionError("should stay sequential")):
        out, rc = _drive(["--chunk", "2", "-j", "8", "--no-lint"], [0], 0)
    assert rc == 0 and "  PASS  chunk 2/4\n" in out


# --- _pytest_env: the gate's self-sufficient child environment -----------------
#
# The chunk subprocess must be able to import ``app`` even when it (or an oracle
# grandchild it spawns) runs with cwd moved away from ROOT, so ``_pytest_env`` pins
# ROOT onto PYTHONPATH. Without it a bare from-checkout run (app not installed,
# PYTHONPATH unset) silently declines every value oracle and dozens of oracle tests
# go RED for a reason unrelated to the code under test.

def test_pytest_env_pins_root_when_pythonpath_unset():
    with mock.patch.dict(os.environ, {}, clear=True):
        env = verify._pytest_env()
    # ROOT is the whole PYTHONPATH (no stray leading/trailing separator).
    assert env["PYTHONPATH"] == str(verify.ROOT)


def test_pytest_env_prepends_root_preserving_inherited():
    inherited = os.pathsep.join(["/some/where", "/other/lib"])
    with mock.patch.dict(os.environ, {"PYTHONPATH": inherited}, clear=True):
        env = verify._pytest_env()
    # ROOT wins the import race (first), but the caller's paths are preserved after.
    assert env["PYTHONPATH"] == str(verify.ROOT) + os.pathsep + inherited


def test_pytest_env_is_a_superset_of_os_environ():
    with mock.patch.dict(os.environ, {"APEX_MARKER": "keep-me"}, clear=True):
        env = verify._pytest_env()
    # Every other inherited var survives (only PYTHONPATH is (re)written).
    assert env["APEX_MARKER"] == "keep-me"


def test_run_chunk_passes_pytest_env_to_subprocess():
    # The env-pinning is actually WIRED into the chunk spawn, not just defined.
    sentinel = {"PYTHONPATH": "sentinel-env"}
    with mock.patch.object(verify, "_pytest_env", return_value=sentinel), \
         mock.patch.object(verify.subprocess, "run") as run:
        run.return_value = mock.Mock(returncode=0)
        verify.run_chunk([verify.ROOT / "tests" / "test_x.py"], [])
    assert run.call_args.kwargs.get("env") is sentinel
