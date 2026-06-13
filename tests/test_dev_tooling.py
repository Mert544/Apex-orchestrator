"""Tests for the development tooling under scripts/ — the verify harness and the
objective scaffold. These keep our own process honest: the green-gate chunking
covers every test file, and the scaffold always emits a discoverable objective.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(script_name: str):
    path = ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(script_name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- scripts/verify.py: the chunked green gate -------------------------------

def test_chunk_files_covers_everything_exactly_once():
    verify = _load("verify.py")
    files = [Path(f"tests/test_{i}.py") for i in range(10)]
    chunks = verify.chunk_files(files, 4)
    flat = [f for c in chunks for f in c]
    assert flat == files  # every file once, original order preserved


def test_chunk_files_is_balanced():
    verify = _load("verify.py")
    files = [Path(f"t{i}.py") for i in range(10)]
    sizes = [len(c) for c in verify.chunk_files(files, 4)]
    assert max(sizes) - min(sizes) <= 1  # 3,3,2,2


def test_chunk_files_handles_more_chunks_than_files():
    verify = _load("verify.py")
    files = [Path("a.py"), Path("b.py")]
    chunks = verify.chunk_files(files, 8)
    assert [f for c in chunks for f in c] == files
    assert all(chunks)  # no empty chunks emitted


def test_chunk_files_is_deterministic():
    verify = _load("verify.py")
    files = [Path(f"t{i}.py") for i in range(17)]
    assert verify.chunk_files(files, 4) == verify.chunk_files(files, 4)


def test_discover_tests_finds_the_real_suite():
    verify = _load("verify.py")
    found = verify.discover_tests()
    assert len(found) > 50  # the suite is large
    assert found == sorted(found)  # stable order
    assert all(p.name.startswith("test_") for p in found)


# --- scripts/new_objective.py: the scaffold ----------------------------------

def test_rendered_transform_parses_and_names_the_plan():
    scaffold = _load("new_objective.py")
    src = scaffold.render_transform("collapse-foo", "collapse foo into bar")
    ast.parse(src)  # valid Python
    assert "def plan_collapse_foo(" in src
    assert 'new="collapse-foo"' in src
    assert "_is_fixture_path" in src


def test_rendered_spec_parses_and_registers():
    scaffold = _load("new_objective.py")
    src = scaffold.render_spec("collapse-foo")
    ast.parse(src)
    assert 'register(ObjectiveSpec(name="collapse-foo"' in src
    assert "plan_collapse_foo" in src


def test_rendered_test_parses_and_asserts_registration():
    scaffold = _load("new_objective.py")
    src = scaffold.render_test("collapse-foo")
    ast.parse(src)
    assert "available_objectives" in src
    assert '"collapse-foo" in available_objectives()' in src


def test_name_helpers():
    scaffold = _load("new_objective.py")
    assert scaffold.to_snake("collapse-foo-bar") == "collapse_foo_bar"
    assert scaffold.to_title("collapse-foo") == "collapse foo"


def test_main_rejects_bad_name():
    scaffold = _load("new_objective.py")
    assert scaffold.main(["Collapse_Foo"]) == 2  # not kebab-case (uppercase/underscore)
    assert scaffold.main(["bad--name"]) == 2     # empty segment
    assert scaffold.main(["1foo"]) == 2          # must start with a letter


def test_scaffold_round_trip_writes_three_files(tmp_path, monkeypatch):
    scaffold = _load("new_objective.py")
    # Redirect the scaffold's ROOT into a throwaway tree so we never touch the
    # real package, then prove it writes a parseable, registration-bearing set.
    (tmp_path / "app" / "execution" / "objectives").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    monkeypatch.setattr(scaffold, "ROOT", tmp_path)

    assert scaffold.main(["collapse-foo", "--summary", "collapse foo"]) == 0
    transform = tmp_path / "app" / "execution" / "collapse_foo.py"
    spec = tmp_path / "app" / "execution" / "objectives" / "collapse_foo.py"
    test = tmp_path / "tests" / "test_collapse_foo.py"
    for p in (transform, spec, test):
        assert p.exists()
        ast.parse(p.read_text(encoding="utf-8"))  # all valid Python

    # Re-running refuses to overwrite.
    assert scaffold.main(["collapse-foo"]) == 1
