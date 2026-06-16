"""Characterization harness for the ``_scan_god_classes`` refactor.

Proves the decomposed implementation is byte-identical to the pre-refactor
original (snapshotted from ``HEAD`` at refactor time) across several
representative temp trees: same ``profile.god_classes`` list — order and
contents — for every input. Offline, stdlib + pytest only.

The "original" is loaded by importing the HEAD snapshot of the module under a
distinct name and instantiating its mixin against the SAME ``ProjectProfiler``
attribute surface, so both implementations see identical inputs and only the
``_scan_god_classes`` logic differs.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.tools.project_profile import ProjectProfiler

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_REL = "app/tools/profile_scanners.py"


def _load_original_mixin():
    """Import the HEAD snapshot of profile_scanners.py as a throwaway module and
    return its ``_CodeQualityScansMixin`` class (the pre-refactor scan)."""
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{TARGET_REL}"], cwd=str(REPO_ROOT)
    ).decode("utf-8")
    mod = types.ModuleType("_orig_profile_scanners_god")
    spec = importlib.util.spec_from_loader(mod.__name__, loader=None)
    mod.__spec__ = spec
    sys.modules[mod.__name__] = mod
    exec(compile(src, "<orig_profile_scanners_god>", "exec"), mod.__dict__)
    return mod._CodeQualityScansMixin


_OriginalMixin = _load_original_mixin()


class _OriginalProfiler(_OriginalMixin, ProjectProfiler):
    """ProjectProfiler whose ``_scan_god_classes`` is the HEAD-snapshot original.

    MRO puts the original mixin first, so ``_scan_god_classes`` (and the helpers
    it carries) come from the snapshot, while every other attribute
    (``root``, ``max_files``, ``_is_fixture_path``, ...) is the real profiler's.
    """


def _make_profile():
    """A bare object the scanner can write ``god_classes`` onto."""
    return types.SimpleNamespace(god_classes=None)


def _run(profiler_cls, root: Path):
    prof = profiler_cls(str(root))
    out = _make_profile()
    prof._scan_god_classes(out)
    return out.god_classes


# --- helpers to synthesize classes -----------------------------------------

def _class_src(name: str, n_methods: int, attrs: list[str]) -> str:
    """A class with ``n_methods`` methods (the first sets ``attrs`` on self)."""
    lines = [f"class {name}:"]
    setters = "\n".join(f"        self.{a} = {i}" for i, a in enumerate(attrs))
    body0 = setters if setters else "        pass"
    lines.append("    def m0(self):")
    lines.append(body0)
    for i in range(1, n_methods):
        lines.append(f"    def m{i}(self):")
        lines.append("        return 1")
    return "\n".join(lines) + "\n"


# --- representative inputs -------------------------------------------------

def _tree_basic(root: Path) -> None:
    (root / "app").mkdir()
    (root / "tests").mkdir()
    # A genuine god-class (16 methods, several attrs).
    (root / "app" / "big.py").write_text(
        _class_src("God", 16, ["a", "b", "c", "d"])
    )
    # Exactly at the floor (15) — should be flagged.
    (root / "app" / "edge.py").write_text(
        _class_src("AtFloor", 15, ["x"])
    )
    # Below the floor (14) — ignored.
    (root / "app" / "ok.py").write_text(
        _class_src("Small", 14, ["y"])
    )
    # Fixture path — excluded.
    (root / "tests" / "test_huge.py").write_text(
        _class_src("HugeTest", 20, ["z"])
    )


def _tree_empty(root: Path) -> None:
    (root / "app").mkdir()
    (root / "app" / "tiny.py").write_text(
        "class A:\n    def one(self):\n        return 1\n"
    )


def _tree_nested_and_async(root: Path) -> None:
    (root / "pkg").mkdir()
    # Async methods count; a nested class's members do NOT count toward outer.
    methods = "\n".join(
        f"    async def a{i}(self):\n        self.v{i} = {i}\n        return {i}"
        for i in range(15)
    )
    src = (
        "class Outer:\n"
        f"{methods}\n"
        "    class Inner:\n"
        + "\n".join(f"        def n{i}(self):\n            return {i}"
                    for i in range(30))
        + "\n"
    )
    (root / "pkg" / "m.py").write_text(src)


def _tree_tie_sort(root: Path) -> None:
    # Two god-classes with the SAME method count in different modules — the
    # (-methods, module, classname) tie-break ordering must be identical.
    (root / "z").mkdir()
    (root / "z" / "b_mod.py").write_text(_class_src("Zebra", 15, ["p"]))
    (root / "z" / "a_mod.py").write_text(_class_src("Apple", 15, ["q"]))


def _tree_attr_variants(root: Path) -> None:
    # Tuple/star/aug-assign self targets all contribute to the attribute count.
    (root / "v").mkdir()
    methods = "\n".join(f"    def m{i}(self):\n        return {i}" for i in range(15))
    src = (
        "class Acc:\n"
        "    def setup(self):\n"
        "        self.a, self.b = 1, 2\n"
        "        (self.c, *self.d) = [1, 2, 3]\n"
        "        self.e += 1\n"
        f"{methods}\n"
    )
    (root / "v" / "acc.py").write_text(src)


def _tree_syntax_error(root: Path) -> None:
    (root / "app").mkdir()
    (root / "app" / "ok.py").write_text(_class_src("Fine", 15, ["a"]))
    (root / "app" / "broken.py").write_text("class Oops(:\n    pass\n")


_BUILDERS = [
    _tree_basic,
    _tree_empty,
    _tree_nested_and_async,
    _tree_tie_sort,
    _tree_attr_variants,
    _tree_syntax_error,
]


@pytest.mark.parametrize("builder", _BUILDERS, ids=[b.__name__ for b in _BUILDERS])
def test_god_classes_byte_identical_to_original(builder, tmp_path: Path):
    builder(tmp_path)
    original = _run(_OriginalProfiler, tmp_path)
    refactored = _run(ProjectProfiler, tmp_path)
    assert refactored == original, (
        f"{builder.__name__}: refactored god_classes diverged from HEAD snapshot"
    )


def test_helpers_are_static():
    """The pure per-AST analysis helpers don't bind ``self`` — determinism
    cannot depend on profiler state."""
    from app.tools.profile_scanners import _CodeQualityScansMixin as M

    for name in ("_class_method_count", "_class_attr_names"):
        assert isinstance(M.__dict__[name], staticmethod), name
