"""Byte-identical characterization proof for the `_substitute` refactor.

Loads the pre-refactor snapshot of `app/execution/inline_function.py` (captured
from `git show HEAD:...`) as a separate module and runs MANY projects through the
full `plan_inline` path on BOTH the snapshot and the live (refactored) module,
asserting their plan fields (blockers, new_contents, originals, edits_by_file)
are byte-for-byte equal. `_substitute` is exercised end-to-end via plan_inline.

Also unit-tests the new pure helpers directly against the snapshot's inline
`_substitute` behaviour for substitution and side-effect-blocker outputs.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import app.execution.inline_function as live

REPO = Path(__file__).resolve().parents[1]
REL = "app/execution/inline_function.py"


def _load_snapshot():
    src = subprocess.run(
        ["git", "show", f"HEAD:{REL}"], cwd=REPO,
        capture_output=True, text=True, check=True).stdout
    snap_path = REPO / "tests" / "_inline_snapshot_eyml1y.py"
    snap_path.write_text(src)
    try:
        spec = importlib.util.spec_from_file_location(
            "_inline_snapshot_eyml1y", snap_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        snap_path.unlink()
    return mod


snap = _load_snapshot()


# A spread of projects: simple subst, multi-param, defaults, keyword args,
# repeated pure params, repeated impure params (blocker), unpacking (blocker),
# multi-line call (blocker), recursive, decorators, *args, bare-object refs,
# attribute-chain args, no call sites, multiple call sites, multi-file.
PROJECTS: list[dict[str, str]] = [
    {"m.py": "def fee(x):\n    return x * 2\n\ny = fee(7)\n"},
    {"m.py": "def add(a, b):\n    return a + b\n\nz = add(1, 2 + 3)\n"},
    {"m.py": "def fee(x):\n    return x + x\n\ny = fee(g())\n"},  # impure repeat blocker
    {"m.py": "def fee(x):\n    return x + x\n\ny = fee(N)\n"},     # pure repeat ok
    {"m.py": "def fee(x):\n    return x + x\n\ny = fee(a.b.c)\n"}, # attr chain pure
    {"m.py": "def fee(x, y=9):\n    return x + y\n\nz = fee(1)\n"},
    {"m.py": "def fee(x, y=9):\n    return x + y\n\nz = fee(1, y=2)\n"},
    {"m.py": "def fee(x, y):\n    return x + y\n\nz = fee(y=2, x=1)\n"},
    {"m.py": "def fee(x):\n    return x\n\nz = fee(*args)\n"},     # unpack blocker
    {"m.py": "def fee(x):\n    return x\n\nz = fee(**kw)\n"},      # kw unpack blocker
    {"m.py": "def fee(x):\n    return x\n\nz = fee(\n    1)\n"},   # multi-line blocker
    {"m.py": "def fee(x):\n    return fee(x)\n\nz = fee(1)\n"},    # recursive
    {"m.py": "@deco\ndef fee(x):\n    return x\n\nz = fee(1)\n"},  # decorator
    {"m.py": "def fee(*a):\n    return a\n\nz = fee(1)\n"},        # *args
    {"m.py": "def fee(x):\n    return x\n\ng = fee\n"},            # bare object
    {"m.py": "def fee(x):\n    return x\n"},                       # no call site
    {"m.py": "def fee(x):\n    return x * 2\n\na = fee(1)\nb = fee(2)\n"},  # 2 sites
    {"m.py": "def fee(x):\n    '''doc'''\n    return x * 2\n\ny = fee(3)\n"},  # docstring
    {"m.py": "def fee(x):\n    return x\n\nz = fee(1, 2)\n"},      # too many positional
    {"m.py": "def fee(x):\n    return x\n\nz = fee(q=1)\n"},       # unknown keyword
    {"m.py": "def fee(x):\n    return (x +\n            x)\n\ny = fee(K)\n"},  # multi-line expr
    {
        "a.py": "def fee(x):\n    return x * 2\n\nuse = fee(1)\n",
        "b.py": "import a\nval = fee(2)\n",
    },
    {
        "defs.py": "def fee(x, y=2):\n    return x + y\n",
        "use.py": "r = fee(10)\n",
    },
    {"m.py": "x = 1\n"},                                          # no such function
    {"m.py": "def fee(x):\n    return x\ndef fee(y):\n    return y\nz = fee(1)\n"},  # dup def
]


def _materialize(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "proj"
    root.mkdir(parents=True)
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def _plan_fields(plan):
    return (
        list(plan.blockers),
        dict(plan.new_contents),
        dict(plan.originals),
        dict(plan.edits_by_file),
        plan.defined_in,
        plan.old,
        plan.new,
    )


def test_plan_inline_byte_identical(tmp_path):
    mismatches = 0
    for i, files in enumerate(PROJECTS):
        root_live = _materialize(tmp_path / f"l{i}", files)
        root_snap = _materialize(tmp_path / f"s{i}", files)
        live_plan = live.plan_inline(root_live, "fee")
        snap_plan = snap.plan_inline(root_snap, "fee")
        if _plan_fields(live_plan) != _plan_fields(snap_plan):
            mismatches += 1
    assert mismatches == 0


def test_substitute_matches_snapshot_directly(tmp_path):
    import ast
    from app.execution.cross_file_rename import RenamePlan

    cases = [
        ("x * 2", {"x"}, {"x": "7"}, {"x": ast.parse("7", mode="eval").body}),
        ("a + b", {"a", "b"}, {"a": "1", "b": "2"},
         {"a": ast.parse("1", mode="eval").body,
          "b": ast.parse("2", mode="eval").body}),
        ("x + x", {"x"}, {"x": "N"}, {"x": ast.parse("N", mode="eval").body}),
        ("x + x", {"x"}, {"x": "g()"}, {"x": ast.parse("g()", mode="eval").body}),
        ("a.b.c", {"a"}, {"a": "q"}, {"a": ast.parse("q", mode="eval").body}),
    ]
    for expr_text, params, bound, arg_nodes in cases:
        expr = ast.parse(expr_text, mode="eval").body
        p_live = RenamePlan(old="fee", new="")
        p_snap = RenamePlan(old="fee", new="")
        r_live = live._substitute(expr_text, expr, params, bound, arg_nodes,
                                  p_live, "m.py:1")
        r_snap = snap._substitute(expr_text, expr, params, bound, arg_nodes,
                                  p_snap, "m.py:1")
        assert r_live == r_snap
        assert list(p_live.blockers) == list(p_snap.blockers)


def test_helper_purity_smoke():
    import ast
    expr = ast.parse("x + x", mode="eval").body
    uses = live._param_uses(expr, {"x"})
    assert len(uses["x"]) == 2
    # pure repeat -> no blocker
    assert live._side_effect_blocker(
        uses, {"x": ast.parse("N", mode="eval").body}) is None
    # impure repeat -> blocker text (without site prefix)
    msg = live._side_effect_blocker(
        uses, {"x": ast.parse("g()", mode="eval").body})
    assert msg is not None and msg.startswith("parameter 'x' is used 2 times")
