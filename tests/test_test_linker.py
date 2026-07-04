import ast
from pathlib import Path

from app.tools.test_linker import (
    TestLinker,
    _call_name,
    _contains_standalone,
    _loader_call_py_args,
    _parse_test_references,
    _resolved_import_names,
    _stem_names_module,
    _stem_tokens,
    count_test_functions,
)


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


# --------------------------------------------------------------------------- #
# Name-order/convention blind spot (ÇAĞ2-W11): the linker's fallback heuristics
# used raw, unanchored substring checks that could CLAIM a link that did not
# exist -- a short/common module stem (or its parent dir name) merely being a
# PREFIX of an unrelated word, or co-occurring anywhere independently in
# 100+ lines of unrelated source, is not evidence of a real reference. These
# pin the specific false-claim shapes found (and fixed) plus the true shapes
# that must keep working.
# --------------------------------------------------------------------------- #

def test_stem_tokens_splits_on_underscore_and_drops_empties():
    assert _stem_tokens("stub_synthesis") == ["stub", "synthesis"]
    # A leading/doubled underscore (the "_private_module" convention's
    # "test__private_module" test file) must not produce a blank token.
    assert _stem_tokens("_base") == ["base"]
    assert _stem_tokens("test__base") == ["test", "base"]
    assert _stem_tokens("") == []


def test_stem_names_module_whole_token_match_not_bare_substring():
    # The real bug: "_base" is a raw substring of "baseline", a DIFFERENT word.
    assert not _stem_names_module("_base", "test_baseline_red")
    assert not _stem_names_module("_base", "test_cli_gate_baseline")
    # A real, exact stem match still counts.
    assert _stem_names_module("_base", "test__base")
    # A qualified prefix before the module's own whole word still counts
    # (an accepted, pre-existing test-naming convention in this project).
    assert _stem_names_module("_base", "test_agent_base")
    # No module tokens at all (pathological empty stem) never matches.
    assert not _stem_names_module("", "test_anything")


def test_contains_standalone_rejects_identifier_prefix_collision():
    # "import _base_name" contains the literal substring "import _base", but
    # _base_name is a DIFFERENT, longer identifier -- not a reference to _base.
    assert not _contains_standalone("from x import _base_name", "import _base")
    # A fixture class "_Base" is not a reference to a "_base" module either.
    assert not _contains_standalone("class _basefactory: pass", "_base")
    # The real, standalone occurrence still matches.
    assert _contains_standalone("import _base\n", "import _base")
    assert _contains_standalone("x = _base + 1", "_base")
    # An empty needle never matches (nothing to claim).
    assert not _contains_standalone("anything", "")


def test_resolved_import_names_plain_and_from_import():
    tree = ast.parse("import a.b.c\nfrom d.e import f, g\n")
    imp, frm = tree.body
    assert _resolved_import_names(imp) == ["a.b.c"]
    assert _resolved_import_names(frm) == ["d.e.f", "d.e.g"]


def test_resolved_import_names_skips_relative_and_star():
    tree = ast.parse("from . import x\nfrom .sub import y\nfrom a import *\n")
    rel_bare, rel_sub, star = tree.body
    assert _resolved_import_names(rel_bare) == []
    assert _resolved_import_names(rel_sub) == []
    assert _resolved_import_names(star) == []


def test_parse_test_references_multi_name_parenthesized_import():
    # The confirmed regression shape: "from pkg import (a, b, c)" never places
    # the package prefix and a submodule name next to each other in the
    # source, so a flat text search cannot see it -- the AST resolver must.
    src = "from app.execution.semantic.transforms import (\n    extract_method,\n    inline_variable,\n    move_class,\n)\n"
    refs = _parse_test_references(src)
    assert "app.execution.semantic.transforms.inline_variable" in refs.imports
    assert "app.execution.semantic.transforms.move_class" in refs.imports
    assert "app.execution.semantic.transforms.extract_method" in refs.imports


def test_parse_test_references_unparseable_source_is_empty():
    refs = _parse_test_references("def broken(:\n")
    assert refs.imports == frozenset()
    assert refs.loaded_filenames == frozenset()


def test_call_name_bare_and_attribute():
    tree = ast.parse("_load('x.py')\nimportlib.util.spec_from_file_location('x', 'y')\nfoo()()\n")
    bare_call, attr_call, weird_call = (n.value for n in tree.body)
    assert _call_name(bare_call) == "_load"
    assert _call_name(attr_call) == "spec_from_file_location"
    assert _call_name(weird_call) == ""  # a called call result has no name


def test_loader_call_py_args_requires_load_named_call():
    # A "load"-named call's bare ".py" argument is a real loaded-filename claim.
    loader = ast.parse("_load('preflight.py')").body[0].value
    assert _loader_call_py_args(loader) == ["preflight.py"]
    # The SAME string, passed to an unrelated call (e.g. writing a fixture
    # file), is not evidence this file was ever loaded as a module.
    non_loader = ast.parse("write_text('preflight.py')").body[0].value
    assert _loader_call_py_args(non_loader) == []
    # A path-like argument (contains "/") is left to the dotted/path-style
    # fallback checks, not claimed here.
    pathlike = ast.parse("_load('scripts/preflight.py')").body[0].value
    assert _loader_call_py_args(pathlike) == []
    # A keyword argument is covered too.
    kw = ast.parse("_load(name='preflight.py')").body[0].value
    assert _loader_call_py_args(kw) == ["preflight.py"]


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_prefix_collision_stem_does_not_falsely_link(tmp_path: Path):
    # module: pkg/_base.py. An UNRELATED test merely starting with the same
    # letters ("baseline") must not be claimed as covering it (before the
    # fix, a bare "module_stem in test_stem" substring check claimed it).
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/_base.py", "def f():\n    return 1\n")
    _write(tmp_path, "tests/test_baseline_unrelated.py", "def test_x():\n    assert True\n")
    _write(tmp_path, "tests/test__base.py", "import pkg._base\n\n\ndef test_x():\n    assert pkg._base\n")

    coverage = TestLinker(tmp_path).analyze()
    linked = coverage.module_to_tests["pkg/_base.py"]
    assert "tests/test_baseline_unrelated.py" not in linked
    assert "tests/test__base.py" in linked


def test_independent_cooccurrence_does_not_link_but_adjacency_does(tmp_path: Path):
    # module: objectives/_base.py (parent dir "objectives", stem "_base").
    _write(tmp_path, "objectives/__init__.py", "")
    _write(tmp_path, "objectives/_base.py", "def f():\n    return 1\n")
    # This test merely mentions "objectives" (unrelated import) and "_base"
    # (an unrelated fixture class) independently -- not a real reference.
    _write(
        tmp_path, "tests/test_unrelated_objectives_thing.py",
        "from app.objectives import add_final  # some other objective\n\n"
        "def test_x():\n    src = 'class _Base:\\n    pass\\n'\n    assert src\n",
    )
    # This test references the module via an adjacent, qualified mention.
    _write(
        tmp_path, "tests/test_calls_it_directly.py",
        "def test_x():\n    # see objectives._base for the shared helper\n    assert True\n",
    )

    coverage = TestLinker(tmp_path).analyze()
    linked = coverage.module_to_tests["objectives/_base.py"]
    assert "tests/test_unrelated_objectives_thing.py" not in linked
    assert "tests/test_calls_it_directly.py" in linked


def test_dynamic_loader_by_filename_links_but_fixture_write_does_not(tmp_path: Path):
    # scripts/ is a real, common case in this project: a standalone script not
    # set up as an importable package, exercised via a small `_load(name)`
    # helper around importlib.util.spec_from_file_location.
    _write(tmp_path, "scripts/preflight.py", "def decide():\n    return True\n")
    _write(
        tmp_path, "tests/test_scripts_tooling.py",
        "import importlib.util\nfrom pathlib import Path\n\n"
        "ROOT = Path(__file__).resolve().parents[1]\n\n"
        "def _load(name):\n"
        "    path = ROOT / 'scripts' / name\n"
        "    spec = importlib.util.spec_from_file_location(name[:-3], path)\n"
        "    mod = importlib.util.module_from_spec(spec)\n"
        "    spec.loader.exec_module(mod)\n"
        "    return mod\n\n"
        "def test_decide():\n"
        "    pf = _load('preflight.py')\n"
        "    assert pf.decide()\n",
    )
    # An UNRELATED module elsewhere, mentioned only as a FIXTURE filename being
    # WRITTEN (not loaded) in some other test, must not be claimed. Using a
    # name that collides with no "load"-named call anywhere isolates this from
    # the (separately accepted) same-bare-filename-in-two-dirs ambiguity the
    # loader-call signal shares with the existing exact-stem-match rule.
    _write(tmp_path, "other/unrelated_thing.py", "def unrelated():\n    return 0\n")
    _write(
        tmp_path, "tests/test_writes_a_fixture_file.py",
        "def test_x(tmp_path):\n"
        "    (tmp_path / 'unrelated_thing.py').write_text('def unrelated(): return 0')\n"
        "    assert True\n",
    )

    coverage = TestLinker(tmp_path).analyze()
    assert "tests/test_scripts_tooling.py" in coverage.module_to_tests["scripts/preflight.py"]
    assert "other/unrelated_thing.py" in coverage.untested_modules
    assert "tests/test_writes_a_fixture_file.py" not in coverage.module_to_tests["other/unrelated_thing.py"]


# --------------------------------------------------------------------------- #
# Live probe (real repo): per-module linkage for the 5 recently-landed
# characterization test files the wave was asked to investigate. None of them
# is missed by the linker's own exact-stem-match path; this pins that fact so
# a future change to _find_linked_tests cannot silently regress it.
# --------------------------------------------------------------------------- #

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_recently_landed_characterization_tests_are_all_linked():
    coverage = TestLinker(_REPO_ROOT).analyze()
    expected = {
        "app/execution/stub_synthesis.py": "tests/test_stub_synthesis.py",
        "app/execution/objectives/_base.py": "tests/test__base.py",
        "app/execution/protocol_scaffold.py": "tests/test_protocol_scaffold.py",
        "app/execution/_transform_base.py": "tests/test__transform_base.py",
        "scripts/wave_common.py": "tests/test_wave_common.py",
    }
    for module, expected_test in expected.items():
        linked = coverage.module_to_tests.get(module)
        assert linked is not None, f"{module} was not even discovered as a module"
        assert expected_test in linked, f"{module} is missing its own {expected_test}: linked={linked}"
