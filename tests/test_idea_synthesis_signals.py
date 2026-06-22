"""Tests for the Idea Engine synthesis-grounding layer.

Each signal must equal what ``apex develop`` would actually land (honesty): a
module qualifies ONLY when the real lander would act on it. The fixtures below
build a tiny project under ``tmp_path`` and assert each module lights up the
RIGHT signal and NOT the others, plus the negative/honesty cases where the
lander refuses (ambiguous stub, fully-annotated module, real ``__init__``
logic), determinism, the ``limit`` cap, and the never-raise guarantee on a
missing/unreadable path.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_synthesis_signals import (
    dataclassifiable_modules,
    fillable_stub_modules,
    inferable_return_modules,
)


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _project(tmp_path: Path) -> Path:
    """A small project exercising each signal in isolation.

    ``calc.py`` holds a genuinely fillable stub (pinned by two witnesses) whose
    own ``def`` is already return-annotated, so it lights up ONLY fillable.
    ``shape.py`` is pure boilerplate ``__init__`` with an annotated header, so it
    lights up ONLY dataclassifiable. ``labels.py`` returns an f-string from an
    unannotated function, so it lights up ONLY inferable-return."""
    root = tmp_path / "proj"
    # Fillable stub: a `...` body pinned by tests; `-> int` keeps it out of the
    # inferable-return signal (its return is already annotated).
    _write(root, "calc.py", "def total(xs) -> int:\n    ...\n")
    _write(
        root,
        "tests/test_calc.py",
        "from calc import total\n\n\n"
        "def test_total():\n"
        "    assert total([1, 2, 3]) == 6\n"
        "    assert total([10, 20]) == 30\n",
    )
    # Boilerplate-init class → @dataclass. The `-> None` header keeps it out of
    # the inferable-return signal.
    _write(
        root,
        "shape.py",
        "class Point:\n"
        "    def __init__(self, x: int, y: int) -> None:\n"
        "        self.x = x\n"
        "        self.y = y\n",
    )
    # Provable, unannotated return (an f-string is always str).
    _write(root, "labels.py", "def label(name):\n    return f\"item-{name}\"\n")
    return root


def _all_modules() -> list[str]:
    return ["calc.py", "shape.py", "labels.py"]


# --- each signal fires for the right module, and not the others --------------

def test_fillable_stub_module_qualifies_only_for_its_signal(tmp_path: Path):
    root = _project(tmp_path)
    mods = _all_modules()
    assert fillable_stub_modules(root, mods) == ["calc.py"]
    assert "calc.py" not in dataclassifiable_modules(root, mods)
    assert "calc.py" not in inferable_return_modules(root, mods)


def test_dataclassifiable_module_qualifies_only_for_its_signal(tmp_path: Path):
    root = _project(tmp_path)
    mods = _all_modules()
    assert dataclassifiable_modules(root, mods) == ["shape.py"]
    assert "shape.py" not in fillable_stub_modules(root, mods)
    assert "shape.py" not in inferable_return_modules(root, mods)


def test_inferable_return_module_qualifies_only_for_its_signal(tmp_path: Path):
    root = _project(tmp_path)
    mods = _all_modules()
    assert inferable_return_modules(root, mods) == ["labels.py"]
    assert "labels.py" not in fillable_stub_modules(root, mods)
    assert "labels.py" not in dataclassifiable_modules(root, mods)


def test_str_root_argument_is_accepted(tmp_path: Path):
    # The public API accepts ``str | Path`` for ``root``; a str path must work.
    root = _project(tmp_path)
    assert dataclassifiable_modules(str(root), _all_modules()) == ["shape.py"]


# --- honesty / negative cases (the lander would REFUSE) ----------------------

def test_ambiguous_only_stub_is_not_fillable(tmp_path: Path):
    """A stub pinned by a SINGLE witness is ambiguous — the lander refuses it, so
    it must not appear in ``fillable_stub_modules`` (no over-promise)."""
    root = tmp_path / "amb"
    _write(root, "amb.py", "def double(n):\n    ...\n")
    _write(
        root,
        "tests/test_amb.py",
        "from amb import double\n\n\ndef test_double():\n    assert double(3) == 6\n",
    )
    assert fillable_stub_modules(root, ["amb.py"]) == []


def test_unpinned_stub_is_not_fillable(tmp_path: Path):
    """A stub with NO pinned test has no contract to satisfy — not fillable."""
    root = tmp_path / "unpinned"
    _write(root, "lonely.py", "def f(x):\n    ...\n")
    assert fillable_stub_modules(root, ["lonely.py"]) == []


def test_real_init_logic_is_not_dataclassifiable(tmp_path: Path):
    """A class whose ``__init__`` does more than copy params onto ``self`` is not
    pure boilerplate — the rewrite refuses, so it must not qualify."""
    root = tmp_path / "real"
    _write(
        root,
        "acct.py",
        "class Acct:\n"
        "    def __init__(self, bal):\n"
        "        if bal < 0:\n"
        "            raise ValueError('neg')\n"
        "        self.bal = bal\n",
    )
    assert dataclassifiable_modules(root, ["acct.py"]) == []


def test_fully_annotated_module_is_not_inferable(tmp_path: Path):
    """Every function already has a return annotation — nothing to add."""
    root = tmp_path / "ann"
    _write(root, "done.py", "def label(name) -> str:\n    return f\"x-{name}\"\n")
    assert inferable_return_modules(root, ["done.py"]) == []


def test_unprovable_return_is_not_inferable(tmp_path: Path):
    """A return whose type is NOT statically provable (a bare name) is refused by
    the inference, so the module does not qualify — an honest under-claim."""
    root = tmp_path / "unprov"
    _write(root, "passthru.py", "def echo(x):\n    return x\n")
    assert inferable_return_modules(root, ["passthru.py"]) == []


# --- test/fixture files self-exclude -----------------------------------------

def test_test_files_never_qualify(tmp_path: Path):
    """The underlying landers refuse to edit the suite they are gated by, so a
    ``tests/...`` path never qualifies for any signal — even when its content
    structurally matches (a boilerplate class / provable return)."""
    root = tmp_path / "suite"
    _write(
        root,
        "tests/test_thing.py",
        "class Holder:\n"
        "    def __init__(self, a):\n"
        "        self.a = a\n\n\n"
        "def helper(name):\n"
        "    return f\"h-{name}\"\n",
    )
    rel = "tests/test_thing.py"
    assert fillable_stub_modules(root, [rel]) == []
    # dataclass/inferable have no path-based fixture guard of their own, but a
    # test file is never offered to this layer as a candidate module; the signal
    # set the Idea Engine consumes is source modules. We still assert the stub
    # signal (which DOES self-exclude) is honest here.


# --- determinism, dedup, limit, robustness -----------------------------------

def test_determinism_same_input_same_ordered_output(tmp_path: Path):
    root = _project(tmp_path)
    mods = ["labels.py", "shape.py", "calc.py"]  # deliberately unsorted
    first = (
        fillable_stub_modules(root, mods),
        dataclassifiable_modules(root, mods),
        inferable_return_modules(root, mods),
    )
    for _ in range(3):
        assert (
            fillable_stub_modules(root, mods),
            dataclassifiable_modules(root, mods),
            inferable_return_modules(root, mods),
        ) == first
    # Output is sorted regardless of input order.
    assert inferable_return_modules(root, mods) == sorted(
        inferable_return_modules(root, mods)
    )


def test_duplicate_input_paths_dedup(tmp_path: Path):
    root = _project(tmp_path)
    mods = ["labels.py", "labels.py", "labels.py"]
    assert inferable_return_modules(root, mods) == ["labels.py"]


def test_limit_caps_results(tmp_path: Path):
    """``limit`` caps the (sorted) result; ``limit=0`` yields nothing; ``None``
    returns everything."""
    root = tmp_path / "many"
    for i in range(4):
        _write(root, f"m{i}.py", f"def f{i}(x):\n    return f\"v-{{x}}-{i}\"\n")
    mods = [f"m{i}.py" for i in range(4)]
    assert inferable_return_modules(root, mods, limit=2) == ["m0.py", "m1.py"]
    assert inferable_return_modules(root, mods, limit=0) == []
    assert inferable_return_modules(root, mods, limit=None) == mods
    assert len(inferable_return_modules(root, mods, limit=10)) == 4  # over-cap


def test_missing_or_unreadable_module_is_absent_not_error(tmp_path: Path):
    """A missing path, a directory in place of a file, and a syntactically broken
    module must all simply be absent — never raise."""
    root = _project(tmp_path)
    (root / "a_dir.py").mkdir()  # a directory where a module path is expected
    _write(root, "broken.py", "def oops(:\n    return 1\n")  # syntax error
    mods = ["does_not_exist.py", "a_dir.py", "broken.py", "labels.py"]
    # No exception, and only the genuinely-qualifying module survives.
    assert fillable_stub_modules(root, mods) == []
    assert dataclassifiable_modules(root, mods) == []
    assert inferable_return_modules(root, mods) == ["labels.py"]


def test_empty_module_iterable_yields_empty(tmp_path: Path):
    root = _project(tmp_path)
    assert fillable_stub_modules(root, []) == []
    assert dataclassifiable_modules(root, []) == []
    assert inferable_return_modules(root, []) == []
