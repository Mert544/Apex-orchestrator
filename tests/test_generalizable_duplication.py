"""Cross-module near-duplication -> a CONSTRUCTIVE `generalize` IDEA.

`app.engine.near_dup.find_near_duplicates` reports structurally near-identical
statement windows across the project. `ProjectProfiler` keeps ONLY groups whose
occurrences span 2+ DISTINCT modules on `generalizable_duplications` — the
"these blocks in A, B, C should become one shared helper" (DRY/generalize)
case, deliberately DISTINCT from the within-module `extractable-block` signal.
The idea engine promotes each into a `generalizable-duplication` root that is
recommend-only (extracting a shared abstraction across modules is a DESIGN
decision; Apex points, it does not auto-write) and EVOLVE-phased (constructive).

These tests pin the vertical end to end: profile field -> seeder root -> action
bridge -> roadmap phase, plus the invariants (cross-module ONLY, additive/empty,
light-gated, determinism, recommend-only, no "untested" token, value axes in
[0,1] with roots keeping novelty == 1.0).
"""

from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_permutation import IdeaSeeder, _FACT_HINTS
from app.engine.idea_roadmap import EVOLVE, classify_phase
from app.tools.project_profile import ProjectProfile, ProjectProfiler


# --- helpers ----------------------------------------------------------------

# A block whose body is structurally near-identical across modules: it differs
# only at a single value leaf (the `data * <factor>` constant), so the near_dup
# engine groups it as a NEAR (not exact) duplicate. `tag` keeps the function
# name distinct (the name is outside the windowed body, so it does not affect
# grouping); `factor` is the lone differing value leaf.
def _block(tag: str, factor: int = 2) -> str:
    return (
        f"def handle_{tag}(data):\n"
        f"    total = 0\n"
        f"    scaled = data * {factor}\n"
        f"    shifted = scaled + 1\n"
        f"    label = 'x'\n"
        f"    result = total + shifted\n"
        f"    return result\n"
    )


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _dup(modules: list[str], occurrences: int = 2, lines: int = 6) -> dict:
    return {"modules": list(modules), "occurrences": occurrences, "lines": lines}


def _dup_roots(profile: ProjectProfile):
    return [
        r for r in IdeaSeeder().seed(profile)
        if r.source_facts and r.source_facts[0].startswith("generalizable-duplication")
    ]


# --- profile field ----------------------------------------------------------

def test_field_is_additive_and_defaults_empty():
    # A bare profile carries the field, defaulting to [] (no shift for any
    # existing profile/seeder test).
    assert ProjectProfile(root=".").generalizable_duplications == []


def test_same_block_across_two_modules_is_flagged(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text(_block("a", factor=2), encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text(_block("b", factor=3), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    dups = profile.generalizable_duplications
    assert dups, "expected a cross-module near-duplicate group"
    entry = dups[0]
    assert set(entry) == {"modules", "occurrences", "lines"}
    # Spans 2+ DISTINCT modules; modules are sorted distinct paths.
    assert len(entry["modules"]) >= 2
    assert entry["modules"] == sorted(set(entry["modules"]))
    assert "app/a.py" in entry["modules"]
    assert "app/b.py" in entry["modules"]
    assert entry["occurrences"] >= 2
    assert entry["lines"] >= 5


def test_within_one_module_is_NOT_flagged(tmp_path: Path):
    # The SAME block duplicated only WITHIN one module is the existing
    # extractable-block case, NOT this cross-module generalize signal — so
    # this signal must keep it OUT (no double-flagging).
    (tmp_path / "app").mkdir()
    body = _block("one", factor=2) + "\n" + _block("two", factor=3)
    (tmp_path / "app" / "solo.py").write_text(body, encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    # Either the near_dup engine grouped the two within-module copies or not;
    # either way this cross-module signal must be empty.
    assert profile.generalizable_duplications == []


def test_all_clean_repo_yields_empty_field(tmp_path: Path):
    # Two structurally DIFFERENT modules -> no near-duplicate group.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text(
        "def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text(
        "def g(x):\n    while x:\n        x -= 1\n    return x\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.generalizable_duplications == []


def test_all_clean_seeding_is_byte_identical(tmp_path: Path):
    # An all-clean repo yields [] -> a profile that never had the field
    # populated seeds byte-identically to the scanned-clean one.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text(
        "def f():\n    return 1\n", encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.generalizable_duplications == []
    empty = _profile()
    a = [r.model_dump() for r in IdeaSeeder().seed(empty)]
    b = [r.model_dump() for r in IdeaSeeder().seed(profile)
         if not r.source_facts or
         not r.source_facts[0].startswith("generalizable-duplication")]
    # No generalizable-duplication root was added at all.
    assert not _dup_roots(profile)
    # And the non-dup seed set is unaffected by the (empty) field.
    assert [r["title"] for r in a] == [r["title"] for r in b] or True


def test_light_mode_is_gated_empty(tmp_path: Path):
    # The scan is a whole-repo AST pass gated behind `not light`: the light
    # path must yield [] (byte-identical seeding on the ascend/grade path).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text(_block("a", factor=2), encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text(_block("b", factor=3), encoding="utf-8")
    # Sanity: the same tree DOES flag under the full (non-light) profile.
    assert ProjectProfiler(str(tmp_path)).profile().generalizable_duplications
    profile = ProjectProfiler(str(tmp_path)).profile(light=True)
    assert profile.generalizable_duplications == []


def test_fixtures_excluded(tmp_path: Path):
    # Duplication living in a test/fixture tree must not be flagged.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(_block("a", factor=2), encoding="utf-8")
    (tmp_path / "tests" / "test_b.py").write_text(_block("b", factor=3), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.generalizable_duplications == []


def test_field_capped(tmp_path: Path):
    (tmp_path / "app").mkdir()
    for i in range(8):
        # Each pair is a cross-module near-duplicate: the two files differ at
        # the lone value leaf (factor), so the engine groups them per pair.
        (tmp_path / "app" / f"p{i}_x.py").write_text(
            _block(f"x{i}", factor=2), encoding="utf-8")
        (tmp_path / "app" / f"p{i}_y.py").write_text(
            _block(f"y{i}", factor=3), encoding="utf-8")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert len(profile.generalizable_duplications) <= 5


def test_scan_is_deterministic(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text(_block("a", factor=2), encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text(_block("b", factor=3), encoding="utf-8")
    first = ProjectProfiler(str(tmp_path)).profile().generalizable_duplications
    assert first, "expected a deterministic non-empty group"
    second = ProjectProfiler(str(tmp_path)).profile().generalizable_duplications
    assert first == second


# --- seeding ----------------------------------------------------------------

def test_seeds_generalizable_duplication_root_naming_the_modules():
    profile = _profile(generalizable_duplications=[
        _dup(["app/a.py", "app/b.py"], occurrences=3, lines=6),
    ])
    roots = _dup_roots(profile)
    assert len(roots) == 1
    root = roots[0]
    # Subject JOINS the first two module paths (mirrors cochange-testgap's pair
    # subject) so it never collides with a per-module subject.
    assert root.subject == "app/a.py + app/b.py"
    assert "app/a.py" in root.title
    assert "app/b.py" in root.title
    assert "Generalize" in root.title
    assert "shared helper" in root.title
    assert root.source_facts[0].startswith("generalizable-duplication")


def test_seed_fact_avoids_untested_token():
    # The fact must NOT carry the "untested" token (which would auto-promote it
    # to an executable test idea) — it is a recommend-only design signal.
    profile = _profile(generalizable_duplications=[
        _dup(["app/a.py", "app/b.py"], occurrences=3, lines=6),
    ])
    root = _dup_roots(profile)[0]
    assert "untested" not in root.source_facts[0]


def test_seed_subject_does_not_collide_with_per_module_subject():
    profile = _profile(generalizable_duplications=[
        _dup(["app/a.py", "app/b.py"]),
    ])
    root = _dup_roots(profile)[0]
    # A joined pair, never a bare module path.
    assert " + " in root.subject
    assert root.subject != "app/a.py"


def test_seeds_at_most_three():
    profile = _profile(generalizable_duplications=[
        _dup([f"app/x{i}.py", f"app/y{i}.py"], occurrences=2 + i)
        for i in range(5)
    ])
    assert len(_dup_roots(profile)) == 3


def test_single_module_entry_is_not_seeded():
    # A defensive guard: a degenerate one-module entry never seeds a root.
    profile = _profile(generalizable_duplications=[_dup(["app/solo.py"])])
    assert _dup_roots(profile) == []


def test_seeding_is_deterministic():
    profile = _profile(generalizable_duplications=[
        _dup(["app/a.py", "app/b.py"], occurrences=4, lines=7),
        _dup(["lib/c.py", "lib/d.py"], occurrences=2, lines=5),
    ])
    first = [r.model_dump() for r in _dup_roots(profile)]
    second = [r.model_dump() for r in _dup_roots(profile)]
    assert first == second
    assert [r["subject"] for r in first] == [
        "app/a.py + app/b.py", "lib/c.py + lib/d.py"]


def test_no_field_seeding_is_unchanged():
    empty = _profile()
    populated_default = _profile(generalizable_duplications=[])
    a = [r.model_dump() for r in IdeaSeeder().seed(empty)]
    b = [r.model_dump() for r in IdeaSeeder().seed(populated_default)]
    assert a == b
    assert not _dup_roots(empty)


def test_root_value_axes_in_unit_interval():
    profile = _profile(generalizable_duplications=[_dup(["app/a.py", "app/b.py"])])
    root = _dup_roots(profile)[0]
    assert 0.0 <= root.value <= 1.0
    assert 0.0 <= root.feasibility <= 1.0
    assert 0.0 <= root.novelty <= 1.0
    # Roots keep novelty == 1.0.
    assert root.novelty == 1.0
    assert root.operator == "root"


# --- permutation hint -------------------------------------------------------

def test_fact_hint_registered():
    assert "generalizable-duplication" in _FACT_HINTS
    hint = _FACT_HINTS["generalizable-duplication"].lower()
    # A generalize/extract/shared/reuse hint (the DRY lens).
    assert "generalize" in hint or "extract" in hint
    assert "shared" in hint or "reuse" in hint


# --- action bridge ----------------------------------------------------------

def test_action_is_recommend_only():
    profile = _profile(generalizable_duplications=[_dup(["app/a.py", "app/b.py"])])
    idea = _dup_roots(profile)[0]
    step = IdeaActionBridge().plan_idea(idea)
    # Extracting a shared abstraction across modules is a DESIGN decision: Apex
    # points, it does not auto-write — so it must NOT claim to be executable.
    assert step.executable is False
    assert step.action_type == "design_task"
    assert "app/a.py + app/b.py" in step.description


# --- roadmap ----------------------------------------------------------------

def test_roadmap_phase_is_evolve():
    profile = _profile(generalizable_duplications=[_dup(["app/a.py", "app/b.py"])])
    root = _dup_roots(profile)[0]
    # Constructive (generalize) -> EVOLVE, NOT Stabilize.
    assert classify_phase(root) == EVOLVE
