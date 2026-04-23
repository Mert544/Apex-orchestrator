from app.engine.self_healing import SelfHealingTestEngine


def test_self_healing_noop_on_passing_tests(tmp_path):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_dummy.py").write_text(
        "def test_ok(): assert True\n", encoding="utf-8"
    )

    engine = SelfHealingTestEngine(tmp_path, test_command="pytest tests/")
    result = engine.heal()

    assert result.iterations >= 1
    assert not result.remaining_failures
    assert not result.patches_applied
