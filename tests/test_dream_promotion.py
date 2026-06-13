"""The dream→wake feedback loop: confirmed discoveries graduate into ideas."""

from __future__ import annotations

import json

from app.engine.dream import PROMOTE_STREAK
from app.tools.project_profile import ProjectProfile


def _coupled_profile() -> ProjectProfile:
    # Two modules that are BOTH high-churn and single-author -> a strong,
    # high-confidence association the dream can discover repeatedly.
    return ProjectProfile(
        root=".",
        churn_hotspots=[{"module": "app/a.py", "commits": 9},
                        {"module": "app/b.py", "commits": 8}],
        knowledge_risks=[{"module": "app/a.py", "share": 100, "commits": 9},
                         {"module": "app/b.py", "share": 95, "commits": 8}],
    )


def _dream_with_fixed_profile(tmp_path, monkeypatch):
    # Force _review_pulse to see our crafted profile (deterministic discovery).
    import app.engine.dream as dm
    from app.tools.project_profile import ProjectProfiler

    prof = _coupled_profile()
    monkeypatch.setattr(ProjectProfiler, "profile", lambda self: prof)
    return dm.dream(tmp_path, curate=True)


def test_promotion_requires_persistence_then_seeds_ideas(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    promo = tmp_path / ".apex" / "dream-promotions.json"

    # Dreams 1 and 2: discovered, but not yet confirmed enough -> no promotion.
    _dream_with_fixed_profile(tmp_path, monkeypatch)
    _dream_with_fixed_profile(tmp_path, monkeypatch)
    assert json.loads(promo.read_text()) == []  # still below the streak gate

    # Dream 3: the SAME law, now seen in PROMOTE_STREAK consecutive dreams.
    report = _dream_with_fixed_profile(tmp_path, monkeypatch)
    assert report.promoted, "a 3x-confirmed high-confidence law should graduate"
    promoted = json.loads(promo.read_text())
    assert promoted and all(p["streak"] >= PROMOTE_STREAK for p in promoted)

    # The waking seeder now turns that promotion into a development idea.
    from app.engine.idea_permutation import IdeaSeeder

    roots = IdeaSeeder(str(tmp_path)).seed(ProjectProfile(root="."))
    insight = next(r for r in roots if r.source_facts
                   and r.source_facts[0].startswith("dream-insight:"))
    assert "Act on a confirmed pattern" in insight.title
    from app.engine.idea_roadmap import EVOLVE, classify_phase

    assert classify_phase(insight) == EVOLVE


def test_default_dream_only_proposes_promotion(tmp_path, monkeypatch):
    import app.engine.dream as dm
    from app.tools.project_profile import ProjectProfiler

    (tmp_path / "app").mkdir()
    prof = _coupled_profile()
    monkeypatch.setattr(ProjectProfiler, "profile", lambda self: prof)
    for _ in range(PROMOTE_STREAK):
        report = dm.dream(tmp_path, curate=False)  # never writes
    assert not (tmp_path / ".apex" / "dream-promotions.json").exists()
    assert any("promote to the idea engine" in p for p in report.proposed)


def test_promotion_clears_when_law_stops_holding(tmp_path, monkeypatch):
    import app.engine.dream as dm
    from app.tools.project_profile import ProjectProfiler

    (tmp_path / "app").mkdir()
    strong = _coupled_profile()
    monkeypatch.setattr(ProjectProfiler, "profile", lambda self: strong)
    for _ in range(PROMOTE_STREAK):
        dm.dream(tmp_path, curate=True)
    assert json.loads((tmp_path / ".apex" / "dream-promotions.json").read_text())

    # The law vanishes (empty profile) -> the store is rewritten empty, no stale.
    monkeypatch.setattr(ProjectProfiler, "profile",
                        lambda self: ProjectProfile(root="."))
    dm.dream(tmp_path, curate=True)
    assert json.loads((tmp_path / ".apex" / "dream-promotions.json").read_text()) == []


def test_promotions_absent_means_no_insight_seeds(tmp_path):
    from app.engine.idea_permutation import IdeaSeeder

    roots = IdeaSeeder(str(tmp_path)).seed(ProjectProfile(root="."))
    assert not any(r.source_facts and r.source_facts[0].startswith("dream-insight:")
                   for r in roots)


def _confluence_profile() -> ProjectProfile:
    # app/big.py carries FOUR signals while two leaf modules carry one each:
    # breadth 4 > typical 1 and confidence 4/5 = 0.80 — a promotable
    # confluence discovery (the gate is >= 0.80).
    return ProjectProfile(
        root=".",
        churn_hotspots=[{"module": "app/big.py", "commits": 9},
                        {"module": "app/small.py", "commits": 5},
                        {"module": "app/tiny.py", "commits": 4}],
        knowledge_risks=[{"module": "app/big.py", "share": 100, "commits": 9}],
        dependency_hubs=["app/big.py"],
        symbol_hubs=["app/big.py"],
    )


def _dream_confluence(tmp_path, monkeypatch):
    import app.engine.dream as dm
    from app.tools.project_profile import ProjectProfiler

    prof = _confluence_profile()
    monkeypatch.setattr(ProjectProfiler, "profile", lambda self: prof)
    return dm.dream(tmp_path, curate=True)


def test_promoted_confluence_materializes_a_saved_work_order(tmp_path, monkeypatch):
    # The loop used to stop at "promoted to the idea engine" — a human still
    # had to run `apex brief --subject ... --save`. Now the dream closes it.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "big.py").write_text("def hub():\n    return 1\n")
    (tmp_path / "app" / "small.py").write_text("def leaf():\n    return 2\n")

    _dream_confluence(tmp_path, monkeypatch)
    _dream_confluence(tmp_path, monkeypatch)
    assert not list((tmp_path / ".apex" / "briefs").glob("*.json")) \
        if (tmp_path / ".apex" / "briefs").exists() else True

    report = _dream_confluence(tmp_path, monkeypatch)  # streak hits the gate
    assert any("work order materialized" in c for c in report.curated)
    saved = list((tmp_path / ".apex" / "briefs").glob("*.json"))
    assert len(saved) == 1
    data = json.loads(saved[0].read_text())
    assert data["subject"].startswith("app/big.py")
    assert data.get("evidence") is not None  # measurable baseline, not a note

    # Idempotent: the next dream must not mint a second order for the same
    # standing confluence (that would be the cyclic noise dream prevents).
    _dream_confluence(tmp_path, monkeypatch)
    assert len(list((tmp_path / ".apex" / "briefs").glob("*.json"))) == 1


def test_archived_brief_blocks_rematerialization(tmp_path, monkeypatch):
    # A just-resolved confluence keeps firing in the churn window for a while;
    # an ARCHIVED brief for the subject must also count as "already ordered".
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "big.py").write_text("def hub():\n    return 1\n")
    (tmp_path / "app" / "small.py").write_text("def leaf():\n    return 2\n")
    archive = tmp_path / ".apex" / "briefs" / "archive"
    archive.mkdir(parents=True)
    (archive / "x.z.json").write_text(json.dumps(
        {"subject": "app/big.py", "evidence": {}}))

    for _ in range(PROMOTE_STREAK + 1):
        _dream_confluence(tmp_path, monkeypatch)
    assert not list((tmp_path / ".apex" / "briefs").glob("*.json"))
