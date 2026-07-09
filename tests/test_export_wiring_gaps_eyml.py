"""Coverage-gap tests for :mod:`app.execution.export_wiring`.

Targets the previously-uncovered error / OSError branches: an unparseable existing
``__init__.py`` (``_existing_init_bindings`` / ``_existing_public_definitions`` /
``_existing_all`` all catch the ``SyntaxError`` and return an empty surface, and
:func:`plan_init_text` rejects a candidate whose broken header will not re-parse); a
sibling ``*.py`` entry that is actually a DIRECTORY (``read_text`` raises ``OSError``,
skipped); and an ``__init__.py`` that is itself a directory (``read_text`` raises
``OSError``, treated as empty).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.export_wiring import (
    collect_package_exports,
    plan_init_text,
    rendered_all_names,
)


def _pkg(tmp_path: Path, name: str = "pkg") -> Path:
    pkg = tmp_path / name
    pkg.mkdir()
    return pkg


# --- unparseable existing __init__.py (lines 153-154, 184-185, 309-310, 437-438) ---

def test_collect_tolerates_unparseable_existing_init(tmp_path):
    # A syntactically broken ``__init__.py`` binds NO names we can see; a sibling
    # module's public symbol is still collected.
    pkg = _pkg(tmp_path)
    (pkg / "mod.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    plan = collect_package_exports(pkg, "def (")
    assert plan.exports == {"foo": "mod"}


def test_rendered_all_names_tolerates_unparseable_existing_init(tmp_path):
    pkg = _pkg(tmp_path)
    (pkg / "mod.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    plan = collect_package_exports(pkg, "def (")
    # The broken init contributes no folded surface — only the new export remains.
    assert rendered_all_names(plan, "def (") == ["foo"]


def test_plan_init_text_refuses_when_broken_header_would_not_reparse(tmp_path):
    # A non-empty broken ``__init__.py`` is prepended verbatim as the candidate's
    # header, so the candidate cannot re-parse — plan_init_text returns None rather
    # than hand the apply layer invalid syntax.
    pkg = _pkg(tmp_path)
    (pkg / "__init__.py").write_text("def (", encoding="utf-8")
    (pkg / "mod.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    new_source, plan = plan_init_text(tmp_path, "pkg/__init__.py")
    assert new_source is None
    assert plan.exports == {"foo": "mod"}  # the export was still discovered


# --- a *.py entry that is a directory (lines 232-233) -----------------------

def test_collect_skips_a_module_path_that_is_a_directory(tmp_path):
    # A directory literally named ``weird.py`` matches the ``*.py`` glob but
    # ``read_text`` raises IsADirectoryError (an OSError) — it is skipped, not fatal.
    pkg = _pkg(tmp_path)
    (pkg / "weird.py").mkdir()
    (pkg / "good.py").write_text("def bar():\n    pass\n", encoding="utf-8")
    plan = collect_package_exports(pkg, "")
    assert plan.exports == {"bar": "good"}


# --- an __init__.py that is itself a directory (lines 420-421) --------------

def test_plan_init_text_treats_unreadable_init_as_empty(tmp_path):
    # ``__init__.py`` is a directory: it EXISTS (so not a namespace package) but
    # ``read_text`` raises OSError, so the existing text is treated as empty and the
    # wiring is computed from the sibling module.
    pkg = _pkg(tmp_path)
    (pkg / "__init__.py").mkdir()
    (pkg / "mod.py").write_text("def bar():\n    pass\n", encoding="utf-8")
    new_source, plan = plan_init_text(tmp_path, "pkg/__init__.py")
    assert new_source is not None
    assert "from .mod import bar" in new_source
    assert plan.exports == {"bar": "mod"}
