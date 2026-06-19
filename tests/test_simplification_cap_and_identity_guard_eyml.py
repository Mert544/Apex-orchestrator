"""Deep mutation-hardening pins for two R&D-wave safety/perf changes:

1. ``app/tools/project_profile.py`` — the simplification-scan SAMPLE cap.
   ``_scan_simplifications`` must never inherit the profiler's 2000-file ceiling
   for the (expensive, capped-output) whole-tree dry-run; it caps at
   ``min(self.max_files, _SIMPLIFICATION_SCAN_CAP)`` where
   ``_SIMPLIFICATION_SCAN_CAP == 500`` (L239, L743). These tests monkeypatch
   ``scan_simplifications`` to CAPTURE the ``max_files`` value actually passed and
   pin the exact 500 boundary: a profiler with max_files > 500 caps at 500;
   <= 500 passes through unchanged.

2. ``app/execution/semantic/transforms/identity_literal.py`` — the multi-``is``
   refusal. A line carrying MORE THAN ONE ``is``/``is not`` operator is refused
   (the whole-line regex can't tell the F632 target from a sibling identity test
   that merely opens with a bracket, so rewriting would change behaviour). A line
   with a single identity-vs-literal comparison still rewrites. These tests build
   the exact adversarial case from the finding and pin both sides of the guard.

Every assertion targets an exact value or boundary. No wall clock, no randomness,
no set/dict iteration order, no real git history — deterministic and reproducible.

Style mirrors ``test_project_profile_deep_mutation_eyml.py`` and
``test_transform_identity_literal.py``: direct calls + tight value assertions.
"""

from __future__ import annotations

import ast

import app.tools.simplification_scan as ss
from app.execution.semantic.transforms import identity_literal as il
from app.tools.project_profile import (
    _SIMPLIFICATION_SCAN_CAP,
    ProjectProfile,
    ProjectProfiler,
)


# --------------------------------------------------------------------------- #
# project_profile: the simplification-scan SAMPLE cap (L239, L743).
# --------------------------------------------------------------------------- #

def test_simplification_scan_cap_constant_is_five_hundred():
    """The sampling cap is exactly 500 (L239)."""
    assert _SIMPLIFICATION_SCAN_CAP == 500


def _capture_scan_max_files(monkeypatch, max_files: int) -> int:
    """Run ``_scan_simplifications`` with a stub ``scan_simplifications`` that
    records the ``max_files`` it received, and return that value.

    ``_scan_simplifications`` imports ``scan_simplifications`` from
    ``app.tools.simplification_scan`` INSIDE the function body, so patching the
    module attribute is what the import resolves to.
    """
    captured: dict[str, int] = {}

    def fake_scan(root, max_files=_SIMPLIFICATION_SCAN_CAP):
        captured["max_files"] = max_files
        return []

    monkeypatch.setattr(ss, "scan_simplifications", fake_scan)
    prof = ProjectProfiler(".", max_files=max_files)
    profile = ProjectProfile(root=".")
    prof._scan_simplifications(profile)
    assert profile.simplification_opportunities == []
    return captured["max_files"]


def test_scan_cap_clamps_max_files_above_cap(monkeypatch):
    """A profiler with max_files > 500 caps the scan at 500 (L743 ``min(...)``).

    The default 2000-file ceiling must NOT reach the scanner — it would make a
    2000-module repo pay ~4x for an 8-entry result.
    """
    assert _capture_scan_max_files(monkeypatch, 2000) == 500


def test_scan_cap_passes_through_at_boundary(monkeypatch):
    """max_files == 500 passes through unchanged — the exact boundary (L743).

    ``min(500, 500) == 500``: flipping the boundary (e.g. ``min`` -> ``max``)
    would still yield 500 here, so the > 500 and < 500 cases below pin direction.
    """
    assert _capture_scan_max_files(monkeypatch, 500) == 500


def test_scan_cap_passes_through_just_below_boundary(monkeypatch):
    """max_files == 499 (< 500) passes through unchanged (L743 ``min(...)``).

    ``min(499, 500) == 499``. A ``max(...)`` mutation would return 500 here, and
    a hardcoded-500 mutation would also return 500 — both caught.
    """
    assert _capture_scan_max_files(monkeypatch, 499) == 499


def test_scan_cap_passes_through_just_above_boundary(monkeypatch):
    """max_files == 501 (> 500) is clamped to 500 (L743 ``min(...)``).

    ``min(501, 500) == 500``. A ``max(...)`` mutation would return 501 here.
    """
    assert _capture_scan_max_files(monkeypatch, 501) == 500


def test_scan_cap_passes_through_small_value(monkeypatch):
    """A tiny max_files (1) passes straight through (L743 ``min(...)``)."""
    assert _capture_scan_max_files(monkeypatch, 1) == 1


def test_scan_simplifications_best_effort_swallows_failure(monkeypatch):
    """A scanner exception leaves ``simplification_opportunities`` empty, not
    raised (L745-L746 ``except Exception``)."""
    def boom(root, max_files=_SIMPLIFICATION_SCAN_CAP):
        raise RuntimeError("scan blew up")

    monkeypatch.setattr(ss, "scan_simplifications", boom)
    prof = ProjectProfiler(".", max_files=2000)
    profile = ProjectProfile(root=".")
    profile.simplification_opportunities = [{"stale": "entry"}]
    prof._scan_simplifications(profile)
    assert profile.simplification_opportunities == []


# --------------------------------------------------------------------------- #
# identity_literal: the multi-``is`` refusal (L44-L55).
# --------------------------------------------------------------------------- #

def _apply(src: str) -> str | None:
    result = il.apply("m.py", src, "fix identity-literal")
    return result.patch_requests[0]["new_content"] if result else None


# The exact adversarial case from the finding: a line with TWO identity
# operators where only the first is a literal target. The whole-line regex
# would also rewrite ``y is (z)`` (a bracket-opening sibling identity test) to
# ``==``, silently changing behaviour — so the line must be refused entirely.
_ADVERSARIAL = "R = (q is 6) or (y is (z))\n"


def test_adversarial_multi_is_line_is_refused():
    """A line carrying TWO ``is`` operators is NOT rewritten (L48-L55 the
    per-line identity count + the ``== 1`` keep-filter).

    ``R = (q is 6) or (y is (z))`` has a real F632 target (``q is 6``) AND a
    bracket-opening sibling (``y is (z)``); rewriting the sibling to ``==`` would
    change behaviour, so the whole line is refused — ``apply`` returns None.
    """
    assert _apply(_ADVERSARIAL) is None


def test_single_identity_literal_line_is_rewritten():
    """A plain single ``x is 5`` line IS rewritten to ``x == 5`` (L52-L55).

    With one identity operator there is no sibling to corrupt, so the rewrite is
    provably safe and fires.
    """
    out = _apply("if x is 5:\n    pass\n")
    assert out == "if x == 5:\n    pass\n"
    ast.parse(out)


def test_single_identity_in_multi_line_module_still_rewrites():
    """The single-identity ``x is 5`` rewrites even when the adversarial line is
    also present — only the unsafe line is held back (L55 filters per-line).

    The safe line on its own is rewritten; the adversarial line is left intact,
    so the module is NOT a no-op (it returns a patch) but the unsafe ``is`` is
    preserved.
    """
    src = "if x is 5:\n    pass\nR = (q is 6) or (y is (z))\n"
    out = _apply(src)
    assert out is not None
    assert "if x == 5:" in out
    # The adversarial line is preserved verbatim — its ``is`` operators untouched.
    assert "R = (q is 6) or (y is (z))" in out
    ast.parse(out)


def test_two_literal_identities_on_one_line_are_refused():
    """A line with TWO identity-vs-LITERAL comparisons is still refused (L55).

    Even when BOTH siblings are literal targets, the count exceeds one, so the
    whole-line regex's all-or-nothing rewrite is held back rather than risk
    re-associating either occurrence.
    """
    assert _apply("R = (q is 6) and (p is 7)\n") is None


def test_chained_identity_comparison_is_refused():
    """A chained ``a is b is 5`` carries two identity ops in ONE Compare node and
    is refused (L50 ``n_ident`` sums ops within a node, L55 ``== 1`` filter)."""
    assert _apply("if a is b is 5:\n    pass\n") is None
