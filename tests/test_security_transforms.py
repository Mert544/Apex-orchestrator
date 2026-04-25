from __future__ import annotations

import pytest

from app.execution.semantic.transforms.security import apply as security_apply


class TestSecurityTransforms:
    def test_eval_to_literal_eval(self):
        source = 'import os\nx = eval(user_input)\n'
        result = security_apply("test.py", source, "eval() usage is unsafe")
        assert result is not None
        assert result.transform_type == "eval_to_literal_eval"
        assert "ast.literal_eval" in result.patch_requests[0]["new_content"]
        assert "import ast" in result.patch_requests[0]["new_content"]

    def test_eval_already_safe(self):
        source = 'import ast\nx = ast.literal_eval(user_input)\n'
        result = security_apply("test.py", source, "eval() usage is unsafe")
        assert result is None

    def test_os_system_to_subprocess(self):
        source = 'import os\nos.system(cmd)\n'
        result = security_apply("test.py", source, "os.system() shell injection")
        assert result is not None
        assert result.transform_type == "os_system_to_subprocess"
        assert "subprocess.run" in result.patch_requests[0]["new_content"]
        assert "import subprocess" in result.patch_requests[0]["new_content"]

    def test_bare_except_to_exception(self):
        source = 'import os\ntry:\n    x\nexcept:\n    pass\n'
        result = security_apply("test.py", source, "bare except clause")
        assert result is not None
        assert result.transform_type == "bare_except_to_exception"
        assert "except Exception:" in result.patch_requests[0]["new_content"]

    def test_no_match_returns_none(self):
        source = 'import os\nx = 1\n'
        result = security_apply("test.py", source, "unrelated issue")
        assert result is None

    def test_does_not_double_import(self):
        source = 'import ast\nx = eval(user_input)\n'
        result = security_apply("test.py", source, "eval() usage")
        assert result is not None
        assert result.patch_requests[0]["new_content"].count("import ast") == 1
