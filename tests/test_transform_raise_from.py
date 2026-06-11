from __future__ import annotations

from app.execution.semantic.transforms.raise_from import apply as raise_from_apply


def test_appends_from_to_bound_handler():
    src = (
        "def f(p):\n"
        "    try:\n"
        "        g(p)\n"
        "    except OSError as err:\n"
        '        raise RuntimeError("boom")\n'
    )
    result = raise_from_apply("m.py", src, "Chain re-raised exceptions")
    assert result is not None
    out = result.patch_requests[0]["new_content"]
    assert 'raise RuntimeError("boom") from err' in out
    compile(out, "m.py", "exec")                       # generated code runs


def test_unbound_handler_is_declined():
    # No `as err` binding -> nothing safe to chain to -> honest no-op.
    src = (
        "def f(p):\n"
        "    try:\n"
        "        g(p)\n"
        "    except OSError:\n"
        '        raise RuntimeError("boom")\n'
    )
    assert raise_from_apply("m.py", src, "Chain re-raised exceptions") is None


def test_already_chained_and_bare_raise_left_alone():
    src = (
        "def f(p):\n"
        "    try:\n"
        "        g(p)\n"
        "    except OSError as err:\n"
        '        raise RuntimeError("boom") from err\n'
        "    except ValueError as e:\n"
        "        raise\n"
    )
    assert raise_from_apply("m.py", src, "Chain re-raised exceptions") is None


def test_trailing_comment_is_preserved():
    src = (
        "def f(p):\n"
        "    try:\n"
        "        g(p)\n"
        "    except OSError as exc:\n"
        '        raise RuntimeError("boom")  # explain\n'
    )
    out = raise_from_apply("m.py", src, "x").patch_requests[0]["new_content"]
    assert 'raise RuntimeError("boom") from exc  # explain' in out
    compile(out, "m.py", "exec")


def test_nested_function_raise_is_not_chained():
    # A raise inside a nested def fires later, outside the handler -> skip.
    src = (
        "def f(p):\n"
        "    try:\n"
        "        g(p)\n"
        "    except OSError as err:\n"
        "        def cb():\n"
        '            raise RuntimeError("later")\n'
        "        return cb\n"
    )
    assert raise_from_apply("m.py", src, "x") is None
