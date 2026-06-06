"""End-to-end guard: one harden pass converges every auto-fixable issue-type.

Builds a module that mixes eval, a bare-except, a mutable default, an `== None`
comparison, and an identity-vs-literal bug, then runs the real apply_plan harden
path (test-verified). All of them must be fixed in a single pass with no
rollback — the proof that detector -> ladder -> transform -> convergence are
coordinated across fix-types.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.models.idea import ActionPlan, IdeaNode


def test_harden_converges_all_fix_types_in_one_pass(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    src = tmp_path / "app" / "messy.py"
    src.write_text(
        "def run(rule, x, items=[]):\n"
        "    try:\n"
        "        v = eval(rule)\n"          # -> ast.literal_eval
        "    except:\n"                      # -> except Exception
        "        v = 0\n"
        "    if x == None:\n"                # -> is None
        "        return items\n"
        "    if x is 5:\n"                   # -> x == 5
        "        return v\n"
        "    return v\n"
    )
    (tmp_path / "tests" / "test_messy.py").write_text(
        "from app.messy import run\n\ndef test_run():\n    assert run('1', None) == []\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n")

    idea = IdeaNode(id="i", title="Harden: app/messy.py", subject="app/messy.py",
                    operator="harden", operator_chain=["harden"],
                    source_facts=["sensitive-path: app/messy.py"])
    plan = ActionPlan(steps=[IdeaActionBridge().plan_idea(idea)], stats={}, mode="supervised")
    res = IdeaActionBridge().apply_plan(plan, str(tmp_path), mode="supervised", verify=True)

    assert res["rolled_back"] == 0
    after = src.read_text()
    assert "ast.literal_eval(rule)" in after
    assert "except Exception:" in after and "except:" not in after
    assert "items=None" in after and "if items is None:" in after   # mutable-default guard
    assert "x is None" in after                                     # modernized
    assert "x == 5" in after                                        # identity-literal fixed
    # the project's own test still passes (verified, so the file is correct)
