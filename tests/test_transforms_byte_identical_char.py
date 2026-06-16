"""Characterization harness proving three refactored transforms are byte-identical.

Feeds many source snippets (including cases that must NOT change) through both the
original (the ``HEAD`` snapshot, loaded dynamically from git) and the refactored
apply path, asserting the full rewritten output strings (and None/skip results)
match character-for-character. Zero mismatches per file is the proof.

The originals are loaded straight from ``git show HEAD:<path>`` and registered as
real submodules of ``app.execution.semantic.transforms`` so their relative imports
(``from ..result``, ``from .base``) resolve without leaving any stray module on
disk. The base for the diff is the current ``HEAD`` commit.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import types

import app.execution.semantic.transforms.extract_method as new_em
import app.execution.semantic.transforms.merge_nested_if as new_mi
import app.execution.semantic.transforms.organize_imports as new_oi

_PKG = "app.execution.semantic.transforms"


def _load_head_module(stem: str) -> types.ModuleType:
    """Import the HEAD snapshot of ``<stem>.py`` as a submodule of the transforms pkg."""
    path = f"app/execution/semantic/transforms/{stem}.py"
    src = subprocess.check_output(["git", "show", f"HEAD:{path}"], text=True)
    name = f"{_PKG}._head_{stem}"
    spec = importlib.util.spec_from_loader(name, loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = _PKG  # make `from ..result` / `from .base` resolve
    sys.modules[name] = module
    exec(compile(src, path, "exec"), module.__dict__)
    return module


orig_oi = _load_head_module("organize_imports")
orig_em = _load_head_module("extract_method")
orig_mi = _load_head_module("merge_nested_if")


def _payload(res):
    if res is None:
        return None
    pr = res.patch_requests[0]
    return (
        res.transform_type,
        tuple(res.rationale),
        pr["path"],
        pr["new_content"],
        pr["expected_old_content"],
    )


# ---------------------------------------------------------------------------
# organize_imports
# ---------------------------------------------------------------------------
OI_SNIPPETS = [
    # syntax error -> None
    "def f(:\n",
    # nothing unused -> None
    "import os\nprint(os.getcwd())\n",
    # one unused import
    "import os\nimport sys\nprint(sys.argv)\n",
    # all imports unused
    "import os\nimport sys\nx = 1\n",
    # from import, used
    "from a import b\nprint(b)\n",
    # from import unused
    "from a import b\nx = 1\n",
    # module name used via attribute
    "from a import b\nprint(a.thing)\n",
    # __future__ never unused
    "from __future__ import annotations\nx = 1\n",
    # noqa honoured
    "import os  # noqa\nx = 1\n",
    # noqa on multi-line import
    "from a import (\n    b,\n)  # noqa\nx = 1\n",
    # aliased import used
    "import numpy as np\nprint(np.array)\n",
    # aliased import unused
    "import numpy as np\nx = 1\n",
    # dotted import, top used
    "import os.path\nprint(os.getcwd())\n",
    # dotted import unused
    "import os.path\nx = 1\n",
    # attribute on name used
    "import os\nfrom sys import argv\nprint(os.getcwd())\nprint(argv)\n",
    # mixed used/unused single Import statement (one used keeps all)
    "import os, sys\nprint(sys.argv)\n",
    # multi-line from import unused
    "from a import (\n    b,\n    c,\n)\nx = 1\n",
    # empty source
    "",
    # only a comment
    "# hello\n",
    # from with module used as attribute base
    "from pkg import thing\nresult = pkg.helper()\n",
    # multiple unused lines
    "import os\nimport sys\nimport json\ny = 2\n",
    # no trailing newline, unused
    "import os\nx = 1",
    # from import where asname used
    "from a import b as c\nprint(c)\n",
    # from import where asname unused
    "from a import b as c\nx = 1\n",
]


def test_organize_imports_byte_identical():
    for src in OI_SNIPPETS:
        for rel in ("foo.py", "pkg/bar.py"):
            old = _payload(orig_oi.apply(rel, src))
            new = _payload(new_oi.apply(rel, src))
            assert old == new, f"mismatch organize_imports rel={rel!r} src={src!r}"


# ---------------------------------------------------------------------------
# extract_method
# ---------------------------------------------------------------------------
EM_SRC_BASIC = (
    "def target():\n"
    "    a = 1\n"
    "    b = 2\n"
    "    c = a + b\n"
    "    return c\n"
)
EM_SRC_NESTED = (
    "class C:\n"
    "    def target(self):\n"
    "        x = 1\n"
    "        y = 2\n"
    "        return x + y\n"
)
EM_SRC_ASYNC = (
    "async def target():\n"
    "    val = compute()\n"
    "    other = val + 1\n"
    "    return other\n"
)
EM_SRC_NOASSIGN = (
    "def target():\n"
    "    print('hi')\n"
    "    print('bye')\n"
)
EM_SRC_BLANKS = (
    "def target():\n"
    "    a = 1\n"
    "\n"
    "    b = 2\n"
    "    return b\n"
)

# (source, start, end, new_name, target_fn, params)
EM_CASES = [
    (EM_SRC_BASIC, 2, 4, "helper", "target", ["a", "b"]),
    (EM_SRC_BASIC, 2, 4, "helper", "target", []),
    (EM_SRC_BASIC, 2, 3, "helper", "target", ["a"]),
    (EM_SRC_BASIC, 4, 4, "helper", "target", ["a", "b"]),
    # invalid: start < 1
    (EM_SRC_BASIC, 0, 3, "helper", "target", []),
    # invalid: end < start
    (EM_SRC_BASIC, 3, 2, "helper", "target", []),
    # invalid: empty new_function_name
    (EM_SRC_BASIC, 2, 3, "", "target", []),
    # invalid: empty target_function
    (EM_SRC_BASIC, 2, 3, "helper", "", []),
    # end_line beyond file
    (EM_SRC_BASIC, 2, 99, "helper", "target", []),
    # syntax error source
    ("def f(:\n    x=1\n", 2, 2, "helper", "f", []),
    # target function not found
    (EM_SRC_BASIC, 2, 3, "helper", "missing", []),
    # nested method
    (EM_SRC_NESTED, 3, 4, "helper", "target", ["self"]),
    (EM_SRC_NESTED, 3, 5, "helper", "target", []),
    # async function
    (EM_SRC_ASYNC, 2, 3, "helper", "target", []),
    # no assignment -> no return var
    (EM_SRC_NOASSIGN, 2, 3, "helper", "target", []),
    # block with blank lines
    (EM_SRC_BLANKS, 2, 4, "helper", "target", []),
    # block all blank (no indents) -> None
    ("def target():\n\n\n    return 1\n", 2, 3, "helper", "target", []),
    # extract whole body
    (EM_SRC_BASIC, 2, 5, "helper", "target", []),
]


def test_extract_method_byte_identical():
    for src, s, e, name, tgt, params in EM_CASES:
        for rel in ("foo.py", "x/y.py"):
            old = _payload(orig_em.apply(rel, src, s, e, name, tgt, params))
            new = _payload(new_em.apply(rel, src, s, e, name, tgt, params))
            assert old == new, (
                f"mismatch extract_method rel={rel!r} args={(s, e, name, tgt, params)!r}"
            )


# ---------------------------------------------------------------------------
# merge_nested_if
# ---------------------------------------------------------------------------
MI_SNIPPETS = [
    # canonical mergeable
    "if a:\n    if b:\n        do()\n",
    # mergeable with complex conditions needing parens
    "if a or c:\n    if b:\n        do()\n",
    "if a:\n    if b or d:\n        do()\n",
    # multi-statement body inside outer -> refuse
    "if a:\n    if b:\n        do()\n    other()\n",
    # outer has else -> refuse
    "if a:\n    if b:\n        do()\nelse:\n    nope()\n",
    # inner has else -> refuse
    "if a:\n    if b:\n        do()\n    else:\n        no()\n",
    # comment between headers -> refuse
    "if a:\n    # comment\n    if b:\n        do()\n",
    # not nested if -> None
    "if a:\n    do()\n",
    # deeper body
    "if a:\n    if b:\n        x = 1\n        y = 2\n",
    # nested 3 deep (merges topmost pair)
    "if a:\n    if b:\n        if c:\n            do()\n",
    # indented context (inside function)
    "def f():\n    if a:\n        if b:\n            do()\n",
    # syntax error
    "if a\n    if b:\n        do()\n",
    # blank line in body preserved
    "if a:\n    if b:\n        x = 1\n\n        y = 2\n",
    # multi-line outer header -> refuse
    "if (a or\n    c):\n    if b:\n        do()\n",
    # multi-line inner header -> refuse
    "if a:\n    if (b or\n        d):\n        do()\n",
    # trailing comment on outer header -> refuse
    "if a:  # note\n    if b:\n        do()\n",
    # inline body on inner -> refuse
    "if a:\n    if b: do()\n",
    # no if at all
    "x = 1\ny = 2\n",
    # body without trailing newline
    "if a:\n    if b:\n        do()",
    # nested with deeper indent step
    "if a:\n        if b:\n                do()\n",
    # multiple sibling top-level ifs, second mergeable
    "if z:\n    only()\nif a:\n    if b:\n        do()\n",
]


def test_merge_nested_if_byte_identical():
    for src in MI_SNIPPETS:
        for rel in ("foo.py", "m/n.py"):
            old = _payload(orig_mi.apply(rel, src, "Title"))
            new = _payload(new_mi.apply(rel, src, "Title"))
            assert old == new, f"mismatch merge_nested_if rel={rel!r} src={src!r}"
