"""Characterization harness proving the refactor of ``_quality_section`` is
byte-identical to the original at git HEAD.

``_quality_section`` was decomposed into small pure per-analyzer helpers. This
test loads the *original* function body from ``git show HEAD:<file>`` into an
isolated module, then renders the FULL HTML string for a battery of
representative project shapes through both the original and the refactored
implementation and asserts exact (byte-for-byte) equality. It also exercises the
empty-tree gate and the per-analyzer absence fallback (a missing analyzer module
degrades to "omitted").

Offline, stdlib-only, deterministic — no network, no time/random assertions.
"""

import os
import subprocess
import sys
import types

import pytest

from app.reporting import dashboard_sections as REFACTORED

_REL = "app/reporting/dashboard_sections.py"
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_original():
    """Compile the HEAD version of the module under a throwaway module name."""
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{_REL}"], cwd=_REPO
    ).decode("utf-8")
    mod = types.ModuleType("_dashboard_sections_head")
    mod.__file__ = os.path.join(_REPO, _REL)
    sys.modules["_dashboard_sections_head"] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


ORIGINAL = _load_original()


# --- project fixtures spanning the analyzer matrix --------------------------

def _proj_all(tmp_path):
    """Every analyzer fires: typed/documented + untyped/undocumented/branchy."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "good.py").write_text(
        '"""Module docstring."""\n\n\n'
        "def tidy(x: int) -> int:\n"
        '    """Documented and fully typed."""\n'
        "    return x + 1\n",
        encoding="utf-8",
    )
    branches = "".join(f"    if x == {i}:\n        return {i}\n" for i in range(25))
    (app / "messy.py").write_text(
        "def tangle(x):\n"
        "    # TODO: simplify this dispatcher\n"
        "    # FIXME: <script>alert(1)</script> & breakage\n"
        f"{branches}"
        "    return -1\n",
        encoding="utf-8",
    )
    return str(tmp_path)


def _proj_empty(tmp_path):
    """No Python sources -> section gates to ""."""
    (tmp_path / "README.md").write_text("# nothing\n", encoding="utf-8")
    return str(tmp_path)


def _proj_clean(tmp_path):
    """Fully typed + documented, no debt, low complexity (bars near 100%)."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "clean.py").write_text(
        '"""Mod."""\n\n\n'
        "def a(x: int) -> int:\n"
        '    """Doc."""\n'
        "    return x\n\n\n"
        "def b(y: int) -> int:\n"
        '    """Doc."""\n'
        "    return y\n",
        encoding="utf-8",
    )
    return str(tmp_path)


def _proj_special(tmp_path):
    """HTML-special characters in module names + marker text to test escaping."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "weird_and_co.py").write_text(
        "def f(a):\n"
        "    # TODO: a < b && c > d \"quoted\" 'apos'\n"
        "    if a:\n"
        "        return 1\n"
        "    return 0\n",
        encoding="utf-8",
    )
    return str(tmp_path)


_FIXTURES = [_proj_all, _proj_empty, _proj_clean, _proj_special]


@pytest.mark.parametrize("make", _FIXTURES, ids=[f.__name__ for f in _FIXTURES])
def test_quality_section_byte_identical(make, tmp_path):
    root = make(tmp_path)
    before = ORIGINAL._quality_section(root)
    after = REFACTORED._quality_section(root)
    assert before == after, "rendered HTML diverged from HEAD original"


def test_quality_section_empty_returns_blank(tmp_path):
    root = _proj_empty(tmp_path)
    assert REFACTORED._quality_section(root) == ""
    assert ORIGINAL._quality_section(root) == ""


def test_quality_run_missing_module_degrades_to_none():
    # An absent analyzer module yields None (the "omitted" fallback), never raises.
    assert REFACTORED._quality_run(".", "no_such_analyzer_xyz", "analyze") is None


def test_quality_hotspots_empty_rows_is_empty_block():
    # Pure helper: no rows -> no block fragment, so callers can += unconditionally.
    assert REFACTORED._quality_hotspots("Heading", []) == []
    out = REFACTORED._quality_hotspots("Heading", ["<li>x</li>"])
    assert out == ["<h4 style='margin:8px 0 4px'>Heading</h4>"
                   "<ul class='commits'><li>x</li></ul>"]


def test_per_helper_absent_inputs_are_empty():
    # Each per-analyzer helper returns ([], []) for None / zero-data inputs.
    for fn in (
        REFACTORED._quality_type_hints,
        REFACTORED._quality_docstrings,
        REFACTORED._quality_complexity,
        REFACTORED._quality_todo_debt,
    ):
        assert fn(None) == ([], [])
