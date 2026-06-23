"""infer-type-hints — sound PARAMETER inference from a SINGLE CONJOINED runtime
``isinstance`` guard at function entry (an extension of the single-guard rule).

Today a single ``assert isinstance(x, C)`` (or ``if not isinstance(x, C):
raise``) at function entry annotates ONE parameter. A SINGLE CONJOINED guard now
annotates EACH conjoined parameter:

  - ``assert isinstance(x, A) and isinstance(y, B)`` ⇒ ``x: A, y: B``
  - ``if not (isinstance(x, A) and isinstance(y, B)): raise ...`` ⇒ ``x: A, y: B``

i.e. an ``ast.BoolOp``/``ast.And`` whose operands are each a single-class
isinstance guard is split, binding every operand's parameter to its class.

``and`` is SOUND because the guard raises unless EVERY conjunct holds, so every
path that continues past it has PROVEN each conjoined parameter's type —
identical runtime ENFORCEMENT to the single-guard rule, recording no new runtime
value. The suite pins the LOCKED refusals preserved here: an ``or`` guard
(proves NEITHER operand's type), a tuple-of-classes operand (``isinstance(x,
(int, str))`` is a Union, not a single class), and a conjunct that is not an
isinstance guard at all — each of which yields NO binding from the whole
conjunction; a default-value parameter is still NOT inferred. A fake-green canary
proves the landed annotation changes no runtime value, and a determinism test
pins input → output stability (including a byte-identical no-op).

Test bodies use a bare ``return x`` (an UNPROVABLE return) on purpose, so the
ONLY annotation that can land is the parameter one under test — isolating this
capability from the independent return-type rule (which would, e.g., add
``-> None`` for a ``return None`` body). One test deliberately uses ``len(x)`` to
pin that a conjoined param guard and a provable return compose.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms.type_annotations import (
    _annotatable_params,
    _entry_guard_bindings,
    _guard_test_bindings,
    infer_annotations,
)


# --- a conjoined guard lands EACH conjoined parameter's type -----------------

def test_assert_and_infers_both_params():
    # `and` of two single-class isinstance guards binds both params.
    src = (
        "def f(x, y):\n"
        "    assert isinstance(x, int) and isinstance(y, str)\n"
        "    return x\n"
    )
    assert infer_annotations(src) == (
        "def f(x: int, y: str):\n"
        "    assert isinstance(x, int) and isinstance(y, str)\n"
        "    return x\n"
    )


def test_if_not_conjoined_raise_infers_both_params():
    # The `if not (... and ...): raise` form binds both params too.
    src = (
        "def f(x, y):\n"
        "    if not (isinstance(x, int) and isinstance(y, str)):\n"
        "        raise TypeError\n"
        "    return x\n"
    )
    assert infer_annotations(src) == (
        "def f(x: int, y: str):\n"
        "    if not (isinstance(x, int) and isinstance(y, str)):\n"
        "        raise TypeError\n"
        "    return x\n"
    )


def test_assert_and_three_way_binds_all_three():
    # A 3-way `and` binds every conjoined param, in source order.
    src = (
        "def f(a, b, c):\n"
        "    assert isinstance(a, int) and isinstance(b, str) and isinstance(c, bytes)\n"
        "    return a\n"
    )
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(a: int, b: str, c: bytes):")


def test_assert_and_with_message_binds_both():
    # The assert's optional message does not affect the conjoined bind.
    src = (
        "def f(x, y):\n"
        '    assert isinstance(x, int) and isinstance(y, str), "bad"\n'
        "    return x\n"
    )
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(x: int, y: str):")


def test_assert_and_with_leading_docstring_binds_both():
    # A leading docstring may precede the conjoined guard — still the entry guard.
    src = (
        "def f(x, y):\n"
        '    """doc"""\n'
        "    assert isinstance(x, int) and isinstance(y, str)\n"
        "    return x\n"
    )
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(x: int, y: str):")


def test_conjoined_guard_and_provable_return_compose():
    # A conjoined param guard AND a provable return (`len(x)` -> int) land together.
    src = (
        "def f(x, y):\n"
        "    assert isinstance(x, list) and isinstance(y, str)\n"
        "    return len(x)\n"
    )
    assert infer_annotations(src) == (
        "def f(x: list, y: str) -> int:\n"
        "    assert isinstance(x, list) and isinstance(y, str)\n"
        "    return len(x)\n"
    )


# --- LOCKED refusals preserved (the whole point) -----------------------------

def test_refuses_or_guard_binds_neither():
    # An `or` guard proves NEITHER operand's type -> no parameter binding.
    src = (
        "def f(x, y):\n"
        "    assert isinstance(x, int) or isinstance(y, str)\n"
        "    return x\n"
    )
    assert infer_annotations(src) is None


def test_refuses_if_not_or_guard_binds_neither():
    # `if not (a or b): raise` proves neither operand's type -> no binding.
    src = (
        "def f(x, y):\n"
        "    if not (isinstance(x, int) or isinstance(y, str)):\n"
        "        raise TypeError\n"
        "    return x\n"
    )
    assert infer_annotations(src) is None


def test_refuses_when_a_conjunct_is_tuple_of_classes():
    # A tuple-second-arg conjunct (`isinstance(x, (int, str))`) is a Union, not a
    # single class -> that conjunct yields no binding -> the WHOLE conjunction
    # yields nothing (so the sound `y: bytes` conjunct does NOT land either).
    src = (
        "def f(x, y):\n"
        "    assert isinstance(x, (int, str)) and isinstance(y, bytes)\n"
        "    return x\n"
    )
    assert infer_annotations(src) is None


def test_refuses_when_a_conjunct_is_not_isinstance():
    # A non-isinstance conjunct voids the whole conjunction (no partial bind).
    src = (
        "def f(x, y):\n"
        "    assert isinstance(x, int) and y > 0\n"
        "    return x\n"
    )
    assert infer_annotations(src) is None


def test_refuses_when_a_conjunct_has_dotted_class():
    # A dotted class in any conjunct is not a bare type Name -> whole conj voids.
    src = (
        "def f(x, y):\n"
        "    assert isinstance(x, int) and isinstance(y, numbers.Integral)\n"
        "    return x\n"
    )
    assert infer_annotations(src) is None


def test_refuses_when_a_conjunct_has_unknown_class():
    # A bare Name outside the known-builtin set voids the whole conjunction.
    src = (
        "def f(x, y):\n"
        "    assert isinstance(x, int) and isinstance(y, Foo)\n"
        "    return x\n"
    )
    assert infer_annotations(src) is None


def test_refuses_conjoined_guard_nested_under_if():
    # A conjoined guard nested under `if z:` is NOT unconditional -> refuse.
    src = (
        "def f(x, y, z):\n"
        "    if z:\n"
        "        assert isinstance(x, int) and isinstance(y, str)\n"
        "    return x\n"
    )
    assert infer_annotations(src) is None


def test_conjoined_default_value_param_still_refused():
    # LOCKED refusal preserved: a default value is NOT a type bound. The guard
    # binds `x` (it IS guarded); the defaulted-but-unguarded `y` stays bare.
    src = (
        "def f(x, y=0):\n"
        "    assert isinstance(x, int)\n"
        "    return x\n"
    )
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(x: int, y=0):")


def test_conjoined_already_annotated_conjunct_not_overwritten():
    # Never overwrite an existing annotation: the conjoined guard names `x` and
    # `y`, but `x` is already annotated, so only `y` gains its annotation.
    src = (
        "def f(x: object, y):\n"
        "    assert isinstance(x, int) and isinstance(y, str)\n"
        "    return x\n"
    )
    out = infer_annotations(src)
    assert out is not None
    assert out.startswith("def f(x: object, y: str):")


# --- direct helper unit checks -----------------------------------------------

def test_guard_test_bindings_single_isinstance():
    test = ast.parse("isinstance(x, int)", mode="eval").body
    assert _guard_test_bindings(test) == [("x", "int")]


def test_guard_test_bindings_conjunction_in_order():
    test = ast.parse(
        "isinstance(x, int) and isinstance(y, str)", mode="eval").body
    assert _guard_test_bindings(test) == [("x", "int"), ("y", "str")]


def test_guard_test_bindings_refuses_or():
    test = ast.parse(
        "isinstance(x, int) or isinstance(y, str)", mode="eval").body
    assert _guard_test_bindings(test) == []


def test_guard_test_bindings_refuses_partial_conjunction():
    # One bad conjunct voids the whole conjunction (no partial list).
    test = ast.parse(
        "isinstance(x, int) and isinstance(y, (int, str))", mode="eval").body
    assert _guard_test_bindings(test) == []


def test_entry_guard_bindings_assert_and_if_conjoined_forms():
    assert_stmt = ast.parse(
        "assert isinstance(x, int) and isinstance(y, str)").body[0]
    assert _entry_guard_bindings(assert_stmt) == [("x", "int"), ("y", "str")]
    if_stmt = ast.parse(
        "if not (isinstance(a, int) and isinstance(b, bytes)):\n"
        "    raise TypeError\n"
    ).body[0]
    assert _entry_guard_bindings(if_stmt) == [("a", "int"), ("b", "bytes")]


def test_annotatable_params_reports_each_conjoined_param():
    fn = ast.parse(
        "def f(x, y):\n"
        "    assert isinstance(x, int) and isinstance(y, str)\n"
        "    return x\n"
    ).body[0]
    params = _annotatable_params(fn)
    assert [(arg.arg, cls) for arg, cls in params] == [("x", "int"), ("y", "str")]


# --- behaviour preservation (fake-green canary) + determinism ----------------

def test_conjoined_annotation_preserves_runtime_value_and_is_distinct():
    # FAKE-GREEN CANARY: the conjoined annotation adds `: T` TEXT only and never
    # changes runtime behaviour. The two params get DISTINCT types (x:int, y:str
    # — NOT both the same), so a copy-the-first-class bug would be caught.
    src = (
        "def f(x, y):\n"
        "    assert isinstance(x, int) and isinstance(y, str)\n"
        "    return x\n"
    )
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f(x: int, y: str):")

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)  # parses (canary) + runs

    assert orig_ns["f"](1, "a") == new_ns["f"](1, "a") == 1
    ann = new_ns["f"].__annotations__
    assert "int" in str(ann.get("x")) and "str" in str(ann.get("y"))
    assert str(ann.get("x")) != str(ann.get("y"))  # distinct, not both the same
    assert "x" not in orig_ns["f"].__annotations__  # original was unannotated


def test_conjoined_guard_enforces_types_so_annotation_cannot_lie():
    # SOUNDNESS made concrete: the conjoined guard REJECTS a wrong-typed arg at
    # runtime, so `x: int, y: str` records facts the runtime already enforces.
    src = (
        "def f(x, y):\n"
        "    if not (isinstance(x, int) and isinstance(y, str)):\n"
        "        raise TypeError\n"
        "    return x\n"
    )
    out = infer_annotations(src)
    assert out is not None and out.startswith("def f(x: int, y: str):")

    ns: dict[str, object] = {}
    exec(compile(out, "<n>", "exec"), ns)
    assert ns["f"](3, "ok") == 3
    raised = False
    try:
        ns["f"](3, 4)  # y is not a str
    except TypeError:
        raised = True
    assert raised  # a wrong conjunct is rejected, so the annotations never lie


def test_conjoined_param_inference_is_deterministic_and_byte_identical():
    accepted = (
        "def f(x, y):\n"
        "    assert isinstance(x, int) and isinstance(y, str)\n"
        "    return x\n"
    )
    # Same input -> same output, repeatedly.
    first = infer_annotations(accepted)
    assert first == infer_annotations(accepted)
    assert first is not None
    # Re-running on the ALREADY-annotated output is a byte-identical no-op
    # (both params are now annotated, so nothing provable changes -> None).
    assert infer_annotations(first) is None
    # And a refused `or` shape is stably refused.
    refused = (
        "def f(x, y):\n"
        "    assert isinstance(x, int) or isinstance(y, str)\n"
        "    return x\n"
    )
    assert infer_annotations(refused) == infer_annotations(refused) is None
