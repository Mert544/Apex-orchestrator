from __future__ import annotations

import argparse

from app.cli import cmd_grade
from app.engine.health_score import HealthScore, _letter, grade, render_grade_markdown


def test_letter_boundaries():
    assert _letter(100) == "A+"
    assert _letter(93) == "A"
    assert _letter(83) == "B"
    assert _letter(70) == "C-"
    assert _letter(61) == "D-"
    assert _letter(40) == "F"


def test_clean_project_scores_high(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calc.py").write_text('def add(a, b):\n    """Add."""\n    return a + b\n')
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    h = grade(str(tmp_path))
    assert isinstance(h, HealthScore)
    assert h.score >= 90 and h.letter.startswith("A")
    assert not h.fixes  # nothing costing points


def test_messy_project_scores_low_with_fixes(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "bad.py").write_text(
        "import yaml\ndef load(s, cache=[]):\n    if s == None:\n        return eval(s)\n    return yaml.load(s)\n"
    )
    h = grade(str(tmp_path))
    assert h.score < 90
    assert h.fixes  # concrete improvement suggestions present
    # Security and testing both cost points.
    lost = {c.name: c.points_lost for c in h.components}
    assert lost["Security"] > 0 and lost["Testing"] > 0


def test_score_clamped_and_components_present(tmp_path):
    (tmp_path / "app").mkdir()
    # Many findings -> security penalty caps, score never negative.
    body = "\n".join(f"def f{i}(c=[]):\n    return eval(c)" for i in range(20))
    (tmp_path / "app" / "lots.py").write_text(body + "\n")
    h = grade(str(tmp_path))
    assert 0 <= h.score <= 100
    assert {c.name for c in h.components} == {"Security", "Architecture", "Testing", "Code debt"}


def test_render_markdown(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f(c):\n    return eval(c)\n")
    md = render_grade_markdown(grade(str(tmp_path)))
    assert "Project health:" in md
    assert "Points lost" in md


def test_cmd_grade_min_score_gate(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "bad.py").write_text("def f(c):\n    return eval(c)\n")
    # A high bar fails on a low-scoring project.
    rc = cmd_grade(argparse.Namespace(target=str(tmp_path), min_score=95, json=False))
    assert rc == 1
    capsys.readouterr()
    # No bar -> always exit 0.
    rc = cmd_grade(argparse.Namespace(target=str(tmp_path), min_score=0, json=False))
    assert rc == 0


def test_cmd_grade_json(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f(x):\n    return x\n")
    rc = cmd_grade(argparse.Namespace(target=str(tmp_path), min_score=0, json=True))
    assert rc == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    assert "score" in payload and "letter" in payload and "components" in payload


def test_fixture_paths_excluded_from_security(tmp_path):
    # Intentional vulnerability fixtures (examples/, tests/) must NOT drag the
    # project's security grade down — only the project's own code counts.
    from app.engine.health_score import _is_fixture_path, grade

    assert _is_fixture_path("examples/legacy/app.py") is True
    assert _is_fixture_path("app/tests/test_x.py") is True
    assert _is_fixture_path("tests/test_x.py") is True
    assert _is_fixture_path("app/engine/foo.py") is False

    (tmp_path / "app").mkdir()
    (tmp_path / "examples").mkdir()
    # Real code is clean; the eval lives only in an examples/ fixture.
    (tmp_path / "app" / "core.py").write_text("def f(x):\n    return x + 1\n")
    (tmp_path / "examples" / "bad.py").write_text("def r(c):\n    return eval(c)\n")
    h = grade(str(tmp_path))
    sec = next(c for c in h.components if c.name == "Security")
    assert sec.points_lost == 0  # the fixture eval is not counted
