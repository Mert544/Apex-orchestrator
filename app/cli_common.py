"""Shared CLI helpers — kept tiny so command modules avoid import cycles."""

from __future__ import annotations

from pathlib import Path


def _get_project_root() -> Path:
    """Default target: the project you're standing in.

    `apex` is a tool you run *on the current project*, so the default is the
    working directory — not a path derived from where the package happens to
    be installed. (The old __file__-based variant resolved to the REPO'S
    PARENT when run from a source checkout: every no-`--target` run analyzed
    the wrong directory, wrote artifacts there, and rolled back every fix
    because the test suite ran from the wrong root. Found by dogfooding.)
    """
    return Path.cwd().resolve()
