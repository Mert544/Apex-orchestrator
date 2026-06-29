"""The god-class (Single-Responsibility violation / decompose) seeding signal.

A top-level class declaring an unusually high number of methods is doing too
much: too many behaviours have accreted onto one type, so it is a decomposition
candidate ("split into smaller, cohesive collaborators"). The scan counts, per
top-level class, its methods (``def``/``async def`` body members) and its
distinct ``self.X =`` attributes, and flags classes whose method count reaches
``_GOD_CLASS_METHOD_FLOOR``; it sorts ``(-methods, module, classname)`` and caps
to 5. It is a whole-repo structural read the GRADE never consumes, so it is gated
behind ``not light`` — light mode yields []. The idea engine promotes each into a
``god-class`` root that is recommend-only (HOW to decompose the class is a DESIGN
call; Apex names the class, it does not auto-write the split) and EVOLVE-phased.

These tests pin the vertical end to end: profile field -> seeder root -> action
bridge -> roadmap phase, plus the invariants (god ONLY, additive/empty,
light-gated, determinism, recommend-only, no "untested" token, no leading
magnitude shape, value axes in [0,1] with roots keeping novelty == 1.0).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_permutation import IdeaSeeder, _FACT_HINTS
from app.engine.idea_roadmap import EVOLVE, classify_phase
from app.tools.project_profile import ProjectProfile, ProjectProfiler
from app.tools.project_profile import ProjectProfiler as _PP

_FLOOR = _PP._GOD_CLASS_METHOD_FLOOR


# --- helpers ----------------------------------------------------------------

def _class(name: str, methods: int, attrs: int = 0) -> str:
    """A class declaring EXACTLY ``methods`` methods total and assigning ``attrs``
    distinct ``self.X`` attributes. When ``attrs`` is given, an ``__init__`` holds
    the assignments and counts as one of the ``methods`` (so the body always has
    ``methods`` ``def`` members, matching what the scan counts)."""
    lines = [f"class {name}:"]
    remaining = methods
    if attrs:
        lines.append("    def __init__(self):")
        for i in range(attrs):
            lines.append(f"        self.attr_{i} = {i}")
        remaining -= 1  # __init__ is itself one of the methods
    for i in range(remaining):
        lines.append(f"    def method_{i}(self):")
        lines.append(f"        return {i}")
    return "\n".join(lines) + "\n"


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _entry(module: str, classname: str, methods: int, attributes: int = 0) -> dict:
    return {"module": module, "classname": classname,
            "methods": methods, "attributes": attributes}


def _god_roots(profile: ProjectProfile):
    return [
        r for r in IdeaSeeder().seed(profile)
        if r.source_facts and r.source_facts[0].startswith("god-class")
    ]


# --- profile field ----------------------------------------------------------

def test_field_is_additive_and_defaults_empty():
    # A bare profile carries the field, defaulting to [] (no shift for any
    # existing profile/seeder test).
    assert ProjectProfile(root=".").god_classes == []


def test_god_class_is_flagged(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "big.py").write_text(
        _class("Kitchen", _FLOOR + 2, attrs=4), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    classes = profile.god_classes
    assert classes, "a class with many methods should be flagged"
    entry = classes[0]
    assert set(entry) == {"module", "classname", "methods", "attributes"}
    assert entry["module"] == "app/big.py"
    assert entry["classname"] == "Kitchen"
    assert entry["methods"] >= _FLOOR
    assert entry["methods"] == _FLOOR + 2
    # The distinct ``self.X =`` attributes are counted too.
    assert entry["attributes"] == 4


def test_small_class_is_NOT_flagged(tmp_path: Path):
    # A class comfortably below the method floor stays clean.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "small.py").write_text(
        _class("Tidy", 3, attrs=2), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.god_classes == []


def test_class_just_below_floor_is_NOT_flagged(tmp_path: Path):
    # Exactly one method under the floor stays clean — the floor is a >= bar.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "near.py").write_text(
        _class("Almost", _FLOOR - 1), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.god_classes == []


def test_class_exactly_at_floor_is_flagged(tmp_path: Path):
    # The floor is inclusive (>=), so a class with exactly that many methods
    # is a god-class.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "edge.py").write_text(
        _class("Edge", _FLOOR), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert [c["classname"] for c in profile.god_classes] == ["Edge"]


def test_nested_class_starts_its_own_tally(tmp_path: Path):
    # An OUTER class small at its own top level, but containing an INNER class
    # that itself declares many methods, must NOT be charged the inner's
    # methods — the inner scope owns its own members (and inner classes are not
    # top-level, so they are never scanned). So this whole module flags nothing.
    inner = _class("Inner", _FLOOR + 1)
    indented = "\n".join("    " + ln for ln in inner.splitlines())
    src = (
        "class Outer:\n"
        "    def only(self):\n"
        "        return 1\n"
        f"{indented}\n"
    )
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "wrap.py").write_text(src, encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.god_classes == []


def test_async_methods_count(tmp_path: Path):
    # ``async def`` members count toward the method tally too.
    lines = ["class AsyncHeavy:"]
    for i in range(_FLOOR):
        lines.append(f"    async def m_{i}(self):")
        lines.append(f"        return {i}")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert [c["classname"] for c in profile.god_classes] == ["AsyncHeavy"]
    assert profile.god_classes[0]["methods"] == _FLOOR


def test_empty_project_yields_empty_field(tmp_path: Path):
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.god_classes == []


def test_light_mode_skips_the_scan(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "big.py").write_text(
        _class("Kitchen", _FLOOR + 2), encoding="utf-8")
    # Sanity: the same tree DOES flag under the full (non-light) profile.
    assert ProjectProfiler(str(tmp_path)).profile().god_classes
    profile = ProjectProfiler(str(tmp_path)).profile(light=True)
    assert profile.god_classes == []


def test_fixtures_excluded(tmp_path: Path):
    # A god-class living in a test/fixture tree is throwaway — never a real
    # subject.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_big.py").write_text(
        _class("Kitchen", _FLOOR + 2), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.god_classes == []


def test_field_capped(tmp_path: Path):
    (tmp_path / "app").mkdir()
    for i in range(8):
        (tmp_path / "app" / f"m{i}.py").write_text(
            _class(f"Cls{i}", _FLOOR + 1), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert len(profile.god_classes) <= 5


def test_scan_is_deterministic_and_sorted(tmp_path: Path):
    (tmp_path / "app").mkdir()
    # Two classes of different method count so ordering is observable.
    (tmp_path / "app" / "a.py").write_text(
        _class("Bigger", _FLOOR + 3), encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text(
        _class("Smaller", _FLOOR), encoding="utf-8")
    first = ProjectProfiler(str(tmp_path)).profile().god_classes
    second = ProjectProfiler(str(tmp_path)).profile().god_classes
    assert first == second, "same repo -> identical result"
    # Most methods first, then stable by (module, classname).
    keys = [(-e["methods"], e["module"], e["classname"]) for e in first]
    assert keys == sorted(keys)
    assert first[0]["classname"] == "Bigger"


# --- seeding ----------------------------------------------------------------

def test_seeds_god_class_root_naming_the_class():
    profile = _profile(god_classes=[
        _entry("app/x.py", "Mega", _FLOOR + 1, attributes=7),
    ])
    roots = _god_roots(profile)
    assert len(roots) == 1
    root = roots[0]
    # Subject is ``module::classname`` so it never collides with the module's
    # own idea (mirrors incomplete-protocol's ``module::Class``).
    assert root.subject == "app/x.py::Mega"
    assert "Mega" in root.title
    assert "app/x.py" in root.title
    # Autonomous-39 W3a + the over-claim guard: the title must HONESTLY name the
    # executable step (promote self-free methods to @staticmethod) and NOT
    # over-promise a full decomposition — the responsibility-split stays a design
    # task. So the title states @staticmethod promotion + "design task", never
    # "decompose into collaborators".
    assert "@staticmethod" in root.title
    assert "design task" in root.title
    assert "decompose" not in root.title.lower()
    assert root.source_facts[0].startswith("god-class")


def test_seed_fact_avoids_untested_token():
    # The fact must NOT carry the "untested" token (which would auto-promote it
    # to an executable test idea) — it is a recommend-only design signal.
    profile = _profile(god_classes=[_entry("app/x.py", "Mega", 20)])
    root = _god_roots(profile)[0]
    assert "untested" not in root.source_facts[0]


def test_seed_fact_has_no_leading_magnitude_shape():
    # The fact VALUE must NOT start with "<int> <magnitude>" (e.g. "15 methods")
    # which would inflate it via the magnitude bonus.
    profile = _profile(god_classes=[_entry("app/x.py", "Mega", 20)])
    fact = _god_roots(profile)[0].source_facts[0]
    # The fact value follows the "label: " prefix.
    value = fact.split(": ", 1)[1]
    assert not re.match(r"^\d+\s+\w", value), fact


def test_seed_subject_does_not_collide_with_module_subject():
    profile = _profile(god_classes=[_entry("app/x.py", "Mega", 20)])
    root = _god_roots(profile)[0]
    assert "::" in root.subject
    assert root.subject != "app/x.py"


def test_seeds_at_most_three():
    profile = _profile(god_classes=[
        _entry(f"app/m{i}.py", f"Cls{i}", 16 + i) for i in range(5)
    ])
    assert len(_god_roots(profile)) == 3


def test_degenerate_entry_is_not_seeded():
    # A defensive guard: an entry missing module/classname never seeds a root.
    profile = _profile(god_classes=[{"methods": 20}])
    assert _god_roots(profile) == []


def test_seeding_is_deterministic():
    profile = _profile(god_classes=[
        _entry("app/a.py", "Foo", 18),
        _entry("lib/b.py", "Bar", 16),
    ])
    first = [r.model_dump() for r in _god_roots(profile)]
    second = [r.model_dump() for r in _god_roots(profile)]
    assert first == second
    assert [r["subject"] for r in first] == ["app/a.py::Foo", "lib/b.py::Bar"]


def test_no_field_seeding_is_unchanged():
    empty = _profile()
    populated_default = _profile(god_classes=[])
    a = [r.model_dump() for r in IdeaSeeder().seed(empty)]
    b = [r.model_dump() for r in IdeaSeeder().seed(populated_default)]
    assert a == b
    assert not _god_roots(empty)


def test_root_value_axes_in_unit_interval():
    profile = _profile(god_classes=[_entry("app/x.py", "Mega", 20)])
    root = _god_roots(profile)[0]
    assert 0.0 <= root.value <= 1.0
    assert 0.0 <= root.feasibility <= 1.0
    assert 0.0 <= root.novelty <= 1.0
    # Roots keep novelty == 1.0.
    assert root.novelty == 1.0
    assert root.operator == "root"


# --- permutation hint -------------------------------------------------------

def test_fact_hint_registered():
    assert "god-class" in _FACT_HINTS
    hint = _FACT_HINTS["god-class"].lower()
    # A decompose / split-responsibility hint (the SRP lens).
    assert "decompose" in hint or "split" in hint
    assert "responsibilit" in hint or "cohesive" in hint


# --- action bridge ----------------------------------------------------------

def test_action_is_executable_promote_staticmethod():
    profile = _profile(god_classes=[_entry("app/x.py", "Mega", 20)])
    idea = _god_roots(profile)[0]
    step = IdeaActionBridge().plan_idea(idea)
    # Autonomous-39 W3a: the EXECUTABLE move is promote_staticmethod — promote the
    # class's self-free methods to @staticmethod (a real decoupling that changes no
    # call site). The full responsibility-split stays a DESIGN task, so the
    # description must HONESTLY say so and must NOT claim a decomposition.
    assert step.executable is True
    assert step.action_type == "promote_staticmethod"
    # The subject is "module::Class"; the surfaced target is the own-module rel
    # (the lander strips the suffix), so the step has a real patchable file.
    assert step.target == "app/x.py"
    assert "app/x.py::Mega" in step.description
    assert "@staticmethod" in step.description
    assert "design task" in step.description
    assert "decompose" not in step.description.lower()


# --- roadmap ----------------------------------------------------------------

def test_roadmap_phase_is_evolve():
    profile = _profile(god_classes=[_entry("app/x.py", "Mega", 20)])
    root = _god_roots(profile)[0]
    # A structural decompose / split-responsibilities improvement -> EVOLVE
    # (the same phase as its sibling coordinator god-module signal).
    assert classify_phase(root) == EVOLVE
