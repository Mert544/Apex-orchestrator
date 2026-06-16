"""Characterization harness for `render_review_markdown`.

Proves the refactored renderer emits byte-identical markdown to the snapshot of
the original implementation, across inputs that exercise every branch:

- empty / no-changed-files short-circuit
- clean diff (no findings)
- findings with each `fix_kind` routing (suggestion, rule:, extract, inline,
  duplication, auto_fixable, needs-a-human) and every severity icon
- the `limit` cap + hidden-count footer (and `0` = unlimited)
- inline suggestion diff blocks
- the change-impact section, with and without the "(+N more)" suffix

The original is loaded from a frozen source string captured from `HEAD`, so the
test is self-contained and stays green only while the live renderer matches it
byte-for-byte.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app.engine.diff_review import (
    ChangeImpact,
    ReviewFinding,
    ReviewResult,
    render_review_markdown,
)

_REPO = Path(__file__).resolve().parents[1]


def _load_original_render():
    """Compile the renderer exactly as it existed at HEAD and return it.

    Self-contained: no test fixtures on disk, no network — `git show` reads the
    committed blob and we exec it as a throwaway module so the original and the
    live function can be compared in the same process.
    """
    src = subprocess.run(
        ["git", "show", "HEAD:app/engine/diff_review.py"],
        cwd=str(_REPO), capture_output=True, text=True, check=True,
    ).stdout
    spec = importlib.util.spec_from_loader("_diff_review_head", loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_diff_review_head"] = mod
    exec(compile(src, "<diff_review@HEAD>", "exec"), mod.__dict__)
    return mod.render_review_markdown


_original_render = _load_original_render()


def _finding(file, line, category, severity, message, auto_fixable, fix_kind="",
             suggestion=None):
    f = ReviewFinding(file, line, category, severity, message, auto_fixable, fix_kind)
    f.suggestion = suggestion
    return f


def _cases():
    """Every distinct branch of the renderer, as (label, result, limit)."""
    cases: list[tuple[str, ReviewResult, int]] = []

    # No changed files at all.
    cases.append(("empty", ReviewResult(base="HEAD", files_reviewed=0), 0))
    cases.append(("empty-named-base",
                  ReviewResult(base="origin/main", files_reviewed=0), 0))

    # Clean diff: files reviewed, no findings.
    cases.append(("clean", ReviewResult(base="HEAD", files_reviewed=3), 0))
    cases.append(("clean-one", ReviewResult(base="v1.2", files_reviewed=1), 5))

    # One finding per fix-routing branch + each severity icon.
    routed = [
        _finding("app/a.py", 1, "security", "high", "eval is unsafe", True,
                 "eval", suggestion=("eval(x)", "literal_eval(x)")),
        _finding("app/b.py", 2, "convention", "medium",
                 "rule `no-len-zero`: `len(x)==0` → `not x`", True, "rule:no-len-zero"),
        _finding("app/c.py", 3, "refactor", "low", "long fn", False, "extract"),
        _finding("app/d.py", 4, "refactor", "low", "single-use helper", False, "inline"),
        _finding("app/e.py", 5, "refactor", "low", "duplicated block", False, "duplication"),
        _finding("app/f.py", 6, "bug", "high", "auto fixable other", True, "open-encoding"),
        _finding("app/g.py", 7, "docs", "low", "needs human", False, ""),
        _finding("app/h.py", 8, "style", "medium", "weird sev icon", False, "unknown"),
    ]
    cases.append(("all-routes",
                  ReviewResult(base="HEAD", files_reviewed=8, findings=list(routed)), 0))

    # Unknown severity → ⚪ fallback icon.
    cases.append(("odd-severity",
                  ReviewResult(base="HEAD", files_reviewed=1, findings=[
                      _finding("app/x.py", 1, "security", "critical", "??", False, "")]), 0))

    # Limit truncation + hidden footer, and limit=0 unlimited.
    many = [_finding(f"app/m{i}.py", i + 1, "security", "high", f"issue {i}", False, "")
            for i in range(6)]
    cases.append(("limit-2", ReviewResult(base="HEAD", files_reviewed=6,
                                          findings=list(many)), 2))
    cases.append(("limit-0-unlimited", ReviewResult(base="HEAD", files_reviewed=6,
                                                    findings=list(many)), 0))
    cases.append(("limit-exceeds", ReviewResult(base="HEAD", files_reviewed=6,
                                               findings=list(many)), 40))
    cases.append(("limit-negative", ReviewResult(base="HEAD", files_reviewed=6,
                                                findings=list(many)), -3))

    # Suggestion block rendering with multiple findings interleaved.
    mixed = [
        _finding("app/s.py", 10, "security", "high", "sug one", True, "none-comparison",
                 suggestion=("x == None", "x is None")),
        _finding("app/s.py", 12, "style", "low", "plain", False, ""),
        _finding("app/s.py", 14, "security", "medium", "sug two", True, "fstring-no-placeholder",
                 suggestion=("f'hi'", "'hi'")),
    ]
    cases.append(("suggestions",
                  ReviewResult(base="HEAD", files_reviewed=1, findings=mixed), 0))

    # Impacts only (no findings).
    cases.append(("impacts-only", ReviewResult(
        base="HEAD", files_reviewed=1,
        impacts=[ChangeImpact("app/m.py", "parse", 3, 2, ["app/a.py:1", "app/b.py:2"])]), 0))

    # Impacts with "(+N more)" suffix.
    cases.append(("impacts-more", ReviewResult(
        base="HEAD", files_reviewed=1,
        impacts=[ChangeImpact("app/m.py", "parse", 3, 10, ["app/a.py:1", "app/b.py:2"])]), 0))

    # Findings AND impacts together.
    cases.append(("findings-and-impacts", ReviewResult(
        base="HEAD", files_reviewed=2, findings=list(routed),
        impacts=[ChangeImpact("app/m.py", "f", 1, 3, ["app/a.py:1"]),
                 ChangeImpact("app/n.py", "g", 9, 1, ["app/c.py:9"])]), 0))

    # Empty callers list on an impact (caller_count == 0, no "more" suffix).
    cases.append(("impacts-empty-callers", ReviewResult(
        base="HEAD", files_reviewed=1,
        impacts=[ChangeImpact("app/m.py", "fn", 2, 0, [])]), 0))

    return cases


@pytest.mark.parametrize("label,result,limit", _cases(), ids=[c[0] for c in _cases()])
def test_render_byte_identical_to_head(label, result, limit):
    assert render_review_markdown(result, limit) == _original_render(result, limit)
