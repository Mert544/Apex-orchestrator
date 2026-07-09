"""Tests for scripts/verify.py's ``--impacted --nodes`` wiring: the opt-in
node-narrowing banner and pytest argv, plus the byte-identical contract for
plain ``--impacted`` (no ``--nodes``) after the flag was added — node
narrowing must never leak into the default fast-iteration path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(script_name: str):
    path = ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(script_name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(script_name[:-3], mod)
    spec.loader.exec_module(mod)
    return mod


def test_verify_nodes_flag_banner(monkeypatch, capsys):
    v = _load("verify.py")
    monkeypatch.setattr(v, "default_impacted_base", lambda: "main")
    monkeypatch.setattr(v, "git_changed_files",
                        lambda base: ["app/engine/node_impact.py"])
    monkeypatch.setattr(v, "impacted_selection",
                        lambda changed, root=v.ROOT: ([], []))

    import app.engine.node_impact as node_impact_mod
    import app.engine.test_impact as test_impact_mod

    monkeypatch.setattr(
        test_impact_mod, "impacted_test_files",
        lambda root, changed: ["tests/test_x.py", "tests/test_y.py"])
    monkeypatch.setattr(
        node_impact_mod, "impacted_test_nodes",
        lambda root, changed: (["tests/test_x.py::test_a"], ["tests/test_y.py"]))

    calls: list[list[str]] = []

    def fake_run_chunk(files, extra):
        calls.append([str(f) for f in files])
        return 0

    monkeypatch.setattr(v, "run_chunk", fake_run_chunk)

    args = v._build_parser().parse_args(["--impacted", "--nodes"])
    results: list[tuple[str, int]] = []
    v._run_impacted(args, results)

    out = capsys.readouterr().out
    assert "node-narrowed 1/2 impacted files (fail-closed)" in out
    flat = [f for chunk in calls for f in chunk]
    assert "tests/test_x.py::test_a" in flat
    assert "tests/test_y.py" in flat
    assert [code for _, code in results] == [0] * len(results)


def test_verify_without_nodes_flag_byte_identical(monkeypatch, capsys):
    v = _load("verify.py")
    monkeypatch.setattr(v, "default_impacted_base", lambda: "main")
    monkeypatch.setattr(v, "git_changed_files",
                        lambda base: ["app/engine/node_impact.py"])
    monkeypatch.setattr(
        v, "impacted_selection",
        lambda changed, root=v.ROOT: ([v.ROOT / "tests" / "test_x.py"], []))

    calls: list[list[str]] = []

    def fake_run_chunk(files, extra):
        calls.append([str(f) for f in files])
        return 0

    monkeypatch.setattr(v, "run_chunk", fake_run_chunk)

    args = v._build_parser().parse_args(["--impacted"])
    results: list[tuple[str, int]] = []
    v._run_impacted(args, results)
    out = capsys.readouterr().out

    # No node-narrowing disclosure — the default path never touches
    # app.engine.node_impact.
    assert "node-narrowed" not in out
    assert "1 test file(s) by import reachability" in out
    assert calls == [[str(v.ROOT / "tests" / "test_x.py")]]
