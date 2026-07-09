"""1-arg witness-DERIVED ``return a.replace(old, new)`` family for implement-stub.

This suite covers the NEW 1-arg mined-substitution shape: ``return a.replace(old,
new)`` for the ONE constant ``(old, new)`` pair MINED from the input->output
transformation that, applied to EVERY witnessed input, reproduces EVERY expected
output. ``slug('a b') == 'a-b', slug('c d e') == 'c-d-e'`` lands
``return s.replace(' ', '-')`` — the single substitution the witnesses actually
describe, DERIVED (never the combinatorial cross-product guess the old literal-pair
``_ordered_string_pairs`` makes) by reading the changed span of a seed witness and
INTERSECTING it across the rest. ``str.replace`` returns a real ``str``, type-exact
for the accept-gate.

The pair is VERIFIED to reproduce every witness (``inp.replace(old, new) == out``)
before it is emitted, so the body holds by construction; the existing type-exact
accept-gate and the off-witness str canary probes stay the sole arbiters, so nothing
lands that is not witness-verified and unambiguous (never-fake-green). Plus: the
outputs must actually DIFFER from the inputs for at least one witness (an ``out == in``
contract is the identity another family owns, refused here); the >=2-distinct-witness
overfit floor (a single witness bakes its own literals into a wrong map); the empty
``old`` is excluded (``replace('', x)`` inserts everywhere — degenerate); the pair is
emitted ONLY when it is the UNIQUE survivor, so when TWO distinct ``(old, new)`` both
reproduce every witness the family REFUSES rather than guess; and a determinism check.

The mined grounded pair takes precedence over the literal cross-product (which DEFERS
to it), so a pure-substitution contract that the cross-product left under-determined
(rival shapes tripping the ambiguity guard) now lands. A case-folding contract
(``slug('A B') == 'a-b'``) is NOT a plain substitution — the miner finds no pair and
the pre-existing ``s.lower().replace(' ', '-')`` behaviour is preserved untouched.
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


# --- LANDED: the unique witnessed (old, new) ---------------------------------

def test_single_char_substitution_lands(tmp_path: Path):
    # slug('a b') == 'a-b', slug('c d e') == 'c-d-e' -> s.replace(' ', '-'). ' '->'-' is
    # the ONLY (old, new) that reproduces both: the seed's wider spans (' b'->'-b',
    # 'a b'->'a-b') fail on 'c d e', so only the single-char substitution survives. The
    # inputs are already lowercase, so NO .lower() is needed — the literal cross-product
    # leaves this under-determined (rival spans trip the ambiguity guard), but the mined
    # grounded pair lands it unambiguously.
    body = _plan_body(
        tmp_path, "sl.py",
        "def slug(s):\n    raise NotImplementedError\n",
        "from app.sl import slug\n"
        "def test():\n"
        "    assert slug('a b') == 'a-b'\n"
        "    assert slug('c d e') == 'c-d-e'\n")
    assert body is not None and "return s.replace(' ', '-')" in body


def test_multi_char_substring_substitution_lands(tmp_path: Path):
    # f('foobaz') == 'barbaz', f('xfoo') == 'xbar' -> s.replace('foo', 'bar'). The
    # MULTI-CHAR substring 'foo'->'bar' is the unique survivor: single-char spans
    # ('f'/'o'->...) cannot reproduce both whole-word swaps, so only the full 'foo'->'bar'
    # fits every witness. A substring substitution is a value no slice / split / value-free
    # string-method template can spell.
    body = _plan_body(
        tmp_path, "mc.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.mc import f\n"
        "def test():\n"
        "    assert f('foobaz') == 'barbaz'\n"
        "    assert f('xfoo') == 'xbar'\n")
    assert body is not None and "return s.replace('foo', 'bar')" in body


def test_deletion_substitution_lands(tmp_path: Path):
    # strip_dash('a-b') == 'ab', strip_dash('c-d-e') == 'cde' -> s.replace('-', ''). A
    # deletion is a substitution with an EMPTY new: '-'->'' is the unique survivor (the
    # wider seed spans fail on the second witness). An empty NEW is fine — only an empty
    # OLD is degenerate. The mined pair lands; the literal cross-product would leave it
    # ambiguous.
    body = _plan_body(
        tmp_path, "dl.py",
        "def strip_dash(s):\n    raise NotImplementedError\n",
        "from app.dl import strip_dash\n"
        "def test():\n"
        "    assert strip_dash('a-b') == 'ab'\n"
        "    assert strip_dash('c-d-e') == 'cde'\n")
    assert body is not None and "return s.replace('-', '')" in body


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "sl.py").write_text(
        "def slug(s):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_sl.py").write_text(
        "from app.sl import slug\n"
        "def test():\n"
        "    assert slug('a b') == 'a-b'\n"
        "    assert slug('c d e') == 'c-d-e'\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/sl.py").new_contents.get("app/sl.py")
    again = plan_implement_stub(str(tmp_path), "app/sl.py").new_contents.get("app/sl.py")
    assert first is not None and "return s.replace(' ', '-')" in first
    assert first == again


# --- REFUSALS ----------------------------------------------------------------

def test_single_witness_floor_refused(tmp_path: Path):
    # A LONE slug('a b') == 'a-b' is a single example: the >=2-distinct-witness floor
    # withholds the witness-DERIVED replace family (one example could pin an arbitrary
    # (old, new) — e.g. 'a b'->'a-b' — that is wrong for the next input). Whatever
    # pre-existing value-free shape (if any) the gate lands, it is NEVER a .replace( body
    # mined from a single example.
    body = _plan_body(
        tmp_path, "s1.py",
        "def slug(s):\n    raise NotImplementedError\n",
        "from app.s1 import slug\n"
        "def test():\n    assert slug('a b') == 'a-b'\n")
    assert body is None or ".replace(" not in body


def test_identity_contract_refused(tmp_path: Path):
    # echo('abc') == 'abc', echo('xyz') == 'xyz' is the IDENTITY: every output equals its
    # input, so no real substitution is described — a no-op replace would collapse to the
    # passthrough / value-free chain another family owns. The mined family refuses rather
    # than bake a coincidental (old, new) whose new == old.
    body = _plan_body(
        tmp_path, "id.py",
        "def echo(s):\n    raise NotImplementedError\n",
        "from app.id import echo\n"
        "def test():\n"
        "    assert echo('abc') == 'abc'\n"
        "    assert echo('xyz') == 'xyz'\n")
    assert body is None or ".replace(" not in body


# Legitimately slow, not hung: refusal paths probe EVERY candidate through
# the real nested-pytest gate (~2 min on a 2-core box), living at the exact
# edge of the global --timeout=120 hang-catcher — measured borderline both
# pre- and post-wave, so this is a hardware-speed margin, not a regression.
# Same precedent as test_security_audit.py's widened timeout.
@pytest.mark.timeout(300)
def test_no_pair_reproduces_contract_refused(tmp_path: Path):
    # f('ab') == 'cd', f('ef') == 'gh' is a str->str contract that NO single (old, new)
    # reproduces (the two transforms share no common substitution). The family emits
    # nothing — never a guessed pair baked onto a contract no real .replace explains.
    body = _plan_body(
        tmp_path, "nf.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.nf import f\n"
        "def test():\n"
        "    assert f('ab') == 'cd'\n"
        "    assert f('ef') == 'gh'\n")
    assert body is None or ".replace(" not in body


# Legitimately slow, not hung: refusal paths probe EVERY candidate through
# the real nested-pytest gate (~2 min on a 2-core box), living at the exact
# edge of the global --timeout=120 hang-catcher — measured borderline both
# pre- and post-wave, so this is a hardware-speed margin, not a regression.
# Same precedent as test_security_audit.py's widened timeout.
@pytest.mark.timeout(300)
def test_ambiguous_two_pairs_fit_refused(tmp_path: Path):
    # f('cab') == 'ccb', f('dab') == 'dcb' is reproduced by TWO distinct pairs — both
    # 'a'->'c' AND 'ab'->'cb' give 'ccb'/'dcb' — so the witnesses cannot tell which span
    # is meant. The family refuses rather than guess: no .replace( body is emitted
    # (never-fake-green).
    body = _plan_body(
        tmp_path, "am.py",
        "def f(s):\n    raise NotImplementedError\n",
        "from app.am import f\n"
        "def test():\n"
        "    assert f('cab') == 'ccb'\n"
        "    assert f('dab') == 'dcb'\n")
    assert body is None or ".replace(" not in body


def test_int_arg_is_no_replace(tmp_path: Path):
    # double(2) == 4, double(5) == 10 is an INT contract: an int has no .replace, and the
    # replace family mines only str args, so it never contributes a body here (n * 2 lands
    # instead). No .replace( body is mined from an int arg.
    body = _plan_body(
        tmp_path, "i.py",
        "def double(n):\n    raise NotImplementedError\n",
        "from app.i import double\n"
        "def test():\n"
        "    assert double(2) == 4\n"
        "    assert double(5) == 10\n")
    assert body is None or ".replace(" not in body


def test_case_fold_contract_unaffected_lands_lower_replace(tmp_path: Path):
    # slug('A B') == 'a-b', slug('C D') == 'c-d' is a CASE-FOLDING contract: a plain
    # s.replace(' ', '-') gives 'A-B' != 'a-b', so the mined family finds NO pair and the
    # pre-existing s.lower().replace(' ', '-') behaviour is preserved untouched. The mined
    # variant must not destabilise this existing landing.
    body = _plan_body(
        tmp_path, "cf.py",
        "def slug(s):\n    raise NotImplementedError\n",
        "from app.cf import slug\n"
        "def test():\n"
        "    assert slug('A B') == 'a-b'\n"
        "    assert slug('C D') == 'c-d'\n")
    assert body is not None and ".lower().replace(' ', '-')" in body


# --- FAKE-GREEN CANARY -------------------------------------------------------

def test_fake_green_canary_off_witness_rejects_wrong_pair():
    # The off-witness str canary is what keeps a wrong (old, new) from passing as green.
    # For the ' '->'-' slug contract, a case-flipped rival (e.g. derived from a witness
    # with no surrounding whitespace) can coincide on the witnessed values yet diverge on
    # a perturbation. The canary carries probes (whitespace-padded / separator-injected)
    # where the witness-true pair and any rival genuinely differ, so the gate can reject a
    # pair that merely coincides on the witnesses. Only the witness-true ' '->'-'
    # (verified against every witness) is what the miner emits.
    from app.execution.stub_synthesis import _str_canary_probes

    pairs = [("a b", "a-b"), ("c d e", "c-d-e")]
    # ' '->'-' is witness-true; a rival whole-span swap 'a b'->'a-b' coincides on witness 1.
    assert all(inp.replace(" ", "-") == out for inp, out in pairs)
    assert "a b".replace("a b", "a-b") == "a-b"  # rival coincides on the first witness
    # the off-witness canary carries a probe where the truth and the rival diverge.
    witnesses = [(("a b",), "a-b"), (("c d e",), "c-d-e")]
    probes = [p[0] for p in _str_canary_probes(witnesses)]
    assert any(s.replace(" ", "-") != s.replace("a b", "a-b") for s in probes)


# --- helper unit tests -------------------------------------------------------

def test_replace_templates_pick_unique_pair():
    from app.execution.stub_synthesis import _replace_templates

    # the unique ' '->'-' fit -> exactly the one body.
    assert _replace_templates(
        "s", [("'a b'", "'a-b'"), ("'c d e'", "'c-d-e'")],
    ) == [("replace(' ','-')", "s.replace(' ', '-')")]
    # the unique multi-char 'foo'->'bar' fit -> one body.
    assert _replace_templates(
        "s", [("'foobaz'", "'barbaz'"), ("'xfoo'", "'xbar'")],
    ) == [("replace('foo','bar')", "s.replace('foo', 'bar')")]
    # a deletion ('-'->'') is a valid substitution (empty NEW is fine) -> one body.
    assert _replace_templates(
        "s", [("'a-b'", "'ab'"), ("'c-d-e'", "'cde'")],
    ) == [("replace('-','')", "s.replace('-', '')")]
    # two distinct pairs ('a'->'c' and 'ab'->'cb') fit -> ambiguous, refuse.
    assert _replace_templates(
        "s", [("'cab'", "'ccb'"), ("'dab'", "'dcb'")]) == []
    # no single pair reproduces -> refuse.
    assert _replace_templates("s", [("'ab'", "'cd'"), ("'ef'", "'gh'")]) == []
    # an all-identity contract (out == in) -> refuse (no substitution).
    assert _replace_templates("s", [("'abc'", "'abc'"), ("'xyz'", "'xyz'")]) == []
    # a non-str arg -> refuse.
    assert _replace_templates("n", [("2", "4"), ("5", "10")]) == []
    # no witnesses (structural view) -> nothing to mine.
    assert _replace_templates("s", []) == []


def test_replace_pair_candidates_mine_seed_span():
    from app.execution.stub_synthesis import _replace_pair_candidates

    # seed 'a b'->'a-b': the substring spans whose segment-join reproduces the output,
    # sorted, the empty old excluded, no-ops dropped.
    assert _replace_pair_candidates([("a b", "a-b")]) == [
        (" ", "-"), (" b", "-b"), ("a ", "a-"), ("a b", "a-b")]
    # an empty pair list (structural view) -> no candidates.
    assert _replace_pair_candidates([]) == []


def test_replace_new_for_old_segment_derivation():
    from app.execution.stub_synthesis import _replace_new_for_old

    # the unique new that segment-joins the segments of 'a b' split on ' ' to 'a-b'.
    assert _replace_new_for_old("a b", "a-b", " ") == "-"
    # a deletion: '-' -> '' rebuilds 'ab' from 'a-b'.
    assert _replace_new_for_old("a-b", "ab", "-") == ""
    # an old ABSENT from the input is not a candidate.
    assert _replace_new_for_old("abc", "xyz", "q") is None
    # an empty old is degenerate (insert-everywhere) -> None, never a substitution.
    assert _replace_new_for_old("ab", "axb", "") is None
    # multiple occurrences must share ONE constant new (here ' '->'-' twice).
    assert _replace_new_for_old("a a a", "a-a-a", " ") == "-"
    # inconsistent separators (the gaps disagree) -> no single new.
    assert _replace_new_for_old("x.x.x", "x-x_x", ".") is None


def test_replace_witness_pairs_validation():
    from app.execution.stub_synthesis import _replace_witness_pairs

    # str args with str expected that differ -> the parsed pairs.
    assert _replace_witness_pairs(
        [("'a b'", "'a-b'"), ("'c d'", "'c-d'")]) == [("a b", "a-b"), ("c d", "c-d")]
    # an all-identity contract (out == in for every witness) -> None (no substitution).
    assert _replace_witness_pairs([("'a'", "'a'"), ("'b'", "'b'")]) is None
    # a non-str expected is type-distinct (a .replace is a str) -> None.
    assert _replace_witness_pairs([("'a'", "1"), ("'b'", "2")]) is None
    # a non-str arg -> None.
    assert _replace_witness_pairs([("2", "'a'"), ("5", "'b'")]) is None
    # a multi-arg witness -> None (this is a 1-arg family).
    assert _replace_witness_pairs([("'a', 'b'", "'x'"), ("'c', 'd'", "'y'")]) is None
