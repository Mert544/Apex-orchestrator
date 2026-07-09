"""1-arg LEFT-CONSTANT REPEAT family for implement-stub synthesis.

This suite covers the NEW 1-arg sequence-repeat shape: ``return k * a`` for a
witness-MINED integer ``k`` — the sequence-repetition MIRROR of the existing
witness-derived ``a * k`` (:func:`_scalar_arith_templates`, constant on the RIGHT).
That family only reliably finds ``k`` for plain NUMERIC witnesses — its constant
source is int-literal presence or an arithmetic offset/quotient, not a structural
length ratio — so a genuine sequence-repeat contract (``quad([5, 8]) == [5, 8, 5,
8, 5, 8, 5, 8]``) bakes no literal ``4`` anywhere in the witness text and is never
proposed by it. This family derives ``k`` STRUCTURALLY instead: the sole integer
such that ``k * seq`` reproduces the EXPECTED sequence across every witness.

Every witness independently proposes a ``k``; ALL witnesses must agree on the exact
same ``k``, and any witness that cannot support the shape at all (non-literal,
multi-arg, mixed-type, non-sequence, empty input, or a length ratio that does not
actually reproduce the sequence) voids the WHOLE family — never guessed. Gated
behind the same >=2-distinct-witness overfit floor every other value-derived shape
in this module uses. Only ``*`` is offered, and only on the LEFT (``k * a``) — the
spelling this family owns, distinct from :func:`_scalar_arith_templates`'s
RIGHT-constant ``a * k``.

Covered: list and str landings with a NON-COINCIDENTAL multiplier (proves the
derivation is structural, not literal-presence luck), the >=2-distinct-witness
floor refusal, an inconsistent-``k`` refusal, a mixed-type refusal, a REGRESSION
PIN that the pre-existing numeric right-constant family (``a * k``) is unaffected,
determinism, and helper unit tests for the mining functions including their empty /
single / non-sequence / k-in-{0,1} edge paths.
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


# --- LANDED: k * a on a list, k not literally present in the witnesses -------

def test_left_constant_mult_lands_list(tmp_path: Path):
    # quad([5, 8]) == [5, 8, 5, 8, 5, 8, 5, 8], quad([2]) == [2, 2, 2, 2] -> 4 * xs.
    # Neither witness contains the literal 4 anywhere (elements are 5, 8, 2), so the
    # RIGHT-constant _scalar_arith_templates family (which only proposes literal-
    # present / arithmetically-derived k) can never find it: only the structural
    # length-ratio derivation this family adds can.
    body = _plan_body(
        tmp_path, "q4.py",
        "def quad(xs):\n    raise NotImplementedError\n",
        "from app.q4 import quad\n"
        "def test():\n"
        "    assert quad([5, 8]) == [5, 8, 5, 8, 5, 8, 5, 8]\n"
        "    assert quad([2]) == [2, 2, 2, 2]\n")
    assert body is not None and "return 4 * xs" in body


def test_left_constant_mult_lands_str(tmp_path: Path):
    # triple_s('ab') == 'ababab', triple_s('x') == 'xxx' -> 3 * s. A str is a sequence
    # too; _scalar_arith_templates is not even OFFERED for a str-kind argument, so this
    # family is the SOLE source of a multiply body here.
    body = _plan_body(
        tmp_path, "trs.py",
        "def triple_s(s):\n    raise NotImplementedError\n",
        "from app.trs import triple_s\n"
        "def test():\n"
        "    assert triple_s('ab') == 'ababab'\n"
        "    assert triple_s('x') == 'xxx'\n")
    assert body is not None and "return 3 * s" in body


# --- REGRESSION PIN: pre-existing numeric right-constant family unaffected ---

def test_numeric_right_constant_regression_unaffected(tmp_path: Path):
    # triple(3) == 9, triple(5) == 15 -> n * 3 (the PRE-EXISTING _scalar_arith_templates
    # shape, RIGHT constant). A plain int argument is never a str/bytes/list/tuple, so
    # this NEW family never even proposes a candidate for it — byte-identical to before.
    body = _plan_body(
        tmp_path, "nm.py",
        "def triple(n):\n    raise NotImplementedError\n",
        "from app.nm import triple\n"
        "def test():\n"
        "    assert triple(3) == 9\n"
        "    assert triple(5) == 15\n")
    assert body is not None and "return n * 3" in body


# --- DETERMINISM -------------------------------------------------------------

def test_determinism_same_fixture_same_body(tmp_path: Path):
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / "q4.py").write_text(
        "def quad(xs):\n    raise NotImplementedError\n", encoding="utf-8")
    (tmp_path / "tests" / "test_q4.py").write_text(
        "from app.q4 import quad\n"
        "def test():\n"
        "    assert quad([5, 8]) == [5, 8, 5, 8, 5, 8, 5, 8]\n"
        "    assert quad([2]) == [2, 2, 2, 2]\n", encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "app/q4.py").new_contents.get("app/q4.py")
    again = plan_implement_stub(str(tmp_path), "app/q4.py").new_contents.get("app/q4.py")
    assert first is not None and "return 4 * xs" in first
    assert first == again


# --- REFUSALS ----------------------------------------------------------------

def test_single_witness_floor_refused(tmp_path: Path):
    # A LONE quad([5, 8]) == [5, 8, 5, 8, 5, 8, 5, 8] must NOT land a k*a body: one
    # witness cannot tell a genuine repeat from a coincidental length match — the
    # >=2-distinct-witness floor withholds it.
    body = _plan_body(
        tmp_path, "s1.py",
        "def quad1(xs):\n    raise NotImplementedError\n",
        "from app.s1 import quad1\n"
        "def test():\n    assert quad1([5, 8]) == [5, 8, 5, 8, 5, 8, 5, 8]\n")
    assert body is None or "* xs" not in body


def test_inconsistent_k_refused(tmp_path: Path):
    # quadi([5, 8]) == [5, 8]*4, but quadi([2]) == [2, 2] is only a 2x repeat -> the
    # two witnesses disagree on k (4 vs 2), so the WHOLE family voids -- never guessed.
    body = _plan_body(
        tmp_path, "qi.py",
        "def quadi(xs):\n    raise NotImplementedError\n",
        "from app.qi import quadi\n"
        "def test():\n"
        "    assert quadi([5, 8]) == [5, 8, 5, 8, 5, 8, 5, 8]\n"
        "    assert quadi([2]) == [2, 2]\n")
    assert body is None or "* xs" not in body


def test_mixed_type_witness_refused(tmp_path: Path):
    # mixedt([1, 2]) == '12121212' (a list repeated into a STR) can never satisfy
    # k * seq == expected (list * k is never == to a str) -- TYPE-EXACT, refused.
    body = _plan_body(
        tmp_path, "mx.py",
        "def mixedt(xs):\n    raise NotImplementedError\n",
        "from app.mx import mixedt\n"
        "def test():\n"
        "    assert mixedt([1, 2]) == '12121212'\n"
        "    assert mixedt([3]) == '333'\n")
    assert body is None or "* xs" not in body


def test_non_literal_arg_is_honest_no_op(tmp_path: Path):
    # The witness arg is a module-level name, not a literal: no literal witness is
    # mined, so the family is withheld and nothing is guessed. No crash.
    body = _plan_body(
        tmp_path, "nl.py",
        "def quad(xs):\n    raise NotImplementedError\n",
        "from app.nl import quad\n"
        "XS = [5, 8]\n"
        "def test():\n    assert quad(XS) == [5, 8, 5, 8, 5, 8, 5, 8]\n")
    assert body is None or isinstance(body, str)


# --- helper unit tests: _sequence_repeat_factor / _witness_repeat_factor -----

def test_witness_repeat_factor_mines_k():
    from app.execution.stub_synthesis import _witness_repeat_factor

    assert _witness_repeat_factor("[5, 8]", "[5, 8, 5, 8, 5, 8, 5, 8]") == 4
    assert _witness_repeat_factor("[2]", "[2, 2, 2, 2]") == 4
    assert _witness_repeat_factor("'ab'", "'ababab'") == 3


def test_witness_repeat_factor_excludes_zero_and_one():
    from app.execution.stub_synthesis import _witness_repeat_factor

    # k == 1: a plain passthrough -- owned by the identity family, not this one.
    assert _witness_repeat_factor("[1, 2]", "[1, 2]") is None
    # k == 0: an always-empty result -- owned by the constant-return fallback.
    assert _witness_repeat_factor("[1, 2]", "[]") is None


def test_witness_repeat_factor_rejects_non_sequence_and_mixed_type():
    from app.execution.stub_synthesis import _witness_repeat_factor

    assert _witness_repeat_factor("5", "20") is None  # a bare int is not a sequence
    assert _witness_repeat_factor("[1, 2]", "'1212'") is None  # list -> str: refused
    assert _witness_repeat_factor("[]", "[]") is None  # empty input: no ratio


def test_witness_repeat_factor_rejects_non_reproducing_ratio():
    from app.execution.stub_synthesis import _witness_repeat_factor

    # length ratio divides evenly (4 / 2 == 2) but the shuffled expected is NOT
    # actually seq * 2 -- the reproduction check (not just the length ratio) refuses.
    assert _witness_repeat_factor("[1, 2]", "[2, 1, 1, 2]") is None


def test_sequence_repeat_factor_requires_consistency_and_floor():
    from app.execution.stub_synthesis import _sequence_repeat_factor

    assert _sequence_repeat_factor([]) is None  # structural view: nothing to mine
    assert _sequence_repeat_factor([("[5, 8]", "[5, 8, 5, 8]")]) is None  # below floor
    assert _sequence_repeat_factor(
        [("[5, 8]", "[5, 8, 5, 8, 5, 8, 5, 8]"), ("[2]", "[2, 2]")]) is None  # k mismatch
    assert _sequence_repeat_factor(
        [("[5, 8]", "[5, 8, 5, 8, 5, 8, 5, 8]"), ("[2]", "[2, 2, 2, 2]")]) == 4


def test_left_constant_mult_templates_emit_body_pairs():
    from app.execution.stub_synthesis import _left_constant_mult_templates

    assert _left_constant_mult_templates(
        "xs", [("[5, 8]", "[5, 8, 5, 8, 5, 8, 5, 8]"), ("[2]", "[2, 2, 2, 2]")]
    ) == [("4*a", "4 * xs")]
    assert _left_constant_mult_templates("xs", []) == []  # no witnesses -> no template
