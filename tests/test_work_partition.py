from pathlib import Path

from app.engine.work_partition import (
    Partition,
    Task,
    max_parallelism,
    partition_work,
    render_partition_markdown,
)


def _make_chain(root: Path) -> None:
    """Plant a synthetic project: app.a -> app.b -> app.c import chain.

    Mirrors tests/test_blast_radius.py so the blast-radius overlap path is real:
    editing app/c.py has app/b.py and app/a.py as transitive dependents.
    """
    (root / "app").mkdir(parents=True)
    (root / "app" / "a.py").write_text("import app.b\n", encoding="utf-8")
    (root / "app" / "b.py").write_text("import app.c\n", encoding="utf-8")
    (root / "app" / "c.py").write_text("def c():\n    return 1\n", encoding="utf-8")


def _make_isolated(root: Path) -> None:
    """Plant three mutually-unrelated modules in separate packages — no edges."""
    for pkg, mod, body in (
        ("api", "h", "def h():\n    return 1\n"),
        ("lib", "u", "def u():\n    return 2\n"),
        ("core", "k", "def k():\n    return 3\n"),
    ):
        (root / pkg).mkdir(parents=True, exist_ok=True)
        (root / pkg / f"{mod}.py").write_text(body, encoding="utf-8")


def test_three_nonoverlapping_tasks_three_partitions(tmp_path: Path):
    _make_isolated(tmp_path)
    tasks = [
        Task("alpha", ["api/h.py"]),
        Task("beta", ["lib/u.py"]),
        Task("gamma", ["core/k.py"]),
    ]
    parts = partition_work(tmp_path, tasks)
    assert max_parallelism(parts) == 3
    # Partitions are ordered by first task name (alpha, beta, gamma); each
    # carries only its own task's file.
    assert [p.tasks for p in parts] == [["alpha"], ["beta"], ["gamma"]]
    assert [p.files for p in parts] == [["api/h.py"], ["lib/u.py"], ["core/k.py"]]


def test_two_tasks_sharing_a_file_one_partition(tmp_path: Path):
    _make_isolated(tmp_path)
    tasks = [
        Task("writer", ["api/h.py"]),
        Task("editor", ["api/h.py", "lib/u.py"]),
    ]
    parts = partition_work(tmp_path, tasks)
    assert max_parallelism(parts) == 1
    assert parts[0].tasks == ["editor", "writer"]
    # Union of both tasks' files, sorted.
    assert parts[0].files == ["api/h.py", "lib/u.py"]


def test_blast_radius_overlap_one_partition(tmp_path: Path):
    # task_b edits app/b.py; task_c edits app/c.py. app/b.py is a transitive
    # dependent of app/c.py, so the change blast-radii overlap even though the
    # two tasks share NO edited file directly.
    _make_chain(tmp_path)
    tasks = [
        Task("task_b", ["app/b.py"]),
        Task("task_c", ["app/c.py"]),
    ]
    parts = partition_work(tmp_path, tasks)
    assert max_parallelism(parts) == 1
    assert parts[0].tasks == ["task_b", "task_c"]
    assert parts[0].files == ["app/b.py", "app/c.py"]


def test_blast_radius_no_overlap_stays_parallel(tmp_path: Path):
    # Editing the LEAF (app/c.py) and a sibling at the top of an unrelated tree
    # never collide. app/a.py depends on c only transitively, so editing a.py
    # has no dependents of its own that c touches.
    _make_chain(tmp_path)
    (tmp_path / "solo").mkdir()
    (tmp_path / "solo" / "s.py").write_text("def s():\n    return 9\n", encoding="utf-8")
    tasks = [
        Task("touch_a", ["app/a.py"]),  # a is a leaf importer; nothing depends on it
        Task("touch_solo", ["solo/s.py"]),
    ]
    parts = partition_work(tmp_path, tasks)
    assert max_parallelism(parts) == 2
    assert [p.tasks for p in parts] == [["touch_a"], ["touch_solo"]]


def test_transitive_conflict_chains_into_one_partition(tmp_path: Path):
    # A~B (share a file) and B~C (blast-radius overlap) ⇒ A, B, C all one group.
    _make_chain(tmp_path)
    tasks = [
        Task("t1", ["app/c.py"]),
        Task("t2", ["app/c.py", "app/b.py"]),  # shares c with t1
        Task("t3", ["app/a.py"]),  # a is a transitive dependent of c (in t2's radius)
    ]
    parts = partition_work(tmp_path, tasks)
    assert max_parallelism(parts) == 1
    assert parts[0].tasks == ["t1", "t2", "t3"]
    assert parts[0].files == ["app/a.py", "app/b.py", "app/c.py"]


def test_unresolved_task_is_conservative_serial_with_all(tmp_path: Path):
    # A task with NO resolvable files cannot be proven disjoint, so it folds
    # every other (otherwise-parallel) task into one serial partition.
    _make_isolated(tmp_path)
    tasks = [
        Task("safe1", ["api/h.py"]),
        Task("safe2", ["lib/u.py"]),
        Task("mystery", []),  # declares nothing → untrustworthy footprint
    ]
    parts = partition_work(tmp_path, tasks)
    assert max_parallelism(parts) == 1
    assert parts[0].tasks == ["mystery", "safe1", "safe2"]
    assert parts[0].files == ["api/h.py", "lib/u.py"]


def test_skipped_only_files_treated_as_unresolved(tmp_path: Path):
    # A task whose only file lives under a skipped dir resolves to nothing and is
    # treated conservatively like a no-file task.
    _make_isolated(tmp_path)
    tasks = [
        Task("safe", ["api/h.py"]),
        Task("worktree", [".claude/worktrees/wt/app/x.py"]),
    ]
    parts = partition_work(tmp_path, tasks)
    assert max_parallelism(parts) == 1
    assert parts[0].tasks == ["safe", "worktree"]
    # The skipped path is dropped from the union; only the safe task's file remains.
    assert parts[0].files == ["api/h.py"]


def test_deterministic_ordering(tmp_path: Path):
    _make_isolated(tmp_path)
    # Same tasks declared in a scrambled order must yield identical output.
    a = partition_work(
        tmp_path,
        [Task("gamma", ["core/k.py"]), Task("alpha", ["api/h.py"]), Task("beta", ["lib/u.py"])],
    )
    b = partition_work(
        tmp_path,
        [Task("beta", ["lib/u.py"]), Task("gamma", ["core/k.py"]), Task("alpha", ["api/h.py"])],
    )
    assert [p.to_dict() for p in a] == [p.to_dict() for p in b]
    # And partitions are ordered by their first task name.
    assert [p.tasks[0] for p in a] == ["alpha", "beta", "gamma"]


def test_empty_input(tmp_path: Path):
    parts = partition_work(tmp_path, [])
    assert parts == []
    assert max_parallelism(parts) == 0


def test_max_parallelism_counts_partitions():
    parts = [Partition(["a"], ["x.py"]), Partition(["b"], ["y.py"])]
    assert max_parallelism(parts) == 2
    assert max_parallelism([]) == 0


def test_render_markdown_parallel_plan(tmp_path: Path):
    _make_isolated(tmp_path)
    parts = partition_work(
        tmp_path,
        [Task("alpha", ["api/h.py"]), Task("beta", ["lib/u.py"])],
    )
    md = render_partition_markdown(parts)
    assert "# Parallel Work Plan" in md
    assert "Max parallelism: 2 agent(s)." in md
    assert "## Parallel group 1" in md
    assert "## Parallel group 2" in md
    assert "tasks: [alpha]" in md
    assert "touching files: [api/h.py]" in md


def test_render_markdown_serial_group_flagged(tmp_path: Path):
    _make_chain(tmp_path)
    parts = partition_work(
        tmp_path,
        [Task("task_b", ["app/b.py"]), Task("task_c", ["app/c.py"])],
    )
    md = render_partition_markdown(parts)
    assert "run serially — they overlap" in md
    assert "tasks: [task_b, task_c]" in md


def test_render_markdown_empty():
    md = render_partition_markdown([])
    assert "_No tasks to partition._" in md


def test_render_markdown_no_resolved_files(tmp_path: Path):
    parts = partition_work(tmp_path, [Task("mystery", [])])
    md = render_partition_markdown(parts)
    assert "(no resolved files)" in md
