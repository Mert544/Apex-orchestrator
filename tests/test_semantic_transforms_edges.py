"""Edge/error-path coverage for under-covered semantic transforms.

Targets the no-match, blocker/refusal, syntax-error and successful-rewrite
branches of organize_imports, raise_from and security that the existing suites
leave uncovered. Deterministic, hermetic, in-memory source strings only.
"""

from __future__ import annotations

from app.execution.semantic.transforms.organize_imports import apply as organize_apply
from app.execution.semantic.transforms.raise_from import apply as raise_from_apply
from app.execution.semantic.transforms.security import apply as security_apply


# --------------------------------------------------------------------------
# organize_imports
# --------------------------------------------------------------------------

def test_organize_syntax_error_returns_none():
    # Unparseable source -> honest no-op, no crash.
    assert organize_apply("m.py", "def f(:\n") is None


def test_organize_removes_unused_import_from():
    # `from sys import argv` is used; `from os import path` is not -> drop it.
    src = "from os import path\nfrom sys import argv\nargv\n"
    result = organize_apply("m.py", src)
    assert result is not None
    out = result.patch_requests[0]["new_content"]
    assert "from os import path" not in out
    assert "from sys import argv" in out
    assert result.transform_type == "organize_imports"
    compile(out, "m.py", "exec")


def test_organize_keeps_import_used_via_attribute():
    # `os.getcwd()` binds the name `os` through an Attribute access -> keep it.
    src = "import os\nos.getcwd()\n"
    assert organize_apply("m.py", src) is None


def test_organize_keeps_import_from_when_module_name_used():
    # The module's leading name is referenced, so the whole import stays.
    src = "from collections import abc\nabc\n"
    assert organize_apply("m.py", src) is None


def test_organize_honours_noqa_marker():
    # A noqa comment is a human declaring the import intentional.
    src = "import os  # noqa\n"
    assert organize_apply("m.py", src) is None


def test_organize_keeps_future_import():
    # __future__ imports are compiler directives, never "unused".
    src = "from __future__ import annotations\n"
    assert organize_apply("m.py", src) is None


def test_organize_no_unused_imports_returns_none():
    # Every import is used -> nothing to do.
    src = "import os\nimport sys\nos.getcwd()\nsys.exit()\n"
    assert organize_apply("m.py", src) is None


def test_organize_asname_alias_tracked():
    # The bound alias is used, so the aliased import must survive.
    src = "import numpy as np\nnp.array([1])\n"
    assert organize_apply("m.py", src) is None


# --------------------------------------------------------------------------
# raise_from
# --------------------------------------------------------------------------

def test_raise_from_syntax_error_returns_none():
    assert raise_from_apply("m.py", "def f(:\n", "x") is None


def test_raise_from_multiline_raise_is_declined():
    # A raise spanning lines is fragile to patch with line surgery -> skip.
    src = (
        "def f(p):\n"
        "    try:\n"
        "        g()\n"
        "    except OSError as err:\n"
        "        raise RuntimeError(\n"
        '            "boom"\n'
        "        )\n"
    )
    assert raise_from_apply("m.py", src, "x") is None


def test_raise_from_chains_raise_nested_in_if():
    # The fixable raise sits inside an `if` within the handler -> recurse in.
    src = (
        "def f(p):\n"
        "    try:\n"
        "        g()\n"
        "    except OSError as err:\n"
        "        if p:\n"
        '            raise RuntimeError("x")\n'
    )
    result = raise_from_apply("m.py", src, "x")
    assert result is not None
    out = result.patch_requests[0]["new_content"]
    assert 'raise RuntimeError("x") from err' in out
    compile(out, "m.py", "exec")


def test_raise_from_chains_raise_nested_in_for():
    # Recursion path through a loop body inside the handler.
    src = (
        "def f(p):\n"
        "    try:\n"
        "        g()\n"
        "    except OSError as err:\n"
        "        for i in p:\n"
        '            raise RuntimeError("x")\n'
    )
    result = raise_from_apply("m.py", src, "x")
    assert result is not None
    assert 'from err' in result.patch_requests[0]["new_content"]


def test_raise_from_chains_raise_in_else_branch():
    # _first_fixable_raise also scans the `orelse` of an If.
    src = (
        "def f(p):\n"
        "    try:\n"
        "        g()\n"
        "    except OSError as err:\n"
        "        if p:\n"
        "            log()\n"
        "        else:\n"
        '            raise RuntimeError("x")\n'
    )
    result = raise_from_apply("m.py", src, "x")
    assert result is not None
    assert 'from err' in result.patch_requests[0]["new_content"]


def test_raise_from_no_fixable_raise_returns_none():
    # Handler binds the exception but never re-raises -> nothing to chain.
    src = (
        "def f(p):\n"
        "    try:\n"
        "        g()\n"
        "    except OSError as err:\n"
        "        log(err)\n"
    )
    assert raise_from_apply("m.py", src, "x") is None


# --------------------------------------------------------------------------
# security: base-exception dispatch (whole _patch_base_exception path)
# --------------------------------------------------------------------------

def test_base_exception_narrowed_to_exception():
    src = "try:\n    f()\nexcept BaseException:\n    log()\n"
    result = security_apply("m.py", src, "base-exception too broad")
    assert result is not None
    assert result.transform_type == "base_exception_to_exception"
    out = result.patch_requests[0]["new_content"]
    assert "except Exception:" in out
    assert "BaseException" not in out
    compile(out, "m.py", "exec")


def test_base_exception_dispatch_via_baseexception_keyword():
    # The alternate dispatch spelling ("baseexception") reaches the same patcher.
    src = "try:\n    f()\nexcept BaseException:\n    cleanup()\n"
    result = security_apply("m.py", src, "BaseException handler is too broad")
    assert result is not None
    assert result.transform_type == "base_exception_to_exception"


def test_base_exception_that_reraises_is_declined():
    # A bare `raise` means the broad catch is intentional cleanup -> leave it.
    src = "try:\n    f()\nexcept BaseException:\n    raise\n"
    assert security_apply("m.py", src, "base-exception") is None


def test_base_exception_absent_returns_none():
    # No BaseException handler present -> nothing to narrow.
    src = "try:\n    f()\nexcept Exception:\n    pass\n"
    assert security_apply("m.py", src, "base-exception") is None


def test_security_syntax_error_returns_none():
    assert security_apply("m.py", "def f(:\n", "eval usage") is None


def test_security_unknown_title_returns_none():
    # Title matches no known issue keyword -> top-level no-op dispatch.
    src = "x = 1\n"
    assert security_apply("m.py", src, "some unrelated lint warning") is None
