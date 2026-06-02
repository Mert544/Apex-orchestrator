from app.execution.patch_request_generator import PatchRequestGenerator


def test_uses_second_target_when_first_not_inlineable(tmp_path):
    # First target doesn't exist; second is a real markdown file. The generator
    # must fall through to the second target (regression: previously sliced [:1]
    # and forced a fallback draft instead).
    (tmp_path / "doc.md").write_text("# Title\n")
    gen = PatchRequestGenerator()
    result = gen.generate(
        str(tmp_path),
        {"target_files": ["missing.py", "doc.md"], "title": "t", "task_id": "k", "branch": "x.a"},
    )
    paths = [pr["path"] for pr in result.patch_requests]
    assert "doc.md" in paths
    assert any("draft" in r.lower() for r in result.rationale)


def test_python_marker_added_to_py_target(tmp_path):
    (tmp_path / "m.py").write_text("x = 1\n")
    gen = PatchRequestGenerator()
    result = gen.generate(
        str(tmp_path),
        {"target_files": ["m.py"], "title": "t", "task_id": "k", "branch": "x.a"},
    )
    assert result.patch_requests[0]["path"] == "m.py"
    assert "apex-orchestrator draft" in result.patch_requests[0]["new_content"]


def test_fallback_when_no_inlineable_target(tmp_path):
    # No targets resolve to .md/.py -> standalone draft under .apex/patch-drafts/.
    gen = PatchRequestGenerator()
    result = gen.generate(
        str(tmp_path),
        {"target_files": ["nonexistent.bin"], "title": "t", "task_id": "k", "branch": "x.a"},
    )
    assert result.patch_requests[0]["path"].startswith(".apex/patch-drafts/")
    assert result.patch_requests[0]["expected_old_content"] is None
