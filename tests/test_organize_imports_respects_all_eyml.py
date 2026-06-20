"""Regression: ``organize_imports`` must never strip an ``__all__``-listed
re-export.

Field-test P1: on a package ``__init__`` whose body is just
``from .mod import Name`` lines + ``__all__ = ["Name", ...]`` (exactly what the
``wire-exports`` develop objective lands), the import organizer treated each
re-export as an unused import and proposed deleting the public API — silently
undoing ``wire-exports`` while still reporting "verified". A name listed in
``__all__`` is a deliberate public re-export and is USED.

The fix is strictly subtractive on the removal set: a module with no ``__all__``
behaves byte-identically to before; only ``__all__``-listed names gain
protection.
"""

from __future__ import annotations

from app.execution.semantic.transforms import organize_imports


def _new_content(source: str) -> str | None:
    result = organize_imports.apply("pkg/__init__.py", source)
    if result is None:
        return None
    return result.patch_requests[0]["new_content"]


def test_all_listed_reexport_is_kept():
    source = (
        "from .core import Engine\n"
        "from .io import save\n"
        "\n"
        '__all__ = ["Engine", "save"]\n'
    )
    # Every import is a re-export listed in __all__ -> nothing to remove.
    assert organize_imports.apply("pkg/__init__.py", source) is None


def test_all_listed_reexport_kept_when_other_import_removed():
    source = (
        "from .core import Engine\n"
        "from .unused import Dangling\n"
        "\n"
        '__all__ = ["Engine"]\n'
    )
    out = _new_content(source)
    assert out is not None
    assert "from .core import Engine" in out  # protected re-export survives
    assert "Dangling" not in out  # genuinely-unused import still removed


def test_non_all_unused_import_still_removed():
    source = (
        "from .core import Engine\n"
        "import os\n"
        "\n"
        '__all__ = ["Engine"]\n'
    )
    out = _new_content(source)
    assert out is not None
    assert "import os" not in out
    assert "from .core import Engine" in out


def test_no_all_module_is_byte_identical_to_before():
    # No __all__ at all: the new protection adds zero export names, so the
    # removal decision is exactly today's behaviour.
    source = (
        "from .core import Engine\n"
        "import os\n"
    )
    out = _new_content(source)
    assert out is not None
    # Both unused (no __all__, no body use) -> both removed, as before the fix.
    assert "Engine" not in out
    assert "import os" not in out


def test_plain_import_in_all_is_kept():
    source = (
        "import json\n"
        "\n"
        '__all__ = ["json"]\n'
    )
    assert organize_imports.apply("pkg/__init__.py", source) is None


def test_aliased_import_bound_name_in_all_is_kept():
    source = (
        "from .core import Engine as Eng\n"
        "\n"
        '__all__ = ["Eng"]\n'
    )
    assert organize_imports.apply("pkg/__init__.py", source) is None


def test_all_built_with_augassign_is_kept():
    source = (
        "from .core import Engine\n"
        "from .io import save\n"
        "\n"
        "__all__ = []\n"
        '__all__ += ["Engine", "save"]\n'
    )
    assert organize_imports.apply("pkg/__init__.py", source) is None


def test_dynamic_all_falls_back_without_crashing():
    # Non-literal __all__: no protection, no crash; behaves like today.
    source = (
        "from .core import Engine\n"
        "names = ['Engine']\n"
        "__all__ = list(names)\n"
    )
    out = _new_content(source)
    assert out is not None
    # __all__ is dynamic -> Engine unprotected -> removed (current behaviour).
    assert "from .core import Engine" not in out


def test_tuple_all_is_honoured():
    source = (
        "from .core import Engine\n"
        "\n"
        '__all__ = ("Engine",)\n'
    )
    assert organize_imports.apply("pkg/__init__.py", source) is None


def test_deterministic_repeated_runs():
    source = (
        "from .core import Engine\n"
        "from .unused import Dangling\n"
        "\n"
        '__all__ = ["Engine"]\n'
    )
    first = _new_content(source)
    for _ in range(5):
        assert _new_content(source) == first
