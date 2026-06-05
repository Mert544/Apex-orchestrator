from __future__ import annotations

import ast

from app.engine.detectors import detect, has_open_without_encoding
from app.execution.semantic.transforms import open_encoding as oe


def _apply(src: str) -> str | None:
    r = oe.apply("m.py", src, "open-encoding")
    return r.patch_requests[0]["new_content"] if r else None


def test_adds_encoding_to_bare_open():
    out = _apply("def g(p):\n    return open(p)\n")
    assert out is not None
    assert 'open(p, encoding="utf-8")' in out
    ast.parse(out)


def test_adds_encoding_after_text_mode():
    out = _apply('def g(p):\n    return open(p, "w")\n')
    assert out is not None
    assert 'open(p, "w", encoding="utf-8")' in out
    ast.parse(out)


def test_binary_mode_is_skipped():
    # Binary opens take no encoding; must be left untouched.
    assert _apply('def g(p):\n    return open(p, "rb")\n') is None


def test_existing_encoding_is_skipped():
    assert _apply('def g(p):\n    return open(p, encoding="latin-1")\n') is None


def test_dynamic_mode_is_skipped():
    # Mode is a variable — we can't prove it is text, so stay safe.
    assert _apply("def g(p, mode):\n    return open(p, mode)\n") is None


def test_non_builtin_open_is_skipped():
    # obj.open() (e.g. a file-like or Path.open) is not the builtin.
    assert _apply("def g(p, fs):\n    return fs.open(p)\n") is None


def test_kwargs_smuggling_is_skipped():
    # **kwargs could carry encoding=; don't risk a duplicate kwarg.
    assert _apply("def g(p, kw):\n    return open(p, **kw)\n") is None


def test_multiline_call_is_skipped_but_safe():
    # A multi-line open() is skipped (line-exact edit only); no crash.
    src = "def g(p):\n    return open(\n        p,\n    )\n"
    assert _apply(src) is None


def test_detector_agrees_with_transform():
    src = "def g(p):\n    return open(p)\n"
    assert has_open_without_encoding(src) is True
    issues = [i for i in detect(src) if i.fix_kind == "open-encoding"]
    assert len(issues) == 1
    assert issues[0].category == "bug"


def test_with_statement_real_world():
    # The common `with open(path, "r") as f:` form (seen in paramiko).
    out = _apply('def g(filename):\n    with open(filename, "r") as f:\n        return f.read()\n')
    assert out is not None
    assert 'open(filename, "r", encoding="utf-8")' in out
    ast.parse(out)
