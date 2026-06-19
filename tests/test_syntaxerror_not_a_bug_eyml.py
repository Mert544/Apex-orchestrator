"""Honesty pin: an unparseable / newer-grammar file is OUT OF SCOPE, not a bug.

A red-team found Apex falsely accusing files of being "likely-crash / dead-code
bugs": a file that uses valid PEP 695 syntax (``def f[T]`` / ``type X = ...``,
3.12+) is a ``SyntaxError`` on the 3.11 runtime, and the detector emits that as a
high-severity ``category="bug"`` finding with no fix. The Correctness grade then
counted it as a likely-crash logic bug and told the user to run ``apex review`` —
a false accusation about a file with no logic bug and no offered fix. (A genuinely
truncated ``def f(`` is also just a SyntaxError; treating every unparseable file
as out-of-scope rather than a logic bug is the honest stance.)

These tests pin that:
  * a pure-SyntaxError file does NOT contribute to the Correctness
    "likely-crash / dead-code bug" count and does NOT trigger the
    ``apex review`` remediation, and
  * a REAL flagged logic bug STILL docks Correctness (no under-counting).
"""

from __future__ import annotations

from app.engine.detectors import Issue, detect
from app.engine.health_score import (
    _count_correctness_bugs,
    _is_unparseable_bug,
    grade,
)

# A file that parses only on 3.12+ (PEP 695 generic syntax). On the 3.11 runtime
# this is a SyntaxError — valid, modern code, NOT a logic bug.
_PEP695_SOURCE = "def first[T](xs: list[T]) -> T:\n    return xs[0]\n"

# The classic truncated function: a SyntaxError too, equally out of scope.
_TRUNCATED_SOURCE = "def f(\n"


# --------------------------------------------------------------------------
# detector still reports the SyntaxError marker (contract unchanged)
# --------------------------------------------------------------------------

def test_pep695_is_a_syntaxerror_finding_on_this_runtime():
    # We only get to make this claim about PEP 695 if it actually fails to parse
    # here; if a future runtime parses it, the file is in scope and the premise
    # changes. Either way it must never be a real logic bug.
    out = detect(_PEP695_SOURCE)
    if out:
        assert out[0].message.startswith("SyntaxError:")
        assert out[0].category == "bug" and out[0].severity == "high"
        assert out[0].fix_kind == ""


def test_truncated_def_is_a_syntaxerror_finding():
    out = detect(_TRUNCATED_SOURCE)
    assert out and out[0].message.startswith("SyntaxError:")


# --------------------------------------------------------------------------
# _is_unparseable_bug — recognises ONLY the SyntaxError marker
# --------------------------------------------------------------------------

def test_is_unparseable_bug_true_for_syntaxerror_marker():
    assert _is_unparseable_bug(Issue(1, "bug", "high", "SyntaxError: invalid syntax", ""))


def test_is_unparseable_bug_false_for_real_logic_bug():
    # A genuine no-fix high-severity logic bug must NOT be mistaken for unparseable.
    assert not _is_unparseable_bug(
        Issue(5, "bug", "high", "frozen dataclass field is mutated", "")
    )
    # And nothing about category/severity should false-positive either.
    assert not _is_unparseable_bug(Issue(1, "security", "high", "SyntaxError: x", ""))
    assert not _is_unparseable_bug(Issue(1, "bug", "medium", "SyntaxError: x", ""))
    assert not _is_unparseable_bug(Issue(1, "bug", "high", "SyntaxError: x", "some-fix"))


# --------------------------------------------------------------------------
# _count_correctness_bugs — excludes SyntaxError, keeps real bugs
# --------------------------------------------------------------------------

def test_count_excludes_pure_syntaxerror_file():
    # The only finding the detector can offer a truncated/newer-grammar file is
    # the SyntaxError marker — it must count as ZERO correctness bugs.
    assert _count_correctness_bugs(detect(_TRUNCATED_SOURCE)) == 0
    pep695 = detect(_PEP695_SOURCE)
    if pep695:  # SyntaxError on this runtime
        assert _count_correctness_bugs(pep695) == 0


def test_count_still_counts_a_real_logic_bug():
    issues = [
        Issue(3, "bug", "high", "return inside finally swallows exceptions", ""),
    ]
    assert _count_correctness_bugs(issues) == 1


def test_count_ignores_only_the_syntaxerror_when_mixed():
    issues = [
        Issue(1, "bug", "high", "SyntaxError: invalid syntax", ""),
        Issue(2, "bug", "high", "frozen dataclass mutation", ""),
    ]
    # Only the real bug is counted; the SyntaxError marker is dropped.
    assert _count_correctness_bugs(issues) == 1


# --------------------------------------------------------------------------
# end-to-end grade(): no false Correctness accusation, no apex-review nudge
# --------------------------------------------------------------------------

def _corr(h):
    return next(c for c in h.components if c.name == "Correctness")


def test_grade_pep695_file_does_not_dock_correctness(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "modern.py").write_text(_PEP695_SOURCE)
    (tmp_path / "tests" / "test_modern.py").write_text(
        "def test_ok():\n    assert True\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")

    h = grade(str(tmp_path))
    corr = _corr(h)
    # No likely-crash / dead-code accusation for an out-of-scope file...
    assert corr.points_lost == 0
    assert "0 likely-crash" in corr.detail
    # ...and no remediation pointing the user at `apex review` for it.
    assert not any("apex review" in f for f in h.fixes)


def test_grade_truncated_file_does_not_dock_correctness(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "broken.py").write_text(_TRUNCATED_SOURCE)
    (tmp_path / "tests" / "test_broken.py").write_text(
        "def test_ok():\n    assert True\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")

    corr = _corr(grade(str(tmp_path)))
    assert corr.points_lost == 0
    assert not corr.top_files


def test_grade_real_logic_bug_still_docks_correctness(tmp_path):
    # The guard the original feature provides must still fire: a real
    # frozen-dataclass mutation costs Correctness points and earns the nudge.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "from dataclasses import dataclass\n"
        "@dataclass(frozen=True)\nclass C:\n    x: int\n"
        "    def bump(self):\n        self.x = self.x + 1\n"
    )
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import C\ndef test_c():\n    assert C(1).x == 1\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")

    h = grade(str(tmp_path))
    corr = _corr(h)
    assert corr.points_lost > 0
    assert any("apex review" in f for f in h.fixes)
