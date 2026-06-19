"""Harden CONVERGENCE re-gates EVERY fix — no unverified behaviour change auto-committed.

P0 "dishonest-green" defect (red-team, eyml): the ``_converge_harden`` loop in
``app/engine/idea_action_bridge.py`` auto-committed the file's REMAINING fixes
UNCONDITIONALLY — it never recomputed the per-fix tier and never consulted
``_unverified_behaviour_change``. So when the LEAD finding was a pure-annotation
flag (``pickle`` -> Tier-0 ``# SECURITY`` comment, correctly committed), the loop
then applied AND committed the same file's behaviour-CHANGING rewrites
(``subprocess shell=True`` -> ``shlex.split``/``shell=False``, ``yaml.load`` ->
``safe_load``) with NO tier re-check, NO shield, NO coverage gate, on a module
with ZERO covering tests. A buyer silently received unverified behaviour changes —
the exact thing the autonomous-commit gate exists to prevent.

The fix re-gates each converged fix EXACTLY as the primary step does:
``_effective_tier`` re-prices the next fix against the CURRENT file, and the
commit is routed through the SAME ``_unverified_behaviour_change`` gate. A
behaviour-changing converged fix on an uncovered module is left APPLIED on disk
but WITHHELD from the commit, and convergence STOPS (the file now carries an
uncommitted change — compounding is unsafe). A Tier-0 converged fix still
commits freely.

HARD GATES pinned here:
  * P0 repro: annotation-led harden on an UNTESTED module with subprocess+yaml
    issues -> the behaviour-changing converged fixes are NOT auto-committed
    (applied-on-disk-but-withheld); git gains ONLY the safe Tier-0 comment commit
    (+ any shield), NOT the subprocess/yaml rewrites.
  * Convergence STILL works honestly: on a COVERED module the converged fixes DO
    commit (verified path) — proves convergence was not just disabled.
  * A multi-annotation file (two Tier-0 flags) still converges and commits both
    (safe additive convergence intact).
  * Determinism: same fixture twice -> byte-identical results.

Mutation-harden: reverting ``_converge_harden`` to the unconditional commit fails
``test_p0_behaviour_changing_converged_fix_withheld_on_untested_module``.

Deterministic, stdlib + pytest only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.models.idea import ActionPlan, ActionStep


# --- helpers -----------------------------------------------------------------

def _git_init(root: Path) -> None:
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t.com"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "-A"],
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"],
    ):
        subprocess.run(cmd, cwd=root, capture_output=True)


def _commit_count(root: Path) -> int:
    out = subprocess.run(["git", "rev-list", "--count", "HEAD"],
                         cwd=root, capture_output=True, text=True)
    return int(out.stdout.strip())


def _log_text(root: Path) -> str:
    return subprocess.run(["git", "log", "-p"], cwd=root,
                          capture_output=True, text=True).stdout


def _harden_step(target: str) -> ActionStep:
    return ActionStep(
        branch_path="x.1", title=f"harden {target}", operator="harden",
        subject=target, action_type="harden_security", target=target,
        executable=True, source_facts=[f"security-finding: {target}"],
    )


def _run_autonomous(root: Path, target: str) -> dict:
    plan = ActionPlan(steps=[_harden_step(target)], mode="autonomous")
    return IdeaActionBridge().apply_plan(
        plan, str(root), mode="autonomous", verify=True, commit=True,
        test_first=True, max_apply=3,
    )


# A module whose TOP finding is a Tier-0 annotation flag (pickle), followed by
# behaviour-CHANGING rewrites (subprocess shell=True literal, yaml.load). The
# detection ladder advances pickle -> subprocess-shell-literal -> yaml.
_VULN_SRC = (
    "import pickle\n"
    "import subprocess\n"
    "import yaml\n"
    "\n"
    "\n"
    "def load(b):\n"
    "    return pickle.loads(b)\n"
    "\n"
    "\n"
    "def run():\n"
    "    return subprocess.run(\"ls\", shell=True)\n"
    "\n"
    "\n"
    "def parse(text):\n"
    "    return yaml.load(text)\n"
)


def _build_uncovered(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    src = tmp_path / "pkg" / "vuln.py"
    src.write_text(_VULN_SRC)
    # A passing test that NEVER references pkg.vuln -> the module is uncovered.
    (tmp_path / "tests" / "test_unrelated.py").write_text(
        "def test_ok():\n    assert True\n")
    _git_init(tmp_path)
    return src


# --- PIN 1: the P0 repro -----------------------------------------------------

def test_p0_behaviour_changing_converged_fix_withheld_on_untested_module(tmp_path):
    src = _build_uncovered(tmp_path)
    before_commits = _commit_count(tmp_path)

    summary = _run_autonomous(tmp_path, "pkg/vuln.py")

    rows = [r for r in summary["results"] if r["action"] == "harden_security"]
    assert len(rows) == 1
    row = rows[0]

    # Lead fix is the Tier-0 annotation flag — correctly committed.
    assert row["transform_type"] == "flag_pickle_loads"
    assert row["risk_tier"] == 0
    assert row["committed"] is True

    # The converged behaviour-changing fix was applied on disk...
    after = src.read_text()
    assert "# SECURITY (Apex: untrusted pickle" in after          # safe Tier-0 comment
    assert 'subprocess.run(shlex.split("ls"), shell=False)' in after  # applied on disk

    # ...but WITHHELD from the auto-commit, and convergence STOPPED before the
    # next behaviour change (yaml stays untouched — compounding on an
    # uncommitted file is unsafe). ``converged_withheld`` is the distinct flag
    # for a withheld CONVERGED fix (the LEAD fix committed fine, so the row's
    # ``commit_withheld`` primary-step semantics are NOT co-opted).
    assert row.get("converged_withheld") is True
    assert "NOT committed" in row.get("reason", "")
    assert "unverified behaviour change" in row.get("reason", "")
    assert "yaml.load(text)" in after          # NOT rewritten
    assert "yaml.safe_load" not in after

    # Git gained ONLY the safe Tier-0 comment commit (+ any shield) — NOT the
    # subprocess rewrite. Before the fix this loop produced 3 auto-fix commits
    # whose diffs contained shlex.split / yaml.safe_load.
    log = _log_text(tmp_path)
    assert "# SECURITY (Apex: untrusted pickle" in log   # the comment IS committed
    assert "shlex.split" not in log                      # the rewrite is NOT committed
    assert "yaml.safe_load" not in log
    # No more than the lead comment commit (+ optional shield) landed.
    assert _commit_count(tmp_path) - before_commits <= 2


# --- PIN 2: convergence STILL commits on a COVERED module (honest green) ------

def test_converged_fix_commits_when_module_is_covered(tmp_path):
    # A vuln module whose top finding is a Tier-0 pickle flag, followed by a
    # behaviour-CHANGING subprocess rewrite — now a function-level test EXERCISES
    # both functions, so the converged fix is verified and DOES commit. Proves
    # the gate withholds only the UNVERIFIED case — convergence is not disabled.
    # (``true`` is used so the deterministic returncode is 0 in any environment.)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    src = tmp_path / "pkg" / "vuln.py"
    src.write_text(
        "import pickle\n"
        "import subprocess\n"
        "\n"
        "\n"
        "def load(b):\n"
        "    return pickle.loads(b)\n"
        "\n"
        "\n"
        "def run():\n"
        '    return subprocess.run("true", shell=True)\n'
    )
    (tmp_path / "tests" / "test_vuln.py").write_text(
        "import pickle\n"
        "from pkg.vuln import load, run\n"
        "\n"
        "def test_load():\n"
        "    assert load(pickle.dumps([1, 2])) == [1, 2]\n"
        "\n"
        "def test_run():\n"
        "    assert run().returncode == 0\n"
    )
    _git_init(tmp_path)

    summary = _run_autonomous(tmp_path, "pkg/vuln.py")
    rows = [r for r in summary["results"] if r["action"] == "harden_security"]
    assert len(rows) == 1
    row = rows[0]

    # Verified by the covering test — nothing withheld.
    assert row["verified"] is True
    assert row.get("converged_withheld") is not True
    assert row.get("commit_withheld") is not True
    assert row.get("converged_fixes", 0) >= 1

    after = src.read_text()
    assert 'subprocess.run(shlex.split("true"), shell=False)' in after

    # The behaviour-changing rewrite is COMMITTED (honest green on a covered
    # module).
    log = _log_text(tmp_path)
    assert "shlex.split" in log


# --- PIN 3: multi-annotation file still converges + commits both (additive) ---

def test_two_tier0_flags_both_converge_and_commit(tmp_path):
    # pickle (flag) + SQL f-string (flag): two pure-annotation Tier-0 findings.
    # Both are comment-only, so safe additive convergence commits BOTH — the gate
    # only fires for behaviour changes.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    src = tmp_path / "pkg" / "flags.py"
    src.write_text(
        "import pickle\n"
        "\n"
        "\n"
        "def load(b):\n"
        "    return pickle.loads(b)\n"
        "\n"
        "\n"
        "def query(cur, uid):\n"
        '    return cur.execute(f"SELECT * FROM u WHERE id={uid}")\n'
    )
    (tmp_path / "tests" / "test_unrelated.py").write_text(
        "def test_ok():\n    assert True\n")
    _git_init(tmp_path)

    summary = _run_autonomous(tmp_path, "pkg/flags.py")
    rows = [r for r in summary["results"] if r["action"] == "harden_security"]
    assert len(rows) == 1
    row = rows[0]

    # Two Tier-0 flags: lead committed + one converged, nothing withheld.
    assert row["risk_tier"] == 0
    assert row["committed"] is True
    assert row.get("converged_withheld") is not True
    assert row.get("converged_fixes", 0) >= 1

    after = src.read_text()
    assert "# SECURITY (Apex: untrusted pickle" in after
    assert "# SECURITY (Apex: SQL injection" in after
    # Both comment-only flags committed; no behaviour change anywhere.
    log = _log_text(tmp_path)
    assert "# SECURITY (Apex: untrusted pickle" in log
    assert "# SECURITY (Apex: SQL injection" in log


# --- PIN 4: determinism — same fixture twice -> byte-identical results --------

# Fields whose value is inherently non-deterministic (a git hash, or a measured
# wall-clock duration the verifier records) — excluded so the comparison pins the
# DECISION (tier, gate, withheld reason, applied/committed) not the stopwatch.
_NONDET_KEYS = {"commit_hash", "duration_seconds"}


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in sorted(obj.items())
                if k not in _NONDET_KEYS}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def _normalise(summary: dict) -> list:
    return [_strip(r) for r in summary["results"]]


def test_determinism_byte_identical_results(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    for root in (root_a, root_b):
        root.mkdir()
        _build_uncovered(root)

    a = _run_autonomous(root_a, "pkg/vuln.py")
    b = _run_autonomous(root_b, "pkg/vuln.py")

    assert _normalise(a) == _normalise(b)
    assert (root_a / "pkg" / "vuln.py").read_text() == \
        (root_b / "pkg" / "vuln.py").read_text()
