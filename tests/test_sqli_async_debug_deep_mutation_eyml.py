"""Deep-mutation hardening for the broadened SQLi + DEBUG detection.

Targets the Batch-2 detection breadth in ``app/engine/detectors.py``:

  * the broadened SQL-injection pass (``_detect_sql_injection`` /
    ``_tainted_sql_for_sink`` / ``_is_tainted_sql_string`` /
    ``_format_call_template`` / ``_looks_like_sql`` / ``_collect_assignments``):
    the async ``fetch``/``fetchrow``/``fetchval``/``fetchmany`` sinks,
    ``str.format()`` taint, ``"..." + var`` concat — inline AND
    assigned-then-passed — each flagging ONLY when the text ``_looks_like_sql``,
    and the classic inline-f-string rule NOT double-firing with the new pass;
  * the ``DEBUG = True`` flag (``_detect_debug_flag``): ``True`` flags,
    ``False`` / a call / an attribute do not.

Each shape pins its boolean / count / locus EXACTLY so a flipped membership
test, a dropped keyword, or a relaxed guard fails a test. Deep-mutation
companion to ``test_sqli_async_debug_detection_eyml.py``.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

from app.engine.detectors import (
    detect,
    has_debug_flag,
    security_label,
    _looks_like_sql,
)


def _sql(src: str):
    return [i for i in detect(src) if i.fix_kind == "sql"]


def _debug(src: str):
    return [i for i in detect(src) if i.fix_kind == "debug-flag"]


# --- _looks_like_sql: keyword membership, case-insensitive -------------------

def test_looks_like_sql_select_true():
    assert _looks_like_sql("SELECT * FROM t") is True


def test_looks_like_sql_is_case_insensitive():
    assert _looks_like_sql("select * from t") is True
    assert _looks_like_sql("Insert Into t") is True


def test_looks_like_sql_non_sql_false():
    assert _looks_like_sql("hello world") is False


def test_looks_like_sql_each_keyword_family():
    for kw in ("select ", "insert ", "update ", "delete ", "create table",
               "drop table", "alter table", "union ", "order by", "group by"):
        assert _looks_like_sql(f"x {kw} y") is True, kw


def test_looks_like_sql_bare_word_without_space_not_matched():
    # The keywords carry a trailing space ("select "), so a bare "select" with no
    # following token does not match — pins the exact token, not a loose stem.
    assert _looks_like_sql("preselected") is False


# --- async / driver fetch sinks: each verb flags exactly once ----------------

def test_each_fetch_verb_inline_fstring_flags_once():
    for verb in ("fetch", "fetchrow", "fetchval", "fetchmany"):
        src = (
            "async def q(conn, uid):\n"
            f'    return await conn.{verb}(f"SELECT name FROM t WHERE id={{uid}}")\n'
        )
        out = _sql(src)
        assert len(out) == 1, verb
        assert (out[0].line, out[0].category, out[0].severity, out[0].fix_kind) == \
            (2, "security", "high", "sql"), verb
        assert security_label(src) == "sql", verb


def test_fetch_assigned_then_passed_flags_at_sink_line():
    src = (
        "async def q(conn, uid):\n"
        '    sql = f"SELECT * FROM users WHERE id={uid}"\n'
        "    return await conn.fetch(sql)\n"
    )
    out = _sql(src)
    assert len(out) == 1
    assert out[0].line == 3  # flagged at the sink, not the assignment


def test_fetch_parameterized_not_flagged():
    src = (
        "async def q(conn, uid):\n"
        '    return await conn.fetchrow("SELECT * FROM users WHERE id=$1", uid)\n'
    )
    assert _sql(src) == []
    assert security_label(src) is None


def test_non_sql_fetch_fstring_not_flagged():
    # A generic .fetch() with a non-SQL f-string — the _looks_like_sql guard must
    # suppress it. Flip the guard to True-always and this fails.
    src = "def pull(queue, job):\n    return queue.fetch(f\"job {job}\")\n"
    assert _sql(src) == []
    assert security_label(src) is None


def test_fetch_fstring_without_placeholder_not_flagged():
    # A constant f-string (no FormattedValue) is not tainted.
    src = "async def q(conn):\n    return await conn.fetch(f\"SELECT 1 FROM t\")\n"
    assert _sql(src) == []


# --- str.format() taint ------------------------------------------------------

def test_format_into_execute_flags_once_at_call_line():
    src = (
        "def q(cur, uid):\n"
        '    cur.execute("SELECT * FROM users WHERE id={}".format(uid))\n'
    )
    out = _sql(src)
    assert len(out) == 1
    assert (out[0].line, out[0].fix_kind) == (2, "sql")


def test_format_into_fetchval_flags():
    src = (
        "async def q(conn, uid):\n"
        '    return await conn.fetchval("SELECT n FROM t WHERE id={}".format(uid))\n'
    )
    assert len(_sql(src)) == 1
    assert security_label(src) == "sql"


def test_format_keyword_arg_taint_flags():
    # The taint test also considers keyword arguments to format().
    src = (
        "def q(cur, uid):\n"
        '    cur.execute("SELECT * FROM t WHERE id={id}".format(id=uid))\n'
    )
    assert len(_sql(src)) == 1


def test_format_assigned_then_passed_flags_at_sink_line():
    src = (
        "def q(cur, uid):\n"
        '    sql = "SELECT * FROM users WHERE id={}".format(uid)\n'
        "    cur.execute(sql)\n"
    )
    out = _sql(src)
    assert len(out) == 1
    assert out[0].line == 3


def test_format_pure_literal_arg_not_flagged():
    # All-constant format args -> constant string -> not tainted.
    src = (
        "def q(cur):\n"
        "    cur.execute(\"SELECT * FROM t WHERE n={}\".format('admin'))\n"
    )
    assert _sql(src) == []


def test_non_sql_format_not_flagged():
    src = "def greet(name):\n    return \"hi {}\".format(name)\n"
    assert _sql(src) == []
    assert security_label(src) is None


def test_format_on_non_literal_receiver_not_flagged():
    # The receiver of .format must be a string literal; tmpl.format(uid) is not.
    src = (
        "def q(cur, uid, tmpl):\n"
        "    cur.execute(tmpl.format(uid))\n"
    )
    assert _sql(src) == []


# --- string concat taint -----------------------------------------------------

def test_concat_into_execute_flags():
    src = "def q(cur, uid):\n    cur.execute(\"SELECT * FROM users WHERE id=\" + uid)\n"
    out = _sql(src)
    assert len(out) == 1
    assert out[0].fix_kind == "sql"


def test_concat_var_on_left_flags():
    # Either side may carry the string literal; the var on the left still taints.
    src = "def q(cur, uid):\n    cur.execute(uid + \" FROM users WHERE 1\")\n"
    assert len(_sql(src)) == 1


def test_concat_assigned_then_passed_to_fetch_flags():
    src = (
        "async def q(conn, uid):\n"
        '    sql = "SELECT * FROM users WHERE id=" + uid\n'
        "    return await conn.fetch(sql)\n"
    )
    out = _sql(src)
    assert len(out) == 1
    assert out[0].line == 3


def test_non_sql_concat_not_flagged():
    # A non-SQL concat into a sink must not flag (the _looks_like_sql guard).
    src = "def q(cur, name):\n    cur.execute(\"hello \" + name)\n"
    assert _sql(src) == []


# --- classic-sink behaviour preserved (no double-fire) -----------------------

def test_classic_inline_fstring_single_finding():
    # The historical execute(f"...") finding fires EXACTLY once — the broadened
    # pass deliberately skips this shape. Flip the skip and you get 2.
    src = "def q(cur, uid):\n    cur.execute(f\"SELECT {uid}\")\n"
    assert len(_sql(src)) == 1


def test_classic_inline_fstring_non_sql_still_single():
    # The classic per-node rule fires on ANY f-string into execute (no SQL-look
    # guard), so a non-SQL f-string into execute is still a single finding, not
    # zero and not two.
    src = "def q(cur, x):\n    cur.execute(f\"value {x}\")\n"
    assert len(_sql(src)) == 1


def test_parameterized_execute_not_flagged():
    src = "def q(cur, uid):\n    cur.execute(\"SELECT * FROM t WHERE id=?\", (uid,))\n"
    assert _sql(src) == []
    assert security_label(src) is None


def test_cursor_classic_sink_inline_fstring_single():
    src = "def q(db, uid):\n    db.cursor(f\"SELECT {uid}\")\n"
    assert len(_sql(src)) == 1


# --- DEBUG flag --------------------------------------------------------------

def test_debug_true_flags_once_exact_record():
    src = "DEBUG = True\n"
    out = _debug(src)
    assert len(out) == 1
    f = out[0]
    assert (f.line, f.category, f.severity, f.fix_kind) == (1, "bug", "low", "debug-flag")
    assert has_debug_flag(src) is True


def test_lowercase_debug_true_flags():
    assert has_debug_flag("debug = True\n") is True


def test_debug_annotated_true_flags():
    assert has_debug_flag("DEBUG: bool = True\n") is True


def test_debug_false_does_not_flag():
    assert has_debug_flag("DEBUG = False\n") is False
    assert _debug("DEBUG = False\n") == []


def test_debug_assigned_call_does_not_flag():
    assert has_debug_flag("debug = get_flag()\n") is False


def test_debug_assigned_attribute_does_not_flag():
    assert has_debug_flag("DEBUG = settings.DEBUG\n") is False


def test_debug_value_one_does_not_flag():
    # The guard is `value is True`, not a truthy check: 1 must NOT flag.
    assert has_debug_flag("DEBUG = 1\n") is False


def test_unrelated_name_true_does_not_flag():
    # Only DEBUG/debug names are flagged; VERBOSE = True is not.
    assert has_debug_flag("VERBOSE = True\n") is False


def test_debug_inside_string_literal_not_flagged():
    assert has_debug_flag("config = '''DEBUG = True'''\n") is False


# --- determinism -------------------------------------------------------------

def test_detection_is_deterministic():
    src = (
        "DEBUG = True\n"
        "async def q(conn, uid):\n"
        '    sql = f"SELECT * FROM users WHERE id={uid}"\n'
        "    return await conn.fetch(sql)\n"
    )
    first = [(i.line, i.fix_kind, i.severity) for i in detect(src)]
    for _ in range(5):
        assert [(i.line, i.fix_kind, i.severity) for i in detect(src)] == first
