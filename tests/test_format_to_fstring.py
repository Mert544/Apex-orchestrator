"""Tests for the format-to-fstring develop objective."""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.format_to_fstring import plan_format_to_fstring


def _write(tmp_path: Path, rel: str, body: str) -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return rel


def _converted(tmp_path: Path, body: str, rel: str = "mod.py") -> str:
    _write(tmp_path, rel, body)
    plan = plan_format_to_fstring(tmp_path, rel)
    assert not plan.blockers
    return plan.new_contents.get(rel, body)


def _untouched(tmp_path: Path, body: str, rel: str = "mod.py") -> None:
    _write(tmp_path, rel, body)
    plan = plan_format_to_fstring(tmp_path, rel)
    assert not plan.blockers
    assert not plan.new_contents


# --- conversions that SHOULD happen --------------------------------------

def test_empty_field_single_arg(tmp_path):
    out = _converted(tmp_path, 'x = "{}".format(x)\n')
    assert out == 'x = f"{x}"\n'


def test_empty_fields_two_args(tmp_path):
    out = _converted(tmp_path, 'x = "{} = {}".format(a, b)\n')
    assert out == 'x = f"{a} = {b}"\n'


def test_indexed_fields(tmp_path):
    out = _converted(tmp_path, 'x = "{0}-{1}".format(a, b)\n')
    assert out == 'x = f"{a}-{b}"\n'


def test_named_field(tmp_path):
    out = _converted(tmp_path, 'x = "{n}".format(n=v)\n')
    assert out == 'x = f"{v}"\n'


def test_named_fields_two(tmp_path):
    out = _converted(tmp_path, 'x = "{a}:{b}".format(a=p, b=q)\n')
    assert out == 'x = f"{p}:{q}"\n'


def test_literal_text_around_fields(tmp_path):
    out = _converted(tmp_path, 'x = "x={}".format(v)\n')
    assert out == 'x = f"x={v}"\n'


def test_attribute_arg(tmp_path):
    out = _converted(tmp_path, 'x = "{}".format(self.name)\n')
    assert out == 'x = f"{self.name}"\n'


def test_subscript_arg(tmp_path):
    out = _converted(tmp_path, 'x = "{}".format(d[k])\n')
    assert out == 'x = f"{d[k]}"\n'


def test_call_arg(tmp_path):
    out = _converted(tmp_path, 'x = "{}".format(f())\n')
    assert out == 'x = f"{f()}"\n'


def test_constant_arg(tmp_path):
    out = _converted(tmp_path, 'x = "{}".format(42)\n')
    assert out == 'x = f"{42}"\n'


def test_single_quote_preserved(tmp_path):
    out = _converted(tmp_path, "x = '{}'.format(v)\n")
    assert out == "x = f'{v}'\n"


def test_indexed_out_of_order(tmp_path):
    out = _converted(tmp_path, 'x = "{1}-{0}".format(a, b)\n')
    assert out == 'x = f"{b}-{a}"\n'


def test_indexed_repeated_name(tmp_path):
    # A positional Name reused across fields is fine (pure reference).
    out = _converted(tmp_path, 'x = "{0}{0}".format(a)\n')
    assert out == 'x = f"{a}{a}"\n'


def test_named_repeated_name(tmp_path):
    out = _converted(tmp_path, 'x = "{n}-{n}".format(n=v)\n')
    assert out == 'x = f"{v}-{v}"\n'


def test_multiple_occurrences(tmp_path):
    rel = _write(tmp_path, "mod.py", 'a = "{}".format(p)\nb = "{}".format(q)\n')
    plan = plan_format_to_fstring(tmp_path, rel)
    assert plan.edits_by_file[rel] == 2
    assert plan.new_contents[rel] == 'a = f"{p}"\nb = f"{q}"\n'


def test_two_occurrences_on_one_line(tmp_path):
    # Right-to-left column splicing keeps both offsets valid.
    out = _converted(tmp_path, 'x = "{}".format(a) + "{}".format(b)\n')
    assert out == 'x = f"{a}" + f"{b}"\n'


def test_edits_count_and_plan_fields(tmp_path):
    rel = _write(tmp_path, "mod.py", 'a = "{}".format(p)\nb = "x={}".format(q)\n')
    plan = plan_format_to_fstring(tmp_path, rel)
    assert plan.old == rel
    assert plan.new == "format-to-fstring"
    assert plan.edits_by_file[rel] == 2
    assert plan.originals[rel] == 'a = "{}".format(p)\nb = "x={}".format(q)\n'
    assert plan.new_contents[rel] == 'a = f"{p}"\nb = f"x={q}"\n'


# --- shapes that MUST be left untouched ----------------------------------

def test_format_spec_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{:0.2f}".format(v)\n')


def test_conversion_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{!r}".format(v)\n')


def test_indexed_format_spec_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{0:>5}".format(v)\n')


def test_named_format_spec_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{n:d}".format(n=v)\n')


def test_attribute_access_in_field_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{0.name}".format(obj)\n')


def test_index_access_in_field_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{0[1]}".format(seq)\n')


def test_escaped_braces_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{{}}".format()\n')


def test_escaped_brace_with_field_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{{}} {}".format(v)\n')


def test_lone_close_brace_untouched(tmp_path):
    _untouched(tmp_path, 'x = "} {}".format(v)\n')


def test_unterminated_field_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{ no close".format()\n')


def test_kwargs_unpacking_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{n}".format(**kw)\n')


def test_args_unpacking_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{}".format(*args)\n')


def test_too_few_args_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{} {}".format(a)\n')


def test_too_many_args_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{}".format(a, b)\n')


def test_index_out_of_range_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{1}".format(a)\n')


def test_leftover_positional_untouched(tmp_path):
    # {0} consumes a, but b is never referenced.
    _untouched(tmp_path, 'x = "{0}".format(a, b)\n')


def test_leftover_keyword_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{a}".format(a=p, b=q)\n')


def test_missing_keyword_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{n}".format(m=v)\n')


def test_mixed_auto_and_index_untouched(tmp_path):
    # str.format itself forbids mixing automatic and manual numbering.
    _untouched(tmp_path, 'x = "{} {0}".format(a, b)\n')


def test_mixed_auto_and_named_consumes_positional(tmp_path):
    # {} consumes positional a; {n} consumes keyword v — both referenced.
    out = _converted(tmp_path, 'x = "{} {n}".format(a, n=v)\n')
    assert out == 'x = f"{a} {v}"\n'


def test_repeated_call_arg_untouched(tmp_path):
    # An f-string would call f() twice; .format() evaluates the arg once.
    _untouched(tmp_path, 'x = "{0}{0}".format(f())\n')


def test_repeated_named_call_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{n}{n}".format(n=g())\n')


def test_binop_arg_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{}".format(a + b)\n')


def test_ternary_arg_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{}".format(a if c else b)\n')


def test_no_field_untouched(tmp_path):
    _untouched(tmp_path, 'x = "plain".format()\n')


def test_raw_string_template_untouched(tmp_path):
    _untouched(tmp_path, 'x = r"{}".format(v)\n')


def test_bytes_template_untouched(tmp_path):
    # bytes has no .format that we model; left is a bytes Constant.
    _untouched(tmp_path, 'x = b"{}".format(v)\n')


def test_fstring_template_untouched(tmp_path):
    # value of the attribute is a JoinedStr, not an ast.Constant — no match.
    _untouched(tmp_path, 'x = f"{y}".format(v)\n')


def test_backslash_in_template_untouched(tmp_path):
    _untouched(tmp_path, 'x = "a\\tb {}".format(v)\n')


def test_quote_in_template_untouched(tmp_path):
    # An inner double-quote would break a double-quoted f-string.
    _untouched(tmp_path, "x = \"say \\\"{}\\\"\".format(v)\n")


def test_multiline_call_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{} {}".format(\n    a, b)\n')


def test_not_str_literal_receiver_untouched(tmp_path):
    # .format on a variable, not a string literal — out of scope.
    _untouched(tmp_path, 'x = template.format(v)\n')


def test_other_method_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{}".join(v)\n')


def test_negative_index_untouched(tmp_path):
    # "{-1}" is not a valid field; str.format would raise — skip.
    _untouched(tmp_path, 'x = "{-1}".format(a)\n')


# --- semantic equivalence ------------------------------------------------

def test_semantic_equivalence_empty_fields(tmp_path):
    body = 'def render(a, b):\n    return "{} and {} = {}".format(a, b, a)\n'
    out = _converted(tmp_path, body)
    assert out == 'def render(a, b):\n    return f"{a} and {b} = {a}"\n'
    before_ns: dict = {}
    after_ns: dict = {}
    exec(body, before_ns)
    exec(out, after_ns)
    for a, b in [(1, 2), ("x", "y"), (0, 0), (3.5, 4)]:
        assert before_ns["render"](a, b) == after_ns["render"](a, b)


def test_semantic_equivalence_indexed(tmp_path):
    body = 'def f(a, b):\n    return "{1}/{0}".format(a, b)\n'
    out = _converted(tmp_path, body)
    assert out == 'def f(a, b):\n    return f"{b}/{a}"\n'
    before_ns: dict = {}
    after_ns: dict = {}
    exec(body, before_ns)
    exec(out, after_ns)
    for a, b in [(1, 2), ("p", "q"), (0, 9)]:
        assert before_ns["f"](a, b) == after_ns["f"](a, b)


def test_semantic_equivalence_named(tmp_path):
    body = 'def f(v):\n    return "name={n}!".format(n=v)\n'
    out = _converted(tmp_path, body)
    assert out == 'def f(v):\n    return f"name={v}!"\n'
    before_ns: dict = {}
    after_ns: dict = {}
    exec(body, before_ns)
    exec(out, after_ns)
    for v in [1, "hi", 0, 3.5]:
        assert before_ns["f"](v) == after_ns["f"](v)


def test_semantic_equivalence_attr_and_subscript(tmp_path):
    body = (
        "class C:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "    def label(self, d):\n"
        '        return "n={} k={}".format(self.name, d[0])\n'
    )
    out = _converted(tmp_path, body)
    before_ns: dict = {}
    after_ns: dict = {}
    exec(body, before_ns)
    exec(out, after_ns)
    assert (before_ns["C"]("hi").label(["z"])
            == after_ns["C"]("hi").label(["z"]))


# --- the produced f-string must re-parse (guard) -------------------------

def test_produced_fstring_reparses(tmp_path):
    out = _converted(tmp_path, 'x = "{0}-{1}-{n}".format(a, b, n=c)\n')
    assert out == 'x = f"{a}-{b}-{c}"\n'
    # Re-parse guard: the whole module re-parses, and the new RHS is a JoinedStr.
    tree = ast.parse(out)
    joined = [n for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)]
    assert len(joined) == 1
    fmt = [v for v in joined[0].values if isinstance(v, ast.FormattedValue)]
    assert len(fmt) == 3


# --- determinism ---------------------------------------------------------

def test_determinism(tmp_path):
    body = (
        'a = "{}".format(p)\n'
        'b = "{0}-{1}".format(q, r)\n'
        'c = "{name}".format(name=s)\n'
    )
    rel = _write(tmp_path, "mod.py", body)
    first = plan_format_to_fstring(tmp_path, rel).new_contents[rel]
    for _ in range(5):
        again = plan_format_to_fstring(tmp_path, rel).new_contents[rel]
        assert again == first
    assert first == ('a = f"{p}"\n'
                     'b = f"{q}-{r}"\n'
                     'c = f"{s}"\n')


# --- blocker / no-op / fixture -------------------------------------------

def test_unparseable_is_blocker(tmp_path):
    rel = _write(tmp_path, "broken.py", "def f(:\n    pass\n")
    plan = plan_format_to_fstring(tmp_path, rel)
    assert plan.blockers
    assert "doesn't parse" in plan.blockers[0]
    assert not plan.new_contents


def test_unreadable_is_blocker(tmp_path):
    plan = plan_format_to_fstring(tmp_path, "does_not_exist.py")
    assert plan.blockers
    assert "cannot read" in plan.blockers[0]


def test_empty_plan_is_noop_not_failure(tmp_path):
    rel = _write(tmp_path, "mod.py", "x = 1\n")
    plan = plan_format_to_fstring(tmp_path, rel)
    assert not plan.blockers
    assert not plan.new_contents
    assert not plan.ok


def test_fixture_path_excluded(tmp_path):
    rel = _write(tmp_path, "tests/test_thing.py", 'x = "{}".format(v)\n')
    plan = plan_format_to_fstring(tmp_path, rel)
    assert not plan.blockers
    assert not plan.new_contents


def test_examples_path_excluded(tmp_path):
    rel = _write(tmp_path, "examples/demo.py", 'x = "{}".format(v)\n')
    plan = plan_format_to_fstring(tmp_path, rel)
    assert not plan.new_contents


# --- self-registration ---------------------------------------------------

def test_self_registration():
    from app.engine.objective_compiler import available_objectives
    assert "format-to-fstring" in available_objectives()
