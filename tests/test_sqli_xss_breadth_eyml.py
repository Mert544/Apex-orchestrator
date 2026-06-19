"""Detection-breadth tests: broadened SQLi shapes + Jinja/HTML XSS.

Closes red-team gaps:
  * SQLi previously fired ONLY for an inline f-string as a direct execute()/
    cursor() argument. It now also flags an f-string/concat assigned to a
    variable then passed, and an inline string ``+``/``%`` concatenation — while
    a parameterized query stays clean (no false positive).
  * Jinja template XSS (``{{ ... | safe }}`` / ``{% autoescape false %}``) is now
    a high-confidence polyglot finding, with plain ``{{ x }}`` staying clean.

These are FLAG-ONLY detections (human review); nothing is auto-fixed.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.skills.security_agent import SecurityAgent
from app.engine.polyglot_findings import scan_polyglot_findings


def _scan_py(src: str) -> list[dict]:
    return SecurityAgent()._scan_ast("app/db.py", src)


def _sqli(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f["risk_type"] == "sql_injection"]


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _kinds(findings: list[dict]) -> set[str]:
    return {f["kind"] for f in findings}


# --- SQLi: the three unsafe shapes all fire ---------------------------------

def test_sqli_inline_fstring_in_execute_fires() -> None:
    findings = _sqli(_scan_py("cursor.execute(f'SELECT * FROM t WHERE id = {uid}')"))
    assert len(findings) == 1
    assert findings[0]["severity"] == "critical"
    assert findings[0]["line"] == 1


def test_sqli_assigned_fstring_then_execute_fires() -> None:
    src = (
        "def q(uid):\n"
        "    query = f'SELECT * FROM t WHERE id = {uid}'\n"
        "    cursor.execute(query)\n"
    )
    findings = _sqli(_scan_py(src))
    assert len(findings) == 1
    assert findings[0]["severity"] == "critical"
    # Flagged at the execute() call site (the Name argument).
    assert findings[0]["line"] == 3


def test_sqli_inline_concatenation_fires() -> None:
    findings = _sqli(_scan_py("cursor.execute('SELECT * FROM t WHERE id = ' + uid)"))
    assert len(findings) == 1
    assert findings[0]["severity"] == "critical"


def test_sqli_percent_format_fires() -> None:
    findings = _sqli(_scan_py("cursor.execute('SELECT * FROM t WHERE id = %s' % uid)"))
    assert len(findings) == 1


def test_sqli_assigned_concat_then_execute_fires() -> None:
    src = (
        "def q(uid):\n"
        "    query = 'SELECT * FROM t WHERE id = ' + uid\n"
        "    cursor.execute(query)\n"
    )
    assert len(_sqli(_scan_py(src))) == 1


# --- SQLi: no false positives -----------------------------------------------

def test_sqli_parameterized_query_not_flagged() -> None:
    findings = _sqli(_scan_py("cursor.execute('SELECT * FROM t WHERE id = ?', (uid,))"))
    assert findings == []


def test_sqli_static_fstring_no_interpolation_not_flagged() -> None:
    # An f-string with no FormattedValue is just a literal — not a risk.
    assert _sqli(_scan_py("cursor.execute(f'SELECT 1')")) == []


def test_sqli_literal_only_concat_not_flagged() -> None:
    assert _sqli(_scan_py("cursor.execute('SELECT ' + '1')")) == []


def test_sqli_plain_string_literal_not_flagged() -> None:
    assert _sqli(_scan_py("cursor.execute('SELECT 1')")) == []


def test_sqli_concat_outside_sql_sink_not_flagged() -> None:
    # The same concat to a non-SQL call must not fire.
    assert _sqli(_scan_py("log.write('id=' + uid)")) == []


def test_sqli_assigned_safe_literal_then_execute_not_flagged() -> None:
    src = (
        "def q():\n"
        "    query = 'SELECT 1'\n"
        "    cursor.execute(query)\n"
    )
    assert _sqli(_scan_py(src)) == []


def test_sqli_later_reassignment_does_not_mask_prior_unsafe() -> None:
    # Resolution picks the nearest binding PRIOR to the call line.
    src = (
        "def q(uid):\n"
        "    query = f'SELECT {uid}'\n"
        "    cursor.execute(query)\n"
        "    query = 'safe'\n"
    )
    assert len(_sqli(_scan_py(src))) == 1


# --- SQLi: robustness -------------------------------------------------------

def test_sqli_deterministic() -> None:
    src = (
        "def q(uid):\n"
        "    query = f'SELECT {uid}'\n"
        "    cursor.execute(query)\n"
        "    cursor.execute('a' + uid)\n"
    )
    assert _scan_py(src) == _scan_py(src)


def test_sqli_no_crash_on_syntax_error() -> None:
    assert _scan_py("cursor.execute(f'{") == []


# --- Jinja / HTML XSS: fires ------------------------------------------------

def test_jinja_safe_filter_fires(tmp_path) -> None:
    _write(tmp_path, "t.html", "<p>{{ user.name | safe }}</p>\n")
    findings = scan_polyglot_findings(str(tmp_path))
    safe = [f for f in findings if f["kind"] == "jinja-safe"]
    assert len(safe) == 1
    assert safe[0]["severity"] == "high"
    assert safe[0]["line"] == 1


def test_jinja_autoescape_false_fires(tmp_path) -> None:
    _write(tmp_path, "t.html", "{% autoescape false %}\n{{ x }}\n{% endautoescape %}\n")
    findings = scan_polyglot_findings(str(tmp_path))
    hits = [f for f in findings if f["kind"] == "jinja-autoescape-off"]
    assert len(hits) == 1
    assert hits[0]["severity"] == "high"


def test_jinja_safe_in_script_context_is_strongest_signal(tmp_path) -> None:
    _write(tmp_path, "t.html", "<script>var n = {{ user.name | safe }};</script>\n")
    findings = scan_polyglot_findings(str(tmp_path))
    # The stronger context kind fires; the plain jinja-safe does not double-report.
    assert "jinja-safe-context" in _kinds(findings)
    assert "jinja-safe" not in _kinds(findings)


def test_jinja_safe_in_attribute_context_fires(tmp_path) -> None:
    _write(tmp_path, "t.html", '<a title="{{ user.bio | safe }}">x</a>\n')
    findings = scan_polyglot_findings(str(tmp_path))
    assert "jinja-safe-context" in _kinds(findings)


def test_jinja_safe_filter_chain_fires(tmp_path) -> None:
    _write(tmp_path, "t.html", "<p>{{ value | e | safe }}</p>\n")
    findings = scan_polyglot_findings(str(tmp_path))
    assert "jinja-safe" in _kinds(findings)


# --- Jinja / HTML XSS: no false positives -----------------------------------

def test_plain_interpolation_not_flagged(tmp_path) -> None:
    _write(tmp_path, "t.html", "<p>{{ user.name }}</p>\n")
    findings = scan_polyglot_findings(str(tmp_path))
    assert not any(f["kind"].startswith("jinja-") for f in findings)


def test_autoescape_true_not_flagged(tmp_path) -> None:
    _write(tmp_path, "t.html", "{% autoescape true %}\n{{ x }}\n{% endautoescape %}\n")
    findings = scan_polyglot_findings(str(tmp_path))
    assert not any(f["kind"].startswith("jinja-") for f in findings)


def test_safe_word_without_filter_not_flagged(tmp_path) -> None:
    # The word "safe" outside a filter position must not match.
    _write(tmp_path, "t.html", "<p>{{ safe_value }}</p>\n<p>stay safe</p>\n")
    findings = scan_polyglot_findings(str(tmp_path))
    assert not any(f["kind"].startswith("jinja-") for f in findings)


# --- Jinja / HTML XSS: robustness -------------------------------------------

def test_jinja_minified_line_skipped_no_hang(tmp_path) -> None:
    # A line over _MAX_LINE_LEN is skipped (the per-line scanner guards length),
    # so a pathological minified template cannot hang the scan.
    line = "x" * 3000 + "{{ a | safe }}"
    _write(tmp_path, "t.html", line + "\n<p>{{ b | safe }}</p>\n")
    findings = scan_polyglot_findings(str(tmp_path))
    safe = [f for f in findings if f["kind"] == "jinja-safe"]
    # Only the short second line fires; the oversized first line is skipped.
    assert len(safe) == 1
    assert safe[0]["line"] == 2


def test_jinja_deterministic(tmp_path) -> None:
    _write(tmp_path, "t.html", "<p>{{ a | safe }}</p>\n{% autoescape false %}\n")
    assert scan_polyglot_findings(str(tmp_path)) == scan_polyglot_findings(str(tmp_path))
