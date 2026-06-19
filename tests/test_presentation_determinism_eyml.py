"""Determinism red-team regression tests for the PRESENTATION layer.

Two human-facing surfaces were found to leak wall-clock / host-path bytes into
output that CI diffs under the "same repo state -> same bytes" guarantee:

FIX 1 (F2): ``SwarmCoordinator`` printed ``[swarm] ...`` progress lines — some
embedding a wall-clock duration (``Completed in Xs``) — to STDOUT, polluting the
analytical payload of ``apex scan``. They now go to STDERR, so two scans produce
byte-identical STDOUT.

FIX 2 (F3): the reporting dashboard stamps a wall-clock ``generated`` time and
the absolute ``project_root`` into the HTML. That artifact is a *human snapshot*,
explicitly OUT OF SCOPE for the byte guarantee (documented in
``app/reporting/dashboard.py``). This test pins that decision: across two renders
of the same repo state, the timestamp line is the ONLY field that varies.
"""

from __future__ import annotations

import io
import re
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import app.agents.swarm_coordinator as swarm_mod
from app.agents.swarm_coordinator import SwarmCoordinator, _emit_status
from app.reporting.dashboard import build_dashboard


# --------------------------------------------------------------------------- #
# FIX 1 (F2): [swarm] progress lines must NOT pollute scan STDOUT.             #
# --------------------------------------------------------------------------- #


def test_emit_status_writes_to_stderr_not_stdout():
    """The status helper is the single chokepoint: stderr only, stdout clean."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        _emit_status("[swarm] Completed in 1.2s with 0 result(s)")
    assert out.getvalue() == ""
    assert "[swarm] Completed in 1.2s with 0 result(s)" in err.getvalue()


def test_run_autonomous_keeps_swarm_lines_off_stdout():
    """A real (agent-less) run: every ``[swarm]`` line lands on STDERR, and the
    wall-clock ``Completed in Xs`` line is absent from STDOUT entirely."""
    coord = SwarmCoordinator()
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        results = coord.run_autonomous("neutral goal", target=".", mode="report")

    stdout, stderr = out.getvalue(), err.getvalue()
    # The deterministic result is the returned list, not anything on stdout.
    assert isinstance(results, list)
    # STDOUT carries no [swarm] progress noise at all.
    assert "[swarm]" not in stdout
    assert "Completed in" not in stdout
    # The progress trace (incl. the wall-clock line) is preserved on STDERR.
    assert "[swarm] Completed in" in stderr
    assert "[swarm] Goal: neutral goal" in stderr


def test_scan_stdout_is_byte_identical_across_runs():
    """HARD GATE: the wall-clock ``[swarm] Completed in Xs`` line no longer makes
    two runs differ. Because the line is off STDOUT, captured STDOUT is empty and
    byte-identical across runs even though the elapsed duration differs."""
    captured = []
    for _ in range(2):
        coord = SwarmCoordinator()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            coord.run_autonomous("neutral goal", target=".", mode="report")
        captured.append(out.getvalue())
        # Sanity: the timing line really was emitted (just to stderr).
        assert "[swarm] Completed in" in err.getvalue()

    assert captured[0] == captured[1]
    assert "[swarm]" not in captured[0]


def test_emit_status_is_the_only_swarm_print_target():
    """Guard against regression: the module routes status through ``_emit_status``
    (stderr), so no raw ``print(... [swarm] ...)`` to stdout can creep back in."""
    src = Path(swarm_mod.__file__).read_text()
    # Every textual [swarm] line is emitted via the helper, not a bare print.
    assert "print(message, file=sys.stderr)" in src
    assert "[swarm]" in src
    # No [swarm] string is handed to a bare ``print(`` lacking a stderr target.
    for m in re.finditer(r"print\((.*?)\)", src, flags=re.DOTALL):
        assert "[swarm]" not in m.group(1) or "sys.stderr" in m.group(1)


# --------------------------------------------------------------------------- #
# FIX 2 (F3): dashboard is a human snapshot — OUT OF SCOPE for byte-identity.  #
# Pin that the timestamp is the ONLY varying field across two same-state       #
# renders, and that the out-of-scope decision is documented in the module.     #
# --------------------------------------------------------------------------- #


_STAMP_RE = re.compile(r"generated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC")


def _project(tmp: Path) -> Path:
    (tmp / "app").mkdir()
    (tmp / "app" / "svc.py").write_text(
        "import os\ndef run(cmd):\n    return eval(cmd)\n"
    )
    (tmp / "app" / "main.py").write_text("def main():\n    return 1\n")
    return tmp


def _norm(html_doc: str) -> str:
    return _STAMP_RE.sub("generated <STAMP>", html_doc)


def test_dashboard_timestamp_is_the_only_varying_field(tmp_path):
    """OUT-OF-SCOPE decision, pinned: two renders of the same repo state are
    byte-identical once the single wall-clock ``generated`` line is normalized.
    The absolute ``project_root`` is identical across the two renders (same
    checkout), so the timestamp is the only field that can vary."""
    _project(tmp_path)
    first = build_dashboard(str(tmp_path), max_ideas=20, idea_depth=2,
                            breadth=3, quality=False)
    second = build_dashboard(str(tmp_path), max_ideas=20, idea_depth=2,
                             breadth=3, quality=False)

    # Exactly one wall-clock stamp leaks per render.
    assert len(_STAMP_RE.findall(first)) == 1
    # Normalizing that single line makes the two renders byte-identical:
    # the timestamp is provably the ONLY varying field.
    assert _norm(first) == _norm(second)


def test_dashboard_documents_out_of_scope_decision():
    """The module docstring must state the byte-determinism scope decision so the
    leak is a documented, intentional human-snapshot trait — not a silent bug."""
    src = Path(
        __import__("app.reporting.dashboard", fromlist=["__file__"]).__file__
    ).read_text()
    assert "OUT OF SCOPE" in src
    assert "human snapshot" in src
