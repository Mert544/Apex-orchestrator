from __future__ import annotations

from pathlib import Path

from app.reporting.deadcode import find_dead_code, render_dead_code_markdown


def _proj(tmp: Path) -> Path:
    (tmp / "pkg").mkdir()
    (tmp / "pkg" / "__init__.py").write_text("")
    (tmp / "pkg" / "used.py").write_text("def alive():\n    return 1\n")
    (tmp / "pkg" / "dead.py").write_text("def ghost():\n    return 2\n")
    # consumer references alive() but never ghost()
    (tmp / "pkg" / "main.py").write_text("from pkg.used import alive\n\ndef run():\n    return alive()\n")
    (tmp / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    return tmp


def test_finds_unreferenced_symbol(tmp_path: Path):
    rows = find_dead_code(str(_proj(tmp_path)))
    names = {r["symbol"] for r in rows}
    assert "ghost" in names
    assert "alive" not in names          # referenced -> not dead


def test_references_from_tests_count(tmp_path: Path):
    _proj(tmp_path)
    (tmp_path / "tests").mkdir()
    # A test references ghost -> it must no longer be reported as dead.
    (tmp_path / "tests" / "test_ghost.py").write_text("from pkg.dead import ghost\ndef test_g():\n    assert ghost() == 2\n")
    names = {r["symbol"] for r in find_dead_code(str(tmp_path))}
    assert "ghost" not in names


def test_decorated_and_exported_and_dunder_excluded(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "m.py").write_text(
        "__all__ = ['Exported']\n"
        "import functools\n"
        "class Exported:\n    pass\n"
        "@functools.cache\ndef registered():\n    return 1\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    names = {r["symbol"] for r in find_dead_code(str(tmp_path))}
    assert "Exported" not in names       # in __all__
    assert "registered" not in names     # decorated


def test_private_symbol_is_high_confidence_and_public_is_review(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "m.py").write_text(
        "def _hidden():\n    return 1\n\ndef public():\n    return 2\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    rows = find_dead_code(str(tmp_path))
    by_name = {r["symbol"]: r["confidence"] for r in rows}
    assert by_name["_hidden"] == "high"
    assert by_name["public"] == "review"
    # high-confidence (private) findings are ordered first
    assert rows[0]["symbol"] == "_hidden"


def test_render_includes_confidence_column_and_summary(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "m.py").write_text("def _hidden():\n    return 1\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    md = render_dead_code_markdown(find_dead_code(str(tmp_path)))
    assert "Confidence" in md
    assert "high-confidence" in md
    assert "| high |" in md


def test_empty_render():
    assert "No unreferenced" in render_dead_code_markdown([])
