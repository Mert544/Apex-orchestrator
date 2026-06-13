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

    assert "CONSTANT_86400 = 86400\n" in new
    assert new.count("CONSTANT_86400") == 4  # 1 definition + 3 replacements
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

    assert "CONST_HTTPS_API_EXAMPLE_COM = 'https://api.example.com'\n" in new
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
        "CONSTANT_500 = 'reserved'\n"
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
    assert "CONSTANT_500_2 = 500\n" in new
    assert "CONSTANT_500 = 'reserved'\n" in new
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
                      if ln.startswith("CONSTANT_4096"))
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
    assert "CONSTANT_222 = 222\n" in new
    assert "CONSTANT_111" not in new
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
    assert "CONSTANT_3_14 = 3.14\n" in new
    assert plan.edits_by_file["app/flt.py"] == 3
    ast.parse(new)


def test_module_not_found_blocks(tmp_path):
    plan = plan_extract_constant(tmp_path, "app/missing.py")
    assert not plan.new_contents
    assert plan.blockers
