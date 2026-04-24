from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.fractal_patch_generator import FractalPatchGenerator, FractalPatch


class TestFractalPatchGenerator:
    def test_no_patch_when_not_recommended(self):
        gen = FractalPatchGenerator()
        finding = {"issue": "eval() usage", "file": "a.py"}
        meta = {"recommended_action": "review"}
        patches = gen.generate(finding, meta)
        assert len(patches) == 0

    def test_patch_eval(self):
        gen = FractalPatchGenerator()
        finding = {"issue": "eval() usage", "file": "a.py", "line": 5}
        meta = {"recommended_action": "patch"}
        patches = gen.generate(finding, meta)
        assert len(patches) == 1
        assert patches[0].action == "replace_with_literal_eval"
        assert "ast.literal_eval" in patches[0].new_code

    def test_patch_os_system(self):
        gen = FractalPatchGenerator()
        finding = {"issue": "os.system() usage", "file": "b.py", "line": 10}
        meta = {"recommended_action": "patch"}
        patches = gen.generate(finding, meta)
        assert len(patches) == 1
        assert patches[0].action == "replace_with_subprocess_run"

    def test_patch_bare_except(self):
        gen = FractalPatchGenerator()
        finding = {"issue": "bare except clause", "file": "c.py", "line": 3}
        meta = {"recommended_action": "patch"}
        patches = gen.generate(finding, meta)
        assert len(patches) == 1
        assert patches[0].action == "add_exception_type"

    def test_patch_missing_docstring(self):
        gen = FractalPatchGenerator()
        finding = {"issue": "missing_docstring", "file": "d.py", "line": 1, "target": "foo"}
        meta = {"recommended_action": "patch"}
        patches = gen.generate(finding, meta)
        assert len(patches) == 1
        assert patches[0].action == "add_docstring"

    def test_apply_patch(self, tmp_path: Path):
        gen = FractalPatchGenerator()
        file = tmp_path / "test.py"
        file.write_text("x = eval(user_input)\n")
        patch = FractalPatch(
            file="test.py",
            finding="eval",
            action="replace",
            old_code="x = eval(user_input)",
            new_code="x = ast.literal_eval(user_input)",
            confidence=0.9,
        )
        ok = gen.apply(patch, str(tmp_path))
        assert ok is True
        assert patch.applied is True
        content = file.read_text()
        assert "ast.literal_eval" in content
        assert "x = eval(user_input)" not in content

    def test_apply_patch_missing_file(self, tmp_path: Path):
        gen = FractalPatchGenerator()
        patch = FractalPatch(
            file="missing.py",
            finding="eval",
            action="replace",
            old_code="x",
            new_code="y",
            confidence=0.9,
        )
        ok = gen.apply(patch, str(tmp_path))
        assert ok is False
