"""A public library class + method subclassed/overridden only from tests.

ADVERSARIAL SHAPE: ``Widget`` is a leaf in ``pkg/`` (the scan's own modules) but
is subclassed in ``tests/uses.py``, and EVERY one of its methods is overridden
there. ``@typing.final`` (class or method) is a pure RUNTIME no-op, so a green
pytest suite can NEVER catch a false ``@final`` on a class/method a TYPE CHECKER
sees subclassed/overridden — which is why the over-approximate scan is
tests-INCLUSIVE (``all_module_sources``). add-final must NOT seal ``Widget`` and
seal-final-method must NOT seal ``area``/``describe``: both must refuse.
"""


class Widget:
    def __init__(self, size=0):
        self.size = size

    def area(self):
        return self.size * self.size

    def describe(self):
        return f"widget-{self.size}"
