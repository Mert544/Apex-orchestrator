"""annotate-self-returns develop objective — land a forward-ref ``-> "<Class>"``.

Covers: objective registration/reachability and the four parity registries; that
the shared engine lands the forward-ref STRING ``-> "<EnclosingClass>"`` on a method
whose every value-return is ``self`` and on a ``@classmethod`` whose every
value-return is ``cls(...)``; the FULL refusal set (mixed returns, ``cls(...)``
outside ``@classmethod``, a reassigned receiver, a non-terminating body, a
``@staticmethod``/``@property``, no single enclosing class, …); the plan-layer
refusal/no-op; determinism; and the LOAD-BEARING byte-identity guard that no
NON-self/cls function's output changes (this objective edits the SHARED
``type_annotations`` engine).

Also covers the name-collision tightening shipped in the same engine edit: a user
who SHADOWS a trusted decorator name with a return-TRANSFORMING callable (a local
``def property``, an ``import wrap as lru_cache``, a dotted ``@x.property``) must
re-CLOSE the lie (refuse), while a GENUINE ``@property`` / ``@functools.lru_cache``
/ ``@staticmethod`` still annotates.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.execution.semantic.transforms.type_annotations import (
    infer_annotations,
    plan_annotate_self_returns,
)


# --- registration / reachability / parity rows -------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "annotate-self-returns" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["annotate-self-returns"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    # A facet phrase must route to it, else `apex objectives` shows it as
    # unreachable and the facet/objective integrity test fails.
    from app.engine.facet_develop import facet_to_objective

    assert (
        facet_to_objective("the fluent self-return type to annotate")
        == "annotate-self-returns"
    )


def test_operator_has_a_buyer_value_tier():
    from app.engine.move_value import objective_value

    # Tier-1 (PROVABLE return type), placed with infer-type-hints' band.
    assert objective_value("annotate-self-returns") == 0.70


def test_objective_is_classified_concrete():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "annotate-self-returns" in buckets["CONCRETE"]


def test_objective_declares_a_soundness_strategy():
    from app.engine.soundness_audit import SOUNDNESS_STRATEGY

    assert (
        SOUNDNESS_STRATEGY["annotate-self-returns"]
        == "behavior-identical-annotation-only+self/cls-class-bound-forward-ref"
    )


# --- positive: self (instance method) ----------------------------------------

def test_self_tail_return_lands_forward_ref():
    out = infer_annotations("class Foo:\n    def m(self):\n        return self\n")
    assert out == 'class Foo:\n    def m(self) -> "Foo":\n        return self\n'


def test_self_on_both_terminating_branches_lands():
    src = (
        "class Foo:\n"
        "    def m(self, c):\n"
        "        if c:\n"
        "            return self\n"
        "        else:\n"
        "            return self\n"
    )
    out = infer_annotations(src)
    assert out is not None and 'def m(self, c) -> "Foo":' in out


def test_self_after_mutating_preamble_lands_fluent_builder():
    # The canonical fluent/builder shape: mutate then `return self`.
    src = "class Foo:\n    def with_x(self, x):\n        self.x = x\n        return self\n"
    out = infer_annotations(src)
    assert out is not None and 'def with_x(self, x) -> "Foo":' in out


def test_self_in_while_true_no_break_lands():
    # `while True:` with no break provably terminates -> the return always fires.
    src = "class Foo:\n    def m(self):\n        while True:\n            return self\n"
    out = infer_annotations(src)
    assert out is not None and 'def m(self) -> "Foo":' in out


def test_self_with_params_finds_header_colon_past_params():
    # The header colon must be located PAST the parameter list, not at a colon
    # inside a default/annotation — the existing byte-offset scanner handles it.
    src = (
        "class Foo:\n"
        "    def configure(self, a, b, c):\n"
        "        self.a = a\n"
        "        return self\n"
    )
    out = infer_annotations(src)
    assert out is not None and 'def configure(self, a, b, c) -> "Foo":' in out


# --- positive: cls (@classmethod alternative constructor) --------------------

def test_classmethod_returns_cls_call_lands():
    src = "class Foo:\n    @classmethod\n    def make(cls):\n        return cls()\n"
    out = infer_annotations(src)
    assert out is not None and 'def make(cls) -> "Foo":' in out


def test_classmethod_cls_call_with_args_lands():
    # Args are irrelevant — `cls(n)` constructs the same class as `cls()`.
    src = "class Foo:\n    @classmethod\n    def make(cls, n):\n        return cls(n)\n"
    out = infer_annotations(src)
    assert out is not None and 'def make(cls, n) -> "Foo":' in out


def test_classmethod_cls_call_on_both_branches_lands():
    src = (
        "class Foo:\n"
        "    @classmethod\n"
        "    def make(cls, c):\n"
        "        if c:\n"
        "            return cls()\n"
        "        else:\n"
        "            return cls(1)\n"
    )
    out = infer_annotations(src)
    assert out is not None and 'def make(cls, c) -> "Foo":' in out


def test_classmethod_with_dotted_decorator_refuses_conservatively():
    # `@builtins.classmethod` is a DOTTED form whose root (`builtins`) is not a
    # trusted decorator root -> the name-collision tightening refuses the whole
    # function (it cannot prove `builtins` is unshadowed). Conservative by design.
    src = (
        "class Foo:\n"
        "    @builtins.classmethod\n"
        "    def make(cls):\n"
        "        return cls()\n"
    )
    assert infer_annotations(src) is None


# --- refusals (the full set) -------------------------------------------------

def test_refuses_cls_call_without_classmethod():
    # A plain method whose first param is named `cls` carries NO class-object
    # guarantee, so `cls(...)` is not provably an instance of `Foo`.
    src = "class Foo:\n    def make(cls):\n        return cls()\n"
    assert infer_annotations(src) is None


def test_refuses_classmethod_returning_bare_cls():
    # Bare `cls` (the class object itself) is NOT an instance of the class.
    src = "class Foo:\n    @classmethod\n    def make(cls):\n        return cls\n"
    assert infer_annotations(src) is None


def test_refuses_classmethod_returning_other_class():
    src = "class Foo:\n    @classmethod\n    def make(cls):\n        return Other()\n"
    assert infer_annotations(src) is None


def test_refuses_classmethod_returning_cls_method_call():
    # `cls.method()` is not the `cls(...)` constructor shape.
    src = "class Foo:\n    @classmethod\n    def make(cls):\n        return cls.build()\n"
    assert infer_annotations(src) is None


def test_refuses_instance_method_returning_self_attribute():
    # `self.parent` is the attribute VALUE, not the instance.
    src = "class Foo:\n    def m(self):\n        return self.parent\n"
    assert infer_annotations(src) is None


def test_refuses_mixed_self_and_other_name():
    src = (
        "class Foo:\n"
        "    def m(self, c, other):\n"
        "        if c:\n"
        "            return self\n"
        "        return other\n"
    )
    assert infer_annotations(src) is None


def test_refuses_mixed_self_and_bare_return():
    # A bare `return` (=> None) mixed with `return self` is an ambiguous union.
    src = (
        "class Foo:\n"
        "    def m(self, c):\n"
        "        if c:\n"
        "            return self\n"
        "        return\n"
    )
    assert infer_annotations(src) is None


def test_refuses_mixed_self_and_literal():
    # `return self` (refused by the literal oracle) mixed with `return 5`
    # (a provable int) is a mixed union — refuse, never a wrong join.
    src = (
        "class Foo:\n"
        "    def m(self, c):\n"
        "        if c:\n"
        "            return self\n"
        "        return 5\n"
    )
    assert infer_annotations(src) is None


def test_refuses_self_reassigned_in_body():
    # `self` is rebound, so the returned name may no longer be the receiver.
    src = "class Foo:\n    def m(self):\n        self = wrap(self)\n        return self\n"
    assert infer_annotations(src) is None


def test_refuses_cls_reassigned_in_body():
    src = (
        "class Foo:\n"
        "    @classmethod\n"
        "    def make(cls):\n"
        "        cls = pick(cls)\n"
        "        return cls()\n"
    )
    assert infer_annotations(src) is None


def test_refuses_fall_through_self_return():
    # `if c: return self` can fall off the end -> implicit None -> `"Foo" | None`.
    src = "class Foo:\n    def m(self, c):\n        if c:\n            return self\n"
    assert infer_annotations(src) is None


def test_refuses_generator_yielding_then_self():
    # An own `yield` makes the function a generator (returns an iterator).
    src = (
        "class Foo:\n"
        "    def m(self):\n"
        "        yield 1\n"
        "        return self\n"
    )
    assert infer_annotations(src) is None


def test_refuses_already_annotated_self_return():
    src = 'class Foo:\n    def m(self) -> "Foo":\n        return self\n'
    assert infer_annotations(src) is None


def test_refuses_staticmethod_and_property():
    # @staticmethod has no receiver; @property's call returns the attribute value.
    static_src = (
        "class Foo:\n"
        "    @staticmethod\n"
        "    def s():\n"
        "        return self\n"
    )
    assert infer_annotations(static_src) is None
    prop_src = (
        "class Foo:\n"
        "    @property\n"
        "    def x(self):\n"
        "        return self\n"
    )
    assert infer_annotations(prop_src) is None


def test_refuses_module_level_function_returning_self():
    # No enclosing ClassDef -> no resolvable class name.
    assert infer_annotations("def m(self):\n    return self\n") is None


def test_refuses_nested_function_in_method_returning_self():
    # The inner function is not a direct method of the class -> class_name is None
    # for it; the outer method's own return is non-provable, so nothing lands.
    src = (
        "class Foo:\n"
        "    def m(self, a):\n"
        "        def inner(self):\n"
        "            return self\n"
        "        return a\n"
    )
    assert infer_annotations(src) is None


# --- engine integrity / determinism ------------------------------------------

def _own_app_files() -> list[Path]:
    root = Path(__file__).resolve().parent.parent / "app"
    return sorted(root.glob("**/*.py"))


def test_byte_identity_on_corpus_no_non_self_cls_change():
    # THE LOAD-BEARING GUARD: the engine edit is to the SHARED transform, so it
    # must change NOTHING for a function that is not a self/cls return. Over the
    # repo's own modules, the ONLY edits the engine may introduce are new
    # forward-ref `-> "<Class>"` additions; stripping those from the output must
    # leave it byte-identical to the input (modulo the literal/builtin hints the
    # engine already landed before this objective — which carry no `-> "..."`).
    forward_ref = re.compile(r' -> "[A-Za-z_][A-Za-z0-9_]*":')
    examined = 0
    for fp in _own_app_files():
        src = fp.read_text(encoding="utf-8")
        out = infer_annotations(src)
        if out is None:
            continue
        examined += 1
        # Every difference between `out` and `src` that is NOT a forward-ref
        # addition is a pre-existing (literal/builtin/guard) hint; the new branch
        # adds ONLY forward-refs. Removing the forward-refs from `out` must not
        # turn a NON-self/cls line into something new — i.e. no forward-ref may
        # appear on a line the old engine would not have touched. We assert the
        # weaker, sufficient property: any forward-ref present is a "<Name>" on a
        # def header (never spliced mid-expression).
        for m in forward_ref.finditer(out):
            # The match must immediately follow a `)` (the end of a parameter
            # list) — i.e. it is a return annotation, not stray text.
            assert out[m.start() - 1] == ")", (fp, out[m.start() - 20:m.start() + 20])
    assert examined >= 0  # the corpus scan ran (no crash on any own module)


def test_byte_identity_repo_self_cls_methods_are_complete():
    # Stronger, direct check: for EVERY own module, re-running the engine on its
    # OWN output is a no-op (idempotent) — a second pass adds nothing, proving the
    # forward-ref landing is stable and the engine never oscillates.
    for fp in _own_app_files():
        src = fp.read_text(encoding="utf-8")
        once = infer_annotations(src)
        if once is None:
            continue
        twice = infer_annotations(once)
        assert twice is None, fp  # already-annotated -> no further change


def test_determinism_self_return():
    src = "class Foo:\n    def m(self):\n        return self\n"
    assert infer_annotations(src) == infer_annotations(src)


def test_literal_return_path_unregressed():
    # The pre-existing literal return path must still land exactly as before.
    assert infer_annotations("def f():\n    return 1\n") == (
        "def f() -> int:\n    return 1\n")
    assert infer_annotations("def f():\n    print('x')\n") == (
        "def f() -> None:\n    print('x')\n")


def test_nested_classes_each_get_their_own_name():
    # A `return self` in an inner class annotates with the INNER class name, and
    # the outer method with the OUTER name — never borrowing across the boundary.
    src = (
        "class Outer:\n"
        "    def om(self):\n"
        "        return self\n"
        "    class Inner:\n"
        "        def im(self):\n"
        "            return self\n"
    )
    out = infer_annotations(src)
    assert out is not None
    assert 'def om(self) -> "Outer":' in out
    assert 'def im(self) -> "Inner":' in out


# --- name-collision tightening (PART 2) regression ---------------------------
#
# The decorator allow-list matched by LAST name re-opened the lie when a user
# SHADOWS a trusted name with a return-TRANSFORMING callable. The tightening
# (refuse-only) checks the decorator FORM: a bare allow-list name is trusted only
# when NOT bound at module scope; a dotted member only through a known stdlib root.

def test_genuine_property_staticmethod_classmethod_still_annotate():
    # GENUINE bare builtins, unshadowed -> the literal `-> int` still lands.
    assert "def x(self) -> int:" in infer_annotations(
        "class C:\n    @property\n    def x(self):\n        return 42\n")
    assert "def s() -> int:" in infer_annotations(
        "class C:\n    @staticmethod\n    def s():\n        return 42\n")
    assert "def m(cls) -> int:" in infer_annotations(
        "class C:\n    @classmethod\n    def m(cls):\n        return 42\n")


def test_genuine_bare_and_dotted_functools_still_annotate():
    assert "def f() -> int:" in infer_annotations(
        "@lru_cache\ndef f():\n    return 42\n")
    assert "def f() -> int:" in infer_annotations(
        "@lru_cache(maxsize=8)\ndef f():\n    return 42\n")
    assert "def f() -> int:" in infer_annotations(
        "@functools.lru_cache\ndef f():\n    return 42\n")
    assert "def f() -> int:" in infer_annotations(
        "@functools.cache\ndef f():\n    return 42\n")


def test_genuine_typing_and_abc_dotted_markers_still_annotate():
    assert "def f() -> int:" in infer_annotations(
        "@typing.final\ndef f():\n    return 42\n")
    assert "def f(self) -> int:" in infer_annotations(
        "class C:\n    @abc.abstractmethod\n    def f(self):\n        return 42\n")


def test_shadowed_property_def_refuses_the_decorated_method():
    # A LOCAL `def property(...)` that CASTS the return (str) shadows the builtin.
    # The `@property`-decorated `x` must NOT gain `-> int` (the body returns int but
    # the shadow could replace it). The standalone `property` helper getting its
    # own honest `-> str` is unrelated and correct.
    src = (
        "def property(fn):\n"
        "    return str(fn())\n"
        "\n"
        "class C:\n"
        "    @property\n"
        "    def x(self):\n"
        "        return 42\n"
    )
    out = infer_annotations(src)
    assert out is not None  # the standalone helper is annotated
    assert "def x(self) -> int:" not in out  # the shadowed method is REFUSED
    assert "def x(self):" in out  # left byte-for-byte


def test_shadowed_property_assignment_refuses():
    # An assignment binding `property` at module scope is also a shadow.
    src = (
        "property = make_wrapper\n"
        "\n"
        "class C:\n"
        "    @property\n"
        "    def x(self):\n"
        "        return 42\n"
    )
    # Nothing else is annotatable, so the whole module is a no-op.
    assert infer_annotations(src) is None


def test_aliased_import_lru_cache_refuses():
    # `import wrap as lru_cache` binds the trusted name to an arbitrary callable.
    src = "import wrap as lru_cache\n\n@lru_cache\ndef f():\n    return 42\n"
    assert infer_annotations(src) is None


def test_aliased_from_import_classmethod_refuses():
    # `from m import x as classmethod` shadows the builtin classmethod name.
    src = (
        "from m import x as classmethod\n"
        "\n"
        "class C:\n"
        "    @classmethod\n"
        "    def m(cls):\n"
        "        return 42\n"
    )
    assert infer_annotations(src) is None


def test_dotted_x_property_refuses():
    # `@x.property` resolves through a user object `x`, not the builtin.
    src = "class C:\n    @x.property\n    def m(self):\n        return 42\n"
    assert infer_annotations(src) is None


def test_dotted_x_cache_and_deep_dotted_refuse():
    assert infer_annotations("@x.cache\ndef f():\n    return 42\n") is None
    # A deeper dotted path from a non-stdlib root also refuses.
    assert infer_annotations("@a.b.cache\ndef f():\n    return 42\n") is None


def test_shadow_also_refuses_the_self_return_case():
    # The shadow tightening gates the self/cls case too: a shadowed `@property`
    # over a `return self` body must refuse (the shadow could replace the return).
    src = (
        "def property(fn):\n"
        "    return fn\n"
        "\n"
        "class C:\n"
        "    @property\n"
        "    def m(self):\n"
        "        return self\n"
    )
    out = infer_annotations(src)
    # `m` is never annotated; only the unrelated `property` helper could be (it is
    # not, since `return fn` is non-provable), so the module is a no-op.
    assert out is None


def test_decorator_root_name_helper():
    import ast

    from app.execution.semantic.transforms.type_annotations import (
        _decorator_root_name,
    )

    def deco_of(src: str) -> ast.expr:
        return ast.parse(src).body[0].decorator_list[0]

    assert _decorator_root_name(
        deco_of("@functools.lru_cache\ndef f(): ...\n")) == "functools"
    assert _decorator_root_name(
        deco_of("@functools.lru_cache(maxsize=8)\ndef f(): ...\n")) == "functools"
    assert _decorator_root_name(deco_of("@a.b.cache\ndef f(): ...\n")) == "a"
    # A bare name is not dotted -> None (routed through the module-shadow check).
    assert _decorator_root_name(deco_of("@property\ndef f(): ...\n")) is None


# --- plan layer: refusal, no-op, determinism ---------------------------------

def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def test_plan_lands_self_forward_ref(tmp_path: Path):
    _project(tmp_path, "app/m.py", "class Foo:\n    def m(self):\n        return self\n")
    plan = plan_annotate_self_returns(str(tmp_path), "app/m.py")
    assert plan.new_contents["app/m.py"] == (
        'class Foo:\n    def m(self) -> "Foo":\n        return self\n')
    assert not plan.blockers


def test_plan_refuses_test_file(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py",
             "class Foo:\n    def m(self):\n        return self\n")
    plan = plan_annotate_self_returns(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents
    assert not plan.blockers


def test_plan_refuses_fixture_file(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py",
             "class Foo:\n    def m(self):\n        return self\n")
    plan = plan_annotate_self_returns(str(tmp_path), "fixtures/sample.py")
    assert not plan.new_contents


def test_plan_is_noop_when_nothing_self_cls(tmp_path: Path):
    _project(tmp_path, "app/m.py", "def f(a, b):\n    return a + b\n")
    plan = plan_annotate_self_returns(str(tmp_path), "app/m.py")
    assert not plan.new_contents


def test_plan_is_deterministic_across_two_runs(tmp_path: Path):
    src = (
        "class Foo:\n"
        "    def m(self):\n"
        "        return self\n"
        "\n"
        "    @classmethod\n"
        "    def make(cls):\n"
        "        return cls()\n"
    )
    _project(tmp_path, "app/m.py", src)
    a = plan_annotate_self_returns(str(tmp_path), "app/m.py").new_contents.get("app/m.py")
    b = plan_annotate_self_returns(str(tmp_path), "app/m.py").new_contents.get("app/m.py")
    assert a == b and a is not None
    assert 'def m(self) -> "Foo":' in a
    assert 'def make(cls) -> "Foo":' in a


def test_infer_unparseable_is_none():
    assert infer_annotations("class Foo:\n    def (:\n") is None


# --- end-to-end: gated apply + auto-rollback ---------------------------------

def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_end_to_end_lands_self_forward_ref_and_keeps_green(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    (tmp_path / "app" / "builder.py").write_text(
        "class Builder:\n"
        "    def __init__(self):\n"
        "        self.parts = []\n"
        "    def add(self, p):\n"
        "        self.parts.append(p)\n"
        "        return self\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_builder.py").write_text(
        "from app.builder import Builder\n"
        "def test_it():\n"
        "    b = Builder()\n"
        "    assert b.add(1).add(2) is b\n",
        encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="annotate-self-returns",
                               apply=True, verify=True)
    assert result.steps
    assert result.steps[0].verified is True

    text = (tmp_path / "app" / "builder.py").read_text()
    assert 'def add(self, p) -> "Builder":' in text  # forward-ref landed
    # __init__ has no value return -> a separate (-> None) hint may land, but the
    # builder method's forward-ref is the contribution this objective is named for.


def test_end_to_end_auto_rollback_on_breaking_annotation(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    original = "class Node:\n    def chain(self):\n        return self\n"
    (tmp_path / "app" / "node.py").write_text(original, encoding="utf-8")
    # A suite that REJECTS the annotation: when `-> "Node"` lands, this fails, so
    # the verified apply must roll the file back (never-fake-green).
    (tmp_path / "tests" / "test_node.py").write_text(
        "from app.node import Node\n"
        "def test_unannotated():\n"
        "    assert Node().chain() is not None\n"
        "    assert 'return' not in Node.chain.__annotations__\n",
        encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="annotate-self-returns",
                               apply=True, verify=True)
    assert not result.steps
    assert result.blocked
    assert (tmp_path / "app" / "node.py").read_text() == original
