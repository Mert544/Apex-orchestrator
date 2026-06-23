"""1-arg OCCURRENCE-COUNT family for implement-stub synthesis.

This suite covers the NEW 1-arg occurrence-count shape: ``return a.count(k)`` for
the ONE constant sub-element / substring ``k`` whose ``.count`` reproduces EVERY
witness's expected int. ``n_l('hello') == 2, n_l('world') == 1, n_l('xyz') == 0``
lands ``return s.count('l')`` — the element actually counted, MINED from the witness
inputs (every substring present, every list/tuple element) and VERIFIED against every
pair, NOT a memorized lookup table that another (constant) family would own. The arg
may be a ``str`` (substring count) or a ``list`` / ``tuple`` (element count); both
``.count`` returns a real ``int``, type-exact for the accept-gate.

``k`` is VERIFIED to reproduce every witness's expected int before it is emitted (so
the body holds by construction); the existing type-exact accept-gate and the
off-witness str / sequence canary probes stay the sole arbiters, so nothing lands
that is not witness-verified and unambiguous (never-fake-green). Plus: the expected
ints must VARY (an all-equal contract collapses to a constant another family owns,
refused here); the >=2-distinct-witness overfit floor (a single witness pins one int
and can derive nothing); ``k`` is emitted ONLY when it is the UNIQUE survivor, so when
TWO distinct ``k`` both reproduce every witness the family REFUSES rather than guess;
and a determinism check.
"""

from __future__ import annotations

from pathlib import Path


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


# --- LANDED: the unique witnessed count ``k`` --------------------------------

def test_char_count_lands(tmp_path: Path):
    # n_l('hello') == 2, n_l('world') == 1, n_l('xyz') == 0 -> s.count('l'). 'l' is the
    # ONLY substring whose count reproduces all three (2/1/0); the expected ints VARY,
    # so it is a genuine count, not a constant. No other substring fits every witness,
    # so the count lands unambiguously as the real element counted.
    body = _plan_body(
        tmp_path, "n.py",
        "def n_l(s):\n    raise NotImplementedError\n",
        "from app.n import n_l\n"
        "def test():\n"
        "    assert n_l('hello') == 2\n"
        "    assert n_l('world') == 1\n"
        "    assert n_l('xyz') == 0\n")
    assert body is not None and "return s.count('l')" in body


def test_substring_count_lands(tmp_path: Path):
    # f('abxab') == 2, f('ab') == 1, f('axb') == 0, f('ba') == 0 -> s.count('ab'). The
    # MULTI-CHAR substring 'ab' is the unique survivor: the single char 'b' counts 1 on
    # 'axb'/'ba' (expected 0) and 'a' likewise, so only 'ab' reproduces every witness.
    # A substring count is a value no slice / split / value-free string-method template
    # can spell.
    body = _plan_body(
        tmp_path, "sb.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.sb import f\n"
        "def test():\n"
        "    assert f('abxab') == 2\n"
        "    assert f('ab') == 1\n"
        "    assert f('axb') == 0\n"
        "    assert f('ba') == 0\n")
    assert body is not None and "return s.count('ab')" in body


def test_list_element_count_lands(tmp_path: Path):
    # cnt([1, 2, 1, 3]) == 2, cnt([1]) == 1, cnt([4, 5]) == 0 -> xs.count(1). The element
    # 1 is the unique survivor among the witnessed list elements; the expected ints vary,
    # so it is a genuine count. list.count returns a real int, type-exact for the gate.
    body = _plan_body(
        tmp_path, "lc.py",
        "def cnt(xs):\n    raise NotImplementedError\n",
        "from app.lc import cnt\n"
        "def test():\n"
        "    assert cnt([1, 2, 1, 3]) == 2\n"
        "    assert cnt([1]) == 1\n"
        "    assert cnt([4, 5]) == 0\n")
    assert body is not None and "return xs.count(1)" in body


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "n.py").write_text(
        "def n_l(s):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_n.py").write_text(
        "from app.n import n_l\n"
        "def test():\n"
        "    assert n_l('hello') == 2\n"
        "    assert n_l('world') == 1\n"
        "    assert n_l('xyz') == 0\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/n.py").new_contents.get("app/n.py")
    again = plan_implement_stub(str(tmp_path), "app/n.py").new_contents.get("app/n.py")
    assert first is not None and "return s.count('l')" in first
    assert first == again


# --- REFUSALS ----------------------------------------------------------------

def test_non_varying_all_same_output_refused(tmp_path: Path):
    # f('a') == 1, f('bb') == 1 has CONSTANT expected ints (all 1): a count that is the
    # same for every input collapses to a constant the constant-last fallback owns, so
    # this family refuses it rather than baking a coincidental k. Whatever value-free
    # shape lands, it is NEVER a witness-mined .count(.
    body = _plan_body(
        tmp_path, "av.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.av import f\n"
        "def test():\n"
        "    assert f('a') == 1\n"
        "    assert f('bb') == 1\n")
    assert body is None or ".count(" not in body


def test_single_witness_floor_refused(tmp_path: Path):
    # A LONE f('hello') == 2 is a single example: the >=2-distinct-witness floor
    # withholds the witness-DERIVED count family (one example could pin an arbitrary k
    # that is wrong for the next input). Whatever pre-existing value-free shape (if any)
    # the gate lands, it is NEVER a .count( body mined from a single example.
    body = _plan_body(
        tmp_path, "s1.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.s1 import f\n"
        "def test():\n    assert f('hello') == 2\n")
    assert body is None or ".count(" not in body


def test_no_constant_reproduces_contract_refused(tmp_path: Path):
    # f('ab') == 5, f('cd') == 9 is an int contract that NO substring's count
    # reproduces (every substring counts 0 or 1 on these distinct 2-char strings, never
    # 5 or 9). The family emits nothing — never a guessed k baked onto a contract no
    # real .count explains.
    body = _plan_body(
        tmp_path, "nf.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.nf import f\n"
        "def test():\n"
        "    assert f('ab') == 5\n"
        "    assert f('cd') == 9\n")
    assert body is None or ".count(" not in body


def test_ambiguous_two_constants_fit_refused(tmp_path: Path):
    # f('abcabc') == 2, f('bcx') == 1, f('zzz') == 0 is reproduced by THREE distinct
    # substrings — 'b', 'bc' AND 'c' all count (2, 1, 0) — so the witnesses cannot tell
    # which is meant. The family refuses rather than guess: no .count( body is emitted
    # (never-fake-green).
    body = _plan_body(
        tmp_path, "am.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.am import f\n"
        "def test():\n"
        "    assert f('abcabc') == 2\n"
        "    assert f('bcx') == 1\n"
        "    assert f('zzz') == 0\n")
    assert body is None or ".count(" not in body


def test_int_arg_is_no_count(tmp_path: Path):
    # double(2) == 4, double(5) == 10 is an INT contract: an int has no .count, and the
    # count family mines only str / list / tuple args, so it never contributes a body
    # here (n * 2 lands instead). No .count( body is mined from an int arg.
    body = _plan_body(
        tmp_path, "i.py",
        "def double(n):\n    raise NotImplementedError\n",
        "from app.i import double\n"
        "def test():\n"
        "    assert double(2) == 4\n"
        "    assert double(5) == 10\n")
    assert body is None or ".count(" not in body


# --- FAKE-GREEN CANARY -------------------------------------------------------

def test_fake_green_canary_off_witness_rejects_wrong_k():
    # The off-witness str canary is what keeps a wrong k from passing as green. For the
    # 'l'-count contract, a case-flipped rival 'L' counts the same (0) on the
    # all-lowercase witnesses, so the witnessed values alone cannot tell 'l' from 'L'.
    # The canary's swapcase probe (e.g. 'HELLO' from 'hello') splits them: 'l' counts 0
    # there while 'L' counts 2 — proving the off-witness probe rejects the wrong k. Only
    # the witness-true 'l' (verified against every witness) survives.
    from app.execution.stub_synthesis import _str_canary_probes

    pairs = [("hello", 2), ("world", 1), ("xyz", 0)]
    # 'l' is witness-true; the case-flipped rival 'L' coincides on the witnessed casing.
    assert all(s.count("l") == e for s, e in pairs)
    assert all(s.count("L") == 0 for s, _e in pairs)  # rival coincides on witnesses
    # the off-witness canary carries a probe where the truth and the rival diverge.
    witnesses = [(("hello",), 2), (("world",), 1), (("xyz",), 0)]
    probes = [p[0] for p in _str_canary_probes(witnesses)]
    assert any(s.count("l") != s.count("L") for s in probes)


# --- helper unit tests -------------------------------------------------------

def test_count_templates_pick_unique_k():
    from app.execution.stub_synthesis import _count_templates

    # the unique 'l' fit -> exactly the one body.
    assert _count_templates(
        "s", [("'hello'", "2"), ("'world'", "1"), ("'xyz'", "0")],
    ) == [("count('l')", "s.count('l')")]
    # the unique element 1 fit on lists -> one body.
    assert _count_templates(
        "xs", [("[1, 2, 1, 3]", "2"), ("[1]", "1"), ("[4, 5]", "0")],
    ) == [("count(1)", "xs.count(1)")]
    # three substrings ('b', 'bc', 'c') fit -> ambiguous, refuse.
    assert _count_templates(
        "s", [("'abcabc'", "2"), ("'bcx'", "1"), ("'zzz'", "0")]) == []
    # no substring's count reaches 5/9 -> refuse.
    assert _count_templates("s", [("'ab'", "5"), ("'cd'", "9")]) == []
    # all-equal expected -> a constant, refuse.
    assert _count_templates("s", [("'a'", "1"), ("'bb'", "1")]) == []
    # a single witness (floor not met) -> refuse.
    assert _count_templates("s", [("'hello'", "2")]) == []
    # a non-str/list/tuple arg -> refuse.
    assert _count_templates("n", [("2", "1"), ("5", "0")]) == []
    # no witnesses (structural view) -> nothing to mine.
    assert _count_templates("s", []) == []


def test_count_candidates_mine_substrings_and_elements():
    from app.execution.stub_synthesis import _count_candidates

    # substrings of 'ab' (sorted, non-empty, the degenerate '' excluded).
    assert _count_candidates([("ab", 1), ("ba", 0)]) == ["a", "ab", "b", "ba"]
    # distinct list elements, sorted when orderable.
    assert _count_candidates([([3, 1, 1], 2), ([2], 0)]) == [1, 2, 3]
    # tuple elements are mined the same way as list elements.
    assert _count_candidates([((1, 2), 1), ((2, 2), 2)]) == [1, 2]


def test_count_witness_pairs_validation():
    from app.execution.stub_synthesis import _count_witness_pairs

    # str args with varying int expected -> the parsed pairs.
    assert _count_witness_pairs(
        [("'hello'", "2"), ("'xyz'", "0")]) == [("hello", 2), ("xyz", 0)]
    # all-equal expected ints collapse to a constant -> None.
    assert _count_witness_pairs([("'a'", "1"), ("'b'", "1")]) is None
    # a bool expected is type-distinct from int (a .count is a plain int) -> None.
    assert _count_witness_pairs([("'a'", "True"), ("'b'", "False")]) is None
    # a non-str/list/tuple arg -> None.
    assert _count_witness_pairs([("2", "1"), ("5", "0")]) is None
    # a multi-arg witness -> None (this is a 1-arg family).
    assert _count_witness_pairs([("'a', 'b'", "1"), ("'c', 'd'", "0")]) is None
