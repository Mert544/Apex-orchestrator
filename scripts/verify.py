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

Exit code is non-zero if any chunk or ruff fails — drop it straight into CI.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
DEFAULT_CHUNKS = 4


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


def run_chunk(files: list[Path], extra: list[str]) -> int:
    """Run one chunk in its own pytest process; return its exit code."""
    cmd = [sys.executable, "-m", "pytest", *(_rel(f) for f in files),
           "-q", "-p", "no:cacheprovider", *extra]
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def run_ruff() -> int:
    """Run ``ruff check app/``; return its exit code (0 = clean)."""
    return subprocess.run([sys.executable, "-m", "ruff", "check", "app/"],
                          cwd=str(ROOT)).returncode


def _build_parser() -> argparse.ArgumentParser:
    """The argument parser — kept apart so ``main`` reads as pure control flow."""
    parser = argparse.ArgumentParser(description="Apex chunked verification gate")
    parser.add_argument("--chunks", type=int, default=DEFAULT_CHUNKS,
                        help=f"number of test chunks (default {DEFAULT_CHUNKS})")
    parser.add_argument("--chunk", type=int, default=0,
                        help="run only this 1-based chunk of --chunks (fast re-run)")
    parser.add_argument("--no-lint", action="store_true", help="skip ruff")
    parser.add_argument("--lint-only", action="store_true", help="run ruff only")
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


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    start = time.time()
    results: list[tuple[str, int]] = []

    if not args.lint_only:
        all_chunks = chunk_files(discover_tests(), args.chunks)
        if args.chunk and not chunk_in_range(args.chunk, len(all_chunks)):
            print(f"⛔ --chunk {args.chunk} out of range (1..{len(all_chunks)})")
            return 2
        selected = select_chunks(all_chunks, args.chunk)
        for i, chunk in enumerate(selected, 1):
            label = chunk_label(i, args.chunk, len(all_chunks), len(selected))
            print(f"\n===== {label} — {len(chunk)} file(s) =====", flush=True)
            results.append((label, run_chunk(chunk, args.pytest_args)))

    if not args.no_lint and not args.pytest_args:
        print("\n===== ruff check app/ =====", flush=True)
        results.append(("ruff", run_ruff()))

    lines, code = render_summary(results, time.time() - start)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
