"""Mine stub WITNESSES from a function's OWN docstring ``>>>`` doctests.

Until now witnesses came ONLY from test FILES (``_function_witnesses`` /
``_witnesses_in_file``), so a stub whose contract lives in its docstring examples
was invisible — never filled. This suite pins a SECOND witness source: the stub's
own docstring doctest examples, fed into the SAME template machinery (every
family) the test-file witnesses feed. A doctest ``>>> double(3)\\n6`` is the same
KIND of witness as ``assert double(3) == 6``, so it flows through the identical
accept-gate, off-witness canary, >=2-distinct overfit floor and ambiguity arbiter
— no new template logic, only a new witness SOURCE, and never-fake-green holds.

How it reuses the existing machinery (no reimplementation):

* ``doctest.DocTestParser`` extracts each ``>>> <call>`` / ``<expected>`` pair;
* the call is parsed in ``mode='eval'`` (rejecting assignments, multi-statement
  and ``raise`` examples) and accepted only when it is a direct ``stub.name(...)``
  call (``_is_symbol_call``);
* the args text is rendered by the EXISTING ``_render_call_args`` (rejecting
  keyword/starred args) and the literal-ness of both args and the expected
  ``want`` is decided by the EXISTING ``_literal_tuple`` / ``_literal_value``
  extractors — a non-literal, prose, or exception example is simply IGNORED.

GUARDS pinned here: a doctest example is a witness ONLY if it is a literal call to
the stub's own function with literal args + literal expected (same strictness as
the test-file extractor); the >=2-distinct-witness floor still applies (a single
doctest example does NOT qualify); a doctest example MERGES with any test-file
assert for the same function (more evidence is better, consistency is enforced by
the accept-gate); a malformed / garbage docstring raises NOTHING and yields no
witness; deterministic (examples mined in source order, after the test files);
and the doctest pass is ADDITIVE — with no ``module_source`` the witness set is
byte-for-byte the prior test-file-only behavior. An end-to-end check confirms the
in-process ``can_fill_stub_in_process`` now fills a doctest-only stub.
"""

from __future__ import annotations

from pathlib import Path


# --- helpers -----------------------------------------------------------------

def _stub(src: str):
    """The first (only) stub the source declares — the function under fill."""
    from app.execution.stub_synthesis import find_stub_functions

    stubs = find_stub_functions(src)
    assert stubs, "fixture must declare exactly one stub"
    return stubs[0]


def _doctest_ws(src: str):
    """The ``(args_text, expected_text)`` witnesses mined from the stub's own
    docstring ``>>>`` examples in ``src``."""
    from app.execution.stub_synthesis import _doctest_witnesses

    return _doctest_witnesses(src, _stub(src))


def _bodies(src: str):
    """The candidate body EXPRS proposed for the stub, seeded by its doctest
    witnesses — the surface the template families read."""
    from app.execution.stub_synthesis import candidate_bodies

    return [expr for _label, expr in candidate_bodies(_stub(src), _doctest_ws(src))]


# --- ACCEPTS: a doctest-only contract becomes fillable -----------------------

def test_two_doctest_examples_mine_scalar_double():
    # >>> double(3) -> 6, >>> double(5) -> 10 : two LITERAL calls with literal
    # expected, mined in source order, seed the value-derived `n * 2` template.
    src = (
        "def double(n):\n"
        '    """\n'
        "    Doubles n.\n\n"
        "    >>> double(3)\n"
        "    6\n"
        "    >>> double(5)\n"
        "    10\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    assert _doctest_ws(src) == [("3", "6"), ("5", "10")]
    assert "n * 2" in _bodies(src)


def test_two_doctest_examples_mine_string_upper():
    # >>> shout('ab') -> 'AB', >>> shout('cd') -> 'CD' : string literals flow
    # through the SAME literal extractor and seed the `s.upper()` family.
    src = (
        "def shout(s):\n"
        '    """\n'
        "    >>> shout('ab')\n"
        "    'AB'\n"
        "    >>> shout('cd')\n"
        "    'CD'\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    assert _doctest_ws(src) == [("'ab'", "'AB'"), ("'cd'", "'CD'")]
    assert "s.upper()" in _bodies(src)


def test_doctest_only_stub_fills_in_process(tmp_path: Path):
    # End-to-end: a stub whose ONLY contract is its docstring examples (NO test
    # files) is synthesized in-process once `module_source` is supplied — `n * 2`.
    from app.execution.stub_synthesis import (
        can_fill_stub_in_process, synthesize_expr_from_witnesses,
    )

    src = (
        "def double(n):\n"
        '    """\n'
        "    >>> double(3)\n"
        "    6\n"
        "    >>> double(5)\n"
        "    10\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    stub = _stub(src)
    assert synthesize_expr_from_witnesses(tmp_path, [], stub, src) == "n * 2"
    assert can_fill_stub_in_process(tmp_path, [], stub, src) is True


def test_doctest_merges_with_test_file_assert(tmp_path: Path):
    # A SINGLE doctest example MERGED with a SINGLE test-file assert (distinct
    # args) clears the >=2-distinct floor together and fills. The test-file
    # witness comes first, the doctest one after — a stable, deterministic order.
    from app.execution.stub_synthesis import (
        _function_witnesses, synthesize_expr_from_witnesses,
    )

    src = (
        "def double(n):\n"
        '    """\n'
        "    >>> double(3)\n"
        "    6\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    (tmp_path / "test_m.py").write_text(
        "from m import double\n"
        "def test_x():\n"
        "    assert double(5) == 10\n",
        encoding="utf-8",
    )
    stub = _stub(src)
    # test-file witness FIRST, docstring example AFTER (source order, additive).
    assert _function_witnesses(tmp_path, ["test_m.py"], stub, src) == [
        ("5", "10"), ("3", "6"),
    ]
    assert synthesize_expr_from_witnesses(
        tmp_path, ["test_m.py"], stub, src) == "n * 2"


# --- REFUSALS: the same strictness as the test-file extractor ----------------

def test_single_doctest_below_distinct_floor(tmp_path: Path):
    # A LONE doctest example yields ONE witness — below the >=2-distinct floor a
    # bare constant could overfit it, so the stub is NOT fillable in-process.
    from app.execution.stub_synthesis import can_fill_stub_in_process

    src = (
        "def double(n):\n"
        '    """\n'
        "    >>> double(3)\n"
        "    6\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    assert _doctest_ws(src) == [("3", "6")]  # mined, but only one
    assert can_fill_stub_in_process(tmp_path, [], _stub(src), src) is False


def test_non_literal_prose_and_exception_examples_ignored():
    # Only `f(3) -> 6` is a literal call with literal expected. `x = 5` (an
    # assignment, not an expression), `f(x)` (non-literal arg), and the Traceback
    # (a non-literal expected) are each IGNORED — never guessed.
    src = (
        "def f(n):\n"
        '    """\n'
        "    Compute stuff.\n"
        "    >>> x = 5\n"
        "    >>> f(x)\n"
        "    10\n"
        "    >>> f(2)\n"
        "    Traceback (most recent call last):\n"
        "    ValueError\n"
        "    >>> f(3)\n"
        "    6\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    assert _doctest_ws(src) == [("3", "6")]


def test_foreign_and_method_calls_ignored():
    # `obj.f(3)` (a method call, not a bare-Name callee) and `g(3)` (a DIFFERENT
    # function) are not the stub's own contract — only `f(4) -> 8` is mined.
    src = (
        "def f(n):\n"
        '    """\n'
        "    >>> obj.f(3)\n"
        "    6\n"
        "    >>> g(3)\n"
        "    6\n"
        "    >>> f(4)\n"
        "    8\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    assert _doctest_ws(src) == [("4", "8")]


def test_keyword_and_starred_args_ignored():
    # A keyword arg (`f(n=3)`) and a starred arg (`f(*xs)`) make the witness's arg
    # tuple unrecoverable, so `_render_call_args` rejects them — only `f(2) -> 4`.
    src = (
        "def f(n):\n"
        '    """\n'
        "    >>> f(n=3)\n"
        "    6\n"
        "    >>> f(*xs)\n"
        "    6\n"
        "    >>> f(2)\n"
        "    4\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    assert _doctest_ws(src) == [("2", "4")]


def test_malformed_docstring_no_crash_no_witness():
    # A garbage docstring (an unterminated call, gibberish expected) must raise
    # NOTHING and yield no witness — parsing is fully guarded.
    src = (
        "def f(n):\n"
        '    """\n'
        "    >>> f(  (((\n"
        "    ???\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    assert _doctest_ws(src) == []


def test_no_docstring_and_unparseable_source_yield_nothing():
    # A stub with NO docstring yields no witness; an unparseable source yields no
    # witness (and does not raise) — both edge/empty paths.
    from app.execution.stub_synthesis import _doctest_witnesses

    no_doc = "def f(n):\n    raise NotImplementedError\n"
    stub = _stub(no_doc)
    assert _doctest_witnesses(no_doc, stub) == []
    assert _doctest_witnesses("def f(:\n  bad", stub) == []


def test_additive_no_source_is_test_file_only(tmp_path: Path):
    # With NO `module_source`, the witness set is byte-for-byte the test-file-only
    # behavior: a doctest-only stub is NOT fillable (the source is never read), so
    # the doctest pass is purely opt-in/additive and shifts no existing fill.
    from app.execution.stub_synthesis import (
        _function_witnesses, can_fill_stub_in_process,
    )

    src = (
        "def double(n):\n"
        '    """\n'
        "    >>> double(3)\n"
        "    6\n"
        "    >>> double(5)\n"
        "    10\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    stub = _stub(src)
    assert _function_witnesses(tmp_path, [], stub) == []  # default: no doctest pass
    assert can_fill_stub_in_process(tmp_path, [], stub) is False


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_source_same_witnesses():
    # Same source -> same witnesses, same order, every time (no clock/random).
    src = (
        "def double(n):\n"
        '    """\n'
        "    >>> double(3)\n"
        "    6\n"
        "    >>> double(5)\n"
        "    10\n"
        "    >>> double(7)\n"
        "    14\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    first = _doctest_ws(src)
    again = _doctest_ws(src)
    assert first == [("3", "6"), ("5", "10"), ("7", "14")]
    assert first == again
