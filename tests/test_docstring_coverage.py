"""Tests for the public-API docstring-coverage analyzer."""

from __future__ import annotations

from app.tools.docstring_coverage import (
    DocstringCoverage,
    _is_fixture_path,
    _is_public_module,
    _is_public_name,
    analyze_docstring_coverage,
)


def _write(tmp_path, rel, source):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


# ── fully-documented public API → 1.0 ───────────────────────────────────────

def test_fully_documented_is_one(tmp_path):
    _write(
        tmp_path,
        "m.py",
        '"""Module doc."""\n'
        "\n"
        "\n"
        "def f():\n"
        '    """f doc."""\n'
        "    return 1\n"
        "\n"
        "\n"
        "class C:\n"
        '    """C doc."""\n'
        "\n"
        "    def method(self):\n"
        '        """method doc."""\n'
        "        return 2\n",
    )
    cov = analyze_docstring_coverage(tmp_path)
    assert cov.overall_public_ratio == 1.0
    assert cov.documented_public == cov.total_public == 4
    assert cov.undocumented_public == []


# ── undocumented public symbols are listed ──────────────────────────────────

def test_undocumented_public_listed(tmp_path):
    _write(
        tmp_path,
        "m.py",
        "def f():\n"
        "    return 1\n"
        "\n"
        "\n"
        "class C:\n"
        "    def method(self):\n"
        "        return 2\n",
    )
    cov = analyze_docstring_coverage(tmp_path)
    # module + function f + class C + method C.method = 4 public, 0 documented.
    assert cov.total_public == 4
    assert cov.documented_public == 0
    assert cov.overall_public_ratio == 0.0
    entries = {(e["symbol"], e["kind"]) for e in cov.undocumented_public}
    assert ("<module>", "module") in entries
    assert ("f", "function") in entries
    assert ("C", "class") in entries
    assert ("C.method", "function") in entries
    # every entry carries the three required keys
    for e in cov.undocumented_public:
        assert set(e) == {"module", "symbol", "kind"}
        assert e["module"] == "m.py"


# ── private symbols are not penalized ───────────────────────────────────────

def test_private_symbols_not_penalized(tmp_path):
    _write(
        tmp_path,
        "m.py",
        '"""Module doc."""\n'
        "\n"
        "\n"
        "def _helper():\n"
        "    return 1\n"
        "\n"
        "\n"
        "class _Internal:\n"
        "    def _do(self):\n"
        "        return 2\n"
        "\n"
        "\n"
        "class C:\n"
        '    """C doc."""\n'
        "\n"
        "    def __init__(self):\n"  # dunder is exempt
        "        self.x = 1\n"
        "\n"
        "    def _private_method(self):\n"  # private method exempt
        "        return 3\n",
    )
    cov = analyze_docstring_coverage(tmp_path)
    # Public surface: module + class C only. Both documented → 1.0.
    assert cov.total_public == 2
    assert cov.documented_public == 2
    assert cov.overall_public_ratio == 1.0
    assert cov.undocumented_public == []


def test_underscore_module_excluded(tmp_path):
    # _private.py is a private module → not part of the public surface.
    _write(tmp_path, "_private.py", "def f():\n    return 1\n")
    _write(tmp_path, "pub.py", '"""doc."""\n')
    cov = analyze_docstring_coverage(tmp_path)
    assert cov.total_modules == 1
    assert all(e["module"] != "_private.py" for e in cov.undocumented_public)


def test_init_module_counted_as_public(tmp_path):
    # __init__.py IS the package's public surface (despite the underscores).
    _write(tmp_path, "pkg/__init__.py", "x = 1\n")  # no docstring
    cov = analyze_docstring_coverage(tmp_path)
    assert cov.total_modules == 1
    assert cov.documented_modules == 0
    assert any(
        e["module"].replace("\\", "/") == "pkg/__init__.py"
        and e["kind"] == "module"
        for e in cov.undocumented_public
    )


# ── module docstring detection ──────────────────────────────────────────────

def test_module_docstring_detected(tmp_path):
    _write(tmp_path, "documented.py", '"""I am documented."""\n')
    _write(tmp_path, "bare.py", "x = 1\n")
    cov = analyze_docstring_coverage(tmp_path)
    assert cov.total_modules == 2
    assert cov.documented_modules == 1
    undoc_modules = {
        e["module"] for e in cov.undocumented_public if e["kind"] == "module"
    }
    assert undoc_modules == {"bare.py"}


# ── empty / missing trees are safe ──────────────────────────────────────────

def test_empty_project_is_safe(tmp_path):
    cov = analyze_docstring_coverage(tmp_path)
    assert isinstance(cov, DocstringCoverage)
    assert cov.overall_public_ratio == 1.0  # vacuously documented
    assert cov.total_public == 0
    assert cov.documented_public == 0
    assert cov.undocumented_public == []


def test_missing_root_is_safe(tmp_path):
    cov = analyze_docstring_coverage(tmp_path / "does_not_exist")
    assert cov.overall_public_ratio == 1.0
    assert cov.total_public == 0
    assert cov.undocumented_public == []


def test_empty_file_is_safe(tmp_path):
    _write(tmp_path, "empty.py", "")
    cov = analyze_docstring_coverage(tmp_path)
    # An empty module is a public, undocumented module — but no crash.
    assert cov.total_modules == 1
    assert cov.documented_modules == 0


def test_syntax_error_skipped(tmp_path):
    _write(tmp_path, "good.py", '"""doc."""\n')
    _write(tmp_path, "broken.py", "def (:\n")
    cov = analyze_docstring_coverage(tmp_path)
    # Unparseable file is skipped, not counted; good.py is the only module.
    assert cov.total_modules == 1
    assert cov.documented_modules == 1
    assert cov.overall_public_ratio == 1.0


# ── fixtures / tests excluded ───────────────────────────────────────────────

def test_tests_and_fixtures_excluded(tmp_path):
    _write(tmp_path, "tests/test_x.py", "def f():\n    return 1\n")
    _write(tmp_path, "fixtures/data.py", "def g():\n    return 2\n")
    _write(tmp_path, "examples/demo.py", "def h():\n    return 3\n")
    _write(tmp_path, "pkg/test_helper.py", "def j():\n    return 4\n")
    _write(tmp_path, "real.py", '"""doc."""\n')
    cov = analyze_docstring_coverage(tmp_path)
    # Only real.py contributes to the public surface.
    assert cov.total_modules == 1
    assert cov.total_public == 1
    assert cov.documented_public == 1
    assert cov.overall_public_ratio == 1.0


# ── cap on the undocumented list ────────────────────────────────────────────

def test_undocumented_list_capped(tmp_path):
    # 30 undocumented public functions across two modules → list capped at 15.
    body = "".join(f"def f{i}():\n    return {i}\n\n\n" for i in range(30))
    _write(tmp_path, "a.py", '"""doc."""\n\n\n' + body)
    cov = analyze_docstring_coverage(tmp_path)
    assert len(cov.undocumented_public) == 15
    # capped list is still a prefix of the deterministic sort
    syms = [e["symbol"] for e in cov.undocumented_public]
    assert syms == sorted(syms)


# ── determinism ─────────────────────────────────────────────────────────────

def test_determinism(tmp_path):
    _write(tmp_path, "z.py", "def z():\n    return 1\n")
    _write(tmp_path, "a.py", "def a():\n    return 1\n")
    _write(tmp_path, "m.py", '"""doc."""\n\n\nclass C:\n    pass\n')
    first = analyze_docstring_coverage(tmp_path)
    second = analyze_docstring_coverage(tmp_path)
    assert first == second
    assert first.undocumented_public == second.undocumented_public


def test_max_files_cap_is_deterministic(tmp_path):
    for i in range(10):
        _write(tmp_path, f"mod_{i:02d}.py", "x = 1\n")
    cov = analyze_docstring_coverage(tmp_path, max_files=3)
    assert cov.total_modules == 3
    # The capped set is the alphabetically-first three (sorted walk order).
    seen = {e["module"] for e in cov.undocumented_public if e["kind"] == "module"}
    assert seen == {"mod_00.py", "mod_01.py", "mod_02.py"}


# ── publicness-rule helpers ─────────────────────────────────────────────────

def test_is_public_name():
    assert _is_public_name("parse")
    assert not _is_public_name("_helper")
    assert not _is_public_name("__init__")  # dunder is non-public here


def test_is_public_module():
    assert _is_public_module("config")
    assert _is_public_module("__init__")  # the public-surface carve-out
    assert not _is_public_module("_internal")


def test_is_fixture_path():
    assert _is_fixture_path("tests/test_x.py")
    assert _is_fixture_path("examples/demo.py")
    assert _is_fixture_path("pkg/test_helper.py")
    assert _is_fixture_path("a/fixtures/b.py")
    assert not _is_fixture_path("app/tools/docstring_coverage.py")


# ── async functions are treated as functions ────────────────────────────────

def test_async_functions_counted(tmp_path):
    _write(
        tmp_path,
        "m.py",
        '"""doc."""\n'
        "\n"
        "\n"
        "async def fetch():\n"
        "    return 1\n",
    )
    cov = analyze_docstring_coverage(tmp_path)
    assert cov.total_functions == 1
    assert cov.documented_functions == 0
    assert any(
        e["symbol"] == "fetch" and e["kind"] == "function"
        for e in cov.undocumented_public
    )
