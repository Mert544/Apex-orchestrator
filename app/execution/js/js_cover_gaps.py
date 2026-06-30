"""JS/TS characterization-test GENERATOR — the JS mirror of ``test_shield``.

The JS image of :mod:`app.execution.test_shield`'s value-oracle path: given an
untested EXPORTED JS/TS function, this synthesizes a jest *characterization* test
that PINS the function's CURRENT behaviour. The oracle is the function's OWN
executed output — Apex calls it with synthesized arguments at generation time and,
when the real return is a JSON-serialisable simple value, emits
``expect(fn(<args>)).toEqual(<captured>)``. The captured value IS what the function
returned, so the assertion passes BY CONSTRUCTION while turning a silent regression
into a visible test failure. There is NO LLM and NO guessing: the oracle is sound
by construction within a decidable input slice, and Apex REFUSES (an honest no-op)
the moment soundness cannot be guaranteed.

Like ``test_shield`` it pins CURRENT behaviour — INCLUDING any bug — the accepted
characterization trade-off: a future change that alters the behaviour breaks the
test loudly, which is exactly the safety net a maintainer wants on previously
untested code.

A target is landable ONLY when BOTH the input slice and the output are decidable:

* **Input synthesis — the SOUND slice only** (no LLM basis for anything else):
  zero-arg ``()``; OR every parameter carries a TS PRIMITIVE type
  (``number``->``0``, ``string``->``""``, ``boolean``->``false``, ``T[]`` /
  ``Array<T>``->``[]``); OR every parameter has a LITERAL default (re-emitted
  verbatim). ANY untyped, non-defaulted parameter -> REFUSE (the honest reach
  ceiling).
* **A reproducible value oracle** — the captured return must be a JSON-serialisable
  simple value (number/string/boolean/null, or arrays/objects composed only of
  those) AND survive the ENV-REPRODUCIBILITY re-capture gate
  (:func:`_env_is_reproducible`): re-executing the producing call in clean ``node``
  child processes under varied ``TZ`` / ``cwd`` / ``$HOME`` / ``$TMPDIR`` AND across
  a ``> 1s`` wall-clock gap must re-render the SAME ``JSON.stringify`` bytes on EVERY
  axis. Without this gate a flaky value (clock/random/env/IO) would pass the jest
  gate ONCE then go RED later — the moat's cardinal fake-green sin. The driver's AST
  ``pure`` flag (a forbidden-call/free-identifier scan) is the cheap FIRST guard;
  this gate is the load-bearing second.

The generator only PROPOSES the test bytes (:func:`generate_js_cover_test`); the
objective decides to land it via a :class:`RenamePlan` proven by the FORCED jest
gate + byte-for-byte auto-rollback. A module ALREADY covered by a linked jest test
is never clobbered (the generator returns ``None``). Deterministic, offline
(``typescript`` is global; Apex installs nothing), zero-token: the synthesized
inputs are fixed, the transpile/capture is a pure function of the bytes, and the
re-capture variation values are pinned, so the same module yields byte-identical
test source every run.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.execution.js.js_tool import (
    JsCoverTarget,
    cover_targets,
    global_node_modules,
)

__all__ = ["JsCoverTest", "generate_js_cover_test"]


# A safe "zero value" literal to synthesize for a parameter of each TS PRIMITIVE
# type — the JS image of test_shield's ``_ARG_SAMPLE``. A primitive-typed param is
# the SOUND slice: its zero sample is a real value of the declared type, so the
# captured oracle is a faithful characterization. Anything not here (an object
# type, a union, a custom class, a generic ``T``) is NOT a primitive and makes the
# target refuse unless every param is instead literal-defaulted.
_PRIMITIVE_SAMPLE: dict[str, str] = {
    "number": "0",
    "string": '""',
    "boolean": "false",
    "bigint": "0n",
}


def _array_sample(ts_type: str) -> str | None:
    """``"[]"`` when ``ts_type`` is an ARRAY type (``T[]`` or ``Array<T>`` /
    ``ReadonlyArray<T>``), else ``None``.

    An array type's sound zero sample is the empty array — a real value of the type
    regardless of the element type ``T`` (we never need to synthesize a ``T``). Pure
    string inspection of the verbatim annotation: a trailing ``[]`` (``number[]``,
    ``string[][]``) or an ``Array<...>`` / ``ReadonlyArray<...>`` head. Anything
    else is not an array type."""
    t = ts_type.strip()
    if t.endswith("[]"):
        return "[]"
    if t.startswith("Array<") and t.endswith(">"):
        return "[]"
    if t.startswith("ReadonlyArray<") and t.endswith(">"):
        return "[]"
    return None


def _sample_for_param(ts_type: str | None, default_text: str | None) -> str | None:
    """The SOUND sample argument source for ONE parameter, or ``None`` to REFUSE.

    The honest reach ceiling, in priority order: (1) a LITERAL default is re-emitted
    verbatim (the author already chose a concrete value); (2) a PRIMITIVE type maps
    to its fixed zero sample; (3) an ARRAY type maps to ``[]``. ANY other shape — an
    untyped, non-defaulted param, an object/union/custom/generic type with no
    default — yields ``None``: there is no LLM-free basis for a sound sample, so the
    whole target is refused. Deterministic: a fixed table + pure string inspection,
    no clock/random."""
    if default_text is not None:
        return default_text  # a literal default the author chose — verbatim
    if ts_type is None:
        return None  # untyped, non-defaulted -> no sound basis -> refuse
    prim = _PRIMITIVE_SAMPLE.get(ts_type.strip())
    if prim is not None:
        return prim
    return _array_sample(ts_type)  # T[] / Array<T> -> "[]", else None (refuse)


def _synth_args(target: JsCoverTarget) -> list[str] | None:
    """The synthesized argument SOURCES for ``target``'s call, or ``None`` to REFUSE.

    Zero-arg is the trivial sound slice (an empty list). Otherwise EVERY parameter
    must yield a sound sample (:func:`_sample_for_param`); a single un-synthesizable
    param refuses the whole target. The list is the literal source of each argument,
    in order — exactly what the call ``fn(<a0>, <a1>)`` and the oracle child use."""
    out: list[str] = []
    for param in target.params:
        sample = _sample_for_param(param.type, param.default_text)
        if sample is None:
            return None  # an un-synthesizable param -> refuse the whole target
        out.append(sample)
    return out


@dataclass
class JsCoverTest:
    """A proposed jest characterization test, NOT yet written to disk.

    ``functions`` is the document-ordered list of exported function names the test
    actually pins with a value oracle. Empty is never proposed (the generator
    returns ``None`` instead) — a test that pins nothing is not worth landing."""

    module_rel: str
    test_rel: str
    content: str
    functions: list[str] = field(default_factory=list)


# The capture/transpile probe (the twin of test_shield's ``_RECAPTURE_PROBE``):
# transpile the target module to CommonJS with the global ``typescript`` (a pure,
# typecheck-free syntax transform), write it as a SIBLING temp file in the module's
# OWN directory so any relative ``import``/``require`` resolves against the real
# tree, ``require`` it, call ``mod[name](<synthArgs>)`` (the args are LLM-free
# synthesized literal SOURCE), and print the canonical ``JSON.stringify`` of the
# return. argv: source file, function name, JSON array of arg-source strings.
#
# Serializability gate (the JS image of ``_is_simple_literal``): a return is a value
# oracle ONLY when ``JSON.stringify`` yields a string that ``JSON.parse`` round-
# trips to a deep-equal value — this rejects ``undefined`` (stringify -> undefined),
# a function, a class instance with methods, ``NaN``/``Infinity`` (stringify ->
# ``null``, which would not round-trip to the original), a circular structure
# (stringify throws), a ``BigInt`` (stringify throws), and a ``Symbol``. Any failure
# at any step (transpile error, require throws, the call throws, a non-serialisable
# return) prints ``{"ok": false}`` so the caller DECLINES — never an unverified
# oracle.
_CAPTURE_PROBE = r"""
"use strict";
// `node -e <script> A B C` exposes process.argv as [node, A, B, C] (no script
// placeholder, the leading `--` consumed by node), so the args start at argv[1].
const fs = require("fs");
const path = require("path");
const ts = require("typescript");
const srcFile = process.argv[1];
const name = process.argv[2];
const argSources = JSON.parse(process.argv[3]);
let tmpFile = null;
// decline() exits the probe, but process.exit(0) BYPASSES the finally{} cleanup
// below, so it must FIRST remove the sibling temp it wrote into the buyer's source
// dir (the transient-hazard CLAUDE.md warns about). Guarded: tmpFile is null until
// the temp is written, so a decline before that (transpile/require failure) is a
// no-op; the unlink is wrapped so a missing/locked file never masks the exit.
function decline() {
  if (tmpFile) { try { fs.unlinkSync(tmpFile); } catch (e) {} }
  process.stdout.write(JSON.stringify({ ok: false }));
  process.exit(0);
}
// A value is a SOUND oracle leaf only when every scalar it (recursively) contains
// is a JSON-faithful, deterministic literal: a finite number (NaN/Infinity
// stringify to `null` — a WRONG oracle, the JS image of test_shield rejecting
// NaN), a string, a boolean, or null. A function/undefined/symbol/bigint leaf, or
// any non-plain object (a class instance with a prototype, a Map/Set/Date) is
// rejected — JSON.stringify would silently drop or mis-encode it, so pinning the
// serialized form would assert a value the function does not actually return.
function isSoundValue(v, seen) {
  if (v === null) return true;
  const t = typeof v;
  if (t === "boolean" || t === "string") return true;
  if (t === "number") return Number.isFinite(v);  // NaN/Infinity -> reject
  if (t === "undefined" || t === "function" || t === "symbol" || t === "bigint") return false;
  if (t === "object") {
    if (seen.indexOf(v) !== -1) return false;  // circular -> reject
    seen.push(v);
    if (Array.isArray(v)) return v.every((x) => isSoundValue(x, seen));
    // Only a PLAIN object (Object.prototype or null proto) is a faithful JSON
    // map; a class instance / Map / Set / Date has a non-plain prototype.
    const proto = Object.getPrototypeOf(v);
    if (proto !== Object.prototype && proto !== null) return false;
    return Object.keys(v).every((k) => isSoundValue(v[k], seen));
  }
  return false;
}
try {
  const source = fs.readFileSync(srcFile, "utf8");
  const out = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2019,
      esModuleInterop: true,
      // No typecheck, no source map, no emit decorators metadata — a pure,
      // deterministic syntax-only TS->CJS transform (identity-ish for plain JS).
    },
    fileName: srcFile,
    reportDiagnostics: false,
  });
  // Write the transpiled module as a sibling of the original (so a relative
  // import resolves against the real node_modules / siblings), require it, then
  // delete it. ABSOLUTE path so `require` treats it as a file (a bare/relative
  // specifier under `node -e` is a module-name lookup, not a path). A fixed prefix
  // keeps the FILENAME deterministic per process.
  const dir = path.resolve(path.dirname(srcFile));
  tmpFile = path.join(dir, ".apex_cover_capture_" + process.pid + ".js");
  fs.writeFileSync(tmpFile, out.outputText, "utf8");
  const mod = require(tmpFile);
  const fn = mod && mod[name];
  if (typeof fn !== "function") decline();
  // Build the call from the synthesized literal arg SOURCES (LLM-free literals).
  const callBody = "return fn(" + argSources.join(", ") + ");";
  const value = (new Function("fn", callBody))(fn);
  // Soundness gate: every scalar leaf must be a JSON-faithful deterministic literal
  // (a finite number / string / boolean / null, in plain objects/arrays). This
  // rejects NaN/Infinity (which JSON.stringify maps to `null` — a WRONG oracle),
  // undefined, a function, a class instance with a prototype, a Map/Set/Date, and a
  // circular structure — none of which JSON.stringify pins faithfully.
  if (!isSoundValue(value, [])) decline();
  let serialized;
  try { serialized = JSON.stringify(value); } catch (e) { decline(); }
  if (typeof serialized !== "string") decline();
  // Belt-and-suspenders: the serialized form must re-parse + re-serialize identically.
  let roundTrip;
  try { roundTrip = JSON.parse(serialized); } catch (e) { decline(); }
  if (JSON.stringify(roundTrip) !== serialized) decline();
  process.stdout.write(JSON.stringify({ ok: true, json: serialized }));
} catch (e) {
  decline();
} finally {
  if (tmpFile) { try { fs.unlinkSync(tmpFile); } catch (e) {} }
}
"""


# Distinct, fixed values for each environment axis a captured value might read —
# the JS image of test_shield's ``_ENV_VARIATION_SEEDS``. A value that reads cwd
# (``process.cwd()``), ``$HOME`` (``os.homedir()``), ``$TZ`` (a locale-formatted
# date — though the AST gate already refuses ``Date``), or ``$TMPDIR``
# (``os.tmpdir()``) re-renders different bytes under at least one variation. The
# values are pinned literals so the gate is itself DETERMINISTIC (same variations
# every run); cwd / HOME / TMPDIR are filled with REAL temp directories at call
# time (a non-existent cwd would make every child fail and spuriously decline).
_ENV_VARIATIONS = (
    {"name": "alpha", "TZ": "America/New_York"},
    {"name": "beta", "TZ": "Asia/Tokyo"},
)


def _probe_env(project_root: Path, extra: dict[str, str]) -> dict[str, str]:
    """The child-process environment: the parent env, ``NODE_PATH`` set to the
    global ``node_modules`` (so the transpile child's ``require("typescript")``
    resolves), plus ``extra`` overrides. ``NODE_PATH`` mirrors the one
    :func:`app.execution.js.js_tool._run_driver` sets for every driver call."""
    env = dict(os.environ)
    node_path = global_node_modules()
    if node_path:
        env["NODE_PATH"] = node_path
    env.update(extra)
    return env


def _run_capture(project_root: Path, src_file: str, name: str,
                 arg_sources: list[str], env_overrides: dict[str, str],
                 cwd: str | None) -> str | None:
    """Re-capture ``name(arg_sources)``'s canonical ``JSON.stringify`` in a CLEAN
    ``node`` subprocess under ``env_overrides`` (layered on the parent env) and
    working directory ``cwd``, or ``None`` on ANY failure.

    The single subprocess primitive the in-process capture and every env/clock axis
    share: a fresh ``node`` runs :data:`_CAPTURE_PROBE` (transpile -> require ->
    call -> stringify) under the given env. A value that reads cwd / HOME / TZ /
    TMPDIR re-renders DIFFERENT bytes here; any subprocess error/crash/timeout, or a
    child that itself declines, yields ``None`` (the caller then declines too —
    never an unverified oracle)."""
    env = _probe_env(project_root, env_overrides)
    try:
        proc = subprocess.run(
            ["node", "-e", _CAPTURE_PROBE, "--",
             src_file, name, json.dumps(arg_sources)],
            cwd=cwd if cwd is not None else str(project_root),
            capture_output=True, text=True, env=env, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    if not result.get("ok"):
        return None
    captured = result.get("json")
    return captured if isinstance(captured, str) else None


# The TIME probe: capture the canonical JSON TWICE in ONE fresh node process,
# separated by a real ``> 1s`` busy-wait, and report whether the two captures are
# byte-identical. A value that reads the wall clock advances across the gap and the
# two captures DIFFER (so the caller declines it); a stable value is identical on
# both. The ``> 1s`` gap makes a ``Date.now()`` ms reading advance by >=1000
# DETERMINISTICALLY (the check always declines a clock value and always accepts a
# stable one), so the gate stays deterministic. A BUSY-WAIT (not setTimeout) keeps
# the probe synchronous and avoids the event loop, so a transpiled module's
# top-level code cannot interfere. argv as the capture probe.
_TIME_PROBE = r"""
"use strict";
// argv layout as the capture probe: `node -e <script> A B C` -> argv[1..3].
const fs = require("fs");
const path = require("path");
const ts = require("typescript");
const srcFile = process.argv[1];
const name = process.argv[2];
const argSources = JSON.parse(process.argv[3]);
let tmpFile = null;
// decline() exits the probe, but process.exit(0) BYPASSES the finally{} cleanup
// below, so it must FIRST remove the sibling temp it wrote into the buyer's source
// dir (the transient-hazard CLAUDE.md warns about). Guarded as in _CAPTURE_PROBE.
function decline() {
  if (tmpFile) { try { fs.unlinkSync(tmpFile); } catch (e) {} }
  process.stdout.write(JSON.stringify({ ok: false }));
  process.exit(0);
}
function isSoundValue(v, seen) {
  if (v === null) return true;
  const t = typeof v;
  if (t === "boolean" || t === "string") return true;
  if (t === "number") return Number.isFinite(v);
  if (t === "undefined" || t === "function" || t === "symbol" || t === "bigint") return false;
  if (t === "object") {
    if (seen.indexOf(v) !== -1) return false;
    seen.push(v);
    if (Array.isArray(v)) return v.every((x) => isSoundValue(x, seen));
    const proto = Object.getPrototypeOf(v);
    if (proto !== Object.prototype && proto !== null) return false;
    return Object.keys(v).every((k) => isSoundValue(v[k], seen));
  }
  return false;
}
function serialize(value) {
  if (!isSoundValue(value, [])) return null;
  let s;
  try { s = JSON.stringify(value); } catch (e) { return null; }
  if (typeof s !== "string") return null;
  let rt;
  try { rt = JSON.parse(s); } catch (e) { return null; }
  return JSON.stringify(rt) === s ? s : null;
}
try {
  const source = fs.readFileSync(srcFile, "utf8");
  const out = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2019, esModuleInterop: true },
    fileName: srcFile, reportDiagnostics: false,
  });
  const dir = path.resolve(path.dirname(srcFile));
  tmpFile = path.join(dir, ".apex_cover_time_" + process.pid + ".js");
  fs.writeFileSync(tmpFile, out.outputText, "utf8");
  const mod = require(tmpFile);
  const fn = mod && mod[name];
  if (typeof fn !== "function") decline();
  const callBody = "return fn(" + argSources.join(", ") + ");";
  const call = new Function("fn", callBody);
  const first = serialize(call(fn));
  if (first === null) decline();
  // Busy-wait > 1s so a millisecond clock reading advances deterministically.
  const start = Date.now();
  while (Date.now() - start < 1100) { /* spin */ }
  const second = serialize(call(fn));
  if (second === null) decline();
  process.stdout.write(JSON.stringify({ ok: true, stable: first === second, json: first }));
} catch (e) {
  decline();
} finally {
  if (tmpFile) { try { fs.unlinkSync(tmpFile); } catch (e) {} }
}
"""


def _time_recapture_is_stable(project_root: Path, src_file: str, name: str,
                              arg_sources: list[str], in_process_json: str) -> bool:
    """``True`` iff the value is stable across a wall-clock gap (the time axis).

    Runs :data:`_TIME_PROBE`: one child captures the canonical JSON twice, separated
    by a ``> 1s`` busy-wait. A value that reads the clock advances and the two
    captures differ -> ``False``; we ALSO require the child's first capture to match
    ``in_process_json`` so a value that already diverged from the parent is refused.
    A child that fails/declines -> ``False``."""
    env = _probe_env(project_root, {})
    try:
        proc = subprocess.run(
            ["node", "-e", _TIME_PROBE, "--",
             src_file, name, json.dumps(arg_sources)],
            cwd=str(project_root), capture_output=True, text=True,
            env=env, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False
    if not result.get("ok") or not result.get("stable"):
        return False
    return result.get("json") == in_process_json


def _env_recapture_matches(project_root: Path, src_file: str, name: str,
                           arg_sources: list[str], in_process_json: str,
                           stack: contextlib.ExitStack) -> bool:
    """Re-capture under each environment variation; ``True`` iff EVERY variation
    re-renders byte-identically to ``in_process_json``.

    For each spec in :data:`_ENV_VARIATIONS` a fresh temp cwd, ``$HOME`` and
    ``$TMPDIR`` are created (registered on ``stack`` so they are cleaned up) and the
    producing call is re-run there with that spec's distinct ``$TZ``. A value that
    reads cwd / HOME / TMPDIR / TZ diverges under at least one variation and yields
    ``False``; a child that fails/declines also yields ``False`` (refuse, never an
    unverified oracle)."""
    for spec in _ENV_VARIATIONS:
        base = stack.enter_context(tempfile.TemporaryDirectory(prefix="apex_jsenv_"))
        var_cwd = os.path.join(base, "cwd")
        var_home = os.path.join(base, "home")
        var_tmp = os.path.join(base, "tmp")
        for d in (var_cwd, var_home, var_tmp):
            os.makedirs(d, exist_ok=True)
        overrides = {
            "HOME": var_home, "TMPDIR": var_tmp, "TEMP": var_tmp, "TMP": var_tmp,
            "TZ": spec["TZ"],
        }
        child = _run_capture(project_root, src_file, name, arg_sources,
                             overrides, var_cwd)
        if child is None or child != in_process_json:
            return False
    return True


def _env_is_reproducible(project_root: Path, src_file: str, name: str,
                         arg_sources: list[str], in_process_json: str) -> bool:
    """The multi-AXIS environment-reproducibility gate (the load-bearing soundness
    guarantee — the JS port of ``test_shield._env_is_reproducible``).

    A captured value is honest to PIN only if re-running the producing call under a
    VARIED environment re-renders the SAME canonical ``JSON.stringify`` bytes. We
    re-capture in clean ``node`` subprocesses under distinct cwd / ``$HOME`` /
    ``$TZ`` / ``$TMPDIR`` variations (:func:`_env_recapture_matches`) AND across a
    ``> 1s`` wall-clock gap (:func:`_time_recapture_is_stable`), accepting the value
    ONLY when it is byte-identical across ALL of them. This catches a value that
    reads any of those axes (``process.cwd()``, ``os.homedir()``, ``os.tmpdir()``,
    ``Date.now()``, ``new Date().toLocaleString()`` ...) EVEN IF it slipped the
    driver's AST ``pure`` scan (a transitive read through a local helper the scan
    does not follow). Conservative by construction: any child that fails/declines
    makes this ``False`` — over-refusal is safe, a future-RED pinned test is not.
    Deterministic: the variation values are pinned, so the same input yields the same
    decision every run."""
    with contextlib.ExitStack() as stack:
        if not _env_recapture_matches(project_root, src_file, name, arg_sources,
                                      in_process_json, stack):
            return False
    return _time_recapture_is_stable(project_root, src_file, name, arg_sources,
                                     in_process_json)


def _capture_oracle(project_root: Path, rel: str, target: JsCoverTarget,
                    arg_sources: list[str]) -> str | None:
    """The canonical ``JSON.stringify`` oracle for ``target`` called with
    ``arg_sources``, or ``None`` when no honest value oracle is available.

    Captures the real return once (the in-process baseline is itself a clean
    subprocess under the parent env), then DECLINES unless the value survives the
    full env-reproducibility re-capture gate (:func:`_env_is_reproducible`) — varied
    cwd / HOME / TZ / TMPDIR and a wall-clock gap. Any decline (the call throws on
    the synthesized args, a non-serialisable return, an env-fragile value) yields
    ``None`` and the target lands no test. The function is asserted ``pure`` by the
    driver BEFORE reaching here, so this gate is the second, load-bearing flaky-test
    guard on top of that AST scan."""
    # ABSOLUTE source path: the env-reproducibility gate VARIES the child cwd, so a
    # relative path would resolve against the wrong directory in those children.
    src_file = str((Path(project_root) / rel).resolve())
    baseline = _run_capture(project_root, src_file, target.name, arg_sources, {}, None)
    if baseline is None:
        return None  # call threw / non-serialisable / transpile failed -> no oracle
    if not _env_is_reproducible(project_root, src_file, target.name,
                                arg_sources, baseline):
        return None  # env/clock-fragile -> would go RED elsewhere -> refuse
    return baseline


def _matcher_for(captured_json: str) -> str:
    """The jest matcher for a captured value: ``toStrictEqual`` for an object/array
    return (a structural deep-equal that also checks the prototype/shape), else
    ``toEqual`` for a scalar. Mirrors the ts_driver mined-matcher set
    (toBe/toEqual/toStrictEqual). Pure inspection of the serialized JSON's first
    non-whitespace character — ``{`` or ``[`` is a composite."""
    head = captured_json.lstrip()[:1]
    return "toStrictEqual" if head in ("{", "[") else "toEqual"


def _import_specifier(module_rel: str, test_rel: str) -> str:
    """The relative ``require`` specifier from ``test_rel`` to ``module_rel`` (no
    extension, POSIX, always ``./``-prefixed) — e.g. a test at
    ``__tests__/math.cover.test.js`` importing ``src/math.ts`` yields
    ``../src/math``. Deterministic: a pure path computation, no filesystem touch."""
    rel = os.path.relpath(Path(module_rel).with_suffix("").as_posix(),
                          Path(test_rel).parent.as_posix())
    spec = Path(rel).as_posix()
    return spec if spec.startswith((".", "/")) else "./" + spec


def _render(module_rel: str, test_rel: str, module_stem: str,
            oracles: list[tuple[str, list[str], str]]) -> str:
    """The deterministic jest test source pinning each ``(name, args, captured)``
    value oracle.

    Each oracle becomes ``expect(name(<args>)).toEqual(<captured>)`` (or
    ``toStrictEqual`` for an object/array return) — a true VALUE-ORACLE
    characterization that asserts what the function really does, never a fabricated
    expectation. The functions are imported by a relative ``require`` so the test
    runs under the project's own jest (which transforms ``.ts``). Document order,
    no clock/random — same module -> byte-identical bytes."""
    spec = _import_specifier(module_rel, test_rel)
    names = ", ".join(name for name, _args, _cap in oracles)
    lines = [
        "// Generated by Apex Orchestrator - jest characterization test",
        f"// module: {module_rel}",
        "//",
        "// Pins the module's CURRENT behaviour. Each exported function below was",
        "// CALLED with synthesized inputs at generation time and its real return",
        "// value captured and pinned as a value oracle (expect(fn(...)).toEqual(",
        "// <value>)) — sound by construction, env-reproducibility-gated. Regenerate,",
        "// do not hand-tune.",
        f'const {{ {names} }} = require("{spec}");',
        "",
    ]
    for name, args, captured in oracles:
        matcher = _matcher_for(captured)
        call = f"{name}({', '.join(args)})"
        lines += [
            f'test("{module_stem}: {name} characterization", () => {{',
            "  // Value oracle: the captured real return value pins behaviour exactly.",
            f"  expect({call}).{matcher}({captured});",
            "});",
            "",
        ]
    return "\n".join(lines)


def _test_rel_for(module_rel: str) -> str:
    """The deterministic NEW jest test path for ``module_rel`` — a sibling
    ``<dir>/__tests__/<stem>.cover.test.<ext>`` (jest's default ``__tests__``
    discovery, the ``.cover.test`` infix distinguishing Apex's generated
    characterization test). The extension follows the source (``.ts`` source -> a
    ``.ts`` test so jest's TS transform applies). Pure path computation."""
    src = Path(module_rel)
    ext = src.suffix.lstrip(".") or "js"
    # A jest .ts test needs a TS-aware extension; keep .tsx/.jsx/.mjs/.cjs as-is.
    return (src.parent / "__tests__" / f"{src.stem}.cover.test.{ext}").as_posix()


def generate_js_cover_test(project_root: str | Path, module_rel: str,
                           locate_test) -> JsCoverTest | None:
    """Synthesize a jest characterization test for ``module_rel`` (relative to
    root), or ``None`` when one cannot/should not be generated.

    Returns a :class:`JsCoverTest` to be landed by the objective, or ``None`` when:
      - the module exposes no landable characterization target (no exported public
        pure function whose inputs are in the SOUND slice and whose real return is a
        reproducible value oracle);
      - the destination ``<dir>/__tests__/<stem>.cover.test.<ext>`` already exists
        (never clobber a generated test);
      - ``locate_test(name)`` finds an EXISTING jest test that already pins a target
        (never clobber / duplicate — the module, or that function, is already
        covered).

    ``locate_test`` is the caller-supplied linkage probe (the objective passes
    :func:`app.execution.lang.js_adapter._locate_test` bound to the project + file):
    given a function name it returns the single jest test that imports the module
    AND references the name, or ``None``. Deterministic; reuses the driver's
    source-order target enumeration."""
    root = Path(project_root)
    targets = cover_targets(root, module_rel)
    if not targets:
        return None  # nothing exported/characterizable — honest no-op

    test_rel = _test_rel_for(module_rel)
    if (root / test_rel).exists():
        return None  # never clobber a generated test

    oracles: list[tuple[str, list[str], str]] = []
    for target in targets:
        if not target.pure:
            continue  # the AST flaky-test pre-filter refused it
        if locate_test(target.name) is not None:
            continue  # an existing jest test already pins it — never clobber/dup
        arg_sources = _synth_args(target)
        if arg_sources is None:
            continue  # an un-synthesizable param — outside the sound input slice
        captured = _capture_oracle(root, module_rel, target, arg_sources)
        if captured is None:
            continue  # the call threw / non-serialisable / env-fragile -> refuse
        oracles.append((target.name, arg_sources, captured))

    if not oracles:
        return None  # no landable value oracle — honest no-op (never a smoke test)

    module_stem = Path(module_rel).stem
    content = _render(module_rel, test_rel, module_stem, oracles)
    return JsCoverTest(
        module_rel=module_rel,
        test_rel=test_rel,
        content=content,
        functions=[name for name, _args, _cap in oracles],
    )
