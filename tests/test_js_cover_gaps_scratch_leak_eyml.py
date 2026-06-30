"""js-cover-gaps scratch-file leak regression (field-test P1b).

The embedded node capture/time probes (:data:`_CAPTURE_PROBE` / :data:`_TIME_PROBE`)
write a transpiled module as a SIBLING of the buyer's source — ``.apex_cover_capture_
<pid>.js`` / ``.apex_cover_time_<pid>.js`` — so a relative ``import``/``require``
resolves against the real tree, then delete it in a ``finally`` block. But
``decline()`` exits via ``process.exit(0)``, which BYPASSES that ``finally``: when a
module's only exported function returns a NON-SERIALISABLE value (``NaN`` /
``undefined`` / a class instance — ``isSoundValue`` rejects it -> ``decline()``), the
sibling temp was left behind in the buyer's source directory, EVEN on a dry-run, and
the env-reproducibility gate spawns SEVERAL captures so several files leaked. This is
the transient-hazard class CLAUDE.md warns about.

The fix makes ``decline()`` ``fs.unlinkSync(tmpFile)`` (guarded) BEFORE
``process.exit(0)``. These tests drive the real capture path on a declining module
and assert NO ``.apex_cover_*`` file survives in the target dir.

JS-RUNS-NOT-SKIP: these need node + global ``typescript`` only (no jest). A sentinel
in :mod:`tests.test_js_cover_gaps_objective_eyml` already FAILS loudly when that
toolchain is absent, so a silent skip here cannot hide a broken JS lane.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.execution.js.js_cover_gaps import (
    _capture_oracle,
    _run_capture,
    generate_js_cover_test,
)
from app.execution.js.js_tool import cover_targets, global_node_modules


def _node_ok() -> bool:
    """True when ``node`` is on PATH and the global ``typescript`` resolves — the
    minimum for the transpile/capture children to run (mirrors the sibling suite)."""
    if shutil.which("node") is None:
        return False
    nm = global_node_modules()
    return bool(nm) and (Path(nm) / "typescript").is_dir()


_needs_node = pytest.mark.skipif(
    not _node_ok(), reason="node + global typescript not available")


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    """A throwaway project root (single ``package.json``, NO ``node_modules``) with
    ``rel`` -> ``src`` — enough for node to transpile + capture."""
    root = tmp_path / "proj"
    (root / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(src, encoding="utf-8")
    (root / "package.json").write_text(
        '{ "name": "p", "version": "1.0.0", "scripts": { "test": "jest" } }\n',
        encoding="utf-8")
    return root


def _scratch_files(directory: Path) -> list[str]:
    """Every leaked Apex capture/time scratch file in ``directory`` (the leak)."""
    return sorted(
        p.name for p in directory.iterdir()
        if p.name.startswith(".apex_cover_capture_")
        or p.name.startswith(".apex_cover_time_")
    )


@_needs_node
def test_capture_oracle_declining_module_leaves_no_scratch_file(tmp_path: Path):
    """The capture path on a module whose only export returns ``NaN`` declines (the
    serializability gate rejects ``NaN``) — and must leave NO ``.apex_cover_*`` file
    behind in the source dir. ``_capture_oracle`` runs the in-process baseline
    capture AND the multi-axis env-reproducibility gate, so SEVERAL probe children
    spawn; the guarded cleanup in ``decline()`` must clean up every one."""
    src = "export function nan() { return NaN; }\n"
    root = _project(tmp_path, "src/m.ts", src)
    src_dir = root / "src"

    targets = {t.name: t for t in cover_targets(root, "src/m.ts")}
    assert "nan" in targets, "the nan() export should be a (pure) cover target"

    oracle = _capture_oracle(root, "src/m.ts", targets["nan"], [])
    assert oracle is None  # NaN is non-serialisable -> declined (no oracle)

    # THE LEAK REGRESSION: not a single sibling scratch file may remain.
    assert _scratch_files(src_dir) == [], (
        "decline() leaked a scratch capture file into the buyer's source dir")


@_needs_node
def test_run_capture_decline_removes_its_own_temp(tmp_path: Path):
    """A single ``_run_capture`` on a declining (``undefined``-returning) function
    returns ``None`` AND removes its own ``.apex_cover_capture_*`` temp — the
    decline() guarded-unlink, isolated to one probe invocation."""
    src = "export function u() { return undefined; }\n"
    root = _project(tmp_path, "src/u.ts", src)
    src_dir = root / "src"
    src_abs = str((root / "src/u.ts").resolve())

    captured = _run_capture(root, src_abs, "u", [], {}, None)
    assert captured is None  # undefined is non-serialisable -> the child declined

    assert _scratch_files(src_dir) == [], (
        "decline() left a .apex_cover_capture_<pid>.js temp in the source dir")


@_needs_node
def test_generate_cover_test_declining_module_dry_run_no_leak(tmp_path: Path):
    """End-to-end (dry-run — the generator only PROPOSES bytes, writes nothing): a
    module whose every export declines (class instance / undefined / NaN) yields no
    landable test AND leaves no scratch file in the source tree."""
    src = ("class Box { constructor() { this.v = 1; } get() { return this.v; } }\n"
           "export function make() { return new Box(); }\n"
           "export function undef() { return undefined; }\n"
           "export function nan() { return NaN; }\n")
    root = _project(tmp_path, "src/ns.ts", src)
    src_dir = root / "src"

    cover = generate_js_cover_test(root, "src/ns.ts", lambda name: None)
    assert cover is None  # nothing landable — every export declines

    assert _scratch_files(src_dir) == [], (
        "the declined dry-run leaked .apex_cover_* scratch files into src/")
