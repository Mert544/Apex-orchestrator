from __future__ import annotations

import json
import re
import types
from pathlib import Path

from app.reporting.city_dashboard import _module_set, build_city, build_city_model


class _FakeProfile:
    """A controllable stand-in for ProjectProfiler().profile()."""

    def __init__(self, **kw):
        self.module_to_tests = kw.get("module_to_tests", {})
        self.dependency_hubs = kw.get("dependency_hubs", [])
        self.fragile_modules = kw.get("fragile_modules", [])
        self.untested_modules = kw.get("untested_modules", [])
        self.dependency_edges = kw.get("dependency_edges", [])
        self.coordinator_modules = kw.get("coordinator_modules", [])


class _FakeMetrics:
    def __init__(self, loc=10, complexity=1):
        self.loc = loc
        self.complexity = complexity


class _FakeCodeMetrics:
    def __init__(self, project_root):
        pass

    def for_modules(self, modules):
        return {m: _FakeMetrics() for m in modules}


def _grade_obj(score=80, letter="B"):
    return types.SimpleNamespace(score=score, letter=letter)


def _patch_build(monkeypatch, profile, *, sec=None, grade=None):
    import app.engine.health_score as hs
    import app.tools.code_metrics as cm
    import app.tools.project_profile as pp

    monkeypatch.setattr(
        pp, "ProjectProfiler", lambda root: types.SimpleNamespace(profile=lambda: profile)
    )
    monkeypatch.setattr(cm, "CodeMetrics", _FakeCodeMetrics)
    monkeypatch.setattr(hs, "grade", grade or (lambda root: _grade_obj()))

    import app.agents.skills as skills
    if sec is not None:
        monkeypatch.setattr(skills, "SecurityAgent", sec)


class _NoFindings:
    def run(self, project_root):
        return {"findings": []}


# --------------------------------------------------------------------------
# _module_set surfaces coordinator modules even when coverage missed them.
# --------------------------------------------------------------------------
def test_module_set_includes_coordinator_modules():
    prof = _FakeProfile(
        module_to_tests={"app/a.py": []},
        coordinator_modules=[
            {"module": "app/god.py", "fan_out": 9, "imports": ["app/a.py"]},
            {"module": "not-a-dict"},  # non-dict entry is ignored, no crash
            123,  # non-dict, non-str entry is ignored
        ],
    )
    mods = _module_set(prof)
    assert "app/god.py" in mods
    assert "app/a.py" in mods


# --------------------------------------------------------------------------
# A coordinator module gets the distinct visual-cue data + a HUD count.
# --------------------------------------------------------------------------
def test_coordinator_module_is_flagged_and_counted(monkeypatch):
    profile = _FakeProfile(
        module_to_tests={
            "app/god.py": ["tests/test_god.py"],
            "app/a.py": [],
            "app/b.py": [],
        },
        coordinator_modules=[
            {"module": "app/god.py", "fan_out": 7, "imports": ["app/a.py", "app/b.py"]},
        ],
    )
    _patch_build(monkeypatch, profile, sec=_NoFindings)
    model = build_city_model("/proj")

    by = {b["name"]: b for b in model["buildings"]}
    god = by["app/god.py"]
    assert god["coordinator"] is True
    assert god["fan_out"] == 7
    # Imports are carried through in the deterministic order the profile emits.
    assert god["coord_imports"] == ["app/a.py", "app/b.py"]
    # A non-coordinator desk reports the opposite.
    assert by["app/a.py"]["coordinator"] is False
    assert by["app/a.py"]["fan_out"] == 0
    # The HUD totals expose a coordinator count grounded in the buildings.
    assert model["totals"]["coordinators"] == 1


def test_no_coordinators_keeps_count_zero(monkeypatch):
    profile = _FakeProfile(module_to_tests={"app/a.py": []})
    _patch_build(monkeypatch, profile, sec=_NoFindings)
    model = build_city_model("/proj")
    assert model["totals"]["coordinators"] == 0
    assert all(b["coordinator"] is False for b in model["buildings"])
    assert all(b["fan_out"] == 0 for b in model["buildings"])


# --------------------------------------------------------------------------
# The rendered page wires the coordinator cue, legend, and HUD KPI in.
# --------------------------------------------------------------------------
def test_html_surfaces_coordinator_cue_and_kpi(monkeypatch):
    profile = _FakeProfile(
        module_to_tests={"app/god.py": [], "app/a.py": []},
        coordinator_modules=[
            {"module": "app/god.py", "fan_out": 8, "imports": ["app/a.py"]},
        ],
    )
    _patch_build(monkeypatch, profile, sec=_NoFindings)
    html = build_city("/proj")

    # Legend entry, the in-scene amber-spire branch, and the HUD KPI are present.
    assert "coordinator (high fan-out)" in html
    assert "if (b.coordinator)" in html
    assert 'kpi(t.coordinators,"coordinators")' in html
    # The coordinator's own data is embedded in the model JSON.
    m = re.search(r"const DATA = (\{.*?\});", html, re.S)
    assert m is not None
    data = json.loads(m.group(1))
    god = next(b for b in data["buildings"] if b["name"] == "app/god.py")
    assert god["coordinator"] is True and god["fan_out"] == 8


# --------------------------------------------------------------------------
# Self-containment + a single canonical UTC timestamp.
# --------------------------------------------------------------------------
def _real_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "util.py").write_text(
        "def helper(x):\n    return x + 1\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0'\n", encoding="utf-8"
    )
    return tmp_path


def test_page_is_self_contained(tmp_path: Path):
    _real_project(tmp_path)
    html = build_city(str(tmp_path))
    # No injected stylesheet links, no offline-breaking remote assets beyond the
    # single documented Three.js library script the build API already promises.
    assert 'rel="stylesheet"' not in html
    remotes = re.findall(r"https?://[^\s\"'<>]+", html)
    assert remotes == [
        "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
    ], remotes
    assert "three.min.js" in html  # build API contract preserved


def test_single_canonical_utc_timestamp(tmp_path: Path):
    _real_project(tmp_path)
    model = build_city_model(str(tmp_path))
    stamp = model["generated"]
    # Canonical: minute-granularity UTC, never local time / seconds.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", stamp), stamp

    html = build_city(str(tmp_path))
    # The stamp appears exactly once in the page (single source of truth) and no
    # second second-granularity timestamp leaked in.
    assert html.count(stamp) == 1
    assert not re.search(r"\d{2}:\d{2}:\d{2}", html)
