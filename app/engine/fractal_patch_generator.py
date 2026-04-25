from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class FractalPatch:
    """A patch generated from fractal analysis."""

    file: str
    finding: str
    action: str
    old_code: str
    new_code: str
    confidence: float
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "finding": self.finding,
            "action": self.action,
            "old_code": self.old_code,
            "new_code": self.new_code,
            "confidence": self.confidence,
            "applied": self.applied,
        }


class FractalPatchGenerator:
    """Generate AST-based patches from fractal security findings.

    When meta-analysis recommends 'patch', this engine produces
    deterministic, reviewable code changes.

    Supported transforms:
    - eval() → ast.literal_eval() or json.loads()
    - os.system() → subprocess.run()
    - bare except → except Exception
    - missing docstring → add placeholder docstring
    """

    def generate(self, finding: dict[str, Any], meta: dict[str, Any]) -> list[FractalPatch]:
        if meta.get("recommended_action") != "patch":
            return []

        issue = finding.get("issue", "").lower()
        file_path = finding.get("file", "")
        line = finding.get("line", 0)

        patches: list[FractalPatch] = []

        if "eval" in issue:
            patches.append(self._patch_eval(file_path, line))
        elif "os.system" in issue:
            patches.append(self._patch_os_system(file_path, line))
        elif "bare except" in issue:
            patches.append(self._patch_bare_except(file_path, line))
        elif "missing_docstring" in issue:
            patches.append(self._patch_missing_docstring(file_path, line, finding))
        elif "missing_test" in issue:
            patches.append(self._patch_missing_test(file_path, line, finding))

        return patches

    def _patch_eval(self, file_path: str, line: int) -> FractalPatch:
        return FractalPatch(
            file=file_path,
            finding="eval() usage",
            action="replace_with_literal_eval",
            old_code="eval(user_input)",
            new_code="ast.literal_eval(user_input)",
            confidence=0.85,
        )

    def _patch_os_system(self, file_path: str, line: int) -> FractalPatch:
        return FractalPatch(
            file=file_path,
            finding="os.system() usage",
            action="replace_with_subprocess_run",
            old_code="os.system(command)",
            new_code='import subprocess; subprocess.run(command, shell=False, check=True)  # TODO: split args properly',
            confidence=0.8,
        )

    def _patch_bare_except(self, file_path: str, line: int) -> FractalPatch:
        return FractalPatch(
            file=file_path,
            finding="bare except clause",
            action="add_exception_type",
            old_code="except:",
            new_code="except Exception:",
            confidence=0.95,
        )

    def _patch_missing_docstring(self, file_path: str, line: int, finding: dict[str, Any]) -> FractalPatch:
        target = finding.get("target", "function")
        return FractalPatch(
            file=file_path,
            finding="missing docstring",
            action="add_docstring",
            old_code=f"def {target}():",
            new_code=f'''def {target}():
    """TODO: Add docstring for {target}."""''',
            confidence=0.9,
        )

    def _patch_missing_test(self, file_path: str, line: int, finding: dict[str, Any]) -> FractalPatch:
        func = finding.get("target", "function")
        return FractalPatch(
            file=file_path,
            finding="missing test coverage",
            action="generate_test_stub",
            old_code="",
            new_code=f'''def test_{func}():
    """TODO: Implement test for {func}."""
    assert {func}() is not None
''',
            confidence=0.7,
        )

    def apply(self, patch: FractalPatch, project_root: str = ".") -> bool:
        """Apply a patch to the filesystem. Returns True if successful."""
        path = Path(project_root) / patch.file
        if not path.exists():
            return False
        content = path.read_text(encoding="utf-8")
        if patch.old_code not in content:
            return False
        content = content.replace(patch.old_code, patch.new_code, 1)
        path.write_text(content, encoding="utf-8")
        patch.applied = True
        return True
