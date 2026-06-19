"""Coverage detection must key on a REAL import, not a substring mention.

A red-team audit found that ``_references_module`` matched the module's dotted
path anywhere in the test text — including inside a comment or a string literal —
so a test that merely *names* a module in a comment was counted as "covering" it.
That over-counts coverage strength and (via ``module_referenced_by_suite``) can
green-light a Tier-1 fix on code no test exercises. These tests pin the
AST-exact behaviour: only an actual ``import`` counts.

Deterministic; stdlib-only.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.verification_strength import (
    _references_module,
    assess_strength,
    module_referenced_by_suite,
)


def test_comment_mention_is_not_coverage():
    assert _references_module("# see pkg.danger for details\n", "pkg/danger.py") is False


def test_string_mention_is_not_coverage():
    assert _references_module('x = "pkg.danger"\n', "pkg/danger.py") is False
    assert _references_module('"""docs about pkg.danger"""\n', "pkg/danger.py") is False


def test_real_imports_are_coverage():
    for src in ("import pkg.danger\n",
                "from pkg import danger\n",
                "from pkg.danger import run\n",
                "import pkg.danger as d\n"):
        assert _references_module(src, "pkg/danger.py") is True, src


def test_unrelated_import_is_not_coverage():
    assert _references_module("import pkg.other\nfrom os import path\n",
                              "pkg/danger.py") is False


def test_unparsable_text_falls_back_to_import_regex():
    # A test file with a syntax error still counts if it has an import line.
    broken = "import pkg.danger\ndef oops(\n"
    assert _references_module(broken, "pkg/danger.py") is True
    # ...but a broken file that only mentions it in a comment does not.
    broken_comment = "# pkg.danger\ndef oops(\n"
    assert _references_module(broken_comment, "pkg/danger.py") is False


def test_module_referenced_by_suite_uses_real_imports(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "danger.py").write_text("def run():\n    return 1\n",
                                                encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    # Only a comment mention -> NOT covered.
    (tests / "test_comment.py").write_text(
        "# exercises pkg.danger thoroughly\ndef test_x():\n    assert True\n",
        encoding="utf-8")
    assert module_referenced_by_suite(str(tmp_path), "pkg/danger.py") is False
    # Add a real import -> covered.
    (tests / "test_real.py").write_text(
        "from pkg import danger\ndef test_y():\n    assert danger.run() == 1\n",
        encoding="utf-8")
    assert module_referenced_by_suite(str(tmp_path), "pkg/danger.py") is True


def test_assess_strength_demotes_comment_only_to_none(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_c.py").write_text(
        "# touches pkg.m\ndef test_a():\n    assert True\n", encoding="utf-8")
    strength = assess_strength(
        str(tmp_path), ["pkg/m.py"],
        {"pkg/m.py": "def foo():\n    return 1\n"},
        {"pkg/m.py": "def foo():\n    return 2\n"})
    # A comment-only "reference" is no coverage at all.
    assert strength["level"] == "none"
