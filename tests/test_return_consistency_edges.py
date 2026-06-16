"""Edge / error-path tests for the return-consistency analyzer.

Targets the branches the basic suite leaves uncovered: nested-def/lambda return
ownership, generator early-exit, the structural ``_block_always_exits`` proofs
for ``with``/``try``/empty blocks, the ``max_files`` cap, and the unreadable-file
skip. Deterministic and hermetic (``tmp_path`` only).
"""

from __future__ import annotations

import ast

from app.tools.return_consistency import (
    _block_always_exits,
    _classify_function,
    _is_generator,
    _own_returns,
    analyze_return_consistency,
)


def _fn(src: str):
    """Parse a single top-level function and return its AST node."""
    tree = ast.parse(src)
    return tree.body[0]


def test_nested_def_returns_not_owned_by_outer():
    # The inner def's value-return must NOT be counted as the outer's; the outer
    # only owns its own bare return -> no value-bearing return -> not flagged.
    fn = _fn(
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return\n"
    )
    owned = _own_returns(fn)
    assert len(owned) == 1
    assert owned[0].value is None
    assert _classify_function(fn) is None


def test_lambda_inside_function_is_skipped():
    # A lambda body is another callable; walking must stop at it. The outer owns
    # only its value return -> consistent, not flagged.
    fn = _fn(
        "def f():\n"
        "    g = lambda x: x + 1\n"
        "    return g\n"
    )
    assert len(_own_returns(fn)) == 1
    assert _classify_function(fn) is None


def test_generator_early_exit_with_nested_def():
    # A nested def appears BEFORE the yield; the generator walk must skip the
    # nested def and still find the outer yield (exercises the nested-skip and
    # the found-early-return branches).
    fn = _fn(
        "def gen():\n"
        "    def helper():\n"
        "        return 1\n"
        "    yield 1\n"
        "    yield 2\n"
    )
    assert _is_generator(fn) is True


def test_with_block_that_exits_is_not_fall_through(tmp_path):
    # The else-branch ends in a ``with`` whose body returns -> the block always
    # exits, so no implicit fall-through despite the value return above.
    src = (
        "def f(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        "    else:\n"
        "        with open('x') as fh:\n"
        "            return fh.read()\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    rc = analyze_return_consistency(tmp_path)
    assert rc.offenders == []


def test_try_finally_exit_block():
    fn = _fn(
        "def f():\n"
        "    try:\n"
        "        x = 1\n"
        "    finally:\n"
        "        return x\n"
    )
    assert _block_always_exits(fn.body) is True


def test_try_all_paths_exit_via_body_and_handlers():
    # No finally; body returns and the single handler returns -> always exits.
    fn = _fn(
        "def f():\n"
        "    try:\n"
        "        return 1\n"
        "    except ValueError:\n"
        "        return 2\n"
    )
    assert _block_always_exits(fn.body) is True


def test_try_handler_falls_through_means_not_exit():
    # The except handler does NOT return -> the try can fall through.
    fn = _fn(
        "def f():\n"
        "    try:\n"
        "        return 1\n"
        "    except ValueError:\n"
        "        x = 2\n"
    )
    assert _block_always_exits(fn.body) is False


def test_try_else_used_when_present():
    # An else is present; the body branch is replaced by the else for the exit
    # proof. Here the else does NOT exit -> not always-exiting.
    fn = _fn(
        "def f():\n"
        "    try:\n"
        "        x = 1\n"
        "    except ValueError:\n"
        "        return 2\n"
        "    else:\n"
        "        y = 3\n"
    )
    assert _block_always_exits(fn.body) is False


def test_empty_block_does_not_always_exit():
    assert _block_always_exits([]) is False


def test_try_falls_through_flags_function(tmp_path):
    # A value return in the try body, but no finally and the body itself can fall
    # through (no return/raise as last stmt) -> implicit fall-through.
    src = (
        "def f(flag):\n"
        "    try:\n"
        "        if flag:\n"
        "            return 1\n"
        "    except ValueError:\n"
        "        return 2\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    rc = analyze_return_consistency(tmp_path)
    assert rc.offenders[0]["reason"] == "implicit-fall-through"


def test_max_files_cap_stops_scanning(tmp_path):
    # Two offender files but max_files=1: only the first (sorted) is scanned.
    src = (
        "def f(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        "    return\n"
    )
    (tmp_path / "a.py").write_text(src, encoding="utf-8")
    (tmp_path / "b.py").write_text(src, encoding="utf-8")
    rc = analyze_return_consistency(tmp_path, max_files=1)
    assert [o["module"] for o in rc.offenders] == ["a.py"]


def test_unreadable_file_is_skipped(tmp_path, monkeypatch):
    # Force read_text to raise OSError to exercise the except-OSError continue.
    import app.tools.return_consistency as mod

    src = (
        "def f(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        "    return\n"
    )
    good = tmp_path / "good.py"
    good.write_text(src, encoding="utf-8")
    bad = tmp_path / "bad.py"
    bad.write_text(src, encoding="utf-8")

    real_read = mod.Path.read_text

    def fake_read(self, *args, **kwargs):
        if self.name == "bad.py":
            raise OSError("boom")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(mod.Path, "read_text", fake_read)
    rc = analyze_return_consistency(tmp_path)
    assert [o["module"] for o in rc.offenders] == ["good.py"]
