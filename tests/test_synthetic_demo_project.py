from pathlib import Path

from app.skills.decomposer import Decomposer
from app.tools.project_profile import ProjectProfiler


def test_synthetic_demo_project_emits_expected_signals():
    repo_root = Path(__file__).resolve().parents[1]
    demo_root = repo_root / "examples" / "synthetic_shop"

    profile = ProjectProfiler(demo_root).profile()

    assert "app/main.py" in profile.entrypoints
    assert any(path.endswith("pyproject.toml") for path in profile.config_files)
    assert any("auth" in path.lower() for path in profile.sensitive_paths)
    assert any(path.endswith("order_service.py") for path in profile.dependency_hubs)
    assert any(path.endswith("token_service.py") for path in profile.untested_modules)
    assert any(path.endswith("order_service.py") for path in profile.critical_untested_modules)


def test_synthetic_demo_project_seeds_high_value_claims():
    repo_root = Path(__file__).resolve().parents[1]
    demo_root = repo_root / "examples" / "synthetic_shop"

    claims = Decomposer(project_root=demo_root).decompose(
        "Scan the target project, extract meaningful implementation claims, and continue with constitution-driven fractal questioning."
    )

    assert any("Dependency hub claim" in claim for claim in claims)
    assert any("Untested module claim" in claim for claim in claims)
    assert any("Sensitive surface claim" in claim for claim in claims)
