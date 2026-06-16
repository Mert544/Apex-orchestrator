"""Characterization: byte-identical proof for the ``plan_extract`` refactor.

Feeds many source inputs (valid extractions, every blocker path, edge/empty
cases) through the refactored ``plan_extract`` and compares the FULL plan output
(originals, new_contents, edits_by_file, blockers, warnings) against an
independent snapshot of the pre-refactor implementation captured from
``git show HEAD:app/execution/extract_method.py``. Zero mismatches required.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from app.execution.extract_method import plan_extract as plan_extract_new


def _load_original_plan_extract():
    """Import the pre-refactor module under a private name from `git show HEAD`."""
    repo = Path(__file__).resolve().parents[1]
    src = subprocess.run(
        ["git", "show", "HEAD:app/execution/extract_method.py"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout
    tmp = repo / "tests" / "_orig_extract_method_snapshot.py"
    tmp.write_text(src, encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location(
            "_orig_extract_method_snapshot", tmp)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_orig_extract_method_snapshot"] = mod
        spec.loader.exec_module(mod)
        return mod.plan_extract
    finally:
        tmp.unlink(missing_ok=True)


plan_extract_orig = _load_original_plan_extract()


def _plan_tuple(plan):
    return (
        plan.old, plan.new,
        dict(plan.originals), dict(plan.new_contents),
        dict(plan.edits_by_file),
        list(plan.blockers), list(plan.warnings),
    )


# A spread of source bodies exercising every plan_extract branch.
_SOURCES = {
    "simple.py": (
        "def f(a, b):\n"
        "    x = a + b\n"
        "    y = x * 2\n"
        "    z = y + 1\n"
        "    return z\n"
    ),
    "method.py": (
        "class C:\n"
        "    @property\n"
        "    def m(self, n):\n"
        "        p = n + 1\n"
        "        q = p * p\n"
        "        return q\n"
    ),
    "noflow.py": (
        "def g():\n"
        "    print('a')\n"
        "    print('b')\n"
    ),
    "control.py": (
        "def h(items):\n"
        "    total = 0\n"
        "    for it in items:\n"
        "        total += it\n"
        "    return total\n"
    ),
    "nested.py": (
        "def outer():\n"
        "    a = 1\n"
        "    def inner():\n"
        "        return a\n"
        "    return inner\n"
    ),
    "broken.py": (
        "def f(:\n"
        "    pass\n"
    ),
    "loopjump.py": (
        "def j(items):\n"
        "    out = []\n"
        "    for it in items:\n"
        "        out.append(it)\n"
        "    break\n"
        "    return out\n"
    ),
    "liveout.py": (
        "def k(a):\n"
        "    b = a + 1\n"
        "    c = b + 2\n"
        "    d = c + 3\n"
        "    return b + c + d\n"
    ),
    "comp.py": (
        "def cp(seq):\n"
        "    sq = [v * v for v in seq]\n"
        "    tot = sum(sq)\n"
        "    return tot\n"
    ),
    "decorated_fn.py": (
        "@staticmethod\n"
        "def df(a):\n"
        "    x = a + 1\n"
        "    y = x + 1\n"
        "    return y\n"
    ),
}

# (file, start, end, helper) requests probing every guard + the happy path.
_REQUESTS = [
    ("simple.py", 2, 3, "helper"),
    ("simple.py", 2, 4, "helper"),
    ("simple.py", 3, 4, "_h"),
    ("simple.py", 5, 2, "helper"),          # start > end
    ("simple.py", 2, 3, "f"),               # name already bound
    ("simple.py", 2, 3, "9bad"),            # invalid identifier
    ("simple.py", 2, 3, "not ident"),       # invalid identifier
    ("simple.py", 10, 12, "helper"),        # outside any function
    ("method.py", 4, 5, "helper"),          # method with decorator
    ("method.py", 4, 4, "helper"),
    ("noflow.py", 2, 3, "helper"),          # no params/returns -> warning
    ("control.py", 2, 4, "helper"),         # AugAssign live_in
    ("control.py", 5, 5, "helper"),         # return -> blocker
    ("nested.py", 3, 4, "helper"),          # nested def -> blocker
    ("nested.py", 2, 5, "helper"),          # range spans nested def
    ("broken.py", 1, 2, "helper"),          # parse error
    ("missing.py", 1, 2, "helper"),         # cannot read
    ("loopjump.py", 5, 5, "helper"),        # unenclosed break -> blocker
    ("loopjump.py", 2, 4, "helper"),
    ("liveout.py", 2, 4, "helper"),         # multiple live_out
    ("comp.py", 2, 3, "helper"),            # comprehension target scoping
    ("decorated_fn.py", 3, 4, "helper"),    # decorated top-level fn insert point
]


def test_plan_extract_byte_identical(tmp_path):
    root = tmp_path
    for name, body in _SOURCES.items():
        (root / name).write_text(body, encoding="utf-8")

    mismatches = []
    for file_rel, start, end, helper in _REQUESTS:
        old = plan_extract_orig(str(root), file_rel, start, end, helper)
        new = plan_extract_new(str(root), file_rel, start, end, helper)
        if _plan_tuple(old) != _plan_tuple(new):
            mismatches.append((file_rel, start, end, helper))
    assert not mismatches, f"plan output diverged for: {mismatches}"


def test_at_least_one_success_and_one_blocker(tmp_path):
    """Guard the harness itself: confirm it covers both produced edits and
    blockers so a trivially-empty comparison can't pass silently."""
    root = tmp_path
    for name, body in _SOURCES.items():
        (root / name).write_text(body, encoding="utf-8")
    produced = blocked = 0
    for file_rel, start, end, helper in _REQUESTS:
        plan = plan_extract_new(str(root), file_rel, start, end, helper)
        if plan.new_contents:
            produced += 1
        if plan.blockers:
            blocked += 1
    assert produced >= 3
    assert blocked >= 5
