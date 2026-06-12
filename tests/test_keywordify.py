"""Keywordify: positional call sites become keywords — the drop-enabler."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.keywordify import plan_keywordify
from app.execution.param_drop import plan_param_drop


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def scale(value, factor=2, bias=0):\n"
        "    return value * factor + bias\n"
    )
    (tmp_path / "app" / "user.py").write_text(
        "from app.core import scale\n"
        "\n"
        "def f(v):\n"
        "    return scale(v, 4)  # positional today\n"
    )
    (tmp_path / "app" / "attr_user.py").write_text(
        "import app.core\n"
        "\n"
        "def h(v):\n"
        "    return app.core.scale(v, 5, 1)\n"
    )
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import scale\n"
        "def test_scale():\n"
        "    assert scale(2, factor=3) == 6\n"
    )
    return tmp_path


def test_positional_calls_become_keywords_everywhere(tmp_path):
    _project(tmp_path)
    plan = plan_keywordify(tmp_path, "scale")
    assert plan.ok, plan.blockers
    assert "scale(value=v, factor=4)  # positional today" in plan.new_contents["app/user.py"]
    assert "app.core.scale(value=v, factor=5, bias=1)" in plan.new_contents["app/attr_user.py"]
    # The mixed call keeps its existing keyword and gains one.
    assert "scale(value=2, factor=3)" in plan.new_contents["tests/test_core.py"]
    for text in plan.new_contents.values():
        ast.parse(text)


def test_posonly_params_stay_positional(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def cut(text, /, width=10):\n"
        "    return text[:width]\n"
        "\n"
        "def g(t):\n"
        "    return cut(t, 5)\n"
    )
    plan = plan_keywordify(tmp_path, "cut")
    assert plan.ok, plan.blockers
    assert "cut(t, width=5)" in plan.new_contents["app/m.py"]
    ast.parse(plan.new_contents["app/m.py"])


def test_call_feeding_varargs_is_left_alone_with_warning(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def join(sep, *parts):\n"
        "    return sep.join(parts)\n"
        "\n"
        "def g():\n"
        "    return join('-', 'a', 'b')\n"
    )
    plan = plan_keywordify(tmp_path, "join")
    assert not plan.blockers
    assert not plan.new_contents  # naming earlier args would strand the rest
    assert any("can't be named" in w for w in plan.warnings)


def test_starred_call_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "star.py").write_text(
        "from app.core import scale\n"
        "def g(xs):\n"
        "    return scale(*xs)\n"
    )
    plan = plan_keywordify(tmp_path, "scale")
    assert not plan.ok
    assert any("unknowable" in b for b in plan.blockers)
    assert not plan.new_contents


def test_wrapped_argument_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "wrapped.py").write_text(
        "from app.core import scale\n"
        "def g(v):\n"
        "    return scale((v), 4)\n"  # scale((value=v)...) would be a SyntaxError
    )
    plan = plan_keywordify(tmp_path, "scale")
    assert not plan.ok
    assert any("non-trivial spelling" in b for b in plan.blockers)


def test_multiline_call_converts_in_place(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "tall.py").write_text(
        "from app.core import scale\n"
        "def g(v):\n"
        "    return scale(v,\n"
        "                 4,\n"
        "                 1)\n"
    )
    plan = plan_keywordify(tmp_path, "scale")
    assert plan.ok, plan.blockers
    tall = plan.new_contents["app/tall.py"]
    assert "scale(value=v,\n" in tall
    assert "factor=4,\n" in tall
    assert "bias=1)" in tall
    ast.parse(tall)


def test_keywordify_then_drop_chains(tmp_path):
    # The whole point: a drop blocked on positional callers becomes
    # unblocked once keywordify has run.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def render(text, color=None):\n"
        "    return text\n"
        "\n"
        "def g(t):\n"
        "    return render(t, 'red')\n"
    )
    assert not plan_param_drop(tmp_path, "render", "color").ok  # positional caller

    res = apply_rename(tmp_path, plan_keywordify(tmp_path, "render"), verify=False)
    assert res["applied"] is True

    drop = plan_param_drop(tmp_path, "render", "color")
    assert drop.ok, drop.blockers
    assert "def render(text):" in drop.new_contents["app/m.py"]
    assert "render(text=t)" in drop.new_contents["app/m.py"]


def test_cli_signature_keywordify(tmp_path, capsys):
    from app.cli import cmd_signature

    _project(tmp_path)
    ns = argparse.Namespace(op="keywordify", function="scale", param="",
                            default="", target=str(tmp_path), dry_run=True,
                            no_verify=False, json=False)
    assert cmd_signature(ns) == 0
    out = capsys.readouterr().out
    assert "-    return scale(v, 4)" in out
    assert "+    return scale(value=v, factor=4)" in out

    ns.dry_run = False
    assert cmd_signature(ns) == 0
    assert "tests pass" in capsys.readouterr().out
    assert "scale(value=v, factor=4)" in (tmp_path / "app" / "user.py").read_text()
