"""Scaffold a continuous-integration workflow for a project that has none.

Apex's grade is "A+ on itself", but the honest buyer question is "what does
Apex actually BUILD for my project?". A project with no CI has no automated
gate stopping broken changes from merging — a real, common, and *fixable* gap.
Generating a CI workflow is a genuine project-DEVELOPMENT action, not a flag:
it is purely ADDITIVE (a brand-new file under ``.github/workflows/``; no
existing source is touched), deterministic, and verifiable through the SAME
guarded apply gate as every transform (snapshot → write → verify → rollback).
That is why ``add_ci`` is a Tier-0 (additive-only) capability, exactly like the
``create_test_stub`` action that writes a new test file.

The scaffolder refuses rather than fabricates (trust over activity):

  * a project that ALREADY has CI (any ``.github`` workflow, or a well-known
    single-file CI config) gets ``None`` — nothing to add;
  * a project that does not look like Python gets ``None`` — Apex only knows
    how to scaffold a Python CI honestly, so it declines instead of writing a
    workflow it cannot stand behind.

When it does fire, the emitted YAML is a function of a few boolean facts about
the repo (does it have a packaging file? a requirements file? a ruff config?),
so the output is byte-identical across runs on the same tree — no time, no
randomness, no filesystem-ordering dependence.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.semantic.result import SemanticPatchResult

# The conventional, fixed destination. A single deterministic path keeps the
# transform idempotent: a second run sees the file and refuses.
CI_WORKFLOW_PATH = ".github/workflows/apex-ci.yml"

# Single-file CI configs for other systems — their presence means the project
# already has CI and we must not add a second, competing pipeline.
_OTHER_CI_MARKERS = (
    ".gitlab-ci.yml",
    ".circleci/config.yml",
    "azure-pipelines.yml",
    "Jenkinsfile",
    ".travis.yml",
    "bitbucket-pipelines.yml",
)


def has_ci(project_root: str) -> bool:
    """True when the project already has some continuous-integration config.

    Mirrors the profiler's notion of CI (any file under ``.github/**`` whose
    path mentions ``workflows``) and widens it to the common single-file CI
    configs of other systems, so we never bolt a second pipeline onto a repo
    that already gates its changes.
    """
    root = Path(project_root)
    workflows = root / ".github" / "workflows"
    try:
        if workflows.is_dir() and any(
            p.is_file() for p in workflows.iterdir()
        ):
            return True
    except OSError:
        return False
    return any((root / marker).exists() for marker in _OTHER_CI_MARKERS)


def _is_python_project(project_root: str) -> bool:
    """True when the repo looks like Python — a packaging/marker file, or any
    ``.py`` file outside the VCS and tooling directories."""
    root = Path(project_root)
    for marker in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"):
        if (root / marker).exists():
            return True
    try:
        for path in root.rglob("*.py"):
            parts = set(path.parts)
            if {".git", ".tox", ".venv", "venv", "build", "dist"} & parts:
                continue
            return True
    except OSError:
        return False
    return False


def _install_command(root: Path) -> str:
    """The single deterministic dependency-install line for the repo's shape."""
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        return "pip install -e ."
    if (root / "requirements.txt").exists():
        return "pip install -r requirements.txt"
    return "pip install pytest"


def _has_ruff_config(root: Path) -> bool:
    """True when the repo configures ruff (a ruff step would be meaningful)."""
    for cfg in ("ruff.toml", ".ruff.toml"):
        if (root / cfg).exists():
            return True
    pyproject = root / "pyproject.toml"
    try:
        return pyproject.exists() and "[tool.ruff" in pyproject.read_text(
            encoding="utf-8")
    except OSError:
        return False


def _render_yaml(install: str, with_ruff: bool) -> str:
    """Render a minimal, valid GitHub Actions workflow.

    Deterministic: the only inputs are the install line and whether to add a
    ruff step. Fixed Python version, fixed action pins, fixed ordering.
    """
    lines = [
        "name: CI",
        "",
        "on:",
        "  push:",
        "    branches: [main]",
        "  pull_request:",
        "",
        "jobs:",
        "  test:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        "      - uses: actions/checkout@v4",
        "      - uses: actions/setup-python@v5",
        "        with:",
        '          python-version: "3.11"',
        "      - name: Install dependencies",
        "        run: |",
        "          python -m pip install --upgrade pip",
        f"          {install}",
    ]
    if with_ruff:
        lines += [
            "      - name: Lint (ruff)",
            "        run: python -m ruff check .",
        ]
    lines += [
        "      - name: Run tests",
        "        run: python -m pytest",
    ]
    return "\n".join(lines) + "\n"


def generate_ci_workflow(project_root: str) -> SemanticPatchResult | None:
    """A patch that creates a CI workflow, or ``None`` when none should be added.

    Returns ``None`` (declines) when the project already has CI or does not look
    like a Python project. Otherwise returns a :class:`SemanticPatchResult` with
    a single ADDITIVE patch request creating :data:`CI_WORKFLOW_PATH`
    (``expected_old_content == ""`` marks a brand-new file), to be applied and
    verified through the bridge's guarded gate.
    """
    if has_ci(project_root) or not _is_python_project(project_root):
        return None
    root = Path(project_root)
    install = _install_command(root)
    with_ruff = _has_ruff_config(root)
    content = _render_yaml(install, with_ruff)
    return SemanticPatchResult(
        patch_requests=[{
            "path": CI_WORKFLOW_PATH,
            "new_content": content,
            # ``None`` (not "") marks a brand-NEW file: the apply skill writes a
            # missing file only when no prior content is expected, and skips a
            # would-be-new file whose expected_old_content is a real string.
            "expected_old_content": None,
        }],
        transform_type="add_ci_workflow",
        rationale=[
            f"Scaffolded {CI_WORKFLOW_PATH}: a Python CI workflow (checkout, "
            f"setup-python, '{install}'"
            + (", ruff" if with_ruff else "")
            + ", pytest) for a project with no existing CI gate "
            "(additive — no existing file touched)."
        ],
    )
