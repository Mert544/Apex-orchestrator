"""END-TO-END: a stub pinned ONLY by its docstring ``>>>`` examples is LANDED.

The unit suite ``test_stub_doctest_witnesses_eyml`` pins the witness MINING (a
``>>> double(3)\\n6`` becomes a ``("3", "6")`` witness). This suite pins the rest
of the wiring that makes that mining REAL in production — the three fixes that
turn a dead extractor into a landing, verified contribution:

1. ``module_source`` is threaded to the scan oracle, so a doctest-only stub (NO
   ``test_*.py`` file) is reported fillable by ``can_fill_stub_in_process`` and
   ``module_has_fillable_stub`` — not silently dropped.
2. ``plan_implement_stub`` actually LANDS such a stub, verifying the synthesized
   body by RUNNING its own ``>>>`` examples with the stdlib ``doctest`` (a
   doctest-only stub has no pytest file to gate it). The scan oracle and the apply
   gate AGREE: a doctest-only stub the scan calls fillable is exactly one the
   apply lands and doctest-verifies — never an over-count.
3. Honesty nits: a ``# doctest: +SKIP`` example is unenforced and ignored (like an
   xfail assert), and a doctest ``want`` that contains ``#`` (a string repr like
   ``'#red'``) is parsed whole, never truncated by test-file comment-stripping.

Never-fake-green is pinned both ways: a body that does NOT reproduce the examples
is refused (``verify_body_via_doctest`` rejects it, so nothing lands), and the
verified-apply engine still rolls a fill back if the impacted suite regresses. The
no-doctest path is unchanged (``module_source=None`` is byte-for-byte as before),
the >=2-distinct floor still rejects a lone example, and everything is
deterministic and offline.
"""

from __future__ import annotations

import doctest
import types
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.objectives.implement_stub import plan_implement_stub
from app.execution.stub_synthesis import (
    can_fill_stub_in_process,
    filled_source_passes_doctests,
    find_stub_functions,
    has_enforceable_doctest_examples,
    module_has_fillable_stub,
    synthesize_doctest_body,
    synthesize_expr_from_witnesses,
    verify_body_via_doctest,
)


# --- helpers -----------------------------------------------------------------

def _stub(src: str):
    """The single stub the source declares — the function under fill."""
    stubs = find_stub_functions(src)
    assert stubs, "fixture must declare exactly one stub"
    return stubs[0]


def _doctest_is_green(source: str) -> bool:
    """True when EVERY ``>>>`` example in ``source`` passes — the contract the
    apply path claims to have satisfied, re-checked here independently with the
    stdlib ``doctest`` (the buyer's own verification)."""
    module = types.ModuleType("apex_e2e_mod")
    exec(compile(source, "apex_e2e_mod.py", "exec"), module.__dict__)  # noqa: S102
    result = doctest.testmod(module, verbose=False)
    return result.attempted > 0 and result.failed == 0


_DOUBLE = (
    "def double(n):\n"
    '    """Double n.\n\n'
    "    >>> double(3)\n"
    "    6\n"
    "    >>> double(5)\n"
    "    10\n"
    '    """\n'
    "    raise NotImplementedError\n"
)


# --- (a) a doctest-only stub is SEEN and LANDED, verified by doctest ----------

def test_doctest_only_stub_is_scanned_fillable(tmp_path: Path):
    # The scan oracle and the module scan both report the doctest-only stub
    # fillable once the module source is threaded through (fix 1).
    (tmp_path / "m.py").write_text(_DOUBLE, encoding="utf-8")
    stub = _stub(_DOUBLE)
    assert can_fill_stub_in_process(tmp_path, [], stub, _DOUBLE) is True
    assert module_has_fillable_stub(tmp_path, "m.py") is True


def test_doctest_only_stub_lands_and_is_doctest_green(tmp_path: Path):
    # plan_implement_stub LANDS the body for a stub with NO pinned test file, and
    # the filled module's own doctests pass (fix 2). The docstring is preserved.
    (tmp_path / "m.py").write_text(_DOUBLE, encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "m.py")
    assert plan.ok
    filled = plan.new_contents["m.py"]
    assert "return n * 2" in filled
    assert ">>> double(3)" in filled  # docstring (the contract) kept intact
    assert _doctest_is_green(filled)
    # The scan must not mutate the tree it reports on — the file is restored.
    assert (tmp_path / "m.py").read_text(encoding="utf-8") == _DOUBLE


def test_doctest_only_stub_survives_verified_apply(tmp_path: Path):
    # The full verified-apply engine writes the doctest-verified fill and keeps it
    # (no test regresses), so the body genuinely LANDS on disk — a real
    # contribution, not just a plan.
    (tmp_path / "m.py").write_text(_DOUBLE, encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "m.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=True)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)
    landed = (tmp_path / "m.py").read_text(encoding="utf-8")
    assert "return n * 2" in landed
    assert _doctest_is_green(landed)


def test_scan_and_apply_agree_doctest_only(tmp_path: Path):
    # The whole point of fix 2: the cheap scan and the real apply land the SAME
    # set. The scan says fillable; the apply lands; the synthesized body the apply
    # uses is the one the doctest-verifying synth returns.
    (tmp_path / "m.py").write_text(_DOUBLE, encoding="utf-8")
    stub = _stub(_DOUBLE)
    assert can_fill_stub_in_process(tmp_path, [], stub, _DOUBLE) is True
    assert synthesize_doctest_body(tmp_path, [], stub, _DOUBLE) == "n * 2"
    plan = plan_implement_stub(str(tmp_path), "m.py")
    assert plan.ok and "return n * 2" in plan.new_contents["m.py"]


# --- (b) never-fake-green: a body failing its doctest is NOT landed -----------

def test_body_that_fails_doctest_is_rejected(tmp_path: Path):
    # The doctest verification is the apply gate: a WRONG body (n * 3) does not
    # reproduce the examples, so verify_body_via_doctest refuses it. Only the
    # correct body (n * 2) verifies — the synth never returns an unverified body.
    (tmp_path / "m.py").write_text(_DOUBLE, encoding="utf-8")
    stub = _stub(_DOUBLE)
    assert verify_body_via_doctest(_DOUBLE, stub, "n * 3") is False
    assert verify_body_via_doctest(_DOUBLE, stub, "n * 2") is True


def test_inconsistent_doctests_land_nothing(tmp_path: Path):
    # Examples no single template reproduces (3->100, 5->7) pin NO synthesizable
    # contract: the scan is honest (not fillable) and the apply lands nothing —
    # an under-claim, never a fake-green guess.
    src = (
        "def f(n):\n"
        '    """\n'
        "    >>> f(3)\n"
        "    100\n"
        "    >>> f(5)\n"
        "    7\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    stub = _stub(src)
    assert can_fill_stub_in_process(tmp_path, [], stub, src) is False
    assert synthesize_doctest_body(tmp_path, [], stub, src) is None
    plan = plan_implement_stub(str(tmp_path), "m.py")
    assert not plan.ok
    assert "m.py" not in plan.new_contents


def test_verified_apply_rolls_back_when_impacted_suite_red(tmp_path: Path):
    # never-fake-green at the engine level: even a correctly doctest-verified fill
    # is ROLLED BACK if a co-located, currently-green pytest test regresses. Here a
    # sibling's test is red, importing the module, so the impacted-scope gate fails
    # after the (doctest-correct) fill and the engine restores the stub.
    src = (
        _DOUBLE
        + "def other():\n"
        + "    return 1\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    (tmp_path / "test_other.py").write_text(
        "from m import other\n"
        "def test_other():\n"
        "    assert other() == 999\n",
        encoding="utf-8",
    )
    plan = plan_implement_stub(str(tmp_path), "m.py")
    assert plan.ok  # the doctest fill IS synthesizable+verified
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=True)
    assert result.get("applied") is False
    assert result.get("rolled_back") is True
    # the module is restored to its stub form — nothing fake-green left on disk.
    assert "raise NotImplementedError" in (tmp_path / "m.py").read_text(encoding="utf-8")


# --- (c) a +SKIP example is unenforced and ignored ----------------------------

def test_skip_example_ignored_in_scan_and_verify(tmp_path: Path):
    # The +SKIP example (2 -> 999) disagrees with n * 2; because it is UNENFORCED
    # it is dropped from BOTH witness mining and the doctest verification, so the
    # stub still fills as n * 2 and its enforceable examples stay green.
    src = (
        "def double(n):\n"
        '    """\n'
        "    >>> double(3)\n"
        "    6\n"
        "    >>> double(5)\n"
        "    10\n"
        "    >>> double(2)  # doctest: +SKIP\n"
        "    999\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    stub = _stub(src)
    assert can_fill_stub_in_process(tmp_path, [], stub, src) is True
    assert synthesize_doctest_body(tmp_path, [], stub, src) == "n * 2"
    # verify must skip the +SKIP example too (else n*2 would "fail" on 2 -> 999).
    assert verify_body_via_doctest(src, stub, "n * 2") is True
    plan = plan_implement_stub(str(tmp_path), "m.py")
    assert plan.ok and "return n * 2" in plan.new_contents["m.py"]


def test_only_skip_examples_land_nothing(tmp_path: Path):
    # When EVERY example is +SKIP there is no enforceable contract at all — the
    # scan refuses and the apply lands nothing (an all-skip contract is no
    # contract, like an all-xfail test set).
    src = (
        "def double(n):\n"
        '    """\n'
        "    >>> double(3)  # doctest: +SKIP\n"
        "    6\n"
        "    >>> double(5)  # doctest: +SKIP\n"
        "    10\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    stub = _stub(src)
    assert can_fill_stub_in_process(tmp_path, [], stub, src) is False
    assert verify_body_via_doctest(src, stub, "n * 2") is False  # no enforceable ex.
    assert not plan_implement_stub(str(tmp_path), "m.py").ok


# --- (d) a doctest `want` containing `#` is handled, not truncated ------------

def test_want_with_hash_is_parsed_whole_and_lands(tmp_path: Path):
    # The expected OUTPUT '#red' contains a '#' INSIDE the string repr. The
    # test-file path strips a trailing '# comment'; a doctest want must NOT be —
    # so the witness keeps the whole '#red' and the f-string body fills + verifies.
    src = (
        "def tag(s):\n"
        '    """\n'
        "    >>> tag('red')\n"
        "    '#red'\n"
        "    >>> tag('blue')\n"
        "    '#blue'\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    stub = _stub(src)
    assert can_fill_stub_in_process(tmp_path, [], stub, src) is True
    plan = plan_implement_stub(str(tmp_path), "m.py")
    assert plan.ok
    filled = plan.new_contents["m.py"]
    assert _doctest_is_green(filled)  # tag('red') == '#red' holds
    assert _stub(src)  # sanity: the fixture was a stub to begin with


# --- (e) the no-doctest path is byte-for-byte unchanged (opt-in by source) ----

def test_no_module_source_does_not_fill_doctest_only_stub(tmp_path: Path):
    # With module_source omitted (the default), the doctest pass never runs: a
    # doctest-only stub is NOT fillable, exactly as before this feature.
    (tmp_path / "m.py").write_text(_DOUBLE, encoding="utf-8")
    stub = _stub(_DOUBLE)
    assert can_fill_stub_in_process(tmp_path, [], stub) is False
    assert synthesize_expr_from_witnesses(tmp_path, [], stub) is None
    assert synthesize_doctest_body(tmp_path, [], stub, None) is None


def test_module_with_no_doctests_unaffected(tmp_path: Path):
    # A plain pytest-pinned stub with NO docstring examples lands EXACTLY as before
    # — threading module_source through adds zero witnesses (no `>>>` to mine), so
    # the existing test-file-only behavior is preserved end-to-end.
    src = (
        "def add(a, b):\n"
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    (tmp_path / "test_m.py").write_text(
        "from m import add\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
        "    assert add(4, 1) == 5\n",
        encoding="utf-8",
    )
    plan = plan_implement_stub(str(tmp_path), "m.py")
    assert plan.ok
    assert "return a + b" in plan.new_contents["m.py"]


# --- (f) the >=2-distinct floor still applies to doctest witnesses ------------

def test_single_doctest_example_below_distinct_floor(tmp_path: Path):
    # A LONE example yields ONE witness; competing shapes (n * 2 vs n + 3) both fit
    # it but diverge off-witness, so the ambiguity floor refuses — exactly as a
    # single test-file assert would. Nothing is landed.
    src = (
        "def double(n):\n"
        '    """\n'
        "    >>> double(3)\n"
        "    6\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    stub = _stub(src)
    assert can_fill_stub_in_process(tmp_path, [], stub, src) is False
    assert synthesize_doctest_body(tmp_path, [], stub, src) is None
    assert not plan_implement_stub(str(tmp_path), "m.py").ok


def test_doctest_merges_with_test_file_to_clear_floor(tmp_path: Path):
    # A SINGLE doctest example + a SINGLE test-file assert (distinct args) together
    # clear the >=2-distinct floor and land — doctest witnesses MERGE with
    # test-file ones (more evidence), and the merged stub is fillable.
    src = (
        "def double(n):\n"
        '    """\n'
        "    >>> double(3)\n"
        "    6\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    (tmp_path / "test_m.py").write_text(
        "from m import double\n"
        "def test_x():\n"
        "    assert double(5) == 10\n",
        encoding="utf-8",
    )
    stub = _stub(src)
    assert can_fill_stub_in_process(tmp_path, ["test_m.py"], stub, src) is True
    assert synthesize_doctest_body(tmp_path, ["test_m.py"], stub, src) == "n * 2"
    plan = plan_implement_stub(str(tmp_path), "m.py")
    assert plan.ok and "return n * 2" in plan.new_contents["m.py"]


# --- (g) edge/empty: no docstring, unparseable, method, determinism -----------

def test_method_doctest_stub_not_landed(tmp_path: Path):
    # A method's `self` is not a module global, so its doctest cannot be run by the
    # in-process verifier — it is conservatively NOT counted and NOT landed (no
    # over-count, no fake-green). A bare-name `>>> width(...)` call is not the
    # method's own contract anyway.
    src = (
        "class Box:\n"
        "    def width(self):\n"
        '        """\n'
        "        >>> width(1)\n"
        "        2\n"
        "        >>> width(3)\n"
        "        6\n"
        '        """\n'
        "        raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    stub = _stub(src)
    assert verify_body_via_doctest(src, stub, "2") is False
    plan = plan_implement_stub(str(tmp_path), "m.py")
    assert "m.py" not in plan.new_contents


def test_empty_and_unparseable_sources_yield_no_fill(tmp_path: Path):
    # A stub with NO docstring is not doctest-pinnable; an unparseable module
    # raises nothing and lands nothing — both edge paths are guarded.
    no_doc = "def f(n):\n    raise NotImplementedError\n"
    stub = _stub(no_doc)
    assert verify_body_via_doctest(no_doc, stub, "n * 2") is False
    assert synthesize_doctest_body(tmp_path, [], stub, no_doc) is None
    assert verify_body_via_doctest("def f(:\n  bad", stub, "n * 2") is False


def test_determinism_same_project_same_plan(tmp_path: Path):
    # Same fixtures -> identical landed source every run (no clock/random).
    (tmp_path / "m.py").write_text(_DOUBLE, encoding="utf-8")
    first = plan_implement_stub(str(tmp_path), "m.py").new_contents.get("m.py")
    again = plan_implement_stub(str(tmp_path), "m.py").new_contents.get("m.py")
    assert first is not None
    assert first == again
    assert "return n * 2" in first


# --- (h) doctest + a NON-LITERAL pinned test no longer lose the landing -------
#
# Regression guard for a real over-count + lost-landing bug: BOTH stub passes
# used to SKIP any stub that had a mineable doctest witness ("the doctest pass
# owns it"). But the doctest pass can only synthesize when the COMBINED witnesses
# are literal-evaluable. A stub with (a) a doctest example AND (b) a pinned test
# whose witnesses are NON-literal (a fixture arg / computed expectation) thus fell
# in a hole: the doctest pass declined (non-evaluable) and the pytest pass was
# skipped, so ADDING a correct doctest REMOVED the landing — while the scan still
# over-counted it fillable. The fix lets the pytest pass RUN and DOCTEST-VERIFIES
# its synthesized body before accepting.

# A doctest example (f(2)==4 -> n*2) AND a FIXTURE-arg pinned test (f(val)==6,
# val=3 -> also n*2). The doctest witness alone is below the >=2-distinct floor
# and the fixture witness is non-literal, so the in-process doctest synth declines
# — only the pytest gate can land it, and the doctest-VERIFY must let it through.
_DOCTEST_PLUS_FIXTURE = (
    "def f(n):\n"
    '    """\n'
    "    >>> f(2)\n"
    "    4\n"
    '    """\n'
    "    raise NotImplementedError\n"
)
_FIXTURE_TEST_6 = (
    "import pytest\n"
    "from m import f\n"
    "@pytest.fixture\n"
    "def val():\n"
    "    return 3\n"
    "def test_f(val):\n"
    "    assert f(val) == 6\n"
)


def test_doctest_plus_fixture_test_lands_again(tmp_path: Path):
    # The reviewer's trigger: WITHOUT the docstring this stub lands ``n * 2`` off
    # its fixture test; WITH the docstring the old upfront skip lost the landing.
    # Now the pytest pass runs, doctest-verifies ``n * 2`` (f(2)==4 holds), and the
    # body LANDS — adding a correct doctest no longer removes a contribution.
    (tmp_path / "m.py").write_text(_DOCTEST_PLUS_FIXTURE, encoding="utf-8")
    (tmp_path / "test_mod.py").write_text(_FIXTURE_TEST_6, encoding="utf-8")
    plan = plan_implement_stub(str(tmp_path), "m.py")
    assert plan.ok
    filled = plan.new_contents["m.py"]
    assert "return n * 2" in filled
    assert ">>> f(2)" in filled  # docstring (the contract) kept intact
    # The landed body satisfies BOTH contracts: its own doctest AND the fixture
    # pytest assert (f(3) == 6) — scan==apply, never-fake-green.
    assert _doctest_is_green(filled)
    module = types.ModuleType("apex_h_mod")
    exec(compile(filled, "apex_h_mod.py", "exec"), module.__dict__)  # noqa: S102
    assert module.f(3) == 6


def test_doctest_plus_fixture_survives_verified_apply(tmp_path: Path):
    # scan==apply end-to-end: the doctest-pinned stub the scan reports fillable is
    # the one the verified-apply engine actually lands and keeps (the fixture test
    # is green for n*2, so no rollback).
    (tmp_path / "m.py").write_text(_DOCTEST_PLUS_FIXTURE, encoding="utf-8")
    (tmp_path / "test_mod.py").write_text(_FIXTURE_TEST_6, encoding="utf-8")
    stub = _stub(_DOCTEST_PLUS_FIXTURE)
    # the scan offered it (it formerly over-counted, but now the apply backs it up)
    assert can_fill_stub_in_process(tmp_path, ["test_mod.py"], stub,
                                    _DOCTEST_PLUS_FIXTURE) is True
    plan = plan_implement_stub(str(tmp_path), "m.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=True)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)
    landed = (tmp_path / "m.py").read_text(encoding="utf-8")
    assert "return n * 2" in landed
    assert _doctest_is_green(landed)


# --- (i) never-fake-green: a pytest-passing, doctest-VIOLATING body is refused -

def test_pytest_passing_doctest_violating_body_is_refused(tmp_path: Path):
    # The fake-green hole the old upfront skip protected, kept closed by the new
    # doctest-verify. The doctest demands n*2 (f(2)==4, f(5)==10), but the pinned
    # test asserts only f(0)==0 — which the FIRST fixed-order candidate (the
    # passthrough ``return n``) also satisfies. The pytest gate alone would land
    # ``return n``; that VIOLATES the doctest, so the doctest-verify refuses it and
    # nothing lands (an honest under-claim, never a body the examples reject).
    src = (
        "def f(n):\n"
        '    """\n'
        "    >>> f(2)\n"
        "    4\n"
        "    >>> f(5)\n"
        "    10\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    (tmp_path / "test_mod.py").write_text(
        "import pytest\n"
        "from m import f\n"
        "@pytest.fixture\n"
        "def zero():\n"
        "    return 0\n"
        "def test_f(zero):\n"
        "    assert f(zero) == 0\n",
        encoding="utf-8",
    )
    plan = plan_implement_stub(str(tmp_path), "m.py")
    assert not plan.ok
    assert "m.py" not in plan.new_contents
    # The guard that does the refusing: the doctest-violating filled source fails,
    # while the doctest-satisfying one passes (so a satisfying body WOULD land).
    stub = _stub(src)
    violating = src.replace("    raise NotImplementedError\n", "    return n\n")
    satisfying = src.replace("    raise NotImplementedError\n", "    return n * 2\n")
    assert filled_source_passes_doctests(violating, stub) is False
    assert filled_source_passes_doctests(satisfying, stub) is True


def test_doctest_satisfying_body_that_also_passes_pytest_lands(tmp_path: Path):
    # The LANDS half of never-fake-green: when the pytest gate's first passing
    # candidate ALSO satisfies the doctest, it lands. Here f(3)==6 forces n*2 (the
    # passthrough/`n*0` candidates fail f(3)==6 first), and n*2 satisfies the two
    # doctest examples too — both contracts hold, so the body lands.
    src = (
        "def f(n):\n"
        '    """\n'
        "    >>> f(2)\n"
        "    4\n"
        "    >>> f(5)\n"
        "    10\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    (tmp_path / "test_mod.py").write_text(
        "import pytest\n"
        "from m import f\n"
        "@pytest.fixture\n"
        "def three():\n"
        "    return 3\n"
        "def test_f(three):\n"
        "    assert f(three) == 6\n",
        encoding="utf-8",
    )
    plan = plan_implement_stub(str(tmp_path), "m.py")
    assert plan.ok
    assert "return n * 2" in plan.new_contents["m.py"]
    assert _doctest_is_green(plan.new_contents["m.py"])


# --- (j) the pure-doctest-only path (no test file) still lands exactly as-is --

def test_pure_doctest_only_path_still_lands(tmp_path: Path):
    # The fix must not disturb the doctest-ONLY pathway: a stub pinned solely by
    # >=2 distinct doctest examples (no test file at all) still lands through the
    # doctest pass, doctest-green, byte-for-byte as the worktree had it.
    (tmp_path / "m.py").write_text(_DOUBLE, encoding="utf-8")
    stub = _stub(_DOUBLE)
    assert can_fill_stub_in_process(tmp_path, [], stub, _DOUBLE) is True
    assert synthesize_doctest_body(tmp_path, [], stub, _DOUBLE) == "n * 2"
    plan = plan_implement_stub(str(tmp_path), "m.py")
    assert plan.ok
    filled = plan.new_contents["m.py"]
    assert "return n * 2" in filled
    assert _doctest_is_green(filled)


def test_filled_source_passes_doctests_edge_paths(tmp_path: Path):
    # The new helper's empty/edge guards: no enforceable example -> False, a
    # non-compiling filled source -> False, a method (self not a module global) ->
    # False — all conservative, never a fake-green.
    no_doc_filled = "def f(n):\n    return n * 2\n"
    stub = _stub("def f(n):\n    raise NotImplementedError\n")
    assert filled_source_passes_doctests(no_doc_filled, stub) is False  # no example
    assert filled_source_passes_doctests("def f(:\n  bad", stub) is False  # broken
    method_src = (
        "class Box:\n"
        "    def width(self):\n"
        '        """\n'
        "        >>> width(1)\n"
        "        2\n"
        "        >>> width(3)\n"
        "        6\n"
        '        """\n'
        "        raise NotImplementedError\n"
    )
    method_stub = _stub(method_src)
    method_filled = method_src.replace(
        "        raise NotImplementedError\n", "        return self * 2\n")
    # `width` is not a module global in the filled source -> conservatively False.
    assert filled_source_passes_doctests(method_filled, method_stub) is False


def test_comparison_style_doctest_is_enforced_no_fake_green(tmp_path: Path):
    # NEVER-FAKE-GREEN regression (the gate TRIGGER must match its VERIFIER): an
    # ENFORCEABLE but NON-witness example — the very common assertion idiom
    # `>>> f(2) == 4` (a Compare, not a mined literal `f(...)` call) — must still be
    # enforced. The pinned fixture test asserts only f(0)==0, which the passthrough
    # `return n` satisfies; but `return n` makes `f(2) == 4` evaluate False. The old
    # trigger (`_has_doctest_witnesses`) was False here (no mined witness), so the
    # doctest gate short-circuited and `return n` LANDED doctest-RED — a fake-green.
    # Triggering on `has_enforceable_doctest_examples` closes the hole.
    src = (
        "def f(n):\n"
        '    """\n'
        "    >>> f(2) == 4\n"
        "    True\n"
        '    """\n'
        "    raise NotImplementedError\n"
    )
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    (tmp_path / "test_mod.py").write_text(
        "import pytest\n"
        "from m import f\n"
        "@pytest.fixture\n"
        "def zero():\n"
        "    return 0\n"
        "def test_f(zero):\n"
        "    assert f(zero) == 0\n",
        encoding="utf-8",
    )
    plan = plan_implement_stub(str(tmp_path), "m.py")
    # Whatever lands (if anything) must satisfy the enforceable example — NEVER a
    # doctest-violating body. Before the fix `return n` landed (doctest RED).
    landed = plan.new_contents.get("m.py")
    if landed is not None:
        assert "return n\n" not in landed  # the fake-green body must not land
        assert _doctest_is_green(landed)
    # The trigger predicate itself now sees this enforceable comparison example.
    assert has_enforceable_doctest_examples(src, _stub(src)) is True
    # And the verifier correctly rejects the passthrough that violates it.
    violating = src.replace("    raise NotImplementedError\n", "    return n\n")
    assert filled_source_passes_doctests(violating, _stub(src)) is False
