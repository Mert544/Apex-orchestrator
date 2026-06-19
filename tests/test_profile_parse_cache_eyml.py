"""Byte-identical + read-once proof for routing the base profile walk and the
mixin AST scanners through the shared per-build parse cache.

Two contracts, both offline (stdlib + pytest only):

1. **Byte-identical output.** For several representative temp trees -- including
   one carrying an UNPARSABLE ``.py`` file -- a ``ProjectProfiler.profile()``
   built with the cache-routed code produces a profile whose ``__dict__`` equals
   the one the pre-change ``HEAD`` snapshot produced. The whole point of the
   change is a pure performance refactor: the cache key is ``(path, mtime)`` and
   never reaches any output, and an unparsable file is skipped exactly as the
   inline ``ast.parse`` except-clause skipped it, so nothing observable shifts.

2. **Fewer reads + shared parse.** The cache-routed build reads the in-scope
   ``.py`` files FEWER times than the pre-change ``HEAD`` snapshot did, and the
   three mixin AST scanners share ONE cached parse per file (via
   ``parse_cached``) instead of each re-parsing the whole tree. Before the change
   the base walk read each file three times and every mixin scanner re-parsed the
   whole tree; after it the shared cache collapses the routed paths to one parse
   per file. (Other analyzers the profiler invokes -- the dependency graph, test
   linker, extract/inline/near-dup scans -- live in other modules and keep their
   own reads; this test counts only the routing the change controls.)

The "original" is the ``HEAD`` snapshot of BOTH touched modules
(``app/tools/project_profile.py`` and ``app/tools/profile_scanners.py``), loaded
under throwaway names and wired together so the snapshot's profiler is exercised
on the SAME inputs as the live one.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

import app.tools.python_structure as ps
from app.tools.project_profile import ProjectProfiler

REPO_ROOT = Path(__file__).resolve().parents[1]
_PROFILE_REL = "app/tools/project_profile.py"
_SCANNERS_REL = "app/tools/profile_scanners.py"


def _git_show(rel: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"HEAD:{rel}"], cwd=str(REPO_ROOT)
    ).decode("utf-8")


def _exec_module(name: str, src: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod.__spec__ = spec
    sys.modules[name] = mod
    exec(compile(src, f"<{name}>", "exec"), mod.__dict__)
    return mod


def _load_original_profiler():
    """Build a ``ProjectProfiler`` class from the HEAD snapshot of BOTH modules.

    The snapshot ``project_profile`` imports ``_CodeQualityScansMixin`` from
    ``app.tools.profile_scanners`` by absolute name, so we temporarily install
    the snapshot scanners module under that name, exec the snapshot profiler
    against it, then restore the real modules. The two are self-consistent: the
    profiler we return is the pre-change implementation end to end.
    """
    scanners_src = _git_show(_SCANNERS_REL)
    profile_src = _git_show(_PROFILE_REL)

    saved = {
        name: sys.modules.get(name)
        for name in ("app.tools.profile_scanners", "app.tools.project_profile")
    }
    try:
        _exec_module("app.tools.profile_scanners", scanners_src)
        prof_mod = _exec_module("app.tools.project_profile", profile_src)
        return prof_mod.ProjectProfiler
    finally:
        for name, mod in saved.items():
            if mod is not None:
                sys.modules[name] = mod
            else:  # pragma: no cover - both modules are always already imported
                sys.modules.pop(name, None)


_OriginalProfiler = _load_original_profiler()


# Parse-aware scope-honesty fields added AFTER this HEAD snapshot was taken
# (``fix(scope): parse-aware honest analyzed-ratio``). They are ADDITIVE: the
# HEAD-snapshot profiler does not set them, so the live profiler's dict carries
# three extra keys it cannot. This test's contract is that the parse-CACHE
# routing produced byte-identical output for every pre-existing field, NOT that
# no field is ever added later, so these additive keys are dropped from BOTH
# sides before the comparison. (The parse-aware behaviour has its own dedicated
# suite: ``tests/test_scope_parse_aware_eyml.py``.)
_POST_SNAPSHOT_FIELDS = ("unparsed_files", "unparsed_count", "analyzed_ratio_honest")


def _profile_dict(profiler_cls, root: Path) -> dict:
    # A fresh per-build cache for every profile, exactly as a new process would
    # see -- the cache must never leak state (or mtime keys) across builds.
    ps._PARSE_CACHE.clear()
    ps._TREE_CACHE.clear()
    d = dict(profiler_cls(str(root)).profile(light=False).__dict__)
    for key in _POST_SNAPSHOT_FIELDS:
        d.pop(key, None)
    return d


# --- representative trees ---------------------------------------------------

def _method_block(n: int) -> str:
    return "\n".join(f"    def m{i}(self):\n        return {i}" for i in range(n))


def _tree_mixed(root: Path) -> None:
    """A realistic small repo: a god-class, a deeply-nested function, a module
    with a dead param, debt markers and a security finding -- so every routed
    scanner and base-walk detector has something to find."""
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "big.py").write_text(
        "class God:\n" + _method_block(16) + "\n"
    )
    (root / "app" / "nested.py").write_text(
        "def staircase(x):\n"
        "    if x:\n"
        "        for i in range(x):\n"
        "            while i:\n"
        "                with open('f') as fh:\n"
        "                    try:\n"
        "                        return fh\n"
        "                    except OSError:\n"
        "                        pass\n"
    )
    (root / "app" / "deadparam.py").write_text(
        "def uniquely_named_fn(used, unused_one):\n"
        "    return used + 1\n"
    )
    (root / "app" / "debt.py").write_text(
        "# TODO: one\n# FIXME: two\n# XXX: three\nx = 1\n"
    )
    (root / "app" / "danger.py").write_text(
        "import os\n\n\ndef run(cmd):\n    os.system(cmd)\n"
    )
    # Fixture/test code -- excluded everywhere.
    (root / "tests" / "test_thing.py").write_text(
        "class HugeTest:\n" + _method_block(20) + "\n"
    )


def _tree_unparsable(root: Path) -> None:
    """A tree with a syntactically broken module: the cache returns ``None`` for
    it and every routed scanner must SKIP it, identically to the old inline
    ``ast.parse`` except-clause."""
    (root / "app").mkdir()
    (root / "app" / "ok.py").write_text("class Fine:\n" + _method_block(15) + "\n")
    (root / "app" / "broken.py").write_text("class Oops(:\n    pass\n")
    (root / "app" / "also_broken.py").write_text("def f(:\n    return\n")


def _tree_empty(root: Path) -> None:
    (root / "app").mkdir()
    (root / "app" / "tiny.py").write_text(
        "def f():\n    return 1\n"
    )


_BUILDERS = [_tree_mixed, _tree_unparsable, _tree_empty]


@pytest.mark.parametrize("builder", _BUILDERS, ids=[b.__name__ for b in _BUILDERS])
def test_profile_byte_identical_to_head_snapshot(builder, tmp_path: Path):
    builder(tmp_path)
    original = _profile_dict(_OriginalProfiler, tmp_path)
    routed = _profile_dict(ProjectProfiler, tmp_path)
    assert routed == original, (
        f"{builder.__name__}: cache-routed profile diverged from HEAD snapshot"
    )


def _count_total_io(profiler_cls, root: Path) -> tuple[int, int, int]:
    """Run ``profiler_cls(root).profile()`` while counting, for the in-scope
    ``.py`` files under ``root``, the total number of ``Path.read_text`` calls,
    the total number of ``ast.parse`` calls flowing through the SHARED cache
    (``app.tools.python_structure.parse_cached``'s ``_parse_tree``), and the
    number of DISTINCT files that cache ended up holding a tree for.

    The shared-cache parse count is the load-bearing one: before the change each
    of the three mixin scanners ran its own ``ast.parse`` over the whole tree, so
    a file routed through the cache is parsed once instead of three times.
    """
    reads = 0
    root_resolved = str(root.resolve())

    real_read_text = Path.read_text
    real_parse_tree = ps._parse_tree

    cache_parses = {"n": 0}

    def counting_read_text(self, *a, **k):
        nonlocal reads
        try:
            rp = str(self.resolve())
        except OSError:
            rp = str(self)
        if rp.endswith(".py") and root_resolved in rp:
            reads += 1
        return real_read_text(self, *a, **k)

    def counting_parse_tree(path):
        cache_parses["n"] += 1
        return real_parse_tree(path)

    try:
        Path.read_text = counting_read_text  # type: ignore[method-assign]
        ps._parse_tree = counting_parse_tree  # type: ignore[assignment]
        ps._PARSE_CACHE.clear()
        ps._TREE_CACHE.clear()
        profiler_cls(str(root)).profile(light=False)
        cached_files = len(ps._TREE_CACHE)
    finally:
        Path.read_text = real_read_text  # type: ignore[method-assign]
        ps._parse_tree = real_parse_tree  # type: ignore[assignment]
    return reads, cache_parses["n"], cached_files


def test_routing_reduces_reads_and_parses_vs_head_snapshot(tmp_path: Path):
    """The cache-routed build reads the in-scope ``.py`` files FEWER times than
    the HEAD snapshot did, and the mixin AST scanners share ONE cached parse per
    file instead of re-parsing the whole tree three times.

    The routed build's total ``read_text`` count over the in-scope files is
    strictly lower (base walk 3->1 per ``.py`` plus the three mixin scanners
    reusing cached trees instead of each re-reading + re-parsing the tree). The
    shared cache parses each cached file exactly once (``_parse_tree`` call count
    == distinct cached files), proving the mixin scanners share one parse rather
    than tripling it."""
    _tree_mixed(tmp_path)

    old_reads, _old_cache_parses, _ = _count_total_io(_OriginalProfiler, tmp_path)
    new_reads, new_cache_parses, cached_files = _count_total_io(ProjectProfiler, tmp_path)

    # The shared cache parses each file it holds exactly once -- the three mixin
    # scanners that used to each re-parse the whole tree now share these trees.
    assert new_cache_parses == cached_files

    # Fewer disk reads of the in-scope sources than the un-routed snapshot.
    assert new_reads < old_reads, (
        f"expected fewer reads after routing: old={old_reads} new={new_reads}"
    )


def test_cache_skips_unparsable_file_consistently(tmp_path: Path):
    """An unparsable module yields ``None`` from the cache and is skipped by the
    routed scanners exactly as the HEAD snapshot skipped it -- the god-class in
    the sibling parsable file is still found, the broken files contribute
    nothing, and the two implementations agree byte for byte."""
    _tree_unparsable(tmp_path)
    original = _profile_dict(_OriginalProfiler, tmp_path)
    routed = _profile_dict(ProjectProfiler, tmp_path)
    assert routed["god_classes"] == original["god_classes"]
    assert [g["module"] for g in routed["god_classes"]] == ["app/ok.py"]
    assert routed == original
