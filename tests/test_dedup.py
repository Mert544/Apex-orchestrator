"""Tests for the deterministic code-duplication detector."""

from __future__ import annotations

from pathlib import Path

from app.engine.dedup import (
    DuplicateBlock,
    find_duplicates,
    render_duplicates_markdown,
)
from app.memory.graph_store import GraphStore


def test_graph_store_question_dedup():
    graph = GraphStore()
    q = "What is missing?"
    assert graph.has_similar_question(q) is False
    graph.register_question(q)
    assert graph.has_similar_question(q) is True


# A 5-statement block, identical wherever it is pasted.
_DUP_BLOCK = """\
    total = 0
    total += 1
    total += 2
    total += 3
    return total
"""


def _write(root: Path, rel: str, body_lines: list[str]) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body_lines) + "\n", encoding="utf-8")


def _module_with_dup(func_name: str) -> str:
    return f"def {func_name}():\n{_DUP_BLOCK}"


def test_identical_block_across_two_modules(tmp_path: Path) -> None:
    _write(tmp_path, "app/a.py", [_module_with_dup("alpha")])
    _write(tmp_path, "app/b.py", [_module_with_dup("beta")])

    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)

    assert len(blocks) == 1
    block = blocks[0]
    assert block.lines == 5
    assert len(block.occurrences) == 2
    assert "app/a.py:2" in block.occurrences
    assert "app/b.py:2" in block.occurrences


def test_block_appearing_once_not_reported(tmp_path: Path) -> None:
    _write(tmp_path, "app/a.py", [_module_with_dup("alpha")])
    # A different, unique function — no duplicate anywhere.
    _write(tmp_path, "app/b.py", [
        "def unique():",
        "    x = 1",
        "    y = 2",
        "    z = 3",
        "    w = 4",
        "    return x + y + z + w",
    ])

    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)

    assert blocks == []


def test_block_shorter_than_min_not_reported(tmp_path: Path) -> None:
    short = ["def f():", "    a = 1", "    b = 2", "    return a + b"]
    _write(tmp_path, "app/a.py", short)
    _write(tmp_path, "app/b.py", ["def g():", "    a = 1", "    b = 2",
                                   "    return a + b"])

    # The shared block is only 3 statements; min is 5.
    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)

    assert blocks == []


def test_fixture_and_test_files_excluded(tmp_path: Path) -> None:
    # Same duplicated block, but only inside test/fixture files.
    _write(tmp_path, "tests/test_x.py", [_module_with_dup("alpha")])
    _write(tmp_path, "fixtures/sample.py", [_module_with_dup("beta")])
    _write(tmp_path, "app/real.py", [_module_with_dup("gamma")])

    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)

    # Only one real occurrence survives exclusion -> nothing to report.
    assert blocks == []


def test_self_overlap_not_double_counted(tmp_path: Path) -> None:
    # One function repeats the same 5-statement run twice back-to-back at two
    # distinct linenos, so they ARE two distinct occurrences — but the SAME
    # location must never be appended twice.
    repeated = ["def f():"]
    for _ in range(2):
        repeated += ["    total = 0", "    total += 1", "    total += 2",
                     "    total += 3", "    total += 4"]
    _write(tmp_path, "app/a.py", repeated)

    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)

    assert len(blocks) == 1
    # No location appears twice in the list.
    assert len(blocks[0].occurrences) == len(set(blocks[0].occurrences))
    assert len(blocks[0].occurrences) == 2


def test_determinism(tmp_path: Path) -> None:
    _write(tmp_path, "app/a.py", [_module_with_dup("alpha")])
    _write(tmp_path, "app/b.py", [_module_with_dup("beta")])
    _write(tmp_path, "app/c.py", [_module_with_dup("gamma")])

    first = [b.to_dict() for b in find_duplicates(tmp_path)]
    second = [b.to_dict() for b in find_duplicates(tmp_path)]

    assert first == second
    # Occurrences are sorted deterministically.
    assert first[0]["occurrences"] == sorted(first[0]["occurrences"])


def test_sorted_by_lines_desc_then_fingerprint(tmp_path: Path) -> None:
    long_block = ["    a = 1", "    a += 1", "    a += 2", "    a += 3",
                  "    a += 4", "    return a"]
    _write(tmp_path, "app/a.py", ["def f():"] + long_block)
    _write(tmp_path, "app/b.py", ["def g():"] + long_block)

    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert blocks  # at least one reported
    line_counts = [b.lines for b in blocks]
    assert line_counts == sorted(line_counts, reverse=True)


def test_render_shows_count_and_locations(tmp_path: Path) -> None:
    _write(tmp_path, "app/a.py", [_module_with_dup("alpha")])
    _write(tmp_path, "app/b.py", [_module_with_dup("beta")])

    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    md = render_duplicates_markdown(blocks)

    assert "1 duplicated block(s)" in md
    assert "app/a.py:2" in md
    assert "app/b.py:2" in md
    assert "occurrence(s)" in md


def test_render_empty_is_clean() -> None:
    md = render_duplicates_markdown([])
    assert "No significant duplication" in md
    assert "duplicated block(s)" not in md


def test_to_dict_shape() -> None:
    block = DuplicateBlock(fingerprint="fp", lines=5,
                           occurrences=["m:1", "n:2"])
    assert block.to_dict() == {
        "fingerprint": "fp",
        "lines": 5,
        "occurrences": ["m:1", "n:2"],
    }
