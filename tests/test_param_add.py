"""Parameter add: a safe default keeps every existing call site valid."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.param_add import plan_param_add


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url, timeout=10):\n"
        "    # the network seam\n"
        "    return f'{url}:{timeout}'\n"
    )
    (tmp_path / "app" / "user.py").write_text(
        "from app.core import fetch\n"
        "\n"
        "def f():\n"
        "    return fetch('a', timeout=5)\n"
    )
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import fetch\n"
        "def test_fetch():\n"
        "    assert fetch('a') == 'a:10'\n"
    )
    return tmp_path


def test_plan_appends_with_default(tmp_path):
    _project(tmp_path)
    plan = plan_param_add(tmp_path, "fetch", "retries", "3")
    assert plan.ok, plan.blockers
    core = plan.new_contents["app/core.py"]
    assert "def fetch(url, timeout=10, retries=3):" in core
    assert "# the network seam" in core  # comments untouched
    # Only the def site changes — defaults keep every caller valid.
    assert list(plan.new_contents) == ["app/core.py"]
    ast.parse(core)


def test_vararg_and_kwonly_get_keyword_only_placement(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "shapes.py").write_text(
        "def star_fn(a, *items):\n"
        "    return a + len(items)\n"
        "\n"
        "def kw_fn(a, *, flag=False):\n"
        "    return a\n"
        "\n"
        "def kwargs_fn(a, **extra):\n"
        "    return a + len(extra)\n"
        "\n"
        "def pos_fn(probe, /):\n"
        "    return probe\n"
    )
    # Before *args a trailing default would absorb positionals — must go after.
    plan = plan_param_add(tmp_path, "star_fn", "trace", "None")
    assert plan.ok, plan.blockers
    assert "def star_fn(a, *items, trace=None):" in plan.new_contents["app/shapes.py"]

    plan = plan_param_add(tmp_path, "kw_fn", "depth", "1")
    assert plan.ok, plan.blockers
    assert "def kw_fn(a, *, flag=False, depth=1):" in plan.new_contents["app/shapes.py"]

    plan = plan_param_add(tmp_path, "kwargs_fn", "retries", "3")
    assert plan.ok, plan.blockers
    assert "def kwargs_fn(a, retries=3, **extra):" in plan.new_contents["app/shapes.py"]

    plan = plan_param_add(tmp_path, "pos_fn", "rest", "0")
    assert plan.ok, plan.blockers
    assert "def pos_fn(probe, /, rest=0):" in plan.new_contents["app/shapes.py"]
    for text in plan.new_contents.values():
        ast.parse(text)


def test_validation_blocks(tmp_path):
    _project(tmp_path)
    assert not plan_param_add(tmp_path, "fetch", "with", "0").ok      # keyword
    assert not plan_param_add(tmp_path, "fetch", "no-dash", "0").ok   # identifier
    assert not plan_param_add(tmp_path, "fetch", "retries", "3 +").ok  # bad expr
    assert not plan_param_add(tmp_path, "ghost", "retries", "3").ok   # no function
    assert not plan_param_add(tmp_path, "fetch", "timeout", "0").ok   # already a param


def test_name_already_used_in_body_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "core.py").write_text(
        "LIMIT = 9\n"
        "def fetch(url):\n"
        "    return f'{url}:{LIMIT}'\n"
    )
    plan = plan_param_add(tmp_path, "fetch", "LIMIT", "1")
    assert not plan.ok
    assert any("already used inside" in b for b in plan.blockers)


def test_call_site_already_passing_keyword_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url, **extra):\n"
        "    return url, extra\n"
    )
    (tmp_path / "app" / "user.py").write_text(
        "from app.core import fetch\n"
        "def f():\n"
        "    return fetch('a', retries=2)\n"  # routes into **extra today
    )
    plan = plan_param_add(tmp_path, "fetch", "retries", "3")
    assert not plan.ok
    assert any("already passes" in b for b in plan.blockers)


def test_dict_expansion_call_warns(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "dyn.py").write_text(
        "from app.core import fetch\n"
        "def d(opts):\n"
        "    return fetch('a', **opts)\n"
    )
    plan = plan_param_add(tmp_path, "fetch", "retries", "3")
    assert plan.ok
    assert any("may already carry 'retries'" in w for w in plan.warnings)


def test_comment_inside_signature_blocks(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url,  # the endpoint\n"
        "          timeout=10):\n"
        "    return url\n"
    )
    plan = plan_param_add(tmp_path, "fetch", "retries", "3")
    assert not plan.ok
    assert any("comment" in b for b in plan.blockers)


def test_multiline_signature_collapses_cleanly(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "core.py").write_text(
        "def fetch(url,\n"
        "          timeout=10):\n"
        "    return f'{url}:{timeout}'\n"
    )
    plan = plan_param_add(tmp_path, "fetch", "retries", "3")
    assert plan.ok, plan.blockers
    assert "def fetch(url, timeout=10, retries=3):" in plan.new_contents["app/core.py"]


def test_apply_verifies_and_rolls_back(tmp_path):
    _project(tmp_path)
    res = apply_rename(tmp_path, plan_param_add(tmp_path, "fetch", "retries", "3"),
                       verify=True)
    assert res["applied"] is True and res["verified"] is True
    assert "retries=3" in (tmp_path / "app" / "core.py").read_text()

    # Now a red suite: everything must come back.
    (tmp_path / "tests" / "test_red.py").write_text("def test_red():\n    assert False\n")
    before = (tmp_path / "app" / "core.py").read_text()
    res2 = apply_rename(tmp_path, plan_param_add(tmp_path, "fetch", "verbose", "False"),
                        verify=True)
    assert res2["applied"] is False and res2["rolled_back"] is True
    assert (tmp_path / "app" / "core.py").read_text() == before


def test_cli_signature_add(tmp_path, capsys):
    from app.cli import cmd_signature

    _project(tmp_path)
    ns = argparse.Namespace(op="add", function="fetch", param="retries",
                            default="3", target=str(tmp_path), dry_run=True,
                            no_verify=False, json=False)
    assert cmd_signature(ns) == 0
    out = capsys.readouterr().out
    assert "-def fetch(url, timeout=10):" in out
    assert "+def fetch(url, timeout=10, retries=3):" in out

    ns.dry_run = False
    assert cmd_signature(ns) == 0
    assert "tests pass" in capsys.readouterr().out
    assert "retries=3" in (tmp_path / "app" / "core.py").read_text()


def test_characterization_pins_plan_across_paths(tmp_path):
    """Pin the exact plan for one happy path and every blocker/warning branch,
    so the helper decomposition stays byte-identical."""
    counter = [0]

    def plan_for(files, func, param, default):
        # Each case lives in its own subdir so earlier files never leak in.
        counter[0] += 1
        root = tmp_path / f"case{counter[0]}"
        root.mkdir()
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        out = plan_param_add(root, func, param, default)
        return out.defined_in, sorted(out.blockers), sorted(out.warnings), \
            dict(out.new_contents), dict(out.edits_by_file)

    # Happy path: only the def site changes, keyword-only placement preserved.
    defined, blockers, warnings, contents, edits = plan_for(
        {"app/s.py": "def star(a, *items):\n    return a\n"}, "star", "retries", "3")
    assert defined == "app/s.py" and not blockers and not warnings
    assert contents == {"app/s.py": "def star(a, *items, retries=3):\n    return a\n"}
    assert edits == {"app/s.py": 1}

    # Blocker: invalid identifier (no project even parsed).
    assert plan_for({}, "fn", "1bad", "3") == (
        "", ["'1bad' is not a valid identifier"], [], {}, {})

    # Blocker: default is not an expression.
    assert plan_for({}, "fn", "retries", "def x") == (
        "", ["default 'def x' is not a valid expression"], [], {}, {})

    # Blocker: not defined exactly once.
    assert plan_for({"a.py": "def fn(a):\n    return a\n",
                     "b.py": "def fn(b):\n    return b\n"}, "fn", "retries", "3") == (
        "", ["'fn' must be defined exactly once at top level (found 2)"], [], {}, {})

    # Blocker: parameter already exists.
    assert plan_for({"app/s.py": "def fn(a, retries=1):\n    return a\n"},
                    "fn", "retries", "3")[1] == [
        "fn() already has a parameter 'retries'"]

    # Blocker: the name is already used in the body.
    assert plan_for({"app/s.py": "def fn(a):\n    retries = 2\n    return retries\n"},
                    "fn", "retries", "3")[1] == [
        "'retries' is already used inside fn() — adding the "
        "parameter would change what that name means"]

    # Blocker: a comment inside the signature block.
    assert plan_for({"app/s.py": "def fn(\n    a,  # first\n):\n    return a\n"},
                    "fn", "retries", "3")[1] == [
        "app/s.py: the signature block contains a comment — rebuilding "
        "it would drop the comment, so this stays a human edit"]

    # Blocker: a call site already passes the keyword.
    assert plan_for(
        {"app/core.py": "def fetch(url):\n    return url\n",
         "app/user.py": "from app.core import fetch\n"
                        "def f():\n    return fetch('a', retries=9)\n"},
        "fetch", "retries", "3")[1] == [
        "app/user.py:3: a call already passes 'retries=' — adding the "
        "parameter would rewire it"]

    # Warning: an f(**…) call site may already carry the param at runtime.
    _, blk, warn, _, _ = plan_for(
        {"app/core.py": "def fetch(url):\n    return url\n",
         "app/user.py": "from app.core import fetch\n"
                        "def f(d):\n    return fetch('a', **d)\n"},
        "fetch", "retries", "3")
    assert not blk
    assert warn == [
        "app/user.py:3: fetch(**…) may already carry 'retries' at "
        "runtime; check manually"]
