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

from app.execution._apply_verify import (
    function_of,
    regressed_functions,
    run_full_suite_verification,
    suite_failing_nodes,
)


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


# --- suite_failing_nodes: the DETERMINISTIC full failing-node-id set ----------


class _NodeSummary:
    """A fake TestRunSummary carrying pytest short-summary output."""

    def __init__(self, commands: list, stdout: str = "", stderr: str = "") -> None:
        self.commands = commands
        self.results = [{"stdout": stdout, "stderr": stderr}]


def _patch_nodes(monkeypatch, summary: _NodeSummary, detected=None) -> None:
    """Patch the lazily-imported runner. ``detected`` is what ``_detect_commands``
    returns (defaults to a single pytest command when the summary has commands), so
    ``suite_failing_nodes`` can build its ``--continue-on-collection-errors`` run."""
    import app.skills.execution.run_tests as run_tests_mod

    if detected is None:
        detected = [["python", "-m", "pytest", "-q"]] if summary.commands else []
    captured: dict[str, list] = {}

    class _FakeSkill:
        def _detect_commands(self, root):  # noqa: ANN001 - test double
            return detected

        def run(self, root: str, commands=None):  # noqa: ANN001 - test double
            captured["commands"] = commands
            return summary

    monkeypatch.setattr(run_tests_mod, "RunTestsSkill", _FakeSkill)
    return captured


def test_failing_nodes_parses_every_failed_and_error_node(monkeypatch) -> None:
    # ALL failing nodes (not the 5-cap the human-facing summary uses), both
    # FAILED and ERROR lines, returned as a deterministic sorted frozenset.
    out = (
        "FAILED tests/test_b.py::test_two - AssertionError\n"
        "FAILED tests/test_a.py::test_one - AssertionError\n"
        "ERROR tests/test_c.py::test_err - ImportError\n"
        "FAILED tests/test_a.py::test_three\n"
    )
    _patch_nodes(monkeypatch, _NodeSummary(commands=[["pytest"]], stdout=out))
    available, nodes = suite_failing_nodes(Path("/tmp"))
    assert available is True
    assert nodes == frozenset({
        "tests/test_a.py::test_one",
        "tests/test_a.py::test_three",
        "tests/test_b.py::test_two",
        "tests/test_c.py::test_err",
    })
    # Sorting is deterministic.
    assert sorted(nodes) == [
        "tests/test_a.py::test_one",
        "tests/test_a.py::test_three",
        "tests/test_b.py::test_two",
        "tests/test_c.py::test_err",
    ]


def test_failing_nodes_empty_when_all_green(monkeypatch) -> None:
    _patch_nodes(monkeypatch, _NodeSummary(
        commands=[["pytest"]], stdout="5 passed in 0.1s\n"))
    available, nodes = suite_failing_nodes(Path("/tmp"))
    assert available is True
    assert nodes == frozenset()


def test_failing_nodes_no_suite_available(monkeypatch) -> None:
    # No test command detected -> suite_available False, empty failing set.
    _patch_nodes(monkeypatch, _NodeSummary(commands=[], stdout=""))
    available, nodes = suite_failing_nodes(Path("/tmp"))
    assert available is False
    assert nodes == frozenset()


def test_failing_nodes_threads_continue_on_collection_errors(monkeypatch) -> None:
    # FIX 1: the failing-node run makes collection errors NON-FATAL so one
    # un-collectable module can't mask the whole suite. The pytest command carries
    # ``--continue-on-collection-errors`` exactly once, appended to the detected
    # command (the target's interpreter is preserved).
    captured = _patch_nodes(
        monkeypatch,
        _NodeSummary(commands=[["python", "-m", "pytest", "-q"]], stdout=""),
        detected=[["python", "-m", "pytest", "-q"]])
    suite_failing_nodes(Path("/tmp"))
    assert captured["commands"] == [
        ["python", "-m", "pytest", "-q", "--continue-on-collection-errors"]]
    assert captured["commands"][0].count("--continue-on-collection-errors") == 1


def test_failing_nodes_non_pytest_command_unchanged(monkeypatch) -> None:
    # A non-pytest runner (npm) is NOT given the pytest flag — byte-identical.
    captured = _patch_nodes(
        monkeypatch,
        _NodeSummary(commands=[["npm", "test"]], stdout=""),
        detected=[["npm", "test", "--", "--runInBand"]])
    suite_failing_nodes(Path("/tmp"))
    assert captured["commands"] == [["npm", "test", "--", "--runInBand"]]


def test_failing_nodes_no_collection_error_identical_set(monkeypatch) -> None:
    # CONFIRM byte-identical when there is NO collection error: the same FAILED set
    # is parsed regardless of the (no-op) flag.
    out = "FAILED tests/test_a.py::test_one - AssertionError\n5 passed\n"
    _patch_nodes(monkeypatch, _NodeSummary(
        commands=[["python", "-m", "pytest", "-q"]], stdout=out))
    available, nodes = suite_failing_nodes(Path("/tmp"))
    assert available is True
    assert nodes == frozenset({"tests/test_a.py::test_one"})


# --- function_of: strip the parametrize suffix --------------------------------


def test_function_of_strips_parametrize_suffix() -> None:
    assert function_of("t.py::test_lookup[a-1]") == "t.py::test_lookup"
    assert function_of("t.py::test_lookup[x-1]") == "t.py::test_lookup"
    # A plain (non-parametrized) node is unchanged.
    assert function_of("t.py::test_plain") == "t.py::test_plain"
    # A bare collection-error file (no ``::``) is unchanged.
    assert function_of("t.py") == "t.py"


# --- regressed_functions: function-granularity true-regression diff -----------


def test_regressed_functions_empty_when_nothing_new() -> None:
    base = frozenset({"t.py::test_a", "t.py::test_b"})
    assert regressed_functions(base, base) == frozenset()


def test_regressed_functions_charges_a_new_green_to_red() -> None:
    # A function GREEN at baseline (absent) now RED -> charged.
    base = frozenset({"t.py::test_a"})
    after = frozenset({"t.py::test_a", "t.py::test_new"})
    assert regressed_functions(base, after) == frozenset({"t.py::test_new"})


def test_regressed_functions_ignores_parametrize_id_shift() -> None:
    # FIX 2 (id-shift): same function still RED, parametrize ids shifted ->
    # NOT a regression (no over-rollback). The empty set is returned.
    base = frozenset({"t.py::test_lookup[a-1]", "t.py::test_lookup[b-2]"})
    after = frozenset({"t.py::test_lookup[x-1]", "t.py::test_lookup[y-2]"})
    assert regressed_functions(base, after) == frozenset()


def test_regressed_functions_added_param_case_under_red_func_is_not_regression() -> None:
    # A still-red function gaining an extra parametrize case is not a new failure.
    base = frozenset({"t.py::test_lookup[a-1]"})
    after = frozenset({"t.py::test_lookup[a-1]", "t.py::test_lookup[c-3]"})
    assert regressed_functions(base, after) == frozenset()


def test_regressed_functions_unmask_not_charged() -> None:
    # FIX 3 (unmask): a baseline COLLECTION ERROR (bare file-level ERROR node) that
    # the session clears, unmasking PRE-EXISTING failures of functions in that file,
    # must NOT charge those as regressions — they were masked (never collected, never
    # proven green) at baseline. The diff recognises the baseline collection-error
    # file and excludes after-failures of its functions -> EMPTY set (no over-rollback).
    base = frozenset({"tests/test_mod.py"})  # collection-error file node
    after = frozenset({
        "tests/test_mod.py::test_pre_existing_a",
        "tests/test_mod.py::test_pre_existing_b",
    })
    assert regressed_functions(base, after) == frozenset()


def test_regressed_functions_unmask_still_charges_other_files() -> None:
    # A clearing of one file's collection error does NOT excuse a GENUINE regression
    # introduced in a DIFFERENT, fully-collected file — that is still charged.
    base = frozenset({"tests/test_mod.py"})  # masked file at baseline
    after = frozenset({
        "tests/test_mod.py::test_pre_existing_a",  # unmasked, not charged
        "tests/test_other.py::test_real_regression",  # genuine, charged
    })
    assert regressed_functions(base, after) == frozenset(
        {"tests/test_other.py::test_real_regression"})


def test_regressed_functions_is_deterministic() -> None:
    base = frozenset({"t.py::test_a[1]"})
    after = frozenset({"t.py::test_b", "t.py::test_c"})
    assert regressed_functions(base, after) == regressed_functions(base, after)
