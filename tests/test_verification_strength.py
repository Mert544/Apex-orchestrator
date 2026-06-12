"""Coverage-aware verification: what a green suite proves about a change."""

from __future__ import annotations

from app.engine.verification_strength import assess_strength, changed_functions


def test_changed_functions_detects_modified_and_new():
    old = "def a():\n    return 1\n\ndef b():\n    return 2\n"
    new = "def a():\n    return 99\n\ndef b():\n    return 2\n\ndef c():\n    return 3\n"
    assert changed_functions(old, new) == ["a", "c"]


def test_changed_functions_unparsable_side_is_silent():
    assert changed_functions("def broken(:\n", "def ok():\n    return 1\n") == ["ok"]


def _project(tmp_path, test_body: str):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def handler(x):\n    return x + 1\n")
    (tmp_path / "tests" / "test_x.py").write_text(test_body)
    return tmp_path


def _assess(tmp_path):
    old = "def handler(x):\n    return x + 1\n"
    new = 'def handler(x):\n    """D."""\n    return x + 1\n'
    return assess_strength(tmp_path, ["app/svc.py"], {"app/svc.py": old}, {"app/svc.py": new})


def test_function_level_when_a_referencing_test_names_the_function(tmp_path):
    _project(tmp_path, "from app.svc import handler\ndef test_h():\n    assert handler(1) == 2\n")
    s = _assess(tmp_path)
    assert s["level"] == "function"
    assert s["changed_functions"] == ["app/svc.py::handler"]
    assert s["function_tests"] == ["tests/test_x.py"]


def test_module_level_when_referenced_but_function_unnamed(tmp_path):
    _project(tmp_path, "import app.svc\ndef test_smoke():\n    assert app.svc is not None\n")
    s = _assess(tmp_path)
    assert s["level"] == "module"
    assert s["module_tests"] == ["tests/test_x.py"]
    assert s["function_tests"] == []


def test_none_level_when_suite_never_looks_at_the_module(tmp_path):
    _project(tmp_path, "def test_unrelated():\n    assert 1 + 1 == 2\n")
    assert _assess(tmp_path)["level"] == "none"


def test_test_change_level_when_only_tests_changed(tmp_path):
    _project(tmp_path, "def test_t():\n    assert True\n")
    s = assess_strength(tmp_path, ["tests/test_new.py"], {}, {"tests/test_new.py": "def test_n():\n    assert True\n"})
    assert s["level"] == "test-change"


def test_weakest_link_across_changed_files(tmp_path):
    # One covered file + one uncovered file -> the claim degrades to 'none'.
    _project(tmp_path, "from app.svc import handler\ndef test_h():\n    assert handler(1) == 2\n")
    (tmp_path / "app" / "ghost.py").write_text("def g():\n    return 1\n")
    s = assess_strength(
        tmp_path, ["app/svc.py", "app/ghost.py"],
        {"app/svc.py": "def handler(x):\n    return x + 1\n", "app/ghost.py": "def g():\n    return 1\n"},
        {"app/svc.py": 'def handler(x):\n    """D."""\n    return x + 1\n',
         "app/ghost.py": 'def g():\n    """D."""\n    return 1\n'},
    )
    assert s["level"] == "none"


def test_apply_step_attaches_strength_and_proof_records_it(tmp_path):
    # End to end: a verified docstring fix on a module whose test names the
    # changed function is recorded as function-level verification.
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "svc.py").write_text("def handler(x):\n    return x + 1\n")
    (tmp_path / "tests" / "test_svc.py").write_text(
        "from app.svc import handler\ndef test_h():\n    assert handler(1) == 2\n"
    )
    from app.engine.idea_action_bridge import IdeaActionBridge
    from app.engine.proof_of_fix import build_proof
    from app.models.idea import IdeaNode

    idea = IdeaNode(id="i", title="Document: app/svc.py", subject="app/svc.py",
                    operator="document", operator_chain=["document"],
                    source_facts=["dependency-hub: app/svc.py"])
    step = IdeaActionBridge().plan_idea(idea)
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised", verify=True)
    assert res["applied"] is True
    assert res["verification_strength"]["level"] == "function"

    summary = {"mode": "supervised", "verify": True, "total_executable": 1,
               "applied": 1, "rolled_back": 0, "blocked": 0, "committed": 0,
               "results": [{"branch": "x", "action": "add_docstring", "operator": "document",
                            "label": "dependency-hub", "target": "app/svc.py", **res}]}
    record = build_proof(summary, str(tmp_path))["fixes"][0]
    assert record["verification"]["strength"]["level"] == "function"


def test_maintenance_markdown_says_what_the_suite_proves():
    from app.engine.idea_action_bridge import render_maintenance_markdown

    summary = {"mode": "supervised", "verify": True, "total_executable": 2,
               "applied": 2, "rolled_back": 0, "blocked": 0,
               "results": [
                   {"branch": "a", "action": "add_docstring", "applied": True, "verified": True,
                    "changed_files": ["app/x.py"], "target": "app/x.py",
                    "verification_strength": {"level": "function"}},
                   {"branch": "b", "action": "add_docstring", "applied": True, "verified": True,
                    "changed_files": ["app/y.py"], "target": "app/y.py",
                    "verification_strength": {"level": "none"}},
               ]}
    md = render_maintenance_markdown(summary, ".")
    assert "name the changed function" in md
    assert "⚠️ no test references this module" in md
