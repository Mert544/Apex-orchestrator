from pathlib import Path

from app.skills.decomposer import Decomposer


def test_project_aware_decomposer_seeds_structural_claims(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True, exist_ok=True)

    (tmp_path / "app" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "tests" / "test_basic.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

    decomposer = Decomposer(project_root=tmp_path)
    claims = decomposer.decompose(
        "Scan the target project, extract meaningful implementation claims, and continue with constitution-driven fractal questioning."
    )

    assert len(claims) >= 5
    assert any("Project profile claim" in claim for claim in claims)
    assert any("Entrypoint claim" in claim for claim in claims)
    assert any("Validation surface claim" in claim for claim in claims)
    assert any("Automation claim" in claim for claim in claims)
