"""Regression suite for wave W99-fix0: the dedup/near-dup family's shipped bugs.

An adversarial red-team (independently skeptic-verified, probe-CONFIRMED on the
shipped tree) produced repros where the family's landers emitted silently-wrong
code with ZERO blockers. Each finding is frozen here exactly as the live probe
drove it — fixture → real detector (or a hand-built/replayed group, where
staleness is the point) → the SHIPPED planner — asserting the new blocker text
and empty ``new_contents``, plus a negative control per rail proving the
neighbouring sound shape still lands (exec-equivalence asserted wherever the
probe demonstrated wrong runtime values).

The seven fixes:

  1. OVERLAPPING same-file occurrence spans — the bottom-up call-site splice
     rewrites the lower copy first, so the upper copy's slice consumes the
     fresh call line and neighbouring code (near-dup probe: ``f(0)`` 7 → None).
     New shared rail ``_overlap_blocker`` (family-wide + near-dup lane).
  2. Multi-line BYTES literals escaped the multi-line-string rail
     (``isinstance(..., str)``): the re-indent corrupted the literal's contents
     and the corrupted module still parsed. Widened to ``(str, bytes)``; the
     blocker STRING is unchanged (pinned elsewhere).
  3. STALE-GROUP structural drift — operator/attribute/comparator edits are
     invisible to the leaf-path walk, so replaying a stale group silently
     rewired the unedited copy (probe: ``f1(5)`` 21 → 90). The FULL structural
     template is now re-derived per occurrence and must be identical.
  4. ``match``-PATTERN constant holes — ``case 100:`` vs ``case 200:`` grouped
     and spliced to ``case p0:``, a CAPTURE pattern that always matches
     (probe: ``alpha(7)`` 0 → 16). Pattern-position holes now refuse.
  5. ``global``/``nonlocal``-declared names the run binds or reads — a run
     STORE of a global-declared name became a helper-local bind, so an in-run
     call read a stale module global (probe: ``alpha(5)`` 19 → 13). New shared
     per-run rail ``_global_decl_reason`` (family-wide + near-dup lane).
  6. Docstring-position runs — a run starting at the enclosing function's
     docstring nulls ``__doc__`` after the lift (probe: ``alpha.__doc__``
     'Compute the A-variant.' → None). Now refused.
  7. ``_apply_line_holes`` mixed UTF-8 BYTE offsets with CHARACTER slicing —
     a multibyte character before a hole misplaced the splice (probe: emit
     failed the parse gate with 'invalid decimal literal'). TRUE REPAIR: the
     splice now works on encoded bytes, exactly like ``near_dup._segment``.

Fixes 1-6 are strictly refuse-direction; fix 7 repairs an emit that the parse
gate was masking as a refusal. Deterministic throughout.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from app.engine.dedup import DuplicateBlock, find_duplicates
from app.engine.near_dup import NearDuplicateGroup, find_near_duplicates
from app.execution._dedup_helpers import (
    _global_decl_reason,
    _multiline_string_reason,
    _overlap_blocker,
)
from app.execution.cross_file_rename import RenamePlan
from app.execution.dedup_extract import plan_dedup_extract
from app.execution.dedup_total_return import plan_dedup_total_return
from app.execution.near_dup_extract import (
    _apply_line_holes,
    _docstring_span_blocker,
    _pattern_node_ids,
    plan_near_dup_extract,
)
from app.execution.near_dup_total_return import plan_near_dup_total_return


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _block(occurrences: list[str], lines: int) -> DuplicateBlock:
    return DuplicateBlock(fingerprint="x", lines=lines, occurrences=occurrences)


def _assert_blocked(plan, *needles: str) -> None:
    """The refuse-direction contract: a blocker carrying every ``needle``,
    and NO rewrite output at all."""
    assert not plan.ok, f"expected a blocked plan, got new={plan.new_contents}"
    assert any(all(n in b for n in needles) for b in plan.blockers), (
        f"expected a blocker containing {needles!r}, got {plan.blockers}")
    assert not plan.new_contents


def _group_at(groups: list[NearDuplicateGroup], *locs: str) -> NearDuplicateGroup:
    """The group whose (sorted) occurrences are exactly ``locs``."""
    want = sorted(locs)
    for g in groups:
        if list(g.occurrences) == want:
            return g
    raise AssertionError(
        f"no group at {want}; got {[g.occurrences for g in groups]}")


def _exec_module(source: str) -> dict:
    ns: dict = {}
    exec(compile(source, "<mod>", "exec"), ns)  # noqa: S102 - controlled test src
    return ns


# ══════════════════════════════════════════════════════════════════════════
# Fix 1 — overlapping occurrence spans (P0: silent splice corruption).
# ══════════════════════════════════════════════════════════════════════════

_OVERLAP_NEAR = (
    "def f(x):\n"
    "    x = x + 1\n"
    "    x = x + 1\n"
    "    x = x + 1\n"
    "    x = x + 1\n"
    "    x = x + 1\n"
    "    x = x + 2\n"
    "    return x\n"
)


def test_overlapping_near_dup_occurrences_block(tmp_path):
    # The verified P0 repro: the periodic body self-overlaps — windows at
    # lines 2 (span 2-6) and 3 (span 3-7) share lines 3-6. The old planner
    # spliced bottom-up, ate `x = x + 2` AND `return x`, and emitted a module
    # that parsed with blockers == [] (f(0): 7 -> None). Now: refusal.
    _write(tmp_path, "mod.py", _OVERLAP_NEAR)
    groups = find_near_duplicates(tmp_path, min_statements=5)
    plan = plan_near_dup_extract(tmp_path, _group_at(groups, "mod.py:2",
                                                     "mod.py:3"))
    _assert_blocked(plan, "occurrences at lines 2 and 3 overlap",
                    "cannot be rewritten independently")


_OVERLAP_EXACT = (
    "def f(x):\n"
    "    x = x + 1\n"
    "    x = x + 1\n"
    "    x = x + 1\n"
    "    x = x + 1\n"
    "    x = x + 1\n"
    "    x = x + 1\n"
    "    return x\n"
)


def test_overlapping_exact_dup_occurrences_block(tmp_path):
    # The exact-dup twin: six byte-identical statements, windows at lines 2
    # (span 2-4) and 4 (span 4-6) overlap at line 4. Identity passes (the
    # runs ARE identical) — only the new overlap rail refuses.
    _write(tmp_path, "m.py", _OVERLAP_EXACT)
    plan = plan_dedup_extract(tmp_path, _block(["m.py:2", "m.py:4"], 3))
    _assert_blocked(plan, "occurrences at lines 2 and 4 overlap",
                    "cannot be rewritten independently")


def test_overlap_negative_disjoint_same_file_copies_land(tmp_path):
    # Negative control: the SAME file, spans 2-4 and 5-7 — disjoint — still
    # lands, and the rewrite is exec-equivalent (f(0) == 6 on both sides).
    _write(tmp_path, "m.py", _OVERLAP_EXACT)
    plan = plan_dedup_extract(tmp_path, _block(["m.py:2", "m.py:5"], 3))
    assert plan.ok, f"blockers={plan.blockers}"
    new = plan.new_contents["m.py"]
    assert _exec_module(new)["f"](0) == _exec_module(_OVERLAP_EXACT)["f"](0) == 6


def test_overlap_blocker_empty_resolved_is_none():
    # Edge/empty path: no occurrences -> nothing can overlap.
    assert _overlap_blocker([]) is None


def test_overlap_blocker_touching_spans_fire_exactly_at_boundary():
    # b.span_lo == a.span_hi is an overlap (they share a line); one line of
    # daylight (span_lo == span_hi + 1) is not.
    a = SimpleNamespace(rel="m.py", span_lo=2, span_hi=4)
    b = SimpleNamespace(rel="m.py", span_lo=4, span_hi=6)
    assert "overlap" in _overlap_blocker([a, b])
    c = SimpleNamespace(rel="m.py", span_lo=5, span_hi=7)
    assert _overlap_blocker([a, c]) is None
    # Different files never overlap.
    d = SimpleNamespace(rel="n.py", span_lo=2, span_hi=4)
    assert _overlap_blocker([a, d]) is None


# ══════════════════════════════════════════════════════════════════════════
# Fix 2 — multi-line BYTES literals escaped the multi-line-string rail (P1).
# ══════════════════════════════════════════════════════════════════════════

_BYTES_MULTILINE = '''\
class Codec:
    def encode_alpha(self):
        payload = b"""HDR1
        row-a
        row-b
"""
        size = len(payload)
        return size

    def encode_beta(self):
        payload = b"""HDR1
        row-a
        row-b
"""
        size = len(payload)
        return size
'''

_BYTES_SINGLE_LINE = '''\
class Codec:
    def encode_alpha(self):
        payload = b"HDR1"
        size = len(payload)
        return size

    def encode_beta(self):
        payload = b"HDR1"
        size = len(payload)
        return size
'''


def test_multiline_bytes_extract_blocks(tmp_path):
    # The verified P1 repro: the b"""…""" continuation lines were dedented
    # 8 -> 4 with four spaces injected before the closing quotes — corrupted
    # content that still parsed, with blockers == []. Now: the (unchanged)
    # multi-line-string blocker fires for bytes too.
    _write(tmp_path, "m.py", _BYTES_MULTILINE)
    blocks = find_duplicates(tmp_path, min_statements=3, min_occurrences=2)
    assert blocks, "the exact-dup detector must group the twin methods"
    plan = plan_dedup_extract(tmp_path, blocks[0])
    _assert_blocked(plan, "multi-line string constant",
                    "rewrite the string's contents")


def test_multiline_bytes_total_return_blocks(tmp_path):
    # The run always returns, so the total-return sibling admits it — the
    # shared rail must refuse there too (one rail, family-wide).
    _write(tmp_path, "m.py", _BYTES_MULTILINE)
    plan = plan_dedup_total_return(tmp_path, _block(["m.py:3", "m.py:11"], 3))
    _assert_blocked(plan, "multi-line string constant")


def test_multiline_bytes_negative_single_line_lands(tmp_path):
    # Negative control: a SINGLE-line bytes literal has no continuation lines
    # to corrupt — still lands, literal intact, exec-equivalent.
    _write(tmp_path, "m.py", _BYTES_SINGLE_LINE)
    blocks = find_duplicates(tmp_path, min_statements=3, min_occurrences=2)
    plan = plan_dedup_extract(tmp_path, blocks[0])
    assert plan.ok, f"blockers={plan.blockers}"
    new = plan.new_contents["m.py"]
    assert 'b"HDR1"' in new
    assert _exec_module(new)["Codec"]().encode_alpha() == 4


def test_multiline_string_reason_covers_bytes():
    # Unit rows: multi-line bytes trips the rail; single-line bytes does not.
    fn = ast.parse('def f():\n    p = b"""a\nb"""\n').body[0]
    assert _multiline_string_reason(fn.body) is not None
    fn2 = ast.parse('def f():\n    p = b"ab"\n').body[0]
    assert _multiline_string_reason(fn2.body) is None


# ══════════════════════════════════════════════════════════════════════════
# Fix 3 — stale-group structural drift (P1: silent rewire of the unedited copy).
# ══════════════════════════════════════════════════════════════════════════

_STALE_A = (
    "def f1(x):\n"
    "    a = x + 1\n"
    "    b = a - 3\n"
    "    c = b + x\n"
    "    d = c + 7\n"
    "    e = d + a\n"
    "    return e\n"
    "\n"
    "\n"
    "def f2(x):\n"
    "    a = x + 1\n"
    "    b = a - 3\n"
    "    c = b + x\n"
    "    d = c + 8\n"
    "    e = d + a\n"
    "    return e\n"
)

# Operator-only drift in f2: `e = d + a` -> `e = d * a`. The value-leaf paths
# and segments are IDENTICAL (the leaf walk never visits operator nodes), so
# every pre-fix plan gate passed and f1 was silently rewired (f1(5): 21 -> 90).
_STALE_B = _STALE_A.replace("d = c + 8\n    e = d + a",
                            "d = c + 8\n    e = d * a")


def test_stale_group_operator_drift_blocks(tmp_path):
    _write(tmp_path, "m.py", _STALE_A)
    groups = find_near_duplicates(tmp_path, min_statements=5)
    stale = _group_at(groups, "m.py:2", "m.py:11")
    # The file drifts AFTER the group was built (the staleness window the
    # objective-compiler greedy pass / a concurrent edit can hit).
    _write(tmp_path, "m.py", _STALE_B)
    plan = plan_near_dup_extract(tmp_path, stale)
    _assert_blocked(plan, "no longer share one structural template",
                    "structural drift")


def test_stale_negative_unchanged_replay_lands_identically(tmp_path):
    # Negative control: replaying a group against the UNCHANGED tree still
    # lands, byte-identically across replays, and exec-equivalent.
    _write(tmp_path, "m.py", _STALE_A)
    groups = find_near_duplicates(tmp_path, min_statements=5)
    group = _group_at(groups, "m.py:2", "m.py:11")
    first = plan_near_dup_extract(tmp_path, group)
    second = plan_near_dup_extract(tmp_path, group)
    assert first.ok, f"blockers={first.blockers}"
    assert first.new_contents == second.new_contents
    old_ns = _exec_module(_STALE_A)
    new_ns = _exec_module(first.new_contents["m.py"])
    assert (new_ns["f1"](5), new_ns["f2"](5)) == \
        (old_ns["f1"](5), old_ns["f2"](5)) == (21, 22)


# ══════════════════════════════════════════════════════════════════════════
# Fix 4 — match-PATTERN constant holes (P0: `case p0:` is a capture pattern).
# ══════════════════════════════════════════════════════════════════════════

_MATCH_PATTERN_HOLE = (
    "def alpha(x):\n"
    "    a = x + 1\n"
    "    b = a * 2\n"
    "    r = 0\n"
    "    match x:\n"
    "        case 0:\n"
    "            r = a\n"
    "        case 100:\n"
    "            r = b\n"
    "    return r\n"
    "\n"
    "\n"
    "def beta(x):\n"
    "    a = x + 1\n"
    "    b = a * 2\n"
    "    r = 0\n"
    "    match x:\n"
    "        case 0:\n"
    "            r = a\n"
    "        case 200:\n"
    "            r = b\n"
    "    return r\n"
)


def test_match_pattern_constant_hole_blocks(tmp_path):
    # The verified P0 repro: `case 100:` vs `case 200:` grouped (a MatchValue
    # constant IS a wildcarded leaf) and the splice emitted `case p0:` — a
    # CAPTURE pattern that always matches and binds p0 (alpha(7): 0 -> 16,
    # beta(100): 0 -> 202). Every other gate passed. Now: refusal.
    _write(tmp_path, "mod.py", _MATCH_PATTERN_HOLE)
    groups = find_near_duplicates(tmp_path, min_statements=5)
    plan = plan_near_dup_extract(tmp_path, _group_at(groups, "mod.py:2",
                                                     "mod.py:14"))
    _assert_blocked(plan, "inside a `match` pattern",
                    "would become a capture pattern")


_MATCH_BODY_HOLE = (
    "def alpha(x):\n"
    "    a = x + 1\n"
    "    r = 0\n"
    "    match x:\n"
    "        case 0:\n"
    "            r = a + 10\n"
    "    return r\n"
    "\n"
    "\n"
    "def beta(x):\n"
    "    a = x + 1\n"
    "    r = 0\n"
    "    match x:\n"
    "        case 0:\n"
    "            r = a + 20\n"
    "    return r\n"
)


def test_match_negative_case_body_hole_lands(tmp_path):
    # Negative control: the differing constant sits in the case BODY —
    # ordinary expression position inside a match statement — so the rail
    # must not fire; the pattern (`case 0:`) survives verbatim.
    _write(tmp_path, "mod.py", _MATCH_BODY_HOLE)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    plan = plan_near_dup_extract(tmp_path, _group_at(groups, "mod.py:2",
                                                     "mod.py:11"))
    assert plan.ok, f"blockers={plan.blockers}"
    new = plan.new_contents["mod.py"]
    assert "case 0:" in new and "case p0" not in new
    old_ns, new_ns = _exec_module(_MATCH_BODY_HOLE), _exec_module(new)
    for arg in (0, 5):
        assert (new_ns["alpha"](arg), new_ns["beta"](arg)) == \
            (old_ns["alpha"](arg), old_ns["beta"](arg))


def test_pattern_node_ids_edge_paths():
    # Empty run -> empty set; a match statement contributes exactly its
    # pattern subtree (the case-body constant is NOT collected).
    assert _pattern_node_ids([]) == set()
    stmt = ast.parse("match x:\n    case 100:\n        r = 5\n").body[0]
    ids = _pattern_node_ids([stmt])
    pat_const = stmt.cases[0].pattern.value
    body_const = stmt.cases[0].body[0].value
    assert id(pat_const) in ids
    assert id(body_const) not in ids


# ══════════════════════════════════════════════════════════════════════════
# Fix 5 — global/nonlocal-declared names bound or read by the run (P0/P1).
# ══════════════════════════════════════════════════════════════════════════

_GLOBAL_STORE_NEAR = (
    "G = 0\n"
    "\n"
    "\n"
    "def probe():\n"
    "    return G\n"
    "\n"
    "\n"
    "def alpha(x):\n"
    "    global G\n"
    "    G = x + 1\n"
    "    r = probe() + 10\n"
    "    s = r + 1\n"
    "    t = s + 2\n"
    "    return t\n"
    "\n"
    "\n"
    "def beta(x):\n"
    "    global G\n"
    "    G = x + 1\n"
    "    r = probe() + 20\n"
    "    s = r + 1\n"
    "    t = s + 2\n"
    "    return t\n"
)


def test_global_declared_store_near_dup_blocks(tmp_path):
    # The verified repro: the run only STORES G (never loads it), so the old
    # live-in/loads-based reasoning saw nothing — yet in the helper `G = x+1`
    # becomes a helper-LOCAL bind and probe() reads the stale module global
    # (alpha(5): 19 -> 13). Now: refusal.
    _write(tmp_path, "mod.py", _GLOBAL_STORE_NEAR)
    groups = find_near_duplicates(tmp_path, min_statements=5)
    plan = plan_near_dup_extract(tmp_path, _group_at(groups, "mod.py:10",
                                                     "mod.py:19"))
    _assert_blocked(plan, "declares `G` global/nonlocal",
                    "binds or reads it")


_GLOBAL_STORE_EXACT = _GLOBAL_STORE_NEAR.replace("probe() + 20", "probe() + 10")


def test_global_declared_store_exact_dup_blocks(tmp_path):
    # The byte-identical twin through the exact lane: the shared rail must
    # refuse family-wide, not just for the parameterized lane.
    _write(tmp_path, "m.py", _GLOBAL_STORE_EXACT)
    plan = plan_dedup_extract(tmp_path, _block(["m.py:10", "m.py:19"], 5))
    _assert_blocked(plan, "declares `G` global/nonlocal")


_GLOBAL_UNTOUCHED = (
    "G = 0\n"
    "\n"
    "\n"
    "def alpha(x):\n"
    "    global G\n"
    "    G = 1\n"
    "    r = x + 10\n"
    "    s = r + 1\n"
    "    t = s + 2\n"
    "    return t\n"
    "\n"
    "\n"
    "def beta(x):\n"
    "    global G\n"
    "    G = 1\n"
    "    r = x + 20\n"
    "    s = r + 1\n"
    "    t = s + 2\n"
    "    return t\n"
)


def test_global_negative_run_not_touching_declared_name_lands(tmp_path):
    # Negative control: the enclosing functions DO declare `global G`, but the
    # extracted run (r/s/t/return) neither binds nor reads G — still lands.
    _write(tmp_path, "mod.py", _GLOBAL_UNTOUCHED)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    plan = plan_near_dup_extract(tmp_path, _group_at(groups, "mod.py:7",
                                                     "mod.py:16"))
    assert plan.ok, f"blockers={plan.blockers}"
    old_ns = _exec_module(_GLOBAL_UNTOUCHED)
    new_ns = _exec_module(plan.new_contents["mod.py"])
    assert (new_ns["alpha"](1), new_ns["beta"](1)) == \
        (old_ns["alpha"](1), old_ns["beta"](1)) == (14, 24)


def test_global_store_run_in_same_fixture_blocks(tmp_path):
    # The sibling window one line up DOES bind the declared name (`G = 1` is
    # in the run) — the rail refuses it while the window below still lands.
    _write(tmp_path, "mod.py", _GLOBAL_UNTOUCHED)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    plan = plan_near_dup_extract(tmp_path, _group_at(groups, "mod.py:6",
                                                     "mod.py:15"))
    _assert_blocked(plan, "declares `G` global/nonlocal")


def test_global_decl_reason_none_without_declarations():
    # Edge path: no Global/Nonlocal anywhere -> the rail stays silent.
    fn = ast.parse("def f(x):\n    y = x + 1\n    return y\n").body[0]
    assert _global_decl_reason(fn, fn.body) is None


# ══════════════════════════════════════════════════════════════════════════
# Fix 6 — docstring-position runs null the function's __doc__ (P2).
# ══════════════════════════════════════════════════════════════════════════

_DOC_HOLE = (
    "def alpha(x):\n"
    '    """Compute the A-variant."""\n'
    "    a = x + 1\n"
    "    b = a * 2\n"
    "    c = b + 3\n"
    "    return c\n"
    "\n"
    "\n"
    "def beta(x):\n"
    '    """Compute the B-variant."""\n'
    "    a = x + 1\n"
    "    b = a * 2\n"
    "    c = b + 3\n"
    "    return c\n"
)


def test_docstring_position_run_blocks(tmp_path):
    # The verified repro: the differing DOCSTRINGS became the hole, the lift
    # replaced alpha's body with a call, and alpha.__doc__ silently went
    # 'Compute the A-variant.' -> None (help/sphinx/doctest all observe it).
    _write(tmp_path, "mod.py", _DOC_HOLE)
    groups = find_near_duplicates(tmp_path, min_statements=5)
    plan = plan_near_dup_extract(tmp_path, _group_at(groups, "mod.py:2",
                                                     "mod.py:10"))
    _assert_blocked(plan, "starts at the enclosing function's docstring",
                    "null the function's `__doc__`")


_DOC_SAME = (
    "def alpha(x):\n"
    '    """Same doc."""\n'
    "    a = x + 1\n"
    "    b = a * 2\n"
    "    c = b + 10\n"
    "    return c\n"
    "\n"
    "\n"
    "def beta(x):\n"
    '    """Same doc."""\n'
    "    a = x + 1\n"
    "    b = a * 2\n"
    "    c = b + 20\n"
    "    return c\n"
)


def test_docstring_identical_but_lifted_still_blocks(tmp_path):
    # IDENTICAL docstrings are no safer: lifting the docstring statement out
    # of the body nulls __doc__ on BOTH functions regardless of the hole.
    _write(tmp_path, "mod.py", _DOC_SAME)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    plan = plan_near_dup_extract(tmp_path, _group_at(groups, "mod.py:2",
                                                     "mod.py:10"))
    _assert_blocked(plan, "null the function's `__doc__`")


def test_docstring_negative_run_below_docstring_lands(tmp_path):
    # Negative control: the sibling window starting BELOW the docstring lands
    # and both docstrings survive the rewrite.
    _write(tmp_path, "mod.py", _DOC_SAME)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    plan = plan_near_dup_extract(tmp_path, _group_at(groups, "mod.py:3",
                                                     "mod.py:11"))
    assert plan.ok, f"blockers={plan.blockers}"
    new_ns = _exec_module(plan.new_contents["mod.py"])
    assert new_ns["alpha"].__doc__ == new_ns["beta"].__doc__ == "Same doc."
    old_ns = _exec_module(_DOC_SAME)
    assert (new_ns["alpha"](1), new_ns["beta"](1)) == \
        (old_ns["alpha"](1), old_ns["beta"](1)) == (14, 24)


def test_docstring_span_blocker_empty_resolved_is_none():
    # Edge/empty path.
    assert _docstring_span_blocker([]) is None


# ══════════════════════════════════════════════════════════════════════════
# Fix 7 — _apply_line_holes byte/char mixing (P3: TRUE REPAIR, not a refusal).
# ══════════════════════════════════════════════════════════════════════════

_UTF8_HOLE = (
    "def alpha(x):\n"
    "    a = x + 1\n"
    '    d = ("é", 10)\n'
    "    b = a + d[1]\n"
    "    c = b * 2\n"
    "    return c\n"
    "\n"
    "\n"
    "def beta(x):\n"
    "    a = x + 1\n"
    '    d = ("é", 20)\n'
    "    b = a + d[1]\n"
    "    c = b * 2\n"
    "    return c\n"
)


def test_multibyte_char_before_hole_lands_correctly(tmp_path):
    # The verified repro: AST columns are UTF-8 BYTE offsets, the splice
    # sliced CHARACTERS, so the 'é' shifted the hole one column right and the
    # emit died at the parse gate ('invalid decimal literal'). Repaired: the
    # splice works on encoded bytes and the hole lands exactly on the literal.
    _write(tmp_path, "mod.py", _UTF8_HOLE)
    groups = find_near_duplicates(tmp_path, min_statements=5)
    plan = plan_near_dup_extract(tmp_path, _group_at(groups, "mod.py:2",
                                                     "mod.py:10"))
    assert plan.ok, f"blockers={plan.blockers}"
    new = plan.new_contents["mod.py"]
    assert 'd = ("é", p0)' in new
    old_ns, new_ns = _exec_module(_UTF8_HOLE), _exec_module(new)
    for arg in (0, 3):
        assert (new_ns["alpha"](arg), new_ns["beta"](arg)) == \
            (old_ns["alpha"](arg), old_ns["beta"](arg))


def test_apply_line_holes_multibyte_unit_splice():
    # '    d = ("é", 10)': the é is TWO bytes, so the constant '10' spans
    # BYTE columns 15..17 (character columns 14..16). The byte splice must
    # replace exactly the literal.
    line = '    d = ("é", 10)\n'
    plan = RenamePlan(old="x", new="_s")
    assert _apply_line_holes(line, [(15, 17, "p0")], plan) == '    d = ("é", p0)\n'
    assert not plan.blockers


def test_apply_line_holes_ascii_behaviour_unchanged():
    # Negative control: pure-ASCII lines splice exactly as before.
    line = "    d = c + 10\n"
    plan = RenamePlan(old="x", new="_s")
    assert _apply_line_holes(line, [(12, 14, "p0")], plan) == "    d = c + p0\n"


def test_apply_line_holes_span_splitting_multibyte_char_blocks():
    # Edge path: a span that starts INSIDE the é's two bytes cannot decode —
    # refuse with a blocker instead of raising.
    line = '    d = ("é", 10)\n'
    plan = RenamePlan(old="x", new="_s")
    assert _apply_line_holes(line, [(11, 17, "p0")], plan) is None
    assert any("splits a multi-byte character" in b for b in plan.blockers)


# ══════════════════════════════════════════════════════════════════════════
# Fix 8 — multi-line str/bytes constants in the NEAR-DUP lane (P1: the family
# rail existed but was not wired here; `_reindent` rewrote their continuation
# lines exactly like the exact-lane bytes repro of Fix 2).
# ══════════════════════════════════════════════════════════════════════════

_MLSTR_NEAR = (
    "def alpha(x):\n"
    '    hdr = """H1\n'
    "        row-a\n"
    '"""\n'
    "    a = x + 7\n"
    "    b = a * 2\n"
    "    return (hdr, b)\n"
    "\n"
    "\n"
    "def beta(x):\n"
    '    hdr = """H1\n'
    "        row-a\n"
    '"""\n'
    "    a = x + 8\n"
    "    b = a * 2\n"
    "    return (hdr, b)\n"
)


def test_multiline_str_near_dup_blocks(tmp_path):
    # The verified repro: the SHARED (non-differing) multi-line str rode into
    # the helper and `_reindent` injected four spaces before the closing
    # quotes (literal changed, blockers == []). Now: the family rail refuses.
    _write(tmp_path, "mod.py", _MLSTR_NEAR)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    plan = plan_near_dup_extract(tmp_path, _group_at(groups, "mod.py:2",
                                                     "mod.py:11"))
    _assert_blocked(plan, "multi-line string constant",
                    "rewrite the string's contents")


_MLSTR_HOLE_NEAR = (
    "def alpha(x):\n"
    '    hdr = """red\n'
    'tail"""\n'
    "    a = x + 1\n"
    "    b = a * 2\n"
    "    return (hdr, b)\n"
    "\n"
    "\n"
    "def beta(x):\n"
    '    hdr = """blue\n'
    'tail"""\n'
    "    a = x + 1\n"
    "    b = a * 2\n"
    "    return (hdr, b)\n"
)


def test_multiline_str_hole_near_dup_blocks(tmp_path):
    # The DIFFERING leaf itself being a multi-line str is no safer: the splice
    # would emit a broken single-line call argument. Same rail, same refusal.
    _write(tmp_path, "mod.py", _MLSTR_HOLE_NEAR)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    plan = plan_near_dup_extract(tmp_path, _group_at(groups, "mod.py:2",
                                                     "mod.py:10"))
    _assert_blocked(plan, "multi-line string constant")


_SLSTR_NEAR = (
    "def alpha(x):\n"
    '    hdr = "H1"\n'
    "    a = x + 7\n"
    "    b = a * 2\n"
    "    return (hdr, b)\n"
    "\n"
    "\n"
    "def beta(x):\n"
    '    hdr = "H1"\n'
    "    a = x + 8\n"
    "    b = a * 2\n"
    "    return (hdr, b)\n"
)


def test_single_line_str_near_dup_negative_lands(tmp_path):
    # Negative control: the rail keys on MULTI-LINE spans, not on strings —
    # the single-line twin lands, exec-equivalent, string intact.
    _write(tmp_path, "mod.py", _SLSTR_NEAR)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    plan = plan_near_dup_extract(tmp_path, _group_at(groups, "mod.py:2",
                                                     "mod.py:9"))
    assert plan.ok, f"blockers={plan.blockers}"
    old_ns = _exec_module(_SLSTR_NEAR)
    new_ns = _exec_module(plan.new_contents["mod.py"])
    for arg in (0, 3):
        assert (new_ns["alpha"](arg), new_ns["beta"](arg)) == \
            (old_ns["alpha"](arg), old_ns["beta"](arg))
    assert new_ns["alpha"](0)[0] == "H1"


# ══════════════════════════════════════════════════════════════════════════
# W99a — the shipped rails, INHERITED row: each also refuses on the near-dup
# TOTAL-RETURN lane (``plan_near_dup_total_return``), now writable since the
# lander exists. Same rails, same shared pipeline, an always-returning shape.
# ══════════════════════════════════════════════════════════════════════════

_OVERLAP_TOTAL_RETURN = '''\
def f(x):
    return 1
    return 1
    return 1
    return 1
    return 1
    return 2
'''


def test_overlap_total_return_lane_blocks(tmp_path):
    _write(tmp_path, "mod.py", _OVERLAP_TOTAL_RETURN)
    groups = find_near_duplicates(tmp_path, min_statements=5)
    group = _group_at(groups, "mod.py:2", "mod.py:3")
    plan = plan_near_dup_total_return(tmp_path, group)
    _assert_blocked(plan, "occurrences at lines 2 and 3 overlap",
                    "cannot be rewritten independently")


_GLOBAL_DECL_TOTAL_RETURN = '''\
G = 0


def probe():
    return G


def alpha(x, flag):
    global G
    if flag:
        return -1
    G = x + 1
    r = probe() + 10
    return r


def beta(x, flag):
    global G
    if flag:
        return -1
    G = x + 1
    r = probe() + 20
    return r
'''


def test_global_decl_total_return_lane_blocks(tmp_path):
    _write(tmp_path, "mod.py", _GLOBAL_DECL_TOTAL_RETURN)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    group = _group_at(groups, "mod.py:10", "mod.py:19")
    plan = plan_near_dup_total_return(tmp_path, group)
    _assert_blocked(plan, "declares `G` global/nonlocal", "binds or reads it")


_MULTILINE_BYTES_TOTAL_RETURN = '''\
def alpha(x, flag):
    if flag:
        return -1
    hdr = b"""H1
        row-a
"""
    a = x + 7
    return (hdr, a)


def beta(x, flag):
    if flag:
        return -1
    hdr = b"""H1
        row-a
"""
    a = x + 8
    return (hdr, a)
'''


def test_multiline_bytes_total_return_lane_blocks(tmp_path):
    _write(tmp_path, "mod.py", _MULTILINE_BYTES_TOTAL_RETURN)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    group = _group_at(groups, "mod.py:2", "mod.py:12")
    plan = plan_near_dup_total_return(tmp_path, group)
    _assert_blocked(plan, "multi-line string constant",
                    "rewrite the string's contents")


_DRIFT_TOTAL_RETURN_BASE = (
    "def f1(x, flag):\n"
    "    if flag:\n"
    "        return -1\n"
    "    a = x + 1\n"
    "    b = a - 3\n"
    "    d = b + 7\n"
    "    return d\n"
    "\n\n"
    "def f2(x, flag):\n"
    "    if flag:\n"
    "        return -1\n"
    "    a = x + 1\n"
    "    b = a - 3\n"
    "    d = b + 8\n"
    "    return d\n"
)
# Operator-only drift in f2: `d = b + 8` -> `d = b * 8` (value-leaf paths and
# segments stay identical; only the re-derived structural TEMPLATE catches it).
_DRIFT_TOTAL_RETURN_STALE = _DRIFT_TOTAL_RETURN_BASE.replace(
    "d = b + 8\n    return d", "d = b * 8\n    return d")


def test_template_drift_total_return_lane_blocks(tmp_path):
    _write(tmp_path, "m.py", _DRIFT_TOTAL_RETURN_BASE)
    groups = find_near_duplicates(tmp_path, min_statements=5)
    group = _group_at(groups, "m.py:2", "m.py:11")
    _write(tmp_path, "m.py", _DRIFT_TOTAL_RETURN_STALE)
    plan = plan_near_dup_total_return(tmp_path, group)
    _assert_blocked(plan, "no longer share one structural template",
                    "structural drift")


_MATCH_PATTERN_TOTAL_RETURN = '''\
def alpha(x, flag):
    if flag:
        return -1
    a = x + 1
    r = 0
    match x:
        case 0:
            r = a
        case 100:
            r = a + 1
    return r


def beta(x, flag):
    if flag:
        return -1
    a = x + 1
    r = 0
    match x:
        case 0:
            r = a
        case 200:
            r = a + 1
    return r
'''


def test_match_pattern_total_return_lane_blocks(tmp_path):
    _write(tmp_path, "mod.py", _MATCH_PATTERN_TOTAL_RETURN)
    groups = find_near_duplicates(tmp_path, min_statements=5)
    group = _group_at(groups, "mod.py:2", "mod.py:15")
    plan = plan_near_dup_total_return(tmp_path, group)
    _assert_blocked(plan, "inside a `match` pattern",
                    "would become a capture pattern")


_DOCSTRING_TOTAL_RETURN = '''\
def alpha(n, flag):
    """Compute A."""
    if flag:
        return -1
    a = n + 1
    b = a * 2
    return b


def beta(n, flag):
    """Compute B."""
    if flag:
        return -1
    a = n + 1
    b = a * 2
    return b
'''


def test_docstring_total_return_lane_blocks(tmp_path):
    _write(tmp_path, "mod.py", _DOCSTRING_TOTAL_RETURN)
    groups = find_near_duplicates(tmp_path, min_statements=5)
    group = _group_at(groups, "mod.py:2", "mod.py:11")
    plan = plan_near_dup_total_return(tmp_path, group)
    _assert_blocked(plan, "starts at the enclosing function's docstring",
                    "null the function's `__doc__`")
