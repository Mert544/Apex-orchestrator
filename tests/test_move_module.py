"""Module move/rename: every import form rewritten, conservatively."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.execution.move_module import apply_move, plan_move


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "helpers.py").write_text(
        "# helper module\n"
        "def double(x):\n"
        "    return x * 2\n"
    )
    (tmp_path / "app" / "user_import.py").write_text(
        "import app.helpers\n"
        "\n"
        "def f(v):\n"
        "    return app.helpers.double(v)  # qualified use\n"
    )
    (tmp_path / "app" / "user_from.py").write_text(
        "from app.helpers import double\n"
        "\n"
        "def g(v):\n"
        "    return double(v)\n"
    )
    (tmp_path / "app" / "user_pkg.py").write_text(
        "from app import helpers\n"
        "\n"
        "def h(v):\n"
        "    return helpers.double(v)\n"
    )
    (tmp_path / "tests" / "test_helpers.py").write_text(
        "from app.helpers import double\n"
        "def test_double():\n"
        "    assert double(2) == 4\n"
    )
    return tmp_path


def test_plan_rewrites_every_import_form(tmp_path):
    _project(tmp_path)
    plan = plan_move(tmp_path, "app/helpers.py", "app/util/math_helpers.py")
    assert plan.ok, plan.blockers
    # `import app.helpers` + qualified usages.
    ui = plan.new_contents["app/user_import.py"]
    assert "import app.util.math_helpers" in ui
    assert "return app.util.math_helpers.double(v)  # qualified use" in ui
    # `from app.helpers import double` — module path rewritten, name untouched.
    assert "from app.util.math_helpers import double" in plan.new_contents["app/user_from.py"]
    assert "from app.util.math_helpers import double" in plan.new_contents["tests/test_helpers.py"]
    # `from app import helpers` — parent AND stem rewritten, usages renamed.
    upkg = plan.new_contents["app/user_pkg.py"]
    assert "from app.util import math_helpers" in upkg
    assert "return math_helpers.double(v)" in upkg
    # The moved file's own content is preserved (comment included).
    assert plan.moved_content.startswith("# helper module\n")
    # The new package needs an __init__.py.
    assert plan.init_files == ["app/util/__init__.py"]


def test_aliased_imports_leave_usages_untouched(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "user_alias.py").write_text(
        "import app.helpers as hh\n"
        "from app import helpers as h2\n"
        "def k(v):\n"
        "    return hh.double(v) + h2.double(v)\n"
    )
    plan = plan_move(tmp_path, "app/helpers.py", "app/util/math_helpers.py")
    assert plan.ok, plan.blockers
    ua = plan.new_contents["app/user_alias.py"]
    assert "import app.util.math_helpers as hh" in ua
    assert "from app.util import math_helpers as h2" in ua
    assert "return hh.double(v) + h2.double(v)" in ua  # aliases keep working


def test_relative_import_of_moved_module_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "user_rel.py").write_text(
        "from .helpers import double\ndef r(v):\n    return double(v)\n")
    plan = plan_move(tmp_path, "app/helpers.py", "app/util/math_helpers.py")
    assert not plan.ok
    assert any("relative import" in b for b in plan.blockers)


def test_moved_file_with_relative_imports_blocks_on_dir_change(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "base.py").write_text("X = 1\n")
    (tmp_path / "app" / "helpers.py").write_text(
        "from .base import X\ndef double(x):\n    return x * 2 * X\n")
    plan = plan_move(tmp_path, "app/helpers.py", "app/util/math_helpers.py")
    assert not plan.ok
    assert any("relative imports and changes directory" in b for b in plan.blockers)
    # Same-directory rename is fine: relative imports stay valid.
    plan2 = plan_move(tmp_path, "app/helpers.py", "app/math_helpers.py")
    assert plan2.ok, plan2.blockers


def test_multi_alias_from_parent_blocks_when_parent_changes(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "other.py").write_text("Y = 2\n")
    (tmp_path / "app" / "user_multi.py").write_text(
        "from app import helpers, other\ndef m(v):\n    return helpers.double(v) + other.Y\n")
    plan = plan_move(tmp_path, "app/helpers.py", "app/util/math_helpers.py")
    assert not plan.ok
    assert any("split it manually" in b for b in plan.blockers)


def test_destination_and_source_validation(tmp_path):
    _project(tmp_path)
    assert not plan_move(tmp_path, "app/ghost.py", "app/new.py").ok
    assert not plan_move(tmp_path, "app/helpers.py", "app/user_from.py").ok   # exists
    assert not plan_move(tmp_path, "app/helpers.py", "app/__init__.py").ok    # dunder
    assert not plan_move(tmp_path, "app/helpers.py", "app/2bad/new.py").ok    # not importable


def test_string_reference_warns(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "dyn.py").write_text(
        "import importlib\ndef d():\n    return importlib.import_module('app.helpers')\n")
    plan = plan_move(tmp_path, "app/helpers.py", "app/util/math_helpers.py")
    assert plan.ok
    assert any("string literal 'app.helpers'" in w for w in plan.warnings)


def test_apply_moves_verifies_and_keeps_on_green(tmp_path):
    _project(tmp_path)
    plan = plan_move(tmp_path, "app/helpers.py", "app/util/math_helpers.py")
    res = apply_move(tmp_path, plan, verify=True)
    assert res["applied"] is True and res["verified"] is True
    assert not (tmp_path / "app" / "helpers.py").exists()
    assert (tmp_path / "app" / "util" / "math_helpers.py").read_text().startswith("# helper module")
    assert (tmp_path / "app" / "util" / "__init__.py").exists()


def test_apply_rolls_back_everything_on_red(tmp_path):
    _project(tmp_path)
    (tmp_path / "tests" / "test_red.py").write_text("def test_red():\n    assert False\n")
    before = (tmp_path / "app" / "helpers.py").read_text()
    plan = plan_move(tmp_path, "app/helpers.py", "app/util/math_helpers.py")
    res = apply_move(tmp_path, plan, verify=True)
    assert res["applied"] is False and res["rolled_back"] is True
    # Original world fully restored: file back, destination + new package gone.
    assert (tmp_path / "app" / "helpers.py").read_text() == before
    assert not (tmp_path / "app" / "util" / "math_helpers.py").exists()
    assert not (tmp_path / "app" / "util" / "__init__.py").exists()
    assert "import app.helpers" in (tmp_path / "app" / "user_import.py").read_text()


def test_cli_move_dry_run_and_apply(tmp_path, capsys):
    from app.cli import cmd_move

    _project(tmp_path)
    ns = argparse.Namespace(src="app/helpers.py", dst="app/util/math_helpers.py",
                            target=str(tmp_path), dry_run=True, no_verify=False, json=False)
    assert cmd_move(ns) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "rename app/helpers.py -> app/util/math_helpers.py" in out
    assert (tmp_path / "app" / "helpers.py").exists()  # nothing changed

    ns.dry_run = False
    assert cmd_move(ns) == 0
    assert "tests pass" in capsys.readouterr().out
    assert not (tmp_path / "app" / "helpers.py").exists()


def test_cli_move_blocked_exits_nonzero(tmp_path, capsys):
    from app.cli import cmd_move

    _project(tmp_path)
    ns = argparse.Namespace(src="app/helpers.py", dst="app/user_from.py",
                            target=str(tmp_path), dry_run=False, no_verify=False, json=False)
    assert cmd_move(ns) == 1
    assert "⛔" in capsys.readouterr().out
