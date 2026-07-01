"""``cross_file_rename._rollback`` — the shared auto-rollback primitive that
EVERY landing runs on a failed verify. Its contract (from its own docstring): a
file the plan CREATED must be DELETED, not rewritten, because a never-existed
file has no original to restore.

Several planners double-track a created file: they record its ``originals`` entry
as ``""`` (generate_usage_doc, scaffold_from_protocol, wire_exports, pin_doctest,
…). The regression these tests guard is a rollback that rewrites such a file to
its empty original (step 1) and then SKIPS the delete (step 2, whose old
``rel not in plan.originals`` guard was false for a double-tracked file) — leaking
a 0-byte artifact instead of restoring the exact pre-plan tree.

``created`` is built by ``apply_rename`` as ``[rel for rel in plan.new_contents
if not (root / rel).exists()]`` (the files that did not exist before the write),
so these tests reconstruct that list the same way and never assert on internals.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, _rollback


def _created(root: Path, existed_before: set[str], plan: RenamePlan) -> list[str]:
    """The ``created`` list exactly as ``apply_rename`` computes it: every planned
    target that did not exist on disk before the plan's write. We snapshot which
    rels existed BEFORE writing (``existed_before``) so this stays faithful even
    after the new files are on disk."""
    return [rel for rel in plan.new_contents if rel not in existed_before]


def _write_plan(root: Path, plan: RenamePlan) -> list[str]:
    """Apply ``plan``'s writes to disk (mkdir + write_text, like ``apply_rename``)
    and return the ``created`` list for the files that were newly made."""
    existed = {rel for rel in plan.new_contents if (root / rel).exists()}
    for rel, content in plan.new_contents.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content, encoding="utf-8")
    return _created(root, existed, plan)


def test_rollback_deletes_a_created_file_double_tracked_as_empty_original(tmp_path):
    """A plan that CREATES a new file the way the real planners do — recording its
    original as ``""`` in ``plan.originals`` — must, after ``_rollback``, leave that
    file GONE: not present, and NOT a leaked empty artifact."""
    doc_rel = "app/USAGE.md"
    plan = RenamePlan(old="x", new="y")
    # This is exactly what generate_usage_doc / scaffold_from_protocol / wire_exports
    # record for a target that did not exist: original == "" AND it is a created file.
    plan.originals[doc_rel] = ""
    plan.new_contents[doc_rel] = "# Usage\n\nGenerated content.\n"

    created = _write_plan(tmp_path, plan)
    assert created == [doc_rel]  # apply_rename would classify it as created
    assert (tmp_path / doc_rel).read_text(encoding="utf-8")  # non-empty on disk now

    _rollback(tmp_path, plan, created)

    # The pre-plan tree had no such file, so the exact restore is: it is gone.
    assert not (tmp_path / doc_rel).exists(), "created file leaked instead of deleted"


def test_rollback_restores_a_preexisting_edited_file_to_exact_bytes(tmp_path):
    """The COMMON case must be behaviour-preserving: a file that existed before the
    plan and was EDITED is restored to its exact original bytes on rollback."""
    rel = "app/core.py"
    original = "# the central helper\ndef compute(x):\n    return x * 2\n"
    (tmp_path / "app").mkdir()
    (tmp_path / rel).write_text(original, encoding="utf-8")

    plan = RenamePlan(old="compute", new="calculate")
    plan.originals[rel] = original
    plan.new_contents[rel] = original.replace("compute", "calculate")

    created = _write_plan(tmp_path, plan)
    assert created == []  # it existed before → never a created file
    assert "calculate" in (tmp_path / rel).read_text(encoding="utf-8")  # edited on disk

    _rollback(tmp_path, plan, created)

    restored = (tmp_path / rel).read_text(encoding="utf-8")
    assert restored == original  # byte-exact, comment and all
    assert "calculate" not in restored


def test_rollback_mixed_created_gone_and_edited_restored(tmp_path):
    """A plan with BOTH a created file (double-tracked as ``""``) and an edited
    pre-existing file: after rollback the created file is GONE and the edited file
    is restored to its exact original — the two paths don't interfere."""
    edited_rel = "pkg/mod.py"
    created_rel = "pkg/NEW.md"
    original = "def edited():\n    return 1\n"
    (tmp_path / "pkg").mkdir()
    (tmp_path / edited_rel).write_text(original, encoding="utf-8")

    plan = RenamePlan(old="a", new="b")
    plan.originals[edited_rel] = original
    plan.new_contents[edited_rel] = "def edited():\n    return 2\n"
    plan.originals[created_rel] = ""  # created, double-tracked with an empty original
    plan.new_contents[created_rel] = "# brand new\n"

    created = _write_plan(tmp_path, plan)
    assert created == [created_rel]

    _rollback(tmp_path, plan, created)

    assert not (tmp_path / created_rel).exists(), "created file leaked"
    assert (tmp_path / edited_rel).read_text(encoding="utf-8") == original


def test_rollback_no_created_files_only_restores(tmp_path):
    """Empty/edge path: no created files at all — every ``originals`` entry is a
    pre-existing file, so all are restored and nothing is deleted."""
    rel_a, rel_b = "a.py", "b.py"
    orig_a, orig_b = "A = 1\n", "B = 2\n"
    (tmp_path / rel_a).write_text(orig_a, encoding="utf-8")
    (tmp_path / rel_b).write_text(orig_b, encoding="utf-8")

    plan = RenamePlan(old="A", new="Z")
    plan.originals[rel_a] = orig_a
    plan.originals[rel_b] = orig_b
    plan.new_contents[rel_a] = "Z = 1\n"
    plan.new_contents[rel_b] = "B = 2  # touched\n"

    created = _write_plan(tmp_path, plan)
    assert created == []

    _rollback(tmp_path, plan, created)

    assert (tmp_path / rel_a).read_text(encoding="utf-8") == orig_a
    assert (tmp_path / rel_b).read_text(encoding="utf-8") == orig_b


def test_rollback_created_delete_is_guarded_against_already_gone(tmp_path):
    """The OSError guard survives: if a created file was already removed before
    ``_rollback`` runs (e.g. a concurrent cleanup), rollback still restores the
    edited files and does not raise on the missing created target."""
    created_rel = "gen/OUT.md"
    edited_rel = "gen/keep.py"
    original = "KEEP = True\n"
    (tmp_path / "gen").mkdir()
    (tmp_path / edited_rel).write_text(original, encoding="utf-8")

    plan = RenamePlan(old="a", new="b")
    plan.originals[edited_rel] = original
    plan.new_contents[edited_rel] = "KEEP = False\n"
    plan.originals[created_rel] = ""
    plan.new_contents[created_rel] = "# generated\n"

    created = _write_plan(tmp_path, plan)
    assert created == [created_rel]
    (tmp_path / created_rel).unlink()  # simulate it already being gone

    _rollback(tmp_path, plan, created)  # must not raise

    assert not (tmp_path / created_rel).exists()
    assert (tmp_path / edited_rel).read_text(encoding="utf-8") == original
