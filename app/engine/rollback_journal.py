from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PatchRecord:
    """Record of a single patch application for potential rollback."""

    patch_id: str
    file_path: str
    old_content: str
    new_content: str
    diff: str
    applied_at: str
    promoted: bool = False
    reverted: bool = False
    run_id: str = ""
    issue: str = ""
    action_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "file_path": self.file_path,
            "old_content": self.old_content,
            "new_content": self.new_content,
            "diff": self.diff,
            "applied_at": self.applied_at,
            "promoted": self.promoted,
            "reverted": self.reverted,
            "run_id": self.run_id,
            "issue": self.issue,
            "action_type": self.action_type,
        }


class RollbackJournal:
    """Journal for patch rollback capability.

    Tracks all patch applications with old content for potential rollback.
    Supports both sandbox and promoted patches.

    Usage:
        journal = RollbackJournal(project_root=".")
        patch_id = journal.record_patch(file, old, new, run_id="run-123")
        # ... if something goes wrong:
        success = journal.rollback(patch_id)
        # ... or cleanup after successful promotion:
        journal.mark_promoted(patch_id)
    """

    def __init__(self, project_root: str = ".", log_dir: str = ".apex") -> None:
        self.project_root = Path(project_root)
        self.journal_path = Path(log_dir) / "patch_journal.json"
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self.records: list[PatchRecord] = []
        self._load()

    def _load(self) -> None:
        if self.journal_path.exists():
            try:
                data = json.loads(self.journal_path.read_text(encoding="utf-8"))
                self.records = [PatchRecord(**r) for r in data.get("records", [])]
            except Exception:
                self.records = []

    def _save(self) -> None:
        self.journal_path.write_text(
            json.dumps(
                {"records": [r.to_dict() for r in self.records], "version": "2.0"},
                indent=2,
            ),
            encoding="utf-8",
        )

    def _generate_patch_id(self, file_path: str) -> str:
        """Generate unique patch ID."""
        import uuid

        return f"patch-{Path(file_path).stem[:8]}-{uuid.uuid4().hex[:6]}"

    def _generate_diff(self, old: str, new: str) -> str:
        """Generate a simple unified diff."""
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)

        diff_lines = []
        max_lines = max(len(old_lines), len(new_lines))

        for i in range(max_lines):
            old_line = old_lines[i] if i < len(old_lines) else None
            new_line = new_lines[i] if i < len(new_lines) else None

            if old_line is None:
                diff_lines.append(f"+{i + 1}: {new_line.rstrip()}")
            elif new_line is None:
                diff_lines.append(f"-{i + 1}: {old_line.rstrip()}")
            elif old_line.rstrip() != new_line.rstrip():
                diff_lines.append(f"-{i + 1}: {old_line.rstrip()}")
                diff_lines.append(f"+{i + 1}: {new_line.rstrip()}")

        return "\n".join(diff_lines[:50]) if diff_lines else "no changes"

    def record_patch(
        self,
        file_path: str,
        old_content: str,
        new_content: str,
        run_id: str = "",
        issue: str = "",
        action_type: str = "patch",
    ) -> str:
        """Record a patch for potential rollback. Returns patch_id."""
        patch_id = self._generate_patch_id(file_path)

        record = PatchRecord(
            patch_id=patch_id,
            file_path=file_path,
            old_content=old_content,
            new_content=new_content,
            diff=self._generate_diff(old_content, new_content),
            applied_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            run_id=run_id,
            issue=issue,
            action_type=action_type,
        )

        self.records.append(record)
        self._save()
        return patch_id

    def rollback(self, patch_id: str) -> bool:
        """Rollback a patch by restoring old content. Returns True if successful."""
        for record in reversed(self.records):
            if record.patch_id == patch_id and not record.reverted:
                try:
                    file_path = self.project_root / record.file_path
                    file_path.write_text(record.old_content, encoding="utf-8")
                    record.reverted = True
                    self._save()
                    return True
                except Exception:
                    return False
        return False

    def rollback_last(self) -> bool:
        """Rollback the most recent non-reverted patch. Returns True if successful."""
        for record in reversed(self.records):
            if not record.reverted:
                return self.rollback(record.patch_id)
        return False

    def rollback_all(self) -> int:
        """Rollback all non-reverted patches. Returns count of rolled back patches."""
        count = 0
        for record in self.records:
            if not record.reverted:
                try:
                    file_path = self.project_root / record.file_path
                    file_path.write_text(record.old_content, encoding="utf-8")
                    record.reverted = True
                    count += 1
                except Exception:
                    pass
        if count > 0:
            self._save()
        return count

    def mark_promoted(self, patch_id: str) -> bool:
        """Mark a patch as promoted (applied to original)."""
        for record in self.records:
            if record.patch_id == patch_id:
                record.promoted = True
                self._save()
                return True
        return False

    def get_patch_history(self, file_path: str | None = None) -> list[dict[str, Any]]:
        """Get patch history, optionally filtered by file."""
        records = self.records
        if file_path:
            records = [r for r in records if r.file_path == file_path]
        return [r.to_dict() for r in reversed(records)]

    def get_active_patches(self) -> list[dict[str, Any]]:
        """Get list of non-reverted, non-promoted patches."""
        active = [r for r in self.records if not r.reverted and not r.promoted]
        return [r.to_dict() for r in reversed(active)]

    def get_statistics(self) -> dict[str, Any]:
        """Get journal statistics."""
        total = len(self.records)
        promoted = sum(1 for r in self.records if r.promoted)
        reverted = sum(1 for r in self.records if r.reverted)
        active = total - promoted - reverted

        return {
            "total_patches": total,
            "promoted": promoted,
            "reverted": reverted,
            "active": active,
        }

    def cleanup_old_records(self, keep_last: int = 100) -> int:
        """Remove old records, keeping only the most recent."""
        if len(self.records) <= keep_last:
            return 0

        original_len = len(self.records)
        self.records = self.records[-keep_last:]
        self._save()
        return original_len - len(self.records)
