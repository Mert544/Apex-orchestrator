"""Characterization harness for `_line_suggestion`.

Proves the refactored `_line_suggestion` (now decomposed into the pure helpers
`_suggestion_transform` / `_rewritten_source` / `_single_line_change`) returns a
result byte-identical to the snapshot of the original implementation, across
inputs that exercise every branch:

- each routed `fix_kind` (open-encoding, none-comparison, identity-literal,
  negated-comparison, raise-from, fstring-no-placeholder, collection-literal,
  the two security kinds `bare except` / `base-exception`)
- the unrouted `fix_kind` → None short-circuit (`else` branch)
- a transform that raises → None (malformed source)
- a transform that yields no patch (already-clean source) → None
- the line-count-mismatch guard (an edit that adds/removes lines) → None
- the direct hit at `finding.line` vs. the single-diff fallback
- a multi-line edit / no edit → None

The original is loaded from a frozen blob captured from `HEAD`, exec'd as a
throwaway module so original and live function run in the same process and can
be compared call-for-call. Self-contained: only `git show`, no network.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app.engine.diff_review import ReviewFinding, _line_suggestion

_REPO = Path(__file__).resolve().parents[1]


def _load_original_line_suggestion():
    """Compile `_line_suggestion` exactly as it existed at HEAD and return it."""
    src = subprocess.run(
        ["git", "show", "HEAD:app/engine/diff_review.py"],
        cwd=str(_REPO), capture_output=True, text=True, check=True,
    ).stdout
    spec = importlib.util.spec_from_loader("_diff_review_head_ls", loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_diff_review_head_ls"] = mod
    exec(compile(src, "<diff_review@HEAD>", "exec"), mod.__dict__)
    return mod._line_suggestion


_original_line_suggestion = _load_original_line_suggestion()


def _finding(line: int, fix_kind: str) -> ReviewFinding:
    return ReviewFinding("app/x.py", line, "security", "high", "msg", True, fix_kind)


def _cases() -> list[tuple[str, str, str, ReviewFinding]]:
    """(label, rel, source, finding) covering every branch of _line_suggestion."""
    cases: list[tuple[str, str, str, ReviewFinding]] = []

    # --- Each routed fix_kind on a source where the detector fires. ---
    cases.append(("open-encoding", "app/x.py", "open('f.txt')\n", _finding(1, "open-encoding")))
    cases.append(("none-comparison", "app/x.py", "x == None\n", _finding(1, "none-comparison")))
    cases.append(("identity-literal", "app/x.py", "x is 1\n", _finding(1, "identity-literal")))
    cases.append(("negated-comparison", "app/x.py", "not a == b\n",
                  _finding(1, "negated-comparison")))
    cases.append(("raise-from", "app/x.py",
                  "try:\n    pass\nexcept Exception as e:\n    raise ValueError('x')\n",
                  _finding(4, "raise-from")))
    cases.append(("fstring-no-placeholder", "app/x.py", "y = f'hello'\n",
                  _finding(1, "fstring-no-placeholder")))
    cases.append(("collection-literal", "app/x.py", "d = dict()\n",
                  _finding(1, "collection-literal")))
    cases.append(("bare-except", "app/x.py",
                  "try:\n    pass\nexcept:\n    pass\n", _finding(3, "bare except")))
    cases.append(("base-exception", "app/x.py",
                  "try:\n    pass\nexcept BaseException:\n    pass\n",
                  _finding(3, "base-exception")))

    # --- Unrouted fix_kind → else branch → None. ---
    cases.append(("unrouted-empty", "app/x.py", "x == None\n", _finding(1, "")))
    cases.append(("unrouted-extract", "app/x.py", "x == None\n", _finding(1, "extract")))
    cases.append(("unrouted-rule", "app/x.py", "x == None\n", _finding(1, "rule:foo")))

    # --- Transform raises (syntactically broken source) → None. ---
    cases.append(("raises-syntax", "app/x.py", "def (:\n  x == None\n",
                  _finding(1, "none-comparison")))

    # --- Transform yields no patch (already clean) → None. ---
    cases.append(("no-patch-clean", "app/x.py", "x is None\n", _finding(1, "none-comparison")))
    cases.append(("no-patch-encoding", "app/x.py", "open('f', encoding='utf-8')\n",
                  _finding(1, "open-encoding")))

    # --- Direct hit at finding.line, multi-line file (fix on line 2). ---
    cases.append(("direct-hit-line2", "app/x.py",
                  "import os\ny = x == None\nz = 1\n", _finding(2, "none-comparison")))

    # --- Fallback: finding.line doesn't match the changed line, single diff. ---
    cases.append(("fallback-wrong-line", "app/x.py",
                  "import os\ny = x == None\nz = 1\n", _finding(3, "none-comparison")))
    cases.append(("fallback-line-out-of-range", "app/x.py",
                  "y = x == None\n", _finding(99, "none-comparison")))
    cases.append(("fallback-line-zero", "app/x.py",
                  "y = x == None\n", _finding(0, "none-comparison")))

    # --- No effective change at the finding line but another line differs. ---
    cases.append(("two-none-comparisons", "app/x.py",
                  "a = x == None\nb = y == None\n", _finding(1, "none-comparison")))

    return cases


@pytest.mark.parametrize("label,rel,source,finding", _cases(),
                         ids=[c[0] for c in _cases()])
def test_line_suggestion_byte_identical_to_head(label, rel, source, finding):
    assert (_line_suggestion(rel, source, finding)
            == _original_line_suggestion(rel, source, finding))
