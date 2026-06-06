import pytest

from app.utils.branching import index_to_branch_token, make_branch_path


def test_single_letter_tokens_cover_first_26():
    assert index_to_branch_token(0) == "a"
    assert index_to_branch_token(1) == "b"
    assert index_to_branch_token(25) == "z"


def test_rolls_over_to_two_letters_bijectively():
    # bijective base-26 (spreadsheet-column style): 26 -> "aa", not "ba"
    assert index_to_branch_token(26) == "aa"
    assert index_to_branch_token(27) == "ab"
    assert index_to_branch_token(51) == "az"
    assert index_to_branch_token(52) == "ba"


def test_tokens_are_unique_and_ordered_over_a_range():
    tokens = [index_to_branch_token(i) for i in range(200)]
    assert len(set(tokens)) == 200          # bijective: no collisions
    assert tokens == sorted(tokens, key=lambda t: (len(t), t))


def test_negative_index_rejected():
    with pytest.raises(ValueError):
        index_to_branch_token(-1)


def test_make_branch_path_appends_token_to_parent():
    assert make_branch_path("x.a", 0) == "x.a.a"
    assert make_branch_path("root", 26) == "root.aa"


def test_make_branch_path_uses_x_prefix_when_no_parent():
    assert make_branch_path("", 0) == "x.a"
    assert make_branch_path("", 1) == "x.b"
