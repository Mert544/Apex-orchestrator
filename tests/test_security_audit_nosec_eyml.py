"""`scripts/security_audit.py` — `# nosec` acknowledgment mechanism.

The audit fails the pipeline on critical call patterns (eval/exec/os.system/
pickle.loads/yaml.load). Deliberate, reviewed uses — like the fixed-template
eval/exec sites in ``app/execution/stub_synthesis.py`` — carry bandit-style
``# nosec <rule> - <rationale>`` annotations. These tests pin the honest
contract of honoring them:

  * an UNANNOTATED critical call still fails (bucketed ``critical``);
  * an annotated call moves to the ``acknowledged`` bucket — visible in the
    report and summary, but not pipeline-failing;
  * strictly FAIL-CLOSED: mixed annotation (one call marked, one not, in the
    same function) stays critical; so does anything unresolvable;
  * class methods and multi-line call spans are handled;
  * live pin: Apex's own tree audits with ZERO unacknowledged criticals —
    every deliberate eval/exec is annotated (RED before this mechanism:
    security-audit failed live on PR #4 with 6 criticals in
    ``stub_synthesis.py``, every one already carrying `# nosec`).

Discovered live: the first time the security-audit CI job got past its test
stage (after the shallow-clone fix), it turned out the audit script had never
been green on Apex's own codebase — the deliberate synthesis-engine eval/exec
sites were annotated for bandit, but our own auditor ignored the annotations.
"""

from __future__ import annotations

from pathlib import Path

from scripts.security_audit import run_audit


def _project(tmp_path: Path, body: str) -> Path:
    (tmp_path / "core.py").write_text(body, encoding="utf-8")
    return tmp_path


def _critical_names(report: dict) -> set[str]:
    return {r["function"] for r in report["risks"]["critical"]}


def _acknowledged_names(report: dict) -> set[str]:
    return {r["function"] for r in report["risks"]["acknowledged"]}


def test_unannotated_eval_stays_critical(tmp_path):
    root = _project(tmp_path, (
        "def risky(expr):\n"
        "    '''Evaluate.'''\n"
        "    return eval(expr)\n"))
    report = run_audit(root)
    assert report["summary"]["critical"] == 1
    assert report["summary"]["acknowledged"] == 0
    assert _critical_names(report) == {"risky"}


def test_nosec_annotated_eval_is_acknowledged_not_critical(tmp_path):
    root = _project(tmp_path, (
        "def guarded(expr):\n"
        "    '''Evaluate a fixed template.'''\n"
        "    return eval(expr, {}, {})  # nosec B307 - fixed templates only\n"))
    report = run_audit(root)
    assert report["summary"]["critical"] == 0
    assert report["summary"]["acknowledged"] == 1
    assert _acknowledged_names(report) == {"guarded"}
    # Still fully visible — an audit trail, never a mute button.
    acked = report["risks"]["acknowledged"][0]
    assert acked["file"] == "core.py"
    assert "eval()" in acked["risk"]


def test_mixed_annotation_fails_closed_to_critical(tmp_path):
    # Two eval calls in ONE function, only one annotated: the function's
    # eval risk must stay critical — every call site needs its own mark.
    root = _project(tmp_path, (
        "def half_marked(a, b):\n"
        "    '''Evaluate both.'''\n"
        "    x = eval(a)  # nosec B307 - fixed templates only\n"
        "    y = eval(b)\n"
        "    return x, y\n"))
    report = run_audit(root)
    assert report["summary"]["critical"] >= 1
    assert report["summary"]["acknowledged"] == 0


def test_class_method_annotation_resolves(tmp_path):
    root = _project(tmp_path, (
        "class Engine:\n"
        "    def run(self, src):\n"
        "        '''Execute a fixed template.'''\n"
        "        exec(src, {})  # nosec B102 - fixed templates only\n"))
    report = run_audit(root)
    assert report["summary"]["critical"] == 0
    assert _acknowledged_names(report) == {"Engine.run"}


def test_multiline_call_span_annotation_counts(tmp_path):
    # The annotation may sit on any line of a multi-line call's span.
    root = _project(tmp_path, (
        "def spread(src, ns):\n"
        "    '''Execute compiled source.'''\n"
        "    exec(\n"
        "        compile(src, '<t>', 'exec'),\n"
        "        ns,\n"
        "    )  # nosec B102 - fixed doctest source\n"))
    report = run_audit(root)
    assert report["summary"]["critical"] == 0
    assert report["summary"]["acknowledged"] == 1


def test_chain_pattern_os_system_acknowledgeable(tmp_path):
    root = _project(tmp_path, (
        "import os\n\n\n"
        "def shell(cmd):\n"
        "    '''Run a fixed command.'''\n"
        "    os.system(cmd)  # nosec B605 - fixed command\n"))
    report = run_audit(root)
    assert report["summary"]["critical"] == 0
    assert report["summary"]["acknowledged"] == 1


def test_nosec_on_unrelated_line_does_not_acknowledge(tmp_path):
    # The annotation must sit within the risky CALL's own span — a stray
    # `# nosec` elsewhere in the function acknowledges nothing.
    root = _project(tmp_path, (
        "def stray(expr):\n"
        "    '''Evaluate.'''\n"
        "    x = 1  # nosec\n"
        "    return eval(expr)\n"))
    report = run_audit(root)
    assert report["summary"]["critical"] == 1
    assert report["summary"]["acknowledged"] == 0
