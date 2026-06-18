"""Deep-mutation characterization tests for ``CheckpointManager``.

These kill mutation survivors that the default 30-mutant cap masks (the module
has 42 mutation sites; the cap stops at 30). The full ``_collect_sites`` /
``_splice`` sweep over a temp copy surfaced 11 survivors past the cap. Each test
below pins a behavior that a surviving single-token mutation would change, so the
mutant is now caught.

Survivors killed here (REAL):
* L29 ``mkdir(..., exist_ok=True)`` -> ``exist_ok=False`` — a re-instantiation
  on an existing checkpoint dir must NOT raise.
* L53 ``json.dumps(checkpoint, indent=2)`` -> ``indent=3`` — the on-disk
  checkpoint JSON is indented with exactly two spaces.
* L57 ``json.dumps(checkpoint, indent=2)`` -> ``indent=3`` — ``latest.json`` is
  indented with exactly two spaces.
* L118 ``list_checkpoints(limit=10)`` default -> ``11`` — the default cap is
  exactly ten entries.

Documented EQUIVALENT survivors (no deterministic, cheap kill — left unkilled):
* L71 ``stats.get("findings_count", 0)`` -> default ``1``: the default is only
  read when the key is absent, and both ``0`` and ``1`` fail ``findings > 5``;
  ``findings`` is used nowhere else, so the flip never changes any output.
* L85 ``subprocess.run(..., text=True)`` -> ``text=False`` in ``git status``:
  ``result.stdout`` becomes ``bytes`` but ``bytes.strip()`` is still truthy for a
  dirty tree, so the add/commit branch is taken identically.
* L86 / L94 / L102 ``timeout=10`` -> ``11`` on the git subprocess calls: only the
  hang ceiling shifts by one second; killing it would require a ~10s real hang,
  which is neither cheap nor deterministic.
* L93 / L101 ``capture_output=True`` -> ``False`` on ``git add`` / ``git commit``:
  neither call's result is inspected, so the commit still happens identically.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.checkpoint_manager import CheckpointManager


def _mgr(tmp_path: Path) -> CheckpointManager:
    return CheckpointManager(project_root=str(tmp_path))


def test_reinit_on_existing_dir_does_not_raise(tmp_path: Path):
    # Kills L29 exist_ok=True->False: the second manager re-uses the existing
    # checkpoint dir; with exist_ok=False mkdir would raise FileExistsError.
    first = _mgr(tmp_path)
    assert first.checkpoint_dir.exists()
    second = _mgr(tmp_path)
    assert second.checkpoint_dir == first.checkpoint_dir
    assert second.checkpoint_dir.exists()


def test_checkpoint_json_indented_with_two_spaces(tmp_path: Path):
    # Kills L53 indent=2->3: the checkpoint file's body lines start with exactly
    # two leading spaces, never three.
    mgr = _mgr(tmp_path)
    mgr.save_checkpoint(run_id="ind", mode="m", goal="g", force=True)
    raw = (mgr.checkpoint_dir / "checkpoint-ind.json").read_text(encoding="utf-8")
    body_lines = raw.splitlines()[1:]
    indented = [ln for ln in body_lines if ln.startswith(" ")]
    assert indented, "expected at least one indented JSON line"
    for ln in indented:
        leading = len(ln) - len(ln.lstrip(" "))
        # Two-space indent => every nesting level is a multiple of 2 (never 3).
        assert leading % 2 == 0
    # A top-level key sits at exactly two spaces of indent.
    assert any(ln.startswith('  "run_id"') for ln in body_lines)


def test_latest_json_indented_with_two_spaces(tmp_path: Path):
    # Kills L57 indent=2->3: latest.json is written with the same two-space
    # indent as the per-run checkpoint file.
    mgr = _mgr(tmp_path)
    mgr.save_checkpoint(run_id="lat", mode="m", goal="g", force=True)
    raw = (mgr.checkpoint_dir / "latest.json").read_text(encoding="utf-8")
    body_lines = raw.splitlines()[1:]
    for ln in (l for l in body_lines if l.startswith(" ")):
        leading = len(ln) - len(ln.lstrip(" "))
        assert leading % 2 == 0
    assert any(ln.startswith('  "run_id"') for ln in body_lines)
    # And the bodies match exactly (both serialized with the same indent).
    cp_raw = (mgr.checkpoint_dir / "checkpoint-lat.json").read_text(encoding="utf-8")
    assert raw == cp_raw


def test_list_checkpoints_default_limit_is_ten(tmp_path: Path):
    # Kills L118 limit default 10->11: with eleven checkpoints and no explicit
    # limit, exactly ten are returned (a default of 11 would return eleven).
    mgr = _mgr(tmp_path)
    for i in range(11):
        mgr.save_checkpoint(run_id=f"r{i:02d}", mode="m", goal="g", force=True)
    listed = mgr.list_checkpoints()
    assert len(listed) == 10


def test_checkpoint_json_is_two_space_for_nested_stats(tmp_path: Path):
    # Reinforces the indent=2 kill against nested structures: a nested stats
    # dict is indented at four spaces (2 * depth), never six.
    mgr = _mgr(tmp_path)
    mgr.save_checkpoint(
        run_id="nest", mode="m", goal="g",
        stats={"patches_applied": 1, "findings_count": 2},
    )
    raw = (mgr.checkpoint_dir / "checkpoint-nest.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["stats"] == {"patches_applied": 1, "findings_count": 2}
    # The nested key lives at depth 2 => four leading spaces under two-space indent.
    assert any(ln.startswith('    "patches_applied"') for ln in raw.splitlines())
