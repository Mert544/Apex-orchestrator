"""Characterization tests pinning ``SecurityAgent._scan_ast`` behavior.

These exercise every branch of the (refactored) ``_scan_ast`` decomposition:
syntax-error early return, the nested ``compile()`` de-duplication for
``eval(compile(...))`` / ``exec(compile(...))``, call-sink detection,
bare-except detection, and inline suppression dropping. They assert exact
finding dicts (order + contents) so any drift is caught.
"""

from __future__ import annotations

from app.agents.skills.security_agent import SecurityAgent


def _scan(src: str) -> list[dict]:
    return SecurityAgent()._scan_ast("rel/p.py", src)


def test_syntax_error_returns_empty() -> None:
    assert _scan("this is not python (") == []
    assert _scan("") == []


def test_eval_call_flagged() -> None:
    assert _scan("eval('1+1')") == [
        {
            "file": "rel/p.py",
            "line": 1,
            "risk_type": "eval() usage",
            "severity": "critical",
            "details": "Detected eval at line 1",
            "suggestion": "Replace with ast.literal_eval or json.loads",
        }
    ]


def test_bare_except_flagged() -> None:
    findings = _scan("try:\n    x()\nexcept:\n    pass\n")
    assert findings == [
        {
            "file": "rel/p.py",
            "line": 3,
            "risk_type": "bare_except",
            "severity": "medium",
            "details": "Bare except clause at line 3",
            "suggestion": "Use 'except Exception:' or specific exceptions",
        }
    ]


def test_typed_except_not_flagged() -> None:
    assert _scan("try:\n    x()\nexcept Exception:\n    pass\n") == []


def test_nested_compile_deduplicated() -> None:
    # eval(compile(...)) and exec(compile(...)) report only the eval/exec sink,
    # never a second compile() finding.
    assert [f["risk_type"] for f in _scan("eval(compile('x','f','exec'))")] == ["eval() usage"]
    assert [f["risk_type"] for f in _scan("exec(compile('x','f','exec'))")] == ["exec() usage"]


def test_standalone_compile_still_flagged() -> None:
    assert [f["risk_type"] for f in _scan("compile('x','f','exec')")] == ["compile() usage"]


def test_multiple_nested_compiles_all_deduplicated() -> None:
    out = _scan("eval(compile('a','b','c'), compile('d','e','f'))")
    assert [f["risk_type"] for f in out] == ["eval() usage"]


def test_call_and_bare_except_ordered_by_walk() -> None:
    # ``ast.walk`` is breadth-first, so the shallower ExceptHandler is visited
    # before the deeper calls inside the try body.
    src = "def f():\n    eval('a')\n    try:\n        os.system('b')\n    except:\n        exec('c')\n"
    assert [f["risk_type"] for f in _scan(src)] == [
        "eval() usage",
        "bare_except",
        "os.system() shell injection",
        "exec() usage",
    ]


def test_nosec_suppresses_finding() -> None:
    assert _scan("import os\nos.system('rm')  # nosec\n") == []


def test_noqa_security_code_suppresses() -> None:
    assert _scan("eval('x')  # noqa: S307\n") == []


def test_unrelated_noqa_does_not_suppress() -> None:
    assert [f["risk_type"] for f in _scan("eval('x')  # noqa: E501\n")] == ["eval() usage"]


def test_bare_except_e722_suppressed() -> None:
    assert _scan("try:\n    pass\nexcept:  # noqa: E722\n    pass\n") == []


def test_sql_fstring_detected() -> None:
    assert [f["risk_type"] for f in _scan("cursor.execute(f'select {x}')")] == ["sql_injection"]
