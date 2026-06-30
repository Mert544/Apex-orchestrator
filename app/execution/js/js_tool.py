"""Thin Python wrapper around the bundled ``ts_driver.js`` — the ONE place that
knows the node invocation for Apex's JS/TS support.

Every JS/TS parse/transform Apex does goes through this module: it builds a
:class:`CommandSpec` and runs it on the EXISTING :class:`CommandRunner` (so the
``node`` allow-list entry and the subprocess discipline are shared with the rest
of Apex), passing ``NODE_PATH`` so the driver's ``require("typescript")``
resolves to the globally-installed compiler regardless of the target project's
own ``node_modules``. The driver speaks canonical JSON on stdout and exits 2 on
REFUSE; a non-zero exit (refusal, missing node, or any error) is read
CONSERVATIVELY here as "no result", so an ambiguous file lands nothing rather
than guessing — the JS image of the Python path's refusal discipline.

Deterministic and offline: ``ts.createSourceFile`` is a pure function of the
bytes, the driver emits stable JSON, and no clock/random is consulted, so the
same project yields byte-identical results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.runtime.command_runner import CommandResult, CommandRunner, CommandSpec

__all__ = [
    "JsStub",
    "JsWitness",
    "JsDocTarget",
    "JsWireTarget",
    "JsCoverParam",
    "JsCoverTarget",
    "DRIVER",
    "global_node_modules",
    "scan_stubs",
    "mine_witnesses",
    "mine_jsdoc_witnesses",
    "fill_body",
    "doc_targets",
    "exported_names",
    "reparse_exports_identical",
    "wire_targets",
    "all_exported_names",
    "reparse_exports_superset",
    "cover_targets",
]

# The bundled driver checked into this package — never a string Apex generates.
DRIVER = Path(__file__).with_name("ts_driver.js")


@dataclass(frozen=True)
class JsStub:
    """One top-level ``throw``-stub function the driver found, with the exact
    UTF-16 code-unit span of its body block (``body_start`` = the ``{``,
    ``body_end`` = just past the ``}``) so a fill is a precise splice, not an
    unparse. The driver emits these as UTF-16 code units (the SourceFile text's
    native index); the Python splice re-indexes them to code points first."""

    name: str
    params: tuple[str, ...]
    body_start: int
    body_end: int


@dataclass(frozen=True)
class JsWitness:
    """One ``expect(name(args)).matcher(expected)`` example a jest test pins, as
    the literal source bytes of the arguments and the expected value — the
    ``(args, expected)`` tuple the synthesiser's gate and constant floor use."""

    args: tuple[str, ...]
    expected: str


@dataclass(frozen=True)
class JsDocTarget:
    """One EXPORTED, JSDoc-less function/const-arrow the driver found, with the
    proven AST facts a minimal JSDoc is built from: its declared parameter
    ``names`` (in order), the per-param declared ``param_types`` read VERBATIM off
    each TS annotation (one entry per param, parallel to ``params``; an entry is
    ``None`` when that param carries no annotation — js-document-param-types
    surfaces the typed ones, document-export-jsdoc ignores the field), the
    ``return_type`` text read VERBATIM off a TS return annotation (``None`` for
    plain JS / no annotation — the document-export-jsdoc honesty gate refuses
    those, a name+param-only JSDoc restating the signature adds nothing), the
    ``returns_inferred`` type PROVEN from the body's OWN literal ``return``
    statements (``"boolean"``/``"string"``/``"number"``/``"Array"``/``"Object"``/a
    constructor name), or ``None`` when ANY return is non-literal / void / ``null`` /
    heterogeneous; js-document-returns-inferred surfaces this for PLAIN-JS exports a
    declared annotation does not cover and the other JSDoc objectives ignore it. It
    is DISJOINT from ``return_type`` by construction — that is the DECLARED TS
    annotation (document-export-jsdoc's surface), this is inferred only where none is
    declared, so js-document-returns-inferred fires ONLY when ``return_type is None``.
    The ``throws_types`` — the DISTINCT thrown constructor names of the body in source
    order, read VERBATIM off each literal ``throw new <Identifier>(...)`` node, or
    ``None`` when ANY throw is an unprovable shape (a variable / call / member-ctor /
    re-throw); document-raises-jsdoc surfaces this as the ``@throws {Ctor}`` set and
    the other JSDoc objectives ignore it (exactly as document-export-jsdoc ignores
    ``param_types``), and the UTF-16-code-unit ``insert_offset`` of the statement
    start (BEFORE any ``export`` keyword, so the JSDoc splices in as leading trivia;
    re-indexed to a code-point index by the Python splice)."""

    name: str
    params: tuple[str, ...]
    param_types: tuple[str | None, ...]
    return_type: str | None
    returns_inferred: str | None
    throws_types: tuple[str, ...] | None
    insert_offset: int


@dataclass(frozen=True)
class JsWireTarget:
    """One DEFINED-but-unexported top-level PUBLIC function/const-arrow the driver
    found — the missing-export target the js-wire-exports objective lands an ESM
    ``export`` keyword for. ``kind`` is ``"function"`` or ``"const"`` (advisory; the
    splice just prepends ``export ``), and ``insert_offset`` is the UTF-16 code-unit
    offset of the statement start, where prepending ``export `` publishes the
    already-defined binding (a pure export-surface GROW; the Python splice re-indexes
    it to a code-point index first). The driver only emits these for clean ESM
    modules — a file carrying any ``module.exports``/``export default``/``export =``
    yields none (the deferred surface)."""

    name: str
    kind: str
    insert_offset: int


@dataclass(frozen=True)
class JsCoverParam:
    """One parameter of a js-cover-gaps CHARACTERIZATION target: its ``name``, the
    verbatim TS type annotation ``type`` (or ``None`` when the param carries no
    annotation), and the verbatim literal default ``default_text`` (or ``None`` when
    the param has no default or a non-literal default). The input synthesiser reads
    these to build a SOUND sample argument (a primitive type maps to a fixed zero
    sample; a literal default is re-emitted verbatim), and REFUSES the whole target
    when a param is neither typed-primitive nor literal-defaulted (no LLM-free basis
    for an untyped, non-defaulted param)."""

    name: str
    type: str | None
    default_text: str | None


@dataclass(frozen=True)
class JsCoverTarget:
    """One EXPORTED, public, undecorated, NON-async, NON-generator function/const-
    arrow the driver found as a js-cover-gaps characterization candidate: its
    ``name``, the ordered ``params`` (:class:`JsCoverParam`), the ``pure`` flag (the
    driver's AST forbidden-call/free-identifier scan — the cheap FIRST flaky-test
    guard, with the Python env-reproducibility re-capture gate as the load-bearing
    second), and the ``export_kind`` addressing (``"named"`` — reached as
    ``mod.name`` after transpile/require). The Python side decides the SOUND input
    slice from ``params`` and refuses an impure target outright."""

    name: str
    params: tuple[JsCoverParam, ...]
    pure: bool
    export_kind: str


@lru_cache(maxsize=1)
def global_node_modules() -> str:
    """``npm root -g`` — the global ``node_modules`` dir holding ``typescript`` —
    so the driver's ``require("typescript")`` resolves. Memoized (a pure function
    of the install) and conservative: an empty string when ``npm`` cannot answer,
    which simply leaves ``NODE_PATH`` unset (the driver then refuses, landing
    nothing)."""
    try:
        res = CommandRunner().run(CommandSpec(command=["npm", "root", "-g"]))
    except Exception:
        return ""
    return res.stdout.strip() if res.ok else ""


def _run_driver(args: list[str], cwd: Path) -> CommandResult | None:
    """Spawn ``node ts_driver.js <args>`` with ``NODE_PATH`` set, or ``None`` when
    the runner refuses/raises. The single seam every driver call funnels through."""
    env = {}
    node_path = global_node_modules()
    if node_path:
        env["NODE_PATH"] = node_path
    try:
        return CommandRunner().run(CommandSpec(
            command=["node", str(DRIVER), *args], cwd=cwd, env=env or None))
    except Exception:
        return None


def _driver_json(args: list[str], cwd: Path):
    """The parsed JSON the driver printed for ``args``, or ``None`` on ANY failure
    (refusal/exit-2, missing node, unparseable output). Conservative by design —
    a ``None`` is read by callers as "refuse / nothing to do"."""
    res = _run_driver(args, cwd)
    if res is None or not res.ok:
        return None
    try:
        return json.loads(res.stdout)
    except (ValueError, TypeError):
        return None


def scan_stubs(root: Path, rel: str) -> list[JsStub]:
    """The top-level ``throw``-stub functions in ``root/rel`` (empty on refuse).

    A file that does not parse, has no fillable stub, or that the driver declines
    yields ``[]`` — nothing to do, never a guess."""
    data = _driver_json(["scan", str(root / rel)], root)
    if not isinstance(data, list):
        return []
    return [JsStub(name=d["name"], params=tuple(d["params"]),
                   body_start=d["bodyStart"], body_end=d["bodyEnd"])
            for d in data]


def mine_witnesses(root: Path, test_rel: str, name: str) -> list[JsWitness]:
    """The witness tuples the jest test ``root/test_rel`` pins on ``name`` (empty
    when none / on refuse). Deterministic source order, as the driver emits."""
    data = _driver_json(["mine", str(root / test_rel), name], root)
    if not isinstance(data, list):
        return []
    return [JsWitness(args=tuple(d["args"]), expected=d["expected"]) for d in data]


def mine_jsdoc_witnesses(root: Path, rel: str, name: str) -> list[JsWitness]:
    """The witness tuples the stub ``name``'s OWN leading JSDoc ``@example`` block
    pins in ``root/rel`` (empty when none / on refuse).

    The SAME ``(args, expected)`` shape :func:`mine_witnesses` returns, but mined
    from the stub's docstring contract instead of a jest test — the
    ``js-implement-from-jsdoc`` objective's witness source. Deterministic source
    order, exactly as the driver's ``mine-jsdoc`` emits; a file that does not
    parse, a stub with no JSDoc, or a JSDoc with no usable example yields ``[]``."""
    data = _driver_json(["mine-jsdoc", str(root / rel), name], root)
    if not isinstance(data, list):
        return []
    return [JsWitness(args=tuple(d["args"]), expected=d["expected"]) for d in data]


def fill_body(root: Path, rel: str, name: str, body: str) -> bool:
    """Splice ``{ <body> }`` over the body block of the single stub ``name`` in
    ``root/rel``, writing the file in place. ``True`` on success, ``False`` when
    the driver refused (``name`` not a unique fillable stub) so nothing changed.

    This is the in-place editing primitive the synthesiser uses against a
    THROWAWAY copy while probing templates; the LANDED change is carried as a
    :class:`RenamePlan` and applied by the gated/rollback writer, never here."""
    res = _run_driver(["fill", str(root / rel), name, body], root)
    return bool(res is not None and res.ok)


def doc_targets(root: Path, rel: str) -> list[JsDocTarget]:
    """The EXPORTED, JSDoc-less function/const-arrow targets in ``root/rel`` (empty
    on refuse). Conservative: a file that does not parse, has no such target, or
    that the driver declines yields ``[]`` — nothing to document, never a guess.

    Deterministic source order, exactly as the driver's ``doc-targets`` emits."""
    data = _driver_json(["doc-targets", str(root / rel)], root)
    if not isinstance(data, list):
        return []
    return [JsDocTarget(name=d["name"], params=tuple(d["params"]),
                        param_types=tuple(d["paramTypes"]),
                        return_type=d["returnType"],
                        returns_inferred=d["returnsInferred"],
                        throws_types=(tuple(d["throwsTypes"])
                                      if d["throwsTypes"] is not None else None),
                        insert_offset=d["insertOffset"])
            for d in data]


def exported_names(root: Path, rel: str) -> frozenset[str] | None:
    """The set of EXPORTED function/const-arrow names ``root/rel`` declares, or
    ``None`` when the driver could not parse it (its conservative-refuse path).

    This is the behaviour-identical oracle's witness — see
    :func:`reparse_exports_identical`."""
    data = _driver_json(["doc-verify", str(root / rel)], root)
    if not isinstance(data, dict) or not isinstance(data.get("names"), list):
        return None
    return frozenset(data["names"])


def reparse_exports_identical(root: Path, rel: str, new_source: str) -> bool:
    """The behaviour-identical oracle for a JSDoc splice: ``True`` iff ``new_source``
    (the JSDoc-spliced bytes of ``root/rel``) RE-PARSES cleanly AND carries the
    EXACT same exported-name set as the on-disk original.

    A JSDoc is leading trivia — it changes ZERO runtime bytes — so the exported
    surface is unchanged BY CONSTRUCTION; this check proves the splice did not
    corrupt the file (a broken splice would fail to re-parse, the driver would
    exit 2, and ``exported_names`` would return ``None``). The probe writes
    ``new_source`` to a THROWAWAY file (the real tree is never touched here) and
    asks the driver for its exported names. Conservative: any driver failure (a
    parse diagnostic, missing node) yields ``None`` and we refuse (return
    ``False``) rather than land an unverified change."""
    import tempfile

    before = exported_names(root, rel)
    if before is None:
        return False
    suffix = Path(rel).suffix or ".js"
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / ("probe" + suffix)
        probe.write_text(new_source, encoding="utf-8")
        after = exported_names(Path(tmp), probe.name)
    return after is not None and after == before


def wire_targets(root: Path, rel: str) -> list[JsWireTarget]:
    """The DEFINED-but-unexported top-level PUBLIC function/const-arrow targets in
    ``root/rel`` (empty on refuse). Conservative: a file that does not parse, has no
    such target, or that carries any ``module.exports``/``export default``/
    ``export =`` (the deferred CJS/default surface) yields ``[]`` — nothing to wire,
    never a guess.

    Deterministic source order, exactly as the driver's ``wire-targets`` emits."""
    data = _driver_json(["wire-targets", str(root / rel)], root)
    if not isinstance(data, list):
        return []
    return [JsWireTarget(name=d["name"], kind=d["kind"], insert_offset=d["insertOffset"])
            for d in data]


def all_exported_names(root: Path, rel: str) -> frozenset[str] | None:
    """The FULL set of exported names ``root/rel`` declares — ESM ``export``,
    ``export {`` named bindings, and CJS ``module.exports.NAME``/``exports.NAME`` —
    or ``None`` when the driver could not parse it (its conservative-refuse path).

    This is the wire oracle's witness (the superset analogue of
    :func:`exported_names`): see :func:`reparse_exports_superset`."""
    data = _driver_json(["wire-verify", str(root / rel)], root)
    if not isinstance(data, dict) or not isinstance(data.get("names"), list):
        return None
    return frozenset(data["names"])


def reparse_exports_superset(root: Path, rel: str, new_source: str,
                             added: frozenset[str] | set[str]) -> bool:
    """The wire oracle for an ESM ``export``-keyword splice: ``True`` iff
    ``new_source`` (the spliced bytes of ``root/rel``) RE-PARSES cleanly AND carries
    EXACTLY the on-disk original's full exported-name set UNION ``added``.

    A pure export-surface GROW only PUBLISHES already-defined bindings; this check
    proves the splice added precisely the ``added`` names and corrupted nothing (a
    broken splice would fail to re-parse, the driver would exit 2, and
    :func:`all_exported_names` would return ``None``; a stray extra/missing export
    would make the set differ). The probe writes ``new_source`` to a THROWAWAY file
    (the real tree is never touched here) and asks the driver for its full exported
    set. Conservative: any driver failure (a parse diagnostic, missing node) yields
    ``None`` and we refuse (return ``False``) rather than land an unverified
    change. The strict ``document_export_jsdoc`` re-parse oracle with ``==``
    relaxed to ``== before | added`` (we INTEND to grow the surface by ``added``)."""
    import tempfile

    before = all_exported_names(root, rel)
    if before is None:
        return False
    suffix = Path(rel).suffix or ".js"
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / ("probe" + suffix)
        probe.write_text(new_source, encoding="utf-8")
        after = all_exported_names(Path(tmp), probe.name)
    return after is not None and after == before | frozenset(added)


def cover_targets(root: Path, rel: str) -> list[JsCoverTarget]:
    """The EXPORTED, public, undecorated, non-async, non-generator function/const-
    arrow CHARACTERIZATION targets in ``root/rel`` (empty on refuse).

    Conservative: a file that does not parse, has no such target, or that the driver
    declines yields ``[]`` — nothing to characterize, never a guess. Deterministic
    source order, exactly as the driver's ``cover-targets`` emits. Each target
    carries its parameter infos (name + verbatim type + verbatim literal default), a
    ``pure`` flag (the driver's forbidden-call/free-identifier scan), and the export
    addressing — the facts the js-cover-gaps input synthesiser + oracle need."""
    data = _driver_json(["cover-targets", str(root / rel)], root)
    if not isinstance(data, list):
        return []
    return [JsCoverTarget(
        name=d["name"],
        params=tuple(JsCoverParam(name=p["name"], type=p["type"],
                                  default_text=p["defaultText"])
                     for p in d["params"]),
        pure=bool(d["pure"]),
        export_kind=d["exportKind"],
    ) for d in data]
