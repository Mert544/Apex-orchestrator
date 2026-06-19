"""Detection-breadth: async DB SQL sinks, str.format() SQLi, hardcoded DEBUG.

Closes red-team gaps in the central detector (``app/engine/detectors.py``):

  1. SQL injection via the realistic async/driver fetch verbs
     (asyncpg / ``databases``: ``fetch``/``fetchrow``/``fetchval``/``fetchmany``),
     inline AND assigned-then-passed, plus the previously-missed
     ``str.format()`` and ``"..." + var`` taint into any sink.
  2. A hardcoded ``DEBUG = True`` / ``debug = True`` production-debug flag.

Each capability is proven three ways, mirroring the sibling detector suites:
(a) the detector fires on the vulnerable form with the right severity / locus /
routing fix_kind; (b) it does NOT fire on the safe parameterized / non-SQL /
constant form (zero false positives); (c) the SQL label still flows through the
``security_label`` query the bridge consumes.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

from app.engine.detectors import (
    detect,
    has_debug_flag,
    security_label,
)


def _findings(src: str):
    return [(i.line, i.category, i.severity, i.fix_kind, i.message) for i in detect(src)]


def _sql(src: str):
    return [i for i in detect(src) if i.fix_kind == "sql"]


# --- async / driver fetch sinks (asyncpg / databases) ------------------------

def test_fetchrow_inline_fstring_flagged():
    src = (
        "async def q(conn, uid):\n"
        '    return await conn.fetchrow(f"SELECT * FROM users WHERE id={uid}")\n'
    )
    out = _sql(src)
    assert len(out) == 1
    f = out[0]
    assert (f.line, f.category, f.severity, f.fix_kind) == (2, "security", "high", "sql")
    assert security_label(src) == "sql"


def test_all_fetch_verbs_flagged_inline():
    for verb in ("fetch", "fetchrow", "fetchval", "fetchmany"):
        src = (
            "async def q(conn, uid):\n"
            f'    return await conn.{verb}(f"SELECT name FROM t WHERE id={{uid}}")\n'
        )
        assert security_label(src) == "sql", verb


def test_fetch_assigned_then_passed_flagged():
    # q = f"...{uid}"; conn.fetch(q) — resolved through the assignment map.
    src = (
        "async def q(conn, uid):\n"
        '    sql = f"SELECT * FROM users WHERE id={uid}"\n'
        "    return await conn.fetch(sql)\n"
    )
    out = _sql(src)
    assert len(out) == 1
    assert out[0].line == 3  # flagged at the sink call, not the assignment
    assert security_label(src) == "sql"


def test_fetchrow_parameterized_not_flagged():
    # asyncpg parameter placeholders ($1) — safe, must NOT flag.
    src = (
        "async def q(conn, uid):\n"
        '    return await conn.fetchrow("SELECT * FROM users WHERE id=$1", uid)\n'
    )
    assert _sql(src) == []
    assert security_label(src) is None


def test_non_sql_fetch_fstring_not_flagged():
    # A generically-named .fetch() on a non-DB object with an f-string that is
    # not SQL must not be flagged (precision guard against flooding).
    src = (
        "def pull(queue, job):\n"
        '    return queue.fetch(f"job {job}")\n'
    )
    assert _sql(src) == []
    assert security_label(src) is None


# --- str.format() taint ------------------------------------------------------

def test_format_into_execute_flagged():
    src = (
        "def q(cur, uid):\n"
        '    cur.execute("SELECT * FROM users WHERE id={}".format(uid))\n'
    )
    out = _sql(src)
    assert len(out) == 1
    assert (out[0].line, out[0].fix_kind) == (2, "sql")
    assert security_label(src) == "sql"


def test_format_into_fetchval_flagged():
    src = (
        "async def q(conn, uid):\n"
        '    return await conn.fetchval("SELECT n FROM t WHERE id={}".format(uid))\n'
    )
    assert security_label(src) == "sql"


def test_format_assigned_then_passed_flagged():
    src = (
        "def q(cur, uid):\n"
        '    sql = "SELECT * FROM users WHERE id={}".format(uid)\n'
        "    cur.execute(sql)\n"
    )
    out = _sql(src)
    assert len(out) == 1
    assert out[0].line == 3


def test_format_with_literal_arg_not_flagged():
    # A pure-literal format produces a constant string — no taint, no flag.
    src = (
        "def q(cur):\n"
        '    cur.execute("SELECT * FROM t WHERE n={}".format(\'admin\'))\n'
    )
    assert _sql(src) == []


def test_non_sql_format_not_flagged():
    # "...{}".format(name) that is not SQL feeding a non-sink must not flag.
    src = "def greet(name):\n    return \"hi {}\".format(name)\n"
    assert _sql(src) == []
    assert security_label(src) is None


# --- string concat taint -----------------------------------------------------

def test_concat_into_execute_flagged():
    src = (
        "def q(cur, uid):\n"
        '    cur.execute("SELECT * FROM users WHERE id=" + uid)\n'
    )
    out = _sql(src)
    assert len(out) == 1
    assert out[0].fix_kind == "sql"


# --- classic-sink behavior preserved (no duplicate, no regression) -----------

def test_classic_inline_fstring_single_finding():
    # The historical execute(f"...") finding must still fire EXACTLY once — the
    # broadened pass deliberately skips this shape to avoid a duplicate.
    src = "def q(cur, uid):\n    cur.execute(f\"SELECT {uid}\")\n"
    assert len(_sql(src)) == 1


def test_parameterized_execute_not_flagged():
    src = "def q(cur, uid):\n    cur.execute(\"SELECT * FROM t WHERE id=?\", (uid,))\n"
    assert _sql(src) == []
    assert security_label(src) is None


# --- hardcoded DEBUG flag ----------------------------------------------------

def test_debug_true_flagged():
    src = "DEBUG = True\n"
    out = detect(src)
    assert len(out) == 1
    f = out[0]
    assert (f.line, f.category, f.severity, f.fix_kind) == (1, "bug", "low", "debug-flag")
    assert has_debug_flag(src)


def test_lowercase_debug_true_flagged():
    assert has_debug_flag("debug = True\n")


def test_debug_false_not_flagged():
    src = "DEBUG = False\n"
    assert not has_debug_flag(src)
    assert detect(src) == []


def test_debug_call_not_flagged():
    # Config-driven debug (a call / attribute) is not a hardcoded flag.
    assert not has_debug_flag("debug = get_flag()\n")
    assert not has_debug_flag("DEBUG = os.environ.get('DEBUG')\n")


def test_debug_annotated_true_flagged():
    assert has_debug_flag("DEBUG: bool = True\n")


def test_debug_inside_string_literal_not_flagged():
    # A "DEBUG = True" that lives inside a string constant is not a real
    # module-level assignment — must not be flagged (it is not parsed as code).
    src = "config = '''DEBUG = True'''\n"
    assert not has_debug_flag(src)


# --- determinism -------------------------------------------------------------

def test_detection_is_deterministic():
    src = (
        "DEBUG = True\n"
        "async def q(conn, uid):\n"
        '    sql = f"SELECT * FROM users WHERE id={uid}"\n'
        "    return await conn.fetch(sql)\n"
    )
    first = _findings(src)
    for _ in range(5):
        assert _findings(src) == first
