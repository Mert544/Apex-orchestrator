"""Contract for the ``sql_text_wrap`` transform (detect -> landing fix).

A STATIC raw-SQL literal reaching a DB sink (``session.execute("SELECT ...")`` /
``await conn.execute("...")``) is wrapped in SQLAlchemy ``text(...)`` and the
``from sqlalchemy import text`` import is added — the API-supported form. A
DYNAMIC query (f-string / ``.format()`` / ``%`` / concat / a bare name) is REFUSED
(no rewrite): those can't be safely auto-parametrized, so they stay FLAGGED.

Invariants locked here: idempotency (re-wrapping is a no-op), comment-preservation
via the splice path, byte-determinism, and the Tier-1 classification (the fix is
behaviour-adjacent, so it earns the coverage gate — withheld when uncovered).

Deterministic, stdlib + pytest only, offline.
"""

from __future__ import annotations

import ast

from app.execution.risk_tiers import TIER_BY_ACTION, tier_for, tier_for_transform
from app.execution.semantic.transforms.sql_text_wrap import apply


class TestStaticLiteralWrapped:
    def test_static_execute_is_wrapped_in_text(self) -> None:
        src = 'session.execute("SELECT 1")\n'
        result = apply("t.py", src, "")
        assert result is not None
        assert result.transform_type == "sql_text_wrap"
        out = result.patch_requests[0]["new_content"]
        assert "session.execute(text('SELECT 1'))" in out
        ast.parse(out)

    def test_import_is_added(self) -> None:
        src = 'session.execute("SELECT 1")\n'
        out = apply("t.py", src, "").patch_requests[0]["new_content"]
        assert "from sqlalchemy import text" in out
        # The import is added exactly once.
        assert out.count("from sqlalchemy import text") == 1

    def test_await_conn_execute_is_wrapped(self) -> None:
        src = 'async def f(conn):\n    await conn.execute("SELECT 2")\n'
        out = apply("t.py", src, "").patch_requests[0]["new_content"]
        assert "await conn.execute(text('SELECT 2'))" in out
        ast.parse(out)

    def test_fetch_sink_is_wrapped(self) -> None:
        src = 'await db.fetch("SELECT * FROM t")\n'
        out = apply("t.py", src, "").patch_requests[0]["new_content"]
        assert "db.fetch(text('SELECT * FROM t'))" in out

    def test_existing_text_import_not_duplicated(self) -> None:
        src = 'from sqlalchemy import text\nsession.execute("SELECT 1")\n'
        out = apply("t.py", src, "").patch_requests[0]["new_content"]
        assert out.count("from sqlalchemy import text") == 1
        assert "execute(text('SELECT 1'))" in out

    def test_import_lands_after_future_import(self) -> None:
        src = (
            "from __future__ import annotations\n"
            'session.execute("SELECT 1")\n'
        )
        out = apply("t.py", src, "").patch_requests[0]["new_content"]
        lines = out.splitlines()
        # future import must remain the first statement
        assert lines[0] == "from __future__ import annotations"
        assert "from sqlalchemy import text" in out
        ast.parse(out)

    def test_patch_records_expected_old_content(self) -> None:
        src = 'session.execute("SELECT 1")\n'
        req = apply("t.py", src, "").patch_requests[0]
        assert req["expected_old_content"] == src
        assert req["path"] == "t.py"


class TestDynamicSqlRefused:
    def test_fstring_is_not_wrapped(self) -> None:
        src = 'x = 1\nsession.execute(f"SELECT {x}")\n'
        assert apply("t.py", src, "") is None

    def test_format_is_not_wrapped(self) -> None:
        src = 'x = 1\nsession.execute("SELECT {}".format(x))\n'
        assert apply("t.py", src, "") is None

    def test_percent_is_not_wrapped(self) -> None:
        src = 'x = 1\nsession.execute("SELECT %s" % x)\n'
        assert apply("t.py", src, "") is None

    def test_concat_is_not_wrapped(self) -> None:
        src = 'x = 1\nsession.execute("SELECT " + str(x))\n'
        assert apply("t.py", src, "") is None

    def test_bare_name_is_not_wrapped(self) -> None:
        src = 'q = "SELECT 1"\nsession.execute(q)\n'
        assert apply("t.py", src, "") is None

    def test_non_sink_call_left_alone(self) -> None:
        src = 'queue.process("SELECT 1")\n'
        assert apply("t.py", src, "") is None


class TestIdempotent:
    def test_second_apply_is_noop(self) -> None:
        src = 'session.execute("SELECT 1")\n'
        out = apply("t.py", src, "").patch_requests[0]["new_content"]
        assert apply("t.py", out, "") is None

    def test_already_text_wrapped_literal_is_noop(self) -> None:
        src = 'from sqlalchemy import text\nsession.execute(text("SELECT 1"))\n'
        assert apply("t.py", src, "") is None


class TestCommentPreserved:
    def test_trailing_comment_survives(self) -> None:
        src = 'session.execute("SELECT 1")  # run the query\n'
        out = apply("t.py", src, "").patch_requests[0]["new_content"]
        assert "# run the query" in out
        assert "execute(text('SELECT 1'))" in out

    def test_preceding_comment_survives(self) -> None:
        src = '# important query\nsession.execute("SELECT 1")\n'
        out = apply("t.py", src, "").patch_requests[0]["new_content"]
        assert "# important query" in out
        assert "execute(text('SELECT 1'))" in out


class TestDeterminism:
    def test_same_input_same_output(self) -> None:
        src = 'session.execute("SELECT 1")\nawait db.fetch("SELECT 2")\n'
        first = apply("t.py", src, "").patch_requests[0]["new_content"]
        for _ in range(5):
            assert apply("t.py", src, "").patch_requests[0]["new_content"] == first

    def test_syntax_error_returns_none(self) -> None:
        assert apply("t.py", "def (:\n", "") is None


class TestTierClassification:
    def test_action_is_registered_tier1(self) -> None:
        assert TIER_BY_ACTION["sql_text_wrap"] == 1
        assert tier_for("sql_text_wrap") == 1

    def test_tier_is_at_least_one(self) -> None:
        # Behaviour-adjacent: it must earn the coverage gate, never auto-apply
        # blind as a Tier-0 additive change.
        assert tier_for("sql_text_wrap") >= 1

    def test_transform_type_is_not_an_annotation_flag(self) -> None:
        # The wrap CHANGES the call's argument (behaviour-adjacent), so unlike the
        # comment-only SQL FLAG it must NOT be demoted to Tier 0.
        assert tier_for_transform("sql_text_wrap", "sql_text_wrap") == 1
