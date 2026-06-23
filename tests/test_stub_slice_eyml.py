"""1-arg SLICE family for implement-stub synthesis.

This suite covers the NEW 1-arg slice shapes: ``return a[:k]`` / ``return a[k:]`` /
``return a[i:j]`` for fixed bounds mined from the witnesses — the contiguous
sub-sequence that reproduces EVERY witnessed expected output from that witness's own
sequence literal. ``head([3, 1, 2, 4]) == [3, 1], head([5, 9, 1]) == [5, 9]`` lands
``return xs[:2]`` (a prefix); ``rest([3, 1, 2]) == [1, 2], rest([5, 9, 1, 4]) ==
[9, 1, 4]`` lands ``return xs[1:]`` (a suffix); an interior window lands ``xs[i:j]``.
These spell a sub-sequence body no scalar index or reduction template can.

The bounds come from the per-witness TYPE-EXACT intersection of the slice positions
that reproduce that witness, so the slice reproduces every witness by construction; the
existing type-exact accept-gate and the off-witness sequence-canary probes (reorder /
reverse / empty) stay the sole arbiters, so nothing lands that is not witness-verified
and unambiguous (never-fake-green). Like the constant-index family, a slice bakes
witness-derived bounds, so the >=2-distinct-witness overfit floor plus the type-exact
accept gate plus canary divergence prevent overfit / ambiguity. Fixtures use UNSORTED /
VARIED witnesses on purpose — a sorted or repeated-element witness can be ambiguous
(the #D lesson), and a single witness can never disambiguate a slice from a constant.

Covered: prefix / suffix / interior-window landings, a string-arg slice, the
identity-``a[:]`` and empty-slice exclusions (passthrough owns the whole sequence), the
>=2-distinct-witness floor refusal (single witness), a no-common-bound honest refusal,
a non-literal-arg honest no-op, determinism, and helper unit tests for the mining /
template functions including their empty / single / non-sequence edge paths.
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


# --- LANDED: prefix a[:k] ----------------------------------------------------

def test_prefix_slice_lands(tmp_path: Path):
    # head([3, 1, 2, 4]) == [3, 1], head([5, 9, 1]) == [5, 9] -> xs[:2]. UNSORTED
    # witnesses so the prefix is unambiguous (no reduction returns a 2-element list);
    # this is the exact gap the family fills — a prefix sub-sequence no prior template
    # (first/last/min/max/sorted) spells.
    body = _plan_body(
        tmp_path, "hd.py",
        "def head(xs):\n    raise NotImplementedError\n",
        "from app.hd import head\n"
        "def test():\n"
        "    assert head([3, 1, 2, 4]) == [3, 1]\n"
        "    assert head([5, 9, 1]) == [5, 9]\n")
    assert body is not None and "return xs[:2]" in body


# --- LANDED: suffix a[k:] ----------------------------------------------------

def test_suffix_slice_lands(tmp_path: Path):
    # rest([3, 1, 2]) == [1, 2], rest([5, 9, 1, 4]) == [9, 1, 4] -> xs[1:]. The tails
    # are of DIFFERING length, yet one start (1) reproduces both because ``1:`` runs to
    # each sequence's own end — only the open-ended suffix family can spell a
    # varying-length tail.
    body = _plan_body(
        tmp_path, "rs.py",
        "def rest(xs):\n    raise NotImplementedError\n",
        "from app.rs import rest\n"
        "def test():\n"
        "    assert rest([3, 1, 2]) == [1, 2]\n"
        "    assert rest([5, 9, 1, 4]) == [9, 1, 4]\n")
    assert body is not None and "return xs[1:]" in body


# --- LANDED: interior window a[i:j] ------------------------------------------

def test_interior_window_slice_lands(tmp_path: Path):
    # mid([9, 8, 7, 6, 5]) == [8, 7], mid([1, 2, 3, 4, 5]) == [2, 3] -> xs[1:3]. The
    # absolute (1, 3) window reproduces both witnesses; neither a prefix (start 0) nor a
    # suffix (stop == len) can spell an interior window, so the closed family owns it.
    body = _plan_body(
        tmp_path, "cw.py",
        "def mid(xs):\n    raise NotImplementedError\n",
        "from app.cw import mid\n"
        "def test():\n"
        "    assert mid([9, 8, 7, 6, 5]) == [8, 7]\n"
        "    assert mid([1, 2, 3, 4, 5]) == [2, 3]\n")
    assert body is not None and "return xs[1:3]" in body


def test_string_arg_slice_lands(tmp_path: Path):
    # pre('hello') == 'he', pre('world') == 'wo' -> s[:2]. A str is a sequence too, so
    # the prefix family lands a fixed-length character prefix.
    body = _plan_body(
        tmp_path, "sp.py",
        "def pre(s):\n    raise NotImplementedError\n",
        "from app.sp import pre\n"
        "def test():\n"
        "    assert pre('hello') == 'he'\n"
        "    assert pre('world') == 'wo'\n")
    assert body is not None and "return s[:2]" in body


# --- identity / empty slices are NOT spelled by this family ------------------

def test_full_sequence_stays_passthrough_no_identity_slice(tmp_path: Path):
    # echo([3, 1, 2]) == [3, 1, 2], echo([5, 9]) == [5, 9] -> the long-standing
    # passthrough body wins; the slice family deliberately drops the identity ``xs[:]``
    # (it would only shadow passthrough), so no full-length slice template is emitted.
    body = _plan_body(
        tmp_path, "ec.py",
        "def echo(xs):\n    raise NotImplementedError\n",
        "from app.ec import echo\n"
        "def test():\n"
        "    assert echo([3, 1, 2]) == [3, 1, 2]\n"
        "    assert echo([5, 9]) == [5, 9]\n")
    assert body is not None and "return xs" in body and "xs[:]" not in body


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "hd.py").write_text(
        "def head(xs):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_hd.py").write_text(
        "from app.hd import head\n"
        "def test():\n"
        "    assert head([3, 1, 2, 4]) == [3, 1]\n"
        "    assert head([5, 9, 1]) == [5, 9]\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/hd.py").new_contents.get("app/hd.py")
    again = plan_implement_stub(str(tmp_path), "app/hd.py").new_contents.get("app/hd.py")
    assert first is not None and "return xs[:2]" in first
    assert first == again


# --- REFUSALS ----------------------------------------------------------------

def test_single_witness_floor_refused(tmp_path: Path):
    # A LONE head([3, 1, 2, 4]) == [3, 1] must NOT land a slice body: one witness can't
    # tell xs[:2] from a bare ``return [3, 1]``, so the >=2-distinct-witness floor
    # withholds it. The list result equals no reduction/passthrough either, and a list
    # literal is not the constant last-resort's type oracle here, so the WHOLE synthesis
    # honestly REFUSES (file untouched) rather than overfit a slice to one example.
    body = _plan_body(
        tmp_path, "sw.py",
        "def head(xs):\n    raise NotImplementedError\n",
        "from app.sw import head\n"
        "def test():\n    assert head([3, 1, 2, 4]) == [3, 1]\n")
    assert body is None


def test_no_common_bound_mines_no_slice(tmp_path: Path):
    # pick([1, 2, 3]) == [1, 2] (a PREFIX, k=2) vs pick([9, 1, 2]) == [1, 2] (a SUFFIX,
    # k=1 — NOT a prefix): the slice that reproduces the expected output differs across
    # the witnesses, so every bound intersection is EMPTY and NO slice body is mined.
    # Any body that does land here is a pre-existing shape, NEVER an a[i:j] — the family
    # never guesses a bound that fails a witness.
    body = _plan_body(
        tmp_path, "ncm.py",
        "def pick(xs):\n    raise NotImplementedError\n",
        "from app.ncm import pick\n"
        "def test():\n"
        "    assert pick([1, 2, 3]) == [1, 2]\n"
        "    assert pick([9, 1, 2]) == [1, 2]\n")
    assert body is None or "xs[" not in body


# --- honesty: non-literal arg ------------------------------------------------

def test_non_literal_arg_is_honest_no_op(tmp_path: Path):
    # The witness arg is a module-level name, not a literal: no literal witness is
    # mined, so the slice family is withheld and nothing is guessed. No crash; any body
    # must be gate-verified, never a fake-green.
    body = _plan_body(
        tmp_path, "nl.py",
        "def head(xs):\n    raise NotImplementedError\n",
        "from app.nl import head\n"
        "XS = [3, 1, 2, 4]\n"
        "def test():\n    assert head(XS) == [3, 1]\n")
    assert body is None or isinstance(body, str)


# --- helper unit tests: bound mining -----------------------------------------

def test_prefix_bounds_intersection_sorted():
    from app.execution.stub_synthesis import _prefix_bounds

    # k == 2 reproduces [3, 1] / [5, 9] from each witness's own list -> [2]; the empty
    # prefix (k == 0) and whole-sequence identity (k >= len) are never mined.
    assert _prefix_bounds(
        [("[3, 1, 2, 4]", "[3, 1]"), ("[5, 9, 1]", "[5, 9]")]) == [2]
    # a string sequence mines the same way (character prefix length).
    assert _prefix_bounds(
        [("'hello'", "'he'"), ("'world'", "'wo'")]) == [2]


def test_suffix_bounds_intersection_sorted():
    from app.execution.stub_synthesis import _suffix_bounds

    # start == 1 reproduces the (differing-length) tails [1, 2] / [9, 1, 4] -> [1].
    assert _suffix_bounds(
        [("[3, 1, 2]", "[1, 2]"), ("[5, 9, 1, 4]", "[9, 1, 4]")]) == [1]


def test_closed_bounds_intersection_sorted():
    from app.execution.stub_synthesis import _closed_bounds

    # (1, 3) reproduces [8, 7] / [2, 3]; prefixes (start 0) and suffixes (stop == len)
    # are excluded — the open-ended families own those — so only the interior pair lands.
    assert _closed_bounds(
        [("[9, 8, 7, 6, 5]", "[8, 7]"), ("[1, 2, 3, 4, 5]", "[2, 3]")]) == [(1, 3)]
    # a string interior window mines the same way.
    assert _closed_bounds(
        [("'hello'", "'ell'"), ("'world'", "'orl'")]) == [(1, 4)]


def test_bounds_empty_single_and_non_sequence_mine_nothing():
    from app.execution.stub_synthesis import (
        _closed_bounds,
        _prefix_bounds,
        _suffix_bounds,
    )

    for fn in (_prefix_bounds, _suffix_bounds, _closed_bounds):
        # structural view: no literal to mine
        assert fn([]) == []
        # below the >=2-distinct-witness floor
        assert fn([("[3, 1, 2, 4]", "[3, 1]")]) == []
        # a non-sequence (int) argument cannot be sliced -> nothing
        assert fn([("5", "5"), ("6", "6")]) == []
        # a non-literal expected value -> the family cannot be mined
        assert fn([("[1, 2, 3]", "xs"), ("[5, 9]", "ys")]) == []


def test_type_mismatch_expected_refuses_family():
    from app.execution.stub_synthesis import _prefix_bounds, _slice_witness_seqs

    # A slice preserves its sequence's type, so a list-arg witness whose expected value
    # is an int can NEVER be a slice -> the whole family refuses (None seqs -> []).
    assert _slice_witness_seqs([("[1, 2, 3]", "1"), ("[5, 9]", "5")]) is None
    assert _prefix_bounds([("[1, 2, 3]", "1"), ("[5, 9]", "5")]) == []


def test_templates_emit_slice_body_pairs():
    from app.execution.stub_synthesis import _slice_templates

    # prefix, suffix, and closed pairs in fixed (prefix -> suffix -> closed) order.
    assert _slice_templates(
        "xs", [("[3, 1, 2, 4]", "[3, 1]"), ("[5, 9, 1]", "[5, 9]")]) == [
        ("slice[:2]", "xs[:2]")]
    assert _slice_templates(
        "xs", [("[3, 1, 2]", "[1, 2]"), ("[5, 9, 1, 4]", "[9, 1, 4]")]) == [
        ("slice[1:]", "xs[1:]")]
    assert _slice_templates(
        "xs",
        [("[9, 8, 7, 6, 5]", "[8, 7]"), ("[1, 2, 3, 4, 5]", "[2, 3]")]) == [
        ("slice[1:3]", "xs[1:3]")]
    assert _slice_templates("xs", []) == []  # no witnesses -> no template
