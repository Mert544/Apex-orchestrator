"""1-arg DICT-KEY family for implement-stub synthesis.

This suite covers the NEW 1-arg dict-key shape: ``return a[k]`` for a fixed mapping
KEY ``k`` mined from the witnesses — the value stored under a CONSTANT key in EVERY
witnessed ``dict``. ``port({'host': 'a', 'port': 80}) == 80, port({'host': 'b',
'port': 443}) == 443`` lands ``return cfg['port']`` — a value no sequence index,
slice, or reduction template can spell (the argument is a mapping, not a sequence).

It is the mapping counterpart of the sequence constant-index family, and the two are
MUTUALLY EXCLUSIVE: the sequence miner's type gate is ``list`` / ``tuple`` / ``str``
and rejects a ``dict``; this miner's type gate is ``dict`` and rejects everything
else. Keys are the TYPE-EXACT intersection of the ``str`` / ``int`` keys whose value
reproduces every witness, so the key reproduces every witness by construction; the
existing type-exact accept-gate is the final arbiter (never-fake-green).

Because a ``dict`` argument has an EMPTY off-witness canary set, the off-witness
ambiguity guard is BLIND to a key choice, so this family carries TWO mandatory
never-fake-green guards enforced at MINE time:

* VARY-VALUES — the mined key's value must DIFFER across witnesses; an all-equal-value
  contract is a CONSTANT the constant-last fallback owns, and stamping ``a[k]`` over it
  would be fake-green, so it is REFUSED (the constant body lands instead);
* UNIQUE survivor — if MORE THAN ONE key survives the intersection, the witnesses
  cannot tell which key is meant, so NOTHING is mined.

Plus the >=2-distinct-witness overfit floor, ``bool`` / ``int`` type-exactness on both
keys and values, hashseed-safety (``d[k]`` reads one key, never iterates — UNLIKE the
forbidden ``set(a)``), a non-``dict`` no-op, a determinism check, and helper unit
tests for the mining / template / key-kind functions including their edge paths.
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


# --- LANDED: str key ---------------------------------------------------------

def test_str_key_dict_index_lands(tmp_path: Path):
    # port({'host': 'a', 'port': 80}) == 80, port({'host': 'b', 'port': 443}) == 443 ->
    # cfg['port']. 'port' is the only key whose value type-exactly reproduces BOTH
    # expecteds; 'host' fails (its value is a str, the expected an int). The values VARY
    # (80 != 443), so the contract is a genuine key read, not a constant.
    body = _plan_body(
        tmp_path, "pt.py",
        "def port(cfg):\n    raise NotImplementedError\n",
        "from app.pt import port\n"
        "def test():\n"
        "    assert port({'host': 'a', 'port': 80}) == 80\n"
        "    assert port({'host': 'b', 'port': 443}) == 443\n")
    assert body is not None and "return cfg['port']" in body


# --- LANDED: int key ---------------------------------------------------------

def test_int_key_dict_index_lands(tmp_path: Path):
    # look({1: 'a', 2: 'b'}) == 'a', look({1: 'c', 2: 'd'}) == 'c' -> d[1]. Key 1 holds
    # the expected value in both witnesses; key 2 holds 'b'/'d' which never match. Int
    # keys are mineable (str/int only); values VARY ('a' != 'c').
    body = _plan_body(
        tmp_path, "lk.py",
        "def look(d):\n    raise NotImplementedError\n",
        "from app.lk import look\n"
        "def test():\n"
        "    assert look({1: 'a', 2: 'b'}) == 'a'\n"
        "    assert look({1: 'c', 2: 'd'}) == 'c'\n")
    assert body is not None and "return d[1]" in body


# --- GUARD 1: VARY-VALUES refusal (never-fake-green) --------------------------

def test_all_equal_value_refuses_dict_index(tmp_path: Path):
    # f({'a': 5, 'b': 1}) == 5, f({'a': 5, 'b': 9}) == 5: the expected value is CONSTANT
    # (5 on both), so the contract is a plain ``return 5`` the constant-last fallback
    # owns. A dict arg has an EMPTY canary set, so the off-witness guard is BLIND to the
    # key choice — landing d['a'] here would be FAKE-GREEN (it stamps a key read over a
    # constant). GUARD 1 refuses the dict-index family at mine time; the honest constant
    # body lands instead (NOT an a[k] shape).
    body = _plan_body(
        tmp_path, "ae.py",
        "def f(d):\n    raise NotImplementedError\n",
        "from app.ae import f\n"
        "def test():\n"
        "    assert f({'a': 5, 'b': 1}) == 5\n"
        "    assert f({'a': 5, 'b': 9}) == 5\n")
    assert body is not None and "[" not in body  # no d['a'] / d[...] — a constant landed


# --- GUARD 2: >1 surviving key refusal ---------------------------------------

def test_more_than_one_surviving_key_refuses(tmp_path: Path):
    # g({'a': 7, 'b': 7}) == 7, g({'a': 8, 'b': 8}) == 8: BOTH keys 'a' and 'b' hold the
    # expected value in every witness (and the values VARY, clearing GUARD 1), so two
    # keys survive the intersection. The witnesses cannot tell which key is meant ->
    # GUARD 2 mines NOTHING (parity with the unique-survivor discipline). No a[k] body.
    body = _plan_body(
        tmp_path, "mk.py",
        "def g(d):\n    raise NotImplementedError\n",
        "from app.mk import g\n"
        "def test():\n"
        "    assert g({'a': 7, 'b': 7}) == 7\n"
        "    assert g({'a': 8, 'b': 8}) == 8\n")
    assert body is None or "d[" not in body


# --- overfit floor: single witness -------------------------------------------

def test_single_witness_floor_refuses(tmp_path: Path):
    # A LONE port({'host': 'a', 'port': 80}) == 80 must NOT mine a key: one witness can't
    # tell cfg['port'] from a bare return 80 (and the >=2-distinct-witness floor withholds
    # the family). Any body that lands is the constant fallback, never a key read.
    body = _plan_body(
        tmp_path, "sf.py",
        "def port(cfg):\n    raise NotImplementedError\n",
        "from app.sf import port\n"
        "def test():\n    assert port({'host': 'a', 'port': 80}) == 80\n")
    assert body is None or "cfg[" not in body


# --- honesty: non-dict arg ---------------------------------------------------

def test_non_dict_arg_mines_no_dict_index(tmp_path: Path):
    # second([1, 2, 3]) == 2, second([5, 9, 1]) == 9: a LIST argument is NOT a dict, so
    # the dict-index family mines nothing (it is mutually exclusive with the sequence
    # constant-index family, which owns this). The sequence index xs[1] may land, but no
    # dict-index body — confirms the flipped type gate.
    body = _plan_body(
        tmp_path, "nd.py",
        "def second(xs):\n    raise NotImplementedError\n",
        "from app.nd import second\n"
        "def test():\n"
        "    assert second([1, 2, 3]) == 2\n"
        "    assert second([5, 9, 1]) == 9\n")
    # the sequence family still lands its interior index; the dict family did not fire
    assert body is not None and "return xs[1]" in body


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "pt.py").write_text(
        "def port(cfg):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_pt.py").write_text(
        "from app.pt import port\n"
        "def test():\n"
        "    assert port({'host': 'a', 'port': 80}) == 80\n"
        "    assert port({'host': 'b', 'port': 443}) == 443\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/pt.py").new_contents.get("app/pt.py")
    second = plan_implement_stub(str(tmp_path), "app/pt.py").new_contents.get("app/pt.py")
    assert first is not None and "return cfg['port']" in first
    assert first == second


# --- helper unit tests: _dict_index_constants --------------------------------

def test_mines_unique_key_repr_sorted():
    from app.execution.stub_synthesis import _dict_index_constants

    # the single key whose value reproduces every witness, values varying.
    assert _dict_index_constants(
        [("{'host': 'a', 'port': 80}", "80"),
         ("{'host': 'b', 'port': 443}", "443")]) == ["port"]
    assert _dict_index_constants(
        [("{1: 'a', 2: 'b'}", "'a'"), ("{1: 'c', 2: 'd'}", "'c'")]) == [1]


def test_vary_values_guard_refuses_all_equal():
    from app.execution.stub_synthesis import _dict_index_constants

    # GUARD 1: every witness's expected value is the same constant -> [] (a constant the
    # fallback owns, not a key read — and the dict canary is empty, so it is enforced here).
    assert _dict_index_constants(
        [("{'a': 5, 'b': 1}", "5"), ("{'a': 5, 'b': 9}", "5")]) == []


def test_unique_survivor_guard_refuses_multiple_keys():
    from app.execution.stub_synthesis import _dict_index_constants

    # GUARD 2: two keys both reproduce every (varying) witness -> [] (ambiguous key).
    assert _dict_index_constants(
        [("{'a': 7, 'b': 7}", "7"), ("{'a': 8, 'b': 8}", "8")]) == []


def test_empty_single_and_non_dict_witnesses_mine_nothing():
    from app.execution.stub_synthesis import _dict_index_constants

    assert _dict_index_constants([]) == []  # structural view: no literal to mine
    assert _dict_index_constants([("{'a': 1, 'b': 2}", "1")]) == []  # below the floor
    # a non-dict (list) argument is out of scope -> nothing (sequence family owns it)
    assert _dict_index_constants([("[1, 2, 3]", "2"), ("[5, 9, 1]", "9")]) == []
    # a non-literal expected refuses the family
    assert _dict_index_constants([("{'a': 1}", "object()"), ("{'a': 2}", "object()")]) == []


def test_bool_int_type_exactness_on_keys_and_values():
    from app.execution.stub_synthesis import _dict_index_constants

    # bool KEY excluded: True is type-distinct from int, so a True key is never mined.
    # Here only the 'flag' bool key could hold 5 — excluded -> the int key 'n' is the
    # survivor (its values 1/0 vary).
    assert _dict_index_constants(
        [("{True: 9, 'n': 1}", "1"), ("{True: 9, 'n': 0}", "0")]) == ["n"]
    # value type-exactness: key 'n' holds int 1, expected is int 1; key 'flag' holds bool
    # True, type-distinct from int 1 -> 'flag' never matches an int expected -> ['n'].
    assert _dict_index_constants(
        [("{'flag': True, 'n': 1}", "1"), ("{'flag': True, 'n': 0}", "0")]) == ["n"]


def test_dict_key_kind_ok_str_int_not_bool():
    from app.execution.stub_synthesis import _dict_key_kind_ok

    assert _dict_key_kind_ok("port") is True
    assert _dict_key_kind_ok(1) is True
    assert _dict_key_kind_ok(True) is False  # bool is type-distinct from int
    assert _dict_key_kind_ok(1.5) is False
    assert _dict_key_kind_ok(None) is False


def test_templates_emit_dict_index_body_pairs():
    from app.execution.stub_synthesis import _dict_index_templates

    assert _dict_index_templates(
        "cfg",
        [("{'host': 'a', 'port': 80}", "80"),
         ("{'host': 'b', 'port': 443}", "443")]) == [
        ("dict_index['port']", "cfg['port']")]
    assert _dict_index_templates("d", []) == []  # no witnesses -> no template
