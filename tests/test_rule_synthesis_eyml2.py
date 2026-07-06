"""Rule synthesis — attribute-access shape keys (eyml2 wave).

Targets the ``ast.Attribute`` arm of ``_shape_key`` (the ``A(...)`` token) which
the first wave left uncovered. Deterministic AST mining, stdlib + pytest only.
"""

from __future__ import annotations

import ast

from app.engine.rule_synthesis import _shape_key, mine_recurring_patterns

# Three files each ``return <name>.<attr>`` — names/attrs differ per site, so only
# an identifier-abstracted key (attribute access -> ``A(N)``) collapses them.
_ATTR_RETURN_SOURCES = {
    "a.py": "def f():\n    return obj.attr\n",
    "b.py": "def g():\n    return foo.bar\n",
    "c.py": "def h():\n    return baz.qux\n",
}


def test_shape_key_abstracts_attribute_access_directly():
    node = ast.parse("obj.attr").body[0].value  # an ast.Attribute
    assert isinstance(node, ast.Attribute)
    assert _shape_key(node) == "A(N)"


def test_shape_key_nests_chained_attribute_access():
    node = ast.parse("a.b.c").body[0].value
    assert _shape_key(node) == "A(A(N))"


def test_recurring_attribute_return_mines_one_pattern():
    patterns = mine_recurring_patterns(_ATTR_RETURN_SOURCES)
    shapes = {p["shape"] for p in patterns}
    assert "Return[A(N)]" in shapes
    pat = next(p for p in patterns if p["shape"] == "Return[A(N)]")
    assert pat["support"] == 3
