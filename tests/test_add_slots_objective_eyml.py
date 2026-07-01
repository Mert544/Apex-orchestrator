"""add-slots develop objective — LAND ``__slots__`` on a project's own class whose
instance-attribute set is PROVABLY CLOSED (never extended dynamically anywhere in the
project). The structural DUAL of freeze-dataclass, pre-anticipated at
``freeze_dataclass.py:43``.

``__slots__`` changes ONLY the per-instance storage mechanism (drops ``__dict__``),
not any observable VALUE, FOR a closed-attribute class — so the change is
value-preserving BY CONSTRUCTION. The lone failure mode — an attribute STORE to a
name not in ``__slots__`` now raising ``AttributeError`` — is closed STATICALLY by
requiring the declared slot tuple to be a SUPERSET of every attribute name ever stored
on any instance of this class across EVERY module (tests INCLUDED, via
``all_module_sources``). The never-fake-green guard here is therefore structural: a
class with an off-slot store anywhere is REFUSED, even though the change would not
break a (narrowly-exercised) suite.

Covers: the core transform (plain ``__init__`` class, ``@dataclass`` field list,
leading docstring placement, single-field trailing comma, reverse-source-order
multi-class splice) plus EVERY refusal — an attribute stored outside the proven field
set (in a method, in ``__post_init__``, or via a literal ``setattr`` in a SEPARATE test
source), a non-``object`` base, an already-``__slots__`` class (idempotent), a
class-attr / slot-name collision, a ``@dataclass`` field WITH a default (the slots
conflict), a Protocol / ABC / Enum subclass, a public-surface class under
``refuse_public``, a non-enumerable attribute set (``**kwargs`` / non-literal
``setattr`` / ``__dict__`` write / no constructor), an empty field set, and an
unparseable source; plus idempotency and determinism (across ``PYTHONHASHSEED``);
the whole-project closed-attribute over-approximation; objective registration /
reachability (available, callable spec, reachable-from-facet, the facet-map<->registry
1:1 parity invariant, substring-safety, the north-star manifest classing it CONCRETE
with the reverse tripwire clean, the soundness-strategy manifest carrying it with NO
SCOPE_VERIFY_ALLOWLIST entry, the facet ladder carrying the phrase with the originals
still leading, the move-value tier); the END-TO-END landing (``apply_rename``
verify=True slots the class in place and the suite stays green); and the
never-fake-green guarantee (an off-slot store anywhere refuses the slot a
narrowly-exercised suite would otherwise let pass).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.objectives.add_slots import plan_add_slots
from app.execution.slots_synthesis import (
    _source_dict_reads,
    _source_weakrefs,
    add_slots,
    slottable_classes,
)

_PHRASE = "the closed-attribute class to give slots"

# A private plain class with a boilerplate ``__init__`` and no off-field store:
# slottable. PRIVATE so the objective's public-surface refusal does not also fire.
_LEAF = (
    '"""A point module."""\n'
    "\n"
    "\n"
    "class _Point:\n"
    "    def __init__(self, x, y):\n"
    "        self.x = x\n"
    "        self.y = y\n"
)


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _slots_of(source: str) -> dict[str, tuple[str, ...]]:
    """``{Class: (slot, ...)}`` for every class declaring ``__slots__`` in ``source``."""
    tree = ast.parse(source)
    out: dict[str, tuple[str, ...]] = {}
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for stmt in cls.body:
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__slots__" for t in stmt.targets
            ):
                out[cls.name] = tuple(
                    e.value for e in stmt.value.elts  # type: ignore[attr-defined]
                )
    return out


# --- the core transform: detection ------------------------------------------

def test_slottable_detects_closed_attribute_init_class():
    assert slottable_classes(_LEAF) == ["_Point"]


def test_slottable_empty_on_syntax_error():
    assert slottable_classes("class C(:\n") == []


def test_no_class_is_not_slottable():
    assert slottable_classes("def f():\n    return 1\n") == []


# --- the core transform: rewrite --------------------------------------------

def test_adds_slots_to_closed_attribute_init_class():
    out = add_slots(_LEAF)
    assert out is not None
    assert out.splitlines()[0] == '"""A point module."""'  # docstring stays first
    assert "    __slots__ = ('x', 'y',)" in out
    assert _slots_of(out) == {"_Point": ("x", "y")}
    # __slots__ sits at the TOP of the body, directly above __init__.
    assert "\n    __slots__ = ('x', 'y',)\n    def __init__(self, x, y):\n" in out
    ast.parse(out)  # never lands broken Python


def test_adds_slots_to_dataclass_using_field_names():
    # The slot set is the dataclass field list (ClassVar excluded), in declaration
    # order. (The runtime exec lives in the next test, which omits a ClassVar default
    # — under this module's ``from __future__ import annotations`` the stringized
    # ``ClassVar[int]`` annotation would misclassify in an exec'd namespace, a quirk
    # orthogonal to the slot synthesis proven here.)
    src = (
        "from dataclasses import dataclass\n"
        "from typing import ClassVar\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class _Rec:\n"
        "    x: int\n"
        "    y: str\n"
        "    kind: ClassVar[int] = 0\n"
    )
    out = add_slots(src)
    assert out is not None
    assert _slots_of(out) == {"_Rec": ("x", "y")}  # ClassVar is not slotted
    ast.parse(out)


def test_slotted_dataclass_constructs_and_drops_dict():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class _Rec:\n"
        "    x: int\n"
        "    y: str\n"
    )
    out = add_slots(src)
    assert out is not None and _slots_of(out) == {"_Rec": ("x", "y")}
    ns: dict = {}
    exec(out, ns)  # the slotted dataclass constructs and drops __dict__
    inst = ns["_Rec"](1, "a")
    assert (inst.x, inst.y) == (1, "a")
    assert not hasattr(inst, "__dict__")


def test_slots_inserted_after_leading_docstring():
    src = (
        "class _C:\n"
        '    """Holds an a."""\n'
        "    def __init__(self, a):\n"
        "        self.a = a\n"
    )
    out = add_slots(src)
    assert out is not None
    lines = out.splitlines()
    assert lines[1].strip() == '"""Holds an a."""'  # docstring stays body[0]
    assert lines[2] == "    __slots__ = ('a',)"  # slots immediately after it
    ast.parse(out)


def test_single_field_keeps_trailing_comma_tuple():
    src = "class _C:\n    def __init__(self, a):\n        self.a = a\n"
    out = add_slots(src)
    assert out is not None
    assert "    __slots__ = ('a',)" in out  # trailing comma -> a tuple, not a paren


def test_multiple_classes_each_slotted_in_source_order():
    # Two classes whose field vocabularies are IDENTICAL ({x, y}) — so the
    # whole-project store set ({x, y}) is a superset of NEITHER more than the other,
    # and BOTH are slottable. This exercises the REVERSE-source-order multi-splice
    # (earlier line spans stay valid). (Distinct field sets across siblings would
    # refuse BOTH under the conservative whole-project name-only scan — soundness over
    # recall — see ``test_sibling_with_distinct_field_set_refuses_both``.)
    src = (
        "class _A:\n"
        "    def __init__(self, x, y):\n"
        "        self.x = x\n"
        "        self.y = y\n"
        "\n"
        "\n"
        "class _B:\n"
        "    def __init__(self, x, y):\n"
        "        self.x = x\n"
        "        self.y = y\n"
    )
    out = add_slots(src)
    assert out is not None
    assert _slots_of(out) == {"_A": ("x", "y"), "_B": ("x", "y")}
    ast.parse(out)


def test_sibling_with_distinct_field_set_refuses_both():
    # Conservative whole-project name-only scan (soundness over recall): two classes
    # with DISTINCT field sets pollute each other's store vocabulary, so neither's
    # field set is a superset of the project-wide store set -> BOTH refuse. The
    # off-by-default posture: add-slots fires only on a provably-closed vocabulary.
    src = (
        "class _A:\n"
        "    def __init__(self, p):\n"
        "        self.p = p\n"
        "\n"
        "\n"
        "class _B:\n"
        "    def __init__(self, q):\n"
        "        self.q = q\n"
    )
    assert slottable_classes(src) == []
    assert add_slots(src) is None


def test_preserves_trailing_newline_absence():
    out = add_slots("class _C:\n    def __init__(self, a):\n        self.a = a")
    assert out is not None and not out.endswith("\n")


# --- the whole-project closed-attribute over-approximation ------------------

def test_refuses_when_attribute_stored_outside_field_set():
    # A method stores ``self.z`` (z is not a field) -> not a closed attribute set.
    src = (
        "class _C:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "    def go(self):\n"
        "        self.z = 1\n"
    )
    assert slottable_classes(src) == []
    assert add_slots(src) is None


def test_refuses_when_post_init_stores_off_field_attribute():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class _C:\n"
        "    x: int\n"
        "    def __post_init__(self):\n"
        "        self.cached = self.x * 2\n"
    )
    assert add_slots(src) is None  # ``cached`` is stored but not a field -> refuse


def test_refuses_attribute_set_via_setattr_in_a_test_source():
    # A SEPARATE (test) source stores an off-slot attr via a literal setattr — the
    # tests-INCLUSIVE scan must see it and refuse (a mock's off-slot store is a real
    # AttributeError under __slots__ the suite cannot fully cover).
    main = "class _C:\n    def __init__(self, a):\n        self.a = a\n"
    test_src = (
        "from m import _C\n"
        "\n"
        "\n"
        "def test_it():\n"
        "    inst = _C(1)\n"
        "    setattr(inst, 'z', 5)\n"
    )
    assert add_slots(main) is not None  # slottable in isolation ...
    assert add_slots(main, [main, test_src]) is None  # ... refused once the test is in scope


def test_whole_project_scan_can_only_add_refusals():
    main = "class _C:\n    def __init__(self, a):\n        self.a = a\n"
    sibling = "class Other:\n    def go(self):\n        self.z = 1\n"
    assert add_slots(main) is not None
    assert add_slots(main, [main, sibling]) is None  # sibling's ``z`` store refuses


# --- READ-path hazards: weakref + __dict__/vars() READ (never-fake-green) ----
#
# ``__slots__`` (without ``__weakref__`` / ``__dict__`` in the tuple) ALSO breaks two
# READ paths the STORE-only superset scan never sees: a ``weakref.ref(inst)`` raises
# ``TypeError`` (no ``__weakref__`` slot) and an ``inst.__dict__`` / ``vars(inst)`` READ
# raises ``AttributeError`` / ``TypeError`` (no ``__dict__`` slot). Either signal present
# anywhere in the project -> REFUSE (the name-only scan cannot prove THIS class's
# instances do not flow to the site — soundness over recall, the store-scan posture).

def test_refuses_when_instance_weakref_ref_taken_in_same_module():
    src = (
        "import weakref\n"
        "\n"
        "\n"
        "class _Node:\n"
        "    def __init__(self, v):\n"
        "        self.v = v\n"
        "\n"
        "\n"
        "def track(n):\n"
        "    return weakref.ref(n)\n"
    )
    assert slottable_classes(src) == []  # the weakref READ path forbids the slot
    assert add_slots(src) is None


def test_refuses_when_weakref_only_in_a_sibling_source():
    # The class is clean IN ISOLATION; a SIBLING source takes a weak reference -> the
    # whole-project READ scan refuses (it cannot prove the class's instances never flow
    # to that site). Mirrors the cross-module off-slot-store refusal.
    main = "class _C:\n    def __init__(self, a):\n        self.a = a\n"
    sibling = "import weakref\ndef hold(o):\n    return weakref.proxy(o)\n"
    assert add_slots(main) is not None  # slottable alone ...
    assert add_slots(main, [main, sibling]) is None  # ... refused once the weakref is in scope


def test_refuses_weakref_via_from_import_alias():
    # ``from weakref import ref`` -> a BARE ``ref(...)`` call; the trailing-name match
    # still counts it (alias-tolerant), so the slot is refused.
    src = (
        "from weakref import ref\n"
        "\n"
        "\n"
        "class _C:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "\n"
        "def keep(o):\n"
        "    return ref(o)\n"
    )
    assert add_slots(src) is None


def test_refuses_weakref_container_construction():
    # Constructing a ``WeakValueDictionary`` implies weak-referenced instances -> the
    # missing-``__weakref__`` hazard, matched on the trailing token regardless of alias.
    src = (
        "import weakref\n"
        "\n"
        "\n"
        "class _C:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "\n"
        "_REGISTRY = weakref.WeakValueDictionary()\n"
    )
    assert add_slots(src) is None


def test_refuses_when_instance_dunder_dict_read():
    # An ``inst.__dict__`` READ (a LOAD, NOT the ``__dict__[...] =`` store) breaks under
    # a ``__dict__``-less ``__slots__`` -> refuse.
    src = (
        "class _C:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "\n"
        "def snapshot(o):\n"
        "    return dict(o.__dict__)\n"
    )
    assert slottable_classes(src) == []
    assert add_slots(src) is None


def test_refuses_when_vars_called_on_instance():
    src = (
        "class _C:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "\n"
        "def as_map(o):\n"
        "    return vars(o)\n"
    )
    assert add_slots(src) is None


def test_dunder_dict_store_alone_does_not_trip_the_read_scan():
    # EDGE: a ``<expr>.__dict__[...] =`` STORE is NOT a ``__dict__`` READ — the read scan
    # must ignore it (the dynamic-store gate already handles that store form). A class
    # with NO such store and a sibling whose ONLY ``__dict__`` use is the store stays
    # slottable as far as the READ signal is concerned.
    assert _source_dict_reads("def f(o):\n    o.__dict__['z'] = 1\n") is False
    # The class itself with a __dict__ store is still refused — by the dynamic-store gate
    # (a separate path), proving the read scan is not what (incorrectly) catches it here.
    main = "class _C:\n    def __init__(self, a):\n        self.a = a\n"
    store_sibling = "def f(o):\n    o.__dict__['z'] = 1\n"
    assert add_slots(main, [main, store_sibling]) is not None  # store-only sibling: still lands


def test_read_scan_helpers_empty_on_unparseable_source():
    # EMPTY/edge path: an unparseable source contributes NO read signal (a False), so a
    # syntax-error sibling never spuriously refuses a clean class.
    assert _source_weakrefs("def (:\n") is False
    assert _source_dict_reads("def (:\n") is False


def test_read_scan_helpers_false_when_no_signal_present():
    # EMPTY path: a plain source with neither a weakref nor a __dict__/vars read yields
    # False for both, so the clean-class landing path is unaffected.
    clean = "class _C:\n    def __init__(self, a):\n        self.a = a\n"
    assert _source_weakrefs(clean) is False
    assert _source_dict_reads(clean) is False


def test_dotted_vars_is_not_the_builtin_and_does_not_refuse():
    # EDGE: ``mod.vars(o)`` is an ATTRIBUTE call, not the bare ``vars`` builtin, so it is
    # NOT a __dict__ read — the clean class still lands. (A bare ``vars`` Name is what the
    # hazard scan matches.)
    src = (
        "import mod\n"
        "\n"
        "\n"
        "class _C:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "\n"
        "def go(o):\n"
        "    return mod.vars(o)\n"
    )
    assert _source_dict_reads(src) is False
    assert add_slots(src) is not None  # dotted ``mod.vars`` is not the builtin -> lands


# --- READ-path hazards: from-import ALIAS resolution (the P0 hole) -----------
#
# The trailing-name scan alone MISSES a ``from weakref import ref as r`` rename: ``r(inst)``
# reads as a bare ``r`` ∉ the call-name set, so the class would be SLOTTED and
# ``weakref.ref(inst)`` would raise ``TypeError`` at runtime — the exact clone of the
# runtime-skip ``from pytest import skip as s`` hole. The fix resolves module-level
# weakref / builtins import aliases first. These tests FAIL pre-fix (the aliased fixture
# was slotted) and pass post-fix (refused), and they regression-guard the attribute form
# (``wr.ref``) and the NON-aliased ``from weakref import ref`` which already refused.

def _weak_fixture(import_line: str, call_expr: str) -> str:
    """A private slottable class plus a function that calls ``call_expr`` under
    ``import_line`` — the closed-attribute class is clean, so ONLY the weakref/dict-read
    signal can refuse it."""
    return (
        f"{import_line}\n"
        "\n"
        "\n"
        "class _C:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "\n"
        "def use(o):\n"
        f"    return {call_expr}\n"
    )


def test_refuses_weakref_ref_via_from_import_rename():
    # ``from weakref import ref as r`` -> ``r(inst)``: the bare-``Name`` alias resolves to
    # the canonical ``ref``, so the slot is refused. (Pre-fix this fixture was SLOTTED.)
    src = _weak_fixture("from weakref import ref as r", "r(o)")
    assert _source_weakrefs(src) is True
    assert slottable_classes(src) == []
    assert add_slots(src) is None


def test_refuses_weakref_proxy_via_from_import_rename():
    src = _weak_fixture("from weakref import proxy as p", "p(o)")
    assert _source_weakrefs(src) is True
    assert add_slots(src) is None


def test_refuses_weakvaluedictionary_via_from_import_rename():
    # A renamed weakref CONTAINER: ``from weakref import WeakValueDictionary as W`` ->
    # ``W()`` construction implies weak-referenced instances -> refuse.
    src = _weak_fixture("from weakref import WeakValueDictionary as W", "W()")
    assert _source_weakrefs(src) is True
    assert add_slots(src) is None


def test_refuses_weakset_via_from_import_rename():
    src = _weak_fixture("from weakref import WeakSet as W", "W()")
    assert _source_weakrefs(src) is True
    assert add_slots(src) is None


def test_refuses_vars_via_from_builtins_rename():
    # ``from builtins import vars as v`` -> ``v(inst)`` reads ``inst.__dict__`` -> refuse.
    src = _weak_fixture("from builtins import vars as v", "v(o)")
    assert _source_dict_reads(src) is True
    assert add_slots(src) is None


def test_refuses_getattr_dunder_dict_read():
    # ``getattr(inst, "__dict__")`` reads the instance ``__dict__`` as a CALL that slips
    # past the ``.__dict__`` attribute scan -> caught by the getattr-literal shape.
    src = (
        "class _C:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "\n"
        "\n"
        "def snap(o):\n"
        "    return getattr(o, \"__dict__\")\n"
    )
    assert _source_dict_reads(src) is True
    assert slottable_classes(src) == []
    assert add_slots(src) is None


# --- regression guards: the forms that ALREADY refused must keep refusing ----

def test_regression_weakref_attribute_form_still_refuses():
    # ``import weakref as wr; wr.ref(inst)`` — the attribute form reads through the
    # trailing token unchanged; the alias fix must not regress it.
    src = _weak_fixture("import weakref as wr", "wr.ref(o)")
    assert _source_weakrefs(src) is True
    assert add_slots(src) is None


def test_regression_non_aliased_from_weakref_import_still_refuses():
    # ``from weakref import ref`` with NO rename -> bare ``ref(inst)`` whose trailing token
    # is the canonical; both the pre-fix trailing scan and the alias map catch it.
    src = _weak_fixture("from weakref import ref", "ref(o)")
    assert _source_weakrefs(src) is True
    assert add_slots(src) is None


# --- soundness: a same-named import from an UNRELATED module does NOT refuse --

def test_unrelated_module_ref_alias_does_not_over_refuse():
    # ``from other import ref as r`` is NOT the weakref surface (untrusted module), so the
    # alias resolution does NOT bind ``r`` -> the clean class STILL slots (no false refusal,
    # mirroring the trusted-module gate of ``_collect_skip_aliases``).
    src = _weak_fixture("from other import ref as r", "r(o)")
    assert _source_weakrefs(src) is False
    assert add_slots(src) is not None


def test_clean_class_with_no_read_hazard_anywhere_still_slots():
    # OVER-REFUSAL guard: a slottable class with NEITHER a weakref nor any __dict__/vars/
    # getattr read present STILL slots — the alias machinery never spuriously refuses.
    src = "class _C:\n    def __init__(self, a):\n        self.a = a\n"
    assert _source_weakrefs(src) is False
    assert _source_dict_reads(src) is False
    out = add_slots(src)
    assert out is not None
    assert _slots_of(out) == {"_C": ("a",)}


# --- the core transform: REFUSALS (honest no-ops) ---------------------------

def test_refuses_class_with_non_object_base():
    src = "class _C(_Mixin):\n    def __init__(self, a):\n        self.a = a\n"
    assert add_slots(src) is None


def test_refuses_class_with_class_keyword():
    src = (
        "class _C(metaclass=_Meta):\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
    )
    assert add_slots(src) is None


def test_refuses_class_already_declaring_slots():
    # Idempotency: a class already carrying __slots__ is a byte-identical no-op.
    src = (
        "class _C:\n"
        "    __slots__ = ('a',)\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
    )
    assert add_slots(src) is None


def test_refuses_class_attr_colliding_with_slot_name():
    # A class-body ``a = 0`` default collides with the would-be slot ``a`` -> the
    # class-creation ValueError, so refuse.
    src = (
        "class _C:\n"
        "    a = 0\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
    )
    assert add_slots(src) is None


def test_refuses_dataclass_field_with_default_slot_conflict():
    # A @dataclass field WITH a default is the well-known __slots__ + default
    # conflict (ValueError at class creation) -> refuse. A BARE annotation is fine.
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class _C:\n"
        "    x: int = 5\n"
    )
    assert add_slots(src) is None


def test_refuses_protocol_subclass():
    src = (
        "from typing import Protocol\n"
        "\n"
        "\n"
        "class _P(Protocol):\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
    )
    assert slottable_classes(src) == []
    assert add_slots(src) is None


def test_refuses_abc_subclass():
    src = (
        "from abc import ABC\n"
        "\n"
        "\n"
        "class _A(ABC):\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
    )
    assert add_slots(src) is None


def test_refuses_abcmeta_metaclass():
    src = (
        "from abc import ABCMeta\n"
        "\n"
        "\n"
        "class _A(metaclass=ABCMeta):\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
    )
    assert add_slots(src) is None


def test_refuses_enum_subclass():
    src = (
        "import enum\n"
        "\n"
        "\n"
        "class _Color(enum.Enum):\n"
        "    RED = 1\n"
        "    GREEN = 2\n"
    )
    assert add_slots(src) is None


def test_refuses_public_surface_class_when_refuse_public():
    # A top-level non-underscore class is public surface; refuse_public refuses it,
    # but the SAME class slots when refuse_public is off (private/in-isolation).
    src = "class Point:\n    def __init__(self, a):\n        self.a = a\n"
    assert add_slots(src, refuse_public=True) is None
    assert add_slots(src, refuse_public=False) is not None


def test_refuses_kwargs_capture():
    src = (
        "class _C:\n"
        "    def __init__(self, **kwargs):\n"
        "        self.a = 1\n"
    )
    assert add_slots(src) is None


def test_refuses_nonliteral_setattr_on_self():
    src = (
        "class _C:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "    def put(self, k, v):\n"
        "        setattr(self, k, v)\n"
    )
    assert add_slots(src) is None


def test_refuses_dict_attribute_write():
    src = (
        "class _C:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "    def hack(self):\n"
        "        self.__dict__['z'] = 1\n"
    )
    assert add_slots(src) is None


def test_refuses_empty_field_set_no_constructor():
    assert add_slots("class _C:\n    pass\n") is None


def test_refuses_empty_field_set_init_with_no_pure_copies():
    # An __init__ that stores only a COMPUTED attribute has no pure-copy field — the
    # computed store also lands outside any (empty) field set, so refuse either way.
    src = (
        "class _C:\n"
        "    def __init__(self, a):\n"
        "        self.value = a + 1\n"
    )
    assert add_slots(src) is None


def test_refuses_unparseable_source():
    assert add_slots("def (:\n") is None


def test_byte_identical_when_no_eligible_class():
    assert add_slots("CONST = 1\n\n\ndef f():\n    return CONST\n") is None


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_byte_identical_noop():
    once = add_slots(_LEAF)
    assert once is not None
    assert add_slots(once) is None  # 2nd run sees __slots__ -> byte-identical no-op


def test_deterministic_across_two_runs():
    a = add_slots(_LEAF)
    b = add_slots(_LEAF)
    assert a is not None and a == b


def test_deterministic_across_hashseed():
    # Emission is SOURCE-ORDER stable, never hash-ordered: the bytes must be
    # identical across two different PYTHONHASHSEED values (the determinism moat).
    src = (
        "class _A:\n"
        "    def __init__(self, p, q, r):\n"
        "        self.p = p\n"
        "        self.q = q\n"
        "        self.r = r\n"
    )
    snippet = (
        "from app.execution.slots_synthesis import add_slots\n"
        "import sys\n"
        "sys.stdout.write(add_slots(%r) or '<none>')\n" % src
    )

    def _run(seed: str) -> str:
        env = {"PYTHONHASHSEED": seed, "PATH": __import__("os").environ.get("PATH", "")}
        out = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True, text=True, env=env,
            cwd=str(Path(__file__).resolve().parents[1]), check=True)
        return out.stdout

    first = _run("0")
    second = _run("12345")
    assert first == second
    assert "__slots__ = ('p', 'q', 'r',)" in first


# --- registration / reachability --------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "add-slots" in set(available_objectives())


def test_objective_total_is_seventy_eight():
    from app.engine.objective_compiler import available_objectives

    # 87 after js-document-returns-inferred (the PLAIN-JS inferred-@returns JSDoc
    # objective) self-registered; this count pin is the tripwire each new objective
    # round bumps.
    assert len(set(available_objectives())) == 93


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["add-slots"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_not_expensive_nor_scope_verify():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["add-slots"]
    assert getattr(spec, "expensive", False) is False
    assert getattr(spec, "scope_verify", False) is False


# --- PARITY ROW 1: move_value tier ------------------------------------------

def test_parity_move_value_has_add_slots_tier():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("add_slots") == 0.45
    assert objective_value("add-slots") == 0.45
    assert objective_value("add-slots") != DEFAULT_VALUE  # not the unknown fallback


# --- PARITY ROW 2: north-star manifest --------------------------------------

def test_parity_manifest_classifies_concrete():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())  # raises if unclassified
    assert "add-slots" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_parity_concrete_count_is_thirty_six():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert len(buckets["CONCRETE"]) == 48  # add-functools-wraps (48th CONCRETE)


# --- PARITY ROW 3: soundness-strategy manifest ------------------------------

def test_parity_soundness_strategy_present_and_no_scope_verify_entry():
    from app.engine.objective_compiler import available_objectives
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_completeness,
        strategy_subset_of_registry,
    )

    sc = strategy_completeness(available_objectives())  # raises if undeclared
    assert "add-slots" in sc
    assert (
        SOUNDNESS_STRATEGY["add-slots"]
        == "behavior-identical-storage+whole-project-closed-attribute-superset-proof-or-refuse"
    )
    assert "add-slots" not in SCOPE_VERIFY_ALLOWLIST  # scope_verify stays off
    assert strategy_subset_of_registry() == []  # no stale strategy name


# --- PARITY ROW 3b: the soundness corpus READ-path shapes -------------------

def test_parity_soundness_corpus_read_path_shapes_refuse_add_slots():
    # The standing proof: the two new adversarial shapes are present in the corpus and
    # add-slots REFUSES both (its STORE-only superset proof would otherwise slot them,
    # silently breaking a weakref / __dict__-read). No other objective VIOLATES on them.
    from app.engine.soundness_audit import (
        _SHAPE_MUST_REFUSE,
        corpus_refusal_findings,
        corpus_shapes,
        repo_root,
    )

    root = repo_root()
    shapes = set(corpus_shapes(root))
    assert {"weakref_target", "dunder_dict_read"} <= shapes
    assert _SHAPE_MUST_REFUSE["weakref_target"] == frozenset({"add-slots"})
    assert _SHAPE_MUST_REFUSE["dunder_dict_read"] == frozenset({"add-slots"})
    findings = corpus_refusal_findings(root, include_heavy=False)
    assert findings["add-slots"]["weakref_target"] == "refused"
    assert findings["add-slots"]["dunder_dict_read"] == "refused"
    # no objective lands a (would-be VIOLATION) change on either new shape
    for per_shape in findings.values():
        for shape in ("weakref_target", "dunder_dict_read"):
            assert not per_shape[shape].startswith("VIOLATION")


# --- PARITY ROW 4 + 5: facet map and ladder ---------------------------------

def test_parity_facet_routes_and_one_to_one_holds():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP, facet_to_objective
    from app.engine.objective_compiler import available_objectives

    assert facet_to_objective(_PHRASE) == "add-slots"
    # the standing 1:1 invariant: the facet map reaches EXACTLY the registry.
    assert len(set(FACET_OBJECTIVE_MAP.values())) == len(set(available_objectives()))
    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_parity_facet_phrase_is_substring_order_safe():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    keys = list(FACET_OBJECTIVE_MAP)
    assert _PHRASE in keys
    for other in keys:
        if other == _PHRASE:
            continue
        assert _PHRASE not in other, f"{_PHRASE!r} is a substring of {other!r}"
        assert other not in _PHRASE, f"{other!r} is a substring of {_PHRASE!r}"


def test_parity_facet_phrase_lives_in_ladder_with_originals_leading():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["unreachable or no-op statements"]
    assert _PHRASE in ladder
    # add-slots was the tail until synthesize-dunders (its sibling) was appended after
    # it; the originals still lead and emit first, which is what this pin guards.
    assert ladder[0] == "redundant pass statement"  # originals still lead
    # the freeze-dataclass sibling stays directly before it.
    assert ladder[ladder.index(_PHRASE) - 1] == "a never-mutated dataclass to freeze"
    # synthesize-dunders' phrase now follows add-slots' directly (appended last).
    assert ladder[ladder.index(_PHRASE) + 1] == "the repr and eq to synthesize from fields"


# --- the plan: a closed-attribute class gets __slots__ -----------------------

def test_plan_lands_slots_on_eligible_module(tmp_path: Path):
    _project(tmp_path, "app/point.py", _LEAF)
    plan = plan_add_slots(str(tmp_path), "app/point.py")
    assert plan.ok
    new = plan.new_contents["app/point.py"]
    assert "    __slots__ = ('x', 'y',)" in new
    assert _slots_of(new) == {"_Point": ("x", "y")}
    ast.parse(new)
    assert plan.originals["app/point.py"] == _LEAF  # original captured for rollback
    assert plan.edits_by_file["app/point.py"] == 1


def test_plan_uses_whole_project_closed_attribute_scan(tmp_path: Path):
    # The class is closed in its OWN module, but a SIBLING stores an off-slot attr
    # of the same name -> the whole-project scan must refuse.
    _project(tmp_path, "app/point.py",
             "class _Point:\n    def __init__(self, x):\n        self.x = x\n")
    _project(tmp_path, "app/other.py",
             "class Other:\n    def go(self):\n        self.z = 1\n")
    plan = plan_add_slots(str(tmp_path), "app/point.py")
    assert not plan.new_contents  # refused by the cross-module off-slot store


def test_plan_refuses_already_slotted(tmp_path: Path):
    _project(tmp_path, "app/point.py",
             "class _C:\n    __slots__ = ('a',)\n"
             "    def __init__(self, a):\n        self.a = a\n")
    assert not plan_add_slots(str(tmp_path), "app/point.py").new_contents


def test_plan_refuses_public_class(tmp_path: Path):
    # A top-level non-underscore class is public surface — the objective turns the
    # public-surface refusal ON, so it is not slotted.
    _project(tmp_path, "app/point.py",
             "class Point:\n    def __init__(self, a):\n        self.a = a\n")
    assert not plan_add_slots(str(tmp_path), "app/point.py").new_contents


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _LEAF)
    assert not plan_add_slots(str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _LEAF)
    assert not plan_add_slots(str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_add_slots(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_lands_slots_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    src = (
        '"""A point module."""\n'
        "\n"
        "\n"
        "class _Point:\n"
        "    def __init__(self, x, y):\n"
        "        self.x = x\n"
        "        self.y = y\n"
    )
    (tmp_path / "app" / "point.py").write_text(src, encoding="utf-8")
    (tmp_path / "tests" / "test_point.py").write_text(
        "from app.point import _Point\n"
        "def test_values():\n"
        "    p = _Point(1, 2)\n"
        "    assert (p.x, p.y) == (1, 2)\n"
        "def test_slotted():\n"
        "    assert _Point.__slots__ == ('x', 'y')\n"
        "    assert not hasattr(_Point(1, 2), '__dict__')\n",
        encoding="utf-8")

    plan = plan_add_slots(str(tmp_path), "app/point.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "point.py").read_text(encoding="utf-8")
    assert "    __slots__ = ('x', 'y',)" in landed  # the slot tuple LANDED
    assert "def __init__(self, x, y):" in landed  # behaviour preserved (proven green)


def test_never_fake_green_off_slot_store_is_not_slotted(tmp_path: Path):
    # never-fake-green, STRUCTURAL form. ``__slots__`` only changes storage, so a
    # class whose off-slot store path is NOT exercised by the suite would stay green
    # even though the slot is a false "closed-attribute" claim (a future off-slot
    # store would AttributeError). The honesty guard is the whole-project scan, not
    # the suite: ``_C`` provably stores ``z`` outside its field set, so the engine
    # REFUSES to slot it — the change can never land on a non-closed class.
    src = (
        "class _C:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n"
        "    def stash(self, v):\n"
        "        self.z = v\n"
    )
    _project(tmp_path, "app/svc.py", src)
    plan = plan_add_slots(str(tmp_path), "app/svc.py")
    assert not plan.new_contents  # the off-slot store forbids the slot
