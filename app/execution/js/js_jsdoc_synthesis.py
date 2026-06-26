"""JS/TS stub-body synthesis FROM A JSDoc ``@example`` contract — the LLM-free
fill space + a GENERATED-jest gate.

The DISJOINT JS/TS sibling of :mod:`app.execution.js.js_stub_synthesis`: where
that module gates a body against a jest test the developer ALREADY wrote, this
one fills a stub whose contract lives ONLY in its own JSDoc ``@example`` block
and that NO jest test references. It REUSES the fixed template space verbatim
(:func:`app.execution.js.js_stub_synthesis.candidate_bodies` — passthrough ->
binary -> reduction -> constant-with->=2-witnesses) and adds ZERO new synthesis
logic; the ONLY new machinery is the ORACLE: Apex GENERATES a throwaway jest spec
from the mined ``@example`` witnesses and keeps the FIRST template whose generated
spec goes green.

The generated spec is written ONLY into the THROWAWAY COPY (next to the source as
``<stem>.apexjsdoc.test.js``) and dies with the copy — Apex NEVER writes a test
into the real tree (parity with "never edit the suite I'm gated by"). The landed
change is the ONE source file's spliced body, carried as a ``RenamePlan`` and
applied by the gated/rollback writer, which re-runs the FULL real suite and
byte-rolls-back on any regression.

Deterministic (fixed template order, fixed spec text, no clock/random — same
project + same ``@example`` -> same body), offline (the project owns its
``node_modules``; ``typescript`` is global; Apex installs nothing), zero-token.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from app.execution.js.js_gate import run_jest_gate
from app.execution.js.js_stub_synthesis import candidate_bodies
from app.execution.js.js_tool import (
    JsStub,
    JsWitness,
    fill_body,
    mine_jsdoc_witnesses,
)
from app.skills.execution.run_tests import RunTestsSkill

__all__ = ["generated_spec_source", "synthesize_js_jsdoc_body"]

# The basename suffix of the GENERATED jest spec — a ``.test.js`` so jest's
# default discovery runs it, marked ``apexjsdoc`` so it is unmistakably Apex's
# throwaway probe (it lives only in the copy and is never written to the real
# tree).
_SPEC_SUFFIX = ".apexjsdoc.test.js"


def generated_spec_source(file_rel: str, name: str,
                          witnesses: list[JsWitness]) -> str:
    """The throwaway jest spec text proving ``name`` against its mined JSDoc
    ``witnesses`` — one ``expect(name(...args)).toEqual(expected)`` per witness,
    importing ``name`` from the sibling source by relative path.

    A pure function of ``(file_rel, name, witnesses)`` — fixed import line, fixed
    assertion order (witness source order), no clock/random — so the same contract
    yields byte-identical spec text. The args/expected are the EXACT literal source
    bytes the driver mined off the ``@example`` lines, so the assertion reproduces
    the documented example verbatim."""
    stem = Path(file_rel).stem
    lines = [
        f'const {{ {name} }} = require("./{stem}");',
        f'test("{name} satisfies its jsdoc @example", () => {{',
    ]
    for w in witnesses:
        call = f"{name}({', '.join(w.args)})"
        lines.append(f"  expect({call}).toEqual({w.expected});")
    lines.append("});")
    return "\n".join(lines) + "\n"


def _gate_green(copy_root: Path, file_rel: str, name: str, body: str,
                spec_rel: str, runner: RunTestsSkill) -> bool:
    """Fill ``body`` into the stub ``name`` in the COPY and return whether the
    copy's jest suite (now including the generated ``spec_rel``) goes green.

    The suite run is FORCED to jest (:func:`app.execution.js.js_gate.run_jest_gate`
    passes the jest command explicitly so :meth:`RunTestsSkill._detect_commands`'
    pytest-first auto-detection can never substitute pytest on a mixed repo) AND
    must show jest actually executed >=1 passing test — so the generated
    ``spec_rel`` genuinely ran, never a vacuous ``--passWithNoTests`` pass. A driver
    refusal (the fill did not apply) or a no-suite copy is read as NOT green — never
    a fake-green. The generated spec is already on disk in the copy when this runs;
    jest discovers it by its ``.test.js`` name."""
    if not fill_body(copy_root, file_rel, name, body):
        return False
    return run_jest_gate(copy_root, runner)


def synthesize_js_jsdoc_body(root: Path, file_rel: str, stub: JsStub,
                             runner: RunTestsSkill | None = None) -> str | None:
    """The first fixed-template body whose GENERATED jest spec (built from the
    stub's OWN JSDoc ``@example`` block) goes GREEN, or ``None`` (REFUSE) when none
    does.

    Mines the witnesses the stub's docstring pins on ``stub.name``, builds the
    fixed template space, and — in a THROWAWAY copy of the project under ``root``
    (so the real tree is never touched while probing) — writes the generated spec
    next to the source and probes each candidate IN ORDER. The FIRST body whose
    copy goes green is returned; if every template leaves the copy red, nothing is
    returned. The generated spec lives ONLY in the copy. Deterministic and
    offline."""
    runner = runner or RunTestsSkill()
    witnesses = mine_jsdoc_witnesses(root, file_rel, stub.name)
    if not witnesses:
        return None  # no usable @example -> nothing to prove against -> refuse
    candidates = candidate_bodies(stub, witnesses)
    if not candidates:
        return None
    spec_rel = (Path(file_rel).parent / (Path(file_rel).stem + _SPEC_SUFFIX)).as_posix()
    spec_text = generated_spec_source(file_rel, stub.name, witnesses)
    with tempfile.TemporaryDirectory(prefix="apex_jsdoc_") as tmp:
        copy_root = Path(tmp) / "project"
        shutil.copytree(root, copy_root, ignore=shutil.ignore_patterns(".git"))
        (copy_root / spec_rel).write_text(spec_text, encoding="utf-8")
        for _label, body in candidates:
            shutil.copy2(root / file_rel, copy_root / file_rel)
            if _gate_green(copy_root, file_rel, stub.name, body, spec_rel, runner):
                return body
    return None
