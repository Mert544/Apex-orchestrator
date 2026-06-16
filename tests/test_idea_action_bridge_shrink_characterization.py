"""Byte-identical characterization proof for the shrink of ``_test_stub_body``
and ``_diff_and_verdict`` in ``app/engine/idea_action_bridge.py``.

Loads a pristine snapshot of the file at base HEAD as a SEPARATE module and
asserts the refactored implementations produce output identical to the originals
across a wide matrix of inputs (anchors present/absent, weird symbols, multiple
patch requests, .py vs non-.py, parse errors, missing/new files, suite
references). No network, stdlib + repo only.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

import app.engine.idea_action_bridge as refac

REPO = Path(__file__).resolve().parents[1]
TARGET = "app/engine/idea_action_bridge.py"


def _load_original() -> types.ModuleType:
    """Import the base-HEAD snapshot of the bridge as an isolated module."""
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{TARGET}"], cwd=REPO, text=True,
    )
    path = Path(tempfile.gettempdir()) / "_orig_iab_snapshot.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_orig_iab_snapshot", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_orig_iab_snapshot"] = mod
    spec.loader.exec_module(mod)
    return mod


ORIG = _load_original()


class _Node:
    def __init__(self, subject="", anchors=None):
        self.subject = subject
        if anchors is not None:
            self.anchors = anchors


class _Result:
    def __init__(self, patch_requests):
        self.patch_requests = patch_requests


# ---- _test_stub_body matrix ------------------------------------------------

_ANCHOR_SETS = [
    None,
    [],
    [{"symbol": "_scan_churn", "module": "app/tools/project_profile.py", "line": 550, "metric": "cyclomatic 18"}],
    [{"symbol": "Foo.bar", "module": "pkg/mod.py", "line": 3}],
    [{"symbol": "  weird-name!!  "}, {"symbol": "___"}, {"symbol": ""}],
    [{"symbol": "123abc"}, {"symbol": "A"}],
    [{"symbol": "x"}, {"symbol": "y"}, {"symbol": "z::w"}],
    ["not-a-dict", {"symbol": "ok"}, {"no_symbol": 1}],
    [{"symbol": "_"}],
]

_SUBJECTS = [
    "",
    "app/foo/bar.py",
    "app/foo/bar.py::Cls.method",
    "weird path/with spaces.py",
    "no_extension_module",
    "a/b/c/d.py::fn",
    "UPPER/Name.PY",
]

_TARGETS = ["", "app/foo/bar.py", "some/Dir/Mod.py", "x.py", "no_ext", "a/b.py"]


@pytest.mark.parametrize("anchors", _ANCHOR_SETS)
@pytest.mark.parametrize("subject", _SUBJECTS)
@pytest.mark.parametrize("target", _TARGETS)
def test_stub_body_byte_identical(anchors, subject, target):
    node = _Node(subject=subject, anchors=anchors)
    assert refac._test_stub_body(node, target) == ORIG._test_stub_body(node, target)


def test_stub_body_node_without_anchors_attr():
    class Bare:
        subject = "app/x.py"
    bare = Bare()
    assert refac._test_stub_body(bare, "") == ORIG._test_stub_body(bare, "")


# ---- _diff_and_verdict matrix ----------------------------------------------

def _write_tree(root: Path, files: dict[str, str]):
    for rel, content in files.items():
        fp = root / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")


_PY_OK_OLD = "def f():\n    if a:\n        if b:\n            return 1\n    return 0\n"
_PY_OK_NEW = "def f():\n    return 1\n"
_PY_BAD_NEW = "def f(:\n    pass\n"


@pytest.mark.parametrize("requests,existing", [
    ([], {}),
    ([{"path": "m.py", "new_content": _PY_OK_NEW}], {"m.py": _PY_OK_OLD}),
    ([{"path": "m.py", "new_content": _PY_OK_NEW}], {}),  # new file
    ([{"path": "m.py", "new_content": _PY_BAD_NEW}], {"m.py": _PY_OK_OLD}),
    ([{"path": "notes.txt", "new_content": "hello\nworld\n"}], {"notes.txt": "hello\n"}),
    ([{"path": "a.py", "new_content": _PY_OK_NEW},
      {"path": "b.txt", "new_content": "x\n"}], {"a.py": _PY_OK_OLD}),
    ([{"path": "x.py", "new_content": _PY_OK_OLD}], {"x.py": _PY_OK_OLD}),  # no change
    ([{"path": "p.py", "new_content": _PY_OK_NEW},
      {"path": "q.py", "new_content": _PY_BAD_NEW}],
     {"p.py": _PY_OK_OLD, "q.py": _PY_OK_OLD}),
    ([{"path": "", "new_content": ""}], {}),
    ([{"path": "deep/dir/mod.py", "new_content": _PY_OK_NEW}], {"deep/dir/mod.py": _PY_OK_OLD}),
])
def test_diff_and_verdict_byte_identical(tmp_path, requests, existing):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    _write_tree(root_a, existing)
    _write_tree(root_b, existing)
    out_orig = ORIG.IdeaActionBridge._diff_and_verdict(_Result(requests), str(root_a))
    out_refac = refac.IdeaActionBridge._diff_and_verdict(_Result(requests), str(root_b))
    assert out_orig == out_refac


def test_diff_and_verdict_with_suite_reference(tmp_path):
    # A changed module referenced by a test file -> covered True in both.
    files = {
        "pkg/widget.py": "def w():\n    return 1\n",
        "tests/test_widget.py": "import pkg.widget\n\n\ndef test_w():\n    assert pkg.widget.w()\n",
    }
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    _write_tree(root_a, files)
    _write_tree(root_b, files)
    reqs = [{"path": "pkg/widget.py", "new_content": "def w():\n    return 2\n"}]
    out_orig = ORIG.IdeaActionBridge._diff_and_verdict(_Result(reqs), str(root_a))
    out_refac = refac.IdeaActionBridge._diff_and_verdict(_Result(reqs), str(root_b))
    assert out_orig == out_refac
    assert out_refac is not None and out_refac["covered"] is True


def test_result_without_patch_requests_attr():
    class Bare:
        pass
    assert (refac.IdeaActionBridge._diff_and_verdict(Bare(), "/tmp")
            == ORIG.IdeaActionBridge._diff_and_verdict(Bare(), "/tmp"))
