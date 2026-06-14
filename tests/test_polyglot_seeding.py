"""Polyglot hotspots -> grounded development IDEAS.

`scan_polyglot_facts` names the biggest / most-churned NON-Python source files;
`ProjectProfiler` carries them on `polyglot_hotspots`; the idea engine promotes
each into a `polyglot-hotspot` root framed as honest AWARENESS (Apex can't
deep-analyse non-Python source, so the action is recommend-only). These tests
pin the seeding vertical end to end: profile field -> seeder root -> action
bridge -> roadmap phase, plus the invariants (additive/empty, dedup,
determinism, recommend-only, value/feasibility/novelty in [0,1]).
"""

import subprocess
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_permutation import IdeaSeeder, _FACT_HINTS
from app.engine.idea_roadmap import EVOLVE, classify_phase
from app.tools.project_profile import ProjectProfile, ProjectProfiler


# --- helpers ----------------------------------------------------------------

def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _hot(path: str, language: str = "JavaScript", loc: int = 412,
         churn: int = 8) -> dict:
    return {"path": path, "language": language, "loc": loc, "churn": churn}


def _polyglot_roots(profile: ProjectProfile):
    return [
        r for r in IdeaSeeder().seed(profile)
        if r.source_facts and r.source_facts[0].startswith("polyglot-hotspot")
    ]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True,
                   capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "T")
    _git(root, "config", "commit.gpgsign", "false")


# --- profile field ----------------------------------------------------------

def test_field_is_additive_and_defaults_empty():
    # A bare profile carries the field, defaulting to [] (no shift for any
    # existing profile/seeder test).
    assert ProjectProfile(root=".").polyglot_hotspots == []


def test_profiler_populates_field_from_polyglot_tree(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "web").mkdir()
    (tmp_path / "app" / "main.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "web" / "app.js").write_text(
        "const a = 1;\nconst b = 2;\nconsole.log(a, b);\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    hotspots = profile.polyglot_hotspots
    assert hotspots, "expected the non-Python file named as a hotspot"
    entry = next(h for h in hotspots if h["path"] == "web/app.js")
    assert entry["language"] == "JavaScript"
    assert entry["loc"] == 3
    assert set(entry) == {"path", "language", "loc", "churn"}
    assert not any(h["path"].endswith(".py") for h in hotspots)


def test_profiler_field_capped_at_three(tmp_path: Path):
    (tmp_path / "web").mkdir()
    for i in range(6):
        (tmp_path / "web" / f"f{i}.js").write_text(
            f"const x{i} = {i};\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert len(profile.polyglot_hotspots) <= 3


def test_apex_generated_report_html_is_not_a_hotspot(tmp_path: Path):
    # An Apex idea-report HTML page written INTO the scanned tree is an Apex
    # artifact, not project source — it must not become a hotspot (so a
    # dashboard run that writes its output into the project stays deterministic
    # and the signal only names files the developer wrote).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "report.html").write_text(
        "<!DOCTYPE html>\n<html><head><title>Apex Idea Tree</title></head>\n"
        "<body>lots\nof\nlines\nhere\n</body></html>\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert all(h["path"] != "report.html" for h in profile.polyglot_hotspots)


def test_hand_written_html_still_a_hotspot(tmp_path: Path):
    # A developer's own HTML (no Apex marker) is still named.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "index.html").write_text(
        "<html>\n<body>\n<h1>Hi</h1>\n</body>\n</html>\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert any(h["path"] == "index.html" for h in profile.polyglot_hotspots)


def test_all_python_repo_yields_empty_field(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text("y = 2\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.polyglot_hotspots == []


# --- seeding ----------------------------------------------------------------

def test_seeds_polyglot_hotspot_root_naming_the_file():
    profile = _profile(polyglot_hotspots=[_hot("src/app.js", loc=412, churn=8)])
    roots = _polyglot_roots(profile)
    assert len(roots) == 1
    root = roots[0]
    assert root.subject == "src/app.js"
    assert "src/app.js" in root.title
    assert "412 LOC" in root.title
    assert "8 recent commits" in root.title
    assert "outside Python analysis scope" in root.title
    assert root.source_facts[0].startswith("polyglot-hotspot")


def test_seed_commit_word_singular_for_one_commit():
    profile = _profile(polyglot_hotspots=[_hot("src/one.js", loc=10, churn=1)])
    root = _polyglot_roots(profile)[0]
    assert "1 recent commit" in root.title
    assert "1 recent commits" not in root.title


def test_all_python_seeding_is_unchanged():
    # No polyglot hotspots -> no polyglot root, and the whole seed set is
    # byte-identical to a profile that never had the field populated.
    empty = _profile()
    populated_default = _profile(polyglot_hotspots=[])
    a = [r.model_dump() for r in IdeaSeeder().seed(empty)]
    b = [r.model_dump() for r in IdeaSeeder().seed(populated_default)]
    assert a == b
    assert not _polyglot_roots(empty)


def test_seeds_dedup_on_subject_path():
    # Same path twice -> one root (the shared seen_subjects chokepoint).
    profile = _profile(polyglot_hotspots=[
        _hot("src/app.js", loc=412, churn=8),
        _hot("src/app.js", loc=412, churn=8),
    ])
    assert len(_polyglot_roots(profile)) == 1


def test_seeds_at_most_three():
    profile = _profile(polyglot_hotspots=[
        _hot(f"src/f{i}.js", loc=100 - i, churn=10 - i) for i in range(5)
    ])
    assert len(_polyglot_roots(profile)) == 3


def test_seeding_is_deterministic():
    profile = _profile(polyglot_hotspots=[
        _hot("src/a.js", loc=400, churn=9),
        _hot("web/b.html", language="HTML", loc=200, churn=3),
    ])
    first = [r.model_dump() for r in _polyglot_roots(profile)]
    second = [r.model_dump() for r in _polyglot_roots(profile)]
    assert first == second
    assert [r["subject"] for r in first] == ["src/a.js", "web/b.html"]


def test_root_value_axes_in_unit_interval():
    profile = _profile(polyglot_hotspots=[_hot("src/app.js")])
    root = _polyglot_roots(profile)[0]
    assert 0.0 <= root.value <= 1.0
    assert 0.0 <= root.feasibility <= 1.0
    assert 0.0 <= root.novelty <= 1.0
    # Roots keep novelty == 1.0.
    assert root.novelty == 1.0
    assert root.operator == "root"


# --- permutation hint -------------------------------------------------------

def test_fact_hint_registered():
    assert "polyglot-hotspot" in _FACT_HINTS
    hint = _FACT_HINTS["polyglot-hotspot"].lower()
    # An awareness / review-oriented hint (not a transform lens).
    assert "review" in hint or "awareness" in hint


# --- action bridge ----------------------------------------------------------

def test_action_is_recommend_only():
    profile = _profile(polyglot_hotspots=[_hot("src/app.js")])
    idea = _polyglot_roots(profile)[0]
    step = IdeaActionBridge().plan_idea(idea)
    # Apex has NO deterministic transform for non-Python source: it must NOT
    # claim to be executable, even though the path looks like a real file.
    assert step.executable is False
    assert step.action_type == "design_task"
    assert "src/app.js" in step.description


def test_action_recommend_only_even_for_html_subject():
    profile = _profile(polyglot_hotspots=[_hot("web/index.html", language="HTML")])
    idea = _polyglot_roots(profile)[0]
    step = IdeaActionBridge().plan_idea(idea)
    assert step.executable is False


# --- roadmap phase ----------------------------------------------------------

def test_classified_as_evolve():
    profile = _profile(polyglot_hotspots=[_hot("src/app.js")])
    idea = _polyglot_roots(profile)[0]
    # Awareness / evolve signal — NOT a test-first stabilize target.
    assert classify_phase(idea) == EVOLVE
