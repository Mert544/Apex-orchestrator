"""Deep mutation-hardening for the proof-integrity wave's recursion guards.

Two moat-critical pieces added this session must resist single-token mutation:

1. ``verification_strength._references_module`` / ``_imported_modules`` —
   AST-EXACT import detection. A module named only in a COMMENT or a STRING
   LITERAL is NOT coverage (the over-counting a substring match used to allow);
   a REAL import IS coverage; an UNPARSABLE test file falls back to an
   import-position regex (never a bare-word body match); and a RecursionError /
   SyntaxError "bomb" test file contributes NO coverage without crashing.
   Each case below pins the exact boolean a mutant would flip.

2. The RecursionError / MemoryError hardening across the analysis surface. A
   deeply-nested-expression "bomb" file — ``x = '1+'*40000 + '1'`` whose source
   is ``x = 1+1+1+...+1`` (80k chars) — overflows ``ast.parse`` with a
   RecursionError. Every analyzer that parses project source must SKIP it (treat
   it as unparsable) rather than crash. We pin that for:
     * ``detectors.security_labels``       -> []     (and ``security_label`` None)
     * ``python_structure._parse_tree``    -> None
     * ``python_structure._parse_source``  -> None
     * ``completeness.incomplete_protocols`` survives a bomb in the tree
     * ``ProjectProfiler.profile``         survives a bomb in the tree
     * ``IdeaPermutationEngine.run``       survives a bomb in the tree
   A mutant that drops ``RecursionError`` from any of those ``except`` tuples
   would turn these green tests red (the bomb would propagate).

Determinism: the bomb is a fixed construction; every assertion is exact-value
(booleans, ``None``, ``[]``, object type). No timestamps, wall-clock, or
set/dict iteration order.
"""
from __future__ import annotations

from pathlib import Path

from app.engine.verification_strength import (
    _imported_modules,
    _references_module,
    module_referenced_by_suite,
)

# The recursion "bomb": its SOURCE is ``x = 1+1+1+...+1`` (40000 terms), which
# overflows ast.parse's recursion limit. Built once, deterministically.
_BOMB_SOURCE = "x = " + "1+" * 40000 + "1"


def _bomb_raises_recursion() -> bool:
    import ast

    try:
        ast.parse(_BOMB_SOURCE)
    except RecursionError:
        return True
    except Exception:
        return False
    return False


# ===========================================================================
# _imported_modules — AST-exact dotted import extraction.
# ===========================================================================
def test_imported_modules_collects_plain_import():
    assert _imported_modules("import app.engine.foo") == {"app.engine.foo"}


def test_imported_modules_collects_from_import_base_and_members():
    mods = _imported_modules("from app.engine import foo, bar")
    assert mods == {"app.engine", "app.engine.foo", "app.engine.bar"}


def test_imported_modules_ignores_comment_and_string_mentions():
    # A module named in a comment or a string literal is NOT imported.
    text = "# app.engine.foo is great\nx = 'app.engine.foo'\nimport os\n"
    assert _imported_modules(text) == {"os"}


def test_imported_modules_returns_none_on_unparsable_text():
    # Unparsable -> None (the signal the caller uses to fall back to regex).
    assert _imported_modules("def (:") is None


def test_imported_modules_bare_import_member_when_no_base():
    # ``from . import x`` has an empty base, so the member is added bare.
    assert _imported_modules("from . import widget") == {"widget"}


def test_imported_modules_aliased_import_uses_real_name_not_alias():
    # ``import a.b as c`` records the real dotted name ``a.b``, not the alias.
    assert _imported_modules("import a.b as c") == {"a.b"}


# ===========================================================================
# _references_module — coverage = REAL import only, never a mention.
# ===========================================================================
def test_references_module_true_for_real_dotted_import():
    assert _references_module("import app.engine.foo", "app/engine/foo.py") is True


def test_references_module_true_for_from_import_of_stem():
    # ``from app.engine import foo`` names ``foo`` as a clean import member.
    assert _references_module("from app.engine import foo", "app/engine/foo.py") is True


def test_references_module_false_for_comment_only_mention():
    assert _references_module("# uses app.engine.foo", "app/engine/foo.py") is False


def test_references_module_false_for_string_literal_mention():
    assert _references_module("x = 'app.engine.foo'", "app/engine/foo.py") is False


def test_references_module_false_for_unrelated_import():
    assert _references_module("import os\nimport sys", "app/engine/foo.py") is False


def test_references_module_false_for_non_py_target():
    # A non-``.py`` target can never be referenced as a Python module.
    assert _references_module("import app.engine.foo", "app/engine/foo.txt") is False


def test_references_module_unparsable_falls_back_to_import_regex_true():
    # Cannot parse -> regex over import POSITIONS finds the stem in an import.
    text = "def (:\nimport app.engine.foo\n"
    assert _references_module(text, "app/engine/foo.py") is True


def test_references_module_true_via_full_dotted_path_match(tmp_path: Path):
    # The first AST branch: the test imports the EXACT project-relative dotted
    # path. Pins the ``dotted in mods`` rung (L116) and its slice (L112).
    assert _references_module("import pkg.sub.mod", "pkg/sub/mod.py") is True


def test_references_module_unparsable_body_word_is_not_coverage():
    # The regex matches only an IMPORT position, never a bare body word like a
    # function call ``foo()`` — otherwise common names would flood as coverage.
    text = "def (:\n    foo()\n"
    assert _references_module(text, "app/engine/foo.py") is False


def test_references_module_bomb_test_contributes_no_coverage_without_crashing():
    # A RecursionError bomb test file is unparsable -> _imported_modules None ->
    # regex fallback. It names no import of the target stem, so it is NOT
    # coverage; and crucially the call must NOT raise.
    assert _bomb_raises_recursion() is True
    assert _references_module(_BOMB_SOURCE, "app/engine/foo.py") is False


# ===========================================================================
# module_referenced_by_suite — a bomb test file in the suite is collected but
# contributes nothing; a real referencing test still wins.
# ===========================================================================
def test_module_referenced_by_suite_short_circuits_for_test_file_target():
    # A test-file target never needs a shield -> always True, WITHOUT scanning
    # the suite (pins the ``or``/``True`` guard at the function head: the ``or``
    # branch fires on the test-path predicate, returning True).
    assert module_referenced_by_suite("/nonexistent-root", "tests/test_x.py") is True


def test_module_referenced_by_suite_short_circuits_for_non_py_target():
    # A non-``.py`` target likewise never needs a shield -> True (pins the first
    # arm of the ``or`` guard; an ``and`` mutant would scan and return False).
    assert module_referenced_by_suite("/nonexistent-root", "data/config.yml") is True


def test_suite_with_only_a_bomb_test_references_nothing(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "danger.py").write_text(
        "import os\ndef run():\n    return os.getcwd()\n", encoding="utf-8")
    (tmp_path / "tests" / "test_bomb.py").write_text(_BOMB_SOURCE + "\n", encoding="utf-8")
    # Only the (unparsable) bomb test exists -> module is unreferenced; no crash.
    assert module_referenced_by_suite(str(tmp_path), "app/danger.py") is False


def test_real_test_references_module_even_with_bomb_present(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "danger.py").write_text(
        "import os\ndef run():\n    return os.getcwd()\n", encoding="utf-8")
    (tmp_path / "tests" / "test_bomb.py").write_text(_BOMB_SOURCE + "\n", encoding="utf-8")
    (tmp_path / "tests" / "test_danger.py").write_text(
        "from app.danger import run\ndef test_run():\n    run()\n", encoding="utf-8")
    # The real test names the module; the bomb file beside it does not crash it.
    assert module_referenced_by_suite(str(tmp_path), "app/danger.py") is True


# ===========================================================================
# detectors.security_labels / security_label — bomb is SKIPPED, not crashing.
# ===========================================================================
def test_security_labels_skips_recursion_bomb_to_empty_list():
    from app.engine.detectors import security_labels

    assert security_labels(_BOMB_SOURCE) == []


def test_security_label_returns_none_for_recursion_bomb_with_no_needle():
    from app.engine.detectors import security_label

    # The bomb has no substring-fallback needle (eval/os.system/...), so None.
    assert security_label(_BOMB_SOURCE) is None


def test_security_labels_still_detects_real_finding():
    # Control: a normal dangerous file is still graded (the guard didn't blunt
    # detection of parseable source).
    from app.engine.detectors import security_labels

    assert "eval" in security_labels("x = eval(input())\n")


# ===========================================================================
# python_structure._parse_tree / _parse_source — bomb -> None, no crash.
# ===========================================================================
def test_parse_tree_returns_none_for_recursion_bomb(tmp_path: Path):
    from app.tools.python_structure import _parse_tree

    bomb = tmp_path / "bomb.py"
    bomb.write_text(_BOMB_SOURCE + "\n", encoding="utf-8")
    assert _parse_tree(bomb) is None


def test_parse_source_returns_none_for_recursion_bomb(tmp_path: Path):
    from app.tools.python_structure import _parse_source

    bomb = tmp_path / "bomb.py"
    bomb.write_text(_BOMB_SOURCE + "\n", encoding="utf-8")
    assert _parse_source(bomb) is None


def test_parse_tree_parses_a_normal_module(tmp_path: Path):
    # Control: a clean module still parses to a Module node.
    import ast

    from app.tools.python_structure import _parse_tree

    ok = tmp_path / "ok.py"
    ok.write_text("import os\n\n\ndef f():\n    return 1\n", encoding="utf-8")
    tree = _parse_tree(ok)
    assert isinstance(tree, ast.Module)


# ===========================================================================
# completeness.incomplete_protocols — survives a bomb in the tree.
# ===========================================================================
def test_incomplete_protocols_survives_a_bomb_file(tmp_path: Path):
    from app.engine.completeness import incomplete_protocols

    (tmp_path / "bomb.py").write_text(_BOMB_SOURCE + "\n", encoding="utf-8")
    # A clean module beside the bomb so the scan has real work to do too.
    (tmp_path / "clean.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    out = incomplete_protocols(str(tmp_path))
    # No crash; the bomb yields nothing and the clean file has no protocol gap.
    assert out == []


# ===========================================================================
# ProjectProfiler.profile and IdeaPermutationEngine.run — survive a bomb tree.
# ===========================================================================
def _seed_project_with_bomb(root: Path) -> None:
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "danger.py").write_text(
        "import os\n\n\ndef run():\n    return os.getcwd()\n", encoding="utf-8")
    (root / "tests" / "test_bomb.py").write_text(_BOMB_SOURCE + "\n", encoding="utf-8")


def test_project_profiler_survives_a_bomb_file(tmp_path: Path):
    from app.tools.project_profile import ProjectProfile, ProjectProfiler

    _seed_project_with_bomb(tmp_path)
    profile = ProjectProfiler(str(tmp_path)).profile()
    # The bomb file did not crash the profiler; a real profile is produced.
    assert isinstance(profile, ProjectProfile)


def test_idea_permutation_run_survives_a_bomb_file(tmp_path: Path):
    from app.engine.idea_permutation import IdeaPermutationEngine
    from app.models.idea import IdeaTreeReport

    _seed_project_with_bomb(tmp_path)
    report = IdeaPermutationEngine(project_root=str(tmp_path)).run()
    # The full seed->permute->synthesize pipeline survived the bomb in the tree.
    assert isinstance(report, IdeaTreeReport)
