from __future__ import annotations

import types

from app.reporting.city_dashboard import _module_set, build_city_model


class _FakeProfile:
    """A controllable stand-in for ProjectProfiler().profile()."""

    def __init__(self, **kw):
        self.module_to_tests = kw.get("module_to_tests", {})
        self.dependency_hubs = kw.get("dependency_hubs", [])
        self.fragile_modules = kw.get("fragile_modules", [])
        self.untested_modules = kw.get("untested_modules", [])
        self.dependency_edges = kw.get("dependency_edges", [])


class _FakeMetrics:
    """Stand-in for ModuleMetrics with the fields build_city_model reads."""

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


# --------------------------------------------------------------------------
# _module_set: the "extra not already present" append path (line 34)
# --------------------------------------------------------------------------
def test_module_set_appends_extras_not_in_coverage():
    prof = _FakeProfile(
        module_to_tests={"app/a.py": []},
        dependency_hubs=["app/hub.py"],
        fragile_modules=["app/frag.py"],
        untested_modules=["app/untested.py", "app/a.py"],  # a.py is a dup -> skipped
    )
    mods = _module_set(prof)
    # All extras present exactly once; non-.py entries excluded.
    assert mods.count("app/a.py") == 1
    assert "app/hub.py" in mods
    assert "app/frag.py" in mods
    assert "app/untested.py" in mods


def test_module_set_filters_non_py_and_non_str():
    prof = _FakeProfile(
        module_to_tests={"app/a.py": [], "app/readme.md": [], 123: []},
        dependency_hubs=["app/b.py"],
    )
    mods = _module_set(prof)
    assert mods == ["app/a.py", "app/b.py"]


# --------------------------------------------------------------------------
# Health classification branches: untested (94) and ok (100)
# --------------------------------------------------------------------------
def _patch_build(monkeypatch, profile, *, sec=None, grade=None):
    import app.tools.project_profile as pp
    import app.tools.code_metrics as cm
    import app.engine.health_score as hs

    monkeypatch.setattr(pp, "ProjectProfiler", lambda root: types.SimpleNamespace(profile=lambda: profile))
    monkeypatch.setattr(cm, "CodeMetrics", _FakeCodeMetrics)

    if grade is None:
        monkeypatch.setattr(hs, "grade", lambda root: _grade_obj())
    else:
        monkeypatch.setattr(hs, "grade", grade)

    import app.agents.skills as skills
    if sec is not None:
        monkeypatch.setattr(skills, "SecurityAgent", sec)


def test_health_fragile_untested_hub_and_ok_branches(monkeypatch):
    profile = _FakeProfile(
        module_to_tests={
            "app/ok.py": ["tests/test_ok.py"],
            "app/untested.py": [],
            "app/frag.py": [],
            "app/hub.py": [],
        },
        untested_modules=["app/untested.py"],
        fragile_modules=["app/frag.py"],
        dependency_hubs=["app/hub.py"],
    )

    class _NoFindings:
        def run(self, project_root):
            return {"findings": []}

    _patch_build(monkeypatch, profile, sec=_NoFindings)
    model = build_city_model("/proj")
    by = {b["name"]: b for b in model["buildings"]}
    assert by["app/frag.py"]["health"] == "fragile"
    assert by["app/untested.py"]["health"] == "untested"
    assert by["app/hub.py"]["health"] == "hub"
    assert by["app/ok.py"]["health"] == "ok"
    # ok module had a linked test
    assert by["app/ok.py"]["tests"] == 1


# --------------------------------------------------------------------------
# Edge handling: self-loop skip (122), duplicate skip (125), cap break (129)
# --------------------------------------------------------------------------
def test_edges_skip_self_loops_and_duplicates(monkeypatch):
    edges = [
        ("app/a.py", "app/a.py"),  # self-loop -> skipped (line 122)
        ("app/a.py", "app/b.py"),  # kept
        ("app/a.py", "app/b.py"),  # duplicate -> skipped (line 125)
        ("app/b.py", "app/missing.py"),  # dst not rendered -> skipped
    ]
    profile = _FakeProfile(
        module_to_tests={"app/a.py": [], "app/b.py": []},
        dependency_edges=edges,
    )

    class _NoFindings:
        def run(self, project_root):
            return {"findings": []}

    _patch_build(monkeypatch, profile, sec=_NoFindings)
    model = build_city_model("/proj")
    # Exactly one unique, valid, non-self edge survives.
    assert len(model["edges"]) == 1
    a, b = model["edges"][0]
    assert a != b


def test_edges_capped_at_160(monkeypatch):
    # Build a fully-connected-ish graph that produces > 160 unique edges.
    names = [f"app/m{i}.py" for i in range(40)]
    edges = []
    for i in range(40):
        for j in range(40):
            if i != j:
                edges.append((names[i], names[j]))
    # 40*39 = 1560 unique candidate edges, well past the 160 cap (line 129).
    profile = _FakeProfile(
        module_to_tests={n: [] for n in names},
        dependency_edges=edges,
    )

    class _NoFindings:
        def run(self, project_root):
            return {"findings": []}

    _patch_build(monkeypatch, profile, sec=_NoFindings)
    model = build_city_model("/proj")
    assert len(model["edges"]) == 160


# --------------------------------------------------------------------------
# SecurityAgent failure swallowed (56-57)
# --------------------------------------------------------------------------
def test_security_agent_exception_is_swallowed(monkeypatch):
    profile = _FakeProfile(module_to_tests={"app/a.py": []})

    class _Boom:
        def run(self, project_root):
            raise RuntimeError("scanner exploded")

    _patch_build(monkeypatch, profile, sec=_Boom)
    model = build_city_model("/proj")
    # No findings recorded; building still rendered.
    assert model["totals"]["findings"] == 0
    assert any(b["name"] == "app/a.py" for b in model["buildings"])


# --------------------------------------------------------------------------
# grade() failure -> fallback health (162-163)
# --------------------------------------------------------------------------
def test_grade_exception_falls_back(monkeypatch):
    profile = _FakeProfile(module_to_tests={"app/a.py": []})

    class _NoFindings:
        def run(self, project_root):
            return {"findings": []}

    def _boom_grade(root):
        raise ValueError("cannot grade")

    _patch_build(monkeypatch, profile, sec=_NoFindings, grade=_boom_grade)
    model = build_city_model("/proj")
    assert model["grade"] == {"score": 0, "letter": "?"}
