"""Characterization harness proving the ``_append_arg`` refactor is byte-identical.

Feeds many source snippets through ``plan_simplify_comprehension`` (the public
``plan_*`` path that drives ``_append_arg``) and compares the FULL plan output of
the refactored module against a frozen replica of the ORIGINAL ``_append_arg``
implementation. Zero mismatches over the corpus.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys

import app.execution.comprehension as comprehension

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_original_module():
    """Load the pre-refactor ``comprehension.py`` (from ``git show HEAD``) as a
    standalone module so its plan output can be diffed against the live one."""
    src = subprocess.check_output(
        ["git", "show", "HEAD:app/execution/comprehension.py"],
        cwd=_REPO_ROOT,
        text=True,
    )
    spec = importlib.util.spec_from_loader("_comprehension_original", loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_comprehension_original"] = mod
    exec(compile(src, "<git:HEAD comprehension.py>", "exec"), mod.__dict__)
    return mod


# --- Frozen replica of the ORIGINAL _append_arg (pre-refactor). ---------------
def _original_append_arg(for_stmt: ast.For, name: str) -> ast.expr | None:
    if for_stmt.orelse:
        return None
    if len(for_stmt.body) != 1:
        return None
    if not comprehension._is_name_target(for_stmt.target):
        return None
    stmt = for_stmt.body[0]
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return None
    call = stmt.value
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != "append":
        return None
    if not isinstance(func.value, ast.Name) or func.value.id != name:
        return None
    if len(call.args) != 1 or call.keywords:
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Starred):
        return None
    receiver = func.value
    for node in ast.walk(stmt):
        if isinstance(node, ast.Name) and node.id == name and node is not receiver:
            return None
    return arg


# --- Corpus: each snippet exercises a distinct accept/skip branch. -----------
_SNIPPETS = [
    # Canonical accept.
    "out = []\nfor x in items:\n    out.append(x)\n",
    # No trailing newline on last line.
    "out = []\nfor x in items:\n    out.append(x)",
    # Tuple target.
    "out = []\nfor a, b in pairs:\n    out.append(a + b)\n",
    # Nested-tuple target.
    "out = []\nfor (a, (b, c)) in tri:\n    out.append(a)\n",
    # List target.
    "out = []\nfor [a, b] in pairs:\n    out.append(b)\n",
    # Complex expr arg.
    "out = []\nfor x in items:\n    out.append(f(x) + g(x))\n",
    # else clause -> skip.
    "out = []\nfor x in items:\n    out.append(x)\nelse:\n    pass\n",
    # multi-statement body -> skip.
    "out = []\nfor x in items:\n    out.append(x)\n    y = 1\n",
    # attribute target -> skip.
    "out = []\nfor o.a in items:\n    out.append(o.a)\n",
    # subscript target -> skip.
    "out = []\nfor d[k] in items:\n    out.append(1)\n",
    # starred target -> skip.
    "out = []\nfor a, *b in items:\n    out.append(a)\n",
    # empty-tuple-ish / non-name -> skip handled by is_name_target.
    "out = []\nfor x in items:\n    y.append(x)\n",
    # non-append method -> skip.
    "out = []\nfor x in items:\n    out.extend(x)\n",
    # wrong receiver name -> skip.
    "out = []\nfor x in items:\n    other.append(x)\n",
    # not a call body -> skip.
    "out = []\nfor x in items:\n    out\n",
    # assignment body (not Expr) -> skip.
    "out = []\nfor x in items:\n    z = out.append(x)\n",
    # zero args -> skip.
    "out = []\nfor x in items:\n    out.append()\n",
    # two args -> skip.
    "out = []\nfor x in items:\n    out.append(x, y)\n",
    # keyword arg -> skip.
    "out = []\nfor x in items:\n    out.append(x, k=1)\n",
    # starred arg -> skip.
    "out = []\nfor x in items:\n    out.append(*x)\n",
    # other reference to name in body -> skip.
    "out = []\nfor x in items:\n    out.append(out)\n",
    # reference to name buried in arg -> skip.
    "out = []\nfor x in items:\n    out.append(len(out))\n",
    # receiver call chained -> append on result, wrong receiver type.
    "out = []\nfor x in items:\n    out.foo.append(x)\n",
    # multi-line iterable -> still matched by _append_arg (segment-skip later).
    "out = []\nfor x in (\n    a,\n    b,\n):\n    out.append(x)\n",
    # multiple occurrences in one module.
    (
        "out = []\nfor x in items:\n    out.append(x)\n"
        "res = []\nfor y in more:\n    res.append(y * 2)\n"
    ),
    # nested function scope.
    "def f():\n    out = []\n    for x in items:\n        out.append(x)\n    return out\n",
    # no match at all.
    "z = 3\nprint(z)\n",
    # for without preceding empty-list assign.
    "for x in items:\n    out.append(x)\n",
    # assign is [0], not [] -> skip.
    "out = [0]\nfor x in items:\n    out.append(x)\n",
]


def _plan_tuple(mod, source: str, tmp_path):
    """Run ``plan_simplify_comprehension`` from ``mod`` on ``source`` and return a
    fully-comparable snapshot of the resulting plan."""
    p = tmp_path / "m.py"
    p.write_text(source)
    plan = mod.plan_simplify_comprehension(str(tmp_path), "m.py")
    return (
        plan.old,
        plan.new,
        plan.ok,
        tuple(plan.blockers),
        tuple(plan.warnings),
        tuple(sorted(plan.originals.items())),
        tuple(sorted(plan.new_contents.items())),
        tuple(sorted(plan.edits_by_file.items())),
    )


def test_append_arg_byte_identical_unit(tmp_path):
    """Each snippet's ``_append_arg`` verdict matches the frozen original exactly."""
    mismatches = []
    for src in _SNIPPETS:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.For):
                # exercise every plausible name binding seen in the snippet
                for name in ("out", "res", "other", "y"):
                    refactored = comprehension._append_arg(node, name)
                    original = _original_append_arg(node, name)
                    # compare by identity of returned node (or None)
                    if (refactored is None) != (original is None):
                        mismatches.append((src, name, "noneness"))
                    elif refactored is not None and refactored is not original:
                        mismatches.append((src, name, "node-identity"))
    assert not mismatches, mismatches


def test_plan_output_byte_identical(tmp_path):
    """Full plan output of the live (refactored) module is byte-identical to the
    pre-refactor module (loaded from ``git show HEAD``) for every snippet."""
    original = _load_original_module()
    for i, src in enumerate(_SNIPPETS):
        sub = tmp_path / f"s{i}"
        sub.mkdir()
        got = _plan_tuple(comprehension, src, sub)
        want = _plan_tuple(original, src, sub)
        assert got == want, (i, src)
