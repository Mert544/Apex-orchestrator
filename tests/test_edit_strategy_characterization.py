"""Characterization tests pinning EditStrategy.choose decisions.

These lock the exact (strategy, confidence, reasons) for representative inputs
across every branch and precedence boundary, so a future refactor cannot drift
the chosen strategy. The grid mirrors the original sequential if-chain order.
"""

from __future__ import annotations

import pytest

from app.execution.edit_strategy import EditStrategy


def _choose(title="", patch_plan=None, related_tests=None, repair_context=None):
    return EditStrategy().choose(
        title=title,
        patch_plan=patch_plan or {},
        related_tests=related_tests,
        repair_context=repair_context,
    )


# (title, patch_plan, related_tests, repair_context) -> (strategy, confidence, reasons)
_CASES = [
    # Repair context wins over everything, including patch-plan flags + keywords.
    (
        ("eval rename", {"rename": True}, None, {"failure_type": "test_failure"}),
        ("repair_test_assertion", 0.8, ["Repair context indicates a test failure."]),
    ),
    (
        ("eval", {"rename": True}, None, {"failure_type": "patch_scope_failure"}),
        ("add_docstring", 0.6, ["Repair context indicates scope reduction is needed."]),
    ),
    (
        ("", {}, None, {"failure_type": "other"}),
        ("add_docstring", 0.5, ["No strong signal; defaulting to add_docstring."]),
    ),
    # Patch-plan flags win over keywords; first truthy flag wins.
    (
        ("eval security", {"rename": True}, None, None),
        ("rename_variable", 0.9, ["Patch plan explicitly requests a rename."]),
    ),
    (
        ("", {"extract": True, "inline": True}, None, None),
        ("extract_method", 0.8, ["Patch plan explicitly requests method extraction."]),
    ),
    (
        ("", {"inline": True}, None, None),
        ("inline_variable", 0.8, ["Patch plan explicitly requests variable inlining."]),
    ),
    (
        ("", {"move": True}, None, None),
        ("move_class", 0.7, ["Patch plan explicitly requests class move."]),
    ),
    (
        ("", {"extract_class": True}, None, None),
        ("extract_class", 0.7, ["Patch plan explicitly requests class extraction."]),
    ),
    # Keyword rules, in precedence order.
    (
        ("eval injection", {}, None, None),
        ("fix_eval", 0.85, ["Keywords suggest an eval() security fix."]),
    ),
    (
        ("os.system call", {}, None, None),
        ("fix_os_system", 0.85, ["Keywords suggest an os.system() security fix."]),
    ),
    (
        ("bare except", {}, None, None),
        ("fix_bare_except", 0.9, ["Keywords suggest a bare-except fix."]),
    ),
    (
        ("bareexcept", {}, None, None),
        ("fix_bare_except", 0.9, ["Keywords suggest a bare-except fix."]),
    ),
    (
        ("base-exception narrowing", {}, None, None),
        ("fix_base_exception", 0.9, ["Keywords suggest narrowing except BaseException."]),
    ),
    (
        ("pickle.loads", {}, None, None),
        ("fix_pickle", 0.8, ["Keywords suggest flagging unsafe pickle.loads()."]),
    ),
    (
        ("sql injection", {}, None, None),
        ("fix_sql", 0.8, ["Keywords suggest flagging an SQL-injection risk."]),
    ),
    (
        ("injection", {}, None, None),
        ("fix_sql", 0.8, ["Keywords suggest flagging an SQL-injection risk."]),
    ),
    (
        ("yaml.load", {}, None, None),
        ("fix_yaml", 0.85, ["Keywords suggest a yaml.load() safety fix."]),
    ),
    (
        ("tempfile mktemp", {}, None, None),
        ("fix_tempfile", 0.8, ["Keywords suggest flagging an insecure tempfile.mktemp()."]),
    ),
    (
        ("weak-hash hashlib", {}, None, None),
        ("fix_weak_hash", 0.8, ["Keywords suggest flagging a weak hashlib.md5()/sha1()."]),
    ),
    (
        ("mutable default arg", {}, None, None),
        ("fix_mutable_default", 0.85, ["Keywords suggest a mutable-default-argument fix."]),
    ),
    (
        ("modernize none-comparison", {}, None, None),
        ("modernize", 0.85, ["Keywords suggest behavior-preserving modernization."]),
    ),
    (
        ("open-encoding", {}, None, None),
        ("fix_open_encoding", 0.85, ["Keywords suggest adding an explicit open() encoding."]),
    ),
    (
        ("net-timeout hang", {}, None, None),
        ("fix_net_timeout", 0.8, ["Keywords suggest flagging a network call without a timeout."]),
    ),
    (
        ("identity-literal", {}, None, None),
        ("fix_identity_literal", 0.85, ["Keywords suggest fixing an identity-vs-literal comparison."]),
    ),
    (
        ("negated-comparison", {}, None, None),
        ("fix_negated_comparison", 0.85, ["Keywords suggest fixing a negated membership/identity test."]),
    ),
    (
        ("raise-from", {}, None, None),
        ("fix_raise_from", 0.85, ["Keywords suggest chaining a re-raised exception to its cause."]),
    ),
    (
        ("fstring-no-placeholder", {}, None, None),
        ("fix_fstring", 0.85, ["Keywords suggest dropping a dead f-string prefix."]),
    ),
    (
        ("collection-literal", {}, None, None),
        ("fix_collection_literal", 0.85, ["Keywords suggest replacing an empty constructor with a literal."]),
    ),
    (
        ("import unused cleanup", {}, None, None),
        ("organize_imports", 0.7, ["Keywords suggest import cleanup."]),
    ),
    (
        ("docstring document", {}, None, None),
        ("add_docstring", 0.85, ["Keywords suggest documentation."]),
    ),
    (
        ("type typing annotation", {}, None, None),
        ("add_type_annotations", 0.8, ["Keywords suggest type annotation work."]),
    ),
    (
        ("guard validate input security", {}, None, None),
        ("add_guard_clause", 0.85, ["Keywords suggest input validation."]),
    ),
    # 'security' alone still routes to guard (no concrete fix keyword present).
    (
        ("security review", {}, None, None),
        ("add_guard_clause", 0.85, ["Keywords suggest input validation."]),
    ),
    # eval precedence over guard/security in the same text.
    (
        ("eval security guard", {}, None, None),
        ("fix_eval", 0.85, ["Keywords suggest an eval() security fix."]),
    ),
    # change_strategy contributes to the combined text.
    (
        ("", {"change_strategy": ["Add guard clause for invalid input."]}, None, None),
        ("add_guard_clause", 0.85, ["Keywords suggest input validation."]),
    ),
    # Test-related defaults.
    (
        ("improve test coverage", {}, None, None),
        ("add_docstring", 0.6, ["Context suggests test-related work."]),
    ),
    (
        ("unrelated", {}, ["tests/test_x.py"], None),
        ("add_docstring", 0.6, ["Context suggests test-related work."]),
    ),
    # Final fallback.
    (
        ("totally unrelated request", {}, None, None),
        ("add_docstring", 0.5, ["No strong signal; defaulting to add_docstring."]),
    ),
    (
        ("totally unrelated request", {}, [], {}),
        ("add_docstring", 0.5, ["No strong signal; defaulting to add_docstring."]),
    ),
]


@pytest.mark.parametrize("inputs,expected", _CASES)
def test_choose_is_pinned(inputs, expected):
    title, patch_plan, related_tests, repair_context = inputs
    result = _choose(title, patch_plan, related_tests, repair_context)
    assert (result.strategy, result.confidence, result.reasons) == expected


def test_choose_reasons_are_single_entry_lists():
    # Every branch appends exactly one reason; pin that invariant.
    for inputs, _expected in _CASES:
        title, patch_plan, related_tests, repair_context = inputs
        result = _choose(title, patch_plan, related_tests, repair_context)
        assert len(result.reasons) == 1


def test_choose_is_deterministic():
    args = ("guard validate", {"change_strategy": ["security"]}, ["t.py"], {})
    first = _choose(*args).to_dict()
    for _ in range(5):
        assert _choose(*args).to_dict() == first


def test_none_inputs_default_cleanly():
    result = _choose("", {}, None, None)
    assert result.strategy == "add_docstring"
    assert result.confidence == 0.5
