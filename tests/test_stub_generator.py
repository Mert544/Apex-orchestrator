

def test_dunder_module_target_is_refused(tmp_path):
    # A stub request for __init__/__main__ must be refused outright — the
    # name-based source lookup would resolve to the wrong package's file.
    from app.execution.semantic.generators.stub import try_create_stub

    (tmp_path / "app" / "agents" / "limbs").mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "agents" / "limbs" / "__init__.py").write_text("")
    assert try_create_stub(tmp_path, "tests/test___init__.py", "t", "id") is None
