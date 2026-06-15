"""Incomplete-protocol signal: pure-AST analysis + the full idea vertical.

`app.engine.completeness.incomplete_protocols` names the SAFE, unambiguous
Python contract gaps (``__eq__`` without ``__hash__``; the sync/async
context-manager pairs); `ProjectProfiler` carries them on
`incomplete_protocols`; the idea engine promotes each into a CONSTRUCTIVE
`incomplete-protocol` root framed as "finish what you started" — recommend-only
(Apex points, it does not auto-write). These tests pin both the conservative
detection (every false-positive guard) AND the seeding vertical end to end:
profile field -> seeder root -> action bridge -> roadmap phase, plus the
invariants (additive/empty, dedup, determinism, recommend-only,
value/feasibility/novelty in [0,1], all-clean -> byte-identical seeding).
"""

from pathlib import Path

from app.engine.completeness import (
    incomplete_protocols,
    render_completeness_markdown,
)
from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_permutation import IdeaSeeder, _FACT_HINTS
from app.engine.idea_roadmap import EVOLVE, classify_phase
from app.tools.project_profile import ProjectProfile, ProjectProfiler


# --- helpers ----------------------------------------------------------------

def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _proto(module="app/money.py", cls="Money", line=12,
           protocol="equality/hash", have="__eq__", missing="__hash__") -> dict:
    return {"module": module, "class": cls, "line": line,
            "protocol": protocol, "have": have, "missing": missing}


def _proto_roots(profile: ProjectProfile):
    return [
        r for r in IdeaSeeder().seed(profile)
        if r.source_facts and r.source_facts[0].startswith("incomplete-protocol")
    ]


def _write(tmp_path: Path, rel: str, body: str) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


# --- analysis: the canonical eq/hash gap ------------------------------------

def test_eq_without_hash_is_flagged(tmp_path: Path):
    _write(tmp_path, "app/money.py",
           "class Money:\n"
           "    def __init__(self, cents):\n        self.cents = cents\n"
           "    def __eq__(self, other):\n        return self.cents == other.cents\n")
    items = incomplete_protocols(str(tmp_path))
    assert len(items) == 1
    it = items[0]
    assert it == {"module": "app/money.py", "class": "Money", "line": 1,
                  "protocol": "equality/hash", "have": "__eq__",
                  "missing": "__hash__"}


def test_eq_with_hash_is_not_flagged(tmp_path: Path):
    _write(tmp_path, "app/m.py",
           "class M:\n"
           "    def __eq__(self, o):\n        return True\n"
           "    def __hash__(self):\n        return 0\n")
    assert incomplete_protocols(str(tmp_path)) == []


def test_dataclass_with_eq_is_not_flagged(tmp_path: Path):
    # @dataclass auto-generates __hash__ (when eq + frozen) / sets it to None;
    # either way the contract is the framework's job, not a gap.
    _write(tmp_path, "app/d.py",
           "from dataclasses import dataclass\n\n"
           "@dataclass\nclass D:\n"
           "    x: int\n"
           "    def __eq__(self, o):\n        return self.x == o.x\n")
    assert incomplete_protocols(str(tmp_path)) == []


def test_dotted_dataclass_decorator_is_not_flagged(tmp_path: Path):
    _write(tmp_path, "app/d.py",
           "import dataclasses\n\n"
           "@dataclasses.dataclass\nclass D:\n"
           "    x: int\n"
           "    def __eq__(self, o):\n        return self.x == o.x\n")
    assert incomplete_protocols(str(tmp_path)) == []


def test_attrs_decorator_is_not_flagged(tmp_path: Path):
    _write(tmp_path, "app/a.py",
           "import attr\n\n"
           "@attr.s\nclass A:\n"
           "    def __eq__(self, o):\n        return True\n")
    assert incomplete_protocols(str(tmp_path)) == []


def test_hash_none_is_not_flagged(tmp_path: Path):
    # __hash__ = None is the deliberate "unhashable" idiom — author handled it.
    _write(tmp_path, "app/u.py",
           "class U:\n"
           "    def __eq__(self, o):\n        return True\n"
           "    __hash__ = None\n")
    assert incomplete_protocols(str(tmp_path)) == []


def test_hash_annotated_assign_is_not_flagged(tmp_path: Path):
    _write(tmp_path, "app/u.py",
           "from typing import Optional, Callable\n"
           "class U:\n"
           "    __hash__: Optional[Callable] = None\n"
           "    def __eq__(self, o):\n        return True\n")
    assert incomplete_protocols(str(tmp_path)) == []


def test_subclass_with_non_object_base_is_not_flagged(tmp_path: Path):
    # A non-object base may supply __hash__/__eq__ we can't see statically.
    _write(tmp_path, "app/s.py",
           "class Base:\n    pass\n\n"
           "class Sub(Base):\n"
           "    def __eq__(self, o):\n        return True\n")
    items = incomplete_protocols(str(tmp_path))
    assert items == []


def test_explicit_object_base_is_flagged(tmp_path: Path):
    _write(tmp_path, "app/o.py",
           "class O(object):\n"
           "    def __eq__(self, o):\n        return True\n")
    items = incomplete_protocols(str(tmp_path))
    assert len(items) == 1 and items[0]["class"] == "O"


def test_metaclass_keyword_base_is_not_flagged(tmp_path: Path):
    _write(tmp_path, "app/k.py",
           "class K(metaclass=type):\n"
           "    def __eq__(self, o):\n        return True\n")
    assert incomplete_protocols(str(tmp_path)) == []


# --- analysis: context managers ---------------------------------------------

def test_enter_without_exit_is_flagged(tmp_path: Path):
    _write(tmp_path, "app/cm.py",
           "class CM:\n"
           "    def __enter__(self):\n        return self\n")
    items = incomplete_protocols(str(tmp_path))
    assert len(items) == 1
    assert items[0]["protocol"] == "context-manager"
    assert items[0]["have"] == "__enter__"
    assert items[0]["missing"] == "__exit__"


def test_exit_without_enter_is_flagged(tmp_path: Path):
    _write(tmp_path, "app/cm.py",
           "class CM:\n"
           "    def __exit__(self, *a):\n        return False\n")
    items = incomplete_protocols(str(tmp_path))
    assert len(items) == 1
    assert items[0]["have"] == "__exit__" and items[0]["missing"] == "__enter__"


def test_complete_context_manager_is_not_flagged(tmp_path: Path):
    _write(tmp_path, "app/cm.py",
           "class CM:\n"
           "    def __enter__(self):\n        return self\n"
           "    def __exit__(self, *a):\n        return False\n")
    assert incomplete_protocols(str(tmp_path)) == []


def test_aenter_without_aexit_is_flagged(tmp_path: Path):
    _write(tmp_path, "app/acm.py",
           "class ACM:\n"
           "    async def __aenter__(self):\n        return self\n")
    items = incomplete_protocols(str(tmp_path))
    assert len(items) == 1
    assert items[0]["protocol"] == "async-context-manager"
    assert items[0]["missing"] == "__aexit__"


def test_complete_async_context_manager_is_not_flagged(tmp_path: Path):
    _write(tmp_path, "app/acm.py",
           "class ACM:\n"
           "    async def __aenter__(self):\n        return self\n"
           "    async def __aexit__(self, *a):\n        return False\n")
    assert incomplete_protocols(str(tmp_path)) == []


# --- analysis: structure / scope --------------------------------------------

def test_nested_class_is_walked(tmp_path: Path):
    _write(tmp_path, "app/n.py",
           "class Outer:\n"
           "    class Inner:\n"
           "        def __eq__(self, o):\n            return True\n")
    items = incomplete_protocols(str(tmp_path))
    assert len(items) == 1 and items[0]["class"] == "Inner"


def test_test_and_example_files_are_excluded(tmp_path: Path):
    body = "class C:\n    def __eq__(self, o):\n        return True\n"
    _write(tmp_path, "tests/test_thing.py", body)
    _write(tmp_path, "examples/demo.py", body)
    _write(tmp_path, "app/foo_test.py", body)
    assert incomplete_protocols(str(tmp_path)) == []


def test_skip_dirs_are_excluded(tmp_path: Path):
    body = "class C:\n    def __eq__(self, o):\n        return True\n"
    _write(tmp_path, ".venv/lib/pkg.py", body)
    _write(tmp_path, "node_modules/m.py", body)
    assert incomplete_protocols(str(tmp_path)) == []


def test_syntax_error_file_is_skipped(tmp_path: Path):
    _write(tmp_path, "app/broken.py", "class C(:\n  def __eq__(self): pass\n")
    assert incomplete_protocols(str(tmp_path)) == []


def test_all_clean_repo_yields_empty(tmp_path: Path):
    _write(tmp_path, "app/a.py", "class A:\n    pass\n")
    _write(tmp_path, "app/b.py",
           "class B:\n"
           "    def __eq__(self, o):\n        return True\n"
           "    def __hash__(self):\n        return 0\n")
    assert incomplete_protocols(str(tmp_path)) == []


def test_results_are_sorted_and_deterministic(tmp_path: Path):
    _write(tmp_path, "app/z.py",
           "class Z:\n    def __enter__(self):\n        return self\n")
    _write(tmp_path, "app/a.py",
           "class A:\n    def __eq__(self, o):\n        return True\n")
    first = incomplete_protocols(str(tmp_path))
    second = incomplete_protocols(str(tmp_path))
    assert first == second
    assert [it["module"] for it in first] == ["app/a.py", "app/z.py"]


def test_eq_hash_takes_precedence_over_context_manager(tmp_path: Path):
    # A class with BOTH gaps reports the canonical eq/hash one (one gap/class).
    _write(tmp_path, "app/both.py",
           "class C:\n"
           "    def __eq__(self, o):\n        return True\n"
           "    def __enter__(self):\n        return self\n")
    items = incomplete_protocols(str(tmp_path))
    assert len(items) == 1 and items[0]["protocol"] == "equality/hash"


# --- render -----------------------------------------------------------------

def test_render_empty_is_empty_string():
    assert render_completeness_markdown([]) == ""


def test_render_names_class_and_gap():
    md = render_completeness_markdown([_proto()])
    assert "`Money`" in md
    assert "app/money.py:12" in md
    assert "__eq__" in md and "__hash__" in md


# --- profile field ----------------------------------------------------------

def test_field_is_additive_and_defaults_empty():
    assert ProjectProfile(root=".").incomplete_protocols == []


def test_profiler_populates_field(tmp_path: Path):
    _write(tmp_path, "app/money.py",
           "class Money:\n    def __eq__(self, o):\n        return True\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert any(p["class"] == "Money" and p["missing"] == "__hash__"
               for p in profile.incomplete_protocols)


def test_profiler_light_mode_skips_the_scan(tmp_path: Path):
    # The constructive scan is gated out of the LIGHT path: the grade/ascend
    # re-grade never reads incomplete_protocols, and the light path already
    # parses every file once, so a second whole-repo AST walk there is wasted.
    # The idea engine profiles with light=False, where the signal is populated.
    _write(tmp_path, "app/money.py",
           "class Money:\n    def __eq__(self, o):\n        return True\n")
    light = ProjectProfiler(str(tmp_path)).profile(light=True)
    assert light.incomplete_protocols == []
    full = ProjectProfiler(str(tmp_path)).profile()
    assert any(p["class"] == "Money" for p in full.incomplete_protocols)


def test_profiler_clean_repo_yields_empty_field(tmp_path: Path):
    _write(tmp_path, "app/a.py", "class A:\n    pass\n")
    profile = ProjectProfiler(str(tmp_path)).profile()
    assert profile.incomplete_protocols == []


# --- seeding ----------------------------------------------------------------

def test_seeds_incomplete_protocol_root():
    profile = _profile(incomplete_protocols=[_proto()])
    roots = _proto_roots(profile)
    assert len(roots) == 1
    root = roots[0]
    assert root.subject == "app/money.py::Money"
    # The example title from the spec.
    assert root.title == (
        "Complete the equality/hash protocol on `Money` (app/money.py:12) — "
        "defines __eq__ but no __hash__ (instances can't be set/dict keys)"
    )
    assert root.source_facts[0].startswith("incomplete-protocol")


def test_seed_fact_value_avoids_untested_token():
    # "untested" in the fact would auto-promote it to an executable test stub.
    profile = _profile(incomplete_protocols=[_proto()])
    root = _proto_roots(profile)[0]
    assert "untested" not in root.source_facts[0].lower()


def test_seed_context_manager_title():
    profile = _profile(incomplete_protocols=[
        _proto(module="app/res.py", cls="Res", line=4,
               protocol="context-manager", have="__enter__", missing="__exit__"),
    ])
    root = _proto_roots(profile)[0]
    assert "context-manager protocol on `Res` (app/res.py:4)" in root.title
    assert "with` block" in root.title


def test_all_clean_seeding_is_byte_identical():
    empty = _profile()
    populated_default = _profile(incomplete_protocols=[])
    a = [r.model_dump() for r in IdeaSeeder().seed(empty)]
    b = [r.model_dump() for r in IdeaSeeder().seed(populated_default)]
    assert a == b
    assert not _proto_roots(empty)


def test_seeds_dedup_on_subject():
    profile = _profile(incomplete_protocols=[_proto(), _proto()])
    assert len(_proto_roots(profile)) == 1


def test_seeds_at_most_three():
    profile = _profile(incomplete_protocols=[
        _proto(module=f"app/m{i}.py", cls=f"C{i}") for i in range(5)
    ])
    assert len(_proto_roots(profile)) == 3


def test_seeding_is_deterministic():
    profile = _profile(incomplete_protocols=[
        _proto(module="app/a.py", cls="A"),
        _proto(module="app/b.py", cls="B", protocol="context-manager",
               have="__enter__", missing="__exit__"),
    ])
    first = [r.model_dump() for r in _proto_roots(profile)]
    second = [r.model_dump() for r in _proto_roots(profile)]
    assert first == second
    assert [r["subject"] for r in first] == ["app/a.py::A", "app/b.py::B"]


def test_root_value_axes_in_unit_interval():
    profile = _profile(incomplete_protocols=[_proto()])
    root = _proto_roots(profile)[0]
    assert 0.0 <= root.value <= 1.0
    assert 0.0 <= root.feasibility <= 1.0
    assert 0.0 <= root.novelty <= 1.0
    assert root.novelty == 1.0
    assert root.operator == "root"


# --- permutation hint -------------------------------------------------------

def test_fact_hint_registered():
    assert "incomplete-protocol" in _FACT_HINTS
    hint = _FACT_HINTS["incomplete-protocol"].lower()
    assert "complete" in hint or "finish" in hint


# --- action bridge: recommend-only ------------------------------------------

def test_action_is_recommend_only():
    profile = _profile(incomplete_protocols=[_proto()])
    idea = _proto_roots(profile)[0]
    step = IdeaActionBridge().plan_idea(idea)
    # Recommend-only EVEN THOUGH the module::Class subject carries a real file
    # path (app/money.py): Apex points at the gap, it does not auto-write it.
    assert step.executable is False
    assert step.action_type == "design_task"
    assert "app/money.py::Money" in step.description


def test_action_recommend_only_for_context_manager():
    profile = _profile(incomplete_protocols=[
        _proto(module="app/res.py", cls="Res", protocol="context-manager",
               have="__enter__", missing="__exit__"),
    ])
    idea = _proto_roots(profile)[0]
    step = IdeaActionBridge().plan_idea(idea)
    assert step.executable is False


# --- roadmap phase ----------------------------------------------------------

def test_classified_as_evolve():
    profile = _profile(incomplete_protocols=[_proto()])
    idea = _proto_roots(profile)[0]
    # Constructive "finish what you started" — EVOLVE, not a Stabilize/test-first
    # target.
    assert classify_phase(idea) == EVOLVE
