"""Doctest oracle — prove a generated ``USAGE.md``'s examples actually run.

The self-verification that makes ``generate-usage-doc`` trustworthy even on a
project with NO test suite. Each public symbol's ``>>>`` examples (copied verbatim
from its docstring into the doc) are executed against the imported package in a
CLEAN subprocess. The oracle reports, per symbol, whether ITS examples ran green
— so the renderer keeps only proven examples and OMITS any that fail (an honest
under-claim, never a fake-green). A symbol with no examples trivially "passes"
(there is nothing to run).

A subprocess (rather than ``doctest`` in-process) keeps it deterministic and
isolated: a fresh interpreter with the project root on ``sys.path`` and bytecode
writing off, no cached modules from the host process, no state leakage. The
package is imported once; each symbol's examples are run in a namespace seeded
with the package module, exactly how a reader following the doc would run them.
Stdlib-only, no clock, no random.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from app.execution.import_oracle import package_dotted_name

__all__ = ["verify_examples", "examples_run_green"]

# The probe: import the package, then run each symbol's doctest examples in a
# namespace that has the package module bound by BOTH its dotted name's last
# component and its symbols. Report the set of symbol names whose examples all
# passed. Input via argv: project root, dotted package, JSON {name: [examples]}.
_PROBE = r"""
import doctest, importlib, json, sys
root, dotted, payload_json = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
payload = json.loads(payload_json)
try:
    mod = importlib.import_module(dotted)
except BaseException as exc:  # noqa: BLE001 - any import failure means refuse all
    print(json.dumps({"ok": False, "passed": []}))
    sys.exit(0)


def _namespace():
    ns = {"__name__": "__usage_doc__"}
    leaf = dotted.split(".")[-1]
    ns[leaf] = mod
    for attr in dir(mod):
        if not attr.startswith("_"):
            ns[attr] = getattr(mod, attr)
    return ns


passed = []
parser = doctest.DocTestParser()
runner = doctest.DocTestRunner(verbose=False, optionflags=0)
for name, examples in payload.items():
    source = "\n".join(examples) + "\n"
    try:
        test = parser.get_doctest(source, _namespace(), name, None, 0)
    except ValueError:
        continue
    result = runner.run(test, clear_globs=True)
    if result.failed == 0 and result.attempted > 0:
        passed.append(name)
print(json.dumps({"ok": True, "passed": passed}))
"""


def examples_run_green(
    project_root: str | Path, init_rel: str,
    examples_by_symbol: dict[str, list[str]],
) -> set[str]:
    """The set of symbol NAMES whose doctest examples all run green.

    Imports the package owning ``init_rel`` in a clean subprocess and runs each
    symbol's ``>>>`` examples in a namespace seeded with the package's public
    attributes. A symbol whose examples raise, fail a comparison, or cannot be
    parsed is left OUT of the returned set (the renderer then omits its examples).
    Symbols with no examples are not passed in — they are trivially fine and the
    caller keeps them. Returns an empty set on any subprocess error or if the
    package fails to import — refuse rather than claim unproven examples."""
    payload = {name: ex for name, ex in examples_by_symbol.items() if ex}
    if not payload:
        return set()
    root = Path(project_root)
    dotted = package_dotted_name(init_rel)
    if not dotted:
        return set()
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE, str(root), dotted, json.dumps(payload)],
            cwd=str(root), capture_output=True, text=True, env=env, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if proc.returncode != 0:
        return set()
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return set()
    if not result.get("ok"):
        return set()
    return set(result.get("passed", []))


def verify_examples(
    project_root: str | Path, init_rel: str,
    examples_by_symbol: dict[str, list[str]],
) -> set[str]:
    """Alias of :func:`examples_run_green` — the verb the objective reads with."""
    return examples_run_green(project_root, init_rel, examples_by_symbol)
