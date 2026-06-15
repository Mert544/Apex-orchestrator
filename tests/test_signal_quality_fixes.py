"""Two grounded signal-quality false positives Apex's own health audit found,
both living in ``app/tools/project_profile.py``:

Fix 1 — the INTENTIONAL ``app/execution/*`` transform-plan scaffold (every
transform deliberately repeats the isolated read -> ``ast.parse`` -> collect
rewrites -> apply -> re-parse -> append a blocker -> return a ``RenamePlan``
shell, importing a common ``_transform_base``) was flagged as cross-module
"duplication to generalize". The ``_GENERALIZE_MAX_MODULES`` cap does NOT catch
2-module scaffold pairs. An all-scaffold group is now excluded from
``generalizable_duplications`` while genuine app-code duplication elsewhere is
still flagged.

Fix 2 — a thin, essentially-empty package ``__init__.py`` (e.g. a blank
``app/__init__.py``) can clear the fan-in hub bar yet defines nothing to
regress, so it seeded a near-zero-value "cover the dependency hub" idea
(busywork). A minimum-defined-symbol floor now keeps it OUT of
``hub_untested_modules`` while a real hub module with code and many dependents
still qualifies.

All tests are deterministic and ``tmp_path``-based.
"""

from pathlib import Path

from app.engine.idea_seeder import IdeaSeeder
from app.tools.project_profile import ProjectProfiler


# --- shared helpers ---------------------------------------------------------

# A function body that is structurally near-identical across modules (it differs
# only at the lone ``factor`` value leaf), so ``find_near_duplicates`` groups it
# as a NEAR duplicate. >= 5 statements so it clears the engine's min window.
def _dup_body(tag: str, factor: int = 2) -> str:
    return (
        f"def handle_{tag}(data):\n"
        f"    total = 0\n"
        f"    scaled = data * {factor}\n"
        f"    shifted = scaled + 1\n"
        f"    label = 'x'\n"
        f"    result = total + shifted\n"
        f"    return result\n"
    )


# A STRUCTURALLY DISTINCT near-duplicate body (a different statement shape from
# ``_dup_body``), so genuine app-code duplication forms its OWN near-dup group
# rather than merging with the scaffold group.
def _other_body(tag: str, factor: int = 2) -> str:
    return (
        f"def process_{tag}(items):\n"
        f"    acc = []\n"
        f"    base = len(items) + {factor}\n"
        f"    for it in items:\n"
        f"        acc.append(it - base)\n"
        f"    final = sum(acc)\n"
        f"    return final\n"
    )


# A flat ``app/execution/*`` transform-scaffold module: it imports the common
# ``_transform_base`` (the scaffold marker) AND carries the near-duplicate body,
# exactly like the real bool_return.py / comprehension.py family.
def _scaffold_module(tag: str, factor: int) -> str:
    return (
        "from __future__ import annotations\n"
        "from app.execution._transform_base import apply_line_rewrites\n"
        "from app.execution.cross_file_rename import RenamePlan\n\n"
        + _dup_body(tag, factor)
    )


def _write_execution_base(root: Path) -> None:
    """The ``app/execution/`` package + the shared ``_transform_base`` helper the
    scaffold modules import (so the scaffold marker resolves to a real file)."""
    execdir = root / "app" / "execution"
    execdir.mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (execdir / "__init__.py").write_text("", encoding="utf-8")
    (execdir / "_transform_base.py").write_text(
        "def apply_line_rewrites(source, rewrites):\n    return source\n",
        encoding="utf-8",
    )
    (execdir / "cross_file_rename.py").write_text(
        "class RenamePlan:\n    pass\n", encoding="utf-8")


# ===========================================================================
# Fix 1 — transform-scaffold is NOT flagged as generalizable duplication
# ===========================================================================

def test_execution_scaffold_pair_is_not_generalizable_duplication(tmp_path: Path):
    # Two flat app/execution/* transforms sharing the _transform_base scaffold
    # AND the near-duplicate body: this is the BY-DESIGN per-transform shell, so
    # it must NOT be reported as cross-module duplication to generalize.
    _write_execution_base(tmp_path)
    execdir = tmp_path / "app" / "execution"
    (execdir / "bool_return.py").write_text(
        _scaffold_module("a", factor=2), encoding="utf-8")
    (execdir / "comprehension.py").write_text(
        _scaffold_module("b", factor=3), encoding="utf-8")

    dups = ProjectProfiler(str(tmp_path)).profile().generalizable_duplications
    flagged = {m for d in dups for m in d["modules"]}
    assert "app/execution/bool_return.py" not in flagged
    assert "app/execution/comprehension.py" not in flagged


def test_genuine_duplication_elsewhere_is_still_flagged(tmp_path: Path):
    # The scaffold guard must be surgical: genuine cross-module duplication in
    # ordinary app code (NOT the execution scaffold) is still flagged.
    _write_execution_base(tmp_path)
    execdir = tmp_path / "app" / "execution"
    (execdir / "bool_return.py").write_text(
        _scaffold_module("a", factor=2), encoding="utf-8")
    (execdir / "comprehension.py").write_text(
        _scaffold_module("b", factor=3), encoding="utf-8")
    # Genuine duplication in two ordinary modules outside the scaffold, using a
    # STRUCTURALLY DISTINCT body so it forms its own near-dup group (not merged
    # with the scaffold group).
    pkg = tmp_path / "app" / "core"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "alpha.py").write_text(_other_body("alpha", factor=2), encoding="utf-8")
    (pkg / "beta.py").write_text(_other_body("beta", factor=3), encoding="utf-8")

    dups = ProjectProfiler(str(tmp_path)).profile().generalizable_duplications
    flagged = {m for d in dups for m in d["modules"]}
    # The scaffold pair is excluded...
    assert "app/execution/bool_return.py" not in flagged
    assert "app/execution/comprehension.py" not in flagged
    # ...but the genuine app-code duplication is kept.
    assert "app/core/alpha.py" in flagged
    assert "app/core/beta.py" in flagged


def test_execution_module_without_scaffold_marker_is_not_excused(tmp_path: Path):
    # An app/execution/* module that does NOT import a scaffold marker is NOT
    # treated as scaffold (the guard requires the marker, not just the dir), so
    # genuine duplication between such modules is still flagged.
    _write_execution_base(tmp_path)
    execdir = tmp_path / "app" / "execution"
    # No _transform_base / RenamePlan import — just duplicated bodies.
    (execdir / "plain_one.py").write_text(_dup_body("one", factor=2), encoding="utf-8")
    (execdir / "plain_two.py").write_text(_dup_body("two", factor=3), encoding="utf-8")

    dups = ProjectProfiler(str(tmp_path)).profile().generalizable_duplications
    flagged = {m for d in dups for m in d["modules"]}
    assert "app/execution/plain_one.py" in flagged
    assert "app/execution/plain_two.py" in flagged


def test_scaffold_predicate_is_directory_and_marker_scoped(tmp_path: Path):
    # Unit-level: the predicate is True only for a flat app/execution/* file that
    # imports a scaffold marker; nested subpackages and non-importers are False.
    _write_execution_base(tmp_path)
    execdir = tmp_path / "app" / "execution"
    (execdir / "bool_return.py").write_text(
        _scaffold_module("a", factor=2), encoding="utf-8")
    nested = execdir / "objectives"
    nested.mkdir()
    (nested / "__init__.py").write_text("", encoding="utf-8")
    (nested / "deep.py").write_text(
        _scaffold_module("deep", factor=4), encoding="utf-8")
    (execdir / "plain.py").write_text(_dup_body("p", factor=2), encoding="utf-8")

    prof = ProjectProfiler(str(tmp_path))
    assert prof._is_execution_scaffold_module("app/execution/bool_return.py")
    # Nested subpackage is NOT the flat scaffold family.
    assert not prof._is_execution_scaffold_module(
        "app/execution/objectives/deep.py")
    # A flat module that does not import a marker is not scaffold.
    assert not prof._is_execution_scaffold_module("app/execution/plain.py")
    # A file outside app/execution/ is never scaffold.
    assert not prof._is_execution_scaffold_module("app/core/alpha.py")
    # A path we cannot read is conservatively NOT scaffold.
    assert not prof._is_execution_scaffold_module("app/execution/missing.py")


def test_scaffold_exclusion_is_deterministic(tmp_path: Path):
    _write_execution_base(tmp_path)
    execdir = tmp_path / "app" / "execution"
    (execdir / "bool_return.py").write_text(
        _scaffold_module("a", factor=2), encoding="utf-8")
    (execdir / "comprehension.py").write_text(
        _scaffold_module("b", factor=3), encoding="utf-8")
    first = ProjectProfiler(str(tmp_path)).profile().generalizable_duplications
    second = ProjectProfiler(str(tmp_path)).profile().generalizable_duplications
    assert first == second


# ===========================================================================
# Fix 2 — a thin empty __init__.py is NOT a hub-coverage target
# ===========================================================================

def _fan_in_importers(root: Path, target_import: str, count: int) -> None:
    """Write ``count`` modules that each import ``target_import`` so the target
    accrues fan-in (clearing the hub bar)."""
    pkg = root / "app" / "deps"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for i in range(count):
        (pkg / f"importer_{i}.py").write_text(
            f"import {target_import}\n\n"
            f"def use_{i}():\n    return {i}\n",
            encoding="utf-8",
        )


def test_thin_empty_init_is_not_a_hub_coverage_target(tmp_path: Path):
    # A blank app/hub/__init__.py with many importers clears the fan-in bar but
    # defines NOTHING to regress — it must NOT become a hub-coverage target.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    hubdir = tmp_path / "app" / "hub"
    hubdir.mkdir()
    (hubdir / "__init__.py").write_text("", encoding="utf-8")  # 0 symbols
    _fan_in_importers(tmp_path, "app.hub", count=5)

    profile = ProjectProfiler(str(tmp_path)).profile()
    hub_modules = {h["module"] for h in profile.hub_untested_modules}
    assert "app/hub/__init__.py" not in hub_modules
    # And no "Cover the dependency hub" idea is seeded for it.
    titles = [r.title for r in IdeaSeeder().seed(profile)]
    assert not any(
        "Cover the dependency hub" in t and "app/hub/__init__.py" in t
        for t in titles
    )


def test_real_hub_module_with_symbols_still_seeds_a_coverage_idea(tmp_path: Path):
    # A real module that defines code AND has many untested dependents is still
    # the high-leverage coverage target — the symbol floor must not drop it from
    # the idea set. (Such a module is ALSO fragile, so the more-severe fragility
    # root claims it before hub-untested — both are "cover this heavily-depended-
    # on hub" coverage ideas; the point is the floor never silences a real hub.)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    core = tmp_path / "app" / "core.py"
    core.write_text(
        "def compute(x):\n"
        "    if x > 0:\n"
        "        return x * 2\n"
        "    return -x\n\n"
        "def helper(y):\n"
        "    return y + 1\n",
        encoding="utf-8",
    )
    _fan_in_importers(tmp_path, "app.core", count=5)

    profile = ProjectProfiler(str(tmp_path)).profile()
    # The real hub IS a coverage target (via fragility and/or hub-untested).
    covered = (
        {h["module"] for h in profile.hub_untested_modules}
        | set(profile.fragile_modules)
    )
    assert "app/core.py" in covered
    # And a coverage idea naming it IS seeded.
    titles = [r.title for r in IdeaSeeder().seed(profile)]
    assert any("app/core.py" in t for t in titles)


def test_empty_init_dropped_but_real_hub_kept_together(tmp_path: Path):
    # Both in one tree: the empty package shell is dropped from EVERY coverage
    # path, while the real code hub is still surfaced as a coverage target.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    hubdir = tmp_path / "app" / "shell"
    hubdir.mkdir()
    (hubdir / "__init__.py").write_text("", encoding="utf-8")
    core = tmp_path / "app" / "core.py"
    core.write_text(
        "def run(x):\n    if x:\n        return 1\n    return 0\n",
        encoding="utf-8",
    )
    _fan_in_importers(tmp_path, "app.shell", count=4)
    _fan_in_importers(tmp_path, "app.core", count=4)

    profile = ProjectProfiler(str(tmp_path)).profile()
    covered = (
        {h["module"] for h in profile.hub_untested_modules}
        | set(profile.fragile_modules)
    )
    # The empty shell is never a coverage target.
    assert "app/shell/__init__.py" not in covered
    # The real code hub still is.
    assert "app/core.py" in covered


def test_hub_floor_is_deterministic(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    hubdir = tmp_path / "app" / "hub"
    hubdir.mkdir()
    (hubdir / "__init__.py").write_text("", encoding="utf-8")
    _fan_in_importers(tmp_path, "app.hub", count=5)
    first = ProjectProfiler(str(tmp_path)).profile().hub_untested_modules
    second = ProjectProfiler(str(tmp_path)).profile().hub_untested_modules
    assert first == second


def test_hub_scan_floor_unit_level(tmp_path: Path):
    # Unit-level: passing symbol_counts gates a 0-symbol hub; omitting it
    # (symbol_counts=None) preserves the prior behaviour (no floor).
    prof = ProjectProfiler(str(tmp_path))

    class _Node:
        def __init__(self, path, in_degree):
            self.path = path
            self.in_degree = in_degree

    graph = {
        "app/empty/__init__.py": _Node("app/empty/__init__.py", 5),
        "app/real.py": _Node("app/real.py", 5),
    }
    module_to_tests: dict = {}  # both untested
    counts = {"app/empty/__init__.py": 0, "app/real.py": 3}

    with_floor = prof._scan_hub_untested_modules(
        graph, module_to_tests, shallow=set(), claimed=set(),
        symbol_counts=counts)
    got = {h["module"] for h in with_floor}
    assert got == {"app/real.py"}

    # No symbol_counts -> floor not applied -> both kept (back-compat).
    without_floor = prof._scan_hub_untested_modules(
        graph, module_to_tests, shallow=set(), claimed=set())
    assert {h["module"] for h in without_floor} == {
        "app/empty/__init__.py", "app/real.py"}
