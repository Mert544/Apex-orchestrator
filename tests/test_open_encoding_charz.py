"""Characterization tests for the two ``_is_text_open_without_encoding`` guards.

Both ``open_encoding`` (the transform) and ``detectors`` (the scanner) must agree
on which ``open(...)`` calls are text-mode-without-encoding, since the detector
decides what the transform then fixes. This pins the exact boolean semantics so a
refactor of either function stays byte-identical in behaviour.
"""

from __future__ import annotations

import ast

import pytest

from app.engine.detectors import (
    _is_text_open_without_encoding as det_is_text_open,
)
from app.execution.semantic.transforms.open_encoding import (
    _is_text_open_without_encoding as oe_is_text_open,
)

# (source snippet, expected result of _is_text_open_without_encoding)
_CASES: list[tuple[str, bool]] = [
    # text-mode-without-encoding positives
    ("open('f')", True),
    ("open('f', 'r')", True),
    ("open('f', 'w')", True),
    ("open('f', 'a')", True),
    ("open('f', 'r+')", True),
    ("open('f', mode='r')", True),
    ("open('f', mode='w')", True),
    ("open(path)", True),
    ("open(get_path())", True),
    ("open('f', buffering=1)", True),
    ("open('f', 'r', buffering=1)", True),
    ("open('f', errors='strict')", True),
    ("open('f', newline='')", True),
    ("open('f', 'rt')", True),
    ("open('f', 'r', 1)", True),
    ("open('f', buffering=-1, mode='r')", True),
    # negatives: binary mode (positional or keyword)
    ("open('f', 'rb')", False),
    ("open('f', 'wb')", False),
    ("open('f', 'br')", False),
    ("open('f', mode='rb')", False),
    ("open('f', mode='ab')", False),
    ("open('f', mode='rb', encoding='utf-8')", False),
    # negatives: explicit encoding present
    ("open('f', encoding='utf-8')", False),
    ("open('f', 'r', encoding='utf-8')", False),
    ("open('f', mode='r', encoding='latin-1')", False),
    ("open('f', encoding='utf-8', mode='r')", False),
    # negatives: **kwargs could smuggle in encoding
    ("open('f', **opts)", False),
    ("open('f', 'r', **opts)", False),
    ("open(**opts)", False),
    # negatives: dynamic (non-constant) mode
    ("open('f', m)", False),
    ("open('f', mode=m)", False),
    ("open('f', get_mode())", False),
    ("open('f', 'r' + extra)", False),
    ("open('f', mode='r' + x)", False),
    ("open('f', f'r')", False),
    # negatives: not the builtin open / bare open()
    ("open()", False),
    # no positional path (path passed as file= keyword) — not in scope
    ("open(file='f')", False),
    ("open(file='f', mode='w')", False),
    ("io.open('f')", False),
    ("os.open('f', 0)", False),
    ("self.open('f')", False),
    ("myopen('f')", False),
    ("opened('f')", False),
    ("print('f')", False),
    ("json.load(f)", False),
]


def _first_call(src: str) -> ast.Call:
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            return node
    raise AssertionError(f"no Call node in {src!r}")


@pytest.mark.parametrize(("src", "expected"), _CASES)
def test_open_encoding_guard(src: str, expected: bool) -> None:
    assert oe_is_text_open(_first_call(src)) is expected


@pytest.mark.parametrize(("src", "expected"), _CASES)
def test_detectors_guard(src: str, expected: bool) -> None:
    assert det_is_text_open(_first_call(src)) is expected


@pytest.mark.parametrize(("src", "_expected"), _CASES)
def test_both_guards_agree(src: str, _expected: bool) -> None:
    node = _first_call(src)
    assert oe_is_text_open(node) is det_is_text_open(node)
