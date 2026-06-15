from pathlib import Path

from app.tools.python_structure import PythonStructureAnalyzer


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
    assert "pathlib" in module.imports
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
    assert "b" in structure.imports
    assert "a" not in structure.imports
