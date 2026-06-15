"""The `apex deps` subcommand: deterministic dependency audit at the CLI.

The contract under test:

  * a tmp project renders a human report and returns 0;
  * `--json` mirrors the findings as valid JSON with the five keys;
  * the subparser is registered and wired to `cmd_deps`;
  * `--strict` returns non-zero when a finding fires, 0 when clean;
  * a missing/empty target degrades to a clean report (rc 0), never crashes.

Deterministic, stdlib-only, LLM-free — builds a real small project over tmp.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import app.cli_reporting as cli_reporting
from app.cli_reporting import cmd_deps


def _ns(target: Path, *, json_out: bool = False, strict: bool = False) -> argparse.Namespace:
    return argparse.Namespace(target=str(target), json=json_out, strict=strict)


def _run(target: Path, *, json_out: bool = False, strict: bool = False) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_deps(_ns(target, json_out=json_out, strict=strict))
    return rc, buf.getvalue()


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _project(root: Path, deps: list[str], imports: list[str]) -> None:
    decl = "".join(f'  "{d}",\n' for d in deps)
    _write(
        root, "pyproject.toml",
        "[project]\n"
        'name = "demo"\n'
        'version = "0.1.0"\n'
        f"dependencies = [\n{decl}]\n",
    )
    _write(root, "app/__init__.py", "")
    _write(root, "app/core.py", "".join(f"import {m}\n" for m in imports))


def test_deps_returns_zero_and_prints_report(tmp_path):
    _project(tmp_path, ["requests>=2", "PyYAML>=6"], ["requests", "yaml"])
    rc, out = _run(tmp_path)

    assert rc == 0
    assert "Dependency audit" in out
    assert "heuristic" in out.lower()


def test_deps_json_is_valid_and_has_keys(tmp_path):
    _project(tmp_path, ["requests>=2", "rich>=13"], ["requests", "numpy"])
    rc, out = _run(tmp_path, json_out=True)

    assert rc == 0
    data = json.loads(out)
    assert set(data) == {
        "declared", "imported_third_party", "unused", "undeclared", "unpinned"
    }
    assert "rich" in data["unused"]
    assert "numpy" in data["undeclared"]
    # JSON mirrors the report's findings deterministically (sorted lists).
    for key in data:
        assert data[key] == sorted(data[key])


def test_deps_subparser_registered_and_wired():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    cli_reporting.register_parsers(sub)

    assert "deps" in sub.choices
    assert sub.choices["deps"].get_default("func") is cmd_deps


def test_deps_strict_fails_on_finding(tmp_path):
    # rich is declared but never imported -> a finding -> --strict returns 1.
    _project(tmp_path, ["requests>=2", "rich>=13"], ["requests"])
    rc, _ = _run(tmp_path, strict=True)
    assert rc == 1


def test_deps_strict_passes_when_clean(tmp_path):
    # All declared deps imported, all pinned -> no findings -> --strict returns 0.
    _project(tmp_path, ["requests>=2", "PyYAML>=6"], ["requests", "yaml"])
    rc, _ = _run(tmp_path, strict=True)
    assert rc == 0


def test_deps_strict_off_returns_zero_even_with_findings(tmp_path):
    _project(tmp_path, ["requests>=2", "rich>=13"], ["requests"])
    rc, _ = _run(tmp_path, strict=False)
    assert rc == 0


def test_deps_empty_target_is_clean(tmp_path):
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "no dependency issues found" in out.lower()
