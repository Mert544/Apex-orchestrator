import json

from app.mcp.tools import apex_ideate, build_apex_tools


def test_apex_ideate_registered():
    tools = build_apex_tools()
    assert "apex_ideate" in tools
    assert hasattr(tools["apex_ideate"], "input_schema")


def test_apex_ideate_returns_idea_tree(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("def main():\n    return 1\n")
    out = apex_ideate(project_root=str(tmp_path), depth=2, breadth=3, max_ideas=12, actions=True)
    data = json.loads(out)
    assert data["ideas"]
    assert "action_plan" in data
    assert data["action_plan"]["steps"]
