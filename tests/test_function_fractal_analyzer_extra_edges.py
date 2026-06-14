"""Further edge-path coverage for the function-fractal analyzer.

Targets the two branches the existing suites leave open:

* the cross-file-impact BFS ``visited`` de-dup (a diamond where one caller is
  reached by two paths), and
* the ``_resolve_call`` imported-name path where the ``imported::name``
  candidate is NOT a known function so the resolver falls through.

A dead-code branch in ``_resolve_call`` is documented with an ``xfail`` (see
``test_resolve_call_dead_duplicate_candidate_is_unreachable``). All inputs are
explicit synthetic sources; nothing asserts on time, randomness, or ordering.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.tools.function_fractal_analyzer import FunctionFractalAnalyzer


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --- compute_cross_file_impact: BFS visited de-dup (diamond) ---------------

def test_cross_file_impact_bfs_dedupes_diamond_caller(tmp_path: Path):
    # Diamond: risky <- a, risky <- b, a <- c, b <- c. The BFS over callers
    # reaches ``c`` along TWO paths (via a and via b); the second arrival hits
    # the ``caller in visited`` guard and is counted exactly once.
    _write(tmp_path / "app" / "r.py", "def risky():\n    eval('1')\n")
    _write(
        tmp_path / "app" / "a.py",
        "from app.r import risky\n"
        "def a():\n"
        "    return risky()\n",
    )
    _write(
        tmp_path / "app" / "b.py",
        "from app.r import risky\n"
        "def b():\n"
        "    return risky()\n",
    )
    _write(
        tmp_path / "app" / "c.py",
        "from app.a import a\n"
        "from app.b import b\n"
        "def c():\n"
        "    return a() + b()\n",
    )
    impact = FunctionFractalAnalyzer().compute_cross_file_impact(tmp_path / "app")
    downstream = impact["app.r::risky"]["downstream"]
    # ``c`` is present exactly once despite being reachable via both a and b.
    assert downstream.count("app.c::c") == 1
    assert len(downstream) == len(set(downstream))
    assert impact["app.r::risky"]["downstream_count"] == len(downstream)


# --- _resolve_call: imported name whose candidate isn't a known function ----

def test_resolve_call_imported_name_falls_through_to_local(tmp_path: Path):
    # ``name`` is in imports, but ``imported::name`` is NOT a known function, so
    # the imported-candidate branch is exercised and falls through to the local
    # lookup, which DOES match.
    analyzer = FunctionFractalAnalyzer()
    call = ast.parse("helper()", mode="eval").body
    imports = {"helper": "some.other.module"}
    all_functions = {"app.mod::helper": "app/mod.py"}
    resolved = analyzer._resolve_call(call, imports, "app.mod", all_functions)
    assert resolved == "app.mod::helper"


def test_resolve_call_imported_candidate_matches(tmp_path: Path):
    # When ``imported::name`` IS a known function, it resolves directly.
    analyzer = FunctionFractalAnalyzer()
    call = ast.parse("helper()", mode="eval").body
    imports = {"helper": "app.lib"}
    all_functions = {"app.lib::helper": "app/lib.py"}
    resolved = analyzer._resolve_call(call, imports, "app.mod", all_functions)
    assert resolved == "app.lib::helper"


@pytest.mark.xfail(
    reason="Dead code: app/tools/function_fractal_analyzer.py:379-381 build a "
    "second candidate identical to the first (both `f'{imported}::{name}'`); "
    "since line 376 already returned on a hit, the line 380 re-check is always "
    "False and the line 381 `return candidate2` is unreachable.",
    strict=True,
)
def test_resolve_call_dead_duplicate_candidate_is_unreachable():
    # There is no input for which the SECOND candidate check (line 380) can
    # succeed while the FIRST (line 376) failed — they test the identical
    # string. This test asserts the contrary to mark the dead branch as a
    # known bug without weakening the real behavior.
    analyzer = FunctionFractalAnalyzer()
    call = ast.parse("helper()", mode="eval").body
    imports = {"helper": "app.lib"}
    # Crafted so candidate (line 375) is absent but a hypothetical "second"
    # candidate would differ — impossible, because candidate2 == candidate.
    all_functions = {"app.lib::helper_other": "app/lib.py"}
    # If 381 were reachable this would return a value; it cannot, so it is None.
    assert analyzer._resolve_call(call, imports, "app.mod", all_functions) is not None
