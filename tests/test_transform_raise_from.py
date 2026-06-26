from __future__ import annotations

import ast

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


# --- runtime-equivalence: exec the rewrite and compare the RAISED exception ----
#
# ``compile()``/``ast.parse`` only proves syntax — it would happily pass the
# del-err regression (``raise X() from err`` after ``del err`` parses fine but
# raises ``UnboundLocalError`` at runtime). These tests EXEC the rewrite and assert
# the raised exception's TYPE and ``__cause__`` are what the chain promises, or that
# the unsafe shape was REFUSED. This is the layer that catches a behavior change a
# re-parse floor cannot see.

def _raised(source: str) -> tuple[type, type | None]:
    """Exec ``source`` (which must define ``f()`` that raises), call ``f()``, and
    return ``(type(exc), type(exc.__cause__))`` — the raised exception's type and its
    explicit cause's type (``None`` when there is no ``__cause__``)."""
    ns: dict = {}
    exec(compile(source, "m.py", "exec"), ns)  # noqa: S102 - test-local trusted source
    try:
        ns["f"]()
    except BaseException as exc:  # noqa: BLE001 - capture whatever propagates
        cause = exc.__cause__
        return type(exc), (type(cause) if cause is not None else None)
    raise AssertionError("f() did not raise")


def test_runtime_clean_case_chains_caught_exception():
    # The clean case LANDS and, at runtime, raises the SAME type with ``__cause__``
    # set to the CAUGHT exception (the chain the fix promises).
    src = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('orig')\n"
        "    except ValueError as err:\n"
        '        raise RuntimeError("boom")\n'
    )
    before_type, before_cause = _raised(src)
    assert before_type is RuntimeError and before_cause is None  # no chain yet
    res = raise_from_apply("m.py", src, "x")
    assert res is not None
    out = res.patch_requests[0]["new_content"]
    assert 'raise RuntimeError("boom") from err' in out
    after_type, after_cause = _raised(out)
    # SAME exception type; ``__cause__`` is now the caught ValueError.
    assert after_type is RuntimeError
    assert after_cause is ValueError


def test_runtime_del_binding_is_refused_not_unbound_local():
    # ``del err`` before the raise: a textual transform would land ``from err`` and
    # turn the runtime exception into UnboundLocalError. The fix REFUSES instead, so
    # the behavior (RuntimeError) is preserved unchanged.
    src = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('orig')\n"
        "    except ValueError as err:\n"
        "        del err\n"
        '        raise RuntimeError("boom")\n'
    )
    assert _raised(src)[0] is RuntimeError  # baseline raises RuntimeError
    assert raise_from_apply("m.py", src, "x") is None  # REFUSED (no behavior change)


def test_runtime_rebound_binding_is_refused_not_wrong_cause():
    # ``err = KeyError(...)`` before the raise: a textual transform would chain the
    # REBOUND KeyError as ``__cause__`` (a fabricated, wrong cause). The fix REFUSES,
    # so it never falsifies the "chains to its original cause" claim.
    src = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('orig')\n"
        "    except ValueError as err:\n"
        "        err = KeyError('x')\n"
        '        raise RuntimeError("boom")\n'
    )
    assert _raised(src)[0] is RuntimeError
    assert raise_from_apply("m.py", src, "x") is None  # REFUSED (no wrong cause landed)


def test_runtime_string_collision_splice_is_correct_not_corrupting():
    # The raise's source text also appears in a string literal earlier on the SAME
    # physical line. A textual ``str.replace`` would splice ``from err`` INTO the
    # string and leave the REAL raise un-caused (a corruption/churn loop). The
    # column-offset splice chains the REAL raise and leaves the string intact.
    src = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('orig')\n"
        "    except ValueError as err:\n"
        '        tag = "raise RuntimeError(1)"; raise RuntimeError(1)\n'
    )
    res = raise_from_apply("m.py", src, "x")
    assert res is not None
    out = res.patch_requests[0]["new_content"]
    # The string literal is UNTOUCHED; the REAL raise carries the chain.
    assert 'tag = "raise RuntimeError(1)"; raise RuntimeError(1) from err' in out
    assert 'tag = "raise RuntimeError(1) from err"' not in out  # not spliced into string
    ast.parse(out)  # re-parses
    after_type, after_cause = _raised(out)
    assert after_type is RuntimeError
    assert after_cause is ValueError  # chained to the CAUGHT exception, correctly
    # Idempotent: a second apply on the landed output is a byte-identical no-op.
    assert raise_from_apply("m.py", out, "x") is None


def test_runtime_multi_occurrence_but_safe_chains_correctly():
    # The constructor argument repeats the callable name (``RuntimeError`` appears
    # twice on the line), but there is no del/rebind of ``err`` — so the fix LANDS,
    # splicing exactly once at the raise's end and chaining the caught exception.
    src = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('orig')\n"
        "    except ValueError as err:\n"
        "        raise RuntimeError(str(RuntimeError))\n"
    )
    res = raise_from_apply("m.py", src, "x")
    assert res is not None
    out = res.patch_requests[0]["new_content"]
    assert out.count(" from err") == 1  # spliced exactly once
    assert "raise RuntimeError(str(RuntimeError)) from err" in out
    after_type, after_cause = _raised(out)
    assert after_type is RuntimeError
    assert after_cause is ValueError


def test_safe_attribute_mutation_of_binding_still_lands():
    # ``err.args = ...`` MUTATES the caught exception but does NOT rebind the name, so
    # ``err`` still names the caught exception at the raise -> the fix LANDS.
    src = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('orig')\n"
        "    except ValueError as err:\n"
        "        err.args = ('annotated',)\n"
        '        raise RuntimeError("boom")\n'
    )
    res = raise_from_apply("m.py", src, "x")
    assert res is not None
    after_type, after_cause = _raised(res.patch_requests[0]["new_content"])
    assert after_type is RuntimeError
    assert after_cause is ValueError
