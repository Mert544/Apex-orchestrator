"""Characterization tests pinning ``SecurityAgent._check_call`` behavior.

These exercise every branch of the (refactored) ``_check_call`` decomposition:
bare-builtin matching, module-qualified sink matching (exact + endswith),
the compile/eval/subprocess false-positive filters, SQL f-string detection,
and the unresolved-call-name early return. They assert exact finding dicts so
any drift in detection, strings, or ordering is caught.
"""

from __future__ import annotations

import ast

from app.agents.skills.security_agent import SecurityAgent


def _check(src: str) -> list[dict]:
    agent = SecurityAgent()
    tree = ast.parse(src)
    out: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            out.extend(agent._check_call("rel/path.py", node, src))
    return out


def test_eval_builtin_flagged() -> None:
    assert _check("eval('1+1')") == [
        {
            "file": "rel/path.py",
            "line": 1,
            "risk_type": "eval() usage",
            "severity": "critical",
            "details": "Detected eval at line 1",
            "suggestion": "Replace with ast.literal_eval or json.loads",
        }
    ]


def test_exec_and_compile_builtins_flagged() -> None:
    assert [f["risk_type"] for f in _check("exec('x=1')")] == ["exec() usage"]
    assert [f["risk_type"] for f in _check("compile('x','f','exec')")] == ["compile() usage"]


def test_method_calls_not_matched_as_builtins() -> None:
    # model.compile() / df.eval() / self.compile() are unrelated user methods.
    assert _check("model.compile()") == []
    assert _check("df.eval('a')") == []
    assert _check("self.compile(x)") == []


def test_false_positive_filters() -> None:
    assert _check("re.compile('x')") == []
    assert _check("regex.compile('x')") == []
    assert _check("ast.literal_eval('1')") == []
    assert _check("literal_eval('1')") == []


def test_module_qualified_sinks_exact_and_endswith() -> None:
    assert [f["risk_type"] for f in _check("os.system('ls')")] == ["os.system() shell injection"]
    assert [f["risk_type"] for f in _check("a.b.os.system('ls')")] == ["os.system() shell injection"]
    assert [f["risk_type"] for f in _check("pkg.pickle.loads(d)")] == ["pickle deserialization"]


def test_subprocess_call_only_flagged_with_shell_true() -> None:
    assert _check("subprocess.call(['ls'])") == []
    assert _check("subprocess.call('ls', shell=False)") == []
    assert _check("subprocess.call('ls', shell=None)") == []
    assert [f["risk_type"] for f in _check("subprocess.call('ls', shell=True)")] == ["subprocess.call()"]


def test_yaml_loads_flagged() -> None:
    assert [f["risk_type"] for f in _check("yaml.load(s)")] == ["yaml unsafe load"]
    assert [f["severity"] for f in _check("yaml.unsafe_load(s)")] == ["critical"]


def test_sql_injection_fstring() -> None:
    findings = _check("cursor.execute(f'select {x}')")
    assert findings == [
        {
            "file": "rel/path.py",
            "line": 1,
            "risk_type": "sql_injection",
            "severity": "critical",
            "details": "f-string used in SQL query at line 1",
            "suggestion": "Use parameterized queries",
        }
    ]


def test_sql_injection_requires_fstring() -> None:
    assert _check("cursor.execute('select 1')") == []


def test_sql_injection_multiple_fstring_args() -> None:
    findings = _check("x.execute(f'{a}', f'{b}', 'plain')")
    assert [f["risk_type"] for f in findings] == ["sql_injection", "sql_injection"]


def test_eval_fstring_yields_only_sink() -> None:
    # "eval" is not an execute/cursor name, so no SQL finding is added.
    assert [f["risk_type"] for f in _check("eval(f'{x}')")] == ["eval() usage"]


def test_unresolved_call_name_returns_empty() -> None:
    assert _check("(lambda: x)()") == []
    assert _check("foo()()") == []
    assert _check("arr[0]()") == []
