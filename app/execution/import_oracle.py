"""Import oracle — prove a generated ``__init__.py`` actually re-exports.

The self-verification that makes ``wire-exports`` trustworthy even on a project
with NO test suite. Given a candidate ``__init__.py`` for a package, this writes
it in place, imports the package in a CLEAN subprocess, and asserts that every
expected export resolves as an attribute of the package. The original file is
always restored (``try``/``finally``), so the oracle is side-effect-free on
success or failure — it never lands the candidate itself; that is the apply
layer's job, gated by this check.

A subprocess (rather than ``importlib`` in-process) keeps it deterministic and
isolated: a fresh interpreter with the project root on ``sys.path`` and bytecode
writing off, no cached modules from the host process, no import-state leakage. If
the subprocess can't run, the import fails, or any name is missing, the oracle
returns ``False`` and the objective refuses. Stdlib-only, no clock, no random.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

__all__ = ["exports_resolve", "package_dotted_name"]

# A tiny, fixed probe program: import the package, report which expected names
# resolve as attributes. Read via argv: project root, dotted package, names JSON.
_PROBE = r"""
import importlib, json, sys
root, dotted, names_json = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
names = json.loads(names_json)
try:
    mod = importlib.import_module(dotted)
except BaseException as exc:  # noqa: BLE001 - any import failure means refuse
    print(json.dumps({"ok": False, "error": repr(exc)}))
    sys.exit(0)
missing = [n for n in names if not hasattr(mod, n)]
print(json.dumps({"ok": not missing, "missing": missing}))
"""


def package_dotted_name(init_rel: str) -> str:
    """Dotted import name for the package owning ``init_rel``.

    ``pkg/__init__.py`` -> ``pkg``; ``a/b/__init__.py`` -> ``a.b``. The project
    root is placed on ``sys.path`` by the probe, so the dotted name is rooted at
    the project, exactly how a real caller would import it."""
    parent = Path(init_rel).parent
    return ".".join(parent.parts)


def exports_resolve(
    project_root: str | Path, init_rel: str, candidate_source: str,
    expected: list[str],
) -> bool:
    """True iff importing the package with ``candidate_source`` as its
    ``__init__.py`` makes EVERY name in ``expected`` resolve as an attribute.

    Writes ``candidate_source`` to the package's ``__init__.py``, imports the
    package in a clean subprocess, and restores the original bytes afterwards
    (whether the import succeeded, failed, or raised). Returns ``False`` on any
    subprocess error, import failure, or missing export — the caller refuses. An
    empty ``expected`` list is vacuously satisfiable but pointless, so it returns
    ``False`` (nothing to prove → nothing to land)."""
    if not expected:
        return False
    root = Path(project_root)
    init_path = root / init_rel
    try:
        original = init_path.read_text(encoding="utf-8")
        had_file = True
    except OSError:
        original, had_file = "", init_path.exists()

    dotted = package_dotted_name(init_rel)
    try:
        init_path.parent.mkdir(parents=True, exist_ok=True)
        init_path.write_text(candidate_source, encoding="utf-8")
        return _run_probe(root, dotted, expected)
    finally:
        if had_file:
            init_path.write_text(original, encoding="utf-8")
        else:
            try:
                init_path.unlink()
            except OSError:
                pass


def _run_probe(root: Path, dotted: str, expected: list[str]) -> bool:
    """Run the import probe in a clean subprocess; True iff every name resolved."""
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE, str(root), dotted, json.dumps(expected)],
            cwd=str(root), capture_output=True, text=True, env=env, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False
    return bool(result.get("ok"))
