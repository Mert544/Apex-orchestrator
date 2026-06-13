"""Parameter reorder: def site rebuilt, keyword callers untouched by design."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.keywordify import plan_keywordify
from app.execution.param_reorder import plan_param_reorder


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url: str, timeout=10, retries=3):\n"
        "    # the network seam\n"
        "    return f'{url}:{timeout}:{retries}'\n"
    )
    (tmp_path / "app" / "user.py").write_text(
        "from app.core import fetch\n"
        "\n"
        "def f():\n"
        "    return fetch(url='a', retries=1, timeout=5)\n"
    )
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import fetch\n"
        "def test_fetch():\n"
        "    assert fetch(url='a') == 'a:10:3'\n"
    )
    return tmp_path


def test_reorder_rebuilds_def_and_leaves_keyword_callers_alone(tmp_path):
    _project(tmp_path)
    plan = plan_param_reorder(tmp_path, "fetch", ["url", "retries", "timeout"])
    assert plan.ok, plan.blockers
    core = plan.new_contents["app/core.py"]
    assert "def fetch(url: str, retries=3, timeout=10):" in core
    assert "# the network seam" in core            # comments survive
    assert list(plan.new_contents) == ["app/core.py"]  # callers untouched
    ast.parse(core)


def test_positional_caller_blocks_with_keywordify_hint(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "pos.py").write_text(
        "from app.core import fetch\n"
        "def g():\n"
        "    return fetch('a', 5)\n"
    )
    plan = plan_param_reorder(tmp_path, "fetch", ["url", "retries", "timeout"])
    assert not plan.ok
    assert any("keywordify" in b for b in plan.blockers)
    assert not plan.new_contents


def test_keywordify_then_reorder_chains(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "pos.py").write_text(
        "from app.core import fetch\n"
        "def g():\n"
        "    return fetch('a', 5)\n"
    )
    res = apply_rename(tmp_path, plan_keywordify(tmp_path, "fetch"), verify=False)
    assert res["applied"] is True
    plan = plan_param_reorder(tmp_path, "fetch", ["url", "retries", "timeout"])
    assert plan.ok, plan.blockers


def test_permutation_and_compile_safety_block(tmp_path):
    _project(tmp_path)
    # Not a permutation (missing / unknown names).
    assert not plan_param_reorder(tmp_path, "fetch", ["url", "timeout"]).ok
    assert not plan_param_reorder(tmp_path, "fetch", ["url", "timeout", "ghost"]).ok
    # Identity order is a no-op, refused honestly.
    assert not plan_param_reorder(tmp_path, "fetch", ["url", "timeout", "retries"]).ok
    # Required-after-defaulted wouldn't compile.
    plan = plan_param_reorder(tmp_path, "fetch", ["timeout", "url", "retries"])
    assert not plan.ok
    assert any("wouldn't compile" in b for b in plan.blockers)


def test_posonly_vararg_and_kwonly_sections_stay_put(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def mix(key, /, a=0, b=1, *rest, flag=False, **extra):\n"
        "    return key, a, b, rest, flag, extra\n"
        "\n"
        "def g():\n"
        "    return mix(1, a=2, b=3, flag=True)\n"
    )
    plan = plan_param_reorder(tmp_path, "mix", ["b", "a"])
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/m.py"]
    # Only the regular section reordered; /, *rest, kwonly, **extra untouched.
    assert "def mix(key, /, b=1, a=0, *rest, flag=False, **extra):" in new
    # The posonly positional caller is fine: position 0 is still `key`.
    ast.parse(new)


def test_comment_inside_signature_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url,  # endpoint\n"
        "          timeout=10):\n"
        "    return url\n"
    )
    plan = plan_param_reorder(tmp_path, "fetch", ["timeout", "url"])
    assert not plan.ok
    assert any("comment" in b for b in plan.blockers)


def test_apply_verifies_and_cli_round_trip(tmp_path, capsys):
    from app.cli import cmd_signature

    _project(tmp_path)
    ns = argparse.Namespace(op="reorder", function="fetch",
                            param="url,retries,timeout", default="",
                            target=str(tmp_path), dry_run=True,
                            no_verify=False, json=False)
    assert cmd_signature(ns) == 0
    out = capsys.readouterr().out
    assert "-def fetch(url: str, timeout=10, retries=3):" in out
    assert "+def fetch(url: str, retries=3, timeout=10):" in out

    ns.dry_run = False
    assert cmd_signature(ns) == 0
    assert "tests pass" in capsys.readouterr().out
    assert "def fetch(url: str, retries=3, timeout=10):" in (
        tmp_path / "app" / "core.py").read_text()
