"""Edge/error-path coverage for app.reporting.dashboard render helpers.

These tests drive the pure, render-only helpers directly with lightweight
inputs (SimpleNamespace / dicts / artifacts on disk) so they stay fast and
deterministic — no time/random/order assertions, no network.
"""

from types import SimpleNamespace

from app.reporting import dashboard as D


# --- _debug_section ---------------------------------------------------------

def test_debug_section_empty_returns_blank():
    assert D._debug_section({}) == ""


def test_debug_section_renders_error_branch():
    html_doc = D._debug_section({"error": "boom"})
    assert "unavailable: boom" in html_doc
    assert "Debug" in html_doc


def test_debug_section_lists_anomalies_and_patterns():
    html_doc = D._debug_section({
        "trace_count": 3,
        "anomalies": ["slow path A"],
        "pattern_issues": ["repeated pattern B"],
        "total_time_sec": 0,
    })
    assert "slow path A" in html_doc
    assert "repeated pattern B" in html_doc
    assert "<ul class='commits'>" in html_doc


def test_debug_section_no_anomalies_shows_clean_message():
    html_doc = D._debug_section({
        "trace_count": 1, "anomalies": [], "pattern_issues": [], "total_time_sec": 0,
    })
    assert "No anomalies detected" in html_doc


# --- _kind_badge_label / _kind_badge ---------------------------------------

def test_kind_badge_label_non_fragile_is_blank():
    assert D._kind_badge_label("other") == ""


def test_kind_badge_label_fragile():
    assert "fragile" in D._kind_badge_label("fragile")


def test_kind_badge_synthesis():
    idea = SimpleNamespace(kind="synthesis", source_facts=[])
    assert "synthesis" in D._kind_badge(idea)


def test_kind_badge_pair():
    idea = SimpleNamespace(kind="pair", source_facts=[])
    assert "module-pair" in D._kind_badge(idea)


def test_kind_badge_fragile_from_source_facts():
    idea = SimpleNamespace(kind="permutation", source_facts=["fragile: app/x.py"])
    assert "fragile" in D._kind_badge(idea)


def test_kind_badge_plain_permutation_is_blank():
    idea = SimpleNamespace(kind="permutation", source_facts=["other: app/x.py"])
    assert D._kind_badge(idea) == ""


# --- optional sections that return "" when absent --------------------------

def test_roadmap_section_none_returns_blank():
    assert D._roadmap_section(None) == ""


def test_roadmap_section_no_phases_returns_blank():
    assert D._roadmap_section(SimpleNamespace(phases=[])) == ""


def test_shape_section_none_returns_blank():
    assert D._shape_section(None) == ""


def test_shape_section_zero_ideas_returns_blank():
    assert D._shape_section(SimpleNamespace(total_ideas=0)) == ""


def test_autonomy_section_none_returns_blank():
    assert D._autonomy_section(None) == ""


def test_pareto_section_empty_returns_blank():
    assert D._pareto_section([], 0) == ""


def test_trajectory_section_empty_returns_blank():
    assert D._trajectory_section([]) == ""


def test_learned_section_empty_returns_blank():
    assert D._learned_section(None) == ""
    assert D._learned_section({"most_reliable": [], "least_reliable": []}) == ""


def test_repo_section_empty_returns_blank():
    assert D._repo_section({}) == ""


# --- _autonomy_section render branches --------------------------------------

def test_autonomy_section_apply_verdict():
    html_doc = D._autonomy_section({
        "act": True, "mode": "supervised", "executable": 4, "reason": "tree clean",
    })
    assert "would apply autonomously" in html_doc
    assert "tree clean" in html_doc


def test_autonomy_section_recommend_verdict():
    html_doc = D._autonomy_section({
        "act": False, "mode": "supervised", "executable": 0, "reason": "dirty tree",
    })
    assert "would recommend only" in html_doc


# --- _pareto_section render -------------------------------------------------

def test_pareto_section_renders_points_and_dominated_count():
    pt = SimpleNamespace(branch_path="x.a", title="Idea A", reasons=["best ROI"],
                         impact=0.8, effort=0.2, roi=4.0)
    html_doc = D._pareto_section([pt], total_ideas=5)
    assert "Efficient frontier" in html_doc
    assert "Idea A" in html_doc
    assert "best ROI" in html_doc


# --- _trajectory_section render ---------------------------------------------

def test_trajectory_section_renders_history():
    history = [
        {"ts": "2026-06-01 10:00 UTC", "applied": 2, "mode": "supervised",
         "before": {"security_findings": 5, "executable_fixes": 10},
         "after": {"security_findings": 2, "executable_fixes": 7}},
        {"ts": "2026-06-02 10:00 UTC", "applied": 1, "mode": "auto",
         "before": {"security_findings": 2, "executable_fixes": 7},
         "after": {"security_findings": 1, "executable_fixes": 6}},
    ]
    html_doc = D._trajectory_section(history)
    assert "Self-improvement trajectory" in html_doc
    assert "5 → 1" in html_doc  # first.before -> last.after


# --- _learned_section render ------------------------------------------------

def test_learned_section_renders_reliable_rows():
    learned = {
        "operators_tracked": 2, "labels_tracked": 1,
        "most_reliable": [{"key": "harden", "success_rate": 0.8, "samples": 5}],
        "least_reliable": [{"key": "modernize", "success_rate": 0.2, "samples": 5}],
    }
    html_doc = D._learned_section(learned)
    assert "What Apex has learned" in html_doc
    assert "harden" in html_doc and "80%" in html_doc
    assert "modernize" in html_doc and "20%" in html_doc


# --- _reasoning_section error branch ----------------------------------------

def test_reasoning_section_error_branch():
    html_doc = D._reasoning_section({"error": "no orchestrator"})
    assert "unavailable: no orchestrator" in html_doc


def test_reasoning_section_no_claims_empty_table():
    html_doc = D._reasoning_section({
        "mode": "fast", "confidence_map": {}, "debug_stats": {},
        "estimated_total_tokens": 0,
    })
    assert "No claims." in html_doc


def test_reasoning_section_renders_claims():
    html_doc = D._reasoning_section({
        "mode": "deep",
        "confidence_map": {"claim one": 0.512345},
        "debug_stats": {"mean_relevance": 0.7},
        "estimated_total_tokens": 100,
    })
    assert "claim one" in html_doc
    assert "0.512" in html_doc


# --- _proof_section error / no-rows branches --------------------------------

def test_proof_section_invalid_json_returns_blank(tmp_path):
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text("{not valid json", encoding="utf-8")
    assert D._proof_section(str(tmp_path)) == ""


def test_proof_section_no_fixes_returns_blank(tmp_path):
    import json
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text(
        json.dumps({"totals": {"applied": 0}, "fixes": []}), encoding="utf-8")
    assert D._proof_section(str(tmp_path)) == ""


def test_proof_section_blocked_outcome_and_blind_strength(tmp_path):
    import json
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text(json.dumps({
        "generated_at": "2026-06-12T00:00:00+00:00",
        "totals": {"applied": 0, "rolled_back": 0, "blocked": 1, "committed": 0},
        "fixes": [
            {"outcome": "blocked",
             "finding": {"action": "harden_security", "target": "app/x.py"},
             "verification": {"strength": {"level": "none"}}},
        ],
    }), encoding="utf-8")
    html_doc = D._proof_section(str(tmp_path))
    assert "⛔" in html_doc
    assert "applied blind" in html_doc


# --- _roadmap_changes_section guard branches --------------------------------

def test_roadmap_changes_section_none_roadmap_blank(tmp_path):
    assert D._roadmap_changes_section(str(tmp_path), None) == ""


def test_roadmap_changes_section_no_phases_blank(tmp_path):
    assert D._roadmap_changes_section(str(tmp_path), SimpleNamespace(phases=[])) == ""


def test_roadmap_changes_section_no_snapshot_blank(tmp_path):
    # phases present, but no roadmap-snapshot.json on disk -> empty.
    roadmap = SimpleNamespace(phases=[SimpleNamespace(name="Secure", items=[])])
    assert D._roadmap_changes_section(str(tmp_path), roadmap) == ""


def test_roadmap_changes_section_identical_snapshot_blank(tmp_path):
    # An unchanged roadmap (snapshot == current) yields no new/dropped -> "".
    from app.engine.idea_roadmap import Roadmap, RoadmapItem, RoadmapPhase
    from app.engine.roadmap_history import snapshot_roadmap

    item = RoadmapItem(branch_path="x.a", title="Harden: app/a.py", subject="app/a.py",
                       phase="Secure", impact=0.8, effort=0.4, roi=2.0, value=0.6,
                       kind="permutation", rationale="r",
                       source_facts=["security-finding: app/a.py"])
    roadmap = Roadmap(objective="", project_root=str(tmp_path),
                      phases=[RoadmapPhase(name="Secure", theme="t", items=[item])])
    snapshot_roadmap(roadmap, tmp_path / ".apex" / "roadmap-snapshot.json")
    assert D._roadmap_changes_section(str(tmp_path), roadmap) == ""


def test_roadmap_changes_section_snapshot_load_failure_blank(tmp_path):
    # A corrupt snapshot makes the diff machinery raise -> caught -> "".
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "roadmap-snapshot.json").write_text("{broken json", encoding="utf-8")
    roadmap = SimpleNamespace(phases=[SimpleNamespace(name="Secure", items=[])])
    assert D._roadmap_changes_section(str(tmp_path), roadmap) == ""


def test_roadmap_changes_section_diff_exception_blank(tmp_path, monkeypatch):
    # A valid snapshot loads, but diff_roadmaps blowing up is caught -> "".
    import app.engine.roadmap_history as rh
    from app.engine.idea_roadmap import Roadmap, RoadmapItem, RoadmapPhase
    from app.engine.roadmap_history import snapshot_roadmap

    item = RoadmapItem(branch_path="x.a", title="Harden: app/a.py", subject="app/a.py",
                       phase="Secure", impact=0.8, effort=0.4, roi=2.0, value=0.6,
                       kind="permutation", rationale="r",
                       source_facts=["security-finding: app/a.py"])
    roadmap = Roadmap(objective="", project_root=str(tmp_path),
                      phases=[RoadmapPhase(name="Secure", theme="t", items=[item])])
    snapshot_roadmap(roadmap, tmp_path / ".apex" / "roadmap-snapshot.json")

    def _boom(*_a, **_k):
        raise RuntimeError("diff failed")

    monkeypatch.setattr(rh, "diff_roadmaps", _boom)
    assert D._roadmap_changes_section(str(tmp_path), roadmap) == ""


# --- _dream_section ---------------------------------------------------------

def test_dream_section_absent_returns_blank(tmp_path):
    assert D._dream_section(str(tmp_path)) == ""


def test_dream_section_empty_digest_returns_blank(tmp_path):
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "dream-digest.md").write_text("# Dream\n\nno bullets here\n", encoding="utf-8")
    assert D._dream_section(str(tmp_path)) == ""


def test_dream_section_unreadable_digest_returns_blank(tmp_path):
    # A path that exists() but cannot be read as a file (it's a directory)
    # triggers the OSError branch -> "".
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "dream-digest.md").mkdir()  # directory, not a file
    assert D._dream_section(str(tmp_path)) == ""


def test_dream_section_renders_bullets(tmp_path):
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "dream-digest.md").write_text(
        "# Dream digest\n\n## New flows\n- 🌱 discovered a new path\n- ✅ resolved a flow\n",
        encoding="utf-8",
    )
    html_doc = D._dream_section(str(tmp_path))
    assert "discovered a new path" in html_doc
    assert "resolved a flow" in html_doc
    assert "Last dream" in html_doc


# --- _findings_section exposure-exception resilience ------------------------

def test_findings_section_exposure_failure_renders_dash(monkeypatch):
    # analyze_exposure blowing up must not break the findings table; the
    # Exposure column falls back to "—".
    import app.engine.exposure as exposure_mod

    def _boom(*_a, **_k):
        raise RuntimeError("exposure unavailable")

    monkeypatch.setattr(exposure_mod, "analyze_exposure", _boom)
    findings = {"security": {"findings_count": 1, "findings": [
        {"file": "app/main.py", "line": 2, "details": "eval()", "severity": "high"}]}}
    html_doc = D._findings_section(findings, project_root="/does/not/matter")
    assert "app/main.py" in html_doc
    assert "<th>Exposure</th>" in html_doc


# --- _run_scanners / _run_reasoning / _run_debug / _git_info error paths ----

def test_run_scanners_captures_agent_errors(monkeypatch):
    import app.agents.skills as skills

    class _Boom:
        def run(self, **_k):
            raise RuntimeError("scanner failed")

    for name in ("SecurityAgent", "DocstringAgent", "TestStubAgent", "DependencyAgent"):
        monkeypatch.setattr(skills, name, _Boom)
    out = D._run_scanners("/nowhere")
    assert out["security"] == {"error": "scanner failed"}
    assert out["coverage"] == {"error": "scanner failed"}


def test_run_reasoning_error_branch(monkeypatch):
    # Force the import inside _run_reasoning to fail by removing the module.
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "app.orchestrator":
            raise ImportError("no orchestrator")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    out = D._run_reasoning("/nowhere", None)
    assert "error" in out


def test_git_info_outside_repo_returns_empty(tmp_path):
    # tmp_path is not a git repo -> {}.
    assert D._git_info(str(tmp_path)) == {}


def test_git_info_subprocess_failure_returns_empty(monkeypatch):
    # subprocess.run raising (e.g. git missing) is swallowed by the inner
    # _run helper, so the first rev-parse returns "" and _git_info -> {}.
    import subprocess

    def _boom(*_a, **_k):
        raise OSError("git not found")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert D._git_info("/nowhere") == {}


def test_run_debug_error_branch(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "app.engine.debug_engine":
            raise ImportError("no debug engine")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    out = D._run_debug("/nowhere", SimpleNamespace(top_directories=[], total_files=0))
    assert "error" in out


# --- _repo_section render with commits --------------------------------------

def test_full_dashboard_includes_dream_nav_when_digest_present(tmp_path):
    # A dream-digest on disk adds the Dream nav link and section to the page.
    from app.reporting.dashboard import build_dashboard

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def run():\n    return 1\n")
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "dream-digest.md").write_text(
        "# Dream\n\n- 🌱 a discovery while you were away\n", encoding="utf-8")
    html_doc = build_dashboard(str(tmp_path), max_ideas=8, idea_depth=1, breadth=2)
    assert "#dream" in html_doc
    assert "a discovery while you were away" in html_doc


def test_build_dashboard_survives_optional_subsystem_failures(tmp_path, monkeypatch):
    # Every best-effort subsystem (plugins, roadmap, shape, pareto, evolution,
    # learned memory, autonomy) failing to import must not break the dashboard —
    # each except-branch falls back to empty/None and the page still renders.
    import builtins

    from app.reporting.dashboard import build_dashboard

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def run():\n    return 1\n")

    # These modules are imported ONLY by build_dashboard's own best-effort
    # blocks (not by the permutation engine internals), so forcing them to fail
    # exercises every except-branch without breaking the core run.
    failing = {
        "app.plugins.registry",
        "app.engine.idea_roadmap",
        "app.engine.idea_tree_shape",
        "app.engine.idea_pareto",
        "app.engine.evolution",
        "app.engine.idea_memory",
        "app.policies.autonomy_policy",
    }
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        # Only fail when imported from the dashboard module's own frames; the
        # permutation engine imports some of these too and must keep working.
        if name in failing:
            frame = kwargs.get("globals") or (args[0] if args else None)
            modname = frame.get("__name__", "") if isinstance(frame, dict) else ""
            if modname == "app.reporting.dashboard":
                raise ImportError(f"forced failure: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    html_doc = build_dashboard(str(tmp_path), max_ideas=8, idea_depth=1, breadth=2)
    # The page still renders end-to-end despite every optional subsystem failing.
    assert html_doc.startswith("<!doctype html>")
    assert "Project profile" in html_doc
    # The optional sections are simply omitted (no roadmap/shape/autonomy nav).
    assert "#roadmap" not in html_doc
    assert "#autonomy" not in html_doc


def test_repo_section_renders_branch_and_commits():
    git = {"branch": "main", "total_commits": "12", "dirty": 1,
           "commits": ["abc123 fix", "def456 feat"]}
    html_doc = D._repo_section(git)
    assert "Repository" in html_doc
    assert "abc123 fix" in html_doc
    assert "main" in html_doc
