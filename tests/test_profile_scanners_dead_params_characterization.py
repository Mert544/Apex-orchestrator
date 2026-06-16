"""Characterization harness for the ``_scan_dead_params`` refactor.

Proves the decomposed implementation is byte-identical to the pre-refactor
original (snapshotted from ``HEAD`` at refactor time) across several
representative temp trees: same ``profile.dead_params`` list — order and
contents — for every input. Offline, stdlib + pytest only.

The "original" is loaded by importing the HEAD snapshot of the module under a
distinct name and instantiating its mixin against the SAME ``ProjectProfiler``
attribute surface, so both implementations see identical inputs and only the
``_scan_dead_params`` logic differs.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.tools.project_profile import ProjectProfiler

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_REL = "app/tools/profile_scanners.py"


def _load_original_mixin():
    """Import the HEAD snapshot of profile_scanners.py as a throwaway module and
    return its ``_CodeQualityScansMixin`` class (the pre-refactor scan)."""
    src = subprocess.check_output(
        ["git", "show", f"HEAD:{TARGET_REL}"], cwd=str(REPO_ROOT)
    ).decode("utf-8")
    mod = types.ModuleType("_orig_profile_scanners")
    spec = importlib.util.spec_from_loader(mod.__name__, loader=None)
    mod.__spec__ = spec
    sys.modules[mod.__name__] = mod
    exec(compile(src, "<orig_profile_scanners>", "exec"), mod.__dict__)
    return mod._CodeQualityScansMixin


_OriginalMixin = _load_original_mixin()


class _OriginalProfiler(_OriginalMixin, ProjectProfiler):
    """ProjectProfiler whose ``_scan_dead_params`` is the HEAD-snapshot original.

    MRO puts the original mixin first, so ``_scan_dead_params`` (and the helpers
    it carries) come from the snapshot, while every other attribute
    (``root``, ``max_files``, ``_is_fixture_path``, ...) is the real profiler's.
    """


def _make_profile():
    """A bare object the scanner can write ``dead_params`` onto."""
    return types.SimpleNamespace(dead_params=None)


def _run(profiler_cls, root: Path):
    prof = profiler_cls(str(root))
    out = _make_profile()
    prof._scan_dead_params(out)
    return out.dead_params


# --- representative inputs -------------------------------------------------

def _tree_basic(root: Path) -> None:
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "core.py").write_text(
        "def render(text, color=None, width=80):\n"
        "    return text[:width]\n"
        "\n"
        "def fetch(url, *, retries=3):\n"
        "    return url\n"
        "\n"
        "def walk(node, _depth=0):\n"
        "    return node\n"
    )
    (root / "app" / "iface.py").write_text(
        "def apply(x, extra):\n    return x\n"
    )
    (root / "app" / "iface2.py").write_text(
        "import functools\n\n"
        "def apply(y, extra):\n    return y\n\n"
        "def on_event(payload):\n    return 1\n\n"
        "HANDLER = on_event\n\n"
        "@functools.lru_cache\n"
        "def cached(size):\n    return 1\n\n"
        "def proto(handler):\n    raise NotImplementedError\n"
    )
    (root / "tests" / "test_x.py").write_text("def helper(unused):\n    return 1\n")


def _tree_empty(root: Path) -> None:
    (root / "app").mkdir()
    (root / "app" / "clean.py").write_text(
        "def add(a, b):\n    return a + b\n"
    )


def _tree_posonly_kwonly(root: Path) -> None:
    (root / "pkg").mkdir()
    (root / "pkg" / "m.py").write_text(
        "def f(a, b, /, c, *, d, e):\n"
        "    return a + c + e\n"
        "\n"
        "def g(self, cls, used, unused):\n"
        "    return used\n"
        "\n"
        "def h(*args, **kwargs):\n"
        "    return 1\n"
    )


def _tree_async_and_attr_refs(root: Path) -> None:
    (root / "svc").mkdir()
    (root / "svc" / "a.py").write_text(
        "async def handle(req, ctx):\n"
        "    return req\n"
        "\n"
        "def dispatch(table):\n"
        "    return table.handle\n"
    )
    (root / "svc" / "b.py").write_text(
        "def lonely(one, two, three):\n"
        "    return one\n"
        "\n"
        '"""module docstring at end is fine"""\n'
    )


def _tree_docstring_stub(root: Path) -> None:
    (root / "z").mkdir()
    (root / "z" / "p.py").write_text(
        "def documented(keep, drop):\n"
        '    """A real docstring then real code."""\n'
        "    return keep\n"
        "\n"
        "def stub(x, y):\n"
        '    """Just a docstring."""\n'
        "    pass\n"
        "\n"
        "def raiser(a, b):\n"
        "    raise RuntimeError\n"
    )


def _tree_syntax_error(root: Path) -> None:
    (root / "app").mkdir()
    (root / "app" / "ok.py").write_text(
        "def thing(alpha, beta):\n    return alpha\n"
    )
    (root / "app" / "broken.py").write_text("def oops(:\n    pass\n")


_BUILDERS = [
    _tree_basic,
    _tree_empty,
    _tree_posonly_kwonly,
    _tree_async_and_attr_refs,
    _tree_docstring_stub,
    _tree_syntax_error,
]


@pytest.mark.parametrize("builder", _BUILDERS, ids=[b.__name__ for b in _BUILDERS])
def test_dead_params_byte_identical_to_original(builder, tmp_path: Path):
    builder(tmp_path)
    original = _run(_OriginalProfiler, tmp_path)
    refactored = _run(ProjectProfiler, tmp_path)
    assert refactored == original, (
        f"{builder.__name__}: refactored dead_params diverged from HEAD snapshot"
    )


def test_helpers_are_pure_and_static():
    """The extracted analysis helpers don't touch ``self`` — they are pure on
    their AST inputs, so determinism cannot depend on profiler state."""
    from app.tools.profile_scanners import _CodeQualityScansMixin as M

    for name in ("_module_object_refs", "_is_stub_body", "_dead_params_of"):
        assert isinstance(M.__dict__[name], staticmethod), name
