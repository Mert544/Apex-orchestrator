"""Apex's immune posture — ``app/reporting/immune_report`` + ``apex immune``.

Pins the fast, deterministic blind-spot ranking (many callable functions + no
linked test = highest risk) and the honest apply delegation to strengthen-tests.
"""

from __future__ import annotations

from pathlib import Path

from app.reporting.immune_report import (
    _has_linked_test,
    immune_posture,
    render_immune_markdown,
)


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _project(tmp_path: Path) -> Path:
    _write(tmp_path, "app/__init__.py", "")
    # wide + untested (2 public funcs, no linked test) -> highest risk
    _write(tmp_path, "app/wide.py",
           "def a(x):\n    return x\ndef b(y):\n    return y\n")
    # has a linked test -> lower risk
    _write(tmp_path, "app/covered.py", "def c(z):\n    return z\n")
    _write(tmp_path, "tests/test_covered.py",
           "from app.covered import c\ndef test_c():\n    assert c(1) == 1\n")
    # no blindly-callable public function -> not a candidate at all
    _write(tmp_path, "app/private.py", "def _hidden(x):\n    return x\n")
    return tmp_path


def test_ranks_untested_wide_module_first(tmp_path):
    posture = immune_posture(_project(tmp_path))
    mods = [r["module"] for r in posture["top_risk"]]
    assert mods[0] == "app/wide.py"                  # untested + widest
    assert "app/covered.py" in mods                  # candidate but lower
    assert "app/private.py" not in mods              # no callable public fn


def test_reports_signals_per_module(tmp_path):
    posture = immune_posture(_project(tmp_path))
    by_mod = {r["module"]: r for r in posture["top_risk"]}
    assert by_mod["app/wide.py"]["callable_funcs"] == 2
    assert by_mod["app/wide.py"]["has_linked_test"] is False
    assert by_mod["app/covered.py"]["has_linked_test"] is True


def test_has_linked_test_detects_named_and_suffixed(tmp_path):
    _write(tmp_path, "tests/test_foo.py", "")
    _write(tmp_path, "tests/test_bar_edges.py", "")
    assert _has_linked_test(tmp_path, "app/foo.py") is True
    assert _has_linked_test(tmp_path, "app/bar.py") is True
    assert _has_linked_test(tmp_path, "app/baz.py") is False


def test_has_linked_test_detects_private_module_tested_without_underscore(tmp_path):
    # A private module `_apply_verify.py` is conventionally tested under a name
    # WITHOUT the leading underscore (`test_apply_verify_shared.py`); the raw
    # `test__apply_verify*` glob would miss it and cry wolf. The underscore-strip
    # must find it, while a genuinely-untested private module stays blind.
    _write(tmp_path, "tests/test_apply_verify_shared.py", "")
    assert _has_linked_test(tmp_path, "app/execution/_apply_verify.py") is True
    assert _has_linked_test(tmp_path, "app/execution/_never_tested.py") is False


def test_is_deterministic(tmp_path):
    root = _project(tmp_path)
    assert immune_posture(root) == immune_posture(root)


def test_top_bounds_the_list(tmp_path):
    assert len(immune_posture(_project(tmp_path), top=1)["top_risk"]) == 1
    assert immune_posture(_project(tmp_path), top=0)["top_risk"] == []


def test_empty_project_is_honest(tmp_path):
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/only_private.py", "def _p(x):\n    return x\n")
    posture = immune_posture(tmp_path)
    assert posture["top_risk"] == []
    assert "nothing to immunise" in render_immune_markdown(posture)


def test_markdown_flags_untested_modules(tmp_path):
    md = render_immune_markdown(immune_posture(_project(tmp_path)))
    assert "Immune posture" in md
    assert "app/wide.py" in md
    assert "no linked test" in md


def test_cli_immune_report_json_and_text(tmp_path, capsys):
    import argparse

    from app.cli_insight import cmd_immune
    root = _project(tmp_path)
    rc = cmd_immune(argparse.Namespace(
        target=str(root), top=20, apply=False, json=True))
    assert rc == 0
    assert '"module": "app/wide.py"' in capsys.readouterr().out

    rc = cmd_immune(argparse.Namespace(
        target=str(root), top=20, apply=False, json=False))
    assert rc == 0
    assert "blindest" in capsys.readouterr().out


def test_cli_immune_apply_is_honest_when_nothing_lands(tmp_path, capsys):
    import argparse

    from app.cli_insight import cmd_immune
    # a project whose only public fn is already covered -> no killable survivor
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/pass_through.py", "def echo(x):\n    return x\n")
    _write(tmp_path, "tests/test_pass_through.py",
           "from app.pass_through import echo\ndef test_echo():\n    assert echo(7) == 7\n")
    _write(tmp_path, "pyproject.toml", "[project]\nname='d'\nversion='0'\n")
    rc = cmd_immune(argparse.Namespace(
        target=str(tmp_path), top=20, apply=True, max_modules=1, json=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert '"count": 0' in out
