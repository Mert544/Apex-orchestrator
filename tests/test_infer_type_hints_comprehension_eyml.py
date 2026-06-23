"""infer-type-hints — sound RETURN inference for COMPREHENSIONS and COLLECTION
CONSTRUCTORS, syntax-determined shapes layered on the existing return-value oracle.

These shapes are SOUND UNCONDITIONALLY because the type is fixed by the node's
SHAPE alone, regardless of any element/value types:

  - a comprehension's container type is fixed by its node kind:
    ``return [ ... for ... ]`` (``ast.ListComp``) ⇒ ``list``,
    ``return { ... for ... }`` (``ast.SetComp``) ⇒ ``set``,
    ``return { k: v for ... }`` (``ast.DictComp``) ⇒ ``dict`` — classified by the
    context-free literal oracle (:func:`_literal_type` via ``_DISPLAY_TYPES``), so
    each composes recursively with ternary/binop rules;
  - a ``ast.GeneratorExp`` (``return ( ... for ... )``) yields a GENERATOR object,
    NOT a concrete ``list``/``set``, so it is deliberately ABSENT from the display
    table and stays REFUSED (the locked exclusion);
  - a collection-constructor builtin returns its OWN type regardless of args:
    ``list(...)`` ⇒ ``list``, ``dict(...)`` ⇒ ``dict``, ``set(...)`` ⇒ ``set``,
    ``tuple(...)`` ⇒ ``tuple``, ``frozenset(...)`` ⇒ ``frozenset`` — handled by the
    FIXED-result builtin rule (:func:`_builtin_call_returns_type`).

The LOCKED soundness refusals are preserved through the same machinery: a
GeneratorExp refuses; a constructor whose NAME is SHADOWED in the function scope
(``list = ...`` then ``return list(x)``) no longer resolves to the builtin and so
refuses (the existing shadowing guard); and the ELEMENT/VALUE types are never
inferred — only the container type (``list`` for ``[str(x) for x in xs]``, never
``list[str]``). Because every rule routes through the same return-value oracle, it
composes with ternary/recursion: a ternary whose BOTH branches are list
comprehensions lands ``-> list``. A fake-green canary proves the accept path
annotates the REAL inferred type (``list`` vs ``dict`` vs ``set`` produce DISTINCT
annotations, never a hardcoded one), and a determinism + byte-identical check pins
input → output stability.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms.type_annotations import (
    _builtin_call_returns_type,
    _infer_return_type,
    _literal_type,
    _return_value_type,
    infer_annotations,
)


# --- comprehensions land their container type --------------------------------

def test_infers_list_from_list_comprehension():
    src = "def f(xs):\n    return [x for x in xs]\n"
    assert infer_annotations(src) == (
        "def f(xs) -> list:\n    return [x for x in xs]\n")


def test_infers_set_from_set_comprehension():
    src = "def f(xs):\n    return {x for x in xs}\n"
    assert infer_annotations(src) == (
        "def f(xs) -> set:\n    return {x for x in xs}\n")


def test_infers_dict_from_dict_comprehension():
    src = "def f(xs):\n    return {k: v for k, v in xs}\n"
    assert infer_annotations(src) == (
        "def f(xs) -> dict:\n    return {k: v for k, v in xs}\n")


def test_infers_list_from_comprehension_with_condition():
    # The comprehension's element/condition expressions do not affect the
    # container type — the node kind alone fixes ``list``.
    src = "def f(xs):\n    return [x * 2 for x in xs if x]\n"
    assert infer_annotations(src) == (
        "def f(xs) -> list:\n    return [x * 2 for x in xs if x]\n")


# --- collection-constructor builtins land their own type ---------------------

def test_infers_list_from_list_constructor():
    src = "def f(x):\n    return list(x)\n"
    assert infer_annotations(src) == "def f(x) -> list:\n    return list(x)\n"


def test_infers_dict_from_dict_constructor():
    src = "def f(x):\n    return dict(x)\n"
    assert infer_annotations(src) == "def f(x) -> dict:\n    return dict(x)\n"


def test_infers_set_from_set_constructor():
    src = "def f(x):\n    return set(x)\n"
    assert infer_annotations(src) == "def f(x) -> set:\n    return set(x)\n"


def test_infers_tuple_from_tuple_constructor():
    src = "def f(x):\n    return tuple(x)\n"
    assert infer_annotations(src) == "def f(x) -> tuple:\n    return tuple(x)\n"


def test_infers_frozenset_from_frozenset_constructor():
    src = "def f(x):\n    return frozenset(x)\n"
    assert infer_annotations(src) == (
        "def f(x) -> frozenset:\n    return frozenset(x)\n")


def test_infers_list_from_constructor_no_args():
    # ``list()`` returns a list regardless of (here, no) args.
    src = "def f():\n    return list()\n"
    assert infer_annotations(src) == "def f() -> list:\n    return list()\n"


# --- composition: ternary of two list comprehensions -> list -----------------

def test_infers_list_from_ternary_with_both_list_comp_branches():
    # Composition proof: each branch recurses through the FULL return-value
    # oracle, so two provably-``list`` comprehension branches prove the ternary
    # ⇒ ``list``. This pins that comprehensions compose with the ternary rule.
    src = "def f(c, a, b):\n    return [x for x in a] if c else [y for y in b]\n"
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(c, a, b) -> list:")


# --- refusals (the LOCKED soundness rules, preserved) ------------------------

def test_refuses_generator_expression():
    # A generator expression yields a GENERATOR object, NOT a list/set — it is
    # deliberately absent from the display table and stays refused.
    src = "def f(xs):\n    return (x for x in xs)\n"
    assert infer_annotations(src) is None


def test_refuses_shadowed_list_constructor():
    # ``list`` is rebound in the function's own scope, so ``list(x)`` no longer
    # resolves to the builtin — the shadowing guard refuses.
    src = "def f(x):\n    list = something\n    return list(x)\n"
    assert infer_annotations(src) is None


def test_refuses_shadowed_dict_and_set_constructors():
    # The shadowing guard applies to every constructor name.
    for name in ("dict", "set", "tuple", "frozenset"):
        src = f"def f(x):\n    {name} = something\n    return {name}(x)\n"
        assert infer_annotations(src) is None


def test_refuses_attribute_constructor_call():
    # ``obj.list(...)`` is a DIFFERENT, user-defined callable, not the builtin —
    # a non-Name callee refuses.
    src = "def f(obj, x):\n    return obj.list(x)\n"
    assert infer_annotations(src) is None


def test_element_types_are_not_inferred_only_container():
    # SOUNDNESS: only the CONTAINER type is inferred, never the element/value
    # type. A list comprehension of ``str(x)`` lands ``-> list`` (a bare
    # container), never ``list[str]``.
    src = "def f(xs):\n    return [str(x) for x in xs]\n"
    out = infer_annotations(src)
    assert out == "def f(xs) -> list:\n    return [str(x) for x in xs]\n"
    assert "[" not in out.split("->", 1)[1].split(":", 1)[0]  # no list[...] param


def test_refuses_disagreeing_comprehension_types():
    # A list comprehension and a set comprehension in two returns disagree on
    # type ⇒ the function-level resolver refuses (no single certain type).
    src = (
        "def f(c, xs):\n"
        "    if c:\n"
        "        return [x for x in xs]\n"
        "    return {x for x in xs}\n"
    )
    assert infer_annotations(src) is None


# --- direct helper unit checks -----------------------------------------------

def test_literal_type_routes_list_comprehension():
    node = ast.parse("[x for x in y]", mode="eval").body
    assert _literal_type(node) == "list"


def test_literal_type_routes_set_comprehension():
    node = ast.parse("{x for x in y}", mode="eval").body
    assert _literal_type(node) == "set"


def test_literal_type_routes_dict_comprehension():
    node = ast.parse("{k: v for k, v in y}", mode="eval").body
    assert _literal_type(node) == "dict"


def test_literal_type_refuses_generator_expression():
    node = ast.parse("(x for x in y)", mode="eval").body
    assert _literal_type(node) is None


def test_builtin_helper_accepts_each_constructor():
    expected = {
        "list": "list", "dict": "dict", "set": "set",
        "tuple": "tuple", "frozenset": "frozenset",
    }
    for name, want in expected.items():
        node = ast.parse(f"{name}(x)", mode="eval").body
        assert _builtin_call_returns_type(node, frozenset()) == want


def test_builtin_helper_refuses_shadowed_constructor():
    node = ast.parse("list(x)", mode="eval").body
    assert _builtin_call_returns_type(node, frozenset()) == "list"
    # Shadowed in scope -> no longer the builtin -> refuse.
    assert _builtin_call_returns_type(node, frozenset({"list"})) is None


def test_return_value_type_routes_comprehension_and_constructor():
    comp = ast.parse("{x for x in y}", mode="eval").body
    assert _return_value_type(comp, frozenset()) == "set"
    ctor = ast.parse("tuple(x)", mode="eval").body
    assert _return_value_type(ctor, frozenset()) == "tuple"


def test_infer_return_type_uses_comprehension():
    fn = ast.parse("def f(xs):\n    return {k: v for k, v in xs}\n").body[0]
    assert _infer_return_type(fn) == "dict"


# --- fake-green canary + soundness made concrete -----------------------------

def test_list_dict_set_annotations_are_distinct_not_hardcoded():
    # FAKE-GREEN CANARY: the accept path must annotate the ACTUAL inferred type,
    # not a hardcoded constant. A list/dict/set comprehension therefore produce
    # THREE DISTINCT annotations.
    list_out = infer_annotations("def f(xs):\n    return [x for x in xs]\n")
    dict_out = infer_annotations("def f(xs):\n    return {k: v for k, v in xs}\n")
    set_out = infer_annotations("def f(xs):\n    return {x for x in xs}\n")
    assert list_out is not None and "-> list:" in list_out
    assert dict_out is not None and "-> dict:" in dict_out
    assert set_out is not None and "-> set:" in set_out
    assert len({list_out, dict_out, set_out}) == 3  # not one hardcoded annotation


def test_constructor_annotation_preserves_parse_and_runtime_value():
    # The annotation adds ``-> T`` TEXT only and never changes runtime behaviour.
    # The annotated source must still parse, and the runtime return value must be
    # byte-identical to the original's.
    src = "def f(x):\n    return list(x)\n"
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f(x) -> list:")

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)  # parses (canary) + runs

    assert orig_ns["f"]([1, 2]) == new_ns["f"]([1, 2]) == [1, 2]
    assert "return" in new_ns["f"].__annotations__
    assert "list" in str(new_ns["f"].__annotations__.get("return"))


def test_comprehension_return_inference_is_deterministic():
    for src in (
        "def f(xs):\n    return [x for x in xs]\n",
        "def f(xs):\n    return {x for x in xs}\n",
        "def f(xs):\n    return {k: v for k, v in xs}\n",
        "def f(x):\n    return frozenset(x)\n",
    ):
        assert infer_annotations(src) == infer_annotations(src)
    # And a refused shape (generator expression) is stably refused.
    refused = "def f(xs):\n    return (x for x in xs)\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_file_without_qualifying_comprehension_is_byte_identical():
    # A module with NO qualifying provable annotation is unchanged (None): a
    # generator expression alone adds nothing.
    src = "def f(xs):\n    return (x for x in xs)\n"
    assert infer_annotations(src) is None
    # An already-annotated comprehension return is never overwritten.
    annotated = "def f(xs) -> object:\n    return [x for x in xs]\n"
    assert infer_annotations(annotated) is None


def test_comprehension_empty_and_unparseable_paths():
    # Edge/empty paths: an empty module and an unparseable one both yield None.
    assert infer_annotations("") is None
    assert infer_annotations("def f(xs):\n    return [x for x in xs\n") is None
