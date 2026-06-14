"""Tests for the scripts/fix_docstrings.py CLI entrypoint.

``main`` drives :class:`DocstringAgent` over a project root and reports the
gaps. These tests pin its observable contract: the exit code reflects whether
gaps remain, ``--dry-run`` never writes, the default run patches missing
docstrings in place, and a fully-documented tree exits clean.
"""

from __future__ import annotations

from pathlib import Path

from scripts.fix_docstrings import main


def test_dry_run_reports_gaps_without_writing(tmp_path: Path, capsys):
    src = tmp_path / "m.py"
    src.write_text("def undocumented():\n    pass\n", encoding="utf-8")

    rc = main(["--project-root", str(tmp_path), "--dry-run"])

    # Gaps remain -> non-zero exit; the source is untouched.
    assert rc == 1
    assert src.read_text(encoding="utf-8") == "def undocumented():\n    pass\n"
    out = capsys.readouterr().out
    assert "Gaps found: 1" in out
    assert "Dry run" in out
    assert "undocumented" in out


def test_default_run_patches_in_place(tmp_path: Path, capsys):
    src = tmp_path / "m.py"
    src.write_text("def undocumented():\n    pass\n", encoding="utf-8")

    rc = main(["--project-root", str(tmp_path)])

    # A docstring was inserted into the previously-bare function.
    patched = src.read_text(encoding="utf-8")
    assert '"""undocumented implementation."""' in patched
    out = capsys.readouterr().out
    assert "Files patched: 1" in out
    assert "Patched files:" in out
    # gaps_found counts the original gap, so the run still flags a non-zero code.
    assert rc == 1


def test_clean_project_exits_zero(tmp_path: Path, capsys):
    src = tmp_path / "m.py"
    src.write_text(
        'def documented():\n    """Has a docstring."""\n    return 1\n',
        encoding="utf-8",
    )

    rc = main(["--project-root", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Gaps found: 0" in out
    # Nothing to patch -> source unchanged.
    assert '"""Has a docstring."""' in src.read_text(encoding="utf-8")


def test_truncates_gap_listing_to_twenty(tmp_path: Path, capsys):
    body = "".join(f"def fn{i}():\n    pass\n\n\n" for i in range(25))
    (tmp_path / "many.py").write_text(body, encoding="utf-8")

    rc = main(["--project-root", str(tmp_path), "--dry-run"])

    assert rc == 1
    out = capsys.readouterr().out
    assert "Gaps found: 25" in out
    # Listing is capped at 20 with an "... and N more" footer.
    assert "... and 5 more" in out
