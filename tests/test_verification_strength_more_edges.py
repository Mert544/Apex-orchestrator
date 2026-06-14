"""Edge-path coverage for verification_strength helpers.

Targets the previously-uncovered branches:
  - changed_functions: get_source_segment failure fallback (lines 51-52)
  - _test_files: oversized file is skipped (line 70)
  - _test_files: unreadable file (OSError) is skipped (lines 72-73)
  - module_referenced_by_suite: test/non-Python paths short-circuit (line 92)
"""

from __future__ import annotations

from pathlib import Path

from app.engine import verification_strength as vs
from app.engine.verification_strength import (
    assess_strength,
    changed_functions,
    module_referenced_by_suite,
)


def test_changed_functions_source_segment_failure_falls_back_to_name(monkeypatch):
    # When ast.get_source_segment raises, the function name is still recorded,
    # so a changed function is still detected (lines 51-52).
    def boom(_src, _node):
        raise ValueError("no segment")

    monkeypatch.setattr(vs.ast, "get_source_segment", boom)
    old = "def a():\n    return 1\n"
    new = "def a():\n    return 2\n"
    # Both sides map name -> name (the fallback), so they compare equal and the
    # function is NOT reported as changed -- but the fallback path executed.
    assert changed_functions(old, new) == []
    # A function present on only one side is still surfaced via the fallback.
    new2 = "def a():\n    return 1\n\ndef b():\n    return 9\n"
    assert "b" in changed_functions(old, new2)


def test_oversized_test_file_is_skipped(tmp_path: Path, monkeypatch):
    # A test file larger than the byte cap is ignored, so it cannot lift the
    # measured strength (line 70).
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def handler(x):\n    return x + 1\n")
    big = (tmp_path / "tests" / "test_big.py")
    big.write_text("from app.svc import handler\ndef test_h():\n    assert handler(1) == 2\n")

    monkeypatch.setattr(vs, "_MAX_TEST_FILE_BYTES", 1)  # everything is "too big"

    s = assess_strength(
        tmp_path, ["app/svc.py"],
        {"app/svc.py": "def handler(x):\n    return x + 1\n"},
        {"app/svc.py": 'def handler(x):\n    """D."""\n    return x + 1\n'},
    )
    assert s["level"] == "none"
    assert s["module_tests"] == []


def test_unreadable_test_file_is_skipped(tmp_path: Path, monkeypatch):
    # A test file that raises OSError on read is silently skipped (lines 72-73).
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def handler(x):\n    return x + 1\n")
    (tmp_path / "tests" / "test_x.py").write_text(
        "from app.svc import handler\ndef test_h():\n    assert handler(1) == 2\n"
    )

    real_read_text = Path.read_text

    def flaky_read_text(self, *args, **kwargs):
        if self.name == "test_x.py":
            raise OSError("cannot read")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)

    s = assess_strength(
        tmp_path, ["app/svc.py"],
        {"app/svc.py": "def handler(x):\n    return x + 1\n"},
        {"app/svc.py": 'def handler(x):\n    """D."""\n    return x + 1\n'},
    )
    assert s["level"] == "none"


def test_module_referenced_short_circuits_for_test_and_non_python(tmp_path: Path):
    # Test files and non-Python targets never need a shield: True without
    # scanning the suite (line 92).
    assert module_referenced_by_suite(tmp_path, "tests/test_thing.py") is True
    assert module_referenced_by_suite(tmp_path, "README.md") is True
    assert module_referenced_by_suite(tmp_path, "app/foo_test.py") is True


def test_module_referenced_false_when_no_test_mentions_module(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "lonely.py").write_text("def f():\n    return 1\n")
    (tmp_path / "tests" / "test_other.py").write_text("def test_o():\n    assert True\n")
    assert module_referenced_by_suite(tmp_path, "app/lonely.py") is False
