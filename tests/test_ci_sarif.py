"""CI on-ramp: `apex review --sarif` emits a CI-uploadable SARIF 2.1.0 file.

Exercises the exact command the `Apex CI` workflow wires
(`apex review --base <ref> --sarif <path>`) over a throwaway git project and
asserts the written JSON is a well-formed SARIF log: top-level `version` /
`$schema`, a `runs` array, a tool driver name, and a list `results`. This is
the contract `github/codeql-action/upload-sarif` depends on.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from app.cli import cmd_review


def _init_repo_with_finding(root: Path) -> None:
    """Create a tiny committed project, then add a high-severity diff finding."""
    (root / "app").mkdir()
    (root / "app" / "m.py").write_text("def base():\n    return 1\n")
    for c in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t.com"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "-A"],
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"],
    ):
        subprocess.run(c, cwd=root, capture_output=True)
    # New, changed line carrying an obvious security issue for the diff review.
    (root / "app" / "m.py").write_text(
        "def base():\n    return 1\n\ndef bad(c):\n    return eval(c)\n"
    )


def _run_sarif_export(root: Path, out: Path) -> int:
    args = argparse.Namespace(
        target=str(root), base="HEAD", fail_on_high=False,
        json=False, fix=False, sarif=str(out),
    )
    return cmd_review(args)


def test_sarif_export_writes_wellformed_document(tmp_path: Path) -> None:
    _init_repo_with_finding(tmp_path)
    out = tmp_path / "ci" / "apex.sarif"

    rc = _run_sarif_export(tmp_path, out)

    assert rc == 0
    assert out.is_file()
    sarif = json.loads(out.read_text(encoding="utf-8"))

    # SARIF 2.1.0 envelope.
    assert sarif["version"] == "2.1.0"
    assert "$schema" in sarif and "sarif-2.1.0" in sarif["$schema"]

    # At least one run with a named tool driver.
    runs = sarif["runs"]
    assert isinstance(runs, list) and len(runs) >= 1
    run = runs[0]
    assert run["tool"]["driver"]["name"]

    # results must be a list (uploadable even when empty).
    assert isinstance(run["results"], list)
    # The eval() finding landed in the diff.
    assert any("eval" in r["ruleId"] for r in run["results"])


def test_sarif_export_on_clean_diff_is_uploadable(tmp_path: Path) -> None:
    """No findings in the diff -> still a valid SARIF with an empty results list."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def base():\n    return 1\n")
    for c in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t.com"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "-A"],
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"],
    ):
        subprocess.run(c, cwd=tmp_path, capture_output=True)

    out = tmp_path / "apex.sarif"
    rc = _run_sarif_export(tmp_path, out)

    assert rc == 0
    sarif = json.loads(out.read_text(encoding="utf-8"))
    assert sarif["version"] == "2.1.0"
    assert isinstance(sarif["runs"], list) and sarif["runs"]
    assert sarif["runs"][0]["results"] == []
