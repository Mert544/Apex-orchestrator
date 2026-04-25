from __future__ import annotations

from app.skills.safety.check_patch_scope import CheckPatchScopeSkill, PatchScopeResult


def test_patch_scope_ok_with_few_files():
    skill = CheckPatchScopeSkill()
    result = skill.run(changed_files=["app/main.py", "app/cli.py"])
    assert result.ok
    assert result.changed_file_count == 2


def test_patch_scope_rejects_too_many_files():
    skill = CheckPatchScopeSkill()
    result = skill.run(changed_files=[f"f{i}.py" for i in range(10)], max_allowed_files=5)
    assert not result.ok
    assert "scope too large" in result.reasons[0].lower()


def test_patch_scope_flags_sensitive_paths():
    skill = CheckPatchScopeSkill()
    result = skill.run(changed_files=["app/auth.py"])
    assert not result.ok
    assert result.touched_sensitive_paths == ["app/auth.py"]


def test_patch_scope_flags_token_files():
    skill = CheckPatchScopeSkill()
    result = skill.run(changed_files=["config/token.py"])
    assert not result.ok
    assert "token" in result.touched_sensitive_paths[0]


def test_patch_scope_custom_hints():
    skill = CheckPatchScopeSkill()
    result = skill.run(
        changed_files=["app/production.py"],
        sensitive_hints=("production",),
    )
    assert not result.ok
    assert result.touched_sensitive_paths == ["app/production.py"]


def test_patch_scope_dataclass():
    r = PatchScopeResult(ok=True, changed_file_count=1, max_allowed_files=5, touched_sensitive_paths=[], reasons=[])
    assert r.ok
    assert r.max_allowed_files == 5
