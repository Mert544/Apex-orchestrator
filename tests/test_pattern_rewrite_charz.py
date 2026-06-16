"""Characterization harness proving the refactor of ``pattern_rewrite`` is
byte-identical to the pre-refactor snapshot.

``tests/_pattern_rewrite_charz_baseline.py`` is a verbatim copy of the file at
the refactor's base commit. We run a large matrix of pattern/replacement/source
inputs through BOTH the live module and the baseline, comparing every field of
the resulting plan (and the raw ``_match`` capture behaviour). Zero mismatches
is the contract.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import types

import app.execution.pattern_rewrite as live

# Load the pre-refactor snapshot of the module straight from git, pinned to the
# base commit, so the baseline can never drift from what it characterizes.
_REL = "app/execution/pattern_rewrite.py"
_BASE_COMMIT = "bdf76506829c4cd4181545c72b951fc1d3e789d7"
_BASE_SRC = subprocess.check_output(
    ["git", "show", f"{_BASE_COMMIT}:{_REL}"], text=True,
)
base = types.ModuleType("_pattern_rewrite_baseline")
base.__dict__["__spec__"] = importlib.util.spec_from_loader(
    "_pattern_rewrite_baseline", loader=None,
)
exec(compile(_BASE_SRC, "<HEAD:" + _REL + ">", "exec"), base.__dict__)


_SOURCES = [
    "",
    "x = 1\n",
    "if len(items) == 0:\n    pass\n",
    "a = len(items) == 0\nb = len(other) == 0\n",
    "a = len(items) == 0\nb = len(items) == 0\n",
    "if len(x) == 0 and len(y) == 0:\n    print(len(z) == 0)\n",
    "v = (len(\n    items) == 0)\n",  # spans lines -> skipped
    "result = foo(bar) + foo(bar)\n",
    "nested = len(len(items)) == 0\n",
    "m = a == b == c\n",
    "broken = (\n",  # SyntaxError source
    "s = 'len($x) == 0'\n",
    "t = a + b\nu = a + b\nw = c + d\n",
    "deep = f(g(h(x))) == f(g(h(x)))\n",
    "p = obj.attr == 0\nq = obj.attr == 0\n",
    "same = len(a) == 0\nmix = len(a) == 1\n",
    "x=1;y=len(z)==0\n",  # two stmts one line
]

_RULES = [
    ("len($x) == 0", "not $x"),
    ("len($x) == 0", "len($y) == 0"),       # unbound replacement metavar
    ("$x", "$x"),                            # bare metavar pattern -> blocker
    ("len($x) == 0", "not $x and $z"),       # another unbound
    ("a + b", "b + a"),
    ("$x + $x", "2 * $x"),
    ("foo($x)", "bar($x)"),
    ("len(($x) == 0", "not $x"),            # invalid pattern expr
    ("len($x) == 0", "not ($x"),            # invalid replacement expr
    ("$x == $y", "$y == $x"),
    ("obj.attr == 0", "obj.attr is None"),
    ("f(g(h($x)))", "$x"),
    ("$a == $b == $c", "chained"),
    ("len($x) == 1", "one_of($x)"),
]


def _plan_snapshot(plan):
    return (
        plan.old,
        plan.new,
        dict(plan.originals),
        dict(plan.new_contents),
        dict(plan.edits_by_file),
        list(plan.blockers),
        list(plan.warnings),
    )


def _build_project(tmp_path, sources):
    root = tmp_path
    root.mkdir(parents=True, exist_ok=True)
    for i, src in enumerate(sources):
        (root / f"mod_{i}.py").write_text(src)
    return root


def test_plan_pattern_rewrite_byte_identical(tmp_path):
    mismatches = []
    n = 0
    for ri, (pat, rep) in enumerate(_RULES):
        # vary which subset of sources lands in the project tree
        for split in range(0, len(_SOURCES) + 1, 3):
            sub = _SOURCES[: split + 1]
            proj = _build_project(tmp_path / f"r{ri}_s{split}", sub)
            live_plan = live.plan_pattern_rewrite(proj, pat, rep)
            base_plan = base.plan_pattern_rewrite(proj, pat, rep)
            n += 1
            if _plan_snapshot(live_plan) != _plan_snapshot(base_plan):
                mismatches.append((pat, rep, split))
    assert not mismatches, f"{len(mismatches)} mismatches: {mismatches[:5]}"
    assert n > 50


def test_match_byte_identical():
    mismatches = []
    n = 0
    for pat, _rep in _RULES:
        encoded = live._encode_metavars(pat)
        try:
            ptree = ast.parse(encoded, mode="eval").body
        except SyntaxError:
            continue
        for src in _SOURCES:
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                lb, bb = {}, {}
                lr = live._match(node, ptree, src, lb)
                br = base._match(node, ptree, src, bb)
                n += 1
                if (lr, lb) != (br, bb):
                    mismatches.append((pat, ast.dump(node)[:60]))
    assert not mismatches, f"{len(mismatches)} mismatches: {mismatches[:5]}"
    assert n > 50


def test_match_lines_byte_identical(tmp_path):
    for pat, _rep in _RULES:
        tree = live.compile_pattern(pat)
        btree = base.compile_pattern(pat)
        # compile_pattern returns either None or an ast.expr; compare via dump
        if (tree is None) != (btree is None):
            raise AssertionError(f"compile_pattern divergence for {pat!r}")
        if tree is None:
            continue
        for src in _SOURCES:
            assert live.match_lines(src, tree) == base.match_lines(src, btree), pat
