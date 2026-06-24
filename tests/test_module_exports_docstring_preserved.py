"""wire-module-exports residual-defect regression — ``__all__`` must land AFTER the
module docstring (never above it), so ``module.__doc__`` is always PRESERVED.

The shipped v2 had a residual defect (confirmed by two real-OSS pilot runs on
boltons — 5/6 landed modules lost their docstring): when a module has a leading
COMMENT / LICENSE header BEFORE its docstring::

    # Copyright ...
    # Licensed ...
    \"\"\"Module doc.\"\"\"
    import ...

the pre-AST ``_safe_insertion_index`` skipped a shebang + PEP-263 coding line but
NOT a general leading comment block, so the shared ``_import_insertion_index``
failed to locate the docstring and returned 0. ``__all__`` was spliced as the
module's FIRST statement, demoting the string literal so it was no longer the
docstring → ``module.__doc__`` became ``None``. The fix makes the insertion index
AST-based: it reads the docstring node's ``end_lineno`` directly (comments are not
statements, so the docstring is still located) and lands ``__all__`` after it.

These tests assert the docstring SURVIVES via ``ast.get_docstring`` on the rewrite,
across a comment header, a comment header with no docstring, the plain line-0
docstring, and a full shebang + coding + comment + docstring prologue, plus
idempotence — all behaviours the existing suites never asserted.
"""

from __future__ import annotations

import ast

from app.execution.module_exports import _safe_insertion_index, add_module_all


def _docstring(out: str) -> str | None:
    """The module docstring of ``out`` as the runtime would see it — re-parse and
    read ``body[0]`` exactly like ``module.__doc__`` is populated at import."""
    return ast.get_docstring(ast.parse(out))


# --- (1) comment header + docstring => __all__ AFTER the docstring, doc kept ---

def test_comment_header_then_docstring_preserves_docstring():
    src = (
        "# Copyright 2024 Example\n"
        "# Licensed under MIT\n"
        '"""My module docstring."""\n'
        "import re\n"
        "\n"
        "\n"
        "def foo():\n"
        "    return re\n"
    )
    out = add_module_all(src)
    assert out is not None
    # The docstring is byte-for-byte preserved (the bug nulled it to None).
    assert _docstring(out) == "My module docstring."
    lines = out.splitlines()
    all_idx = lines.index("__all__ = [")
    doc_idx = lines.index('"""My module docstring."""')
    assert all_idx > doc_idx  # __all__ lands BELOW the docstring, never above it
    # The leading comment header is untouched and still leads the file.
    assert lines[0] == "# Copyright 2024 Example"
    assert lines[1] == "# Licensed under MIT"
    ast.parse(out)  # never lands broken Python


def test_comment_header_with_multiline_docstring_preserved():
    # A multi-line docstring after a comment header — end_lineno must span all of it.
    src = (
        "# header line\n"
        '"""First line.\n'
        "\n"
        'Second paragraph.\n'
        '"""\n'
        "import os\n"
        "\n"
        "\n"
        "def run():\n"
        "    return os\n"
    )
    out = add_module_all(src)
    assert out is not None
    assert _docstring(out) == "First line.\n\nSecond paragraph."
    lines = out.splitlines()
    # __all__ sits after the docstring's CLOSING line, before the import.
    assert lines.index("__all__ = [") > lines.index('"""')  # the closing fence
    assert lines.index("__all__ = [") < lines.index("import os")


# --- (2) comment header + NO docstring => __all__ after comments, valid --------

def test_comment_header_no_docstring_lands_after_comment_block():
    src = (
        "# Copyright 2024 Example\n"
        "# Licensed under MIT\n"
        "import os\n"
        "\n"
        "\n"
        "def foo():\n"
        "    return os\n"
    )
    out = add_module_all(src)
    assert out is not None
    # There is no docstring to protect, but the comment header stays on top and
    # __all__ lands after the comment block (polite + valid), before the import.
    assert _docstring(out) is None  # no docstring existed; none is invented
    lines = out.splitlines()
    assert lines[0] == "# Copyright 2024 Example"
    assert lines[1] == "# Licensed under MIT"
    all_idx = lines.index("__all__ = [")
    assert all_idx > 1  # below the comment block
    assert all_idx <= lines.index("import os")  # at/above the first real statement
    ast.parse(out)


def test_comment_header_then_future_then_import_no_docstring():
    # Comment header, a __future__ import, then a regular import, NO docstring:
    # __all__ clears the comment block and the __future__ import, lands before the
    # regular import (the v1 canonical spot for __future__).
    src = (
        "# license\n"
        "from __future__ import annotations\n"
        "import os\n"
        "\n"
        "\n"
        "def foo():\n"
        "    return os\n"
    )
    out = add_module_all(src)
    assert out is not None
    lines = out.splitlines()
    assert lines[0] == "# license"
    all_idx = lines.index("__all__ = [")
    assert all_idx > lines.index("from __future__ import annotations")
    assert all_idx <= lines.index("import os")
    ast.parse(out)


# --- (3) docstring at line 0 (no comments) => unchanged correct behaviour ------

def test_plain_docstring_line_zero_unchanged_and_preserved():
    src = (
        '"""Top docstring."""\n'
        "from __future__ import annotations\n"
        "\n"
        "import os\n"
        "\n"
        "\n"
        "def foo():\n"
        "    return os\n"
    )
    out = add_module_all(src)
    assert out is not None
    assert _docstring(out) == "Top docstring."
    lines = out.splitlines()
    # Byte-identical to the established canonical spot: docstring, __future__, blank,
    # then __all__ (matches the existing suite's canonical-spot expectation).
    assert lines[0] == '"""Top docstring."""'
    assert lines[1] == "from __future__ import annotations"
    assert lines[2] == ""
    assert lines[3] == "__all__ = ["


def test_single_line_docstring_no_imports_preserved():
    src = '"""Doc."""\n\n\ndef g():\n    pass\n'
    out = add_module_all(src)
    assert out is not None
    assert _docstring(out) == "Doc."
    lines = out.splitlines()
    assert lines[0] == '"""Doc."""'
    assert lines.index("__all__ = [") > 0  # below the docstring


# --- (4) shebang + coding + comment + docstring => all four kept, __all__ below -

def test_shebang_coding_comment_docstring_all_preserved():
    src = (
        "#!/usr/bin/env python\n"
        "# -*- coding: utf-8 -*-\n"
        "# a leading note\n"
        '"""Quad-prologue docstring."""\n'
        "import os\n"
        "\n"
        "\n"
        "def run():\n"
        "    return os\n"
    )
    out = add_module_all(src)
    assert out is not None
    assert _docstring(out) == "Quad-prologue docstring."
    lines = out.splitlines()
    # All four prologue elements survive, in order, above __all__.
    assert lines[0] == "#!/usr/bin/env python"
    assert lines[1] == "# -*- coding: utf-8 -*-"
    assert lines[2] == "# a leading note"
    assert lines[3] == '"""Quad-prologue docstring."""'
    all_idx = lines.index("__all__ = [")
    assert all_idx == 4  # directly below the docstring, above the import
    ast.parse(out)


def test_shebang_then_comment_then_docstring_no_coding_line():
    # Shebang + comment + docstring (no coding line) — shebang stays on line 1,
    # docstring preserved, __all__ below both.
    src = (
        "#!/usr/bin/env python\n"
        "# note\n"
        '"""Doc here."""\n'
        "\n"
        "\n"
        "def run():\n"
        "    pass\n"
    )
    out = add_module_all(src)
    assert out is not None
    assert _docstring(out) == "Doc here."
    lines = out.splitlines()
    assert lines[0] == "#!/usr/bin/env python"
    assert lines.index("__all__ = [") > lines.index('"""Doc here."""')


# --- (5) idempotence — a second run is a byte-identical no-op ------------------

def test_comment_header_docstring_idempotent_second_run_is_noop():
    src = (
        "# Copyright 2024 Example\n"
        '"""Doc."""\n'
        "import os\n"
        "\n"
        "\n"
        "def foo():\n"
        "    return os\n"
    )
    once = add_module_all(src)
    assert once is not None
    assert _docstring(once) == "Doc."
    # A second pass over the landed file declares no new __all__ — byte-identical.
    assert add_module_all(once) is None


def test_quad_prologue_idempotent_second_run_is_noop():
    src = (
        "#!/usr/bin/env python\n"
        "# coding: utf-8\n"
        "# note\n"
        '"""Doc."""\n'
        "\n"
        "\n"
        "def run():\n"
        "    pass\n"
    )
    once = add_module_all(src)
    assert once is not None and _docstring(once) == "Doc."
    assert add_module_all(once) is None


def test_deterministic_with_comment_header():
    src = (
        "# c\n"
        '"""D."""\n'
        "def f():\n"
        "    pass\n"
    )
    a = add_module_all(src)
    b = add_module_all(src)
    assert a is not None and a == b


# --- the insertion index helper itself, directly -------------------------------

def test_safe_insertion_index_lands_after_comment_and_docstring():
    lines = [
        "# header",
        '"""Doc."""',
        "import os",
        "",
        "def f():",
        "    return os",
    ]
    # Index 2 = the line of ``import os`` (after the comment + docstring), so the
    # docstring at index 1 is never demoted.
    assert _safe_insertion_index(lines) == 2


def test_safe_insertion_index_falls_back_on_unparseable_source():
    # Broken Python: the AST path cannot parse, so it falls back to the line-based
    # floor (which still returns a sane non-negative index; nothing is landed later
    # because rejoin_guarded re-parses and drops broken output).
    lines = ["def (:", "    pass"]
    idx = _safe_insertion_index(lines)
    assert isinstance(idx, int) and idx >= 0
    # And add_module_all refuses the unparseable module outright (no rewrite).
    assert add_module_all("def (:\n    pass\n") is None


def test_safe_insertion_index_empty_source_is_zero():
    # An empty module parses to an empty body — no docstring, no future, no code;
    # the index stays at the prologue floor (0). add_module_all refuses (no public).
    assert _safe_insertion_index([]) == 0
    assert add_module_all("") is None
    assert add_module_all("# only a comment\n") is None
