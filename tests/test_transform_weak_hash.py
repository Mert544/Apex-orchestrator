from __future__ import annotations

from app.engine.detectors import detect, security_label
from app.execution.semantic.transforms import security as sec


def _flag(src: str) -> str | None:
    r = sec.apply("m.py", src, "Fix weak-hash in m.py")
    return r.patch_requests[0]["new_content"] if r else None


def test_detects_md5_and_sha1():
    for algo in ("md5", "sha1"):
        src = f"import hashlib\ndef h(b):\n    return hashlib.{algo}(b).hexdigest()\n"
        issues = [i for i in detect(src) if i.fix_kind == "weak-hash"]
        assert len(issues) == 1 and issues[0].category == "security"


def test_usedforsecurity_false_is_not_flagged():
    # Declared non-security -> respected, like noqa/shell=True precision filters.
    src = "import hashlib\ndef h(b):\n    return hashlib.md5(b, usedforsecurity=False).hexdigest()\n"
    assert not [i for i in detect(src) if i.fix_kind == "weak-hash"]


def test_sha256_is_not_flagged():
    src = "import hashlib\ndef h(b):\n    return hashlib.sha256(b).hexdigest()\n"
    assert not [i for i in detect(src) if i.fix_kind == "weak-hash"]


def test_flag_inserts_comment_and_is_idempotent():
    src = "import hashlib\ndef h(b):\n    return hashlib.md5(b).hexdigest()\n"
    out = _flag(src)
    assert out is not None and "Apex: weak hash" in out
    import ast
    ast.parse(out)
    assert _flag(out) is None


def test_eval_outranks_weak_hash_in_label():
    src = "import hashlib\ndef h(b, c):\n    hashlib.md5(b)\n    return eval(c)\n"
    assert security_label(src) == "eval"
