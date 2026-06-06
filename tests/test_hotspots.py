from __future__ import annotations

from pathlib import Path

from app.reporting.hotspots import build_hotspots, render_hotspots_markdown


def _branchy(name: str, branches: int) -> str:
    body = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(branches))
    return f"def {name}(x):\n{body}\n    return -1\n"


def _project(tmp: Path) -> Path:
    (tmp / "app").mkdir()
    (tmp / "tests").mkdir()
    # A complex, heavily-imported, UNtested module -> should be the top hotspot.
    (tmp / "app" / "hot.py").write_text(_branchy("hot", 12), encoding="utf-8")
    # Importers give hot.py a high fan-in.
    for i in range(3):
        (tmp / "app" / f"caller{i}.py").write_text(
            f"from app.hot import hot\n\ndef use{i}():\n    return hot({i})\n", encoding="utf-8"
        )
    # A simple, tested module -> low risk.
    (tmp / "app" / "calm.py").write_text("def calm(x):\n    return x + 1\n", encoding="utf-8")
    (tmp / "tests" / "test_calm.py").write_text(
        "from app.calm import calm\n\ndef test_calm():\n    assert calm(1) == 2\n", encoding="utf-8"
    )
    (tmp / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0'\n", encoding="utf-8")
    return tmp


def test_hot_module_ranks_first(tmp_path: Path):
    rows = build_hotspots(str(_project(tmp_path)))
    assert rows
    top = rows[0]
    assert top["module"].endswith("hot.py")
    assert top["complexity"] >= 12
    assert top["fan_in"] >= 3
    # every row carries the full set of fields
    for r in rows:
        assert {"module", "loc", "complexity", "fan_in", "tests", "risk"} <= set(r)


def test_risk_rises_with_complexity_and_fan_in(tmp_path: Path):
    rows = build_hotspots(str(_project(tmp_path)))
    by_name = {Path(r["module"]).name: r for r in rows}
    # hot.py (complex, imported, untested) outranks calm.py (simple, tested).
    assert by_name["hot.py"]["risk"] > by_name.get("calm.py", {"risk": 0})["risk"]


def test_risk_formula_is_consistent(tmp_path: Path):
    # Every row's risk is exactly complexity * (1 + fan_in) / (1 + tests),
    # rounded — so more complexity/importers raise it and tests lower it.
    rows = build_hotspots(str(_project(tmp_path)))
    assert rows
    for r in rows:
        expected = round(r["complexity"] * (1 + r["fan_in"]) / (1 + r["tests"]), 2)
        assert r["risk"] == expected


def test_risk_counts_test_functions_not_files(tmp_path: Path):
    # Two projects, identical module, but one has a single test file with MANY
    # real test functions. Depth must lower the risk — file count would not.
    def make(root: Path, n_tests: int) -> dict:
        (root / "app").mkdir(parents=True)
        (root / "tests").mkdir()
        (root / "app" / "hot.py").write_text(_branchy("hot", 12), encoding="utf-8")
        fns = "\n".join(f"def test_h{i}():\n    assert hot({i}) == {i}" for i in range(n_tests))
        (root / "tests" / "test_hot.py").write_text(
            f"from app.hot import hot\n{fns}\n", encoding="utf-8"
        )
        (root / "pyproject.toml").write_text("[project]\nname='d'\nversion='0'\n", encoding="utf-8")
        return {Path(r["module"]).name: r for r in build_hotspots(str(root))}

    thin = make(tmp_path / "thin", 1)
    deep = make(tmp_path / "deep", 8)
    assert deep["hot.py"]["tests"] == 8          # counts functions in the one file
    assert thin["hot.py"]["tests"] == 1
    assert deep["hot.py"]["risk"] < thin["hot.py"]["risk"]


def test_limit_is_respected(tmp_path: Path):
    _project(tmp_path)
    assert len(build_hotspots(str(tmp_path), limit=2)) <= 2


def test_empty_project_is_safe(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='e'\nversion='0'\n", encoding="utf-8")
    rows = build_hotspots(str(tmp_path))
    assert rows == []
    assert "No named modules" in render_hotspots_markdown(rows)


def test_markdown_table_renders(tmp_path: Path):
    rows = build_hotspots(str(_project(tmp_path)))
    md = render_hotspots_markdown(rows)
    assert "# Complexity hotspots" in md
    assert "| Module |" in md
    assert "hot.py" in md
