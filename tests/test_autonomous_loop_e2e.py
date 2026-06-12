"""End-to-end guard for the autonomous improvement loop.

These tests exercise the *whole seam* — perceive (scan) → propose (ideate) →
apply → **verify (run the project's real tests)** → converge — on a realistic
messy project, asserting real outcomes (fixes land, nothing rolls back, findings
drop, the files are actually corrected, and the project's tests still pass).

This is the test class that would have caught the "verify always fails because
RunTestsSkill spawned the wrong Python interpreter" bug, which left every fix
rolling back while 1600+ unit tests stayed green. Component unit tests can't see
that seam; only running the full loop against a real project can.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.engine.evolution import EvolutionLoop


def _messy_project(tmp_path: Path) -> Path:
    """A project with real, auto-fixable issues + a passing test suite that
    imports the project's own modules (so the verify path must use a working
    interpreter). Uses only stdlib so it runs in any environment."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    # eval + os.system + a mutable default argument
    (tmp_path / "app" / "danger.py").write_text(
        "import os\n"
        "def run(cmd, history=[]):\n"
        "    history.append(cmd)\n"
        "    os.system(cmd)\n"
        "    return eval(cmd)\n"
    )
    # `== None` comparison
    (tmp_path / "app" / "cfg.py").write_text(
        "def get(x):\n    if x == None:\n        return 0\n    return x\n"
    )
    (tmp_path / "app" / "util.py").write_text(
        "def parse(s):\n    try:\n        return int(s)\n    except:\n        return 0\n"
    )
    # A real test suite that imports the project's modules and passes.
    (tmp_path / "tests" / "test_app.py").write_text(
        "from app.cfg import get\n"
        "from app.util import parse\n"
        "def test_get():\n    assert get(None) == 0\n    assert get(7) == 7\n"
        "def test_parse():\n    assert parse('5') == 5\n    assert parse('x') == 0\n"
    )
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t.com"],
                ["git", "config", "user.name", "t"], ["git", "add", "-A"],
                ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=tmp_path, capture_output=True)
    return tmp_path


def test_evolve_actually_applies_verified_fixes(tmp_path):
    # The core guarantee: the loop APPLIES fixes (not just plans them) and they
    # pass verification. The RunTestsSkill bug made this assertion fail (0
    # applied, everything rolled back) while every unit test stayed green.
    _messy_project(tmp_path)
    result = EvolutionLoop(tmp_path, mode="supervised", max_cycles=3, max_apply_per_cycle=6).run()

    assert result.applied >= 3, f"expected real fixes to land, got {result.applied}"
    assert not result.circuit_broken, "the loop should not thrash; fixes must verify cleanly"
    # Findings must go down (ideally to zero) — the project got healthier.
    assert result.after["security_findings"] < result.before["security_findings"]


def test_evolve_actually_fixes_the_source(tmp_path):
    proj = _messy_project(tmp_path)
    EvolutionLoop(proj, mode="supervised", max_cycles=3, max_apply_per_cycle=6).run()

    danger = (proj / "app" / "danger.py").read_text()
    cfg = (proj / "app" / "cfg.py").read_text()
    assert "ast.literal_eval(cmd)" in danger   # eval rewritten to the safe form
    assert "os.system" not in danger           # os.system replaced
    assert "history=[]" not in danger          # mutable default fixed
    assert "== None" not in cfg                # comparison modernized


def test_project_tests_still_pass_after_evolve(tmp_path):
    # A self-improvement run must never leave the project broken: its own test
    # suite must still pass afterward (verified independently here).
    proj = _messy_project(tmp_path)
    EvolutionLoop(proj, mode="supervised", max_cycles=3, max_apply_per_cycle=6).run()
    # Isolate like RunTestsSkill does: PYTHONPATH = the project under test ONLY.
    # An inherited PYTHONPATH (e.g. Apex's own root when Apex verifies itself)
    # would make the tmp project's namespace `app/` lose to Apex's regular
    # `app/` package — found by dogfooding `apex auto` on this repo.
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(proj)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(proj), capture_output=True, text=True, timeout=120, env=env,
    )
    assert result.returncode == 0, f"project tests broke after evolve:\n{result.stdout[-800:]}"
