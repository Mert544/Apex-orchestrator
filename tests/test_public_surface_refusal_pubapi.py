"""PUBLIC-SURFACE refusal for the ``@final`` / freeze family (deep re-audit F1/F2/F3).

add-final, seal-final-method, and freeze-dataclass stamp ``@typing.final`` /
``@dataclass(frozen=True)`` onto a subject PROVABLY never subclassed / overridden /
mutated *anywhere in the project's OWN source*. But the whole-project scan
(``all_module_sources`` / ``project_sources``) only sees the project's OWN modules —
so "provably never subclassed in THIS repo" is NOT "safe to forbid subclassing" for a
PUBLISHED library's public API: an external consumer Apex cannot see may subclass the
class, override the method, or mutate the dataclass. ``@final`` is a runtime no-op so
the pytest suite can NEVER catch a false seal; freeze adds ``__hash__`` + immutability
(a real runtime contract change). The fix is a PUBLIC-SURFACE REFUSAL: when the
class / method is published API, default to refusing (an honest no-op) rather than
landing an unprovable contract change.

"Public surface" (DEFAULT-PUBLIC — REFUSE-on-ambiguity): if the module declares
``__all__`` -> the listed names; else (no ``__all__``) -> EVERY top-level
non-underscore name. A leading-underscore name is NEVER public. We do NOT gate the
no-``__all__`` case on an ``__init__.py`` library-module check — Apex runs over
PEP-420 NAMESPACE packages (a public module's dir may carry no ``__init__.py``), and
the plan layer already refuses true non-importable files (setup.py / conf.py /
conftest.py / …) before the transform; so a public non-underscore class in a module
with NO ``__init__.py`` beside it and NO ``__all__`` is STILL public API → refused.

Covers: the shared helpers (``module_public_surface`` / ``is_public_name``) and their
edge/empty paths; each objective's transform-level refusal (public ``__all__`` class,
public non-underscore class with no ``__all__`` and no ``__init__.py``, a computed
``__all__``); that PRIVATE / underscore-prefixed subjects are STILL sealed/frozen (no
over-refusal); the plan/objective level (incl. a NAMESPACE-package module with no
``__init__.py``); and that EVERY pre-existing refusal (internal subclass, override,
mutation) is intact.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.final_marker import add_final_decorator, finalizable_classes
from app.execution.final_method import (
    add_final_method_decorator,
    finalizable_methods,
)
from app.execution.freeze_dataclass import (
    freeze_dataclass_decorator,
    freezable_classes,
    is_public_name,
    module_public_surface,
)
from app.execution.objectives.add_final import plan_add_final
from app.execution.objectives.freeze_dataclass import plan_freeze_dataclass
from app.execution.objectives.seal_final_method import plan_seal_final_method


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


# --- the public-surface computation -----------------------------------------

def test_module_public_surface_uses_all_when_declared():
    src = '__all__ = ["A", "B"]\nclass A:\n    pass\nclass B:\n    pass\nclass C:\n    pass\n'
    assert module_public_surface(src) == {"A", "B"}


def test_module_public_surface_tuple_all():
    src = '__all__ = ("A",)\nclass A:\n    pass\n'
    assert module_public_surface(src) == {"A"}


def test_module_public_surface_top_level_names_when_no_all():
    src = "class Pub:\n    pass\ndef helper():\n    return 1\nCONST = 3\nclass _Priv:\n    pass\n"
    surface = module_public_surface(src)
    assert {"Pub", "helper", "CONST"} <= surface
    assert "_Priv" not in surface  # underscore names are never public


def test_module_public_surface_computed_all_falls_back_to_top_level():
    # A computed __all__ can't be enumerated, so EVERY top-level public name is
    # treated as exported (refuse-on-ambiguity).
    src = '__all__ = _base + ["X"]\nclass Foo:\n    pass\n'
    assert "Foo" in module_public_surface(src)


def test_module_public_surface_empty_on_syntax_error():
    assert module_public_surface("class (:\n") == set()


# --- is_public_name: the gate (DEFAULT-PUBLIC) ------------------------------

def test_is_public_name_underscore_never_public():
    assert not is_public_name("_X", "class _X:\n    pass\n")


def test_is_public_name_in_all_is_public():
    src = '__all__ = ["Exported"]\nclass Exported:\n    pass\n'
    assert is_public_name("Exported", src)


def test_is_public_name_not_in_all_is_private():
    src = '__all__ = ["Other"]\nclass NotExported:\n    pass\nclass Other:\n    pass\n'
    assert not is_public_name("NotExported", src)


def test_is_public_name_computed_all_refuses_every_name():
    src = '__all__ = list(_names)\nclass Anything:\n    pass\n'
    assert is_public_name("Anything", src)


def test_is_public_name_no_all_top_level_is_public_default():
    # DEFAULT-PUBLIC: a top-level non-underscore name with no __all__ is public,
    # with NO __init__.py / library-module gate.
    src = "class CacheMemory:\n    pass\n"
    assert is_public_name("CacheMemory", src)


def test_is_public_name_false_on_syntax_error():
    assert not is_public_name("X", "class (:\n")


# --- add-final: REFUSE a public-surface class (refuse_public=True) ----------

_ALL_PUBLIC = '__all__ = ["PublicBase"]\n\n\nclass PublicBase:\n    pass\n'
_PUBLIC_NO_ALL = "class CacheMemory(dict):\n    pass\n"


def test_add_final_refuses_all_listed_public_class():
    # __all__-exported public API — an external subclass we cannot see may exist.
    assert add_final_decorator(_ALL_PUBLIC, [_ALL_PUBLIC], refuse_public=True) is None


def test_add_final_refuses_public_class_without_all():
    # No __all__, a top-level non-underscore class — a default ``import *`` export —
    # so refuse, with NO __init__.py check (default-public).
    assert add_final_decorator(
        _PUBLIC_NO_ALL, [_PUBLIC_NO_ALL], refuse_public=True) is None


def test_add_final_isolation_does_not_apply_public_refusal():
    # The in-isolation default (refuse_public=False) does NOT refuse a public class —
    # "public API" is undefined without an importable-module context, so the bare
    # transform / convenience helper still seals it. The objective turns the gate on.
    assert finalizable_classes(_PUBLIC_NO_ALL) == ["CacheMemory"]
    out = add_final_decorator(_PUBLIC_NO_ALL, [_PUBLIC_NO_ALL])  # refuse_public=False
    assert out is not None and "@final" in out


def test_add_final_seals_private_class_even_with_refusal_on():
    # A PRIVATE (underscore-prefixed) class is NOT public surface — the project scan
    # is authoritative — so it is STILL sealed even with the public refusal ON.
    priv = "class _Helper:\n    pass\n"
    out = add_final_decorator(priv, [priv], refuse_public=True)
    assert out is not None and "@final" in out
    ast.parse(out)


def test_add_final_only_private_class_sealed_in_mixed_module():
    # A module exporting one public class and one private class: with the refusal ON,
    # only the private class is sealed; the public one is refused.
    src = (
        '__all__ = ["Public"]\n'
        "\n"
        "\n"
        "class Public:\n"
        "    pass\n"
        "\n"
        "\n"
        "class _Internal:\n"
        "    pass\n"
    )
    out = add_final_decorator(src, [src], refuse_public=True)
    assert out is not None
    from app.execution.final_marker import class_has_final_decorator
    tree = ast.parse(out)
    finals = {n.name for n in tree.body
              if isinstance(n, ast.ClassDef) and class_has_final_decorator(n)}
    assert finals == {"_Internal"}


def test_add_final_internal_subclass_still_refused_unchanged():
    # The PRE-EXISTING refusal is intact: a class with an internal subclass is
    # refused regardless of public-surface status. (Both are private here.)
    base = "class _Base:\n    pass\n"
    sub = "from m import _Base\n\n\nclass _Sub(_Base):\n    pass\n"
    assert add_final_decorator(base, [base, sub], refuse_public=True) is None


# --- freeze-dataclass: REFUSE a public-surface dataclass --------------------

_FZ_ALL_PUBLIC = (
    '__all__ = ["Config"]\n'
    "from dataclasses import dataclass\n"
    "\n"
    "\n"
    "@dataclass\n"
    "class Config:\n"
    "    x: int = 0\n"
)
_FZ_PUBLIC_NO_ALL = (
    "from dataclasses import dataclass\n"
    "\n"
    "\n"
    "@dataclass\n"
    "class Settings:\n"
    "    x: int = 0\n"
)


def test_freeze_refuses_all_listed_public_dataclass():
    assert freeze_dataclass_decorator(
        _FZ_ALL_PUBLIC, [_FZ_ALL_PUBLIC], refuse_public=True) is None


def test_freeze_refuses_public_dataclass_without_all():
    assert freeze_dataclass_decorator(
        _FZ_PUBLIC_NO_ALL, [_FZ_PUBLIC_NO_ALL], refuse_public=True) is None


def test_freeze_isolation_does_not_apply_public_refusal():
    # In isolation (refuse_public=False) a public dataclass still freezes.
    assert freezable_classes(_FZ_PUBLIC_NO_ALL) == ["Settings"]
    out = freeze_dataclass_decorator(_FZ_PUBLIC_NO_ALL, [_FZ_PUBLIC_NO_ALL])
    assert out is not None and "@dataclass(frozen=True)" in out


def test_freeze_freezes_private_dataclass_even_with_refusal_on():
    priv = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class _State:\n"
        "    x: int = 0\n"
    )
    out = freeze_dataclass_decorator(priv, [priv], refuse_public=True)
    assert out is not None and "@dataclass(frozen=True)" in out


def test_freeze_internal_subclass_still_refused_unchanged():
    # PRE-EXISTING refusal intact: a dataclass used as a base is refused.
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class _P:\n"
        "    x: int\n"
        "\n"
        "\n"
        "class _Q(_P):\n"
        "    pass\n"
    )
    assert freeze_dataclass_decorator(src, [src], refuse_public=True) is None


# --- seal-final-method: REFUSE methods of a public-surface class ------------

_SM_ALL_PUBLIC = (
    '__all__ = ["Service"]\n'
    "\n"
    "\n"
    "class Service:\n"
    "    def commit(self) -> int:\n"
    "        return 1\n"
)
_SM_PUBLIC_NO_ALL = (
    "class Repository:\n"
    "    def save(self) -> int:\n"
    "        return 1\n"
)


def test_seal_method_refuses_public_class_via_all():
    # The method's CLASS is __all__-exported public — external code may subclass it
    # and override the method — so refuse.
    assert add_final_method_decorator(
        _SM_ALL_PUBLIC, [_SM_ALL_PUBLIC], refuse_public=True) is None


def test_seal_method_refuses_public_class_without_all():
    assert add_final_method_decorator(
        _SM_PUBLIC_NO_ALL, [_SM_PUBLIC_NO_ALL], refuse_public=True) is None


def test_seal_method_isolation_does_not_apply_public_refusal():
    # In isolation (refuse_public=False) a method of a public class still seals.
    assert finalizable_methods(_SM_PUBLIC_NO_ALL) == ["Repository.save"]
    out = add_final_method_decorator(_SM_PUBLIC_NO_ALL, [_SM_PUBLIC_NO_ALL])
    assert out is not None and "@final" in out


def test_seal_method_seals_method_of_private_class_even_with_refusal_on():
    priv = (
        "class _Worker:\n"
        "    def run(self) -> int:\n"
        "        return 1\n"
    )
    out = add_final_method_decorator(priv, [priv], refuse_public=True)
    assert out is not None and "@final" in out


def test_seal_method_overridden_method_still_refused_unchanged():
    # PRE-EXISTING refusal intact: an overridden method is refused. (Both private.)
    base = "class _Base:\n    def run(self):\n        return 1\n"
    sub = "from m import _Base\n\n\nclass _Sub(_Base):\n    def run(self):\n        return 2\n"
    assert add_final_method_decorator(base, [base, sub], refuse_public=True) is None


# --- the plan / objective level ---------------------------------------------
#
# The coordinator-confirmed PEP-420 reality: Apex modules live in NAMESPACE packages
# (dirs with NO __init__.py). A public class in such a module — with no __all__ —
# is STILL public API and MUST be refused. These plan tests deliberately do NOT
# create an __init__.py, proving the refusal does not depend on one.

def test_plan_add_final_refuses_public_class_in_namespace_module(tmp_path: Path):
    # No app/__init__.py (a PEP-420 namespace module) and no __all__: the public
    # class is STILL refused. This is the exact F1 over-claim the fix closes.
    _project(tmp_path, "app/cache.py", _PUBLIC_NO_ALL)
    plan = plan_add_final(str(tmp_path), "app/cache.py")
    assert not plan.new_contents  # public class in a namespace module — refused


def test_plan_add_final_refuses_all_exported_class(tmp_path: Path):
    _project(tmp_path, "app/base.py", _ALL_PUBLIC)
    assert not plan_add_final(str(tmp_path), "app/base.py").new_contents


def test_plan_add_final_seals_private_class(tmp_path: Path):
    _project(tmp_path, "app/internal.py", "class _Helper:\n    pass\n")
    plan = plan_add_final(str(tmp_path), "app/internal.py")
    assert plan.ok
    assert "@final" in plan.new_contents["app/internal.py"]


def test_plan_freeze_refuses_public_dataclass_in_namespace_module(tmp_path: Path):
    _project(tmp_path, "app/conf.py", _FZ_PUBLIC_NO_ALL)
    assert not plan_freeze_dataclass(str(tmp_path), "app/conf.py").new_contents


def test_plan_freeze_seals_private_dataclass(tmp_path: Path):
    _project(tmp_path, "app/state.py",
             "from dataclasses import dataclass\n@dataclass\nclass _S:\n    x: int = 0\n")
    plan = plan_freeze_dataclass(str(tmp_path), "app/state.py")
    assert plan.ok
    assert "@dataclass(frozen=True)" in plan.new_contents["app/state.py"]


def test_plan_seal_method_refuses_public_class_in_namespace_module(tmp_path: Path):
    _project(tmp_path, "app/repo.py", _SM_PUBLIC_NO_ALL)
    assert not plan_seal_final_method(str(tmp_path), "app/repo.py").new_contents


def test_plan_seal_method_seals_private_class(tmp_path: Path):
    _project(tmp_path, "app/worker.py",
             "class _Worker:\n    def run(self):\n        return 1\n")
    plan = plan_seal_final_method(str(tmp_path), "app/worker.py")
    assert plan.ok
    assert "@final" in plan.new_contents["app/worker.py"]


def test_plan_add_final_refuses_public_class_in_package_module(tmp_path: Path):
    # And it is equally refused in a REGULAR package (dir WITH __init__.py): the
    # rule is the same either way (default-public, no library-module branching).
    _project(tmp_path, "app/__init__.py", "")
    _project(tmp_path, "app/cache.py", _PUBLIC_NO_ALL)
    assert not plan_add_final(str(tmp_path), "app/cache.py").new_contents


def test_plan_add_final_refuses_public_init_module(tmp_path: Path):
    # A public class declared in an __init__.py is public surface and refused.
    _project(tmp_path, "app/__init__.py", _PUBLIC_NO_ALL)
    assert not plan_add_final(str(tmp_path), "app/__init__.py").new_contents


# --- determinism / idempotency of the new path ------------------------------

def test_public_surface_refusal_is_deterministic():
    a = add_final_decorator(_ALL_PUBLIC, [_ALL_PUBLIC], refuse_public=True)
    b = add_final_decorator(_ALL_PUBLIC, [_ALL_PUBLIC], refuse_public=True)
    assert a == b is None  # both None — refused, deterministically


def test_private_seal_idempotent():
    priv = "class _Helper:\n    pass\n"
    once = add_final_decorator(priv, [priv], refuse_public=True)
    assert once is not None
    # 2nd run = byte-identical no-op (already @final).
    assert add_final_decorator(once, [once], refuse_public=True) is None
