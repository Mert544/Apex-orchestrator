"""Coverage-gap tests for :mod:`app.execution.enum_unique`.

Targets the previously-uncovered soundness branches: a non-Name/Attribute base
(``_base_attr_name`` -> None); a called ``@unique()`` idempotency shape; the member-
scan branches (multi-target assign, annotated member WITH a value, a non-member
assignment target, a bare annotation binding no member, a dunder assignment); the
``_literal_value`` reductions (``None`` member, an un-reducible ``...`` constant,
unary ``-``/``+`` numeric members); an aliased ``import ... as unique`` other-binding;
the fresh-import fallback when the existing ``from enum import`` line carries a
comment; and the syntax-error no-op of :func:`uniqueable_enums`.
"""

from __future__ import annotations

import ast

from app.execution.enum_unique import (
    add_enum_unique_decorator,
    enum_has_unique_decorator,
    uniqueable_enums,
)


def _first_class(source: str) -> ast.ClassDef:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.ClassDef)
    return node


# --- enum shape / base detection (line 84) ----------------------------------

def test_subscript_base_before_enum_is_tolerated():
    # A non-Name/non-Attribute base (a Subscript) contributes ``None`` to the base
    # scan; the trailing ``Enum`` base still marks the class as an enum.
    src = (
        "from enum import Enum\n"
        "\n"
        "\n"
        "class C(Wrap[int], Enum):\n"
        "    A = 1\n"
        "    B = 2\n"
    )
    assert uniqueable_enums(src) == ["C"]


# --- the idempotency shape probe (line 99) ----------------------------------

def test_called_unique_decorator_counts_as_present():
    cls = _first_class("@unique()\nclass C(Enum):\n    A = 1\n")
    assert enum_has_unique_decorator(cls) is True


def test_dotted_enum_unique_decorator_counts_as_present():
    cls = _first_class("@enum.unique\nclass C(Enum):\n    A = 1\n")
    assert enum_has_unique_decorator(cls) is True


# --- member-scan branches (lines 127, 130, 135, 148, 150-151) ---------------

def test_annotated_member_with_value_is_a_member():
    src = (
        "from enum import Enum\n"
        "\n"
        "\n"
        "class C(Enum):\n"
        "    A: int = 1\n"
        "    B: int = 2\n"
    )
    assert uniqueable_enums(src) == ["C"]


def test_multi_target_assign_makes_enum_unmodelled():
    # ``A = B = 1`` is not a single-target member assignment; the body cannot be
    # enumerated exactly, so the whole enum is refused.
    src = (
        "from enum import Enum\n"
        "\n"
        "\n"
        "class C(Enum):\n"
        "    A = B = 1\n"
    )
    assert uniqueable_enums(src) == []


def test_dunder_and_bare_annotation_are_inert_but_members_seal():
    # A dunder assignment (non-member target) and a bare ``x: int`` type declaration
    # are both inert; the real members still make the enum sealable.
    src = (
        "from enum import Enum\n"
        "\n"
        "\n"
        "class C(Enum):\n"
        "    __private__ = 0\n"
        "    x: int\n"
        "    A = 1\n"
        "    B = 2\n"
    )
    assert uniqueable_enums(src) == ["C"]


def test_subscript_target_assignment_makes_enum_unmodelled():
    # A single-target assignment to a non-Name (a Subscript) is neither a member nor
    # inert, so the whole enum is refused.
    src = (
        "from enum import Enum\n"
        "\n"
        "\n"
        "class C(Enum):\n"
        "    reg[0] = 1\n"
        "    A = 1\n"
    )
    assert uniqueable_enums(src) == []


# --- literal-value reductions (lines 187-189, 190-196) ----------------------

def test_none_member_value_is_a_distinct_literal():
    src = (
        "from enum import Enum\n"
        "\n"
        "\n"
        "class C(Enum):\n"
        "    A = None\n"
        "    B = 1\n"
    )
    assert uniqueable_enums(src) == ["C"]


def test_ellipsis_member_value_is_not_reducible():
    # ``...`` is a Constant whose value is neither scalar nor None — un-provable, so
    # the whole enum is refused.
    src = (
        "from enum import Enum\n"
        "\n"
        "\n"
        "class C(Enum):\n"
        "    A = ...\n"
        "    B = 1\n"
    )
    assert uniqueable_enums(src) == []


def test_unary_signed_numeric_members_are_distinct_literals():
    src = (
        "from enum import Enum\n"
        "\n"
        "\n"
        "class C(Enum):\n"
        "    A = -1\n"
        "    B = +2\n"
    )
    out = add_enum_unique_decorator(src)
    assert out is not None
    assert "@unique" in out
    ast.parse(out)


# --- binding scan: aliased other-source ``unique`` (line 248) ---------------

def test_import_aliased_as_unique_blocks_the_seal():
    # ``import json as unique`` binds ``unique`` from a NON-enum source; the bare
    # ``@unique`` form is not provable and no fresh import may be added, so refuse.
    src = (
        "from enum import Enum\n"
        "import json as unique\n"
        "\n"
        "\n"
        "class C(Enum):\n"
        "    A = 1\n"
        "    B = 2\n"
    )
    assert uniqueable_enums(src) == []


# --- fresh-import fallback when enum import is commented (line 356) ----------

def test_commented_enum_import_forces_fresh_unique_import_line():
    # The existing ``from enum import Enum  # stdlib`` line is not cleanly widenable
    # (it carries a comment), so a fresh ``from enum import unique`` line is inserted.
    src = (
        "from enum import Enum  # stdlib\n"
        "\n"
        "\n"
        "class C(Enum):\n"
        "    A = 1\n"
        "    B = 2\n"
    )
    out = add_enum_unique_decorator(src)
    assert out is not None
    assert "from enum import unique" in out
    assert "from enum import Enum  # stdlib" in out  # original line untouched
    assert "@unique" in out
    ast.parse(out)


# --- robustness (lines 422-423) ---------------------------------------------

def test_syntax_error_source_is_a_clean_noop():
    assert uniqueable_enums("def (") == []
    assert add_enum_unique_decorator("def (") is None
