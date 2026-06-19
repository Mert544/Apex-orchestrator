"""Adversarial robustness for ``ci_scaffold.has_ci`` — the "don't bolt a second
pipeline onto a repo that already gates its changes" invariant must survive a
``.github/workflows`` directory we cannot read.

A red-team pass found that an ``OSError`` while listing ``.github/workflows``
(permissions, a races-away dir, a path that is not really a dir) used to make
``has_ci`` return ``False`` outright — which would scaffold a SECOND CI pipeline
onto a repo that already gates via, e.g., a readable ``.gitlab-ci.yml``. The fix
falls through to the single-file marker check instead of declaring "no CI".

Deterministic; stdlib-only.
"""

from __future__ import annotations

from pathlib import Path

from app.execution import ci_scaffold


def test_unreadable_workflows_dir_falls_through_to_markers(monkeypatch, tmp_path):
    # A .github/workflows that raises on iteration, plus a readable gitlab config:
    # has_ci must still report True (the repo already has CI elsewhere).
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".gitlab-ci.yml").write_text("ci\n", encoding="utf-8")

    real_iterdir = Path.iterdir

    def boom(self):
        if self.name == "workflows":
            raise OSError("permission denied")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", boom)
    assert ci_scaffold.has_ci(str(tmp_path)) is True


def test_unreadable_workflows_dir_with_no_other_ci_is_false(monkeypatch, tmp_path):
    # Same unreadable dir but NO other CI marker: honestly report no detectable
    # CI (so the scaffolder may add one) rather than crashing.
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

    real_iterdir = Path.iterdir

    def boom(self):
        if self.name == "workflows":
            raise OSError("permission denied")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", boom)
    assert ci_scaffold.has_ci(str(tmp_path)) is False


def test_empty_workflows_dir_is_not_ci(tmp_path):
    # An empty .github/workflows is not CI — the scaffolder may add one.
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    assert ci_scaffold.has_ci(str(tmp_path)) is False


def test_other_markers_detected_without_github_dir(tmp_path):
    for marker in (".gitlab-ci.yml", "Jenkinsfile", ".travis.yml"):
        d = tmp_path / marker.replace("/", "_")
        d.mkdir()
        (d / marker).write_text("ci\n", encoding="utf-8")
        assert ci_scaffold.has_ci(str(d)) is True
