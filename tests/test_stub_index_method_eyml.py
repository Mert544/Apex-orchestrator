"""1-arg INDEX-METHOD family for implement-stub synthesis.

This suite covers the NEW 1-arg index-method shape: ``return a.index(k)`` for a fixed
element ``k`` mined from the witnesses — the int POSITION at which the literal ``k`` FIRST
occurs in the sequence. ``find_three([5, 3, 9]) == 1, find_three([3, 8]) == 0`` lands
``return xs.index(3)`` — the INVERSE of the constant-index family (``a[k]`` is the element
AT position ``k``; ``a.index(k)`` is the POSITION of element ``k``), a value no scalar,
slice, or reduction template can spell.

The element comes from the TYPE-EXACT intersection of the elements whose ``seq.index(k)``
equals each witness's expected int, so the body reproduces every witness by construction;
the existing type-exact accept-gate and the off-witness sequence-canary probes stay the
sole arbiters, so nothing lands that is not witness-verified and unambiguous
(never-fake-green). ``.index`` raises ``ValueError`` when ``k`` is absent, so an
element-absent witness makes the candidate raise and the gate rejects it. Plus: the
>=2-distinct-witness overfit floor (a single witness must NOT derive an element — it can't
tell ``xs.index(3)`` from a bare ``return 0``), an element-absent REFUSAL, no confusion
with the constant-index ``a[k]`` family, and a determinism check.
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


# --- LANDED: position of a witness-mined element -----------------------------

def test_find_three_index_lands(tmp_path: Path):
    # find_three([5, 3, 9]) == 1, find_three([3, 8]) == 0 -> xs.index(3). The element 3
    # sits at position 1 in the first witness and 0 in the second; .index(3) reproduces
    # BOTH. Varied/unsorted witnesses so the position is genuinely the index of 3, not a
    # reduction coincidence — the exact gap the family fills.
    body = _plan_body(
        tmp_path, "ft.py",
        "def find_three(xs):\n    raise NotImplementedError\n",
        "from app.ft import find_three\n"
        "def test():\n"
        "    assert find_three([5, 3, 9]) == 1\n"
        "    assert find_three([3, 8]) == 0\n")
    assert body is not None and "return xs.index(3)" in body


def test_string_member_index_lands(tmp_path: Path):
    # pos_b('abc') == 1, pos_b('zbx') == 1 -> s.index('b'). A str is a sequence too, so
    # the family lands the position of a fixed character.
    body = _plan_body(
        tmp_path, "pb.py",
        "def pos_b(s):\n    raise NotImplementedError\n",
        "from app.pb import pos_b\n"
        "def test():\n"
        "    assert pos_b('abc') == 1\n"
        "    assert pos_b('zbx') == 1\n")
    assert body is not None and "return s.index('b')" in body


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "ft.py").write_text(
        "def find_three(xs):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_ft.py").write_text(
        "from app.ft import find_three\n"
        "def test():\n"
        "    assert find_three([5, 3, 9]) == 1\n"
        "    assert find_three([3, 8]) == 0\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/ft.py").new_contents.get("app/ft.py")
    again = plan_implement_stub(str(tmp_path), "app/ft.py").new_contents.get("app/ft.py")
    assert first is not None and "return xs.index(3)" in first
    assert first == again


# --- REFUSALS ----------------------------------------------------------------

def test_single_witness_floor_refused(tmp_path: Path):
    # A LONE find_three([5, 3, 9]) == 1 must NOT land an index-method body: one witness
    # can't tell xs.index(3) from a bare return 1, so the >=2-distinct-witness floor
    # withholds it. Whatever pre-existing value-free shape (if any) the gate lands, it is
    # NEVER an xs.index(...) body mined from a single example — that is the floor's job.
    body = _plan_body(
        tmp_path, "s1.py",
        "def find_three(xs):\n    raise NotImplementedError\n",
        "from app.s1 import find_three\n"
        "def test():\n    assert find_three([5, 3, 9]) == 1\n")
    assert body is None or ".index(" not in body


def test_element_absent_witness_refused(tmp_path: Path):
    # locate([5, 3, 9]) == 1 mines element 3 (.index(3) == 1), but the second witness
    # locate([7, 8]) == 1 has NO 3 — .index(3) RAISES ValueError there, so the candidate
    # never passes the accept-gate. Element 8 sits at position 1 in the second witness but
    # is absent from the first, so no element reproduces BOTH: the intersection is empty
    # and no xs.index(...) body lands.
    body = _plan_body(
        tmp_path, "ea.py",
        "def locate(xs):\n    raise NotImplementedError\n",
        "from app.ea import locate\n"
        "def test():\n"
        "    assert locate([5, 3, 9]) == 1\n"
        "    assert locate([7, 8]) == 1\n")
    assert body is None or ".index(" not in body


def test_constant_index_not_an_index_method(tmp_path: Path):
    # second([1, 2, 3]) == 2, second([5, 9, 1]) == 9 is the CONSTANT-INDEX family
    # (element AT position 1), NOT the index-method family. It must land xs[1], never an
    # xs.index(...) body — the two families stay distinct (a[k] vs a.index(k)).
    body = _plan_body(
        tmp_path, "ci.py",
        "def second(xs):\n    raise NotImplementedError\n",
        "from app.ci import second\n"
        "def test():\n"
        "    assert second([1, 2, 3]) == 2\n"
        "    assert second([5, 9, 1]) == 9\n")
    assert body is not None and "return xs[1]" in body and ".index(" not in body


# --- honesty: non-literal / non-int-expected ---------------------------------

def test_non_literal_arg_is_honest_no_op(tmp_path: Path):
    # The witness arg is a module-level name, not a literal: no literal witness is mined,
    # so the index-method family is withheld and nothing is guessed. No crash.
    body = _plan_body(
        tmp_path, "nl.py",
        "def find_three(xs):\n    raise NotImplementedError\n",
        "from app.nl import find_three\n"
        "XS = [5, 3, 9]\n"
        "def test():\n    assert find_three(XS) == 1\n")
    assert body is None or isinstance(body, str)


# --- helper unit tests: _index_method_constants / _index_templates -----------

def test_mines_intersection_element_sorted():
    from app.execution.stub_synthesis import _index_method_constants

    # element 3 has .index(3) == the expected int in both witnesses -> [3].
    assert _index_method_constants(
        [("[5, 3, 9]", "1"), ("[3, 8]", "0")]) == [3]
    # a str member at a consistent first-occurrence position.
    assert _index_method_constants(
        [("'abc'", "1"), ("'zbx'", "1")]) == ["b"]


def test_empty_single_and_non_sequence_witnesses_mine_nothing():
    from app.execution.stub_synthesis import _index_method_constants

    assert _index_method_constants([]) == []  # structural view: no literal to mine
    assert _index_method_constants([("[5, 3, 9]", "1")]) == []  # below the floor
    # a non-sequence (int) argument cannot be .index'd -> nothing
    assert _index_method_constants([("5", "0"), ("6", "0")]) == []
    # elements at the positions differ across witnesses -> empty intersection
    assert _index_method_constants(
        [("[5, 3, 9]", "1"), ("[7, 8]", "0")]) == []


def test_non_int_expected_refuses_whole_family():
    from app.execution.stub_synthesis import _index_method_constants

    # a slice-shaped (list) expected can never be an .index result -> nothing
    assert _index_method_constants(
        [("[5, 3, 9]", "[3]"), ("[3, 8]", "[3]")]) == []
    # a bool expected is type-distinct from int (the position is always an int) -> nothing
    assert _index_method_constants(
        [("[5, 3]", "True"), ("[3, 8]", "False")]) == []


def test_out_of_range_and_earlier_duplicate_drop_element():
    from app.execution.stub_synthesis import _index_method_constants

    # expected position out of range for its sequence -> nothing
    assert _index_method_constants(
        [("[5, 3]", "5"), ("[3, 8]", "0")]) == []
    # the candidate element seq[expected] has an EARLIER duplicate, so .index returns a
    # smaller position than expected -> the element is dropped, family refuses.
    assert _index_method_constants(
        [("[3, 3, 9]", "1"), ("[3, 8]", "0")]) == []


def test_templates_emit_index_method_body_pairs():
    from app.execution.stub_synthesis import _index_templates

    assert _index_templates(
        "xs", [("[5, 3, 9]", "1"), ("[3, 8]", "0")]) == [("index(3)", "xs.index(3)")]
    assert _index_templates("xs", []) == []  # no witnesses -> no template
