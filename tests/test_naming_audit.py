"""Tests for the deterministic PEP 8 naming-convention auditor.

Covers the three clear-violation cases from the spec (a lowercase class, a
CamelCase function, a mixed-case module assignment), the PEP 8-correct cases
that must NOT be flagged, every exclusion (dunders, single-letter loop vars,
test/fixture trees, framework spellings), the empty/missing-root safety paths,
and byte-for-byte determinism across repeated runs.
"""

from __future__ import annotations

from app.tools.naming_audit import NamingAudit, analyze_naming


def _violation_names(audit: NamingAudit) -> set[str]:
    return {v["name"] for v in audit.violations}


def _by_name(audit: NamingAudit, name: str) -> dict | None:
    for v in audit.violations:
        if v["name"] == name:
            return v
    return None


def test_flags_clear_violations_with_correct_expected_style(tmp_path):
    (tmp_path / "m.py").write_text(
        "class lower_case:\n"
        "    pass\n"
        "\n"
        "def CamelCase():\n"
        "    pass\n"
        "\n"
        "BADConst = 1\n",
        encoding="utf-8",
    )
    audit = analyze_naming(tmp_path)

    assert isinstance(audit, NamingAudit)
    assert audit.files_scanned == 1
    assert _violation_names(audit) == {"lower_case", "CamelCase", "BADConst"}

    # A class spelled in lowercase must be graded against PascalCase.
    cls = _by_name(audit, "lower_case")
    assert cls is not None
    assert cls["kind"] == "class"
    assert cls["expected_style"] == "PascalCase"
    assert cls["module"] == "m.py"

    # A CamelCase function must be graded against snake_case.
    fn = _by_name(audit, "CamelCase")
    assert fn is not None
    assert fn["kind"] == "function"
    assert fn["expected_style"] == "snake_case"

    # A mixed-case module assignment is a variable, not a constant, so it is
    # graded against snake_case (it is neither valid UPPER_SNAKE nor snake_case).
    var = _by_name(audit, "BADConst")
    assert var is not None
    assert var["kind"] == "variable"
    assert var["expected_style"] == "snake_case"


def test_camelcase_method_and_async_function_flagged(tmp_path):
    (tmp_path / "m.py").write_text(
        "class GoodClass:\n"
        "    def doThing(self):\n"        # camelCase method -> snake_case
        "        pass\n"
        "\n"
        "async def AnotherCamel():\n"      # async def graded the same way
        "    pass\n",
        encoding="utf-8",
    )
    audit = analyze_naming(tmp_path)
    assert _violation_names(audit) == {"doThing", "AnotherCamel"}
    for name in ("doThing", "AnotherCamel"):
        assert _by_name(audit, name)["kind"] == "function"
        assert _by_name(audit, name)["expected_style"] == "snake_case"


def test_pep8_correct_names_are_not_flagged(tmp_path):
    (tmp_path / "m.py").write_text(
        "MAX_FILES = 500\n"               # valid UPPER_SNAKE constant
        "default_value = 1\n"             # valid snake_case variable
        "_private = 2\n"                  # leading-underscore snake is fine
        "\n"
        "class ProjectProfile:\n"         # valid PascalCase
        "    pass\n"
        "\n"
        "class HTTPServer:\n"             # Pascal with leading acronym is fine
        "    pass\n"
        "\n"
        "def run_step(value):\n"          # valid snake_case
        "    return value\n",
        encoding="utf-8",
    )
    audit = analyze_naming(tmp_path)
    assert audit.violations == []
    # Counts still reflect every graded declaration.
    assert audit.functions == 1
    assert audit.classes == 2
    assert audit.variables == 3


def test_acronym_class_and_allcaps_function_are_ambiguous_and_skipped(tmp_path):
    # All-caps class (acronym) and all-caps function/var (would-be constant) are
    # ambiguous, not clear camelCase slips, so the conservative auditor skips
    # them rather than risk a false positive.
    (tmp_path / "m.py").write_text(
        "class HTTP:\n"
        "    pass\n"
        "\n"
        "def FOO():\n"
        "    pass\n"
        "\n"
        "ALIAS = 1\n",                    # valid UPPER_SNAKE constant
        encoding="utf-8",
    )
    audit = analyze_naming(tmp_path)
    assert audit.violations == []


def test_dunders_are_excluded(tmp_path):
    (tmp_path / "m.py").write_text(
        "__all__ = ['x']\n"               # dunder module var -> excluded
        "\n"
        "class C:\n"
        "    def __init__(self):\n"       # dunder method -> excluded
        "        pass\n"
        "    def __myDunderish__(self):\n"  # still a dunder shape -> excluded
        "        pass\n",
        encoding="utf-8",
    )
    audit = analyze_naming(tmp_path)
    assert audit.violations == []


def test_single_letter_loop_var_not_flagged(tmp_path):
    (tmp_path / "m.py").write_text(
        "def good_func(items):\n"
        "    for i in items:\n"           # single-char loop var -> excluded
        "        print(i)\n"
        "    return items\n",
        encoding="utf-8",
    )
    audit = analyze_naming(tmp_path)
    assert audit.violations == []


def test_single_letter_module_var_not_flagged(tmp_path):
    (tmp_path / "m.py").write_text("T = object()\n", encoding="utf-8")
    audit = analyze_naming(tmp_path)
    assert audit.violations == []


def test_framework_method_names_excluded(tmp_path):
    (tmp_path / "m.py").write_text(
        "class Handler:\n"
        "    def setUp(self):\n"          # unittest protocol -> excluded
        "        pass\n"
        "    def do_GET(self):\n"         # http.server dispatch -> excluded
        "        pass\n",
        encoding="utf-8",
    )
    audit = analyze_naming(tmp_path)
    assert audit.violations == []


def test_test_and_fixture_files_never_graded(tmp_path):
    # A file under a tests/ tree may use any casing freely; it is counted as
    # scanned-but-skipped, so its names never appear as violations.
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_thing.py").write_text(
        "class badClass:\n"
        "    pass\n"
        "def CamelHelper():\n"
        "    pass\n",
        encoding="utf-8",
    )
    # A test_-prefixed file at the root is also skipped.
    (tmp_path / "test_root.py").write_text("def AnotherCamel():\n    pass\n",
                                           encoding="utf-8")
    audit = analyze_naming(tmp_path)
    assert audit.violations == []
    assert audit.files_scanned == 0  # both files were skipped, not graded


def test_nested_assignments_not_graded_as_module_constants(tmp_path):
    # Only module-level (depth 0) assignments are graded. A function-local or
    # class-body assignment with odd casing is left alone.
    (tmp_path / "m.py").write_text(
        "def f():\n"
        "    badLocal = 1\n"              # local -> not graded
        "    return badLocal\n"
        "\n"
        "class C:\n"
        "    badAttr = 2\n",             # class attribute -> not graded
        encoding="utf-8",
    )
    audit = analyze_naming(tmp_path)
    assert audit.violations == []
    assert audit.variables == 0


def test_annotated_module_assignment_is_graded(tmp_path):
    (tmp_path / "m.py").write_text("badVar: int = 1\n", encoding="utf-8")
    audit = analyze_naming(tmp_path)
    assert _violation_names(audit) == {"badVar"}
    assert _by_name(audit, "badVar")["kind"] == "variable"
    assert _by_name(audit, "badVar")["expected_style"] == "snake_case"


def test_allcaps_constant_with_bad_chars_flagged_upper_snake(tmp_path):
    # An all-caps name that isn't valid UPPER_SNAKE (here it cannot occur via a
    # plain identifier with hyphens, so use a leading-digit-free all-caps name
    # that fails the regex only via... ) — guard the UPPER_SNAKE branch.
    (tmp_path / "m.py").write_text("ALLÄCAPS = 1\n", encoding="utf-8")
    audit = analyze_naming(tmp_path)
    # The name is all-caps (isupper True) but not ASCII UPPER_SNAKE -> flagged
    # as a malformed constant.
    assert _violation_names(audit) == {"ALLÄCAPS"}
    assert _by_name(audit, "ALLÄCAPS")["expected_style"] == "UPPER_SNAKE"


def test_empty_root_is_safe(tmp_path):
    audit = analyze_naming(tmp_path)
    assert isinstance(audit, NamingAudit)
    assert audit.files_scanned == 0
    assert audit.functions == 0
    assert audit.classes == 0
    assert audit.variables == 0
    assert audit.violations == []


def test_missing_root_is_safe(tmp_path):
    audit = analyze_naming(tmp_path / "does_not_exist")
    assert isinstance(audit, NamingAudit)
    assert audit.files_scanned == 0
    assert audit.violations == []


def test_unparsable_source_is_skipped_not_counted(tmp_path):
    (tmp_path / "broken.py").write_text("def oops(:\n    pass\n", encoding="utf-8")
    (tmp_path / "ok.py").write_text("def CamelCase():\n    pass\n", encoding="utf-8")
    audit = analyze_naming(tmp_path)
    # Only the parseable file is scanned/graded.
    assert audit.files_scanned == 1
    assert _violation_names(audit) == {"CamelCase"}


def test_violations_are_capped_and_sorted(tmp_path):
    # 30 distinct camelCase functions across two modules; the cap keeps ~20 and
    # the order is deterministic by (module, kind, name).
    a_src = "".join(f"def camelA{i:02d}():\n    pass\n" for i in range(15))
    b_src = "".join(f"def camelB{i:02d}():\n    pass\n" for i in range(15))
    (tmp_path / "a.py").write_text(a_src, encoding="utf-8")
    (tmp_path / "b.py").write_text(b_src, encoding="utf-8")
    audit = analyze_naming(tmp_path)
    assert len(audit.violations) == 20
    keys = [(v["module"], v["kind"], v["name"]) for v in audit.violations]
    assert keys == sorted(keys)
    # Sorting before the cap means module 'a' fills the cap first.
    assert all(v["module"] == "a.py" for v in audit.violations[:15])


def test_max_files_cap_is_respected(tmp_path):
    for i in range(5):
        (tmp_path / f"m{i}.py").write_text("x = 1\n", encoding="utf-8")
    audit = analyze_naming(tmp_path, max_files=2)
    assert audit.files_scanned == 2


def test_determinism_repeated_runs_identical(tmp_path):
    (tmp_path / "m.py").write_text(
        "class lower_case:\n"
        "    pass\n"
        "def CamelCase():\n"
        "    pass\n"
        "BADConst = 1\n",
        encoding="utf-8",
    )
    first = analyze_naming(tmp_path)
    second = analyze_naming(tmp_path)
    assert first == second
    assert first.violations == second.violations
