"""seal-final-method develop objective — LAND ``@typing.final`` on a project's own
METHOD that is PROVABLY never overridden anywhere in the project.

``@typing.final`` on a method is a PURE runtime no-op (it only records the intent
and is a type-checker hint), so sealing a method ``@final`` is behaviour-preserving
BY CONSTRUCTION — there is nothing at runtime to break. The only honesty risk is a
FALSE "final" on a method that IS overridden; that is closed STRUCTURALLY by a
whole-project over-approximate, transitive subclass-method scan, NOT by the suite —
which is exactly why the never-fake-green guard here is structural: an overridden
method is never sealed even though the no-op decorator would keep the suite green (a
fake-green the structural scan forbids).

Covers: the core transform (fresh import insert; widen an existing ``from typing
import ...``; the dotted ``@typing.final`` fallback when ``final`` is shadowed but
``typing`` is bound; decorator/indent preservation; async methods;
trailing-newline preservation) plus EVERY refusal — overridden (same-module,
cross-module, dotted base, subscripted base, transitive grandchild), already
``@final`` / ``@typing.final``, a dunder, a property / staticmethod / classmethod /
overload / abstractmethod, a Protocol / ABC / ABCMeta class, a shadowed ``final``
with no usable ``typing``, a ``final`` imported from another module, test/fixture,
syntax error; plus idempotency and determinism; the whole-project subclass-method
over-approximation; objective registration / reachability (available, callable
spec, reachable-from-facet, the facet-map<->registry 1:1 parity invariant,
substring-safety, the north-star manifest classing it CONCRETE with the reverse
tripwire clean, the facet ladder carrying the phrase with the originals still
leading); the END-TO-END landing (``apply_rename`` verify=True seals the method in
place and the suite stays green); and the never-fake-green guarantee (an overridden
method is NOT sealed — incl. the conservative-ambiguity refusal — the structural
scan refusing the false claim a no-op decorator's green suite would otherwise hide).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.final_method import (
    add_final_method_decorator,
    finalizable_methods,
    method_has_final_decorator,
    subclass_method_names,
)
from app.execution.objectives.seal_final_method import plan_seal_final_method

# A class with one plain instance method, never overridden: gains a fresh
# ``from typing import final`` + ``@final`` on the method.
_LEAF = (
    '"""A service module."""\n'
    "\n"
    "\n"
    "class Service:\n"
    "    def commit(self) -> int:\n"
    "        return 1\n"
)

_PHRASE = "the method to seal as final"


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


def _final_method_names(source: str) -> set[str]:
    """``{Class.method}`` for every method carrying ``@final`` in ``source``."""
    tree = ast.parse(source)
    out: set[str] = set()
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for fn in cls.body:
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    method_has_final_decorator(fn):
                out.add(f"{cls.name}.{fn.name}")
    return out


# --- the core transform: detection ------------------------------------------

def test_finalizable_detects_never_overridden_method():
    assert finalizable_methods(_LEAF) == ["Service.commit"]


def test_method_has_final_decorator_true_for_bare_final():
    fn = ast.parse("class C:\n    @final\n    def m(self):\n        pass\n").body[0].body[0]
    assert method_has_final_decorator(fn)


def test_method_has_final_decorator_true_for_dotted_typing_final():
    fn = ast.parse(
        "class C:\n    @typing.final\n    def m(self):\n        pass\n"
    ).body[0].body[0]
    assert method_has_final_decorator(fn)


def test_method_has_final_decorator_false_when_absent():
    fn = ast.parse("class C:\n    def m(self):\n        pass\n").body[0].body[0]
    assert not method_has_final_decorator(fn)


def test_async_method_is_finalizable():
    src = "class C:\n    async def fetch(self):\n        return 1\n"
    assert finalizable_methods(src) == ["C.fetch"]


def test_multiple_methods_all_sealable_in_a_leaf_class():
    src = (
        "class C:\n"
        "    def a(self):\n"
        "        return 1\n"
        "    def b(self):\n"
        "        return 2\n"
    )
    assert finalizable_methods(src) == ["C.a", "C.b"]


# --- the core transform: rewrite --------------------------------------------

def test_seals_method_and_adds_fresh_typing_import():
    out = add_final_method_decorator(_LEAF)
    assert out is not None
    lines = out.splitlines()
    assert lines[0] == '"""A service module."""'  # docstring stays first
    assert "from typing import final" in lines
    assert lines.index("from typing import final") < lines.index("    @final")
    assert "    @final" in lines  # decorator carries the method's indentation
    assert "    def commit(self) -> int:" in out
    ast.parse(out)  # never lands broken Python


def test_final_decorator_sits_directly_above_the_method():
    out = add_final_method_decorator(_LEAF)
    assert out is not None
    assert "\n    @final\n    def commit(self) -> int:\n" in out


def test_widens_existing_typing_import_in_place():
    src = "from typing import Any\n\n\nclass C:\n    def m(self) -> Any:\n        return 1\n"
    out = add_final_method_decorator(src)
    assert out is not None
    assert out.count("from typing import") == 1  # widened, not a second line
    assert out.splitlines()[0] == "from typing import Any, final"
    assert "    @final" in out
    ast.parse(out)


def test_uses_dotted_typing_final_when_final_name_is_shadowed():
    # ``final`` is shadowed by a local def, but ``typing`` is bound bare — so the
    # dotted ``@typing.final`` is provable and used (and NO ``from typing import
    # final`` is added, which would re-bind the shadowed name).
    src = (
        "import typing\n"
        "\n"
        "\n"
        "def final(c):\n"
        "    return c\n"
        "\n"
        "\n"
        "class C:\n"
        "    def m(self):\n"
        "        pass\n"
    )
    out = add_final_method_decorator(src)
    assert out is not None
    assert "@typing.final" in out
    assert "from typing import final" not in out  # the shadow is not re-imported
    ast.parse(out)


def test_preserves_an_existing_method_decorator():
    src = (
        "import functools\n"
        "\n"
        "\n"
        "class C:\n"
        "    @functools.wraps\n"
        "    def m(self):\n"
        "        pass\n"
    )
    out = add_final_method_decorator(src)
    assert out is not None
    # The existing decorator stays; @final is added directly above the def.
    assert "    @functools.wraps\n    @final\n    def m(self):" in out
    ast.parse(out)


def test_preserves_trailing_newline_absence():
    out = add_final_method_decorator("class C:\n    def m(self):\n        return 1")
    assert out is not None and not out.endswith("\n")


def test_async_method_seal_lands():
    src = "class C:\n    async def fetch(self):\n        return 1\n"
    out = add_final_method_decorator(src)
    assert out is not None
    assert "    @final\n    async def fetch(self):" in out
    ast.parse(out)


# --- the whole-project subclass-method over-approximation -------------------

def test_subclass_method_names_collects_override():
    base = "class Base:\n    def run(self):\n        return 1\n"
    sub = "from m import Base\n\n\nclass Sub(Base):\n    def run(self):\n        return 2\n"
    assert subclass_method_names("Base", [base, sub]) == {"run"}


def test_subclass_method_names_empty_for_leaf():
    assert subclass_method_names("Service", [_LEAF]) == set()


def test_project_scan_can_only_add_refusals():
    # A method sealable in isolation REFUSES once a SIBLING module overrides it.
    base = "class Base:\n    def run(self):\n        return 1\n"
    assert finalizable_methods(base) == ["Base.run"]
    sub = "from m import Base\n\n\nclass Sub(Base):\n    def run(self):\n        return 2\n"
    assert add_final_method_decorator(base, [base, sub]) is None


def test_dotted_base_override_refused_cross_module():
    # A sibling overrides ``run`` through a DOTTED base (``a.Base``); the
    # whole-project scan (final ``.attr``) must see it and refuse to seal Base.run.
    base = "class Base:\n    def run(self):\n        return 1\n"
    sub = "import a\n\n\nclass Sub(a.Base):\n    def run(self):\n        return 2\n"
    assert finalizable_methods(base) == ["Base.run"]
    assert add_final_method_decorator(base, [base, sub]) is None


def test_subscripted_base_override_refused_cross_module():
    # A SUBSCRIPTED base ``class Sub(Base[int])`` really subclasses ``Base`` — the
    # subscript head must be recorded, so an override there refuses the seal.
    base = (
        "from typing import Generic, TypeVar\n"
        "T = TypeVar('T')\n"
        "\n"
        "\n"
        "class Base(Generic[T]):\n"
        "    def run(self):\n"
        "        return 1\n"
    )
    sub = "from m import Base\n\n\nclass Sub(Base[int]):\n    def run(self):\n        return 2\n"
    assert finalizable_methods(base) == ["Base.run"]
    assert add_final_method_decorator(base, [base, sub]) is None


def test_dotted_subscripted_base_override_refused():
    # The dotted-AND-subscripted form ``class Sub(pkg.Base[Any])`` — head resolved
    # to its final ``.attr`` ``"Base"`` — must also refuse the seal.
    base = "class Base:\n    def run(self):\n        return 1\n"
    sub = (
        "import pkg\n"
        "from typing import Any\n"
        "\n"
        "\n"
        "class Sub(pkg.Base[Any]):\n"
        "    def run(self):\n"
        "        return 2\n"
    )
    assert finalizable_methods(base) == ["Base.run"]
    assert add_final_method_decorator(base, [base, sub]) is None


def test_transitive_grandchild_override_refused():
    # ``run`` is overridden two levels down (Base <- Mid <- Leaf). The transitive
    # by-name closure must reach the grandchild and refuse to seal Base.run.
    base = "class Base:\n    def run(self):\n        return 1\n"
    mid = "from m import Base\n\n\nclass Mid(Base):\n    def helper(self):\n        return 0\n"
    leaf = "from m import Mid\n\n\nclass Leaf(Mid):\n    def run(self):\n        return 9\n"
    assert subclass_method_names("Base", [base, mid, leaf]) == {"helper", "run"}
    assert add_final_method_decorator(base, [base, mid, leaf]) is None


# --- the core transform: REFUSALS (honest no-ops) ---------------------------

def test_refuses_overridden_method_same_module():
    src = (
        "class Base:\n"
        "    def run(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "class Sub(Base):\n"
        "    def run(self):\n"
        "        return 2\n"
    )
    # ``Base.run`` is overridden -> refused; ``Sub.run`` (a leaf method) is sealable.
    assert finalizable_methods(src) == ["Sub.run"]


def test_refuses_already_final_bare_idempotent():
    src = (
        "from typing import final\n"
        "\n"
        "\n"
        "class C:\n"
        "    @final\n"
        "    def m(self):\n"
        "        pass\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_already_typing_final_idempotent():
    src = (
        "import typing\n"
        "\n"
        "\n"
        "class C:\n"
        "    @typing.final\n"
        "    def m(self):\n"
        "        pass\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_dunder_method():
    # A dunder is routinely overridden by design — sealing it is the wrong intent.
    src = (
        "class C:\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "    def __eq__(self, other):\n"
        "        return True\n"
    )
    assert finalizable_methods(src) == []
    assert add_final_method_decorator(src) is None


def test_refuses_property():
    src = (
        "class C:\n"
        "    @property\n"
        "    def value(self):\n"
        "        return 1\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_staticmethod():
    src = (
        "class C:\n"
        "    @staticmethod\n"
        "    def helper():\n"
        "        return 1\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_classmethod():
    src = (
        "class C:\n"
        "    @classmethod\n"
        "    def make(cls):\n"
        "        return cls()\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_overload():
    src = (
        "from typing import overload\n"
        "\n"
        "\n"
        "class C:\n"
        "    @overload\n"
        "    def m(self, x: int) -> int:\n"
        "        ...\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_abstractmethod():
    # An abstractmethod is MEANT to be overridden — refuse.
    src = (
        "from abc import abstractmethod\n"
        "\n"
        "\n"
        "class C:\n"
        "    @abstractmethod\n"
        "    def run(self):\n"
        "        ...\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_dotted_abstractmethod():
    src = (
        "import abc\n"
        "\n"
        "\n"
        "class C:\n"
        "    @abc.abstractmethod\n"
        "    def run(self):\n"
        "        ...\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_protocol_class():
    # A Protocol's methods are meant to be implemented (overridden) — refuse all.
    src = (
        "from typing import Protocol\n"
        "\n"
        "\n"
        "class P(Protocol):\n"
        "    def run(self):\n"
        "        ...\n"
    )
    assert finalizable_methods(src) == []
    assert add_final_method_decorator(src) is None


def test_refuses_subscripted_protocol_class():
    src = (
        "from typing import Protocol, TypeVar\n"
        "T = TypeVar('T')\n"
        "\n"
        "\n"
        "class P(Protocol[T]):\n"
        "    def run(self):\n"
        "        ...\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_abc_base_class():
    src = (
        "from abc import ABC\n"
        "\n"
        "\n"
        "class A(ABC):\n"
        "    def run(self):\n"
        "        return 1\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_dotted_abc_base_class():
    src = (
        "import abc\n"
        "\n"
        "\n"
        "class A(abc.ABC):\n"
        "    def run(self):\n"
        "        return 1\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_abcmeta_metaclass_class():
    src = (
        "from abc import ABCMeta\n"
        "\n"
        "\n"
        "class A(metaclass=ABCMeta):\n"
        "    def run(self):\n"
        "        return 1\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_when_final_shadowed_and_no_usable_typing():
    # ``final`` is shadowed by a local def and ``typing`` is NOT bound bare — there
    # is no provable spelling of ``typing.final``, so refuse (round-16 lesson).
    src = (
        "def final(c):\n"
        "    return c\n"
        "\n"
        "\n"
        "class C:\n"
        "    def m(self):\n"
        "        pass\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_when_final_bound_to_another_module():
    # ``final`` is imported from a DIFFERENT module, so a bare ``@final`` would not
    # be ``typing.final`` — refuse (no fresh import would override a real binding).
    src = (
        "from foo import final\n"
        "\n"
        "\n"
        "class C:\n"
        "    def m(self):\n"
        "        pass\n"
    )
    assert add_final_method_decorator(src) is None


def test_refuses_syntax_error():
    assert add_final_method_decorator("def (:\n") is None


def test_finalizable_methods_empty_on_syntax_error():
    assert finalizable_methods("class C(:\n") == []


def test_no_methods_is_noop():
    assert add_final_method_decorator("class C:\n    x = 1\n") is None


def test_module_with_no_class_is_noop():
    assert add_final_method_decorator("def f():\n    return 1\n") is None


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_noop():
    once = add_final_method_decorator(_LEAF)
    assert once is not None
    assert add_final_method_decorator(once) is None  # 2nd run = byte-identical no-op


def test_deterministic_across_two_runs():
    a = add_final_method_decorator(_LEAF)
    b = add_final_method_decorator(_LEAF)
    assert a is not None and a == b


# --- registration / reachability --------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "seal-final-method" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["seal-final-method"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "seal-final-method"


def test_facet_reachability_parity_invariant_holds():
    # The standing 1:1 invariant: the facet map reaches EXACTLY the registered
    # objectives. Adding this objective to BOTH sides keeps the equality.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_substring_order_safe():
    # The new key must be neither a substring of, nor contain, any other key (with
    # a different objective) — else the first-match scan would mis-route.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    keys = list(FACET_OBJECTIVE_MAP)
    assert _PHRASE in keys
    for other in keys:
        if other == _PHRASE:
            continue
        assert _PHRASE not in other, f"{_PHRASE!r} is a substring of {other!r}"
        assert other not in _PHRASE, f"{other!r} is a substring of {_PHRASE!r}"


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "seal-final-method" in buckets["CONCRETE"]
    # No stale manifest name (a name with no live objective) was introduced.
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_extension_points_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["extension points"]
    assert _PHRASE in ladder
    assert ladder[0] == "the hook interface"  # originals still lead


# --- the plan: a never-overridden method gets @final -------------------------

# A PRIVATE class with one method: not public surface, so the objective (which turns
# the public-surface refusal ON) still seals the method.
_LEAF_PRIV = (
    '"""A service module."""\n'
    "\n"
    "\n"
    "class _Service:\n"
    "    def commit(self) -> int:\n"
    "        return 1\n"
)


def test_plan_lands_final(tmp_path: Path):
    _project(tmp_path, "app/svc.py", _LEAF_PRIV)
    plan = plan_seal_final_method(str(tmp_path), "app/svc.py")
    assert plan.ok
    new = plan.new_contents["app/svc.py"]
    assert "    @final" in new
    assert "from typing import final" in new
    assert plan.originals["app/svc.py"] == _LEAF_PRIV  # original captured for rollback
    assert plan.edits_by_file["app/svc.py"] == 1


def test_plan_uses_whole_project_subclass_scan(tmp_path: Path):
    # The method is never overridden in its OWN module, but a SIBLING module
    # overrides it — the whole-project scan must refuse.
    _project(tmp_path, "app/svc.py",
             "class Base:\n    def run(self):\n        return 1\n")
    _project(tmp_path, "app/other.py",
             "from app.svc import Base\n\n\nclass Sub(Base):\n    def run(self):\n        return 2\n")
    plan = plan_seal_final_method(str(tmp_path), "app/svc.py")
    assert not plan.new_contents  # refused by the cross-module override


def test_plan_refuses_already_final(tmp_path: Path):
    _project(tmp_path, "app/svc.py",
             "from typing import final\n\n\nclass C:\n    @final\n    def m(self):\n        pass\n")
    assert not plan_seal_final_method(str(tmp_path), "app/svc.py").new_contents


def test_plan_refuses_protocol_in_module(tmp_path: Path):
    _project(tmp_path, "app/iface.py",
             "from typing import Protocol\n\n\nclass P(Protocol):\n    def run(self):\n        ...\n")
    assert not plan_seal_final_method(str(tmp_path), "app/iface.py").new_contents


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _LEAF)
    assert not plan_seal_final_method(str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _LEAF)
    assert not plan_seal_final_method(str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_seal_final_method(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_lands_final_and_keeps_green(tmp_path: Path):
    # A method of a PRIVATE (underscore-prefixed) class in a package module: the
    # class is NOT public surface, so the project-own subclass scan is authoritative
    # and the method seal lands. (The public-surface refusal — added below — protects
    # only methods of published API classes.)
    _suite_project(tmp_path)
    src = (
        '"""A service module."""\n'
        "\n"
        "\n"
        "class _Service:\n"
        "    def commit(self) -> int:\n"
        "        return 1\n"
    )
    (tmp_path / "app" / "svc.py").write_text(src, encoding="utf-8")
    (tmp_path / "tests" / "test_svc.py").write_text(
        "from app.svc import _Service\n"
        "def test_commit():\n"
        "    assert _Service().commit() == 1\n"
        "def test_final_flag():\n"
        "    assert _Service.commit.__final__ is True\n",
        encoding="utf-8")

    plan = plan_seal_final_method(str(tmp_path), "app/svc.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "svc.py").read_text(encoding="utf-8")
    assert "    @final" in landed  # the decorator LANDED on the method
    assert "from typing import final" in landed
    # Behaviour preserved (proven green by the apply gate running the tests above):
    # the method still returns 1 and now carries ``__final__``.
    assert "def commit(self) -> int:" in landed


def test_never_fake_green_overridden_method_is_not_sealed(tmp_path: Path):
    # never-fake-green, STRUCTURAL form. ``@typing.final`` on a method is a pure
    # runtime no-op, so sealing an OVERRIDDEN method would NOT break the suite — it
    # would stay green on a FALSE "final" claim (a type checker would later reject
    # the override). The honesty guard is therefore the whole-project subclass-method
    # scan, not the suite: ``_Base.run`` is provably overridden by ``_Sub.run``, so
    # the engine REFUSES to seal it. The no-op decorator can never land on a
    # wrongly-claimed-final method. (PRIVATE classes, so the public-surface refusal
    # does not also fire — this test isolates the OVERRIDE guard.)
    src = (
        "class _Base:\n"
        "    def run(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "class _Sub(_Base):\n"
        "    def run(self):\n"
        "        return 2\n"
    )
    _project(tmp_path, "app/hier.py", src)
    plan = plan_seal_final_method(str(tmp_path), "app/hier.py")
    # A rewrite IS proposed (the leaf ``_Sub.run`` is sealable) ...
    assert plan.ok
    landed = plan.new_contents["app/hier.py"]
    # ... but ``_Base.run`` (overridden) is NEVER sealed — only the leaf method is.
    assert _final_method_names(landed) == {"_Sub.run"}
    assert "@final\n    def run(self):\n        return 1" not in landed  # false claim never lands


def test_never_fake_green_conservative_ambiguity_refusal(tmp_path: Path):
    # never-fake-green, CONSERVATIVE-AMBIGUITY form. A SAME-NAMED but unrelated class
    # ``Worker`` lives in another module and overrides ``run`` under ITS OWN base
    # ``Base`` (a different ``Base`` by identity, but the SAME NAME). Because the
    # subclass scan is purely by NAME, ``Base.run`` here is conservatively treated as
    # potentially overridden and REFUSED — over-refusal is SAFE (we just do not seal),
    # the asymmetry the spec calls for. No false "final" is ever landed under
    # ambiguity.
    base = "class Base:\n    def run(self):\n        return 1\n"
    other = (
        "class Base:\n"            # same NAME, unrelated class in another module
        "    pass\n"
        "\n"
        "\n"
        "class Worker(Base):\n"
        "    def run(self):\n"
        "        return 7\n"
    )
    _project(tmp_path, "app/svc.py", base)
    _project(tmp_path, "app/worker.py", other)
    plan = plan_seal_final_method(str(tmp_path), "app/svc.py")
    # Conservatively refused: a same-named subclass defines ``run`` (over-refuse,
    # never a wrong seal).
    assert not plan.new_contents


# --- FIX 1: a TEST-FILE override is a REAL one @final breaks for a type checker --

def test_fix1_not_sealed_when_overridden_only_in_a_test_file(tmp_path: Path):
    # FIX 1 (soundness, test-INCLUSIVE scan). ``@typing.final`` on a method is a pure
    # runtime no-op, so a method overridden ONLY in a test (a mock / fake subclass)
    # stays GREEN even though a TYPE CHECKER would reject that override once the
    # method is sealed — a false "final" the pytest suite can NEVER catch. The plan
    # now scans EVERY module (``all_module_sources``), tests INCLUDED, so the
    # test-only override is seen and the seal is REFUSED. (Under the old
    # tests-EXCLUDING ``project_sources`` scan the mock override was invisible and
    # ``Service.run`` was wrongly sealed.)
    _project(tmp_path, "app/svc.py",
             "class Service:\n    def run(self):\n        return 1\n")
    _project(tmp_path, "tests/test_svc.py",
             "from app.svc import Service\n\n\n"
             "class FakeService(Service):\n    def run(self):\n        return 2\n")
    plan = plan_seal_final_method(str(tmp_path), "app/svc.py")
    assert not plan.new_contents  # the test-only override forbids the seal


def test_fix1_method_with_no_test_override_still_seals(tmp_path: Path):
    # FIX 1 must not over-refuse: a (PRIVATE-class) method merely CALLED (not
    # overridden) in a test STILL seals under the test-inclusive scan — the test file
    # contributes no overriding subclass, so no override name is recorded. (Private
    # class, so the public-surface refusal does not fire either.)
    _project(tmp_path, "app/svc.py", _LEAF_PRIV)
    _project(tmp_path, "tests/test_svc.py",
             "from app.svc import _Service\n\n\n"
             "def test_commit():\n    assert _Service().commit() == 1\n")
    plan = plan_seal_final_method(str(tmp_path), "app/svc.py")
    assert plan.ok
    assert "@final" in plan.new_contents["app/svc.py"]
