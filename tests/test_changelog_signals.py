"""apex changelog: the coordinator (high-fan-OUT) decoupling watch-item.

The changelog's health read-out gains one forward-looking note: the project's
heaviest coordinator module (``profile.coordinator_modules[0]`` — a god-module
that imports many internal siblings, a decoupling candidate). The note is gated
on availability: a repo with no god-module yields the section [], so the notes
render BYTE-IDENTICALLY to before the feature existed. The list the profiler
hands back is already sorted ``(-fan_out, module)``, so the surfaced top entry is
deterministic for a given repo state.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import app.reporting.changelog as cl
from app.reporting.changelog import build_changelog
from app.tools.project_profile import ProjectProfiler

# Comfortably above the floor so the module is unambiguously a god-module.
_FAN_OUT = ProjectProfiler._COORDINATOR_FAN_OUT_FLOOR + 3


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, capture_output=True,
                   env=dict(os.environ))


def _plain_repo(root: Path) -> Path:
    """A committed repo with no god-module — coordinator section stays empty."""
    (root / "app").mkdir()
    (root / "app" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-qm", "initial release")
    return root


def _god_module_repo(root: Path) -> Path:
    """A committed repo whose ``app/coordinator.py`` imports many siblings."""
    pkg = root / "app"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for i in range(_FAN_OUT):
        (pkg / f"leaf{i}.py").write_text(
            f"def fn_{i}(x):\n    return x + {i}\n", encoding="utf-8")
    imports = "\n".join(f"import app.leaf{i}" for i in range(_FAN_OUT))
    body = "\n".join(f"    a = app.leaf{i}.fn_{i}(a)" for i in range(_FAN_OUT))
    (pkg / "coordinator.py").write_text(
        f"{imports}\n\n\ndef run(a):\n{body}\n    return a\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-qm", "initial release")
    return root


# --- present: the heaviest coordinator surfaces as a watch-item --------------

def test_coordinator_watch_item_present(tmp_path):
    _god_module_repo(tmp_path)
    md = build_changelog(tmp_path)
    assert "## Decoupling watch-item (heaviest coordinator module)" in md
    assert "`app/coordinator.py`" in md
    assert f"(fan-out {_FAN_OUT})" in md
    # It names a few of the internal modules the god-module wires together.
    assert "— wires `app/leaf" in md


def test_coordinator_section_in_isolation(tmp_path):
    _god_module_repo(tmp_path)
    lines = cl._coordinator_section(tmp_path)
    assert lines[0] == "## Decoupling watch-item (heaviest coordinator module)"
    assert lines[1] == ""
    assert lines[2].startswith("- `app/coordinator.py` (fan-out ")
    assert lines[-1] == ""


# --- absent: no god-module → section [] → byte-identical notes ---------------

def test_no_coordinator_renders_byte_identical(tmp_path):
    _plain_repo(tmp_path)
    # With the section empty its lines must contribute nothing at all.
    assert cl._coordinator_section(tmp_path) == []
    md = build_changelog(tmp_path)
    assert "Decoupling watch-item" not in md
    assert "coordinator" not in md.lower()


def test_profiler_failure_is_swallowed(monkeypatch, tmp_path):
    """A profiler that raises is gated to [] — the note never crashes the notes."""
    def boom(*a, **k):
        raise RuntimeError("profile blew up")

    import app.tools.project_profile as pp
    monkeypatch.setattr(pp.ProjectProfiler, "profile", boom)
    assert cl._coordinator_section(tmp_path) == []


def test_empty_coordinator_list_is_gated(monkeypatch, tmp_path):
    """An empty ``coordinator_modules`` yields [] (the no-god-module path)."""
    class _P:
        coordinator_modules: list = []

    class _Prof:
        def __init__(self, *a, **k):
            pass

        def profile(self, *a, **k):
            return _P()

    import app.tools.project_profile as pp
    monkeypatch.setattr(pp, "ProjectProfiler", _Prof)
    assert cl._coordinator_section(tmp_path) == []


def test_coordinator_without_imports_omits_wires(monkeypatch, tmp_path):
    """A flagged module with no named imports renders without the wires clause."""
    class _P:
        coordinator_modules = [{"module": "app/big.py", "fan_out": 9,
                                "imports": []}]

    class _Prof:
        def __init__(self, *a, **k):
            pass

        def profile(self, *a, **k):
            return _P()

    import app.tools.project_profile as pp
    monkeypatch.setattr(pp, "ProjectProfiler", _Prof)
    lines = cl._coordinator_section(tmp_path)
    assert lines[2] == "- `app/big.py` (fan-out 9)"
    assert "wires" not in lines[2]


def test_coordinator_skips_malformed_entries(monkeypatch, tmp_path):
    """Non-dict / module-less entries are skipped; the first real one surfaces."""
    class _P:
        coordinator_modules = ["junk", {"fan_out": 3},
                               {"module": "app/real.py", "fan_out": 7,
                                "imports": ["app/a.py", 5, "app/b.py"]}]

    class _Prof:
        def __init__(self, *a, **k):
            pass

        def profile(self, *a, **k):
            return _P()

    import app.tools.project_profile as pp
    monkeypatch.setattr(pp, "ProjectProfiler", _Prof)
    lines = cl._coordinator_section(tmp_path)
    # Only the dict WITH a module is surfaced, and the non-str import (5) drops.
    assert lines[2] == "- `app/real.py` (fan-out 7) — wires `app/a.py`, `app/b.py`"


def test_all_dicts_lack_module_returns_empty(monkeypatch, tmp_path):
    """Every entry missing ``module`` → top is None → section [] (gated)."""
    class _P:
        coordinator_modules = [{"fan_out": 3}, {"imports": ["x"]}]

    class _Prof:
        def __init__(self, *a, **k):
            pass

        def profile(self, *a, **k):
            return _P()

    import app.tools.project_profile as pp
    monkeypatch.setattr(pp, "ProjectProfiler", _Prof)
    assert cl._coordinator_section(tmp_path) == []


# --- determinism: same repo state → byte-identical notes twice ----------------

def test_changelog_deterministic_with_coordinator(tmp_path):
    _god_module_repo(tmp_path)
    first = build_changelog(tmp_path)
    second = build_changelog(tmp_path)
    assert first == second
    assert "## Decoupling watch-item (heaviest coordinator module)" in first
