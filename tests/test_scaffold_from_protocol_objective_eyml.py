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


# --- proof-depth: derived-from impact-scope on a multi-module RED baseline ----
#
# The unblock: a CREATED file (``<stem>_impl.py``) has no importing test yet, so
# ``impacted_test_files(list(plan.new_contents))`` is empty and the impact-scope
# gate would degrade to the FULL suite — on a multi-module RED baseline an
# UNRELATED still-red module then vetoes the oracle-proven scaffold. The plan now
# carries the protocol module in ``derived_from``, so the scope is seeded from the
# protocol's own importing tests, and the unrelated red module can no longer veto.

def _red_baseline_two_module_project(tmp_path: Path) -> Path:
    """A flat-layout 2-module project with a legitimately RED baseline.

    Module A = ``app/greeter.py`` (the protocol), exercised by a GREEN
    ``tests/test_greeter.py`` that imports the protocol AND constructs the
    about-to-land ``GreeterImpl``. Module B = ``app/broken.py`` whose
    ``tests/test_broken.py`` FAILS (an unimplemented function) — the unrelated
    still-red module. So the FULL suite is RED, but the protocol's own tests pass
    once the scaffold lands."""
    _suite_project(tmp_path)
    (tmp_path / "app" / "greeter.py").write_text(_PROTO, encoding="utf-8")
    # GREEN test for the protocol module — imports app.greeter (so derived_from
    # seeds the scope to it) and constructs the about-to-land GreeterImpl (a green
    # suite proves the scaffold genuinely constructs, mirroring the oracle).
    (tmp_path / "tests" / "test_greeter.py").write_text(
        "from app.greeter import Greeter\n"
        "from app.greeter_impl import GreeterImpl\n\n"
        "def test_impl_constructs():\n"
        "    assert Greeter is not None\n"
        "    assert GreeterImpl() is not None\n", encoding="utf-8")
    # UNRELATED module B with a RED test — never imports the protocol.
    (tmp_path / "app" / "broken.py").write_text(
        "def unfinished():\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_broken.py").write_text(
        "from app.broken import unfinished\n\n"
        "def test_unfinished():\n    assert unfinished() == 42\n", encoding="utf-8")
    return tmp_path


def test_plan_carries_protocol_module_as_derived_from(tmp_path: Path):
    # The provenance: the created impl is derived FROM the protocol source module,
    # so the plan records exactly that one existing file in ``derived_from``.
    _suite_project(tmp_path)
    (tmp_path / "app" / "greeter.py").write_text(_PROTO, encoding="utf-8")
    plan = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py")
    assert plan.ok
    assert plan.derived_from == ["app/greeter.py"]


def test_derived_from_unblocks_landing_on_red_baseline(tmp_path: Path):
    # THE UNBLOCK PROOF: with impact_scope=True the gate seeds scope from the
    # protocol's importing tests (via derived_from), so the unrelated still-red
    # module B does NOT veto the oracle-proven scaffold — it LANDS, scoped against
    # exactly the protocol's own (green) test.
    _red_baseline_two_module_project(tmp_path)
    plan = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py")
    assert plan.ok and plan.derived_from == ["app/greeter.py"]
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=True)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)
    ev = result["test_evidence"]
    assert ev["scoped"] is True
    # The scope is the protocol's own test, NOT the unrelated red module's test.
    assert "tests/test_greeter.py" in ev["tests"]
    assert "tests/test_broken.py" not in ev["tests"]
    # The implementer genuinely LANDED on disk.
    landed = tmp_path / "app" / "greeter_impl.py"
    assert landed.exists()
    assert "class GreeterImpl(Greeter):" in landed.read_text(encoding="utf-8")


def test_derived_from_scope_still_catches_a_genuine_regression(tmp_path: Path):
    # never-fake-green REGRESSION-CATCH: if the protocol's own test would FAIL
    # against the scaffolded impl (here the test asserts behavior a bare ...-body
    # cannot satisfy), the derived-from-scoped gate catches it, rolls back, and the
    # created impl file is unlinked — the scope is a real backstop, not a rubber
    # stamp. The unrelated red module is irrelevant to this verdict.
    _suite_project(tmp_path)
    (tmp_path / "app" / "greeter.py").write_text(_PROTO, encoding="utf-8")
    # A protocol test that DEMANDS behavior the generated ``...``-body cannot give:
    # GreeterImpl().greet(...) returns None (the ... body), so == 'hi alice' fails.
    (tmp_path / "tests" / "test_greeter.py").write_text(
        "from app.greeter_impl import GreeterImpl\n\n"
        "def test_greet_behaves():\n"
        "    assert GreeterImpl().greet('alice') == 'hi alice'\n", encoding="utf-8")
    plan = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py")
    assert plan.ok  # the oracle only proves CONSTRUCTION, not behavior
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=True)
    assert result.get("applied") is False
    assert result.get("rolled_back") is True
    # The created impl was rolled back (unlinked) — no scaffold survives.
    landed = tmp_path / "app" / "greeter_impl.py"
    surviving = landed.read_text(encoding="utf-8") if landed.exists() else ""
    assert "class GreeterImpl" not in surviving
    assert surviving == ""


def test_byte_identical_scope_seed_for_a_plan_without_derived_from(
        tmp_path: Path, monkeypatch):
    # OFF-BY-DEFAULT BYTE-IDENTITY: for any plan with the default derived_from=[],
    # _verify_scoped must seed the scope from EXACTLY list(plan.new_contents) —
    # no extra entries — so every other objective is unchanged. We record the
    # changed_files argument impacted_test_files is called with (patched at its
    # import source, since _verify_scoped imports it lazily by name).
    import subprocess

    import app.engine.test_impact as ti
    import app.execution.cross_file_rename as cfr

    seen: dict[str, list[str]] = {}

    def _spy(root, changed_files):
        seen["changed_files"] = list(changed_files)
        # Return non-empty so _verify_scoped proceeds to (a stubbed) subprocess.
        return ["tests/test_x.py"]

    monkeypatch.setattr(ti, "impacted_test_files", _spy)

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())

    plan = cfr.RenamePlan(old="x", new="y")
    plan.new_contents = {"app/mod.py": "x = 1\n"}
    # default derived_from == []
    assert plan.derived_from == []
    cfr._verify_scoped(tmp_path, plan)
    assert seen["changed_files"] == ["app/mod.py"]  # NO extra derived-from entry


def test_derived_from_widens_scope_seed_for_scaffold(tmp_path: Path, monkeypatch):
    # The dual of the byte-identity test: when derived_from IS set, the scope seed
    # is exactly list(new_contents) + derived_from (so the protocol module is
    # included). Pins the one-line concatenation in _verify_scoped.
    import subprocess

    import app.engine.test_impact as ti
    import app.execution.cross_file_rename as cfr

    seen: dict[str, list[str]] = {}

    def _spy(root, changed_files):
        seen["changed_files"] = list(changed_files)
        return ["tests/test_greeter.py"]

    monkeypatch.setattr(ti, "impacted_test_files", _spy)

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())

    plan = cfr.RenamePlan(old="app/greeter.py", new="scaffold-from-protocol")
    plan.new_contents = {"app/greeter_impl.py": "x = 1\n"}
    plan.derived_from = ["app/greeter.py"]
    cfr._verify_scoped(tmp_path, plan)
    assert seen["changed_files"] == ["app/greeter_impl.py", "app/greeter.py"]


def test_idempotent_noop_plan_has_no_derived_from(tmp_path: Path):
    # IDEMPOTENCE PRESERVED: a second run after the impl exists is a byte-identical
    # no-op (empty new_contents, plan.ok False) AND derived_from is irrelevant —
    # the new field is set only on the assignment path that also fills new_contents,
    # so the no-op path leaves it at the default []. Confirms the field does not
    # perturb the idempotent path.
    _suite_project(tmp_path)
    (tmp_path / "app" / "greeter.py").write_text(_PROTO, encoding="utf-8")
    first = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py")
    impl_rel = "app/greeter_impl.py"
    (tmp_path / impl_rel).write_text(first.new_contents[impl_rel], encoding="utf-8")
    again = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py")
    assert not again.new_contents
    assert again.ok is False
    assert again.derived_from == []


# --- proof-depth: the soundness denetçi blesses the widened allowlist ---------

def test_scaffold_opts_into_scope_verify():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["scaffold-from-protocol"]
    assert spec.scope_verify is True


def test_scope_verify_allowlist_passes_with_scaffold():
    # The denetçi A3 check: scaffold-from-protocol now sets scope_verify=True AND is
    # in the audited allowlist, so check_scope_verify_allowlist is clean.
    from app.engine.soundness_audit import check_scope_verify_allowlist

    ok, reasons = check_scope_verify_allowlist()
    assert ok and reasons == []


def test_scope_verify_allowlist_would_fail_if_scaffold_delisted():
    # NEGATIVE CONTROL: an off-list objective that sets scope_verify=True is a FAIL.
    # Inject a spec mapping where scaffold-from-protocol still sets the flag but is
    # NOT in the allowlist (simulated by checking against a planted spec that is not
    # in SCOPE_VERIFY_ALLOWLIST), proving the allowlist edit is load-bearing.
    from app.engine.develop_registry import ObjectiveSpec
    from app.engine.soundness_audit import check_scope_verify_allowlist

    planted = {
        "scaffold-from-protocol": ObjectiveSpec(
            name="scaffold-from-protocol",
            fitness=lambda r: 0.0, moves=lambda r: [], scope_verify=True),
        "not-on-the-allowlist": ObjectiveSpec(
            name="not-on-the-allowlist",
            fitness=lambda r: 0.0, moves=lambda r: [], scope_verify=True),
    }
    ok, reasons = check_scope_verify_allowlist(planted)
    assert ok is False
    assert any("not-on-the-allowlist" in r for r in reasons)
    # scaffold-from-protocol, being ON the allowlist, is NOT flagged.
    assert not any("scaffold-from-protocol" in r for r in reasons)


def test_strategy_completeness_reflects_impact_scoped_gate():
    from app.engine.objective_compiler import available_objectives
    from app.engine.soundness_audit import (
        SOUNDNESS_STRATEGY,
        strategy_completeness,
    )

    # The forward tripwire does not raise (every live objective has a strategy).
    table = strategy_completeness(available_objectives())
    assert "scaffold-from-protocol" in table
    # The manifest stays TRUTHFUL: the strategy now names BOTH the instantiation
    # oracle (the independent correctness proof) and the impact-scoped derived-from
    # gate (the regression backstop).
    strat = SOUNDNESS_STRATEGY["scaffold-from-protocol"]
    assert "instantiation-oracle" in strat
    assert "impact-scoped-derived-from-gate" in strat


def test_scaffold_plan_new_contents_unchanged_by_derived_from(tmp_path: Path):
    # DETERMINISM / new_contents untouched: the determinism harness hashes ONLY
    # plan.new_contents. Adding derived_from must not perturb it — two runs produce
    # byte-identical new_contents, and derived_from is a separate, fixed echo.
    _project(tmp_path, "app/greeter.py", _PROTO)
    one = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py")
    two = plan_scaffold_from_protocol(str(tmp_path), "app/greeter.py")
    assert one.new_contents == two.new_contents
    assert one.derived_from == two.derived_from == ["app/greeter.py"]
    # derived_from is NOT folded into new_contents (the hashed surface).
    assert "app/greeter.py" not in one.new_contents
