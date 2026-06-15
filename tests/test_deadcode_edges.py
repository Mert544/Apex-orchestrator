"""Edge-path coverage for app.reporting.deadcode.

Targets branches the happy-path tests don't reach: class method-body line
collection (only walked when ``evidence`` is supplied), the dunder and
``main``/``test_`` candidate exclusions, and the unparseable-file skip. All
deterministic and hermetic (a synthetic project under tmp_path; evidence is
hand-built, never a real traced run).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.runtime_trace import RuntimeEvidence
from app.reporting.deadcode import find_dead_code, render_dead_code_markdown


def _pyproject(tmp: Path) -> None:
    (tmp / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")


def test_dead_class_method_body_lines_drive_runtime_label(tmp_path: Path):
    # A class whose method body runs (per evidence) is "refuted"; one whose body
    # never runs is "runtime-confirmed". Reaching either label requires
    # _use_only_lines to have collected the class's method-body lines (the
    # ClassDef branch) and find_dead_code to thread them through as body_lines.
    _pyproject(tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    # _Widget is private and unreferenced -> a high-confidence dead candidate.
    # Its method body is on line 3 of the file; the class header on line 1.
    src = "class _Widget:\n    def do(self):\n        return 42\n"
    (tmp_path / "pkg" / "w.py").write_text(src)

    abs_path = str(tmp_path / "pkg" / "w.py")

    # Evidence: the file loaded (header line 1 ran) but the method body (line 3)
    # never ran -> the class's use-only body lines are all unexecuted ->
    # "runtime-confirmed".
    confirmed_ev = RuntimeEvidence(executed=frozenset({(abs_path, 1)}))
    rows = find_dead_code(str(tmp_path), evidence=confirmed_ev)
    widget = next(r for r in rows if r["symbol"] == "_Widget")
    assert widget["kind"] == "class"
    assert widget["runtime"] == "runtime-confirmed"

    # Now evidence where the method body (line 3) DID run -> "refuted". This only
    # differs from the above because _use_only_lines collected line 3 as a
    # method-body line.
    refuted_ev = RuntimeEvidence(executed=frozenset({(abs_path, 1), (abs_path, 3)}))
    rows2 = find_dead_code(str(tmp_path), evidence=refuted_ev)
    widget2 = next(r for r in rows2 if r["symbol"] == "_Widget")
    assert widget2["runtime"] == "refuted"


def test_static_only_when_file_never_loaded(tmp_path: Path):
    # Evidence with no lines for the file -> static-only (runtime can't say).
    _pyproject(tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "w.py").write_text("def _ghost():\n    return 1\n")

    rows = find_dead_code(str(tmp_path), evidence=RuntimeEvidence(executed=frozenset()))
    ghost = next(r for r in rows if r["symbol"] == "_ghost")
    assert ghost["runtime"] == "static-only"


def test_dunder_named_symbol_is_not_a_candidate(tmp_path: Path):
    # A module-level dunder function (rare but legal) is excluded from candidates
    # even when unreferenced (the name.startswith/endswith("__") guard).
    _pyproject(tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "m.py").write_text(
        "def __getattr__(name):\n    return 1\n\ndef _real_dead():\n    return 2\n"
    )

    names = {r["symbol"] for r in find_dead_code(str(tmp_path))}
    assert "__getattr__" not in names   # dunder excluded
    assert "_real_dead" in names         # ordinary private dead symbol still found


def test_main_and_test_prefixed_names_are_not_candidates(tmp_path: Path):
    # Entry-point `main` and `test_`-prefixed defs are excluded even when
    # unreferenced in non-test code (the `main`/`test_` guard).
    _pyproject(tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "cli.py").write_text(
        "def main():\n    return 0\n\n"
        "def test_helper():\n    return 1\n\n"
        "def _genuinely_dead():\n    return 2\n"
    )

    names = {r["symbol"] for r in find_dead_code(str(tmp_path))}
    assert "main" not in names           # entry-point name excluded
    assert "test_helper" not in names    # test_-prefixed name excluded
    assert "_genuinely_dead" in names    # control: real dead symbol reported


def test_render_with_runtime_key_adds_legend_and_runtime_column():
    # When any row carries a "runtime" key, the renderer switches to the 6-column
    # layout, prints the runtime legend, and emits the per-row runtime cell.
    rows = [
        {"module": "pkg/m.py", "symbol": "_dead", "kind": "function",
         "line": 3, "confidence": "high", "runtime": "runtime-confirmed"},
    ]
    md = render_dead_code_markdown(rows)
    assert "| Module | Symbol | Kind | Line | Confidence | Runtime |" in md
    assert "Runtime legend" in md
    assert "| runtime-confirmed |" in md
    assert "`_dead`" in md


def test_render_with_runtime_key_defaults_missing_runtime_cell_to_static_only():
    # A mixed batch where one row has a runtime label and another omits it: the
    # has_runtime branch still renders, and the row missing the key falls back to
    # the "static-only" default cell.
    rows = [
        {"module": "pkg/a.py", "symbol": "_x", "kind": "function",
         "line": 1, "confidence": "high", "runtime": "refuted"},
        {"module": "pkg/b.py", "symbol": "y", "kind": "class",
         "line": 2, "confidence": "review"},  # no "runtime" key
    ]
    md = render_dead_code_markdown(rows)
    assert "| refuted |" in md
    assert "| static-only |" in md  # defaulted cell for the row without a key


def test_unparseable_file_is_skipped_not_fatal(tmp_path: Path):
    # A syntactically broken .py must be skipped (the except SyntaxError branch),
    # while a sibling valid file is still scanned normally.
    _pyproject(tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "broken.py").write_text("def oops(:\n    this is not python\n")
    (tmp_path / "pkg" / "good.py").write_text("def _alone():\n    return 1\n")

    # No exception, and the valid file's dead symbol is reported.
    names = {r["symbol"] for r in find_dead_code(str(tmp_path))}
    assert "_alone" in names
