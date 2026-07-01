"""Shield mines docstring examples into REAL correctness assertions.

`apex shield` already pins CURRENT behaviour with value oracles. This suite
covers the upgrade: it ALSO mines doctest-style ``>>> expr`` / expected-output
pairs out of docstrings (via the stdlib ``doctest`` parser -- deterministic,
offline, zero-token) and emits assertions of the DOCUMENTED-correct behaviour:

  - a documented example the CURRENT code satisfies -> a normal passing
    assertion (a real correctness pin, not just a current-behaviour pin);
  - a documented example the code does NOT satisfy (a real bug / unfinished
    stub) -> an honest ``@pytest.mark.xfail(strict=True)`` so the suite stays
    green AND the discrepancy is surfaced, never hidden, never a false green,
    never silently dropped;
  - a documented exception -> a ``pytest.raises`` assertion;
  - a function with NO docstring example -> the existing value-oracle/smoke path
    is unchanged.

Everything stays valid Python (``ast.parse``), deterministic across runs, and
the generated suite is green after ``--apply``.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

from app.execution.test_shield import (
    generate_characterization_test,
    write_shield_test,
)


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")


def _make_pkg(root: Path, rel: str, body: str) -> str:
    _write(root, "mypkg/__init__.py", "")
    _write(root, rel, body)
    return rel


def _run_generated(tmp_path: Path, path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", path, "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


# --- documented-correct example, code is correct -> passing assertion --------


def test_correct_docstring_example_becomes_passing_assertion(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/fact.py",
        '''
        def factorial(n):
            """Compute n!.

            Examples:
                >>> factorial(5)
                120
            """
            result = 1
            for i in range(2, n + 1):
                result *= i
            return result
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # A real correctness assertion of the DOCUMENTED answer (not an xfail).
    assert "assert repr(factorial(5)) == '120'" in shield.content
    assert "xfail" not in shield.content
    # Valid Python, and green after apply.
    ast.parse(shield.content)
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- documented-but-unmet example -> honest xfail (never a fake green) --------


def test_unsatisfied_docstring_example_becomes_honest_xfail(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/buggy.py",
        '''
        def double(n):
            """Double a number.

            Examples:
                >>> double(4)
                8
            """
            return n + 1  # BUG: should be n * 2
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # The discrepancy is SURFACED, not dropped: the example is still emitted...
    assert "repr(double(4)) == '8'" in shield.content
    # ...but honestly, as a strict xfail (NOT a passing assertion of a wrong answer).
    assert "@pytest.mark.xfail(strict=True" in shield.content
    assert "docstring example not yet satisfied" in shield.content
    ast.parse(shield.content)
    # Suite stays green: the documented-but-unmet example xfails, it does not fail.
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "xfailed" in proc.stdout


def test_unsatisfied_example_is_never_a_fake_passing_assertion(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/stub.py",
        '''
        def answer():
            """The answer.

            Examples:
                >>> answer()
                42
            """
            raise NotImplementedError  # an unfinished stub
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # It must NOT emit a plain passing assertion of the undelivered answer; xfail.
    assert "@pytest.mark.xfail(strict=True" in shield.content
    assert "repr(answer()) == '42'" in shield.content
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- documented exception -> pytest.raises -----------------------------------


def test_documented_exception_becomes_pytest_raises(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/div.py",
        '''
        def divide(a, b):
            """Divide a by b.

            Examples:
                >>> divide(6, 0)
                Traceback (most recent call last):
                ZeroDivisionError: division by zero
            """
            return a / b
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "with pytest.raises(ZeroDivisionError):" in shield.content
    assert "divide(6, 0)" in shield.content
    # The code really does raise -> this is a PASSING assertion, not an xfail.
    assert "xfail" not in shield.content
    ast.parse(shield.content)
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_bare_type_exception_becomes_passing_pytest_raises(tmp_path):
    # A message-LESS traceback: the want's last line is a BARE exception type
    # (``TypeError``, no ``: message``). doctest's strict exception matcher would
    # reject this form even when the code raises EXACTLY that type, which would
    # mis-score a SATISFIED contract as unmet and emit a strict-xfail that XPASSes
    # at runtime -> a RED suite on CORRECT code (a fake-red honesty bug). The code
    # really does raise TypeError, so this must be a PASSING pytest.raises.
    rel = _make_pkg(
        tmp_path,
        "mypkg/baretype.py",
        '''
        def f(x):
            """Add one to x.

            Examples:
                >>> f(None)
                Traceback (most recent call last):
                TypeError
            """
            return x + 1
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "with pytest.raises(TypeError):" in shield.content
    assert "f(None)" in shield.content
    # The code really does raise TypeError -> PASSING assertion, never a strict-xfail.
    assert "xfail" not in shield.content
    ast.parse(shield.content)
    # And the generated suite is GREEN (no [XPASS(strict)] on correct code).
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "XPASS" not in proc.stdout


def test_bare_type_exception_not_raised_becomes_xfail(tmp_path):
    # Same message-less bare-type form, but the code does NOT raise it -> the
    # documented contract is unmet, so it must stay an HONEST xfail (never a fake
    # green). This guards that the bare-type fix did not blanket-pass everything.
    rel = _make_pkg(
        tmp_path,
        "mypkg/barenoraise.py",
        '''
        def g(x):
            """Return zero.

            Examples:
                >>> g(None)
                Traceback (most recent call last):
                TypeError
            """
            return 0  # never raises -> the documented contract is unmet
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "@pytest.mark.xfail(strict=True" in shield.content
    assert "with pytest.raises(TypeError):" in shield.content
    ast.parse(shield.content)
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "xfailed" in proc.stdout


def test_documented_exception_not_raised_becomes_xfail(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/nodiv.py",
        '''
        def safe(a, b):
            """Divide a by b.

            Examples:
                >>> safe(6, 0)
                Traceback (most recent call last):
                ZeroDivisionError: division by zero
            """
            return 0  # never raises -> the documented contract is unmet
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # Documented exception the code does NOT raise -> honest xfail, not green.
    assert "@pytest.mark.xfail(strict=True" in shield.content
    assert "with pytest.raises(ZeroDivisionError):" in shield.content
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- no docstring example -> existing value-oracle path is unchanged ----------


def test_no_docstring_example_keeps_value_oracle(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/plain.py",
        """
        def add(a: int, b: int):
            return a + b
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # No examples mined -> no docexample tests, no pytest import added.
    assert "docexample" not in shield.content
    assert "import pytest" not in shield.content
    # The existing value-oracle pin is unchanged.
    assert "assert fn(0, 0) == 0" in shield.content
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_docstring_without_examples_adds_nothing(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/described.py",
        '''
        def add(a: int, b: int):
            """Add two numbers (prose only, no doctest example)."""
            return a + b
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "docexample" not in shield.content
    assert "assert fn(0, 0) == 0" in shield.content


# --- composition: examples AND value oracles coexist -------------------------


def test_examples_and_value_oracles_coexist(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/both.py",
        '''
        def doc(n: int):
            """Increment.

            Examples:
                >>> doc(1)
                2
            """
            return n + 1

        def nodoc(n: int):
            return n * 10
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # The documented function gets a documented-correctness assertion...
    assert "assert repr(doc(1)) == '2'" in shield.content
    # ...and the undocumented one keeps its current-behaviour value oracle.
    assert "assert fn(0) == 0" in shield.content  # nodoc(0) == 0
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- determinism + idempotency + validity ------------------------------------


def test_generated_doc_assertions_are_deterministic(tmp_path):
    body = '''
        def factorial(n):
            """Compute n!.

            Examples:
                >>> factorial(5)
                120
                >>> factorial(0)
                1
            """
            result = 1
            for i in range(2, n + 1):
                result *= i
            return result
    '''
    rel = _make_pkg(tmp_path, "mypkg/det.py", body)
    first = generate_characterization_test(tmp_path, rel)
    second = generate_characterization_test(tmp_path, rel)
    assert first is not None and second is not None
    assert first.content == second.content
    # Document order preserved across the two examples.
    assert first.content.index("factorial(5)") < first.content.index("factorial(0)")
    ast.parse(first.content)


def test_idempotent_apply_does_not_clobber(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/idem.py",
        '''
        def f(n):
            """Doubler.

            Examples:
                >>> f(2)
                4
            """
            return n * 2
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    write_shield_test(tmp_path, shield)
    # Re-running after apply refuses (file exists) -> idempotent, no second write.
    assert generate_characterization_test(tmp_path, rel) is None


def test_multistatement_example_is_not_falsely_pinned(tmp_path):
    # A setup-dependent example (`>>> obj = C()` then `>>> obj.m()`) is not a
    # self-contained single expression. The single-expression part cannot resolve
    # `obj` in isolation, so it is honestly xfailed, never asserted as a fake green.
    rel = _make_pkg(
        tmp_path,
        "mypkg/multi.py",
        '''
        class C:
            """A holder.

            Examples:
                >>> c = C()
                >>> c.value()
                7
            """
            def value(self):
                return 7
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    ast.parse(shield.content)
    # The assignment `c = C()` is dropped (not a single expression); the
    # `c.value()` example cannot resolve `c` standalone -> honest xfail, not green.
    if "c.value()" in shield.content:
        assert "xfail" in shield.content
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- set/dict-repr example -> never a PYTHONHASHSEED-fragile assertion ---------
# A docstring whose expected output is a ``set``/``dict`` repr re-renders in a
# DIFFERENT element/key order under another ``PYTHONHASHSEED``. A landed
# ``assert repr(expr) == '{...}'`` over it is green under one seed and RED under
# another -- a future-red fake-green. The generator must NEVER land such an
# assertion (it REFUSES the example, mirroring pin_doctest's guard).


def _run_generated_with_seed(
    tmp_path: Path, path: str, seed: str
) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    return subprocess.run(
        [sys.executable, "-m", "pytest", path, "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )


def test_set_repr_example_is_never_seed_fragile_assertion(tmp_path):
    # A public function whose docstring example returns a SET literal (its repr
    # order is PYTHONHASHSEED-dependent). The generator must NOT emit
    # ``assert repr(tags(...)) == "{...}"`` -- that assertion could pass under one
    # seed and fail under another. It is refused (never landed).
    rel = _make_pkg(
        tmp_path,
        "mypkg/tags.py",
        '''
        def tags():
            """Return the tag set.

            Examples:
                >>> tags()
                {'a', 'b', 'c'}
            """
            return {'a', 'b', 'c'}
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    ast.parse(shield.content)
    # The seed-fragile ``assert repr(tags()) == '{...}'`` form is NOT rendered
    # (the doctest example is refused). A value-oracle ``assert fn() == {...}``
    # MAY appear -- that is set/dict EQUALITY, which is order-independent and
    # therefore seed-stable; only the ``repr`` comparison is fragile.
    assert "repr(tags())" not in shield.content
    # Proven stable: the LANDED suite stays green under two distinct hash seeds
    # (a fragile set-repr assertion would go RED under at least one).
    path = write_shield_test(tmp_path, shield)
    for seed in ("0", "424242"):
        proc = _run_generated_with_seed(tmp_path, path, seed)
        assert proc.returncode == 0, (
            f"seed={seed}: " + proc.stdout + proc.stderr
        )


def test_dict_repr_example_is_never_seed_fragile_assertion(tmp_path):
    # The dict sibling: a docstring example whose expected output is a DICT repr
    # is refused too (its key order can be set-iteration-derived, so it is
    # likewise seed-fragile). No assertion over the dict repr is landed.
    rel = _make_pkg(
        tmp_path,
        "mypkg/lookup.py",
        '''
        def lookup():
            """Return the lookup mapping.

            Examples:
                >>> lookup()
                {'x': 1, 'y': 2}
            """
            return {'x': 1, 'y': 2}
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    ast.parse(shield.content)
    # The seed-fragile ``repr`` comparison is refused; a value-oracle equality
    # ``assert fn() == {...}`` (order-independent, seed-stable) may remain.
    assert "repr(lookup())" not in shield.content
    path = write_shield_test(tmp_path, shield)
    for seed in ("0", "424242"):
        proc = _run_generated_with_seed(tmp_path, path, seed)
        assert proc.returncode == 0, (
            f"seed={seed}: " + proc.stdout + proc.stderr
        )


def test_ordered_list_example_still_pinned_no_over_refusal(tmp_path):
    # No over-refusal: a docstring example whose expected output is an ORDERED
    # repr (a list -- order is stable across seeds) is still mined into a real
    # passing assertion. Only the unordered set/dict shape is refused.
    rel = _make_pkg(
        tmp_path,
        "mypkg/seq.py",
        '''
        def seq():
            """Return the sequence.

            Examples:
                >>> seq()
                [1, 2, 3]
            """
            return [1, 2, 3]
        ''',
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "assert repr(seq()) == '[1, 2, 3]'" in shield.content
    ast.parse(shield.content)
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
