"""Characterization tests for find_dead_code after its decomposition into pure
helpers (_parse_project / _gather_dead / _confidence / _annotate_runtime).

These pin the externally observable behaviour — finding contents, ordering,
limit slicing, exclusions, and the additive runtime annotation — so the refactor
stays byte-identical and any future drift is caught.
"""
from __future__ import annotations

from pathlib import Path

from app.engine.runtime_trace import RuntimeEvidence
from app.reporting.deadcode import (
    _confidence,
    find_dead_code,
    render_dead_code_markdown,
)


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def test_basic_dead_and_live(tmp_path: Path) -> None:
    _write(tmp_path, {
        "app/core.py": "def _used():\n    return 1\n\ndef _dead():\n    return 2\n",
        "app/main.py": "from app.core import _used\n\ndef main():\n    return _used()\n",
    })
    rows = find_dead_code(str(tmp_path))
    symbols = {(r["module"], r["symbol"]) for r in rows}
    assert ("app/core.py", "_dead") in symbols
    assert ("app/core.py", "_used") not in symbols
    assert all(r["symbol"] != "main" for r in rows)


def test_confidence_private_vs_public() -> None:
    assert _confidence("_x") == "high"
    assert _confidence("Public") == "review"


def test_high_confidence_sorts_first(tmp_path: Path) -> None:
    _write(tmp_path, {
        "app/a.py": "def public_dead():\n    return 1\n",
        "app/b.py": "def _priv_dead():\n    return 1\n",
    })
    rows = find_dead_code(str(tmp_path))
    assert rows[0]["confidence"] == "high"
    assert rows[0]["symbol"] == "_priv_dead"
    # deterministic ordering: (confidence-rank, module, line)
    assert [r["confidence"] for r in rows] == sorted(
        (r["confidence"] for r in rows), key=lambda c: 0 if c == "high" else 1
    )


def test_limit_slices_after_sort(tmp_path: Path) -> None:
    _write(tmp_path, {
        "app/m.py": "def _d1():\n    return 1\n\ndef _d2():\n    return 2\n\ndef _d3():\n    return 3\n",
    })
    assert len(find_dead_code(str(tmp_path), limit=2)) == 2
    assert find_dead_code(str(tmp_path), limit=0) == []


def test_exclusions_all_export_decorator_dunder_test(tmp_path: Path) -> None:
    _write(tmp_path, {
        "app/api.py": (
            "__all__ = ['Exported']\n\n"
            "class Exported:\n    pass\n\n"
            "import functools\n\n@functools.cache\ndef decorated():\n    return 1\n\n"
            "def __dunder__():\n    return 1\n\n"
            "def test_inline():\n    return 1\n"
        ),
        "tests/test_t.py": "def _never_reported():\n    return 1\n",
        "examples/demo.py": "def _example_dead():\n    return 1\n",
    })
    rows = find_dead_code(str(tmp_path))
    reported = {r["symbol"] for r in rows}
    assert reported == set()


def test_syntax_error_and_empty_tree(tmp_path: Path) -> None:
    assert find_dead_code(str(tmp_path)) == []
    _write(tmp_path, {
        "app/bad.py": "def broken(:\n    pass\n",
        "app/ok.py": "def _ok_dead():\n    return 1\n",
    })
    rows = find_dead_code(str(tmp_path))
    assert [r["symbol"] for r in rows] == ["_ok_dead"]


def test_evidence_adds_runtime_key(tmp_path: Path) -> None:
    _write(tmp_path, {"app/m.py": "def _d():\n    return 1\n"})
    rows_no = find_dead_code(str(tmp_path))
    assert all("runtime" not in r for r in rows_no)

    # Empty evidence -> file never loaded -> static-only, key still present.
    rows_ev = find_dead_code(
        str(tmp_path), evidence=RuntimeEvidence(executed=frozenset())
    )
    assert all("runtime" in r for r in rows_ev)
    assert {r["runtime"] for r in rows_ev} == {"static-only"}


def test_render_runtime_column_only_with_evidence(tmp_path: Path) -> None:
    _write(tmp_path, {"app/m.py": "def _d():\n    return 1\n"})
    static_md = render_dead_code_markdown(find_dead_code(str(tmp_path)))
    assert "Runtime" not in static_md
    ev_md = render_dead_code_markdown(
        find_dead_code(str(tmp_path), evidence=RuntimeEvidence(executed=frozenset()))
    )
    assert "| Runtime |" in ev_md


def test_determinism_repeated_runs(tmp_path: Path) -> None:
    _write(tmp_path, {
        "app/a.py": "def _x():\n    return 1\n",
        "app/b.py": "def _y():\n    return 1\n",
        "app/c.py": "def z_pub():\n    return 1\n",
    })
    first = find_dead_code(str(tmp_path))
    for _ in range(3):
        assert find_dead_code(str(tmp_path)) == first
