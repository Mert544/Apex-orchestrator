"""Characterization tests for param_drop's signature rebuild and call-site
keyword pruning. These pin the exact rewrite output and skip conditions of
``plan_param_drop`` across the parameter-kind space, guarding the decomposed
``_rebuild_params`` / ``_collect_removals`` helpers against drift."""
import tempfile
from pathlib import Path

from app.execution.param_drop import plan_param_drop


def _plan(snippet: str, func: str, param: str):
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "mod.py").write_text(snippet)
        return plan_param_drop(d, func, param)


# (label, snippet, drop, expected new "mod.py" content or None, expect_blocked)
CASES = [
    (
        "simple_positional",
        "def f(a, b):\n    return a\n\nf(1, b=2)\n",
        "b",
        "def f(a):\n    return a\n\nf(1)\n",
        False,
    ),
    (
        "annotated_default_spacing",
        "def f(a: int, b: int = 5, c: int = 9):\n    return a + c\n\nf(1, b=2, c=3)\n",
        "b",
        "def f(a: int, c: int = 9):\n    return a + c\n\nf(1, c=3)\n",
        False,
    ),
    (
        "unannotated_default_spacing",
        "def f(a, b=5, c=9):\n    return a + c\n\nf(1, b=2, c=3)\n",
        "b",
        "def f(a, c=9):\n    return a + c\n\nf(1, c=3)\n",
        False,
    ),
    (
        "keyword_only_keeps_star",
        "def f(a, *, b, c):\n    return a + c\n\nf(1, b=2, c=3)\n",
        "b",
        "def f(a, *, c):\n    return a + c\n\nf(1, c=3)\n",
        False,
    ),
    (
        "posonly_keeps_slash",
        "def f(a, b, /, c):\n    return a + c\n\nf(a=1, b=2, c=3)\n",
        "b",
        "def f(a, /, c):\n    return a + c\n\nf(a=1, c=3)\n",
        False,
    ),
    (
        "vararg_present_keeps_star_args",
        "def f(a, *args, b):\n    return a\n\nf(1, b=2)\n",
        "b",
        "def f(a, *args):\n    return a\n\nf(1)\n",
        False,
    ),
    (
        "kwarg_present_preserved",
        "def f(a, b, **kw):\n    return a\n\nf(1, b=2, x=3)\n",
        "b",
        "def f(a, **kw):\n    return a\n\nf(1, x=3)\n",
        False,
    ),
    (
        "drop_first_keyword",
        "def f(a, b, c):\n    return b + c\n\nf(a=1, b=2, c=3)\n",
        "a",
        "def f(b, c):\n    return b + c\n\nf(b=2, c=3)\n",
        False,
    ),
    (
        "positional_pass_blocks",
        "def f(a, b):\n    return a\n\nf(1, 2)\n",
        "b",
        None,
        True,
    ),
    (
        "reads_param_blocks",
        "def f(a, b):\n    return a + b\n\nf(1, b=2)\n",
        "b",
        None,
        True,
    ),
    (
        "vararg_target_blocks",
        "def f(a, *args):\n    return a\n\nf(1)\n",
        "args",
        None,
        True,
    ),
    (
        "comment_in_signature_blocks",
        "def f(a,  # note\n      b):\n    return a\n\nf(1, b=2)\n",
        "b",
        None,
        True,
    ),
    (
        "line_spanning_keyword_blocks",
        "def f(a, b):\n    return a\n\nf(\n    1,\n    b=(\n        2\n    ),\n)\n",
        "b",
        None,
        True,
    ),
]


def test_rewrite_outputs_and_skips():
    for label, snippet, drop, expected, blocked in CASES:
        plan = _plan(snippet, "f", drop)
        if blocked:
            assert plan.blockers, f"{label}: expected a blocker"
            assert not plan.new_contents, f"{label}: blocked plan must rewrite nothing"
        else:
            assert not plan.blockers, f"{label}: unexpected blocker {plan.blockers}"
            assert plan.new_contents.get("mod.py") == expected, label


def test_kwargs_call_site_blocks_the_drop():
    # A f(**mapping) site is the parameter's LIVE boundary: the dict could
    # carry 'b' at runtime and param_drop can't rewrite the splat to prove it
    # doesn't. Dropping 'b' would change the accepted-keyword contract, so the
    # drop is REFUSED (never fake green) and nothing is rewritten.
    plan = _plan("def f(a, b):\n    return a\n\nd = {}\nf(1, **d)\n", "f", "b")
    assert plan.blockers
    assert any("could still pass 'b'" in b and "refused" in b
               for b in plan.blockers)
    assert not plan.new_contents


def test_keyword_on_own_line_warns_but_rewrites():
    # The keyword stands alone with its separating comma on the line above,
    # out of reach of an intra-line edit -> ragged warning, still rewritten.
    plan = _plan("def f(a, b):\n    return a\n\nf(\n    1,\n    b=2\n)\n", "f", "b")
    assert not plan.blockers
    assert any("ragged" in w for w in plan.warnings)
    assert "b=2" not in plan.new_contents["mod.py"]


def test_not_a_parameter_blocks():
    plan = _plan("def f(a):\n    return a\n\nf(1)\n", "f", "z")
    assert plan.blockers
    assert not plan.new_contents
