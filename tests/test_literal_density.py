"""Magic-literal density: flags the *repeated, bare, meaningful* constant only.

Covers the conservative allow-list (0/1/-1/2, "", dunders, docstrings,
annotations, simple defaults, fixtures), the repeat threshold, empty-safety,
and determinism — the invariants that keep the signal taste-free.
"""

from __future__ import annotations

from pathlib import Path

from app.tools.literal_density import (
    ALLOWED_NUMBERS,
    ALLOWED_STRINGS,
    REPEAT_THRESHOLD,
    LiteralDensity,
    analyze_literal_density,
)


def _write(root: Path, rel: str, source: str) -> None:
    """Materialise ``source`` at ``root/rel``, creating parent dirs."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


# ── repeated magic numbers ────────────────────────────────────────────────────

def test_repeated_magic_number_is_flagged(tmp_path: Path):
    # 3600 written three times across the module -> a "extract a constant" hit.
    _write(tmp_path, "app/timers.py",
           "def a():\n    return 3600\n"
           "def b():\n    return 3600\n"
           "def c():\n    return 3600 + 5\n")
    result = analyze_literal_density(tmp_path)

    assert isinstance(result, LiteralDensity)
    assert result.files_analyzed == 1
    literals = {entry["literal"]: entry for entry in result.repeated}
    assert "3600" in literals
    assert literals["3600"]["count"] == REPEAT_THRESHOLD
    assert literals["3600"]["modules"] == ["app/timers.py"]


def test_repeat_threshold_is_inclusive_lower_bound(tmp_path: Path):
    # Twice is below threshold -> not surfaced; thrice -> surfaced.
    _write(tmp_path, "app/two.py", "x = 4242\ny = 4242\n")
    twice = analyze_literal_density(tmp_path)
    assert all(e["literal"] != "4242" for e in twice.repeated)

    _write(tmp_path, "app/two.py", "x = 4242\ny = 4242\nz = 4242\n")
    thrice = analyze_literal_density(tmp_path)
    flagged = {e["literal"]: e["count"] for e in thrice.repeated}
    assert flagged.get("4242") == REPEAT_THRESHOLD


def test_repeated_count_spans_multiple_modules(tmp_path: Path):
    _write(tmp_path, "app/a.py", "PORT = 8080\n")
    _write(tmp_path, "app/b.py", "host = 8080\n")
    _write(tmp_path, "app/c.py", "bind = 8080\n")
    result = analyze_literal_density(tmp_path)

    entry = next(e for e in result.repeated if e["literal"] == "8080")
    assert entry["count"] == 3
    assert entry["modules"] == ["app/a.py", "app/b.py", "app/c.py"]


# ── the universal numeric allow-list ─────────────────────────────────────────

def test_zero_one_minus_one_two_are_never_flagged(tmp_path: Path):
    # All of {0, 1, -1, 2} repeated heavily -> still nothing repeated/magic.
    _write(tmp_path, "app/allowed.py",
           "a = 0\nb = 0\nc = 0\n"
           "d = 1\ne = 1\nf = 1\n"
           "g = -1\nh = -1\ni = -1\n"
           "j = 2\nk = 2\nl = 2\n")
    result = analyze_literal_density(tmp_path)

    assert result.total_magic == 0
    assert result.repeated == []
    assert {0, 1, 2} <= set(ALLOWED_NUMBERS)


def test_minus_one_allowed_outside_default_position(tmp_path: Path):
    # ``-1`` parses as UnaryOp(USub, 1); allowed wherever it appears.
    _write(tmp_path, "app/m.py",
           "x = items[-1]\ny = items[-1]\nz = items[-1]\n")
    result = analyze_literal_density(tmp_path)
    assert result.total_magic == 0


def test_booleans_are_not_magic(tmp_path: Path):
    _write(tmp_path, "app/flags.py", "a = True\nb = True\nc = False\n")
    result = analyze_literal_density(tmp_path)
    assert result.total_magic == 0


# ── the string allow-list, docstrings, annotations, defaults ─────────────────

def test_empty_and_dunder_strings_allowed(tmp_path: Path):
    _write(tmp_path, "app/s.py",
           "a = ''\nb = ''\nc = ''\n"
           "name = '__main__'\nm2 = '__main__'\nm3 = '__main__'\n")
    result = analyze_literal_density(tmp_path)
    assert result.total_magic == 0
    assert "" in ALLOWED_STRINGS


def test_docstrings_are_not_counted(tmp_path: Path):
    # The identical docstring three times must never become a repeated literal.
    _write(tmp_path, "app/doc.py",
           '"""module level prose worth more than forty chars here ok."""\n'
           "def f():\n"
           '    """module level prose worth more than forty chars here ok."""\n'
           "    return 0\n"
           "class C:\n"
           '    """module level prose worth more than forty chars here ok."""\n')
    result = analyze_literal_density(tmp_path)
    assert result.total_magic == 0
    assert result.repeated == []


def test_type_annotations_are_not_counted(tmp_path: Path):
    _write(tmp_path, "app/ann.py",
           "from typing import Literal\n"
           "x: 'Forward' = None\n"
           "y: Literal['mode-aaa'] = 'mode-aaa'\n"
           "def f(a: 'Forward') -> 'Forward':\n"
           "    return a\n")
    result = analyze_literal_density(tmp_path)
    # Only the assigned value 'mode-aaa' (not the annotation) is a candidate;
    # used twice (< threshold) so it is not in repeated, and annotations add 0.
    assert all(e["literal"] != "'Forward'" for e in result.repeated)


def test_simple_default_arguments_are_not_counted(tmp_path: Path):
    _write(tmp_path, "app/defs.py",
           "def a(timeout=3600):\n    return timeout\n"
           "def b(timeout=3600):\n    return timeout\n"
           "def c(timeout=3600):\n    return timeout\n")
    result = analyze_literal_density(tmp_path)
    # 3600 appears only in default position -> never flagged, never repeated.
    assert result.total_magic == 0
    assert result.repeated == []


def test_dunder_all_export_names_are_not_counted(tmp_path: Path):
    _write(tmp_path, "app/pkg.py",
           "__all__ = ['alpha-export', 'alpha-export', 'alpha-export']\n")
    result = analyze_literal_density(tmp_path)
    assert result.total_magic == 0


# ── fixtures / tests excluded ────────────────────────────────────────────────

def test_fixture_and_test_files_are_excluded(tmp_path: Path):
    magic = "x = 9999\ny = 9999\nz = 9999\n"
    _write(tmp_path, "tests/test_thing.py", magic)
    _write(tmp_path, "app/sub/test_inner.py", magic)
    _write(tmp_path, "fixtures/data.py", magic)
    _write(tmp_path, "app/conftest.py", magic)
    result = analyze_literal_density(tmp_path)

    assert result.files_analyzed == 0
    assert result.total_magic == 0
    assert result.repeated == []


def test_real_module_alongside_fixtures_still_analyzed(tmp_path: Path):
    _write(tmp_path, "tests/test_thing.py", "x = 7777\ny = 7777\nz = 7777\n")
    _write(tmp_path, "app/real.py", "a = 5555\nb = 5555\nc = 5555\n")
    result = analyze_literal_density(tmp_path)

    assert result.files_analyzed == 1
    flagged = {e["literal"] for e in result.repeated}
    assert "5555" in flagged
    assert "7777" not in flagged


# ── empty-safety ─────────────────────────────────────────────────────────────

def test_missing_root_is_safe(tmp_path: Path):
    result = analyze_literal_density(tmp_path / "does-not-exist")
    assert result == LiteralDensity()
    assert result.total_magic == 0
    assert result.density == 0.0
    assert result.repeated == []


def test_empty_tree_is_safe(tmp_path: Path):
    result = analyze_literal_density(tmp_path)
    assert result.files_analyzed == 0
    assert result.total_magic == 0
    assert result.density == 0.0


def test_unparseable_source_is_not_magic(tmp_path: Path):
    _write(tmp_path, "app/broken.py", "def f(:\n    return 3600 3600 3600\n")
    result = analyze_literal_density(tmp_path)
    assert result.total_magic == 0
    assert result.repeated == []
    # The file is still counted as analyzed (its lines contribute to density).
    assert result.files_analyzed == 1


def test_density_property_is_bounded_and_rounded(tmp_path: Path):
    _write(tmp_path, "app/d.py", "x = 9001\ny = 9001\nz = 9001\n")
    result = analyze_literal_density(tmp_path)
    assert 0.0 <= result.density <= 1.0
    # Stable to four places.
    assert result.density == round(result.density, 4)


# ── determinism ──────────────────────────────────────────────────────────────

def test_determinism_same_input_same_output(tmp_path: Path):
    for i in range(5):
        _write(tmp_path, f"app/mod_{i}.py",
               "p = 3600\nq = 3600\nr = 3600\ns = 1234\nt = 1234\nu = 1234\n")
    first = analyze_literal_density(tmp_path)
    second = analyze_literal_density(tmp_path)

    assert first == second
    assert [e["literal"] for e in first.repeated] == \
        [e["literal"] for e in second.repeated]


def test_repeated_ordering_is_count_then_literal(tmp_path: Path):
    # 'bbb' appears 5x, 'aaa' 3x, 'ccc' 4x -> ordered by -count then repr.
    _write(tmp_path, "app/o.py",
           "a1 = 'aaa-magic'\na2 = 'aaa-magic'\na3 = 'aaa-magic'\n"
           "b1 = 'bbb-magic'\nb2 = 'bbb-magic'\nb3 = 'bbb-magic'\n"
           "b4 = 'bbb-magic'\nb5 = 'bbb-magic'\n"
           "c1 = 'ccc-magic'\nc2 = 'ccc-magic'\nc3 = 'ccc-magic'\nc4 = 'ccc-magic'\n")
    result = analyze_literal_density(tmp_path)
    order = [e["literal"] for e in result.repeated]
    assert order == ["'bbb-magic'", "'ccc-magic'", "'aaa-magic'"]


def test_repeated_list_is_capped(tmp_path: Path):
    # Twenty distinct literals each repeated thrice -> capped at ~15.
    lines = []
    for n in range(20):
        val = 100000 + n
        lines += [f"v{n}_{k} = {val}" for k in range(3)]
    _write(tmp_path, "app/many.py", "\n".join(lines) + "\n")
    result = analyze_literal_density(tmp_path)
    assert len(result.repeated) <= 15
