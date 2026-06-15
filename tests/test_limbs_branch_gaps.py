"""Branch-gap tests for app.agents.limbs.

test_limbs.py (smoke) + test_limbs_edges.py (error paths) already reach 100%
line coverage, but three conditional branches remain only partially taken:

  * 101->98  DebugLimb._analyze_traceback: a 'File "...", line N' line whose
             regex does NOT match (so the loop continues instead of returning).
  * 314->308 RefactorLimb._execute: a FunctionDef that HAS a docstring (so the
             missing-docstring append is skipped and the walk continues), plus
             the long-function (>50 body) detection branch.
  * 394->404 DependencyLimb._check_outdated: subprocess returns a non-zero
             returncode, so the JSON branch is skipped and the empty default
             dict is returned.

These tests are deterministic and offline; the only external call (pip list)
is monkeypatched.
"""

from __future__ import annotations

import types

from app.agents.limbs import (
    DebugLimb,
    DependencyLimb,
    DocLimb,
    RefactorLimb,
)


# --- 101->98: File-line present but regex fails to match ---------------------

def test_analyze_traceback_file_line_without_match_continues(tmp_path):
    """A line that contains 'File ' and the project name but no parseable
    'File "...", line N' pattern must NOT short-circuit; the scan continues and
    falls through to the keyword classifiers (branch 101->98)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    limb = DebugLimb()
    # 'File ' + project name present, but no quoted path / line number, so the
    # inner regex returns None and the loop continues to the next line where a
    # ValueError keyword is finally classified.
    trace = "File proj summary line (no quotes)\nValueError: bad\n"
    cause = limb._analyze_traceback(trace, proj)
    assert cause == {"type": "ValueError", "detail": "invalid value"}


def test_analyze_traceback_file_line_no_match_and_no_keyword_returns_none(tmp_path):
    """Same loop-continue branch, but with nothing else to classify -> None."""
    proj = tmp_path / "proj"
    proj.mkdir()
    limb = DebugLimb()
    trace = "File proj but unparseable\nanother benign line\n"
    assert limb._analyze_traceback(trace, proj) is None


# --- 156->154: Call node whose func is not a bare Name is skipped ------------

def test_scan_file_with_attribute_call_finds_no_eval(tmp_path):
    """A method/attribute call (node.func is ast.Attribute, not ast.Name) must
    be walked past without matching eval/exec (branch 156->154)."""
    (tmp_path / "obj_calls.py").write_text(
        "import os\n\n\ndef go():\n    os.getcwd()\n    'x'.upper()\n    return 1\n",
        encoding="utf-8",
    )
    issues = DebugLimb()._scan_file_for_common_issues(tmp_path / "obj_calls.py")
    # No eval/exec bare-name calls present.
    assert issues == []


# --- 314->308: function with docstring skips the missing-doc append ----------

def test_refactor_documented_function_not_flagged(tmp_path):
    """A FunctionDef that already has a docstring must not be reported as
    missing a docstring; the walk simply continues (branch 314->308)."""
    (tmp_path / "documented.py").write_text(
        'def good():\n    """I am documented."""\n    return 1\n',
        encoding="utf-8",
    )
    result = RefactorLimb().run(project_root=str(tmp_path))
    assert not any("good" in i for i in result["issues_found"])


def test_refactor_flags_long_function(tmp_path):
    """A function with more than 50 statements triggers the long-function
    finding (line 310-313 true branch)."""
    body = "".join(f"    x{n} = {n}\n" for n in range(60))
    src = f'def big():\n    """doc."""\n{body}'
    (tmp_path / "huge.py").write_text(src, encoding="utf-8")
    result = RefactorLimb().run(project_root=str(tmp_path))
    assert any("Long function 'big'" in i for i in result["issues_found"])
    # It is documented, so it should NOT also appear as a missing-docstring item.
    assert not any(
        "Missing docstring" in i and "big" in i for i in result["issues_found"]
    )


# --- DocLimb: deterministic test-file-skip and documented-node branches ------

def test_doc_limb_skips_test_named_files_and_documented_nodes(tmp_path):
    """Deterministically exercises the DocLimb 'test' filename skip and the
    'top-level node already has a docstring' branch using tmp_path (no reliance
    on the project tree, which makes these branches flaky across runs)."""
    # A file whose name contains 'test' must be skipped entirely.
    (tmp_path / "test_skip_me.py").write_text(
        "def undocumented():\n    return 1\n", encoding="utf-8"
    )
    # A fully documented module + class, so no missing docs are recorded and the
    # documented-node branch (skip the missing_count increment) is taken.
    (tmp_path / "documented.py").write_text(
        '"""Module doc."""\n\n\nclass Thing:\n    """Class doc."""\n\n    def m(self):\n'
        '        return 1\n',
        encoding="utf-8",
    )
    result = DocLimb().run(project_root=str(tmp_path), target="all")
    # documented.py has a module docstring -> not in missing_docs.
    assert "documented.py" not in result["missing_docs"]
    # test_skip_me.py was skipped, so it is never reported as missing docs.
    assert not any("test_skip_me" in m for m in result["missing_docs"])
    # The documented top-level class did not add to missing function/class docs.
    assert any("Found 0 missing" in d for d in result["generated_docs"])


# --- 394->404: pip list returns non-zero exit code ---------------------------

def test_check_outdated_nonzero_returncode_returns_empty(monkeypatch, tmp_path):
    """When `pip list --outdated` exits non-zero, the JSON parsing branch is
    skipped and the empty default dict is returned (branch 394->404)."""
    monkeypatch.setattr(
        "app.agents.limbs.subprocess.run",
        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="[]", stderr="boom"),
    )
    out = DependencyLimb()._check_outdated(tmp_path)
    assert out == {"outdated": [], "updates": []}


def test_check_security_nonzero_returncode_returns_empty(monkeypatch, tmp_path):
    """pip audit non-zero exit also yields the empty default list."""
    monkeypatch.setattr(
        "app.agents.limbs.subprocess.run",
        lambda *a, **k: types.SimpleNamespace(returncode=2, stdout="{}", stderr="x"),
    )
    assert DependencyLimb()._check_security_issues(tmp_path) == []
