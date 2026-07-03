#!/usr/bin/env python3
"""The durable wave gate — content-keyed chunk checkpoints, insurance bundle,
push-on-green. In-repo so a container reset can never lose the tooling again.

What it runs, in order (the session's monitor grammar, one line per step):

    chunk NN: GREEN (Xs)            # or: chunk NN: RED (Xs) rc=N
    ruff: PASS                      # ruff check app/
    north-star: PASS                # python -m app.cli self-audit --north-star
    ✅ GATE ALL GREEN (16/16 chunks + ruff + north-star) on <tip12>
    PUSHED: origin/<branch> @ <tip12>

Chunks are the EXACT ``scripts/verify.py`` partition: each chunk is a verify.py
subprocess (``--chunks N --chunk K --no-lint``), so this runner can never drift
from the canonical gate — verify.py itself selects the files. At most
``MAX_JOBS = 3`` chunks run concurrently: this container OOMs at 5 concurrent
pytest processes (see CLAUDE.md), so the ceiling is hard-coded and requests
above it are clamped.

Checkpoints (``--state-dir``, default ``.apex/gatechk`` — gitignored via the
existing ``.apex/*`` rule) are keyed by CONTENT, not tip hash:

    key = sha256( tree(HEAD:app) + tree(HEAD:scripts) + blob(tests/conftest.py)
                  + working-tree hashes of any dirty app/scripts file
                  + the blob hashes of the chunk's OWN test files )

so a test-only fix re-runs ONLY the chunks whose files changed (minutes, not
the full ~40-minute sweep), while ANY app/ or scripts/ change invalidates every
chunk (a source change can affect any test). A checkpoint is written only for a
GREEN chunk — never fake green.

Self-healing: ``--tip <sha>`` asserts HEAD is that commit and, if the container
was reset underneath us, restores it (fetch origin, then ``git bundle
unbundle <state-dir>/wave.bundle`` as the offline fallback, then hard-reset).

Insurance (``--insurance``, DEFAULT OFF): before chunking, write the wave
bundle (``origin/<branch>..HEAD`` when origin has the branch, else full HEAD)
into the state dir AND print it gzip+base64 to stdout — the transcript itself
becomes the backup — and best-effort push ``refs/backup/wave-<tip12>`` to
origin (a rejection warns and continues; the backup ref is deleted best-effort
after the all-green push).

Push happens ONLY on all-green (chunks + ruff + north-star), with 2/4/8/16s
retries, after idempotently configuring the local-proxy credential helper.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verify
import wave_common as wc

ROOT = wc.ROOT
DEFAULT_CHUNKS = 16
DEFAULT_STATE_DIR = ".apex/gatechk"
# The OOM ceiling: 5 concurrent pytest processes has OOM'd this container
# (CLAUDE.md "≤3 heavy engineers"); the gate itself obeys the same physics.
MAX_JOBS = 3
RETRY_DELAYS = (2, 4, 8, 16)
# The local-proxy credential helper this environment's remote needs; configured
# idempotently (only when origin points at the proxy AND no helper is set).
CREDENTIAL_HELPER = "!f(){ echo username=local_proxy; echo password=x; }; f"


def effective_jobs(requested: int) -> int:
    """Clamp the requested concurrency into [1, MAX_JOBS] — the OOM ceiling."""
    return max(1, min(requested, MAX_JOBS))


# --- content keys -------------------------------------------------------------

def chunk_key(base_material: str, blob_hashes: list[str]) -> str:
    """The checkpoint key for one chunk — a pure sha256 of the shared base
    material plus the chunk's own test-file blob hashes, in chunk order."""
    h = hashlib.sha256()
    h.update(base_material.encode("utf-8"))
    for blob in blob_hashes:
        h.update(b"\0" + blob.encode("utf-8"))
    return h.hexdigest()


def base_key_material(dirty: set[str]) -> str:
    """The key material every chunk shares: the app/ and scripts/ tree hashes,
    the conftest blob, and the working-tree hash of any dirty app/scripts file
    (so an uncommitted source edit invalidates every checkpoint)."""
    conftest = (wc.working_blob_hash("tests/conftest.py")
                if "tests/conftest.py" in dirty
                else wc.head_hash("HEAD:tests/conftest.py"))
    parts = [
        "app=" + wc.head_hash("HEAD:app"),
        "scripts=" + wc.head_hash("HEAD:scripts"),
        "conftest=" + conftest,
    ]
    for rel in sorted(p for p in dirty if p.startswith(("app/", "scripts/"))):
        parts.append(f"dirty:{rel}=" + wc.working_blob_hash(rel))
    return "\n".join(parts)


def head_test_blobs() -> dict[str, str]:
    """``{rel_path: blob_hash}`` for every file under tests/ at HEAD — one
    ls-tree call instead of a rev-parse per test file."""
    blobs: dict[str, str] = {}
    for line in wc.git_out("ls-tree", "-r", "HEAD", "tests", check=False).splitlines():
        meta, _, rel = line.partition("\t")
        fields = meta.split()
        if len(fields) == 3 and fields[1] == "blob":
            blobs[rel] = fields[2]
    return blobs


def chunk_keys(chunks: list[list[Path]]) -> list[str]:
    """The content key of every chunk, in chunk order. A dirty (or untracked)
    test file is hashed from the working tree so the key follows what pytest
    would actually run, not what HEAD says."""
    dirty = wc.dirty_paths("app", "scripts", "tests")
    head_blobs = head_test_blobs()
    base = base_key_material(dirty)
    keys: list[str] = []
    for files in chunks:
        hashes: list[str] = []
        for f in files:
            rel = f.relative_to(ROOT).as_posix() if f.is_absolute() else Path(f).as_posix()
            hashes.append(wc.working_blob_hash(rel) if rel in dirty
                          else head_blobs.get(rel, "absent"))
        keys.append(chunk_key(base, hashes))
    return keys


# --- checkpoints ----------------------------------------------------------------

def checkpoint_path(state_dir: Path, idx: int, key: str) -> Path:
    """Where chunk ``idx``'s GREEN checkpoint for ``key`` lives."""
    return state_dir / f"chunk-{idx:02d}-{key[:16]}.json"


def write_checkpoint(state_dir: Path, idx: int, key: str, files: list[Path]) -> None:
    """Record a GREEN chunk. Only green is ever recorded — a red chunk leaves
    no checkpoint, so it always re-runs."""
    payload = {"chunk": idx, "key": key,
               "files": [f.name for f in files], "rc": 0}
    checkpoint_path(state_dir, idx, key).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# --- chunk execution ------------------------------------------------------------

def run_verify_chunk(idx: int, total: int) -> tuple[int, float, str]:
    """Run one chunk as a ``scripts/verify.py`` subprocess (the canonical
    partition — no re-implementation to drift). Returns (rc, elapsed, output)."""
    start = time.time()
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "verify.py"),
         "--chunks", str(total), "--chunk", str(idx), "--no-lint"],
        cwd=str(ROOT), capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, time.time() - start, out


def chunk_line(idx: int, rc: int, elapsed: float, cached: bool = False) -> str:
    """One monitor-grammar status line: ``chunk NN: GREEN (Xs)`` or
    ``chunk NN: RED (Xs) rc=N`` (a cached hit appends ``cached`` AFTER the
    grammar so prefix-anchored monitors still match)."""
    if rc == 0:
        return f"chunk {idx:02d}: GREEN ({elapsed:.0f}s)" + (" cached" if cached else "")
    return f"chunk {idx:02d}: RED ({elapsed:.0f}s) rc={rc}"


def run_chunks(chunks: list[list[Path]], keys: list[str], state_dir: Path,
               total: int, jobs: int) -> list[int]:
    """Run every non-checkpointed chunk (at most ``jobs`` ≤ MAX_JOBS at once);
    cached chunks report GREEN immediately. Returns per-chunk exit codes in
    chunk order. A red chunk's captured output is replayed for diagnosis."""
    rcs = [0] * len(chunks)
    pending: list[tuple[int, str, list[Path]]] = []
    for i, (files, key) in enumerate(zip(chunks, keys), 1):
        if checkpoint_path(state_dir, i, key).exists():
            print(chunk_line(i, 0, 0.0, cached=True), flush=True)
        else:
            pending.append((i, key, files))
    with ThreadPoolExecutor(max_workers=effective_jobs(jobs)) as pool:
        futures = {pool.submit(run_verify_chunk, i, total): (i, key, files)
                   for i, key, files in pending}
        for fut in as_completed(futures):
            i, key, files = futures[fut]
            rc, elapsed, out = fut.result()
            rcs[i - 1] = rc
            print(chunk_line(i, rc, elapsed), flush=True)
            if rc != 0:
                print(out, flush=True)
            else:
                write_checkpoint(state_dir, i, key, files)
    return rcs


# --- push + insurance -----------------------------------------------------------

def ensure_credential_helper() -> None:
    """Idempotently configure the local-proxy credential helper: only when no
    helper is configured AND origin actually points at the local proxy. Running
    it twice (or on a normally-configured clone) changes nothing."""
    if wc.git_out("config", "--get", "credential.helper", check=False):
        return
    if "local_proxy@" not in wc.git_out("config", "--get", "remote.origin.url", check=False):
        return
    wc.git_ok("config", "credential.helper", CREDENTIAL_HELPER)


def _push_once(refspec: str) -> int:
    return subprocess.run(["git", "push", "origin", refspec],
                          cwd=str(ROOT)).returncode


def push_with_retries(branch: str, tip12: str,
                      delays: tuple[int, ...] = RETRY_DELAYS,
                      pusher=None, sleep=time.sleep) -> bool:
    """Push HEAD to origin/<branch>, retrying on failure with the 2/4/8/16s
    backoff. Prints the monitor-grammar ``PUSHED:`` line on success."""
    pusher = pusher or _push_once
    refspec = f"HEAD:refs/heads/{branch}"
    for attempt in range(len(delays) + 1):
        if pusher(refspec) == 0:
            print(f"PUSHED: origin/{branch} @ {tip12}", flush=True)
            return True
        if attempt < len(delays):
            print(f"push failed — retrying in {delays[attempt]}s", flush=True)
            sleep(delays[attempt])
    print("⛔ push failed after retries — gate is green but UNPUSHED", flush=True)
    return False


def encode_bundle(data: bytes) -> str:
    """gzip+base64 a bundle for the transcript — deterministic (``mtime=0``
    pins the gzip header), so the same bundle always prints the same text."""
    return base64.encodebytes(gzip.compress(data, mtime=0)).decode("ascii")


def make_insurance(state_dir: Path, tip12: str, branch: str) -> None:
    """The reset-insurance: write the wave bundle into the state dir, print it
    gzip+base64 (the transcript becomes the durable copy), and best-effort push
    a backup ref. Every failure here warns and continues — insurance must never
    block the gate itself."""
    bundle = state_dir / "wave.bundle"
    spec = (f"origin/{branch}..HEAD"
            if wc.git_out("rev-parse", "--verify", f"origin/{branch}", check=False)
            else "HEAD")
    if not wc.git_ok("bundle", "create", str(bundle), spec) and \
            not wc.git_ok("bundle", "create", str(bundle), "HEAD"):
        print("insurance: bundle creation FAILED — continuing without", flush=True)
        return
    print(f"--- insurance bundle wave-{tip12} (gzip+base64; decode, gunzip, "
          "then `git bundle unbundle`) ---")
    sys.stdout.write(encode_bundle(bundle.read_bytes()))
    print(f"--- end insurance bundle wave-{tip12} ---", flush=True)
    ensure_credential_helper()
    if wc.git_ok("push", "origin", f"HEAD:refs/backup/wave-{tip12}"):
        print(f"insurance: backup ref refs/backup/wave-{tip12} pushed", flush=True)
    else:
        print("insurance: backup-ref push rejected — continuing "
              "(the bundle above is the fallback)", flush=True)


def delete_backup_ref(tip12: str) -> None:
    """Best-effort removal of the insurance ref once the branch is pushed."""
    if wc.git_ok("push", "origin", f":refs/backup/wave-{tip12}"):
        print(f"insurance: backup ref refs/backup/wave-{tip12} deleted", flush=True)


# --- tip self-healing -----------------------------------------------------------

def _commit_present(sha: str) -> bool:
    return wc.git_ok("cat-file", "-e", f"{sha}^{{commit}}")


def restore_tip(tip: str, state_dir: Path) -> bool:
    """Assert HEAD is ``tip``; if the container was reset underneath us,
    restore it — fetch origin, then unbundle the wave bundle as the offline
    fallback, then hard-reset. False when the commit is unrecoverable."""
    if not _commit_present(tip):
        print(f"tip {tip} not local — fetching origin", flush=True)
        wc.git_ok("fetch", "origin")
    bundle = state_dir / "wave.bundle"
    if not _commit_present(tip) and bundle.is_file():
        print(f"tip {tip} still absent — unbundling {bundle}", flush=True)
        wc.git_ok("bundle", "unbundle", str(bundle))
    if not _commit_present(tip):
        print(f"⛔ cannot obtain {tip}: not local, not in origin, "
              f"no usable {bundle}", flush=True)
        return False
    want = wc.git_out("rev-parse", f"{tip}^{{commit}}")
    head = wc.git_out("rev-parse", "HEAD")
    if head != want:
        print(f"HEAD {head[:12]} != tip {want[:12]} — restoring "
              "(git reset --hard)", flush=True)
        return wc.git_ok("reset", "--hard", want)
    return True


# --- cli -------------------------------------------------------------------------

def warn_if_tracked(state_dir: Path) -> None:
    """Checkpoints are runtime artifacts — warn loudly if the chosen state dir
    is not gitignored (the default ``.apex/gatechk`` is, via ``.apex/*``)."""
    if not wc.git_ok("check-ignore", "-q", str(state_dir)):
        print(f"⚠ state dir {state_dir} is NOT gitignored — "
              "checkpoints could leak into commits", flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apex durable wave gate: content-keyed chunked verify + "
                    "ruff + north-star, push on all-green")
    parser.add_argument("--chunks", type=int, default=DEFAULT_CHUNKS,
                        help=f"number of verify chunks (default {DEFAULT_CHUNKS})")
    parser.add_argument("--jobs", "-j", type=int, default=MAX_JOBS,
                        help=f"concurrent chunks, clamped to {MAX_JOBS} "
                             "(the container's OOM ceiling)")
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR,
                        help=f"checkpoint dir (default {DEFAULT_STATE_DIR}, gitignored)")
    parser.add_argument("--tip", default=None,
                        help="assert/restore HEAD to this commit before gating")
    parser.add_argument("--branch", default=None,
                        help="branch to push (default: current branch)")
    parser.add_argument("--insurance", action="store_true",
                        help="write + print the wave bundle and push a backup "
                             "ref before gating (default off)")
    parser.add_argument("--no-push", action="store_true",
                        help="never push, even on all-green (dry gate)")
    return parser


def _push_phase(args: argparse.Namespace, branch: str, tip12: str) -> int:
    """The on-green tail: configure credentials, push with retries, retire the
    insurance ref. Returns the process exit code."""
    if args.no_push:
        print("push: skipped (--no-push)", flush=True)
        return 0
    ensure_credential_helper()
    if not push_with_retries(branch, tip12):
        return 1
    if args.insurance:
        delete_backup_ref(tip12)
    return 0


def gate_verdict(rcs: list[int], ruff_rc: int, ns_rc: int,
                 nchunks: int, tip12: str) -> bool:
    """Print the red summary or the all-green monitor line; True iff green."""
    red = [f"chunk {i:02d}" for i, rc in enumerate(rcs, 1) if rc != 0]
    red += ["ruff"] if ruff_rc else []
    red += ["north-star"] if ns_rc else []
    if red:
        print(f"⛔ GATE RED on {tip12}: {', '.join(red)} — NOT pushing", flush=True)
        return False
    print(f"✅ GATE ALL GREEN ({nchunks}/{nchunks} chunks + ruff + "
          f"north-star) on {tip12}", flush=True)
    return True


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    state_dir = ROOT / args.state_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    warn_if_tracked(state_dir)
    if args.tip and not restore_tip(args.tip, state_dir):
        return 2
    tip12 = wc.git_out("rev-parse", "HEAD")[:12]
    branch = args.branch or wc.current_branch()
    if not branch or branch == "HEAD":
        print("⛔ detached HEAD — pass --branch to name the push target")
        return 2
    if args.insurance:
        make_insurance(state_dir, tip12, branch)
    chunks = verify.chunk_files(verify.discover_tests(), args.chunks)
    rcs = run_chunks(chunks, chunk_keys(chunks), state_dir, args.chunks,
                     args.jobs)
    ruff_rc = verify.run_ruff()
    print(f"ruff: {'PASS' if ruff_rc == 0 else 'FAIL'}", flush=True)
    ns_rc = verify.run_north_star_audit()
    print(f"north-star: {'PASS' if ns_rc == 0 else 'FAIL'}", flush=True)
    if not gate_verdict(rcs, ruff_rc, ns_rc, len(chunks), tip12):
        return 1
    return _push_phase(args, branch, tip12)


if __name__ == "__main__":
    raise SystemExit(main())
