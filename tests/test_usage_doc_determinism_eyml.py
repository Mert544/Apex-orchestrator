"""generate-usage-doc determinism — the LANDED USAGE.md must not vary by seed.

P1 moat regression guard. A docstring doctest whose expected output is a ``set``
literal (``>>> get_tags()`` -> ``{'a', 'b', 'c'}``) used to be KEPT in the
generated doc under some ``PYTHONHASHSEED`` values and OMITTED under others,
because the inner ``doctest`` subprocess inherited the PARENT's randomized seed
and a set's repr order is hash-seed-dependent. Two CI runs then produced
different ``USAGE.md`` git diffs — violating the deterministic/no-random moat.

The fix pins ``PYTHONHASHSEED`` in the subprocess env that
``examples_run_green`` passes to ``subprocess.run`` (the only env-construction /
subprocess site in :mod:`app.execution.doctest_oracle`). These tests prove:

* the subprocess env pins the seed (the mechanism), and there is no OTHER
  unpinned env site in the module;
* a set-repr example's keep/omit verdict is now STABLE across simulated parent
  seeds (the prior keep@seed1 vs omit@seed0 flip is gone), so
  ``plan_generate_usage_doc`` renders BYTE-IDENTICAL ``USAGE.md``;
* a non-set / non-submodule project renders byte-identically too (no behavior
  drift); and
* FIX 2: examples that reference symbols defined in a SUBMODULE the ``__init__``
  does not re-export now RESOLVE (are kept) instead of all being dropped.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import app.execution.doctest_oracle as oracle
from app.execution.doctest_oracle import verify_examples
from app.execution.objectives.generate_usage_doc import plan_generate_usage_doc

# A set whose repr order under the PINNED seed (PYTHONHASHSEED=0) is
# ``{'c', 'a', 'b'}``; writing the docstring's expected output to match that
# fixed repr means the example is KEPT deterministically. Under a RANDOMIZED
# parent seed the inner repr would wander, so without the pin the keep/omit
# decision (and the doc bytes) would flip seed-to-seed.
_SEED0_SET_REPR = "{'c', 'a', 'b'}"


def _set_pkg(root: Path, *, reexport: bool, repr_literal: str = _SEED0_SET_REPR) -> None:
    """A package whose one public function returns ``{'a','b','c'}`` and whose
    docstring example expects ``repr_literal``."""
    pkg = root / "apipkg"
    pkg.mkdir()
    (pkg / "core.py").write_text(
        '"""Core helpers."""\n\n\n'
        "def get_tags():\n"
        '    """Return the tag set.\n\n'
        f"    >>> get_tags()\n    {repr_literal}\n"
        '    """\n'
        "    return {'a', 'b', 'c'}\n",
        encoding="utf-8",
    )
    init = "from .core import get_tags\n" if reexport else '"""apipkg."""\n'
    (pkg / "__init__.py").write_text(init, encoding="utf-8")


def _usage_bytes(root: Path, init_rel: str = "apipkg/__init__.py") -> str:
    plan = plan_generate_usage_doc(str(root), init_rel)
    return plan.new_contents.get("apipkg/USAGE.md", "")


# --- the mechanism: the subprocess env pins the hash seed --------------------

def test_subprocess_env_pins_pythonhashseed(tmp_path, monkeypatch):
    """The env dict handed to ``subprocess.run`` carries ``PYTHONHASHSEED`` set to
    a FIXED value — even when the parent process has a different one set."""
    _set_pkg(tmp_path, reexport=True)
    captured: dict[str, dict[str, str]] = {}
    real_run = subprocess.run

    def _spy(cmd, **kwargs):
        captured["env"] = dict(kwargs.get("env") or {})
        return real_run(cmd, **kwargs)

    monkeypatch.setenv("PYTHONHASHSEED", "12345")  # a hostile parent seed
    monkeypatch.setattr(oracle.subprocess, "run", _spy)
    verify_examples(str(tmp_path), "apipkg/__init__.py",
                    {"get_tags": [f">>> get_tags()\n{_SEED0_SET_REPR}"]})

    assert "env" in captured, "examples_run_green must spawn a subprocess here"
    seed = captured["env"].get("PYTHONHASHSEED")
    assert seed == "0", f"hash seed must be pinned to a fixed value, got {seed!r}"
    # It must be FIXED, not merely forwarded from the (randomized) parent.
    assert seed != "12345"


def test_module_has_no_unpinned_subprocess_env_site():
    """Defence in depth: every place this module copies ``os.environ`` into a
    subprocess env also pins ``PYTHONHASHSEED`` (no sibling site was missed)."""
    src = Path(oracle.__file__).read_text(encoding="utf-8")
    # The module copies the parent environment exactly once (one probe spawn).
    assert src.count("**os.environ") == 1
    assert src.count('"PYTHONHASHSEED"') == 1
    # And it does spawn exactly one subprocess to evaluate examples.
    assert src.count("subprocess.run(") == 1


# --- the symptom is gone: stable verdict across simulated parent seeds -------

def _verify_under_parent_seed(root: Path, seed: str, repr_literal: str) -> bool:
    """Run ``verify_examples`` in a fresh interpreter whose PARENT seed is
    ``seed`` (so the pin, not the parent, must decide the verdict). Returns
    whether ``get_tags`` was kept. The root and the (quote-laden) repr literal
    are passed as argv so the inlined program needs no embedded quoting."""
    code = (
        "import sys; from app.execution.doctest_oracle import verify_examples;"
        "root, lit = sys.argv[1], sys.argv[2];"
        "ex = '>>> get_tags()\\n' + lit;"
        "v = verify_examples(root, 'apipkg/__init__.py', {'get_tags': [ex]});"
        "print('KEPT' if 'get_tags' in v else 'OMITTED')"
    )
    env = {**os.environ, "PYTHONHASHSEED": seed,
           "PYTHONPATH": os.getcwd() + os.pathsep + os.environ.get("PYTHONPATH", "")}
    proc = subprocess.run([sys.executable, "-c", code, str(root), repr_literal],
                          capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip().splitlines()[-1] == "KEPT"


def test_set_repr_verdict_is_stable_across_parent_seeds(tmp_path):
    """A set-repr example matching the PINNED-seed repr is KEPT regardless of the
    parent process's hash seed — the prior keep@seed1 / omit@seed0 flip is gone."""
    _set_pkg(tmp_path, reexport=True)
    verdicts = {
        seed: _verify_under_parent_seed(tmp_path, seed, _SEED0_SET_REPR)
        for seed in ("0", "1", "2", "3", "5")
    }
    # All seeds agree (no flip), and they agree on KEEP (the example is true
    # under the pinned seed). Determinism is the headline; the value is a bonus.
    assert len(set(verdicts.values())) == 1, f"verdict flips by seed: {verdicts}"
    assert all(verdicts.values()), verdicts


def test_usage_md_is_byte_identical_across_parent_seeds(tmp_path):
    """The end-to-end artifact: the same package renders byte-identical
    ``USAGE.md`` no matter the parent seed (the set-repr example included)."""
    _set_pkg(tmp_path, reexport=True)
    rendered: set[str] = set()
    for seed in ("0", "1", "2", "3", "5"):
        code = (
            "import sys;"
            "from app.execution.objectives.generate_usage_doc import"
            " plan_generate_usage_doc;"
            "p = plan_generate_usage_doc(sys.argv[1], 'apipkg/__init__.py');"
            "sys.stdout.write(p.new_contents.get('apipkg/USAGE.md', ''))"
        )
        env = {**os.environ, "PYTHONHASHSEED": seed,
               "PYTHONPATH": os.getcwd() + os.pathsep
               + os.environ.get("PYTHONPATH", "")}
        proc = subprocess.run([sys.executable, "-c", code, str(tmp_path)],
                              capture_output=True, text=True, env=env, timeout=120)
        assert proc.returncode == 0, proc.stderr
        rendered.add(proc.stdout)
    assert len(rendered) == 1, "USAGE.md bytes differ across parent seeds"
    (only,) = rendered
    assert ">>> get_tags()" in only  # the proven set-repr example is kept


def test_usage_md_repeatable_in_process(tmp_path):
    """Two in-process runs of the plan produce byte-identical doc text."""
    _set_pkg(tmp_path, reexport=True)
    assert _usage_bytes(tmp_path) == _usage_bytes(tmp_path) != ""


# --- no drift for an ordinary (non-set, non-submodule) project ---------------

def test_plain_project_unchanged_and_deterministic(tmp_path):
    """A package with a plain scalar-repr example renders byte-identically across
    runs and keeps its example — the fix changes nothing for the common case."""
    pkg = tmp_path / "apipkg"
    pkg.mkdir()
    (pkg / "core.py").write_text(
        '"""Core."""\n\n\n'
        "def add(a: int, b: int = 0) -> int:\n"
        '    """Return the sum.\n\n    >>> add(2, 3)\n    5\n    """\n'
        "    return a + b\n",
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text("from .core import add\n", encoding="utf-8")
    first = _usage_bytes(tmp_path)
    assert first == _usage_bytes(tmp_path)
    assert "`add(a: int, b: int = 0) -> int`" in first
    assert ">>> add(2, 3)" in first  # plain example kept exactly as before


# --- FIX 2: submodule-defined symbols resolve instead of being dropped -------

def test_submodule_example_resolves_without_reexport(tmp_path):
    """When the documented symbol lives in a SUBMODULE and ``__init__`` does NOT
    re-export it, the example's call now RESOLVES (kept) instead of NameError-ing
    and dropping every example."""
    pkg = tmp_path / "apipkg"
    pkg.mkdir()
    (pkg / "core.py").write_text(
        '"""Core."""\n\n\n'
        "def greet(name):\n"
        '    """Greet.\n\n    >>> greet(\'x\')\n    \'hi x\'\n    """\n'
        "    return 'hi ' + name\n",
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text('"""apipkg."""\n', encoding="utf-8")  # no re-export
    verified = verify_examples(str(tmp_path), "apipkg/__init__.py",
                               {"greet": [">>> greet('x')\n'hi x'"]})
    assert verified == {"greet"}  # resolved via the submodule namespace


def test_submodule_layout_lands_doc_with_examples(tmp_path):
    """End-to-end: a submodule-layout package lands a ``USAGE.md`` that KEEPS the
    submodule symbol's example (the doc no longer loses all its examples)."""
    pkg = tmp_path / "apipkg"
    pkg.mkdir()
    (pkg / "core.py").write_text(
        '"""Core."""\n\n\n'
        "def greet(name):\n"
        '    """Greet.\n\n    >>> greet(\'x\')\n    \'hi x\'\n    """\n'
        "    return 'hi ' + name\n",
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text('"""apipkg."""\n', encoding="utf-8")
    plan = plan_generate_usage_doc(str(tmp_path), "apipkg/__init__.py")
    md = plan.new_contents.get("apipkg/USAGE.md", "")
    assert "`greet(name)`" in md
    assert ">>> greet('x')" in md  # FIX 2: example kept, not dropped


def test_reexport_layout_still_resolves(tmp_path):
    """Regression: a re-exporting layout behaves exactly as before — the package's
    own attribute wins and the example resolves."""
    _set_pkg(tmp_path, reexport=True, repr_literal=_SEED0_SET_REPR)
    verified = verify_examples(str(tmp_path), "apipkg/__init__.py",
                               {"get_tags": [f">>> get_tags()\n{_SEED0_SET_REPR}"]})
    assert verified == {"get_tags"}


def test_submodule_binding_does_not_fake_green_a_wrong_example(tmp_path):
    """Conservatism: binding submodule symbols never makes a genuinely WRONG
    example pass — a wrong expected output is still honestly dropped."""
    pkg = tmp_path / "apipkg"
    pkg.mkdir()
    (pkg / "core.py").write_text(
        '"""Core."""\n\n\n'
        "def f(x):\n"
        '    """F.\n\n    >>> f(1)\n    999\n    """\n'
        "    return x\n",
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text('"""apipkg."""\n', encoding="utf-8")
    verified = verify_examples(str(tmp_path), "apipkg/__init__.py",
                               {"f": [">>> f(1)\n999"]})
    assert verified == set()  # wrong output -> still dropped, no fake-green
