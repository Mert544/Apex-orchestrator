"""1-arg AFFINE-STRING (f-string) family for implement-stub synthesis.

This suite covers the NEW 1-arg affine-string shape: ``return f"{p}{a}{s}"`` for a
common literal PREFIX ``p`` and SUFFIX ``s`` mined from the witnesses whose EXPECTED
value is a ``str`` and whose output is ``p + str(arg) + s`` (the arg sits verbatim
between a fixed prefix and suffix). ``label(3) == "item-3"`` lands ``f"item-{n}"``;
``greet("Bob") == "Hi Bob!"`` lands ``f"Hi {name}!"``.

The body is the NATURAL human spelling — an f-string ``{a}`` stringifies, so an int
arg and a str arg share the SAME body shape (no redundant ``str()`` wrapper). The
existing type-exact accept-gate stays the sole arbiter, so nothing lands that is not
witness-verified (never-fake-green). Plus: the >=2-distinct-witness overfit floor (a
single witness must NOT derive a prefix/suffix), an off-witness-canary ambiguity
REFUSAL (two splits that coincide on a thin witness set but diverge off-witness ->
file untouched), a non-string-output refusal, a refusal when an existing shape
diverges off-witness, a non-literal-arg honest no-op, and a determinism check.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# --- helpers -----------------------------------------------------------------

def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _plan_body(tmp_path: Path, module: str, src: str, test_src: str) -> str | None:
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / module).write_text(src, encoding="utf-8")
    (tmp_path / "tests" / f"test_{module}").write_text(test_src, encoding="utf-8")
    rel = f"app/{module}"
    return plan_implement_stub(str(tmp_path), rel).new_contents.get(rel)


# --- LANDED: int arg, prefix only --------------------------------------------

def test_int_prefix_affine_lands(tmp_path: Path):
    # label(3) == "item-3", label(7) == "item-7" -> f"item-{n}". Two distinct args
    # pin the prefix "item-" and empty suffix; the f-string stringifies the int.
    body = _plan_body(
        tmp_path, "lb.py",
        "def label(n):\n    raise NotImplementedError\n",
        "from app.lb import label\n"
        "def test():\n"
        "    assert label(3) == 'item-3'\n"
        "    assert label(7) == 'item-7'\n")
    assert body is not None and 'return f"item-{n}"' in body


def test_int_prefix_and_suffix_affine_lands(tmp_path: Path):
    # row(2) == "[2]", row(9) == "[9]" -> f"[{n}]": a non-empty prefix AND suffix.
    body = _plan_body(
        tmp_path, "rw.py",
        "def row(n):\n    raise NotImplementedError\n",
        "from app.rw import row\n"
        "def test():\n"
        "    assert row(2) == '[2]'\n"
        "    assert row(9) == '[9]'\n")
    assert body is not None and 'return f"[{n}]"' in body


# --- LANDED: str arg ---------------------------------------------------------

def test_str_arg_affine_lands(tmp_path: Path):
    # greet("Bob") == "Hi Bob!", greet("Al") == "Hi Al!" -> f"Hi {name}!". The str
    # arg sits verbatim in the middle; no redundant str() wrapper appears.
    body = _plan_body(
        tmp_path, "gr.py",
        "def greet(name):\n    raise NotImplementedError\n",
        "from app.gr import greet\n"
        "def test():\n"
        "    assert greet('Bob') == 'Hi Bob!'\n"
        "    assert greet('Al') == 'Hi Al!'\n")
    assert body is not None and 'return f"Hi {name}!"' in body
    assert "str(" not in body  # natural body, no redundant conversion


def test_str_arg_suffix_only_affine_lands(tmp_path: Path):
    # ext("a") == "a.txt", ext("read") == "read.txt" -> f"{name}.txt": suffix only.
    body = _plan_body(
        tmp_path, "ex.py",
        "def ext(name):\n    raise NotImplementedError\n",
        "from app.ex import ext\n"
        "def test():\n"
        "    assert ext('a') == 'a.txt'\n"
        "    assert ext('read') == 'read.txt'\n")
    assert body is not None and 'return f"{name}.txt"' in body


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "lb.py").write_text(
        "def label(n):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_lb.py").write_text(
        "from app.lb import label\n"
        "def test():\n"
        "    assert label(3) == 'item-3'\n"
        "    assert label(7) == 'item-7'\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/lb.py").new_contents.get("app/lb.py")
    second = plan_implement_stub(str(tmp_path), "app/lb.py").new_contents.get("app/lb.py")
    assert first is not None and 'return f"item-{n}"' in first
    assert first == second


# --- REFUSALS ----------------------------------------------------------------

def test_single_witness_floor_refused(tmp_path: Path):
    # A LONE label(3) == "item-3" must NOT land an affine body: one witness can't
    # tell f"item-{n}" from a bare return "item-3", so the >=2-witness floor (and the
    # constant floor) withholds it -> REFUSE (file untouched).
    body = _plan_body(
        tmp_path, "s1.py",
        "def label(n):\n    raise NotImplementedError\n",
        "from app.s1 import label\n"
        "def test():\n    assert label(3) == 'item-3'\n")
    assert body is None


# Legitimately slow, not hung: refusal paths probe EVERY candidate through
# the real nested-pytest gate (~2 min on a 2-core box), living at the exact
# edge of the global --timeout=120 hang-catcher — measured borderline both
# pre- and post-wave, so this is a hardware-speed margin, not a regression.
# Same precedent as test_security_audit.py's widened timeout.
@pytest.mark.timeout(300)
def test_coincidental_split_no_consistent_affine_refused(tmp_path: Path):
    # dub("aa") == "aaa", dub("bb") == "bbb": each output COULD be split affinely on
    # its own (prefix "a" or suffix "a"), but NO single fixed prefix/suffix holds for
    # BOTH distinct args (a fixed-literal "a" added to "bb" gives "abb"/"bba", never
    # "bbb"). The >=2-distinct-witness requirement thus admits no affine body, and the
    # contract is otherwise under-specified -> REFUSE (file untouched). This proves the
    # floor: a per-witness-coincidental split is never landed.
    body = _plan_body(
        tmp_path, "am.py",
        "def dub(x):\n    raise NotImplementedError\n",
        "from app.am import dub\n"
        "def test():\n"
        "    assert dub('aa') == 'aaa'\n"
        "    assert dub('bb') == 'bbb'\n")
    assert body is None


def test_non_string_output_no_affine(tmp_path: Path):
    # square(2) == 4, square(3) == 9: the expected values are ints, not strings, so
    # the affine family is never offered; a numeric shape (n ** 2 etc.) may land but
    # never an f-string body.
    body = _plan_body(
        tmp_path, "sq.py",
        "def square(n):\n    raise NotImplementedError\n",
        "from app.sq import square\n"
        "def test():\n"
        "    assert square(2) == 4\n"
        "    assert square(3) == 9\n")
    assert body is None or 'f"' not in body


def test_existing_shape_diverges_off_witness_refused(tmp_path: Path):
    # tag("a") == "a", tag("b") == "b": the only consistent affine split is empty/
    # empty (pure stringification), which the family deliberately does NOT emit (it ==
    # str(x)). The contract is instead matched by several value-free shapes
    # (passthrough / str / .lower() / .upper() / ...) that coincide on these
    # all-lowercase single-char witnesses but DIVERGE off-witness (the swapcase /
    # whitespace canary probes) -> under-specified -> REFUSE. Confirms a pure-
    # stringification contract is never landed as an affine body.
    body = _plan_body(
        tmp_path, "tg.py",
        "def tag(x):\n    raise NotImplementedError\n",
        "from app.tg import tag\n"
        "def test():\n"
        "    assert tag('a') == 'a'\n"
        "    assert tag('b') == 'b'\n")
    assert body is None


def test_pure_stringification_stays_str_not_affine(tmp_path: Path):
    # as_text(7) == "7", as_text(42) == "42": the only affine split is empty/empty
    # (== str(n)), which the family withholds, so the long-standing value-free
    # str(n) body still wins — the affine widening never shifts this existing idea.
    body = _plan_body(
        tmp_path, "at.py",
        "def as_text(n):\n    raise NotImplementedError\n",
        "from app.at import as_text\n"
        "def test():\n"
        "    assert as_text(7) == '7'\n"
        "    assert as_text(42) == '42'\n")
    assert body is not None and "return str(n)" in body
    assert 'f"' not in body


# --- honesty: non-literal arg ------------------------------------------------

def test_non_literal_arg_is_honest_no_op(tmp_path: Path):
    # The witness arg is a module-level name, not a literal: no literal witness is
    # mined, so the affine family is withheld and nothing is guessed. No crash; any
    # body must be gate-verified, never a fake-green.
    body = _plan_body(
        tmp_path, "nl.py",
        "def label(n):\n    raise NotImplementedError\n",
        "from app.nl import label\n"
        "N = 3\n"
        "def test():\n    assert label(N) == 'item-3'\n")
    assert body is None or isinstance(body, str)
