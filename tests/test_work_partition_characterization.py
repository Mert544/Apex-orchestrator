"""Characterization: refactored partition_work matches the original byte-for-byte.

Loads the pre-refactor source straight from ``git show HEAD:...`` as an isolated
module (the golden), and runs it alongside the live (refactored) module over many
task configurations covering every branch (empty, single, disjoint, shared-file,
blast-radius chain, unresolved tasks, skipped files, duplicate/normalisable
paths). It asserts the full Partition output (order + tasks + files) is identical.
"""

from __future__ import annotations

import importlib.util
import itertools
import subprocess
import sys

import pytest

from app.engine.work_partition import Task, partition_work


def _load_original():
    """Import the HEAD version of work_partition under a fresh module name."""
    src = subprocess.run(
        ["git", "show", "HEAD:app/engine/work_partition.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    spec = importlib.util.spec_from_loader("_work_partition_original", loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_work_partition_original"] = mod
    exec(compile(src, "<HEAD:work_partition.py>", "exec"), mod.__dict__)
    return mod


_ORIGINAL = _load_original()


def _result_repr(parts):
    """Total-order-sensitive, fully-content-sensitive representation."""
    return [(p.tasks, p.files) for p in parts]


def _reference(project_root, tasks):
    """Golden output: the original partition_work, loaded from HEAD."""
    orig_tasks = [_ORIGINAL.Task(t.name, list(t.files)) for t in tasks]
    return _ORIGINAL.partition_work(project_root, orig_tasks)


@pytest.fixture
def project(tmp_path):
    """A small import graph: b imports a; c imports b; d standalone."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("X = 1\n")
    (tmp_path / "pkg" / "b.py").write_text("from pkg.a import X\n")
    (tmp_path / "pkg" / "c.py").write_text("from pkg.b import X\n")
    (tmp_path / "pkg" / "d.py").write_text("Y = 2\n")
    return tmp_path


def _candidate_tasks():
    return [
        Task("t_empty", []),
        Task("t_skip", ["node_modules/x.js"]),
        Task("t_a", ["pkg/a.py"]),
        Task("t_a_dup", ["pkg/a.py", "./pkg/a.py", "pkg/a.py"]),
        Task("t_b", ["pkg/b.py"]),
        Task("t_c", ["pkg/c.py"]),
        Task("t_d", ["pkg/d.py"]),
        Task("t_unresolved", ["does_not_exist.py"]),
        Task("t_multi", ["pkg/a.py", "pkg/d.py"]),
    ]


@pytest.mark.parametrize("k", [0, 1, 2, 3])
def test_byte_identical_across_combinations(project, k):
    tasks = _candidate_tasks()
    mismatches = 0
    for combo in itertools.combinations(tasks, k):
        got = _result_repr(partition_work(project, list(combo)))
        want = _result_repr(_reference(project, list(combo)))
        if got != want:
            mismatches += 1
    assert mismatches == 0


def test_explicit_branches(project):
    cases = [
        [],
        [Task("solo", ["pkg/a.py"])],
        [Task("x", ["pkg/a.py"]), Task("y", ["pkg/d.py"])],  # disjoint
        [Task("x", ["pkg/a.py"]), Task("y", ["pkg/a.py"])],  # shared file
        [Task("x", ["pkg/a.py"]), Task("y", ["pkg/c.py"])],  # blast-radius chain
        [Task("x", ["pkg/a.py"]), Task("u", [])],  # unresolved folds all
        [Task("x", []), Task("y", [])],  # all unresolved
        [Task("z", ["pkg/a.py"]), Task("a", ["pkg/a.py"])],  # name-order sort
    ]
    for tasks in cases:
        assert _result_repr(partition_work(project, tasks)) == _result_repr(
            _reference(project, tasks)
        )


def test_full_chain_collapses(project):
    tasks = [
        Task("ta", ["pkg/a.py"]),
        Task("tb", ["pkg/b.py"]),
        Task("tc", ["pkg/c.py"]),
        Task("td", ["pkg/d.py"]),
    ]
    parts = partition_work(project, tasks)
    assert _result_repr(parts) == _result_repr(_reference(project, tasks))
