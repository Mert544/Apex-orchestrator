"""Tests for the percent-to-fstring develop objective."""

from __future__ import annotations

from pathlib import Path

from app.execution.percent_to_fstring import plan_percent_to_fstring


def _write(tmp_path: Path, rel: str, body: str) -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return rel


def _converted(tmp_path: Path, body: str, rel: str = "mod.py") -> str:
    _write(tmp_path, rel, body)
    plan = plan_percent_to_fstring(tmp_path, rel)
    assert not plan.blockers
    return plan.new_contents.get(rel, body)


# --- conversions that SHOULD happen --------------------------------------

def test_single_placeholder(tmp_path):
    out = _converted(tmp_path, 'x = "x=%s" % v\n')
    assert out == 'x = f"x={v}"\n'


def test_two_placeholders_tuple(tmp_path):
    out = _converted(tmp_path, 'x = "%s = %s" % (a, b)\n')
    assert out == 'x = f"{a} = {b}"\n'


def test_attribute_arg(tmp_path):
    out = _converted(tmp_path, 'x = "%s" % self.name\n')
    assert out == 'x = f"{self.name}"\n'


def test_constant_arg(tmp_path):
    out = _converted(tmp_path, 'x = "%s" % 42\n')
    assert out == 'x = f"{42}"\n'


def test_single_quote_preserved(tmp_path):
    out = _converted(tmp_path, "x = '%s' % v\n")
    assert out == "x = f'{v}'\n"


def test_literal_percent_preserved(tmp_path):
    out = _converted(tmp_path, 'x = "100%% of %s" % v\n')
    assert out == 'x = f"100% of {v}"\n'


def test_only_literal_percent_with_placeholder(tmp_path):
    out = _converted(tmp_path, 'x = "%s%%" % v\n')
    assert out == 'x = f"{v}%"\n'


def test_braces_in_literal_escaped(tmp_path):
    out = _converted(tmp_path, 'x = "{a} %s }" % v\n')
    assert out == 'x = f"{{a}} {v} }}"\n'


def test_multiple_occurrences(tmp_path):
    rel = _write(tmp_path, "mod.py", 'a = "%s" % p\nb = "%s" % q\n')
    plan = plan_percent_to_fstring(tmp_path, rel)
    assert plan.edits_by_file[rel] == 2
    assert plan.new_contents[rel] == 'a = f"{p}"\nb = f"{q}"\n'


def test_edits_count_and_plan_fields(tmp_path):
    rel = _write(tmp_path, "mod.py", 'a = "%s" % p\nb = "x=%s" % q\n')
    plan = plan_percent_to_fstring(tmp_path, rel)
    assert plan.old == rel
    assert plan.new == "percent-to-fstring"
    assert plan.edits_by_file[rel] == 2
    assert plan.originals[rel] == 'a = "%s" % p\nb = "x=%s" % q\n'
    assert plan.new_contents[rel] == 'a = f"{p}"\nb = f"x={q}"\n'


# --- shapes that MUST be left untouched ----------------------------------

def _untouched(tmp_path: Path, body: str, rel: str = "mod.py") -> None:
    _write(tmp_path, rel, body)
    plan = plan_percent_to_fstring(tmp_path, rel)
    assert not plan.blockers
    assert not plan.new_contents


def test_mapping_key_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%(name)s" % d\n')


def test_dynamic_width_star_untouched(tmp_path):
    # ``*`` pulls width from an arg — not a fixed, provable spec; refuse.
    _untouched(tmp_path, 'x = "%*d" % (w, n)\n')


def test_percent_c_untouched(tmp_path):
    # ``%c`` maps to chr(); ``{}`` would str() the int — refuse.
    _untouched(tmp_path, 'x = "%c" % n\n')


def test_string_precision_untouched(tmp_path):
    # ``%.3s`` truncates the string — kept out of the proven set, refuse.
    _untouched(tmp_path, 'x = "%.3s" % v\n')


def test_int_precision_untouched(tmp_path):
    # ``%.3d`` zero-pads digits, which ``{:d}`` cannot express — refuse.
    _untouched(tmp_path, 'x = "%.3d" % n\n')


def test_trailing_lone_percent_untouched(tmp_path):
    # A lone '%' that isn't part of '%s' or '%%' disqualifies the literal.
    _untouched(tmp_path, 'x = "done %s 50%" % v\n')


def test_count_mismatch_too_many_args_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%s" % (a, b)\n')


def test_count_mismatch_too_few_args_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%s %s" % (a,)\n')


def test_call_arg_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%s" % f()\n')


def test_subscript_arg_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%s" % d[k]\n')


def test_binop_arg_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%s" % (a + b)\n')


def test_call_arg_in_tuple_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%s %s" % (a, g())\n')


def test_star_arg_in_tuple_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%s" % (*args,)\n')


def test_raw_string_template_untouched(tmp_path):
    _untouched(tmp_path, 'x = r"%s" % v\n')


def test_bytes_template_untouched(tmp_path):
    # bytes %-format isn't a str literal we embed in an f-string.
    _untouched(tmp_path, 'x = b"%s" % v\n')


def test_fstring_template_untouched(tmp_path):
    # left is a JoinedStr, not an ast.Constant — no match.
    _untouched(tmp_path, 'x = f"%s" % v\n')


def test_backslash_in_template_untouched(tmp_path):
    _untouched(tmp_path, 'x = "a\\tb %s" % v\n')


def test_multiline_binop_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%s %s" % (\n    a, b)\n')


def test_no_placeholder_untouched(tmp_path):
    # No '%s' at all (and a non-string right) — nothing to interpolate.
    _untouched(tmp_path, 'x = "plain" % ()\n')


def test_mod_on_numbers_untouched(tmp_path):
    # A genuine modulo, left isn't a string constant.
    _untouched(tmp_path, 'x = a % b\n')


def test_mod_on_non_literal_string_untouched(tmp_path):
    # %-format on a variable, not a string literal — out of scope.
    _untouched(tmp_path, 'x = template % v\n')


# --- semantic equivalence ------------------------------------------------

def test_semantic_equivalence(tmp_path):
    body = 'def render(a, b):\n    return "%s and %s = %s" % (a, b, a)\n'
    out = _converted(tmp_path, body)
    assert out == 'def render(a, b):\n    return f"{a} and {b} = {a}"\n'
    before_ns: dict = {}
    after_ns: dict = {}
    exec(body, before_ns)
    exec(out, after_ns)
    for a, b in [(1, 2), ("x", "y"), (0, 0), (3.5, 4)]:
        assert before_ns["render"](a, b) == after_ns["render"](a, b)


def test_semantic_equivalence_single_arg(tmp_path):
    body = 'def f(v):\n    return "x=%s" % v\n'
    out = _converted(tmp_path, body)
    assert out == 'def f(v):\n    return f"x={v}"\n'
    before_ns: dict = {}
    after_ns: dict = {}
    exec(body, before_ns)
    exec(out, after_ns)
    for v in [1, "hi", 0, 3.5]:
        assert before_ns["f"](v) == after_ns["f"](v)


def test_semantic_equivalence_literal_percent(tmp_path):
    body = 'def f(v):\n    return "100%% done: %s" % v\n'
    out = _converted(tmp_path, body)
    assert out == 'def f(v):\n    return f"100% done: {v}"\n'
    before_ns: dict = {}
    after_ns: dict = {}
    exec(body, before_ns)
    exec(out, after_ns)
    for v in ["go", 7, "x"]:
        assert before_ns["f"](v) == after_ns["f"](v)


def test_semantic_equivalence_constant_and_attr(tmp_path):
    body = (
        "class C:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "    def label(self):\n"
        '        return "n=%s v=%s" % (self.name, 7)\n'
    )
    out = _converted(tmp_path, body)
    before_ns: dict = {}
    after_ns: dict = {}
    exec(body, before_ns)
    exec(out, after_ns)
    assert before_ns["C"]("hi").label() == after_ns["C"]("hi").label()


# --- numeric / format conversions (the widened set) ----------------------

def test_percent_d_refused_float_divergence(tmp_path):
    # ``"%d" % 3.14`` TRUNCATES to ``"3"``; ``f"{3.14:d}"`` RAISES ValueError.
    # The transform cannot statically rule out a float arg, so decimal ``d``/``i``
    # (with any flags/width) are REFUSED rather than risk turning a working
    # truncation into a crash. (Radix ``x``/``X``/``o`` reject floats in BOTH
    # forms, so they stay convertible — see the tests below.)
    _untouched(tmp_path, 'x = "%d" % n\n')


def test_percent_i_refused(tmp_path):
    _untouched(tmp_path, 'x = "%i" % n\n')


def test_percent_r(tmp_path):
    assert _converted(tmp_path, 'x = "%r" % n\n') == 'x = f"{n!r}"\n'


def test_percent_f(tmp_path):
    assert _converted(tmp_path, 'x = "%f" % n\n') == 'x = f"{n:f}"\n'


def test_percent_precision_f(tmp_path):
    assert _converted(tmp_path, 'x = "%.2f" % v\n') == 'x = f"{v:.2f}"\n'


def test_percent_hex_lower(tmp_path):
    assert _converted(tmp_path, 'x = "%x" % n\n') == 'x = f"{n:x}"\n'


def test_percent_hex_upper(tmp_path):
    assert _converted(tmp_path, 'x = "%X" % n\n') == 'x = f"{n:X}"\n'


def test_percent_octal(tmp_path):
    assert _converted(tmp_path, 'x = "%o" % n\n') == 'x = f"{n:o}"\n'


def test_percent_exp_and_general(tmp_path):
    assert _converted(tmp_path, 'x = "%e" % v\n') == 'x = f"{v:e}"\n'
    assert _converted(tmp_path, 'x = "%g" % v\n') == 'x = f"{v:g}"\n'


def test_percent_zero_pad_width_decimal_refused(tmp_path):
    # ``%05d`` is still a decimal conversion — refused (float divergence).
    _untouched(tmp_path, 'x = "%05d" % n\n')


def test_percent_zero_pad_width_hex_converts(tmp_path):
    # The same width/flag on a RADIX conversion is safe (rejects floats both ways).
    assert _converted(tmp_path, 'x = "%05x" % n\n') == 'x = f"{n:05x}"\n'


def test_percent_width_decimal_refused(tmp_path):
    _untouched(tmp_path, 'x = "%5d" % n\n')


def test_percent_plus_flag_decimal_refused(tmp_path):
    _untouched(tmp_path, 'x = "%+d" % n\n')


def test_percent_left_string(tmp_path):
    assert _converted(tmp_path, 'x = "%-10s" % s\n') == 'x = f"{s!s:<10}"\n'


def test_percent_right_string(tmp_path):
    assert _converted(tmp_path, 'x = "%5s" % s\n') == 'x = f"{s!s:>5}"\n'


def test_percent_alt_hex(tmp_path):
    assert _converted(tmp_path, 'x = "%#x" % n\n') == 'x = f"{n:#x}"\n'


def test_percent_minus_drops_zero_decimal_refused(tmp_path):
    # ``%-05d`` is still decimal — refused. (The ``-``/``0`` flag normalisation is
    # exercised on a safe radix conversion in test_percent_minus_drops_zero_hex.)
    _untouched(tmp_path, 'x = "%-05d" % n\n')


def test_percent_minus_drops_zero_hex(tmp_path):
    # printf ignores ``0`` when ``-`` is present; the f-spec must drop it too.
    assert _converted(tmp_path, 'x = "%-05x" % n\n') == 'x = f"{n:<5x}"\n'


def test_mixed_string_and_decimal_tuple_refused(tmp_path):
    # A decimal ``%d`` anywhere refuses the WHOLE template (all-or-nothing).
    _untouched(tmp_path, 'x = "%s=%d" % (k, v)\n')


def test_mixed_string_and_hex_tuple_converts(tmp_path):
    out = _converted(tmp_path, 'x = "%s=%x" % (k, v)\n')
    assert out == 'x = f"{k}={v:x}"\n'


# --- round-trip honesty gate for the widened set -------------------------

# (template, [representative values]) — every value is eval'd through both the
# original ``%`` expression and the converted f-string; they must be IDENTICAL.
_ROUNDTRIP_INTS = [0, 1, -1, 7, 255, -255, 1000000, True, False]
_ROUNDTRIP_FLOATS = [0.0, 1.5, -1.5, 3.14159, -3.14159, 1e10, 0.000123, 100.0]
_ROUNDTRIP_STRS = ["", "a", "hello", "x" * 12, "tab\tless"[:3]]

# NOTE: decimal ``%d``/``%i`` (and any flagged/width form ``%5d``/``%05d``/…) are
# intentionally ABSENT — they are refused (``"%d" % 3.14`` truncates but
# ``f"{:d}"`` raises). Only the radix ints ``x``/``X``/``o`` (which reject floats
# in BOTH forms) round-trip here, over int values.
_ROUNDTRIP_CASES = [
    ('"%x" % v', _ROUNDTRIP_INTS),
    ('"%X" % v', _ROUNDTRIP_INTS),
    ('"%o" % v', _ROUNDTRIP_INTS),
    ('"%5x" % v', _ROUNDTRIP_INTS),
    ('"%05x" % v', _ROUNDTRIP_INTS),
    ('"%-5x" % v', _ROUNDTRIP_INTS),
    ('"%-05x" % v', _ROUNDTRIP_INTS),
    ('"%#x" % v', _ROUNDTRIP_INTS),
    ('"%f" % v', _ROUNDTRIP_FLOATS + _ROUNDTRIP_INTS),
    ('"%.2f" % v', _ROUNDTRIP_FLOATS + _ROUNDTRIP_INTS),
    ('"%.0f" % v', _ROUNDTRIP_FLOATS + _ROUNDTRIP_INTS),
    ('"%10.2f" % v', _ROUNDTRIP_FLOATS + _ROUNDTRIP_INTS),
    ('"%-10.2f" % v', _ROUNDTRIP_FLOATS + _ROUNDTRIP_INTS),
    ('"%+.2f" % v', _ROUNDTRIP_FLOATS + _ROUNDTRIP_INTS),
    ('"%e" % v', _ROUNDTRIP_FLOATS + _ROUNDTRIP_INTS),
    ('"%E" % v', _ROUNDTRIP_FLOATS + _ROUNDTRIP_INTS),
    ('"%g" % v', _ROUNDTRIP_FLOATS + _ROUNDTRIP_INTS),
    ('"%G" % v', _ROUNDTRIP_FLOATS + _ROUNDTRIP_INTS),
    ('"%s" % v', _ROUNDTRIP_STRS + _ROUNDTRIP_INTS + _ROUNDTRIP_FLOATS),
    ('"%r" % v', _ROUNDTRIP_STRS + _ROUNDTRIP_INTS + _ROUNDTRIP_FLOATS),
    ('"%-10s" % v', _ROUNDTRIP_STRS + _ROUNDTRIP_INTS),
    ('"%10s" % v', _ROUNDTRIP_STRS + _ROUNDTRIP_INTS),
    ('"got %x items (%s)" % (v, v)', _ROUNDTRIP_INTS),
]


def test_roundtrip_equivalence_widened_set(tmp_path):
    for i, (expr, values) in enumerate(_ROUNDTRIP_CASES):
        body = f"def f(v):\n    return {expr}\n"
        out = _converted(tmp_path, body, rel=f"m{i}.py")
        assert out.startswith("def f(v):\n    return f"), (expr, out)
        before_ns: dict = {}
        after_ns: dict = {}
        exec(body, before_ns)
        exec(out, after_ns)
        for v in values:
            assert before_ns["f"](v) == after_ns["f"](v), (expr, v)


def test_determinism_same_source_same_output(tmp_path):
    body = 'x = "%s=%x %05o %-10s" % (a, b, c, d)\n'
    first = _converted(tmp_path, body, rel="a.py")
    second = _converted(tmp_path, body, rel="b.py")
    assert first == second
    assert first == 'x = f"{a}={b:x} {c:05o} {d!s:<10}"\n'


def test_idempotent_on_converted_output(tmp_path):
    body = 'x = "%s=%x %.2f" % (a, b, c)\n'
    once = _converted(tmp_path, body, rel="once.py")
    # Feeding the already-converted f-string back in is a strict no-op.
    rel = _write(tmp_path, "twice.py", once)
    plan = plan_percent_to_fstring(tmp_path, rel)
    assert not plan.blockers
    assert not plan.new_contents


# --- blocker / no-op / fixture -------------------------------------------

def test_unparseable_is_blocker(tmp_path):
    rel = _write(tmp_path, "broken.py", "def f(:\n    pass\n")
    plan = plan_percent_to_fstring(tmp_path, rel)
    assert plan.blockers
    assert "doesn't parse" in plan.blockers[0]
    assert not plan.new_contents


def test_unreadable_is_blocker(tmp_path):
    plan = plan_percent_to_fstring(tmp_path, "does_not_exist.py")
    assert plan.blockers
    assert "cannot read" in plan.blockers[0]


def test_empty_plan_is_noop_not_failure(tmp_path):
    rel = _write(tmp_path, "mod.py", "x = 1\n")
    plan = plan_percent_to_fstring(tmp_path, rel)
    assert not plan.blockers
    assert not plan.new_contents
    assert not plan.ok


def test_fixture_path_excluded(tmp_path):
    rel = _write(tmp_path, "tests/test_thing.py", 'x = "%s" % v\n')
    plan = plan_percent_to_fstring(tmp_path, rel)
    assert not plan.blockers
    assert not plan.new_contents


def test_examples_path_excluded(tmp_path):
    rel = _write(tmp_path, "examples/demo.py", 'x = "%s" % v\n')
    plan = plan_percent_to_fstring(tmp_path, rel)
    assert not plan.new_contents


# --- self-registration ---------------------------------------------------

def test_self_registration():
    from app.engine.objective_compiler import available_objectives
    assert "percent-to-fstring" in available_objectives()
