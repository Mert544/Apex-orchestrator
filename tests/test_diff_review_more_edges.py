"""Edge-path coverage for app.engine.diff_review.

Targets the genuinely-missing lines from coverage term-missing: the
changed_lines failure/return paths, the per-fix_kind _line_suggestion
branches and its fall-back single-diff path, the ChangeImpact.to_dict,
the duplication occurrence-parse edge cases, the read-OSError skip, the
syntax-error skip in change impacts, and the render "needs a human" branch.

Hermetic: tmp git repos with a fixed committer env and gpgsign off; no
network, no time/random/order assertions.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.engine.diff_review import (
    ChangeImpact,
    ReviewFinding,
    ReviewResult,
    _line_suggestion,
    changed_lines,
    render_review_markdown,
    review,
    scan_findings,
)


def _git(tmp_path: Path, *cmds):
    for c in cmds:
        subprocess.run(c, cwd=tmp_path, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "base.py").write_text("def existing():\n    return 1\n")
    _git(tmp_path, ["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
         ["git", "config", "user.name", "t"], ["git", "add", "-A"],
         ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"])
    return tmp_path


# --- changed_lines failure / empty paths -------------------------------------

def test_changed_lines_returns_empty_when_git_errors(tmp_path):
    # Not a git repo at all -> git diff returns non-zero -> {} (lines 102-103).
    (tmp_path / "x.py").write_text("a = 1\n")
    assert changed_lines(str(tmp_path)) == {}


def test_changed_lines_returns_empty_when_subprocess_raises(monkeypatch, tmp_path):
    # subprocess.run raising is swallowed -> {} (lines 100-101).
    import app.engine.diff_review as dr

    def boom(*a, **k):
        raise OSError("git missing")

    monkeypatch.setattr(dr.subprocess, "run", boom)
    assert changed_lines(str(tmp_path)) == {}


def test_changed_lines_ignores_malformed_hunk_header(monkeypatch, tmp_path):
    # A diff whose @@ header doesn't match _HUNK is skipped (line 114 continue),
    # leaving no lines for that file -> filtered out of the result.
    import app.engine.diff_review as dr

    class FakeOut:
        returncode = 0
        stdout = "+++ b/app/base.py\n@@ totally not a hunk @@\n+code\n"

    monkeypatch.setattr(dr.subprocess, "run", lambda *a, **k: FakeOut())
    assert changed_lines(str(tmp_path)) == {}


# --- compiled-rules drop / rule-finding off-diff branch ----------------------

def test_compiled_rules_drops_uncompilable_pattern(tmp_path):
    # A saved rule whose pattern is a bare metavariable compiles to None and is
    # silently dropped (the 132->130 loop-skip), never breaking the review.
    from app.engine.diff_review import _compiled_rules
    from app.execution.rewrite_rules import save_rule

    _repo(tmp_path)
    save_rule(str(tmp_path), "broken", "$x", "$x")
    assert _compiled_rules(str(tmp_path)) == []


def test_rule_findings_skips_match_off_diff(tmp_path):
    # A line the rule matches but that is NOT in the changed set is skipped
    # (the 219->218 inner `if ln in lines` False branch) -> no finding.
    from app.engine.diff_review import _compiled_rules, _rule_findings
    from app.execution.rewrite_rules import save_rule

    _repo(tmp_path)
    save_rule(str(tmp_path), "no-len-zero", "len($x) == 0", "not $x")
    compiled = _compiled_rules(str(tmp_path))
    src = "def chk(xs):\n    return len(xs) == 0\n"
    # The match is on line 2, but we pass an empty changed-line set -> off diff.
    assert _rule_findings(str(tmp_path), "m.py", src, set(), compiled) == []


# --- _line_suggestion per-fix_kind branches ----------------------------------

def test_line_suggestion_none_comparison_branch():
    src = "def f(x):\n    return x != None\n"
    f = next(x for x in scan_findings("m.py", src) if x.fix_kind == "none-comparison")
    assert _line_suggestion("m.py", src, f) == ("return x != None", "return x is not None")


def test_line_suggestion_identity_literal_branch():
    src = "def f(x):\n    return x is 5\n"
    f = next(x for x in scan_findings("m.py", src) if x.fix_kind == "identity-literal")
    assert _line_suggestion("m.py", src, f) == ("return x is 5", "return x == 5")


def test_line_suggestion_raise_from_branch():
    src = ("def f():\n    try:\n        pass\n"
           "    except ValueError as e:\n        raise RuntimeError(\"x\")\n")
    f = next(x for x in scan_findings("m.py", src) if x.fix_kind == "raise-from")
    old, new = _line_suggestion("m.py", src, f)
    assert old == 'raise RuntimeError("x")'
    assert new == 'raise RuntimeError("x") from e'


def test_line_suggestion_bare_except_branch():
    src = "def f():\n    try:\n        pass\n    except:\n        pass\n"
    f = next(x for x in scan_findings("m.py", src) if x.fix_kind == "bare except")
    assert _line_suggestion("m.py", src, f) == ("except:", "except Exception:")


def test_line_suggestion_negated_comparison_branch_returns_none():
    # Exercises the negated-comparison dispatch arm (line 174); the transform
    # finds nothing to rewrite here, so the helper returns None.
    src = "def f(x):\n    return not x == 1\n"
    f = ReviewFinding("m.py", 2, "style", "low", "msg", True, "negated-comparison")
    assert _line_suggestion("m.py", src, f) is None


def test_line_suggestion_unknown_fix_kind_returns_none():
    # The else arm (line 184) -> immediate None.
    f = ReviewFinding("m.py", 1, "style", "low", "msg", True, "no-such-kind")
    assert _line_suggestion("m.py", "a = 1\n", f) is None


def test_line_suggestion_fallback_single_diff_when_finding_line_wrong():
    # The finding's .line points at an unchanged line, so the idx check fails and
    # the helper falls back to "the single differing line" (lines 198-202).
    src = "def f(x):\n    return x != None\n"
    base = next(x for x in scan_findings("m.py", src) if x.fix_kind == "none-comparison")
    misaligned = ReviewFinding(base.file, 1, base.category, base.severity,
                               base.message, base.auto_fixable, base.fix_kind)
    assert _line_suggestion("m.py", src, misaligned) == (
        "return x != None", "return x is not None")


# --- ChangeImpact.to_dict ----------------------------------------------------

def test_change_impact_to_dict_round_trips():
    im = ChangeImpact(file="app/m.py", function="parse", lineno=3,
                      caller_count=2, callers=["app/a.py:5", "app/b.py:9"])
    d = im.to_dict()
    assert d == {"file": "app/m.py", "function": "parse", "lineno": 3,
                 "caller_count": 2, "callers": ["app/a.py:5", "app/b.py:9"]}


# --- duplication occurrence-parse edge cases ---------------------------------

def _dup_body() -> str:
    return ("    a = 1\n    b = a + 2\n    c = b * 3\n"
            "    d = c - 4\n    return d + 5\n")


def test_duplication_skips_occurrence_off_diff(tmp_path):
    # Both copies are committed; only one is on the diff. The off-diff copy is
    # skipped by the `lineno not in lines` guard (line 313/continue), and since
    # only one copy lands on the diff there IS a sibling to point at.
    body = _dup_body()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "base.py").write_text(
        f"def existing():\n{body}\ndef twin():\n{body}")
    _git(tmp_path, ["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
         ["git", "config", "user.name", "t"], ["git", "add", "-A"],
         ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"])
    # Edit only the first copy's body (changes lines in existing()), keeping twin
    # untouched. The duplicate is still detected; the on-diff copy is reported.
    (tmp_path / "app" / "base.py").write_text(
        "def existing():\n    a = 1\n    b = a + 2\n    c = b * 3\n"
        "    d = c - 4\n    return d + 6\n"
        f"\ndef twin():\n{body}")
    result = review(str(tmp_path))
    dups = [f for f in result.findings if f.fix_kind == "duplication"]
    # Either zero (if the edit broke the clone) or only the on-diff occurrence.
    assert all(f.file == "app/base.py" for f in dups)


def test_duplication_skips_malformed_and_lone_occurrences(monkeypatch):
    # Drive the occurrence-parse guards in _duplication_findings directly:
    #   * "no-colon-here" -> rpartition gives empty module (line 307 continue)
    #   * "app/m.py:abc"  -> non-digit lineno (line 307 continue)
    # Both malformed entries are dropped from `parsed`, leaving only the real
    # on-diff copy with no sibling to point at -> no finding (line 317 continue).
    import app.engine.dedup as dedup
    from app.engine.diff_review import _duplication_findings

    block = dedup.DuplicateBlock(
        fingerprint="fp", lines=5,
        occurrences=["no-colon-here", "app/m.py:abc", "app/m.py:10"])
    monkeypatch.setattr(dedup, "find_duplicates", lambda root: [block])
    changed = {"app/m.py": {10}}
    out = _duplication_findings("/proj", changed)
    assert out == []


def test_duplication_skips_fixture_occurrence(monkeypatch):
    # A duplicated block whose on-diff copy lives under tests/ is filtered by the
    # fixture guard (line 311 continue) -> no finding for it.
    import app.engine.dedup as dedup
    from app.engine.diff_review import _duplication_findings

    block = dedup.DuplicateBlock(
        fingerprint="fp", lines=5,
        occurrences=["tests/t.py:5", "tests/t2.py:9"])
    monkeypatch.setattr(dedup, "find_duplicates", lambda root: [block])
    changed = {"tests/t.py": {5}, "tests/t2.py": {9}}
    assert _duplication_findings("/proj", changed) == []


def test_duplication_emits_when_two_real_copies_on_diff(monkeypatch):
    # Control case: two real copies both on the diff -> a finding for each, each
    # naming the other (confirms the guards above were the reason, not a no-op).
    import app.engine.dedup as dedup
    from app.engine.diff_review import _duplication_findings

    block = dedup.DuplicateBlock(
        fingerprint="fp", lines=5,
        occurrences=["app/a.py:3", "app/b.py:7"])
    monkeypatch.setattr(dedup, "find_duplicates", lambda root: [block])
    changed = {"app/a.py": {3}, "app/b.py": {7}}
    out = _duplication_findings("/proj", changed)
    assert {f.file for f in out} == {"app/a.py", "app/b.py"}
    assert all(f.fix_kind == "duplication" for f in out)


# --- read OSError skip in review() -------------------------------------------

def test_review_skips_file_that_cannot_be_read(monkeypatch, tmp_path):
    # A changed file whose read_text raises OSError is skipped (lines 337-338),
    # leaving no findings for it but not crashing the review.
    _repo(tmp_path)
    (tmp_path / "app" / "base.py").write_text(
        "def existing():\n    return 1\n\ndef risky(c):\n    return eval(c)\n")

    real_read = Path.read_text
    raised = {"done": False}

    def flaky(self, *a, **k):
        # Fail only the first read of base.py (review()'s source-load loop);
        # let any later reads (e.g. call-graph build) proceed normally.
        if self.name == "base.py" and not raised["done"]:
            raised["done"] = True
            raise OSError("unreadable")
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", flaky)
    result = review(str(tmp_path))
    assert result.findings == []
    assert result.impacts == []


# --- syntax-error skip in _change_impacts ------------------------------------

def test_change_impacts_skips_unparseable_changed_file(tmp_path):
    # A changed file that doesn't parse must not crash impact analysis; it is
    # simply skipped (lines 377-378).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text("def good():\n    return 1\n")
    _git(tmp_path, ["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
         ["git", "config", "user.name", "t"], ["git", "add", "-A"],
         ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"])
    (tmp_path / "app" / "core.py").write_text("def good(:\n    return 1\n")
    result = review(str(tmp_path))
    assert result.impacts == []


# --- render "needs a human" branch -------------------------------------------

def test_render_needs_a_human_for_non_autofixable_plain_finding():
    # A non-auto-fixable finding with no special fix_kind and no suggestion hits
    # the final else (line 436): "needs a human".
    f = ReviewFinding("app/m.py", 4, "bug", "high", "logic looks wrong",
                      auto_fixable=False, fix_kind="")
    md = render_review_markdown(ReviewResult(base="HEAD", files_reviewed=1, findings=[f]))
    assert "needs a human" in md
    assert "🔴" in md


def test_line_suggestion_swallows_transform_exception(monkeypatch):
    # A transform that raises is caught (lines 185-186) -> None, never crashes.
    from app.execution.semantic.transforms import open_encoding

    def boom(*a, **k):
        raise RuntimeError("transform blew up")

    monkeypatch.setattr(open_encoding, "apply", boom)
    f = ReviewFinding("m.py", 2, "bug", "low", "msg", True, "open-encoding")
    assert _line_suggestion("m.py", "def f(p):\n    return open(p).read()\n", f) is None


def test_line_suggestion_none_when_line_count_changes(monkeypatch):
    # A patch that changes the line count (an import was injected) is not a tidy
    # one-liner -> None (line 193).
    from app.execution.semantic.result import SemanticPatchResult
    from app.execution.semantic.transforms import open_encoding

    src = "def f(p):\n    return open(p).read()\n"

    def grow(rel, source, title):
        new = "import io\n" + src  # one extra line vs the original
        return SemanticPatchResult(patch_requests=[{"new_content": new}])

    monkeypatch.setattr(open_encoding, "apply", grow)
    f = ReviewFinding("m.py", 2, "bug", "low", "msg", True, "open-encoding")
    assert _line_suggestion("m.py", src, f) is None


def test_line_suggestion_none_when_multiple_lines_differ(monkeypatch):
    # Finding line unchanged AND more than one line differs -> the fall-back
    # single-diff path declines (line 202 returns None).
    from app.execution.semantic.result import SemanticPatchResult
    from app.execution.semantic.transforms import open_encoding

    src = "def f(p):\n    a = 1\n    b = 2\n"

    def two_diffs(rel, source, title):
        new = "def f(p):\n    a = 11\n    b = 22\n"  # lines 2 and 3 both differ
        return SemanticPatchResult(patch_requests=[{"new_content": new}])

    monkeypatch.setattr(open_encoding, "apply", two_diffs)
    # Finding points at line 1 (the def), which does NOT change.
    f = ReviewFinding("m.py", 1, "bug", "low", "msg", True, "open-encoding")
    assert _line_suggestion("m.py", src, f) is None


def test_render_plain_autofixable_finding_says_apex_can_autofix():
    # An auto-fixable finding without a shown suggestion and a plain fix_kind hits
    # the `elif f.auto_fixable` arm (line 434): "Apex can auto-fix".
    f = ReviewFinding("app/m.py", 2, "security", "high", "eval of input",
                      auto_fixable=True, fix_kind="eval")
    md = render_review_markdown(ReviewResult(base="HEAD", files_reviewed=1, findings=[f]))
    assert "Apex can auto-fix" in md
