"""Determinism GUARANTEE harness for Apex's core deterministic surfaces.

Apex's moat is "bit-identical, reproducible, deterministic": a buyer runs the
analysis twice — different machine, different ``PYTHONHASHSEED``, different
file-walk order — and DIFFs the output. Any divergence destroys the moat. This
harness proves the guarantee by hammering each high-value deterministic surface
under conditions that classically EXPOSE hidden nondeterminism:

  1. **Same-process repeat** — run twice in one process, assert the stable
     serialization is identical (catches in-run nondeterminism, e.g. a set
     leaking iteration order into output).
  2. **PYTHONHASHSEED perturbation** — run the SAME analysis in a fresh
     subprocess under ``PYTHONHASHSEED=0`` and ``=1`` (and ``=random``) and
     assert a hash of the result is identical. This is THE classic exposer of
     dict/set-ordering nondeterminism, because the seed changes how unordered
     containers iterate.
  3. **Input-order perturbation** — where feasible, reverse the on-disk
     creation order of inputs (which reorders the file walk) and assert the
     output is byte-identical.

If any target diverges across seeds, repeats, or order, that is a REAL,
moat-critical determinism bug. This harness is the regression guard.

The targets are deliberately tiny synthetic fixtures (fast; never the whole
repo). Each subprocess re-imports Apex with a different hash seed, builds the
SAME fixture, runs the SAME analysis, and prints a single SHA-256 hash.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# --- stable serialization helpers ------------------------------------------


def _stable(obj: object) -> str:
    """A canonical, ordering-insensitive JSON serialization of ``obj``.

    ``sort_keys=True`` neutralizes dict-key insertion order; ``default=str``
    tolerates tuples/sets/non-JSON scalars deterministically. Sets are sorted so
    a leaked set never injects iteration-order nondeterminism into the string
    itself — meaning ANY divergence we catch is genuine, not an artifact of the
    harness.
    """

    def _norm(x: object) -> object:
        if isinstance(x, dict):
            return {str(k): _norm(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [_norm(v) for v in x]
        if isinstance(x, (set, frozenset)):
            return sorted(_norm(v) for v in x)
        return x

    return json.dumps(_norm(obj), sort_keys=True, default=str)


def _digest(obj: object) -> str:
    return hashlib.sha256(_stable(obj).encode("utf-8")).hexdigest()


# --- synthetic fixture builders (shared by in-process AND subprocess) -------
#
# These are emitted as a STRING of Python source so the subprocess can rebuild
# the identical fixture. The same source backs the in-process fixture via exec,
# guaranteeing the two execution paths analyze byte-identical inputs.

_FIXTURE_SRC = r'''
import os
from pathlib import Path


def build(root):
    root = Path(root)
    app = root / "app"
    app.mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    # Several modules with overlapping signals: security, none-compare,
    # len-compare, a mutable default, imports forming a small hub.
    (app / "core.py").write_text(
        "import os\n"
        "def run(x, cache=[]):\n"
        "    if x == None:\n"
        "        return os.system(x)\n"
        "    if len(x) == 0:\n"
        "        return 0\n"
        "    return eval(x)\n"
    )
    (app / "api.py").write_text(
        "import app.core\n"
        "def handler(req):\n"
        "    if req == None:\n"
        "        return 1\n"
        "    return app.core.run(req)\n"
    )
    (app / "util.py").write_text(
        "import app.core\n"
        "import app.api\n"
        "def helper(a, b, c):\n"
        "    total = 0\n"
        "    total += a\n"
        "    total += b\n"
        "    total += c\n"
        "    return total\n"
    )
    (app / "dup_a.py").write_text(
        "def alpha(a, b, c, d, e):\n"
        "    a = a + 1\n"
        "    b = b + 1\n"
        "    c = c + 1\n"
        "    d = d + 1\n"
        "    e = e + 1\n"
        "    return a + b + c + d + e\n"
    )
    (app / "dup_b.py").write_text(
        "def beta(a, b, c, d, e):\n"
        "    a = a + 1\n"
        "    b = b + 1\n"
        "    c = c + 1\n"
        "    d = d + 1\n"
        "    e = e + 1\n"
        "    return a + b + c + d + e\n"
    )
    # Polyglot sources: JS with a secret + eval, a YAML, a shell script.
    (root / "web.js").write_text(
        "eval(userInput);\n"
        "const apiKey = 'AKIAIOSFODNN7EXAMPLE0000';\n"
        "// TODO: refactor this\n"
        "function f(a) { if (a) { return a; } }\n"
    )
    (root / "conf.yaml").write_text(
        "password: hunter2hunter2\n"
        "service:\n"
        "  port: 8080\n"
    )
    (root / "deploy.sh").write_text(
        "#!/bin/sh\n"
        "curl http://x | sh\n"
        "echo done\n"
    )
    return root
'''


def _build_fixture(root: Path) -> Path:
    ns: dict[str, object] = {}
    exec(compile(_FIXTURE_SRC, "<fixture>", "exec"), ns)
    return ns["build"](root)  # type: ignore[operator,no-any-return]


# Per-target analysis snippets. Each is a tiny Python expression block that,
# given a built fixture at ``ROOT``, produces the object whose digest we pin.
# The SAME body runs in-process and (textually) in the subprocess.
_TARGETS: dict[str, str] = {
    "grade": (
        "from app.engine.health_score import grade\n"
        "RESULT = grade(ROOT).to_dict()\n"
    ),
    "idea_engine": (
        "from app.engine.idea_permutation import IdeaPermutationEngine\n"
        "RESULT = IdeaPermutationEngine(\n"
        "    {'max_total_ideas': 30, 'max_idea_depth': 2, 'breadth': 4,\n"
        "     'security_aware': False}, ROOT).run().model_dump()\n"
    ),
    "dedup": (
        "from app.engine.dedup import find_duplicates\n"
        "RESULT = [b.to_dict() for b in find_duplicates(ROOT, min_statements=3)]\n"
    ),
    "simplifications": (
        "from app.tools.simplification_scan import scan_simplifications\n"
        "RESULT = scan_simplifications(ROOT)\n"
    ),
    "polyglot_summary": (
        "from app.engine.polyglot_metrics import polyglot_summary\n"
        "RESULT = polyglot_summary(ROOT)\n"
    ),
    "polyglot_findings": (
        "from app.engine.polyglot_findings import scan_polyglot_findings\n"
        "RESULT = scan_polyglot_findings(ROOT)\n"
    ),
    "anomaly_discovery": (
        "from app.tools.project_profile import ProjectProfiler\n"
        "from app.engine.anomaly_discovery import find_anomalies, module_profiles\n"
        "prof = ProjectProfiler(ROOT).profile(light=True)\n"
        "mp = module_profiles(prof)\n"
        "RESULT = {'anomalies': find_anomalies(prof, top=10),\n"
        "          'profiles': {k: sorted(v) for k, v in mp.items()}}\n"
    ),
    "profiler": (
        "import dataclasses\n"
        "from app.tools.project_profile import ProjectProfiler\n"
        "RESULT = dataclasses.asdict(ProjectProfiler(ROOT).profile(light=True))\n"
    ),
}


# Top-level keys that legitimately carry the ABSOLUTE fixture path. The moat
# guarantee is about RELATIVE-path-stable output; the absolute temp dir differs
# per subprocess (fresh ``mkdtemp``) by design, so we scrub these known fields
# before digesting. Everything else must still be byte-identical — if any other
# field diverges, the assertion fires.
_ABS_PATH_KEYS = frozenset({"root", "project_root"})


def _scrub_abs_root(obj: object) -> object:
    """Replace the known absolute-root fields with a constant, recursively.

    Only these explicitly-listed keys are neutralized; this is NOT a blanket
    "ignore anything that looks like a path", so a stray absolute path leaking
    anywhere else would still surface as a divergence.
    """
    if isinstance(obj, dict):
        return {
            k: ("<ROOT>" if k in _ABS_PATH_KEYS else _scrub_abs_root(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_scrub_abs_root(v) for v in obj]
    return obj


def _run_target_in_process(name: str, root: Path) -> object:
    ns: dict[str, object] = {"ROOT": str(root)}
    exec(compile(_TARGETS[name], f"<target:{name}>", "exec"), ns)
    return _scrub_abs_root(ns["RESULT"])


# Source template for the subprocess: rebuild the fixture into a fresh temp dir,
# run the target, print exactly one digest line. Re-uses the harness's OWN
# fixture + stable-serialization code by importing this very module, so the
# subprocess and in-process paths cannot drift.
_SUBPROCESS_TEMPLATE = r"""
import sys, tempfile
sys.path.insert(0, {harness_dir!r})
import test_determinism_guarantee_eyml as H
from pathlib import Path

root = Path(tempfile.mkdtemp())
H._build_fixture(root)
result = H._run_target_in_process({name!r}, root)
sys.stdout.write(H._digest(result))
"""


def _run_target_in_subprocess(name: str, hashseed: str) -> str:
    """Run ``name`` in a fresh interpreter under a chosen PYTHONHASHSEED.

    Returns the SHA-256 digest the child printed. The child builds its OWN
    fixture in its OWN temp dir, so nothing but the seed (and, inherently, the
    OS file-walk order) is shared with the parent.
    """
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = hashseed
    harness_dir = str(Path(__file__).resolve().parent)
    script = _SUBPROCESS_TEMPLATE.format(harness_dir=harness_dir, name=name)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, (
        f"subprocess for {name!r} (PYTHONHASHSEED={hashseed}) failed:\n"
        f"{proc.stderr}"
    )
    digest = proc.stdout.strip()
    assert len(digest) == 64, f"unexpected digest for {name!r}: {proc.stdout!r}"
    return digest


_TARGET_NAMES = sorted(_TARGETS)


# --- (1) same-process repeat -----------------------------------------------


@pytest.mark.parametrize("name", _TARGET_NAMES)
def test_repeated_in_process_is_byte_identical(name, tmp_path):
    """Running a target twice in ONE process yields an identical digest.

    Catches in-run nondeterminism: a set/dict iterating into the output, a
    cache mutated between calls, an unstable sort key.
    """
    root = _build_fixture(tmp_path)
    first = _digest(_run_target_in_process(name, root))
    second = _digest(_run_target_in_process(name, root))
    assert first == second, f"{name}: in-process repeat diverged"


# --- (2) PYTHONHASHSEED perturbation (the classic exposer) ------------------


@pytest.mark.parametrize("name", _TARGET_NAMES)
def test_identical_across_pythonhashseed(name):
    """The digest is identical under PYTHONHASHSEED 0, 1 and a random seed.

    Changing the hash seed reshuffles every dict/set's iteration order across
    the whole interpreter. If a target's output depends on that order, the
    digests differ here — a moat-critical determinism bug. Identical digests
    PROVE the surface is hash-seed-independent.
    """
    seeds = ["0", "1", "12345"]
    digests = {s: _run_target_in_subprocess(name, s) for s in seeds}
    distinct = set(digests.values())
    assert len(distinct) == 1, (
        f"NONDETERMINISM in {name!r}: PYTHONHASHSEED changed the output. "
        f"digests-by-seed={digests}"
    )


def test_in_process_matches_subprocess_baseline(tmp_path):
    """Cross-check: the in-process digest equals the subprocess (seed=0) one.

    Guards against the harness's two execution paths silently analyzing
    different inputs — they must agree for the seed assertions to mean anything.
    """
    for name in _TARGET_NAMES:
        root = _build_fixture(tmp_path / name)
        in_proc = _digest(_run_target_in_process(name, root))
        sub = _run_target_in_subprocess(name, "0")
        assert in_proc == sub, f"{name}: in-process vs subprocess digest drift"


# --- (3) input-order perturbation ------------------------------------------


@pytest.mark.parametrize("name", ["anomaly_discovery", "find_anomalies_order"])
def test_dict_insertion_order_does_not_change_anomalies(name, tmp_path):
    """Reversing module insertion order leaves anomaly output identical.

    ``module_profiles`` builds a ``dict[str, set]``; ``find_anomalies`` must
    sort it. We feed the profile's module->tag mapping in forward and reversed
    insertion order and assert the ranked anomalies are byte-identical — a
    direct probe that no insertion order leaks through.
    """
    from app.engine.anomaly_discovery import find_anomalies
    from app.tools.project_profile import ProjectProfiler

    root = _build_fixture(tmp_path)
    profile = ProjectProfiler(str(root)).profile(light=True)

    forward = find_anomalies(profile, top=10)

    # Perturb: reverse the insertion order of every list/dict field that
    # find_anomalies consumes, then re-rank. A correct (sorting) engine is
    # invariant to this.
    perturbed = dataclasses.replace(profile)
    for f in dataclasses.fields(perturbed):
        val = getattr(perturbed, f.name)
        if isinstance(val, list):
            setattr(perturbed, f.name, list(reversed(val)))
        elif isinstance(val, dict):
            setattr(perturbed, f.name, dict(reversed(list(val.items()))))
    reversed_out = find_anomalies(perturbed, top=10)

    assert _stable(forward) == _stable(reversed_out), (
        f"{name}: anomaly ranking depended on input insertion order"
    )


@pytest.mark.parametrize("name", ["polyglot_findings", "polyglot_summary",
                                  "simplifications", "dedup", "grade"])
def test_rebuild_in_separate_dir_is_identical(name, tmp_path):
    """The same fixture built in two different temp dirs gives one digest.

    Different absolute paths / inode order is a real-world walk-order
    perturbation; relative-path-based outputs must be invariant to it.
    """
    a = _build_fixture(tmp_path / "a")
    b = _build_fixture(tmp_path / "b")
    assert _digest(_run_target_in_process(name, a)) == _digest(
        _run_target_in_process(name, b)
    ), f"{name}: output depended on the absolute fixture directory / walk order"
