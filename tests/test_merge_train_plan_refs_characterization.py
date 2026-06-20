"""Characterization test: refactored ``plan_refs`` is byte-identical to HEAD.

Loads BOTH the current (refactored) ``scripts/merge_train.py`` and the HEAD
snapshot of the same file as separate modules, stubs the git/partition seams with
identical deterministic fakes in each, then drives ``plan_refs`` across many input
shapes covering every branch (add-only, clashing add-only, parallel, serial, empty,
duplicate refs). Every ``RefPlan`` field must match exactly between the two.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIVE_PATH = ROOT / "scripts" / "merge_train.py"


@pytest.fixture(autouse=True)
def _restore_sys_modules():
    """Snapshot ``sys.modules`` and restore it exactly after each test.

    ``_load_module`` and ``_install_fakes`` inject scratch modules plus fake
    ``app`` / ``app.engine`` / ``app.engine.work_partition`` entries into the
    global import table. Without teardown those fakes (which lack the real
    module's symbols/``__file__``) leak into later tests that resolve
    ``app.engine.work_partition`` freshly, causing order-dependent failures.
    Saving and restoring the table keeps the test hermetic.
    """
    saved = dict(sys.modules)
    try:
        yield
    finally:
        # Drop anything this test added.
        for name in set(sys.modules) - set(saved):
            del sys.modules[name]
        # Restore anything this test replaced or removed.
        for name, mod in saved.items():
            sys.modules[name] = mod


def _load_module(name: str, source: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__file__ = str(LIVE_PATH)
    sys.modules[name] = mod
    exec(compile(source, str(LIVE_PATH), "exec"), mod.__dict__)
    return mod


def _head_source() -> str:
    return subprocess.run(
        ["git", "show", "HEAD:scripts/merge_train.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


# ---- Deterministic fakes for the git/partition seams ------------------------

# A fixed "base tree" of tracked files. Anything NOT here is a brand-new path.
_TRACKED = {"app/core.py", "app/util.py", "README.md", "shared/config.yaml"}

# Per-ref changed-file fixtures spanning every branch of plan_refs.
_CHANGED: dict[str, list[str]] = {
    # pure add-only, disjoint new files
    "worktree-agent-aaa": ["new/a1.py", "new/a2.py"],
    "worktree-agent-bbb": ["new/b1.py"],
    # two add-only candidates that CLASH on a shared new path -> demoted to rest
    "worktree-agent-clash1": ["new/shared.py", "new/c1.py"],
    "worktree-agent-clash2": ["new/shared.py", "new/c2.py"],
    # touches an existing tracked file -> never add-only
    "worktree-agent-existing": ["app/core.py"],
    # touches shared tracked file -> will overlap others in partition
    "worktree-agent-overlap1": ["shared/config.yaml", "x/o1.py"],
    "worktree-agent-overlap2": ["shared/config.yaml", "x/o2.py"],
    # disjoint existing-file toucher (parallel-safe)
    "worktree-agent-lone": ["app/util.py"],
    # ref with no changed files at all
    "worktree-agent-empty": [],
}


def _install_fakes(mod: types.ModuleType) -> None:
    mod.tracked_files = lambda base: set(_TRACKED)
    mod.changed_files = lambda base, ref: list(_CHANGED.get(ref, []))

    # Fake app.engine.work_partition: partition by simple file-set intersection
    # (deterministic union-find on shared paths), mirroring the real overlap idea.
    def partition_work(root, tasks):
        names = [t.name for t in tasks]
        files = {t.name: set(t.files) for t in tasks}
        parent = {n: n for n in names}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            parent[find(a)] = find(b)

        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if files[a] & files[b] or not files[a] or not files[b]:
                    union(a, b)
        groups: dict[str, list[str]] = {}
        for n in names:
            groups.setdefault(find(n), []).append(n)

        class _P:
            def __init__(self, task_names):
                self.tasks = sorted(task_names)

        return [_P(g) for g in groups.values()]

    class _Task:
        def __init__(self, name, files):
            self.name = name
            self.files = files

    fake_pkg = types.ModuleType("app")
    fake_engine = types.ModuleType("app.engine")
    fake_wp = types.ModuleType("app.engine.work_partition")
    fake_wp.Task = _Task
    fake_wp.partition_work = partition_work
    sys.modules.setdefault("app", fake_pkg)
    sys.modules.setdefault("app.engine", fake_engine)
    sys.modules["app.engine.work_partition"] = fake_wp


_INPUTS: list[list[str]] = [
    [],
    ["worktree-agent-aaa"],
    ["worktree-agent-empty"],
    ["worktree-agent-aaa", "worktree-agent-bbb"],
    ["worktree-agent-clash1", "worktree-agent-clash2"],
    ["worktree-agent-overlap1", "worktree-agent-overlap2"],
    ["worktree-agent-lone", "worktree-agent-existing"],
    ["worktree-agent-aaa", "worktree-agent-aaa", "worktree-agent-bbb"],  # dupes
    ["worktree-agent-bbb", "worktree-agent-aaa"],  # ordering
    list(_CHANGED.keys()),  # everything at once
    ["worktree-agent-overlap1", "worktree-agent-lone", "worktree-agent-aaa"],
]


def _plan_tuples(mod: types.ModuleType, base: str, refs: list[str]):
    return [
        (p.ref, list(p.changed), p.adds_only, p.group, list(p.peers))
        for p in mod.plan_refs(base, refs)
    ]


def test_plan_refs_byte_identical_to_head():
    live = _load_module("merge_train_live_eyml1y", LIVE_PATH.read_text())
    head = _load_module("merge_train_head_eyml1y", _head_source())
    _install_fakes(live)
    _install_fakes(head)

    mismatches = 0
    for refs in _INPUTS:
        for base in ("HEAD", "origin/main"):
            got = _plan_tuples(live, base, refs)
            want = _plan_tuples(head, base, refs)
            if got != want:
                mismatches += 1
            assert got == want, f"mismatch for refs={refs} base={base}"
    assert mismatches == 0


def test_branches_actually_exercised():
    """Sanity: the fixtures really produce add/parallel/serial groups."""
    live = _load_module("merge_train_live_branchcheck_eyml1y", LIVE_PATH.read_text())
    _install_fakes(live)
    # add-only (aaa), parallel (lone, disjoint existing toucher), serial (overlap1/2)
    plans = live.plan_refs(
        "HEAD",
        [
            "worktree-agent-aaa",
            "worktree-agent-lone",
            "worktree-agent-overlap1",
            "worktree-agent-overlap2",
        ],
    )
    groups = {p.group for p in plans}
    assert {"add", "parallel", "serial"} <= groups
    by_ref = {p.ref: p for p in plans}
    assert by_ref["worktree-agent-aaa"].group == "add"
    assert by_ref["worktree-agent-lone"].group == "parallel"
    assert by_ref["worktree-agent-overlap1"].group == "serial"
    assert by_ref["worktree-agent-overlap1"].peers == ["worktree-agent-overlap2"]

    # separately: the clashing add-only candidates are demoted out of "add"
    clash_plans = live.plan_refs(
        "HEAD", ["worktree-agent-clash1", "worktree-agent-clash2"]
    )
    assert all(p.group != "add" for p in clash_plans)
