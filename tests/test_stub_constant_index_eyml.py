"""1-arg CONSTANT-INDEX family for implement-stub synthesis.

This suite covers the NEW 1-arg constant-index shape: ``return a[k]`` for a fixed
integer index ``k`` mined from the witnesses — the position the expected value sits at
in EVERY witnessed sequence. ``second([1, 2, 3]) == 2, second([5, 9, 1]) == 9`` lands
``return xs[1]`` — an INTERIOR index no other template can spell (the endpoints
``xs[0]`` / ``xs[-1]`` already have their own ``first`` / ``last`` builtins).

The index comes from the TYPE-EXACT intersection of the non-negative positions where
each witness's expected value occurs in that witness's own sequence literal, so the
index reproduces every witness by construction; the existing type-exact accept-gate and
the off-witness sequence-canary probes stay the sole arbiters, so nothing lands that is
not witness-verified and unambiguous (never-fake-green). Plus: the >=2-distinct-witness
overfit floor (a single witness must NOT derive an index — it can't tell ``xs[0]`` from
a bare ``return 1``), an ASCENDING-sorted ambiguity REFUSAL (``xs[0]`` and ``min(xs)``
coincide on a sorted witness set but diverge on the reversed canary -> file untouched),
no duplication of the existing ``xs[0]`` / ``xs[-1]`` builtins, a string-arg index, a
non-literal-arg honest no-op, and a determinism check.
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


# --- LANDED: interior index --------------------------------------------------

def test_second_element_index_lands(tmp_path: Path):
    # second([1, 2, 3]) == 2, second([5, 9, 1]) == 9 -> xs[1]. UNSORTED witnesses so
    # the index is unambiguous (no reduction coincides); this is the exact gap the
    # family fills — an interior index no prior template (first/last/min/max) spells.
    body = _plan_body(
        tmp_path, "sx.py",
        "def second(xs):\n    raise NotImplementedError\n",
        "from app.sx import second\n"
        "def test():\n"
        "    assert second([1, 2, 3]) == 2\n"
        "    assert second([5, 9, 1]) == 9\n")
    assert body is not None and "return xs[1]" in body


def test_third_element_index_lands(tmp_path: Path):
    # third([1, 2, 9, 4]) == 9, third([7, 8, 5, 3]) == 5 -> xs[2]. The expected value
    # sits at index 2 in BOTH witnesses; the intersection pins exactly that index.
    body = _plan_body(
        tmp_path, "th.py",
        "def third(items):\n    raise NotImplementedError\n",
        "from app.th import third\n"
        "def test():\n"
        "    assert third([1, 2, 9, 4]) == 9\n"
        "    assert third([7, 8, 5, 3]) == 5\n")
    assert body is not None and "return items[2]" in body


def test_string_arg_index_lands(tmp_path: Path):
    # initial2('abc') == 'b', initial2('xyz') == 'y' -> s[1]. A str is a sequence too,
    # so the interior-index family lands on a character at a fixed position.
    body = _plan_body(
        tmp_path, "ci.py",
        "def initial2(s):\n    raise NotImplementedError\n",
        "from app.ci import initial2\n"
        "def test():\n"
        "    assert initial2('abc') == 'b'\n"
        "    assert initial2('xyz') == 'y'\n")
    assert body is not None and "return s[1]" in body


# --- no duplication of the existing endpoint builtins ------------------------

def test_first_element_stays_builtin_no_duplicate_index(tmp_path: Path):
    # first([3, 1, 2]) == 3, first([5, 9]) == 5 -> the long-standing xs[0] ``first``
    # builtin still wins; the index family deliberately omits index 0 (it would only
    # shadow that body), so no index[0] template is emitted and the existing idea is
    # unchanged.
    body = _plan_body(
        tmp_path, "fi.py",
        "def first(xs):\n    raise NotImplementedError\n",
        "from app.fi import first\n"
        "def test():\n"
        "    assert first([3, 1, 2]) == 3\n"
        "    assert first([5, 9]) == 5\n")
    assert body is not None and "return xs[0]" in body


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "sx.py").write_text(
        "def second(xs):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_sx.py").write_text(
        "from app.sx import second\n"
        "def test():\n"
        "    assert second([1, 2, 3]) == 2\n"
        "    assert second([5, 9, 1]) == 9\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/sx.py").new_contents.get("app/sx.py")
    second = plan_implement_stub(str(tmp_path), "app/sx.py").new_contents.get("app/sx.py")
    assert first is not None and "return xs[1]" in first
    assert first == second


# --- REFUSALS ----------------------------------------------------------------

def test_single_witness_floor_refused(tmp_path: Path):
    # A LONE second([1, 7, 2, 9]) == 7 must NOT land an index body: one witness can't
    # tell xs[1] from a bare return 7, so the >=2-distinct-witness floor withholds it.
    # The interior value 7 equals no reduction/passthrough/mean either, so the WHOLE
    # synthesis honestly REFUSES (file untouched) rather than land xs[1] on one example.
    body = _plan_body(
        tmp_path, "s1.py",
        "def second(xs):\n    raise NotImplementedError\n",
        "from app.s1 import second\n"
        "def test():\n    assert second([1, 7, 2, 9]) == 7\n")
    assert body is None


def test_ascending_sorted_index_is_ambiguous_refused(tmp_path: Path):
    # head([1, 2, 3]) == 1, head([4, 5, 6]) == 4: index 0 holds the expected value in
    # both, but ASCENDING-sorted witnesses make xs[0] and min(xs) coincide here while
    # diverging on the reversed sequence-canary probe -> under-specified -> REFUSE.
    # Confirms the existing canary ambiguity guard still arbitrates the index family.
    body = _plan_body(
        tmp_path, "as.py",
        "def head(xs):\n    raise NotImplementedError\n",
        "from app.as import head\n"
        "def test():\n"
        "    assert head([1, 2, 3]) == 1\n"
        "    assert head([4, 5, 6]) == 4\n")
    assert body is None


def test_no_common_index_position_mines_no_index(tmp_path: Path):
    # pick([1, 7, 2, 9]) == 7 (pos 1), pick([1, 2, 7, 9]) == 7 (pos 2): the expected
    # value sits at DIFFERENT positions across the witnesses, so the position
    # intersection is EMPTY and NO index body is mined. Any body that does land here is
    # the pre-existing constant last-resort (7 across >=2 tuples), NEVER an a[k] shape —
    # the family never guesses an index that fails a witness.
    body = _plan_body(
        tmp_path, "nc.py",
        "def pick(xs):\n    raise NotImplementedError\n",
        "from app.nc import pick\n"
        "def test():\n"
        "    assert pick([1, 7, 2, 9]) == 7\n"
        "    assert pick([1, 2, 7, 9]) == 7\n")
    assert body is None or "xs[" not in body


# --- honesty: non-literal arg ------------------------------------------------

def test_non_literal_arg_is_honest_no_op(tmp_path: Path):
    # The witness arg is a module-level name, not a literal: no literal witness is
    # mined, so the index family is withheld and nothing is guessed. No crash; any body
    # must be gate-verified, never a fake-green.
    body = _plan_body(
        tmp_path, "nl.py",
        "def second(xs):\n    raise NotImplementedError\n",
        "from app.nl import second\n"
        "XS = [1, 2, 3]\n"
        "def test():\n    assert second(XS) == 2\n")
    assert body is None or isinstance(body, str)


# --- helper unit tests: _constant_index_constants / _constant_index_templates -

def test_mines_intersection_index_sorted():
    from app.execution.stub_synthesis import _constant_index_constants

    # index 1 holds the expected value in both witnesses -> [1]; index 0 dropped even
    # if it ever intersected (the first builtin owns it).
    assert _constant_index_constants(
        [("[1, 2, 3]", "2"), ("[5, 9, 1]", "9")]) == [1]
    assert _constant_index_constants(
        [("[1, 2, 9, 4]", "9"), ("[7, 8, 5, 3]", "5")]) == [2]


def test_empty_single_and_non_sequence_witnesses_mine_nothing():
    from app.execution.stub_synthesis import _constant_index_constants

    assert _constant_index_constants([]) == []  # structural view: no literal to mine
    assert _constant_index_constants([("[1, 2, 3]", "2")]) == []  # below the floor
    # a non-sequence (int) argument cannot be indexed -> nothing
    assert _constant_index_constants([("5", "5"), ("6", "6")]) == []
    # differing positions intersect to empty
    assert _constant_index_constants(
        [("[1, 7, 2]", "7"), ("[1, 2, 7]", "7")]) == []
    # index 0 only -> dropped (first builtin owns it)
    assert _constant_index_constants(
        [("[3, 1, 2]", "3"), ("[5, 9]", "5")]) == []


def test_type_exact_position_excludes_bool_int_mismatch():
    from app.execution.stub_synthesis import _constant_index_constants

    # True == 1 in Python, but the position is type-exact, so a bool element never
    # matches an int expected value -> no index (mirrors the accept-gate).
    assert _constant_index_constants(
        [("[True, 2]", "1"), ("[True, 9]", "1")]) == []


def test_templates_emit_index_body_pairs():
    from app.execution.stub_synthesis import _constant_index_templates

    assert _constant_index_templates(
        "xs", [("[1, 2, 3]", "2"), ("[5, 9, 1]", "9")]) == [("index[1]", "xs[1]")]
    assert _constant_index_templates("xs", []) == []  # no witnesses -> no template
