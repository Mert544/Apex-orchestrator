"""Tests for extract_method.plan_extract — the data-flow extract-method hand."""

from __future__ import annotations

import argparse

import pytest

from app.execution.extract_method import plan_extract


def _write(tmp_path, rel, src):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return p


def test_extract_computes_params_and_returns(tmp_path):
    _write(tmp_path, "m.py",
           "def process(data):\n"
           "    total = 0\n"
           "    count = 0\n"
           "    for x in data:\n"
           "        total += x\n"
           "        count += 1\n"
           "    mean = total / count\n"
           "    return mean\n")
    plan = plan_extract(str(tmp_path), "m.py", 4, 6, "_accumulate")
    assert not plan.blockers
    new = plan.new_contents["m.py"]
    # Params are the live-in names (read from prior scope), returns the live-out.
    assert "def _accumulate(count, data, total):" in new
    assert "return count, total" in new
    assert "count, total = _accumulate(count, data, total)" in new
    # The helper is inserted above the function it came from.
    assert new.index("def _accumulate") < new.index("def process")


def test_extract_no_live_out_makes_void_call(tmp_path):
    _write(tmp_path, "m.py",
           "def f(items):\n"
           "    print('start')\n"
           "    for it in items:\n"
           "        print(it)\n"
           "    print('done')\n")
    plan = plan_extract(str(tmp_path), "m.py", 3, 4, "_show")
    assert not plan.blockers
    new = plan.new_contents["m.py"]
    assert "def _show(items):" in new
    assert "    _show(items)\n" in new
    assert "return" not in new.split("def f")[0]  # helper has no return


def test_extract_method_passes_self_as_param(tmp_path):
    _write(tmp_path, "c.py",
           "class Calc:\n"
           "    def run(self, items):\n"
           "        acc = 0\n"
           "        for it in items:\n"
           "            acc += it * self.factor\n"
           "        return acc\n")
    plan = plan_extract(str(tmp_path), "c.py", 4, 5, "_loop")
    assert not plan.blockers
    new = plan.new_contents["c.py"]
    assert "self" in new.split("class Calc")[0]  # helper references self
    # Helper is module-level, above the class.
    assert new.index("def _loop") < new.index("class Calc")


def test_return_in_range_blocks(tmp_path):
    _write(tmp_path, "r.py",
           "def f(x):\n"
           "    y = x + 1\n"
           "    if y > 0:\n"
           "        return y\n"
           "    z = y * 2\n"
           "    return z\n")
    plan = plan_extract(str(tmp_path), "r.py", 2, 4, "_h")
    assert any("return" in b for b in plan.blockers)
    assert not plan.new_contents


def test_yield_in_range_blocks(tmp_path):
    _write(tmp_path, "g.py",
           "def gen(n):\n"
           "    i = 0\n"
           "    while i < n:\n"
           "        yield i\n"
           "        i += 1\n")
    plan = plan_extract(str(tmp_path), "g.py", 3, 5, "_h")
    assert plan.blockers
    assert not plan.new_contents


def test_nested_function_in_range_blocks(tmp_path):
    _write(tmp_path, "n.py",
           "def outer(x):\n"
           "    a = x + 1\n"
           "    def inner():\n"
           "        return a\n"
           "    return inner()\n")
    plan = plan_extract(str(tmp_path), "n.py", 2, 4, "_h")
    assert any("nested function" in b for b in plan.blockers)


def test_partial_loop_body_range_blocks(tmp_path):
    # Lines 3-4 are INSIDE the for-loop, not top-level statements of the
    # function body — the selection can't snap to a complete statement run.
    _write(tmp_path, "b.py",
           "def f(items):\n"
           "    for it in items:\n"
           "        if it:\n"
           "            break\n"
           "        print(it)\n")
    plan = plan_extract(str(tmp_path), "b.py", 3, 4, "_h")
    assert any("contiguous run" in b for b in plan.blockers)
    assert not plan.new_contents


def test_whole_loop_with_break_extracts_cleanly(tmp_path):
    # When the ENTIRE loop is selected, an inner break stays with its loop —
    # the extraction is valid (break is not a blocker in a complete selection).
    _write(tmp_path, "b.py",
           "def f(items):\n"
           "    found = None\n"
           "    for it in items:\n"
           "        if it:\n"
           "            found = it\n"
           "            break\n"
           "    return found\n")
    plan = plan_extract(str(tmp_path), "b.py", 3, 6, "_scan")
    assert not plan.blockers
    assert "def _scan(items):" in plan.new_contents["b.py"]


def test_name_collision_blocks(tmp_path):
    _write(tmp_path, "n.py",
           "def existing():\n"
           "    pass\n"
           "\n"
           "def g():\n"
           "    a = 1\n"
           "    b = a + 1\n"
           "    return b\n")
    plan = plan_extract(str(tmp_path), "n.py", 5, 6, "existing")
    assert any("already defined" in b for b in plan.blockers)


def test_invalid_helper_name_blocks(tmp_path):
    _write(tmp_path, "m.py", "def f():\n    a = 1\n    b = 2\n    return a + b\n")
    plan = plan_extract(str(tmp_path), "m.py", 2, 3, "not a name")
    assert any("valid function name" in b for b in plan.blockers)


def test_range_outside_function_blocks(tmp_path):
    _write(tmp_path, "m.py", "x = 1\ny = 2\n\ndef f():\n    return x\n")
    plan = plan_extract(str(tmp_path), "m.py", 1, 2, "_h")
    assert any("aren't inside one top-level" in b for b in plan.blockers)


def test_noncontiguous_or_empty_range_blocks(tmp_path):
    _write(tmp_path, "m.py", "def f(x):\n    return x\n")
    # The range covers only the return — but return blocks anyway; use a body
    # range that snaps to nothing complete.
    plan = plan_extract(str(tmp_path), "m.py", 1, 1, "_h")
    # Line 1 is the def line — no complete body statement fully inside.
    assert plan.blockers


def test_start_after_end_blocks(tmp_path):
    _write(tmp_path, "m.py", "def f():\n    a = 1\n    b = 2\n    return a + b\n")
    plan = plan_extract(str(tmp_path), "m.py", 3, 2, "_h")
    assert any("start line must be" in b for b in plan.blockers)


def test_unreadable_file_blocks(tmp_path):
    plan = plan_extract(str(tmp_path), "missing.py", 1, 2, "_h")
    assert any("cannot read" in b for b in plan.blockers)


def test_syntax_error_file_blocks(tmp_path):
    _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    plan = plan_extract(str(tmp_path), "bad.py", 1, 2, "_h")
    assert any("doesn't parse" in b for b in plan.blockers)


def test_extracted_result_parses_and_is_equivalent(tmp_path):
    # Functional check: the extracted version computes the same result.
    src = ("def compute(nums):\n"
           "    scaled = []\n"
           "    for n in nums:\n"
           "        scaled.append(n * 3)\n"
           "    out = sum(scaled)\n"
           "    return out\n")
    _write(tmp_path, "m.py", src)
    plan = plan_extract(str(tmp_path), "m.py", 2, 4, "_scale")
    assert not plan.blockers
    new = plan.new_contents["m.py"]
    ns_old: dict = {}
    ns_new: dict = {}
    exec(compile(src, "old", "exec"), ns_old)
    exec(compile(new, "new", "exec"), ns_new)
    assert ns_old["compute"]([1, 2, 3]) == ns_new["compute"]([1, 2, 3]) == 18


def test_cmd_extract_apply_and_dry_run(tmp_path, capsys):
    from app.cli_refactor import cmd_extract

    src = ("def process(data):\n"
           "    total = 0\n"
           "    for x in data:\n"
           "        total += x\n"
           "    return total\n")
    _write(tmp_path, "m.py", src)

    # Dry run shows a diff, changes nothing.
    rc = cmd_extract(argparse.Namespace(
        file="m.py", start=3, end=4, name="_sum", target=str(tmp_path),
        dry_run=True, no_verify=True, json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry run" in out.lower()
    assert (tmp_path / "m.py").read_text() == src  # untouched

    # Real apply (no-verify since there's no test suite) rewrites the file.
    rc = cmd_extract(argparse.Namespace(
        file="m.py", start=3, end=4, name="_sum", target=str(tmp_path),
        dry_run=False, no_verify=True, json=False))
    assert rc == 0
    assert "def _sum(" in (tmp_path / "m.py").read_text()


def test_cmd_extract_blocked_returns_one(tmp_path, capsys):
    from app.cli_refactor import cmd_extract

    _write(tmp_path, "m.py", "def f(x):\n    return x\n")
    rc = cmd_extract(argparse.Namespace(
        file="m.py", start=2, end=2, name="_h", target=str(tmp_path),
        dry_run=False, no_verify=True, json=False))
    assert rc == 1
    assert "blocked" in capsys.readouterr().out.lower()
