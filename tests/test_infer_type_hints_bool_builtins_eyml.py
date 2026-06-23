"""infer-type-hints — sound RETURN inference for ALWAYS-bool builtin calls.

Capability C5 (expand sound return-type inference): a ``return <builtin>(...)``
whose callee is a builtin that ALWAYS returns a ``bool`` — ``callable``,
``issubclass``, ``isinstance``, ``hasattr`` (joining the existing ``bool``) —
resolves to ``bool``. Each is a non-overridable C-slot predicate, so its result
type is FIXED by the callable regardless of the argument values (a bad class arg
raises, a never-returns path that keeps ``-> bool`` sound).

These route through the BUILTIN-CALL table (:func:`_builtin_call_returns_type`),
NOT through ``ast.Compare`` — so the LOCKED ``==``/``<`` ⇒ refuse rule
(:func:`_is_certain_bool`) is UNTOUCHED. This suite pins that refusal
(``x == y`` / ``x < y`` ⇒ ``None``) alongside the new lands, the existing
soundness guards (an ``obj.isinstance(...)`` attribute callee and a SHADOWED
``isinstance`` both refuse), a fake-green parse+runtime canary, and determinism.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms.type_annotations import (
    _builtin_call_returns_type,
    infer_annotations,
)


def _expr(src: str) -> ast.expr:
    """Parse a single expression string into its ``ast.expr`` node."""
    return ast.parse(src, mode="eval").body


# --- the new always-bool builtins land --------------------------------------

def test_infers_bool_from_isinstance():
    assert infer_annotations("def f(x):\n    return isinstance(x, int)\n") == (
        "def f(x) -> bool:\n    return isinstance(x, int)\n")


def test_infers_bool_from_issubclass():
    assert infer_annotations("def f(c):\n    return issubclass(c, int)\n") == (
        "def f(c) -> bool:\n    return issubclass(c, int)\n")


def test_infers_bool_from_callable():
    assert infer_annotations("def f(x):\n    return callable(x)\n") == (
        "def f(x) -> bool:\n    return callable(x)\n")


def test_infers_bool_from_hasattr():
    assert infer_annotations("def f(o):\n    return hasattr(o, 'n')\n") == (
        "def f(o) -> bool:\n    return hasattr(o, 'n')\n")


def test_existing_bool_builtin_still_lands():
    # The pre-existing ``bool(...)`` entry is byte-identical in behaviour.
    assert infer_annotations("def f(x):\n    return bool(x)\n") == (
        "def f(x) -> bool:\n    return bool(x)\n")


def test_bool_builtins_agree_across_arms():
    # Two arms, each an always-bool builtin call -> agree on bool.
    src = (
        "def f(x, y):\n"
        "    if x:\n"
        "        return isinstance(x, int)\n"
        "    return callable(y)\n"
    )
    out = infer_annotations(src)
    assert out is not None and "-> bool:" in out


# --- LOCKED refusals the soundness argument requires ------------------------

def test_locked_eq_compare_still_refuses():
    # LOCKED: ``==`` dispatches to an overridable ``__eq__`` -> NOT provably bool
    # -> refuse. The bool-builtin table must NOT leak into the Compare path.
    assert infer_annotations("def f(x, y):\n    return x == y\n") is None


def test_locked_lt_compare_still_refuses():
    # LOCKED: ``<`` dispatches to an overridable ``__lt__`` -> refuse.
    assert infer_annotations("def f(x, y):\n    return x < y\n") is None


def test_attribute_callee_refuses():
    # ``obj.isinstance(...)`` is a DIFFERENT (user-defined) callable, not the
    # builtin -> refuse (a bare-Name callee is required).
    assert infer_annotations("def f(o, x):\n    return o.isinstance(x)\n") is None


def test_shadowed_builtin_refuses():
    # A local rebinds ``isinstance`` -> the call no longer resolves to the
    # builtin -> refuse (the shadowing guard stays sound).
    src = (
        "def f(x):\n"
        "    isinstance = make_check()\n"
        "    return isinstance(x, int)\n"
    )
    assert infer_annotations(src) is None


def test_user_function_named_like_predicate_refuses():
    # A plain user call (not in the builtin table) refuses.
    assert infer_annotations("def f(x):\n    return validate(x)\n") is None


# --- _builtin_call_returns_type unit (the routed helper) --------------------

def test_helper_returns_bool_for_each_new_member():
    for name in ("callable", "issubclass", "isinstance", "hasattr"):
        node = _expr(f"{name}(x, y)")
        assert _builtin_call_returns_type(node, frozenset()) == "bool", name


def test_helper_shadow_guard_refuses_with_frozenset():
    # The same call refuses once the name is in ``assigned_names``.
    node = _expr("isinstance(x, int)")
    assert _builtin_call_returns_type(node, frozenset({"isinstance"})) is None


def test_helper_attribute_callee_refuses():
    node = _expr("o.isinstance(x)")
    assert _builtin_call_returns_type(node, frozenset()) is None


def test_helper_non_call_refuses():
    # A non-Call node (here a bare Name) is not a builtin call -> None.
    assert _builtin_call_returns_type(_expr("isinstance"), frozenset()) is None


# --- behaviour preservation (fake-green canary) + determinism ---------------

def test_annotation_preserves_parse_and_runtime_value():
    # FAKE-GREEN CANARY: the rewrite adds ``-> bool`` TEXT only and never changes
    # runtime behaviour. The annotated source must still parse, and the runtime
    # return value must be byte-identical to the original's.
    src = "def f(x):\n    return isinstance(x, int)\n"
    out = infer_annotations(src)
    assert out == "def f(x) -> bool:\n    return isinstance(x, int)\n"

    orig_ns: dict[str, object] = {}
    exec(compile(src, "<orig>", "exec"), orig_ns)  # parses + runs
    new_ns: dict[str, object] = {}
    exec(compile(out, "<new>", "exec"), new_ns)     # parses (canary) + runs

    assert orig_ns["f"](3) == new_ns["f"](3) is True
    assert orig_ns["f"]("s") == new_ns["f"]("s") is False
    assert "return" not in orig_ns["f"].__annotations__
    assert "bool" in str(new_ns["f"].__annotations__.get("return"))
    assert type(new_ns["f"](3)) is bool


def test_bool_builtin_inference_is_deterministic():
    src = "def f(x):\n    return isinstance(x, int)\n"
    assert infer_annotations(src) == infer_annotations(src)
    # And a locked-refused shape is stably refused.
    refused = "def f(x, y):\n    return x == y\n"
    assert infer_annotations(refused) == infer_annotations(refused) is None


def test_empty_and_unparseable_paths():
    assert infer_annotations("") is None
    assert infer_annotations("def (:\n") is None
