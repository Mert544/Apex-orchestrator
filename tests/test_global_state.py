"""Tests for the mutable-global-state analyzer."""

from __future__ import annotations

import textwrap
from pathlib import Path

from app.tools.global_state import GlobalState, analyze_global_state


def _write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_lowercase_mutable_dict_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", "CACHE = {}\n")
    result = analyze_global_state(tmp_path)
    names = {m["name"] for m in result.mutable_globals}
    # CACHE is UPPER_SNAKE -> constant -> NOT flagged.
    assert "CACHE" not in names


def test_lowercase_name_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", "cache = {}\n")
    result = analyze_global_state(tmp_path)
    flagged = [m for m in result.mutable_globals if m["name"] == "cache"]
    assert len(flagged) == 1
    entry = flagged[0]
    assert entry["kind"] == "dict"
    assert entry["module"] == "mod"
    assert entry["line"] == 1


def test_upper_snake_constant_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", "REGISTRY = []\n")
    result = analyze_global_state(tmp_path)
    assert result.mutable_globals == []
    assert result.mutable_globals_count == 0


def test_underscore_constant_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", "_CACHE = {}\n__all__ = ['a']\n")
    result = analyze_global_state(tmp_path)
    assert result.mutable_globals == []


def test_immutable_constants_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mod.py",
        """
        name = "apex"
        count = 7
        pi = 3.14
        flag = True
        nothing = None
        pair = (1, 2)
        frozen = frozenset({1, 2})
        empty = tuple()
        """,
    )
    result = analyze_global_state(tmp_path)
    assert result.mutable_globals == []
    assert result.mutable_globals_count == 0


def test_mutable_constructors_and_literals(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mod.py",
        """
        items = list()
        mapping = dict()
        seen = set()
        literal_list = [1, 2]
        literal_set = {1, 2}
        """,
    )
    result = analyze_global_state(tmp_path)
    by_name = {m["name"]: m["kind"] for m in result.mutable_globals}
    assert by_name == {
        "items": "list",
        "mapping": "dict",
        "seen": "set",
        "literal_list": "list",
        "literal_set": "set",
    }


def test_class_body_assignments_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mod.py",
        """
        class Config:
            options = {}
            tags = []
        """,
    )
    result = analyze_global_state(tmp_path)
    assert result.mutable_globals == []


def test_global_mutation_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mod.py",
        """
        items = []

        def add(x):
            global items
            items.append(x)
        """,
    )
    result = analyze_global_state(tmp_path)
    muts = result.global_mutations
    assert len(muts) == 1
    m = muts[0]
    assert m["function"] == "add"
    assert m["name"] == "items"
    assert m["module"] == "mod"
    assert m["line"] >= 1


def test_tests_and_fixtures_excluded(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_thing.py", "cache = {}\n")
    _write(tmp_path, "conftest.py", "fixture_state = {}\n")
    result = analyze_global_state(tmp_path)
    assert result.mutable_globals == []
    assert result.global_mutations == []


def test_empty_tree_is_safe(tmp_path: Path) -> None:
    result = analyze_global_state(tmp_path)
    assert isinstance(result, GlobalState)
    assert result.mutable_globals == []
    assert result.global_mutations == []
    assert result.mutable_globals_count == 0
    assert result.global_mutations_count == 0
    assert result.files_scanned == 0


def test_syntax_error_file_is_skipped(tmp_path: Path) -> None:
    _write(tmp_path, "broken.py", "def (:\n")
    _write(tmp_path, "good.py", "data = {}\n")
    result = analyze_global_state(tmp_path)
    assert {m["name"] for m in result.mutable_globals} == {"data"}


def test_cap_at_15(tmp_path: Path) -> None:
    lines = "\n".join(f"v{i} = []" for i in range(40))
    _write(tmp_path, "many.py", lines + "\n")
    result = analyze_global_state(tmp_path)
    assert len(result.mutable_globals) == 15
    assert result.mutable_globals_count == 40


def test_determinism(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "alpha = []\n")
    _write(
        tmp_path,
        "b.py",
        """
        beta = {}

        def touch():
            global beta
            beta['k'] = 1
        """,
    )
    first = analyze_global_state(tmp_path)
    second = analyze_global_state(tmp_path)
    assert first == second
    assert first.mutable_globals == second.mutable_globals
    assert first.global_mutations == second.global_mutations
