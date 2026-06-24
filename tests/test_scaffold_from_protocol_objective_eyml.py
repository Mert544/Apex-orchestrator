"""scaffold-from-protocol develop objective — LAND a concrete implementer for a
``typing.Protocol`` the project declares but has not implemented yet.

Covers: objective registration / reachability (a facet phrase routes to it and
the facet-map<->registry 1:1 parity invariant still holds); the north-star
manifest classes it CONCRETE with the reverse-tripwire clean; the facet ladder
carries the phrase with the originals still leading; the plan LANDS a NEW
``<stem>_impl.py`` with one ``...``-bodied override per fillable member
(decorators preserved, ``@abstractmethod`` dropped, annotations stripped); the
END-TO-END landing (``apply_rename`` verify=True creates the file, the suite
stays green, AND the landed class genuinely INSTANTIATES); and every REFUSAL that
keeps it honest — a marker protocol (no fillable members), an already-implemented
protocol (an explicit subclass, or the impl file already present), a non-Protocol
class, an alias-imported Protocol (a conservative miss), and a test/fixture
input. Idempotency (a second run is a byte-identical no-op), determinism (same
input -> same output), and the never-fake-green auto-rollback (a scaffold that
would break the suite is deleted on disk) are pinned too.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.objectives.scaffold_from_protocol import (
    plan_scaffold_from_protocol,
)

# A Protocol with three FILLABLE members of different kinds and NO implementer:
# an @abstractmethod, a @property, and a NotImplementedError-bodied method.
_PROTO = (
    "from typing import Protocol\n"
    "from abc import abstractmethod\n\n\n"
    "class Greeter(Protocol):\n"
    "    name: str\n\n"
    "    @abstractmethod\n"
    "    def greet(self, who: str) -> str: ...\n\n"
    "    @property\n"
    "    def label(self) -> str: ...\n\n"
    "    def shout(self, msg: str) -> str:\n"
    "        raise NotImplementedError\n"
)


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


# --- registration / reachability ---------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "scaffold-from-protocol" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["scaffold-from-protocol"]
    assert callable(spec.fitness) and callable(spec.moves)
    # The oracle runs a subprocess per candidate, so the spec is flagged expensive.
    assert spec.expensive is True


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(
        "the protocol stub to scaffold") == "scaffold-from-protocol"


def test_facet_reachability_parity_invariant_holds():
    # The standing 1:1 invariant: the facet map reaches EXACTLY the registered
    # objectives. Adding scaffold-from-protocol to BOTH sides keeps the equality.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_substring_order_safe():
    # The new key must be neither a substring of, nor contain, any other key
    # (with a different objective) — else the first-match scan would mis-route.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    new = "the protocol stub to scaffold"
    keys = list(FACET_OBJECTIVE_MAP)
    assert new in keys
    for other in keys:
        if other == new:
            continue
        assert new not in other, f"{new!r} is a substring of {other!r}"
        assert other not in new, f"{other!r} is a substring of {new!r}"


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "scaffold-from-protocol" in buckets["CONCRETE"]
    # No stale manifest name (a name with no live objective) was introduced.
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_shared_interface_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["the shared interface to extract"]
    assert "the protocol stub to scaffold" in ladder
    assert ladder[0] == "the common method signatures"  # originals still lead


# --- the plan: a Protocol with no implementer gets scaffolded -----------------

def test_plan_lands_a_concrete_implementer(tmp_path: Path):
    _suite_project(tmp_path)
    (tmp_path / "app" / "greeter.py").write_text(_PROTO, encoding="utf-8")
    plan = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py")
    assert plan.ok
    impl_rel = "app/greeter_impl.py"
    gen = plan.new_contents[impl_rel]
    # Imports the real protocol module (NOT the impl file) and subclasses it.
    assert "from app.greeter import Greeter" in gen
    assert "class GreeterImpl(Greeter):" in gen
    # One override per fillable member, each with a ``...`` body.
    assert "def greet(self, who): ..." in gen
    assert "def shout(self, msg): ..." in gen
    # The original is captured (existing-or-"") so the engine can roll the create
    # back; here the file did not exist, so the original is the empty string.
    assert plan.originals[impl_rel] == ""
    assert plan.edits_by_file[impl_rel] == 3


def test_generated_scaffold_source_parses(tmp_path: Path):
    _project(tmp_path, "app/greeter.py", _PROTO)
    gen = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py").new_contents[
        "app/greeter_impl.py"]
    ast.parse(gen)  # never ship un-parseable scaffold source


def test_decorators_preserved_and_abstractmethod_dropped(tmp_path: Path):
    # The @property keeps its kind on the override; the @abstractmethod is dropped
    # (the override is concrete) and annotations are stripped (no NameError).
    _project(tmp_path, "app/greeter.py", _PROTO)
    gen = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py").new_contents[
        "app/greeter_impl.py"]
    assert "    @property\n    def label(self): ..." in gen
    assert "@abstractmethod" not in gen          # dropped on the override
    assert "-> str" not in gen                   # return annotations stripped
    assert "who: str" not in gen                 # param annotations stripped


def test_only_fillable_members_are_redeclared(tmp_path: Path):
    # A member with a REAL concrete default body must NOT be overridden (that would
    # clobber behaviour) — only the abstract / unimplemented members are.
    src = (
        "from typing import Protocol\n"
        "from abc import abstractmethod\n\n\n"
        "class Calc(Protocol):\n"
        "    @abstractmethod\n"
        "    def add(self, a, b): ...\n\n"
        "    def doubled(self, a):\n"
        "        return a * 2\n"   # concrete default — keep, do not clobber
    )
    _project(tmp_path, "app/calc.py", src)
    gen = plan_scaffold_from_protocol(str(tmp_path), "app/calc.py").new_contents[
        "app/calc_impl.py"]
    assert "def add(self, a, b): ..." in gen
    assert "def doubled" not in gen   # concrete default not redeclared


def test_args_kwargs_fallback_when_signature_is_exotic(tmp_path: Path):
    # Positional-only / kw-only / *args / **kwargs strip to a clean param list,
    # and unknown annotations are stripped so the override never NameErrors.
    src = (
        "from typing import Protocol\n\n\n"
        "class C(Protocol):\n"
        "    def f(self, a, b=5, /, c=3, *args, k=1, **kw) -> 'X': ...\n"
    )
    _project(tmp_path, "app/c.py", src)
    gen = plan_scaffold_from_protocol(str(tmp_path), "app/c.py").new_contents[
        "app/c_impl.py"]
    assert "def f(self, a, b, /, c, *args, k, **kw): ..." in gen
    ast.parse(gen)


# --- REFUSALS: honest under-claims -------------------------------------------

def test_refuses_marker_protocol_no_members(tmp_path: Path):
    # A Protocol with zero fillable members pins nothing to scaffold.
    marker = (
        "from typing import Protocol\n\n\n"
        "class Marker(Protocol):\n    x: int\n    y: str\n"
    )
    _project(tmp_path, "app/marker.py", marker)
    assert not plan_scaffold_from_protocol(
        str(tmp_path), "app/marker.py").new_contents


def test_refuses_when_explicit_subclass_already_implements(tmp_path: Path):
    # An explicit ``class Real(Greeter)`` already implements it -> no scaffold.
    src = _PROTO + (
        "\n\nclass Real(Greeter):\n"
        "    name = ''\n"
        "    def greet(self, who):\n        return who\n"
        "    @property\n    def label(self):\n        return ''\n"
        "    def shout(self, msg):\n        return msg\n"
    )
    _project(tmp_path, "app/greeter.py", src)
    assert not plan_scaffold_from_protocol(
        str(tmp_path), "app/greeter.py").new_contents


def test_refuses_when_impl_file_already_present(tmp_path: Path):
    # Idempotency at the detection layer: a sibling already defining GreeterImpl
    # (the scaffold's own output name) is seen as the implementer -> no-op.
    _suite_project(tmp_path)
    (tmp_path / "app" / "greeter.py").write_text(_PROTO, encoding="utf-8")
    (tmp_path / "app" / "greeter_impl.py").write_text(
        "class GreeterImpl:\n    pass\n", encoding="utf-8")
    assert not plan_scaffold_from_protocol(
        str(tmp_path), "app/greeter.py").new_contents


def test_refuses_non_protocol_class(tmp_path: Path):
    # A plain class (or an ABC that is not a Protocol) is not in scope.
    src = (
        "class Plain:\n"
        "    def a(self): ...\n"
        "    def b(self):\n        raise NotImplementedError\n"
    )
    _project(tmp_path, "app/plain.py", src)
    assert not plan_scaffold_from_protocol(
        str(tmp_path), "app/plain.py").new_contents


def test_refuses_alias_imported_protocol(tmp_path: Path):
    # ``from typing import Protocol as P`` is a deliberate conservative miss — the
    # base name is not literally ``Protocol``, so the scaffold refuses (never a
    # wrong scaffold) rather than guessing.
    src = (
        "from typing import Protocol as P\n"
        "from abc import abstractmethod\n\n\n"
        "class Q(P):\n"
        "    @abstractmethod\n    def a(self): ...\n"
    )
    _project(tmp_path, "app/q.py", src)
    assert not plan_scaffold_from_protocol(
        str(tmp_path), "app/q.py").new_contents


def test_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _PROTO)
    assert not plan_scaffold_from_protocol(
        str(tmp_path), "tests/test_x.py").new_contents


def test_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _PROTO)
    assert not plan_scaffold_from_protocol(
        str(tmp_path), "fixtures/sample.py").new_contents


def test_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_scaffold_from_protocol(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- idempotency / determinism -----------------------------------------------

def test_idempotent_second_run_is_a_noop(tmp_path: Path):
    # After the impl file lands, the explicit ``class GreeterImpl(Greeter)`` IS the
    # implementer, so a second run sees it and is a no-op.
    _suite_project(tmp_path)
    (tmp_path / "app" / "greeter.py").write_text(_PROTO, encoding="utf-8")
    plan = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py")
    impl_rel = "app/greeter_impl.py"
    (tmp_path / impl_rel).write_text(plan.new_contents[impl_rel], encoding="utf-8")
    again = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py")
    assert not again.new_contents


def test_deterministic_across_two_runs(tmp_path: Path):
    _project(tmp_path, "app/greeter.py", _PROTO)
    one = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py").new_contents.get(
        "app/greeter_impl.py")
    two = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py").new_contents.get(
        "app/greeter_impl.py")
    assert one is not None and one == two
    # Members are emitted in SOURCE order (greet before label before shout).
    assert one.index("def greet") < one.index("def label") < one.index("def shout")


# --- end-to-end: gated apply, real landing, the class INSTANTIATES ------------

def test_end_to_end_lands_scaffold_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    (tmp_path / "app" / "greeter.py").write_text(_PROTO, encoding="utf-8")
    # A pre-existing test that IMPORTS and INSTANTIATES the (about-to-land) impl —
    # so a green suite proves the scaffold genuinely constructs (the oracle's claim
    # re-checked at the suite level).
    (tmp_path / "tests" / "test_uses_impl.py").write_text(
        "def test_constructs():\n"
        "    from app.greeter_impl import GreeterImpl\n"
        "    assert GreeterImpl() is not None\n", encoding="utf-8")

    plan = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = tmp_path / "app" / "greeter_impl.py"
    assert landed.exists()                       # the new implementer LANDED
    text = landed.read_text(encoding="utf-8")
    assert "class GreeterImpl(Greeter):" in text
    # The landed class genuinely satisfies the Protocol: the suite (which imports
    # and constructs it) passed under the apply gate above — never-fake-green.


def _src_layout_project(tmp_path: Path) -> Path:
    """A standard ``src/``-layout suite project: ``pyproject.toml`` declares
    ``pythonpath=['src']`` so the package imports WITHOUT the ``src`` prefix
    (``mylib.greeter``, not ``src.mylib.greeter``) — exactly the layout whose impl
    module the oracle could not import until ``root/src`` was put on its path."""
    (tmp_path / "src" / "mylib").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "mylib" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='mylib'\nversion='0'\n\n"
        "[tool.pytest.ini_options]\npythonpath=['src']\n", encoding="utf-8")
    (tmp_path / "src" / "mylib" / "greeter.py").write_text(_PROTO, encoding="utf-8")
    return tmp_path


def test_src_layout_protocol_lands_and_instantiates(tmp_path: Path):
    # NIT-1: on a ``src/`` layout the dotted-path picker selects ``mylib.greeter``
    # (sorted before ``src.mylib.greeter``), so the oracle must import
    # ``mylib.greeter_impl`` with ``root/src`` on its path. Before the fix the
    # oracle saw only ``root`` -> import failure -> empty plan on EVERY src project.
    _src_layout_project(tmp_path)
    plan = plan_scaffold_from_protocol(str(tmp_path), "src/mylib/greeter.py")
    assert plan.ok  # the oracle actually imported + INSTANTIATED GreeterImpl
    impl_rel = "src/mylib/greeter_impl.py"
    gen = plan.new_contents[impl_rel]
    # The scaffold imports the package under its REAL top-level name (src stripped).
    assert "from mylib.greeter import Greeter" in gen
    assert "class GreeterImpl(Greeter):" in gen
    assert plan.edits_by_file[impl_rel] == 3


def test_src_layout_end_to_end_lands_and_stays_green(tmp_path: Path):
    # The full apply gate on a src/ layout: a pre-existing test imports + constructs
    # the about-to-land impl under ``mylib.greeter_impl``; a green suite proves the
    # scaffold genuinely instantiates (never-fake-green) on this layout too.
    _src_layout_project(tmp_path)
    (tmp_path / "tests" / "test_uses_impl.py").write_text(
        "def test_constructs():\n"
        "    from mylib.greeter_impl import GreeterImpl\n"
        "    assert GreeterImpl() is not None\n", encoding="utf-8")
    plan = plan_scaffold_from_protocol(str(tmp_path), "src/mylib/greeter.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)
    landed = tmp_path / "src" / "mylib" / "greeter_impl.py"
    assert landed.exists()
    assert "class GreeterImpl(Greeter):" in landed.read_text(encoding="utf-8")


def test_atexit_print_does_not_break_the_oracle(tmp_path: Path):
    # NIT-2: a protocol module that registers an ``atexit`` print emits a trailing
    # non-JSON line on the probe's stdout AFTER the probe's ``{"ok": true}`` verdict
    # (atexit fires at interpreter shutdown). The oracle must scan for the LAST
    # valid JSON OBJECT, not literally the last line, or it spuriously refuses an
    # otherwise-instantiable scaffold. The scaffold still LANDS here.
    noisy = (
        "import atexit\n"
        "atexit.register(lambda: print('shutdown banner -- not json'))\n" + _PROTO)
    _suite_project(tmp_path)
    (tmp_path / "app" / "greeter.py").write_text(noisy, encoding="utf-8")
    plan = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py")
    assert plan.ok  # the trailing atexit line did not defeat the oracle's JSON parse
    gen = plan.new_contents["app/greeter_impl.py"]
    assert "class GreeterImpl(Greeter):" in gen


def test_end_to_end_auto_rollback_when_scaffold_breaks_suite(tmp_path: Path):
    # never-fake-green at the engine level: if the protocol module is mutated AFTER
    # the plan is built so the landed scaffold's ``from app.greeter import Greeter``
    # no longer resolves (the Protocol is renamed away), the suite errors on import
    # and the verified apply rolls the CREATE back — leaving no scaffold on disk.
    _suite_project(tmp_path)
    (tmp_path / "app" / "greeter.py").write_text(_PROTO, encoding="utf-8")
    (tmp_path / "tests" / "test_uses_impl.py").write_text(
        "def test_constructs():\n"
        "    from app.greeter_impl import GreeterImpl\n"
        "    assert GreeterImpl() is not None\n", encoding="utf-8")
    plan = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py")
    assert plan.ok  # green at plan time (the oracle constructed GreeterImpl)
    # Now break the protocol so the (about-to-land) scaffold's import fails.
    (tmp_path / "app" / "greeter.py").write_text(
        _PROTO.replace("class Greeter(", "class Renamed("), encoding="utf-8")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is False
    assert result.get("rolled_back") is True
    # never-fake-green: the file is restored to its pre-change state (it did not
    # exist before, captured as the empty original), so NO scaffold survives.
    landed = tmp_path / "app" / "greeter_impl.py"
    surviving = landed.read_text(encoding="utf-8") if landed.exists() else ""
    assert "class GreeterImpl" not in surviving
    assert surviving == ""
