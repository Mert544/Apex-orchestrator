from __future__ import annotations

from pathlib import Path

from app.validation.real_world_validator import RealWorldValidator


def test_flask_mini_known_issues_detected():
    root = Path(__file__).parent.parent / "examples" / "flask_mini"
    validator = RealWorldValidator(root)
    expected = [
        "eval()",
        "os.system()",
        "pickle.loads",
        "missing_docstring",
        "bare_except",
    ]
    result = validator.assert_expected_issues(expected)

    assert result["all_found"] is True, f"Missing expected issues: {result['missing']}"
    assert result["total_risks"] >= 5


def test_validator_surfaces_risks():
    root = Path(__file__).parent.parent / "examples" / "flask_mini"
    validator = RealWorldValidator(root)
    report = validator.run()
    assert report["functions_analyzed"] >= 5
    assert report["risk_count"] >= 5
    assert any("eval" in r.lower() for r in report["risks_found"])


def test_synthetic_shop_detects_hubs():
    root = Path(__file__).parent.parent / "examples" / "synthetic_shop"
    validator = RealWorldValidator(root)
    report = validator.run()
    assert report["total_files"] >= 5
    assert len(report["critical_untested"]) >= 1


def test_microservices_shop_known_issues_detected():
    root = Path(__file__).parent.parent / "examples" / "microservices_shop"
    validator = RealWorldValidator(root)
    expected = [
        "eval()",
        "os.system()",
        "pickle.loads",
        "missing_docstring",
        "bare_except",
        "too_many_arguments",
    ]
    result = validator.assert_expected_issues(expected)
    assert result["all_found"] is True, f"Missing expected issues: {result['missing']}"
    assert result["total_risks"] >= 6


def test_legacy_bank_known_issues_detected():
    root = Path(__file__).parent.parent / "examples" / "legacy_bank"
    validator = RealWorldValidator(root)
    expected = [
        "eval()",
        "exec()",
        "os.system()",
        "pickle.loads",
        "missing_docstring",
        "too_many_arguments",
    ]
    result = validator.assert_expected_issues(expected)
    assert result["all_found"] is True, f"Missing expected issues: {result['missing']}"
    assert result["total_risks"] >= 6


def test_ml_pipeline_known_issues_detected():
    root = Path(__file__).parent.parent / "examples" / "ml_pipeline"
    validator = RealWorldValidator(root)
    expected = [
        "eval()",
        "exec()",
        "os.system()",
        "yaml.load",
        "missing_docstring",
        "bare_except",
        "too_many_arguments",
    ]
    result = validator.assert_expected_issues(expected)
    assert result["all_found"] is True, f"Missing expected issues: {result['missing']}"
    assert result["total_risks"] >= 6
