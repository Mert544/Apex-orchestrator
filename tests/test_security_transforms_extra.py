from __future__ import annotations

from app.execution.semantic.transforms import security as sec


def _new(src: str, title: str) -> str | None:
    r = sec.apply("m.py", src, title)
    return r.patch_requests[0]["new_content"] if r else None


# --- apply() dispatch + parse guard ------------------------------------------

def test_syntax_error_returns_none():
    assert sec.apply("m.py", "def broken(:\n", "fix eval security") is None


def test_unknown_title_returns_none():
    assert sec.apply("m.py", "x = 1\n", "do something unrelated") is None


# --- eval --------------------------------------------------------------------

def test_eval_rewritten_to_literal_eval():
    out = _new("def f(s):\n    return eval(s)\n", "fix eval security")
    assert out and "ast.literal_eval(s)" in out


def test_eval_already_literal_eval_is_noop():
    assert _new("import ast\ndef f(s):\n    return ast.literal_eval(s)\n", "fix eval security") is None


def test_eval_absent_is_noop():
    assert _new("def f(s):\n    return s\n", "fix eval security") is None


# --- os.system ---------------------------------------------------------------

def test_os_system_absent_is_noop():
    assert _new("import os\ndef f():\n    return os.getcwd()\n", "fix os.system security") is None


# --- bare except -------------------------------------------------------------

def test_bare_except_rewritten():
    # Re-raising handler: narrowing the bare catch to Exception is behaviour-safe.
    out = _new("try:\n    x = 1\nexcept:\n    raise\n", "fix bare except security")
    assert out and "except Exception:" in out


def test_bare_except_that_swallows_is_annotated_not_narrowed():
    # Swallowing handler: a narrow to Exception would change behaviour (it might
    # be catching SystemExit/KeyboardInterrupt), so annotate instead of rewrite.
    out = _new("try:\n    x = 1\nexcept:\n    pass\n", "fix bare except security")
    assert out is not None
    assert "except Exception:" not in out
    assert "# SECURITY (Apex: bare except" in out


def test_bare_except_swallow_flag_is_idempotent():
    # Re-flagging an already-annotated swallowing bare except is a no-op (so the
    # harden ladder converges instead of stacking comments).
    src = "try:\n    x = 1\nexcept:\n    pass\n"
    once = _new(src, "fix bare except security")
    assert once is not None
    assert sec.apply("m.py", once, "fix bare except security") is None


def test_bare_except_absent_is_noop():
    assert _new("try:\n    x = 1\nexcept ValueError:\n    pass\n", "fix bare except security") is None


# --- pickle (flag, idempotent) -----------------------------------------------

def test_pickle_flagged_with_comment():
    out = _new("import pickle\ndef f(b):\n    return pickle.loads(b)\n", "fix pickle security")
    assert out and "Apex: untrusted pickle" in out


def test_pickle_flag_is_idempotent():
    src = "import pickle\ndef f(b):\n    return pickle.loads(b)\n"
    once = _new(src, "fix pickle security")
    assert once is not None
    # Re-running on the already-flagged source makes no further change.
    assert sec.apply("m.py", once, "fix pickle security") is None


def test_pickle_absent_is_noop():
    assert _new("def f(b):\n    return b\n", "fix pickle security") is None


# --- sql f-string (flag) -----------------------------------------------------

def test_sql_fstring_flagged():
    src = "def q(cur, n):\n    cur.execute(f'select * from t where x={n}')\n"
    out = _new(src, "fix sql security")
    assert out is not None  # a warning/flag was added


def test_sql_flag_is_idempotent():
    src = "def q(cur, n):\n    cur.execute(f'select * from t where x={n}')\n"
    once = _new(src, "fix sql security")
    assert once is not None
    # Re-running must not stack a second warning (regression guard).
    assert sec.apply("m.py", once, "fix sql security") is None


def test_sql_plain_query_is_noop():
    src = "def q(cur):\n    cur.execute('select 1')\n"
    assert _new(src, "fix sql security") is None


# --- yaml --------------------------------------------------------------------

def test_yaml_load_to_safe_load():
    out = _new("import yaml\ndef f(s):\n    return yaml.load(s)\n", "fix yaml security")
    assert out and "yaml.safe_load(s)" in out


def test_yaml_with_explicit_loader_is_noop():
    src = "import yaml\ndef f(s):\n    return yaml.load(s, Loader=yaml.SafeLoader)\n"
    assert _new(src, "fix yaml security") is None
