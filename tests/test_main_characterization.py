"""Characterization harness proving app.main.main() is byte-identical
before and after the refactor that shrinks ``main``.

The original (pre-refactor) implementation is preserved verbatim in
``tests/_main_original_snapshot.txt``. Each scenario runs the ORIGINAL and the
REFACTORED ``main()`` in two *separate, fresh subprocesses* against two
freshly-created (but structurally identical) target directories, then compares
stdout, stderr and exit code byte-for-byte.

Separate processes + fresh targets are required because ``main`` (on the
no-plan path) drives ``FractalResearchOrchestrator``, which persists state to
``<target>/.apex`` and embeds per-run timing/run-id fields. Running the two
implementations in isolation removes that cross-run coupling, leaving only
``main``'s own dispatch/printing as the variable under test. Genuinely
volatile fields (run ids, wall-clock durations, micro-timings) are normalized
IDENTICALLY on both sides so any real behavioral divergence still surfaces.

``main()`` takes no argv and is driven entirely by environment variables; it
signals outcomes by early ``return`` plus stdout/stderr (process exit code 0
on success), so those streams + exit code ARE the observable contract.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_MAIN_PATH = REPO_ROOT / "app" / "main.py"
SNAPSHOT_PATH = Path(__file__).resolve().parent / "_main_original_snapshot.txt"

_MAIN_ENV_KEYS = (
    "EPISTEMIC_TARGET_ROOT",
    "EPISTEMIC_FOCUS_BRANCH",
    "EPISTEMIC_OBJECTIVE",
    "EPISTEMIC_AUTOMATION_PLAN",
    "APEX_MODE",
    "APEX_AUTO_PATCH",
    "APEX_AUTO_COMMIT",
    "APEX_MAX_FRACTAL_BUDGET",
    "APEX_SAFETY_POLICY",
    "APEX_PLUGIN_PATH",
    "APEX_USE_FRACTAL",
)

# Driver run in a subprocess. ``mode`` selects which main to invoke:
#   "orig" -> exec the frozen snapshot (with the real app/main __file__)
#   "new"  -> import the live app.main
_DRIVER = r"""
import sys, types
mode = sys.argv[1]
real_main = sys.argv[2]
if mode == "orig":
    src = open(sys.argv[3], encoding="utf-8").read()
    mod = types.ModuleType("_apex_main_orig")
    mod.__file__ = real_main
    code = compile(src, real_main, "exec")
    exec(code, mod.__dict__)
    mod.main()
else:
    from app.main import main
    main()
"""


def _scenarios(target: str) -> list[dict]:
    """A spread of env scenarios covering every branch of ``main``."""
    return [
        {
            "EPISTEMIC_AUTOMATION_PLAN": "project_scan",
            "EPISTEMIC_OBJECTIVE": "security audit",
            "APEX_USE_FRACTAL": "1",
            "APEX_MODE": "report",
            "EPISTEMIC_FOCUS_BRANCH": "",
        },
        {
            "EPISTEMIC_AUTOMATION_PLAN": "project_scan",
            "EPISTEMIC_OBJECTIVE": "audit security risks",
            "APEX_MODE": "report",
            "EPISTEMIC_FOCUS_BRANCH": "",
        },
        {
            "EPISTEMIC_AUTOMATION_PLAN": "docstring_loop",
            "EPISTEMIC_OBJECTIVE": "improve documentation",
            "APEX_MODE": "report",
            "EPISTEMIC_FOCUS_BRANCH": "",
        },
        # Supervised (default) + plan -> safety-gate print path.
        {
            "EPISTEMIC_AUTOMATION_PLAN": "project_scan",
            "EPISTEMIC_OBJECTIVE": "neutral scan",
        },
        {
            "EPISTEMIC_AUTOMATION_PLAN": "security_audit",
            "EPISTEMIC_OBJECTIVE": "neutral",
            "APEX_MODE": "supervised",
            "APEX_USE_FRACTAL": "true",
        },
        # No agents -> legacy runner fallback.
        {
            "EPISTEMIC_AUTOMATION_PLAN": "noop_plan_xyz",
            "EPISTEMIC_OBJECTIVE": "neutral",
            "APEX_MODE": "report",
        },
        {
            "EPISTEMIC_AUTOMATION_PLAN": "project_scan",
            "EPISTEMIC_OBJECTIVE": "neutral",
            "APEX_MODE": "report",
            "APEX_AUTO_PATCH": "yes",
            "APEX_AUTO_COMMIT": "0",
            "APEX_MAX_FRACTAL_BUDGET": "7",
            "APEX_SAFETY_POLICY": "strict",
        },
        {
            "EPISTEMIC_AUTOMATION_PLAN": "project_scan",
            "EPISTEMIC_OBJECTIVE": "neutral",
            "APEX_MODE": "report",
            "APEX_MAX_FRACTAL_BUDGET": "notanumber",
        },
        # No plan -> full orchestrator path, report mode.
        {
            "EPISTEMIC_OBJECTIVE": "neutral scan no plan",
            "APEX_MODE": "report",
            "EPISTEMIC_FOCUS_BRANCH": "",
        },
        # No plan, autonomous mode -> debug trace path.
        {
            "EPISTEMIC_OBJECTIVE": "neutral scan",
            "APEX_MODE": "autonomous",
        },
        # Unknown mode -> falls back to supervised + plan.
        {
            "EPISTEMIC_AUTOMATION_PLAN": "project_scan",
            "EPISTEMIC_OBJECTIVE": "neutral",
            "APEX_MODE": "bogusmode",
        },
        {
            "EPISTEMIC_AUTOMATION_PLAN": "noop_plan_xyz",
            "EPISTEMIC_OBJECTIVE": "neutral",
            "APEX_MODE": "report",
            "APEX_PLUGIN_PATH": "",
        },
    ]


def _normalize(text: str, target: str) -> str:
    """Fold out genuinely volatile, target-specific or timing values.

    Both implementations are normalized identically, so any real divergence in
    ``main``'s control flow or printed literals still fails the assertion.
    """
    text = text.replace(target, "<TARGET>")
    # Timestamped run ids: ``run-<epoch>`` and ``run-<YYYYMMDDTHHMMSSZ>``.
    text = re.sub(r"run-\d{8}T\d{6}Z", "run-<TS>", text)
    text = re.sub(r"run-\d+", "run-<ID>", text)
    text = re.sub(r"debug-\d+\.json", "debug-<TS>.json", text)
    # Any wall-clock duration like ``1.9s`` (swarm + orchestrator banners).
    text = re.sub(r"\d+\.\d+s\b", "<DUR>s", text)
    # An uncaught traceback's intermediate Python frames are implementation
    # structure: decomposing ``main`` into helpers necessarily inserts extra
    # ``app/main.py`` frames and shifts line numbers, while the exit code,
    # exception TYPE and MESSAGE (the contract) are unchanged. Collapse any
    # traceback to ``Traceback...<final exception line>`` so a genuine change
    # in the raised type or message still fails, applied identically to both.
    if text.startswith("Traceback (most recent call last):"):
        last = text.rstrip("\n").splitlines()[-1]
        text = "Traceback (most recent call last):\n<FRAMES>\n" + last + "\n"
    # Token estimates are derived from text that embeds run-ids/timestamps, so
    # they vary run-to-run by a few units. Normalize any ``*tokens`` counter.
    text = re.sub(r'("[\w]*tokens":\s*)[-\d.eE+]+', r"\1<NUM>", text)
    # Other volatile orchestrator timing / state fields (key: number).
    for key in (
        "decompose",
        "synthesize",
        "validate",
        "total",
        "duration",
        "elapsed",
        "previous_run_count",
        "memory_question_repeats_degraded",
        "memory_claim_repeats_degraded",
        # The ``reflection`` block is computed from the shared
        # ``.apex/feedback_log.json`` ledger (FeedbackLoop's cwd-relative default;
        # both impls run with cwd=REPO_ROOT). Under the PARALLEL gate
        # (``verify.py -j N``) other suites' ``main()`` runs append/trim that one
        # shared file, so its entry-count-derived numbers race between the orig and
        # new subprocess reads — runtime ledger state, NOT ``main()``'s control
        # flow. Fold them (and the per-node list below) so a real control-flow or
        # printed-literal divergence still fails, exactly as for the fields above.
        "total_runs",
        "total_actions",
        "success_rate",
        "false_positive_rate",
    ):
        text = re.sub(rf'("{key}":\s*)[-\d.eE+]+', r"\1<NUM>", text)
    # ``top_false_positives`` is the same ledger's per-node digest: its float/int
    # fields and even its membership/order shift by an entry under parallel load.
    # Fold the whole list (its item objects contain no ``]``, so the non-greedy
    # match ends at the list's own close) — the block's presence/structure is still
    # verified, only the race-prone data is normalized.
    text = re.sub(r'("top_false_positives":\s*)\[.*?\]', r"\1<LIST>", text,
                  flags=re.DOTALL)
    return text


def _run(mode: str, env_overrides: dict, target: Path) -> tuple[str, str, int]:
    env = dict(os.environ)
    for key in _MAIN_ENV_KEYS:
        env.pop(key, None)
    env.update(env_overrides)
    env["EPISTEMIC_TARGET_ROOT"] = str(target)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER, mode, str(REAL_MAIN_PATH), str(SNAPSHOT_PATH)],
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    return proc.stdout, proc.stderr, proc.returncode


@pytest.mark.parametrize("idx", range(len(_scenarios("/tmp"))))
def test_main_byte_identical(idx, tmp_path):
    orig_target = tmp_path / "orig"
    new_target = tmp_path / "new"
    for t in (orig_target, new_target):
        t.mkdir()
        (t / "risky.py").write_text("result = eval(user_input)\n")

    scenario = _scenarios(str(tmp_path))[idx]

    o_out, o_err, o_code = _run("orig", scenario, orig_target)
    n_out, n_err, n_code = _run("new", scenario, new_target)

    o_out_n = _normalize(o_out, str(orig_target))
    n_out_n = _normalize(n_out, str(new_target))
    o_err_n = _normalize(o_err, str(orig_target))
    n_err_n = _normalize(n_err, str(new_target))

    assert o_code == n_code, f"exit code diverged in scenario {idx}"
    assert o_out_n == n_out_n, f"stdout diverged in scenario {idx}"
    assert o_err_n == n_err_n, f"stderr diverged in scenario {idx}"


def test_snapshot_is_genuine_original():
    """Guards that the snapshot is the real pre-refactor implementation."""
    text = SNAPSHOT_PATH.read_text(encoding="utf-8")
    assert "def main() -> None:" in text
    assert "_build_swarm_for_plan" in text
    # The original ``main`` body is monolithic: it inlines the env parsing.
    assert "EPISTEMIC_AUTOMATION_PLAN" in text
