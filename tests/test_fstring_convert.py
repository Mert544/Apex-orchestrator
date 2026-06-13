"""Tests for the fstring-convert develop objective."""

from __future__ import annotations

from pathlib import Path

from app.execution.fstring_convert import plan_fstring_convert


def _write(tmp_path: Path, rel: str, body: str) -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return rel


def _converted(tmp_path: Path, body: str, rel: str = "mod.py") -> str:
    _write(tmp_path, rel, body)
    plan = plan_fstring_convert(tmp_path, rel)
    assert not plan.blockers
    return plan.new_contents.get(rel, body)


# --- conversions that SHOULD happen --------------------------------------

def test_two_placeholders(tmp_path):
    out = _converted(tmp_path, 'x = "{} = {}".format(a, b)\n')
    assert out == 'x = f"{a} = {b}"\n'


def test_single_placeholder(tmp_path):
    out = _converted(tmp_path, 'x = "x={}".format(v)\n')
    assert out == 'x = f"x={v}"\n'


def test_attribute_arg(tmp_path):
    out = _converted(tmp_path, 'x = "{}".format(self.name)\n')
    assert out == 'x = f"{self.name}"\n'


def test_constant_arg(tmp_path):
    out = _converted(tmp_path, 'x = "{}".format(42)\n')
    assert out == 'x = f"{42}"\n'


def test_single_quote_preserved(tmp_path):
    out = _converted(tmp_path, "x = '{}'.format(v)\n")
    assert out == "x = f'{v}'\n"


def test_edits_count_and_plan_fields(tmp_path):
    rel = _write(tmp_path, "mod.py", 'a = "{}".format(p)\nb = "{}".format(q)\n')
    plan = plan_fstring_convert(tmp_path, rel)
    assert plan.old == rel
    assert plan.new == "fstring-convert"
    assert plan.edits_by_file[rel] == 2
    assert plan.originals[rel] == 'a = "{}".format(p)\nb = "{}".format(q)\n'
    assert plan.new_contents[rel] == 'a = f"{p}"\nb = f"{q}"\n'


# --- shapes that MUST be left untouched ----------------------------------

def _untouched(tmp_path: Path, body: str, rel: str = "mod.py") -> None:
    _write(tmp_path, rel, body)
    plan = plan_fstring_convert(tmp_path, rel)
    assert not plan.blockers
    assert not plan.new_contents


def test_indexed_placeholder_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{0}".format(a)\n')


def test_named_placeholder_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{x}".format(x=1)\n')


def test_format_spec_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{:0.2f}".format(p)\n')


def test_conversion_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{!r}".format(p)\n')


def test_mismatched_count_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{} {}".format(a)\n')


def test_keyword_arg_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{}".format(v=1)\n')


def test_star_arg_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{}".format(*args)\n')


def test_call_arg_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{}".format(f())\n')


def test_subscript_arg_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{}".format(d[k])\n')


def test_binop_arg_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{}".format(a + b)\n')


def test_escaped_braces_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{{}}".format()\n')


def test_lone_brace_untouched(tmp_path):
    _untouched(tmp_path, 'x = "a } b {}".format(v)\n')


def test_no_placeholder_untouched(tmp_path):
    _untouched(tmp_path, 'x = "plain".format()\n')


def test_backslash_in_template_untouched(tmp_path):
    _untouched(tmp_path, 'x = "a\\tb {}".format(v)\n')


def test_already_fstring_untouched(tmp_path):
    # An f-string has no .format() call to convert; nothing matches.
    _untouched(tmp_path, 'x = f"{v}"\n')


def test_raw_string_template_untouched(tmp_path):
    _untouched(tmp_path, 'x = r"{}".format(v)\n')


def test_bytes_template_untouched(tmp_path):
    # bytes has no str .format placeholder semantics; func.value isn't a str.
    _untouched(tmp_path, 'x = b"{}".format(v)\n')


def test_multiline_call_untouched(tmp_path):
    _untouched(tmp_path, 'x = "{} {}".format(\n    a, b)\n')


def test_format_on_non_literal_untouched(tmp_path):
    # .format() on a variable, not a string literal — out of scope.
    _untouched(tmp_path, 'x = template.format(v)\n')


# --- semantic equivalence ------------------------------------------------

def test_semantic_equivalence(tmp_path):
    body = 'def render(a, b):\n    return "{} and {} = {}".format(a, b, a)\n'
    out = _converted(tmp_path, body)
    assert out == 'def render(a, b):\n    return f"{a} and {b} = {a}"\n'
    before_ns: dict = {}
    after_ns: dict = {}
    exec(body, before_ns)
    exec(out, after_ns)
    for a, b in [(1, 2), ("x", "y"), (0, 0), (3.5, 4)]:
        assert before_ns["render"](a, b) == after_ns["render"](a, b)


def test_semantic_equivalence_constant_and_attr(tmp_path):
    body = (
        "class C:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "    def label(self):\n"
        '        return "n={} v={}".format(self.name, 7)\n'
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
    plan = plan_fstring_convert(tmp_path, rel)
    assert plan.blockers
    assert "doesn't parse" in plan.blockers[0]
    assert not plan.new_contents


def test_unreadable_is_blocker(tmp_path):
    plan = plan_fstring_convert(tmp_path, "does_not_exist.py")
    assert plan.blockers
    assert "cannot read" in plan.blockers[0]


def test_empty_plan_is_noop_not_failure(tmp_path):
    rel = _write(tmp_path, "mod.py", "x = 1\n")
    plan = plan_fstring_convert(tmp_path, rel)
    assert not plan.blockers
    assert not plan.new_contents
    assert not plan.ok


def test_fixture_path_excluded(tmp_path):
    rel = _write(tmp_path, "tests/test_thing.py", 'x = "{}".format(v)\n')
    plan = plan_fstring_convert(tmp_path, rel)
    assert not plan.blockers
    assert not plan.new_contents


def test_examples_path_excluded(tmp_path):
    rel = _write(tmp_path, "examples/demo.py", 'x = "{}".format(v)\n')
    plan = plan_fstring_convert(tmp_path, rel)
    assert not plan.new_contents


# --- self-registration ---------------------------------------------------

def test_self_registration():
    from app.engine.objective_compiler import available_objectives
    assert "fstring-convert" in available_objectives()
