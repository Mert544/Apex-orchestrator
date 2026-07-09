"""Coverage gaps for :mod:`app.execution.final_method` — the missing decorator-shape
and parse-guard branches the objective suite
(``test_seal_final_method_objective_eyml``) does not already hit:

  - a CALLED decorator (``@register()``) on a method: ``_decorator_attr_name`` unwraps
    the ``Call`` to its callable name (the recursion branch);
  - a SUBSCRIPT decorator (``@decs[0]``, PEP 614): a shape that is neither ``Name`` nor
    ``Attribute`` nor ``Call`` → ``_decorator_attr_name`` returns ``None`` (so it is not
    a skip-decorator, and the method is still considered);
  - a whole-project ``project_sources`` list containing an UNPARSEABLE source — the
    per-source parse guard in ``_collect_class_facts`` skips it and still seals.

Everything deterministic (pure AST + line splice, no clock/random/network).
"""

from __future__ import annotations

import ast

from app.execution.final_method import (
    add_final_method_decorator,
    finalizable_methods,
)


def test_called_decorator_unwrapped_to_callable_name():
    # ``@register()`` is a Call decorator — ``_decorator_attr_name`` recurses through
    # ``.func`` to ``"register"`` (not a skip decorator), so the plain method is still
    # sealable in isolation.
    src = (
        "class Service:\n"
        "    @register()\n"
        "    def commit(self):\n"
        "        return 1\n"
    )
    assert finalizable_methods(src) == ["Service.commit"]


def test_subscript_decorator_is_neither_name_nor_attribute():
    # ``@decs[0]`` (PEP-614 relaxed decorator) is an ``ast.Subscript`` — neither Name,
    # Attribute, nor Call — so ``_decorator_attr_name`` returns ``None`` (not in the
    # skip set), and the method is still sealable.
    src = (
        "class Service:\n"
        "    @decs[0]\n"
        "    def commit(self):\n"
        "        return 1\n"
    )
    assert finalizable_methods(src) == ["Service.commit"]


def test_project_sources_with_unparseable_source_is_skipped():
    # The whole-project subclass scan tolerates an UNPARSEABLE sibling source (the
    # per-source parse guard in ``_collect_class_facts`` ``continue``s past it) and
    # still seals the good module's never-overridden method.
    good = "class Service:\n    def commit(self):\n        return 1\n"
    out = add_final_method_decorator(good, [good, "def (  # not valid python\n"])
    assert out is not None
    assert "@final" in out
    assert "def commit" in out
    ast.parse(out)
