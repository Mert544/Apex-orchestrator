#!/usr/bin/env python3
""""Neredeyiz?" — the 5-second freshness pulse a new session runs first.

Prints, in a fixed deterministic order, everything a fresh session needs to
continue where the last one left off:

* local vs origin tip (+ ahead/behind divergence) — is this checkout stale?
* the newest ``docs/PROGRESS.md`` entry's first line — what shipped last;
* the rank-1 landable from ``.apex/agenda.json`` — what Apex itself would do
  next (an honest absent-line when no agenda exists; nothing is invented);
* pending deferred items — every ``ERTELENEN`` / ``AÇIK KARAR`` marker line
  still sitting in PROGRESS;
* whether ``.apex/gatechk`` holds checkpoints reusable at the CURRENT content
  keys (so the next gate run's cost is known before starting it).

Read-only (git plumbing reads + file reads; ``hash-object`` without ``-w``
writes nothing), no clock, no network — same repo state, same output, always.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import gate_runner
import wave_common as wc

ROOT = wc.ROOT
_DEFERRED_MARKERS = ("ERTELENEN", "AÇIK KARAR")
_DEFERRED_CAP = 8


def _trunc(text: str, width: int) -> str:
    text = text.strip()
    return text if len(text) <= width else text[: width - 1] + "…"


def tip_lines() -> list[str]:
    """Local vs origin tip and their divergence — honest when origin's ref is
    not present locally (this is read-only; it never fetches)."""
    branch = wc.current_branch()
    lines = [f"branch: {branch or '(not a git repo?)'}",
             f"local:  {wc.git_out('rev-parse', 'HEAD', check=False)[:12]}"]
    origin = (wc.git_out("rev-parse", f"origin/{branch}", check=False)
              if branch and branch != "HEAD" else "")
    if not origin:
        lines.append(f"origin: absent (origin/{branch} not known locally — "
                     "fetch to compare)")
        return lines
    lines.append(f"origin: {origin[:12]} (origin/{branch})")
    counts = wc.git_out("rev-list", "--left-right", "--count",
                        f"HEAD...origin/{branch}", check=False)
    ahead, _, behind = counts.partition("\t")
    lines.append(f"divergence: ahead {ahead or '?'} / behind {behind.strip() or '?'}")
    return lines


def progress_line(path: Path | None = None) -> str:
    """The first line of the NEWEST docs/PROGRESS.md entry (the file is
    newest-first: header block, ``---``, then the latest wave paragraph)."""
    path = path or ROOT / "docs" / "PROGRESS.md"
    if not path.is_file():
        return f"progress: absent ({path.name} not found)"
    lines = path.read_text(encoding="utf-8").splitlines()
    seen_rule = False
    for line in lines:
        if line.strip() == "---":
            seen_rule = True
            continue
        if seen_rule and line.strip():
            return "progress: " + _trunc(line, 200)
    return "progress: no entry found after the header rule"


def agenda_line(path: Path | None = None) -> str:
    """The rank-1 landable from .apex/agenda.json — or the honest absent line
    (a pulse never invents an agenda that was not computed)."""
    path = path or ROOT / ".apex" / "agenda.json"
    if not path.is_file():
        return ("agenda: absent (.apex/agenda.json not found — "
                "`apex agenda` or a daemon beat writes it)")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return "agenda: unreadable (.apex/agenda.json is not valid JSON)"
    landable = (data.get("lanes") or {}).get("landable") or []
    if not landable:
        return "agenda: no landable entries (lanes.landable is empty)"
    top = landable[0]
    return (f"agenda: rank-1 landable = {top.get('fix_kind', '?')} @ "
            f"{top.get('file', '?')}:{top.get('line', 0)} "
            f"(value {top.get('value', 0)})")


def deferred_lines(path: Path | None = None) -> list[str]:
    """Every PROGRESS line carrying a deferred/open-decision marker, with line
    numbers — the debt a new session should know it inherited."""
    path = path or ROOT / "docs" / "PROGRESS.md"
    if not path.is_file():
        return [f"deferred: unknown ({path.name} not found)"]
    hits = [(n, line) for n, line in
            enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if any(marker in line for marker in _DEFERRED_MARKERS)]
    if not hits:
        return ["deferred: none found (no ERTELENEN / AÇIK KARAR markers)"]
    lines = [f"deferred: {len(hits)} marker line(s) in {path.name}"]
    lines += [f"  L{n}: {_trunc(line, 140)}" for n, line in hits[:_DEFERRED_CAP]]
    if len(hits) > _DEFERRED_CAP:
        lines.append(f"  … +{len(hits) - _DEFERRED_CAP} more")
    return lines


def gatechk_line(state_dir: Path | None = None, fast: bool = False) -> str:
    """Whether the gate checkpoint dir holds checkpoints reusable at the
    CURRENT content keys (``--fast`` skips the key computation and just
    counts files)."""
    state_dir = state_dir or ROOT / gate_runner.DEFAULT_STATE_DIR
    if not state_dir.is_dir():
        return (f"gatechk: no checkpoint dir ({state_dir.name} absent — "
                "the first gate run creates it)")
    files = sorted(state_dir.glob("chunk-*.json"))
    if not files:
        return "gatechk: dir present, 0 checkpoints"
    if fast:
        return f"gatechk: {len(files)} checkpoint file(s) (--fast: reuse not verified)"
    try:
        chunks = gate_runner.verify.chunk_files(
            gate_runner.verify.discover_tests(), gate_runner.DEFAULT_CHUNKS)
        keys = gate_runner.chunk_keys(chunks)
        reusable = sum(
            1 for i, key in enumerate(keys, 1)
            if gate_runner.checkpoint_path(state_dir, i, key).exists())
        return (f"gatechk: {reusable}/{len(chunks)} chunks reusable at current "
                f"content keys ({len(files)} checkpoint file(s) on disk)")
    except Exception as exc:  # honest degradation — a pulse must never crash
        return f"gatechk: {len(files)} checkpoint file(s) (reuse check unavailable: {exc})"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only session freshness pulse (tips, newest PROGRESS "
                    "entry, agenda rank-1, deferred items, gate checkpoints)")
    parser.add_argument("--fast", action="store_true",
                        help="skip the checkpoint-reuse key computation")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    print("== apex session pulse ==")
    for line in tip_lines():
        print(line)
    print(progress_line())
    print(agenda_line())
    for line in deferred_lines():
        print(line)
    print(gatechk_line(fast=args.fast))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
