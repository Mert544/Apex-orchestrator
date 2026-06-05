from __future__ import annotations

from app.engine.detectors import detect, security_label
from app.execution.semantic.transforms import security as sec


def _flag(src: str) -> str | None:
    r = sec.apply("m.py", src, "Fix tempfile in m.py")
    return r.patch_requests[0]["new_content"] if r else None


def test_detects_tempfile_mktemp():
    src = "import tempfile\ndef t():\n    return tempfile.mktemp()\n"
    issues = [i for i in detect(src) if i.fix_kind == "tempfile"]
    assert len(issues) == 1 and issues[0].category == "security"
    assert security_label(src) == "tempfile"


def test_obj_mktemp_is_not_flagged():
    # A user-defined .mktemp() method is not the tempfile builtin (precision).
    assert not [i for i in detect("def t(o):\n    return o.mktemp()\n") if i.fix_kind == "tempfile"]


def test_flag_inserts_security_comment_and_is_idempotent():
    src = "import tempfile\ndef t():\n    return tempfile.mktemp()\n"
    out = _flag(src)
    assert out is not None and "Apex: insecure temp file" in out
    import ast
    ast.parse(out)
    # Running again must not double-comment.
    assert _flag(out) is None


def test_severity_order_prefers_critical_over_tempfile():
    # eval (critical) outranks a medium tempfile finding in the label contract.
    src = "import tempfile\ndef t(c):\n    tempfile.mktemp()\n    return eval(c)\n"
    assert security_label(src) == "eval"
