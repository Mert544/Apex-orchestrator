"""JS/TS test-STRENGTHENING — kill a mutant the function's MINED witnesses miss.

The LITE, sound, mined-witness variant of the Python ``strengthen_tests`` for the
JS/TS lane. Where :mod:`app.execution.js.js_cover_gaps` writes the FIRST jest
characterization test for an UNTESTED function, this STRENGTHENS an ALREADY-tested
one: it finds a single-token MUTATION the function's EXISTING jest test (its mined
``expect(fn(args)).matcher(expected)`` witnesses) does NOT catch, and lands ONE new
env-gated characterization assertion that DOES — closing a real, *narrower* blind
spot with real new test code.

HONESTY (do NOT over-claim): this strengthens against the function's PINNED/MINED
test witnesses, NOT against arbitrary full-suite blind spots. A feasibility scout
proved the FULL Python-strengthen mirror is unsound to build for JS (survivor
detection would need the buyer's jest suite run per-mutant — a moat hazard). THIS
variant decides survival against the MINED witnesses (no per-mutant suite run) and
proves correctness via the SINGLE landing-time forced jest gate. It NEVER implies
full mutation coverage.

The pipeline (deterministic, no LLM, no clock, no randomness):

1. **Target.** An EXPORTED, public, undecorated, non-async, non-generator PURE
   function (the driver ``cover-targets`` ``pure`` flag) that HAS exactly one linked
   jest test (:func:`app.execution.lang.js_adapter._locate_test` is not ``None``)
   AND mineable witnesses (:func:`app.execution.js.js_tool.mine_witnesses`). This is
   DISJOINT from js-cover-gaps, which fires ONLY when ``_locate_test`` is ``None``.
2. **Mutation seeding.** The driver ``mutate`` subcommand emits a fixed, deterministic
   catalog of single-token mutants (comparison/boundary/arithmetic/boolean flips,
   bool-const, ``n``->``n+1``, ``return X``->``return undefined``), each a UTF-16
   span splice the in-memory copy applies — NEVER written to the real source.
3. **Survivor detection (LITE — NO buyer jest run).** A mutant is a SURVIVOR iff
   EVERY mined witness STILL matches on the mutated source (the existing test is
   blind to it). A mutant that changes a witness is already caught -> skipped; a
   mutant that cannot be transpiled/run is skipped (conservative).
4. **Killing-assertion synthesis.** For a survivor, synthesize a fresh input (the
   js-cover-gaps input synthesis), capture the REAL function's output
   (env-reproducibility-gated + serializable-gated — REUSED from js-cover-gaps) AND
   the MUTANT's output on the same input; KEEP ``expect(fn(input)).toEqual(<real>)``
   ONLY when it DIVERGES on the mutant (real != mutant — it provably kills the
   survivor). The asserted value is the REAL output, never fabricated.
5. **Land.** The new assertions are appended to an Apex-OWNED test file
   ``<stem>.apex-mutants.cover.test.<ext>`` (collision-proof; the buyer's existing
   test is NEVER edited). The objective lands it as a :class:`RenamePlan` proven by
   the FORCED jest gate + byte-for-byte auto-rollback.

REUSES the js-cover-gaps machinery wholesale: the serializability gate
(``isSoundValue``), the env-reproducibility gate (:func:`_env_is_reproducible`), the
input synthesis (:func:`_synth_args`), the capture child discipline. Deterministic,
offline (``typescript`` is global; Apex installs nothing), zero-token: the synthesized
inputs are fixed, the mutant catalog is fixed, and the transpile/capture is a pure
function of the bytes, so the same module yields byte-identical assertions every run.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.execution.js.js_cover_gaps import (
    _array_sample,
    _env_is_reproducible,
    _matcher_for,
    _probe_env,
    _synth_args,
)
from app.execution.js.js_tool import (
    JsCoverParam,
    JsCoverTarget,
    JsWitness,
    cover_targets,
    mine_witnesses,
)
from app.execution.lang.js_adapter import _u16_to_codepoint

__all__ = ["JsMutant", "JsStrengthenTest", "generate_js_strengthen_test"]

# A fixed, DETERMINISTIC per-type probe pool. js-cover-gaps' ``_synth_args`` produces
# a single "zero value" per param — but to KILL a mutant we need an input that
# actually crosses the branch / distinguishes the flipped operator the mutant lives
# on (``add(0,0)`` does NOT tell ``+`` from ``-``; ``add(2,1)`` does). This is the JS
# image of strengthen_tests' ``_PROBE_POOL``: a fixed, boundary-relevant set of
# literal SOURCES per primitive type, tried in this exact order so the FIRST input
# that both runs on the real code and diverges on a survivor is reproducible across
# runs. The literals re-emit verbatim into the asserted call. Numbers span sign / zero
# / off-by-one neighbours (the operator/boundary flips key on these); the others span
# their small sound domains.
_PROBE_POOL: dict[str, tuple[str, ...]] = {
    "number": ("2", "1", "0", "3", "-1"),
    "bigint": ("2n", "1n", "0n"),
    "string": ('""', '"a"', '"ab"'),
    "boolean": ("true", "false"),
}

# Bound on the Cartesian product of probes across a function's parameters, so a
# many-argument function never explodes the search. Deterministic: the first
# ``_MAX_COMBINATIONS`` tuples in fixed product order are tried.
_MAX_COMBINATIONS = 256


def _number_pool(numeric_hints: tuple[str, ...]) -> tuple[str, ...]:
    """The DETERMINISTIC number probe pool: the fixed boundary-relevant base PLUS each
    numeric literal the function's OWN body uses and its off-by-one neighbours.

    A fixed small pool (``2/1/0/3/-1``) distinguishes most operator flips, but a
    BOUNDARY (``>=``->``>``) or a numeric (``n``->``n+1``) mutant on ``n >= 5`` only
    diverges AT the constant ``5`` — which no fixed pool can know. So we make the pool
    function-AWARE: ``numeric_hints`` are the integer literals appearing in the body
    (harvested from the seeded ``number:<N>`` mutants), and for each we add ``N`` and
    ``N±1`` so the boundary value and its neighbours are probed. Deterministic: the
    base first (fixed order), then the sorted hint values, de-duplicated. Pure, no
    clock/random."""
    out: list[str] = list(_PROBE_POOL["number"])
    extra: set[int] = set()
    for hint in numeric_hints:
        try:
            n = int(hint)
        except ValueError:
            continue  # a float/hex/etc. literal -> the base pool still applies
        extra.update((n - 1, n, n + 1))
    for n in sorted(extra):
        token = str(n)
        if token not in out:
            out.append(token)
    return tuple(out)


def _numeric_hints(mutants: list[JsMutant]) -> tuple[str, ...]:
    """The integer literal texts the function's body uses, in deterministic sorted
    order, harvested from its seeded ``number:<N>`` mutants — the boundary values the
    probe pool must include to kill a boundary / numeric mutant."""
    hints = {m.original for m in mutants if m.operator.startswith("number:")}
    return tuple(sorted(hints))


def _probe_values_for_param(param: JsCoverParam,
                            numeric_hints: tuple[str, ...]) -> tuple[str, ...] | None:
    """The DETERMINISTIC candidate argument SOURCES to try for ONE parameter, or
    ``None`` to REFUSE (outside the sound slice).

    Priority (the honest reach ceiling, mirroring js-cover-gaps' ``_sample_for_param``
    but BROADENED to a small pool so a mutant becomes distinguishable): a LITERAL
    default is the single candidate (the author's chosen value); else a ``number``
    type maps to the function-aware :func:`_number_pool` (the fixed base + the body's
    own boundary literals); else another PRIMITIVE type maps to its fixed
    :data:`_PROBE_POOL` row; else an ARRAY type maps to the ``[]`` sound sample.
    Anything else — an untyped non-defaulted param, an object/union/custom/generic
    type with no default — yields ``None`` (no LLM-free basis, the whole target is
    refused). Pure table + string inspection, no clock."""
    if param.default_text is not None:
        return (param.default_text,)  # the author's chosen literal default
    if param.type is None:
        return None  # untyped, non-defaulted -> no sound basis -> refuse
    t = param.type.strip()
    if t == "number":
        return _number_pool(numeric_hints)
    pool = _PROBE_POOL.get(t)
    if pool is not None:
        return pool
    arr = _array_sample(param.type)  # T[] / Array<T> -> "[]" (the sound array sample)
    if arr is not None:
        return (arr,)
    return None  # object/union/custom/generic with no default -> refuse


def _probe_inputs(target: JsCoverTarget, numeric_hints: tuple[str, ...] = ()):
    """Yield DETERMINISTIC candidate argument-source tuples for ``target``, or yield
    nothing when any parameter is outside the sound slice.

    Zero-arg yields the single empty tuple. Otherwise EVERY parameter must contribute
    a sound probe pool (:func:`_probe_values_for_param`); a single un-probeable param
    yields NOTHING (the whole target is refused). ``numeric_hints`` (the body's own
    integer literals — see :func:`_numeric_hints`) widen each ``number`` param's pool
    so a boundary / numeric mutant becomes distinguishable. The tuples are the
    Cartesian product of the per-param pools in fixed order, capped at
    :data:`_MAX_COMBINATIONS`, so the first input that runs + diverges + is
    env-reproducible is reproducible every run."""
    import itertools

    if not target.params:
        yield []
        return
    pools: list[tuple[str, ...]] = []
    for param in target.params:
        values = _probe_values_for_param(param, numeric_hints)
        if values is None:
            return  # an un-probeable param -> refuse the whole target (yield nothing)
        pools.append(values)
    for combo in itertools.islice(itertools.product(*pools), _MAX_COMBINATIONS):
        yield list(combo)


@dataclass(frozen=True)
class JsMutant:
    """One single-token mutant the driver seeded for a function: the ``operator``
    label, the ``original`` token text, the ``mutated`` replacement, and the UTF-16
    code-unit span (``start``/``end``) to splice. A gap-FINDER only — applied to an
    IN-MEMORY copy of the source, never persisted to the real tree."""

    operator: str
    original: str
    mutated: str
    start: int
    end: int


@dataclass
class JsStrengthenTest:
    """A proposed Apex-owned jest test STRENGTHENING the module, NOT yet written.

    ``functions`` is the document-ordered list of function names whose mined-witness
    blind spot the new assertions close. Empty is never proposed (the generator
    returns ``None``) — a test that kills no surviving mutant adds no signal."""

    module_rel: str
    test_rel: str
    content: str
    functions: list[str] = field(default_factory=list)


def _driver_mutants(project_root: Path, module_rel: str, name: str) -> list[JsMutant]:
    """The driver ``mutate`` catalog for ``name`` in ``module_rel`` (empty on refuse).

    Spawns the bundled ``ts_driver.js`` ``mutate`` subcommand (the single-token gap
    seeder). A file that does not parse, a name that is not an exported cover target,
    or any driver failure yields ``[]`` — nothing to strengthen, never a guess.
    Deterministic source order, exactly as the driver emits."""
    from app.execution.js.js_tool import _driver_json

    data = _driver_json(["mutate", str(project_root / module_rel), name], project_root)
    if not isinstance(data, list):
        return []
    return [JsMutant(operator=d["operator"], original=d["original"],
                     mutated=d["mutated"], start=d["start"], end=d["end"])
            for d in data]


def _apply_mutant(source: str, mutant: JsMutant) -> str | None:
    """``source`` with ``mutant``'s UTF-16 span replaced by its ``mutated`` token, or
    ``None`` when the span is stale / splits a surrogate pair (refuse rather than
    produce a corrupt mutant).

    The driver emits ``start``/``end`` as UTF-16 code units (``getStart``/``getEnd``);
    ``source`` is a code-POINT-indexed ``str``, so each offset is re-indexed via
    :func:`app.execution.lang.js_adapter._u16_to_codepoint` (the SAME re-index the JS
    body splice uses) BEFORE slicing. Produces the mutated source IN MEMORY only — it
    is never written to the real module path. Deterministic — a pure splice."""
    start = _u16_to_codepoint(source, mutant.start)
    end = _u16_to_codepoint(source, mutant.end)
    if start is None or end is None or start > end:
        return None
    return source[:start] + mutant.mutated + source[end:]


def _run_node_probe(project_root: Path, script: str, args: list[str]) -> dict | None:
    """Run ``node -e <script> -- <args>`` in a CLEAN subprocess and return the parsed
    JSON result dict, or ``None`` on ANY failure / a declined child.

    The single subprocess primitive every strengthen probe (mutant survival, mutant
    value, real-value capture) funnels through — so the run + JSON-parse + ``ok``-gate
    scaffolding lives in ONE place (never an inline copy). The child's env layers the
    global ``node_modules`` on ``NODE_PATH`` (REUSED from js-cover-gaps via
    :func:`_probe_env`) so its ``require("typescript")`` resolves. A subprocess
    error/crash/timeout, a non-zero exit, unparseable output, or a child that itself
    declined (``{ok:false}``) all yield ``None`` (the caller treats it as
    un-evaluable — conservative, never an unverified verdict). The 60s timeout matches
    js-cover-gaps' capture children."""
    env = _probe_env(project_root, {})
    try:
        proc = subprocess.run(
            ["node", "-e", script, "--", *args],
            cwd=str(project_root), capture_output=True, text=True, env=env, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return result if result.get("ok") else None


# The MUTANT capture/transpile probe (the strengthen twin of js-cover-gaps'
# ``_CAPTURE_PROBE``): transpile the MUTATED SOURCE TEXT (passed as an argument —
# NEVER read off the real module path) to CommonJS with the global ``typescript``,
# write it as a SIBLING temp file in the module's OWN directory so any relative
# import resolves against the real tree, ``require`` it, and either (a) evaluate the
# function on every mined WITNESS and report whether the existing test still matches
# (the survival decision), or (b) capture the function's canonical ``JSON.stringify``
# on a synthesized input (the divergence check). argv: mode ("survive"|"value"),
# source file (for dir/import base), function name, mutated source TEXT, payload JSON
# (the witnesses for "survive", the arg-source strings for "value").
#
# The mutated source is read from argv, NOT from disk — so the real source file is
# never touched and the mutant is never persisted. The transpiled sibling temp file
# is deleted in `finally`. Any failure (transpile error, require throws, call throws)
# reports `{ok:false}` so the caller treats the mutant as un-evaluable (conservative
# skip), never an unverified survival/divergence verdict.
_MUTANT_PROBE = r"""
"use strict";
const fs = require("fs");
const path = require("path");
const ts = require("typescript");
const mode = process.argv[1];
const srcFile = process.argv[2];
const name = process.argv[3];
const mutatedSource = process.argv[4];
const payload = JSON.parse(process.argv[5]);
// The transpiled sibling temp file (set once it is written). `cleanup` deletes it
// and MUST run before every exit path — `process.exit` does NOT run `finally`, so we
// unlink HERE in emit/decline (the early `{ok:false}`/verdict exits) AND in `finally`
// (the fall-through), so the mutant's transpiled bytes are never left in the real
// source dir (the never-persist-mutant invariant).
let tmpFile = null;
function cleanup() { if (tmpFile) { try { fs.unlinkSync(tmpFile); } catch (e) {} tmpFile = null; } }
function emit(o) { cleanup(); process.stdout.write(JSON.stringify(o)); process.exit(0); }
function decline() { emit({ ok: false }); }
// A value is a SOUND oracle leaf only when every scalar it (recursively) contains is
// a JSON-faithful, deterministic literal — the SAME gate js-cover-gaps' capture probe
// applies (a finite number / string / boolean / null, in plain objects/arrays).
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
// Canonical, ORDER-INSENSITIVE JSON of a value (object keys sorted) so a witness
// comparison and a value comparison both ignore property-insertion order — a key
// reorder is not a behavioural divergence. Returns null for a non-sound value.
function canon(v) {
  if (!isSoundValue(v, [])) return null;
  function norm(x) {
    if (Array.isArray(x)) return x.map(norm);
    if (x && typeof x === "object") {
      const o = {};
      for (const k of Object.keys(x).sort()) o[k] = norm(x[k]);
      return o;
    }
    return x;
  }
  try { return JSON.stringify(norm(v)); } catch (e) { return null; }
}
try {
  const out = ts.transpileModule(mutatedSource, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2019, esModuleInterop: true },
    fileName: srcFile, reportDiagnostics: false,
  });
  const dir = path.resolve(path.dirname(srcFile));
  tmpFile = path.join(dir, ".apex_mutant_capture_" + process.pid + ".js");
  fs.writeFileSync(tmpFile, out.outputText, "utf8");
  const mod = require(tmpFile);
  const fn = mod && mod[name];
  if (typeof fn !== "function") decline();
  if (mode === "survive") {
    // The mined witnesses: [{args:[srcExpr...], expected: srcExpr}]. The existing
    // test STILL matches a witness iff fn(...args) canonically equals `expected`
    // evaluated as a literal. A mutant SURVIVES iff EVERY witness still matches.
    for (const w of payload) {
      let got, want;
      try {
        got = (new Function("fn", "return fn(" + w.args.join(", ") + ");"))(fn);
        want = (new Function("return (" + w.expected + ");"))();
      } catch (e) {
        // The witness no longer evaluates on the mutant (e.g. it throws) -> the
        // existing test would CHANGE here -> this mutant is CAUGHT, not a survivor.
        emit({ ok: true, survives: false });
      }
      const cg = canon(got), cw = canon(want);
      // A non-serialisable witness value (a class instance / NaN) cannot be compared
      // soundly -> treat the mutant as un-evaluable (decline), never a false survive.
      if (cg === null || cw === null) decline();
      if (cg !== cw) emit({ ok: true, survives: false });  // witness changed -> caught
    }
    emit({ ok: true, survives: true });  // every witness still matches -> survivor
  } else {
    // mode === "value": the mutant's canonical output on the synthesized arg sources.
    const value = (new Function("fn", "return fn(" + payload.join(", ") + ");"))(fn);
    const c = canon(value);
    if (c === null) decline();
    emit({ ok: true, json: c });
  }
} catch (e) {
  decline();
} finally {
  cleanup();
}
"""


def _run_mutant_probe(project_root: Path, src_file: str, name: str,
                      mutated_source: str, mode: str, payload) -> dict | None:
    """Run :data:`_MUTANT_PROBE` in a CLEAN ``node`` subprocess against
    ``mutated_source`` (passed as an ARGUMENT — never written to the real module
    path), returning the parsed result dict or ``None`` on ANY failure.

    ``mode`` is ``"survive"`` (payload = the mined witnesses) or ``"value"`` (payload
    = the synthesized arg sources). Funnels through :func:`_run_node_probe`, so the
    run/parse/decline scaffolding is shared. Any subprocess error/crash/timeout, or a
    child that declines (``{ok:false}``), yields ``None`` (the caller then treats the
    mutant as un-evaluable — a conservative skip, never an unverified verdict)."""
    return _run_node_probe(project_root, _MUTANT_PROBE,
                           [mode, src_file, name, mutated_source, json.dumps(payload)])


def _mutant_survives_witnesses(project_root: Path, src_file: str, name: str,
                               mutated_source: str,
                               witnesses: list[JsWitness]) -> bool:
    """``True`` iff EVERY mined witness STILL matches on ``mutated_source`` — i.e. the
    existing test is BLIND to this mutant (a SURVIVOR).

    Runs :data:`_MUTANT_PROBE` in ``survive`` mode: the child evaluates ``fn(args)``
    against each witness's ``expected`` (canonically, order-insensitively). A mutant
    that changes ANY witness is CAUGHT (returns ``False``); a mutant that cannot be
    transpiled/run, or whose witness value is non-serialisable, yields ``None`` from
    the probe and is treated as NOT a survivor (conservative — never strengthen
    against a mutant we could not actually evaluate)."""
    payload = [{"args": list(w.args), "expected": w.expected} for w in witnesses]
    result = _run_mutant_probe(project_root, src_file, name, mutated_source,
                               "survive", payload)
    if result is None:
        return False  # un-evaluable mutant -> not a survivor (conservative)
    return bool(result.get("survives"))


def _mutant_value(project_root: Path, src_file: str, name: str,
                  mutated_source: str, arg_sources: list[str]) -> str | None:
    """The mutant's canonical ``JSON.stringify`` on ``arg_sources``, or ``None`` when
    the mutant cannot be evaluated / returns a non-serialisable value.

    Runs :data:`_MUTANT_PROBE` in ``value`` mode. Used ONLY to confirm a survivor
    DIVERGES from the real function on a synthesized input (so the kept assertion
    provably kills it). A ``None`` means no honest divergence can be proven here, so
    the assertion is declined."""
    result = _run_mutant_probe(project_root, src_file, name, mutated_source,
                               "value", list(arg_sources))
    if result is None:
        return None
    captured = result.get("json")
    return captured if isinstance(captured, str) else None


# The REAL-value capture probe (a CANONICAL twin of js-cover-gaps' ``_CAPTURE_PROBE``)
# — reads the REAL on-disk source, calls fn(argSources), and prints the canonical
# (key-sorted) JSON so the value compares order-insensitively to the mutant's. The
# env-reproducibility gate compares the in-process baseline to the per-axis re-capture
# byte-for-byte; both go through THIS canonicalisation, so a key reorder is not a
# divergence. argv: source file, function name, JSON array of arg-source strings.
_REAL_CANON_PROBE = r"""
"use strict";
const fs = require("fs");
const path = require("path");
const ts = require("typescript");
const srcFile = process.argv[1];
const name = process.argv[2];
const argSources = JSON.parse(process.argv[3]);
// `cleanup` runs before EVERY exit (process.exit skips `finally`), so the transpiled
// sibling temp file is never left in the real source dir.
let tmpFile = null;
function cleanup() { if (tmpFile) { try { fs.unlinkSync(tmpFile); } catch (e) {} tmpFile = null; } }
function emit(o) { cleanup(); process.stdout.write(JSON.stringify(o)); process.exit(0); }
function decline() { emit({ ok: false }); }
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
function canon(v) {
  if (!isSoundValue(v, [])) return null;
  function norm(x) {
    if (Array.isArray(x)) return x.map(norm);
    if (x && typeof x === "object") {
      const o = {};
      for (const k of Object.keys(x).sort()) o[k] = norm(x[k]);
      return o;
    }
    return x;
  }
  try { return JSON.stringify(norm(v)); } catch (e) { return null; }
}
try {
  const source = fs.readFileSync(srcFile, "utf8");
  const out = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2019, esModuleInterop: true },
    fileName: srcFile, reportDiagnostics: false,
  });
  const dir = path.resolve(path.dirname(srcFile));
  tmpFile = path.join(dir, ".apex_real_canon_" + process.pid + ".js");
  fs.writeFileSync(tmpFile, out.outputText, "utf8");
  const mod = require(tmpFile);
  const fn = mod && mod[name];
  if (typeof fn !== "function") decline();
  const value = (new Function("fn", "return fn(" + argSources.join(", ") + ");"))(fn);
  const c = canon(value);
  if (c === null) decline();
  emit({ ok: true, json: c });
} catch (e) {
  decline();
} finally {
  cleanup();
}
"""


def _capture_real_canon(project_root: Path, src_file: str, name: str,
                        arg_sources: list[str]) -> str | None:
    """The REAL function's canonical (key-sorted) ``JSON.stringify`` on
    ``arg_sources`` read off the on-disk source, or ``None`` on any decline.

    The baseline the env-reproducibility gate re-validates and the asserted value the
    landed test pins. Canonical so it compares order-insensitively to the mutant's
    output (a key reorder is not a divergence). Funnels through
    :func:`_run_node_probe`, so the run/parse/decline scaffolding is shared."""
    result = _run_node_probe(project_root, _REAL_CANON_PROBE,
                             [src_file, name, json.dumps(arg_sources)])
    if result is None:
        return None
    captured = result.get("json")
    return captured if isinstance(captured, str) else None


def _killing_oracle(project_root: Path, module_rel: str, target: JsCoverTarget,
                    arg_sources: list[str], source: str,
                    survivors: list[JsMutant]) -> str | None:
    """The REAL canonical output to pin for ``target`` on ``arg_sources``, IFF it
    kills at least one survivor and survives the env-reproducibility gate — else
    ``None`` (no honest killing assertion on this input).

    The sound landing (mirrors the Python ``_killing_assertion`` double gate, but the
    mutant comes from the MINED-witness survivor set, not a per-mutant suite run):

    * capture the REAL function's canonical output once
      (:func:`_capture_real_canon`); decline if the call throws / the value is
      non-serialisable;
    * require the value to survive the ENV-REPRODUCIBILITY re-capture gate (varied
      cwd/HOME/TZ/TMPDIR + a wall-clock gap — :func:`_env_is_reproducible`), so a
      flaky/clock/env value is never pinned (the js-cover-gaps soundness guarantee);
    * require at least one survivor to DIVERGE on this input (real != mutant —
      :func:`_mutant_value`), proving the assertion actually KILLS a mutant the mined
      witnesses miss. An input on which every survivor agrees would add no signal.

    The asserted value is the REAL output, never fabricated. Returns the canonical
    JSON string to pin, or ``None`` to keep searching / refuse."""
    src_file = str((project_root / module_rel).resolve())
    real = _capture_real_canon(project_root, src_file, target.name, arg_sources)
    if real is None:
        return None  # call threw / non-serialisable -> no oracle on this input
    # The kill proof FIRST (cheap): at least one survivor must diverge from the real
    # output on this input. We check divergence BEFORE the (subprocess-heavy, >1s
    # wall-clock) env gate so the gate runs at most ONCE — on a genuinely killing
    # input — rather than for every non-killing probe.
    if not _kills_a_survivor(project_root, src_file, target.name, source,
                             arg_sources, real, survivors):
        return None  # no survivor diverges on this input -> add no signal, keep going
    # Only now gate the killing value for env-reproducibility (REUSED from
    # js-cover-gaps): it compares the canonical baseline to the per-axis canonical
    # re-capture + a wall-clock gap, so a stable value passes and a clock/env-fragile
    # one is refused. The asserted value is the REAL output, never fabricated.
    if not _env_is_reproducible(project_root, src_file, target.name, arg_sources, real):
        return None  # env/clock-fragile -> would go RED elsewhere -> refuse
    return real


def _kills_a_survivor(project_root: Path, src_file: str, name: str, source: str,
                      arg_sources: list[str], real: str,
                      survivors: list[JsMutant]) -> bool:
    """``True`` iff at least one survivor's output on ``arg_sources`` DIVERGES from the
    real output ``real`` — i.e. ``expect(fn(input)).toEqual(real)`` would FAIL on that
    mutant (it provably kills it).

    A survivor whose span is stale, or that cannot be evaluated on this input, is not
    a proven kill here (skipped). The comparison is on the CANONICAL (key-sorted) JSON
    of both, so a property reorder is not a divergence."""
    for mutant in survivors:
        mutated_source = _apply_mutant(source, mutant)
        if mutated_source is None:
            continue  # stale span -> cannot build this mutant -> skip
        mval = _mutant_value(project_root, src_file, name, mutated_source, arg_sources)
        if mval is None:
            continue  # mutant un-evaluable on this input -> not a proven kill here
        if mval != real:
            return True  # real != mutant -> this assertion KILLS the survivor
    return False


def _strengthen_target(project_root: Path, module_rel: str, target: JsCoverTarget,
                       source: str, locate_test) -> tuple[str, list[str], str] | None:
    """``(name, arg_sources, captured)`` for a single landable killing assertion on
    ``target``, or ``None`` when the target offers none (an honest refusal).

    The per-function spine: REFUSE unless the target is pure, in the sound input
    slice, has exactly one linked jest test, mines >=1 witness, and that test is
    GREEN on the real code (so its witnesses can be trusted). Then seed the mutant
    catalog, keep the SURVIVORS (every mined witness still matches — the existing
    test is blind), and synthesize a single env-gated killing assertion against the
    survivor set. ``None`` at any unmet gate — never a fabricated or unverified
    assertion."""
    if not target.pure:
        return None  # the AST flaky-test pre-filter refused it
    # The sound-slice gate (the SAME ceiling js-cover-gaps enforces): every param must
    # be zero-arg / typed-primitive / literal-defaulted, else refuse. ``_synth_args``
    # is the decidable-slice oracle; the richer per-input search uses ``_probe_inputs``.
    if _synth_args(target) is None:
        return None  # an un-synthesizable param -> outside the sound input slice
    test_rel = locate_test(target.name)
    if test_rel is None:
        return None  # no single linked jest test -> js-cover-gaps' lane, not ours
    witnesses = mine_witnesses(project_root, test_rel, target.name)
    if not witnesses:
        return None  # no mineable witness -> nothing to strengthen against
    src_file = str((project_root / module_rel).resolve())
    # The existing test's witnesses must be GREEN on the REAL code, or they cannot be
    # trusted as the survival oracle. A witness that does NOT match the real function
    # is a RED/stale test -> refuse (the JS image of strengthen-tests' baseline_ok).
    if not _witnesses_green_on_real(project_root, src_file, target.name, source,
                                    witnesses):
        return None
    mutants = _driver_mutants(project_root, module_rel, target.name)
    if not mutants:
        return None  # no seedable mutant -> nothing to strengthen
    survivors = [m for m in mutants
                 if _is_survivor(project_root, src_file, target.name, source, m,
                                 witnesses)]
    if not survivors:
        return None  # every mutant caught -> well-tested -> the common no-op
    # Search the deterministic probe inputs IN FIXED ORDER for the FIRST input where
    # the real output is env-reproducible AND diverges from a survivor (it kills it).
    # The body's own integer literals widen each number param's pool so a boundary /
    # numeric mutant (which only diverges at its constant) becomes distinguishable.
    hints = _numeric_hints(mutants)
    for arg_sources in _probe_inputs(target, hints):
        captured = _killing_oracle(project_root, module_rel, target, arg_sources,
                                   source, survivors)
        if captured is not None:
            return target.name, arg_sources, captured
    return None  # no env-gated input kills a survivor -> refuse (never fake-green)


def _is_survivor(project_root: Path, src_file: str, name: str, source: str,
                 mutant: JsMutant, witnesses: list[JsWitness]) -> bool:
    """``True`` iff ``mutant`` is a SURVIVOR of the mined witnesses — every witness
    still matches on the mutated source (the existing test is blind to it).

    Builds the mutated source IN MEMORY (:func:`_apply_mutant`; ``False`` if the span
    is stale) and runs the survival probe. A mutant the witnesses catch, or one that
    cannot be evaluated, is NOT a survivor (conservative)."""
    mutated_source = _apply_mutant(source, mutant)
    if mutated_source is None:
        return False  # stale span -> cannot build the mutant -> skip
    return _mutant_survives_witnesses(project_root, src_file, name, mutated_source,
                                      witnesses)


def _witnesses_green_on_real(project_root: Path, src_file: str, name: str,
                             source: str, witnesses: list[JsWitness]) -> bool:
    """``True`` iff EVERY mined witness matches the REAL function — the baseline-OK
    gate (the existing test is GREEN on the code it pins).

    Reuses the survival probe against the UNMUTATED source: a witness that does not
    match the real function is a RED/stale test whose witnesses cannot be trusted as
    the survival oracle, so we refuse (never strengthen against an unsound baseline).
    A probe failure (un-evaluable / non-serialisable witness) is also a refusal."""
    return _mutant_survives_witnesses(project_root, src_file, name, source, witnesses)


# The Apex-OWNED test-file infix — collision-proof and unmistakably Apex-owned, so it
# shares a basename with NO buyer test (the JS image of strengthen_tests'
# ``_apex_mutants`` suffix). The buyer's existing ``<stem>.test.<ext>`` is NEVER
# edited; this NEW sibling carries the strengthening assertions.
_GENERATED_INFIX = "apex-mutants.cover.test"


def _test_rel_for(module_rel: str) -> str:
    """The deterministic NEW Apex-owned jest test path for ``module_rel`` — a sibling
    ``<dir>/__tests__/<stem>.apex-mutants.cover.test.<ext>`` (jest's default
    ``__tests__`` discovery; the ``apex-mutants.cover.test`` infix is collision-proof
    and never collides with the buyer's own ``<stem>.test`` / the js-cover-gaps
    ``<stem>.cover.test``). The extension follows the source so jest's TS transform
    applies. Pure path computation."""
    src = Path(module_rel)
    ext = src.suffix.lstrip(".") or "js"
    return (src.parent / "__tests__" / f"{src.stem}.{_GENERATED_INFIX}.{ext}").as_posix()


def _import_specifier(module_rel: str, test_rel: str) -> str:
    """The relative ``require`` specifier from ``test_rel`` to ``module_rel`` (no
    extension, POSIX, always ``./``-prefixed). Deterministic; a pure path computation,
    no filesystem touch. (The strengthen twin of js-cover-gaps' ``_import_specifier``;
    kept local so this module stays self-contained.)"""
    rel = os.path.relpath(Path(module_rel).with_suffix("").as_posix(),
                          Path(test_rel).parent.as_posix())
    spec = Path(rel).as_posix()
    return spec if spec.startswith((".", "/")) else "./" + spec


def _render(module_rel: str, test_rel: str, module_stem: str,
            oracles: list[tuple[str, list[str], str]]) -> str:
    """The deterministic Apex-owned jest test source pinning each killing assertion.

    Each oracle becomes ``expect(name(<args>)).toEqual(<captured>)`` (or
    ``toStrictEqual`` for an object/array return) — a true VALUE-ORACLE assertion that
    pins what the REAL function does on an input where a surviving mutant DIVERGED, so
    it KILLS that mutant (a blind spot the buyer's mined witnesses miss). The asserted
    value is the REAL captured output, never fabricated. Document order, no
    clock/random — same module -> byte-identical bytes. The buyer's own test file is
    NEVER referenced; this is a standalone Apex-owned sibling."""
    spec = _import_specifier(module_rel, test_rel)
    names = ", ".join(name for name, _args, _cap in oracles)
    lines = [
        "// Generated by Apex Orchestrator - jest mutant-killing assertions",
        f"// module: {module_rel}",
        "//",
        "// STRENGTHENS the module's EXISTING jest test: each assertion below pins the",
        "// REAL behaviour on an input where a single-token MUTANT survived the buyer's",
        "// MINED test witnesses (a real blind spot) yet DIVERGED from the real output —",
        "// so the assertion KILLS that mutant. The value is the function's OWN captured",
        "// return (sound by construction, env-reproducibility-gated). This is the",
        "// function's MINED-witness blind spot, NOT a full-mutation guarantee. The",
        "// buyer's own test file is never edited. Regenerate, do not hand-tune.",
        f'const {{ {names} }} = require("{spec}");',
        "",
    ]
    for name, args, captured in oracles:
        matcher = _matcher_for(captured)
        call = f"{name}({', '.join(args)})"
        lines += [
            f'test("{module_stem}: {name} mutant-killing characterization", () => {{',
            "  // Kills a mutant the buyer's mined witnesses miss: the captured real",
            "  // return pins behaviour the surviving mutant diverged from.",
            f"  expect({call}).{matcher}({captured});",
            "});",
            "",
        ]
    return "\n".join(lines)


def _prepare(root: Path, module_rel: str
             ) -> tuple[list[JsCoverTarget], str, str] | None:
    """The shared preamble for a strengthening run: ``(targets, test_rel, source)``,
    or ``None`` to refuse early.

    ``None`` when the module exposes no cover target, when Apex's OWN generated test
    path already exists (never clobber it), or when the source cannot be read. Folds
    the three early refusals into one helper so the entry point stays a clean
    target-loop (and so its statement shape is its OWN, not a structural twin of the
    js-cover-gaps entry point)."""
    targets = cover_targets(root, module_rel)
    if not targets:
        return None  # nothing exported/characterizable — honest no-op
    test_rel = _test_rel_for(module_rel)
    if (root / test_rel).exists():
        return None  # never clobber Apex's own generated strengthening test
    try:
        source = (root / module_rel).read_text(encoding="utf-8")
    except OSError:
        return None  # unreadable source — no-op
    return targets, test_rel, source


def generate_js_strengthen_test(project_root: str | Path, module_rel: str,
                                locate_test) -> JsStrengthenTest | None:
    """Synthesize an Apex-owned jest test STRENGTHENING ``module_rel``, or ``None``.

    Returns a :class:`JsStrengthenTest` to be landed by the objective, or ``None``
    when nothing is strengthenable:
      - the module exposes no landable target (no exported pure function with exactly
        one linked jest test, mineable witnesses, a green baseline, a surviving
        mutant, and an env-gated input that kills it);
      - the destination ``<dir>/__tests__/<stem>.apex-mutants.cover.test.<ext>``
        already exists (never clobber Apex's own generated test).

    ``locate_test`` is the caller-supplied linkage probe (the objective passes
    :func:`app.execution.lang.js_adapter._locate_test` bound to the project + file):
    given a function name it returns the single jest test that links it, or ``None``.
    This is the DISJOINTNESS key with js-cover-gaps — strengthen fires ONLY when a
    linked test exists; cover-gaps ONLY when ``locate_test`` is ``None``. Deterministic;
    the buyer's existing test is NEVER edited."""
    root = Path(project_root)
    prepared = _prepare(root, module_rel)
    if prepared is None:
        return None  # no targets / generated test exists / unreadable — honest no-op
    targets, test_rel, source = prepared

    oracles: list[tuple[str, list[str], str]] = []
    for target in targets:
        result = _strengthen_target(root, module_rel, target, source, locate_test)
        if result is not None:
            oracles.append(result)

    if not oracles:
        return None  # no surviving mutant killable with an honest oracle — no-op

    module_stem = Path(module_rel).stem
    content = _render(module_rel, test_rel, module_stem, oracles)
    return JsStrengthenTest(
        module_rel=module_rel,
        test_rel=test_rel,
        content=content,
        functions=[name for name, _args, _cap in oracles],
    )
