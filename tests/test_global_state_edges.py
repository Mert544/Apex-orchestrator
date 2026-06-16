"""Edge / error-path tests for the mutable-global-state analyzer.

Covers the all-underscore constant guard, non-Name assignment targets
(tuple-unpacking / subscript), the annotated-assignment branch, the module-name
fallback when a path is outside root, and the ``max_files`` cap. Deterministic
and hermetic.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from app.tools.global_state import (
    _assigned_names,
    _is_constant_name,
    _module_name,
    analyze_global_state,
)


def _write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_all_underscore_name_is_constant():
    # core after strip('_') is empty -> treated as a constant, never flagged.
    assert _is_constant_name("___") is True
    assert _is_constant_name("_") is True


def test_assigned_names_skips_non_name_targets():
    # Tuple-unpacking and subscript targets are not simple module globals.
    tup = ast.parse("a, b = [], []").body[0].targets[0]
    assert _assigned_names(tup) == []
    sub = ast.parse("d['k'] = []").body[0].targets[0]
    assert _assigned_names(sub) == []


def test_tuple_unpacking_assignment_not_flagged(tmp_path: Path):
    _write(tmp_path, "mod.py", "first, second = [], {}\n")
    result = analyze_global_state(tmp_path)
    assert result.mutable_globals == []


def test_annotated_assignment_flagged(tmp_path: Path):
    # AnnAssign with a value goes through the annotated branch.
    _write(tmp_path, "mod.py", "registry: dict = {}\n")
    result = analyze_global_state(tmp_path)
    flagged = [m for m in result.mutable_globals if m["name"] == "registry"]
    assert len(flagged) == 1
    assert flagged[0]["kind"] == "dict"


def test_annotation_without_value_ignored(tmp_path: Path):
    # A bare annotation (no value) assigns nothing -> not flagged.
    _write(tmp_path, "mod.py", "pending: list\n")
    result = analyze_global_state(tmp_path)
    assert result.mutable_globals == []


def test_module_name_outside_root_falls_back(tmp_path: Path):
    # A path not under root cannot be made relative -> the dotted name is built
    # from the absolute path's own parts (fallback branch).
    other = tmp_path / "elsewhere" / "thing.py"
    name = _module_name(other, tmp_path / "root")
    assert name.endswith("thing")
    assert isinstance(name, str)


def test_max_files_cap_stops_scanning(tmp_path: Path):
    _write(tmp_path, "a.py", "alpha = []\n")
    _write(tmp_path, "b.py", "beta = []\n")
    result = analyze_global_state(tmp_path, max_files=1)
    assert result.files_scanned == 1
    assert {m["name"] for m in result.mutable_globals} == {"alpha"}
