import ast
import time
from pathlib import Path

from app.tools.python_structure import (
    PythonStructureAnalyzer,
    _PARSE_CACHE,
    _TREE_CACHE,
    _parse_file,
    parse_cached,
)


def test_python_structure_analyzer_extracts_imports_and_symbols(tmp_path: Path):
    source = tmp_path / "service.py"
    source.write_text(
        "import os\nfrom pathlib import Path\n\nclass Service:\n    pass\n\ndef build_path():\n    return Path('.')\n",
        encoding="utf-8",
    )

    results = PythonStructureAnalyzer(tmp_path).analyze()
    assert len(results) == 1
    module = results[0]
    assert module.path == "service.py"
    assert "os" in module.imports
    # `from pathlib import Path` records the submodule-qualified edge so the
    # resolver can reach a real `pathlib/Path` target, falling back to the
    # package only when the name is a bare symbol (the import-style fix).
    assert "pathlib.Path" in module.imports
    assert "Service" in module.symbols
    assert "build_path" in module.symbols


def test_python_structure_ignores_worktree_copies(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("def real(): pass\n", encoding="utf-8")
    copy = tmp_path / ".claude" / "worktrees" / "agent-1" / "app"
    copy.mkdir(parents=True)
    (copy / "copy.py").write_text("def copy(): pass\n", encoding="utf-8")

    results = PythonStructureAnalyzer(tmp_path).analyze()
    paths = {Path(m.path).as_posix() for m in results}
    assert paths == {"app/real.py"}


def test_unparseable_file_is_dropped_returns_none(tmp_path: Path):
    good = tmp_path / "good.py"
    good.write_text("def ok():\n    return 1\n", encoding="utf-8")
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n    pass\n", encoding="utf-8")  # SyntaxError

    analyzer = PythonStructureAnalyzer(tmp_path)
    # The unparseable module is dropped (None) rather than raising...
    assert analyzer._analyze_file(bad) is None
    # ...while the valid module survives.
    paths = {m.path for m in analyzer.analyze()}
    assert "good.py" in paths
    assert "bad.py" not in paths


def test_narrowed_except_does_not_swallow_unrelated_error(tmp_path: Path):
    analyzer = PythonStructureAnalyzer(tmp_path)
    # A non-Path argument triggers AttributeError on .read_text, which is NOT in
    # the narrowed (SyntaxError, OSError, ValueError) tuple, so it surfaces
    # instead of being silently turned into None.
    import pytest

    with pytest.raises(AttributeError):
        analyzer._analyze_file(object())  # type: ignore[arg-type]


def test_type_checking_imports_are_not_counted(tmp_path: Path):
    # Imports guarded by `if TYPE_CHECKING:` never run, so they must NOT appear as
    # import edges — otherwise a type-hint import added to BREAK a cycle gets
    # miscounted AS a cycle (a false positive that cost real grade points).
    source = tmp_path / "mod.py"
    source.write_text(
        "from __future__ import annotations\n"
        "from typing import TYPE_CHECKING\n"
        "import os\n"
        "if TYPE_CHECKING:\n"
        "    from app.tools.project_profile import ProjectProfile\n"
        "    import json\n"
        "def f(p: ProjectProfile) -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )
    structure = PythonStructureAnalyzer(tmp_path)._analyze_file(source)
    assert structure is not None
    # The runtime import survives; the two TYPE_CHECKING-only imports are dropped.
    assert "os" in structure.imports
    assert "app.tools.project_profile" not in structure.imports
    assert "json" not in structure.imports


def test_type_checking_else_arm_is_still_counted(tmp_path: Path):
    # The `else` of `if TYPE_CHECKING:` DOES execute at runtime, so its imports
    # are real edges and must be kept.
    source = tmp_path / "mod2.py"
    source.write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from a import OnlyForTypes\n"
        "else:\n"
        "    from b import RealRuntimeDep\n",
        encoding="utf-8",
    )
    structure = PythonStructureAnalyzer(tmp_path)._analyze_file(source)
    assert structure is not None
    # The runtime `else`-arm edge is submodule-qualified (`from b import
    # RealRuntimeDep` → `b.RealRuntimeDep`); the TYPE_CHECKING-only `a` edge is
    # still dropped entirely.
    assert "b.RealRuntimeDep" in structure.imports
    assert "a" not in structure.imports
    assert "a.OnlyForTypes" not in structure.imports


def _write_multi_file_project(root: Path) -> None:
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text(
        "import os\nfrom pathlib import Path\n\nclass A:\n    def m(self):\n        return Path('.')\n",
        encoding="utf-8",
    )
    (pkg / "b.py").write_text(
        "from typing import TYPE_CHECKING\nimport json\n\n"
        "if TYPE_CHECKING:\n    from pkg.a import A\n\n"
        "def build():\n    return json.dumps({})\n",
        encoding="utf-8",
    )
    (root / "top.py").write_text(
        "import sys\n\nasync def go():\n    return sys.argv\n",
        encoding="utf-8",
    )


def test_repeated_analyze_returns_identical_module_structures(tmp_path: Path):
    # Two analyzers over the SAME unchanged tree must produce byte-for-byte equal
    # ModuleStructure lists. The second run is served from the parse cache, so this
    # proves the cache introduces no drift in path / imports / symbols.
    _write_multi_file_project(tmp_path)

    first = PythonStructureAnalyzer(tmp_path).analyze()
    second = PythonStructureAnalyzer(tmp_path).analyze()

    assert [(m.path, m.imports, m.symbols) for m in first] == [
        (m.path, m.imports, m.symbols) for m in second
    ]
    # The TYPE_CHECKING-only import is dropped in BOTH runs (cache preserves it).
    b = next(m for m in first if m.path.endswith("b.py"))
    assert "json" in b.imports
    assert "pkg.a" not in b.imports

    # The cache returns COPIES: mutating one result must not corrupt the next run.
    first[0].imports.append("__poison__")
    third = PythonStructureAnalyzer(tmp_path).analyze()
    assert "__poison__" not in third[0].imports


def test_cache_serves_hit_for_unchanged_file(tmp_path: Path):
    source = tmp_path / "m.py"
    source.write_text("import os\n\ndef f():\n    return os\n", encoding="utf-8")

    stat = source.stat()
    key = (str(source.resolve()), stat.st_mtime_ns)
    _PARSE_CACHE.pop(key, None)

    first = _parse_file(source)
    assert key in _PARSE_CACHE
    # A second call for the unchanged file returns the SAME cached object identity
    # (cache hit, no re-parse) yet equal content.
    second = _parse_file(source)
    assert second is first
    assert second == (["os"], ["f"])


def test_cache_respects_mtime_change(tmp_path: Path):
    # A file rewritten between builds gets a new mtime -> a new key -> a fresh
    # parse, so stale results are never served. This is the correctness guarantee
    # tests of changing tmp files rely on.
    source = tmp_path / "evolving.py"
    source.write_text("def old():\n    return 1\n", encoding="utf-8")
    before = _parse_file(source)
    assert before == ([], ["old"])

    # Force a distinct mtime even on coarse-grained filesystems.
    new_ns = source.stat().st_mtime_ns + 1_000_000_000
    source.write_text("import os\n\ndef new():\n    return os\n", encoding="utf-8")
    import os as _os

    _os.utime(source, ns=(new_ns, new_ns))

    after = _parse_file(source)
    assert after == (["os"], ["new"])
    # The original key still maps to the original parse (mtime-keyed isolation).
    old_key = (str(source.resolve()), source.stat().st_mtime_ns)
    assert old_key in _PARSE_CACHE


def test_cache_makes_second_analyze_faster(tmp_path: Path, monkeypatch):
    # The warm second analyze() over a multi-file tree must be served ENTIRELY
    # from the process-level parse cache. Pinned on the actual ast.parse CALL
    # COUNT, not wall-clock: the old timing probe (warm_dt < cold_dt) was
    # context-fragile — in a full gate chunk (~2800 prior tests) a GC pause
    # landing in the warm window flipped it even though the cache worked
    # (warm 58ms vs cold 8ms, reproduced 4x in-chunk, green solo). Counting
    # parses asserts the SAME claim ("guard against the cache silently being
    # bypassed") deterministically — and STRICTER: zero re-parses, not merely
    # "faster".
    pkg = tmp_path / "many"
    pkg.mkdir()
    for i in range(40):
        (pkg / f"mod_{i}.py").write_text(
            f"import os\nimport sys\nfrom pathlib import Path\n\n"
            f"class C{i}:\n    def method(self):\n        return Path('.')\n\n"
            f"def fn_{i}():\n    return os, sys\n",
            encoding="utf-8",
        )

    import app.tools.python_structure as ps
    calls = {"n": 0}
    real_parse = ps.ast.parse

    def counting_parse(*args, **kwargs):
        calls["n"] += 1
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(ps.ast, "parse", counting_parse)

    cold = PythonStructureAnalyzer(tmp_path).analyze()
    cold_parses = calls["n"]
    warm = PythonStructureAnalyzer(tmp_path).analyze()
    warm_parses = calls["n"] - cold_parses

    assert len(cold) == len(warm) == 40
    assert cold_parses >= 40  # the cold run genuinely parsed the fresh tree
    assert warm_parses == 0   # the warm run re-parsed NOTHING — pure cache


def test_parse_cached_returns_module_equal_to_direct_parse(tmp_path: Path):
    src = "import os\n\n\ndef f(x):\n    if x:\n        return os\n    return None\n"
    mod = tmp_path / "m.py"
    mod.write_text(src, encoding="utf-8")
    tree = parse_cached(mod)
    assert isinstance(tree, ast.Module)
    # Same content -> structurally identical tree (byte-identical dumps).
    assert ast.dump(tree) == ast.dump(ast.parse(src))


def test_parse_cached_serves_hit_for_unchanged_file(tmp_path: Path):
    mod = tmp_path / "hit.py"
    mod.write_text("def g():\n    return 1\n", encoding="utf-8")
    key = (str(mod.resolve()), mod.stat().st_mtime_ns)
    _TREE_CACHE.pop(key, None)

    first = parse_cached(mod)
    assert key in _TREE_CACHE
    # A second call returns the very same cached object (no re-parse).
    second = parse_cached(mod)
    assert first is second


def test_parse_cached_respects_mtime_change(tmp_path: Path):
    mod = tmp_path / "chg.py"
    mod.write_text("def a():\n    return 1\n", encoding="utf-8")
    before = parse_cached(mod)
    old_key = (str(mod.resolve()), mod.stat().st_mtime_ns)

    import os as _os
    st = mod.stat()
    _os.utime(mod, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    mod.write_text("def a():\n    return 2\n", encoding="utf-8")

    after = parse_cached(mod)
    assert after is not before
    new_key = (str(mod.resolve()), mod.stat().st_mtime_ns)
    assert old_key in _TREE_CACHE and new_key in _TREE_CACHE


def test_parse_cached_none_for_unparseable_and_missing(tmp_path: Path):
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n", encoding="utf-8")
    assert parse_cached(bad) is None
    assert parse_cached(tmp_path / "nope.py") is None


def test_tree_cache_is_independent_of_parse_cache(tmp_path: Path):
    # The tree cache must not touch the existing (imports, symbols) cache.
    mod = tmp_path / "indep.py"
    mod.write_text("import os\n\n\ndef h():\n    return os\n", encoding="utf-8")
    _PARSE_CACHE.clear()
    parse_cached(mod)  # populates _TREE_CACHE only
    assert _PARSE_CACHE == {}
    _parse_file(mod)   # now populates _PARSE_CACHE
    assert any(k[0] == str(mod.resolve()) for k in _PARSE_CACHE)
