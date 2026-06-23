"""Deep mutation-hardening for ``app/engine/dream_landing.py`` — the line-targeted
mutants that moved here with the dream→landing seam.

When the seam (`dream_confluence_modules` / `compile_from_dream` and their
helpers) was relocated out of ``objective_compiler.py`` into ``dream_landing.py``
(so its imports of ``ascend``/``dream`` flow one-way), the source lines those
mutants pin moved too. These tests are the re-anchored survivors — each pins a
single mutated token's observable effect against ``dream_landing.py``'s current
lines, named for its line + operator there.

Style mirrors ``test_objective_compiler_deep_mutation_eyml.py``: a tiny
``tmp_path`` project, direct calls, no fakes for the parts under test.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.engine.dream_landing import compile_from_dream, dream_confluence_modules


def _project(tmp_path: Path, body: str, rel: str = "app/m.py") -> Path:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / rel).write_text(body, encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_import():\n    assert app.m is not None\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


_THREE_DEAD = (
    "def render(text, color=None, width=80):\n"
    "    return text[:width]\n\n\n"
    "def fetch(url, retries=3):\n"
    "    return url\n\n\n"
    "def use():\n"
    "    return render('hi', width=2) + fetch('u')\n"
)


# --- L46: `key.split(":", 1)[1]` maxsplit matters at index [1] ----------------

def test_l46_confluence_key_keeps_full_module_path_after_first_colon(tmp_path):
    # A confluence key may carry a module path; `split(":", 1)[1]` keeps
    # EVERYTHING after the first colon. With a windows-style or namespaced module
    # containing a second ':' the `1 -> 2` maxsplit mutant would truncate it.
    _project(tmp_path, "x = 1\n", rel="app/a:b.py")
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-promotions.json").write_text(
        json.dumps([{"key": "confluence:app/a:b.py"}]), encoding="utf-8")
    # maxsplit 1 -> "app/a:b.py" (the real file). maxsplit 2 -> "app/a" (missing).
    assert dream_confluence_modules(str(tmp_path)) == ["app/a:b.py"]


# --- L129/L130: compile_from_dream default flags -----------------------------

def test_l130_compile_from_dream_apply_defaults_true(tmp_path):
    # `apply: bool = True` default -> the scoped campaign writes. The
    # `True -> False` mutant would default to a dry run (applied=False).
    _project(tmp_path, _THREE_DEAD)
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-promotions.json").write_text(
        json.dumps([{"key": "confluence:app/m.py"}]), encoding="utf-8")
    results = compile_from_dream(str(tmp_path), objective="dead-params",
                                 verify=False)
    assert results
    assert results[0].applied is True


def test_l129_compile_from_dream_verify_defaults_true(tmp_path):
    # `verify: bool = True` default -> the scoped campaign suite-verifies each
    # landed step. The `True -> False` mutant would default verify off.
    _project(tmp_path, _THREE_DEAD)
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "dream-promotions.json").write_text(
        json.dumps([{"key": "confluence:app/m.py"}]), encoding="utf-8")
    results = compile_from_dream(str(tmp_path), objective="dead-params")
    assert results and results[0].steps
    assert all(s.verified is True for s in results[0].steps)


# --- Equivalent mutants (documented, not tested) -----------------------------
#
# * L129 `max_steps: int = 25` default (compile_from_dream): this objective runs
#   a SCOPED, per-module campaign — `max_steps` caps the moves landed in ONE
#   module, threaded straight into ``compile_objective`` as that module's cap. No
#   single module realistically presents > 25 simultaneously landable moves for
#   one objective (modernize yields <= 3/module; the dead-param/import/bool
#   detectors yield at most a handful), so the cap is never the binding
#   constraint and 25 vs 26 is unobservable. The non-scoped 25-default IS pinned
#   in ``test_objective_compiler_deep_mutation_eyml.py`` (compile_objective /
#   compile_all). EQUIVALENT-IN-PRACTICE.
