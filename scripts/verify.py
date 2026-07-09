#!/usr/bin/env python3
"""Apex verification harness — the project's one-command green gate.

The full suite (~290 test files) OOMs when run as a SINGLE pytest process in a
memory-constrained container: one process accumulates every module's state until
the kernel kills it (exit 137). This runner splits the suite into N chunks and
runs each in its OWN pytest process, so memory is reclaimed between chunks, then
runs ruff. It is the canonical "is it green?" command — reproducible,
restart-proof (it lives in the repo, not in /tmp), and cross-platform (pure
stdlib, so it works on Windows as well as Linux/macOS).

    python scripts/verify.py               # 4 chunks + ruff  (the default gate)
    python scripts/verify.py --chunks 6    # more, smaller chunks
    python scripts/verify.py --chunk 3     # ONLY chunk 3 of the default 4 (fast re-run)
    python scripts/verify.py --no-lint     # tests only
    python scripts/verify.py --lint-only   # ruff only
    python scripts/verify.py -- -x -k foo  # pass extra args through to pytest
    python scripts/verify.py --chunks 16 -j 8   # 16 chunks, 8 at a time (multi-core host)
    python scripts/verify.py --impacted    # ONLY the tests reaching your changes
    python scripts/verify.py --impacted --base main   # ...diffed against main

The IMPACTED mode is the fast ITERATION loop (founder discipline, 2026-07-08:
develop-velocity — never steal hours waiting on full gates mid-wave): it maps
the files changed since ``--base`` (default: the branch's own origin ref)
through Apex's OWN import-reachability engine (``impacted_test_files`` —
transitive imports, conftest fixtures, literal dynamic imports) and runs ONLY
those test files. It is loudly NOT the push gate: pushing still requires the
full run above. Known contention-heavy test files (``HEAVY_SOLO``) are
excluded from the parallel chunk pool and run SOLO after it — under full-CPU
contention they time out flakily (3× in one day at -j4), each costing a
~20-minute isolated re-run to prove innocent; running them contention-free
kills that tax without weakening the gate.

By default chunks run SEQUENTIALLY so a memory-constrained container never holds
two suites at once (the OOM the chunking exists to prevent). On a host with more
RAM and cores, ``--jobs/-j N`` runs up to N chunks concurrently — each still its
own process, so determinism is unchanged — which (with more ``--chunks``) cuts
wall-clock to roughly the slowest chunk. Exit code is non-zero if any chunk or
ruff fails — drop it straight into CI.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
DEFAULT_CHUNKS = 4

# Test files that flake under FULL-CPU contention (pytest chunks racing on all
# cores) while passing reliably alone — each entry must carry evidence. They
# are excluded from the parallel chunk pool and run SOLO (contention-free)
# after it, so a red gate is a REAL red, not a 20-minute prove-the-flake tax.
# Add a file only after it has flaked in ≥2 independent gate runs at the
# canonical -j4 AND passed isolated re-runs each time.
HEAVY_SOLO = (
    # timed out/failed under -j4 load in 3 consecutive gates (2026-07-08),
    # isolated re-run all-green each time (~97s solo for the slowest test).
    "tests/test_stub_fstring_body_eyml.py",
)


def _pytest_env() -> dict[str, str]:
    """The child environment for a pytest chunk, with the apex repo ROOT pinned
    onto ``PYTHONPATH``.

    The parent pytest process imports ``app`` fine (it runs with ``cwd=ROOT``),
    but several soundness engines (test_shield value/order/env oracle re-capture,
    import/doctest/stub oracles, cross-file-rename verify) prove a change by
    re-running it in a FRESH subprocess under a VARIED working directory — and
    that grandchild imports ``app.…`` too. With ``cwd`` moved away from ROOT it
    can import ``app`` only if the interpreter already knows where the package
    lives, i.e. ``app`` is pip-installed OR ``PYTHONPATH`` carries ROOT. On a bare
    from-checkout run with neither, EVERY value oracle silently DECLINES (the
    import fails, the probe returns "no oracle") and dozens of oracle tests go RED
    for a reason that has nothing to do with the code under test. Pinning ROOT
    here makes the gate SELF-SUFFICIENT and deterministic — it no longer depends
    on an ambient ``PYTHONPATH`` the shell/container may or may not export — which
    is exactly the determinism the proof gate exists to guarantee. A test that
    sets its own ``PYTHONPATH`` (``{**os.environ, "PYTHONPATH": ...}``) still wins,
    because it overrides this in its own child env."""
    inherited = os.environ.get("PYTHONPATH", "")
    pythonpath = str(ROOT) + (os.pathsep + inherited if inherited else "")
    return {**os.environ, "PYTHONPATH": pythonpath}


def discover_tests(tests_dir: Path = TESTS_DIR) -> list[Path]:
    """Every ``tests/test_*.py`` file, sorted — the stable, deterministic order
    that makes ``--chunk K`` mean the same set of files every run."""
    return sorted(tests_dir.glob("test_*.py"))


def chunk_files(files: list[Path], n: int) -> list[list[Path]]:
    """Split ``files`` into ``n`` balanced, contiguous chunks.

    Every file appears in exactly one chunk; chunk sizes differ by at most one;
    empty chunks (more chunks than files) are dropped. Deterministic: the same
    inputs always yield the same partition, so ``--chunk K`` is reproducible."""
    n = max(1, min(n, len(files))) if files else 1
    k, m = divmod(len(files), n)
    chunks: list[list[Path]] = []
    start = 0
    for i in range(n):
        size = k + (1 if i < m else 0)
        chunks.append(files[start:start + size])
        start += size
    return [c for c in chunks if c]


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def split_heavy(files: list[Path],
                heavy: tuple[str, ...] = HEAVY_SOLO) -> tuple[list[Path], list[Path]]:
    """Partition the discovered test files into ``(chunk_pool, solo_tail)``.

    Pure: membership by repo-relative posix path against ``heavy``; order
    preserved on both sides, every file lands on exactly one side. The solo
    tail runs contention-free AFTER the chunk phase (see module docstring)."""
    pool: list[Path] = []
    solos: list[Path] = []
    for f in files:
        (solos if _rel(f).replace("\\", "/") in heavy else pool).append(f)
    return pool, solos


def default_impacted_base() -> str:
    """The default diff base for ``--impacted``: the branch's own origin ref
    (what this wave has not pushed yet), else ``main``, else ``HEAD`` (an
    empty diff — honest no-op). Best-effort and quiet."""
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(ROOT),
        capture_output=True, text=True).stdout.strip()
    for candidate in (f"origin/{branch}" if branch else "", "main", "HEAD"):
        if candidate and subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", candidate],
                cwd=str(ROOT), capture_output=True).returncode == 0:
            return candidate
    return "HEAD"


def git_changed_files(base: str) -> list[str]:
    """Repo-relative paths changed since ``base``: committed (``base...HEAD``),
    staged, unstaged, and untracked — the full picture of what this wave
    touched. Sorted, de-duplicated; a failing git command contributes nothing
    (the selection then honestly shrinks toward empty rather than guessing)."""
    commands = (
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        ["git", "diff", "--name-only"],
        ["git", "diff", "--name-only", "--cached"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    )
    changed: set[str] = set()
    for cmd in commands:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        if proc.returncode == 0:
            changed.update(line.strip() for line in proc.stdout.splitlines()
                           if line.strip())
    return sorted(changed)


def impacted_selection(changed: list[str],
                       root: Path = ROOT) -> tuple[list[Path], list[str]]:
    """Map changed files to ``(test_paths_to_run, uncovered_py_files)`` via
    Apex's own impact engine (``app.engine.test_impact.impacted_test_files`` —
    transitive imports, conftest fixtures, literal dynamic imports).

    ``uncovered_py_files`` lists the changed ``.py`` files NO test reaches —
    disclosed loudly so an impacted-green run never silently implies those
    were exercised (never-fake-green applies to the fast gate too)."""
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from app.engine.test_impact import impacted_test_files

    py_changed = [c for c in changed
                  if c.endswith(".py") and (root / c).exists()]
    impacted = impacted_test_files(root, py_changed)
    uncovered = [c for c in py_changed
                 if not c.startswith("tests/")
                 and not impacted_test_files(root, [c])]
    return [root / rel for rel in impacted], uncovered


def run_chunk(files: list[Path], extra: list[str]) -> int:
    """Run one chunk in its own pytest process; return its exit code."""
    cmd = [sys.executable, "-m", "pytest", *(_rel(f) for f in files),
           "-q", "-p", "no:cacheprovider", *extra]
    return subprocess.run(cmd, cwd=str(ROOT), env=_pytest_env()).returncode


def run_chunk_captured(files: list[Path], extra: list[str]) -> tuple[int, str]:
    """Run one chunk in its own pytest process, CAPTURING its output; return
    ``(exit_code, combined_text)``. Used only by the parallel runner so that
    concurrently-running chunks never interleave their dots on the shared
    stdout — each block is buffered and replayed in chunk order afterwards."""
    cmd = [sys.executable, "-m", "pytest", *(_rel(f) for f in files),
           "-q", "-p", "no:cacheprovider", *extra]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          env=_pytest_env())
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_chunks_parallel(
    labelled: list[tuple[str, list[Path]]], extra: list[str], jobs: int,
) -> list[tuple[str, int]]:
    """Run the labelled chunks concurrently — at most ``jobs`` pytest processes
    at once — each still in its OWN process (no in-process xdist, so per-test
    isolation and determinism are unchanged; only the timing differs). Each
    chunk's output is captured and replayed in chunk ORDER once all finish, so
    the transcript is deterministic regardless of completion order. Returns
    ``(label, exit_code)`` pairs in chunk order.

    Memory note: each chunk peaks around its own pytest process, so only raise
    ``jobs`` on a host with the RAM for it (the cloud gate stays at 1)."""
    from concurrent.futures import ThreadPoolExecutor

    outcomes: list[tuple[int, str]] = [(0, "")] * len(labelled)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(run_chunk_captured, files, extra): idx
            for idx, (_label, files) in enumerate(labelled)
        }
        for fut in futures:
            outcomes[futures[fut]] = fut.result()
    results: list[tuple[str, int]] = []
    for idx, (label, files) in enumerate(labelled):
        code, text = outcomes[idx]
        print(f"\n===== {label} — {len(files)} file(s) =====", flush=True)
        if text:
            print(text if text.endswith("\n") else text + "\n", end="", flush=True)
        results.append((label, code))
    return results


def run_ruff() -> int:
    """Run ``ruff check app/``; return its exit code (0 = clean)."""
    return subprocess.run([sys.executable, "-m", "ruff", "check", "app/"],
                          cwd=str(ROOT)).returncode


def run_north_star_audit() -> int:
    """Run ``apex self-audit --north-star``; return its exit code (0 = PASS/no drift).

    The standing North-Star denetçi (CLAUDE.md names it the durable, automatic form
    of the mission audit) as a first-class gate STEP, a peer of ruff: every gate run
    auto-checks that the objective corpus has not drifted from concrete-development
    (the audit exits non-zero on drift). It is a fast in-process report run in its own
    subprocess — the same isolation discipline ``run_ruff`` keeps — so a red audit
    fails the gate loudly instead of being caught only at wave close. Zero-token,
    offline, deterministic."""
    return subprocess.run(
        [sys.executable, "-m", "app.cli", "self-audit", "--north-star"],
        cwd=str(ROOT)).returncode


def _build_parser() -> argparse.ArgumentParser:
    """The argument parser — kept apart so ``main`` reads as pure control flow."""
    parser = argparse.ArgumentParser(description="Apex chunked verification gate")
    parser.add_argument("--chunks", type=int, default=DEFAULT_CHUNKS,
                        help=f"number of test chunks (default {DEFAULT_CHUNKS})")
    parser.add_argument("--chunk", type=int, default=0,
                        help="run only this 1-based chunk of --chunks (fast re-run)")
    parser.add_argument("--jobs", "-j", type=int, default=1,
                        help="run chunks concurrently, up to N pytest processes at "
                             "once (default 1 = sequential). Each chunk needs ~1-2GB "
                             "RAM; raise only on a host with the memory (the cloud "
                             "gate stays 1). Pairs well with more --chunks.")
    parser.add_argument("--no-lint", action="store_true", help="skip ruff")
    parser.add_argument("--lint-only", action="store_true", help="run ruff only")
    parser.add_argument("--impacted", action="store_true",
                        help="fast ITERATION mode: run only the test files that "
                             "reach the files changed since --base (import "
                             "reachability). NOT the push gate — pushing still "
                             "requires the full run.")
    parser.add_argument("--base", default="",
                        help="diff base for --impacted (default: the branch's "
                             "own origin ref, else main)")
    parser.add_argument("pytest_args", nargs="*",
                        help="extra args passed through to pytest (after --)")
    return parser


def select_chunks(all_chunks: list[list[Path]], chunk: int) -> list[list[Path]]:
    """The chunks to run: just chunk ``K`` (1-based) if requested and in range,
    else every chunk. Pure — the in-range check is shared with ``chunk_in_range``."""
    if chunk and chunk_in_range(chunk, len(all_chunks)):
        return [all_chunks[chunk - 1]]
    return all_chunks


def chunk_in_range(chunk: int, total: int) -> bool:
    """Whether a 1-based ``--chunk`` selector names an existing chunk."""
    return 1 <= chunk <= total


def chunk_label(i: int, chunk: int, total: int, selected: int) -> str:
    """Header label for the i-th selected chunk: pinned to the requested chunk's
    position when ``--chunk`` was given, else its index within the run."""
    return f"chunk {chunk}/{total}" if chunk else f"chunk {i}/{selected}"


def render_summary(results: list[tuple[str, int]], elapsed: float) -> tuple[list[str], int]:
    """Render the final summary block as lines plus the process exit code (1 if
    any step failed, else 0). Pure: no printing, no clock — caller supplies both."""
    failed = [name for name, code in results if code != 0]
    lines = ["\n" + "=" * 48]
    lines += [f"  {'PASS' if code == 0 else 'FAIL'}  {name}" for name, code in results]
    lines.append(f"  {'─' * 44}")
    if failed:
        lines.append(f"  ❌ {len(failed)} step(s) failed: {', '.join(failed)}  ({elapsed:.0f}s)")
        return lines, 1
    lines.append(f"  ✅ all green ({len(results)} step(s), {elapsed:.0f}s)")
    return lines, 0


def _run_labelled(labelled: list[tuple[str, list[Path]]], args,
                  results: list[tuple[str, int]]) -> None:
    """Run labelled chunks (parallel when ``-j`` allows, else streamed) and
    append their outcomes — the one shared runner for every mode."""
    if args.jobs > 1 and len(labelled) > 1:
        results.extend(run_chunks_parallel(labelled, args.pytest_args, args.jobs))
        return
    for label, chunk in labelled:
        print(f"\n===== {label} — {len(chunk)} file(s) =====", flush=True)
        results.append((label, run_chunk(chunk, args.pytest_args)))


def _run_impacted(args, results: list[tuple[str, int]]) -> None:
    """The ``--impacted`` fast-iteration mode: honest banner, reachability
    selection, loud disclosure of changed files no test reaches."""
    base = args.base or default_impacted_base()
    changed = git_changed_files(base)
    files, uncovered = impacted_selection(changed)
    print(f"⚡ IMPACTED gate — {len(changed)} changed file(s) vs {base} → "
          f"{len(files)} test file(s) by import reachability.")
    print("   NOT the push gate: pushing still requires the full run "
          "(python scripts/verify.py --chunks 16 -j 4).")
    for rel in uncovered:
        print(f"   ⚠ no test reaches {rel} — an impacted-green does NOT vouch for it")
    if not files:
        print("   (no impacted tests — nothing to run)")
        return
    sel = chunk_files(files, max(1, min(args.chunks, len(files))))
    labelled = [(f"impacted {i}/{len(sel)}", c) for i, c in enumerate(sel, 1)]
    _run_labelled(labelled, args, results)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    start = time.time()
    results: list[tuple[str, int]] = []

    if not args.lint_only and args.impacted:
        _run_impacted(args, results)
    elif not args.lint_only:
        pool, solos = split_heavy(discover_tests())
        all_chunks = chunk_files(pool, args.chunks)
        if args.chunk and not chunk_in_range(args.chunk, len(all_chunks)):
            print(f"⛔ --chunk {args.chunk} out of range (1..{len(all_chunks)})")
            return 2
        selected = select_chunks(all_chunks, args.chunk)
        labelled = [
            (chunk_label(i, args.chunk, len(all_chunks), len(selected)), chunk)
            for i, chunk in enumerate(selected, 1)
        ]
        _run_labelled(labelled, args, results)
        # The contention-heavy solo tail: full runs only (a --chunk K fast
        # re-run targets the pool partition), one file per process, AFTER the
        # parallel phase so nothing races it on the cores.
        if not args.chunk:
            solo_labelled = [(f"solo {_rel(f)}", [f]) for f in solos]
            for label, chunk in solo_labelled:
                print(f"\n===== {label} — {len(chunk)} file(s) =====", flush=True)
                results.append((label, run_chunk(chunk, args.pytest_args)))

    if not args.no_lint and not args.pytest_args:
        print("\n===== ruff check app/ =====", flush=True)
        results.append(("ruff", run_ruff()))
        print("\n===== self-audit --north-star =====", flush=True)
        results.append(("north-star", run_north_star_audit()))

    lines, code = render_summary(results, time.time() - start)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
