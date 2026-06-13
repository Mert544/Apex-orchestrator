"""External benchmark — Apex graded against real, pinned codebases.

The missing piece of the trust story is *calibration*: a self-assigned A+
means little until you can see how the same rubric grades codebases the
world already knows. ``apex bench`` clones each repo in a manifest at a
**pinned ref**, runs the exact same grade/profile machinery `apex grade`
uses, and renders one comparable table — reproducible by anyone, from the
same manifest, at the same SHAs.

This is deliberately NOT a precision/recall benchmark: real repos carry no
ground-truth labels, and we refuse to invent them (see
``docs/comparison.md``). What it honestly provides:
  - the grade *distribution* across known projects (calibration context);
  - a findings inventory per repo (what the detectors say, at what size);
  - full reproducibility (pinned SHAs, deterministic engine).

Manifest entries are either remote (``{"name", "url", "ref"}``) or local
(``{"name", "path"}``) — local entries keep the test suite offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any


@dataclass
class BenchEntry:
    name: str
    url: str = ""
    ref: str = ""
    path: str = ""


@dataclass
class BenchResult:
    name: str
    ref: str = ""
    score: int = 0
    letter: str = ""
    components: dict[str, int] = field(default_factory=dict)  # name -> points lost
    details: dict[str, str] = field(default_factory=dict)     # name -> detail line
    total_files: int = 0
    duration_seconds: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "ref": self.ref, "score": self.score,
            "letter": self.letter, "components": self.components,
            "details": self.details, "total_files": self.total_files,
            "duration_seconds": self.duration_seconds, "error": self.error,
        }


def load_manifest(path: str | Path) -> list[BenchEntry]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [BenchEntry(**entry) for entry in data.get("repos", [])]


def _checkout(entry: BenchEntry, workdir: Path) -> tuple[Path, str]:
    """Materialize the entry's code; returns (project_root, resolved_ref)."""
    if entry.path:
        return Path(entry.path), entry.ref or "local"
    dest = workdir / entry.name
    dest.mkdir(parents=True, exist_ok=True)

    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=dest, capture_output=True,
                              text=True, timeout=300)

    _git("init", "-q")
    _git("remote", "add", "origin", entry.url)
    ref = entry.ref or "HEAD"
    fetched = _git("fetch", "--depth", "1", "-q", "origin", ref)
    if fetched.returncode != 0:
        raise RuntimeError(f"fetch failed for {entry.name}@{ref}: {fetched.stderr.strip()[:200]}")
    _git("checkout", "-q", "FETCH_HEAD")
    head = _git("rev-parse", "HEAD")
    return dest, head.stdout.strip()


def bench_entry(entry: BenchEntry, workdir: Path) -> BenchResult:
    """Grade one manifest entry with the exact machinery `apex grade` uses."""
    from app.engine.health_score import grade
    from app.tools.project_profile import ProjectProfiler

    started = time.monotonic()
    try:
        root, ref = _checkout(entry, workdir)
        if not root.exists():
            raise RuntimeError(f"path not found: {root}")
        h = grade(root)
        profile = ProjectProfiler(str(root)).profile()
        return BenchResult(
            name=entry.name, ref=ref, score=h.score, letter=h.letter,
            components={c.name: c.points_lost for c in h.components},
            details={c.name: c.detail for c in h.components},
            total_files=profile.total_files,
            duration_seconds=round(time.monotonic() - started, 2),
        )
    except Exception as exc:  # one broken entry must not sink the bench
        return BenchResult(name=entry.name, ref=entry.ref, error=str(exc)[:300],
                           duration_seconds=round(time.monotonic() - started, 2))


def run_bench(entries: list[BenchEntry], keep: bool = False,
              workdir: str | Path | None = None) -> list[BenchResult]:
    work = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="apex-bench-"))
    work.mkdir(parents=True, exist_ok=True)
    try:
        return [bench_entry(e, work) for e in entries]
    finally:
        if not keep and workdir is None:
            shutil.rmtree(work, ignore_errors=True)


def render_bench_markdown(results: list[BenchResult], manifest_path: str = "") -> str:
    lines = ["# Apex external benchmark — the same rubric on known codebases", ""]
    if manifest_path:
        lines.append(f"_Reproduce: `apex bench --manifest {manifest_path}` "
                     "(pinned refs; deterministic engine)._")
    lines += [
        "",
        "| Repo | Ref | Files | Grade | Security | Architecture | Testing | Code debt | Correctness |",
        "|---|---|---:|---|---|---|---|---|---|",
    ]
    for r in results:
        if r.error:
            lines.append(f"| {r.name} | `{(r.ref or '?')[:8]}` | — | ⚠️ error | "
                         f"{r.error} | | | | |")
            continue
        c = r.components
        lines.append(
            f"| {r.name} | `{r.ref[:8]}` | {r.total_files} | "
            f"**{r.letter} ({r.score})** | −{c.get('Security', 0)} | "
            f"−{c.get('Architecture', 0)} | −{c.get('Testing', 0)} | "
            f"−{c.get('Code debt', 0)} | −{c.get('Correctness', 0)} |"
        )
    lines += [
        "",
        "_Columns show points lost per component (0 = clean under this rubric)._",
        "_No precision/recall is claimed: real repos carry no ground-truth labels._",
        "",
    ]
    return "\n".join(lines)
