"""Characterization harness for unused_imports — proves the refactor of
``_collect_rewrites`` into pure helpers preserves byte-identical output.

The original (pre-refactor) ``strip_unused_imports`` is reconstructed inline as
a golden oracle and run over a broad corpus of snippets; its output is compared
byte-for-byte against the current implementation. Zero mismatches is the proof.
"""

from __future__ import annotations

import ast

from app.execution.unused_imports import (
    plan_remove_unused_imports,
    strip_unused_imports,
)
from app.execution import unused_imports as ui


# ── golden oracle: the original _collect_rewrites verbatim ──────────────────

def _golden_collect_rewrites(tree, lines, used, keep):
    rewrites = []
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            if any(alias.name == "*" for alias in node.names):
                continue
        if ui._has_noqa(lines, node.lineno, node.end_lineno):
            continue

        survivors = [
            alias for alias in node.names
            if ui._bound_name(alias) in used or ui._bound_name(alias) in keep
        ]
        if len(survivors) == len(node.names):
            continue

        indent = " " * node.col_offset
        last = lines[node.end_lineno - 1]
        newline = "\n" if last.endswith("\n") else ""

        if not survivors:
            rewrites.append(ui._Rewrite(node.lineno, node.end_lineno, None))
            continue

        parts = [
            alias.name if alias.asname is None
            else f"{alias.name} as {alias.asname}"
            for alias in survivors
        ]
        if isinstance(node, ast.Import):
            text = f"{indent}import {', '.join(parts)}{newline}"
        else:
            level = "." * node.level
            module = node.module or ""
            text = (f"{indent}from {level}{module} import "
                    f"{', '.join(parts)}{newline}")
        rewrites.append(ui._Rewrite(node.lineno, node.end_lineno, text))
    return rewrites


def _golden_strip(source):
    """Original strip_unused_imports, using the golden _collect_rewrites."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    if ui._has_star_import(tree):
        return None
    import_nodes = {
        id(node) for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    }
    used = ui._used_names(tree, import_nodes)
    keep = ui._all_names(tree)
    lines = source.splitlines(keepends=True)
    rewrites = _golden_collect_rewrites(tree, lines, used, keep)
    if not rewrites:
        return None
    new_source = ui._apply(lines, rewrites)
    try:
        ast.parse(new_source)
    except SyntaxError:
        return None
    if new_source == source:
        return None
    return new_source


CORPUS = [
    # plain unused / used
    "import os\nx = 1\n",
    "import os\nos.getcwd()\n",
    "import a.b.c\nprint(a.b.c)\n",
    "import a.b.c\nx = 1\n",
    "import a.b as c\nc.run()\n",
    "import a.b as c\nx = 1\n",
    # from-imports, partial and full
    "from x import a, b\nprint(b)\n",
    "from x import a, b, c\nprint(a)\nprint(c)\n",
    "from x import a, b\nx = 1\n",
    "from x import a as p, b as q\nprint(q)\n",
    "from x import a as p, b as q\nx = 1\n",
    # future + star (never touched / no-op)
    "from __future__ import annotations\nx = 1\n",
    "from os import *\nx = 1\n",
    "from os import *\nimport sys\n",
    # noqa
    "import os  # noqa\nx = 1\n",
    "from x import a, b  # noqa\nprint(b)\n",
    # relative imports
    "from . import a, b\nprint(a)\n",
    "from .mod import a, b\nprint(b)\n",
    "from ..pkg.mod import a, b\nx = 1\n",
    "from . import a\nx = 1\n",
    # multiline parenthesized from-import (full + partial)
    "from x import (\n    a,\n    b,\n)\nprint(a)\n",
    "from x import (\n    a,\n    b,\n)\nx = 1\n",
    # __all__ keeps an export
    "import os\n__all__ = ['os']\n",
    "from x import a, b\n__all__ = ('a',)\nprint(b)\n",
    "from x import a, b\n__all__ = ['a']\n",
    # imports inside try / function (non-module-body, ignored)
    "try:\n    import os\nexcept ImportError:\n    os = None\n",
    "def f():\n    import os\n    return 1\n",
    # multiple statements, mixed
    "import os\nimport sys\nprint(sys.argv)\n",
    "import os\nimport sys\nfrom x import a, b\nprint(a)\nsys.exit()\n",
    # attribute-chain head detection
    "import os.path\nos.path.join('a')\n",
    "import json\nimport os\ndata = json.loads('{}')\n",
    # no trailing newline
    "import os",
    "import os\nx = 1",
    "from x import a, b\nx = 1",
    # syntax error
    "import os\ndef (:\n",
    # empty / trivial
    "",
    "x = 1\n",
    "# just a comment\n",
    # used only in __all__ string plus elsewhere
    "from x import a, b, c\n__all__ = ['a']\nprint(c)\n",
    # asname collides with use
    "import os as system\nsystem.getcwd()\n",
    # back-to-back imports both unused
    "import os\nimport sys\nx = 1\n",
    # nested attribute as decorator etc.
    "import functools\n@functools.wraps\ndef f():\n    pass\n",
    "import functools\ndef f():\n    pass\n",
]


def test_strip_byte_identical_to_golden():
    mismatches = []
    for src in CORPUS:
        got = strip_unused_imports(src)
        want = _golden_strip(src)
        if got != want:
            mismatches.append((src, want, got))
    assert not mismatches, f"{len(mismatches)} byte-mismatches: {mismatches[:3]}"


def test_collect_rewrites_helper_byte_identical():
    """Directly compare _collect_rewrites output (lo/hi/text) against golden."""
    mismatches = []
    for src in CORPUS:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        if ui._has_star_import(tree):
            continue
        import_nodes = {
            id(n) for n in tree.body
            if isinstance(n, (ast.Import, ast.ImportFrom))
        }
        used = ui._used_names(tree, import_nodes)
        keep = ui._all_names(tree)
        lines = src.splitlines(keepends=True)
        got = [(r.lo, r.hi, r.text)
               for r in ui._collect_rewrites(tree, lines, used, keep)]
        want = [(r.lo, r.hi, r.text)
                for r in _golden_collect_rewrites(tree, lines, used, keep)]
        if got != want:
            mismatches.append((src, want, got))
    assert not mismatches, f"{len(mismatches)} mismatches: {mismatches[:3]}"


def test_plan_path_still_works(tmp_path):
    p = tmp_path / "m.py"
    p.write_text("import os\nimport sys\nprint(sys.argv)\n")
    plan = plan_remove_unused_imports(tmp_path, "m.py")
    assert plan is not None
