from __future__ import annotations

import ast

from app.engine.detectors import detect, has_fstring_no_placeholder
from app.execution.semantic.transforms import fstring


def _apply(src: str) -> str | None:
    r = fstring.apply("m.py", src, "drop dead f-string prefix")
    return r.patch_requests[0]["new_content"] if r else None


def test_plain_fstring_loses_prefix():
    out = _apply('x = f"hello"\n')
    assert out == 'x = "hello"\n'
    ast.parse(out)


def test_fstring_with_placeholder_untouched():
    assert _apply('x = f"value={n}"\n') is None


def test_normal_string_untouched():
    assert _apply('x = "plain"\n') is None


def test_escaped_braces_are_undoubled():
    # f"{{}}" renders "{}" — dropping the prefix must un-double the braces so
    # the runtime value is preserved exactly.
    out = _apply('x = f"{{}}"\n')
    assert out == 'x = "{}"\n'
    # Equivalence: both evaluate to the same string.
    assert eval(compile(ast.parse('f"{{}}"', mode="eval"), "<o>", "eval")) == "{}"
    assert eval(compile(ast.parse('"{}"', mode="eval"), "<n>", "eval")) == "{}"


def test_raw_fstring_keeps_raw_prefix():
    out = _apply('x = rf"raw {{x}}"\n')
    assert out == 'x = r"raw {x}"\n'
    ast.parse(out)


def test_triple_quoted_fstring():
    out = _apply('x = f"""triple"""\n')
    assert out == 'x = """triple"""\n'
    ast.parse(out)


def test_uppercase_prefix_handled():
    out = _apply('x = F"hi"\n')
    assert out == 'x = "hi"\n'


def test_multiline_fstring_skipped():
    # A node spanning lines is skipped to keep the splice exact.
    assert _apply('x = f"""\nline\n"""\n') is None


def test_implicit_concat_conservatively_skipped():
    # f"a" f"b" is a single JoinedStr spanning two tokens — the minimal-edit
    # validation fails (result isn't one constant), so it's left untouched.
    assert _apply('x = f"a" f"b"\n') is None


def test_detector_flags_and_transform_is_idempotent():
    src = 'def g():\n    return f"static"\n'
    assert has_fstring_no_placeholder(src)
    once = _apply(src)
    assert once is not None and 'f"static"' not in once
    assert _apply(once) is None  # nothing left to fix


def test_detector_ignores_placeholder_fstring():
    assert not has_fstring_no_placeholder('y = f"x={x}"\n')


def test_detector_line_numbers_only_placeholderless():
    src = 'a = f"plain"\nb = f"has {x}"\nc = f"{{esc}}"\n'
    lines = sorted(i.line for i in detect(src) if i.fix_kind == "fstring-no-placeholder")
    assert lines == [1, 3]  # line 2 has a real placeholder


def test_noqa_f541_suppresses():
    # An inline ruff suppression keeps the finding out (consistency with the
    # rest of the detector's noqa handling).
    src = 'x = f"hi"  # noqa: F541\n'
    assert not any(i.fix_kind == "fstring-no-placeholder" for i in detect(src))


def test_value_preserved_for_many_cases():
    # Property: wherever the transform fires, the literal's runtime value is
    # unchanged (the safety invariant that makes the rewrite trustworthy).
    cases = ['f"a"', "f'b'", 'f"{{x}}"', 'rf"r{{y}}"', 'f"tab\\there"']
    for expr in cases:
        src = f"v = {expr}\n"
        out = _apply(src)
        if out is None:
            continue
        old_v = eval(compile(ast.parse(expr, mode="eval"), "<o>", "eval"))
        new_expr = out.split("=", 1)[1].strip()
        new_v = eval(compile(ast.parse(new_expr, mode="eval"), "<n>", "eval"))
        assert old_v == new_v
