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

    def test_eval_of_nonliteral_string_is_not_rewritten(self):
        # eval("a * b") is a runtime expression, not a Python literal —
        # ast.literal_eval would crash on it, so the transform must NOT rewrite
        # it, and must NOT add a spurious unused `import ast`.
        source = 'def f():\n    return eval("principal * (1 + rate)")\n'
        result = security_apply("test.py", source, "eval() usage is unsafe")
        assert result is None

    def test_eval_already_safe(self):
        source = 'import ast\nx = ast.literal_eval(user_input)\n'
        result = security_apply("test.py", source, "eval() usage is unsafe")
        assert result is None

    def test_os_system_to_subprocess(self):
        source = 'import os\nos.system(cmd)\n'
        result = security_apply("test.py", source, "os.system() shell injection")
        assert result is not None
        assert result.transform_type == "os_system_to_subprocess"
        content = result.patch_requests[0]["new_content"]
        assert "subprocess.run" in content
        assert "import subprocess" in content
        # The command must be tokenised with shlex.split (os.system runs through
        # a shell, which splits the string). Wrapping it as [cmd] with
        # shell=False would seek one executable literally named "ls -la".
        assert "shlex.split(cmd)" in content
        assert "import shlex" in content
        # No spurious `import ast` — the os.system rewrite never uses ast.
        assert "import ast" not in content
        import ast as _ast
        _ast.parse(content)  # result is valid Python

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


class TestOsSystemFString:
    def test_fstring_command_is_hardened_to_subprocess(self):
        # os.system(f"cmd {x}") is a classic shell-injection sink. The fix runs
        # it shell-free (no shell=True), neutralizing injection, while shlex.split
        # preserves the shell's whitespace tokenization.
        import ast
        src = 'import os\ndef run(f):\n    os.system(f"backup.sh {f}")\n'
        result = security_apply("t.py", src, "Fix os.system")
        assert result is not None
        out = result.patch_requests[0]["new_content"]
        assert 'subprocess.run(shlex.split(f"backup.sh {f}"), check=True)' in out
        assert "os.system" not in out
        ast.parse(out)                       # generated code is valid

    def test_eval_fstring_is_declined(self):
        # eval(f"...") is never a literal -> literal_eval would crash -> decline.
        assert security_apply("t.py", 'def g(x):\n    return eval(f"{x}+1")\n', "Fix eval") is None


class TestImportInsertionFutureSafe:
    def test_eval_import_lands_after_future_import(self):
        # Inserting `import ast` at line 0 would break a file that opens with
        # `from __future__ import annotations` (must be the first statement).
        src = "from __future__ import annotations\ndef f(s):\n    return eval(s)\n"
        out = security_apply("t.py", src, "Fix eval").patch_requests[0]["new_content"]
        compile(out, "t.py", "exec")                 # the real test: it compiles
        assert "ast.literal_eval(s)" in out

    def test_os_system_imports_land_after_docstring_and_future(self):
        src = ('"""Mod."""\nfrom __future__ import annotations\nimport os\n'
               'def run(f):\n    os.system(f"x {f}")\n')
        out = security_apply("t.py", src, "Fix os.system").patch_requests[0]["new_content"]
        compile(out, "t.py", "exec")
        # docstring and future import stay first
        lines = [l for l in out.splitlines() if l.strip()]
        assert lines[0] == '"""Mod."""'
        assert lines[1] == "from __future__ import annotations"
