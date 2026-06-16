"""Shared leaf helpers for Apex's GitLab-flavoured finding exporters.

:mod:`app.reporting.codeclimate_export` (the "Code Quality" widget) and
:mod:`app.reporting.gitlab_sast_export` (the "Security" SAST report) read the
*same* Apex findings and share a small, byte-identical core: how a field is read
off a finding (dataclass/object or dict), how its source path is resolved, and
how that path is made repo-relative against a ``project_root``. Those three
functions were duplicated verbatim across both modules; hoisting them here keeps
exactly one implementation to reason about while leaving each formatter's
format-specific mapping (severity scale, issue/vulnerability shape) in place.

This is a leaf module: it imports nothing but the stdlib ``typing`` (under
``TYPE_CHECKING`` only ``Any`` is needed), so it can be imported by either
exporter with no risk of an import cycle. No clock, no randomness, no network —
the helpers stay pure so the exporters remain byte-deterministic.
"""

from __future__ import annotations

from typing import Any


def field(finding: Any, name: str, default: Any) -> Any:
    """Read ``name`` from a finding that may be a dataclass/object or a dict.

    Apex's own findings (``ReviewFinding`` / ``Issue``) expose fields as
    attributes; a caller may equally hand us plain dicts. Read either, and fall
    back to ``default`` when the field is absent so a partial finding still
    exports.
    """
    if isinstance(finding, dict):
        value = finding.get(name, default)
    else:
        value = getattr(finding, name, default)
    return default if value is None else value


def path_of(finding: Any) -> str:
    """The finding's source path. Apex review findings use ``file``; ``path`` is
    accepted as a synonym for raw detector/dict findings."""
    path = field(finding, "file", None)
    if path is None:
        path = field(finding, "path", "")
    return str(path)


def relative_path(path: str, project_root: str) -> str:
    """Strip ``project_root`` prefix so paths are repo-relative (what GitLab wants).

    A no-op when ``project_root`` is empty (the default) or the path isn't under
    it. String-level so it stays deterministic and never touches the filesystem.
    """
    if not project_root:
        return path
    root = project_root.rstrip("/\\") + "/"
    norm = path.replace("\\", "/")
    if norm.startswith(root.replace("\\", "/")):
        return norm[len(root):]
    return path


__all__ = ["field", "path_of", "relative_path"]
