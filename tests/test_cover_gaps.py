"""Tests for the cover-gaps transform (app/execution/cover_gaps.py).

cover-gaps is the detection->action move: an UNTESTED module becomes the ACTION
of writing a characterization test for it. The plan's only write is a NEW
``tests/test_*.py`` file (in ``new_contents``, never ``originals``).
"""

from __future__ import annotations

import ast
import textwrap

import app.execution.cover_gaps as cover_gaps
import app.execution.test_shield as test_shield
from app.execution.cover_gaps import _is_fixture_path, plan_cover_gaps
from app.execution.test_shield import ShieldTest


def _write(root, rel, body):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def _make_project(root):
    """A minimal importable project: ``app/`` package + ``pyproject.toml``."""
    _write(root, "pyproject.toml", "[project]\nname = 'demo'\nversion = '0.0.0'\n")
    _write(root, "app/__init__.py", "")
    return root


# ── happy path: an untested module becomes a written test ───────────────────

def test_untested_module_writes_a_new_test(tmp_path):
    _make_project(tmp_path)
    rel = "app/calc.py"
    _write(tmp_path, rel, "def add(a, b):\n    return a + b\n")

    plan = plan_cover_gaps(tmp_path, rel)

    assert plan.old == rel
    assert plan.new == "cover-gaps"
    assert plan.ok
    assert not plan.blockers
    # The only write is the new test file, project-relative under tests/.
    assert list(plan.new_contents) == ["tests/test_calc.py"]
    assert plan.edits_by_file == {"tests/test_calc.py": 1}


def test_written_content_lands_in_new_contents_not_originals(tmp_path):
    _make_project(tmp_path)
    rel = "app/calc.py"
    _write(tmp_path, rel, "def add(a, b):\n    return a + b\n")

    plan = plan_cover_gaps(tmp_path, rel)

    test_path = "tests/test_calc.py"
    assert test_path in plan.new_contents
    # A NEW file: nothing recorded in originals (it does not exist yet).
    assert plan.originals == {}
    assert test_path not in plan.originals


def test_written_content_parses_and_imports_the_module(tmp_path):
    _make_project(tmp_path)
    rel = "app/calc.py"
    _write(tmp_path, rel, "def add(a, b):\n    return a + b\n")

    plan = plan_cover_gaps(tmp_path, rel)
    content = plan.new_contents["tests/test_calc.py"]

    ast.parse(content)  # always parses
    assert "import app.calc" in content
    assert "def test_calc_imports" in content


# ── no-op: an existing test is never clobbered ──────────────────────────────

def test_existing_test_path_is_a_noop(tmp_path):
    _make_project(tmp_path)
    rel = "app/calc.py"
    _write(tmp_path, rel, "def add(a, b):\n    return a + b\n")
    # A test already exists for this module on disk.
    _write(tmp_path, "tests/test_calc.py", "def test_already_here():\n    assert True\n")

    plan = plan_cover_gaps(tmp_path, rel)

    assert not plan.ok
    assert not plan.blockers
    assert plan.new_contents == {}


def test_existing_test_path_noop_via_monkeypatch(tmp_path, monkeypatch):
    """Force the 'already exists' branch deterministically: the generator yields
    a shield whose test_path is on disk, so the plan refuses to clobber it."""
    _make_project(tmp_path)
    rel = "app/calc.py"
    _write(tmp_path, rel, "def add(a, b):\n    return a + b\n")
    _write(tmp_path, "tests/test_calc.py", "x = 1\n")

    def _fake(project_root, module_rel):
        return ShieldTest(
            module="app.calc",
            test_path="tests/test_calc.py",
            content="import app.calc\n",
            functions=[],
        )

    monkeypatch.setattr(test_shield, "generate_characterization_test", _fake)
    monkeypatch.setattr(cover_gaps, "generate_characterization_test", _fake)

    plan = plan_cover_gaps(tmp_path, rel)
    assert plan.new_contents == {}
    assert not plan.blockers


# ── no-op: nothing safely characterizable -> generator returns None ─────────

def test_unshieldable_module_is_a_noop(tmp_path):
    _make_project(tmp_path)
    rel = "app/side.py"
    # Only a private/side-effecting callable and a call at import: no public,
    # blindly-callable top-level function -> generator still returns a smoke
    # import test. To force a true None, monkeypatch below; here we assert the
    # honest fallback is at least a valid plan or empty.
    _write(tmp_path, rel, "def _helper():\n    return 1\n")

    plan = plan_cover_gaps(tmp_path, rel)
    # A module with only private callables still gets an import-smoke test;
    # the plan is a valid new-file write. It must never raise or block.
    assert not plan.blockers
    for content in plan.new_contents.values():
        ast.parse(content)


def test_generate_returns_none_is_empty_noop(tmp_path, monkeypatch):
    """When the generator declines (returns None), the plan is an empty no-op."""
    _make_project(tmp_path)
    rel = "app/calc.py"
    _write(tmp_path, rel, "def add(a, b):\n    return a + b\n")

    def _none(project_root, module_rel):
        return None

    monkeypatch.setattr(test_shield, "generate_characterization_test", _none)
    monkeypatch.setattr(cover_gaps, "generate_characterization_test", _none)

    plan = plan_cover_gaps(tmp_path, rel)
    assert not plan.ok
    assert not plan.blockers
    assert plan.new_contents == {}
    assert plan.originals == {}


# ── unparseable generated content -> blocker ────────────────────────────────

def test_unparseable_content_blocks(tmp_path, monkeypatch):
    _make_project(tmp_path)
    rel = "app/calc.py"
    _write(tmp_path, rel, "def add(a, b):\n    return a + b\n")

    def _broken(project_root, module_rel):
        return ShieldTest(
            module="app.calc",
            test_path="tests/test_calc.py",
            content="def (:\n",  # does not parse
            functions=[],
        )

    monkeypatch.setattr(test_shield, "generate_characterization_test", _broken)
    monkeypatch.setattr(cover_gaps, "generate_characterization_test", _broken)

    plan = plan_cover_gaps(tmp_path, rel)
    assert not plan.ok
    assert plan.blockers
    assert plan.new_contents == {}


# ── fixture/example subjects are excluded ───────────────────────────────────

def test_fixture_subject_is_a_noop(tmp_path):
    _make_project(tmp_path)
    rel = "tests/helpers.py"
    _write(tmp_path, rel, "def add(a, b):\n    return a + b\n")

    plan = plan_cover_gaps(tmp_path, rel)
    assert not plan.ok
    assert not plan.blockers
    assert plan.new_contents == {}


def test_example_subject_is_a_noop(tmp_path):
    _make_project(tmp_path)
    rel = "examples/demo.py"
    _write(tmp_path, rel, "def add(a, b):\n    return a + b\n")

    plan = plan_cover_gaps(tmp_path, rel)
    assert not plan.ok
    assert not plan.blockers
    assert plan.new_contents == {}


def test_is_fixture_path_recognizes_subjects():
    assert _is_fixture_path("tests/test_x.py")
    assert _is_fixture_path("examples/demo.py")
    assert _is_fixture_path("pkg/fixtures/data.py")
    assert _is_fixture_path("app/test_helper.py")  # name starts with test_
    assert not _is_fixture_path("app/calc.py")


# ── determinism ─────────────────────────────────────────────────────────────

def test_deterministic_same_input_same_output(tmp_path):
    _make_project(tmp_path)
    rel = "app/calc.py"
    _write(tmp_path, rel, "def add(a, b):\n    return a + b\n")

    a = plan_cover_gaps(tmp_path, rel)
    b = plan_cover_gaps(tmp_path, rel)
    assert a.new_contents == b.new_contents
    assert a.edits_by_file == b.edits_by_file
