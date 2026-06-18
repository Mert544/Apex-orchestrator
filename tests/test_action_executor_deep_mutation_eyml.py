"""Deep-mutation characterization for ``app/engine/action_executor.py``.

The default mutation run caps at 30 seeded faults; the apply/verify/rollback
core has 57 mutable sites. Enumerating the FULL universe and verifying each
splice against the covering tests surfaced 14 survivors the cap masked. This
file kills every REAL survivor and documents the EQUIVALENT ones (mutations
that change source but not observable behaviour, hence unkillable).

Each test names the exact site (``file:line`` + operator) it pins so a future
regression maps straight back to the splice. Special attention is paid to the
verify / promote / replace-count paths: a mutant that lets a one-shot
replacement double-fire, or that promotes the wrong journal record, is exactly
the "fakes green / silently corrupts" defect this executor must never allow.

EQUIVALENT survivors (documented, not killed):
- ``action_executor.py:56`` ``dry_run: bool = False -> True`` (``__init__``
  param). The value is stored as ``self._dry_run`` and never read anywhere in
  the module, so flipping its default is unobservable. (Dead field.)
- ``action_executor.py:116`` ``replace(..., 1) -> 2`` inside the ``dry_run``
  branch. The ``new_content`` it builds is never used (dry-run returns only a
  stdout summary), so the count is unobservable. (Dead assignment.)
- ``action_executor.py:169`` ``timeout=60 -> 61``. Both timeouts dwarf any
  trivial sandbox test run; no deterministic input distinguishes 60s from 61s.
- ``action_executor.py:238`` ``ignore_errors=True -> False`` in ``cleanup``'s
  ``shutil.rmtree``. ``cleanup`` only calls rmtree on an existing directory and
  the flag changes behaviour only when rmtree hits an error; there is no
  deterministic way to force that error without mocking shutil internals.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.action_executor import ActionExecutor, ActionResult
from app.engine.fractal_patch_generator import FractalPatch


def _patch(**kw) -> FractalPatch:
    defaults = dict(
        file="m.py", finding="eval", action="fix",
        old_code="eval(x)", new_code="literal_eval(x)", confidence=0.9,
    )
    defaults.update(kw)
    return FractalPatch(**defaults)


def _exec(tmp_path: Path) -> ActionExecutor:
    (tmp_path / "m.py").write_text("y = eval(x)\n")
    return ActionExecutor(project_root=str(tmp_path))


class TestActionResultDefaults:
    def test_default_feedback_score_is_zero(self):
        # Kills action_executor.py:23  number:0.0>1.0 (ActionResult default).
        # The dataclass default must be the neutral 0.0, not a success score.
        r = ActionResult(action_type="patch", success=True)
        assert r.feedback_score == 0.0


class TestExecutePatchDefaults:
    def test_run_tests_defaults_false_no_pytest_run(self, tmp_path):
        # Kills action_executor.py:84  constant:False>True (run_tests default).
        # Called without run_tests the apply path must NOT shell out to pytest:
        # it returns a "patch" result (not "test") with neutral feedback.
        ex = _exec(tmp_path)
        result = ex.execute_patch(_patch())
        assert result.action_type == "patch"
        assert result.feedback_score == 0.0
        ex.cleanup()

    def test_applied_flag_set_true_after_apply(self, tmp_path):
        # Kills action_executor.py:141  constant:True>False (patch.applied).
        ex = _exec(tmp_path)
        patch = _patch()
        ex.execute_patch(patch)
        assert patch.applied is True
        ex.cleanup()

    def test_applied_not_tested_feedback_is_zero(self, tmp_path):
        # Kills action_executor.py:154  number:0.0>1.0 (applied-not-tested
        # feedback). Applying without running tests is "unknown", never +1.0.
        ex = _exec(tmp_path)
        result = ex.execute_patch(_patch())
        assert result.success is True
        assert result.feedback_score == 0.0
        ex.cleanup()


class TestDryRunResult:
    def test_dry_run_feedback_score_is_zero(self, tmp_path):
        # Kills action_executor.py:122  number:0.0>1.0 (dry-run feedback).
        ex = _exec(tmp_path)
        result = ex.execute_patch(_patch(), dry_run=True)
        assert result.success is True
        assert result.feedback_score == 0.0
        ex.cleanup()


class TestReplaceCountIsOneShot:
    """The apply replaces exactly the FIRST occurrence (count=1). A count=2
    mutant would double-fire and silently corrupt a file with two anchors."""

    def test_sandbox_replaces_only_first_occurrence(self, tmp_path):
        # Kills action_executor.py:139  number:1>2 (the write splice).
        (tmp_path / "m.py").write_text("a = TOKEN\nb = TOKEN\n")
        ex = ActionExecutor(project_root=str(tmp_path))
        ex.execute_patch(_patch(old_code="TOKEN", new_code="X"))
        content = (ex.sandbox_dir / "m.py").read_text()
        assert content == "a = X\nb = TOKEN\n"
        assert content.count("X") == 1
        assert content.count("TOKEN") == 1
        ex.cleanup()

    def test_journal_new_content_replaces_only_first_occurrence(self, tmp_path):
        # Kills action_executor.py:132  number:1>2 (journal new_content splice).
        (tmp_path / "m.py").write_text("a = TOKEN\nb = TOKEN\n")
        ex = ActionExecutor(project_root=str(tmp_path))
        ex.execute_patch(_patch(old_code="TOKEN", new_code="X"))
        record = ex._rollback_journal.records[-1]
        assert record.new_content == "a = X\nb = TOKEN\n"
        ex.cleanup()


class TestRunTestsSubprocessKwargs:
    """A real pytest run must capture stdout as TEXT — these pin the
    subprocess.run keyword arguments that make the captured output usable."""

    def _project_with_test(self, tmp_path) -> ActionExecutor:
        project = tmp_path / "project"
        project.mkdir()
        (project / "m.py").write_text("y = eval(x)\n")
        (project / "test_sandbox_unit.py").write_text(
            "def test_ok():\n    assert 1 + 1 == 2\n"
        )
        return ActionExecutor(project_root=str(project))

    def test_captured_stdout_is_text_not_bytes(self, tmp_path):
        # Kills action_executor.py:168  constant:True>False (text=True).
        # With text=False the captured stdout would be bytes; the result must
        # expose a real str.
        ex = self._project_with_test(tmp_path)
        result = ex.execute_patch(_patch(), run_tests=True)
        assert result.success is True
        assert isinstance(result.stdout, str)
        ex.cleanup()

    def test_stdout_is_actually_captured(self, tmp_path):
        # Kills action_executor.py:167  constant:True>False (capture_output).
        # With capture_output=False, result.stdout would be None instead of the
        # real pytest output text.
        ex = self._project_with_test(tmp_path)
        result = ex.execute_patch(_patch(), run_tests=True)
        assert result.success is True
        assert result.stdout
        assert "passed" in result.stdout
        ex.cleanup()


class TestPromoteMarksCorrectJournalRecord:
    """The promote loop marks the record whose file matches AND is not yet
    promoted (``and``). An ``or`` mutant would promote the FIRST not-yet-promoted
    record regardless of file — marking the WRONG file green."""

    def test_promotes_only_the_changed_files_record(self, tmp_path):
        # Kills action_executor.py:203  boolean:and>or (promote record match).
        project = tmp_path / "project"
        project.mkdir()
        (project / "a.py").write_text("y = eval(x)\n")
        (project / "b.py").write_text("z = eval(x)\n")
        ex = ActionExecutor(project_root=str(project))
        # Record a.py FIRST, then b.py — so the reversed walk hits the
        # non-matching, not-yet-promoted b.py record BEFORE a.py. With `and`
        # b.py is skipped (wrong file); with the `or` mutant b.py's "not
        # promoted" alone satisfies the condition and it is wrongly marked.
        ex.execute_patch(_patch(file="a.py"))
        ex.execute_patch(_patch(file="b.py"))
        # Promote ONLY a.py.
        ex._last_changed_files = ["a.py"]
        assert ex.promote_to_original() is True
        promoted = {r.file_path: r.promoted for r in ex._rollback_journal.records}
        # The a.py record is promoted; b.py is left untouched. Under the `or`
        # mutant the reversed walk would mark b.py (the wrong file) instead and
        # leave a.py unpromoted — a silently mis-tracked promotion.
        assert promoted == {"b.py": False, "a.py": True}
        ex.cleanup()
