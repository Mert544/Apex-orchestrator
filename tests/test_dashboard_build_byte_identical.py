"""Characterization test: ``build_dashboard`` is byte-identical after refactor.

The refactor decomposed ``build_dashboard`` into small pure ``_build_*`` /
``_plugin_operators`` helpers (cyclomatic complexity 12 -> 2). This test proves
the FULL rendered HTML string is unchanged by comparing the current module's
output against the pre-refactor source recovered from ``git show HEAD:<file>``
and loaded as an isolated module, over representative inputs (quality on/off,
varying breadth/depth/max_ideas).

The only nondeterminism in the page is the ``generated`` UTC timestamp; both the
current and snapshot modules import the same ``datetime`` symbol, so a single
patched ``datetime`` (frozen clock) makes the comparison deterministic without
altering any other byte of output.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import datetime, timezone

import pytest

import app.reporting.dashboard as current

REL_PATH = "app/reporting/dashboard.py"


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: A003 - mirrors datetime.now signature
        return datetime(2026, 1, 2, 3, 4, 5, tzinfo=tz or timezone.utc)


def _load_original_module():
    """Load the pre-refactor ``dashboard.py`` (from HEAD) as an isolated module."""
    src = subprocess.run(
        ["git", "show", f"HEAD:{REL_PATH}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    spec = importlib.util.spec_from_loader("dashboard_orig_byteid", loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dashboard_orig_byteid"] = mod
    exec(compile(src, "<dashboard_orig_byteid>", "exec"), mod.__dict__)
    return mod


_ORIGINAL = _load_original_module()


# Representative input grid: quality on/off plus varied breadth/depth/budget.
_CASES = [
    {"quality": True, "max_ideas": 24, "idea_depth": 2, "breadth": 3},
    {"quality": False, "max_ideas": 24, "idea_depth": 2, "breadth": 3},
    {"quality": True, "max_ideas": 6, "idea_depth": 1, "breadth": 1},
    {"quality": False, "max_ideas": 40, "idea_depth": 3, "breadth": 4},
    {"quality": True, "max_ideas": 12, "idea_depth": 2, "breadth": 2,
     "objective": "harden the security posture"},
]


def _freeze(monkeypatch):
    """Freeze the clock in BOTH modules so the timestamp byte is identical."""
    monkeypatch.setattr(current, "datetime", _FrozenDateTime)
    monkeypatch.setattr(_ORIGINAL, "datetime", _FrozenDateTime)


@pytest.mark.parametrize("kwargs", _CASES)
def test_build_dashboard_byte_identical(tmp_path, monkeypatch, kwargs):
    # A tiny but non-trivial project tree (not a git repo -> exercises empty-git path).
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "core.py").write_text(
        "import os\n\n\n"
        "def add(a, b):\n"
        "    # TODO: validate inputs\n"
        "    return a + b\n\n\n"
        "def run(path):\n"
        "    return eval(path)\n"  # a security smell for the scanners
    )
    (tmp_path / "README.md").write_text("# sample project\n")

    _freeze(monkeypatch)
    root = str(tmp_path)

    expected = _ORIGINAL.build_dashboard(root, **kwargs)
    actual = current.build_dashboard(root, **kwargs)

    assert actual == expected, "build_dashboard HTML diverged from pre-refactor output"


def test_build_dashboard_empty_project(tmp_path, monkeypatch):
    """Edge/empty path: an essentially empty project still renders identically.

    A bare (non-git) directory exercises the empty-git / no-autonomy branches and
    every ``_build_*`` helper's graceful-degradation path on a profile with no
    source files.
    """
    _freeze(monkeypatch)
    root = str(tmp_path)
    expected = _ORIGINAL.build_dashboard(root, quality=True)
    actual = current.build_dashboard(root, quality=True)
    assert actual == expected
