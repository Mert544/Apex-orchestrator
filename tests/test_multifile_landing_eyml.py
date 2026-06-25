"""multifile_landing — the first COMPOSED concrete contribution, end-to-end.

Implement a tested stub in a package module AND wire its public export in the
package ``__init__.py`` as ONE verified unit. Covers: the atomic land (both files
written, suite green); the atomic rollback (a combined-change regression restores
BOTH files byte-for-byte — the unit-rollback guarantee); and the honest refusal
when the stub is unsynthesizable (nothing written, neither file touched). Drives
the EXISTING ``apply_rename`` gate over the composed plan — the single gated
writer, now exercised across two files.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.multifile_landing import plan_implement_and_wire


def _pkg_project(tmp_path: Path) -> Path:
    """A tmp project with a package (``app/pkg``) holding a tested stub module and
    an EMPTY ``__init__.py`` waiting to be wired."""
    (tmp_path / "app" / "pkg").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_atomic_land_stub_and_export(tmp_path: Path):
    _pkg_project(tmp_path)
    (tmp_path / "app" / "pkg" / "calc.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.pkg.calc import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")

    plan = plan_implement_and_wire(str(tmp_path), "app/pkg/calc.py")
    assert plan.ok
    assert set(plan.new_contents) == {"app/pkg/calc.py", "app/pkg/__init__.py"}

    res = apply_rename(str(tmp_path), plan, verify=True, impact_scope=True)
    assert res["applied"] is True and res["verified"] is True
    assert res["rolled_back"] is False

    # BOTH halves landed: the stub is filled AND its export is wired.
    calc = (tmp_path / "app" / "pkg" / "calc.py").read_text()
    assert "raise NotImplementedError" not in calc and "return a + b" in calc
    init = (tmp_path / "app" / "pkg" / "__init__.py").read_text()
    assert "from .calc import add" in init and '"add"' in init


def test_atomic_rollback_on_regression(tmp_path: Path):
    _pkg_project(tmp_path)
    calc_before = "def add(a, b):\n    raise NotImplementedError\n"
    init_before = ""
    (tmp_path / "app" / "pkg" / "calc.py").write_text(calc_before, encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.pkg.calc import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n",
        encoding="utf-8")
    # A guard test that IMPORTS the package (so it is in the impact scope of the
    # composed change) and pins a source invariant the fill BREAKS. The combined
    # change must be rejected as a UNIT and BOTH files restored byte-for-byte.
    (tmp_path / "tests" / "test_guard.py").write_text(
        "import inspect\nimport app.pkg.calc as calc\n"
        "def test_guard():\n    assert 'return' not in inspect.getsource(calc)\n",
        encoding="utf-8")

    plan = plan_implement_and_wire(str(tmp_path), "app/pkg/calc.py")
    assert plan.ok and set(plan.new_contents) == {
        "app/pkg/calc.py", "app/pkg/__init__.py"}

    res = apply_rename(str(tmp_path), plan, verify=True, impact_scope=True)
    assert res["applied"] is False and res["rolled_back"] is True

    # Atomic unit rollback: NEITHER file is left in a partial-land state.
    assert (tmp_path / "app" / "pkg" / "calc.py").read_text() == calc_before
    assert (tmp_path / "app" / "pkg" / "__init__.py").read_text() == init_before


def test_refuses_when_stub_unsynthesizable(tmp_path: Path):
    _pkg_project(tmp_path)
    calc_before = "def weird(a, b):\n    raise NotImplementedError\n"
    init_before = ""
    (tmp_path / "app" / "pkg" / "calc.py").write_text(calc_before, encoding="utf-8")
    # Contradictory witnesses (2,3->7 and 4,4->99): no fixed template fits and the
    # literals disagree, so implement-stub REFUSES (empty plan) — the composition
    # then refuses honestly and nothing is written.
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from app.pkg.calc import weird\n"
        "def test_w():\n    assert weird(2, 3) == 7\n    assert weird(4, 4) == 99\n",
        encoding="utf-8")

    plan = plan_implement_and_wire(str(tmp_path), "app/pkg/calc.py")
    assert not plan.ok and not plan.new_contents
    assert plan.blockers  # an explicit refusal reason rides the blockers channel

    # apply_rename on a refusing plan writes nothing — both files are untouched.
    res = apply_rename(str(tmp_path), plan, verify=True, impact_scope=True)
    assert res["applied"] is False
    assert (tmp_path / "app" / "pkg" / "calc.py").read_text() == calc_before
    assert (tmp_path / "app" / "pkg" / "__init__.py").read_text() == init_before
