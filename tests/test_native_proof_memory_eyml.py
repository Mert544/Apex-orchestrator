"""Native intelligence EXPERIENCE memory — ``app/engine/native_proof_memory`` +
its wiring into the candidate ranking and the implement-stub apply.

Pins the "experience" layer: a native idiom shape that has actually landed real
code here is remembered (recency-weighted, version-bounded) and tried first next
time — proven beats merely-common. And the recording path only remembers a
NATIVE-ONLY landing, on a real, verified apply.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.native_proof_memory import (
    decayed_reliability,
    load_experience,
    record_native_landing,
    set_baseline,
)
from app.execution.stub_synthesis import _native_mind_sources


@pytest.fixture(autouse=True)
def _clear_cache():
    _native_mind_sources.cache_clear()
    yield
    _native_mind_sources.cache_clear()


# --- the store: decay + version boundary -------------------------------------

def test_empty_memory_is_neutral(tmp_path):
    assert decayed_reliability(tmp_path) == {}
    assert load_experience(tmp_path)["records"] == []


def test_recency_weighting_ranks_recent_landings_higher(tmp_path):
    record_native_landing(tmp_path, ["p0 + p1"])              # gen 1
    record_native_landing(tmp_path, ["p0 + p1", "p0 - p1"])   # gen 2
    record_native_landing(tmp_path, ["p0 - p1"])              # gen 3
    scores = decayed_reliability(tmp_path)
    # p0 - p1 (gens 2,3) is more recent than p0 + p1 (gens 1,2)
    assert scores["p0 - p1"] > scores["p0 + p1"]


def test_is_deterministic(tmp_path):
    record_native_landing(tmp_path, ["p0 * p1"])
    record_native_landing(tmp_path, ["p0 * p1"])
    assert decayed_reliability(tmp_path) == decayed_reliability(tmp_path)


def test_empty_shapes_is_a_noop(tmp_path):
    record_native_landing(tmp_path, [])
    assert load_experience(tmp_path)["records"] == []


def test_baseline_retires_prior_experience(tmp_path):
    record_native_landing(tmp_path, ["p0 + p1"])
    record_native_landing(tmp_path, ["p0 - p1"])
    assert decayed_reliability(tmp_path)                      # non-empty
    set_baseline(tmp_path)
    assert decayed_reliability(tmp_path) == {}                # all retired
    # a landing AFTER the boundary counts again; the retired ones stay silent
    record_native_landing(tmp_path, ["p0 * p1"])
    assert set(decayed_reliability(tmp_path)) == {"p0 * p1"}


def test_baseline_keeps_the_audit_trail(tmp_path):
    record_native_landing(tmp_path, ["p0 + p1"])
    set_baseline(tmp_path)
    # the record is dropped from SCORING but not deleted from the store
    assert load_experience(tmp_path)["records"] == [{"shape": "p0 + p1", "gen": 1}]


def test_tolerates_a_corrupt_store(tmp_path):
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "native-mind-experience.json").write_text("{ not json")
    assert decayed_reliability(tmp_path) == {}                # never raises


# --- ranking: experience re-orders candidates --------------------------------

def _corpus_project(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "lib.py").write_text(
        "def addf(a, b):\n    return a + b\ndef subf(a, b):\n    return a - b\n")
    return tmp_path


def test_experience_reranks_candidates(tmp_path, monkeypatch):
    from app.execution.stub_synthesis import _native_mind_candidates, find_stub_functions
    _corpus_project(tmp_path)
    stub = find_stub_functions("def f(x, y):\n    raise NotImplementedError\n")[0]
    monkeypatch.setenv("APEX_NATIVE_MIND", "1")

    _native_mind_sources.cache_clear()
    before = [expr for _label, expr in _native_mind_candidates(tmp_path, stub)]
    assert before == ["x + y", "x - y"]                      # frequency order

    record_native_landing(tmp_path, ["2:p0 - p1"])           # subtraction proved
    _native_mind_sources.cache_clear()
    after = [expr for _label, expr in _native_mind_candidates(tmp_path, stub)]
    assert after == ["x - y", "x + y"]                       # proven idiom first


def test_canonical_shape_is_arity_qualified_no_cross_arity_collision():
    from app.engine.native_synth import canonical_shape
    # a 1-arg identity and a 2-arg "return first param" must NOT share a key
    assert canonical_shape(("a",), "a") != canonical_shape(("a", "b"), "a")
    # a 2-arg sum and a 3-arg body that ignores its 3rd param must NOT collide
    assert canonical_shape(("a", "b"), "a + b") != canonical_shape(
        ("a", "b", "c"), "a + b")
    # same idiom at same arity IS one key (grouping still works)
    assert canonical_shape(("a", "b"), "a + b") == canonical_shape(
        ("m", "n"), "m + n") == "2:p0 + p1"


def test_no_experience_leaves_frequency_order_untouched(tmp_path, monkeypatch):
    from app.execution.stub_synthesis import _native_mind_candidates, find_stub_functions
    _corpus_project(tmp_path)
    stub = find_stub_functions("def f(x, y):\n    raise NotImplementedError\n")[0]
    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _native_mind_sources.cache_clear()
    assert [e for _, e in _native_mind_candidates(tmp_path, stub)] == ["x + y", "x - y"]


# --- the detector: only a NATIVE-ONLY landed body is attributed ---------------

def test_detector_attributes_only_native_only_bodies(tmp_path):
    from app.execution.objectives.implement_stub import _landed_native_shapes
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "lib.py").write_text(
        "def clamp(v, lo, hi):\n    return max(lo, min(v, hi))\n")
    original = ("def bound(a, b, c):\n    raise NotImplementedError\n"
                "def total(x, y):\n    raise NotImplementedError\n")
    # bound = native-only clamp; total = a template (a + b)
    filled = ("def bound(a, b, c):\n    return max(b, min(a, c))\n"
              "def total(x, y):\n    return x + y\n")
    _native_mind_sources.cache_clear()
    assert _landed_native_shapes(tmp_path, "pkg/work.py", original, filled) == [
        "3:max(p1, min(p0, p2))"]


def test_detector_excludes_a_doctest_seeded_template(tmp_path):
    # A stub pinned ONLY by a docstring example that seeds a value-template (n*2),
    # with the corpus also offering n*2 natively. The landed n*2 is a TEMPLATE
    # (the doctest seeds the constant), so it must NOT be attributed to the native
    # lane — the detector seeds witnesses with module_source, mirroring the fill.
    from app.execution.objectives.implement_stub import _landed_native_shapes
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "lib.py").write_text("def twice(x):\n    return x * 2\n")
    original = ('def f(n):\n    """Double.\n\n    >>> f(3)\n    6\n    """\n'
                "    raise NotImplementedError\n")
    filled = ('def f(n):\n    """Double.\n\n    >>> f(3)\n    6\n    """\n'
              "    return n * 2\n")
    _native_mind_sources.cache_clear()
    assert _landed_native_shapes(tmp_path, "pkg/mod.py", original, filled) == []


def test_records_only_a_verified_landing(tmp_path):
    from app.engine.objective_compiler import _record_native_experience

    class _Plan:
        native_shapes = ["2:p0 + p1"]

    # applied but NOT verified -> earns no experience
    _record_native_experience(str(tmp_path), _Plan(), {"applied": True, "verified": False})
    assert decayed_reliability(tmp_path) == {}
    # verified -> remembered
    _record_native_experience(str(tmp_path), _Plan(), {"applied": True, "verified": True})
    assert "2:p0 + p1" in decayed_reliability(tmp_path)


# --- end-to-end: a real apply lands a native-only body AND records it ---------

def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='d'\nversion='0'\n")
    return tmp_path


def test_end_to_end_native_landing_is_remembered(tmp_path, monkeypatch):
    from app.engine.objective_compiler import compile_objective
    _suite_project(tmp_path)
    # a 3-arg clamp exemplar no fixed template supplies
    (tmp_path / "app" / "lib.py").write_text(
        "def clamp(v, lo, hi):\n    return max(lo, min(v, hi))\n")
    (tmp_path / "app" / "work.py").write_text(
        "def bound(a, b, c):\n    raise NotImplementedError\n")
    (tmp_path / "tests" / "test_work.py").write_text(
        "from app.work import bound\n"
        "def test_bound():\n"
        "    assert bound(5, 0, 10) == 5\n"
        "    assert bound(-3, 0, 10) == 0\n"
        "    assert bound(99, 0, 10) == 10\n")
    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _native_mind_sources.cache_clear()

    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    # it landed the native-only body...
    assert result.steps and result.steps[0].verified is True
    assert "max(b, min(a, c))" in (tmp_path / "app" / "work.py").read_text()
    # ...and the experience memory remembered the idiom shape (arity-qualified)
    assert "3:max(p1, min(p0, p2))" in decayed_reliability(tmp_path)


def test_end_to_end_off_lane_records_nothing(tmp_path, monkeypatch):
    from app.engine.objective_compiler import compile_objective
    _suite_project(tmp_path)
    # a template-satisfiable stub; with the lane OFF nothing native is attributed
    (tmp_path / "app" / "calc.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.calc import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n")
    monkeypatch.delenv("APEX_NATIVE_MIND", raising=False)
    _native_mind_sources.cache_clear()

    result = compile_objective(str(tmp_path), objective="implement-stub",
                               apply=True, verify=True)
    assert result.steps and result.steps[0].verified is True
    assert "return a + b" in (tmp_path / "app" / "calc.py").read_text()
    assert decayed_reliability(tmp_path) == {}               # template, not native
