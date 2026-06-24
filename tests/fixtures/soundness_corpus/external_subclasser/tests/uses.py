"""A tests-only subclass that OVERRIDES every method of the library class.

This module deliberately lives under ``tests/`` so the objective's MOVE
generator (which scans the project's OWN non-fixture modules) never offers a move
on it, while the tests-INCLUSIVE soundness scan still SEES the subclass and the
overrides — the distinction that makes sealing ``Widget`` / its methods unsound.
"""

from pkg.lib import Widget


class FakeWidget(Widget):
    def area(self):
        return -1

    def describe(self):
        return "fake"
