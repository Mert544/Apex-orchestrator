"""Autonomous-39 W3a: ``promote-staticmethod`` — a NEW develop objective AND the
HONEST god-class executable flip.

A method that never touches ``self`` is not really an instance method. Promoting
it to ``@staticmethod`` (and dropping the now-unused ``self``) makes the coupling
surface honest WITHOUT changing any call site — a ``@staticmethod`` is still a
class attribute, so ``self.m()`` / ``Cls.m()`` / ``inst.m()`` all keep resolving.
This is the SAFE structural move available on a METHOD-BAG god-class: it REDUCES
coupling but does NOT reduce the method count or split responsibilities — the full
decomposition stays a DESIGN task.

THE OVER-CLAIM GUARD (the load-bearing honesty): the god-class fact row and the
seeder title must HONESTLY state the executable action promotes self-free methods
to ``@staticmethod`` AND that the full responsibility-split into cohesive
collaborators stays a design task — they must NEVER claim the executable action
"decomposes into collaborators". A god-class with no self-free method is an HONEST
no-op (the lander finds nothing eligible, never a fabricated decomposition).

These tests lock:
  * the transform's before/after + behaviour preservation (every call form still
    resolves after promotion);
  * ONE refusal-set test per rule (1–10) → an empty no-op, no spurious blocker;
  * the delegated ``::Class``-strip lander path, an honest no-op, and a
    planted-regression rollback through ``apply_rename(impact_scope=True)``;
  * the registry / manifest / soundness / count-pin wiring for the new objective;
  * THE HONEST-TEXT guard on the god-class action description and seeder title.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge, _FACT_ACTIONS
from app.execution.promote_staticmethods import (
    plan_promote_staticmethods,
    promotable_methods,
)
from app.models.idea import IdeaNode


# --- helpers ----------------------------------------------------------------

def _project(root: Path, module_rel: str, source: str,
             test_body: str | None = None) -> None:
    """A minimal importable project carrying ``source`` at ``module_rel``."""
    (root / "app").mkdir(exist_ok=True)
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / module_rel).parent.mkdir(parents=True, exist_ok=True)
    (root / module_rel).write_text(source, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    if test_body is not None:
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "test_m.py").write_text(test_body, encoding="utf-8")


def _run(source: str) -> dict:
    """Exec ``source`` in a fresh namespace and return it."""
    ns: dict = {}
    exec(compile(source, "<rewritten>", "exec"), ns)
    return ns


def _decorators_of(source: str, cls: str, method: str) -> list[str]:
    """The decorator NAMES on ``cls.method`` in ``source`` (``@staticmethod`` ->
    ``"staticmethod"``), so a test can prove the promotion landed."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for stmt in node.body:
                if (isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and stmt.name == method):
                    return [d.id for d in stmt.decorator_list
                            if isinstance(d, ast.Name)]
    raise AssertionError(f"{cls}.{method} not found")


def _god_idea(subject: str) -> IdeaNode:
    """A ``god-class`` root, exactly as ``idea_seeder._seed_god_classes`` emits it:
    a ``"<module_rel>::<Class>"`` subject and the fact label on
    ``source_facts[0]`` (``_root_action`` reads ``fact.split(":")[0]``)."""
    return IdeaNode(
        id="n", title=f"Decouple the god-class `{subject}`",
        subject=subject, operator="root",
        source_facts=[f"god-class: {subject} carries many responsibilities — "
                      f"self-free methods are a @staticmethod decoupling candidate"],
    )


# A plain method-bag class: a self-free ``helper`` (PROMOTABLE) and a self-using
# ``bound`` (REFUSED, rule 1). ``__init__`` is a dunder (refused, rule 4).
_BAG = (
    "class Bag:\n"
    "    def __init__(self, n):\n"
    "        self.n = n\n"
    "    def helper(self, x):\n"
    "        return x + 1\n"
    "    def bound(self, y):\n"
    "        return self.n + y\n"
)


# === 1. before / after + behaviour preservation =============================

def test_promotes_self_free_method_gains_staticmethod_drops_self(tmp_path: Path):
    _project(tmp_path, "app/m.py", _BAG)
    plan = plan_promote_staticmethods(str(tmp_path), "app/m.py")
    assert plan.new_contents and not plan.blockers
    after = plan.new_contents["app/m.py"]
    ast.parse(after)  # the whole module still parses (the re-parse guard held)
    # ``helper`` gained @staticmethod and lost ``self``.
    assert "    @staticmethod\n    def helper(x):\n" in after
    assert _decorators_of(after, "Bag", "helper") == ["staticmethod"]
    # ``bound`` (uses self) and ``__init__`` (dunder) are untouched.
    assert _decorators_of(after, "Bag", "bound") == []
    assert "def bound(self, y):" in after
    assert "def __init__(self, n):" in after
    assert promotable_methods(str(tmp_path), "app/m.py") == ["helper"]
    assert plan.edits_by_file["app/m.py"] == 1


def test_sole_self_param_becomes_empty_parens(tmp_path: Path):
    _project(tmp_path, "app/m.py",
             "class C:\n    def ping(self):\n        return 7\n")
    after = plan_promote_staticmethods(str(tmp_path), "app/m.py").new_contents["app/m.py"]
    assert "    @staticmethod\n    def ping():\n" in after
    ast.parse(after)


def test_call_forms_all_resolve_after_promotion(tmp_path: Path):
    # The whole safety point: a @staticmethod is still a class attribute, so
    # self.m() / Cls.m() / inst.m() ALL keep resolving with the same arguments.
    src = (
        "class C:\n"
        "    def __init__(self):\n"
        "        self.k = 100\n"
        "    def free(self, x):\n"
        "        return x * 2\n"
        "    def via_self(self, x):\n"
        "        return self.free(x) + self.k\n"
    )
    _project(tmp_path, "app/m.py", src)
    after = plan_promote_staticmethods(str(tmp_path), "app/m.py").new_contents["app/m.py"]
    # ``free`` was promoted; ``via_self`` calls ``self.free`` and reads ``self.k``
    # so it stays a bound method.
    assert _decorators_of(after, "C", "free") == ["staticmethod"]
    assert _decorators_of(after, "C", "via_self") == []
    ns = _run(after)
    C = ns["C"]
    inst = C()
    assert C.free(5) == 10          # Cls.m()
    assert inst.free(5) == 10       # inst.m()
    assert inst.via_self(5) == 110  # self.m() inside a method still resolves


def test_idempotent_second_run_is_noop(tmp_path: Path):
    _project(tmp_path, "app/m.py", _BAG)
    after = plan_promote_staticmethods(str(tmp_path), "app/m.py").new_contents["app/m.py"]
    # A second run sees the @staticmethod it landed and refuses (rule 2) — a
    # byte-identical no-op.
    _project(tmp_path, "app/m.py", after)
    assert not plan_promote_staticmethods(str(tmp_path), "app/m.py").new_contents


def test_promotes_several_methods_in_one_module(tmp_path: Path):
    # The lander runs over the MODULE, so it promotes every eligible self-free
    # method (broader but safe — suite-gated upstream).
    src = (
        "class C:\n"
        "    def a(self, x):\n"
        "        return x\n"
        "    def b(self, y):\n"
        "        return y\n"
    )
    _project(tmp_path, "app/m.py", src)
    assert promotable_methods(str(tmp_path), "app/m.py") == ["a", "b"]


# === 2. ONE refusal-set test per rule (→ empty no-op, no spurious blocker) ===

def _refuses(tmp_path: Path, src: str, rel: str = "app/m.py",
             extra: dict[str, str] | None = None) -> None:
    """Assert ``plan_promote_staticmethods`` is an empty no-op on ``src`` (no
    promotion AND no blocker — a clean refusal, never a guess). ``extra`` is a
    ``{relative_path: source}`` map of additional project files (for the
    cross-file rules 7 and 9)."""
    _project(tmp_path, rel, src)
    for extra_rel, extra_src in (extra or {}).items():
        path = tmp_path / extra_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(extra_src, encoding="utf-8")
    plan = plan_promote_staticmethods(str(tmp_path), rel)
    assert not plan.new_contents, plan.new_contents
    assert not plan.blockers, plan.blockers


def test_rule1_refuses_uses_self(tmp_path: Path):
    _refuses(tmp_path,
             "class C:\n    def m(self, x):\n        return self.x + x\n")


def test_rule2_refuses_already_staticmethod(tmp_path: Path):
    _refuses(tmp_path,
             "class C:\n    @staticmethod\n    def m(x):\n        return x\n")


def test_rule2_refuses_already_classmethod(tmp_path: Path):
    _refuses(tmp_path,
             "class C:\n    @classmethod\n    def m(cls, x):\n        return x\n")


def test_rule3_refuses_any_decorator(tmp_path: Path):
    # A @property has no ``self`` use here, but ANY decorator can bind / wrap, so
    # it is refused outright.
    _refuses(tmp_path,
             "class C:\n    @property\n    def m(self):\n        return 1\n")


def test_rule4_refuses_dunder(tmp_path: Path):
    # ``__lt__`` does not touch self but is a dunder (called bound by protocol).
    _refuses(tmp_path,
             "class C:\n    def __lt__(self, o):\n        return True\n")


def test_rule5_refuses_first_param_not_self(tmp_path: Path):
    # A ``cls``-first method (not decorated @classmethod) is not a droppable-self
    # instance method.
    _refuses(tmp_path,
             "class C:\n    def m(cls, x):\n        return x\n")


def test_rule5_refuses_zero_params(tmp_path: Path):
    _refuses(tmp_path,
             "class C:\n    def m():\n        return 1\n")


def test_rule6_refuses_uses_super(tmp_path: Path):
    # ``super`` appears even though ``self`` does not — bound-method machinery.
    _refuses(tmp_path,
             "class C:\n    def m(self, x):\n        return super\n")


def test_rule7_refuses_name_defined_in_two_classes(tmp_path: Path):
    # ``shared`` is defined by TWO classes in the project → a possible override /
    # MRO participant, refuse (the heavy hitter).
    _refuses(tmp_path,
             "class A:\n    def shared(self, x):\n        return x\n",
             extra={"app/other.py": "class B:\n    def shared(self, z):\n        return z\n"})


def test_rule8_refuses_non_top_level_class(tmp_path: Path):
    # A class nested inside a function is not top-level — out of scope.
    _refuses(tmp_path,
             "def make():\n"
             "    class Inner:\n"
             "        def m(self, x):\n"
             "            return x\n"
             "    return Inner\n")


def test_rule9_refuses_name_as_string_literal_anywhere(tmp_path: Path):
    # ``pluck`` appears as a bare string literal (a getattr target) elsewhere in the
    # repo → a dynamic reference static analysis can't follow, refuse.
    _refuses(tmp_path,
             "class C:\n    def pluck(self, x):\n        return x\n",
             extra={"app/use.py": "def f(o):\n    return getattr(o, 'pluck')\n"})


def test_rule10_refuses_test_file(tmp_path: Path):
    # Apex never edits the suite it is gated by.
    _project(tmp_path, "tests/test_x.py", _BAG)
    plan = plan_promote_staticmethods(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_rule10_refuses_non_library_script(tmp_path: Path):
    # A packaging / config script nobody imports as an API (here ``setup.py``).
    _project(tmp_path, "setup.py", _BAG)
    plan = plan_promote_staticmethods(str(tmp_path), "setup.py")
    assert not plan.new_contents and not plan.blockers


def test_unparseable_module_records_blocker_no_write(tmp_path: Path):
    _project(tmp_path, "app/m.py", "class C:\n    def m(self) return\n")
    plan = plan_promote_staticmethods(str(tmp_path), "app/m.py")
    assert not plan.new_contents
    assert plan.blockers  # the parse failure is disclosed, never a silent guess


# === 3. the flip itself: the god-class fact row is now executable ===========

def test_fact_action_is_executable_promote_staticmethod():
    action_type, _desc, executable = _FACT_ACTIONS["god-class"]
    assert action_type == "promote_staticmethod"
    assert executable is True


def test_plan_idea_surfaces_executable_promotion():
    step = IdeaActionBridge().plan_idea(_god_idea("app/m.py::Bag"))
    assert step.action_type == "promote_staticmethod"
    assert step.executable is True
    # The subject is "module::Class"; the surfaced target is the own-module rel.
    assert step.target == "app/m.py"
    assert "app/m.py::Bag" in step.description


def test_promote_staticmethod_is_registered_delegated():
    assert "promote_staticmethod" in IdeaActionBridge._DELEGATED_SYNTHESIS
    assert "promote_staticmethod" in IdeaActionBridge._DELEGATED_ACTIONS
    lander_name, reason = IdeaActionBridge._DELEGATED_SYNTHESIS["promote_staticmethod"]
    assert lander_name == "_plan_promote_staticmethod_lander"
    assert "no self-free method" in reason
    # _step_targets must recognise it as a real transform objective.
    assert "promote_staticmethod" in IdeaActionBridge._ACTION_STRATEGY


# === 4. the delegated lander: ::Class strip, honest no-op, rollback =========

def test_lander_strips_class_suffix_to_module_rel(tmp_path: Path):
    _project(tmp_path, "app/m.py", _BAG)
    lander = IdeaActionBridge._plan_promote_staticmethod_lander()
    via_subject = lander(str(tmp_path), "app/m.py::Bag")
    via_module = lander(str(tmp_path), "app/m.py")
    assert via_subject.new_contents == via_module.new_contents
    assert via_module.new_contents  # the eligible module promotes


def test_lander_honest_noop_when_no_self_free_method(tmp_path: Path):
    # A class whose EVERY method touches self has no self-free method ⇒ an HONEST
    # no-op (never a fabricated decomposition).
    src = (
        "class C:\n"
        "    def __init__(self, n):\n"
        "        self.n = n\n"
        "    def a(self, x):\n"
        "        return self.n + x\n"
        "    def b(self, y):\n"
        "        return self.n * y\n"
    )
    _project(tmp_path, "app/c.py", src)
    plan = IdeaActionBridge._plan_promote_staticmethod_lander()(
        str(tmp_path), "app/c.py::C")
    assert not plan.new_contents


def test_lander_missing_target_is_empty_noop(tmp_path: Path):
    _project(tmp_path, "app/m.py", _BAG)
    plan = IdeaActionBridge._plan_promote_staticmethod_lander()(
        str(tmp_path), "app/absent.py::Nope")
    assert not plan.new_contents


def test_applies_and_lands_promotion_suite_green(tmp_path: Path):
    # Buyer-proof: an eligible god-class lands ≥1 promotion through the gated apply
    # path and the suite stays green.
    _project(
        tmp_path, "app/m.py", _BAG,
        test_body=("from app.m import Bag\n\n"
                   "def test_bag():\n"
                   "    assert Bag(3).helper(4) == 5\n"
                   "    assert Bag.helper(4) == 5\n"
                   "    assert Bag(3).bound(4) == 7\n"))
    step = IdeaActionBridge().plan_idea(_god_idea("app/m.py::Bag"))
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised",
                                        verify=True)
    assert res["applied"] is True, res
    assert res["transform_type"] == "promote_staticmethod"
    assert res.get("suite_green") is True
    assert res["changed_files"] == ["app/m.py"]
    after = (tmp_path / "app" / "m.py").read_text()
    assert _decorators_of(after, "Bag", "helper") == ["staticmethod"]


def test_planted_regression_rolls_back(tmp_path: Path):
    # never-fake-green: a test that pins the OLD bound-call arity (passing an extra
    # positional that only worked while ``helper`` threaded ``self``) would break
    # after promotion — the impact-scoped gate must ROLL BACK, leaving the file
    # byte-identical and reporting applied:False.
    _project(
        tmp_path, "app/m.py", _BAG,
        test_body=("import inspect\n"
                   "from app.m import Bag\n\n"
                   "def test_helper_is_bound_with_self():\n"
                   "    # pins the PRE-promotion signature — promotion drops ``self``,\n"
                   "    # so this assertion regresses and must trigger rollback.\n"
                   "    params = list(inspect.signature(Bag.helper).parameters)\n"
                   "    assert params[0] == 'self'\n"))
    before = (tmp_path / "app" / "m.py").read_text()
    step = IdeaActionBridge().plan_idea(_god_idea("app/m.py::Bag"))
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised",
                                        verify=True)
    assert res["applied"] is False, res
    # The file is byte-identical — the regression was rolled back, never landed.
    assert (tmp_path / "app" / "m.py").read_text() == before


# === 5. registry / manifest / soundness / count-pin wiring ==================

def test_objective_is_registered():
    from app.engine.objective_compiler import available_objectives

    assert "promote-staticmethod" in set(available_objectives())


def test_manifest_classifies_promote_staticmethod_as_tidy():
    from app.engine.north_star_audit import OBJECTIVE_MANIFEST, classify_objectives
    from app.engine.objective_compiler import available_objectives

    assert "promote-staticmethod" in OBJECTIVE_MANIFEST["TIDY"]
    buckets = classify_objectives(set(available_objectives()))  # raises if unclassified
    assert "promote-staticmethod" in buckets["TIDY"]
    assert "promote-staticmethod" not in buckets["CONCRETE"]


def test_soundness_strategy_declared():
    from app.engine.objective_compiler import available_objectives
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_completeness,
    )

    sc = strategy_completeness(available_objectives())  # raises if undeclared
    assert "promote-staticmethod" in sc
    assert SOUNDNESS_STRATEGY["promote-staticmethod"]  # non-empty
    # A behaviour-preserving structural refactor — full-suite gated, NOT scope_verify.
    assert "promote-staticmethod" not in SCOPE_VERIFY_ALLOWLIST


def test_count_pin_is_eighty_five_concrete_forty_one():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    names = set(available_objectives())
    assert len(names) == 90  # 89 after js-strengthen-tests (89th, CONCRETE) registered
    assert len(classify_objectives(names)["CONCRETE"]) == 45  # js-strengthen-tests (89th) is CONCRETE


def test_facet_routes_to_objective():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(
        "the self-free methods to promote to staticmethod") == "promote-staticmethod"


def test_move_value_has_promote_staticmethod():
    from app.engine.move_value import OPERATOR_VALUE

    assert "promote_staticmethod" in OPERATOR_VALUE
    assert 0.0 <= OPERATOR_VALUE["promote_staticmethod"] <= 1.0


# === 6. THE HONEST-TEXT guard (the over-claim moat) =========================

def test_god_class_action_description_is_honest():
    # THE OVER-CLAIM GUARD: the executable god-class action describes what it
    # DELIVERS (self-free-method promotion to @staticmethod) AND that the full
    # responsibility-split stays a design task — it must NEVER claim the executable
    # action "decomposes into collaborators".
    _action, desc, _executable = _FACT_ACTIONS["god-class"]
    assert "@staticmethod" in desc
    assert "self-free" in desc
    assert "design task" in desc
    # The over-claim words are absent: the executable action does NOT decompose.
    assert "decompose" not in desc.lower()
    assert "collaborator" in desc.lower()  # named only as the ADVISORY full-split
    # … and specifically as something that REMAINS / stays a design task.
    assert "remains a design task" in desc or "stays a design task" in desc


def test_seeder_title_is_honest():
    # The surfaced idea title must mirror the same honesty: name the executable
    # @staticmethod promotion + the advisory design-task split, never over-promise a
    # decomposition.
    from app.engine.idea_permutation import IdeaSeeder
    from app.tools.project_profile import ProjectProfile

    profile = ProjectProfile(
        root=".",
        god_classes=[{"module": "app/x.py", "classname": "Mega",
                      "methods": 20, "attributes": 1}])
    roots = [r for r in IdeaSeeder().seed(profile)
             if r.source_facts and r.source_facts[0].startswith("god-class")]
    assert len(roots) == 1
    title = roots[0].title
    assert "@staticmethod" in title
    assert "design task" in title
    assert "decompose" not in title.lower()
