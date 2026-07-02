"""Doctest oracle — prove a generated ``USAGE.md``'s examples actually run.

The self-verification that makes ``generate-usage-doc`` trustworthy even on a
project with NO test suite. Each public symbol's ``>>>`` examples (copied verbatim
from its docstring into the doc) are executed against the imported package in a
CLEAN subprocess. The oracle reports, per symbol, whether ITS examples ran green
— so the renderer keeps only proven examples and OMITS any that fail (an honest
under-claim, never a fake-green). A symbol with no examples trivially "passes"
(there is nothing to run).

A subprocess (rather than ``doctest`` in-process) keeps it deterministic and
isolated: a fresh interpreter with the project root on ``sys.path``, a PINNED
``PYTHONHASHSEED`` (so a ``set``/``dict``-repr expected output is stable instead
of hash-seed-dependent), bytecode writing off, no cached modules from the host
process, no state leakage. The package is imported once; each symbol's examples
are run in a namespace seeded with the package module, exactly how a reader
following the doc would run them. Stdlib-only, no clock, no random.
"""

from __future__ import annotations

import json
import os

from app.execution.target_env import inherited_pythonpath
from pathlib import Path
import subprocess
import sys

from app.execution.import_oracle import package_dotted_name

__all__ = ["verify_examples", "examples_run_green"]

# The probe: import the package, then run each symbol's doctest examples in a
# namespace that has the package module bound by BOTH its dotted name's last
# component and its symbols. Documented symbols can live in a SUBMODULE that the
# package's ``__init__`` does not re-export, so each owning submodule (passed as a
# JSON list of stems) is imported too and its public symbols bound UNDER the
# package's own attributes — the package still wins on a name it re-exports, so a
# re-exporting layout resolves exactly as before, while a submodule-only layout
# now resolves instead of dropping every example. Only symbols that genuinely
# exist are bound (a failed submodule import is skipped); a still-unresolvable
# example is honestly dropped. Report the set of symbol names whose examples all
# passed. Input via argv: project root, dotted package, JSON {name: [examples]},
# and JSON [submodule stems].
_PROBE = r"""
import doctest, importlib, json, sys
root, dotted, payload_json = sys.argv[1], sys.argv[2], sys.argv[3]
submods_json = sys.argv[4] if len(sys.argv) > 4 else "[]"
sys.path.insert(0, root)
payload = json.loads(payload_json)
submods = json.loads(submods_json)
try:
    mod = importlib.import_module(dotted)
except BaseException as exc:  # noqa: BLE001 - any import failure means refuse all
    print(json.dumps({"ok": False, "passed": []}))
    sys.exit(0)


def _bind_public(ns, obj):
    for attr in dir(obj):
        if not attr.startswith("_"):
            ns[attr] = getattr(obj, attr)


def _namespace():
    ns = {"__name__": "__usage_doc__"}
    # Submodule symbols first, then the package's own — the package wins so a
    # re-exported name resolves to the package attribute, byte-identical to before.
    for stem in submods:
        try:
            sub = importlib.import_module(dotted + "." + stem)
        except BaseException:  # noqa: BLE001 - skip a submodule that won't import
            continue
        _bind_public(ns, sub)
    leaf = dotted.split(".")[-1]
    ns[leaf] = mod
    _bind_public(ns, mod)
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


def _package_submodules(project_root: Path, init_rel: str) -> list[str]:
    """The package's own non-``__init__`` module stems (sorted, deterministic) —
    the submodules that may DEFINE a documented symbol whose example is being
    verified. Reuses the doc collector's own module discovery so the probe binds
    exactly the modules the symbols were collected from. ``[]`` when the package
    directory cannot be read (the probe then binds only the package's own attrs,
    its prior behavior)."""
    from app.execution.usage_doc import _module_stems

    package_dir = project_root / Path(init_rel).parent
    try:
        return _module_stems(package_dir)
    except OSError:
        return []


def examples_run_green(
    project_root: str | Path, init_rel: str,
    examples_by_symbol: dict[str, list[str]],
) -> set[str]:
    """The set of symbol NAMES whose doctest examples all run green.

    Imports the package owning ``init_rel`` in a clean subprocess and runs each
    symbol's ``>>>`` examples in a namespace seeded with the package's public
    attributes AND the public symbols of its own submodules (so an example that
    calls a symbol defined in a submodule the ``__init__`` does not re-export still
    resolves; the package's own attributes win on any re-exported name, so a
    re-exporting layout is unaffected). A symbol whose examples raise, fail a
    comparison, or cannot be parsed is left OUT of the returned set (the renderer
    then omits its examples).
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
    submodules = _package_submodules(root, init_rel)
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        # Pin the inner interpreter's hash seed so set/dict reprs are stable: a
        # doctest whose expected output is a `set` literal (e.g. ``{'a', 'b'}``)
        # otherwise passes or fails depending on the parent's RANDOMIZED seed,
        # which would make the KEPT examples — and the landed ``USAGE.md`` — vary
        # run-to-run. A fixed seed keeps the proven artifact byte-deterministic.
        "PYTHONHASHSEED": "0",
        "PYTHONPATH": str(root) + os.pathsep + inherited_pythonpath(),
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE, str(root), dotted,
             json.dumps(payload), json.dumps(submodules)],
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
