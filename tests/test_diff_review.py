from __future__ import annotations

import subprocess
from pathlib import Path

from app.engine.diff_review import (
    ReviewResult,
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


# --- scan_findings (detector coverage) ---------------------------------------

def test_scan_detects_each_category():
    src = (
        "def f(x, opts=[]):\n"          # mutable default (bug) + missing docstring (docs)
        "    if x == None:\n"           # None comparison (style)
        "        return eval(x)\n"      # eval (security)
        "    return opts\n"
    )
    cats = {f.category for f in scan_findings("m.py", src)}
    assert {"bug", "security", "style", "docs"} <= cats


def test_scan_syntax_error():
    out = scan_findings("m.py", "def broken(:\n")
    assert out and out[0].category == "bug" and not out[0].auto_fixable


def test_private_function_no_docstring_finding():
    cats = [f.category for f in scan_findings("m.py", "def _helper():\n    return 1\n")]
    assert "docs" not in cats  # private functions are exempt


# --- diff scoping ------------------------------------------------------------

def test_changed_lines_parses_diff(tmp_path):
    _repo(tmp_path)
    (tmp_path / "app" / "base.py").write_text("def existing():\n    return 1\n\ndef added(x=[]):\n    return x\n")
    changes = changed_lines(str(tmp_path))
    assert "app/base.py" in changes
    assert any(ln >= 3 for ln in changes["app/base.py"])  # the appended lines


def test_review_only_flags_changed_lines(tmp_path):
    _repo(tmp_path)
    # Append a risky function; the untouched `existing` must not be flagged.
    (tmp_path / "app" / "base.py").write_text(
        "def existing():\n    return 1\n\ndef risky(c, o=[]):\n    return eval(c)\n"
    )
    result = review(str(tmp_path))
    assert isinstance(result, ReviewResult)
    files = {f.file for f in result.findings}
    assert files == {"app/base.py"}
    cats = {f.category for f in result.findings}
    assert "security" in cats and "bug" in cats
    # All findings are on changed lines (>=3), not on `existing` (lines 1-2).
    assert all(f.line >= 3 for f in result.findings)


def test_review_clean_diff(tmp_path):
    _repo(tmp_path)
    (tmp_path / "app" / "base.py").write_text(
        "def existing():\n    return 1\n\n\ndef clean(x):\n    \"\"\"Doc.\"\"\"\n    return x is None\n"
    )
    result = review(str(tmp_path))
    assert result.findings == []
    assert "No issues found" in render_review_markdown(result)


def test_review_no_changes(tmp_path):
    _repo(tmp_path)
    result = review(str(tmp_path))
    assert result.files_reviewed == 0
    assert "No changed Python files" in render_review_markdown(result)


def test_render_lists_findings_and_autofix(tmp_path):
    _repo(tmp_path)
    (tmp_path / "app" / "base.py").write_text(
        "def existing():\n    return 1\n\ndef risky(c):\n    return eval(c)\n"
    )
    md = render_review_markdown(review(str(tmp_path)))
    assert "Apex review" in md
    assert "eval()" in md
    assert "auto-fix" in md


def test_to_dict_and_autofix_count(tmp_path):
    _repo(tmp_path)
    (tmp_path / "app" / "base.py").write_text(
        "def existing():\n    return 1\n\ndef risky(c=[]):\n    return eval(c)\n"
    )
    d = review(str(tmp_path)).to_dict()
    assert d["auto_fixable_count"] >= 1
    assert "findings" in d


def test_scan_detects_swallowed_exception():
    src = "def f():\n    try:\n        x = 1\n    except Exception:\n        pass\n"
    msgs = [f.message for f in scan_findings("m.py", src)]
    assert any("silently swallowed" in m for m in msgs)


def test_scan_detects_assert_tuple():
    src = "def f(x):\n    assert (x, 'msg')\n    return x\n"
    found = [f for f in scan_findings("m.py", src) if "assert on a tuple" in f.message]
    assert found and found[0].severity == "high"


def test_scan_detects_bool_and_type_comparisons():
    src = "def f(x):\n    if x == True:\n        return type(x) == int\n    return x\n"
    msgs = [f.message for f in scan_findings("m.py", src)]
    assert any("True/False" in m for m in msgs)
    assert any("isinstance()" in m for m in msgs)


def test_no_false_positive_on_numeric_equality():
    # `x == 5` must NOT be flagged as a True/False comparison (1 == True trap).
    msgs = [f.message for f in scan_findings("m.py", "def f(x):\n    return x == 5\n")]
    assert not any("True/False" in m for m in msgs)


def test_review_reports_change_impact(tmp_path):
    # Changing a function that has callers surfaces the blast radius in review.
    _repo = _git
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text(
        "def parse(s):\n    return s\n\ndef a():\n    return parse('x')\n\ndef b():\n    return parse('y')\n"
    )
    _git(tmp_path, ["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
         ["git", "config", "user.name", "t"], ["git", "add", "-A"],
         ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"])
    (tmp_path / "app" / "core.py").write_text(
        "def parse(s):\n    return s.strip()\n\ndef a():\n    return parse('x')\n\ndef b():\n    return parse('y')\n"
    )
    result = review(str(tmp_path))
    assert result.impacts, "expected a change-impact entry for the modified parse()"
    parse_impact = next(i for i in result.impacts if i.function == "parse")
    assert parse_impact.caller_count == 2  # a() and b() call parse
    md = render_review_markdown(result)
    assert "Change impact" in md and "parse()" in md


def test_review_no_impact_for_uncalled_change(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text("def lonely():\n    return 1\n")
    _git(tmp_path, ["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
         ["git", "config", "user.name", "t"], ["git", "add", "-A"],
         ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"])
    (tmp_path / "app" / "core.py").write_text("def lonely():\n    return 2\n")
    result = review(str(tmp_path))
    assert result.impacts == []  # nothing calls lonely()


def test_review_proposes_inline_fix_for_clean_one_liners():
    from app.engine.diff_review import scan_findings, _line_suggestion
    # open-encoding: a pure single-line rewrite -> show the before/after.
    src = "def load(p):\n    return open(p).read()\n"
    f = next(x for x in scan_findings("m.py", src) if x.fix_kind == "open-encoding")
    old, new = _line_suggestion("m.py", src, f)
    assert old == "return open(p).read()"
    assert new == 'return open(p, encoding="utf-8").read()'


def test_review_no_inline_suggestion_when_imports_are_added():
    # eval -> ast.literal_eval injects `import ast`, so it is auto-fixable but
    # NOT a tidy one-liner -> no inline diff (avoids a misleading suggestion).
    from app.engine.diff_review import scan_findings, _line_suggestion
    src = "def f(s):\n    return eval(s)\n"
    f = next(x for x in scan_findings("m.py", src) if x.fix_kind == "eval")
    assert f.auto_fixable
    assert _line_suggestion("m.py", src, f) is None


def test_render_includes_suggestion_diff_block(tmp_path):
    from app.engine.diff_review import ReviewFinding, ReviewResult, render_review_markdown
    f = ReviewFinding("svc.py", 4, "bug", "low", "open() without encoding=",
                      auto_fixable=True, fix_kind="open-encoding",
                      suggestion=("return open(p).read()",
                                  'return open(p, encoding="utf-8").read()'))
    md = render_review_markdown(ReviewResult(base="HEAD", files_reviewed=1, findings=[f]))
    assert "suggested fix below" in md
    assert "```diff" in md
    assert '+ return open(p, encoding="utf-8").read()' in md


# --- the workflow-failure fixes (comment cap, fixture gate, rule book) --------

def test_render_caps_findings_with_a_summary_footer(tmp_path):
    # The bug that spammed the user's email: a wide diff produced a comment
    # over GitHub's 65 536-char limit. The renderer must bound its output.
    from app.engine.diff_review import ReviewResult, ReviewFinding

    findings = [ReviewFinding(f"app/m{i}.py", 1, "docs", "low",
                              f"public function f{i} lacks a docstring", True)
                for i in range(200)]
    result = ReviewResult(base="origin/main", files_reviewed=200, findings=findings)
    md = render_review_markdown(result, limit=40)
    assert md.count("- 🔵") == 40
    assert "and **160 more**" in md
    # Unlimited still shows everything (terminal use).
    assert render_review_markdown(result, limit=0).count("- 🔵") == 200


def test_gate_ignores_fixture_secrets_but_flags_real_ones():
    # tests/ and examples/ carry intentional flaws (the hardcoded secret used
    # as test data). The CI gate must not fail a PR over them — but a real one
    # in shipping code still blocks.
    from app.engine.diff_review import ReviewResult, ReviewFinding, blocking_high_findings

    fixture = ReviewFinding("tests/test_safety_gates.py", 190, "security", "high",
                            "possible hardcoded secret", False)
    example = ReviewFinding("examples/vuln/app.py", 3, "security", "high",
                            "eval of untrusted input", False)
    real = ReviewFinding("app/payments.py", 8, "security", "high",
                         "possible hardcoded secret", False)
    res = ReviewResult(base="HEAD", files_reviewed=3,
                       findings=[fixture, example, real])
    blocking = blocking_high_findings(res)
    assert [f.file for f in blocking] == ["app/payments.py"]


def test_saved_rule_violation_surfaces_as_a_review_finding(tmp_path):
    from app.execution.rewrite_rules import save_rule

    _repo(tmp_path)
    save_rule(str(tmp_path), "no-len-zero", "len($x) == 0", "not $x")
    # A PR introduces a line that re-enters the convention.
    (tmp_path / "app" / "base.py").write_text(
        "def existing():\n    return 1\n\ndef chk(xs):\n    return len(xs) == 0\n"
    )
    result = review(str(tmp_path))
    rule_hits = [f for f in result.findings if f.category == "convention"]
    assert len(rule_hits) == 1
    assert rule_hits[0].line == 5
    assert rule_hits[0].fix_kind == "rule:no-len-zero"
    md = render_review_markdown(result)
    assert "apex rewrite --rule no-len-zero" in md


def test_review_with_no_rule_book_is_unchanged(tmp_path):
    _repo(tmp_path)
    (tmp_path / "app" / "base.py").write_text(
        "def existing():\n    return 1\n\ndef chk(xs):\n    return len(xs) == 0\n"
    )
    result = review(str(tmp_path))
    assert not any(f.category == "convention" for f in result.findings)


# --- extraction suggestions on the diff (refactor findings) -------------------

def _long_function_source(name: str = "compute") -> str:
    body = "\n".join(f"    acc = acc + {i}" for i in range(45))
    return f"def {name}(start):\n    acc = start\n{body}\n    return acc\n"


def test_review_flags_long_function_with_extract_command(tmp_path):
    _repo(tmp_path)
    (tmp_path / "app" / "base.py").write_text(_long_function_source())
    result = review(str(tmp_path))
    refactors = [f for f in result.findings if f.category == "refactor"]
    assert len(refactors) == 1
    f = refactors[0]
    assert f.severity == "low"
    assert f.fix_kind == "extract"
    assert not f.auto_fixable  # extraction is a judgment call, never auto-applied
    # The message carries the exact, runnable command.
    assert "apex extract app/base.py" in f.message
    assert "_compute_part" in f.message


def test_review_extract_finding_renders_with_refactor_hint(tmp_path):
    _repo(tmp_path)
    (tmp_path / "app" / "base.py").write_text(_long_function_source())
    md = render_review_markdown(review(str(tmp_path)))
    assert "refactor: run the command above" in md
    assert "[refactor]" in md


def test_review_no_extract_finding_when_seam_untouched(tmp_path):
    # Commit a long function, then change ONE line far outside its seam — the
    # seam isn't on the diff, so no extraction finding fires.
    _repo(tmp_path)
    src = _long_function_source()
    (tmp_path / "app" / "base.py").write_text(src)
    _git(tmp_path, ["git", "add", "-A"],
         ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "long"])
    # Append a tiny new, short function — only its lines are on the diff.
    (tmp_path / "app" / "base.py").write_text(src + "\ndef tiny():\n    return 0\n")
    result = review(str(tmp_path))
    assert not [f for f in result.findings if f.category == "refactor"]


def test_review_extract_finding_excluded_for_fixture_paths(tmp_path):
    # A long function added under tests/ must NOT get an extraction finding
    # (fixture/test code is excluded throughout the reviewer).
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "base.py").write_text("def existing():\n    return 1\n")
    _git(tmp_path, ["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
         ["git", "config", "user.name", "t"], ["git", "add", "-A"],
         ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"])
    (tmp_path / "tests" / "base.py").write_text(_long_function_source())
    result = review(str(tmp_path))
    assert not [f for f in result.findings if f.category == "refactor"]


# --- f-string-without-placeholder (style finding with inline suggestion) ------

def test_review_flags_dead_fstring_with_suggestion(tmp_path):
    _repo(tmp_path)
    (tmp_path / "app" / "base.py").write_text(
        'def existing():\n    return 1\n\ndef greet():\n    return f"hello"\n'
    )
    result = review(str(tmp_path))
    fstrings = [f for f in result.findings if f.fix_kind == "fstring-no-placeholder"]
    assert len(fstrings) == 1
    f = fstrings[0]
    assert f.category == "style"
    assert f.auto_fixable
    # A tidy one-liner — the reviewer shows the before/after suggestion.
    assert f.suggestion is not None
    old, new = f.suggestion
    assert 'f"hello"' in old and '"hello"' in new and "f" not in new.split('"')[0]


# --- collection-literal modernization (style finding with inline suggestion) --

def test_review_flags_empty_constructor_with_suggestion(tmp_path):
    _repo(tmp_path)
    (tmp_path / "app" / "base.py").write_text(
        'def existing():\n    return 1\n\ndef build():\n    return dict()\n'
    )
    result = review(str(tmp_path))
    coll = [f for f in result.findings if f.fix_kind == "collection-literal"]
    assert len(coll) == 1
    f = coll[0]
    assert f.category == "style"
    assert f.auto_fixable
    assert f.suggestion is not None
    old, new = f.suggestion
    assert "dict()" in old and "{}" in new
