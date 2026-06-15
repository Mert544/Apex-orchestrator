"""The deep-nesting (guard-clause / extract) seeding signal.

A top-level function whose MAXIMUM control-flow nesting depth (nested
if/for/while/with/try and their async variants) reaches ``_DEEP_NESTING_FLOOR``
is a control-flow staircase that is hard to read — a prime guard-clause / extract
refactor target ("invert the guard / early-return / extract the inner block").

The scan walks each in-scope, non-fixture module's TOP-LEVEL functions (a nested
def/class body starts its own depth count), flags functions at or above the
floor, sorts ``(-depth, module, function)`` and caps to 5. It is a whole-repo
structural read the GRADE never consumes, so it is gated behind ``not light`` —
light mode yields []. The idea engine promotes each into a ``deep-nesting`` root
that is recommend-only (HOW to flatten the staircase is a DESIGN call; Apex names
the function, it does not auto-write) and REFINE-phased.

These tests pin the vertical end to end: profile field -> seeder root -> action
bridge -> roadmap phase, plus the invariants (deep ONLY, additive/empty,
light-gated, determinism, recommend-only, no "untested" token, no leading
magnitude shape, value axes in [0,1] with roots keeping novelty == 1.0).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_permutation import IdeaSeeder, _FACT_HINTS
from app.engine.idea_roadmap import REFINE, classify_phase
from app.tools.project_profile import ProjectProfile, ProjectProfiler
from app.tools.project_profile import ProjectProfiler as _PP

_FLOOR = _PP._DEEP_NESTING_FLOOR


# --- helpers ----------------------------------------------------------------

def _nested(name: str, depth: int) -> str:
    """A function whose body nests ``depth`` ``if`` blocks deep."""
    lines = [f"def {name}(x):"]
    for level in range(depth):
        lines.append("    " * (level + 1) + f"if x > {level}:")
    lines.append("    " * (depth + 1) + "return x")
    return "\n".join(lines) + "\n"


def _flat() -> str:
    """A function comfortably below the floor (shallow control flow)."""
    return (
        "def flat(x):\n"
        "    if x:\n"
        "        return x + 1\n"
        "    return x\n"
    )


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _entry(module: str, function: str, depth: int) -> dict:
    return {"module": module, "function": function, "depth": depth}


def _nest_roots(profile: ProjectProfile):
    return [
        r for r in IdeaSeeder().seed(profile)
        if r.source_facts and r.source_facts[0].startswith("deep-nesting")
    ]


# --- profile field ----------------------------------------------------------

def test_field_is_additive_and_defaults_empty():
    # A bare profile carries the field, defaulting to [] (no shift for any
    # existing profile/seeder test).
    assert ProjectProfile(root=".").deeply_nested_functions == []


def test_deeply_nested_function_is_flagged(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "deep.py").write_text(
        _nested("staircase", _FLOOR + 1), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    nests = profile.deeply_nested_functions
    assert nests, "a deeply-nested function should be flagged"
    entry = nests[0]
    assert set(entry) == {"module", "function", "depth"}
    assert entry["module"] == "app/deep.py"
    assert entry["function"] == "staircase"
    assert entry["depth"] >= _FLOOR


def test_flat_function_is_NOT_flagged(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "shallow.py").write_text(_flat(), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.deeply_nested_functions == []


def test_function_just_below_floor_is_NOT_flagged(tmp_path: Path):
    # Exactly one level under the floor stays clean — the floor is a >= bar.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "near.py").write_text(
        _nested("almost", _FLOOR - 1), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.deeply_nested_functions == []


def test_nested_def_starts_its_own_count(tmp_path: Path):
    # An OUTER function shallow at its own top level, but containing an INNER
    # def that itself nests deeply, must NOT be charged the inner's depth — the
    # inner scope owns its own nesting (and inner defs are not top-level, so they
    # are never scanned). So this whole module flags nothing.
    inner = _nested("inner", _FLOOR + 1)
    indented = "\n".join("    " + ln for ln in inner.splitlines())
    src = f"def outer(x):\n{indented}\n    return inner(x)\n"
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "wrap.py").write_text(src, encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.deeply_nested_functions == []


def test_empty_project_yields_empty_field(tmp_path: Path):
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.deeply_nested_functions == []


def test_light_mode_skips_the_scan(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "deep.py").write_text(
        _nested("staircase", _FLOOR + 1), encoding="utf-8")
    # Sanity: the same tree DOES flag under the full (non-light) profile.
    assert ProjectProfiler(str(tmp_path)).profile().deeply_nested_functions
    profile = ProjectProfiler(str(tmp_path)).profile(light=True)
    assert profile.deeply_nested_functions == []


def test_fixtures_excluded(tmp_path: Path):
    # A deeply-nested function living in a test/fixture tree is throwaway — never
    # a real subject.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_deep.py").write_text(
        _nested("staircase", _FLOOR + 1), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.deeply_nested_functions == []


def test_field_capped(tmp_path: Path):
    (tmp_path / "app").mkdir()
    for i in range(8):
        (tmp_path / "app" / f"m{i}.py").write_text(
            _nested(f"fn{i}", _FLOOR + 1), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert len(profile.deeply_nested_functions) <= 5


def test_scan_is_deterministic_and_sorted(tmp_path: Path):
    (tmp_path / "app").mkdir()
    # Two functions of different depth so ordering is observable.
    (tmp_path / "app" / "a.py").write_text(
        _nested("deeper", _FLOOR + 2), encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text(
        _nested("shallower", _FLOOR), encoding="utf-8")
    first = ProjectProfiler(str(tmp_path)).profile().deeply_nested_functions
    second = ProjectProfiler(str(tmp_path)).profile().deeply_nested_functions
    assert first == second, "same repo -> identical result"
    # Deepest first, then stable by (module, function).
    keys = [(-e["depth"], e["module"], e["function"]) for e in first]
    assert keys == sorted(keys)
    assert first[0]["function"] == "deeper"


# --- seeding ----------------------------------------------------------------

def test_seeds_deep_nesting_root_naming_the_function():
    profile = _profile(deeply_nested_functions=[
        _entry("app/x.py", "foo", _FLOOR + 1),
    ])
    roots = _nest_roots(profile)
    assert len(roots) == 1
    root = roots[0]
    # Subject is ``module::function`` so it never collides with the module's
    # own idea (mirrors incomplete-protocol's ``module::Class``).
    assert root.subject == "app/x.py::foo"
    assert "foo" in root.title
    assert "app/x.py" in root.title
    assert "Flatten" in root.title
    assert root.source_facts[0].startswith("deep-nesting")


def test_seed_fact_avoids_untested_token():
    # The fact must NOT carry the "untested" token (which would auto-promote it
    # to an executable test idea) — it is a recommend-only design signal.
    profile = _profile(deeply_nested_functions=[_entry("app/x.py", "foo", 6)])
    root = _nest_roots(profile)[0]
    assert "untested" not in root.source_facts[0]


def test_seed_fact_has_no_leading_magnitude_shape():
    # The fact must NOT start with "<int> <magnitude>" (e.g. "5 levels",
    # "depth 5") which would inflate it via the magnitude bonus.
    profile = _profile(deeply_nested_functions=[_entry("app/x.py", "foo", 6)])
    fact = root_fact = _nest_roots(profile)[0].source_facts[0]
    # The fact value follows the "label: " prefix.
    value = fact.split(": ", 1)[1]
    assert not re.match(r"^\d+\s+\w", value), root_fact


def test_seed_subject_does_not_collide_with_module_subject():
    profile = _profile(deeply_nested_functions=[_entry("app/x.py", "foo", 6)])
    root = _nest_roots(profile)[0]
    assert "::" in root.subject
    assert root.subject != "app/x.py"


def test_seeds_at_most_three():
    profile = _profile(deeply_nested_functions=[
        _entry(f"app/m{i}.py", f"fn{i}", 6 + i) for i in range(5)
    ])
    assert len(_nest_roots(profile)) == 3


def test_degenerate_entry_is_not_seeded():
    # A defensive guard: an entry missing module/function never seeds a root.
    profile = _profile(deeply_nested_functions=[{"depth": 6}])
    assert _nest_roots(profile) == []


def test_seeding_is_deterministic():
    profile = _profile(deeply_nested_functions=[
        _entry("app/a.py", "foo", 7),
        _entry("lib/b.py", "bar", 6),
    ])
    first = [r.model_dump() for r in _nest_roots(profile)]
    second = [r.model_dump() for r in _nest_roots(profile)]
    assert first == second
    assert [r["subject"] for r in first] == ["app/a.py::foo", "lib/b.py::bar"]


def test_no_field_seeding_is_unchanged():
    empty = _profile()
    populated_default = _profile(deeply_nested_functions=[])
    a = [r.model_dump() for r in IdeaSeeder().seed(empty)]
    b = [r.model_dump() for r in IdeaSeeder().seed(populated_default)]
    assert a == b
    assert not _nest_roots(empty)


def test_root_value_axes_in_unit_interval():
    profile = _profile(deeply_nested_functions=[_entry("app/x.py", "foo", 6)])
    root = _nest_roots(profile)[0]
    assert 0.0 <= root.value <= 1.0
    assert 0.0 <= root.feasibility <= 1.0
    assert 0.0 <= root.novelty <= 1.0
    # Roots keep novelty == 1.0.
    assert root.novelty == 1.0
    assert root.operator == "root"


# --- permutation hint -------------------------------------------------------

def test_fact_hint_registered():
    assert "deep-nesting" in _FACT_HINTS
    hint = _FACT_HINTS["deep-nesting"].lower()
    # A flatten/guard-clause/extract hint (the maintainability lens).
    assert "flatten" in hint or "guard" in hint
    assert "extract" in hint or "early return" in hint


# --- action bridge ----------------------------------------------------------

def test_action_is_recommend_only():
    profile = _profile(deeply_nested_functions=[_entry("app/x.py", "foo", 6)])
    idea = _nest_roots(profile)[0]
    step = IdeaActionBridge().plan_idea(idea)
    # HOW to flatten the staircase is a DESIGN decision: Apex points, it does not
    # auto-write — so it must NOT claim to be executable.
    assert step.executable is False
    assert step.action_type == "design_task"
    assert "app/x.py::foo" in step.description


# --- roadmap ----------------------------------------------------------------

def test_roadmap_phase_is_refine():
    profile = _profile(deeply_nested_functions=[_entry("app/x.py", "foo", 6)])
    root = _nest_roots(profile)[0]
    # A maintainability refactor (guard-clause/extract) -> REFINE, NOT Stabilize.
    assert classify_phase(root) == REFINE
