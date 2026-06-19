"""Deep mutation-hardening for the broadened SQLi shapes and Jinja XSS signals.

Two detectors gained breadth this session; each new shape's boolean is pinned
EXACTLY so a flipped comparison / dropped branch fails a test.

1. ``security_agent._sql_injection_findings`` (+ the AST helpers it shares) flag
   three tainted-SQL shapes feeding an ``execute()``/``cursor()`` sink:
     * an INLINE f-string with an interpolation,
     * an INLINE string ``+``/``%`` concat mixing a literal with a value,
     * an ASSIGNED f-string/concat variable passed by name (assigned-then-passed).
   A PARAMETERIZED query (plain literal + a params tuple) must NOT flag.

2. ``polyglot_findings._scan_html`` flags Jinja escaping bypasses:
     * ``{{ ... | safe }}`` -> ``jinja-safe`` (XSS);
     * ``{% autoescape false %}`` -> ``jinja-autoescape-off``;
     * a ``| safe`` inside a <script>/attribute context -> the stronger
       ``jinja-safe-context`` (and the plain ``jinja-safe`` then does NOT also
       fire — ``elif``);
   while a normal ``{{ x }}`` (auto-escaped) and ``{% autoescape true %}`` match
   nothing.

Determinism: assertions are exact (risk_type strings, finding counts, kind sets,
booleans); no time / ordering reliance.
"""
from __future__ import annotations

import ast

from app.agents.skills.security_agent import (
    SecurityAgent,
    _is_string_concat_binop,
    _joinedstr_has_nonliteral,
    _sql_injection_findings,
)
from app.engine.polyglot_findings import _scan_html


def _sql_risk_types(source: str) -> list[str]:
    """Run the real AST scan and return the sql_injection risk_types found."""
    agent = SecurityAgent()
    findings = agent._scan_ast("db.py", source)
    return [f["risk_type"] for f in findings if f["risk_type"] == "sql_injection"]


# ---------------------------------------------------------------------------
# SQLi shape 1 — inline f-string with an interpolation feeding execute().
# ---------------------------------------------------------------------------
def test_inline_fstring_in_execute_flags():
    src = 'cursor.execute(f"SELECT * FROM users WHERE id = {uid}")\n'
    assert _sql_risk_types(src) == ["sql_injection"]


def test_inline_fstring_without_placeholder_does_not_flag():
    # A placeholder-less f-string is a plain literal, not an injection.
    src = 'cursor.execute(f"SELECT * FROM users")\n'
    assert _sql_risk_types(src) == []


# ---------------------------------------------------------------------------
# SQLi shape 2 — inline string concat / % format mixing a literal and a value.
# ---------------------------------------------------------------------------
def test_inline_concat_in_execute_flags():
    src = 'cursor.execute("SELECT * FROM t WHERE id = " + uid)\n'
    assert _sql_risk_types(src) == ["sql_injection"]


def test_inline_percent_format_in_execute_flags():
    src = 'cursor.execute("SELECT * FROM t WHERE id = %s" % uid)\n'
    assert _sql_risk_types(src) == ["sql_injection"]


def test_literal_only_concat_does_not_flag():
    # "a" + "b" is literal-only — no tainted value mixed in.
    src = 'cursor.execute("SELECT * " + "FROM t")\n'
    assert _sql_risk_types(src) == []


# ---------------------------------------------------------------------------
# SQLi shape 3 — assigned f-string/concat variable passed by name.
# ---------------------------------------------------------------------------
def test_assigned_fstring_then_executed_flags():
    src = (
        'q = f"SELECT * FROM users WHERE id = {uid}"\n'
        "cursor.execute(q)\n"
    )
    assert _sql_risk_types(src) == ["sql_injection"]


def test_assigned_concat_then_executed_flags():
    src = (
        'q = "SELECT * FROM t WHERE id = " + uid\n'
        "cursor.execute(q)\n"
    )
    assert _sql_risk_types(src) == ["sql_injection"]


def test_assigned_literal_then_executed_does_not_flag():
    # A safe literal binding passed by name is NOT tainted.
    src = (
        'q = "SELECT * FROM users"\n'
        "cursor.execute(q)\n"
    )
    assert _sql_risk_types(src) == []


def test_name_with_no_prior_binding_does_not_flag():
    # No prior assignment in scope -> nothing resolved -> no finding.
    src = "cursor.execute(q)\n"
    assert _sql_risk_types(src) == []


# ---------------------------------------------------------------------------
# Parameterized query — the safe shape that must NEVER flag.
# ---------------------------------------------------------------------------
def test_parameterized_query_does_not_flag():
    src = 'cursor.execute("SELECT * FROM t WHERE id = ?", (uid,))\n'
    assert _sql_risk_types(src) == []


def test_parameterized_named_style_does_not_flag():
    src = 'cursor.execute("SELECT * FROM t WHERE id = %s", (uid,))\n'
    assert _sql_risk_types(src) == []


# ---------------------------------------------------------------------------
# Sink gating — a tainted f-string NOT passed to execute()/cursor() is ignored
# by this detector (it only fires on the SQL sink call name).
# ---------------------------------------------------------------------------
def test_tainted_fstring_to_non_sql_call_does_not_flag():
    src = 'logger.info(f"value = {uid}")\n'
    assert _sql_risk_types(src) == []


def test_finding_metadata_is_exact():
    src = 'cursor.execute(f"SELECT {uid}")\n'
    agent = SecurityAgent()
    findings = [f for f in agent._scan_ast("db.py", src)
                if f["risk_type"] == "sql_injection"]
    assert len(findings) == 1
    f = findings[0]
    assert f["severity"] == "critical"
    assert f["suggestion"] == "Use parameterized queries"
    assert f["file"] == "db.py"


# ---------------------------------------------------------------------------
# The shared AST predicates, isolated.
# ---------------------------------------------------------------------------
def _expr(code: str) -> ast.expr:
    return ast.parse(code, mode="eval").body


def test_joinedstr_nonliteral_predicate():
    assert _joinedstr_has_nonliteral(_expr('f"{x}"')) is True
    assert _joinedstr_has_nonliteral(_expr('f"plain"')) is False


def test_string_concat_binop_predicate():
    # literal + value -> True; literal + literal -> False; numeric add -> False.
    assert _is_string_concat_binop(_expr('"a" + x')) is True
    assert _is_string_concat_binop(_expr('"a" + "b"')) is False
    assert _is_string_concat_binop(_expr("a + b")) is False
    # A non-BinOp expression is not a concat.
    assert _is_string_concat_binop(_expr("x")) is False


def test_sql_injection_findings_skips_non_sql_sink_directly():
    # Direct unit on the helper: a non-execute/cursor func_name returns [].
    node = ast.parse('logger.info(f"{x}")', mode="eval").body
    assert _sql_injection_findings("f.py", node, "logger.info", {}) == []


# ===========================================================================
# Jinja XSS — polyglot _scan_html, each kind pinned exactly.
# ===========================================================================
def _html_kinds(line: str) -> set[str]:
    return {kind for _sev, kind, _msg in _scan_html(line)}


def test_jinja_safe_filter_flags_xss():
    kinds = _html_kinds("<p>{{ user_bio | safe }}</p>")
    assert "jinja-safe" in kinds
    assert "jinja-safe-context" not in kinds


def test_plain_interpolation_does_not_flag():
    # Auto-escaped {{ x }} is safe — no jinja finding at all.
    assert _html_kinds("<p>{{ user_bio }}</p>") == set()


def test_autoescape_false_flags():
    kinds = _html_kinds("{% autoescape false %}")
    assert "jinja-autoescape-off" in kinds


def test_autoescape_true_does_not_flag():
    assert _html_kinds("{% autoescape true %}") == set()


def test_safe_in_script_context_is_the_stronger_signal_only():
    # In a <script> context the | safe is the STRONGER jinja-safe-context, and
    # the plain jinja-safe must NOT also fire (the scanner uses elif).
    line = "<script>var x = {{ payload | safe }};</script>"
    kinds = _html_kinds(line)
    assert "jinja-safe-context" in kinds
    assert "jinja-safe" not in kinds


def test_safe_in_attribute_context_is_the_stronger_signal():
    line = '<a href="{{ url | safe }}">x</a>'
    kinds = _html_kinds(line)
    assert "jinja-safe-context" in kinds
    assert "jinja-safe" not in kinds


def test_safe_severity_is_high():
    findings = _scan_html("{{ x | safe }}")
    assert findings == [("high", "jinja-safe",
                         "Jinja | safe filter bypasses HTML auto-escaping (XSS)")]


def test_autoescape_off_severity_and_message_exact():
    findings = _scan_html("{% autoescape false %}")
    assert findings == [("high", "jinja-autoescape-off",
                         "Jinja autoescape disabled — interpolations are unescaped (XSS)")]


def test_safe_filter_in_chain_still_flags():
    # ``| e | safe`` — safe as the last filter in a chain still bypasses escaping.
    kinds = _html_kinds("<p>{{ value | e | safe }}</p>")
    assert "jinja-safe" in kinds
