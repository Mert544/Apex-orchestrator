"""Tests for self-insight — Apex inspects a codebase (incl. itself) with its
newest organs. All tests use a SMALL synthetic tmp project; none profile the
whole Apex repo."""

from __future__ import annotations

import textwrap

import pytest

import app.engine.self_insight as si
from app.engine.self_insight import (
    gather_sources,
    render_self_insight_markdown,
    self_insight,
)

_SECTIONS = ("anomalies", "proposed_rules", "weaknesses", "curriculum")


def _write(root, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def _project_with_anomaly_and_pattern(root) -> None:
    """A small project: several plain modules plus one module that DEFIES the
    norm (carries an eval-style security finding the others lack), and a syntactic
    micro-pattern (the same ``if x: return y`` shape) recurring across files."""
    pattern = """
    def f(x):
        if x:
            return x
        return 0
    """
    # Three ordinary modules sharing the recurring if/return micro-pattern.
    for name in ("alpha", "beta", "gamma"):
        _write(root, f"pkg/{name}.py", pattern)
    # The outlier: same pattern PLUS an eval-based security finding the others lack.
    _write(
        root,
        "pkg/outlier.py",
        """
        def g(x):
            if x:
                return eval(x)
            return 0
        """,
    )


def test_insight_surfaces_anomaly_and_rule(tmp_path):
    _project_with_anomaly_and_pattern(tmp_path)
    insight = self_insight(str(tmp_path))
    assert set(insight) == set(_SECTIONS)
    # The recurring if/return shape is mined into at least one candidate rule.
    assert insight["proposed_rules"], "expected a recurring micro-pattern"
    shapes = " ".join(r["shape"] for r in insight["proposed_rules"])
    assert "If" in shapes or "Return" in shapes
    # The eval outlier deviates from the norm — it should be flagged.
    modules = {a["module"] for a in insight["anomalies"]}
    assert any("outlier" in m for m in modules)


def test_sections_bounded_and_sorted(tmp_path):
    _project_with_anomaly_and_pattern(tmp_path)
    insight = self_insight(str(tmp_path))
    assert len(insight["anomalies"]) <= si._MAX_ANOMALIES
    assert len(insight["proposed_rules"]) <= si._MAX_RULES
    assert len(insight["weaknesses"]) <= si._MAX_WEAKNESSES
    assert len(insight["curriculum"]) <= si._MAX_CURRICULUM
    # Anomalies sorted by deviation desc (the organ's contract, surfaced here).
    devs = [a["deviation"] for a in insight["anomalies"]]
    assert devs == sorted(devs, reverse=True)


def test_empty_project_is_valid_empty_insight(tmp_path):
    insight = self_insight(str(tmp_path))
    assert insight == {k: [] for k in _SECTIONS}
    md = render_self_insight_markdown(str(tmp_path))
    assert md.startswith("# Apex self-insight")
    # Each empty section gets an explicit empty-state line.
    assert "No off-pattern modules surfaced." in md
    assert "No recurring rewritable pattern surfaced." in md
    assert "No proof history to grade fixing from." in md
    assert "No hardening directions yet." in md


def test_tiny_project_does_not_raise(tmp_path):
    _write(tmp_path, "only.py", "x = 1\n")
    insight = self_insight(str(tmp_path))
    assert set(insight) == set(_SECTIONS)
    # One module is far below the anomaly organ's MIN_MODULES floor.
    assert insight["anomalies"] == []


def test_markdown_has_a_heading_per_organ(tmp_path):
    _project_with_anomaly_and_pattern(tmp_path)
    md = render_self_insight_markdown(str(tmp_path))
    for heading in ("Anomalies", "Proposed rules", "Weaknesses", "Curriculum"):
        assert f"## {heading}" in md
    assert md.endswith("\n")


def test_deterministic_byte_identical(tmp_path):
    _project_with_anomaly_and_pattern(tmp_path)
    first = self_insight(str(tmp_path))
    second = self_insight(str(tmp_path))
    assert first == second
    md_first = render_self_insight_markdown(str(tmp_path))
    md_second = render_self_insight_markdown(str(tmp_path))
    assert md_first == md_second


def test_gather_sources_bounded_sorted_and_keyed_relative(tmp_path):
    _project_with_anomaly_and_pattern(tmp_path)
    sources = gather_sources(str(tmp_path))
    assert sources, "expected python sources gathered"
    keys = list(sources)
    assert keys == sorted(keys)
    assert all(not k.startswith("/") for k in keys)
    assert all(k.endswith(".py") for k in keys)
    assert len(sources) <= si._MAX_SOURCES


def test_gather_sources_tolerates_unreadable_file(tmp_path, monkeypatch):
    _write(tmp_path, "good.py", "x = 1\n")
    _write(tmp_path, "bad.py", "y = 2\n")
    real_read = type(tmp_path).read_text

    def flaky(self, *args, **kwargs):
        if self.name == "bad.py":
            raise OSError("boom")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(type(tmp_path), "read_text", flaky)
    sources = gather_sources(str(tmp_path))
    assert "good.py" in sources
    assert "bad.py" not in sources


def test_raising_organ_yields_complete_insight(tmp_path, monkeypatch):
    _project_with_anomaly_and_pattern(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("organ failed")

    monkeypatch.setattr(si, "find_anomalies", boom)
    insight = self_insight(str(tmp_path))
    # The failing organ degrades to an empty section; the rest still populate.
    assert insight["anomalies"] == []
    assert set(insight) == set(_SECTIONS)
    assert insight["proposed_rules"], "other organs must still run"
    # Markdown still renders the full skeleton.
    md = render_self_insight_markdown(str(tmp_path))
    assert "No off-pattern modules surfaced." in md


def test_unprofilable_root_degrades_to_empty(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("no profiler")

    monkeypatch.setattr(
        "app.tools.project_profile.ProjectProfiler.profile", boom
    )
    _write(tmp_path, "only.py", "x = 1\n")
    insight = self_insight(str(tmp_path))
    # Profile failed → anomalies empty, but sources-based organs still run.
    assert insight["anomalies"] == []
    assert set(insight) == set(_SECTIONS)


def test_weaknesses_and_curriculum_from_proof_history(tmp_path):
    """A synthetic proof artifact with repeated rollbacks surfaces a weakness and
    a curriculum line — exercising the inward-looking organs end to end."""
    import json

    apex = tmp_path / ".apex"
    apex.mkdir()
    fixes = [
        {
            "finding": {"action": "harden_eval", "target": "pkg/a.py"},
            "outcome": "rolled_back",
        },
        {
            "finding": {"action": "harden_eval", "target": "pkg/b.py"},
            "outcome": "rolled_back",
        },
    ]
    proof = {"schema": "apex-proof-of-fix/v1", "generated_at": "x", "fixes": fixes}
    # Discover the real schema constant so the proof validates.
    from app.engine.proof_of_fix import SCHEMA

    proof["schema"] = SCHEMA
    (apex / "proof-of-fix.json").write_text(json.dumps(proof), encoding="utf-8")
    insight = self_insight(str(tmp_path))
    actions = {w["action"] for w in insight["weaknesses"]}
    assert "harden_eval" in actions
    assert any("harden_eval" in line for line in insight["curriculum"])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
