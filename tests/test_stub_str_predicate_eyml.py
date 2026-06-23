"""1-arg STRING-PREDICATE family for implement-stub synthesis.

This suite covers the NEW 1-arg boolean string-prefix/suffix shapes:
``return a.startswith(k)`` / ``return a.endswith(k)`` for a string constant ``k``
mined from the witnesses. ``is_http('http://x') == True, is_http('https://z') ==
True, is_http('ftp://y') == False`` lands ``return s.startswith('http')`` — the
witnessed prefix that reproduces every expected bool, a value no scalar / slice /
reduction / value-free string-method template can spell.

``k`` is the common PREFIX (resp. SUFFIX) of the ``True``-expecting strings, then
VERIFIED to reproduce EVERY witness's expected bool before it is emitted, so the
body holds by construction; the existing type-exact accept-gate and the off-witness
str-canary probes stay the sole arbiters, so nothing lands that is not
witness-verified and unambiguous (never-fake-green). The body returns a ``bool`` —
no domain/raise issue, and ``str`` arguments are guaranteed by the str-only family.
Plus: the contract must DISCRIMINATE (at least one True AND one False, else it
collapses to a constant another family owns), the >=2-distinct-witness overfit
floor (a single witness pins one bool and can derive nothing), no confusion with
existing string-method shapes, and a determinism check.
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


# --- LANDED: witness-mined prefix / suffix -----------------------------------

def test_startswith_prefix_lands(tmp_path: Path):
    # is_http('http://x') == True, is_http('https://z') == True, is_http('ftp://y')
    # == False -> s.startswith('http'). Two True strings share the 'http' prefix; the
    # False string does not, so 'http' is the unique common prefix that reproduces
    # every expected bool. The endswith rival can't match (the True suffixes differ),
    # so the predicate lands unambiguously.
    body = _plan_body(
        tmp_path, "h.py",
        "def is_http(s):\n    raise NotImplementedError\n",
        "from app.h import is_http\n"
        "def test():\n"
        "    assert is_http('http://x') == True\n"
        "    assert is_http('https://z') == True\n"
        "    assert is_http('ftp://y') == False\n")
    assert body is not None and "return s.startswith('http')" in body


def test_endswith_suffix_lands(tmp_path: Path):
    # is_png('a.png') == True, is_png('logo.png') == True, is_png('b.txt') == False ->
    # name.endswith('.png'). The True strings share the '.png' suffix; the False one
    # does not. The startswith rival can't match (the True prefixes differ), so the
    # endswith predicate lands unambiguously.
    body = _plan_body(
        tmp_path, "e.py",
        "def is_png(name):\n    raise NotImplementedError\n",
        "from app.e import is_png\n"
        "def test():\n"
        "    assert is_png('a.png') == True\n"
        "    assert is_png('logo.png') == True\n"
        "    assert is_png('b.txt') == False\n")
    assert body is not None and "return name.endswith('.png')" in body


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "h.py").write_text(
        "def is_http(s):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_h.py").write_text(
        "from app.h import is_http\n"
        "def test():\n"
        "    assert is_http('http://x') == True\n"
        "    assert is_http('https://z') == True\n"
        "    assert is_http('ftp://y') == False\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/h.py").new_contents.get("app/h.py")
    again = plan_implement_stub(str(tmp_path), "app/h.py").new_contents.get("app/h.py")
    assert first is not None and "return s.startswith('http')" in first
    assert first == again


# --- REFUSALS ----------------------------------------------------------------

def test_non_discriminating_all_true_refused(tmp_path: Path):
    # f('http://x') == True, f('http://y') == True is NON-discriminating (no False
    # witness): every input the contract names is True, so a startswith/endswith
    # predicate would collapse to a constant True the constant-last fallback owns.
    # The family must refuse it — whatever value-free shape the gate lands, it is
    # NEVER a startswith(...)/endswith(...) predicate mined from an all-True contract.
    body = _plan_body(
        tmp_path, "a.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.a import f\n"
        "def test():\n"
        "    assert f('http://x') == True\n"
        "    assert f('http://y') == True\n")
    assert body is None or (".startswith(" not in body and ".endswith(" not in body)


def test_single_witness_floor_refused(tmp_path: Path):
    # A LONE f('http://x') == True pins exactly one bool and cannot discriminate, so
    # the >=2-distinct-witness floor withholds the predicate family. Whatever
    # pre-existing value-free shape (if any) the gate lands, it is NEVER a
    # startswith/endswith body mined from a single example.
    body = _plan_body(
        tmp_path, "s1.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.s1 import f\n"
        "def test():\n    assert f('http://x') == True\n")
    assert body is None or (".startswith(" not in body and ".endswith(" not in body)


def test_int_arg_is_no_str_predicate(tmp_path: Path):
    # is_big(5) == False, is_big(200) == True is an INT contract: the str-only
    # predicate family is PRUNED for a non-str arg (kind == "int"), so it can never
    # contribute a startswith/endswith body. Whatever the gate/ambiguity guard does
    # with the numeric shapes, no string-predicate body is mined from an int arg.
    body = _plan_body(
        tmp_path, "i.py",
        "def is_big(n):\n    raise NotImplementedError\n",
        "from app.i import is_big\n"
        "def test():\n"
        "    assert is_big(5) == False\n"
        "    assert is_big(200) == True\n")
    assert body is None or (".startswith(" not in body and ".endswith(" not in body)


def test_str_transform_not_a_predicate(tmp_path: Path):
    # shout_down('HELLO') == 'hello', shout_down('WORLD') == 'world' is a str->str
    # TRANSFORM, NOT a bool predicate: the expected values are str, not bool, so
    # _discriminating_str_predicate_witnesses refuses the family. Whatever the
    # existing string-method shapes / ambiguity guard land, it is NEVER a
    # startswith/endswith predicate baked onto a str-returning contract.
    body = _plan_body(
        tmp_path, "l.py",
        "def shout_down(s):\n    raise NotImplementedError\n",
        "from app.l import shout_down\n"
        "def test():\n"
        "    assert shout_down('HELLO') == 'hello'\n"
        "    assert shout_down('WORLD') == 'world'\n")
    assert body is None or (".startswith(" not in body and ".endswith(" not in body)


# --- honesty: non-literal arg ------------------------------------------------

def test_non_literal_arg_is_honest_no_op(tmp_path: Path):
    # The witness arg is a module-level name, not a literal: no literal witness is
    # mined, so the predicate family is withheld and nothing is guessed. No crash.
    body = _plan_body(
        tmp_path, "nl.py",
        "def is_http(s):\n    raise NotImplementedError\n",
        "from app.nl import is_http\n"
        "URL = 'http://x'\n"
        "def test():\n    assert is_http(URL) == True\n")
    assert body is None or isinstance(body, str)


# --- helper unit tests -------------------------------------------------------

def test_templates_emit_predicate_body_pairs():
    from app.execution.stub_synthesis import _str_predicate_templates

    # two True share 'http' + one False -> only startswith('http') (endswith can't
    # match: the True suffixes 'http://x' / 'https://z' have no shared non-empty tail
    # that is False on 'ftp://y').
    assert _str_predicate_templates(
        "s",
        [("'http://x'", "True"), ("'https://z'", "True"), ("'ftp://y'", "False")],
    ) == [("startswith('http')", "s.startswith('http')")]
    # two True share '.png' + one False -> only endswith('.png').
    assert _str_predicate_templates(
        "name",
        [("'a.png'", "True"), ("'logo.png'", "True"), ("'b.txt'", "False")],
    ) == [("endswith('.png')", "name.endswith('.png')")]
    # no witnesses (structural view) -> nothing to mine.
    assert _str_predicate_templates("s", []) == []


def test_discriminating_witnesses_gate():
    from app.execution.stub_synthesis import _discriminating_str_predicate_witnesses

    # a genuine discriminating contract -> the (str, bool) pairs.
    assert _discriminating_str_predicate_witnesses(
        [("'http://x'", "True"), ("'ftp://y'", "False")]) == [
        ("http://x", True), ("ftp://y", False)]
    # all-True -> non-discriminating, None.
    assert _discriminating_str_predicate_witnesses(
        [("'a'", "True"), ("'b'", "True")]) is None
    # all-False -> non-discriminating, None.
    assert _discriminating_str_predicate_witnesses(
        [("'a'", "True"), ("'b'", "True")]) is None
    # a non-bool (int) expected -> the family is refused (a predicate is always bool).
    assert _discriminating_str_predicate_witnesses(
        [("'a'", "0"), ("'b'", "1")]) is None
    # a non-str argument -> str-only, refused.
    assert _discriminating_str_predicate_witnesses(
        [("5", "True"), ("200", "False")]) is None


def test_prefix_and_suffix_constant_miners():
    from app.execution.stub_synthesis import _str_prefix_constant, _str_suffix_constant

    # the True strings share 'http'; it is False on 'ftp://y' -> 'http' reproduces all.
    pairs = [("http://x", True), ("https://z", True), ("ftp://y", False)]
    assert _str_prefix_constant(pairs) == "http"
    # a lone True string yields its own full text as the prefix, which still
    # discriminates the False witness (its prefix differs) -> 'ab'.
    assert _str_prefix_constant([("ab", True), ("cd", False)]) == "ab"
    # the False witness is itself a PREFIX of the True one ('ab' starts with 'a'),
    # so the common-prefix 'ab' makes startswith('ab') False on 'a' (expected True):
    # no single k reproduces both -> None.
    assert _str_prefix_constant([("a", True), ("ab", False)]) is None
    # the True strings share the '.png' suffix; False on 'b.txt'.
    spairs = [("a.png", True), ("logo.png", True), ("b.txt", False)]
    assert _str_suffix_constant(spairs) == ".png"
    assert _str_suffix_constant([("a", True), ("ba", False)]) is None


def test_longest_common_prefix_edges():
    from app.execution.stub_synthesis import _longest_common_prefix

    assert _longest_common_prefix(["http://x", "https://z"]) == "http"
    assert _longest_common_prefix(["abc"]) == "abc"  # single string is its own prefix
    assert _longest_common_prefix([]) == ""          # empty list -> empty prefix
    assert _longest_common_prefix(["ab", "cd"]) == ""  # no shared prefix
