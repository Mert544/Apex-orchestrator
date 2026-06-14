"""Tests for the scripts/fix_coverage.py CLI entrypoint.

``main`` drives :class:`TestStubAgent` over a project root, reporting coverage
gaps and (optionally) writing stub test files. These tests pin its observable
contract: a dry run reports gaps but writes nothing, ``--generate`` lands a
stub file, a fully-tested tree exits clean, and the listing truncates.
"""

from __future__ import annotations

from pathlib import Path

from scripts.fix_coverage import main


def test_dry_run_reports_gaps_without_generating(tmp_path: Path, capsys):
    (tmp_path / "m.py").write_text("def public_fn():\n    return 1\n", encoding="utf-8")

    rc = main(["--project-root", str(tmp_path)])

    # Uncovered public function -> non-zero exit; no tests directory created.
    assert rc == 1
    assert not (tmp_path / "tests").exists()
    out = capsys.readouterr().out
    assert "Gaps found: 1" in out
    assert "Coverage: 0.0%" in out
    assert "Dry run" in out
    assert "m.py::public_fn -> test_m.py" in out


def test_generate_writes_stub_file(tmp_path: Path, capsys):
    (tmp_path / "m.py").write_text("def public_fn():\n    return 1\n", encoding="utf-8")

    rc = main(["--project-root", str(tmp_path), "--generate"])

    stub = tmp_path / "tests" / "test_m.py"
    assert stub.exists()
    content = stub.read_text(encoding="utf-8")
    assert "def test_public_fn():" in content
    out = capsys.readouterr().out
    assert "Generated stubs:" in out
    assert "tests/test_m.py" in out
    assert rc == 1


def test_fully_tested_project_exits_zero(tmp_path: Path, capsys):
    (tmp_path / "m.py").write_text("def public_fn():\n    return 1\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    # An existing matching test_<symbol> closes the gap.
    (tests / "test_m.py").write_text(
        "def test_public_fn():\n    assert public_fn() == 1\n", encoding="utf-8")

    rc = main(["--project-root", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Gaps found: 0" in out
    assert "Coverage: 100.0%" in out


def test_private_functions_are_not_gaps(tmp_path: Path, capsys):
    (tmp_path / "m.py").write_text(
        "def _helper():\n    return 1\n", encoding="utf-8")

    rc = main(["--project-root", str(tmp_path)])

    # Underscore-prefixed functions are skipped, so no gaps and a clean exit.
    assert rc == 0
    out = capsys.readouterr().out
    assert "Functions scanned: 0" in out


def test_truncates_gap_listing_to_twenty(tmp_path: Path, capsys):
    body = "".join(f"def fn{i}():\n    return {i}\n\n\n" for i in range(25))
    (tmp_path / "many.py").write_text(body, encoding="utf-8")

    rc = main(["--project-root", str(tmp_path)])

    assert rc == 1
    out = capsys.readouterr().out
    assert "Gaps found: 25" in out
    assert "... and 5 more" in out
