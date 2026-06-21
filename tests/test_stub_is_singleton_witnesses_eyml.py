"""Widened witness mining: the ``is None`` / ``is True`` / ``is False`` idiom.

The implement-stub witness miner used to recognise ONLY ``func(args) == expected``
asserts. The very common identity-equality idiom ``assert f(x) is None`` /
``is True`` / ``is False`` was DROPPED, so an idiomatically-pinned stub (e.g. the
``d.get(k)`` shape, whose missing-key contract is pinned ``assert cfg(d, 'k') is
None``) silently never landed. This suite proves the miner now ALSO mines those
three SINGLETON identity comparisons as witnesses — and stays conservative
everywhere else:

  * ``is None`` lets a mapping-access stub LAND (``d.get(k)``);
  * ``is True`` / ``is False`` lets a predicate stub land the right body;
  * a NON-singleton ``is`` (``f(x) is 5`` / ``is 'k'`` / ``is some_var``) is NOT
    mined (no false witness) — identity on a small int/str is not a value contract;
  * ``is not`` is NOT mined (the witness model is equality-only);
  * an ``is``-singleton assert inside an ``xfail``/``skip`` test pins no witness;
  * determinism: same fixture -> same body twice;
  * the existing ``==`` mining is byte-identical (strictly additive).

Never-fake-green holds: the singleton text flows through the SAME literal parsing,
accept-gate, and ambiguity guard as ``== None`` would — only the recognised SYNTAX
is widened, never the acceptance rule.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.stub_synthesis import (
    StubFunction,
    _function_witnesses,
    _singleton_witnesses,
    find_stub_functions,
)


# --- unit: the singleton miner itself ----------------------------------------

def _stub(name: str, params: tuple[str, ...]) -> StubFunction:
    return StubFunction(name=name, params=params, lineno=1, end_lineno=2,
                        indent="", is_method=False)


def test_is_none_is_mined():
    text = (
        "def test_x():\n"
        "    assert cfg({'a': 2}, 'k') is None\n")
    assert _singleton_witnesses(text, _stub("cfg", ("d", "k")), []) == [
        ("{'a': 2}, 'k'", "None")]


def test_is_true_and_is_false_are_mined():
    text = (
        "def test_p():\n"
        "    assert is_even(4) is True\n"
        "    assert is_even(3) is False\n")
    assert _singleton_witnesses(text, _stub("is_even", ("n",)), []) == [
        ("4", "True"), ("3", "False")]


def test_reversed_operand_order_is_mined():
    # ``None is f(x)`` (Yoda style) is mined just like ``f(x) is None``.
    text = (
        "def test_x():\n"
        "    assert None is lookup('missing')\n")
    assert _singleton_witnesses(text, _stub("lookup", ("k",)), []) == [
        ("'missing'", "None")]


def test_non_singleton_is_not_mined():
    # ``is 5`` / ``is 'k'`` / ``is some_var`` are NOT value contracts — no witness.
    text = (
        "some_var = object()\n"
        "def test_x():\n"
        "    assert f(3) is 5\n"
        "    assert f(2) is 'k'\n"
        "    assert f(1) is some_var\n")
    assert _singleton_witnesses(text, _stub("f", ("n",)), []) == []


def test_is_not_is_not_mined():
    # ``is not None`` would need a must-NOT-equal channel the witness model lacks.
    text = (
        "def test_x():\n"
        "    assert f(3) is not None\n"
        "    assert f(2) is not True\n")
    assert _singleton_witnesses(text, _stub("f", ("n",)), []) == []


def test_xfail_singleton_assert_is_dropped():
    # An assert in an xfail/skip line range pins no enforceable contract.
    text = (
        "def test_x():\n"
        "    assert f(3) is None\n")
    # Pretend line 2 lives in an unenforced range -> dropped.
    assert _singleton_witnesses(text, _stub("f", ("n",)), [(1, 5)]) == []


def test_keyword_or_star_arg_call_is_skipped():
    text = (
        "def test_x():\n"
        "    assert f(3, k=1) is None\n"
        "    assert f(*xs) is None\n")
    assert _singleton_witnesses(text, _stub("f", ("n", "k")), []) == []


def test_syntax_error_yields_no_singleton_witness():
    assert _singleton_witnesses("def (:::", _stub("f", ("n",)), []) == []


# --- integration: end-to-end landing through the plan path -------------------

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


def test_is_none_lets_dict_get_land(tmp_path: Path):
    # The motivating leak: a `d.get(k)` shape pinned with the idiomatic
    # `is None` for a missing key now LANDS (was refused/ambiguous before).
    body = _plan_body(
        tmp_path, "cfg.py",
        "def cfg(d, k):\n    raise NotImplementedError\n",
        "from app.cfg import cfg\n"
        "def test_get():\n"
        "    assert cfg({'x': 1}, 'x') == 1\n"
        "    assert cfg({'a': 2}, 'k') is None\n")
    assert body is not None and "return d.get(k)" in body


def test_is_true_false_lands_predicate(tmp_path: Path):
    # A parity predicate pinned with `is True`/`is False` lands `n % 2 == 0`.
    body = _plan_body(
        tmp_path, "ev.py",
        "def is_even(n):\n    raise NotImplementedError\n",
        "from app.ev import is_even\n"
        "def test_p():\n"
        "    assert is_even(4) is True\n"
        "    assert is_even(3) is False\n"
        "    assert is_even(2) is True\n")
    assert body is not None and "return n % 2 == 0" in body


def test_is_gt_predicate_lands(tmp_path: Path):
    # A threshold predicate pinned with `is True`/`is False`, with the boundary
    # tightly witnessed (9->False, 10->True), lands `a > 9` (a > k). The boundary
    # witnesses disambiguate the comparison so the ambiguity guard is satisfied.
    body = _plan_body(
        tmp_path, "big.py",
        "def is_big(a):\n    raise NotImplementedError\n",
        "from app.big import is_big\n"
        "def test_b():\n"
        "    assert is_big(9) is False\n"
        "    assert is_big(10) is True\n"
        "    assert is_big(11) is True\n"
        "    assert is_big(3) is False\n")
    assert body is not None and "return a > 9" in body


def test_non_singleton_is_does_not_land_false_body(tmp_path: Path):
    # `f(x) is 5` mines NO witness; with no other (enforceable, evaluable)
    # contract there is nothing to synthesize against -> refuse (no false green).
    body = _plan_body(
        tmp_path, "ns.py",
        "def f(n):\n    raise NotImplementedError\n",
        "from app.ns import f\n"
        "def test_x():\n"
        "    assert f(3) is 5\n"
        "    assert f(2) is 5\n")
    assert body is None  # `is 5` is not a value contract — nothing mined, refused


def test_is_none_determinism(tmp_path: Path):
    src = "def cfg(d, k):\n    raise NotImplementedError\n"
    test_src = (
        "from app.cfgd import cfg\n"
        "def test_get():\n"
        "    assert cfg({'x': 1}, 'x') == 1\n"
        "    assert cfg({'a': 2}, 'k') is None\n")
    first = _plan_body(tmp_path, "cfgd.py", src, test_src)
    # second run in a fresh dir -> identical body (no clock/random)
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    second = _plan_body(second_dir, "cfgd.py", src, test_src)
    assert first is not None and first == second


# --- regression: the `==` mining is byte-identical (strictly additive) --------

def test_equality_mining_byte_identical(tmp_path: Path):
    # A pure `==` contract yields exactly the witnesses it always did; the new
    # singleton pass appends nothing when there is no `is` compare.
    _suite_project(tmp_path)
    (tmp_path / "app" / "add.py").write_text(
        "def add(a, b):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_add.py").write_text(
        "from app.add import add\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
        "    assert add(10, 1) == 11\n", encoding="utf-8")
    src = (tmp_path / "app" / "add.py").read_text(encoding="utf-8")
    stub = next(s for s in find_stub_functions(src) if s.name == "add")
    assert _function_witnesses(tmp_path, ["tests/test_add.py"], stub) == [
        ("2, 3", "5"), ("10, 1", "11")]


def test_mixed_eq_and_is_none_witnesses_both_mined(tmp_path: Path):
    # `==` and `is None` asserts in one file: the `==` witness keeps its exact
    # text and the `is None` witness is appended (additive, not replacing).
    _suite_project(tmp_path)
    (tmp_path / "app" / "cfgm.py").write_text(
        "def cfg(d, k):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_cfgm.py").write_text(
        "from app.cfgm import cfg\n"
        "def test_get():\n"
        "    assert cfg({'x': 1}, 'x') == 1\n"
        "    assert cfg({'a': 2}, 'k') is None\n", encoding="utf-8")
    src = (tmp_path / "app" / "cfgm.py").read_text(encoding="utf-8")
    stub = next(s for s in find_stub_functions(src) if s.name == "cfg")
    assert _function_witnesses(tmp_path, ["tests/test_cfgm.py"], stub) == [
        ("{'x': 1}, 'x'", "1"), ("{'a': 2}, 'k'", "None")]
