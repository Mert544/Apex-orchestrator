"""Characterization tests proving the refactored ContextExtractor.extract is
byte-identical to the original HEAD implementation across every branch.

The original source is loaded from `git show HEAD:...` into an isolated module
so the two implementations can be compared on identical inputs.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.execution.context_extractor import ContextExtractor as RefactoredExtractor

REPO_ROOT = Path(__file__).resolve().parents[1]
REL = "app/execution/context_extractor.py"


def _load_original() -> types.ModuleType:
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{REL}"], cwd=REPO_ROOT, text=True
    )
    spec = importlib.util.spec_from_loader("_original_context_extractor", loader=None)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_original_context_extractor"] = module
    exec(compile(src, "<original_context_extractor>", "exec"), module.__dict__)
    return module


ORIGINAL = _load_original()


def _make_tree(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "tests" / "sub").mkdir()

    # Valid python with imports, function, async function, class.
    (root / "app" / "mod.py").write_text(
        "\n".join(
            [
                "import os",
                "import sys, json",
                "from pathlib import Path",
                "from . import thing",
                "from __future__ import annotations",
                "",
                "def foo():",
                "    return 1",
                "",
                "async def bar():",
                "    return 2",
                "",
                "class Baz:",
                "    pass",
            ]
            + [f"# filler line {i}" for i in range(60)]
        ),
        encoding="utf-8",
    )
    # Syntax-error file (tree is None branch).
    (root / "app" / "broken.py").write_text("def (:\n  bad", encoding="utf-8")
    # Empty file.
    (root / "app" / "empty.py").write_text("", encoding="utf-8")
    # Plain module, no imports/symbols.
    (root / "app" / "plain.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    # ImportFrom with no module (relative import level only) -> module is None.
    (root / "app" / "relimport.py").write_text(
        "from . import a, b\nfrom .pkg import c\n", encoding="utf-8"
    )

    # Tests that match various stems.
    (root / "tests" / "test_mod.py").write_text("# t", encoding="utf-8")
    (root / "tests" / "mod_helper.py").write_text("# t", encoding="utf-8")
    (root / "tests" / "sub" / "test_plain_extra.py").write_text("# t", encoding="utf-8")
    (root / "tests" / "unrelated.py").write_text("# t", encoding="utf-8")
    return root


# Each case targets specific branches.
CASES = [
    # all three slots, mixed kinds
    ["app/mod.py", "app/broken.py", "app/plain.py"],
    # more than 3 -> truncation to first 3
    ["app/mod.py", "app/plain.py", "app/empty.py", "app/relimport.py"],
    # nonexistent file -> skipped
    ["app/missing.py", "app/mod.py"],
    # path escaping root -> skipped
    ["../outside.py", "app/plain.py"],
    # empty file branch
    ["app/empty.py"],
    # relative import / module None branch
    ["app/relimport.py"],
    # no targets
    [],
    # absolute-ish traversal kept out
    ["../../etc/passwd"],
]

WINDOWS = [0, 1, 5, 40, 1000]


@pytest.mark.parametrize("targets", CASES)
@pytest.mark.parametrize("window", WINDOWS)
def test_byte_identical(tmp_path, targets, window):
    root = _make_tree(tmp_path)
    orig = ORIGINAL.ContextExtractor().extract(root, targets, window_lines=window)
    new = RefactoredExtractor().extract(root, targets, window_lines=window)
    orig_dump = json.dumps(orig.to_dict(), sort_keys=False)
    new_dump = json.dumps(new.to_dict(), sort_keys=False)
    assert orig_dump == new_dump


def test_str_path_input(tmp_path):
    root = _make_tree(tmp_path)
    targets = ["app/mod.py", "app/relimport.py"]
    orig = ORIGINAL.ContextExtractor().extract(str(root), targets)
    new = RefactoredExtractor().extract(str(root), targets)
    assert json.dumps(orig.to_dict()) == json.dumps(new.to_dict())


def test_no_tests_dir(tmp_path):
    root = tmp_path / "proj2"
    (root / "app").mkdir(parents=True)
    (root / "app" / "mod.py").write_text("import os\n", encoding="utf-8")
    targets = ["app/mod.py"]
    orig = ORIGINAL.ContextExtractor().extract(root, targets)
    new = RefactoredExtractor().extract(root, targets)
    assert json.dumps(orig.to_dict()) == json.dumps(new.to_dict())
