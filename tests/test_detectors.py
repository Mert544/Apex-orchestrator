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


def test_assert_substantive_branch_coverage():
    from app.engine.detectors import test_has_substantive_assertions as subst

    # Bare truthiness / attribute / constant asserts are shallow.
    assert subst("def t():\n    assert mod\n") is False
    assert subst("def t():\n    assert mod.attr\n") is False
    assert subst("def t():\n    assert True\n") is False
    # `is None` / `is not None` identity-with-None is shallow...
    assert subst("def t():\n    assert x is None\n") is False
    assert subst("def t():\n    assert x is not None\n") is False
    # ...but `is` against a non-None value is a real check.
    assert subst("def t():\n    assert x is SOME_SENTINEL\n") is True
    # BoolOp is substantive iff any operand is.
    assert subst("def t():\n    assert mod and other\n") is False
    assert subst("def t():\n    assert mod and a == 1\n") is True
    # UnaryOp delegates to its operand.
    assert subst("def t():\n    assert not isinstance(x, int)\n") is False
    assert subst("def t():\n    assert not (a == b)\n") is True
    # A plain function-call assertion (not isinstance/callable/hasattr) is real.
    assert subst("def t():\n    assert verify(x)\n") is True
    assert subst("def t():\n    assert hasattr(x, 'y')\n") is False


def test_open_without_encoding_branch_coverage():
    from app.engine.detectors import has_open_without_encoding as needs_enc

    # Plain text open() with no encoding -> flagged.
    assert needs_enc("open('f.txt')") is True
    assert needs_enc("open('f.txt', 'r')") is True
    assert needs_enc("open('f.txt', mode='r')") is True
    # encoding= present (positional-after or keyword) -> fine.
    assert needs_enc("open('f.txt', encoding='utf-8')") is False
    # Binary mode never needs a text encoding.
    assert needs_enc("open('f.txt', 'rb')") is False
    assert needs_enc("open('f.txt', mode='wb')") is False
    # A dynamic (non-constant) mode is left alone — can't prove it's text.
    assert needs_enc("open('f.txt', the_mode)") is False
    # **kwargs might carry encoding -> don't flag.
    assert needs_enc("open('f.txt', **opts)") is False
    # No args, or not the builtin open, -> not flagged.
    assert needs_enc("open()") is False
    assert needs_enc("obj.open('f.txt')") is False


def test_identity_comparison_with_literal_is_flagged():
    from app.engine.detectors import detect

    def has_identity_bug(src):
        return any("identity check against a literal" in i.message and i.category == "bug"
                   for i in detect(src))

    assert has_identity_bug("def f(x):\n    return x is 5\n")
    assert has_identity_bug('def f(n):\n    return n is "admin"\n')
    assert has_identity_bug("def f(x):\n    return x is not 0\n")
    assert has_identity_bug("def f(x):\n    return x is ()\n")
    # Correct identity uses must NOT be flagged.
    assert not has_identity_bug("def f(x):\n    return x is None\n")
    assert not has_identity_bug("def f(x):\n    return x is True\n")
    assert not has_identity_bug("def f(a, b):\n    return a is b\n")


def test_frozen_dataclass_self_assignment_is_flagged():
    from app.engine.detectors import detect

    def frozen_bug(src):
        return any("FrozenInstanceError" in i.message and i.severity == "high" for i in detect(src))

    frozen = ("from dataclasses import dataclass\n"
              "@dataclass(frozen=True)\nclass C:\n    x: int\n"
              "    def bump(self):\n        self.x = self.x + 1\n")
    assert frozen_bug(frozen)
    # AugAssign too
    aug = ("from dataclasses import dataclass\n"
           "@dataclass(frozen=True)\nclass C:\n    x: int\n"
           "    def bump(self):\n        self.x += 1\n")
    assert frozen_bug(aug)
    # A normal (mutable) dataclass is fine; a read-only frozen one is fine.
    assert not frozen_bug("from dataclasses import dataclass\n@dataclass\nclass C:\n    x: int\n    def s(self):\n        self.x = 1\n")
    assert not frozen_bug("from dataclasses import dataclass\n@dataclass(frozen=True)\nclass C:\n    x: int\n    def d(self):\n        return self.x * 2\n")


def test_control_flow_in_finally_is_flagged():
    from app.engine.detectors import detect

    def fin(src):
        return any("finally block" in i.message and i.severity == "high" for i in detect(src))

    assert fin("def f():\n    try:\n        x = 1\n    finally:\n        return 0\n")
    assert fin("def f():\n    for i in range(3):\n        try:\n            pass\n        finally:\n            break\n")
    # Correct: return in a nested function, break inside a loop within finally,
    # return in the try body — none escape the finally.
    assert not fin("def f():\n    try:\n        pass\n    finally:\n        def g():\n            return 1\n")
    assert not fin("def f():\n    try:\n        pass\n    finally:\n        for i in range(2):\n            break\n")
    assert not fin("def f():\n    try:\n        return 1\n    finally:\n        pass\n")


def test_unreachable_except_is_flagged():
    from app.engine.detectors import detect

    def unr(src):
        return any("unreachable except" in i.message and i.severity == "high" for i in detect(src))

    # Exception above a narrower handler -> the narrower one is dead.
    assert unr("def f():\n    try:\n        pass\n    except Exception:\n        pass\n    except ValueError:\n        pass\n")
    # BaseException shadows everything after it.
    assert unr("def f():\n    try:\n        pass\n    except BaseException:\n        pass\n    except KeyboardInterrupt:\n        pass\n")
    # Reachable: KeyboardInterrupt is NOT caught by except Exception.
    assert not unr("def f():\n    try:\n        pass\n    except Exception:\n        pass\n    except KeyboardInterrupt:\n        pass\n")
    # Correct order (specific before broad) is fine.
    assert not unr("def f():\n    try:\n        pass\n    except ValueError:\n        pass\n    except Exception:\n        pass\n")


def test_comparison_with_itself_is_flagged():
    from app.engine.detectors import detect

    def sc(src):
        return any("comparison with itself" in i.message and i.category == "bug" for i in detect(src))

    assert sc("def f(x):\n    return x < x\n")
    assert sc("def f(s):\n    return s.a >= s.a\n")
    assert sc("def f(x):\n    return x is x\n")
    # NaN idioms (!= / ==) and genuinely different / side-effecting operands are fine.
    assert not sc("def f(x):\n    return x != x\n")
    assert not sc("def f(x):\n    return x == x\n")
    assert not sc("def f(a, b):\n    return a < b\n")
    assert not sc("def f(g):\n    return g() < g()\n")


def test_detect_respects_inline_suppression():
    from app.engine.detectors import detect

    def sec_kinds(src):
        return [i.fix_kind for i in detect(src) if i.category == "security"]

    # nosec / noqa:S### / bare noqa silence the security finding...
    assert sec_kinds("def f(c):\n    return eval(c)  # noqa: S307\n") == []
    assert sec_kinds("def f(c):\n    return eval(c)  # nosec\n") == []
    assert sec_kinds("def f(c):\n    return eval(c)  # noqa\n") == []
    # ...but an unrelated code does NOT.
    assert sec_kinds("def f(c):\n    return eval(c)  # noqa: E501\n") == ["eval"]
    # E722 silences the bare-except security finding.
    bare = detect("def f():\n    try:\n        x = 1\n    except:  # noqa: E722\n        pass\n")
    assert not any(i.fix_kind == "bare except" for i in bare)
    # F632 silences the identity-literal bug.
    assert not any("identity check" in i.message
                   for i in detect("def f(x):\n    return x is 5  # noqa: F632\n"))


def test_raise_without_from_is_flagged():
    from app.engine.detectors import detect

    def b904(src):
        return any("original cause" in i.message and i.category == "bug" for i in detect(src))

    base = "def f():\n    try:\n        x = 1\n    except Exception%s:\n        %s\n"
    assert b904(base % ("", 'raise ValueError("bad")'))           # new exc, no from
    # All the correct forms are left alone.
    assert not b904(base % (" as e", 'raise ValueError("bad") from e'))
    assert not b904(base % ("", 'raise ValueError("bad") from None'))
    assert not b904(base % ("", "raise"))                          # bare re-raise
    assert not b904(base % (" as e", "raise e"))                   # re-raise by name


def test_detects_except_base_exception_without_reraise():
    from app.engine.detectors import detect, has_base_exception

    bad = "def f():\n    try:\n        g()\n    except BaseException:\n        log()\n"
    found = [i for i in detect(bad) if i.fix_kind == "base-exception"]
    assert len(found) == 1
    assert found[0].line == 4 and found[0].category == "security"
    assert "KeyboardInterrupt" in found[0].message
    assert has_base_exception(bad)
    # tuple form is caught too
    tup = "def f():\n    try:\n        g()\n    except (ValueError, BaseException):\n        log()\n"
    assert has_base_exception(tup)


def test_base_exception_with_reraise_or_noqa_is_exempt():
    from app.engine.detectors import detect, has_base_exception

    # a bare `raise` makes the broad catch the legitimate cleanup pattern
    reraise = ("def f():\n    try:\n        g()\n    except BaseException:\n"
               "        cleanup()\n        raise\n")
    assert not has_base_exception(reraise)
    # ...but a raise inside a nested function does NOT count as re-raising
    nested = ("def f():\n    try:\n        g()\n    except BaseException:\n"
              "        def h():\n            raise\n        log()\n")
    assert has_base_exception(nested)
    # noqa: B036 silences it
    silenced = "def f():\n    try:\n        g()\n    except BaseException:  # noqa: B036\n        log()\n"
    assert not any(i.fix_kind == "base-exception" for i in detect(silenced))
    # plain `except Exception:` is fine
    assert not has_base_exception("def f():\n    try:\n        g()\n    except Exception:\n        log()\n")


# --- mutable class attribute (shared-state bug) ------------------------------

def _mutable_attr_lines(src: str) -> list[int]:
    return sorted(i.line for i in detect(src)
                  if "mutable class attribute" in i.message)


def test_mutable_class_attr_list_mutated_is_flagged():
    src = ("class Cart:\n"
           "    items = []\n"
           "    def add(self, x):\n"
           "        self.items.append(x)\n")
    assert _mutable_attr_lines(src) == [2]
    issue = next(i for i in detect(src) if "mutable class attribute" in i.message)
    assert issue.category == "bug" and issue.severity == "medium"
    assert not issue.auto_fixable  # detect-only: the fix moves init into __init__


def test_mutable_class_attr_dict_subscript_store_is_flagged():
    src = ("class Reg:\n"
           "    cache = {}\n"
           "    def put(self, k, v):\n"
           "        self.cache[k] = v\n")
    assert _mutable_attr_lines(src) == [2]


def test_mutable_class_attr_augassign_is_flagged():
    src = ("class Acc:\n"
           "    total = []\n"
           "    def go(self, xs):\n"
           "        self.total += xs\n")
    assert _mutable_attr_lines(src) == [2]


def test_mutable_class_attr_empty_constructor_call_is_flagged():
    src = ("class C:\n"
           "    seen = set()\n"
           "    def mark(self, x):\n"
           "        self.seen.add(x)\n")
    assert _mutable_attr_lines(src) == [2]


def test_mutable_class_attr_annotated_is_flagged():
    src = ("class C:\n"
           "    items: list = []\n"
           "    def add(self, x):\n"
           "        self.items.append(x)\n")
    assert _mutable_attr_lines(src) == [2]


def test_reassigned_in_init_is_not_flagged():
    # __init__ rebinds self.items per instance — no shared state, no bug.
    src = ("class C:\n"
           "    items = []\n"
           "    def __init__(self):\n"
           "        self.items = []\n"
           "    def add(self, x):\n"
           "        self.items.append(x)\n")
    assert _mutable_attr_lines(src) == []


def test_read_only_class_constant_is_not_flagged():
    # A class-level mutable that is only READ is a legitimate shared constant.
    src = ("class C:\n"
           "    DEFAULTS = [1, 2, 3]\n"
           "    def first(self):\n"
           "        return self.DEFAULTS[0]\n")
    assert _mutable_attr_lines(src) == []


def test_immutable_class_attr_is_not_flagged():
    # A non-mutable class attribute is never a shared-state bug.
    src = ("class C:\n"
           "    NAME = 'x'\n"
           "    LIMIT = 10\n"
           "    def f(self):\n"
           "        return self.NAME\n")
    assert _mutable_attr_lines(src) == []


def test_unmutated_class_level_mutable_is_not_flagged():
    # Declared but never mutated in place (and never read either) — conservative:
    # no mutation evidence means no flag.
    src = ("class C:\n"
           "    buf = []\n"
           "    def f(self, x):\n"
           "        return x + 1\n")
    assert _mutable_attr_lines(src) == []


# --- broad silent except (swallows every error) ------------------------------

_BROAD_SILENT_MSG = "broad except silently swallows all errors"


def _broad_silent(src: str) -> list[Issue]:
    return [i for i in detect(src) if _BROAD_SILENT_MSG in i.message]


def test_except_exception_pass_is_flagged_broad():
    from app.engine.detectors import has_silent_broad_except

    src = "def f():\n    try:\n        g()\n    except Exception:\n        pass\n"
    found = _broad_silent(src)
    assert len(found) == 1
    assert found[0].line == 4
    assert found[0].category == "bug" and found[0].severity == "medium"
    assert not found[0].auto_fixable  # detect-only: the fix is contextual
    assert has_silent_broad_except(src)


def test_except_base_exception_ellipsis_body_is_flagged():
    from app.engine.detectors import has_silent_broad_except

    # `...` body (Expr -> Ellipsis constant) is silent, just like pass.
    src = "def f():\n    try:\n        g()\n    except BaseException:\n        ...\n"
    found = _broad_silent(src)
    assert len(found) == 1 and found[0].category == "bug" and found[0].severity == "medium"
    assert has_silent_broad_except(src)


def test_broad_except_docstring_only_body_is_flagged():
    # A handler whose only statement is a bare string constant is still silent.
    src = 'def f():\n    try:\n        g()\n    except Exception:\n        "ignore"\n'
    assert len(_broad_silent(src)) == 1


def test_broad_except_tuple_containing_exception_is_flagged():
    from app.engine.detectors import has_silent_broad_except

    src = ("def f():\n    try:\n        g()\n"
           "    except (ValueError, Exception):\n        pass\n")
    assert has_silent_broad_except(src)


def test_narrow_silent_pass_is_not_flagged_broad():
    from app.engine.detectors import has_silent_broad_except

    # `except KeyError: pass` is often a deliberate best-effort — never flagged
    # by the broad detector (though the generic "silently swallowed" still fires).
    src = "def f():\n    try:\n        g()\n    except KeyError:\n        pass\n"
    assert _broad_silent(src) == []
    assert not has_silent_broad_except(src)


def test_broad_except_with_real_body_is_not_flagged():
    from app.engine.detectors import has_silent_broad_except

    # A handler that actually does something (logs the error) is not silent.
    src = "def f():\n    try:\n        g()\n    except Exception as e:\n        log(e)\n"
    assert _broad_silent(src) == []
    assert not has_silent_broad_except(src)


def test_bare_except_pass_does_not_double_flag_broad():
    from app.engine.detectors import has_silent_broad_except

    # Non-duplication rule: bare `except: pass` is covered by the "bare except"
    # security finding plus the generic "silently swallowed" bug finding — the
    # broad detector deliberately stays silent so there is no third message.
    src = "def f():\n    try:\n        g()\n    except:\n        pass\n"
    assert _broad_silent(src) == []
    assert not has_silent_broad_except(src)
    msgs = [i.message for i in detect(src)]
    assert any("bare except" in m for m in msgs)
    assert any("silently swallowed" in m for m in msgs)


def test_except_exception_pass_keeps_generic_silently_swallowed_finding():
    # The broad finding is ADDITIVE: `except Exception: pass` still emits the
    # generic "silently swallowed" message (other modules depend on its wording).
    src = "def f():\n    try:\n        g()\n    except Exception:\n        pass\n"
    msgs = [i.message for i in detect(src)]
    assert any("silently swallowed" in m for m in msgs)
    assert any(_BROAD_SILENT_MSG in m for m in msgs)


# --- unreachable (dead) code -------------------------------------------------

from app.engine.detectors import has_unreachable_code  # noqa: E402


def _unreachable(src: str) -> list[int]:
    return [i.line for i in detect(src) if has_unreachable_code(src) and
            i.message == "unreachable code — this runs after an unconditional "
                         "return/raise/break/continue"]


def test_unreachable_after_return():
    src = "def f():\n    return 1\n    x = 2\n"
    assert _unreachable(src) == [3]            # flagged at the `x = 2` line
    assert has_unreachable_code(src)
    issues = [i for i in detect(src) if i.line == 3 and "unreachable" in i.message]
    assert issues and issues[0].category == "bug" and issues[0].severity == "medium"
    assert issues[0].fix_kind == "" and not issues[0].auto_fixable


def test_unreachable_after_raise():
    src = "def f():\n    raise ValueError()\n    cleanup()\n"
    assert _unreachable(src) == [3]
    assert has_unreachable_code(src)


def test_unreachable_after_break():
    src = "def f():\n    for i in x:\n        break\n        y = i\n"
    assert _unreachable(src) == [4]
    assert has_unreachable_code(src)


def test_unreachable_after_continue():
    src = "def f():\n    for i in x:\n        continue\n        y = i\n"
    assert _unreachable(src) == [4]
    assert has_unreachable_code(src)


def test_terminal_as_last_statement_not_flagged():
    src = "def f():\n    x = 1\n    return x\n"
    assert _unreachable(src) == []
    assert not has_unreachable_code(src)


def test_return_inside_if_does_not_make_following_unreachable():
    # The return is a child of the `if`, not the function body; the print is
    # reachable when the condition is false.
    src = "def f(c):\n    if c:\n        return\n    print('after')\n"
    assert _unreachable(src) == []
    assert not has_unreachable_code(src)


def test_dead_code_inside_branch_only():
    # The return is a DIRECT child of the if-branch and not last → the next
    # sibling inside that branch is dead. Code after the whole `if` is reachable.
    src = (
        "def f(c):\n"
        "    if c:\n"
        "        return 1\n"
        "        z = 2\n"      # dead: inside the branch, after a direct return
        "    print('after')\n"  # reachable: sibling of the `if`
    )
    assert _unreachable(src) == [4]
    assert has_unreachable_code(src)


def test_one_finding_per_block():
    # Two distinct dead blocks → two findings (one each), in document order.
    src = (
        "def f():\n"
        "    return 1\n"
        "    a = 2\n"          # dead in f's body
        "def g():\n"
        "    raise X()\n"
        "    b = 3\n"          # dead in g's body
    )
    assert _unreachable(src) == [3, 6]


def test_only_first_statement_after_terminal_flagged():
    # Multiple dead statements in one block → a single finding at the first.
    src = "def f():\n    return 1\n    a = 2\n    b = 3\n"
    assert _unreachable(src) == [3]


def test_clean_code_has_no_unreachable_finding():
    src = "def f(x):\n    y = x + 1\n    return y\n"
    assert not has_unreachable_code(src)


def test_unreachable_on_syntax_error_is_false():
    assert not has_unreachable_code("def broken(:\n")


# --- additional detector coverage (edge / guard paths) -----------------------

def test_collection_literal_dict_list_tuple_flagged():
    # Empty dict()/list()/tuple() constructors should be flagged as a style nit.
    for call, lit in (("dict()", "{}"), ("list()", "[]"), ("tuple()", "()")):
        out = detect(f"x = {call}\n")
        flagged = [i for i in out if i.fix_kind == "collection-literal"]
        assert flagged and any(lit in i.message for i in flagged)
    # An argumentful constructor is left alone.
    assert not any(i.fix_kind == "collection-literal" for i in detect("x = dict(a=1)\n"))
    assert not any(i.fix_kind == "collection-literal" for i in detect("x = list([1])\n"))


def test_yaml_load_and_tempfile_mktemp_flagged():
    yaml_out = detect("import yaml\ndef f(s):\n    return yaml.load(s)\n")
    assert any(i.fix_kind == "yaml" and i.severity == "medium" for i in yaml_out)
    tmp_out = detect("import tempfile\ndef f():\n    return tempfile.mktemp()\n")
    assert any(i.fix_kind == "tempfile" and i.severity == "medium" for i in tmp_out)


def test_weak_hash_md5_sha1_flagged_unless_declared_non_security():
    md5 = detect("import hashlib\ndef f(b):\n    return hashlib.md5(b)\n")
    assert any(i.fix_kind == "weak-hash" for i in md5)
    sha1 = detect("import hashlib\ndef f(b):\n    return hashlib.sha1(b)\n")
    assert any(i.fix_kind == "weak-hash" for i in sha1)
    # usedforsecurity=False declares it non-security -> not flagged.
    ok = detect("import hashlib\ndef f(b):\n    return hashlib.md5(b, usedforsecurity=False)\n")
    assert not any(i.fix_kind == "weak-hash" for i in ok)


def test_assert_on_tuple_is_flagged():
    out = detect("def f(x):\n    assert (x > 0, 'bad')\n")
    assert any("assert on a tuple" in i.message and i.severity == "high" for i in out)
    # A non-tuple single-value assert is fine.
    assert not any("assert on a tuple" in i.message for i in detect("def f(x):\n    assert x > 0\n"))


def test_negated_comparison_flagged():
    from app.engine.detectors import has_negated_comparison

    assert has_negated_comparison("y = not x in items\n")
    assert has_negated_comparison("y = not x is None\n")
    # The idiomatic forms are not flagged.
    assert not has_negated_comparison("y = x not in items\n")
    assert not has_negated_comparison("y = x is not None\n")
    msgs = [i.message for i in detect("y = not x in items\n")]
    assert any("not in" in m for m in msgs)


def test_compare_to_bool_directly_flagged():
    out = detect("y = flag == True\n")
    assert any("True/False" in i.message and i.fix_kind == "" for i in out)


def test_type_comparison_suggests_isinstance():
    out = detect("y = type(x) == int\n")
    assert any("isinstance()" in i.message and i.severity == "medium" for i in out)


def test_fstring_without_placeholder_flagged():
    from app.engine.detectors import has_fstring_no_placeholder

    assert has_fstring_no_placeholder("x = f'no placeholder here'\n")
    # A real interpolation is not flagged.
    assert not has_fstring_no_placeholder("x = f'value {y}'\n")


def test_net_timeout_branches():
    from app.engine.detectors import has_network_call_without_timeout as needs_to

    # requests/httpx verbs without timeout -> flagged.
    assert needs_to("import requests\nrequests.get('http://x')\n")
    assert needs_to("import httpx\nhttpx.post('http://x', data=1)\n")
    # bare urlopen and urllib.request.urlopen -> flagged.
    assert needs_to("from urllib.request import urlopen\nurlopen('http://x')\n")
    assert needs_to("import urllib\nurllib.request.urlopen('http://x')\n")
    # timeout= present -> not flagged.
    assert not needs_to("import requests\nrequests.get('http://x', timeout=5)\n")
    # **kwargs might carry timeout -> not flagged.
    assert not needs_to("import requests\nrequests.get('http://x', **opts)\n")
    # An unknown owner / non-net verb / plain name call is left alone.
    assert not needs_to("import requests\nsession.get('http://x')\n")
    assert not needs_to("import requests\nrequests.connect('http://x')\n")
    assert not needs_to("frobnicate('http://x')\n")
    # An attribute-named non-urlopen on a deeper chain is left alone.
    assert not needs_to("import other\nother.thing.urlopen('http://x')\n")
    # A callee that is neither a Name nor an Attribute (subscript/call result)
    # is left alone — can't prove it's a network verb.
    assert not needs_to("funcs['get']('http://x')\n")
    assert not needs_to("get_client()('http://x')\n")


def test_exc_names_attribute_form_in_unreachable_handler():
    # A dotted exception type (`except mod.CustomError:`) is read via the
    # Attribute branch; a broader Exception above it still shadows the dotted one.
    src = ("def f():\n    try:\n        g()\n"
           "    except Exception:\n        pass\n"
           "    except mod.CustomError:\n        pass\n")
    assert any("unreachable except" in i.message for i in detect(src))


def test_raise_without_from_inside_nested_blocks():
    from app.engine.detectors import has_fixable_raise_without_from

    # The new raise is nested inside an if/for within the except body.
    nested_if = ("def f():\n    try:\n        g()\n    except Exception as e:\n"
                 "        if cond:\n            raise ValueError('bad')\n")
    assert has_fixable_raise_without_from(nested_if)
    nested_for = ("def f():\n    try:\n        g()\n    except Exception as e:\n"
                  "        for x in xs:\n            raise ValueError('bad')\n")
    assert has_fixable_raise_without_from(nested_for)


def test_escapes_finally_inside_if_and_with():
    def fin(src):
        return any("finally block" in i.message and i.severity == "high" for i in detect(src))

    # return guarded by an if inside finally still escapes.
    assert fin("def f():\n    try:\n        pass\n    finally:\n        if c:\n            return 1\n")
    # return inside a with-block inside finally escapes too.
    assert fin("def f():\n    try:\n        pass\n    finally:\n        with ctx():\n            return 1\n")


def test_mutable_default_via_constructor_call():
    # The dict()/list()/set() call form (not just the literal) is a mutable default.
    assert has_mutable_default("def f(x=list()):\n    return x\n")
    assert has_mutable_default("def f(x=dict()):\n    return x\n")
    assert has_mutable_default("def f(x=set()):\n    return x\n")
    # Keyword-only default with a mutable literal also counts.
    assert has_mutable_default("def f(*, x=[]):\n    return x\n")
    # A constructor with args is not the empty-collection default.
    assert has_mutable_default("def f(x=list([1])):\n    return x\n") is False


def test_self_attr_none_path_via_non_self_mutation():
    # A class-level mutable mutated through a NON-self reference yields no flag
    # (exercises the _self_attr None return for the mutation-evidence scan).
    src = ("class C:\n"
           "    items = []\n"
           "    def add(self, other, x):\n"
           "        other.items.append(x)\n")
    assert not any("mutable class attribute" in i.message for i in detect(src))


def test_security_label_substring_fallback_returns_none():
    # Unparseable AND no security needle -> the substring fallback returns None.
    assert security_label("def broken(:\n    x = 1\n") is None


def test_security_labels_all_present_most_severe_first():
    from app.engine.detectors import security_labels

    src = ("import os, pickle\n"
           "def f(c, b):\n"
           "    os.system(c)\n"
           "    eval(c)\n"
           "    return pickle.loads(b)\n")
    labels = security_labels(src)
    # eval outranks os.system outranks pickle in _SECURITY_ORDER.
    assert labels[:3] == ["eval", "os.system", "pickle"]


def test_security_labels_on_syntax_error_uses_fallback():
    from app.engine.detectors import security_labels

    # Unparseable but contains eval -> the single fallback label.
    assert security_labels("def broken(:\n    eval(x)\n") == ["eval"]
    # Unparseable and clean -> empty list.
    assert security_labels("def broken(:\n    x = 1\n") == []


def test_remaining_has_helpers():
    from app.engine.detectors import (
        has_collection_literal,
        has_fixable_raise_without_from,
        has_fstring_no_placeholder,
        has_identity_literal,
        has_negated_comparison,
    )

    assert has_identity_literal("def f(x):\n    return x is 5\n")
    assert has_fixable_raise_without_from(
        "def f():\n    try:\n        g()\n    except Exception as e:\n        raise ValueError('x')\n"
    )
    assert has_negated_comparison("y = not x in items\n")
    assert has_fstring_no_placeholder("x = f'plain'\n")
    assert has_collection_literal("x = dict()\n")
    # The clean-input negatives.
    assert has_identity_literal("def f(x):\n    return x is None\n") is False
    assert has_collection_literal("x = {}\n") is False


def test_assert_substantive_subscript_is_substantive():
    # A subscript test (not Name/Attribute/Constant/Compare/Call/BoolOp/UnaryOp)
    # falls through to the final `return True` — a real check.
    from app.engine.detectors import test_has_substantive_assertions as subst

    assert subst("def t():\n    assert data['k']\n") is True


def test_substantive_assertions_on_syntax_error_is_false():
    from app.engine.detectors import test_has_substantive_assertions as subst

    assert subst("def broken(:\n") is False
