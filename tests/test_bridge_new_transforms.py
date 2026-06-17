"""The behaviour-preserving simplification transforms must be
dispatchable through ``IdeaActionBridge``.

These assert the registration (each action_type is in both the change-strategy
map and the direct transform dispatch, and each seeding fact routes to an
executable step) and the dispatch behaviour (the bridge's own ``_generate``
path returns the transform's real patch on a matching source and ``None`` on a
non-match — exactly the refuse-on-unsafe contract the apply gate relies on).

Deterministic: fixed sources, no time/random.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_action_bridge import _FACT_ACTIONS, IdeaActionBridge
from app.models.idea import ActionStep


# action_type -> (a fact label that routes to it, the transform_type the
# transform stamps on its result, a source it WILL simplify, a source it will
# REFUSE). One row per new transform.
_CASES = {
    "merge_nested_if": (
        "merge-nested-if",
        "merge_nested_if",
        "def f(a, b):\n    if a:\n        if b:\n            return 1\n",
        "def f(a, b):\n    if a:\n        return 1\n",
    ),
    "redundant_else": (
        "redundant-else",
        "remove_redundant_else",
        "def f(x):\n    if x:\n        return 1\n    else:\n        return 2\n",
        "def f(x):\n    if x:\n        y = 1\n    return y\n",
    ),
    "dict_get_default": (
        "dict-get-default",
        "dict_get_default",
        "def f(d, k):\n    if k in d:\n        v = d[k]\n    else:\n        v = 0\n    return v\n",
        "def f(d, k):\n    return d[k]\n",
    ),
    "isinstance_merge": (
        "isinstance-merge",
        "merge_isinstance",
        "def f(x):\n    return isinstance(x, int) or isinstance(x, str)\n",
        "def f(x):\n    return isinstance(x, int)\n",
    ),
    "simplify_none_compare": (
        "none-compare",
        "simplify_comparison",
        "def f(x):\n    return x == None\n",
        "def f(x):\n    return x is None\n",
    ),
    "unreachable_cleanup": (
        "unreachable-code",
        "remove_unreachable_code",
        "def f():\n    return 1\n    x = 2\n",
        "def f():\n    return 1\n",
    ),
    # Promoted in this wave: same refuse-on-unsafe contract, same guarded gate.
    "chain_comparison": (
        "chained-comparison",
        "chained_comparison",
        "def f(a, b, c):\n    return a < b and b < c\n",
        "def f():\n    return 1\n",
    ),
    "set_literal": (
        "set-literal",
        "set_literal",
        "x = set([1, 2, 3])\n",
        "def f():\n    return 1\n",
    ),
    "startswith_tuple": (
        "startswith-tuple",
        "startswith_tuple",
        'def f(s):\n    return s.startswith("a") or s.startswith("b")\n',
        "def f():\n    return 1\n",
    ),
    "not_in_simplify": (
        "not-in-simplify",
        "simplify_not_in",
        "def f(a, b):\n    return not a in b\n",
        "def f():\n    return 1\n",
    ),
    "tuple_membership": (
        "tuple-membership",
        "tuple_membership",
        "def f(x):\n    return x == 1 or x == 2 or x == 3\n",
        "def f():\n    return 1\n",
    ),
    "dict_literal": (
        "dict-literal",
        "dict_literal",
        "x = dict(a=1, b=2)\n",
        "def f():\n    return 1\n",
    ),
    "double_not": (
        "double-not",
        "double_not_to_bool",
        "def f(x):\n    return not not x\n",
        "def f():\n    return 1\n",
    ),
    "swap_via_tuple": (
        "swap-via-tuple",
        "swap_via_tuple",
        "def f(a, b):\n    tmp = a\n    a = b\n    b = tmp\n    return a, b\n",
        "def f():\n    return 1\n",
    ),
    "membership_set": (
        "membership-set",
        "membership_set",
        "def f(x):\n    return x in (1, 2, 3)\n",
        "def f():\n    return 1\n",
    ),
    "percent_string_concat": (
        "percent-string-concat",
        "fold_string_concat",
        'x = "a" + "b"\n',
        "def f():\n    return 1\n",
    ),
    "redundant_lambda": (
        "redundant-lambda",
        "drop_redundant_lambda",
        "y = sorted(xs, key=lambda x: g(x))\n",
        "def f():\n    return 1\n",
    ),
    "augmented_assign": (
        "augmented-assign",
        "augmented_assign",
        "def f(x):\n    x = x + 1\n    return x\n",
        "def f():\n    return 1\n",
    ),
    "collection_literal": (
        "collection-literal",
        "modernize_collection_literal",
        "x = dict()\n",
        "def f():\n    return 1\n",
    ),
    "fstring_no_placeholder": (
        "fstring-no-placeholder",
        "fix_fstring_no_placeholder",
        'x = f"hello"\n',
        "def f():\n    return 1\n",
    ),
    # Wired this wave: on-disk plan_* transforms routed through the
    # plan_to_apply adapter, same refuse-on-unsafe / guarded-gate contract.
    "combine_nested_with": (
        "nested-with",
        "combine-nested-with",
        "def f():\n    with open('a') as a:\n        with open('b') as b:\n            return a, b\n",
        "def f():\n    return 1\n",
    ),
    "simplify_comprehension": (
        "comprehension",
        "simplify-comprehension",
        "def f(xs):\n    out = []\n    for x in xs:\n        out.append(x + 1)\n    return out\n",
        "def f():\n    return 1\n",
    ),
    "use_enumerate": (
        "use-enumerate",
        "use-enumerate",
        "def f(xs):\n    for i in range(len(xs)):\n        x = xs[i]\n        print(x)\n",
        "def f():\n    return 1\n",
    ),
    "simplify_len_comparison": (
        "len-comparison",
        "simplify-len-comparison",
        "def f(xs):\n    if len(xs) > 0:\n        return 1\n    return 0\n",
        "def f():\n    return 1\n",
    ),
    # Wired this wave: seven more on-disk plan_* transforms routed through the
    # plan_to_apply adapter, same refuse-on-unsafe / guarded-gate contract.
    # transform_type is the plan's ``new`` label (hyphenated).
    "simplify_bool_return": (
        "simplify-bool-return",
        "simplify-bool-return",
        "def f(c):\n    if c:\n        return True\n    else:\n        return False\n",
        "def f():\n    return 1\n",
    ),
    "simplify_ternary_bool": (
        "ternary-bool",
        "simplify-ternary-bool",
        "def f(c):\n    return True if c else False\n",
        "def f():\n    return 1\n",
    ),
    "simplify_dict_get": (
        "dict-get-ternary",
        "simplify-dict-get",
        "def f(x, k):\n    return x[k] if k in x else 0\n",
        "def f():\n    return 1\n",
    ),
    "dict_comprehension": (
        "dict-comprehension",
        "dict-comprehension",
        "def f(xs):\n    out = {}\n    for x in xs:\n        out[x] = x + 1\n    return out\n",
        "def f():\n    return 1\n",
    ),
    "simplify_negated_comparison": (
        "ordering-negation",
        "simplify-negated-comparison",
        "def f(a, b):\n    return not a < b\n",
        "def f():\n    return 1\n",
    ),
    "remove_pointless_pass": (
        "pointless-pass",
        "remove-pointless-pass",
        "def f():\n    x = 1\n    pass\n    return x\n",
        "def f():\n    return 1\n",
    ),
    "fix_assert_tuple": (
        "assert-tuple",
        "fix-assert-tuple",
        'def f(c):\n    assert (c, "msg")\n',
        "def f():\n    return 1\n",
    ),
    # Wired this wave: one more on-disk plan_* transform routed through the
    # plan_to_apply adapter. The match has a PROVABLY-BOOL operand (a Compare),
    # so `(a < b) == True` -> `(a < b)` is value-preserving; the no-match source
    # has nothing to simplify. (A bare-name `x == True` is also refused — it is
    # not provably bool — proven separately in test_bool_comparison_skips_bare_name.)
    "simplify_bool_comparison": (
        "bool-comparison",
        "simplify-bool-comparison",
        "def f(a, b):\n    return (a < b) == True\n",
        "def f():\n    return 1\n",
    ),
}


def test_all_six_action_types_registered() -> None:
    """Every new transform has a change-strategy hint AND a direct dispatch."""
    dispatch = IdeaActionBridge._simplify_dispatch()
    for action_type in _CASES:
        assert action_type in IdeaActionBridge._ACTION_STRATEGY, action_type
        assert action_type in dispatch, action_type
        # The change-strategy hint is a non-empty list (the convention used by
        # every other _ACTION_STRATEGY entry).
        hint = IdeaActionBridge._ACTION_STRATEGY[action_type]
        assert isinstance(hint, list) and hint and hint[0]


def test_dispatch_table_is_deterministic() -> None:
    """Same call -> same set of dispatch keys (no time/random)."""
    a = set(IdeaActionBridge._simplify_dispatch())
    b = set(IdeaActionBridge._simplify_dispatch())
    assert a == b == set(_CASES)


def test_each_fact_routes_to_an_executable_action() -> None:
    """Each seeding fact maps to its action_type and is executable."""
    for action_type, (fact_label, *_rest) in _CASES.items():
        assert fact_label in _FACT_ACTIONS, fact_label
        mapped_action, _desc, executable = _FACT_ACTIONS[fact_label]
        assert mapped_action == action_type
        assert executable is True


def _step(action_type: str, target: str) -> ActionStep:
    return ActionStep(
        branch_path="x.0",
        title="t",
        operator="root",
        subject=target,
        action_type=action_type,
        target=target,
        executable=True,
    )


def test_dispatch_returns_patch_on_match(tmp_path: Path) -> None:
    """The bridge's own _generate path produces the transform's real patch."""
    bridge = IdeaActionBridge()
    for action_type, (_fact, transform_type, match_src, _no) in _CASES.items():
        rel = f"{action_type}_match.py"
        (tmp_path / rel).write_text(match_src, encoding="utf-8")
        result = bridge._generate(_step(action_type, rel), str(tmp_path))
        assert result is not None, action_type
        assert result.transform_type == transform_type
        assert result.patch_requests
        pr = result.patch_requests[0]
        assert pr["path"] == rel
        # A real, behaviour-preserving rewrite: changed and re-parseable.
        assert pr["new_content"] != match_src
        assert pr["expected_old_content"] == match_src
        import ast

        ast.parse(pr["new_content"])


def test_dispatch_returns_none_on_non_match(tmp_path: Path) -> None:
    """A source with nothing to simplify -> the transform refuses (None)."""
    bridge = IdeaActionBridge()
    for action_type, (_fact, _tt, _match, no_src) in _CASES.items():
        rel = f"{action_type}_nomatch.py"
        (tmp_path / rel).write_text(no_src, encoding="utf-8")
        result = bridge._generate(_step(action_type, rel), str(tmp_path))
        assert result is None, action_type


def test_dispatch_returns_none_on_missing_file(tmp_path: Path) -> None:
    """No file -> graceful None (no raise) for every new transform."""
    bridge = IdeaActionBridge()
    for action_type in _CASES:
        result = bridge._generate(_step(action_type, "does_not_exist.py"), str(tmp_path))
        assert result is None, action_type


def test_dispatch_returns_none_on_non_python_target(tmp_path: Path) -> None:
    """A non-.py target is never routed to a Python AST transform."""
    bridge = IdeaActionBridge()
    rel = "notes.txt"
    (tmp_path / rel).write_text("if a:\n    if b:\n        pass\n", encoding="utf-8")
    result = bridge._generate(_step("merge_nested_if", rel), str(tmp_path))
    assert result is None


def test_apply_step_runs_through_guarded_path(tmp_path: Path) -> None:
    """An autonomous apply_step actually rewrites a matching file via the same
    snapshot/apply gate as every other transform (proves the registration is
    wired end-to-end, not just present in a table)."""
    bridge = IdeaActionBridge()
    rel = "merge_apply.py"
    src = _CASES["merge_nested_if"][2]
    (tmp_path / rel).write_text(src, encoding="utf-8")
    out = bridge.apply_step(_step("merge_nested_if", rel), str(tmp_path),
                            mode="autonomous")
    assert out["applied"] is True
    assert out["transform_type"] == "merge_nested_if"
    written = (tmp_path / rel).read_text(encoding="utf-8")
    assert written != src
    assert "and" in written  # the two guards were collapsed into one `and`
    import ast

    ast.parse(written)


def test_report_mode_never_applies(tmp_path: Path) -> None:
    """Report mode is read-only: a new transform step is refused, not applied."""
    bridge = IdeaActionBridge()
    rel = "merge_report.py"
    (tmp_path / rel).write_text(_CASES["merge_nested_if"][2], encoding="utf-8")
    out = bridge.apply_step(_step("merge_nested_if", rel), str(tmp_path),
                            mode="report")
    assert out["applied"] is False


# --- The newly-promoted transforms each flow through the full apply gate. ---

# action_types added in this wave (everything beyond the original six).
_NEW = {
    "chain_comparison", "set_literal", "startswith_tuple", "not_in_simplify",
    "tuple_membership", "dict_literal", "double_not", "swap_via_tuple",
    "membership_set", "percent_string_concat", "redundant_lambda",
    "augmented_assign", "collection_literal", "fstring_no_placeholder",
    "combine_nested_with", "simplify_comprehension", "use_enumerate",
    "simplify_len_comparison",
    # Seven on-disk plan_* transforms wired this wave.
    "simplify_bool_return", "simplify_ternary_bool", "simplify_dict_get",
    "dict_comprehension", "simplify_negated_comparison",
    "remove_pointless_pass", "fix_assert_tuple",
    # One more on-disk plan_* transform wired this wave.
    "simplify_bool_comparison",
}


def test_new_labels_promoted_to_executable() -> None:
    """Every newly-wired label is executable, has a dispatch + strategy, and
    points at a transform_type the transform actually stamps."""
    dispatch = IdeaActionBridge._simplify_dispatch()
    for action_type in _NEW:
        assert action_type in dispatch, action_type
        assert action_type in IdeaActionBridge._ACTION_STRATEGY, action_type
        fact_label, transform_type, *_ = _CASES[action_type]
        mapped_action, _desc, executable = _FACT_ACTIONS[fact_label]
        assert mapped_action == action_type
        assert executable is True


def test_new_transforms_apply_through_guarded_gate(tmp_path: Path) -> None:
    """Each newly-promoted transform actually rewrites its matching file via the
    SAME snapshot/apply gate (autonomous), proving the wiring is end-to-end."""
    import ast

    bridge = IdeaActionBridge()
    for action_type in _NEW:
        _fact, transform_type, match_src, _no = _CASES[action_type]
        rel = f"{action_type}_apply.py"
        (tmp_path / rel).write_text(match_src, encoding="utf-8")
        out = bridge.apply_step(_step(action_type, rel), str(tmp_path),
                                mode="autonomous")
        assert out["applied"] is True, action_type
        assert out["transform_type"] == transform_type, action_type
        written = (tmp_path / rel).read_text(encoding="utf-8")
        assert written != match_src, action_type
        ast.parse(written)


def test_new_transforms_verify_and_keep_on_green(tmp_path: Path) -> None:
    """With verify on, a matching rewrite that leaves a green suite is KEPT
    (not rolled back) — the full snapshot -> write -> test-verify path runs and
    passes for a behaviour-preserving change."""
    bridge = IdeaActionBridge()
    # A trivially-green test so the suite passes after the (behaviour-preserving)
    # rewrite of the sibling module.
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")

    _fact, transform_type, match_src, _no = _CASES["set_literal"]
    rel = "mod_under_change.py"
    (tmp_path / rel).write_text(match_src, encoding="utf-8")
    out = bridge.apply_step(_step("set_literal", rel), str(tmp_path),
                            mode="autonomous", verify=True, run_tests=False)
    assert out["applied"] is True
    assert out.get("rolled_back") is False
    assert out.get("verified") is True
    # File stays changed (kept), not restored to its pre-patch snapshot.
    assert (tmp_path / rel).read_text(encoding="utf-8") != match_src


def test_new_transforms_rollback_on_red(tmp_path: Path) -> None:
    """With verify on, if the suite goes red after a write, EVERY changed file
    is restored to its snapshot — the auto-rollback gate is not weakened for the
    promoted transforms."""
    bridge = IdeaActionBridge()
    # A suite that always fails, so any applied change must roll back.
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_red.py").write_text(
        "def test_red():\n    assert False\n", encoding="utf-8")

    _fact, _tt, match_src, _no = _CASES["double_not"]
    rel = "mod_rollback.py"
    (tmp_path / rel).write_text(match_src, encoding="utf-8")
    # run_tests=False skips the PRE-write safety-gate test check (so the write
    # happens), but verify=True still runs the POST-write suite — which is red,
    # so the change must be rolled back.
    out = bridge.apply_step(_step("double_not", rel), str(tmp_path),
                            mode="autonomous", verify=True, run_tests=False)
    assert out["applied"] is False
    assert out.get("rolled_back") is True
    # The original content was restored byte-for-byte.
    assert (tmp_path / rel).read_text(encoding="utf-8") == match_src


def test_new_transforms_unsafe_input_declines(tmp_path: Path) -> None:
    """An input the transform can't act on safely returns None -> the step stays
    safe (no patch, nothing applied), for every promoted transform."""
    bridge = IdeaActionBridge()
    for action_type in _NEW:
        _fact, _tt, _match, no_src = _CASES[action_type]
        rel = f"{action_type}_unsafe.py"
        (tmp_path / rel).write_text(no_src, encoding="utf-8")
        before = (tmp_path / rel).read_text(encoding="utf-8")
        out = bridge.apply_step(_step(action_type, rel), str(tmp_path),
                                mode="autonomous", verify=True, run_tests=True)
        assert out["applied"] is False, action_type
        assert out["reason"] == "no applicable patch generated", action_type
        # Untouched: the refusal never wrote anything.
        assert (tmp_path / rel).read_text(encoding="utf-8") == before, action_type


def test_new_transforms_report_mode_never_applies(tmp_path: Path) -> None:
    """Report mode is read-only for every promoted transform too."""
    bridge = IdeaActionBridge()
    for action_type in _NEW:
        _fact, _tt, match_src, _no = _CASES[action_type]
        rel = f"{action_type}_report.py"
        (tmp_path / rel).write_text(match_src, encoding="utf-8")
        out = bridge.apply_step(_step(action_type, rel), str(tmp_path),
                                mode="report")
        assert out["applied"] is False, action_type
        # Read-only: the file is never modified.
        assert (tmp_path / rel).read_text(encoding="utf-8") == match_src, action_type


def test_bool_comparison_skips_bare_name(tmp_path: Path) -> None:
    """``x == True`` on a BARE name is unsound (``2 == True`` is False but ``2``
    is truthy), so the transform must REFUSE it — proving the wiring inherits the
    transform's provably-bool guard and fabricates nothing for the unsafe case."""
    bridge = IdeaActionBridge()
    rel = "bare_name_unsound.py"
    src = "def f(x):\n    return x == True\n"
    (tmp_path / rel).write_text(src, encoding="utf-8")
    result = bridge._generate(_step("simplify_bool_comparison", rel), str(tmp_path))
    assert result is None
    # And an autonomous apply leaves the file byte-for-byte untouched.
    out = bridge.apply_step(_step("simplify_bool_comparison", rel), str(tmp_path),
                            mode="autonomous")
    assert out["applied"] is False
    assert (tmp_path / rel).read_text(encoding="utf-8") == src
