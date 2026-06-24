"""Existing thin tests for the env-fragile module.

strengthen-tests only acts on a module that ALREADY has tests; these assert only
type/shape, leaving the exact value unpinned — the surviving mutant a naive
oracle-capturing objective would try to kill with an env-fragile literal.
"""

from pkg.mod import home, order, stamp, where


def test_where():
    assert isinstance(where(), str)


def test_stamp():
    assert isinstance(stamp(), int)


def test_home():
    assert isinstance(home(), str)


def test_order():
    assert sorted(order()) == ["a", "b", "c", "d", "e"]
