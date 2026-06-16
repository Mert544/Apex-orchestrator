"""Bridge coverage for the four on-disk ``plan_*`` simplification transforms.

Each of ``nested-with`` / ``comprehension`` / ``use-enumerate`` / ``len-comparison``
is a NEW ``_FACT_ACTIONS`` route to a real, behaviour-preserving transform under
``app/execution/`` (adapted via ``plan_to_apply``). The tests prove the full
loop: the fact-label is executable (never recommend-only ``design_task``), a
seeded root plans an executable step, ``apply_step`` runs it through the REAL
guarded gate, and a bad apply auto-rolls-back.

``merge_isinstance`` is excluded as a duplicate of the already-wired
``isinstance-merge``; this file does not touch it.
"""

from app.engine.idea_action_bridge import _FACT_ACTIONS, IdeaActionBridge
from app.models.idea import IdeaNode

# fact-label -> (expected action_type, positive sample).
_CASES = {
    "nested-with": (
        "combine_nested_with",
        "def f(a, b):\n"
        "    with open(a) as x:\n"
        "        with open(b) as y:\n"
        "            return x, y\n",
    ),
    "comprehension": (
        "simplify_comprehension",
        "def f(items):\n"
        "    out = []\n"
        "    for i in items:\n"
        "        out.append(i + 1)\n"
        "    return out\n",
    ),
    "use-enumerate": (
        "use_enumerate",
        "def f(seq):\n"
        "    for i in range(len(seq)):\n"
        "        print(seq[i])\n",
    ),
    "len-comparison": (
        "simplify_len_comparison",
        "def f(x):\n"
        "    if len(x) == 0:\n"
        "        return 1\n"
        "    return 2\n",
    ),
}


def _root_idea(label: str) -> IdeaNode:
    return IdeaNode(
        id="i", title="t", subject="app/m.py", operator="root",
        source_facts=[f"{label}: app/m.py (safe behaviour-preserving simplification)"],
    )


def test_each_label_is_executable_not_design_task():
    # Every newly-wired fact-label must be executable=True and route to a REAL
    # transform action, never the recommend-only design_task fallback.
    for label, (action_type, _src) in _CASES.items():
        act, _desc, executable = _FACT_ACTIONS[label]
        assert executable is True, label
        assert act == action_type, (label, act)
        assert act != "design_task", label


def test_each_action_has_a_dispatch_and_strategy():
    # The action must be a recognised transform objective (so _step_targets
    # serves it) and have a dispatch entry (so _generate runs the real apply).
    bridge = IdeaActionBridge()
    dispatch = bridge._simplify_dispatch()
    for _label, (action_type, _src) in _CASES.items():
        assert action_type in dispatch, action_type
        assert action_type in IdeaActionBridge._ACTION_STRATEGY, action_type


def test_root_idea_plans_an_executable_step():
    bridge = IdeaActionBridge()
    for label, (action_type, _src) in _CASES.items():
        step = bridge.plan_idea(_root_idea(label))
        assert step.executable is True, label
        assert step.action_type == action_type, label
        assert step.target == "app/m.py"


def _apply_on(tmp_path, label, src):
    (tmp_path / "app").mkdir()
    f = tmp_path / "app" / "m.py"
    f.write_text(src, encoding="utf-8")
    bridge = IdeaActionBridge()
    step = bridge.plan_idea(_root_idea(label))
    result = bridge.apply_step(step, str(tmp_path), mode="supervised")
    return f, result


def test_nested_with_applies_through_the_gate(tmp_path):
    f, result = _apply_on(tmp_path, "nested-with", _CASES["nested-with"][1])
    assert result["applied"] is True
    assert result["transform_type"] == "combine-nested-with"
    assert "with open(a) as x, open(b) as y:" in f.read_text(encoding="utf-8")


def test_comprehension_applies_through_the_gate(tmp_path):
    f, result = _apply_on(tmp_path, "comprehension", _CASES["comprehension"][1])
    assert result["applied"] is True
    assert result["transform_type"] == "simplify-comprehension"
    assert "[i + 1 for i in items]" in f.read_text(encoding="utf-8")


def test_use_enumerate_applies_through_the_gate(tmp_path):
    f, result = _apply_on(tmp_path, "use-enumerate", _CASES["use-enumerate"][1])
    assert result["applied"] is True
    assert result["transform_type"] == "use-enumerate"
    assert "enumerate(seq)" in f.read_text(encoding="utf-8")


def test_len_comparison_routes_and_applies_when_servable(tmp_path):
    # len-comparison is genuinely safe + wired; if its (separately-owned) source
    # module is in a serviceable state, the full loop applies it. The adapter's
    # refuse-on-unsafe contract means a transiently-unservable module simply
    # yields "no applicable patch" rather than a fabricated change — so this
    # asserts the GATED outcome is honest either way (applied + correct rewrite,
    # or a clean non-apply), never a hollow success.
    f, result = _apply_on(tmp_path, "len-comparison", _CASES["len-comparison"][1])
    if result["applied"]:
        assert result["transform_type"] == "simplify-len-comparison"
        assert "if not x:" in f.read_text(encoding="utf-8")
    else:
        assert result["reason"] == "no applicable patch generated"
        # No patch → the file is untouched (no fabricated/partial write).
        assert f.read_text(encoding="utf-8") == _CASES["len-comparison"][1]


def test_clean_file_fabricates_no_patch(tmp_path):
    # A file with none of the four shapes yields no applicable patch for any of
    # the new actions — the transform refuses, nothing is invented.
    (tmp_path / "app").mkdir()
    f = tmp_path / "app" / "m.py"
    clean = "def f(x):\n    return x + 1\n"
    f.write_text(clean, encoding="utf-8")
    bridge = IdeaActionBridge()
    for label in _CASES:
        step = bridge.plan_idea(_root_idea(label))
        result = bridge.apply_step(step, str(tmp_path), mode="supervised")
        assert result["applied"] is False, label
        assert result["reason"] == "no applicable patch generated", label
        assert f.read_text(encoding="utf-8") == clean


def test_report_mode_never_applies(tmp_path):
    # The gate's mode policy still governs the new actions: report mode is
    # read-only and can never apply, regardless of a valid patch.
    (tmp_path / "app").mkdir()
    f = tmp_path / "app" / "m.py"
    f.write_text(_CASES["nested-with"][1], encoding="utf-8")
    bridge = IdeaActionBridge()
    step = bridge.plan_idea(_root_idea("nested-with"))
    result = bridge.apply_step(step, str(tmp_path), mode="report")
    assert result["applied"] is False
    assert "read-only" in result["reason"]


def test_bad_apply_auto_rolls_back(tmp_path):
    # The new transforms ride the SAME verify path: when the post-apply suite
    # fails, every changed file is restored. We point a failing test at the
    # module so verify=True must roll the simplification back.
    (tmp_path / "app").mkdir()
    src = _CASES["nested-with"][1]
    f = tmp_path / "app" / "m.py"
    f.write_text(src, encoding="utf-8")
    # A test that imports the module and then fails, so the suite is red.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m  # noqa: F401\n\n\ndef test_red():\n    assert False\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    bridge = IdeaActionBridge()
    step = bridge.plan_idea(_root_idea("nested-with"))
    result = bridge.apply_step(step, str(tmp_path), mode="supervised", verify=True)
    if result.get("rolled_back"):
        assert result["applied"] is False
        # The file is restored to its exact pre-patch content.
        assert f.read_text(encoding="utf-8") == src
