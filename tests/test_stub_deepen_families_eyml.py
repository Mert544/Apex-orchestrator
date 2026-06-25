"""Deepened implement-stub template space — 4 NEW witness-gated body families.

Each family lands a VERIFIED body exactly where the old single-``return``-expr
engine produced NOTHING (a previously-refused stub now lands), and each is
AMBIGUITY-CHECKED, HASHSEED-SAFE and VERIFIED-OR-REFUSED:

  (2a) CLAMP / PIECEWISE       — ``max(lo, min(hi, a))`` / ``max(lo, a)`` / relu.
  (2b) ELEMENT-WISE MAP        — ``[x * k for x in a]`` / ``[x * x …]`` / reductions.
  (2c) MULTI-ARG ARITHMETIC    — ``(a + b) / 2`` (2 params) and ``a*b+c`` (3 params).
  (2d) DOCTEST DEEPENING       — a multi-line-``want`` doctest-only map LANDS; a
                                 ``Returns:``-documented stub with no example/test
                                 gets an honest DECLINE, not a guessed body.

The proof discipline mirrors ``test_stub_templates_widened_eyml``: a body returned
by ``plan_implement_stub`` has passed the FULL pinned pytest gate (so it is
behaviour-verified, never just inferred). For each family this suite pins:

  * the LANDING — a discriminating contract lands the intended body;
  * BACK-COMPAT — the new family fires only where the old engine produced nothing;
    a simpler existing shape still wins when it fits;
  * the OVERFIT FLOOR — a single non-discriminating example REFUSES;
  * the AMBIGUITY REFUSAL — a contract two new-shape bodies both satisfy but that
    diverge on a canary REFUSES (never guess-and-pray);
  * DETERMINISM — the same fixture lands a byte-identical body twice AND across
    ``PYTHONHASHSEED`` 0 vs 1 (no clock/random, fixed source order);
  * HASHSEED SAFETY — a set-typed witness never yields a set comprehension.

Everything is offline, zero-token, stdlib-only.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from app.execution.stub_synthesis import (
    StubFunction,
    candidate_bodies,
    find_stub_functions,
    pinned_test_files,
    stub_decline_reason,
    synthesize_doctest_body,
    synthesize_expr_from_witnesses,
)


# --- helpers -----------------------------------------------------------------

def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _plan_body(tmp_path: Path, module: str, src: str, test_src: str) -> str | None:
    """The body ``plan_implement_stub`` LANDS for the one stub in ``src`` — i.e. a
    body that PASSED the full pinned pytest gate, or ``None`` (REFUSE)."""
    from app.execution.objectives.implement_stub import plan_implement_stub

    _suite_project(tmp_path)
    (tmp_path / "app" / module).write_text(src, encoding="utf-8")
    (tmp_path / "tests" / f"test_{module}").write_text(test_src, encoding="utf-8")
    rel = f"app/{module}"
    return plan_implement_stub(str(tmp_path), rel).new_contents.get(rel)


def _stub_named(src: str, name: str) -> StubFunction:
    return next(st for st in find_stub_functions(src) if st.name == name)


def _synth(tmp_path: Path, module: str, src: str, test_src: str,
           fn: str) -> str | None:
    """The in-process witness-determined body for ``fn`` (no pytest gate) — used to
    assert the FAST oracle's verdict (ambiguity / determinism) without the slow
    subprocess gate. Mirrors what ``plan_implement_stub`` lands."""
    (tmp_path / module).write_text(src, encoding="utf-8")
    (tmp_path / f"test_{module}").write_text(test_src, encoding="utf-8")
    stub = _stub_named(src, fn)
    tests = pinned_test_files(tmp_path, module, fn)
    return synthesize_expr_from_witnesses(tmp_path, tests, stub)


# =========================================================================
# (2a) CLAMP / PIECEWISE
# =========================================================================

def test_clamp_two_sided_lands_verified(tmp_path: Path):
    # clip to [0, 50]: -5/-9 saturate low (->0), 99/77 saturate high (->50), 3
    # passes through. Two distinct inputs per boundary + a pass-through pin the
    # two-sided clamp uniquely; the OLD engine had no general ternary, so this is a
    # previously-refused stub that now lands a behaviour-verified body.
    body = _plan_body(
        tmp_path, "cl.py",
        "def clip(x):\n    raise NotImplementedError\n",
        "from app.cl import clip\n"
        "def test():\n"
        "    assert clip(-5) == 0\n    assert clip(-9) == 0\n"
        "    assert clip(3) == 3\n"
        "    assert clip(99) == 50\n    assert clip(77) == 50\n")
    assert body is not None and "return max(0, min(50, x))" in body


def test_clamp_lower_only_lands(tmp_path: Path):
    # relu-at-0: -5/-9 -> 0 (two distinct low inputs), 3 passes through, NO upper
    # saturation. Only the lower clamp ``max(0, x)`` is determined (no hi witness),
    # so it lands without an upper-bound guess.
    body = _plan_body(
        tmp_path, "rl.py",
        "def relu(x):\n    raise NotImplementedError\n",
        "from app.rl import relu\n"
        "def test():\n"
        "    assert relu(-5) == 0\n    assert relu(-9) == 0\n"
        "    assert relu(3) == 3\n    assert relu(8) == 8\n")
    assert body is not None and "return max(0, x)" in body


def test_clamp_single_flat_example_refuses_overfit(tmp_path: Path):
    # ONE flat example (clip(99) == 50) plus one pass-through is below the >=2-
    # distinct-flat-inputs floor: a lone saturation could be a constant, a cap, or
    # a scaling — so the clamp family is withheld and the stub REFUSES.
    body = _plan_body(
        tmp_path, "of.py",
        "def clip(x):\n    raise NotImplementedError\n",
        "from app.of import clip\n"
        "def test():\n    assert clip(3) == 3\n    assert clip(99) == 50\n")
    assert body is None


def test_clamp_upper_only_lands(tmp_path: Path):
    # cap-at-50: 3/8 pass through, 99/60 saturate high (->50), no low saturation.
    # The upper clamp ``min(50, x)`` is uniquely determined and lands.
    body = _plan_body(
        tmp_path, "uc.py",
        "def cap(x):\n    raise NotImplementedError\n",
        "from app.uc import cap\n"
        "def test():\n"
        "    assert cap(3) == 3\n    assert cap(8) == 8\n"
        "    assert cap(99) == 50\n    assert cap(60) == 50\n")
    assert body is not None and "return min(50, x)" in body


def test_clamp_flat_only_no_passthrough_refuses(tmp_path: Path):
    # Every input saturates to 0 and NOTHING passes through unchanged: that is a
    # CONSTANT in disguise, not a clamp, so the clamp family is withheld (no
    # pass-through region). No clamp body is offered for this contract.
    src = "def f(x):\n    raise NotImplementedError\n"
    stub = _stub_named(src, "f")
    witnesses = [("-5", "0"), ("-9", "0"), ("2", "0"), ("7", "0")]
    clamp = [label for label, _expr in candidate_bodies(stub, witnesses)
             if label.startswith(("clamp", "relu", "floor"))]
    assert clamp == []


# =========================================================================
# (2b) ELEMENT-WISE MAP / REDUCTION
# =========================================================================

def test_map_scaled_lands_verified(tmp_path: Path):
    # doubles([1,2])==[2,4], doubles([3])==[6]: only [x*2 for x in a] fits both.
    # The OLD engine emitted no comprehension at all, so this previously refused.
    body = _plan_body(
        tmp_path, "db.py",
        "def doubles(a):\n    raise NotImplementedError\n",
        "from app.db import doubles\n"
        "def test():\n"
        "    assert doubles([1, 2]) == [2, 4]\n    assert doubles([3]) == [6]\n")
    assert body is not None and "return [x * 2 for x in a]" in body


def test_map_square_lands_verified(tmp_path: Path):
    # squares([1,2,3])==[1,4,9], squares([2])==[4]: only [x*x for x in a] fits.
    body = _plan_body(
        tmp_path, "sq.py",
        "def squares(a):\n    raise NotImplementedError\n",
        "from app.sq import squares\n"
        "def test():\n"
        "    assert squares([1, 2, 3]) == [1, 4, 9]\n"
        "    assert squares([2]) == [4]\n")
    assert body is not None and "return [x * x for x in a]" in body


def test_map_ambiguous_all_equal_refuses(tmp_path: Path):
    # g([1,1])==[2,2], g([1])==[2]: BOTH [x*2 …] and [x+1 …] satisfy every witness
    # (1*2 == 1+1 == 2). The per-element canary [1, 2, 3] makes them DIVERGE
    # ([2,4,6] vs [2,3,4]) -> ambiguous -> REFUSE (no guess-and-pray).
    body = _plan_body(
        tmp_path, "am.py",
        "def g(a):\n    raise NotImplementedError\n",
        "from app.am import g\n"
        "def test():\n    assert g([1, 1]) == [2, 2]\n    assert g([1]) == [2]\n")
    assert body is None


def test_map_empty_list_witness_handled(tmp_path: Path):
    # An empty-list witness is a valid sample: doubles([]) == [] holds for every
    # map shape, so it neither lands nor crashes; the non-empty witnesses still
    # pin [x*2 …]. Empty-path safety.
    body = _plan_body(
        tmp_path, "em.py",
        "def doubles(a):\n    raise NotImplementedError\n",
        "from app.em import doubles\n"
        "def test():\n"
        "    assert doubles([]) == []\n"
        "    assert doubles([1, 2]) == [2, 4]\n    assert doubles([3]) == [6]\n")
    assert body is not None and "return [x * 2 for x in a]" in body


def test_map_set_witness_never_yields_set_comprehension():
    # HASHSEED SAFETY: a set-typed witness must never produce a set comprehension
    # (set-iteration order is hashseed-dependent). The candidate space offers only
    # LIST comprehensions / scalars, never ``{... for ...}``.
    stub = StubFunction(name="f", params=("a",), lineno=1, end_lineno=1,
                        indent="", is_method=False)
    cands = candidate_bodies(stub, [("{1, 2}", "{2, 4}"), ("{3}", "{6}")])
    assert not any("{" in expr and "for" in expr for _label, expr in cands)


def test_map_set_output_contract_refuses_soundly(tmp_path: Path):
    # A set-OUTPUT contract (f({1,2}) == {2,4}) is refused: every map body returns a
    # LIST, type-distinct from the expected set, so the type-exact gate rejects it
    # — no hashseed-order-dependent body ever lands (never-fake-green).
    expr = _synth(
        tmp_path, "so.py",
        "def f(a):\n    raise NotImplementedError\n",
        "from m import f\n"
        "def test():\n    assert f({1, 2}) == {2, 4}\n    assert f({3}) == {6}\n",
        "f")
    assert expr is None


# =========================================================================
# (2c) MULTI-ARG ARITHMETIC (2-3 params)
# =========================================================================

def test_avg_float_mean_lands_verified(tmp_path: Path):
    # avg(2,4)==3.0, avg(0,10)==5.0: (a+b)/2. The OLD 2-arg space formed only one
    # binary op on a,b — no mean shape existed, so this previously refused.
    body = _plan_body(
        tmp_path, "av.py",
        "def avg(a, b):\n    raise NotImplementedError\n",
        "from app.av import avg\n"
        "def test():\n    assert avg(2, 4) == 3.0\n    assert avg(0, 10) == 5.0\n")
    assert body is not None and "return (a + b) / 2" in body


def test_avg_int_floor_mean_lands_verified(tmp_path: Path):
    # Integer expecteds pin the // variant: avg(2,4)==3 (int) lands (a+b)//2, the
    # type-exact gate separating it from the float (a+b)/2.
    body = _plan_body(
        tmp_path, "ai.py",
        "def avg(a, b):\n    raise NotImplementedError\n",
        "from app.ai import avg\n"
        "def test():\n    assert avg(2, 4) == 3\n    assert avg(0, 10) == 5\n")
    assert body is not None and "return (a + b) // 2" in body


def test_three_arg_combination_lands_verified(tmp_path: Path):
    # f(2,3,4)==10 (2*3+4), f(1,1,1)==2: a*b+c. The OLD engine ignored param 3
    # entirely — a 3-arg arithmetic stub got NOTHING. Now it lands, verified.
    body = _plan_body(
        tmp_path, "th.py",
        "def f(a, b, c):\n    raise NotImplementedError\n",
        "from app.th import f\n"
        "def test():\n    assert f(2, 3, 4) == 10\n    assert f(1, 1, 1) == 2\n")
    assert body is not None and "return a * b + c" in body


def test_multi_arg_single_example_refuses_overfit(tmp_path: Path):
    # A single 3-arg example pins nothing uniquely (a*b+c, (a+b)*c, … all coincide
    # somewhere); below the >=2-distinct floor the derived combos refuse.
    body = _plan_body(
        tmp_path, "ov3.py",
        "def f(a, b, c):\n    raise NotImplementedError\n",
        "from app.ov3 import f\n"
        "def test():\n    assert f(1, 1, 1) == 2\n")
    assert body is None


# =========================================================================
# BACK-COMPAT — a simpler EXISTING shape still wins
# =========================================================================

def test_existing_binary_add_still_wins_over_new_shapes(tmp_path: Path):
    # add(2,3)==5, add(10,1)==11: the existing ``a + b`` (offered BEFORE the new
    # multi-arg family) still lands — the new shapes never displace a simpler one.
    body = _plan_body(
        tmp_path, "bc1.py",
        "def add(a, b):\n    raise NotImplementedError\n",
        "from app.bc1 import add\n"
        "def test():\n    assert add(2, 3) == 5\n    assert add(10, 1) == 11\n")
    assert body is not None and "return a + b" in body


def test_existing_passthrough_still_wins(tmp_path: Path):
    # A genuine passthrough still lands ``return n`` — the clamp family (offered
    # after) does not steal a pass-through-only contract.
    body = _plan_body(
        tmp_path, "bc2.py",
        "def ident(n):\n    raise NotImplementedError\n",
        "from app.bc2 import ident\n"
        "def test():\n    assert ident(5) == 5\n    assert ident(9) == 9\n")
    assert body is not None and "return n" in body


def test_existing_sum_reduction_still_wins(tmp_path: Path):
    # total([1,2,3])==6, total([4,5])==9: the existing ``sum(a)`` (offered before
    # the map family) still wins over any comprehension.
    body = _plan_body(
        tmp_path, "bc3.py",
        "def total(a):\n    raise NotImplementedError\n",
        "from app.bc3 import total\n"
        "def test():\n    assert total([1, 2, 3]) == 6\n    assert total([4, 5]) == 9\n")
    assert body is not None and "return sum(a)" in body


# =========================================================================
# (2d) DOCTEST DEEPENING
# =========================================================================

_SQUARES_DOC = (
    "def squares(a):\n"
    '    """Square each element.\n\n'
    "    >>> squares([1, 2, 3])\n"
    "    [1, 4, 9]\n"
    "    >>> squares([2])\n"
    "    [4]\n"
    '    """\n'
    "    raise NotImplementedError\n"
)


def test_doctest_only_map_multiline_want_lands(tmp_path: Path):
    # A stub pinned ONLY by doctests whose ``want`` is a multi-line list literal on
    # its own line lands [x*x for x in a], verified by re-running the examples — no
    # test file involved. This is the doctest-deepening landing.
    (tmp_path / "m.py").write_text(_SQUARES_DOC, encoding="utf-8")
    stub = _stub_named(_SQUARES_DOC, "squares")
    expr = synthesize_doctest_body(tmp_path, [], stub, _SQUARES_DOC)
    assert expr == "[x * x for x in a]"


def test_returns_documented_without_example_declines(tmp_path: Path):
    # A stub that documents a return (Google ``Returns:``) but pins NO example/test
    # yields a body of NOTHING and an honest DECLINE naming what to add — never a
    # guessed body.
    src = (
        "def parse(x):\n"
        '    """Parse x.\n\n'
        "    Returns:\n"
        "        The parsed value.\n"
        '    """\n'
        "    raise NotImplementedError\n")
    stub = _stub_named(src, "parse")
    reason = stub_decline_reason(src, stub)
    assert reason is not None
    assert "documents a return but pins no example/test" in reason
    assert "parse" in reason


def test_returns_annotation_without_example_declines(tmp_path: Path):
    # A non-None return ANNOTATION with no example/test also declines.
    src = "def parse(x) -> int:\n    raise NotImplementedError\n"
    stub = _stub_named(src, "parse")
    assert stub_decline_reason(src, stub) is not None


def test_decline_suppressed_when_doctest_present(tmp_path: Path):
    # A ``Returns:``-documented stub that ALSO carries a ``>>>`` example is
    # synthesizable -> no decline (the disclosure is only for the no-witness case).
    src = (
        "def double(n):\n"
        '    """Double n.\n\n'
        "    Returns:\n        twice n.\n\n"
        "    >>> double(3)\n    6\n    >>> double(5)\n    10\n"
        '    """\n'
        "    raise NotImplementedError\n")
    stub = _stub_named(src, "double")
    assert stub_decline_reason(src, stub) is None


def test_decline_suppressed_when_test_present(tmp_path: Path):
    # With ``has_pinned_test=True`` the stub is gated by pytest -> nothing to
    # decline even if it documents a return.
    src = "def parse(x) -> int:\n    raise NotImplementedError\n"
    stub = _stub_named(src, "parse")
    assert stub_decline_reason(src, stub, has_pinned_test=True) is None


def test_no_decline_when_no_return_documented(tmp_path: Path):
    # A bare stub documenting no return value gets NO decline (out of scope).
    src = "def f(x):\n    raise NotImplementedError\n"
    stub = _stub_named(src, "f")
    assert stub_decline_reason(src, stub) is None


def test_decline_is_deterministic():
    src = (
        "def parse(x):\n"
        '    """Parse.\n\n    Returns:\n        a value.\n    """\n'
        "    raise NotImplementedError\n")
    stub = _stub_named(src, "parse")
    assert stub_decline_reason(src, stub) == stub_decline_reason(src, stub)


# =========================================================================
# DETERMINISM (per-family, two runs + cross-hashseed)
# =========================================================================

def test_each_family_synthesis_is_deterministic(tmp_path: Path):
    # Two in-process syntheses of each family over a fresh dir land byte-identical.
    cases = [
        ("def clip(x):\n    raise NotImplementedError\n",
         "from m import clip\n"
         "def test():\n    assert clip(-5)==0\n    assert clip(-9)==0\n"
         "    assert clip(3)==3\n    assert clip(99)==50\n    assert clip(77)==50\n",
         "clip", "max(0, min(50, x))"),
        ("def doubles(a):\n    raise NotImplementedError\n",
         "from m import doubles\n"
         "def test():\n    assert doubles([1,2])==[2,4]\n    assert doubles([3])==[6]\n",
         "doubles", "[x * 2 for x in a]"),
        ("def avg(a, b):\n    raise NotImplementedError\n",
         "from m import avg\n"
         "def test():\n    assert avg(2,4)==3.0\n    assert avg(0,10)==5.0\n",
         "avg", "(a + b) / 2"),
    ]
    for i, (src, test, fn, expected) in enumerate(cases):
        d1 = tmp_path / f"a{i}"
        d2 = tmp_path / f"b{i}"
        d1.mkdir()
        d2.mkdir()
        b1 = _synth(d1, "m.py", src, test, fn)
        b2 = _synth(d2, "m.py", src, test, fn)
        assert b1 == b2 == expected


def test_families_land_identically_across_hashseeds():
    # The landed body for each family is byte-identical under PYTHONHASHSEED 0 vs 1
    # (no clock/random; comprehension/clamp output order is input-driven, never
    # set-iteration-ordered). Run in a seeded subprocess, mirroring examples_pass.
    program = textwrap.dedent(
        """
        import tempfile
        from pathlib import Path
        from app.execution.stub_synthesis import (
            find_stub_functions, pinned_test_files,
            synthesize_expr_from_witnesses,
        )
        def syn(mod_src, test_src, fn):
            d = Path(tempfile.mkdtemp())
            (d / "m.py").write_text(mod_src)
            (d / "test_m.py").write_text(test_src)
            stub = next(s for s in find_stub_functions(mod_src) if s.name == fn)
            tests = pinned_test_files(d, "m.py", fn)
            return synthesize_expr_from_witnesses(d, tests, stub)
        out = []
        out.append(syn("def clip(x):\\n raise NotImplementedError\\n",
            "from m import clip\\ndef t():\\n assert clip(-5)==0\\n"
            " assert clip(-9)==0\\n assert clip(3)==3\\n"
            " assert clip(99)==50\\n assert clip(77)==50\\n", "clip"))
        out.append(syn("def doubles(a):\\n raise NotImplementedError\\n",
            "from m import doubles\\ndef t():\\n assert doubles([1,2])==[2,4]\\n"
            " assert doubles([3])==[6]\\n", "doubles"))
        out.append(syn("def f(a,b,c):\\n raise NotImplementedError\\n",
            "from m import f\\ndef t():\\n assert f(2,3,4)==10\\n"
            " assert f(1,1,1)==2\\n", "f"))
        print(repr(out))
        """
    )

    def run(seed: str) -> str:
        proc = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True, text=True,
            env={"PYTHONHASHSEED": seed, "PYTHONPATH": str(Path.cwd())},
            cwd=str(Path.cwd()), check=True)
        return proc.stdout.strip()

    out0 = run("0")
    out1 = run("1")
    assert out0 == out1
    assert "max(0, min(50, x))" in out0
    assert "[x * 2 for x in a]" in out0
    assert "a * b + c" in out0
