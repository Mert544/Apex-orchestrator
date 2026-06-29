"""apex extract-constant: a repeated magic literal becomes a named constant.

Detection -> action under the family creed — only literals that can be safely
named and spliced are touched, the result re-parses, and behaviour is
unchanged (verified by exec'ing the module before and after).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.extract_constant import plan_extract_constant


def _write(tmp_path: Path, rel: str, text: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _exec_namespace(source: str) -> dict:
    """Run ``source`` as a module and return its (data-only) namespace."""
    ns: dict = {}
    exec(compile(source, "<m>", "exec"), ns)
    return {k: v for k, v in ns.items()
            if not k.startswith("__") and not callable(v)}


def test_repeated_int_extracted_and_equivalent(tmp_path):
    src = (
        "def a():\n"
        "    return 86400\n"
        "def b():\n"
        "    return 86400 + 1\n"
        "RESULT = 86400 * 2\n"
    )
    _write(tmp_path, "app/timing.py", src)

    plan = plan_extract_constant(tmp_path, "app/timing.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/timing.py"]

    assert "VALUE_86400 = 86400\n" in new
    assert new.count("VALUE_86400") == 4  # 1 definition + 3 replacements
    # The literal survives only as the constant's own value (one bare 86400).
    assert new.count("86400") == 5  # 4 names contain it + the assignment RHS
    assert plan.edits_by_file["app/timing.py"] == 3

    ast.parse(new)
    # Functional equivalence: the module-level RESULT is unchanged.
    assert _exec_namespace(src)["RESULT"] == _exec_namespace(new)["RESULT"]


def test_repeated_string_extracted_to_upper_snake(tmp_path):
    src = (
        "def get():\n"
        "    return call('https://api.example.com')\n"
        "def post():\n"
        "    return call('https://api.example.com', data=1)\n"
        "def head():\n"
        "    return probe('https://api.example.com')\n"
        "\n"
        "def call(url, data=0):\n"
        "    return (url, data)\n"
        "def probe(url):\n"
        "    return url\n"
    )
    _write(tmp_path, "app/client.py", src)

    plan = plan_extract_constant(tmp_path, "app/client.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/client.py"]

    assert "HTTPS_API_EXAMPLE_COM = 'https://api.example.com'\n" in new
    # All three standalone occurrences became the name.
    assert plan.edits_by_file["app/client.py"] == 3
    assert new.count("'https://api.example.com'") == 1  # only the definition
    ast.parse(new)
    # Functional equivalence: get() returns the same URL pair before and after.
    before, after = {}, {}
    exec(compile(src, "<b>", "exec"), before)
    exec(compile(new, "<a>", "exec"), after)
    assert before["get"]() == after["get"]()


def test_below_min_occurrences_not_extracted(tmp_path):
    src = (
        "def a():\n"
        "    return 7777\n"
        "def b():\n"
        "    return 7777\n"
    )
    _write(tmp_path, "app/two.py", src)

    plan = plan_extract_constant(tmp_path, "app/two.py", min_occurrences=3)
    assert not plan.new_contents
    assert not plan.blockers  # nothing to do, not an error
    assert plan.ok is False


def test_trivial_literals_never_extracted(tmp_path):
    src = (
        "def a():\n"
        "    return 0 + 1 + 1 + 0\n"
        "def b():\n"
        "    return '' + '' + ''\n"
        "def c():\n"
        "    return 1 - 1 - 1\n"
    )
    _write(tmp_path, "app/trivial.py", src)

    plan = plan_extract_constant(tmp_path, "app/trivial.py", min_occurrences=2)
    assert not plan.new_contents
    assert not plan.blockers


def test_name_collision_resolved_with_suffix(tmp_path):
    # A top-level binding already owns the synthesized base name.
    src = (
        "VALUE_500 = 'reserved'\n"
        "def a():\n"
        "    return 500\n"
        "def b():\n"
        "    return 500\n"
        "def c():\n"
        "    return 500\n"
    )
    _write(tmp_path, "app/coll.py", src)

    plan = plan_extract_constant(tmp_path, "app/coll.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/coll.py"]
    # Base name is taken -> suffixed, and the original binding survives intact.
    assert "VALUE_500_2 = 500\n" in new
    assert "VALUE_500 = 'reserved'\n" in new
    assert plan.edits_by_file["app/coll.py"] == 3
    ast.parse(new)


def test_no_qualifying_literal_is_empty_plan(tmp_path):
    src = (
        "def a():\n"
        "    return name(1, 0)\n"
        "def b():\n"
        "    return other()\n"
    )
    _write(tmp_path, "app/none.py", src)

    plan = plan_extract_constant(tmp_path, "app/none.py", min_occurrences=2)
    assert not plan.new_contents
    assert not plan.blockers
    assert plan.ok is False


def test_existing_module_constant_value_not_counted(tmp_path):
    # The literal sits behind a name once (RHS of NAME=...) and bare twice;
    # the assignment RHS must not count, so only 2 standalone < 3 -> no plan.
    src = (
        "TIMEOUT = 30000\n"
        "def a():\n"
        "    return 30000\n"
        "def b():\n"
        "    return 30000\n"
    )
    _write(tmp_path, "app/cfg.py", src)

    plan = plan_extract_constant(tmp_path, "app/cfg.py", min_occurrences=3)
    assert not plan.new_contents
    assert not plan.blockers


def test_docstring_strings_not_extracted(tmp_path):
    # A repeated string that only appears in docstrings is never a candidate.
    src = (
        '"""banner banner banner"""\n'
        "def a():\n"
        '    """banner banner banner"""\n'
        "    return 1\n"
        "def b():\n"
        '    """banner banner banner"""\n'
        "    return 2\n"
    )
    _write(tmp_path, "app/doc.py", src)

    plan = plan_extract_constant(tmp_path, "app/doc.py", min_occurrences=2)
    assert not plan.new_contents
    assert not plan.blockers


def test_insertion_after_imports_and_docstring(tmp_path):
    src = (
        '"""mod docstring."""\n'
        "from __future__ import annotations\n"
        "import os\n"
        "\n"
        "def a():\n"
        "    return os.getpid() + 4096\n"
        "def b():\n"
        "    return 4096\n"
        "def c():\n"
        "    return 4096\n"
    )
    _write(tmp_path, "app/ordered.py", src)

    plan = plan_extract_constant(tmp_path, "app/ordered.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    new_lines = plan.new_contents["app/ordered.py"].splitlines()
    assign_idx = next(i for i, ln in enumerate(new_lines)
                      if ln.startswith("VALUE_4096"))
    # The constant lands after the import block, before the first def.
    assert new_lines[assign_idx - 1] == "import os"
    ast.parse(plan.new_contents["app/ordered.py"])


def test_fixture_module_skipped(tmp_path):
    src = (
        "def a():\n"
        "    return 99999\n"
        "def b():\n"
        "    return 99999\n"
        "def c():\n"
        "    return 99999\n"
    )
    _write(tmp_path, "tests/test_thing.py", src)

    plan = plan_extract_constant(tmp_path, "tests/test_thing.py",
                                 min_occurrences=3)
    assert not plan.new_contents
    assert plan.blockers  # fixture path is an explicit, blocking refusal


def test_most_repeated_literal_wins(tmp_path):
    src = (
        "def a():\n"
        "    return 111 + 222\n"
        "def b():\n"
        "    return 222 + 222\n"
        "def c():\n"
        "    return 111\n"
    )
    _write(tmp_path, "app/most.py", src)

    plan = plan_extract_constant(tmp_path, "app/most.py", min_occurrences=2)
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/most.py"]
    # 222 appears 3x, 111 twice -> 222 is chosen, 111 left as a literal.
    assert "VALUE_222 = 222\n" in new
    assert "VALUE_111" not in new
    assert "111" in new
    assert plan.edits_by_file["app/most.py"] == 3


def test_float_literal_extracted(tmp_path):
    src = (
        "def a():\n"
        "    return 3.14 * 2\n"
        "def b():\n"
        "    return 3.14\n"
        "def c():\n"
        "    return 3.14 + 0.0\n"
    )
    _write(tmp_path, "app/flt.py", src)

    plan = plan_extract_constant(tmp_path, "app/flt.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/flt.py"]
    assert "VALUE_3_14 = 3.14\n" in new
    assert plan.edits_by_file["app/flt.py"] == 3
    ast.parse(new)


def test_module_not_found_blocks(tmp_path):
    plan = plan_extract_constant(tmp_path, "app/missing.py")
    assert not plan.new_contents
    assert plan.blockers


# --- Idiom denylist + descriptive naming -------------------------------------

def test_idiom_encoding_not_extracted(tmp_path):
    # 'utf-8' is a well-known idiom — repeating it never earns a constant.
    src = (
        "def a():\n"
        "    return b''.decode('utf-8')\n"
        "def b():\n"
        "    return b''.decode('utf-8')\n"
        "def c():\n"
        "    return b''.decode('utf-8')\n"
    )
    _write(tmp_path, "app/enc.py", src)

    plan = plan_extract_constant(tmp_path, "app/enc.py", min_occurrences=3)
    assert not plan.new_contents  # idiom skipped -> nothing to do
    assert not plan.blockers


def test_idiom_among_real_magic_only_real_is_chosen(tmp_path):
    # 'utf-8' appears 3x (idiom, skipped); 'content-type' 3x (real, chosen).
    src = (
        "def a():\n"
        "    return ('content-type', 'utf-8')\n"
        "def b():\n"
        "    return ('content-type', 'utf-8')\n"
        "def c():\n"
        "    return ('content-type', 'utf-8')\n"
    )
    _write(tmp_path, "app/hdr.py", src)

    plan = plan_extract_constant(tmp_path, "app/hdr.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/hdr.py"]
    # The idiom stays inline; the real header literal becomes a clean name.
    assert "CONTENT_TYPE = 'content-type'\n" in new
    assert new.count("'utf-8'") == 3  # untouched
    assert new.count("'content-type'") == 1  # only the definition
    assert plan.edits_by_file["app/hdr.py"] == 3
    ast.parse(new)


def test_content_type_named_descriptively(tmp_path):
    # A clean string slugs straight to UPPER_SNAKE, no CONST_ prefix.
    src = (
        "def a():\n"
        "    return get('content-type')\n"
        "def b():\n"
        "    return get('content-type')\n"
        "def c():\n"
        "    return get('content-type')\n"
        "\n"
        "def get(x):\n"
        "    return x\n"
    )
    _write(tmp_path, "app/ct.py", src)

    plan = plan_extract_constant(tmp_path, "app/ct.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/ct.py"]
    assert "CONTENT_TYPE = 'content-type'\n" in new
    assert "CONST_" not in new  # the machine-ish prefix is gone for good
    ast.parse(new)


def test_utf16_kept_descriptive_not_denylisted(tmp_path):
    # 'utf-16' is NOT in the denylist (only utf-8/utf8/ascii/latin-1 are);
    # it extracts to a self-describing UTF_16 name.
    src = (
        "def a():\n"
        "    return enc('utf-16')\n"
        "def b():\n"
        "    return enc('utf-16')\n"
        "def c():\n"
        "    return enc('utf-16')\n"
        "\n"
        "def enc(x):\n"
        "    return x\n"
    )
    _write(tmp_path, "app/u16.py", src)

    plan = plan_extract_constant(tmp_path, "app/u16.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/u16.py"]
    assert "UTF_16 = 'utf-16'\n" in new
    ast.parse(new)


def test_naming_is_deterministic(tmp_path):
    src = (
        "def a():\n"
        "    return tag('content-type')\n"
        "def b():\n"
        "    return tag('content-type')\n"
        "def c():\n"
        "    return tag('content-type')\n"
        "\n"
        "def tag(x):\n"
        "    return x\n"
    )
    _write(tmp_path, "app/det.py", src)

    first = plan_extract_constant(tmp_path, "app/det.py", min_occurrences=3)
    second = plan_extract_constant(tmp_path, "app/det.py", min_occurrences=3)
    # Same input -> byte-identical output, including the synthesized name.
    assert first.new_contents == second.new_contents
    assert "CONTENT_TYPE = 'content-type'\n" in first.new_contents["app/det.py"]


def test_descriptive_name_collision_suffixed(tmp_path):
    # The slugged base name is already a top-level binding -> deterministic
    # _2 suffix, original binding untouched.
    src = (
        "CONTENT_TYPE = 'reserved'\n"
        "def a():\n"
        "    return tag('content-type')\n"
        "def b():\n"
        "    return tag('content-type')\n"
        "def c():\n"
        "    return tag('content-type')\n"
        "\n"
        "def tag(x):\n"
        "    return x\n"
    )
    _write(tmp_path, "app/ctcoll.py", src)

    plan = plan_extract_constant(tmp_path, "app/ctcoll.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/ctcoll.py"]
    assert "CONTENT_TYPE_2 = 'content-type'\n" in new
    assert "CONTENT_TYPE = 'reserved'\n" in new
    ast.parse(new)


def test_denylist_boundaries(tmp_path):
    from app.execution.extract_constant import _IDIOM_DENYLIST, _qualifies

    # Members of the denylist are refused...
    for idiom in ("utf-8", "utf8", "ascii", "latin-1", "strict", "replace",
                  "ignore", "r", "w", "rb", "wb", "a", "", " ", "__main__"):
        assert idiom in _IDIOM_DENYLIST
        assert _qualifies(idiom) is False, idiom
    for n in (-1, 0, 1, 2):
        assert n in _IDIOM_DENYLIST
        assert _qualifies(n) is False

    # ...but near-neighbours just outside the boundary still qualify.
    for keep in ("utf-16", "content-type", "rw", "main", "exec"):
        assert keep not in _IDIOM_DENYLIST
        assert _qualifies(keep) is True, keep
    for n in (3, -2, 100):
        assert n not in _IDIOM_DENYLIST
        assert _qualifies(n) is True

    # bool is not an int idiom: True/False must not collapse onto 1/0.
    assert _qualifies(True) is False  # bool is never extractable anyway
    assert True not in _IDIOM_DENYLIST or _qualifies(True) is False


def test_leading_digit_slug_falls_back_to_value_prefix(tmp_path):
    # A string whose clean slug starts with a digit ('3d-model' -> '3D_MODEL')
    # is not a valid identifier on its own; it falls back to a readable
    # VALUE_-prefixed name rather than a machine-ish CONST_.
    src = (
        "def a():\n"
        "    return pick('3d-model')\n"
        "def b():\n"
        "    return pick('3d-model')\n"
        "def c():\n"
        "    return pick('3d-model')\n"
        "\n"
        "def pick(x):\n"
        "    return x\n"
    )
    _write(tmp_path, "app/dig.py", src)

    plan = plan_extract_constant(tmp_path, "app/dig.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/dig.py"]
    assert "VALUE_3D_MODEL = '3d-model'\n" in new
    assert "CONST_" not in new
    ast.parse(new)


# --- E741 ambiguous single-char names ----------------------------------------

# flake8/ruff forbids a bare ``I``/``O``/``l`` (ambiguous variable name). A short
# literal can slug straight to one of these, so the emitted constant must widen.
_AMBIGUOUS = {"I", "O", "l"}


def _assigned_name(new_source: str, value_repr: str) -> str:
    """The LHS name of the synthesized ``NAME = <value_repr>`` assignment."""
    for ln in new_source.splitlines():
        stripped = ln.strip()
        if stripped.endswith(f"= {value_repr}"):
            return stripped.split("=", 1)[0].strip()
    raise AssertionError(f"no `... = {value_repr}` assignment in:\n{new_source}")


def test_slug_to_i_widens_off_ambiguous_e741_name(tmp_path):
    # 'i!' slugs to a bare 'I' — an E741 ambiguous name. The fix widens it to a
    # readable, non-ambiguous constant rather than landing lint-dirty code.
    src = (
        "def a():\n"
        "    return tag('i!')\n"
        "def b():\n"
        "    return tag('i!')\n"
        "def c():\n"
        "    return tag('i!')\n"
        "\n"
        "def tag(x):\n"
        "    return x\n"
    )
    _write(tmp_path, "app/amb_i.py", src)

    plan = plan_extract_constant(tmp_path, "app/amb_i.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/amb_i.py"]
    name = _assigned_name(new, "'i!'")
    assert name not in _AMBIGUOUS, name          # the whole point: not 'I'
    assert name == "VALUE_I"
    assert name.isidentifier()
    assert plan.edits_by_file["app/amb_i.py"] == 3
    ast.parse(new)


def test_slug_to_o_widens_off_ambiguous_e741_name(tmp_path):
    # 'o.' slugs to a bare 'O' — likewise widened off the ambiguous set.
    src = (
        "def a():\n"
        "    return tag('o.')\n"
        "def b():\n"
        "    return tag('o.')\n"
        "def c():\n"
        "    return tag('o.')\n"
        "\n"
        "def tag(x):\n"
        "    return x\n"
    )
    _write(tmp_path, "app/amb_o.py", src)

    plan = plan_extract_constant(tmp_path, "app/amb_o.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/amb_o.py"]
    name = _assigned_name(new, "'o.'")
    assert name not in _AMBIGUOUS, name
    assert name == "VALUE_O"
    assert name.isidentifier()
    ast.parse(new)


def test_ambiguous_widening_is_collision_suffixed(tmp_path):
    # The widened base can itself collide with a top-level binding; the existing
    # _free_name suffixing still applies at the call site (deterministic _2).
    src = (
        "VALUE_I = 'reserved'\n"
        "def a():\n"
        "    return tag('i!')\n"
        "def b():\n"
        "    return tag('i!')\n"
        "def c():\n"
        "    return tag('i!')\n"
        "\n"
        "def tag(x):\n"
        "    return x\n"
    )
    _write(tmp_path, "app/amb_coll.py", src)

    plan = plan_extract_constant(tmp_path, "app/amb_coll.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    new = plan.new_contents["app/amb_coll.py"]
    assert "VALUE_I_2 = 'i!'\n" in new
    assert "VALUE_I = 'reserved'\n" in new      # original binding untouched
    assert "\nI = " not in new and not new.startswith("I = ")
    ast.parse(new)


def test_base_name_never_returns_ambiguous_single_char():
    # Unit-level guarantee: no input drives _base_name onto the E741 set.
    from app.execution.extract_constant import _base_name

    for v in ("i!", "!i!", "_i_", "i?", "o.", "O-", "(O)", "l", "I", "O"):
        assert _base_name(v) not in _AMBIGUOUS, v
    # An uppercase 'L' slug is NOT E741 (only lowercase 'l' is) -> left as-is,
    # so the non-ambiguous descriptive name is preserved, not over-widened.
    assert _base_name("(l)") == "L"
    assert _base_name("l_") == "L"


def test_non_ambiguous_names_unchanged_by_e741_guard(tmp_path):
    # Regression-lock: literals that never slug to I/O/l are byte-identical to
    # the pre-fix behaviour (the guard only touches the ambiguous outputs).
    src = (
        "def a():\n"
        "    return tag('content-type')\n"
        "def b():\n"
        "    return tag('content-type')\n"
        "def c():\n"
        "    return tag('content-type')\n"
        "\n"
        "def tag(x):\n"
        "    return x\n"
    )
    _write(tmp_path, "app/unchanged.py", src)

    plan = plan_extract_constant(tmp_path, "app/unchanged.py", min_occurrences=3)
    assert plan.ok, plan.blockers
    assert "CONTENT_TYPE = 'content-type'\n" in plan.new_contents["app/unchanged.py"]
