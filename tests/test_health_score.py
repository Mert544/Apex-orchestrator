from __future__ import annotations

import argparse
import json

from app.cli import cmd_grade
from app.engine.health_score import (
    HealthScore, _letter, grade, load_grade_snapshot, render_grade_diff_markdown,
    render_grade_markdown, save_grade_snapshot,
)


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
    assert {c.name for c in h.components} == {
        "Security", "Architecture", "Testing", "Code debt", "Correctness",
        "Maintainability", "Duplication"}


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


def test_code_debt_excludes_test_files(tmp_path):
    # A mutable-default (or modernization) in a test file must NOT count as the
    # project's code debt — same exclusion as security. (Found running Apex on
    # httpie, whose only flagged debt was tests/test_downloads.py.)
    from app.engine.health_score import grade

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    # Clean production code; the mutable default lives only in a test file.
    (tmp_path / "app" / "core.py").write_text("def f(x):\n    return x + 1\n")
    (tmp_path / "tests" / "test_core.py").write_text("def helper(items=[]):\n    return items\n")
    h = grade(str(tmp_path))
    debt = next(c for c in h.components if c.name == "Code debt")
    assert debt.points_lost == 0


def test_code_debt_counts_production_files(tmp_path):
    # A mutable default in real (non-test) code still counts (no regression).
    from app.engine.health_score import grade

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text("def f(items=[]):\n    return items\n")
    h = grade(str(tmp_path))
    debt = next(c for c in h.components if c.name == "Code debt")
    assert debt.points_lost > 0


def test_security_penalty_is_severity_weighted(tmp_path):
    # One critical finding (eval) must cost more than one medium finding
    # (bare-except). A flat per-finding count graded code-smells like RCEs —
    # not honest. (Surfaced grading paramiko, whose issues are all bare-excepts.)
    from app.engine.health_score import grade

    crit = tmp_path / "crit"
    med = tmp_path / "med"
    crit.mkdir()
    med.mkdir()
    (crit / "a.py").write_text("def r(c):\n    return eval(c)\n")
    (med / "a.py").write_text("def f():\n    try:\n        pass\n    except:\n        pass\n")

    crit_sec = next(c for c in grade(str(crit)).components if c.name == "Security")
    med_sec = next(c for c in grade(str(med)).components if c.name == "Security")
    assert crit_sec.points_lost > med_sec.points_lost > 0


def test_security_penalty_caps_at_30(tmp_path):
    # Even a flood of critical findings is capped (the grade stays bounded).
    from app.engine.health_score import grade

    body = "".join(f"def f{i}(c):\n    return eval(c)\n" for i in range(20))
    (tmp_path / "a.py").write_text(body)
    sec = next(c for c in grade(str(tmp_path)).components if c.name == "Security")
    assert sec.points_lost == 30


def test_reliability_debt_counts_in_grade(tmp_path):
    # open() without encoding / a network call without timeout are auto-fixable
    # reliability debt that must show in the headline grade, not only in review.
    from app.engine.health_score import grade

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "io.py").write_text(
        "def load(p):\n    f = open(p)\n    return f.read()\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_io.py").write_text(
        "from app.io import load\n\ndef test_load():\n    assert callable(load)\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    debt = next(c for c in grade(str(tmp_path)).components if c.name == "Code debt")
    assert debt.points_lost > 0


def test_reliability_debt_excludes_test_files(tmp_path):
    # The same exclusion as the rest of code-debt: a no-encoding open() inside a
    # test file does not count against the project's grade.
    from app.engine.health_score import grade

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "clean.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_clean.py").write_text(
        "def test_open():\n    f = open('x')\n    f.close()\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    debt = next(c for c in grade(str(tmp_path)).components if c.name == "Code debt")
    assert debt.points_lost == 0


def test_shallow_tested_modules_are_not_full_credit(tmp_path):
    # A module covered only by a shape-only stub (isinstance/import) must cost
    # Testing points — linkage is not correctness, so no clean A+ on stubs.
    from app.engine.health_score import grade

    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "m.py").write_text("def f(x: int) -> int:\n    return x + 1\n")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import pkg.m\ndef test_m():\n    assert isinstance(pkg.m.f(0), int)\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    h = grade(str(tmp_path))
    testing = next(c for c in h.components if c.name == "Testing")
    assert testing.points_lost > 0
    assert "shallow" in testing.detail


def test_logic_bug_lowers_grade_via_correctness(tmp_path):
    # A guaranteed-crash logic bug (frozen-dataclass mutation) must cost the
    # grade through the Correctness component, not just show up in review.
    from app.engine.health_score import grade

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "from dataclasses import dataclass\n"
        "@dataclass(frozen=True)\nclass C:\n    x: int\n"
        "    def bump(self):\n        self.x = self.x + 1\n"
    )
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import C\ndef test_c():\n    assert C(1).x == 1\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    h = grade(str(tmp_path))
    corr = next(c for c in h.components if c.name == "Correctness")
    assert corr.points_lost > 0


def test_grade_security_reflects_detect_only_findings(tmp_path):
    # tempfile.mktemp / weak hashes are found by the canonical detector but not
    # the SecurityAgent — the grade's Security score must still reflect them.
    from app.engine.health_score import grade

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "import tempfile, hashlib\n"
        "def t():\n    return tempfile.mktemp()\n"
        "def h(b):\n    return hashlib.md5(b).hexdigest()\n"
    )
    (tmp_path / "tests" / "test_m.py").write_text("from app.m import t\ndef test_t():\n    assert callable(t)\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    sec = next(c for c in grade(str(tmp_path)).components if c.name == "Security")
    assert sec.points_lost > 0


def test_component_top_files_populated_for_security(tmp_path):
    # A file with security issues should appear in the Security component's top_files.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "risky.py").write_text("def f(c):\n    return eval(c)\n")
    h = grade(str(tmp_path))
    sec = next(c for c in h.components if c.name == "Security")
    assert sec.points_lost > 0
    assert any("risky.py" in f for f in sec.top_files)


def test_component_top_files_populated_for_testing(tmp_path):
    # Untested modules should appear in the Testing component's top_files.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "unlinked.py").write_text("def f(x):\n    return x + 1\n")
    h = grade(str(tmp_path))
    test_comp = next(c for c in h.components if c.name == "Testing")
    if test_comp.points_lost > 0:
        assert any("unlinked.py" in f for f in test_comp.top_files)


def test_clean_project_top_files_empty(tmp_path):
    # A clean project has nothing to show in top_files.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calc.py").write_text('def add(a, b):\n    """Add."""\n    return a + b\n')
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    h = grade(str(tmp_path))
    for c in h.components:
        if c.points_lost == 0:
            assert c.top_files == []


def test_render_markdown_shows_top_offenders(tmp_path):
    # When there are security issues, the render includes a Top offenders section.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "risky.py").write_text("def f(c):\n    return eval(c)\n")
    md = render_grade_markdown(grade(str(tmp_path)))
    assert "Top offenders" in md
    assert "risky.py" in md


def test_grade_snapshot_save_and_load(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f(x):\n    return x\n")
    h = grade(str(tmp_path))
    save_grade_snapshot(str(tmp_path), h)
    snap = load_grade_snapshot(str(tmp_path))
    assert snap is not None
    assert snap["score"] == h.score
    assert snap["letter"] == h.letter
    assert len(snap["components"]) == len(h.components)


def test_grade_snapshot_load_returns_none_when_missing(tmp_path):
    assert load_grade_snapshot(str(tmp_path)) is None


def test_grade_diff_markdown(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "bad.py").write_text("def f(c):\n    return eval(c)\n")
    h_bad = grade(str(tmp_path))
    save_grade_snapshot(str(tmp_path), h_bad)

    # "Fix" the project.
    (tmp_path / "app" / "bad.py").write_text("import ast\ndef f(c):\n    return ast.literal_eval(c)\n")
    h_good = grade(str(tmp_path))

    snap = load_grade_snapshot(str(tmp_path))
    md = render_grade_diff_markdown(snap, h_good)
    assert "Grade trend" in md
    assert "Security" in md


def test_cmd_grade_save_and_diff_flags(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f(x):\n    return x\n")
    # --save writes the snapshot
    rc = cmd_grade(argparse.Namespace(target=str(tmp_path), min_score=0, json=False,
                                      save=True, diff=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "grade-snapshot.json" in out
    assert (tmp_path / ".apex" / "grade-snapshot.json").exists()

    # --diff compares to the saved snapshot
    rc = cmd_grade(argparse.Namespace(target=str(tmp_path), min_score=0, json=False,
                                      save=False, diff=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Grade trend" in out


def test_maintainability_penalizes_complex_function(tmp_path):
    # A function with many branches (high cyclomatic complexity) costs
    # Maintainability points and names its file in top_files.
    from app.engine.health_score import grade

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(20))
    (tmp_path / "app" / "tangle.py").write_text(
        f"def classify(x):\n{branches}\n    return -1\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_tangle.py").write_text(
        "from app.tangle import classify\ndef test_c():\n    assert classify(0) == 0\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    h = grade(str(tmp_path))
    maint = next(c for c in h.components if c.name == "Maintainability")
    assert maint.points_lost > 0
    assert any("tangle.py" in f for f in maint.top_files)


def test_maintainability_penalty_is_capped(tmp_path):
    # Even a flood of complex functions can't dominate the grade (small cap).
    from app.engine.health_score import _MAINT_CAP, grade

    (tmp_path / "app").mkdir()
    fns = []
    for n in range(10):
        branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(20))
        fns.append(f"def f{n}(x):\n{branches}\n    return -1\n")
    (tmp_path / "app" / "many.py").write_text("\n".join(fns), encoding="utf-8")
    h = grade(str(tmp_path))
    maint = next(c for c in h.components if c.name == "Maintainability")
    assert maint.points_lost == _MAINT_CAP


def test_maintainability_zero_on_simple_project(tmp_path):
    # A simple project's tiny functions are well under the complexity ceiling, so
    # Maintainability costs nothing and contributes no top_files.
    from app.engine.health_score import grade

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calc.py").write_text(
        'def add(a, b):\n    """Add."""\n    return a + b\n', encoding="utf-8"
    )
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    h = grade(str(tmp_path))
    maint = next(c for c in h.components if c.name == "Maintainability")
    assert maint.points_lost == 0
    assert maint.top_files == []


def test_duplication_penalizes_copy_pasted_block(tmp_path):
    # Two modules sharing an identical >= 5-statement block cost Duplication
    # points and name an offending file in top_files.
    from app.engine.health_score import grade

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    block = (
        "    a = 1\n"
        "    b = 2\n"
        "    c = a + b\n"
        "    d = c * 2\n"
        "    e = d - a\n"
        "    return e\n"
    )
    (tmp_path / "app" / "one.py").write_text(f"def first():\n{block}", encoding="utf-8")
    (tmp_path / "app" / "two.py").write_text(f"def second():\n{block}", encoding="utf-8")
    (tmp_path / "tests" / "test_dup.py").write_text(
        "from app.one import first\ndef test_first():\n    assert first() == 5\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")
    h = grade(str(tmp_path))
    dup = next(c for c in h.components if c.name == "Duplication")
    assert dup.points_lost > 0
    assert dup.top_files
    assert any(f.endswith("one.py") or f.endswith("two.py") for f in dup.top_files)
    assert "extract the duplicated blocks into shared helpers" in h.fixes


def test_duplication_zero_when_no_duplication(tmp_path):
    # A project with no duplicated blocks loses zero Duplication points and lists
    # no offending files.
    from app.engine.health_score import grade

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "calc.py").write_text(
        'def add(a, b):\n    """Add."""\n    return a + b\n', encoding="utf-8"
    )
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    h = grade(str(tmp_path))
    dup = next(c for c in h.components if c.name == "Duplication")
    assert dup.points_lost == 0
    assert dup.top_files == []


def test_cmd_grade_diff_no_snapshot_shows_current_grade(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f(x):\n    return x\n")
    rc = cmd_grade(argparse.Namespace(target=str(tmp_path), min_score=0, json=False,
                                      save=False, diff=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "No grade snapshot found" in out
    assert "Project health" in out  # still shows the current grade
