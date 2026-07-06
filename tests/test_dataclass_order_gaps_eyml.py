"""Coverage-gap / characterization tests for :mod:`app.execution.dataclass_order`.

The module was ALREADY at 100% line coverage from
``tests/test_add_dataclass_order_objective_eyml.py`` when this file was added, so
these are REGRESSION / characterization tests that lock the documented soundness
rails (not padding): a bare/called/frozen ``@dataclass`` gains ``order=True``; the
provenance gate refuses a non-stdlib ``dataclass``; an already-``order=`` / ``eq=
False`` / ``**``-unpacking decorator is left alone; a hand-written or assigned
ordering dunder is a hard refusal; a multi-line / commented decorator is refused;
and the transform is idempotent and syntax-error safe.
"""

from __future__ import annotations

import ast

from app.execution.dataclass_order import (
    add_dataclass_order,
    is_ordered_dataclass_decorator,
    orderable_classes,
)


# --- the core transform: order=True is added --------------------------------

def test_bare_dataclass_gains_order_true():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class Point:\n"
        "    x: int\n"
        "    y: int\n"
    )
    out = add_dataclass_order(src)
    assert out is not None
    assert "@dataclass(order=True)" in out
    ast.parse(out)  # never lands broken Python


def test_called_empty_dataclass_gains_order_true():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass()\n"
        "class P:\n"
        "    x: int\n"
    )
    out = add_dataclass_order(src)
    assert out is not None
    assert "@dataclass(order=True)" in out


def test_frozen_dataclass_keeps_frozen_and_appends_order():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass(frozen=True)\n"
        "class P:\n"
        "    x: int\n"
    )
    out = add_dataclass_order(src)
    assert out is not None
    assert "@dataclass(frozen=True, order=True)" in out


def test_orderable_classes_lists_eligible_class_names():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class A:\n"
        "    x: int\n"
    )
    assert orderable_classes(src) == ["A"]


# --- the soundness refusals -------------------------------------------------

def test_non_stdlib_dataclass_binding_is_refused():
    # ``dataclass`` shadowed by a pydantic import — provenance gate refuses.
    src = (
        "from pydantic.dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n"
    )
    assert add_dataclass_order(src) is None
    assert orderable_classes(src) == []


def test_existing_order_keyword_is_left_alone():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass(order=False)\n"
        "class P:\n"
        "    x: int\n"
    )
    assert add_dataclass_order(src) is None


def test_eq_false_dataclass_is_refused():
    # ``order=True`` requires ``eq=True``; ``eq=False`` would raise ValueError.
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass(eq=False)\n"
        "class P:\n"
        "    x: int\n"
    )
    assert add_dataclass_order(src) is None


def test_kwargs_unpacking_decorator_is_refused():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "OPTS = {'frozen': True}\n"
        "\n"
        "\n"
        "@dataclass(**OPTS)\n"
        "class P:\n"
        "    x: int\n"
    )
    assert add_dataclass_order(src) is None


def test_hand_written_ordering_dunder_is_refused():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n"
        "\n"
        "    def __lt__(self, other):\n"
        "        return self.x < other.x\n"
    )
    assert add_dataclass_order(src) is None


def test_assigned_ordering_dunder_is_refused():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "def _cmp(self, other):\n"
        "    return NotImplemented\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n"
        "    __gt__ = _cmp\n"
    )
    assert add_dataclass_order(src) is None


def test_multiline_decorator_is_refused():
    # A decorator spanning >1 physical line: ast.unparse would collapse comments,
    # so the engine refuses rather than risk content loss.
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass(\n"
        "    frozen=True,\n"
        ")\n"
        "class P:\n"
        "    x: int\n"
    )
    assert add_dataclass_order(src) is None


# --- idempotency + robustness -----------------------------------------------

def test_idempotent_second_run_is_byte_identical_noop():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n"
    )
    once = add_dataclass_order(src)
    assert once is not None
    assert add_dataclass_order(once) is None  # already ordered — no re-touch


def test_syntax_error_source_is_a_clean_noop():
    assert add_dataclass_order("def (") is None
    assert orderable_classes("def (") == []


def test_is_ordered_dataclass_decorator_shape_probe():
    ordered = ast.parse("@dataclass(order=True)\nclass P: ...").body[0]
    plain = ast.parse("@dataclass\nclass P: ...").body[0]
    assert is_ordered_dataclass_decorator(ordered.decorator_list[0]) is True
    assert is_ordered_dataclass_decorator(plain.decorator_list[0]) is False
