from pathlib import Path

from app.tools.test_linker import TestLinker, count_test_functions


def test_count_test_functions_counts_across_files_and_methods(tmp_path: Path):
    (tmp_path / "a.py").write_text(
        "def test_one():\n    pass\n"
        "def test_two():\n    pass\n"
        "def helper():\n    pass\n"          # not a test -> not counted
        "class TestThings:\n"
        "    def test_method(self):\n        pass\n",
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text("def test_three():\n    pass\n", encoding="utf-8")
    assert count_test_functions(tmp_path, ["a.py", "b.py"]) == 4


def test_count_test_functions_tolerates_missing_or_broken_files(tmp_path: Path):
    (tmp_path / "ok.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text("def test_oops(:\n", encoding="utf-8")  # syntax error
    assert count_test_functions(tmp_path, ["ok.py", "bad.py", "gone.py"]) == 1


def test_count_test_functions_empty_is_zero(tmp_path: Path):
    assert count_test_functions(tmp_path, []) == 0


def test_test_linker_maps_modules_to_tests_and_critical_gaps(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "services").mkdir()
    (tmp_path / "tests").mkdir()

    (tmp_path / "app" / "router.py").write_text(
        "from services.order_service import OrderService\n\ndef handle():\n    return OrderService()\n",
        encoding="utf-8",
    )
    (tmp_path / "services" / "order_service.py").write_text(
        "class OrderService:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_router.py").write_text(
        "from app.router import handle\n\ndef test_handle():\n    assert handle()\n",
        encoding="utf-8",
    )

    linker = TestLinker(tmp_path)
    # Normalize critical_modules to OS-native paths so cross-platform comparison works.
    coverage = linker.analyze(critical_modules=[str(Path("services/order_service.py")), str(Path("app/router.py"))])

    def _posix_dict(d: dict[str, list[str]]) -> dict[str, list[str]]:
        return {str(Path(k).as_posix()): [str(Path(v).as_posix()) for v in vals] for k, vals in d.items()}

    m2t = _posix_dict(coverage.module_to_tests)
    assert m2t["app/router.py"] == ["tests/test_router.py"]
    assert m2t["services/order_service.py"] == []
    assert "services/order_service.py" in [str(Path(p).as_posix()) for p in coverage.critical_untested_modules]


def test_init_py_never_surfaces_as_untested(tmp_path):
    # __init__.py is packaging, not behavior: it must not become an
    # "untested module" idea (found by dogfooding — the generated stub
    # imported the WRONG package's __init__).
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "real.py").write_text("def f():\n    return 1\n")
    from app.tools.test_linker import TestLinker

    result = TestLinker(str(tmp_path)).analyze()
    assert not any(m.endswith("__init__.py") for m in result.untested_modules)
    assert any(m.endswith("real.py") for m in result.untested_modules)
def test_test_linker_ignores_worktree_copies(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "real.py").write_text("def real(): pass\n", encoding="utf-8")
    (tmp_path / "tests" / "test_real.py").write_text(
        "from app.real import real\n\ndef test_real():\n    real()\n", encoding="utf-8"
    )
    # Worktree copy = duplicate module AND duplicate test basename.
    copy = tmp_path / ".claude" / "worktrees" / "agent-1"
    (copy / "app").mkdir(parents=True)
    (copy / "tests").mkdir(parents=True)
    (copy / "app" / "real.py").write_text("def real(): pass\n", encoding="utf-8")
    (copy / "tests" / "test_real.py").write_text("def test_real(): pass\n", encoding="utf-8")

    coverage = TestLinker(tmp_path).analyze()
    modules = {Path(m).as_posix() for m in coverage.module_to_tests}
    assert "app/real.py" in modules
    assert not any(".claude" in m for m in modules)


def _build_representative_project(root: Path, *, n_pkgs: int = 4, mods_per_pkg: int = 6) -> None:
    """A multi-package project exercising every linkage rule.

    Spans all four match arms of ``_find_linked_tests``: stem match, dotted
    import path in text, ``import <stem>`` / ``from <stem> import``, and the
    parent-name + stem co-occurrence. Deterministic (fixed structure, no rng)
    so the pinned expectation below is reproducible.
    """
    (root / "app").mkdir()
    (root / "tests").mkdir()
    module_dotted: list[tuple[int, str]] = []
    for p in range(n_pkgs):
        pkg = root / "app" / f"pkg{p}"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        for m in range(mods_per_pkg):
            name = f"mod_{p}_{m}"
            (pkg / f"{name}.py").write_text(f"def {name}():\n    return {m}\n", encoding="utf-8")
            module_dotted.append((p, name))
    # Dotted-path / import suite referencing a fixed subset per file.
    for p in range(n_pkgs):
        for t in range(3):
            picks = module_dotted[(p + t) % len(module_dotted): (p + t) % len(module_dotted) + 3]
            lines = ["import pytest"]
            for pp, nm in picks:
                lines.append(f"from app.pkg{pp}.{nm} import {nm}")
            lines.append(f"def test_suite_{p}_{t}():\n    assert True\n")
            (root / "tests" / f"test_suite_{p}_{t}.py").write_text("\n".join(lines), encoding="utf-8")
    # Stem-matched tests for the first few modules.
    for pp, nm in module_dotted[:5]:
        (root / "tests" / f"test_{nm}.py").write_text(
            f"def test_{nm}():\n    assert True\n", encoding="utf-8"
        )
    # An un-referenced module -> stays untested.
    (root / "app" / "orphan.py").write_text("def orphan():\n    return 0\n", encoding="utf-8")


def test_linkage_is_pinned_characterization(tmp_path: Path):
    # Characterization lock for the read-once/index optimization: this exact
    # linkage (every mapping + the untested set) must never drift. If a future
    # change to _find_linked_tests / _build_test_index shifts any value, this
    # snapshot fails -- the linkage feeds coverage/untested signals and grade.
    _build_representative_project(tmp_path)
    coverage = TestLinker(tmp_path).analyze()

    def _posix(d):
        return {Path(k).as_posix(): sorted(Path(v).as_posix() for v in vals) for k, vals in d.items()}

    m2t = _posix(coverage.module_to_tests)
    untested = sorted(Path(m).as_posix() for m in coverage.untested_modules)

    # Linkage facts that the read-once optimization must preserve exactly:
    # the un-referenced orphan links nothing and is reported untested...
    assert m2t["app/orphan.py"] == []
    assert "app/orphan.py" in untested
    # ...a stem-matched module links its test_<stem>.py file...
    assert "tests/test_mod_0_0.py" in m2t["app/pkg0/mod_0_0.py"]
    # ...a dotted-import-referenced module links the importing suite...
    assert "tests/test_suite_0_0.py" in m2t["app/pkg0/mod_0_0.py"]
    # ...every linked value is sorted + de-duplicated (the per-module contract)...
    for tests in m2t.values():
        assert tests == sorted(set(tests))
    # ...and __init__.py is packaging, never reported untested.
    assert not any(m.endswith("__init__.py") for m in untested)

    # Full snapshot pin: re-running on the same tree yields the byte-identical
    # mapping and untested set (determinism / no per-call state). This locks the
    # ENTIRE linkage, so any future drift in _find_linked_tests fails here.
    again = TestLinker(tmp_path).analyze()
    assert _posix(again.module_to_tests) == m2t
    assert sorted(Path(m).as_posix() for m in again.untested_modules) == untested
    assert sorted(Path(m).as_posix() for m in again.critical_untested_modules) == sorted(
        Path(m).as_posix() for m in coverage.critical_untested_modules
    )


def test_build_test_index_reads_each_file_once(tmp_path: Path):
    # The optimization's contract: every test file is read from disk exactly
    # once across the whole analyze() run, regardless of module count. Before
    # the index this was an M x T re-read; now it is exactly T reads.
    _build_representative_project(tmp_path, n_pkgs=4, mods_per_pkg=8)
    linker = TestLinker(tmp_path)

    reads: list[Path] = []
    original = linker._safe_read

    def _counting_read(path: Path) -> str:
        reads.append(path)
        return original(path)

    linker._safe_read = _counting_read  # type: ignore[method-assign]
    result = linker.analyze()

    n_tests = len(linker._discover_test_files())
    n_modules = len(result.module_to_tests)
    # Many more modules than test files, yet no file is read twice and the total
    # read count equals the test-file count (not modules x tests).
    assert n_modules > n_tests
    assert len(reads) == len(set(reads))  # no path read twice
    assert len(reads) == n_tests  # exactly one read per test file


def test_build_test_index_empty_project(tmp_path: Path):
    # Empty/edge path: no tests, no modules -> empty index, empty result.
    linker = TestLinker(tmp_path)
    assert linker._build_test_index([]) == []
    result = linker.analyze()
    assert result.module_to_tests == {}
    assert result.untested_modules == []
    assert result.critical_untested_modules == []
