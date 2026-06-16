from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.skills.self_audit_agent import SelfAuditAgent

# Each snippet exercises a distinct branch of _analyze_risks (and its helpers):
# eval/exec Name calls, os.system/pickle.loads Attribute calls, bare/typed
# except, attribute values that are not Names, SyntaxError and empty-file paths.
SNIPPETS = [
    ("eval('1')", [("eval()", "critical")]),
    ("exec('x=1')", [("exec()", "critical")]),
    ("os.system('ls')", [("os.system()", "high")]),
    ("pickle.loads(b'')", [("pickle.loads()", "high")]),
    ("try:\n    pass\nexcept:\n    pass\n", [("bare except", "medium")]),
    ("try:\n    pass\nexcept Exception:\n    pass\n", []),
    ("foo.system('x')", []),
    ("os.popen('x')", []),
    ("pickle.dumps(x)", []),
    ("json.loads('x')", []),
    ("obj.method().chained()", []),
    ("a.b.c.system('x')", []),
    ("evaluate(1)", []),
    ("(lambda: 0)()", []),
    ("x = 1\ny = 2\n", []),
    ("@dec\ndef f():\n    eval('z')\n", [("eval()", "critical")]),
    ("this is not valid python )(", []),
    ("", []),
    ("eval(eval(eval('x')))", [("eval()", "critical")] * 3),
    (
        "eval(exec(os.system('y')))\ntry:\n    pickle.loads(z)\nexcept:\n    pass\n",
        [
            ("eval()", "critical"),
            ("exec()", "critical"),
            ("os.system()", "high"),
            ("pickle.loads()", "high"),
            ("bare except", "medium"),
        ],
    ),
]


def _risk_pairs(findings: list[dict]) -> list[tuple[str, str]]:
    return sorted((r["risk"], r["severity"]) for r in findings)


@pytest.mark.parametrize("source,expected", SNIPPETS)
def test_analyze_risks_branches(tmp_path: Path, source: str, expected):
    f = tmp_path / "snippet.py"
    f.write_text(source, encoding="utf-8")
    findings = SelfAuditAgent()._analyze_risks([f])
    for r in findings:
        assert r["file"] == str(f)
        assert isinstance(r["line"], int)
    assert _risk_pairs(findings) == sorted(expected)


def test_analyze_risks_empty_file_list():
    assert SelfAuditAgent()._analyze_risks([]) == []


def test_analyze_risks_preserves_order_and_lineno(tmp_path: Path):
    f = tmp_path / "ordered.py"
    f.write_text("eval('a')\nexec('b')\nos.system('c')\n", encoding="utf-8")
    findings = SelfAuditAgent()._analyze_risks([f])
    assert [(r["risk"], r["line"]) for r in findings] == [
        ("eval()", 1),
        ("exec()", 2),
        ("os.system()", 3),
    ]


def test_helper_purity():
    import ast

    assert SelfAuditAgent._name_call_risk(ast.parse("eval()").body[0].value.func) == (
        "eval()",
        "critical",
    )
    assert SelfAuditAgent._name_call_risk(ast.parse("foo()").body[0].value.func) is None
    attr = ast.parse("os.system()").body[0].value.func
    assert SelfAuditAgent._attr_call_risk(attr) == ("os.system()", "high")
    assert SelfAuditAgent._node_risk(ast.parse("x = 1").body[0]) is None
