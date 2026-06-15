"""Parameter rename: def site + body + keyword call sites, conservatively."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.param_rename import plan_param_rename


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def scale(value, factor=2):\n"
        "    # factor controls the multiplier\n"
        "    return value * factor\n"
    )
    (tmp_path / "app" / "kw_user.py").write_text(
        "from app.core import scale\n"
        "\n"
        "def f(v):\n"
        "    return scale(v, factor=3)\n"
    )
    (tmp_path / "app" / "pos_user.py").write_text(
        "from app.core import scale\n"
        "\n"
        "def g(v):\n"
        "    return scale(v, 4)  # positional stays valid\n"
    )
    (tmp_path / "app" / "attr_user.py").write_text(
        "import app.core\n"
        "\n"
        "def h(v):\n"
        "    return app.core.scale(v, factor=5)\n"
    )
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import scale\n"
        "def test_scale():\n"
        "    assert scale(2, factor=3) == 6\n"
    )
    return tmp_path


def test_plan_covers_def_body_and_keyword_call_sites(tmp_path):
    _project(tmp_path)
    plan = plan_param_rename(tmp_path, "scale", "factor", "multiplier")
    assert plan.ok, plan.blockers
    core = plan.new_contents["app/core.py"]
    assert "def scale(value, multiplier=2):" in core
    assert "return value * multiplier" in core
    assert "# factor controls the multiplier" in core  # comments untouched
    assert "scale(v, multiplier=3)" in plan.new_contents["app/kw_user.py"]
    assert "app.core.scale(v, multiplier=5)" in plan.new_contents["app/attr_user.py"]
    assert "scale(2, multiplier=3)" in plan.new_contents["tests/test_core.py"]
    # Positional call sites are untouched by construction.
    assert "app/pos_user.py" not in plan.new_contents


def test_spaced_keyword_call_site_is_handled(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "spaced.py").write_text(
        "from app.core import scale\n"
        "def s(v):\n"
        "    return scale(v, factor = 7)\n"
    )
    plan = plan_param_rename(tmp_path, "scale", "factor", "multiplier")
    assert plan.ok, plan.blockers
    assert "scale(v, multiplier = 7)" in plan.new_contents["app/spaced.py"]


def test_nested_rebind_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "core.py").write_text(
        "def scale(value, factor=2):\n"
        "    def inner(factor):\n"
        "        return factor + 1\n"
        "    return value * factor + inner(0)\n"
    )
    plan = plan_param_rename(tmp_path, "scale", "factor", "multiplier")
    assert not plan.ok
    assert any("re-binds" in b for b in plan.blockers)


def test_signature_validation_blocks(tmp_path):
    _project(tmp_path)
    assert not plan_param_rename(tmp_path, "ghost", "factor", "m").ok       # no function
    assert not plan_param_rename(tmp_path, "scale", "nope", "m").ok        # not a param
    assert not plan_param_rename(tmp_path, "scale", "factor", "value").ok  # already a param
    assert not plan_param_rename(tmp_path, "scale", "factor", "with").ok   # keyword


def test_dict_expansion_call_warns(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "dyn.py").write_text(
        "from app.core import scale\n"
        "def d(v, opts):\n"
        "    return scale(v, **opts)\n"
    )
    plan = plan_param_rename(tmp_path, "scale", "factor", "multiplier")
    assert plan.ok
    assert any("may still carry 'factor'" in w for w in plan.warnings)


def test_apply_verifies_and_rolls_back(tmp_path):
    _project(tmp_path)
    res = apply_rename(tmp_path, plan_param_rename(tmp_path, "scale", "factor", "multiplier"),
                       verify=True)
    assert res["applied"] is True and res["verified"] is True
    assert "multiplier=2" in (tmp_path / "app" / "core.py").read_text()

    # Now a red suite: everything must come back.
    (tmp_path / "tests" / "test_red.py").write_text("def test_red():\n    assert False\n")
    before = (tmp_path / "app" / "core.py").read_text()
    res2 = apply_rename(tmp_path, plan_param_rename(tmp_path, "scale", "multiplier", "k"),
                        verify=True)
    assert res2["applied"] is False and res2["rolled_back"] is True
    assert (tmp_path / "app" / "core.py").read_text() == before


def _snapshot(plan):
    """A stable, comparable view of a plan: edits + blockers + warnings."""
    return {
        "ok": plan.ok,
        "defined_in": plan.defined_in,
        "new_contents": dict(sorted(plan.new_contents.items())),
        "edits_by_file": dict(sorted(plan.edits_by_file.items())),
        "blockers": list(plan.blockers),
        "warnings": list(plan.warnings),
    }


def test_characterization_rewrite_plan_is_pinned(tmp_path):
    """Pin the full plan (edits + counts + warnings) for the canonical rewrite.

    Guards the behaviour-preserving decomposition of ``plan_param_rename``: any
    change to located spans, edit counts, ordering, or warnings trips this.
    """
    _project(tmp_path)
    (tmp_path / "app" / "dyn.py").write_text(
        "from app.core import scale\n"
        "def d(v, opts):\n"
        "    return scale(v, **opts)\n"
    )
    snap = _snapshot(plan_param_rename(tmp_path, "scale", "factor", "multiplier"))

    assert snap["ok"] is True
    assert snap["defined_in"] == "app/core.py"
    assert snap["new_contents"] == {
        "app/attr_user.py": (
            "import app.core\n"
            "\n"
            "def h(v):\n"
            "    return app.core.scale(v, multiplier=5)\n"
        ),
        "app/core.py": (
            "def scale(value, multiplier=2):\n"
            "    # factor controls the multiplier\n"
            "    return value * multiplier\n"
        ),
        "app/kw_user.py": (
            "from app.core import scale\n"
            "\n"
            "def f(v):\n"
            "    return scale(v, multiplier=3)\n"
        ),
        "tests/test_core.py": (
            "from app.core import scale\n"
            "def test_scale():\n"
            "    assert scale(2, multiplier=3) == 6\n"
        ),
    }
    assert snap["edits_by_file"] == {
        "app/attr_user.py": 1,
        "app/core.py": 2,
        "app/kw_user.py": 1,
        "tests/test_core.py": 1,
    }
    assert snap["blockers"] == []
    assert snap["warnings"] == [
        "app/dyn.py:3: scale(**…) call — a dict may still carry 'factor'; check manually",
    ]


def test_characterization_refusal_plan_is_pinned(tmp_path):
    """Pin a refusal: nothing rewritten, exactly one blocker, no warnings."""
    _project(tmp_path)
    snap = _snapshot(plan_param_rename(tmp_path, "scale", "factor", "value"))

    assert snap["ok"] is False
    assert snap["defined_in"] == "app/core.py"
    assert snap["new_contents"] == {}
    assert snap["edits_by_file"] == {}
    assert snap["blockers"] == ["scale() already has a parameter 'value'"]
    assert snap["warnings"] == []


def test_cli_param_rename(tmp_path, capsys):
    from app.cli import cmd_rename

    _project(tmp_path)
    ns = argparse.Namespace(old="factor", new="multiplier", param="scale",
                            target=str(tmp_path), dry_run=True, no_verify=False, json=False)
    assert cmd_rename(ns) == 0
    out = capsys.readouterr().out
    assert "-def scale(value, factor=2):" in out
    assert "+def scale(value, multiplier=2):" in out

    ns.dry_run = False
    assert cmd_rename(ns) == 0
    assert "tests pass" in capsys.readouterr().out
    assert "multiplier=3" in (tmp_path / "app" / "kw_user.py").read_text()
