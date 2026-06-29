"""shebang / PEP-263 coding-cookie demotion regression — the shared
``_import_insertion_index`` must NEVER land an inserted import above a leading
``#!`` shebang (physical line 1) or a PEP-263 encoding cookie (line 1 or 2).

The latent-correctness bug (F3): ``_import_insertion_index`` skipped leading
blanks → a module docstring → blanks/``from __future__`` but NOT a leading
shebang/cookie. For a file opening::

    # -*- coding: utf-8 -*-
    \"\"\"doc\"\"\"

it returned 0, so the five unprotected callers (``future_annotations`` /
``final_marker`` / ``total_ordering`` / ``enum_unique`` / ``dataclass_rewrite``)
inserted ``from __future__ import annotations`` (or a dataclass import) ABOVE the
cookie — demoting it past the line-1/2 window where PEP 263 honours it, silently
disabling it. A green ASCII suite never noticed (the cookie only bites on
non-UTF-8 source).

The fix lifts a ``_prologue_length``-style skip (shebang line 0, then a coding
cookie on line 0 or 1) INTO the bare helper, BEFORE the docstring/``__future__``
logic. These tests pin: the index lands AFTER the prologue across cookie-only,
shebang-only, shebang+cookie, cookie+docstring, and the full
shebang+cookie+docstring+``__future__`` shape; the five callers keep the cookie on
line 1/2 end-to-end; a plain module with NO prologue is byte-identical to the
pre-fix behaviour (regression-lock); and ``module_exports`` — which wraps the bare
helper as ``prologue + _import_insertion_index(lines[prologue:])`` — stays
byte-identical (the slice has no prologue, so the prologue-aware helper skips 0
there and no double-skip occurs).
"""

from __future__ import annotations

import ast

from app.execution.dataclass_rewrite import (
    _import_insertion_index,
    _is_coding_cookie,
    _prologue_length,
    rewrite_dataclasses,
)
from app.execution.enum_unique import add_enum_unique_decorator
from app.execution.final_marker import add_final_decorator
from app.execution.future_annotations import add_future_annotations
from app.execution.module_exports import add_module_all
from app.execution.total_ordering import seal_total_ordering

# --- the bare helper: where the import index lands across prologue shapes -----


def test_cookie_only_index_after_cookie():
    # A lone PEP-263 cookie on line 1 — the import lands on line 1 (index 1).
    assert _import_insertion_index(["# -*- coding: utf-8 -*-", "import os"]) == 1


def test_bare_coding_cookie_form_index_after_cookie():
    # The bare ``# coding: utf-8`` form (no ``-*-`` fences) is also a cookie.
    assert _import_insertion_index(["# coding: utf-8", "x = 1"]) == 1


def test_coding_equals_cookie_form_index_after_cookie():
    # The ``# coding=utf-8`` (``=`` rather than ``:``) form is also a cookie.
    assert _import_insertion_index(["# coding=utf-8", "x = 1"]) == 1


def test_shebang_only_index_after_shebang():
    # A lone shebang on line 1 — the import lands on line 1 (index 1).
    assert _import_insertion_index(["#!/usr/bin/env python", "import os"]) == 1


def test_shebang_then_cookie_index_after_both():
    # Shebang on line 1, cookie on line 2 — the import lands on line 3 (index 2).
    assert _import_insertion_index(
        ["#!/usr/bin/env python", "# -*- coding: utf-8 -*-", "import os"]
    ) == 2


def test_cookie_then_docstring_index_after_docstring():
    # Cookie + docstring — the import lands below BOTH (index 2), never above the
    # cookie (the exact buggy shape: pre-fix this returned 0).
    assert _import_insertion_index(
        ["# -*- coding: utf-8 -*-", '"""doc"""', "import os"]
    ) == 2


def test_shebang_cookie_docstring_future_index_after_all():
    # The full prologue: shebang, cookie, docstring, then a ``__future__`` import —
    # a fresh import lands after all four (index 4).
    lines = [
        "#!/usr/bin/env python",
        "# -*- coding: utf-8 -*-",
        '"""doc"""',
        "from __future__ import annotations",
        "x = 1",
    ]
    assert _import_insertion_index(lines) == 4


def test_cookie_on_line_three_is_not_a_cookie():
    # PEP 263 only honours a cookie on physical line 1 or 2. A ``# coding:`` comment
    # on line 3 is an ordinary comment — the prologue is just the shebang (1), and a
    # comment is opaque to the docstring/future scan, so the index stays at 1.
    lines = ["#!/usr/bin/env python", "x = 1", "# coding: latin-1", "y = 2"]
    assert _prologue_length(lines) == 1
    assert _import_insertion_index(lines) == 1


def test_prose_comment_mentioning_coding_is_not_a_cookie():
    # A prose comment that merely contains the word "coding" (no ``coding[:=]<name>``
    # token) is NOT an encoding cookie, so the prologue is 0.
    assert _prologue_length(["# notes on coding style", "x = 1"]) == 0
    assert _is_coding_cookie("# notes on coding style") is False
    assert _is_coding_cookie("# -*- coding: utf-8 -*-") is True
    assert _is_coding_cookie("x = 1") is False  # not a comment at all


# --- regression-lock: NO prologue => byte-identical to the pre-fix behaviour ---


def test_plain_docstring_no_prologue_unchanged():
    # The established canonical spot: after the docstring, byte-identical to before.
    assert _import_insertion_index(['"""doc"""', "import os"]) == 1


def test_plain_code_no_prologue_index_zero():
    assert _import_insertion_index(["import os"]) == 0


def test_empty_lines_no_prologue_index_zero():
    assert _import_insertion_index([]) == 0
    assert _prologue_length([]) == 0


def test_docstring_then_future_no_prologue_unchanged():
    lines = ['"""doc"""', "from __future__ import annotations", "", "import os"]
    assert _import_insertion_index(lines) == 3


def test_leading_blanks_then_docstring_no_prologue_unchanged():
    assert _import_insertion_index(["", "", '"""doc"""', "x = 1"]) == 3


# --- end-to-end: the five callers keep the cookie on line 1/2 -----------------

_COOKIE_DOC_TYPED = (
    "# -*- coding: utf-8 -*-\n"
    '"""m"""\n'
    "def f(x: int) -> int:\n"
    "    return x\n"
)


def test_future_annotations_keeps_cookie_on_line_one():
    out = add_future_annotations(_COOKIE_DOC_TYPED)
    assert out is not None
    lines = out.splitlines()
    assert lines[0] == "# -*- coding: utf-8 -*-"  # cookie NOT demoted
    fut = lines.index("from __future__ import annotations")
    assert fut >= 1  # the future import lands below the cookie
    ast.parse(out)


def test_future_annotations_shebang_cookie_kept_on_lines_one_two():
    src = (
        "#!/usr/bin/env python\n"
        "# coding: utf-8\n"
        '"""m"""\n'
        "def f(x: int) -> int:\n"
        "    return x\n"
    )
    out = add_future_annotations(src)
    assert out is not None
    lines = out.splitlines()
    assert lines[0].startswith("#!")  # shebang stays on physical line 1
    assert lines[1] == "# coding: utf-8"  # cookie stays on physical line 2
    ast.parse(out)


def test_dataclass_rewrite_keeps_cookie_on_line_one():
    src = (
        "# -*- coding: utf-8 -*-\n"
        '"""m"""\n'
        "class P:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
    )
    out = rewrite_dataclasses(src)
    assert out is not None
    lines = out.splitlines()
    assert lines[0] == "# -*- coding: utf-8 -*-"  # cookie NOT demoted
    imp = next(i for i, ln in enumerate(lines) if ln.startswith("from dataclasses import"))
    assert imp >= 1  # the dataclass import lands below the cookie
    ast.parse(out)


def test_final_marker_keeps_cookie_on_line_one():
    # A class used as a base only outside a re-export — add-final wires a fresh
    # ``from typing import final``; it must land below the cookie.
    src = (
        "# -*- coding: utf-8 -*-\n"
        '"""m"""\n'
        "class Leaf:\n"
        "    pass\n"
    )
    out = add_final_decorator(src)
    if out is not None:  # add-final may refuse; when it lands, the cookie is safe
        lines = out.splitlines()
        assert lines[0] == "# -*- coding: utf-8 -*-"
        ast.parse(out)


def test_total_ordering_keeps_cookie_on_line_one():
    src = (
        "# -*- coding: utf-8 -*-\n"
        '"""m"""\n'
        "class C:\n"
        "    def __init__(self, v):\n"
        "        self.v = v\n"
        "    def __eq__(self, other):\n"
        "        return self.v == other.v\n"
        "    def __lt__(self, other):\n"
        "        return self.v < other.v\n"
    )
    out = seal_total_ordering(src)
    if out is not None:
        lines = out.splitlines()
        assert lines[0] == "# -*- coding: utf-8 -*-"
        ast.parse(out)


def test_enum_unique_keeps_cookie_on_line_one():
    src = (
        "# -*- coding: utf-8 -*-\n"
        '"""m"""\n'
        "from enum import Enum\n"
        "\n"
        "\n"
        "class Color(Enum):\n"
        "    RED = 1\n"
        "    GREEN = 2\n"
    )
    out = add_enum_unique_decorator(src)
    if out is not None:
        lines = out.splitlines()
        assert lines[0] == "# -*- coding: utf-8 -*-"
        ast.parse(out)


# --- module_exports stays byte-identical (option (b): no double-skip) ----------


def test_module_exports_prologue_length_matches_local_copy():
    # The local ``_prologue_length`` mirrors ``module_exports._prologue_length`` so
    # the wrapper's ``prologue + helper(lines[prologue:])`` math is unchanged.
    from app.execution.module_exports import _prologue_length as me_prologue

    shapes = [
        [],
        ["import os"],
        ["#!/x", "import os"],
        ["# -*- coding: utf-8 -*-", "import os"],
        ["#!/x", "# coding: utf-8", "import os"],
        ["#!/x", "# coding: utf-8", '"""d"""', "x = 1"],
        ["# notes on coding", "x = 1"],
    ]
    for lines in shapes:
        assert _prologue_length(lines) == me_prologue(lines)


def test_module_exports_add_module_all_byte_identical_on_prologue_shapes():
    # With the bare helper now prologue-aware, ``module_exports`` must produce the
    # SAME ``__all__`` placement it did before — its wrapper strips the prologue
    # first, so the helper sees no prologue on the slice and skips 0 (no double-skip)
    # and, for parseable source, ``_safe_insertion_index`` is AST-based and never
    # calls the bare helper at all.
    src = (
        "#!/usr/bin/env python\n"
        "# -*- coding: utf-8 -*-\n"
        '"""m"""\n'
        "import os\n"
        "\n"
        "\n"
        "def foo():\n"
        "    return os\n"
    )
    out = add_module_all(src)
    assert out is not None
    lines = out.splitlines()
    # All-prologue elements survive, in order, above the docstring and __all__.
    assert lines[0] == "#!/usr/bin/env python"
    assert lines[1] == "# -*- coding: utf-8 -*-"
    assert lines[2] == '"""m"""'
    assert ast.get_docstring(ast.parse(out)) == "m"
    all_idx = lines.index("__all__ = [")
    assert all_idx > 2  # below the prologue + docstring


def test_module_exports_plain_module_unchanged():
    # No prologue — the wrapper takes the ``prologue == 0`` branch (byte-identical
    # to the bare helper), so a plain module is placed exactly as before.
    src = '"""m"""\nimport os\n\n\ndef foo():\n    return os\n'
    out = add_module_all(src)
    assert out is not None
    lines = out.splitlines()
    assert lines[0] == '"""m"""'
    assert lines.index("__all__ = [") > 0


# --- determinism --------------------------------------------------------------


def test_deterministic_same_input_same_index():
    lines = ["#!/usr/bin/env python", "# coding: utf-8", '"""d"""', "x = 1"]
    assert _import_insertion_index(lines) == _import_insertion_index(list(lines))
