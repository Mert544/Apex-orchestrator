"""Characterization harness proving introduce_parameter_object is byte-identical
to its pre-refactor behaviour across many source inputs and arg combinations.

The original implementation is re-created inline (verbatim from HEAD) and compared
field-by-field against the live refactored implementation.
"""

from __future__ import annotations

import ast
import itertools

import pytest

from app.execution.advanced_refactoring import (
    AdvancedRefactorResult,
    AdvancedRefactoringEngine,
)


def _original_introduce_parameter_object(
    source_code: str,
    function_name: str,
    param_indices: list[int] | None = None,
    object_name: str = "",
) -> AdvancedRefactorResult:
    """Verbatim copy of the HEAD implementation (pre-refactor)."""
    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        return AdvancedRefactorResult(False, f"Parse error: {e}")

    target_func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            target_func = node
            break
    if not target_func:
        return AdvancedRefactorResult(False, f"Function {function_name} not found")

    args = target_func.args.args
    start = 1 if args and args[0].arg in ("self", "cls") else 0
    params = args[start:]

    if not param_indices:
        param_indices = list(range(len(params)))
    selected = [params[i] for i in param_indices if 0 <= i < len(params)]
    if len(selected) < 2:
        return AdvancedRefactorResult(
            False, f"Need at least 2 parameters to bundle, got {len(selected)}"
        )

    if not object_name:
        object_name = f"{function_name.title().replace('_', '')}Params"

    fields: list[str] = []
    for arg in selected:
        annotation = ""
        if arg.annotation:
            annotation = f": {ast.unparse(arg.annotation)}"
        fields.append(f"    {arg.arg}{annotation}")
    dataclass_code = f"@dataclass\nclass {object_name}:\n" + "\n".join(fields)

    kept = [p for i, p in enumerate(params) if i not in param_indices]
    new_sig_params = ["self"] if start == 1 else []
    new_sig_params.append(f"params: {object_name}")
    for k in kept:
        annotation = ""
        if k.annotation:
            annotation = f": {ast.unparse(k.annotation)}"
        default = ""
        new_sig_params.append(f"{k.arg}{annotation}{default}")

    new_sig = f"def {function_name}(" + ", ".join(new_sig_params) + ") -> ..."
    return AdvancedRefactorResult(
        success=True,
        description=f"Introduced {object_name} for {function_name}",
        new_content=dataclass_code + "\n\n" + new_sig + ":\n    ...",
        old_content=ast.unparse(target_func),
        diff=f"Introduced {object_name} dataclass",
    )


_SOURCES = [
    "",  # empty -> function not found
    "x = 1",  # no function
    "def (:",  # syntax error
    "def foo(): pass",  # zero params
    "def foo(a): pass",  # one param
    "def foo(a, b): pass",  # two bare params
    "def foo(a, b, c, d): pass",
    "def foo(a: int, b: str, c: 'X', d: list[int]): pass",
    "class C:\n    def m(self, a, b, c): pass",
    "class C:\n    def m(cls, a: int, b: int): pass",
    "def foo(self, a, b): pass",  # self as plain function arg
    "def foo(a=1, b=2, c=3): pass",  # defaults present
    "def foo(a: int = 1, b: str = 'z'): pass",
    "def outer():\n    def foo(a, b, c): pass",  # nested target
    "async def foo(a, b, c): pass",  # async def (not matched by FunctionDef)
    "def foo(a, *args, b, c): pass",
    "def foo(a, b, /, c, d): pass",  # posonly excluded from .args differently
    "def foo(é, b, c): pass" if False else "def foo(a, b, c): pass",
    "def dup(a, b): pass\ndef dup(c, d, e): pass",  # duplicate names -> first wins
]

_NAMES = ["foo", "m", "missing", "dup", "create_order", ""]

_INDEX_SETS: list[list[int] | None] = [
    None,
    [],
    [0],
    [0, 1],
    [1, 2],
    [0, 2],
    [0, 1, 2, 3],
    [5, 6],  # out of range
    [0, 99],  # mixed in/out of range
    [-1, 0, 1],  # negative filtered
    [2, 0, 1],  # unordered
]

_OBJ_NAMES = ["", "OrderParams", "MyObj"]


def _cases():
    for src, name, idx, obj in itertools.product(
        _SOURCES, _NAMES, _INDEX_SETS, _OBJ_NAMES
    ):
        yield src, name, idx, obj


@pytest.mark.parametrize("src,name,idx,obj", list(_cases()))
def test_byte_identical(src, name, idx, obj):
    # copy index lists since the original mutates the default-derived list path
    idx_a = list(idx) if idx is not None else None
    idx_b = list(idx) if idx is not None else None
    expected = _original_introduce_parameter_object(src, name, idx_a, obj)
    actual = AdvancedRefactoringEngine.introduce_parameter_object(src, name, idx_b, obj)
    assert actual.to_dict() == expected.to_dict()
    assert actual.success == expected.success
    assert actual.new_content == expected.new_content
    assert actual.old_content == expected.old_content
    assert actual.diff == expected.diff
    assert actual.description == expected.description


def test_case_count_is_substantial():
    # ensure the harness actually exercises many combinations
    assert len(list(_cases())) >= 1000
