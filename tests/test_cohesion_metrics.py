"""Tests for the deterministic class-cohesion (LCOM-style) analyzer."""

from __future__ import annotations

from pathlib import Path

from app.tools.cohesion_metrics import (
    ClassCohesion,
    CohesionMetrics,
    analyze_cohesion,
)


def _write(root: Path, name: str, body: str) -> None:
    (root / name).write_text(body, encoding="utf-8")


def test_high_cohesion_class_not_flagged_below_one(tmp_path: Path) -> None:
    """All methods share ``self.x`` -> every pair connects -> cohesion 1.0."""
    _write(
        tmp_path,
        "high.py",
        '''
class Counter:
    def __init__(self):
        self.x = 0

    def inc(self):
        self.x += 1

    def dec(self):
        self.x -= 1

    def value(self):
        return self.x
''',
    )
    result = analyze_cohesion(tmp_path)
    by_name = {c.classname: c for c in result.low_cohesion}
    assert by_name["Counter"].cohesion == 1.0
    assert by_name["Counter"].methods == 3  # __init__ excluded (dunder)


def test_low_cohesion_two_disjoint_groups_flagged(tmp_path: Path) -> None:
    """Two method-groups on disjoint attrs -> low cohesion, flagged first."""
    _write(
        tmp_path,
        "low.py",
        '''
class Split:
    def __init__(self):
        self.a = 0
        self.b = 0

    def read_a(self):
        return self.a

    def write_a(self):
        self.a = 1

    def read_b(self):
        return self.b

    def write_b(self):
        self.b = 1
''',
    )
    result = analyze_cohesion(tmp_path)
    flagged = {c.classname: c for c in result.low_cohesion}
    assert "Split" in flagged
    # 4 attr-methods -> 6 pairs; only (read_a,write_a) and (read_b,write_b)
    # share -> 2/6.
    assert flagged["Split"].cohesion == round(2 / 6, 4)
    assert flagged["Split"].methods == 4


def test_explicit_formula_pin(tmp_path: Path) -> None:
    """Pin the exact LCOM variant on a hand-computed 3-method case.

    m1 touches {a}, m2 touches {a, b}, m3 touches {b}. Pairs: (m1,m2) share a,
    (m2,m3) share b, (m1,m3) disjoint -> share=2, |P|=3 -> cohesion=2/3.
    """
    _write(
        tmp_path,
        "pin.py",
        '''
class Chain:
    def m1(self):
        return self.a

    def m2(self):
        return self.a + self.b

    def m3(self):
        return self.b
''',
    )
    result = analyze_cohesion(tmp_path)
    chain = next(c for c in result.low_cohesion if c.classname == "Chain")
    assert chain.cohesion == round(2 / 3, 4)
    assert chain.methods == 3


def test_single_method_class_skipped(tmp_path: Path) -> None:
    """A class with <2 attribute-touching methods is undefined -> skipped."""
    _write(
        tmp_path,
        "one.py",
        '''
class Lonely:
    def only(self):
        return self.x
''',
    )
    result = analyze_cohesion(tmp_path)
    assert all(c.classname != "Lonely" for c in result.low_cohesion)
    assert result.classes_skipped == 1
    assert result.classes_analyzed == 0


def test_staticmethod_classmethod_and_no_attr_methods_excluded(tmp_path: Path) -> None:
    """Static/class methods and attr-free methods do not form cohesion pairs."""
    _write(
        tmp_path,
        "statics.py",
        '''
class Mixed:
    @staticmethod
    def s():
        return 1

    @classmethod
    def c(cls):
        return 2

    def uses_a(self):
        return self.a

    def no_attr(self):
        return 42
''',
    )
    result = analyze_cohesion(tmp_path)
    # Only uses_a touches an attribute -> <2 relevant -> skipped.
    assert all(c.classname != "Mixed" for c in result.low_cohesion)
    assert result.classes_skipped == 1


def test_empty_root_is_safe(tmp_path: Path) -> None:
    """No files -> empty, well-formed result, no exceptions."""
    result = analyze_cohesion(tmp_path)
    assert isinstance(result, CohesionMetrics)
    assert result.low_cohesion == []
    assert result.files_analyzed == 0
    assert result.classes_analyzed == 0
    assert result.classes_skipped == 0


def test_missing_root_is_safe(tmp_path: Path) -> None:
    """A non-existent root yields an empty result, not an error."""
    result = analyze_cohesion(tmp_path / "does_not_exist")
    assert result.low_cohesion == []
    assert result.files_analyzed == 0


def test_syntax_error_file_skipped(tmp_path: Path) -> None:
    """Unparseable files are skipped without aborting the scan."""
    _write(tmp_path, "broken.py", "class Oops(:\n    pass\n")
    _write(
        tmp_path,
        "ok.py",
        '''
class Fine:
    def a(self):
        return self.x

    def b(self):
        return self.x
''',
    )
    result = analyze_cohesion(tmp_path)
    assert result.files_analyzed == 1
    assert any(c.classname == "Fine" for c in result.low_cohesion)


def test_test_files_are_excluded(tmp_path: Path) -> None:
    """Classes in test files are not graded."""
    _write(
        tmp_path,
        "test_thing.py",
        '''
class TestCase:
    def a(self):
        return self.p

    def b(self):
        return self.q
''',
    )
    result = analyze_cohesion(tmp_path)
    assert result.files_analyzed == 0
    assert result.low_cohesion == []


def test_determinism(tmp_path: Path) -> None:
    """Same input -> identical output across repeated runs."""
    _write(
        tmp_path,
        "a.py",
        '''
class Split:
    def ra(self):
        return self.a

    def wa(self):
        self.a = 1

    def rb(self):
        return self.b

    def wb(self):
        self.b = 1
''',
    )
    _write(
        tmp_path,
        "b.py",
        '''
class Tight:
    def f(self):
        return self.z

    def g(self):
        self.z = 1
''',
    )
    r1 = analyze_cohesion(tmp_path)
    r2 = analyze_cohesion(tmp_path)
    assert r1 == r2
    # Ascending by cohesion -> the split class sorts before the tight one.
    names = [c.classname for c in r1.low_cohesion]
    assert names == ["Split", "Tight"]


def test_cohesion_in_unit_interval(tmp_path: Path) -> None:
    """Every reported cohesion stays within [0, 1]."""
    _write(
        tmp_path,
        "many.py",
        '''
class Frag:
    def m1(self):
        return self.a

    def m2(self):
        return self.b

    def m3(self):
        return self.c

    def m4(self):
        return self.a + self.b
''',
    )
    result = analyze_cohesion(tmp_path)
    for c in result.low_cohesion:
        assert 0.0 <= c.cohesion <= 1.0
        assert isinstance(c, ClassCohesion)
