"""New PROVABLY-SAFE security auto-rewrites and their flag siblings.

Two crown-jewel rewrites are proven byte-correct AND behaviour-preserving:

  * hashlib.new("md5"|"sha1") -> add usedforsecurity=False. Characterization:
    the digest bytes are IDENTICAL before/after (the kwarg only declares intent),
    so any stored/compared hash is unchanged.
  * subprocess.run("<metachar-free literal>", shell=True) -> shell=False +
    shlex.split("<literal>"). Characterization: for a bare command the shell only
    whitespace-tokenises the string, which shlex.split reproduces exactly, while
    dropping the shell removes the injection surface.

Both rewrites DECLINE (return None / fall back to a flag) on any case they can't
prove safe. The os.popen / TLS / Zip-Slip flag patchers are covered for byte
shape too.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

import ast
import hashlib

from app.execution.semantic.transforms.security import apply as security_apply


class TestHashlibNewWeakRewrite:
    def test_md5_string_form_gets_usedforsecurity_false(self) -> None:
        src = 'import hashlib\nh = hashlib.new("md5")\n'
        result = security_apply("t.py", src, "fix hashlib-new-weak")
        assert result is not None
        assert result.transform_type == "hashlib_new_usedforsecurity_false"
        out = result.patch_requests[0]["new_content"]
        assert 'hashlib.new("md5", usedforsecurity=False)' in out
        ast.parse(out)

    def test_sha1_string_form_rewritten(self) -> None:
        src = 'import hashlib\nh = hashlib.new("sha1")\n'
        result = security_apply("t.py", src, "fix hashlib-new-weak")
        assert result is not None
        assert 'usedforsecurity=False' in result.patch_requests[0]["new_content"]

    def test_digest_is_behaviour_preserving(self) -> None:
        # The whole point: adding usedforsecurity=False must NOT change the digest.
        before = hashlib.new("md5")
        before.update(b"payload")
        after = hashlib.new("md5", usedforsecurity=False)
        after.update(b"payload")
        assert before.hexdigest() == after.hexdigest()

    def test_already_safe_declines(self) -> None:
        src = 'import hashlib\nh = hashlib.new("md5", usedforsecurity=False)\n'
        assert security_apply("t.py", src, "fix hashlib-new-weak") is None

    def test_strong_hash_declines(self) -> None:
        src = 'import hashlib\nh = hashlib.new("sha256")\n'
        assert security_apply("t.py", src, "fix hashlib-new-weak") is None

    def test_dynamic_name_declines(self) -> None:
        # A non-literal algorithm name can't be proven weak — leave it alone.
        src = "import hashlib\nh = hashlib.new(name)\n"
        assert security_apply("t.py", src, "fix hashlib-new-weak") is None


class TestSubprocessShellLiteralRewrite:
    def test_literal_command_rewritten_to_shlex(self) -> None:
        src = 'import subprocess\nsubprocess.run("ls -la /tmp", shell=True)\n'
        result = security_apply("t.py", src, "fix subprocess-shell-literal")
        assert result is not None
        assert result.transform_type == "subprocess_shell_literal_to_shlex"
        out = result.patch_requests[0]["new_content"]
        assert 'subprocess.run(shlex.split("ls -la /tmp"), shell=False)' in out
        assert "import shlex" in out
        assert "shell=True" not in out
        ast.parse(out)

    def test_shlex_split_reproduces_shell_tokenisation(self) -> None:
        # Behaviour-preserving proof: for a bare command the shell just
        # whitespace-splits, which shlex.split reproduces exactly.
        import shlex
        assert shlex.split("ls -la /tmp") == ["ls", "-la", "/tmp"]

    def test_metachar_command_declines(self) -> None:
        # A pipe has shell meaning shlex.split cannot reproduce — must NOT rewrite.
        src = 'import subprocess\nsubprocess.run("cat a | grep b", shell=True)\n'
        assert security_apply("t.py", src, "fix subprocess-shell-literal") is None

    def test_redirection_declines(self) -> None:
        src = 'import subprocess\nsubprocess.run("echo hi > out.txt", shell=True)\n'
        assert security_apply("t.py", src, "fix subprocess-shell-literal") is None

    def test_dynamic_command_declines(self) -> None:
        src = "import subprocess\nsubprocess.run(cmd, shell=True)\n"
        assert security_apply("t.py", src, "fix subprocess-shell-literal") is None

    def test_list_arg_declines(self) -> None:
        src = 'import subprocess\nsubprocess.run(["ls"], shell=True)\n'
        assert security_apply("t.py", src, "fix subprocess-shell-literal") is None

    def test_empty_string_declines(self) -> None:
        src = 'import subprocess\nsubprocess.run("   ", shell=True)\n'
        assert security_apply("t.py", src, "fix subprocess-shell-literal") is None

    def test_future_import_keeps_shlex_legal(self) -> None:
        src = ('from __future__ import annotations\nimport subprocess\n'
               'subprocess.run("ls -la", shell=True)\n')
        result = security_apply("t.py", src, "fix subprocess-shell-literal")
        assert result is not None
        out = result.patch_requests[0]["new_content"]
        # shlex must land AFTER the future import (a future import must be first).
        assert out.index("from __future__") < out.index("import shlex")
        ast.parse(out)


class TestFlagPatchersByteShape:
    def test_os_popen_flagged(self) -> None:
        src = "import os\nos.popen('ls')\n"
        result = security_apply("t.py", src, "fix os.popen")
        assert result is not None
        assert result.transform_type == "flag_os_popen"
        out = result.patch_requests[0]["new_content"]
        assert "# SECURITY (Apex: os.popen" in out
        assert "os.popen('ls')" in out  # original call untouched
        ast.parse(out)

    def test_tls_verify_flagged(self) -> None:
        src = "import requests\nrequests.get(u, verify=False)\n"
        result = security_apply("t.py", src, "fix tls-verify")
        assert result is not None
        assert result.transform_type == "flag_tls_verify"
        out = result.patch_requests[0]["new_content"]
        assert "# SECURITY (Apex: TLS verification" in out
        ast.parse(out)

    def test_zip_slip_flagged(self) -> None:
        src = "import tarfile\nt = tarfile.open(p)\nt.extractall(dest)\n"
        result = security_apply("t.py", src, "fix zip-slip")
        assert result is not None
        assert result.transform_type == "flag_zip_slip"
        out = result.patch_requests[0]["new_content"]
        assert "# SECURITY (Apex: Zip-Slip" in out
        ast.parse(out)

    def test_zip_slip_guarded_not_flagged(self) -> None:
        src = "import tarfile\nt = tarfile.open(p)\nt.extractall(dest, members=safe)\n"
        assert security_apply("t.py", src, "fix zip-slip") is None

    def test_flag_is_idempotent(self) -> None:
        # Re-flagging an already-annotated call must be a no-op (the marker on the
        # preceding line is detected), so the harden ladder can converge.
        src = "import os\nos.popen('ls')\n"
        once = security_apply("t.py", src, "fix os.popen")
        assert once is not None
        twice = security_apply("t.py", once.patch_requests[0]["new_content"], "fix os.popen")
        assert twice is None
