"""Mutation testing — a deterministic test-strength fitness signal.

These tests build tiny synthetic projects in ``tmp_path`` (one module + one
test file each) so the per-mutant pytest runs stay fast, and exercise the
strong/weak/empty/cap/determinism/safety paths plus the CLI command.
"""

from __future__ import annotations

import argparse
import ast

from app.cli_insight import cmd_mutants
from app.engine.mutation_tester import (
    Mutant,
    MutationResult,
    _collect_sites,
    covering_test_files,
    mutation_score,
    render_mutation_markdown,
)
from app.engine.mutation_tester import (
    test_strength_grade as _test_strength_grade,
)

# --- tiny synthetic project scaffolding -----------------------------------

_MODULE_SRC = '''\
def is_equal(a, b):
    return a == b
'''


def _write_project(root, module_src, test_src, module_rel="mod.py"):
    """Lay down a minimal pytest project: one module + one test."""
    (root / module_rel).write_text(module_src, encoding="utf-8")
    (root / "test_mod.py").write_text(test_src, encoding="utf-8")
    return module_rel


# --- site enumeration (pure, fast) ----------------------------------------

def test_collect_sites_covers_all_operator_families():
    src = (
        "def f(a, b):\n"
        "    return a == b and a + b > 0 or True\n"
    )
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    ops = [s.operator for s in sites]
    assert "comparison:==>!=" in ops
    assert "arithmetic:+>-" in ops
    assert "comparison:>><=" in ops
    assert "boolean:and>or" in ops
    assert "boolean:or>and" in ops
    assert "constant:True>False" in ops


def test_collect_sites_covers_new_operator_families():
    src = (
        "def f(x):\n"
        "    x += 1\n"
        "    return x + 1\n"
    )
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    ops = [s.operator for s in sites]
    assert "augassign:+=>-=" in ops
    assert "number:1>2" in ops
    assert "return:value>None" in ops


def test_collect_sites_covers_membership_operators():
    # ``in`` / ``not in`` membership flips are seeded as comparison sites.
    src = (
        "def f(x, allowed, banned):\n"
        "    return x in allowed and x not in banned\n"
    )
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    ops = [s.operator for s in sites]
    assert "comparison:in>not in" in ops
    assert "comparison:not in>in" in ops


def test_collect_sites_membership_splices_exactly():
    # The located span maps to a precise, re-parseable mutant for both
    # directions, leaving the rest of the line byte-for-byte intact.
    from app.engine.mutation_tester import _splice
    src = "ok = x in allowed\n"
    lines = src.splitlines(keepends=True)
    sites = [s for s in _collect_sites(ast.parse(src), lines)
             if s.operator.startswith("comparison:in")]
    assert len(sites) == 1
    assert _splice(lines, sites[0]) == "ok = x not in allowed\n"

    src2 = "ok = x not in banned\n"
    lines2 = src2.splitlines(keepends=True)
    sites2 = [s for s in _collect_sites(ast.parse(src2), lines2)
              if s.operator == "comparison:not in>in"]
    assert len(sites2) == 1
    assert _splice(lines2, sites2[0]) == "ok = x in banned\n"


def test_collect_sites_membership_ignores_in_inside_identifier():
    # An ``in`` substring inside an identifier (``points``) must not be mutated
    # — only the real membership operator token in the operator gap is found.
    src = "ok = x in points\n"
    lines = src.splitlines(keepends=True)
    sites = [s for s in _collect_sites(ast.parse(src), lines)
             if s.operator.startswith("comparison:in")]
    assert len(sites) == 1
    assert sites[0].original == "in"
    assert sites[0].col == 7 and sites[0].end_col == 9


def test_collect_sites_covers_boundary_operators():
    # Relational boundary flips (``<`` <-> ``<=`` etc.) are seeded ALONGSIDE the
    # negation comparison flips for the same token, each with its own label.
    src = (
        "def f(x, n):\n"
        "    return x < n and n >= 0\n"
    )
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    ops = [s.operator for s in sites]
    # Boundary (off-by-one) flips.
    assert "boundary:<><=" in ops
    assert "boundary:>=>>" in ops
    # The existing negation flips for the same tokens still appear too.
    assert "comparison:<>>=" in ops
    assert "comparison:>=><" in ops


def test_collect_sites_boundary_splices_exactly():
    # Each boundary direction yields a precise, re-parseable mutant, leaving the
    # rest of the line byte-for-byte intact.
    from app.engine.mutation_tester import _splice
    cases = {
        "ok = a < b\n": ("boundary:<><=", "ok = a <= b\n"),
        "ok = a <= b\n": ("boundary:<=><", "ok = a < b\n"),
        "ok = a > b\n": ("boundary:>>>=", "ok = a >= b\n"),
        "ok = a >= b\n": ("boundary:>=>>", "ok = a > b\n"),
    }
    for src, (op, expected) in cases.items():
        lines = src.splitlines(keepends=True)
        sites = [s for s in _collect_sites(ast.parse(src), lines)
                 if s.operator == op]
        assert len(sites) == 1, (src, op)
        assert _splice(lines, sites[0]) == expected


def test_collect_sites_boundary_and_negation_distinct_sites():
    # The same ``<`` token must produce TWO distinct sites (boundary + negation)
    # with different mutated text — proving they never collide.
    src = "ok = a < b\n"
    lines = src.splitlines(keepends=True)
    sites = [s for s in _collect_sites(ast.parse(src), lines)
             if s.original == "<"]
    by_op = {s.operator: s.mutated for s in sites}
    assert by_op == {"boundary:<><=": "<=", "comparison:<>>=": ">="}


def test_collect_sites_number_mutates_to_n_plus_one():
    src = "x = 41\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    num = [s for s in sites if s.operator.startswith("number:")]
    assert len(num) == 1
    assert num[0].original == "41" and num[0].mutated == "42"


def test_collect_sites_float_number_mutates_in_kind():
    src = "x = 1.5\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    num = [s for s in sites if s.operator.startswith("number:")]
    assert len(num) == 1
    assert num[0].original == "1.5" and num[0].mutated == "2.5"


def test_collect_sites_skips_bool_for_number_operator():
    # ``True`` is a constant but a bool — it must stay a boolean-constant flip,
    # never a number flip.
    src = "x = True\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    ops = [s.operator for s in sites]
    assert "constant:True>False" in ops
    assert not any(o.startswith("number:") for o in ops)


def test_collect_sites_return_none_has_no_return_mutant():
    # A bare ``return None`` (and ``return`` with no value) is excluded.
    src = (
        "def f():\n"
        "    return None\n"
        "def g():\n"
        "    return\n"
    )
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    assert not any(s.operator == "return:value>None" for s in sites)


def test_collect_sites_skips_multiline_return():
    src = (
        "def f(a, b):\n"
        "    return (a +\n"
        "            b)\n"
    )
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    assert not any(s.operator == "return:value>None" for s in sites)


def test_collect_sites_is_deterministic_document_order():
    src = "x = (1 < 2) and (3 > 4)\n"
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    keys = [(s.line, s.col) for s in sites]
    assert keys == sorted(keys)


def test_collect_sites_skips_multiline_compares():
    src = (
        "def f(a, b):\n"
        "    return (a\n"
        "            == b)\n"
    )
    # The Compare node spans two lines, so it must not be mutated (the splice
    # would not be exact). No single-line mutable site here.
    sites = _collect_sites(ast.parse(src), src.splitlines(keepends=True))
    assert sites == []


# A representative source exercising EVERY mutation family at once, plus the
# overlap cases (boundary + negation on the same relational token, chained
# compares, both membership directions, an ``in`` inside an identifier that must
# NOT be mutated, int + float literals, augmented-assigns, bool constants, and a
# return-value flip). Used as a CHARACTERIZATION pin: the exact ordered set of
# collected sites is frozen here so the ``_collect_sites`` refactor (extraction
# into per-kind helpers + guard clauses) is proven byte-identical.
_CHARACTERIZATION_SRC = (
    "def f(a, b, c, x, n, allowed, banned):\n"
    "    total = 0\n"
    "    total += 1\n"
    "    total -= 2\n"
    "    total *= 3\n"
    "    flag = a == b and b != c or a < n\n"
    "    chained = a < b < c\n"
    "    rel = n >= 0 and n <= 10 and x > 5 and x < 7\n"
    "    mem = x in allowed and x not in banned\n"
    "    ident = x in points if False else True\n"
    "    num = 41\n"
    "    fl = 1.5\n"
    "    big = a + b - c * x\n"
    "    iden = a is b and a is not c\n"
    "    return total + x\n"
)

# The frozen (line, col, end_col, operator, original, mutated) tuple for every
# site, in the exact order ``_collect_sites`` returns them (document order:
# line, col, operator). Any drift in kinds, locations, labels, or ordering trips
# this immediately.
_CHARACTERIZATION_SITES = [
    (2, 12, 13, "number:0>1", "0", "1"),
    (3, 10, 11, "augassign:+=>-=", "+", "-"),
    (3, 13, 14, "number:1>2", "1", "2"),
    (4, 10, 11, "augassign:-=>+=", "-", "+"),
    (4, 13, 14, "number:2>3", "2", "3"),
    (5, 10, 11, "augassign:*=>/=", "*", "/"),
    (5, 13, 14, "number:3>4", "3", "4"),
    (6, 13, 15, "comparison:==>!=", "==", "!="),
    (6, 18, 21, "boolean:and>or", "and", "or"),
    (6, 24, 26, "comparison:!=>==", "!=", "=="),
    (6, 29, 31, "boolean:or>and", "or", "and"),
    (6, 34, 35, "boundary:<><=", "<", "<="),
    (6, 34, 35, "comparison:<>>=", "<", ">="),
    (7, 16, 17, "boundary:<><=", "<", "<="),
    (7, 16, 17, "comparison:<>>=", "<", ">="),
    (7, 20, 21, "boundary:<><=", "<", "<="),
    (7, 20, 21, "comparison:<>>=", "<", ">="),
    (8, 12, 14, "boundary:>=>>", ">=", ">"),
    (8, 12, 14, "comparison:>=><", ">=", "<"),
    (8, 15, 16, "number:0>1", "0", "1"),
    (8, 17, 20, "boolean:and>or", "and", "or"),
    (8, 23, 25, "boundary:<=><", "<=", "<"),
    (8, 23, 25, "comparison:<=>>", "<=", ">"),
    (8, 26, 28, "number:10>11", "10", "11"),
    (8, 29, 32, "boolean:and>or", "and", "or"),
    (8, 35, 36, "boundary:>>>=", ">", ">="),
    (8, 35, 36, "comparison:>><=", ">", "<="),
    (8, 37, 38, "number:5>6", "5", "6"),
    (8, 39, 42, "boolean:and>or", "and", "or"),
    (8, 45, 46, "boundary:<><=", "<", "<="),
    (8, 45, 46, "comparison:<>>=", "<", ">="),
    (8, 47, 48, "number:7>8", "7", "8"),
    (9, 12, 14, "comparison:in>not in", "in", "not in"),
    (9, 23, 26, "boolean:and>or", "and", "or"),
    (9, 29, 35, "comparison:not in>in", "not in", "in"),
    (10, 14, 16, "comparison:in>not in", "in", "not in"),
    (10, 27, 32, "constant:False>True", "False", "True"),
    (10, 38, 42, "constant:True>False", "True", "False"),
    (11, 10, 12, "number:41>42", "41", "42"),
    (12, 9, 12, "number:1.5>2.5", "1.5", "2.5"),
    (13, 12, 13, "arithmetic:+>-", "+", "-"),
    (13, 16, 17, "arithmetic:->+", "-", "+"),
    (13, 20, 21, "arithmetic:*>/", "*", "/"),
    (14, 13, 15, "comparison:is>is not", "is", "is not"),
    (14, 18, 21, "boolean:and>or", "and", "or"),
    (14, 24, 30, "comparison:is not>is", "is not", "is"),
    (15, 11, 20, "return:value>None", "total + x", "None"),
    (15, 17, 18, "arithmetic:+>-", "+", "-"),
]


def test_collect_sites_characterization_pins_full_site_set():
    # CHARACTERIZATION: the complete ordered tuple of collected sites is frozen
    # so the helper-extraction refactor is provably output byte-identical (same
    # kinds, locations, labels, order). This is the contract the refactor must
    # not break.
    lines = _CHARACTERIZATION_SRC.splitlines(keepends=True)
    sites = _collect_sites(ast.parse(_CHARACTERIZATION_SRC), lines)
    actual = [
        (s.line, s.col, s.end_col, s.operator, s.original, s.mutated)
        for s in sites
    ]
    assert actual == _CHARACTERIZATION_SITES


def test_collect_sites_characterization_every_site_splices_exactly():
    # Each pinned site must round-trip: the located span carries exactly its
    # ``original`` text, so the splice is byte-exact. (``_splice`` returns None
    # only on a malformed/non-reparseable result — every pinned site re-parses.)
    from app.engine.mutation_tester import _splice
    lines = _CHARACTERIZATION_SRC.splitlines(keepends=True)
    sites = _collect_sites(ast.parse(_CHARACTERIZATION_SRC), lines)
    for s in sites:
        assert lines[s.line - 1][s.col:s.end_col] == s.original, s.operator
        assert _splice(lines, s) is not None, s.operator


def test_collect_sites_characterization_is_deterministic():
    # Two independent walks of the same source yield byte-identical site tuples
    # (no randomness, fixed operator + document order).
    lines = _CHARACTERIZATION_SRC.splitlines(keepends=True)
    a = _collect_sites(ast.parse(_CHARACTERIZATION_SRC), lines)
    b = _collect_sites(ast.parse(_CHARACTERIZATION_SRC), lines)

    def _to_tuples(ss):
        return [
            (s.line, s.col, s.end_col, s.operator, s.original, s.mutated)
            for s in ss
        ]

    assert _to_tuples(a) == _to_tuples(b)


# --- end-to-end scoring ---------------------------------------------------

def test_strong_suite_kills_comparison_mutant(tmp_path):
    # A suite that pins exact return values catches the == -> != flip.
    test_src = (
        "from mod import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    # ``return a == b`` now seeds both a comparison flip and a return-value
    # flip; the strong suite (exact True/False) kills every one of them.
    assert result.total >= 1
    assert result.killed == result.total
    assert result.survived == 0
    assert result.score == 1.0
    assert result.survivors == []
    ops = {m.operator for m in result.survivors}
    assert ops == set()


def test_weak_suite_lets_mutant_survive(tmp_path):
    # A suite that only checks "not None" never observes the flipped operator,
    # so the comparison mutant survives. (The return-value flip turns the
    # result into ``None`` and IS caught by the ``is not None`` assertion.)
    test_src = (
        "from mod import is_equal\n"
        "def test_smoke():\n"
        "    assert is_equal(1, 1) is not None\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    assert result.total >= 1
    assert result.survived >= 1
    survivor_ops = {m.operator for m in result.survivors}
    assert "comparison:==>!=" in survivor_ops
    comp = next(m for m in result.survivors if m.operator == "comparison:==>!=")
    assert comp.line == 2


_NUM_MODULE_SRC = '''\
def add_one(x):
    return x + 1
'''


def test_number_mutant_killed_by_strong_test(tmp_path):
    # A strong test pins the exact value, so ``1 -> 2`` is caught. (The
    # arithmetic ``+ -> -`` and return-value flips are caught too.)
    test_src = (
        "from mod import add_one\n"
        "def test_add():\n"
        "    assert add_one(1) == 2\n"
    )
    rel = _write_project(tmp_path, _NUM_MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    ops = {m.operator for m in (result.survivors)}
    # No survivor carries the number flip: the strong test killed it.
    assert "number:1>2" not in ops
    killed_ops = {m.operator for m in _mutants_of(result, str(tmp_path), rel)}
    assert "number:1>2" in killed_ops
    assert result.score == 1.0


def test_number_mutant_survives_weak_test(tmp_path):
    # A weak ``is not None`` test never observes the changed number value.
    test_src = (
        "from mod import add_one\n"
        "def test_add():\n"
        "    assert add_one(1) is not None\n"
    )
    rel = _write_project(tmp_path, _NUM_MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    survivor_ops = {m.operator for m in result.survivors}
    assert "number:1>2" in survivor_ops


def test_return_value_mutant_killed_by_value_test(tmp_path):
    module_src = (
        "def make():\n"
        "    return 7\n"
        "def use():\n"
        "    return make()\n"
    )
    test_src = (
        "from mod import use\n"
        "def test_use():\n"
        "    assert use() == 7\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=20)
    # ``return make()`` -> ``return None`` is a seeded fault the value test kills.
    all_ops = {m.operator for m in _mutants_of(result, str(tmp_path), rel)}
    assert "return:value>None" in all_ops
    assert not any(m.operator == "return:value>None" for m in result.survivors)


def test_augmented_assign_mutant_generated(tmp_path):
    module_src = (
        "def accumulate(n):\n"
        "    total = 0\n"
        "    total += n\n"
        "    return total\n"
    )
    test_src = (
        "from mod import accumulate\n"
        "def test_acc():\n"
        "    assert accumulate(3) == 3\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=20)
    all_ops = {m.operator for m in _mutants_of(result, str(tmp_path), rel)}
    assert "augassign:+=>-=" in all_ops
    # The strong test (3 != -3) kills the ``+= -> -=`` flip.
    assert not any(m.operator == "augassign:+=>-=" for m in result.survivors)


_MEMBER_MODULE_SRC = '''\
def is_allowed(x, allowed):
    return x in allowed
'''


def test_membership_mutant_killed_by_strong_test(tmp_path):
    # A suite that pins both an in-set and an out-of-set case catches the
    # ``in -> not in`` flip.
    test_src = (
        "from mod import is_allowed\n"
        "def test_member():\n"
        "    assert is_allowed(1, [1, 2]) is True\n"
        "    assert is_allowed(9, [1, 2]) is False\n"
    )
    rel = _write_project(tmp_path, _MEMBER_MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    all_ops = {m.operator for m in _mutants_of(result, str(tmp_path), rel)}
    assert "comparison:in>not in" in all_ops
    assert not any(m.operator == "comparison:in>not in" for m in result.survivors)


def test_membership_mutant_survives_weak_test(tmp_path):
    # A suite that only checks the in-set case never observes the inverted
    # membership test, so the ``in -> not in`` mutant survives. The assertion
    # only checks the result is a bool (truthy/``is not None``), which holds for
    # both ``in`` and ``not in``, so the flip is never observed.
    test_src = (
        "from mod import is_allowed\n"
        "def test_member():\n"
        "    assert is_allowed(1, [1, 2]) is not None\n"
    )
    rel = _write_project(tmp_path, _MEMBER_MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    survivor_ops = {m.operator for m in result.survivors}
    assert "comparison:in>not in" in survivor_ops


def test_membership_determinism_two_runs_identical(tmp_path):
    # A module exercising both membership directions must produce
    # byte-identical results across two runs.
    module_src = (
        "def gate(x, allowed, banned):\n"
        "    return x in allowed and x not in banned\n"
    )
    test_src = (
        "from mod import gate\n"
        "def test_gate():\n"
        "    assert gate(1, [1], [2]) is True\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    a = mutation_score(str(tmp_path), rel, max_mutants=20).to_dict()
    b = mutation_score(str(tmp_path), rel, max_mutants=20).to_dict()
    assert a == b


_BOUNDARY_MODULE_SRC = '''\
def below(x):
    return x < 10
'''


def test_boundary_mutant_killed_by_edge_test(tmp_path):
    # A suite that pins the BOUNDARY value (x == 10) catches the ``< -> <=``
    # off-by-one flip: under the mutant ``below(10)`` flips from False to True.
    test_src = (
        "from mod import below\n"
        "def test_edge():\n"
        "    assert below(9) is True\n"
        "    assert below(10) is False\n"
    )
    rel = _write_project(tmp_path, _BOUNDARY_MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    all_ops = {m.operator for m in _mutants_of(result, str(tmp_path), rel)}
    assert "boundary:<><=" in all_ops
    assert not any(m.operator == "boundary:<><=" for m in result.survivors)


def test_boundary_mutant_survives_off_by_one_blind_test(tmp_path):
    # A suite that never probes the boundary value (only x=5, x=20) is blind to
    # ``< -> <=``: both operators agree away from the edge, so the mutant
    # survives — exactly the off-by-one gap this operator is designed to expose.
    test_src = (
        "from mod import below\n"
        "def test_blind():\n"
        "    assert below(5) is True\n"
        "    assert below(20) is False\n"
    )
    rel = _write_project(tmp_path, _BOUNDARY_MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    survivor_ops = {m.operator for m in result.survivors}
    assert "boundary:<><=" in survivor_ops


def test_boundary_determinism_two_runs_identical(tmp_path):
    # A module exercising several relational boundaries must produce
    # byte-identical results across two runs (fixed operator + document order).
    module_src = (
        "def gate(x, y):\n"
        "    return x < 10 and y >= 0 or x <= 5 and y > 1\n"
    )
    test_src = (
        "from mod import gate\n"
        "def test_gate():\n"
        "    assert gate(1, 0) is True\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    a = mutation_score(str(tmp_path), rel, max_mutants=30).to_dict()
    b = mutation_score(str(tmp_path), rel, max_mutants=30).to_dict()
    assert a == b


def _mutants_of(result, root, rel):
    """All mutants (killed + survived) re-derived from the source for assertion
    on which operators were SEEDED, independent of kill/survive outcome."""
    import ast as _ast

    from app.engine.mutation_tester import _collect_sites
    from pathlib import Path as _Path

    src = (_Path(root) / rel).read_text(encoding="utf-8")
    sites = _collect_sites(_ast.parse(src), src.splitlines(keepends=True))

    class _M:
        def __init__(self, op):
            self.operator = op

    return [_M(s.operator) for s in sites]


def test_no_mutable_sites_returns_empty_result(tmp_path):
    # A module with NO mutable sites: no operators, no numeric/return-value
    # constants. ``return x`` would now seed a return-value mutant, and a bare
    # ``return None`` is excluded, so we use a function whose body is ``pass``.
    module_src = (
        "def noop(x):\n"
        "    pass\n"
    )
    test_src = (
        "from mod import noop\n"
        "def test_pt():\n"
        "    assert noop(5) is None\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    assert result.total == 0
    assert result.killed == 0
    assert result.survived == 0
    assert result.score == 0.0
    assert result.survivors == []


def test_syntax_error_module_returns_empty_result(tmp_path):
    (tmp_path / "broken.py").write_text("def f(:\n    pass\n", encoding="utf-8")
    result = mutation_score(str(tmp_path), "broken.py")
    assert result.total == 0
    assert result.score == 0.0


def test_missing_module_returns_empty_result(tmp_path):
    result = mutation_score(str(tmp_path), "does_not_exist.py")
    assert result.total == 0
    assert result.score == 0.0


def test_max_mutants_caps_the_count(tmp_path):
    module_src = (
        "def classify(a, b, c):\n"
        "    return a == b and b == c and a == c\n"
    )
    test_src = (
        "from mod import classify\n"
        "def test_c():\n"
        "    assert classify(1, 1, 1) is True\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    # There are >1 mutable sites; cap to 1.
    result = mutation_score(str(tmp_path), rel, max_mutants=1)
    assert result.total == 1


def test_determinism_two_runs_identical(tmp_path):
    test_src = (
        "from mod import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    a = mutation_score(str(tmp_path), rel, max_mutants=10).to_dict()
    b = mutation_score(str(tmp_path), rel, max_mutants=10).to_dict()
    assert a == b


def test_determinism_two_runs_identical_new_operators(tmp_path):
    # A module exercising number / return-value / augmented-assign operators
    # must produce byte-identical results across two runs.
    module_src = (
        "def step(x):\n"
        "    total = 0\n"
        "    total += 1\n"
        "    return total + x\n"
    )
    test_src = (
        "from mod import step\n"
        "def test_step():\n"
        "    assert step(2) == 3\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    a = mutation_score(str(tmp_path), rel, max_mutants=20).to_dict()
    b = mutation_score(str(tmp_path), rel, max_mutants=20).to_dict()
    assert a == b


def test_augassign_splice_keeps_equals_token():
    # The augmented-assign flip mutates only the operator char, leaving ``=``.
    from app.engine.mutation_tester import _Site, _splice
    src = "x += 1\n"
    lines = src.splitlines(keepends=True)
    site = _Site(line=1, col=2, end_col=3, operator="augassign:+=>-=",
                 original="+", mutated="-")
    mutated = _splice(lines, site)
    assert mutated == "x -= 1\n"


def test_original_file_unchanged_after_run(tmp_path):
    # Safety: the real tree is read-only; mutation happens only in copies.
    test_src = (
        "from mod import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    before = (tmp_path / rel).read_text(encoding="utf-8")
    mutation_score(str(tmp_path), rel, max_mutants=10)
    after = (tmp_path / rel).read_text(encoding="utf-8")
    assert after == before == _MODULE_SRC


def test_to_dict_round_trips_fields():
    m = Mutant(module="mod.py", line=2, operator="comparison:==>!=",
               original="==", mutated="!=", killed=True)
    res = MutationResult(module="mod.py", total=1, killed=1, survived=0,
                         score=1.0, survivors=[], scoped_tests=["tests/test_mod.py"])
    assert m.to_dict()["killed"] is True
    d = res.to_dict()
    assert d["module"] == "mod.py" and d["score"] == 1.0 and d["survivors"] == []
    assert d["scoped_tests"] == ["tests/test_mod.py"]


# --- test scoping (deterministic, coverage-free) --------------------------

def _write_pkg_module(root, src):
    """Lay down an ``app/foo.py`` package module for the scoping tests."""
    pkg = root / "app"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "foo.py").write_text(src, encoding="utf-8")
    return "app/foo.py"


def test_covering_test_files_finds_from_import(tmp_path):
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text(
        "from app.foo import is_equal\n"
        "def test_eq():\n    assert is_equal(1, 1) is True\n",
        encoding="utf-8",
    )
    # An unrelated test that imports something else must be ignored.
    (tests / "test_other.py").write_text(
        "import os\ndef test_o():\n    assert os.sep\n", encoding="utf-8",
    )
    covering = covering_test_files(str(tmp_path), rel)
    assert covering == ["tests/test_foo.py"]


def test_covering_test_files_handles_import_forms(tmp_path):
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    # `import app.foo`
    (tests / "test_a.py").write_text(
        "import app.foo\ndef test_a():\n    assert app.foo.is_equal(1, 1)\n",
        encoding="utf-8",
    )
    # `from app import foo` (parent package + member)
    (tests / "test_b.py").write_text(
        "from app import foo\ndef test_b():\n    assert foo.is_equal(1, 1)\n",
        encoding="utf-8",
    )
    # `from app.foo import is_equal`
    (tests / "test_c.py").write_text(
        "from app.foo import is_equal\ndef test_c():\n    assert is_equal(1, 1)\n",
        encoding="utf-8",
    )
    covering = covering_test_files(str(tmp_path), rel)
    assert covering == ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]


def test_covering_test_files_skips_parse_errors(tmp_path):
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text(
        "from app.foo import is_equal\ndef test_ok():\n    assert is_equal(1, 1)\n",
        encoding="utf-8",
    )
    # A syntactically broken test file must be skipped, not crash the scan.
    (tests / "test_broken.py").write_text(
        "from app.foo import is_equal\ndef test_x(:\n    pass\n", encoding="utf-8",
    )
    covering = covering_test_files(str(tmp_path), rel)
    assert covering == ["tests/test_ok.py"]


def test_covering_test_files_empty_when_unrelated(tmp_path):
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_other.py").write_text(
        "import os\ndef test_o():\n    assert os.sep\n", encoding="utf-8",
    )
    assert covering_test_files(str(tmp_path), rel) == []


def test_scoped_run_uses_only_covering_tests(tmp_path):
    # Strong covering test kills the mutant; an unrelated test that would CRASH
    # if executed proves only the covering test was actually run.
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text(
        "from app.foo import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n",
        encoding="utf-8",
    )
    # This unrelated test does NOT import app.foo and would fail loudly if run.
    (tests / "test_poison.py").write_text(
        "def test_poison():\n    assert False, 'should not run'\n",
        encoding="utf-8",
    )
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    assert result.total >= 1
    assert result.killed == result.total
    assert result.score == 1.0
    assert result.scoped_tests == ["tests/test_foo.py"]


def test_scoped_run_no_covering_test_falls_back(tmp_path):
    # No test imports the module -> scope is empty -> fall back to full suite.
    # The full suite here has a weak test that doesn't import the module, so the
    # mutant survives, and scoped_tests is empty to record the fallback.
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_unrelated.py").write_text(
        "def test_u():\n    assert 1 == 1\n", encoding="utf-8",
    )
    result = mutation_score(str(tmp_path), rel, max_mutants=10)
    assert result.total >= 1
    assert result.survived == result.total
    assert result.score == 0.0
    assert result.scoped_tests == []


def test_scope_tests_false_reproduces_full_suite(tmp_path):
    # With scoping off, the original full-suite path runs; scoped_tests stays
    # empty and a strong root-level test still kills the mutant.
    test_src = (
        "from mod import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    result = mutation_score(str(tmp_path), rel, max_mutants=10, scope_tests=False)
    assert result.total >= 1
    assert result.killed == result.total
    assert result.score == 1.0
    assert result.scoped_tests == []


def test_scoped_determinism_two_runs_identical(tmp_path):
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text(
        "from app.foo import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n",
        encoding="utf-8",
    )
    a = mutation_score(str(tmp_path), rel, max_mutants=10).to_dict()
    b = mutation_score(str(tmp_path), rel, max_mutants=10).to_dict()
    assert a == b
    assert a["scoped_tests"] == ["tests/test_foo.py"]


def test_scoped_run_original_tree_unchanged(tmp_path):
    rel = _write_pkg_module(tmp_path, _MODULE_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text(
        "from app.foo import is_equal\n"
        "def test_eq():\n    assert is_equal(1, 1) is True\n",
        encoding="utf-8",
    )
    before = (tmp_path / rel).read_text(encoding="utf-8")
    mutation_score(str(tmp_path), rel, max_mutants=10)
    after = (tmp_path / rel).read_text(encoding="utf-8")
    assert after == before == _MODULE_SRC


# --- CLI ------------------------------------------------------------------

def test_cmd_mutants_human_output(tmp_path, capsys):
    test_src = (
        "from mod import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    args = argparse.Namespace(module=rel, target=str(tmp_path),
                              max_mutants=10, timeout=120, json=False)
    rc = cmd_mutants(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Mutation score" in out
    assert "100.0%" in out


def test_cmd_mutants_json_output(tmp_path, capsys):
    test_src = (
        "from mod import is_equal\n"
        "def test_smoke():\n"
        "    assert is_equal(1, 1) is not None\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    args = argparse.Namespace(module=rel, target=str(tmp_path),
                              max_mutants=10, timeout=120, json=True)
    rc = cmd_mutants(args)
    out = capsys.readouterr().out
    import json as _json
    payload = _json.loads(out)
    assert rc == 0
    assert payload["total"] >= 1
    assert payload["survived"] >= 1
    survivor_ops = {s["operator"] for s in payload["survivors"]}
    assert "comparison:==>!=" in survivor_ops


def test_cmd_mutants_empty_module(tmp_path, capsys):
    module_src = "def noop(x):\n    pass\n"
    test_src = (
        "from mod import noop\n"
        "def test_pt():\n"
        "    assert noop(1) is None\n"
    )
    rel = _write_project(tmp_path, module_src, test_src)
    args = argparse.Namespace(module=rel, target=str(tmp_path),
                              max_mutants=10, timeout=120, json=False)
    rc = cmd_mutants(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "No mutable sites" in out


# --- test-strength grade + markdown rendering -----------------------------

def test_strength_grade_perfect_score_is_a_plus():
    assert _test_strength_grade(1.0) == "A+"
    # Just at the A+ cutoff.
    assert _test_strength_grade(0.97) == "A+"


def test_strength_grade_high_score_is_a():
    # Below the A+ cutoff but at/above the A cutoff.
    assert _test_strength_grade(0.96) == "A"
    assert _test_strength_grade(0.90) == "A"


def test_strength_grade_zero_score_is_f():
    assert _test_strength_grade(0.0) == "F"
    # Just below the D floor.
    assert _test_strength_grade(0.59) == "F"


def test_strength_grade_middle_bands():
    assert _test_strength_grade(0.80) == "B"
    assert _test_strength_grade(0.79) == "C"
    assert _test_strength_grade(0.70) == "C"
    assert _test_strength_grade(0.69) == "D"
    assert _test_strength_grade(0.60) == "D"


def test_render_mutation_markdown_with_survivors_shows_grade_and_blind_spots():
    survivor = Mutant(module="app/foo.py", line=12,
                      operator="comparison:==>!=", original="==", mutated="!=")
    result = MutationResult(
        module="app/foo.py", total=4, killed=3, survived=1, score=0.75,
        survivors=[survivor], scoped_tests=["tests/test_foo.py"],
    )
    md = render_mutation_markdown(result)
    # Letter grade for 0.75 is C, badge present.
    assert "**C**" in md
    # Percentage of the score.
    assert "75.0%" in md
    # Killed / survived / total split surfaces.
    assert "| Mutants killed | 3 |" in md
    assert "| Mutants survived | 1 |" in md
    assert "| Total seeded | 4 |" in md
    # Scope provenance: the covering test file is named.
    assert "tests/test_foo.py" in md
    # The survivor's file:line + operator is rendered (the blind spot).
    assert "app/foo.py:12" in md
    assert "comparison:==>!=" in md
    assert "Blind spots" in md


def test_render_mutation_markdown_perfect_score_no_survivors():
    result = MutationResult(
        module="mod.py", total=3, killed=3, survived=0, score=1.0,
        survivors=[], scoped_tests=[],
    )
    md = render_mutation_markdown(result)
    assert "**A+**" in md
    assert "100.0%" in md
    # No covering test -> full-suite fallback noted.
    assert "full" in md
    # No survivors -> the reassuring line, not a blind-spots section.
    assert "No survivors" in md
    assert "Blind spots" not in md


def test_render_mutation_markdown_empty_total_is_clean():
    result = MutationResult(module="mod.py", total=0, killed=0, survived=0,
                            score=0.0, survivors=[], scoped_tests=[])
    md = render_mutation_markdown(result)
    assert "No mutable sites" in md
    # Must not crash or claim a grade for a zero-site module.
    assert "**F**" not in md


def test_render_mutation_markdown_baseline_red_does_not_fake_a_grade():
    # THE HONESTY BUG this fixes: when the covering suite is already RED on the
    # unmutated module inside the sandbox (baseline_ok=False), mutation_score
    # returns killed=0 / survived=all with baseline_ok=False. The render MUST NOT
    # present that as a real "F, 0% score, N blind spots the tests don't catch" —
    # the tests are NOT blind; the measurement never ran. (Real-world trigger: a
    # covering test reconstructs source via `git show HEAD:` and errors in the
    # `.git`-less sandbox copy.)
    survivor = Mutant(module="app/foo.py", line=29, operator="return:value>None",
                      original="asdict(self)", mutated="None")
    result = MutationResult(
        module="app/foo.py", total=6, killed=0, survived=6, score=0.0,
        survivors=[survivor], scoped_tests=["tests/test_foo_byteident.py"],
        baseline_ok=False,
    )
    md = render_mutation_markdown(result)
    # It must say the score was NOT measured, not stamp a failing grade.
    assert "not measured" in md
    assert "Baseline not green" in md
    # It must NOT fabricate a letter grade or a blind-spots verdict.
    assert "**F**" not in md
    assert "Blind spots" not in md
    assert "Mutation score" not in md
    # It must NOT libel the tests by listing the phantom "survivor" as a blind spot.
    assert "return:value>None" not in md
    # It should still name the covering scope so the offending test is findable,
    # and point at the common cause.
    assert "tests/test_foo_byteident.py" in md
    assert "git show HEAD" in md


def test_render_mutation_markdown_flags_budget_truncated_scan():
    # A budget-exhausted scan examined only a SUBSET of mutants, so "no survivors"
    # means "none among those examined" — not "module clean". The render must say
    # so instead of letting an incomplete scan read as a full pass.
    result = MutationResult(
        module="app/foo.py", total=2, killed=2, survived=0, score=1.0,
        survivors=[], scoped_tests=["tests/test_foo.py"], budget_exhausted=True,
    )
    md = render_mutation_markdown(result)
    assert "Budget exhausted" in md
    assert "partial" in md
    # The examined-set score is still shown honestly (2/2 of what ran).
    assert "| Total seeded | 2 |" in md


def test_cmd_mutants_renders_grade(tmp_path, capsys):
    # A strong covering suite scores 100% -> grade A+ in the rendered output.
    test_src = (
        "from mod import is_equal\n"
        "def test_eq():\n"
        "    assert is_equal(1, 1) is True\n"
        "    assert is_equal(1, 2) is False\n"
    )
    rel = _write_project(tmp_path, _MODULE_SRC, test_src)
    args = argparse.Namespace(module=rel, target=str(tmp_path),
                              max_mutants=10, timeout=120, json=False)
    rc = cmd_mutants(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Test strength:" in out
    assert "**A+**" in out
    assert "100.0%" in out
