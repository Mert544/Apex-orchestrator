"""1-arg STRING-CLASSIFICATION family for implement-stub synthesis.

This suite covers the NEW 1-arg boolean string-classifier shape:
``return a.<method>()`` for the ONE nullary ``str`` classifier — ``isdigit`` /
``isalpha`` / ``isalnum`` / ``isupper`` / ``islower`` / ``isspace`` / ``istitle``
— that reproduces EVERY witness's expected bool. ``is_num('123') == True,
is_num('12a') == False, is_num('') == False`` lands ``return s.isdigit()`` — the
ACTUAL ``str`` property the witnesses describe, found by testing each classifier
against the pairs, NOT a memorized lookup table that another (constant) family
would own.

The chosen method is VERIFIED to reproduce every witness's expected bool before it
is emitted (so the body holds by construction); the existing type-exact accept-gate
and the off-witness str-canary probes stay the sole arbiters, so nothing lands that
is not witness-verified and unambiguous (never-fake-green). The body returns a real
``bool`` — no domain/raise issue, and ``str`` arguments are guaranteed by the
str-only family. Plus: the contract must DISCRIMINATE (at least one True AND one
False, else it collapses to a constant another family owns); the
>=2-distinct-witness overfit floor (a single witness pins one bool and can derive
nothing); a classifier is emitted ONLY when it is the UNIQUE method reproducing
every witness, so when TWO methods both fit (``isdigit`` and ``isalnum`` agree on
all-digit ``True`` strings) the family REFUSES rather than guess; and a determinism
check.
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


def _no_classifier(body: str) -> bool:
    """True when ``body`` contains NO nullary str-classifier call — the refusal
    assertion: whatever value-free shape a fallback may land, it must not be an
    ``.is<...>()`` classifier the family was asked to withhold."""
    from app.execution.stub_synthesis import _STR_CLASSIFIER_METHODS

    return all(f".{m}()" not in body for m in _STR_CLASSIFIER_METHODS)


# --- LANDED: the unique witnessed classifier ---------------------------------

def test_isdigit_classifier_lands(tmp_path: Path):
    # is_num('123') == True, is_num('7') == True, is_num('12a') == False, is_num('')
    # == False -> s.isdigit(). isdigit is the ONLY nullary classifier reproducing all
    # four (isalnum is True on '12a', isalpha is False on '123', ...). The two True
    # strings '123'/'7' share NO common prefix or suffix, so no startswith/endswith
    # rival is mined to compete — the classifier lands unambiguously as the real str
    # property, not a memorized map.
    body = _plan_body(
        tmp_path, "n.py",
        "def is_num(s):\n    raise NotImplementedError\n",
        "from app.n import is_num\n"
        "def test():\n"
        "    assert is_num('123') == True\n"
        "    assert is_num('7') == True\n"
        "    assert is_num('12a') == False\n"
        "    assert is_num('') == False\n")
    assert body is not None and "return s.isdigit()" in body


def test_isalpha_classifier_lands(tmp_path: Path):
    # is_word('abc') == True, is_word('zy') == True, is_word('a1') == False,
    # is_word('12') == False -> s.isalpha(). isalpha is the unique fit: isalnum is
    # True on 'a1'/'12', isdigit is False on 'abc'. The True strings 'abc'/'zy' share
    # no prefix/suffix, so no startswith/endswith rival competes — isalpha lands
    # alone.
    body = _plan_body(
        tmp_path, "w.py",
        "def is_word(s):\n    raise NotImplementedError\n",
        "from app.w import is_word\n"
        "def test():\n"
        "    assert is_word('abc') == True\n"
        "    assert is_word('zy') == True\n"
        "    assert is_word('a1') == False\n"
        "    assert is_word('12') == False\n")
    assert body is not None and "return s.isalpha()" in body


def test_isupper_classifier_lands(tmp_path: Path):
    # is_shout('ABC') == True, is_shout('ZY') == True, is_shout('Abc') == False,
    # is_shout('abc') == False -> s.isupper(). isupper is the unique fit: isalpha is
    # True on all four, islower is True on 'abc', istitle is True on 'Abc'. The True
    # strings 'ABC'/'ZY' share no prefix/suffix, so no startswith/endswith rival
    # competes — isupper lands alone.
    body = _plan_body(
        tmp_path, "u.py",
        "def is_shout(s):\n    raise NotImplementedError\n",
        "from app.u import is_shout\n"
        "def test():\n"
        "    assert is_shout('ABC') == True\n"
        "    assert is_shout('ZY') == True\n"
        "    assert is_shout('Abc') == False\n"
        "    assert is_shout('abc') == False\n")
    assert body is not None and "return s.isupper()" in body


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "n.py").write_text(
        "def is_num(s):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_n.py").write_text(
        "from app.n import is_num\n"
        "def test():\n"
        "    assert is_num('123') == True\n"
        "    assert is_num('7') == True\n"
        "    assert is_num('12a') == False\n"
        "    assert is_num('') == False\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/n.py").new_contents.get("app/n.py")
    again = plan_implement_stub(str(tmp_path), "app/n.py").new_contents.get("app/n.py")
    assert first is not None and "return s.isdigit()" in first
    assert first == again


# --- REFUSALS ----------------------------------------------------------------

def test_non_discriminating_all_true_refused(tmp_path: Path):
    # f('123') == True, f('45') == True is NON-discriminating (no False witness):
    # every input the contract names is True, so a classifier would collapse to a
    # constant True the constant-last fallback owns. Whatever value-free shape the
    # gate lands, it is NEVER an .is<...>() classifier mined from an all-True
    # contract.
    body = _plan_body(
        tmp_path, "at.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.at import f\n"
        "def test():\n"
        "    assert f('123') == True\n"
        "    assert f('45') == True\n")
    assert body is None or ".isdigit(" not in body


def test_single_witness_floor_refused(tmp_path: Path):
    # A LONE f('123') == True pins exactly one bool and cannot discriminate, so the
    # >=2-distinct-witness floor withholds the classification family. Whatever
    # pre-existing value-free shape (if any) the gate lands, it is NEVER an
    # .is<...>() body mined from a single example.
    body = _plan_body(
        tmp_path, "s1.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.s1 import f\n"
        "def test():\n    assert f('123') == True\n")
    assert body is None or _no_classifier(body)


def test_no_classifier_reproduces_contract_refused(tmp_path: Path):
    # f('abc') == True, f('def') == False is a bool contract that NO nullary
    # classifier reproduces: every method agrees on the two all-lowercase-alpha
    # strings (isalpha True/True, islower True/True, isdigit False/False, ...), so
    # none yields True then False. The family emits nothing — never a guessed
    # classifier baked onto a contract no real str property explains.
    body = _plan_body(
        tmp_path, "nf.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.nf import f\n"
        "def test():\n"
        "    assert f('abc') == True\n"
        "    assert f('def') == False\n")
    assert body is None or _no_classifier(body)


def test_ambiguous_two_methods_fit_refused(tmp_path: Path):
    # f('123') == True, f('45') is not used (would be non-discriminating); instead
    # f('123') == True, f('@@') == False. Here BOTH isdigit and isalnum reproduce
    # every witness ('123' is digit AND alnum -> True; '@@' is neither -> False), so
    # the witnesses cannot tell which property is meant. The family refuses rather
    # than guess — no .is<...>() classifier is emitted (never-fake-green).
    body = _plan_body(
        tmp_path, "amb.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.amb import f\n"
        "def test():\n"
        "    assert f('123') == True\n"
        "    assert f('@@') == False\n")
    assert body is None or _no_classifier(body)


def test_int_arg_is_no_str_classifier(tmp_path: Path):
    # is_big(5) == False, is_big(200) == True is an INT contract: the str-only family
    # is PRUNED for a non-str arg (kind == "int"), so it can never contribute a
    # classifier body. No .is<...>() body is mined from an int arg.
    body = _plan_body(
        tmp_path, "i.py",
        "def is_big(n):\n    raise NotImplementedError\n",
        "from app.i import is_big\n"
        "def test():\n"
        "    assert is_big(5) == False\n"
        "    assert is_big(200) == True\n")
    assert body is None or _no_classifier(body)


def test_str_transform_not_a_classifier(tmp_path: Path):
    # shout('hi') == 'HI', shout('yo') == 'YO' is a str->str TRANSFORM, NOT a bool
    # predicate: the expected values are str, not bool, so the discriminating-witness
    # gate refuses the family. Whatever str-method shape lands (here s.upper()), it is
    # NEVER an .is<...>() classifier baked onto a str-returning contract.
    body = _plan_body(
        tmp_path, "t.py",
        "def shout(s):\n    raise NotImplementedError\n",
        "from app.t import shout\n"
        "def test():\n"
        "    assert shout('hi') == 'HI'\n"
        "    assert shout('yo') == 'YO'\n")
    assert body is None or _no_classifier(body)


# --- FAKE-GREEN CANARY -------------------------------------------------------

def test_fake_green_canary_off_witness_rejects_wrong_method():
    # The off-witness str canary is what keeps a wrong classifier from passing as
    # green. For the witnessed-true isdigit contract, isalnum is a rival that could
    # only fake-green: it already FAILS on the witness '12a' (isalnum -> True, the
    # contract expects False), so it is witness-false. And even where a rival
    # coincided on the witnessed CASING, the canary '12A' (the swapcase of the
    # witnessed '12a') splits isdigit (False) from isalnum (True) — proving the
    # off-witness probe rejects the wrong method. Only the witness-true isdigit
    # survives.
    from app.execution.stub_synthesis import (
        _classifier_reproduces_all,
        _str_canary_probes,
    )

    pairs = [("123", True), ("12a", False), ("", False)]
    # isdigit is witness-true; the fake-green rival isalnum is witness-false.
    assert _classifier_reproduces_all("isdigit", pairs) is True
    assert _classifier_reproduces_all("isalnum", pairs) is False
    # the off-witness canary carries a probe where the truth and the rival diverge.
    witnesses = [(("123",), True), (("12a",), False), (("",), False)]
    probes = [p[0] for p in _str_canary_probes(witnesses)]
    assert any(s.isdigit() != s.isalnum() for s in probes)


# --- helper unit tests -------------------------------------------------------

def test_classification_templates_pick_unique_method():
    from app.execution.stub_synthesis import _str_classification_templates

    # the unique isdigit fit -> exactly the one body.
    assert _str_classification_templates(
        "s",
        [("'123'", "True"), ("'12a'", "False"), ("''", "False")],
    ) == [("isdigit()", "s.isdigit()")]
    # isupper is the unique fit here.
    assert _str_classification_templates(
        "s",
        [("'ABC'", "True"), ("'Abc'", "False"), ("'abc'", "False")],
    ) == [("isupper()", "s.isupper()")]
    # two methods fit ('123'->True both digit and alnum, '@@'->False both) -> refuse.
    assert _str_classification_templates(
        "s", [("'123'", "True"), ("'@@'", "False")]) == []
    # no method reproduces a both-lowercase-alpha True/False split -> refuse.
    assert _str_classification_templates(
        "s", [("'abc'", "True"), ("'def'", "False")]) == []
    # non-discriminating all-True -> refuse.
    assert _str_classification_templates(
        "s", [("'1'", "True"), ("'2'", "True")]) == []
    # a non-str arg -> str-only, refuse.
    assert _str_classification_templates(
        "n", [("5", "True"), ("200", "False")]) == []
    # no witnesses (structural view) -> nothing to mine.
    assert _str_classification_templates("s", []) == []


def test_classifier_reproduces_all_witness_truth():
    from app.execution.stub_synthesis import _classifier_reproduces_all

    pairs = [("123", True), ("12a", False), ("", False)]
    # isdigit reproduces every pair; isalpha/isalnum/isupper do not.
    assert _classifier_reproduces_all("isdigit", pairs) is True
    assert _classifier_reproduces_all("isalpha", pairs) is False
    assert _classifier_reproduces_all("isalnum", pairs) is False
    # an empty pair list is vacuously reproduced by any method (the floor/gate, not
    # this primitive, withholds empty contracts).
    assert _classifier_reproduces_all("isdigit", []) is True
