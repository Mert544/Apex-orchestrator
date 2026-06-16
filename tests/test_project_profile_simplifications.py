from pathlib import Path

from app.tools.project_profile import ProjectProfiler


def _repo_with_simplifiable_pattern(root: Path) -> None:
    """A tiny real-source repo carrying a ``not not x`` (double-not) that the
    safe ``double-not`` transform would fire on."""
    (root / "app").mkdir()
    (root / "app" / "logic.py").write_text(
        "def truthy(x):\n    return not not x\n",
        encoding="utf-8",
    )


def test_simplifications_populated_under_full_scan(tmp_path: Path):
    _repo_with_simplifiable_pattern(tmp_path)
    profile = ProjectProfiler(tmp_path).profile()

    opps = profile.simplification_opportunities
    assert opps, "full scan should surface the double-not opportunity"
    for opp in opps:
        assert set(opp) >= {"module", "transform", "fact_label"}
    # The double-not transform must be among the named opportunities, keyed to
    # the source module.
    labels = {o["fact_label"] for o in opps}
    assert "double-not" in labels
    assert any(Path(o["module"]).as_posix() == "app/logic.py" for o in opps)


def test_simplifications_empty_under_light_mode(tmp_path: Path):
    _repo_with_simplifiable_pattern(tmp_path)
    profile = ProjectProfiler(tmp_path).profile(light=True)

    # The whole-tree dry-run is gated behind ``not light`` — the grade path must
    # not pay for it, so the field stays at its empty default.
    assert profile.simplification_opportunities == []


def test_simplifications_empty_on_clean_repo(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "clean.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )
    profile = ProjectProfiler(tmp_path).profile()
    assert profile.simplification_opportunities == []


def test_simplifications_deterministic(tmp_path: Path):
    _repo_with_simplifiable_pattern(tmp_path)
    first = ProjectProfiler(tmp_path).profile().simplification_opportunities
    second = ProjectProfiler(tmp_path).profile().simplification_opportunities
    assert first == second
