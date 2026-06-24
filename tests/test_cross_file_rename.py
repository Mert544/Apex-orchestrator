"""Cross-file rename: definition + imports + call sites, conservatively."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.execution.cross_file_rename import (
    RenamePlan,
    _is_non_library_file,
    apply_rename,
    plan_rename,
    plan_source_rewrite,
)


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "# the central helper\n"
        "def compute(x):\n"
        "    return x * 2\n"
        "\n"
        "def wrapper(x):\n"
        "    return compute(x) + 1  # uses it locally\n"
    )
    (tmp_path / "app" / "user_from.py").write_text(
        "from app.core import compute\n"
        "\n"
        "def f(v):\n"
        "    return compute(v)\n"
    )
    (tmp_path / "app" / "user_attr.py").write_text(
        "import app.core\n"
        "\n"
        "def g(v):\n"
        "    return app.core.compute(v)\n"
    )
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import compute\n"
        "def test_compute():\n"
        "    assert compute(2) == 4\n"
    )
    return tmp_path


def test_plan_covers_definition_imports_and_call_sites(tmp_path):
    _project(tmp_path)
    plan = plan_rename(tmp_path, "compute", "calculate")
    assert plan.ok and plan.defined_in == "app/core.py"
    assert set(plan.new_contents) == {
        "app/core.py", "app/user_from.py", "app/user_attr.py", "tests/test_core.py"}
    # Definition + local call rewritten; the comment survives verbatim.
    core = plan.new_contents["app/core.py"]
    assert "def calculate(x):" in core and "return calculate(x) + 1" in core
    assert "# the central helper" in core and "# uses it locally" in core
    assert "compute" not in core
    # from-import users: import line AND bare call sites.
    assert "from app.core import calculate" in plan.new_contents["app/user_from.py"]
    assert "return calculate(v)" in plan.new_contents["app/user_from.py"]
    # module-attr users: only the attribute is renamed.
    assert "return app.core.calculate(v)" in plan.new_contents["app/user_attr.py"]
    assert "import app.core\n" in plan.new_contents["app/user_attr.py"]


def test_aliased_import_only_rewrites_the_import_line(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "user_alias.py").write_text(
        "from app.core import compute as crunch\n"
        "def h(v):\n"
        "    return crunch(v)\n"
    )
    plan = plan_rename(tmp_path, "compute", "calculate")
    assert plan.ok
    alias = plan.new_contents["app/user_alias.py"]
    assert "from app.core import calculate as crunch" in alias
    assert "return crunch(v)" in alias  # usage through the alias is untouched


def test_ambiguous_definition_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "other.py").write_text("def compute(y):\n    return y\n")
    plan = plan_rename(tmp_path, "compute", "calculate")
    assert not plan.ok
    assert any("ambiguous" in b for b in plan.blockers)


def test_collision_with_existing_binding_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "user_from.py").write_text(
        "from app.core import compute\n"
        "calculate = 41\n"
        "def f(v):\n"
        "    return compute(v) + calculate\n"
    )
    plan = plan_rename(tmp_path, "compute", "calculate")
    assert not plan.ok
    assert any("collision" in b for b in plan.blockers)


def test_local_shadow_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "user_from.py").write_text(
        "from app.core import compute\n"
        "def f(compute):\n"          # parameter shadows the import
        "    return compute(1)\n"
    )
    plan = plan_rename(tmp_path, "compute", "calculate")
    assert not plan.ok
    assert any("shadowed" in b for b in plan.blockers)


def test_missing_symbol_and_bad_identifier_block(tmp_path):
    _project(tmp_path)
    assert not plan_rename(tmp_path, "ghost", "calculate").ok
    assert not plan_rename(tmp_path, "compute", "with").ok       # keyword
    assert not plan_rename(tmp_path, "compute", "calc ulate").ok  # not an identifier
    assert not plan_rename(tmp_path, "compute", "compute").ok     # no-op


def test_string_reference_surfaces_as_warning(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "dynamic.py").write_text(
        "import app.core\n"
        "def d():\n"
        "    return getattr(app.core, 'compute')(3)\n"
    )
    plan = plan_rename(tmp_path, "compute", "calculate")
    assert plan.ok  # warnings never block — they inform
    assert any("string literal 'compute'" in w for w in plan.warnings)


def test_apply_verifies_and_keeps_on_green(tmp_path):
    _project(tmp_path)
    res = apply_rename(tmp_path, plan_rename(tmp_path, "compute", "calculate"), verify=True)
    assert res["applied"] is True and res["verified"] is True
    assert res["rolled_back"] is False
    assert "def calculate(x):" in (tmp_path / "app" / "core.py").read_text()
    # The renamed suite still passes because the test was rewritten too.
    assert "calculate(2) == 4" in (tmp_path / "tests" / "test_core.py").read_text()


def test_apply_rolls_back_when_tests_fail(tmp_path):
    _project(tmp_path)
    (tmp_path / "tests" / "test_always_red.py").write_text(
        "def test_red():\n    assert False\n")
    before = (tmp_path / "app" / "core.py").read_text()
    res = apply_rename(tmp_path, plan_rename(tmp_path, "compute", "calculate"), verify=True)
    assert res["applied"] is False and res["rolled_back"] is True
    assert (tmp_path / "app" / "core.py").read_text() == before


def _new_file_plan(rel: str, content: str) -> RenamePlan:
    """A plan that CREATES a brand-new file (no original to restore)."""
    plan = RenamePlan(old=rel, new="generate")
    plan.new_contents[rel] = content
    plan.edits_by_file[rel] = 1
    return plan


def test_apply_creates_new_file_and_keeps_on_green(tmp_path):
    _project(tmp_path)
    plan = _new_file_plan("tests/test_generated.py",
                          "def test_added():\n    assert True\n")
    res = apply_rename(tmp_path, plan, verify=True)
    assert res["applied"] is True and res["verified"] is True
    assert res["rolled_back"] is False
    assert (tmp_path / "tests" / "test_generated.py").exists()


def test_apply_deletes_created_file_on_rollback(tmp_path):
    _project(tmp_path)
    # A generated file that DROPS the suite to red must be removed on rollback —
    # there is no original to restore, so the orphan would otherwise linger.
    plan = _new_file_plan("tests/test_generated_red.py",
                          "def test_red():\n    assert False\n")
    res = apply_rename(tmp_path, plan, verify=True)
    assert res["applied"] is False and res["rolled_back"] is True
    assert not (tmp_path / "tests" / "test_generated_red.py").exists()


def test_apply_creates_nested_dirs(tmp_path):
    _project(tmp_path)
    plan = _new_file_plan("app/sub/pkg/new_mod.py", "VALUE = 1\n")
    res = apply_rename(tmp_path, plan, verify=False)
    assert res["applied"] is True
    assert (tmp_path / "app" / "sub" / "pkg" / "new_mod.py").read_text() == "VALUE = 1\n"


def test_cli_rename_dry_run_and_apply(tmp_path, capsys):
    from app.cli import cmd_rename

    _project(tmp_path)
    ns = argparse.Namespace(old="compute", new="calculate", target=str(tmp_path),
                            dry_run=True, no_verify=False, json=False)
    assert cmd_rename(ns) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "-def compute(x):" in out and "+def calculate(x):" in out
    assert "compute" in (tmp_path / "app" / "core.py").read_text()  # nothing changed

    ns.dry_run = False
    assert cmd_rename(ns) == 0
    assert "tests pass" in capsys.readouterr().out
    assert "def calculate(x):" in (tmp_path / "app" / "core.py").read_text()


def test_cli_rename_blocked_exits_nonzero(tmp_path, capsys):
    from app.cli import cmd_rename

    _project(tmp_path)
    (tmp_path / "app" / "other.py").write_text("def compute(y):\n    return y\n")
    ns = argparse.Namespace(old="compute", new="calculate", target=str(tmp_path),
                            dry_run=False, no_verify=False, json=False)
    assert cmd_rename(ns) == 1
    assert "⛔" in capsys.readouterr().out


# --- Characterization: pin the produced plan byte-for-byte ----------------
# These tests freeze the exact RenamePlan (every edit, count, ordering, and
# blocker) for representative inputs. They are a behaviour contract: any change
# to plan_rename that is not byte-identical — including refactors — must break
# them. Captured from the planner and asserted against literal expected values.

def test_characterization_full_plan_is_pinned(tmp_path):
    """The complete happy-path plan, frozen edit-for-edit."""
    _project(tmp_path)
    plan = plan_rename(tmp_path, "compute", "calculate")

    assert plan.ok is True
    assert plan.defined_in == "app/core.py"
    assert plan.blockers == []
    assert plan.warnings == []
    # Files touched, and how many distinct spans each received.
    assert dict(sorted(plan.edits_by_file.items())) == {
        "app/core.py": 2,
        "app/user_attr.py": 1,
        "app/user_from.py": 2,
        "tests/test_core.py": 2,
    }
    # Exact rewritten bytes — comments and formatting must survive verbatim.
    assert plan.new_contents == {
        "app/core.py": (
            "# the central helper\n"
            "def calculate(x):\n"
            "    return x * 2\n"
            "\n"
            "def wrapper(x):\n"
            "    return calculate(x) + 1  # uses it locally\n"
        ),
        "app/user_from.py": (
            "from app.core import calculate\n"
            "\n"
            "def f(v):\n"
            "    return calculate(v)\n"
        ),
        "app/user_attr.py": (
            "import app.core\n"
            "\n"
            "def g(v):\n"
            "    return app.core.calculate(v)\n"
        ),
        "tests/test_core.py": (
            "from app.core import calculate\n"
            "def test_compute():\n"
            "    assert calculate(2) == 4\n"
        ),
    }
    # The originals captured for rollback are the untouched inputs.
    assert plan.originals.keys() == plan.new_contents.keys()
    assert plan.originals["app/core.py"].startswith("# the central helper\ndef compute(x):")


def test_characterization_blocker_plan_is_pinned(tmp_path):
    """A refusal: an ambiguous definition yields exactly this blocker and no edits."""
    _project(tmp_path)
    (tmp_path / "app" / "other.py").write_text("def compute(y):\n    return y\n")
    plan = plan_rename(tmp_path, "compute", "calculate")

    assert plan.ok is False
    assert plan.new_contents == {}
    assert plan.edits_by_file == {}
    assert plan.blockers == [
        "'compute' is defined in 2 modules (app/core.py, app/other.py) — ambiguous"
    ]


def test_characterization_invalid_name_blocker_pinned(tmp_path):
    """Up-front name refusals fire before any file is read, in old/new/equality order."""
    _project(tmp_path)
    assert plan_rename(tmp_path, "with", "calculate").blockers == [
        "'with' is not a valid identifier"]
    assert plan_rename(tmp_path, "compute", "for").blockers == [
        "'for' is not a valid identifier"]
    assert plan_rename(tmp_path, "compute", "compute").blockers == [
        "old and new names are identical"]


# --- the shared single-file rewrite: non-library + test/fixture refusal -------
# ``plan_source_rewrite`` is the one shared shape every single-file develop
# objective (add-final, freeze-dataclass, document-signature, infer-type-hints, …)
# reuses. The round-19 re-audit F4 found the WHOLE family could fire on packaging /
# config / task scripts (``@final`` had landed on a class in ``docs/conf.py``); the
# gate below is the single place that now stops all of them.

def _upper(source: str) -> str:
    """A trivial always-changing transform — proves the rewrite actually ran."""
    return source.upper()


def test_is_non_library_file_denylist_only():
    # Denylisted packaging / config / task / generated basenames are non-library at
    # ANY path (root OR inside a package) ...
    for rel in ("setup.py", "conf.py", "docs/conf.py", "noxfile.py", "conftest.py",
                "manage.py", "tasks.py", "pkg/_version.py", "a/b/version.py"):
        assert _is_non_library_file(rel), rel
    # ... but a real module is a library file even with NO ``__init__.py`` beside it
    # (a PEP-420 namespace package, or a loose top-level module). The gate is
    # deliberately denylist-only so it never drops genuine source.
    for rel in ("app/core.py", "app/intent/parser.py", "loose.py",
                "scripts/tool.py", "pkg/__init__.py"):
        assert not _is_non_library_file(rel), rel


def test_plan_source_rewrite_skips_non_library_file(tmp_path):
    # A denylisted config file is a HONEST no-op — read AND transform are skipped, so
    # even though ``_upper`` would change every byte, nothing is recorded.
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "conf.py").write_text("project = 'x'\n", encoding="utf-8")
    (tmp_path / "setup.py").write_text("from setuptools import setup\n", encoding="utf-8")
    for rel in ("docs/conf.py", "setup.py"):
        plan = plan_source_rewrite(tmp_path, rel, "upper", _upper)
        assert not plan.new_contents and not plan.originals and not plan.blockers


def test_plan_source_rewrite_processes_real_library_module(tmp_path):
    # A real package module (``pkg/__init__.py`` present) IS processed ...
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "module.py").write_text("x = 1\n", encoding="utf-8")
    plan = plan_source_rewrite(tmp_path, "pkg/module.py", "upper", _upper)
    assert plan.new_contents == {"pkg/module.py": "X = 1\n"}
    assert plan.edits_by_file == {"pkg/module.py": 1}

    # ... and so is a PEP-420 namespace-package module (NO ``__init__.py`` beside it)
    # — the gate must not refuse genuine source just because the dir lacks one.
    (tmp_path / "ns").mkdir()
    (tmp_path / "ns" / "leaf.py").write_text("y = 2\n", encoding="utf-8")
    nsplan = plan_source_rewrite(tmp_path, "ns/leaf.py", "upper", _upper)
    assert nsplan.new_contents == {"ns/leaf.py": "Y = 2\n"}


def test_plan_source_rewrite_still_refuses_test_and_fixture(tmp_path):
    # The pre-existing test/fixture refusal is intact, layered beside the new gate.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "sample.py").write_text("y = 2\n", encoding="utf-8")
    assert not plan_source_rewrite(tmp_path, "tests/test_x.py", "upper", _upper).new_contents
    assert not plan_source_rewrite(tmp_path, "fixtures/sample.py", "upper", _upper).new_contents


def test_plan_source_rewrite_unchanged_and_unreadable_are_noops(tmp_path):
    # A transform that returns the source unchanged, or returns None, or an
    # unreadable path: all honest no-ops (empty plan, no blocker).
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "m.py").write_text("x = 1\n", encoding="utf-8")
    assert not plan_source_rewrite(tmp_path, "pkg/m.py", "id", lambda s: s).new_contents
    assert not plan_source_rewrite(tmp_path, "pkg/m.py", "none", lambda s: None).new_contents
    missing = plan_source_rewrite(tmp_path, "pkg/gone.py", "upper", _upper)
    assert not missing.new_contents and not missing.blockers
