"""External benchmark harness — offline tests via local manifest entries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.benchmarking.external import (
    BenchEntry,
    load_manifest,
    render_bench_markdown,
    run_bench,
)


def _fixture_repo(tmp_path: Path, name: str, risky: bool = False) -> Path:
    root = tmp_path / name
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    body = "def run(e):\n    return eval(e)\n" if risky else "def run(x):\n    return x + 1\n"
    (root / "app" / "m.py").write_text(body)
    (root / "tests" / "test_m.py").write_text(
        "from app.m import run\ndef test_r():\n    assert run" + ("" if risky else "(1) == 2") + "\n")
    return root


def test_bench_grades_local_entries_and_renders(tmp_path):
    clean = _fixture_repo(tmp_path, "clean")
    risky = _fixture_repo(tmp_path, "risky", risky=True)
    results = run_bench([
        BenchEntry(name="clean", path=str(clean)),
        BenchEntry(name="risky", path=str(risky)),
    ], workdir=tmp_path / "work")
    by_name = {r.name: r for r in results}
    assert by_name["clean"].letter and by_name["clean"].error == ""
    assert by_name["risky"].score < by_name["clean"].score  # eval() costs points
    assert by_name["risky"].components.get("Security", 0) > 0
    md = render_bench_markdown(results, manifest_path="docs/bench/manifest.json")
    assert "| clean |" in md and "| risky |" in md
    assert "No precision/recall is claimed" in md


def test_bench_survives_a_broken_entry(tmp_path):
    results = run_bench([BenchEntry(name="ghost", path=str(tmp_path / "missing"))],
                        workdir=tmp_path / "work")
    assert results[0].error
    assert "⚠️ error" in render_bench_markdown(results)


def test_manifest_roundtrip(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"repos": [
        {"name": "click", "url": "https://github.com/pallets/click", "ref": "abc123"},
        {"name": "local", "path": "/some/dir"},
    ]}))
    entries = load_manifest(manifest)
    assert entries[0].name == "click" and entries[0].ref == "abc123"
    assert entries[1].path == "/some/dir"


def test_cli_bench_local_manifest(tmp_path, capsys):
    from app.cli import cmd_bench

    repo = _fixture_repo(tmp_path, "fixture")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"repos": [{"name": "fixture", "path": str(repo)}]}))
    out_file = tmp_path / "bench.md"
    rc = cmd_bench(argparse.Namespace(manifest=str(manifest), out=str(out_file),
                                      keep=False, json=False))
    assert rc == 0
    assert "external benchmark" in capsys.readouterr().out
    assert "| fixture |" in out_file.read_text(encoding="utf-8")


def test_cli_bench_missing_manifest(tmp_path, capsys):
    from app.cli import cmd_bench

    rc = cmd_bench(argparse.Namespace(manifest=str(tmp_path / "nope.json"),
                                      out="", keep=False, json=False))
    assert rc == 1
    assert "manifest not found" in capsys.readouterr().out
