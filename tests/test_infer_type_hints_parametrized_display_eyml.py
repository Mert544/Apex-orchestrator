"""infer-type-hints — PARAMETRIZED return types for fully-LITERAL displays,
layered on the existing context-free literal oracle (:func:`_literal_type`).

A literal display whose every part proves to a CONSISTENT type via the same
recursive oracle is annotated with a PEP 585 builtin generic instead of the bare
container it used to collapse to:

  - ``return [1, 2]`` ⇒ ``list[int]``, ``return ['a', 'b']`` ⇒ ``list[str]``;
  - ``return {1, 2}`` ⇒ ``set[int]``;
  - ``return {1: 'a', 2: 'b'}`` ⇒ ``dict[int, str]`` (all keys ONE type AND all
    values ONE type);
  - ``return (1, 'a')`` ⇒ ``tuple[int, str]`` — a FIXED-length HETEROGENEOUS
    tuple, one slot per element;
  - nested provable displays lift recursively: ``return [[1], [2]]`` ⇒
    ``list[list[int]]``.

This adds NO new soundness surface: every parametrized element/key/value is
itself proved by the SAME :func:`_literal_type` oracle, so a part that is not
statically certain (a ``Name``/call/attribute) yields ``None`` there and the
whole display falls back to its BARE container — an honest UNDER-claim, never
wrong. The bare-container fallback also covers an EMPTY display (``[]`` ⇒
``list``, ``{}`` ⇒ ``dict``, ``()`` ⇒ ``tuple``), a MIXED-element display
(``[1, 'a']`` ⇒ ``list`` — the elements disagree), a ``**spread`` dict / a
``*spread`` tuple (no fixed shape), and — unchanged — a COMPREHENSION
(``[x for x in xs]`` stays bare ``list``; its element type is not statically
certain). PEP 585 ``list[int]``/``dict[int, str]``/``tuple[int, str]`` need NO
import on the project's Python, and the annotation is runtime-valid.

Because parametrization routes through the SAME return-value oracle it composes
with the ternary/recursion rules via a CONTAINER TYPE-JOIN (least-upper-bound) at
the multi-type agreement points: a ternary whose BOTH branches prove the SAME
parametrized type lands it (``[1] if c else [2]`` ⇒ ``list[int]``), while a
parametrized branch joined with a bare-from-empty ``list`` (``[1] if c else []``)
or a differing-param same-container branch WIDENS to the sound bare base (⇒
``list``) instead of refusing — the join only ever widens a precise type to its
own true base, so the annotation stays sound. DIFFERENT bases (``list`` vs
``set``) still refuse. The same join folds a function's collected return types
(a ``[1, 2]`` return + a bare-``list`` comprehension return ⇒ ``list``). A
fake-green canary proves the accept path annotates the REAL inferred type
(``list[int]`` vs ``dict[int, str]`` are DISTINCT, never a hardcoded constant),
and a determinism + byte-identical/no-op check pins input → output stability.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms.type_annotations import (
    _ifexp_same_type,
    _join_types,
    _literal_type,
    _parametrized_display_type,
    _return_value_type,
    _uniform_element_type,
    infer_annotations,
)


# --- ACCEPT: parametrized literal displays -----------------------------------

def test_infers_list_int_from_int_list_display():
    src = "def f():\n    return [1, 2]\n"
    assert infer_annotations(src) == (
        "def f() -> list[int]:\n    return [1, 2]\n")


def test_infers_list_str_from_str_list_display():
    src = "def f():\n    return ['a', 'b']\n"
    assert infer_annotations(src) == (
        "def f() -> list[str]:\n    return ['a', 'b']\n")


def test_infers_set_int_from_int_set_display():
    src = "def f():\n    return {1, 2}\n"
    assert infer_annotations(src) == (
        "def f() -> set[int]:\n    return {1, 2}\n")


def test_infers_dict_int_str_from_dict_display():
    src = "def f():\n    return {1: 'a', 2: 'b'}\n"
    assert infer_annotations(src) == (
        "def f() -> dict[int, str]:\n    return {1: 'a', 2: 'b'}\n")


def test_infers_heterogeneous_tuple_from_tuple_display():
    # A fixed-length HETEROGENEOUS tuple: one slot per element, in order.
    src = "def f():\n    return (1, 'a')\n"
    assert infer_annotations(src) == (
        "def f() -> tuple[int, str]:\n    return (1, 'a')\n")


def test_infers_longer_heterogeneous_tuple_one_slot_per_element():
    src = "def f():\n    return (1, 'a', True)\n"
    assert infer_annotations(src) == (
        "def f() -> tuple[int, str, bool]:\n    return (1, 'a', True)\n")


def test_infers_single_element_list():
    src = "def f():\n    return [1]\n"
    assert infer_annotations(src) == (
        "def f() -> list[int]:\n    return [1]\n")


def test_infers_nested_list_when_inner_displays_prove():
    # Nested provable displays lift recursively through the same oracle.
    src = "def f():\n    return [[1], [2]]\n"
    assert infer_annotations(src) == (
        "def f() -> list[list[int]]:\n    return [[1], [2]]\n")


def test_infers_dict_of_str_to_list_int_value():
    # Values are themselves provable parametrized displays.
    src = "def f():\n    return {'a': [1]}\n"
    assert infer_annotations(src) == (
        "def f() -> dict[str, list[int]]:\n    return {'a': [1]}\n")


# --- FALLBACK to the BARE container (the honest under-claim) ------------------

def test_mixed_element_list_falls_back_to_bare_list():
    # Elements disagree (int vs str) -> no single element type -> bare ``list``.
    src = "def f():\n    return [1, 'a']\n"
    assert infer_annotations(src) == (
        "def f() -> list:\n    return [1, 'a']\n")


def test_empty_list_falls_back_to_bare_list():
    src = "def f():\n    return []\n"
    assert infer_annotations(src) == "def f() -> list:\n    return []\n"


def test_empty_dict_falls_back_to_bare_dict():
    src = "def f():\n    return {}\n"
    assert infer_annotations(src) == "def f() -> dict:\n    return {}\n"


def test_empty_set_call_is_not_a_set_display():
    # ``set()`` is a constructor call (-> ``set`` via the builtin rule), NOT a
    # display; an empty SET display has no literal form, so this only pins that
    # the empty-display fallback does not over-reach into the constructor path.
    src = "def f():\n    return set()\n"
    assert infer_annotations(src) == "def f() -> set:\n    return set()\n"


def test_empty_tuple_falls_back_to_bare_tuple():
    src = "def f():\n    return ()\n"
    assert infer_annotations(src) == "def f() -> tuple:\n    return ()\n"


def test_comprehension_stays_bare_unchanged():
    # A comprehension's element type is not statically certain -> stays bare
    # ``list`` exactly as before this capability (the comprehension contract).
    src = "def f(xs):\n    return [x for x in xs]\n"
    assert infer_annotations(src) == (
        "def f(xs) -> list:\n    return [x for x in xs]\n")


def test_name_element_list_falls_back_to_bare_list():
    # A bare ``Name`` element is not provable -> the whole list under-claims the
    # bare container (never a wrong ``list[<unknown>]``).
    src = "def f(n):\n    return [n]\n"
    assert infer_annotations(src) == "def f(n) -> list:\n    return [n]\n"


def test_dict_with_spread_falls_back_to_bare_dict():
    # A ``**spread`` entry has no fixed key/value shape -> bare ``dict``.
    src = "def f(d):\n    return {**d, 1: 2}\n"
    assert infer_annotations(src) == "def f(d) -> dict:\n    return {**d, 1: 2}\n"


def test_tuple_with_starred_falls_back_to_bare_tuple():
    # A ``*spread`` element makes the arity variadic -> bare ``tuple``.
    src = "def f(xs):\n    return (1, *xs)\n"
    assert infer_annotations(src) == "def f(xs) -> tuple:\n    return (1, *xs)\n"


def test_dict_with_disagreeing_values_falls_back_to_bare_dict():
    # Keys agree (int) but values disagree (str vs int) -> bare ``dict``.
    src = "def f():\n    return {1: 'a', 2: 3}\n"
    assert infer_annotations(src) == (
        "def f() -> dict:\n    return {1: 'a', 2: 3}\n")


# --- composition with the ternary rule + CONTAINER TYPE-JOIN ------------------

def test_ternary_of_same_parametrized_list_branches_lands_parametrized():
    # Both branches prove ``list[int]`` -> JOIN keeps the precise ``list[int]``.
    src = "def f(c):\n    return [1] if c else [2]\n"
    assert infer_annotations(src) == (
        "def f(c) -> list[int]:\n    return [1] if c else [2]\n")


def test_ternary_of_parametrized_and_empty_list_joins_to_bare_list():
    # ``[1]`` proves ``list[int]`` and ``[]`` proves the BARE ``list``: SAME base
    # container with one bare side -> the JOIN WIDENS to the sound bare ``list``
    # (no longer a refusal — a parametrized list IS a list).
    src = "def f(c):\n    return [1] if c else []\n"
    assert infer_annotations(src) == (
        "def f(c) -> list:\n    return [1] if c else []\n")


def test_ternary_of_differing_param_lists_joins_to_bare_list():
    # ``[1]`` -> ``list[int]`` and ``['a']`` -> ``list[str]``: SAME base, DIFFERING
    # params -> the JOIN WIDENS to the bare ``list``.
    src = "def f(c):\n    return [1] if c else ['a']\n"
    assert infer_annotations(src) == (
        "def f(c) -> list:\n    return [1] if c else ['a']\n")


def test_ternary_of_differing_param_tuples_joins_to_bare_tuple():
    # ``(1, 'a')`` -> ``tuple[int, str]`` and ``(1, 2)`` -> ``tuple[int, int]``:
    # SAME base, DIFFERING params -> the JOIN WIDENS to the bare ``tuple``.
    src = "def f(c):\n    return (1, 'a') if c else (1, 2)\n"
    assert infer_annotations(src) == (
        "def f(c) -> tuple:\n    return (1, 'a') if c else (1, 2)\n")


def test_ternary_of_list_vs_set_still_refuses():
    # DIFFERENT base containers (``list`` vs ``set``) do NOT agree -> the JOIN
    # returns None and the ternary refuses (cross-base unchanged).
    src = "def f(c):\n    return [1] if c else {1}\n"
    assert infer_annotations(src) is None


def test_ternary_of_container_vs_scalar_still_refuses():
    # A container vs a non-container (``list[int]`` vs ``int``) do NOT agree.
    src = "def f(c):\n    return [1] if c else 0\n"
    assert infer_annotations(src) is None


# --- CONTAINER TYPE-JOIN at the RETURN-SET agreement --------------------------

def test_return_set_parametrized_and_comprehension_joins_to_bare_list():
    # A function with a parametrized ``[1, 2]`` return (``list[int]``) and a
    # comprehension return (bare ``list`` — element type not statically certain):
    # SAME base, one bare side -> the JOIN WIDENS to the bare ``list``.
    src = (
        "def f(xs, c):\n"
        "    if c:\n"
        "        return [1, 2]\n"
        "    return [x for x in xs]\n"
    )
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(xs, c) -> list:")


def test_return_set_parametrized_and_empty_joins_to_bare_list():
    # A ``[1]`` return (``list[int]``) and an ``[]`` return (bare ``list``) JOIN
    # to the bare ``list`` across the return set, not just the ternary surface.
    src = (
        "def f(c):\n"
        "    if c:\n"
        "        return [1]\n"
        "    return []\n"
    )
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(c) -> list:")


def test_return_set_of_same_parametrized_lists_keeps_precise_type():
    # Two returns both proving ``list[int]`` -> the JOIN keeps the precise type.
    src = (
        "def f(c):\n"
        "    if c:\n"
        "        return [1]\n"
        "    return [2, 3]\n"
    )
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(c) -> list[int]:")


def test_return_set_of_different_base_containers_still_refuses():
    # A ``list`` return and a ``set`` return -> different base -> refuse.
    src = (
        "def f(c):\n"
        "    if c:\n"
        "        return [1]\n"
        "    return {1}\n"
    )
    assert infer_annotations(src) is None


def test_single_parametrized_return_keeps_precise_type_no_join():
    # A SINGLE return folds to itself: precision retained, no widening.
    src = "def f():\n    return [1, 2]\n"
    assert infer_annotations(src) == (
        "def f() -> list[int]:\n    return [1, 2]\n")


# --- direct _join_types helper unit checks ------------------------------------

def test_join_types_keeps_identical():
    assert _join_types("list[int]", "list[int]") == "list[int]"
    assert _join_types("list", "list") == "list"
    assert _join_types("int", "int") == "int"


def test_join_types_widens_same_base_differing_or_bare():
    assert _join_types("list[int]", "list") == "list"
    assert _join_types("list", "list[int]") == "list"
    assert _join_types("list[int]", "list[str]") == "list"
    assert _join_types("tuple[int, str]", "tuple[int, int]") == "tuple"
    assert _join_types("dict[int, str]", "dict[str, int]") == "dict"


def test_join_types_refuses_cross_base_and_scalar():
    assert _join_types("list[int]", "set[int]") is None
    assert _join_types("list", "set") is None
    assert _join_types("list[int]", "int") is None
    assert _join_types("int", "str") is None


def test_ifexp_same_type_joins_through_helper():
    # The ternary surface routes through the join: a precise pair stays precise,
    # a bare/precise same-container pair widens, a cross-base pair refuses.
    same = ast.parse("[1] if c else [2]", mode="eval").body
    assert _ifexp_same_type(same, frozenset()) == "list[int]"
    widen = ast.parse("[1] if c else []", mode="eval").body
    assert _ifexp_same_type(widen, frozenset()) == "list"
    cross = ast.parse("[1] if c else {1}", mode="eval").body
    assert _ifexp_same_type(cross, frozenset()) is None


# --- fake-green canary + soundness made concrete -----------------------------

def test_parametrized_annotations_are_distinct_not_hardcoded():
    # FAKE-GREEN CANARY: the accept path annotates the ACTUAL inferred type, not
    # a hardcoded constant -> a list[int] and a dict[int, str] are DISTINCT.
    list_out = infer_annotations("def f():\n    return [1, 2]\n")
    dict_out = infer_annotations("def f():\n    return {1: 'a'}\n")
    assert list_out is not None and "-> list[int]:" in list_out
    assert dict_out is not None and "-> dict[int, str]:" in dict_out
    assert list_out != dict_out  # not one hardcoded annotation


def test_parametrized_annotation_preserves_parse_and_runtime_value():
    # The annotation adds ``-> T`` TEXT only and never changes runtime behaviour.
    # The annotated source must still parse, the PEP 585 generic is runtime-valid
    # (no import), and the runtime return value is byte-identical to the original.
    src = "def f():\n    return {1: 'a', 2: 'b'}\n"
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f() -> dict[int, str]:")

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)  # parses + evaluates the annot

    assert orig_ns["f"]() == new_ns["f"]() == {1: "a", 2: "b"}
    assert str(new_ns["f"].__annotations__.get("return")) == "dict[int, str]"


def test_parametrized_display_inference_is_deterministic():
    for src in (
        "def f():\n    return [1, 2]\n",
        "def f():\n    return {1: 'a'}\n",
        "def f():\n    return (1, 'a')\n",
        "def f():\n    return [[1], [2]]\n",
        "def f():\n    return [1, 'a']\n",  # bare fallback, still stable
        "def f(c):\n    return [1] if c else []\n",  # JOIN widens to bare list
    ):
        assert infer_annotations(src) == infer_annotations(src)
    # And a refused shape (cross-base ternary branches) is stably None.
    refused = "def f(c):\n    return [1] if c else {1}\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_already_annotated_display_is_byte_identical_noop():
    # An already-annotated display return is never overwritten -> no-op (None).
    annotated = "def f() -> object:\n    return [1, 2]\n"
    assert infer_annotations(annotated) is None
    # An unparseable source is also a no-op.
    assert infer_annotations("def f():\n    return [1, 2\n") is None


# --- direct helper unit checks -----------------------------------------------

def test_parametrized_display_helper_each_kind():
    cases = {
        "[1, 2]": "list[int]",
        "{1, 2}": "set[int]",
        "{1: 'a'}": "dict[int, str]",
        "(1, 'a')": "tuple[int, str]",
        "[[1]]": "list[list[int]]",
    }
    for expr, want in cases.items():
        node = ast.parse(expr, mode="eval").body
        assert _parametrized_display_type(node) == want, expr


def test_parametrized_display_helper_refuses_empty_mixed_and_nonliteral():
    for expr in ("[]", "{}", "()", "[1, 'a']", "[n]", "(1, *xs)", "{**d, 1: 2}"):
        node = ast.parse(expr, mode="eval").body
        assert _parametrized_display_type(node) is None, expr


def test_parametrized_display_helper_ignores_comprehensions():
    # A comprehension is NOT a display node here -> the helper returns None and
    # the bare-container table owns it (``list`` for a list comprehension).
    for expr in ("[x for x in y]", "{x for x in y}", "{k: v for k, v in y}"):
        node = ast.parse(expr, mode="eval").body
        assert _parametrized_display_type(node) is None, expr


def test_uniform_element_type_helper():
    int_elts = ast.parse("[1, 2]", mode="eval").body.elts
    assert _uniform_element_type(int_elts) == "int"
    mixed_elts = ast.parse("[1, 'a']", mode="eval").body.elts
    assert _uniform_element_type(mixed_elts) is None
    assert _uniform_element_type([]) is None  # empty under-claims


def test_parametrization_is_confined_to_return_value_surface():
    # Parametrization lives at the RETURN-VALUE surface, NOT in the context-free
    # ``_literal_type`` oracle (which the binop/mult rules reuse): the oracle
    # still returns the BARE container, while ``_return_value_type`` parametrizes.
    node = ast.parse("[1, 2]", mode="eval").body
    assert _literal_type(node) == "list"  # bare — the operand oracle is unchanged
    assert _return_value_type(node, frozenset()) == "list[int]"
    # A non-provable display is bare on both surfaces.
    mixed = ast.parse("[1, 'a']", mode="eval").body
    assert _literal_type(mixed) == "list"
    assert _return_value_type(mixed, frozenset()) == "list"


def test_binop_and_mult_operand_classification_unchanged():
    # The binop/sequence-mult rules read ``_literal_type`` of their operands, so
    # confining parametrization to the return surface keeps them landing the BARE
    # container exactly as before this capability (no cross-rule regression).
    assert infer_annotations("def f():\n    return [1] + [2]\n") == (
        "def f() -> list:\n    return [1] + [2]\n")
    assert infer_annotations("def f():\n    return [0] * 3\n") == (
        "def f() -> list:\n    return [0] * 3\n")
