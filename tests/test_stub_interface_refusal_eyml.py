"""Field-found P0 — implement-stub must REFUSE interface declarations, never fill
them with type-incorrect garbage.

The live failure: running ``implement-stub`` on ``app/execution/lang/adapter.py``
filled the ``...`` method bodies of ``class LanguageAdapter(Protocol)`` (decorated
``@runtime_checkable``) with bodies like ``def owns(self, rel: str) -> bool:
return rel`` (a ``str`` where ``bool`` is declared). A Protocol's ``...`` bodies
are INTERFACE DECLARATIONS — they are never executed at runtime, so a test-based
verify can even PASS with garbage in them (a false-green-adjacent). The same is
true of an ``@abstractmethod``'s ``raise NotImplementedError`` (the abstract
declaration itself), an ``@overload`` signature's ``...`` (only the real impl that
follows is executed), and EVERY body in a ``.pyi`` type-stub file (signature-only
by definition).

The fix refuses at the discovery chokepoint :func:`find_stub_functions` (the
single gate every consumer routes through) for the three AST-detectable shapes —
Protocol-class method, ``@abstractmethod``, ``@overload`` — and at the path-aware
gates (``_is_test_or_fixture`` for the scan, ``_is_fixture_path`` for the apply)
for ``.pyi`` files, which carry no source path into ``find_stub_functions``.

Refusing is always SAFE: the worst case is an under-fill; nothing is ever
NEWLY-filled. These tests pin both halves: the four interface shapes yield ZERO
stub-fill targets, AND a genuine module-level/plain-class stub in a non-Protocol,
non-abstract, non-overload context is STILL discovered exactly as before (no
over-refusal — the objective stays idempotent on finished code). Deterministic:
pure AST, no clock/random/network; source order preserved.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.stub_synthesis import find_stub_functions

# The exact byte shape of the bug site: a ``@runtime_checkable`` Protocol whose
# four verbs are ``...`` interface declarations (mirrors adapter.py).
_ADAPTER_SHAPE = '''\
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LanguageAdapter(Protocol):
    """The structural contract a language plugs into."""

    name: str

    def owns(self, rel: str) -> bool:
        """True when ``rel`` is a non-test source file this language may write."""
        ...

    def parse(self, source: str) -> Any | None:
        """The parsed source, or None when it does not parse."""
        ...

    def locate(self, tree, source, query):
        """The target the query names, or None if absent/ambiguous."""
        ...

    def apply(self, source: str, target, edit) -> str | None:
        """source with target's span replaced by edit, or None when stale."""
        ...

    def reparses(self, new_source: str) -> bool:
        """True when new_source is well-formed."""
        ...
'''


# --- 1. the exact adapter.py shape: a runtime_checkable Protocol -------------

def test_runtime_checkable_protocol_methods_are_not_stubs():
    # Every ``...`` method body here is an interface declaration, not a stub.
    assert find_stub_functions(_ADAPTER_SHAPE) == []


def test_literal_adapter_module_yields_zero_stubs():
    # The live regression, dead: the real adapter.py source must discover nothing.
    root = Path(__file__).resolve().parents[1]
    src = (root / "app" / "execution" / "lang" / "adapter.py").read_text(
        encoding="utf-8")
    stubs = find_stub_functions(src)
    assert [s.name for s in stubs] == [], (
        "Protocol-interface methods must never be discovered as fillable stubs")


# --- 2. typing.Protocol (an ATTRIBUTE base) ----------------------------------

def test_attribute_protocol_base_is_refused():
    src = (
        "import typing\n"
        "class X(typing.Protocol):\n"
        "    def m(self, a: int) -> bool: ...\n"
        "    def n(self, s: str) -> str: ...\n"
    )
    assert find_stub_functions(src) == []


def test_protocol_with_other_bases_still_refused():
    # A direct Protocol base anywhere in the bases list is enough (conservative).
    src = (
        "from typing import Protocol\n"
        "class Mixin: ...\n"
        "class X(Mixin, Protocol):\n"
        "    def m(self, a: int) -> bool: ...\n"
    )
    names = [s.name for s in find_stub_functions(src)]
    # ``Mixin``'s class body is a class-level ``...`` (no method) — not a function,
    # so it never was a candidate; ``X.m`` is refused as a Protocol method.
    assert names == []


# --- 3. @abstractmethod / @abc.abstractmethod inside a normal ABC ------------

def test_abstractmethod_not_discovered():
    src = (
        "from abc import ABC, abstractmethod\n"
        "class Y(ABC):\n"
        "    @abstractmethod\n"
        "    def a(self, x):\n"
        "        raise NotImplementedError\n"
    )
    assert find_stub_functions(src) == []


def test_abc_abstractmethod_attribute_form_not_discovered():
    src = (
        "import abc\n"
        "class Y(abc.ABC):\n"
        "    @abc.abstractmethod\n"
        "    def b(self, x):\n"
        "        raise NotImplementedError\n"
    )
    assert find_stub_functions(src) == []


def test_abstractmethod_with_ellipsis_body_not_discovered():
    # The abstract declaration may use ``...`` instead of raise — still refused.
    src = (
        "from abc import ABC, abstractmethod\n"
        "class Y(ABC):\n"
        "    @abstractmethod\n"
        "    def c(self, x) -> int: ...\n"
    )
    assert find_stub_functions(src) == []


# --- 4. @overload signatures (the ... is an overload sig, not a stub) --------

def test_overload_signatures_not_discovered_real_impl_follows_normal_rules():
    src = (
        "from typing import overload\n"
        "import typing\n"
        "@overload\n"
        "def f(x: int) -> int: ...\n"
        "@typing.overload\n"
        "def f(x: str) -> str: ...\n"
        "def f(x):\n"
        "    return x\n"  # the real impl is implemented, not a stub
    )
    # Both overloads refused; the implemented real impl is not a stub body.
    assert find_stub_functions(src) == []


def test_overload_refused_but_real_impl_stub_still_discovered():
    # The real impl, if itself a genuine stub, follows the normal rules and IS
    # discovered — only the @overload SIGNATURES are refused.
    src = (
        "from typing import overload\n"
        "@overload\n"
        "def f(x: int) -> int: ...\n"
        "@overload\n"
        "def f(x: str) -> str: ...\n"
        "def f(x): ...\n"  # genuine, undecorated stub body
    )
    stubs = find_stub_functions(src)
    assert [s.name for s in stubs] == ["f"]
    # It is the real impl (the LAST def), not one of the overload signatures.
    assert stubs[0].lineno == 6


# --- 5. genuine stubs are STILL discovered (no over-refusal / idempotence) ---

def test_genuine_module_and_plain_class_stubs_still_discovered():
    src = (
        "def real_stub(x): ...\n"
        "\n"
        "class Plain:\n"
        "    def helper(self, y):\n"
        "        raise NotImplementedError\n"
        "    def todo_one(self, z):\n"
        "        # TODO: implement this\n"
        "        pass\n"
    )
    names = [s.name for s in find_stub_functions(src)]
    assert names == ["real_stub", "helper", "todo_one"]


def test_genuine_stub_in_non_protocol_class_with_protocol_import():
    # Importing Protocol does NOT taint a class that does not subclass it.
    src = (
        "from typing import Protocol\n"
        "class NotAProtocol:\n"
        "    def real(self, x):\n"
        "        raise NotImplementedError\n"
    )
    assert [s.name for s in find_stub_functions(src)] == ["real"]


def test_mixed_protocol_and_real_module_discovers_only_the_real_stub():
    # A module with BOTH an interface Protocol and a genuine stub: only the
    # genuine one is offered; source order preserved.
    src = _ADAPTER_SHAPE + "\n\ndef genuine(a, b): ...\n"
    assert [s.name for s in find_stub_functions(src)] == ["genuine"]


# --- 6. .pyi refusal at the guarded layers (scan + apply) --------------------

def _pyi_project(root: Path) -> str:
    """A package carrying a ``.pyi`` whose bodies are genuine ``...`` (absent the
    ``.pyi`` guard each would look like a fillable stub), plus a test that pins
    the name — so only the path guard, not a missing spec, can refuse it. Returns
    the module rel path of the ``.pyi``."""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    (root / "app" / "calc.pyi").write_text(
        "def add(a: int, b: int) -> int: ...\n", encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(
        "from app.calc import add\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    return "app/calc.pyi"


def test_pyi_refused_by_scan_oracle(tmp_path: Path):
    # The discovery scan oracle (module_has_fillable_stub) must never count a .pyi.
    from app.execution.stub_synthesis import module_has_fillable_stub

    rel = _pyi_project(tmp_path)
    assert module_has_fillable_stub(tmp_path, rel) is False


def test_pyi_refused_by_apply_planner(tmp_path: Path):
    # The apply objective (plan_implement_stub) must return an empty no-op plan.
    from app.execution.objectives.implement_stub import plan_implement_stub

    rel = _pyi_project(tmp_path)
    plan = plan_implement_stub(tmp_path, rel)
    assert plan.new_contents == {}  # nothing filled — the .pyi is refused outright


def test_pyi_path_predicates_directly():
    # Both guarded path gates classify a .pyi as not-to-edit.
    from app.execution.objectives.implement_stub import (
        _is_fixture_path as apply_gate,
    )
    from app.execution.stub_synthesis import _is_test_or_fixture as scan_gate

    assert scan_gate("app/calc.pyi") is True
    assert apply_gate("app/calc.pyi") is True
    # A real .py source is still editable (no over-refusal).
    assert scan_gate("app/calc.py") is False
    assert apply_gate("app/calc.py") is False
