from __future__ import annotations

from pathlib import Path

from app.validation.real_world_validator import RealWorldValidator


def _write_eval_project(tmp_path: Path) -> Path:
    """A minimal offline project whose only risk is eval()."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "real.py").write_text(
        'def run(code):\n    """Doc."""\n    return eval(code)\n',
        encoding="utf-8",
    )
    return tmp_path


def test_assert_expected_issues_reports_missing_and_found(tmp_path: Path):
    # Covers both the found branch and the missing.append branch (line 53):
    # eval() is present, pickle.loads is not.
    validator = RealWorldValidator(_write_eval_project(tmp_path))
    result = validator.assert_expected_issues(["eval()", "pickle.loads"])
    assert result["all_found"] is False
    assert result["found"] == ["eval()"]
    assert result["missing"] == ["pickle.loads"]


def test_assert_expected_issues_all_missing(tmp_path: Path):
    # An expected issue that never appears exercises the missing path alone.
    validator = RealWorldValidator(_write_eval_project(tmp_path))
    result = validator.assert_expected_issues(["definitely_absent_xyz"])
    assert result["all_found"] is False
    assert result["found"] == []
    assert result["missing"] == ["definitely_absent_xyz"]


def test_assert_expected_issues_empty_expected_is_all_found(tmp_path: Path):
    # No expectations means nothing is missing -> all_found is True.
    validator = RealWorldValidator(_write_eval_project(tmp_path))
    result = validator.assert_expected_issues([])
    assert result["all_found"] is True
    assert result["found"] == []
    assert result["missing"] == []


def test_run_accepts_string_root(tmp_path: Path):
    # __init__ coerces str -> Path; run() must work identically.
    _write_eval_project(tmp_path)
    report = RealWorldValidator(str(tmp_path)).run()
    assert report["project"] == str(tmp_path)
    assert report["risk_count"] == 1
    assert any("eval" in r.lower() for r in report["risks_found"])


def test_run_skips_test_files(tmp_path: Path):
    # Files whose name contains "test_" are excluded from analysis.
    app = tmp_path / "app"
    app.mkdir()
    (app / "real.py").write_text(
        'def run(code):\n    """Doc."""\n    return eval(code)\n',
        encoding="utf-8",
    )
    (app / "test_real.py").write_text(
        'def run(code):\n    """Doc."""\n    return eval(code)\n',
        encoding="utf-8",
    )
    report = RealWorldValidator(tmp_path).run()
    # Only the non-test module is analyzed -> one function, one risk.
    assert report["functions_analyzed"] == 1
    assert report["risk_count"] == 1
