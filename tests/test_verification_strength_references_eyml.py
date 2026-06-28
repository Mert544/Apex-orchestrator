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
    _module_identity,
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


# ── package __init__.py is the PACKAGE, not ``<pkg>.__init__`` ───────────────
# Field test: ``import inflection`` (the normal way to test a single-module
# package) reference ``inflection/__init__.py`` — the importable name is the
# parent dir, so covered-only no longer over-refuses a well-tested package.


def test_module_identity_flat_module_unchanged():
    assert _module_identity("pkg/danger.py") == ("pkg.danger", "danger")
    assert _module_identity("mod.py") == ("mod", "mod")


def test_module_identity_package_init_is_parent_dir():
    # ``inflection/__init__.py`` is imported as ``inflection``, not
    # ``inflection.__init__``; the own-name is the package name.
    assert _module_identity("inflection/__init__.py") == ("inflection", "inflection")


def test_module_identity_nested_package_init_dots_parents():
    # ``a/b/__init__.py`` → dotted ``a.b``, own-name the leaf package ``b``.
    assert _module_identity("a/b/__init__.py") == ("a.b", "b")


def test_module_identity_rejects_non_importable():
    assert _module_identity("notpy.txt") is None          # not a module
    assert _module_identity("__init__.py") is None         # root init: no package


def test_package_init_referenced_by_plain_import():
    # The exact field-test shape: a test that does ``import inflection``.
    assert _references_module("import inflection\n", "inflection/__init__.py") is True
    assert _references_module("import inflection as inf\n",
                              "inflection/__init__.py") is True


def test_package_init_referenced_by_from_import():
    # ``from inflection import camelize`` references the package init too.
    assert _references_module("from inflection import camelize\n",
                              "inflection/__init__.py") is True


def test_nested_package_init_referenced_by_dotted_import():
    assert _references_module("import a.b\n", "a/b/__init__.py") is True
    assert _references_module("from a.b import thing\n", "a/b/__init__.py") is True
    # The leaf package name as a clean import component also references it
    # (a layout whose root-relative path differs from the test's).
    assert _references_module("from a import b\n", "a/b/__init__.py") is True


def test_package_init_NOT_referenced_without_import():
    # SOUNDNESS (no false-green): a test that never imports the package is
    # still ``none`` — exactly as before the fix.
    assert _references_module("import os\nfrom sys import path\n",
                              "inflection/__init__.py") is False
    assert _references_module("# inflection is great\n",
                              "inflection/__init__.py") is False
    assert _references_module('x = "inflection"\n',
                              "inflection/__init__.py") is False
    # A SIBLING package whose name merely SHARES a prefix is not the package
    # (``inflectionx`` is a different top-level module, not ``inflection``).
    assert _references_module("import inflectionx\n",
                              "inflection/__init__.py") is False


def test_package_init_unparsable_falls_back_to_import_line():
    broken = "import inflection\ndef oops(\n"
    assert _references_module(broken, "inflection/__init__.py") is True
    broken_comment = "# inflection\ndef oops(\n"
    assert _references_module(broken_comment, "inflection/__init__.py") is False


def test_assess_strength_package_init_module_vs_function(tmp_path: Path):
    # The full grade on a single-module package, the inflection shape.
    (tmp_path / "inflection").mkdir()
    init = tmp_path / "inflection" / "__init__.py"
    src = "def camelize(s):\n    return s\ndef underscore(s):\n    return s\n"
    init.write_text(src, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_inflection.py").write_text(
        "import inflection\n"
        "def test_camelize():\n    assert inflection.camelize('x') == 'x'\n",
        encoding="utf-8")
    # A change to camelize — the test names it → FUNCTION coverage.
    named = assess_strength(
        str(tmp_path), ["inflection/__init__.py"], {"inflection/__init__.py": src},
        {"inflection/__init__.py":
         "def camelize(s):\n    return s.upper()\ndef underscore(s):\n    return s\n"})
    assert named["level"] == "function"
    # A change to underscore — only imported, never named → MODULE coverage.
    imported = assess_strength(
        str(tmp_path), ["inflection/__init__.py"], {"inflection/__init__.py": src},
        {"inflection/__init__.py":
         "def camelize(s):\n    return s\ndef underscore(s):\n    return s.lower()\n"})
    assert imported["level"] == "module"


def test_assess_strength_package_init_none_when_unimported(tmp_path: Path):
    # SOUNDNESS: a package whose test never imports it stays ``none`` — the fix
    # must not make a genuinely-uncovered __init__.py change look covered.
    (tmp_path / "inflection").mkdir()
    init = tmp_path / "inflection" / "__init__.py"
    src = "def camelize(s):\n    return s\n"
    init.write_text(src, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_unrelated.py").write_text(
        "import os\ndef test_x():\n    assert True\n", encoding="utf-8")
    strength = assess_strength(
        str(tmp_path), ["inflection/__init__.py"], {"inflection/__init__.py": src},
        {"inflection/__init__.py": "def camelize(s):\n    return s.upper()\n"})
    assert strength["level"] == "none"


def test_module_referenced_by_suite_package_init(tmp_path: Path):
    (tmp_path / "inflection").mkdir()
    (tmp_path / "inflection" / "__init__.py").write_text(
        "def camelize(s):\n    return s\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    # No import yet → not covered.
    (tests / "test_c.py").write_text(
        "# uses inflection\ndef test_a():\n    assert True\n", encoding="utf-8")
    assert module_referenced_by_suite(str(tmp_path), "inflection/__init__.py") is False
    # A real ``import inflection`` → covered.
    (tests / "test_real.py").write_text(
        "import inflection\ndef test_b():\n    assert inflection.camelize('x') == 'x'\n",
        encoding="utf-8")
    assert module_referenced_by_suite(str(tmp_path), "inflection/__init__.py") is True
