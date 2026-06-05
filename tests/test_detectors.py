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


def test_detects_shell_true():
    src = "import subprocess\ndef f(c):\n    subprocess.run(c, shell=True)\n"
    msgs = [i.message for i in detect(src)]
    assert any("shell=True" in m for m in msgs)


def test_detects_hardcoded_secret_conservatively():
    # A real-looking secret is flagged; short/placeholder/non-secret names are not.
    flagged = detect("api_key = 'sk-abc123def456'\n")
    assert any("hardcoded secret" in i.message for i in flagged)
    assert not any("secret" in i.message for i in detect("password = 'x'\n"))        # too short
    assert not any("secret" in i.message for i in detect("api_key = 'example'\n"))   # placeholder
    assert not any("secret" in i.message for i in detect("timeout = 'short_value'\n"))  # not secret-named


def test_shell_true_and_secret_not_auto_fixable():
    for src in ("import subprocess\nsubprocess.run('x', shell=True)\n", "token = 'abcdef123456'\n"):
        sec = [i for i in detect(src) if i.category == "security"]
        assert sec and all(not i.auto_fixable for i in sec)


def test_detects_exec_and_pickle():
    out = detect("def f(c):\n    exec(c)\n")
    assert any(i.message.startswith("exec()") and not i.auto_fixable for i in out)
    out2 = detect("import pickle\ndef f(b):\n    return pickle.loads(b)\n")
    assert any(i.fix_kind == "pickle" for i in out2)


def test_secret_via_annotated_assignment():
    # AnnAssign branch: `api_key: str = "..."`.
    out = detect("api_key: str = 'sk-abc123def456'\n")
    assert any("hardcoded secret" in i.message for i in out)


def test_security_label_handles_unreadable_gracefully():
    # security_label on a clean parseable file returns None (no false positive).
    assert security_label("x = 1\n") is None


def test_has_none_comparison_on_syntax_error():
    # has_* helpers must not raise on unparseable input.
    assert has_mutable_default("def broken(:\n") is False
    assert has_none_comparison("def broken(:\n") is False


def test_substantive_vs_shallow_assertions():
    from app.engine.detectors import test_has_substantive_assertions as subst
    # Shallow: import-smoke + isinstance/type contracts only.
    shallow = (
        "import pkg.m\n"
        "def test_imports():\n    assert pkg.m is not None\n"
        "def test_contracts():\n    assert isinstance(pkg.m.f(0), str)\n    assert callable(pkg.m.g)\n"
    )
    assert subst(shallow) is False
    # Substantive: a real value assertion.
    real = "from pkg.m import add\ndef test_add():\n    assert add(2, 3) == 5\n"
    assert subst(real) is True
    # `in` / relational comparisons are substantive too.
    assert subst("def t():\n    assert 1 in [1, 2]\n") is True
