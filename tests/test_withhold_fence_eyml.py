"""Withheld-change FENCE — a later same-file auto-commit cannot leak it into git.

P1 "autonomous-commit honesty" breach (independent auditor, eyml): the per-step
commit gate correctly WITHHELDS a behaviour-changing rewrite (leaving it applied
on disk for review), but a LATER step that commits the SAME FILE swept the
withheld hunk into git via whole-file staging in
``app/engine/git_auto_commit.py`` (``git add -- <file>`` + ``git commit --
<file>`` stages the ENTIRE file).

Exact repro: ``pkg/vuln.py`` (pickle + subprocess shell=True + yaml.load,
UNTESTED) + a passing unrelated test. ``harden_security`` commits the lead Tier-0
pickle comment, then converges and WITHHELDS the behaviour-changing
``subprocess shell=True`` -> ``shlex.split``/``shell=False`` rewrite
(``converged_withheld: true``, "NOT committed — review before committing")
leaving the hunk on disk (convergence then STOPS before yaml). A LATER
``add_docstring`` step on the SAME file is Tier-0, so the gate does NOT withhold
it and ``_settle_applied`` committed it — sweeping the still-on-disk
``shlex.split`` change into git, unreviewed. BREACH.

The fix is a per-pass FILE FENCE: when any step withholds a behaviour change, its
changed file(s) are added to ``_MaintenancePass._fenced_files``. Before any
auto-commit of a later step, if its target is fenced the commit is SKIPPED — the
fix stays applied-on-disk-for-review and is recorded fenced. The fence is
file-scoped: a Tier-0 fix on a DIFFERENT, unfenced file still commits normally.
The "applied on disk for review" semantics are preserved (no hunk is reverted).

(The auditor framed the leak via ``yaml.load`` -> ``yaml.safe_load``; on this
fixture convergence withholds the FIRST behaviour change it reaches — the
``subprocess`` rewrite — and stops, so the asserted withheld hunk is
``shlex.split``. Either way it is a behaviour change reported "NOT committed".)

HARD GATES pinned here:
  * The auditor's exact leak: withheld behaviour change + later Tier-0 fix on the
    SAME file -> ``git show HEAD:<file>`` must NOT contain the withheld change;
    the later step is recorded not-committed/fenced; determinism across two runs.
  * A Tier-0 fix on a DIFFERENT (unfenced) file in the same pass STILL commits —
    the fence is file-scoped, not a global freeze.
  * A no-withhold pass commits byte-identically to before (no fence side-effects).
  * Mutation-harden: removing the fence check re-introduces the leak.

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


def _head_blob(root: Path, rel: str) -> str:
    out = subprocess.run(["git", "show", f"HEAD:{rel}"],
                         cwd=root, capture_output=True, text=True)
    return out.stdout


def _log_text(root: Path) -> str:
    return subprocess.run(["git", "log", "-p"], cwd=root,
                          capture_output=True, text=True).stdout


def _commit_count(root: Path) -> int:
    out = subprocess.run(["git", "rev-list", "--count", "HEAD"],
                         cwd=root, capture_output=True, text=True)
    return int(out.stdout.strip())


def _harden_step(target: str) -> ActionStep:
    return ActionStep(
        branch_path="x.1", title=f"harden {target}", operator="harden",
        subject=target, action_type="harden_security", target=target,
        executable=True, source_facts=[f"security-finding: {target}"],
    )


def _docstring_step(target: str, branch: str = "x.2") -> ActionStep:
    return ActionStep(
        branch_path=branch, title=f"document {target}", operator="document",
        subject=target, action_type="add_docstring", target=target,
        executable=True, source_facts=[f"missing-docstring: {target}"],
    )


# An untested module: pickle (Tier-0 flag) + subprocess shell=True + yaml.load.
# The detection ladder advances pickle -> subprocess-shell-literal -> yaml, and
# the yaml rewrite is the behaviour-changing fix that gets WITHHELD.
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
    '    return subprocess.run("ls", shell=True)\n'
    "\n"
    "\n"
    "def parse(text):\n"
    "    return yaml.load(text)\n"
)

# A plain module that needs a docstring but has no withheld change.
_PLAIN_SRC = (
    "def greet(name):\n"
    '    return "hi " + name\n'
)


def _build_vuln(root: Path) -> Path:
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    src = root / "pkg" / "vuln.py"
    src.write_text(_VULN_SRC)
    # Passing test that NEVER references pkg.vuln -> the module is uncovered.
    (root / "tests" / "test_unrelated.py").write_text(
        "def test_ok():\n    assert True\n")
    _git_init(root)
    return src


def _run(root: Path, steps: list[ActionStep], max_apply: int = 5) -> dict:
    plan = ActionPlan(steps=steps, mode="autonomous")
    return IdeaActionBridge().apply_plan(
        plan, str(root), mode="autonomous", verify=True, commit=True,
        test_first=True, max_apply=max_apply,
    )


# --- PIN 1: the auditor's exact leak is fenced -------------------------------

def test_withheld_change_not_swept_by_later_same_file_docstring(tmp_path):
    src = _build_vuln(tmp_path)
    summary = _run(tmp_path, [
        _harden_step("pkg/vuln.py"),
        _docstring_step("pkg/vuln.py"),
    ])

    rows = {r["action"]: r for r in summary["results"]}
    harden = rows["harden_security"]
    doc = rows["add_docstring"]

    # The harden step withheld the behaviour-changing subprocess rewrite, which
    # is left applied on disk (convergence STOPS at the first behaviour change).
    assert harden.get("converged_withheld") is True
    after = src.read_text()
    assert 'subprocess.run(shlex.split("ls"), shell=False)' in after  # on disk
    assert 'subprocess.run("ls", shell=True)' not in after

    # The LATER same-file docstring step was APPLIED but NOT committed — fenced.
    assert doc.get("applied") is True
    assert doc.get("committed") is False
    assert doc.get("fenced") is True
    assert "unreviewed withheld change" in doc.get("reason", "")

    # THE BREACH CHECK: the withheld rewrite must NOT be in git.
    head = _head_blob(tmp_path, "pkg/vuln.py")
    assert "shlex.split" not in head
    assert 'subprocess.run("ls", shell=True)' in head   # HEAD keeps the original
    log = _log_text(tmp_path)
    assert "shlex.split" not in log


def test_fence_is_deterministic_across_runs(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    for root in (root_a, root_b):
        root.mkdir()
        _build_vuln(root)

    steps_a = [_harden_step("pkg/vuln.py"), _docstring_step("pkg/vuln.py")]
    steps_b = [_harden_step("pkg/vuln.py"), _docstring_step("pkg/vuln.py")]
    a = _run(root_a, steps_a)
    b = _run(root_b, steps_b)

    nondet = {"commit_hash", "duration_seconds"}

    def strip(obj):
        if isinstance(obj, dict):
            return {k: strip(v) for k, v in sorted(obj.items())
                    if k not in nondet}
        if isinstance(obj, list):
            return [strip(v) for v in obj]
        return obj

    assert strip(a["results"]) == strip(b["results"])
    assert _head_blob(root_a, "pkg/vuln.py") == _head_blob(root_b, "pkg/vuln.py")
    assert "shlex.split" not in _head_blob(root_a, "pkg/vuln.py")


# --- PIN 2: the fence is file-scoped, not a global freeze --------------------

def test_tier0_fix_on_different_file_still_commits(tmp_path):
    _build_vuln(tmp_path)
    other = tmp_path / "pkg" / "plain.py"
    other.write_text(_PLAIN_SRC)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "plain"],
                   cwd=tmp_path, capture_output=True)

    summary = _run(tmp_path, [
        _harden_step("pkg/vuln.py"),              # withholds -> fences vuln.py
        _docstring_step("pkg/vuln.py", "x.2"),    # fenced -> NOT committed
        _docstring_step("pkg/plain.py", "x.3"),   # unfenced -> committed
    ])
    rows = {r["target"]: r for r in summary["results"]
            if r["action"] == "add_docstring"}

    # Same-file docstring is fenced...
    assert rows["pkg/vuln.py"].get("fenced") is True
    assert rows["pkg/vuln.py"].get("committed") is False
    # ...but the DIFFERENT, unfenced file's docstring DID commit.
    assert rows["pkg/plain.py"].get("committed") is True
    assert rows["pkg/plain.py"].get("fenced") is not True

    head_plain = _head_blob(tmp_path, "pkg/plain.py")
    assert '"""' in head_plain                    # docstring reached git
    # The withheld vuln rewrite is still NOT in git.
    assert "shlex.split" not in _head_blob(tmp_path, "pkg/vuln.py")


# --- PIN 3: a no-withhold pass commits exactly as before ---------------------

def test_no_withhold_pass_commits_as_before(tmp_path):
    # A clean module with only a missing docstring (Tier-0, no behaviour change,
    # nothing withheld) -> the docstring fix commits normally and no entry is
    # ever fenced. Pins the common case as byte-identical to pre-fence behaviour.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    src = tmp_path / "pkg" / "plain.py"
    src.write_text(_PLAIN_SRC)
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n")
    _git_init(tmp_path)
    before = _commit_count(tmp_path)

    summary = _run(tmp_path, [_docstring_step("pkg/plain.py")])
    doc = summary["results"][0]

    assert doc.get("applied") is True
    assert doc.get("committed") is True
    assert doc.get("fenced") is not True
    assert "fenced" not in doc                     # key absent, not just falsey
    assert summary["committed"] == 1
    assert _commit_count(tmp_path) == before + 1
    assert '"""' in _head_blob(tmp_path, "pkg/plain.py")


# --- PIN 4: mutation-harden — without the fence the leak returns -------------

def test_mutation_without_fence_leaks(tmp_path):
    # Directly exercises the fence on a _MaintenancePass: fence a file, then a
    # Tier-0 fix on it must be withheld. If the fence check in _settle_applied
    # is removed (mutation), this fix would commit and the assertion fails — so
    # this test FAILS when the safety check is reverted.
    src = _build_vuln(tmp_path)
    summary = _run(tmp_path, [
        _harden_step("pkg/vuln.py"),
        _docstring_step("pkg/vuln.py"),
    ])
    doc = next(r for r in summary["results"] if r["action"] == "add_docstring")
    # The fence MUST have withheld the docstring commit.
    assert doc.get("committed") is False, (
        "fence removed: the later same-file Tier-0 fix committed, sweeping the "
        "withheld change into git"
    )
    assert "shlex.split" not in _head_blob(tmp_path, "pkg/vuln.py")
    # src sanity: the withheld change is still applied on disk for review.
    assert "shlex.split" in src.read_text()
