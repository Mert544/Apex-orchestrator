"""Tests for the deterministic return-consistency analyzer.

Covers the headline cases from the spec: a function that returns a value on one
branch and bare-returns on another is flagged; a consistently value-returning
function is not; a generator is excluded; a None-returning (side-effect-only)
function is not flagged; an empty tree is safe; repeated runs are byte-for-byte
identical; and the implicit fall-through path is detected too.
"""

from __future__ import annotations

from app.tools.return_consistency import (
    ReturnConsistency,
    analyze_return_consistency,
)

# Value on one branch, bare return on another -> offender (bare-return).
MIXED_BARE = (
    "def find(xs, target):\n"
    "    for x in xs:\n"
    "        if x == target:\n"
    "            return x\n"
    "        else:\n"
    "            return\n"
)

# Value on the if-branch, implicit fall-through off the end -> offender.
MIXED_FALLTHROUGH = (
    "def first_even(xs):\n"
    "    for x in xs:\n"
    "        if x % 2 == 0:\n"
    "            return x\n"
)

# Every path returns a value -> consistent, not flagged.
CONSISTENT_VALUE = (
    "def sign(n):\n"
    "    if n > 0:\n"
    "        return 1\n"
    "    elif n < 0:\n"
    "        return -1\n"
    "    else:\n"
    "        return 0\n"
)

# Contains yield -> generator, excluded even though it has a bare return.
GENERATOR = (
    "def gen(xs):\n"
    "    for x in xs:\n"
    "        if x is None:\n"
    "            return\n"
    "        yield x\n"
)

# No value-bearing return anywhere -> consistently None, not flagged.
NONE_RETURNING = (
    "def log(msg):\n"
    "    print(msg)\n"
    "    return\n"
)


def test_mixed_value_and_bare_return_is_flagged(tmp_path):
    (tmp_path / "m.py").write_text(MIXED_BARE, encoding="utf-8")
    rc = analyze_return_consistency(tmp_path)
    assert isinstance(rc, ReturnConsistency)
    assert rc.offender_count == 1
    assert rc.offenders == [
        {"module": "m.py", "function": "find", "line": 1, "reason": "bare-return"}
    ]


def test_implicit_fall_through_is_flagged(tmp_path):
    (tmp_path / "m.py").write_text(MIXED_FALLTHROUGH, encoding="utf-8")
    rc = analyze_return_consistency(tmp_path)
    assert rc.offender_count == 1
    assert rc.offenders[0]["function"] == "first_even"
    assert rc.offenders[0]["reason"] == "implicit-fall-through"


def test_consistently_value_returning_not_flagged(tmp_path):
    (tmp_path / "m.py").write_text(CONSISTENT_VALUE, encoding="utf-8")
    rc = analyze_return_consistency(tmp_path)
    assert rc.offenders == []
    assert rc.offender_count == 0


def test_generator_excluded(tmp_path):
    (tmp_path / "m.py").write_text(GENERATOR, encoding="utf-8")
    rc = analyze_return_consistency(tmp_path)
    assert rc.offenders == []


def test_none_returning_not_flagged(tmp_path):
    (tmp_path / "m.py").write_text(NONE_RETURNING, encoding="utf-8")
    rc = analyze_return_consistency(tmp_path)
    assert rc.offenders == []


def test_dunder_excluded(tmp_path):
    src = (
        "class C:\n"
        "    def __eq__(self, other):\n"
        "        if other is None:\n"
        "            return\n"
        "        return self is other\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    rc = analyze_return_consistency(tmp_path)
    assert rc.offenders == []


def test_tests_and_fixtures_excluded(tmp_path):
    tdir = tmp_path / "tests"
    tdir.mkdir()
    (tdir / "test_x.py").write_text(MIXED_BARE, encoding="utf-8")
    (tmp_path / "conftest.py").write_text(MIXED_BARE, encoding="utf-8")
    rc = analyze_return_consistency(tmp_path)
    assert rc.offenders == []


def test_explicit_return_none_counts_as_bare(tmp_path):
    src = (
        "def f(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        "    return None\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    rc = analyze_return_consistency(tmp_path)
    assert rc.offenders[0]["reason"] == "bare-return"


def test_raise_path_does_not_count_as_fall_through(tmp_path):
    src = (
        "def f(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        "    raise ValueError('no')\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    rc = analyze_return_consistency(tmp_path)
    assert rc.offenders == []


def test_empty_tree_is_safe(tmp_path):
    rc = analyze_return_consistency(tmp_path)
    assert rc == ReturnConsistency()
    assert rc.offenders == []
    assert rc.offender_count == 0


def test_missing_root_is_safe(tmp_path):
    rc = analyze_return_consistency(tmp_path / "does_not_exist")
    assert rc.offenders == []
    assert rc.offender_count == 0


def test_unparseable_file_skipped(tmp_path):
    (tmp_path / "bad.py").write_text("def f(:\n", encoding="utf-8")
    (tmp_path / "good.py").write_text(MIXED_BARE, encoding="utf-8")
    rc = analyze_return_consistency(tmp_path)
    assert [o["module"] for o in rc.offenders] == ["good.py"]


def test_determinism(tmp_path):
    (tmp_path / "a.py").write_text(MIXED_BARE, encoding="utf-8")
    (tmp_path / "b.py").write_text(MIXED_FALLTHROUGH, encoding="utf-8")
    first = analyze_return_consistency(tmp_path)
    second = analyze_return_consistency(tmp_path)
    assert first == second
    assert first.to_dict() == second.to_dict()
