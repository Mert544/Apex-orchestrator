from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FilePatch:
    path: str
    new_content: str
    expected_old_content: str | None = None


@dataclass
class PatchApplyResult:
    project_root: str
    changed_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    ok: bool = False
    error: str | None = None


class ApplyPatchSkill:
    def run(self, project_root: str | Path, patches: list[FilePatch], create_missing_dirs: bool = True) -> PatchApplyResult:
        root = Path(project_root).resolve()
        result = PatchApplyResult(project_root=str(root))
        try:
            for patch in patches:
                target = (root / patch.path).resolve()
                if not str(target).startswith(str(root)):
                    raise ValueError(f"Patch path escapes project root: {patch.path}")
                if target.exists():
                    current = target.read_text(encoding="utf-8")
                    if patch.expected_old_content is not None and current != patch.expected_old_content:
                        result.skipped_files.append(patch.path)
                        continue
                else:
                    if patch.expected_old_content is not None:
                        result.skipped_files.append(patch.path)
                        continue
                    if create_missing_dirs:
                        target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(patch.new_content, encoding="utf-8")
                result.changed_files.append(patch.path)
            result.ok = True
            return result
        except Exception as exc:
            result.error = str(exc)
            result.ok = False
            return result
