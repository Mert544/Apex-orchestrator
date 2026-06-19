"""Deep mutation-hardening for the SyntaxError-vs-logic-bug correctness gate.

A file Apex cannot *parse* (a truncated ``def f(`` or newer-grammar syntax on an
older runtime) is reported by the detector as a high-severity ``"bug"`` with a
``"SyntaxError: ..."`` message and NO fix_kind — but it is out of scope, not a
likely-crash logic bug. The deep-finding fix excludes exactly that shape from the
Correctness "likely-crash" count (and its remediation) while STILL counting a real
high-severity, no-fix logic bug.

The pin is the four-conjunct predicate in ``_is_unparseable_bug``:

    category == "bug"  AND  severity == "high"
    AND  not fix_kind  AND  message.startswith("SyntaxError:")

Flipping any single conjunct must change the verdict, so each is asserted both
ways. ``_count_correctness_bugs`` then proves the exclusion only removes the
SyntaxError marker, never the real bug.

Determinism: all assertions are exact booleans / integer counts; no time / order.
"""
from __future__ import annotations

from app.engine.detectors import Issue, detect
from app.engine.health_score import _count_correctness_bugs, _is_unparseable_bug


def _bug(message: str, *, category: str = "bug", severity: str = "high",
         fix_kind: str = "") -> Issue:
    return Issue(line=1, category=category, severity=severity,
                 message=message, fix_kind=fix_kind)


# ---------------------------------------------------------------------------
# _is_unparseable_bug — the full four-conjunct predicate, one flipped conjunct
# per assertion so a dropped/negated term is killed.
# ---------------------------------------------------------------------------
def test_pure_syntaxerror_marker_is_unparseable():
    assert _is_unparseable_bug(_bug("SyntaxError: unexpected EOF")) is True


def test_wrong_category_is_not_unparseable():
    # category must be exactly "bug"; a security SyntaxError-shaped finding is not.
    assert _is_unparseable_bug(_bug("SyntaxError: x", category="security")) is False
    assert _is_unparseable_bug(_bug("SyntaxError: x", category="style")) is False


def test_wrong_severity_is_not_unparseable():
    # severity must be exactly "high".
    assert _is_unparseable_bug(_bug("SyntaxError: x", severity="medium")) is False
    assert _is_unparseable_bug(_bug("SyntaxError: x", severity="low")) is False


def test_with_fix_kind_is_not_unparseable():
    # A SyntaxError marker carries NO fix_kind; any fix_kind disqualifies it.
    assert _is_unparseable_bug(_bug("SyntaxError: x", fix_kind="some-fix")) is False


def test_non_syntaxerror_message_is_not_unparseable():
    # The message MUST start with the stable "SyntaxError:" prefix.
    assert _is_unparseable_bug(_bug("Unreachable code after return")) is False
    assert _is_unparseable_bug(_bug("TypeError: bad")) is False
    # Prefix is anchored at the start, not anywhere in the message.
    assert _is_unparseable_bug(_bug("oops SyntaxError: late")) is False


def test_unparseable_predicate_handles_missing_attributes():
    # The predicate reads via getattr/str, so an object missing fields is False,
    # never a crash.
    class Bare:
        pass

    assert _is_unparseable_bug(Bare()) is False


# ---------------------------------------------------------------------------
# _count_correctness_bugs — the SyntaxError marker is EXCLUDED; a real
# high/no-fix logic bug is STILL counted.
# ---------------------------------------------------------------------------
def test_pure_syntaxerror_excluded_from_count():
    assert _count_correctness_bugs([_bug("SyntaxError: bad")]) == 0


def test_real_high_no_fix_logic_bug_is_counted():
    # A genuine high-severity logic bug with no auto-fix counts as 1.
    assert _count_correctness_bugs([_bug("Unreachable code after return")]) == 1


def test_syntaxerror_excluded_but_real_bug_kept_alongside():
    issues = [_bug("SyntaxError: unexpected EOF"),
              _bug("Frozen dataclass attribute mutation")]
    # Only the real logic bug survives the exclusion.
    assert _count_correctness_bugs(issues) == 1


def test_low_severity_bug_not_counted():
    assert _count_correctness_bugs([_bug("minor", severity="low")]) == 0


def test_bug_with_fix_kind_not_counted():
    # Auto-fixable bugs are reflected by other components, not Correctness.
    assert _count_correctness_bugs([_bug("fixable", fix_kind="raise-from")]) == 0


def test_non_bug_category_not_counted():
    assert _count_correctness_bugs([_bug("x", category="security")]) == 0


def test_two_real_bugs_counted_two():
    issues = [_bug("crash one"), _bug("crash two")]
    assert _count_correctness_bugs(issues) == 2


# ---------------------------------------------------------------------------
# Integration with the real detector: an unparseable file yields exactly the
# excluded SyntaxError marker, so it costs the Correctness bucket nothing.
# ---------------------------------------------------------------------------
def test_real_detector_syntaxerror_is_recognised_and_excluded():
    issues = detect("def f(\n")  # truncated def -> a real SyntaxError Issue
    # The detector emits exactly one high-severity SyntaxError bug, no fix_kind.
    assert len(issues) == 1
    only = issues[0]
    assert only.category == "bug"
    assert only.severity == "high"
    assert only.fix_kind == ""
    assert only.message.startswith("SyntaxError:")
    # And the grade's correctness count excludes it entirely.
    assert _is_unparseable_bug(only) is True
    assert _count_correctness_bugs(issues) == 0
