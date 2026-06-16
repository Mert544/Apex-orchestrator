"""Characterization harness proving the ``_scan_call_sites`` refactor in
``app.execution.param_add`` is byte-identical to the pre-refactor original.

The original module body is recovered from git (``HEAD:app/execution/param_add.py``
at the base commit) and executed under a throwaway module name, so we hold the
exact original ``plan_param_add`` and the refactored one side by side. Many
source snippets are fed through both; every dataclass field of the resulting
``RenamePlan`` (defined_in, originals, new_contents, edits_by_file, blockers,
warnings) must match exactly. Zero mismatches ⇒ byte-identical behaviour.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.execution.param_add import plan_param_add as plan_new

# The base commit the refactor was layered on top of — the snapshot we compare
# against. Using the parent of HEAD would drift once we commit, so we pin the
# refactor's base explicitly via the file path's git blob at that ref.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_TARGET_REL = "app/execution/param_add.py"


def _load_original_plan_param_add():
    """Execute the pre-refactor ``param_add.py`` (recovered from git history)
    as an isolated module and return its ``plan_param_add``."""
    # Find the most recent revision of the target whose _scan_call_sites is the
    # original monolith (i.e. lacks the helper we introduced). Walk back from
    # HEAD over the file's history until we find it.
    revs = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "log", "--format=%H", "--", _TARGET_REL],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    source = None
    for rev in revs:
        blob = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "show", f"{rev}:{_TARGET_REL}"],
            capture_output=True, text=True, check=True,
        ).stdout
        if "_resolve_call_names" not in blob and "_scan_call_sites" in blob:
            source = blob
            break
    assert source is not None, "could not recover pre-refactor param_add.py"

    mod = types.ModuleType("_param_add_original_characterization")
    mod.__file__ = str(_REPO_ROOT / _TARGET_REL)
    spec = importlib.util.spec_from_loader(mod.__name__, loader=None)
    mod.__spec__ = spec
    sys.modules[mod.__name__] = mod
    exec(compile(source, mod.__file__, "exec"), mod.__dict__)
    return mod.plan_param_add


plan_old = _load_original_plan_param_add()


def _plan_tuple(plan):
    """A fully comparable snapshot of every field that defines plan output."""
    return (
        plan.old,
        plan.new,
        plan.defined_in,
        dict(plan.originals),
        dict(plan.new_contents),
        dict(plan.edits_by_file),
        list(plan.blockers),
        list(plan.warnings),
        plan.ok,
        plan.render_diff(),
    )


# (files: {relpath: source}, func_name, param, default) snippets exercising
# every branch of the scan + plan path.
_CASES = [
    # plain append
    ({"app/core.py": "def fetch(url):\n    return url\n"},
     "fetch", "retries", "3"),
    # annotated param spacing
    ({"app/core.py": "def fetch(url: str):\n    return url\n"},
     "fetch", "retries", "3"),
    # *args -> keyword-only placement
    ({"app/s.py": "def star(a, *items):\n    return a\n"},
     "star", "flag", "False"),
    # existing keyword-only
    ({"app/s.py": "def kw(a, *, flag=False):\n    return a\n"},
     "kw", "extra", "0"),
    # **kwargs stays last
    ({"app/s.py": "def kwf(a, **extra):\n    return a\n"},
     "kwf", "flag", "True"),
    # positional-only
    ({"app/s.py": "def po(probe, /):\n    return probe\n"},
     "po", "flag", "1"),
    # posonly + normal + defaults
    ({"app/s.py": "def mix(p, /, a, b=1):\n    return p\n"},
     "mix", "g", "2"),
    # invalid identifier blocker
    ({"app/c.py": "def fetch(url):\n    return url\n"},
     "fetch", "1bad", "3"),
    # keyword param blocker
    ({"app/c.py": "def fetch(url):\n    return url\n"},
     "fetch", "class", "3"),
    # bad default expression blocker
    ({"app/c.py": "def fetch(url):\n    return url\n"},
     "fetch", "retries", "def x"),
    # name clash: existing param
    ({"app/c.py": "def fetch(url, retries=1):\n    return url\n"},
     "fetch", "retries", "3"),
    # name clash: used in body
    ({"app/c.py": "def fetch(url):\n    return retries\n"},
     "fetch", "retries", "3"),
    # comment in signature block -> blocker
    ({"app/c.py": "def fetch(url,  # note\n    timeout=1):\n    return url\n"},
     "fetch", "retries", "3"),
    # missing definition
    ({"app/c.py": "def other(url):\n    return url\n"},
     "fetch", "retries", "3"),
    # call site already passes keyword (from import) -> blocker
    ({"app/core.py": "def fetch(url):\n    return url\n",
      "app/user.py": "from app.core import fetch\n"
                     "def g():\n    return fetch('a', retries=5)\n"},
     "fetch", "retries", "3"),
    # call site passes keyword via aliased from-import
    ({"app/core.py": "def fetch(url):\n    return url\n",
      "app/user.py": "from app.core import fetch as ft\n"
                     "def g():\n    return ft('a', retries=5)\n"},
     "fetch", "retries", "3"),
    # call via module alias attribute
    ({"app/core.py": "def fetch(url):\n    return url\n",
      "app/user.py": "import app.core as c\n"
                     "def g():\n    return c.fetch('a', retries=5)\n"},
     "fetch", "retries", "3"),
    # call via plain module import attribute
    ({"app/core.py": "def fetch(url):\n    return url\n",
      "app/user.py": "import app.core\n"
                     "def g():\n    return app.core.fetch('a', retries=5)\n"},
     "fetch", "retries", "3"),
    # **kwargs splat at call site -> warning, still applies
    ({"app/core.py": "def fetch(url):\n    return url\n",
      "app/user.py": "from app.core import fetch\n"
                     "def g(d):\n    return fetch('a', **d)\n"},
     "fetch", "retries", "3"),
    # call site in definition module itself
    ({"app/core.py": "def fetch(url):\n    return url\n"
                     "def h():\n    return fetch('a', retries=1)\n"},
     "fetch", "retries", "3"),
    # unrelated same-name function elsewhere (no import) -> not ours
    ({"app/core.py": "def fetch(url):\n    return url\n",
      "app/other.py": "def fetch(url):\n    return url\n"
                      "def g():\n    return fetch('a', retries=1)\n"},
     "fetch", "retries", "3"),
    # multiple definitions -> ambiguous (no sole definition)
    ({"app/a.py": "def fetch(url):\n    return url\n",
      "app/b.py": "def fetch(url):\n    return url\n"},
     "fetch", "retries", "3"),
    # call without our keyword -> clean apply
    ({"app/core.py": "def fetch(url):\n    return url\n",
      "app/user.py": "from app.core import fetch\n"
                     "def g():\n    return fetch('a')\n"},
     "fetch", "retries", "3"),
    # syntax-broken file present alongside valid def
    ({"app/core.py": "def fetch(url):\n    return url\n",
      "app/broken.py": "def (:\n"},
     "fetch", "retries", "3"),
]


def _write_project(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


@pytest.mark.parametrize("files,func,param,default", _CASES)
def test_byte_identical(tmp_path, files, func, param, default):
    old = plan_old(_write_project(tmp_path / "old", files), func, param, default)
    new = plan_new(_write_project(tmp_path / "new", files), func, param, default)
    assert _plan_tuple(old) == _plan_tuple(new)


def test_resulting_sources_parse():
    """Any produced new_contents must remain valid Python (sanity)."""
    import tempfile
    for files, func, param, default in _CASES:
        with tempfile.TemporaryDirectory() as d:
            root = _write_project(Path(d), files)
            plan = plan_new(root, func, param, default)
            for text in plan.new_contents.values():
                ast.parse(text)
