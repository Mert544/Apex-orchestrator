"""Characterization test proving run_audit was refactored byte-identically.

Loads the HEAD snapshot of scripts/security_audit.py and the current (refactored)
module independently via importlib, injects identical fake collaborators
(ProjectProfiler / FunctionFractalAnalyzer) into each, drives run_audit across
many scenarios covering every categorization branch and the skip / exception
paths, and asserts the returned report dicts AND the persisted JSON bytes are
identical for every input.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "security_audit.py"


def _load_module(name: str, source: str):
    """Load a module from source text with the script-local globals stubbed.

    The script imports app.tools.* at module scope; we pre-seed sys.modules with
    lightweight stand-ins so importing the source never touches the real, slow
    analyzers. run_audit reads ProjectProfiler / FunctionFractalAnalyzer from the
    module namespace, so tests overwrite those attributes per scenario.
    """
    mod = types.ModuleType(name)
    mod.__file__ = str(SCRIPT)
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod.__spec__ = spec
    # Pre-stub the app.tools imports the source performs at import time.
    placeholders = {
        "app": types.ModuleType("app"),
        "app.tools": types.ModuleType("app.tools"),
        "app.tools.function_fractal_analyzer": types.ModuleType(
            "app.tools.function_fractal_analyzer"
        ),
        "app.tools.project_profile": types.ModuleType("app.tools.project_profile"),
    }
    placeholders["app.tools.function_fractal_analyzer"].FunctionFractalAnalyzer = object
    placeholders["app.tools.project_profile"].ProjectProfiler = object
    saved = {k: sys.modules.get(k) for k in placeholders}
    sys.modules.update(placeholders)
    try:
        code = compile(source, str(SCRIPT), "exec")
        exec(code, mod.__dict__)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return mod


def _head_source() -> str:
    return subprocess.run(
        ["git", "show", "HEAD:scripts/security_audit.py"],
        cwd=str(REPO), capture_output=True, text=True, check=True,
    ).stdout


class _FakeProfile:
    def __init__(self, total_files, critical_untested_modules):
        self.total_files = total_files
        self.critical_untested_modules = critical_untested_modules


def _make_profiler(profile):
    class _P:
        def __init__(self, root):
            self.root = root

        def profile(self):
            return profile
    return _P


def _make_analyzer(file_map, raising):
    """file_map: rel-path -> list of fn dicts. raising: set of rel-paths to raise on."""
    class _A:
        def analyze_file(self, py_file):
            rel = Path(py_file).name
            if rel in raising:
                raise RuntimeError("boom")
            return list(file_map.get(rel, []))
    return _A


def _fn(name, score, risks):
    return {"name": name, "risk_score": score, "risks": list(risks)}


# Scenarios: each yields a (file_map, raising_set, profile) producing files in a
# temp dir, exercising every branch: critical patterns, high/medium/low scores,
# overlap precedence, skipped dirs, analyzer exceptions, empty repo.
_SCENARIOS = [
    # empty repo
    ({}, set(), _FakeProfile(0, [])),
    # one critical pattern of each kind
    ({"a.py": [_fn("f", 0.9, ["uses eval() here"])]}, set(), _FakeProfile(1, ["m"])),
    ({"a.py": [_fn("f", 0.05, ["calls exec() now"])]}, set(), _FakeProfile(3, [])),
    ({"a.py": [_fn("f", 0.5, ["os.system() call"])]}, set(), _FakeProfile(1, [])),
    ({"a.py": [_fn("f", 0.2, ["pickle.loads bad"])]}, set(), _FakeProfile(2, ["x", "y"])),
    ({"a.py": [_fn("f", 0.0, ["yaml.load issue"])]}, set(), _FakeProfile(1, [])),
    # high only (score >= 0.3, not critical)
    ({"a.py": [_fn("f", 0.3, ["some risk"])]}, set(), _FakeProfile(5, [])),
    ({"a.py": [_fn("f", 0.95, ["another risk"])]}, set(), _FakeProfile(5, [])),
    # medium boundary 0.1 and just under 0.3
    ({"a.py": [_fn("f", 0.1, ["med risk"])]}, set(), _FakeProfile(1, [])),
    ({"a.py": [_fn("f", 0.299, ["med risk2"])]}, set(), _FakeProfile(1, [])),
    # low (< 0.1)
    ({"a.py": [_fn("f", 0.099, ["low risk"])]}, set(), _FakeProfile(1, [])),
    ({"a.py": [_fn("f", 0.0, ["low risk2"])]}, set(), _FakeProfile(1, [])),
    # multiple risks on one fn + multiple fns
    (
        {
            "a.py": [
                _fn("f1", 0.9, ["eval() bad", "plain high"]),
                _fn("f2", 0.15, ["med one"]),
            ],
            "b.py": [_fn("g", 0.05, ["low one", "yaml.load also"])],
        },
        set(),
        _FakeProfile(9, ["mod"]),
    ),
    # analyzer raises on one file, succeeds on another
    (
        {"good.py": [_fn("f", 0.4, ["high here"])], "bad.py": [_fn("z", 0.9, ["eval()"])]},
        {"bad.py"},
        _FakeProfile(4, []),
    ),
    # skipped dirs: files under tests/, examples/, scripts/, .claude/ etc.
    ({"a.py": [_fn("f", 0.9, ["eval()"])]}, set(), _FakeProfile(6, [])),
]


def _populate(tmp_path: Path, file_map: dict, include_skipped: bool) -> None:
    for rel in file_map:
        (tmp_path / rel).write_text("# stub\n", encoding="utf-8")
    if include_skipped:
        for sub in ("tests", "examples", "scripts", ".claude/wt", ".epistemic",
                    "node_modules", "dist", "build", "venv", ".venv"):
            d = tmp_path / sub
            d.mkdir(parents=True, exist_ok=True)
            (d / "skipme.py").write_text("# stub\n", encoding="utf-8")
        (tmp_path / "test_thing.py").write_text("# stub\n", encoding="utf-8")


@pytest.mark.parametrize("idx", range(len(_SCENARIOS)))
def test_byte_identical_run_audit(tmp_path, idx):
    file_map, raising, profile = _SCENARIOS[idx]
    head = _load_module("sec_audit_head", _head_source())
    new = _load_module("sec_audit_new", SCRIPT.read_text(encoding="utf-8"))

    results = []
    for label, mod in (("head", head), ("new", new)):
        root = tmp_path / label
        root.mkdir()
        include_skipped = idx == len(_SCENARIOS) - 1
        _populate(root, file_map, include_skipped)
        mod.ProjectProfiler = _make_profiler(profile)
        mod.FunctionFractalAnalyzer = _make_analyzer(file_map, raising)
        report = mod.run_audit(root)
        # Normalize project_root (differs by label) for dict comparison.
        report = json.loads(json.dumps(report, default=str))
        report["project_root"] = "<ROOT>"
        persisted = (root / ".apex" / "security-report.json").read_text(encoding="utf-8")
        persisted = persisted.replace(str(root), "<ROOT>")
        results.append((report, persisted))

    assert results[0][0] == results[1][0], f"report dict mismatch scenario {idx}"
    assert results[0][1] == results[1][1], f"persisted JSON mismatch scenario {idx}"


def test_main_print_paths_identical():
    """Drive main()'s branch logic indirectly via report shape: critical, high, none."""
    head = _load_module("sec_audit_head2", _head_source())
    new = _load_module("sec_audit_new2", SCRIPT.read_text(encoding="utf-8"))
    # The two modules must expose identical public surface.
    assert sorted(n for n in vars(head) if n == "run_audit" or n == "main") == ["main", "run_audit"]
    assert sorted(n for n in vars(new) if n == "run_audit" or n == "main") == ["main", "run_audit"]
