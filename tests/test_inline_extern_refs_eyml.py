"""Falsifiable tests for inline-helpers' extern-reference guard — the fix for
the THIRD root cause of the external `packaging` incident (2026-07): the
inline transform deleted a helper that tests imported directly (``from
pkg.mod import fee``), leaving dangling imports → ImportError at collection.

``plan_inline`` guarded bare-object references (``g = fee``) but was blind to
three reference shapes that ALSO break when the def is deleted:

* an ``from ... import NAME`` alias anywhere in the project (incl. tests);
* a string entry of a curated ``__all__`` (the public re-export contract);
* an attribute-form CALL (``m.fee(3)``) — invisible to the bare-Name call
  rewriter, so the site survives un-rewritten and breaks at runtime.

Each refusal test here failed on the pre-fix code (the plan came back with
ZERO blockers and deleted the def); the control test pins that a genuinely
private same-module helper still inlines.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.inline_function import plan_inline, suggest_inlines


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_import_referenced_helper_is_refused(tmp_path):
    # The literal packaging shape: the test imports the helper BY NAME. Deleting
    # its def leaves the import dangling -> ImportError at collection.
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/mod.py",
           "RATE = 2\n\n\ndef fee(x):\n    return x * RATE\n\n\n"
           "def use(x):\n    return fee(x)\n")
    _write(tmp_path, "tests/test_mod.py",
           "from pkg.mod import fee, use\n\n\n"
           "def test_fee():\n    assert fee(3) == 6\n\n\n"
           "def test_use():\n    assert use(3) == 6\n")
    plan = plan_inline(tmp_path, "fee")
    assert plan.blockers, "an import-referenced helper must be refused"
    assert any("import" in b for b in plan.blockers)
    assert not plan.new_contents


def test_all_exported_helper_is_refused(tmp_path):
    # A curated __all__ entry is a public re-export contract; deleting the def
    # breaks `from pkg.mod import *` consumers and the contract itself.
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/mod.py",
           '__all__ = ["fee"]\n\n\ndef fee(x):\n    return x + 1\n\n\n'
           "def use(x):\n    return fee(x)\n")
    plan = plan_inline(tmp_path, "fee")
    assert plan.blockers, "an __all__-exported helper must be refused"
    assert not plan.new_contents


def test_attribute_called_helper_is_refused(tmp_path):
    # ``m.fee(3)`` is invisible to the bare-Name call rewriter: the def would be
    # deleted while the attribute call site survives -> AttributeError at runtime.
    _write(tmp_path, "a.py",
           "def fee(x):\n    return x + 1\n\n\ndef use(x):\n    return fee(x)\n")
    _write(tmp_path, "b.py", "import a\n\n\ndef via_attr():\n    return a.fee(3)\n")
    plan = plan_inline(tmp_path, "fee")
    assert plan.blockers, "an attribute-called helper must be refused"
    assert not plan.new_contents


def test_suggest_skips_extern_referenced_helpers(tmp_path):
    # The suggester must not advertise a candidate plan_inline now refuses —
    # the two stay mirror images.
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/mod.py",
           "def fee(x):\n    return x + 1\n\n\ndef use(x):\n    return fee(x)\n")
    _write(tmp_path, "tests/test_mod.py", "from pkg.mod import fee\n\n\n"
           "def test_fee():\n    assert fee(1) == 2\n")
    assert suggest_inlines(str(tmp_path)) == []


def test_private_same_module_helper_still_inlines(tmp_path):
    # Control (must pass before AND after the fix): a genuinely private helper,
    # referenced only as a bare call in its own module, still inlines cleanly.
    _write(tmp_path, "a.py",
           "RATE = 2\n\n\ndef _fee(x):\n    return x * RATE\n\n\n"
           "def use(x):\n    return _fee(x)\n")
    plan = plan_inline(tmp_path, "_fee")
    assert not plan.blockers
    assert "a.py" in plan.new_contents
    assert "_fee" not in plan.new_contents["a.py"]
    suggestions = suggest_inlines(str(tmp_path))
    assert any(d["function"] == "_fee" for d in suggestions)
