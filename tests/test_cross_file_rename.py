"""Cross-file rename: definition + imports + call sites, conservatively."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.execution.cross_file_rename import apply_rename, plan_rename


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
