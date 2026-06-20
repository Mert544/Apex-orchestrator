"""Characterization of the shared apply-verification tail.

``apply_rename`` (cross_file_rename) and ``apply_move`` (move_module) used to
carry a byte-identical nine-line block that ran the project's full test suite and
stamped ``verified`` / ``test_evidence`` onto the result dict, returning early on
success. That block now lives once in
:func:`app.execution._apply_verify.run_full_suite_verification`; these tests pin
its contract and confirm both call sites still observe it.
"""

from __future__ import annotations

from pathlib import Path

from app.execution._apply_verify import run_full_suite_verification


class _Summary:
    def __init__(self, ok: bool, commands: list[str]) -> None:
        self.ok = ok
        self.commands = commands


def _patch_runner(monkeypatch, summary: _Summary) -> None:
    """Make the lazily-imported runner/summariser deterministic."""
    import app.skills.execution.run_tests as run_tests_mod
    import app.engine.proof_of_fix as proof_mod

    class _FakeSkill:
        def run(self, root: str):  # noqa: ANN001 - test double
            return summary

    monkeypatch.setattr(run_tests_mod, "RunTestsSkill", _FakeSkill)
    monkeypatch.setattr(proof_mod, "summarize_test_run", lambda s: {"ok": s.ok})


def test_passing_suite_stands_and_marks_not_rolled_back(monkeypatch) -> None:
    _patch_runner(monkeypatch, _Summary(ok=True, commands=["pytest"]))
    out: dict = {}
    stands = run_full_suite_verification(Path("/tmp"), out)
    assert stands is True
    assert out["verified"] is True
    assert out["rolled_back"] is False
    assert out["test_evidence"] == {"ok": True}


def test_no_commands_also_stands(monkeypatch) -> None:
    # No test commands to run -> the change stands (verified is False, but the
    # caller still returns early without rolling back).
    _patch_runner(monkeypatch, _Summary(ok=False, commands=[]))
    out: dict = {}
    stands = run_full_suite_verification(Path("/tmp"), out)
    assert stands is True
    assert out["verified"] is False
    assert out["rolled_back"] is False


def test_failing_suite_requests_rollback(monkeypatch) -> None:
    _patch_runner(monkeypatch, _Summary(ok=False, commands=["pytest"]))
    out: dict = {}
    stands = run_full_suite_verification(Path("/tmp"), out)
    assert stands is False
    assert out["verified"] is False
    # On failure the helper does NOT set rolled_back — that is the caller's job.
    assert "rolled_back" not in out
    assert out["test_evidence"] == {"ok": False}


def test_verified_is_a_real_bool(monkeypatch) -> None:
    # The original block coerced with bool(summary.ok); a truthy non-bool must
    # land as a genuine bool.
    _patch_runner(monkeypatch, _Summary(ok="yes", commands=["pytest"]))  # type: ignore[arg-type]
    out: dict = {}
    run_full_suite_verification(Path("/tmp"), out)
    assert out["verified"] is True


def test_apply_rename_uses_the_shared_tail(tmp_path: Path, monkeypatch) -> None:
    from app.execution import cross_file_rename
    from app.execution.cross_file_rename import apply_rename, plan_rename

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "mod.py").write_text("def helper(x):\n    return x\n")
    (tmp_path / "pkg" / "use.py").write_text(
        "from pkg.mod import helper\n\ndef go():\n    return helper(1)\n")

    calls: dict[str, int] = {"verify": 0}

    def _fake_verify(root, out, *, strength_inputs=None):  # noqa: ANN001 - test double
        calls["verify"] += 1
        out["verified"] = True
        out["rolled_back"] = False
        return True

    monkeypatch.setattr(cross_file_rename, "run_full_suite_verification", _fake_verify)
    plan = plan_rename(str(tmp_path), "helper", "helper2")
    res = apply_rename(str(tmp_path), plan, verify=True)
    assert calls["verify"] == 1
    assert res["verified"] is True
    assert res["rolled_back"] is False


def test_apply_move_uses_the_shared_tail(tmp_path: Path, monkeypatch) -> None:
    from app.execution import move_module
    from app.execution.move_module import apply_move, plan_move

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "mod.py").write_text("def helper(x):\n    return x\n")
    (tmp_path / "pkg" / "use.py").write_text(
        "from pkg.mod import helper\n\ndef go():\n    return helper(1)\n")

    calls: dict[str, int] = {"verify": 0}

    def _fake_verify(root, out):  # noqa: ANN001 - test double
        calls["verify"] += 1
        out["verified"] = True
        out["rolled_back"] = False
        return True

    monkeypatch.setattr(move_module, "run_full_suite_verification", _fake_verify)
    plan = plan_move(str(tmp_path), "pkg/mod.py", "pkg/mod2.py")
    res = apply_move(str(tmp_path), plan, verify=True)
    assert calls["verify"] == 1
    assert res["verified"] is True
    assert res["rolled_back"] is False
