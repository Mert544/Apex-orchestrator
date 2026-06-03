from __future__ import annotations

from app.engine.detectors import (
    Issue,
    detect,
    has_mutable_default,
    has_none_comparison,
    security_label,
)


def test_detect_covers_categories():
    src = (
        "import os, pickle, yaml\n"
        "def run(c, opts=[]):\n"          # mutable default + missing docstring
        "    if c == None:\n"             # none comparison
        "        return None\n"
        "    eval(c)\n"                    # eval
        "    os.system(c)\n"              # os.system
        "    try:\n        pass\n    except:\n        pass\n"  # bare + swallowed
        "    return c\n"
    )
    cats = {i.category for i in detect(src)}
    assert {"security", "bug", "style", "docs"} <= cats
    kinds = {i.fix_kind for i in detect(src)}
    assert "eval" in kinds and "mutable-default" in kinds and "none-comparison" in kinds


def test_detect_syntax_error():
    out = detect("def broken(:\n")
    assert out and out[0].fix_kind == "" and not out[0].auto_fixable


def test_issue_auto_fixable_flag():
    assert Issue(1, "security", "high", "x", "eval").auto_fixable is True
    assert Issue(1, "bug", "high", "x", "").auto_fixable is False


def test_security_label_severity_order():
    # eval outranks a bare except in the same file.
    src = "def f(c):\n    try:\n        return eval(c)\n    except:\n        pass\n"
    assert security_label(src) == "eval"


def test_security_label_detects_sql_fstring():
    src = "def q(cur, name):\n    cur.execute(f'select * from t where n={name}')\n"
    assert security_label(src) == "sql"


def test_security_label_substring_fallback_on_syntax_error():
    # Unparseable file still surfaces an eval via the substring fallback.
    assert security_label("def broken(:\n    eval(x)\n") == "eval"


def test_security_label_none_when_clean():
    assert security_label("def f(x):\n    return x + 1\n") is None


def test_has_mutable_default_and_none_comparison():
    assert has_mutable_default("def f(x=[]):\n    return x\n") is True
    assert has_mutable_default("def f(x=None):\n    return x\n") is False
    assert has_none_comparison("y = a == None\n") is True
    assert has_none_comparison("y = a is None\n") is False


def test_comments_and_strings_ignored():
    # AST-based: eval mentioned in a string/comment is not a finding.
    src = "x = 'use eval() carefully'  # never eval()\n"
    assert security_label(src) is None
    assert not any(i.fix_kind == "eval" for i in detect(src))
