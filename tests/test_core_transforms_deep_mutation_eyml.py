"""Deep-mutation characterization for the three most-used behaviour-preserving
FIX transforms: ``merge_nested_if``, ``guard_clause`` and ``redundant_else``.

The project's mutation tester (``app.engine.mutation_tester``) seeds only the
first 30 single-token faults per module. Enumerating the *full* site universe
for these three transforms surfaces real survivors past that cap — mutants that
the existing suite does not catch yet which genuinely change the transform's
output (a behaviour-preserving rewrite becomes a wrong rewrite, a refusal, or a
crash). Each test below pins the exact ``apply`` output on the discriminating
input so that the corresponding mutant flips a passing test to a failing one.

Every assertion is on the deterministic textual patch the transform produces
(no timestamps, no ordering) and, where a patch is emitted, the result is
re-parsed / executed to confirm it stays behaviour-preserving — which is the
whole point of these conservative transforms.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms import guard_clause as gc
from app.execution.semantic.transforms import merge_nested_if as mni
from app.execution.semantic.transforms import redundant_else as re_t


def _merge(src: str) -> str | None:
    r = mni.apply("m.py", src, "merge nested if")
    return r.patch_requests[0]["new_content"] if r else None


def _guard(src: str) -> str | None:
    r = gc.apply("m.py", src, "add input guard")
    return r.patch_requests[0]["new_content"] if r else None


def _else(src: str) -> str | None:
    r = re_t.apply("m.py", src, "remove redundant else")
    return r.patch_requests[0]["new_content"] if r else None


# --------------------------------------------------------------------------- #
# merge_nested_if
# --------------------------------------------------------------------------- #
def test_merge_preserves_crlf_line_ending_in_header():
    # Kills L159 ``boolean:or>and``: the merged header reuses the outer line's
    # own newline (``\r\n``) via ``outer_line[...] or "\n"``. Flipping ``or`` to
    # ``and`` would force ``"\n"`` and silently strip the ``\r`` from the new
    # header line, corrupting line endings on CRLF sources.
    out = _merge("if a:\r\n    if b:\r\n        x = 1\r\n")
    assert out == "if (a) and (b):\r\n    x = 1\r\n"
    ast.parse(out)
    # The merged header line keeps its CRLF; the body line is untouched.
    assert out.split("\n", 1)[0].endswith("\r")


# --------------------------------------------------------------------------- #
# guard_clause
# --------------------------------------------------------------------------- #
def test_guard_inserted_before_statement_after_docstring_with_blank_gap():
    # Kills L35 ``number:1>2``: when a docstring is followed by a blank line and
    # then the first real statement (``len(node.body) > 1`` is True), the guard
    # is inserted just before that statement (after the blank line). The mutant
    # ``> 2`` falls through to ``first_stmt.end_lineno`` and places the guard
    # immediately after the docstring, before the blank line — a different
    # patch.
    src = 'def f(x):\n    """doc."""\n\n    return x\n'
    out = _guard(src)
    assert out == (
        'def f(x):\n'
        '    """doc."""\n'
        '\n'
        '    if not x:\n'
        '        raise ValueError("x is required")\n'
        '    return x\n'
    )
    ast.parse(out)
    # Docstring is preserved (not demoted to a dead expression).
    fn = next(n for n in ast.walk(ast.parse(out))
              if isinstance(n, ast.FunctionDef))
    assert ast.get_docstring(fn) == "doc."


def test_guard_after_multiline_docstring_only_body_goes_after_docstring():
    # Kills L37 ``boolean:or>and``: when the whole body is a single multi-line
    # docstring, the insert line is ``first_stmt.end_lineno or first_stmt.lineno``
    # — the *last* docstring line. Flipping ``or`` to ``and`` yields
    # ``first_stmt.lineno`` (the *first* docstring line), splicing the guard
    # INTO the docstring and corrupting both the guard and ``__doc__``.
    src = 'def onlydoc(x):\n    """first\n    second\n    """\n'
    out = _guard(src)
    assert out == (
        'def onlydoc(x):\n'
        '    """first\n'
        '    second\n'
        '    """\n'
        '    if not x:\n'
        '        raise ValueError("x is required")\n'
    )
    ast.parse(out)
    fn = next(n for n in ast.walk(ast.parse(out))
              if isinstance(n, ast.FunctionDef))
    assert ast.get_docstring(fn) == "first\nsecond"


# --------------------------------------------------------------------------- #
# redundant_else
# --------------------------------------------------------------------------- #
def test_else_refuses_elif_chain_when_if_does_not_terminate():
    # Kills four ``_is_real_else`` mutants together (L49 ``comparison:==>!=`` and
    # ``number:1>2``, L50 ``comparison:==>!=``, L51 ``comparison:>><=``, and L52
    # ``constant:False>True``): an ``if``/``elif``/``else`` where the leading
    # ``if`` does NOT terminate must be refused (its ``orelse`` is the single
    # ``If`` elif form, not a flattenable real ``else``). Each mutant makes
    # ``_is_real_else`` misclassify the elif as a real else and emit a wrong,
    # behaviour-changing dedent instead of refusing.
    src = (
        "def f(x):\n"
        "    if x:\n"
        "        z = 1\n"
        "    elif y:\n"
        "        return 2\n"
        "    else:\n"
        "        return 3\n"
    )
    assert _else(src) is None


def test_else_flattens_else_holding_a_single_nested_if():
    # Kills L174 ``boolean:or>and``: an ``else:`` whose body is a single nested
    # ``if`` is a genuine real-else (its column is indented past the head), so it
    # flattens. The else-body span end is ``(last.end_lineno or last.lineno) -
    # 1``; flipping ``or`` to ``and`` collapses to ``last.lineno`` and truncates
    # the dedent, mis-indenting the inner ``if``'s own body.
    src = (
        "def f(x, y):\n"
        "    if x:\n"
        "        return 1\n"
        "    else:\n"
        "        if y:\n"
        "            return 2\n"
    )
    out = _else(src)
    assert out == (
        "def f(x, y):\n"
        "    if x:\n"
        "        return 1\n"
        "    if y:\n"
        "        return 2\n"
    )
    ast.parse(out)
    # Behaviour-preserving: x truthy -> 1; x falsey, y truthy -> 2; else None.
    ns: dict = {}
    exec(compile(out, "<t>", "exec"), ns)  # noqa: S102 - trusted test fixture
    assert ns["f"](True, False) == 1
    assert ns["f"](False, True) == 2
    assert ns["f"](False, False) is None


def test_else_removed_when_blank_line_precedes_else_keyword():
    # Kills L104 and L168 ``arithmetic:->+``: both compute the ``if`` head indent
    # from ``lines[if_node.lineno - 1]``. When a blank line sits between the
    # ``if`` body and the ``else:``, flipping ``- 1`` to ``+ 1`` reads the wrong
    # (blank) line for the indent and the transform refuses (returns None)
    # instead of performing the valid dedent.
    src = (
        "def f(x):\n"
        "    if x:\n"
        "        return 1\n"
        "\n"
        "    else:\n"
        "        return 2\n"
    )
    out = _else(src)
    assert out == (
        "def f(x):\n"
        "    if x:\n"
        "        return 1\n"
        "\n"
        "    return 2\n"
    )
    ast.parse(out)
    ns: dict = {}
    exec(compile(out, "<t>", "exec"), ns)  # noqa: S102 - trusted test fixture
    assert ns["f"](True) == 1
    assert ns["f"](False) == 2
