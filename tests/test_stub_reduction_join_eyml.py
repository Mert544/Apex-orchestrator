"""1-arg REDUCTION / JOIN family for implement-stub synthesis.

This suite covers the NEW 1-arg reduction/join shapes that widen what a stub body
can be: ``sep.join(a)`` (witness-derived separator + the value-free ``"".join(a)`` /
``" ".join(a)``), ``max(a)`` / ``min(a)`` (iterable reduction), and the empty-safe
``max(a, default=k)`` / ``min(a, default=k)`` where ``k`` is mined from a witness
whose argument is the empty collection.

Every landing assertion uses DISCRIMINATING witnesses that pin exactly one shape;
the existing type-exact accept-gate stays the sole arbiter, so nothing lands that
is not witness-verified (never-fake-green). Plus: ambiguity REFUSAL cases (a thin
contract several shapes fit -> the file is left untouched), overfit-floor cases (a
single witness must not derive a default/separator), a non-literal-arg honest no-op,
and a determinism check (same fixture -> same body twice).
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


# --- JOIN: witness-derived separator -----------------------------------------

def test_space_join_lands(tmp_path: Path):
    # join_words(["a","b","c"]) == "a b c" -> " ".join(words). The witnessed
    # multi-element list discriminates " " from "" (which would give "abc").
    body = _plan_body(
        tmp_path, "jw.py",
        "def join_words(words):\n    raise NotImplementedError\n",
        "from app.jw import join_words\n"
        "def test():\n"
        "    assert join_words(['a', 'b', 'c']) == 'a b c'\n"
        "    assert join_words(['x', 'y']) == 'x y'\n")
    assert body is not None and "return ' '.join(words)" in body


def test_comma_join_lands_derived_sep(tmp_path: Path):
    # csv(["a","b"]) == "a,b" -> ",".join(words): a non-space separator mined from
    # the witnessed expected, under the >=2-distinct-witness floor.
    body = _plan_body(
        tmp_path, "cv.py",
        "def csv(words):\n    raise NotImplementedError\n",
        "from app.cv import csv\n"
        "def test():\n"
        "    assert csv(['a', 'b']) == 'a,b'\n"
        "    assert csv(['x', 'y', 'z']) == 'x,y,z'\n")
    assert body is not None and 'return \',\'.join(words)' in body


def test_empty_join_lands(tmp_path: Path):
    # cat(["a","b"]) == "ab" -> "".join(words): the value-free empty-separator join.
    body = _plan_body(
        tmp_path, "ct.py",
        "def cat(words):\n    raise NotImplementedError\n",
        "from app.ct import cat\n"
        "def test():\n"
        "    assert cat(['a', 'b']) == 'ab'\n"
        "    assert cat(['x', 'y']) == 'xy'\n")
    assert body is not None and "return ''.join(words)" in body


def test_single_join_witness_value_free_space_still_lands(tmp_path: Path):
    # A single join witness floors out the DERIVED separator, but the value-free
    # " ".join carries no witness literal (no overfit risk) and still lands when it
    # is the only shape that matches.
    body = _plan_body(
        tmp_path, "j1.py",
        "def jw(words):\n    raise NotImplementedError\n",
        "from app.j1 import jw\n"
        "def test():\n    assert jw(['a', 'b']) == 'a b'\n")
    assert body is not None and "return ' '.join(words)" in body


def test_single_element_join_is_ambiguous_refused(tmp_path: Path):
    # Only single-element lists: "".join and " ".join both give the lone element,
    # so they coincide on the witnesses but diverge on the multi-element canary
    # probe -> ambiguous -> REFUSE (file untouched).
    body = _plan_body(
        tmp_path, "ja.py",
        "def jw(words):\n    raise NotImplementedError\n",
        "from app.ja import jw\n"
        "def test():\n"
        "    assert jw(['a']) == 'a'\n"
        "    assert jw(['b']) == 'b'\n")
    assert body is None


def test_non_str_iterable_join_not_offered(tmp_path: Path):
    # A list of ints cannot be str-joined; the join family is kind-pruned, so an
    # int-element contract reaches the numeric reduction instead (sum here).
    body = _plan_body(
        tmp_path, "sm.py",
        "def total(xs):\n    raise NotImplementedError\n",
        "from app.sm import total\n"
        "def test():\n"
        "    assert total([1, 2, 3]) == 6\n"
        "    assert total([10, 5]) == 15\n")
    assert body is not None and "return sum(xs)" in body


# --- REDUCTION: max / min ----------------------------------------------------

def test_max_lands(tmp_path: Path):
    # max_priority([3,1,2]) == 3 -> max(xs). [5,9]->9 discriminates from last(=9 here
    # too) via the reversed canary probe; only max fits both witnesses+probes.
    body = _plan_body(
        tmp_path, "mp.py",
        "def max_priority(xs):\n    raise NotImplementedError\n",
        "from app.mp import max_priority\n"
        "def test():\n"
        "    assert max_priority([3, 1, 2]) == 3\n"
        "    assert max_priority([5, 9]) == 9\n")
    assert body is not None and "return max(xs)" in body


def test_min_lands(tmp_path: Path):
    body = _plan_body(
        tmp_path, "mn.py",
        "def min_priority(xs):\n    raise NotImplementedError\n",
        "from app.mn import min_priority\n"
        "def test():\n"
        "    assert min_priority([3, 1, 2]) == 1\n"
        "    assert min_priority([5, 9]) == 5\n")
    assert body is not None and "return min(xs)" in body


# --- empty-safe reduction: max/min with a derived default --------------------

def test_max_default_lands(tmp_path: Path):
    # top([]) == 0 pins default=0; top([3,1]) == 3 is the second discriminating
    # witness (plain max(xs) would RAISE on []) -> max(xs, default=0).
    body = _plan_body(
        tmp_path, "tp.py",
        "def top(xs):\n    raise NotImplementedError\n",
        "from app.tp import top\n"
        "def test():\n"
        "    assert top([]) == 0\n"
        "    assert top([3, 1]) == 3\n")
    assert body is not None and "return max(xs, default=0)" in body


def test_min_default_lands(tmp_path: Path):
    # bottom([]) == 0 pins default=0; bottom([3,1]) == 1 discriminates min from max.
    body = _plan_body(
        tmp_path, "bt.py",
        "def bottom(xs):\n    raise NotImplementedError\n",
        "from app.bt import bottom\n"
        "def test():\n"
        "    assert bottom([]) == 0\n"
        "    assert bottom([3, 1]) == 1\n")
    assert body is not None and "return min(xs, default=0)" in body


def test_single_empty_witness_does_not_derive_default(tmp_path: Path):
    # A LONE empty-collection witness must NOT pin a default (a single witness can't
    # tell max(xs, default=0) from a bare constant). The derived-default shape is
    # floored out; the contract is satisfied by other coincidental shapes (len/sum),
    # never by an overfit default reduction.
    body = _plan_body(
        tmp_path, "d1.py",
        "def top(xs):\n    raise NotImplementedError\n",
        "from app.d1 import top\n"
        "def test():\n    assert top([]) == 0\n")
    assert body is None or "default=" not in body


# --- ambiguity / overfit refusals --------------------------------------------

def test_single_singleton_list_refused(tmp_path: Path):
    # f([5]) == 5 alone: max/min/sum/first/last ALL give 5 and agree everywhere a
    # one-element list can probe -> under-specified -> REFUSE.
    body = _plan_body(
        tmp_path, "f1.py",
        "def f(xs):\n    raise NotImplementedError\n",
        "from app.f1 import f\n"
        "def test():\n    assert f([5]) == 5\n")
    assert body is None


def test_max_vs_last_vs_len_refused(tmp_path: Path):
    # g([1,2,3]) == 3 is matched by max (=3), last (=3) AND len (=3) — they diverge
    # on the reversed/sorted canary probes -> ambiguous -> REFUSE.
    body = _plan_body(
        tmp_path, "g1.py",
        "def g(xs):\n    raise NotImplementedError\n",
        "from app.g1 import g\n"
        "def test():\n    assert g([1, 2, 3]) == 3\n")
    assert body is None


def test_discriminating_witness_lifts_ambiguity(tmp_path: Path):
    # Add a second witness that only max satisfies (last/len fail): the ambiguity is
    # resolved and max(xs) lands.
    body = _plan_body(
        tmp_path, "g2.py",
        "def g(xs):\n    raise NotImplementedError\n",
        "from app.g2 import g\n"
        "def test():\n"
        "    assert g([1, 2, 3]) == 3\n"
        "    assert g([9, 4]) == 9\n")
    assert body is not None and "return max(xs)" in body


# --- honesty: non-literal arg, determinism -----------------------------------

def test_non_literal_arg_is_honest_no_op(tmp_path: Path):
    # The witness arg is a module-level name, not a literal collection: no witness is
    # mined here, so the value-derived join is withheld and nothing is guessed. No
    # crash; the value-free join can't be in-process matched (non-evaluable witness),
    # and the pytest gate has only a non-literal contract -> honest result (no body
    # or a gate-verified one, never a fake-green).
    body = _plan_body(
        tmp_path, "nl.py",
        "def jn(words):\n    raise NotImplementedError\n",
        "from app.nl import jn\n"
        "WS = ['a', 'b']\n"
        "def test():\n    assert jn(WS) == 'a b'\n")
    # The non-literal call site yields no literal witness; the body, if any, must be
    # gate-verified and never crash. We only assert no exception was raised and the
    # result is a str-or-None.
    assert body is None or isinstance(body, str)


def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "jw.py").write_text(
        "def join_words(words):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_jw.py").write_text(
        "from app.jw import join_words\n"
        "def test():\n"
        "    assert join_words(['a', 'b', 'c']) == 'a b c'\n"
        "    assert join_words(['x', 'y']) == 'x y'\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/jw.py").new_contents.get("app/jw.py")
    second = plan_implement_stub(str(tmp_path), "app/jw.py").new_contents.get("app/jw.py")
    assert first is not None and first == second
