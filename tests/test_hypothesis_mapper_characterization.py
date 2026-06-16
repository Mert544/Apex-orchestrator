"""Characterization tests pinning HypothesisMapper._generate output.

These assert the exact strings produced per pattern, including
last-match-wins hypothesis selection, ordered snippet accumulation,
and the callable fallback. They guard the refactor of _generate into
pure helpers from drifting.
"""

from app.engine.hypothesis_mapper import HypothesisMapper


def _gen(text: str, target: str = "fn"):
    return HypothesisMapper()._generate(text, target)


def test_validation_pattern():
    hyp, snips = _gen("function lacks input validation", "fn")
    assert hyp == "fn raises ValueError on invalid input"
    assert snips == [
        "def test_fn_rejects_invalid_input():\n"
        "    with pytest.raises(ValueError):\n"
        "        fn(None)\n"
    ]


def test_docstring_pattern():
    hyp, snips = _gen("missing docstring here", "fn")
    assert hyp == "fn has a non-empty docstring"
    assert "test_fn_has_docstring" in snips[0]


def test_eval_pattern():
    hyp, snips = _gen("uses eval on data", "fn")
    assert hyp == "fn does not use eval() on untrusted data"
    assert "test_fn_avoids_eval" in snips[0]


def test_typing_pattern():
    hyp, snips = _gen("no type annotation present", "fn")
    assert hyp == "fn has type annotations on all parameters"
    assert "test_fn_has_type_annotations" in snips[0]


def test_zero_pattern():
    hyp, snips = _gen("possible zero division", "fn")
    assert hyp == "fn handles edge case inputs gracefully"
    assert "test_fn_handles_edge_cases" in snips[0]


def test_bare_except_pattern():
    hyp, snips = _gen("contains bare except", "fn")
    assert hyp == "fn catches specific exceptions only"
    assert "test_fn_catches_specific_exceptions" in snips[0]


def test_fallback_when_no_pattern():
    hyp, snips = _gen("nothing relevant matches words", "fn")
    assert hyp == "fn exists and is callable"
    assert snips == [
        "def test_fn_exists_and_callable():\n"
        "    assert callable(fn)\n"
    ]


def test_last_match_wins_for_hypothesis_and_ordered_snippets():
    # validation + docstring both match; docstring is later -> wins hypothesis.
    hyp, snips = _gen("lacks validation and missing docstring", "fn")
    assert hyp == "fn has a non-empty docstring"
    assert len(snips) == 2
    assert "rejects_invalid_input" in snips[0]
    assert "has_docstring" in snips[1]


def test_all_patterns_accumulate_in_order():
    text = (
        "no guard input validation docstring eval typing zero bare except:"
    )
    hyp, snips = _gen(text, "fn")
    # bare-except is the last pattern in the table -> wins hypothesis.
    assert hyp == "fn catches specific exceptions only"
    assert len(snips) == 6
    expected_markers = [
        "rejects_invalid_input",
        "has_docstring",
        "avoids_eval",
        "has_type_annotations",
        "handles_edge_cases",
        "catches_specific_exceptions",
    ]
    for snip, marker in zip(snips, expected_markers):
        assert marker in snip
