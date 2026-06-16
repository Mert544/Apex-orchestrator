"""Exception-handling HYGIENE analyzer: per-category counts, location, exclusion.

Exercises each of the five conservative rules (bare ``except``, broad
``except Exception``/``BaseException``, swallowed handlers, ``raise`` without
``from`` chaining, oversized ``try`` bodies) so each is counted AND located,
confirms a clean narrow ``try``/``except`` is left untouched, and pins the
project-level guarantees: empty-safety, determinism, and test/fixture exclusion.
"""

from __future__ import annotations

from pathlib import Path

from app.tools.exception_hygiene import (
    ExceptionHygiene,
    analyze_exception_hygiene,
)


def _write(root: Path, rel: str, source: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# (a) bare except
# --------------------------------------------------------------------------


def test_bare_except_counted_and_located(tmp_path: Path):
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except:\n"          # line 4 — bare
        "        handle()\n",
    )
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.bare_except == 1
    assert profile.broad_except == 0
    offenders = [o for o in profile.offenders if o["kind"] == "bare_except"]
    assert offenders == [{"module": "app.m", "line": 4, "kind": "bare_except"}]


# --------------------------------------------------------------------------
# (b) broad except Exception / BaseException (incl. tuple); alias NOT flagged
# --------------------------------------------------------------------------


def test_broad_except_exception_counted(tmp_path: Path):
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n        g()\n"
        "    except Exception:\n        log()\n"        # line 4
        "    try:\n        g()\n"
        "    except BaseException as e:\n        log(e)\n",  # line 8
    )
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.broad_except == 2
    assert profile.bare_except == 0
    lines = sorted(
        o["line"] for o in profile.offenders if o["kind"] == "broad_except"
    )
    assert lines == [4, 8]


def test_broad_except_tuple_with_exception_counted(tmp_path: Path):
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n        g()\n"
        "    except (ValueError, Exception):\n        log()\n",
    )
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.broad_except == 1


def test_aliased_or_attribute_catchall_not_flagged(tmp_path: Path):
    # We can't prove `myexc`/`mod.Exception` resolves to a builtin catch-all.
    _write(
        tmp_path,
        "app/m.py",
        "import mod\n"
        "myexc = ValueError\n"
        "def f():\n"
        "    try:\n        g()\n"
        "    except myexc:\n        log()\n"
        "    try:\n        g()\n"
        "    except mod.Exception:\n        log()\n",
    )
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.broad_except == 0


def test_bare_and_broad_not_double_counted(tmp_path: Path):
    # A bare except is the broadest net; it must not ALSO count as broad.
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n        g()\n"
        "    except:\n        handle()\n",
    )
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.bare_except == 1
    assert profile.broad_except == 0


# --------------------------------------------------------------------------
# (c) swallowed: body is only `pass` or only `...`
# --------------------------------------------------------------------------


def test_swallowed_pass_and_ellipsis_counted(tmp_path: Path):
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n        g()\n"
        "    except ValueError:\n        pass\n"         # line 4 swallow
        "    try:\n        g()\n"
        "    except KeyError:\n        ...\n",            # line 8 swallow
    )
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.swallowed == 2
    lines = sorted(
        o["line"] for o in profile.offenders if o["kind"] == "swallowed"
    )
    assert lines == [4, 8]


def test_handler_with_real_body_not_swallowed(tmp_path: Path):
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n        g()\n"
        "    except ValueError:\n"
        "        log('failed')\n"
        "        return None\n",
    )
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.swallowed == 0


# --------------------------------------------------------------------------
# (d) raise without from inside except (lost chaining)
# --------------------------------------------------------------------------


def test_raise_without_from_counted(tmp_path: Path):
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n        g()\n"
        "    except ValueError:\n"
        "        raise RuntimeError('boom')\n",   # line 5 — no `from`
    )
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.raise_without_from == 1
    offenders = [
        o for o in profile.offenders if o["kind"] == "raise_without_from"
    ]
    assert offenders == [
        {"module": "app.m", "line": 5, "kind": "raise_without_from"}
    ]


def test_raise_from_and_bare_reraise_not_flagged(tmp_path: Path):
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n        g()\n"
        "    except ValueError as e:\n"
        "        raise RuntimeError('boom') from e\n"   # chained: ok
        "    try:\n        g()\n"
        "    except KeyError:\n"
        "        raise\n"                                 # re-raise: ok
        "    try:\n        g()\n"
        "    except IndexError:\n"
        "        raise RuntimeError('x') from None\n",    # explicit suppress: ok
    )
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.raise_without_from == 0


def test_raise_in_nested_def_not_attributed_to_handler(tmp_path: Path):
    # A `raise` inside a function defined within the handler is its own scope.
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n        g()\n"
        "    except ValueError:\n"
        "        def inner():\n"
        "            raise RuntimeError('boom')\n"   # belongs to inner, not handler
        "        register(inner)\n",
    )
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.raise_without_from == 0


def test_raise_without_from_inside_handler_control_flow(tmp_path: Path):
    # A raise nested in an `if` directly in the handler still counts.
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n        g()\n"
        "    except ValueError:\n"
        "        if cond():\n"
        "            raise RuntimeError('boom')\n",   # line 6
    )
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.raise_without_from == 1
    assert profile.offenders[0]["line"] == 6


# --------------------------------------------------------------------------
# (e) large try body (> threshold top-level statements)
# --------------------------------------------------------------------------


def test_large_try_counted(tmp_path: Path):
    body = "".join(f"        s{i}()\n" for i in range(15))
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n" + body +
        "    except ValueError:\n        log()\n",
    )
    profile = analyze_exception_hygiene(tmp_path)  # default threshold 12
    assert profile.large_try == 1
    offenders = [o for o in profile.offenders if o["kind"] == "large_try"]
    assert offenders[0]["line"] == 2  # the `try` line


def test_try_at_threshold_not_flagged(tmp_path: Path):
    # Exactly max_try_body statements => strictly-greater-than => not flagged.
    body = "".join(f"        s{i}()\n" for i in range(12))
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n" + body +
        "    except ValueError:\n        log()\n",
    )
    profile = analyze_exception_hygiene(tmp_path, max_try_body=12)
    assert profile.large_try == 0


def test_large_try_threshold_is_configurable(tmp_path: Path):
    body = "".join(f"        s{i}()\n" for i in range(5))
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n" + body +
        "    except ValueError:\n        log()\n",
    )
    assert analyze_exception_hygiene(tmp_path, max_try_body=3).large_try == 1
    assert analyze_exception_hygiene(tmp_path, max_try_body=10).large_try == 0


# --------------------------------------------------------------------------
# Clean narrow try/except is not flagged at all
# --------------------------------------------------------------------------


def test_clean_narrow_try_except_not_flagged(tmp_path: Path):
    _write(
        tmp_path,
        "app/m.py",
        "def f():\n"
        "    try:\n"
        "        value = lookup()\n"
        "    except KeyError as e:\n"
        "        raise LookupError('missing') from e\n"
        "    return value\n",
    )
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.total == 0
    assert profile.offenders == []
    assert profile.files_scanned == 1


# --------------------------------------------------------------------------
# Empty-safety
# --------------------------------------------------------------------------


def test_empty_tree_is_safe(tmp_path: Path):
    profile = analyze_exception_hygiene(tmp_path)
    assert isinstance(profile, ExceptionHygiene)
    assert profile.total == 0
    assert profile.offenders == []
    assert profile.files_scanned == 0


def test_handler_free_tree_is_safe(tmp_path: Path):
    _write(tmp_path, "app/m.py", "def f():\n    return 1\n")
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.total == 0
    assert profile.offenders == []
    assert profile.files_scanned == 1


def test_syntax_error_file_does_not_abort(tmp_path: Path):
    _write(tmp_path, "app/broken.py", "def f(:\n    pass\n")
    _write(
        tmp_path,
        "app/ok.py",
        "def g():\n    try:\n        h()\n    except:\n        pass\n",
    )
    profile = analyze_exception_hygiene(tmp_path)
    # The good file still contributes; the broken one is silently skipped.
    assert profile.bare_except == 1
    assert profile.swallowed == 1


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_determinism(tmp_path: Path):
    for i in range(3):
        _write(
            tmp_path,
            f"app/pkg/m{i}.py",
            "def f():\n"
            "    try:\n        g()\n"
            "    except:\n        pass\n"
            "    try:\n        g()\n"
            "    except Exception:\n        raise RuntimeError('x')\n",
        )
    first = analyze_exception_hygiene(tmp_path)
    second = analyze_exception_hygiene(tmp_path)
    assert first == second
    assert first.offenders == second.offenders
    # Offenders are sorted by (module, line, kind).
    keys = [(o["module"], o["line"], o["kind"]) for o in first.offenders]
    assert keys == sorted(keys)


def test_offenders_capped_at_twenty(tmp_path: Path):
    # 30 modules, each with a bare except => 30 offenders, capped to 20.
    for i in range(30):
        _write(
            tmp_path,
            f"app/m{i:02d}.py",
            "def f():\n    try:\n        g()\n    except:\n        pass\n",
        )
    profile = analyze_exception_hygiene(tmp_path)
    assert profile.bare_except == 30  # counts are NOT capped
    assert len(profile.offenders) == 20  # offender list IS capped


# --------------------------------------------------------------------------
# Test / fixture exclusion
# --------------------------------------------------------------------------


def test_tests_and_fixtures_excluded(tmp_path: Path):
    # All of these are excluded definition sites and must contribute nothing.
    bad = "def f():\n    try:\n        g()\n    except:\n        pass\n"
    _write(tmp_path, "tests/test_thing.py", bad)
    _write(tmp_path, "app/test_inline.py", bad)
    _write(tmp_path, "app/conftest.py", bad)
    _write(tmp_path, "app/fixtures/sample.py", bad)
    _write(tmp_path, "pkg/tests/helpers.py", bad)
    # One real module that SHOULD be flagged.
    _write(tmp_path, "app/real.py", bad)

    profile = analyze_exception_hygiene(tmp_path)
    assert profile.bare_except == 1
    assert profile.files_scanned == 1
    assert {o["module"] for o in profile.offenders} == {"app.real"}


def test_max_files_cap_is_deterministic(tmp_path: Path):
    for i in range(5):
        _write(
            tmp_path,
            f"app/m{i}.py",
            "def f():\n    try:\n        g()\n    except:\n        pass\n",
        )
    # Sorted file list => capping to 2 always picks the same first two modules.
    a = analyze_exception_hygiene(tmp_path, max_files=2)
    b = analyze_exception_hygiene(tmp_path, max_files=2)
    assert a.files_scanned == 2
    assert a == b
