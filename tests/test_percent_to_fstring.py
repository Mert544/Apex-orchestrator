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


def test_percent_d_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%d" % n\n')


def test_percent_r_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%r" % n\n')


def test_percent_f_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%f" % n\n')


def test_mapping_key_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%(name)s" % d\n')


def test_width_spec_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%5s" % v\n')


def test_precision_spec_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%.2f" % v\n')


def test_flag_spec_untouched(tmp_path):
    _untouched(tmp_path, 'x = "%-s" % v\n')


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
