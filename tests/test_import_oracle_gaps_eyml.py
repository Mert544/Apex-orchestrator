"""import-oracle — coverage gaps for the restore / error paths.

Targets the last uncovered lines of :mod:`app.execution.import_oracle` (the happy
path is exercised by ``test_wire_exports_objective_eyml``):

* the NO-existing-``__init__.py`` case — the candidate is written, imported, then
  the freshly-created file is UNLINKED again (side-effect-free even when it did not
  exist before), and the defensive ``except OSError`` keeps a failing unlink from
  ever masking the result;
* the subprocess failing to spawn, exiting non-zero, or emitting unparseable
  stdout each -> ``False`` while the ORIGINAL ``__init__.py`` bytes are restored.

The subprocess is a true external, mocked (``monkeypatch``) as the neighbours do;
nothing here touches the clock, network, or randomness.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import app.execution.import_oracle as oracle
from app.execution.import_oracle import exports_resolve


def _pkg_with_init(tmp_path: Path, init: str = "X = 1\n") -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(init, encoding="utf-8")
    return pkg


def test_missing_init_is_created_probed_then_removed(tmp_path):
    # No __init__.py exists (had_file is False): the candidate is written and
    # imported (the export resolves), then the freshly-created file is removed —
    # the package is a namespace dir again, exactly as it started.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    ok = exports_resolve(tmp_path, "pkg/__init__.py", "from .mod import foo\n", ["foo"])
    assert ok is True
    assert not (pkg / "__init__.py").exists()  # never left behind


def test_missing_init_unresolvable_export_removes_created_file(tmp_path):
    # Same no-init case, but an export that cannot resolve -> False, and the
    # temporarily-written __init__.py is still cleaned up.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    ok = exports_resolve(tmp_path, "pkg/__init__.py", "from .mod import foo\n", ["ghost"])
    assert ok is False
    assert not (pkg / "__init__.py").exists()


def test_failing_unlink_never_masks_the_result(tmp_path, monkeypatch):
    # The restore of a freshly-created __init__.py must never crash the oracle: a
    # unlink that raises OSError is swallowed and the probe's verdict is returned.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("def foo():\n    return 1\n", encoding="utf-8")

    def _boom(self, *_a, **_k):
        raise OSError("cannot unlink")

    monkeypatch.setattr(Path, "unlink", _boom)
    result = exports_resolve(tmp_path, "pkg/__init__.py", "from .mod import foo\n", ["foo"])
    assert result is True  # verdict survives the failed cleanup
    # The write is real, so tidy up despite the patched unlink.
    monkeypatch.undo()
    (pkg / "__init__.py").unlink()


def test_subprocess_spawn_failure_returns_false_and_restores(tmp_path, monkeypatch):
    # subprocess.run raising -> refuse; the original __init__.py bytes are restored.
    pkg = _pkg_with_init(tmp_path)

    def _raise(*_a, **_k):
        raise OSError("cannot spawn")

    monkeypatch.setattr(oracle.subprocess, "run", _raise)
    assert exports_resolve(tmp_path, "pkg/__init__.py", "X = 2\n", ["X"]) is False
    assert (pkg / "__init__.py").read_text() == "X = 1\n"  # restored


def test_nonzero_returncode_returns_false(tmp_path, monkeypatch):
    # A probe that exits non-zero proves nothing -> False, original restored.
    pkg = _pkg_with_init(tmp_path)
    monkeypatch.setattr(
        oracle.subprocess, "run",
        lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="", stderr=""))
    assert exports_resolve(tmp_path, "pkg/__init__.py", "X = 2\n", ["X"]) is False
    assert (pkg / "__init__.py").read_text() == "X = 1\n"


def test_unparseable_stdout_returns_false(tmp_path, monkeypatch):
    # Empty / non-JSON stdout (no last line to decode) -> False, never guess.
    pkg = _pkg_with_init(tmp_path)
    monkeypatch.setattr(
        oracle.subprocess, "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    assert exports_resolve(tmp_path, "pkg/__init__.py", "X = 2\n", ["X"]) is False
    assert (pkg / "__init__.py").read_text() == "X = 1\n"
