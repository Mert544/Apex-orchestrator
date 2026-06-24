"""Environment/run-axis determinism for pin-doctest (latent fake-green fix).

pin-doctest LANDS a suite-enforced test that re-runs a function's ``>>>`` examples
via the stdlib ``doctest`` runner against the live ``__doc__``. Two latent hazards
made such a LANDED test green on the build machine yet RED elsewhere/next-run:

  * an example whose EXPECTED output is a ``set``/``dict`` repr (``{'a', 'b'}``)
    re-renders in a different order under another ``PYTHONHASHSEED``;
  * an example whose output reads the ENVIRONMENT (cwd / ``$HOME`` / a clock) is
    green only under the generation environment.

The fix (1) pins ``PYTHONHASHSEED=0`` in the gate-1 oracle ``examples_pass`` so
the GENERATION decision is deterministic, (2) REFUSES a function whose example has
a set/dict-repr expected output, and (3) REFUSES a function whose examples are not
GREEN under a varied environment (different cwd / ``$HOME`` / ``$TZ`` / ``$TMPDIR`` /
``PYTHONHASHSEED``). A stable example still pins.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.objectives.pin_doctest import (
    _examples_env_stable,
    _want_is_unordered_repr,
    plan_pin_doctest,
)

# A stable, currently-green, unenforced example -> pin-doctest pins it.
_STABLE = (
    "def double(n):\n"
    '    """Double n.\n\n'
    "    >>> double(3)\n"
    "    6\n"
    '    """\n'
    "    return n * 2\n"
)

# An example whose expected output is a SET repr (hash-seed-fragile order).
_SET_REPR = (
    "def letters():\n"
    '    """Letters.\n\n'
    "    >>> letters()\n"
    "    {'a', 'b', 'c'}\n"
    '    """\n'
    "    return set('abc')\n"
)

# An example whose expected output is a multi-key DICT repr.
_DICT_REPR = (
    "def sizes():\n"
    '    """Sizes.\n\n'
    "    >>> sizes()\n"
    "    {'a': 1, 'bb': 2}\n"
    '    """\n'
    "    return {'a': 1, 'bb': 2}\n"
)


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


# --- _want_is_unordered_repr (the set/dict-repr detector) ---------------------


def test_want_is_unordered_repr_flags_set_and_dict():
    assert _want_is_unordered_repr("{'a', 'b'}") is True       # set repr
    assert _want_is_unordered_repr("{1, 2, 3}") is True        # set repr
    assert _want_is_unordered_repr("{'a': 1, 'b': 2}") is True  # dict repr
    assert _want_is_unordered_repr("set()") is True            # empty set (refused)
    assert _want_is_unordered_repr("{}") is True               # empty dict (refused)


def test_want_is_unordered_repr_accepts_ordered_outputs():
    assert _want_is_unordered_repr("6") is False
    assert _want_is_unordered_repr("'hello'") is False
    assert _want_is_unordered_repr("[1, 2, 3]") is False       # list: order-stable text
    assert _want_is_unordered_repr("(1, 2)") is False
    assert _want_is_unordered_repr("True") is False
    assert _want_is_unordered_repr("not a literal") is False


# --- pin-doctest REFUSES set/dict-repr examples -------------------------------


def test_pin_doctest_refuses_set_repr_example(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _SET_REPR)
    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    assert not plan.new_contents  # the hash-seed-fragile example is never pinned
    assert not plan.blockers


def test_pin_doctest_refuses_dict_repr_example(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _DICT_REPR)
    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    assert not plan.new_contents
    assert not plan.blockers


def test_pin_doctest_pins_stable_but_skips_set_repr_sibling(tmp_path: Path):
    # Two functions, one stable (pinned) and one set-repr (skipped) -> only the
    # stable one is enforced, the fragile one is left unpinned.
    src = _STABLE + "\n" + _SET_REPR
    _project(tmp_path, "app/calc.py", src)
    gen = plan_pin_doctest(str(tmp_path), "app/calc.py").new_contents.get(
        "tests/test_calc_doctest.py", "")
    assert "def test_double_doctest():" in gen
    assert "def test_letters_doctest():" not in gen


# --- pin-doctest still pins a stable example ----------------------------------


def test_pin_doctest_still_pins_stable_example(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _STABLE)
    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    gen = plan.new_contents.get("tests/test_calc_doctest.py", "")
    assert "def test_double_doctest():" in gen
    assert "result.failed == 0" in gen


# --- the env-stability gate, unit-tested directly -----------------------------


def test_examples_env_stable_true_for_stable_example(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _STABLE)
    assert _examples_env_stable(tmp_path, "app.calc", "double") is True


def test_examples_env_stable_false_for_home_dependent_example(tmp_path: Path):
    # A function whose doctest output matches the GENERATION env's $HOME -> "green"
    # under the parent env, but RED under a different $HOME, so the env gate refuses.
    import os

    home = os.path.expanduser("~")
    src = (
        "import os\n"
        "def myhome():\n"
        f'    """\n    >>> myhome()\n    {home!r}\n    """\n'
        "    return os.path.expanduser('~')\n"
    )
    _project(tmp_path, "app/calc.py", src)
    assert _examples_env_stable(tmp_path, "app.calc", "myhome") is False


def test_examples_env_stable_false_when_unimportable(tmp_path: Path):
    # No such module in the child -> refuse (never claim an unverified example).
    assert _examples_env_stable(tmp_path, "app.nope", "f") is False


def test_pin_doctest_refuses_home_dependent_example_end_to_end(tmp_path: Path):
    # The whole plan refuses a HOME-dependent (but currently-green) example.
    import os

    home = os.path.expanduser("~")
    src = (
        "import os\n"
        "def myhome():\n"
        f'    """\n    >>> myhome()\n    {home!r}\n    """\n'
        "    return os.path.expanduser('~')\n"
    )
    _project(tmp_path, "app/calc.py", src)
    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    assert not plan.new_contents
    assert not plan.blockers
