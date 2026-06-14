"""Further edge coverage for app/execution/semantic/transforms/fstring.py.

Targets the ``_depluralized`` "nothing actually changed" guard reasoning and a
few more conservative-skip shapes the canonical and ``_more_edges`` suites leave
open. Deterministic, stdlib-only; explicit AST/source inputs only.
"""

from __future__ import annotations

import pytest

from app.execution.semantic.transforms import fstring


def _apply(src: str) -> str | None:
    r = fstring.apply("m.py", src, "drop dead f-string prefix")
    return r.patch_requests[0]["new_content"] if r else None


# --- the candidate-equals-seg guard (line 51) ----------------------------- #

@pytest.mark.xfail(
    reason="fstring.py:51 (`if candidate == seg`) is unreachable defensively: "
    "_depluralized only reaches it when the prefix contains f/F, and stripping "
    "f/F always shortens the segment, so candidate is strictly shorter than seg "
    "and can never equal it. No input exercises the early `return None` there.",
    strict=True,
)
def test_candidate_equals_seg_is_reachable():
    # There is no f-string source segment for which removing the `f` prefix and
    # un-doubling braces yields the identical original segment, so this guard
    # cannot be triggered through _depluralized's public contract.
    probes = ['f""', 'f"x"', 'F"hi"', 'rf"y"', 'f"{{}}"', 'f"a{{b}}c"']
    assert any(fstring._depluralized(seg, "") == seg for seg in probes)


# --- behaviour-preserving rewrites that DO change the source -------------- #

def test_escaped_braces_are_undoubled_on_rewrite():
    # f"{{x}}" with no placeholder is the literal "{x}"; the rewrite must drop
    # the f AND un-double the braces so the value is preserved.
    assert _apply('s = f"{{x}}"\n') == 's = "{x}"\n'


def test_uppercase_F_prefix_rewritten():
    assert _apply('s = F"hi"\n') == 's = "hi"\n'


def test_rf_prefix_kept_as_r_only():
    # The r is preserved, only the f is stripped (raw-string semantics intact).
    assert _apply('s = rf"hi"\n') == 's = r"hi"\n'


# --- conservative skips: value-changing or non-minimal edits -------------- #

def test_multiline_fstring_skipped():
    # A multi-line placeholder-less f-string is skipped to keep the splice exact.
    src = 's = f"""\nhi\n"""\n'
    assert _apply(src) is None


def test_implicit_concat_fstring_first_then_plain_rewritten():
    # f"a" "b" — the span starts at the f-string, so the f is droppable; the
    # node's runtime value is "ab" and the candidate parses to that value.
    assert _apply('s = f"a" "b"\n') == 's = "a" "b"\n'
