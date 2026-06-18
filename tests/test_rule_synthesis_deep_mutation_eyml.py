"""Deep-mutation characterization for rule synthesis.

These tests pin the exact shape keys, support arithmetic, thresholds, ordering,
constants and descriptor text inside ``app/engine/rule_synthesis.py`` that the
feature suite (``test_rule_synthesis_eyml.py``) leaves exposed to surviving AST
mutants. Each assertion is hand-computed so a single comparison / boundary /
constant / slice mutation makes at least one test fail:

* ``_shape_key`` abstraction: ``Name`` -> ``N``, ``Attribute`` -> ``A(...)``,
  ``Constant`` -> ``C:<type>``, structural tags + child ordering verbatim;
* ``_is_mined`` membership = exactly {If, Assign, Return};
* ``_site_label`` ``path:lineno`` format and ``lineno`` default 0;
* ``_accumulate`` sorted sites and SyntaxError skip;
* the support threshold ``len(where) < min_support`` (boundary inclusive),
  ``min_support < 1`` guard, descending-support sort with shape-key tie-break;
* the ``_MAX_EXAMPLES=5`` example cap and ``_MAX_SHAPES=64`` shape cap;
* ``_suggested_name`` slugging (head before ``[``/``(``, non-alnum -> ``_``,
  empty -> ``pattern``);
* ``synthesise_candidate_rule`` exact rationale/safety text, int-coerced support
  and missing-key defaults; ``propose_rules`` ``top`` cap and ``top < 1`` guard.

All assertions are deterministic (pure AST; no time/random; sorted output).
"""

from __future__ import annotations

import ast

from app.engine.rule_synthesis import (
    DEFAULT_MIN_SUPPORT,
    _MAX_EXAMPLES,
    _MAX_SHAPES,
    _MINED_STMTS,
    _accumulate,
    _is_mined,
    _shape_key,
    _site_label,
    _suggested_name,
    mine_recurring_patterns,
    propose_rules,
    synthesise_candidate_rule,
)


def _stmt(src: str) -> ast.stmt:
    return ast.parse(src).body[0]


def _expr(src: str) -> ast.AST:
    return ast.parse(src, mode="eval").body


# --------------------------------------------------------------------------- #
# Constants are exactly what the module documents.
# --------------------------------------------------------------------------- #
def test_module_constants_are_exact():
    """Conservative threshold 3, bounded outputs 64 shapes / 5 examples, and the
    mined-statement set is exactly {If, Assign, Return} in that order."""
    assert DEFAULT_MIN_SUPPORT == 3
    assert _MAX_SHAPES == 64
    assert _MAX_EXAMPLES == 5
    assert _MINED_STMTS == (ast.If, ast.Assign, ast.Return)


# --------------------------------------------------------------------------- #
# _shape_key: identifier/literal abstraction with verbatim structure.
# --------------------------------------------------------------------------- #
def test_shape_key_abstracts_names_and_literals():
    """``a = a + 1`` collapses to the same key as ``count = count + 5``: names
    become ``N``, the int literal becomes ``C:int``, structure kept verbatim."""
    key = _shape_key(_stmt("a = a + 1"))
    assert key == "Assign[N,BinOp[N,Add,C:int]]"
    assert key == _shape_key(_stmt("count = count + 5"))


def test_shape_key_constant_type_tag_distinguishes_types():
    """Constants abstract to their TYPE tag, not value: int / str / float / bool
    are distinct keys, so literal *type* still differentiates shapes."""
    assert _shape_key(_expr("1")) == "C:int"
    assert _shape_key(_expr("'h'")) == "C:str"
    assert _shape_key(_expr("1.5")) == "C:float"
    assert _shape_key(_expr("True")) == "C:bool"


def test_shape_key_attribute_nests_verbatim():
    """Attribute access nests as ``A(...)`` around its abstracted base; the depth
    of the chain is preserved (``a.b.c`` -> two nested ``A``)."""
    assert _shape_key(_expr("a.b")) == "A(N)"
    assert _shape_key(_expr("a.b.c")) == "A(A(N))"


def test_shape_key_child_order_is_preserved():
    """Children are emitted in AST field order; ``if x: return x`` keeps the test
    before the body so structurally different snippets cannot collide."""
    assert _shape_key(_stmt("if x:\n    return x")) == "If[N,Return[N]]"
    assert _shape_key(_stmt("return x")) == "Return[N]"


# --------------------------------------------------------------------------- #
# _is_mined: exactly the three statement types, nothing else.
# --------------------------------------------------------------------------- #
def test_is_mined_accepts_only_the_three_statements():
    """If / Assign / Return are mined; an Expr call, a For and a While are not —
    pins the membership so a widened/narrowed set is caught."""
    assert _is_mined(_stmt("if x:\n    return x")) is True
    assert _is_mined(_stmt("a = a + 1")) is True
    assert _is_mined(_stmt("return x")) is True
    assert _is_mined(_stmt("f()")) is False
    assert _is_mined(_stmt("for i in x:\n    pass")) is False
    assert _is_mined(_stmt("while x:\n    break")) is False


# --------------------------------------------------------------------------- #
# _site_label: path:lineno, with a 0 default when lineno is absent.
# --------------------------------------------------------------------------- #
def test_site_label_format_and_default_lineno():
    node = _stmt("a = a + 1")  # lineno 1
    assert _site_label("pkg/mod.py", node) == "pkg/mod.py:1"
    bare = ast.Assign(targets=[], value=ast.Constant(value=0))  # no lineno
    assert _site_label("x.py", bare) == "x.py:0"


# --------------------------------------------------------------------------- #
# _accumulate: sorted sites, SyntaxError-skip, deterministic across dict order.
# --------------------------------------------------------------------------- #
def test_accumulate_sorts_sites_and_skips_unparseable():
    """Sites for a shape are sorted ``path:lineno`` labels; an unparseable source
    is dropped without raising and does not contribute any key."""
    sources = {
        "z.py": "a = a + 1\n",
        "a.py": "b = b + 1\nc = c + 1\n",
        "broken.py": "def (:\n",
    }
    sites = _accumulate(sources)
    assert sites["Assign[N,BinOp[N,Add,C:int]]"] == ["a.py:1", "a.py:2", "z.py:1"]
    assert all("broken.py" not in s for v in sites.values() for s in v)


# --------------------------------------------------------------------------- #
# Support threshold is len(where) < min_support : exactly-at-threshold passes.
# --------------------------------------------------------------------------- #
def test_support_threshold_is_inclusive_at_min():
    """Three occurrences with min_support 3 surface (``3 < 3`` is False); two do
    not (``2 < 3`` is True). Pins the boundary against a ``<=`` mutant."""
    three = {f"f{i}.py": "a = a + 1\n" for i in range(3)}
    two = {f"f{i}.py": "a = a + 1\n" for i in range(2)}
    pats3 = mine_recurring_patterns(three, min_support=3)
    assert len(pats3) == 1
    assert pats3[0]["support"] == 3
    assert mine_recurring_patterns(two, min_support=3) == []


def test_min_support_below_one_is_rejected():
    """``min_support < 1`` short-circuits to [] before any mining; 1 is allowed."""
    src = {"a.py": "a = a + 1\n"}
    assert mine_recurring_patterns(src, min_support=0) == []
    assert mine_recurring_patterns(src, min_support=-1) == []
    assert mine_recurring_patterns(src, min_support=1)[0]["support"] == 1


def test_empty_sources_short_circuit():
    """No sources -> [] (the ``not sources`` guard) without touching the miner."""
    assert mine_recurring_patterns({}, min_support=1) == []


# --------------------------------------------------------------------------- #
# Sorting: descending support, shape key as the deterministic tie-break.
# --------------------------------------------------------------------------- #
def test_output_sorted_descending_support_then_shape():
    """Assign x4 outranks Return x3 by support; two equal-support shapes order by
    shape key ascending. Pins the ``(-support, shape)`` sort key exactly."""
    src = {}
    for i in range(4):
        src[f"a{i}.py"] = "a = a + 1\n"
    for i in range(3):
        src[f"r{i}.py"] = "def f():\n    return x\n"
    pats = mine_recurring_patterns(src, min_support=3)
    assert [(p["support"], p["shape"]) for p in pats] == [
        (4, "Assign[N,BinOp[N,Add,C:int]]"),
        (3, "Return[N]"),
    ]


def test_equal_support_breaks_ties_by_shape_key():
    """Two distinct shapes, each support 3: ordered by shape key ascending —
    ``Assign...`` before ``Return...``."""
    src = {}
    for i in range(3):
        src[f"a{i}.py"] = "a = a + 1\n"
    for i in range(3):
        src[f"r{i}.py"] = "def f():\n    return x\n"
    shapes = [p["shape"] for p in mine_recurring_patterns(src, min_support=3)]
    assert shapes == ["Assign[N,BinOp[N,Add,C:int]]", "Return[N]"]


# --------------------------------------------------------------------------- #
# _MAX_EXAMPLES: support is the true count, examples are capped at five.
# --------------------------------------------------------------------------- #
def test_examples_capped_at_five_while_support_is_full():
    """Six sites: support stays 6 but only the first five sorted labels are kept
    as examples — pins the ``[:_MAX_EXAMPLES]`` slice against an off-by-one."""
    src = {f"f{i}.py": "a = a + 1\n" for i in range(6)}
    pats = mine_recurring_patterns(src, min_support=3)
    top = pats[0]
    assert top["support"] == 6
    assert top["example_sites"] == [
        "f0.py:1", "f1.py:1", "f2.py:1", "f3.py:1", "f4.py:1",
    ]
    assert len(top["example_sites"]) == _MAX_EXAMPLES


# --------------------------------------------------------------------------- #
# _suggested_name: slug from the leading structural tag.
# --------------------------------------------------------------------------- #
def test_suggested_name_slugs_leading_tag():
    """Head is the tag before the first ``[`` or ``(``; alnum lowercased, every
    other char -> ``_``; empty head -> ``pattern``."""
    assert _suggested_name("Assign[N,BinOp[N,Add,C:int]]") == "synthesised_assign_rule"
    assert _suggested_name("If[N,Return[N]]") == "synthesised_if_rule"
    assert _suggested_name("Return[N]") == "synthesised_return_rule"
    assert _suggested_name("A(N)") == "synthesised_a_rule"
    assert _suggested_name("C:int") == "synthesised_c_int_rule"
    assert _suggested_name("") == "synthesised_pattern_rule"


# --------------------------------------------------------------------------- #
# synthesise_candidate_rule: exact descriptor text + defaults + int coercion.
# --------------------------------------------------------------------------- #
def test_descriptor_rationale_and_safety_text_are_exact():
    """The rationale embeds the shape and support verbatim; the safety note is
    the mandatory recommend-only disclaimer. Pins both strings character-exact."""
    rule = synthesise_candidate_rule(
        {"shape": "If[N,Return[N]]", "support": 3,
         "example_sites": ["p.py:2", "q.py:2", "r.py:2"]}
    )
    assert rule["rationale"] == (
        "Structural shape 'If[N,Return[N]]' recurs across 3 sites "
        "(identifiers and literals abstracted), suggesting a mechanical "
        "micro-pattern a single transform could normalise."
    )
    assert rule["safety_note"] == (
        "RECOMMEND-ONLY: behaviour-preservation is NOT verified. A human must "
        "confirm the rewrite is semantics-preserving across all sites before "
        "implementing a transform; Apex proposes, it does not apply."
    )
    assert rule["suggested_name"] == "synthesised_if_rule"
    assert rule["support"] == 3
    assert rule["example_sites"] == ["p.py:2", "q.py:2", "r.py:2"]


def test_descriptor_coerces_support_and_defaults_missing_keys():
    """A string support is int-coerced; a fully empty pattern defaults to shape
    ``''``, support 0, no examples, and the ``pattern`` fallback name."""
    coerced = synthesise_candidate_rule({"shape": "X", "support": "7"})
    assert coerced["support"] == 7
    assert isinstance(coerced["support"], int)
    empty = synthesise_candidate_rule({})
    assert empty["shape"] == ""
    assert empty["support"] == 0
    assert empty["example_sites"] == []
    assert empty["suggested_name"] == "synthesised_pattern_rule"


# --------------------------------------------------------------------------- #
# propose_rules: top cap, top<1 guard, strongest-first.
# --------------------------------------------------------------------------- #
def test_propose_rules_returns_strongest_first_and_caps_top():
    """Mined at the default threshold, wrapped strongest-first; ``top`` limits the
    count exactly. The Assign (support 4) outranks the Return (support 3)."""
    src = {}
    for i in range(4):
        src[f"a{i}.py"] = "a = a + 1\n"
    for i in range(3):
        src[f"r{i}.py"] = "def f():\n    return x\n"
    one = propose_rules(src, top=1)
    assert len(one) == 1
    assert one[0]["support"] == 4
    assert one[0]["suggested_name"] == "synthesised_assign_rule"
    both = propose_rules(src, top=2)
    assert [r["support"] for r in both] == [4, 3]


def test_propose_rules_top_below_one_is_empty():
    """``top < 1`` short-circuits to [] before mining."""
    src = {f"a{i}.py": "a = a + 1\n" for i in range(3)}
    assert propose_rules(src, top=0) == []
    assert propose_rules(src, top=-2) == []
