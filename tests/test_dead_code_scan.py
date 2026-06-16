"""Tests for the conservative cross-file dead-code analyzer.

Every exclusion rule from ``app.tools.dead_code_scan`` gets a focused case, plus
the empty/safe path and determinism. The tmp project is built fresh per test so
the project-wide use universe is exactly what each case declares.
"""

from __future__ import annotations

from pathlib import Path

from app.tools.dead_code_scan import DeadCodeReport, analyze_dead_code


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _symbols(report: DeadCodeReport) -> set[str]:
    return {c["symbol"] for c in report.candidates}


def test_used_symbol_is_not_flagged_but_unreferenced_one_is(tmp_path: Path):
    # `alive` is called from another module; `ghost` is referenced nowhere.
    # `main` is an entrypoint (rule 4) so it isn't itself flagged as dead.
    _write(tmp_path, "pkg/lib.py", "def alive():\n    return 1\n\n\ndef ghost():\n    return 2\n")
    _write(tmp_path, "pkg/consumer.py", "from pkg.lib import alive\n\n\ndef main():\n    return alive()\n")

    report = analyze_dead_code(tmp_path)

    assert _symbols(report) == {"ghost"}
    assert "alive" not in _symbols(report)
    (only,) = report.candidates
    assert only == {"module": "pkg/lib.py", "symbol": "ghost", "kind": "function", "line": 5}


def test_class_used_via_attribute_is_not_flagged(tmp_path: Path):
    # An Attribute access (`mod.Widget`) counts as a reference.
    _write(tmp_path, "a.py", "class Widget:\n    pass\n\n\nclass Unused:\n    pass\n")
    _write(tmp_path, "b.py", "import a\n\n\ndef main():\n    return a.Widget()\n")

    report = analyze_dead_code(tmp_path)

    assert _symbols(report) == {"Unused"}
    assert report.candidates[0]["kind"] == "class"


def test_all_exported_symbol_is_not_flagged(tmp_path: Path):
    _write(
        tmp_path,
        "api.py",
        '__all__ = ["public_thing"]\n\n\ndef public_thing():\n    return 1\n',
    )
    report = analyze_dead_code(tmp_path)
    assert _symbols(report) == set()


def test_dunder_is_not_flagged(tmp_path: Path):
    # A module-level __getattr__ is unreferenced but a dunder -> never flagged.
    _write(tmp_path, "m.py", "def __getattr__(name):\n    raise AttributeError(name)\n")
    report = analyze_dead_code(tmp_path)
    assert _symbols(report) == set()


def test_entrypoints_and_tests_are_not_flagged(tmp_path: Path):
    _write(
        tmp_path,
        "cli.py",
        "def main():\n    return 0\n\n\ndef cmd_run():\n    return 1\n\n\ndef test_smoke():\n    return 2\n",
    )
    report = analyze_dead_code(tmp_path)
    assert _symbols(report) == set()


def test_string_referenced_name_is_not_flagged(tmp_path: Path):
    # `handler` is never called, only named in a dispatch string -> dynamic use.
    _write(tmp_path, "h.py", "def handler():\n    return 1\n")
    _write(tmp_path, "dispatch.py", 'ROUTES = {"x": "handler"}\n')
    report = analyze_dead_code(tmp_path)
    assert _symbols(report) == set()


def test_getattr_in_module_suppresses_its_own_defs(tmp_path: Path):
    # A module that resolves names dynamically -> its defs are never flagged.
    _write(
        tmp_path,
        "plugin.py",
        "def feature_a():\n    return 1\n\n\n"
        'def load(name):\n    return getattr(__import__("plugin"), name)\n',
    )
    report = analyze_dead_code(tmp_path)
    assert _symbols(report) == set()


def test_star_import_target_module_is_not_flagged(tmp_path: Path):
    # `facade` star-imports `exports`, re-exporting its symbols wholesale, so no
    # def in exports.py may be called dead even though nothing references it by
    # name. A control module that is NOT a star-target still gets flagged.
    _write(tmp_path, "exports.py", "def maybe_reexported():\n    return 1\n")
    _write(tmp_path, "facade.py", "from exports import *\n")
    _write(tmp_path, "control.py", "def truly_dead():\n    return 1\n")
    report = analyze_dead_code(tmp_path)
    assert "maybe_reexported" not in _symbols(report)
    assert _symbols(report) == {"truly_dead"}


def test_decorated_symbol_is_not_flagged(tmp_path: Path):
    _write(
        tmp_path,
        "routes.py",
        "def register(fn):\n    return fn\n\n\n@register\ndef endpoint():\n    return 1\n",
    )
    report = analyze_dead_code(tmp_path)
    # `endpoint` is decorated -> excluded. `register` IS referenced (as the
    # decorator) so it is live too.
    assert _symbols(report) == set()


def test_definitions_in_init_and_test_files_are_not_reported(tmp_path: Path):
    _write(tmp_path, "pkg/__init__.py", "def packaging_helper():\n    return 1\n")
    _write(tmp_path, "tests/test_thing.py", "def helper_used_only_here():\n    return 1\n")
    report = analyze_dead_code(tmp_path)
    assert _symbols(report) == set()


def test_private_unreferenced_symbol_is_flagged(tmp_path: Path):
    # No underscore special-casing: a private dead symbol is still surfaced.
    _write(tmp_path, "internal.py", "def _orphan():\n    return 1\n")
    report = analyze_dead_code(tmp_path)
    assert _symbols(report) == {"_orphan"}


def test_empty_project_is_safe(tmp_path: Path):
    report = analyze_dead_code(tmp_path)
    assert report.candidates == []
    assert report.files_scanned == 0
    assert report.candidate_count == 0
    assert report.reported_count == 0
    assert report.truncated is False


def test_missing_root_is_safe(tmp_path: Path):
    report = analyze_dead_code(tmp_path / "does_not_exist")
    assert report == DeadCodeReport()


def test_unparsable_file_is_skipped_not_crashing(tmp_path: Path):
    _write(tmp_path, "broken.py", "def oops(:\n")  # syntax error
    _write(tmp_path, "ok.py", "def lonely():\n    return 1\n")
    report = analyze_dead_code(tmp_path)
    assert report.files_scanned == 1  # only ok.py parsed
    assert _symbols(report) == {"lonely"}


def test_results_sorted_and_capped(tmp_path: Path):
    # 25 unreferenced top-level functions across files -> capped at 20, sorted.
    for i in range(25):
        _write(tmp_path, f"mod_{i:02d}.py", f"def dead_{i:02d}():\n    return {i}\n")
    report = analyze_dead_code(tmp_path)

    assert report.candidate_count == 25
    assert report.reported_count == 20
    assert len(report.candidates) == 20
    assert report.truncated is True
    keys = [(c["module"], c["line"], c["symbol"]) for c in report.candidates]
    assert keys == sorted(keys)


def test_determinism_same_input_same_output(tmp_path: Path):
    _write(tmp_path, "a.py", "def used():\n    return 1\n\n\ndef dead_a():\n    return 2\n")
    _write(tmp_path, "b.py", "from a import used\n\n\ndef dead_b():\n    return used()\n")

    first = analyze_dead_code(tmp_path)
    second = analyze_dead_code(tmp_path)

    assert first == second
    assert _symbols(first) == {"dead_a", "dead_b"}


def test_max_files_cap_limits_scan(tmp_path: Path):
    for i in range(5):
        _write(tmp_path, f"f{i}.py", f"def dead_{i}():\n    return {i}\n")
    report = analyze_dead_code(tmp_path, max_files=2)
    assert report.files_scanned == 2
    # max_files=0 scans nothing, still safe.
    none = analyze_dead_code(tmp_path, max_files=0)
    assert none.files_scanned == 0
    assert none.candidates == []


def test_collect_module_facts_characterization(tmp_path: Path):
    """Characterization lock for ``_collect_module_facts`` after its helper split.

    One fixture exercises every node-contribution path in a single AST walk —
    Name-load + Attribute use, ``import``/``from import`` aliases, a star-import
    target, a string constant, an ``__all__`` export, a ``getattr`` dynamic call,
    a decorated def, a dunder, an entrypoint, a test name, and plain function /
    class defs — and pins the resulting report exactly. If any extracted helper
    drifts from the original elif-chain semantics, this snapshot breaks.
    """
    _write(
        tmp_path,
        "feature.py",
        "import os.path as _p\n"
        "from collections import OrderedDict as _od\n"
        "from other.mod import *\n"
        '__all__ = ["exported"]\n'
        "MARKER = \"used_via_string\"\n"
        "\n\n"
        "def exported():\n    return _od()\n"
        "\n\n"
        "def used_via_string():\n    return 1\n"
        "\n\n"
        "@staticmethod\n"
        "def decorated():\n    return 2\n"
        "\n\n"
        "def __helper__():\n    return 3\n"
        "\n\n"
        "def main():\n    return getattr(_p, 'join')\n"
        "\n\n"
        "def test_inline():\n    return 4\n"
        "\n\n"
        "class PlainClass:\n    pass\n"
        "\n\n"
        "def truly_dead():\n    return 5\n",
    )
    report = analyze_dead_code(tmp_path)

    # feature.py has a getattr (dynamic access, rule 7) AND is a star-import
    # source elsewhere is not relevant here; the dynamic-access guard alone
    # suppresses every def in this module, so no candidates survive.
    assert report.files_scanned == 1
    assert report.candidates == []
    assert report.candidate_count == 0
    assert report.truncated is False
    # Determinism guard: same input → identical report object.
    assert analyze_dead_code(tmp_path) == report


def test_dynamic_access_suppression_isolated(tmp_path: Path):
    """Without the dynamic-access call, the same defs surface deterministically.

    Mirrors the characterization fixture but drops ``getattr`` so the per-def
    exclusions (dunder/entrypoint/test/decorated/exported/string/star) are what
    filter, proving each extracted helper's branch is wired correctly.
    """
    _write(
        tmp_path,
        "feature.py",
        "from other.mod import *\n"
        '__all__ = ["exported"]\n'
        "MARKER = \"used_via_string\"\n"
        "\n\n"
        "def exported():\n    return 1\n"
        "\n\n"
        "def used_via_string():\n    return 2\n"
        "\n\n"
        "@staticmethod\n"
        "def decorated():\n    return 3\n"
        "\n\n"
        "def __helper__():\n    return 4\n"
        "\n\n"
        "def main():\n    return 5\n"
        "\n\n"
        "def test_inline():\n    return 6\n"
        "\n\n"
        "class PlainClass:\n    pass\n"
        "\n\n"
        "def truly_dead():\n    return 7\n",
    )
    report = analyze_dead_code(tmp_path)
    # exported (rule 3), used_via_string (rule 6), decorated (rule 8),
    # __helper__ (rule 2), main (rule 4), test_inline (rule 5) all excluded;
    # PlainClass and truly_dead are the genuine candidates.
    assert _symbols(report) == {"PlainClass", "truly_dead"}
    assert {c["kind"] for c in report.candidates} == {"class", "function"}
