from pathlib import Path

from app.reporting.dashboard import build_dashboard


def _project(tmp: Path) -> Path:
    (tmp / "app").mkdir()
    (tmp / "app" / "svc.py").write_text("import os\ndef run(cmd):\n    return eval(cmd)\n")
    (tmp / "app" / "main.py").write_text("def main():\n    return 1\n")
    return tmp


def test_dashboard_is_self_contained_html(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=12, idea_depth=2, breadth=3)
    assert html_doc.startswith("<!doctype html>")
    assert "</html>" in html_doc
    # No external scripts/stylesheets — fully self-contained.
    assert "<script src=" not in html_doc
    assert 'rel="stylesheet"' not in html_doc


def test_dashboard_has_all_sections(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path))
    for heading in ("Project profile", "Scan findings", "Idea permutation tree", "Action plan", "Reasoning"):
        assert heading in html_doc


def test_dashboard_includes_roadmap_and_shape(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=30, idea_depth=2, breadth=3)
    # Roadmap section: phases + quick wins + ROI bars.
    assert "Engineering roadmap" in html_doc
    assert "Phase 1" in html_doc
    assert "class='roi'" in html_doc
    # Tree-shape section: telemetry + the engine's own observations.
    assert "Idea-tree shape" in html_doc
    assert "Observations" in html_doc
    # Nav links for both are present.
    assert "#roadmap" in html_doc and "#shape" in html_doc


def test_dashboard_shows_autonomy_panel(tmp_path):
    import subprocess
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def run(e):\n    return eval(e)\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=20)
    assert "Autonomy" in html_doc
    assert "would apply autonomously" in html_doc or "would recommend only" in html_doc
    assert "#autonomy" in html_doc


def test_dashboard_shows_frontier(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=30, idea_depth=2, breadth=4)
    assert "Efficient frontier" in html_doc
    assert "#frontier" in html_doc


def test_dashboard_shows_trajectory_and_learned_when_present(tmp_path):
    import json
    _project(tmp_path)
    apex = tmp_path / ".apex"
    apex.mkdir()
    # A recorded evolve run -> trajectory section.
    (apex / "evolution-history.jsonl").write_text(
        json.dumps({"ts": "2026-06-03 10:00:00 UTC", "applied": 3, "mode": "supervised",
                    "before": {"security_findings": 4, "executable_fixes": 12},
                    "after": {"security_findings": 1, "executable_fixes": 9}}) + "\n",
        encoding="utf-8",
    )
    # Learned memory -> "What Apex has learned" section.
    (apex / "idea-memory.json").write_text(json.dumps({
        "by_operator": {"harden": {"applied": 5, "rolled_back": 1, "blocked": 0}},
        "by_label": {},
    }), encoding="utf-8")
    html_doc = build_dashboard(str(tmp_path), max_ideas=20)
    assert "Self-improvement trajectory" in html_doc and "#trajectory" in html_doc
    assert "What Apex has learned" in html_doc and "#learned" in html_doc
    assert "harden" in html_doc


def test_dashboard_roadmap_shows_measured_signals(tmp_path):
    # core.py is imported by two modules and has real size -> the roadmap
    # surfaces measured fan-in / LOC under the idea.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def core(x):\n    if x:\n        return 1\n    return 0\n"
    )
    (tmp_path / "app" / "a.py").write_text("import app.core\ndef a():\n    return app.core.core(1)\n")
    (tmp_path / "app" / "b.py").write_text("import app.core\ndef b():\n    return app.core.core(2)\n")
    html_doc = build_dashboard(str(tmp_path), max_ideas=30, idea_depth=2, breadth=3)
    assert "imported by" in html_doc or "LOC" in html_doc


def test_dashboard_surfaces_security_finding(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path))
    # The eval() in svc.py should appear as a finding.
    assert "svc.py" in html_doc
    assert "security findings" in html_doc


def test_dashboard_renders_idea_tree(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=12)
    assert "class='op'" in html_doc  # idea operator chips rendered
    assert "Action plan" in html_doc


def test_dashboard_includes_git_repo_section_when_in_repo(tmp_path):
    import subprocess
    _project(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path)
    html_doc = build_dashboard(str(tmp_path))
    assert "Repository" in html_doc
    assert "uncommitted files" in html_doc


def test_dashboard_skips_repo_section_outside_git(tmp_path):
    _project(tmp_path)  # not a git repo
    html_doc = build_dashboard(str(tmp_path))
    # Other sections still render; the repo section is simply omitted.
    assert "Project profile" in html_doc
    assert "<h2>Repository</h2>" not in html_doc


def test_dashboard_includes_debug_section(tmp_path):
    _project(tmp_path)
    html_doc = build_dashboard(str(tmp_path))
    assert "<h2><span class='ico'>🐞</span>Debug</h2>" in html_doc or "Debug" in html_doc
    # Debug chips present (traces / anomalies).
    assert "anomalies" in html_doc


def test_dashboard_badges_synthesis_and_fragility(tmp_path):
    # eval/os.system + import edge -> security findings, synthesis, and a pair.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("import os\ndef a(c):\n    return eval(c)\n")
    (tmp_path / "app" / "b.py").write_text("import app.a\ndef b():\n    return app.a.a('1')\n")
    html_doc = build_dashboard(str(tmp_path), max_ideas=60, idea_depth=2, breadth=6)
    # Synthesized/module-pair appendix and badges render.
    assert "Synthesized" in html_doc
    assert "ibadge" in html_doc


def test_dashboard_architecture_section(tmp_path):
    # A->B->C->A indirect cycle should surface in the architecture section.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("import app.b\ndef a():\n    return app.b.b()\n")
    (tmp_path / "app" / "b.py").write_text("import app.c\ndef b():\n    return app.c.c()\n")
    (tmp_path / "app" / "c.py").write_text("import app.a\ndef c():\n    return 1\n")
    html_doc = build_dashboard(str(tmp_path))
    assert "Architecture health" in html_doc
    assert "Import cycles" in html_doc
    assert "Import cycles" in html_doc  # KPI + section


def test_proof_section_renders_from_artifact(tmp_path):
    import json
    from app.reporting.dashboard import _proof_section

    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text(json.dumps({
        "generated_at": "2026-06-12T00:00:00+00:00",
        "totals": {"applied": 2, "rolled_back": 1, "blocked": 0, "committed": 0},
        "fixes": [
            {"outcome": "applied",
             "finding": {"action": "harden_security", "target": "app/danger.py"},
             "verification": {"strength": {"level": "module"}},
             "shield_test": "tests/test_danger.py"},
            {"outcome": "rolled_back",
             "finding": {"action": "add_docstring", "target": "app/svc.py"},
             "verification": {"performed": True}},
        ],
    }))
    html_doc = _proof_section(str(tmp_path))
    assert "Proof of fix" in html_doc
    assert "app/danger.py" in html_doc
    assert "suite references the module" in html_doc
    assert "tests/test_danger.py" in html_doc and "🛡️" in html_doc
    assert "↩️" in html_doc  # the rolled-back row


def test_proof_section_empty_without_artifact(tmp_path):
    from app.reporting.dashboard import _proof_section

    assert _proof_section(str(tmp_path)) == ""


def test_roadmap_changes_section_narrates_signals(tmp_path):
    from app.engine.idea_roadmap import Roadmap, RoadmapItem, RoadmapPhase
    from app.engine.roadmap_history import snapshot_roadmap
    from app.reporting.dashboard import _roadmap_changes_section

    def _item(title, phase, fact):
        return RoadmapItem(branch_path="x.a", title=title, subject="app/x.py",
                           phase=phase, impact=0.8, effort=0.4, roi=2.0, value=0.6,
                           kind="permutation", rationale="r", source_facts=[fact])

    prev = Roadmap(objective="", project_root=str(tmp_path), phases=[
        RoadmapPhase(name="Secure", theme="t",
                     items=[_item("Harden: app/a.py", "Secure", "security-finding: app/a.py")])])
    snapshot_roadmap(prev, tmp_path / ".apex" / "roadmap-snapshot.json")
    curr = Roadmap(objective="", project_root=str(tmp_path), phases=[
        RoadmapPhase(name="Evolve", theme="t",
                     items=[_item("Smooth the change path of app/b.py", "Evolve",
                                  "churn-hotspot: app/b.py (12 commits)")])])
    html_doc = _roadmap_changes_section(str(tmp_path), curr)
    assert "Where the new work comes from:" in html_doc
    assert "churn-hotspot" in html_doc
    assert "no longer fires" in html_doc


def test_profile_section_lists_churn_and_stale_debt():
    from app.reporting.dashboard import _profile_section
    from app.tools.project_profile import ProjectProfile

    p = ProjectProfile(root=".",
                       churn_hotspots=[{"module": "app/busy.py", "commits": 17}],
                       debt_marker_ages={"app/old.py": 400, "app/new.py": 10})
    html_doc = _profile_section(p)
    assert "app/busy.py · 17 commits" in html_doc
    assert "app/old.py · ~13 months" in html_doc
    assert "app/new.py" not in html_doc  # fresh debt isn't 'stale'
