"""Cyclomatic-complexity DISTRIBUTION analyzer: histogram, threshold, hotspots.

Pins the self-contained McCabe rule (``1 + sum of decision points``) with
explicit small cases, then exercises the project-level profile: bucketing,
the over-threshold count, hotspot ordering, empty-safety, and determinism.
"""

from __future__ import annotations

import ast

from app.tools.complexity_profile import (
    ComplexityProfile,
    analyze_complexity,
    cyclomatic_complexity,
    function_cyclomatic_complexities,
)


def _fn(source: str):
    return ast.parse(source).body[0]


# --------------------------------------------------------------------------
# McCabe rule: 1 + sum of decision points. Pin each documented node weight.
# --------------------------------------------------------------------------


def test_flat_function_is_one():
    src = "def f(x):\n    a = x + 1\n    return a\n"
    assert cyclomatic_complexity(_fn(src)) == 1


def test_each_if_adds_one():
    # N independent ifs => 1 + N. Here N = 3 => 4.
    src = (
        "def f(x):\n"
        "    if x: pass\n"
        "    if x: pass\n"
        "    if x: pass\n"
    )
    assert cyclomatic_complexity(_fn(src)) == 4


def test_elif_counts_else_does_not():
    # elif is a nested If in the AST (+1 each); a plain else adds nothing.
    src = (
        "def f(x):\n"
        "    if x == 1:\n        return 'a'\n"   # +1
        "    elif x == 2:\n        return 'b'\n"  # +1
        "    elif x == 3:\n        return 'c'\n"  # +1
        "    else:\n        return 'd'\n"          # +0
    )
    assert cyclomatic_complexity(_fn(src)) == 4  # 1 + 3


def test_loops_each_add_one():
    src = (
        "def f(xs):\n"
        "    for x in xs:\n"        # +1
        "        while x:\n"        # +1
        "            x -= 1\n"
    )
    assert cyclomatic_complexity(_fn(src)) == 3  # 1 + 2


def test_ternary_adds_one():
    src = "def f(x):\n    return 1 if x else 2\n"  # +1
    assert cyclomatic_complexity(_fn(src)) == 2


def test_assert_adds_one():
    src = "def f(x):\n    assert x\n    return x\n"  # +1
    assert cyclomatic_complexity(_fn(src)) == 2


def test_bool_chain_counts_short_circuits():
    # `a and b and c` => len(values) - 1 = 2 short-circuit branches.
    src = "def f(a, b, c):\n    return a and b and c\n"
    assert cyclomatic_complexity(_fn(src)) == 3  # 1 + 2


def test_bool_or_pair_adds_one():
    src = "def f(a, b):\n    return a or b\n"  # 1 operand boundary
    assert cyclomatic_complexity(_fn(src)) == 2


def test_except_handlers_each_count_try_does_not():
    src = (
        "def f(x):\n"
        "    try:\n"
        "        return 1 / x\n"
        "    except ZeroDivisionError:\n"   # +1
        "        return 0\n"
        "    except ValueError:\n"           # +1
        "        return -1\n"
    )
    assert cyclomatic_complexity(_fn(src)) == 3  # 1 + 2


def test_with_items_each_count():
    # `with a, b:` is two acquisitions => +2.
    src = "def f():\n    with open('a') as x, open('b') as y:\n        pass\n"
    assert cyclomatic_complexity(_fn(src)) == 3  # 1 + 2


def test_comprehension_for_and_if_filters():
    # one `for` clause (+1) plus two `if` filters (+2).
    src = "def f(xs):\n    return [x for x in xs if x if x]\n"
    assert cyclomatic_complexity(_fn(src)) == 4  # 1 + 3


def test_nested_def_is_excluded_from_outer():
    # The inner def owns its own branch; the outer stays flat.
    src = (
        "def outer(x):\n"
        "    def inner(y):\n"
        "        if y: return 1\n"
        "        return 0\n"
        "    return inner(x)\n"
    )
    assert cyclomatic_complexity(_fn(src)) == 1  # outer is flat


def test_match_and_not_are_not_counted():
    # Documented exclusions: `match`/`case` and boolean `not` add nothing.
    src = (
        "def f(x):\n"
        "    y = not x\n"
        "    match x:\n"
        "        case 1:\n            return 'a'\n"
        "        case _:\n            return 'b'\n"
    )
    assert cyclomatic_complexity(_fn(src)) == 1


# --------------------------------------------------------------------------
# function_cyclomatic_complexities: qualified names, nesting, unparsable.
# --------------------------------------------------------------------------


def test_qualified_method_names_and_nesting():
    src = (
        "class Svc:\n"
        "    def run(self, x):\n"
        "        if x: return 1\n"      # Svc.run => 2
        "        def helper(y):\n"
        "            if y: return 2\n"  # Svc.run.helper => 2
        "            return 0\n"
        "        return helper(x)\n"
    )
    rows = function_cyclomatic_complexities(src)
    names = {name: c for name, _ln, c in rows}
    assert names == {"Svc.run": 2, "Svc.run.helper": 2}


def test_unparsable_source_is_silent():
    assert function_cyclomatic_complexities("def broken(:\n") == []


# --------------------------------------------------------------------------
# analyze_complexity: bucketing, threshold, hotspots, mean/median/max.
# --------------------------------------------------------------------------


def _write(root, rel: str, body: str):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_empty_tree_is_safe(tmp_path):
    profile = analyze_complexity(tmp_path)
    assert isinstance(profile, ComplexityProfile)
    assert profile.total == 0
    assert profile.over_threshold == 0
    assert profile.mean == 0.0
    assert profile.median == 0.0
    assert profile.max == 0
    assert profile.hotspots == []
    assert profile.histogram == {"1-5": 0, "6-10": 0, "11-15": 0, "16-20": 0, "21+": 0}


def test_tree_with_no_functions_is_safe(tmp_path):
    _write(tmp_path, "consts.py", "A = 1\nB = 2\n")
    profile = analyze_complexity(tmp_path)
    assert profile.total == 0
    assert profile.files_scanned == 1
    assert profile.hotspots == []


def _n_ifs(name: str, n: int) -> str:
    """A function whose complexity is ``n + 1``: ``n`` independent ifs plus a
    trailing ``return`` so the body is never empty (works for ``n == 0``)."""
    lines = [f"def {name}(x):"]
    lines += ["    if x: pass" for _ in range(n)]
    lines.append("    return x")
    return "\n".join(lines) + "\n"


def test_histogram_bucketing_and_stats(tmp_path):
    # Build functions with known complexities: 1, 6, 13, 22.
    n_ifs = _n_ifs
    _write(tmp_path, "m.py", "".join((
        n_ifs("c1", 0),    # complexity 1   -> bucket 1-5
        n_ifs("c6", 5),    # complexity 6   -> bucket 6-10
        n_ifs("c13", 12),  # complexity 13  -> bucket 11-15
        n_ifs("c22", 21),  # complexity 22  -> bucket 21+
    )))
    profile = analyze_complexity(tmp_path, threshold=12)

    assert profile.total == 4
    assert profile.histogram == {
        "1-5": 1, "6-10": 1, "11-15": 1, "16-20": 0, "21+": 1,
    }
    # values: 1, 6, 13, 22 -> mean 10.5, median (6+13)/2 = 9.5, max 22.
    assert profile.mean == 10.5
    assert profile.median == 9.5
    assert profile.max == 22
    # strictly greater than threshold (12): 13 and 22 qualify, not a 12.
    assert profile.over_threshold == 2


def test_threshold_is_strictly_greater(tmp_path):
    n_ifs = _n_ifs
    # complexity exactly 12 must NOT count toward over_threshold(12).
    _write(tmp_path, "m.py", n_ifs("c12", 11))
    profile = analyze_complexity(tmp_path, threshold=12)
    assert profile.max == 12
    assert profile.over_threshold == 0
    # lowering the threshold below 12 makes it count.
    assert analyze_complexity(tmp_path, threshold=11).over_threshold == 1


def test_hotspots_ordering_and_shape(tmp_path):
    n_ifs = _n_ifs
    # Two modules; b.big is the most complex, then a.mid, then a.low.
    _write(tmp_path, "a.py", n_ifs("mid", 4) + n_ifs("low", 1))
    _write(tmp_path, "b.py", n_ifs("big", 9))
    profile = analyze_complexity(tmp_path)

    assert profile.hotspots[0] == {"module": "b", "function": "big", "complexity": 10}
    assert profile.hotspots[1] == {"module": "a", "function": "mid", "complexity": 5}
    assert profile.hotspots[2] == {"module": "a", "function": "low", "complexity": 2}
    # sorted by (-complexity, module, function): descending complexity here.
    comps = [h["complexity"] for h in profile.hotspots]
    assert comps == sorted(comps, reverse=True)


def test_hotspot_tie_broken_by_module_then_function(tmp_path):
    # Two functions of equal complexity: ordered by module, then function.
    body = "def zfn(x):\n    if x: pass\n"  # complexity 2 each
    _write(tmp_path, "z.py", body)
    _write(tmp_path, "a.py", "def afn(x):\n    if x: pass\n")
    profile = analyze_complexity(tmp_path)
    pairs = [(h["module"], h["function"]) for h in profile.hotspots]
    # a.afn sorts before z.zfn on equal complexity.
    assert pairs == [("a", "afn"), ("z", "zfn")]


def test_hotspots_are_capped_at_15(tmp_path):
    # 20 distinct complex functions -> only 15 hotspots reported.
    parts = []
    for i in range(20):
        parts.append(
            f"def f{i:02d}(x):\n"
            + "".join("    if x: pass\n" for _ in range(i + 1))
        )
    _write(tmp_path, "many.py", "".join(parts))
    profile = analyze_complexity(tmp_path)
    assert profile.total == 20
    assert len(profile.hotspots) == 15
    # the very worst (f19, complexity 21) leads.
    assert profile.hotspots[0]["function"] == "f19"


def test_max_files_cap_is_respected(tmp_path):
    for i in range(5):
        _write(tmp_path, f"m{i}.py", "def f(x):\n    if x: pass\n")
    capped = analyze_complexity(tmp_path, max_files=2)
    assert capped.files_scanned == 2
    assert capped.total == 2


def test_skipped_dirs_are_excluded(tmp_path):
    # A nested worktree copy under .claude must not be counted.
    _write(tmp_path, "real.py", "def f(x):\n    if x: pass\n")
    _write(tmp_path, ".claude/worktrees/w/copy.py", "def g(x):\n    if x: pass\n")
    profile = analyze_complexity(tmp_path)
    assert profile.files_scanned == 1
    assert profile.total == 1
    assert profile.hotspots[0]["module"] == "real"


def test_determinism_same_tree_same_profile(tmp_path):
    _write(tmp_path, "a.py", "def f(x):\n    if x and x: pass\n    return x\n")
    _write(tmp_path, "pkg/b.py", "def g(x):\n    for i in x:\n        if i: pass\n")
    first = analyze_complexity(tmp_path)
    second = analyze_complexity(tmp_path)
    assert first.to_dict() == second.to_dict()


def test_to_dict_round_trips_fields(tmp_path):
    _write(tmp_path, "m.py", "def f(x):\n    if x: pass\n")
    profile = analyze_complexity(tmp_path, threshold=12)
    d = profile.to_dict()
    assert d["threshold"] == 12
    assert d["total"] == 1
    assert d["histogram"]["1-5"] == 1
    assert d["hotspots"] == [{"module": "m", "function": "f", "complexity": 2}]
