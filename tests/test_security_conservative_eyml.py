"""The security engine is conservative on UNTESTED code: it REWRITES only when
provably behaviour-preserving, otherwise ANNOTATES (Tier-0 ``# SECURITY`` comment)
or REFUSES — it never lands broken or silently behaviour-changing Python.

An adversarial audit of the ``harden`` objective found the 14-patcher engine
(:mod:`app.execution.semantic.transforms.security`) could land:

  * a SyntaxError, by inserting a ``# SECURITY`` comment into a backslash
    line-continuation (``x = \\`` / ``# SECURITY`` / ``call()``);
  * a behaviour change, by narrowing a SWALLOWING bare ``except:`` (which may be
    catching ``SystemExit``/``KeyboardInterrupt``) to ``except Exception:``;
  * a behaviour change, by rewriting an ``os.system(...)`` whose int wait-status
    RESULT is USED into a ``subprocess.run(..., check=True)`` (CompletedProcess,
    raises on non-zero);
  * spurious unused imports, by injecting ``import subprocess``/``import shlex``
    for an ``os.system("double-quoted")`` whose call line it failed to rewrite;
  * a mis-split command, by ``shlex.split``-ing an ``os.system`` literal that
    carries a shell metacharacter (``'a && b'`` -> ``['a', '&&', 'b']``).

Each case below is now made conservative. The safe cases (a discarded, metachar-free
``os.system``; a re-raising bare except) STILL land their real fix — no over-refusal.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms import security as sec


def _new(src: str, title: str) -> str | None:
    r = sec.apply("m.py", src, title)
    return r.patch_requests[0]["new_content"] if r else None


def _kind(src: str, title: str) -> str | None:
    r = sec.apply("m.py", src, title)
    return r.transform_type if r else None


# --- P0-1: a flag must never break a backslash line-continuation -------------

def test_pickle_on_continuation_is_refused_not_syntax_error():
    # `val = \` / pickle.loads(raw) — inserting a comment before the call would
    # leave `val = \` immediately followed by a comment (a SyntaxError). The
    # flagger refuses the site rather than land non-parsing Python.
    src = "import pickle\nval = \\\n    pickle.loads(raw)\n"
    out = _new(src, "fix pickle security")
    assert out is None  # refused — nothing landed


def test_pickle_continuation_then_normal_site_flags_the_normal_site():
    # A first (continuation) site is refused, but a SECOND, well-formed pickle
    # call on a later line is still flagged — refusal is per-site, not global.
    src = (
        "import pickle\n"
        "a = \\\n"
        "    pickle.loads(x)\n"
        "b = pickle.loads(y)\n"
    )
    out = _new(src, "fix pickle security")
    assert out is not None
    ast.parse(out)  # never lands a SyntaxError
    assert "# SECURITY (Apex: untrusted pickle" in out
    # The comment annotates the well-formed (second) site, on its own line.
    assert out.count("# SECURITY") == 1


def test_sql_fstring_on_continuation_is_refused():
    src = "def q(cur, n):\n    cur.execute(\\\n        f'select {n}')\n"
    out = _new(src, "fix sql security")
    # Either refused outright, or (if it annotates) the result must still parse.
    if out is not None:
        ast.parse(out)


def test_mktemp_on_continuation_is_refused_or_parses():
    src = "import tempfile\np = \\\n    tempfile.mktemp()\n"
    out = _new(src, "fix tempfile security")
    if out is not None:
        ast.parse(out)


# --- P1-1: bare except — narrow only when it re-raises -----------------------

def test_bare_except_swallow_is_annotated_not_narrowed():
    src = "try:\n    work()\nexcept:\n    pass\n"
    out = _new(src, "fix bare except security")
    assert _kind(src, "fix bare except security") == "flag_bare_except"
    assert out is not None
    assert "except Exception:" not in out  # behaviour preserved (still bare)
    assert "# SECURITY (Apex: bare except" in out
    ast.parse(out)


def test_bare_except_reraise_is_narrowed():
    # `except: raise` re-raises the active exception, so narrowing to Exception is
    # behaviour-equivalent on that path — the safe rewrite still lands.
    src = "try:\n    work()\nexcept:\n    raise\n"
    out = _new(src, "fix bare except security")
    assert _kind(src, "fix bare except security") == "bare_except_to_exception"
    assert out is not None and "except Exception:" in out


def test_bare_except_reraise_nested_in_if_is_narrowed():
    src = "try:\n    work()\nexcept:\n    if cond:\n        raise\n"
    out = _new(src, "fix bare except security")
    assert out is not None and "except Exception:" in out


def test_bare_except_reraise_inside_nested_function_is_not_treated_as_reraise():
    # A `raise` inside a nested function fires later, not during the handler, so
    # the handler still SWALLOWS — it must be annotated, not narrowed.
    src = (
        "try:\n"
        "    work()\n"
        "except:\n"
        "    def later():\n"
        "        raise\n"
        "    pass\n"
    )
    out = _new(src, "fix bare except security")
    assert out is not None
    assert "except Exception:" not in out
    assert "# SECURITY (Apex: bare except" in out


# --- P1-2: os.system — rewrite only when the result is discarded -------------

def test_os_system_discarded_is_rewritten():
    src = "import os\nos.system(cmd)\n"
    out = _new(src, "fix os.system security")
    assert out is not None
    assert "subprocess.run(shlex.split(cmd), check=True)" in out
    assert "os.system(" not in out
    ast.parse(out)


def test_os_system_assigned_result_is_annotated():
    # `rc = os.system(cmd)`: rc is the int wait-status; subprocess.run returns a
    # CompletedProcess (always truthy) and check=True raises on non-zero, so the
    # rewrite would change semantics — annotate instead.
    src = "import os\ndef f(cmd):\n    rc = os.system(cmd)\n    return rc\n"
    out = _new(src, "fix os.system security")
    assert out is not None
    assert "shlex.split" not in out               # NOT rewritten
    assert "import subprocess" not in out          # NO spurious import
    assert "import shlex" not in out
    assert "rc = os.system(cmd)" in out            # call unchanged
    assert "# SECURITY (Apex: os.system" in out
    ast.parse(out)


def test_os_system_in_if_test_is_annotated():
    src = "import os\ndef f(cmd):\n    if os.system(cmd):\n        pass\n"
    out = _new(src, "fix os.system security")
    assert out is not None
    assert "shlex.split" not in out
    assert "if os.system(cmd):" in out  # call unchanged
    assert "# SECURITY (Apex: os.system" in out
    ast.parse(out)


def test_os_system_in_comparison_is_annotated():
    src = "import os\ndef f(cmd):\n    ok = os.system(cmd) == 0\n    return ok\n"
    out = _new(src, "fix os.system security")
    assert out is not None
    assert "shlex.split" not in out
    assert "os.system(cmd) == 0" in out  # call unchanged
    assert "# SECURITY (Apex: os.system" in out
    ast.parse(out)


# --- P1-3: os.system double-quoted literal — no spurious imports -------------

def test_os_system_double_quoted_literal_rewrites_without_spurious_imports():
    # repr('ls') == "'ls'" (single quotes) would miss the double-quoted call and
    # leave it unchanged while still injecting imports (F401). The fix matches the
    # exact source segment, so the call IS rewritten and the imports are real.
    src = 'import os\nos.system("ls")\n'
    out = _new(src, "fix os.system security")
    assert out is not None
    assert 'subprocess.run(shlex.split("ls"), check=True)' in out
    assert 'os.system("ls")' not in out
    # imports present BUT actually used (not orphaned F401).
    assert "import subprocess" in out
    assert "import shlex" in out
    ast.parse(out)


def test_os_system_double_quoted_unchanged_line_injects_no_imports():
    # Defence-in-depth: if (hypothetically) the call line were NOT changed, no
    # subprocess/shlex import may be injected. We assert the invariant directly:
    # whenever the output still contains `os.system(`, it must NOT have grown an
    # import (no F401). For the double-quoted discarded case the call IS rewritten,
    # so this holds vacuously; the assertion guards the contract.
    src = 'import os\nos.system("ls")\n'
    out = _new(src, "fix os.system security")
    assert out is not None
    if "os.system(" in out:
        assert "import subprocess" not in out
        assert "import shlex" not in out


# --- P2-a: os.system shell-metachar literal — annotate, don't mis-split ------

def test_os_system_metachar_literal_is_annotated():
    src = 'import os\nos.system("a && b")\n'
    out = _new(src, "fix os.system security")
    assert out is not None
    assert "shlex.split" not in out              # never mis-split a && b
    assert "import subprocess" not in out
    assert 'os.system("a && b")' in out          # call unchanged
    assert "# SECURITY (Apex: os.system" in out
    ast.parse(out)


def test_os_system_pipe_literal_is_annotated():
    src = "import os\nos.system('cat x | grep y')\n"
    out = _new(src, "fix os.system security")
    assert out is not None
    assert "shlex.split" not in out
    assert "# SECURITY (Apex: os.system" in out


def test_os_system_redirection_literal_is_annotated():
    src = "import os\nos.system('echo hi > out')\n"
    out = _new(src, "fix os.system security")
    assert out is not None
    assert "shlex.split" not in out
    assert "# SECURITY (Apex: os.system" in out


def test_os_system_plain_literal_is_still_rewritten():
    # A metachar-FREE discarded literal stays the safe rewrite (no over-refusal).
    src = "import os\nos.system('ls -la /tmp')\n"
    out = _new(src, "fix os.system security")
    assert out is not None
    assert "subprocess.run(shlex.split('ls -la /tmp'), check=True)" in out
    ast.parse(out)


# --- P2-b: eval Name/Call args are narrowed (docstring-aligned behaviour) -----

def test_eval_name_arg_is_narrowed_to_literal_eval():
    # eval(name): value unknown statically, so narrow to literal_eval (which raises
    # on a non-literal at runtime — the intended hardening). No behaviour change to
    # the patcher; this pins the documented behaviour.
    src = "def f(data):\n    return eval(data)\n"
    out = _new(src, "fix eval security")
    assert out is not None
    assert "ast.literal_eval(data)" in out
    assert "import ast" in out
    ast.parse(out)


def test_eval_call_arg_is_narrowed_to_literal_eval():
    src = "def f():\n    return eval(get())\n"
    out = _new(src, "fix eval security")
    assert out is not None
    assert "ast.literal_eval(get())" in out
    ast.parse(out)


def test_eval_nonliteral_string_still_declined():
    # The literal-string guard is unchanged: a runtime-expression string literal is
    # NOT rewritten (literal_eval would always crash) — no spurious import ast.
    src = 'def f(a, b):\n    return eval("a * b")\n'
    out = _new(src, "fix eval security")
    assert out is None


# --- idempotency of the new annotate-only paths ------------------------------

def test_os_system_annotation_is_idempotent():
    src = "import os\ndef f(cmd):\n    rc = os.system(cmd)\n    return rc\n"
    once = _new(src, "fix os.system security")
    assert once is not None
    assert sec.apply("m.py", once, "fix os.system security") is None
