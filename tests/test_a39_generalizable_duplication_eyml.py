"""Autonomous-39 W1: the PRIMARY-discovery seeder fact ``generalizable-duplication``
is now an EXECUTABLE extract-shared-helper move, not a human ``design_task``.

The cross-module near-duplicate signal used to be devolved to a person ("you
design the abstraction"). ``plan_near_dup_extract`` makes the parameterization
decision deterministically (and BLOCKS with an empty plan on the slightest
doubt), so the seeder fact is flipped to the delegated ``dedup_parameterized``
action: the bridge re-runs the objective's own actionable-group gate and lands a
shared helper through ``apply_rename(impact_scope=True)`` with auto-rollback.

The seeder names the idea with the JOINED pair ``"{modules[0]} + {modules[1]}"``,
so the step target reaching the lander is an ``"A + B"`` string; the lander splits
on ``" + "`` and matches a group touching EITHER module. These tests lock:
  * the flip (action_type ``dedup_parameterized``, executable True);
  * a real cross-module near-dup LANDS one shared helper, suite GREEN, dup gone;
  * a non-actionable signal is an HONEST no-op (writes nothing, never fake-green);
  * the joined-subject split still lands when only the SECOND module participates;
  * a single-module target stays byte-identical (the objective-fact path is intact).
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge, _FACT_ACTIONS
from app.models.idea import IdeaNode

# A 5-statement block that differs across two modules only at ONE constant
# (10 vs 20) — the simplest real cross-module parameterizable near-duplicate.
_DUP_A = "def alpha(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = c + 10\n    return d\n"
_DUP_B = "def beta(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n    d = c + 20\n    return d\n"


def _dup_project(root: Path, with_test: bool = False) -> None:
    """Two modules sharing a constant-only-differing 5-line block. With
    ``with_test`` a real green test exercises BOTH functions so the impacted-test
    gate has something to (re)run after the refactor (behaviour preserved)."""
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "a.py").write_text(_DUP_A, encoding="utf-8")
    (root / "pkg" / "b.py").write_text(_DUP_B, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    if with_test:
        (root / "tests").mkdir()
        (root / "tests" / "test_ab.py").write_text(
            "from pkg.a import alpha\nfrom pkg.b import beta\n\n"
            "def test_alpha():\n    assert alpha(5) == 25\n\n"
            "def test_beta():\n    assert beta(5) == 35\n",
            encoding="utf-8")


def _dup_idea(subject: str) -> IdeaNode:
    """A PRIMARY-discovery ``generalizable-duplication`` root, exactly as the
    seeder emits it: a JOINED ``"A + B"`` subject and the fact label on
    ``source_facts[0]`` (``_root_action`` reads ``fact.split(":")[0]``)."""
    return IdeaNode(
        id="g", title=f"Generalize the duplicated logic across {subject}",
        subject=subject, operator="root",
        source_facts=[f"generalizable-duplication: near-identical 5-line blocks "
                      f"recur across {subject}"],
    )


# ── 1. the flip itself: the fact row is now executable ────────────────────────

def test_fact_action_is_executable_dedup_parameterized():
    action_type, _desc, executable = _FACT_ACTIONS["generalizable-duplication"]
    assert action_type == "dedup_parameterized"
    assert executable is True


def test_plan_idea_surfaces_executable_extract():
    step = IdeaActionBridge().plan_idea(_dup_idea("pkg/a.py + pkg/b.py"))
    assert step.action_type == "dedup_parameterized"
    assert step.executable is True
    # The joined subject is carried verbatim as the (human-readable) target; the
    # lander splits it. It must NOT have been silently dropped to "".
    assert step.target == "pkg/a.py + pkg/b.py"


# ── 2. it LANDS a shared helper on a real cross-module near-dup, suite GREEN ───

def test_applies_and_lands_shared_helper_suite_green(tmp_path: Path):
    _dup_project(tmp_path, with_test=True)
    step = IdeaActionBridge().plan_idea(_dup_idea("pkg/a.py + pkg/b.py"))

    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised",
                                        verify=True)
    assert res["applied"] is True, res
    assert res["transform_type"] == "dedup_parameterized"
    assert res.get("suite_green") is True
    assert sorted(res["changed_files"]) == ["pkg/a.py", "pkg/b.py"]

    a_src = (tmp_path / "pkg" / "a.py").read_text()
    b_src = (tmp_path / "pkg" / "b.py").read_text()
    # ONE shared helper lifts the block; each call site passes its own constant.
    assert "def _shared_1(n, p0):" in a_src
    assert "return _shared_1(n, 10)" in a_src
    assert "return _shared_1(n, 20)" in b_src
    # The other module imports the helper, it does not redefine it.
    assert "import _shared_1" in b_src
    assert "def _shared_1(" not in b_src

    # The duplication is GONE: the detector no longer reports the group.
    from app.engine.near_dup import find_near_duplicates
    assert find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2) == []


# ── 3. a non-actionable signal is an HONEST no-op (writes nothing) ────────────

def test_non_actionable_is_honest_noop_writes_nothing(tmp_path: Path):
    # Structurally identical blocks but a DIVERGENT live-out signature (`d` is
    # read after the block in beta only), so ``plan_near_dup_extract`` BLOCKS —
    # no rewrite is producible. The flipped action must honestly no-op, never
    # fake a green.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    a_before = ("def alpha(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n"
                "    d = c + 10\n    e = d + 1\n    return e\n")
    b_before = ("def beta(n):\n    a = n + 1\n    b = a * 2\n    c = b + 3\n"
                "    d = c + 20\n    e = d + 1\n    return d + e\n")
    (tmp_path / "pkg" / "a.py").write_text(a_before, encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text(b_before, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")

    step = IdeaActionBridge().plan_idea(_dup_idea("pkg/a.py + pkg/b.py"))
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised",
                                        verify=True)
    assert res["applied"] is False
    assert res["transform_type"] == "dedup_parameterized"
    # A disclosed reason is carried (no silent success).
    assert res.get("reason")
    # NOTHING was written — both modules are byte-identical to before.
    assert (tmp_path / "pkg" / "a.py").read_text() == a_before
    assert (tmp_path / "pkg" / "b.py").read_text() == b_before


def test_unmatched_target_is_empty_noop_plan(tmp_path: Path):
    # No actionable group touches EITHER side of the joined target → the lander
    # returns an empty no-op RenamePlan (the honest no-op fed to apply_rename).
    _dup_project(tmp_path)
    plan = IdeaActionBridge._plan_dedup_parameterized_lander()(
        str(tmp_path), "pkg/nope1.py + pkg/nope2.py")
    assert not plan.new_contents
    assert plan.old == "pkg/nope1.py + pkg/nope2.py"
    assert plan.new == "dedup-parameterized"


# ── 4. the joined-subject split: lands when only the SECOND module participates ─

def test_joined_subject_split_matches_second_module(tmp_path: Path):
    # The actionable group touches pkg/a.py + pkg/b.py, but the joined target's
    # FIRST side names a non-participating module. The split must still find the
    # group via the SECOND side — regression-locks the split path.
    _dup_project(tmp_path)
    lander = IdeaActionBridge._plan_dedup_parameterized_lander()
    plan = lander(str(tmp_path), "pkg/absent.py + pkg/b.py")
    assert plan.new_contents, f"split should match via the 2nd module, {plan.blockers}"
    assert sorted(plan.new_contents) == ["pkg/a.py", "pkg/b.py"]


# ── 5. a single-module target stays byte-identical (objective-fact path intact) ─

def test_single_module_target_unchanged(tmp_path: Path):
    # A non-joined target (no " + ") splits to a one-element list, so matching is
    # identical to the pre-flip lander: the module that participates in the group
    # still matches it. (This is the ``apex develop dedup-parameterized`` shape.)
    _dup_project(tmp_path)
    lander = IdeaActionBridge._plan_dedup_parameterized_lander()
    plan = lander(str(tmp_path), "pkg/a.py")
    assert plan.new_contents, f"single-module match must be unchanged, {plan.blockers}"
    assert sorted(plan.new_contents) == ["pkg/a.py", "pkg/b.py"]
    # And a single-module target that touches NO group is still an honest no-op.
    miss = lander(str(tmp_path), "pkg/__init__.py")
    assert not miss.new_contents
    assert miss.old == "pkg/__init__.py"
