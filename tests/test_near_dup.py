"""Tests for the deterministic NEAR-duplicate detector (analysis only)."""

from __future__ import annotations

from pathlib import Path

from app.engine.near_dup import (
    NearDuplicateGroup,
    find_near_duplicates,
    render_near_duplicates_markdown,
)


def _write(root: Path, rel: str, body_lines: list[str]) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body_lines) + "\n", encoding="utf-8")


# A 5-statement function body parameterized by the value of the first assignment's RHS.
def _block(value: str) -> list[str]:
    return [
        f"    x = {value}",
        "    y = x + 1",
        "    z = y + 2",
        "    w = z + 3",
        "    return w",
    ]


def _func(name: str, body: list[str]) -> list[str]:
    return [f"def {name}():"] + body


def test_one_constant_differs_is_near_dup(tmp_path: Path) -> None:
    # Two blocks identical except ONE constant: x = 1 vs x = 2.
    _write(tmp_path, "app/a.py", _func("alpha", _block("1")))
    _write(tmp_path, "app/b.py", _func("beta", _block("2")))

    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)

    assert len(groups) == 1
    g = groups[0]
    assert g.lines == 5
    assert g.diff_count == 1
    assert sorted(g.occurrences) == ["app/a.py:2", "app/b.py:2"]
    # differences[0] holds the value each occurrence carries, parallel to occurrences.
    assert len(g.differences) == 1
    # Occurrences are sorted (a.py before b.py), so values are ["1", "2"].
    assert g.differences[0] == ["1", "2"]


def test_load_name_differs_is_near_dup(tmp_path: Path) -> None:
    # Identical structure and identical Store targets; only a LOADED name differs
    # (`g` vs `h` read on line 2). All other names/structure are byte-identical.
    body_g = ["    base = 10", "    a = base + g", "    b = a + 1",
              "    c = b + 1", "    return c"]
    body_h = ["    base = 10", "    a = base + h", "    b = a + 1",
              "    c = b + 1", "    return c"]
    _write(tmp_path, "app/a.py", _func("alpha", body_g))
    _write(tmp_path, "app/b.py", _func("beta", body_h))

    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)

    assert len(groups) == 1
    g = groups[0]
    assert g.diff_count == 1
    assert g.differences[0] == ["g", "h"]


def test_store_target_name_differs_not_grouped(tmp_path: Path) -> None:
    # Identical structure, but a Store TARGET name differs (binds `x` vs `t`).
    body_x = ["    x = 1", "    x = x + 1", "    x = x + 2",
              "    x = x + 3", "    return x"]
    body_t = ["    t = 1", "    t = t + 1", "    t = t + 2",
              "    t = t + 3", "    return t"]
    _write(tmp_path, "app/a.py", _func("alpha", body_x))
    _write(tmp_path, "app/b.py", _func("beta", body_t))

    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)

    # The bound name is structural, not a value leaf — these must NOT be grouped.
    assert groups == []


def test_different_operator_not_grouped(tmp_path: Path) -> None:
    body_plus = ["    a = 1", "    b = a + 2", "    c = b + 3",
                 "    d = c + 4", "    return d"]
    body_minus = ["    a = 1", "    b = a - 2", "    c = b + 3",
                  "    d = c + 4", "    return d"]
    _write(tmp_path, "app/a.py", _func("alpha", body_plus))
    _write(tmp_path, "app/b.py", _func("beta", body_minus))

    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)

    # `+` vs `-` is an operator difference — structural, never a near-dup.
    assert groups == []


def test_different_node_type_not_grouped(tmp_path: Path) -> None:
    # One block returns a value; the other has a different statement TYPE (a pass).
    body_a = ["    a = 1", "    b = 2", "    c = 3", "    d = 4", "    return d"]
    body_b = ["    a = 1", "    b = 2", "    c = 3", "    d = 4", "    pass"]
    _write(tmp_path, "app/a.py", _func("alpha", body_a))
    _write(tmp_path, "app/b.py", _func("beta", body_b))

    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)

    assert groups == []


def test_more_than_max_diffs_not_grouped(tmp_path: Path) -> None:
    # Four differing constants, with max_diffs=3 → excluded.
    body_a = ["    a = 1", "    b = 2", "    c = 3", "    d = 4", "    return d"]
    body_b = ["    a = 9", "    b = 8", "    c = 7", "    d = 6", "    return d"]
    _write(tmp_path, "app/a.py", _func("alpha", body_a))
    _write(tmp_path, "app/b.py", _func("beta", body_b))

    groups = find_near_duplicates(
        tmp_path, min_statements=5, min_occurrences=2, max_diffs=3)
    assert groups == []

    # The same blocks ARE grouped once max_diffs is raised to cover all 4.
    groups = find_near_duplicates(
        tmp_path, min_statements=5, min_occurrences=2, max_diffs=4)
    assert len(groups) == 1
    assert groups[0].diff_count == 4


def test_exact_duplicates_not_in_near_dup_output(tmp_path: Path) -> None:
    # Byte-identical blocks (0 diffs) belong to find_duplicates, not here.
    _write(tmp_path, "app/a.py", _func("alpha", _block("1")))
    _write(tmp_path, "app/b.py", _func("beta", _block("1")))

    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert groups == []


def test_min_occurrences_respected(tmp_path: Path) -> None:
    # Three near-duplicate blocks differing in one constant each.
    _write(tmp_path, "app/a.py", _func("alpha", _block("1")))
    _write(tmp_path, "app/b.py", _func("beta", _block("2")))
    _write(tmp_path, "app/c.py", _func("gamma", _block("3")))

    # Require >= 3 → the one group with 3 occurrences qualifies.
    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=3)
    assert len(groups) == 1
    assert len(groups[0].occurrences) == 3
    assert groups[0].differences[0] == ["1", "2", "3"]

    # Require >= 4 → nothing qualifies.
    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=4)
    assert groups == []


def test_determinism(tmp_path: Path) -> None:
    _write(tmp_path, "app/a.py", _func("alpha", _block("1")))
    _write(tmp_path, "app/b.py", _func("beta", _block("2")))
    _write(tmp_path, "app/c.py", _func("gamma", _block("3")))

    first = [g.to_dict() for g in find_near_duplicates(tmp_path)]
    second = [g.to_dict() for g in find_near_duplicates(tmp_path)]
    assert first == second
    # Occurrences are sorted within each group.
    for g in first:
        assert g["occurrences"] == sorted(g["occurrences"])


def test_fixture_and_test_files_excluded(tmp_path: Path) -> None:
    # Near-duplicate blocks live ONLY in test/fixture files plus one real module.
    _write(tmp_path, "tests/test_x.py", _func("alpha", _block("1")))
    _write(tmp_path, "fixtures/sample.py", _func("beta", _block("2")))
    _write(tmp_path, "app/real.py", _func("gamma", _block("3")))

    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    # Only the one real occurrence survives exclusion → nothing to report.
    assert groups == []


def test_sorted_by_lines_then_occurrences(tmp_path: Path) -> None:
    # Group A: 3 occurrences (one differing constant). Group B: 2 occurrences,
    # a different shape so it forms its own template.
    _write(tmp_path, "app/a.py", _func("a1", _block("1")))
    _write(tmp_path, "app/b.py", _func("a2", _block("2")))
    _write(tmp_path, "app/c.py", _func("a3", _block("3")))

    other = ["    m = 5", "    n = m * 2", "    o = n * 2",
             "    p = o * 2", "    return p"]
    other2 = ["    m = 6", "    n = m * 2", "    o = n * 2",
              "    p = o * 2", "    return p"]
    _write(tmp_path, "app/d.py", _func("b1", other))
    _write(tmp_path, "app/e.py", _func("b2", other2))

    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert len(groups) == 2
    # All groups have the same line count here, so the 3-occurrence group sorts first.
    assert len(groups[0].occurrences) >= len(groups[1].occurrences)
    assert len(groups[0].occurrences) == 3


def test_render_shows_groups_and_positions(tmp_path: Path) -> None:
    _write(tmp_path, "app/a.py", _func("alpha", _block("1")))
    _write(tmp_path, "app/b.py", _func("beta", _block("2")))

    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    md = render_near_duplicates_markdown(groups)

    assert "1 near-duplicate group(s)" in md
    assert "app/a.py:2" in md
    assert "app/b.py:2" in md
    assert "differing position(s)" in md
    assert "`1`" in md and "`2`" in md


def test_render_empty_is_clean() -> None:
    md = render_near_duplicates_markdown([])
    assert "No near-duplicate blocks detected" in md
    assert "group(s)" not in md


def test_to_dict_shape() -> None:
    g = NearDuplicateGroup(
        occurrences=["m:1", "n:2"],
        lines=5,
        diff_count=1,
        differences=[["1", "2"]],
    )
    assert g.to_dict() == {
        "occurrences": ["m:1", "n:2"],
        "lines": 5,
        "diff_count": 1,
        "differences": [["1", "2"]],
    }


def test_empty_project_is_empty(tmp_path: Path) -> None:
    # No modules at all → no groups, no error.
    assert find_near_duplicates(tmp_path) == []


def test_block_shorter_than_min_not_reported(tmp_path: Path) -> None:
    short = ["def f():", "    a = 1", "    b = 2", "    return a + b"]
    _write(tmp_path, "app/a.py", short)
    _write(tmp_path, "app/b.py",
           ["def g():", "    a = 9", "    b = 8", "    return a + b"])

    # Shared block is only 3 statements; min is 5.
    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert groups == []
