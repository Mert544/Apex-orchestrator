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
    # The byte-identical decompose harness (test_transforms_byte_identical_refactor)
    # loads these two sub-package transforms standalone from /tmp/charorig. Their
    # source uses a relative ``from ..result import`` that cannot resolve when loaded
    # outside the package, so the staged snapshot rewrites it to the absolute form
    # below (a no-op for the top-level snapshots above). The pre-refactor reference
    # is the parent of 1820170, the commit that decomposed both into pure helpers.
    ("app/execution/semantic/transforms/redundant_lambda.py", "1820170",
     "/tmp/charorig/redundant_lambda_orig.py"),
    ("app/execution/semantic/transforms/mutable_defaults.py", "1820170",
     "/tmp/charorig/mutable_defaults_orig.py"),
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
                # A sub-package snapshot loaded standalone (spec_from_file_location)
                # cannot resolve a relative import; rewrite the one ``from ..result``
                # to its absolute form. No-op for the top-level snapshots.
                text = src.stdout.replace(
                    "from ..result import",
                    "from app.execution.semantic.result import",
                )
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                Path(dest).write_text(text, encoding="utf-8")
        except Exception:
            pass  # the harness itself skips/handles a still-missing snapshot


def pytest_configure(config):  # noqa: ARG001  (pytest hook signature)
    # Runs before test modules are collected, so module-level snapshot loads find
    # their file.
    _stage_refactor_snapshots()
