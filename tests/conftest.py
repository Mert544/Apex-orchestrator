import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Byte-identical characterization harnesses load the PRE-REFACTOR snapshot of a
# module from a fixed /tmp path AT MODULE LEVEL. Those snapshots used to be staged
# by hand, so a fresh container (or a /tmp cleanup) made the whole module ERROR at
# collection. Regenerate any missing snapshot deterministically from the parent of
# the refactor commit that the harness characterizes — making the suite
# reproducible from a clean clone. (subject, refactor_commit, /tmp dest)
_SNAPSHOTS = [
    ("app/engine/idea_pareto.py", "a604d66", "/tmp/orig_pareto.py"),
    ("app/engine/idea_explain.py", "a604d66", "/tmp/orig_explain.py"),
    ("app/engine/debug_engine.py", "5e10cb2", "/tmp/debug_engine_original.py"),
    ("app/agents/skills/apex_debug_agent.py", "f537010",
     "/tmp/apex_debug_agent_ORIG.py"),
]


def _stage_refactor_snapshots() -> None:
    """Best-effort: write each missing pre-refactor snapshot from ``<commit>^``."""
    for subject, commit, dest in _SNAPSHOTS:
        if Path(dest).exists():
            continue
        try:
            src = subprocess.run(
                ["git", "show", f"{commit}^:{subject}"],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            if src.returncode == 0 and src.stdout:
                Path(dest).write_text(src.stdout, encoding="utf-8")
        except Exception:
            pass  # the harness itself skips/handles a still-missing snapshot


def pytest_configure(config):  # noqa: ARG001  (pytest hook signature)
    # Runs before test modules are collected, so module-level snapshot loads find
    # their file.
    _stage_refactor_snapshots()
