from __future__ import annotations

from app.execution.semantic.transforms import modernize


def test_rewrites_eq_and_ne_none():
    src = "def f(x):\n    if x == None:\n        return x != None\n"
    r = modernize.apply("m.py", src, "modernize")
    assert r is not None
    out = r.patch_requests[0]["new_content"]
    assert "x is None" in out
    assert "x is not None" in out
    assert "== None" not in out and "!= None" not in out
    assert r.transform_type == "modernize_none_comparison"


def test_handles_no_space_form():
    src = "y = (a ==None)\n"
    r = modernize.apply("m.py", src, "modernize")
    assert r is not None
    assert "is None" in r.patch_requests[0]["new_content"]


def test_ignores_none_in_strings_and_comments():
    # AST-based: '== None' inside a string/comment must not be rewritten.
    src = "s = 'x == None'  # compare x == None\nz = 1\n"
    assert modernize.apply("m.py", src, "modernize") is None


def test_none_on_left_side():
    src = "def f(x):\n    return None == x\n"
    r = modernize.apply("m.py", src, "modernize")
    assert r is not None
    assert "None is x" in r.patch_requests[0]["new_content"]


def test_no_none_comparison_returns_none():
    assert modernize.apply("m.py", "def f(x):\n    return x is None\n", "modernize") is None


def test_syntax_error_returns_none():
    assert modernize.apply("m.py", "def broken(:\n", "modernize") is None


def test_bridge_detects_modernization(tmp_path):
    from app.engine.idea_action_bridge import IdeaActionBridge

    (tmp_path / "a.py").write_text("def f(x):\n    return x == None\n")
    (tmp_path / "b.py").write_text("def f(x):\n    return x is None\n")
    assert IdeaActionBridge._detect_modernization(str(tmp_path), "a.py") is True
    assert IdeaActionBridge._detect_modernization(str(tmp_path), "b.py") is False
    # A comment-only match is not detected.
    (tmp_path / "c.py").write_text("# x == None\nz = 1\n")
    assert IdeaActionBridge._detect_modernization(str(tmp_path), "c.py") is False


def test_end_to_end_simplify_modernizes(tmp_path):
    # A "simplify" idea on a file with `== None` applies the modernization.
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.models.idea import IdeaNode

    (tmp_path / "cmp.py").write_text("def f(x):\n    if x == None:\n        return 1\n    return 0\n")
    idea = IdeaNode(id="i", title="Simplify: cmp.py", subject="cmp.py", operator="simplify",
                    operator_chain=["simplify"], source_facts=["symbol-hub: cmp.py"])
    bridge = IdeaActionBridge()
    step = bridge.plan_idea(idea)
    assert step.action_type == "organize_imports"
    preview = bridge.draft_patch(step, str(tmp_path))
    assert preview is not None
    assert preview.get("transform_type") == "modernize_none_comparison"
