from __future__ import annotations

import os
from pathlib import Path

from app.engine.runtime_trace import (
    RuntimeEvidence,
    StaticFinding,
    confirm_findings,
    trace_callable,
    trace_pytest,
)


def test_executed_lines_empty_for_unknown_path():
    # executed_lines normalises the path and filters the frozenset (lines 53-54);
    # an unknown path yields an empty frozenset.
    ev = RuntimeEvidence(executed=frozenset({("/abs/real.py", 7)}))
    assert ev.executed_lines("/does/not/match.py") == frozenset()


def test_executed_lines_returns_recorded_numbers():
    target = os.path.realpath("/tmp/x.py")
    ev = RuntimeEvidence(executed=frozenset({(target, 2), (target, 9), ("/other.py", 3)}))
    assert ev.executed_lines("/tmp/x.py") == frozenset({2, 9})


def test_trace_callable_accepts_iterable_branch():
    # Passing a non-callable iterable exercises the ``callables = list(target)``
    # branch (line 121); a tuple of two zero-arg callables runs both.
    calls: list[int] = []
    ev = trace_callable((lambda: calls.append(1), lambda: calls.append(2)))
    assert calls == [1, 2]
    assert isinstance(ev, RuntimeEvidence)


def test_confirm_findings_body_refuted_and_confirmed_and_static_only():
    abs_p = os.path.realpath("/proj/mod.py")
    other = os.path.realpath("/proj/other.py")
    # Body line 11 ran -> refuted; file ran but body 11 did not -> runtime-confirmed;
    # no evidence for the file -> static-only. All three carry body_lines.
    ev_body_ran = RuntimeEvidence(executed=frozenset({(abs_p, 11)}))
    ev_file_only = RuntimeEvidence(executed=frozenset({(abs_p, 99)}))
    ev_nothing = RuntimeEvidence(executed=frozenset({(other, 1)}))

    finding = StaticFinding(
        path="/proj/mod.py", lineno=10, symbol="f", body_lines=frozenset({11})
    )
    assert confirm_findings([finding], ev_body_ran)[0].confidence == "refuted"
    assert confirm_findings([finding], ev_file_only)[0].confidence == "runtime-confirmed"
    assert confirm_findings([finding], ev_nothing)[0].confidence == "static-only"


def test_confirm_findings_defline_fallback_branches():
    # Without body_lines the fallback keys on the def line (lines 208-213).
    abs_p = os.path.realpath("/proj/dl.py")
    finding = StaticFinding(path="/proj/dl.py", lineno=4, symbol="g")
    # def line ran -> refuted
    ran = RuntimeEvidence(executed=frozenset({(abs_p, 4)}))
    assert confirm_findings([finding], ran)[0].confidence == "refuted"
    # file ran elsewhere but not the def line -> runtime-confirmed
    elsewhere = RuntimeEvidence(executed=frozenset({(abs_p, 99)}))
    assert confirm_findings([finding], elsewhere)[0].confidence == "runtime-confirmed"
    # no evidence at all -> static-only
    empty = RuntimeEvidence(executed=frozenset())
    assert confirm_findings([finding], empty)[0].confidence == "static-only"


def _write_trivial_test(tmp: Path) -> Path:
    t = tmp / "test_traced_sample.py"
    t.write_text("def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    return t


def test_trace_pytest_no_root_runs_named_test(tmp_path: Path):
    # trace_pytest with root=None traces pytest in-process over a narrow path
    # and returns RuntimeEvidence (lines 161-167).
    t = _write_trivial_test(tmp_path)
    ev = trace_pytest(str(t))
    assert isinstance(ev, RuntimeEvidence)
    assert ev.has_evidence_for(str(t))


def test_trace_pytest_with_root_restores_cwd(tmp_path: Path):
    # When root is given the run happens with that cwd and restores it after
    # (lines 169-174), even though the traced run itself succeeds.
    _write_trivial_test(tmp_path)
    before = os.getcwd()
    ev = trace_pytest("test_traced_sample.py", root=str(tmp_path))
    assert os.getcwd() == before
    assert isinstance(ev, RuntimeEvidence)
