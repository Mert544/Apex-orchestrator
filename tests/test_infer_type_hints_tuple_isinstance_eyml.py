"""infer-type-hints — sound PARAMETER inference from a STRICT one-element-tuple
``isinstance`` guard (``isinstance(x, (int,))``), the single-class shape spelled
with a trailing-comma tuple.

``isinstance(x, (int,))`` is EXACTLY ``isinstance(x, int)`` at runtime: a tuple of
classes succeeds iff ``x`` is an instance of ANY listed class, and a ONE-element
tuple lists exactly one. So an entry guard ``assert isinstance(x, (int,))`` (or
``if not isinstance(x, (int,)): raise``) enforces the SAME single bound as the bare
form — recording ``x: int`` only states the fact the runtime already enforces.
:func:`_isinstance_single_class` therefore unwraps a STRICT ``len == 1`` tuple to
its sole bare ``ast.Name`` and binds that class.

The Union refusal is preserved exactly where it must be: a MULTI-element tuple
(``isinstance(x, (int, float))``) stays REFUSED (it would need a ``Union``), an
EMPTY tuple ``()`` binds nothing, and a one-element tuple whose sole element is NOT
a bare known-builtin Name (``(numbers.Integral,)`` / ``(Foo,)``) is refused. A
fake-green canary proves the landed annotation changes no runtime value, and a
determinism test pins input → output stability.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms.type_annotations import (
    _isinstance_single_class,
    infer_annotations,
)


# --- the strict one-element tuple guard lands a param type -------------------

def test_infers_int_from_assert_isinstance_one_tuple():
    # ``assert isinstance(x, (int,))`` ≡ ``assert isinstance(x, int)`` -> x: int.
    src = "def f(x):\n    assert isinstance(x, (int,))\n    return x\n"
    assert infer_annotations(src) == (
        "def f(x: int):\n    assert isinstance(x, (int,))\n    return x\n")


def test_infers_str_from_if_not_isinstance_one_tuple_raise():
    src = (
        "def f(x):\n"
        "    if not isinstance(x, (str,)):\n"
        "        raise TypeError\n"
        "    return x\n"
    )
    assert infer_annotations(src) == (
        "def f(x: str):\n"
        "    if not isinstance(x, (str,)):\n"
        "        raise TypeError\n"
        "    return x\n"
    )


def test_infers_across_builtin_class_group_one_tuple():
    # The one-element-tuple form lands every known builtin class, same as bare.
    for cls in ("int", "float", "str", "bytes", "bool", "list", "dict", "tuple"):
        src = f"def f(x):\n    assert isinstance(x, ({cls},))\n    return None\n"
        out = infer_annotations(src)
        assert out is not None, cls
        assert out.startswith(f"def f(x: {cls})"), cls


def test_one_tuple_guard_composes_with_provable_return():
    # The one-tuple param guard AND a provable return (`len(x)` -> int) compose.
    src = "def f(x):\n    assert isinstance(x, (int,))\n    return len(x)\n"
    assert infer_annotations(src) == (
        "def f(x: int) -> int:\n    assert isinstance(x, (int,))\n    return len(x)\n")


def test_one_tuple_guard_in_and_conjunction():
    # A conjunction of one-tuple guards binds each param (the leaf accepts each).
    src = (
        "def h(x, y):\n"
        "    assert isinstance(x, (int,)) and isinstance(y, (str,))\n"
        "    return None\n"
    )
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def h(x: int, y: str)")


# --- the Union refusals stay intact (the whole point) ------------------------

def test_refuses_multi_element_tuple_of_classes():
    # LOCKED: a MULTI-element tuple is a Union bound, not a single type -> refuse.
    src = "def f(x):\n    assert isinstance(x, (int, float))\n    return x\n"
    assert infer_annotations(src) is None


def test_refuses_empty_tuple_of_classes():
    # An EMPTY tuple lists no class (``isinstance(x, ())`` is always False) -> it
    # binds nothing; strict ``len == 1`` refuses it.
    src = "def f(x):\n    assert isinstance(x, ())\n    return x\n"
    assert infer_annotations(src) is None


def test_refuses_one_tuple_with_non_name_element():
    # A one-element tuple whose sole element is a DOTTED class (not a bare Name)
    # is not a bare known-builtin type -> refuse conservatively.
    src = "def f(x):\n    assert isinstance(x, (numbers.Integral,))\n    return x\n"
    assert infer_annotations(src) is None


def test_refuses_one_tuple_with_unknown_bare_class():
    # A one-element tuple of an UNKNOWN bare Name (a possible user alias) -> refuse.
    src = "def f(x):\n    assert isinstance(x, (Foo,))\n    return x\n"
    assert infer_annotations(src) is None


def test_refuses_three_element_tuple_of_classes():
    # 3+ elements is still a Union -> refuse.
    src = "def f(x):\n    assert isinstance(x, (int, float, str))\n    return x\n"
    assert infer_annotations(src) is None


# --- direct helper unit checks -----------------------------------------------

def test_isinstance_single_class_accepts_one_element_tuple():
    node = ast.parse("isinstance(x, (int,))", mode="eval").body
    assert _isinstance_single_class(node) == ("x", "int")


def test_isinstance_single_class_still_accepts_bare_name():
    # The original bare-Name form is unchanged (byte-identical behaviour).
    node = ast.parse("isinstance(x, int)", mode="eval").body
    assert _isinstance_single_class(node) == ("x", "int")


def test_isinstance_single_class_refuses_multi_element_tuple():
    node = ast.parse("isinstance(x, (int, float))", mode="eval").body
    assert _isinstance_single_class(node) is None


def test_isinstance_single_class_refuses_empty_tuple():
    node = ast.parse("isinstance(x, ())", mode="eval").body
    assert _isinstance_single_class(node) is None


def test_isinstance_single_class_refuses_one_tuple_non_name():
    node = ast.parse("isinstance(x, (numbers.Integral,))", mode="eval").body
    assert _isinstance_single_class(node) is None


def test_isinstance_single_class_refuses_one_tuple_unknown_name():
    node = ast.parse("isinstance(x, (Foo,))", mode="eval").body
    assert _isinstance_single_class(node) is None


# --- behaviour preservation (fake-green canary) + soundness made concrete ----

def test_one_tuple_guard_preserves_parse_and_runtime_value():
    # FAKE-GREEN CANARY: the annotation adds `: T` TEXT only and never changes
    # runtime behaviour; the annotated source must still parse and return the same.
    src = (
        "def f(x):\n"
        "    if not isinstance(x, (int,)):\n"
        "        raise TypeError\n"
        "    return x + 1\n"
    )
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f(x: int):")

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)  # parses (canary) + runs

    assert orig_ns["f"](5) == new_ns["f"](5) == 6  # value unchanged
    assert "int" in str(new_ns["f"].__annotations__.get("x"))


def test_one_tuple_guard_enforces_type_so_annotation_cannot_lie():
    # SOUNDNESS made concrete: ``isinstance(x, (int,))`` REJECTS a wrong-typed arg
    # at runtime, identical to the bare form, so ``x: int`` records an enforced
    # fact — there is no input for which the annotation is false-but-green.
    src = (
        "def f(x):\n"
        "    if not isinstance(x, (int,)):\n"
        "        raise TypeError\n"
        "    return x\n"
    )
    out = infer_annotations(src)
    assert out is not None

    ns: dict[str, object] = {}
    exec(compile(out, "<n>", "exec"), ns)
    assert ns["f"](3) == 3
    raised = False
    try:
        ns["f"]("not an int")
    except TypeError:
        raised = True
    assert raised  # a non-int is rejected, so `x: int` never contradicts a run


def test_one_tuple_guard_inference_is_deterministic():
    for src in (
        "def f(x):\n    assert isinstance(x, (str,))\n    return x\n",
        "def f(x):\n    if not isinstance(x, (int,)):\n        raise TypeError\n    return x\n",
    ):
        assert infer_annotations(src) == infer_annotations(src)
    # And a refused (multi-element) shape is stably refused.
    refused = "def f(x):\n    assert isinstance(x, (int, float))\n    return x\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_one_tuple_guard_empty_and_unparseable_paths():
    # Edge/empty paths: an empty module and an unparseable one both yield None.
    assert infer_annotations("") is None
    assert infer_annotations("def f(x:\n    assert isinstance(x, (int,))\n") is None
