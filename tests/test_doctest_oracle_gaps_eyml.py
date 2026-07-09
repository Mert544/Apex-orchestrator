"""doctest-oracle — coverage gaps for the refusal / error paths.

Targets the last uncovered lines of :mod:`app.execution.doctest_oracle` (the happy
path is exercised by ``test_generate_usage_doc_objective_eyml`` /
``test_usage_doc_determinism_eyml``). Every case here proves the oracle REFUSES —
returns an empty set — rather than claiming unproven examples:

* ``_package_submodules`` swallows an ``OSError`` from module discovery -> ``[]``
  (the probe then binds only the package's own attrs, its prior behavior);
* an empty dotted package name (``__init__.py`` at the root) -> ``set()``;
* the subprocess failing to spawn, exiting non-zero, or emitting unparseable
  stdout each -> ``set()``.

The subprocess is a true external, mocked (``monkeypatch``) exactly as the sibling
determinism suite does; nothing here touches the clock, network, or randomness.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import app.execution.doctest_oracle as oracle
import app.execution.usage_doc as usage_doc
from app.execution.doctest_oracle import _package_submodules, examples_run_green

_PAYLOAD = {"foo": [">>> 1\n1"]}


def _pkg(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    return pkg


def test_package_submodules_swallows_oserror(tmp_path, monkeypatch):
    # If the doc collector's module discovery raises OSError (an unreadable package
    # dir), _package_submodules degrades to [] rather than propagating — the probe
    # then binds only the package's own attributes.
    def _boom(_package_dir):
        raise OSError("unreadable")

    monkeypatch.setattr(usage_doc, "_module_stems", _boom)
    assert _package_submodules(tmp_path, "pkg/__init__.py") == []


def test_empty_dotted_package_name_returns_empty_set(tmp_path):
    # An __init__.py at the project ROOT has no dotted package name, so there is
    # nothing importable to run the examples against -> refuse (empty set).
    (tmp_path / "__init__.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    assert examples_run_green(tmp_path, "__init__.py", _PAYLOAD) == set()


def test_subprocess_spawn_failure_returns_empty_set(tmp_path, monkeypatch):
    # subprocess.run raising (OSError / SubprocessError) -> refuse, no crash.
    _pkg(tmp_path)

    def _raise(*_a, **_k):
        raise OSError("cannot spawn")

    monkeypatch.setattr(oracle.subprocess, "run", _raise)
    assert examples_run_green(tmp_path, "pkg/__init__.py", _PAYLOAD) == set()


def test_nonzero_returncode_returns_empty_set(tmp_path, monkeypatch):
    # A probe that exits non-zero proves nothing -> refuse.
    _pkg(tmp_path)
    monkeypatch.setattr(
        oracle.subprocess, "run",
        lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="", stderr=""))
    assert examples_run_green(tmp_path, "pkg/__init__.py", _PAYLOAD) == set()


def test_unparseable_stdout_returns_empty_set(tmp_path, monkeypatch):
    # Empty / non-JSON stdout (no last line to decode) -> refuse, never guess.
    _pkg(tmp_path)
    monkeypatch.setattr(
        oracle.subprocess, "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    assert examples_run_green(tmp_path, "pkg/__init__.py", _PAYLOAD) == set()


def test_probe_reporting_not_ok_returns_empty_set(tmp_path, monkeypatch):
    # A well-formed probe result that reports ok=False (the package failed to
    # import inside the subprocess) is honored as a refusal.
    _pkg(tmp_path)
    monkeypatch.setattr(
        oracle.subprocess, "run",
        lambda *_a, **_k: SimpleNamespace(
            returncode=0, stdout='{"ok": false, "passed": []}', stderr=""))
    assert examples_run_green(tmp_path, "pkg/__init__.py", _PAYLOAD) == set()
