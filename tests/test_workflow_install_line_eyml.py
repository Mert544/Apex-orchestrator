"""Guard the "Install Apex" step of the copy-paste adopter workflow templates.

W3B-DIST: `apex-autofix.yml` and `apex-review.yml` both tell an adopter to
"copy to .github/workflows/ / drop this file into any Python repo" — but the
"Install Apex" step ran `pip install .` / `pip install -e .`, which installs
whatever project lives at the repo root. Inside Apex's own repo that's Apex
(correct); copied into an adopting repo, `.` resolves to the ADOPTER's own
project — the `apex` console script is never installed, so the subsequent
`apex review --fix` / `python -m app.cli review` step fails (or, worse,
silently resolves to a same-named script the adopter happens to declare).

These tests pin the fix: both workflows key the install command off
`github.repository` — the self-repo branch keeps the ORIGINAL install line
byte-identical (so Apex's own CI is unaffected), while the adopter branch
installs Apex itself from its pinned GitHub source
(`git+https://github.com/Mert544/Apex-orchestrator@<ref>`). They also pin
that both files' headers honestly describe both modes, and that
`docs/ci.md`'s copy-paste snippet and prose no longer hand an adopter a bare
`pip install .` that installs their own project instead of Apex.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_AUTOFIX = _ROOT / ".github" / "workflows" / "apex-autofix.yml"
_REVIEW = _ROOT / ".github" / "workflows" / "apex-review.yml"
_CI = _ROOT / ".github" / "workflows" / "apex-ci.yml"
_CI_MD = _ROOT / "docs" / "ci.md"

# The single source of truth for the guard idiom every one of these files
# must use — a future edit to any file should be checked against these exact
# literals rather than a hand-copied re-derivation (see design RISKS #3).
_SELF_REPO_SLUG = "Mert544/Apex-orchestrator"
_ADOPTER_SOURCE = "git+https://github.com/Mert544/Apex-orchestrator@"
_GUARD_KEY = "github.repository"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _install_step_run(workflow: dict) -> str:
    """Return the `run:` text of the step named "Install Apex", across all jobs."""
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if step.get("name") == "Install Apex":
                return step.get("run", "")
    raise AssertionError("no step named 'Install Apex' found")


# --------------------------------------------------------------------------
# apex-autofix.yml
# --------------------------------------------------------------------------


def test_apex_autofix_install_branches_self_repo_vs_adopter():
    run_text = _install_step_run(_load_yaml(_AUTOFIX))
    # Pins today's exact bug: a bare `pip install .` has no `if`, no
    # `github.repository` guard, and no adopter-source install anywhere —
    # this assertion is red on the pre-fix file.
    assert _GUARD_KEY in run_text
    assert _SELF_REPO_SLUG in run_text
    assert _ADOPTER_SOURCE in run_text
    assert "pip install ." in run_text


def test_apex_autofix_self_repo_line_is_byte_identical():
    run_text = _install_step_run(_load_yaml(_AUTOFIX))
    lines = [ln.strip() for ln in run_text.splitlines() if ln.strip()]
    # The self-repo branch must keep the EXACT original install command —
    # no flags added or dropped — so Apex's own CI behavior is byte-identical
    # to before this fix.
    assert "pip install ." in lines
    assert "pip install -e ." not in lines


# --------------------------------------------------------------------------
# apex-review.yml
# --------------------------------------------------------------------------


def test_apex_review_install_branches_self_repo_vs_adopter():
    run_text = _install_step_run(_load_yaml(_REVIEW))
    assert _GUARD_KEY in run_text
    assert _SELF_REPO_SLUG in run_text
    assert _ADOPTER_SOURCE in run_text
    assert "pip install -e ." in run_text


def test_apex_review_self_repo_line_is_byte_identical():
    run_text = _install_step_run(_load_yaml(_REVIEW))
    lines = [ln.strip() for ln in run_text.splitlines() if ln.strip()]
    # apex-review.yml's original install used the editable flag; the
    # self-repo branch must preserve it exactly.
    assert "pip install -e ." in lines


# --------------------------------------------------------------------------
# Headers honestly describe both the self-repo and adopter paths
# --------------------------------------------------------------------------


def test_apex_autofix_header_names_adopter_and_self_repo():
    text = _AUTOFIX.read_text(encoding="utf-8")
    assert "ADOPTER" in text
    assert "SELF-REPO" in text or "self-repo" in text


def test_apex_review_header_names_adopter_and_self_repo():
    text = _REVIEW.read_text(encoding="utf-8")
    assert "ADOPTER" in text
    assert "SELF-REPO" in text or "self-repo" in text


# --------------------------------------------------------------------------
# The adopter ref is a documented, adopter-overridable placeholder, not a
# silently hardcoded moving target (design RISKS #2).
# --------------------------------------------------------------------------


def test_adopter_ref_is_documented_and_pinned():
    for path in (_AUTOFIX, _REVIEW):
        text = path.read_text(encoding="utf-8")
        assert "APEX_ADOPTER_REF" in text, f"{path.name} missing APEX_ADOPTER_REF"
        assert "pin" in text.lower(), f"{path.name} missing a 'pin to a release' comment"


# --------------------------------------------------------------------------
# docs/ci.md — the copy-paste snippet and "Beyond GitHub Actions" prose
# --------------------------------------------------------------------------


def test_ci_md_snippet_does_not_bare_pip_install_dot_for_adopters():
    text = _CI_MD.read_text(encoding="utf-8")
    # Find the fenced snippet containing `apex gate` (the minimal copy-paste
    # block this page tells adopters to copy verbatim).
    start = text.index("```yaml")
    end = text.index("```", start + 7)
    snippet = text[start:end]
    assert "apex gate" in snippet
    for line in snippet.splitlines():
        if "pip install ." in line:
            # A bare, unqualified line is exactly today's bug — it must now
            # carry an inline comment steering an adopter to the real path.
            assert "#" in line, (
                "docs/ci.md snippet still hands adopters a bare, "
                "unqualified `pip install .`"
            )
            assert "SELF-REPO" in line or "ADOPTER" in line

    # The "Beyond GitHub Actions" prose must no longer claim an arbitrary
    # adopter can install "the same way: pip install .".
    beyond = text[text.index("Beyond GitHub Actions"):]
    assert _ADOPTER_SOURCE in beyond or "install *Apex*" in beyond or "install Apex" in beyond


# --- apex-ci.yml — the file docs/ci.md funnels adopters to FIRST ------------
# (integration review finding: the primary adopter on-ramp was left unguarded
# by the original track fence — these pins close that gap and keep all THREE
# adopter-facing templates on the same contract.)


def test_apex_ci_install_branches_self_repo_vs_adopter():
    run_text = _install_step_run(_load_yaml(_CI))
    assert _GUARD_KEY in run_text
    assert _SELF_REPO_SLUG in run_text
    assert _ADOPTER_SOURCE in run_text


def test_apex_ci_self_repo_line_is_byte_identical():
    run_text = _install_step_run(_load_yaml(_CI))
    assert "pip install .\n" in run_text or run_text.rstrip().endswith("pip install .") or "pip install .\n" in run_text + "\n" or "  pip install .\n" in run_text
    assert "pip install -e" not in run_text


def test_apex_ci_header_names_adopter_and_self_repo():
    text = _CI.read_text(encoding="utf-8")
    head = text.split("jobs:", 1)[0]
    assert "adopt" in head.lower()
    assert "does not install your project" in head


def test_apex_ci_adopter_ref_is_documented_and_pinned():
    text = _CI.read_text(encoding="utf-8")
    assert "APEX_ADOPTER_REF: main" in text
    assert "pin to a released tag" in text
