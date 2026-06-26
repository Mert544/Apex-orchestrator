"""``JavaScriptAdapter`` — the JS/TS realisation of the :class:`LanguageAdapter`
seam, and the canonical home of the JS develop helpers extracted from
:mod:`app.execution.objectives.js_tdd_implement`.

This module owns the JS-specific machinery the ``js-tdd-implement`` objective
once held inline: the source-suffix set, the jest test-file regex, the
skip-dirs + ``node_modules`` walk, the deterministic test-linkage LOCATE, the
plan builder, and the byte-span splice. They live here now so a SECOND adapter
makes the Protocol non-vacuous and a future ``<lang>-tdd-implement`` clone
reuses the seam instead of re-copying the walk/suffix/linkage. The objective
module re-exports the public names as thin forwarders, so importers and the
registry are unaffected and the 507-line behaviour pin stays green.

:class:`JavaScriptAdapter` is a THIN re-expression of those same functions —
``owns`` IS :func:`is_js_source`, ``parse``/``locate`` read the byte spans
:func:`app.execution.js.js_tool.scan_stubs` already returns, ``apply`` IS the
:func:`_splice_body` byte splice, and ``reparses`` reuses the driver's
exit-2-means-does-not-parse contract via ``scan_stubs``'s conservative-None
path. Because every adapter method is the same predicate/slice the objective
called inline, dispatch through the adapter is byte-identical.

Deterministic (fixed regexes, sorted walk, byte-span splice — no clock/random),
offline, zero-token, exactly as the inline helpers were.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.engine.skip_dirs import SKIPPED_DIRS
from app.execution.cross_file_rename import RenamePlan
from app.execution.js.js_jsdoc_synthesis import synthesize_js_jsdoc_body
from app.execution.js.js_stub_synthesis import synthesize_js_body
from app.execution.js.js_tool import JsStub, mine_jsdoc_witnesses, scan_stubs
from app.execution.lang.adapter import (
    Edit,
    ParseTree,
    Target,
    TargetQuery,
)
from app.skills.execution.run_tests import RunTestsSkill

__all__ = [
    "JavaScriptAdapter",
    "JsMissingBody",
    "JsJsdocStub",
    "plan_js_tdd_implement",
    "plan_js_implement_from_jsdoc",
    "detect_js_stubs",
    "detect_js_jsdoc_stubs",
    "is_js_source",
    "fitness",
    "jsdoc_fitness",
    "landable",
    "jsdoc_landable",
    "JS_SOURCE_SUFFIXES",
]

# Source extensions the TS Compiler API parses as JS/TS. ANY other path is REFUSED
# — this is exactly what makes the objective a clean no-op on a Python (or any
# non-JS) file, so it never disturbs the Python path nor the soundness corpus.
_JS_SOURCE_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"})

# Public alias of the suffix set, so the adapter can expose the gate it enforces
# without leaking a private name.
JS_SOURCE_SUFFIXES = _JS_SOURCE_SUFFIXES

# A jest TEST file (also a refused WRITE target): a ``*.test.*`` / ``*.spec.*``
# basename, or any file under a ``__tests__`` directory. Mirrors jest's own
# default discovery so the test that pins a stub is found and never overwritten.
_TEST_BASENAME_RE = re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$", re.IGNORECASE)


def is_js_source(rel: str) -> bool:
    """True when ``rel`` is a NON-TEST JS/TS source file this objective may fill.

    A file whose suffix is not a JS/TS source extension is rejected (the no-op on
    a ``.py`` / any non-JS file), and a jest test/fixture file is rejected as a
    WRITE target (Apex never edits the suite it is gated by). Pure, no filesystem
    touch."""
    p = rel.replace("\\", "/")
    if Path(p).suffix.lower() not in _JS_SOURCE_SUFFIXES:
        return False
    if _is_js_test(p):
        return False
    return True


def _is_js_test(rel: str) -> bool:
    """True when ``rel`` is a jest test file (``*.test.*`` / ``*.spec.*`` basename,
    or under a ``__tests__`` dir)."""
    p = rel.replace("\\", "/")
    if "__tests__/" in p or p.startswith("__tests__/"):
        return True
    return bool(_TEST_BASENAME_RE.search(Path(p).name))


@dataclass(frozen=True)
class JsMissingBody:
    """One deterministically-located stub a RED jest test demands a body for:
    the ``stub`` (name + params + body span), its source ``file_rel``, and the
    single ``test_rel`` that pins it (located from import + call linkage)."""

    stub: JsStub
    file_rel: str
    test_rel: str


@dataclass(frozen=True)
class JsJsdocStub:
    """One deterministically-located stub whose contract lives ONLY in its own
    JSDoc ``@example`` block and that NO jest test references — the DISJOINT
    sibling of :class:`JsMissingBody` (which requires a LINKING jest test; this
    requires the inverse). The ``stub`` (name + params + body span) and its source
    ``file_rel``; the witnesses are mined from the stub's docstring, not a test."""

    stub: JsStub
    file_rel: str


_ADAPTER_SINGLETON: JavaScriptAdapter | None = None


def _adapter() -> JavaScriptAdapter:
    """The module's :class:`JavaScriptAdapter` singleton — the seam the plan/detect
    helpers dispatch their gate/locate/splice through. Built once on first use
    (the class is defined below); a single instance keeps the helpers and the
    registered adapter the SAME object's behaviour."""
    global _ADAPTER_SINGLETON
    if _ADAPTER_SINGLETON is None:
        _ADAPTER_SINGLETON = JavaScriptAdapter()
    return _ADAPTER_SINGLETON


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _walk_files(root: Path, suffixes: frozenset[str]) -> list[str]:
    """The project's own files with one of ``suffixes`` (rel paths, sorted,
    canonical skip-dirs — ``node_modules``/caches/etc. — excluded). Deterministic."""
    out: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in SKIPPED_DIRS or part == "node_modules"
               for part in Path(rel).parts):
            continue
        out.append(rel)
    return out


def _js_test_files(root: Path) -> list[str]:
    """The project's own jest test files (rel paths, sorted)."""
    return [rel for rel in _walk_files(root, _JS_SOURCE_SUFFIXES) if _is_js_test(rel)]


def _module_stem(file_rel: str) -> str:
    """The basename a ``require``/``import`` would name this module by, sans
    extension — e.g. ``src/math.js`` -> ``math`` — so a test's import can be
    matched without resolving the full module path."""
    return Path(file_rel).stem


def _test_links_stub(text: str, stem: str, name: str) -> bool:
    """True when test source ``text`` both IMPORTS the module ``stem`` (a
    ``require("...stem")`` or ``from "...stem"`` / ``import "...stem"``) AND
    references the symbol ``name`` (called as ``name(...)`` or ``x.name(...)``).

    The deterministic, AST-free linkage that pins which test exercises a stub —
    the JS image of the Python ``_test_imports_module`` + call-site check. Word
    boundaries keep ``add`` from matching ``addmore``."""
    imports = re.search(r"""(?:require|from|import)\b[^\n]*['"][^'"\n]*""" + re.escape(stem)
                        + r"""(?:\.[cm]?[jt]sx?)?['"]""", text)
    if not imports:
        return False
    return bool(re.search(r"(?<![\w$])" + re.escape(name) + r"\s*\(", text))


def _locate_test(root: Path, file_rel: str, name: str) -> str | None:
    """The single jest test that pins stub ``name`` of ``file_rel``, or ``None``.

    A test qualifies when it imports the stub's module AND references the name
    (:func:`_test_links_stub`). Exactly one qualifying test is required — zero or
    many is ambiguous and REFUSED (a non-guessing objective never picks
    arbitrarily). Deterministic: tests scanned in sorted order."""
    stem = _module_stem(file_rel)
    matches = [test_rel for test_rel in _js_test_files(root)
               if _test_links_stub(_read(root / test_rel), stem, name)]
    if len(matches) == 1:
        return matches[0]
    return None


def _iter_own_stubs(root: Path):
    """Yield ``(file_rel, stub)`` for every top-level single-``throw`` stub in every
    own non-test JS/TS source under the single-``package.json`` root gate.

    The shared SCAN both detectors walk: REFUSES the whole project (yields nothing)
    unless a single ``package.json`` is at the root — the single-project gate, the
    JS analogue of one Python project root, and what makes the JS objectives a clean
    no-op on a Python (or any non-JS) tree. Deterministic: sources in sorted order
    (as :func:`_walk_files` emits), stubs in driver source order. The per-stub KEEP
    rule (a pinning jest test vs a JSDoc ``@example`` contract) is the caller's, so
    the two detectors share the walk without duplicating it."""
    if not (root / "package.json").exists():
        return
    adapter = _adapter()
    for file_rel in _walk_files(root, _JS_SOURCE_SUFFIXES):
        if not adapter.owns(file_rel):  # the file gate, via the adapter seam
            continue
        for stub in scan_stubs(root, file_rel):
            yield file_rel, stub


def detect_js_stubs(project_root: str | Path) -> list[JsMissingBody]:
    """Every deterministically-located JS/TS stub a RED jest test demands a body
    for, each pinned to its single test.

    REFUSES the whole project (returns ``[]``) unless a single ``package.json`` is
    at the root — the single-project gate, the JS analogue of one Python project
    root. For each own non-test JS/TS source, each top-level single-``throw`` stub
    that locates to exactly one pinning test is kept. Deterministic: sources and
    tests in sorted order."""
    root = Path(project_root)
    out: list[JsMissingBody] = []
    for file_rel, stub in _iter_own_stubs(root):
        test_rel = _locate_test(root, file_rel, stub.name)
        if test_rel is None:
            continue
        out.append(JsMissingBody(stub=stub, file_rel=file_rel, test_rel=test_rel))
    return out


def _read_plan_source(root: Path, file_rel: str) -> str | None:
    """The on-disk bytes of ``root/file_rel`` to land a body into, or ``None`` when
    it is a non-JS / test / fixture WRITE target (the :func:`is_js_source` file
    gate, via the adapter seam) or is unreadable/missing.

    The shared HEAD of every JS body-landing plan (``js-tdd-implement`` /
    ``js-implement-from-jsdoc``): the same owns-gate + read both perform before
    synthesising, so the no-op-on-``.py`` and unreadable-target refusals live in one
    place instead of being copied per objective."""
    if not _adapter().owns(file_rel):  # the file gate, via the adapter seam
        return None  # non-JS / test / fixture file — refuse (the no-op on .py)
    target = root / file_rel
    original = _read(target)
    if not original and not target.exists():
        return None  # unreadable / missing target — no-op
    return original


def _land_body(plan: RenamePlan, file_rel: str, original: str,
               stub: JsStub, body: str) -> RenamePlan:
    """Splice ``body`` into ``stub``'s body span of ``original`` and record the
    landing on ``plan`` (original for rollback, filled source, single-write edit
    count), or leave ``plan`` empty when the recorded span is stale / the splice is
    a no-op (refuse rather than corrupt the file).

    The shared TAIL of every JS body-landing plan: the same locate-via-the-seam ->
    apply -> record sequence both objectives perform once a body is synthesised, so
    the splice/record idiom lives in one helper rather than copied per objective."""
    adapter = _adapter()
    located = adapter.locate(adapter.parse(original), original,
                             TargetQuery(name=stub.name, extra={"stub": stub}))
    if located is None:
        return plan  # the recorded stub span is stale — refuse rather than corrupt
    filled = adapter.apply(original, located, Edit(body=body))
    if filled is None or filled == original:
        return plan  # the splice did not change the source — refuse
    plan.originals[file_rel] = original
    plan.new_contents[file_rel] = filled
    plan.edits_by_file[file_rel] = 1
    return plan


def plan_js_tdd_implement(project_root: str | Path, missing: JsMissingBody,
                          runner: RunTestsSkill | None = None) -> RenamePlan:
    """Build the synthesise-the-body plan for ONE located stub, or an empty no-op
    plan (an honest refusal).

    REFUSES a non-JS-source or test/fixture write target outright
    (:func:`is_js_source`), then delegates the body to
    :func:`synthesize_js_body` against the RED jest test as the spec. On success
    the plan lands the ONE changed source's new full text in ``new_contents``
    (original in ``originals``), so the gated/rollback writer runs the suite and
    restores it byte-for-byte on any regression. An empty plan means no fixed
    template flipped the test green — nothing is landed (never-fake-green)."""
    plan = RenamePlan(old=missing.file_rel, new="js-tdd-implement")
    root = Path(project_root)
    original = _read_plan_source(root, missing.file_rel)
    if original is None:
        return plan  # non-JS / test / fixture / unreadable — refuse
    runner = runner or RunTestsSkill()
    body = synthesize_js_body(root, missing.file_rel, missing.stub,
                              missing.test_rel, runner)
    if body is None:
        return plan  # no fixed template flips the RED test green — refuse
    return _land_body(plan, missing.file_rel, original, missing.stub, body)


def _splice_body(source: str, stub: JsStub, body: str) -> str | None:
    """Replace the body-block byte span of ``stub`` in ``source`` with
    ``{ <body> }`` and return the new source, or ``None`` when the recorded span
    is out of range (a stale scan — refuse rather than corrupt the file).

    The same exact byte-span splice the driver performs, recomputed in Python so
    the LANDED new_contents is produced WITHOUT a second filesystem write — the
    surrounding formatting/comments survive untouched."""
    if not (0 <= stub.body_start <= stub.body_end <= len(source)):
        return None
    return source[:stub.body_start] + "{ " + body + " }" + source[stub.body_end:]


def _landable(project_root: str | Path) -> list[JsMissingBody]:
    """The located stubs a fixed template can actually satisfy — i.e.
    ``plan_js_tdd_implement`` would land a body. A stub no template fits does NOT
    count (we refuse to touch it), so it never shows as remaining debt — an honest
    measure, exactly like the Python ``tdd-implement._missing``."""
    root = Path(project_root)
    return [mb for mb in detect_js_stubs(root)
            if plan_js_tdd_implement(root, mb).new_contents]


def fitness(project_root: str | Path) -> float:
    """Fitness = how many RED jest tests still demand a body this objective can
    deterministically synthesise. 0 means no implementable stub remains."""
    return float(len(_landable(project_root)))


def landable(project_root: str | Path) -> list[JsMissingBody]:
    """Public alias of :func:`_landable` — the located stubs a fixed template can
    satisfy. The objective's ``moves`` generator iterates this to build its
    ``Move``s (the ``operator="js_tdd_implement"`` literal stays in the objectives
    package so the move-value drift scanner still discovers it)."""
    return _landable(project_root)


# --- js-implement-from-jsdoc: the DISJOINT JSDoc-contract sibling -------------
#
# The INVERSE trigger of ``js-tdd-implement``: a ``throw``-stub with >=1 JSDoc
# ``@example`` AND NO jest test that links it (``_locate_test`` returns None), so
# the two NEVER double-count the same stub. The body is gated against a jest spec
# Apex GENERATES from the ``@example`` lines (in a throwaway copy), never against a
# test in the real tree.


def detect_js_jsdoc_stubs(project_root: str | Path) -> list[JsJsdocStub]:
    """Every JS/TS stub whose contract is its OWN JSDoc ``@example`` block and that
    NO jest test references — the ``js-implement-from-jsdoc`` candidates.

    REFUSES the whole project (returns ``[]``) unless a single ``package.json`` is
    at the root (the single-project gate, the JS analogue of one Python project
    root). For each own non-test JS/TS source, each top-level single-``throw`` stub
    is KEPT only when (a) its leading JSDoc mines >=1 ``@example`` witness AND (b)
    no jest test links it (:func:`_locate_test` is ``None`` — the inverse of
    ``js-tdd-implement``'s trigger), so a stub a test pins stays
    ``js-tdd-implement``'s and is never double-counted. Deterministic: sources in
    sorted order."""
    root = Path(project_root)
    out: list[JsJsdocStub] = []
    for file_rel, stub in _iter_own_stubs(root):
        if not mine_jsdoc_witnesses(root, file_rel, stub.name):
            continue  # no enforceable @example -> not ours
        if _locate_test(root, file_rel, stub.name) is not None:
            continue  # a jest test pins it -> js-tdd-implement's, refuse
        out.append(JsJsdocStub(stub=stub, file_rel=file_rel))
    return out


def plan_js_implement_from_jsdoc(project_root: str | Path, missing: JsJsdocStub,
                                 runner: RunTestsSkill | None = None) -> RenamePlan:
    """Build the synthesise-from-JSDoc plan for ONE located stub, or an empty no-op
    plan (an honest refusal).

    REFUSES a non-JS-source or test/fixture write target outright
    (:func:`is_js_source`), then delegates the body to
    :func:`synthesize_js_jsdoc_body`, which generates a throwaway jest spec from
    the stub's ``@example`` block and keeps the first fixed template whose copy goes
    green. On success the plan lands the ONE changed source's new full text in
    ``new_contents`` (original in ``originals``), so the gated/rollback writer runs
    the FULL real suite and restores it byte-for-byte on any regression. An empty
    plan means no fixed template satisfied the documented examples — nothing is
    landed (never-fake-green); Apex NEVER writes the generated spec into the real
    tree."""
    plan = RenamePlan(old=missing.file_rel, new="js-implement-from-jsdoc")
    root = Path(project_root)
    original = _read_plan_source(root, missing.file_rel)
    if original is None:
        return plan  # non-JS / test / fixture / unreadable — refuse
    runner = runner or RunTestsSkill()
    body = synthesize_js_jsdoc_body(root, missing.file_rel, missing.stub, runner)
    if body is None:
        return plan  # no fixed template satisfies the @example contract — refuse
    return _land_body(plan, missing.file_rel, original, missing.stub, body)


def _jsdoc_landable(project_root: str | Path) -> list[JsJsdocStub]:
    """The JSDoc-contract stubs a fixed template can actually satisfy — i.e.
    ``plan_js_implement_from_jsdoc`` would land a body. A stub no template fits does
    NOT count (we refuse to touch it), so it never shows as remaining debt — an
    honest measure, exactly like :func:`_landable`."""
    root = Path(project_root)
    return [mb for mb in detect_js_jsdoc_stubs(root)
            if plan_js_implement_from_jsdoc(root, mb).new_contents]


def jsdoc_fitness(project_root: str | Path) -> float:
    """Fitness = how many JSDoc-contract stubs still demand a body this objective
    can deterministically synthesise. 0 means no implementable stub remains."""
    return float(len(_jsdoc_landable(project_root)))


def jsdoc_landable(project_root: str | Path) -> list[JsJsdocStub]:
    """Public alias of :func:`_jsdoc_landable` — the JSDoc-contract stubs a fixed
    template can satisfy. The objective's ``moves`` generator iterates this (the
    ``operator="js_implement_from_jsdoc"`` literal stays in the objectives package
    so the move-value drift scanner discovers it)."""
    return _jsdoc_landable(project_root)


class JavaScriptAdapter:
    """The JS/TS :class:`LanguageAdapter`: a thin re-expression of the helpers
    above so the four verbs dispatch through one structural seam.

    ``owns`` IS :func:`is_js_source`; ``parse``/``locate`` read the byte spans
    :func:`scan_stubs` already returns; ``apply`` IS :func:`_splice_body`; and
    ``reparses`` reuses the driver's conservative ``scan_stubs`` path (a file the
    driver exits-2 on yields no stubs). Every method is the same predicate/slice
    the objective called inline, so dispatch is byte-identical."""

    name = "javascript"

    def owns(self, rel: str) -> bool:
        """True when ``rel`` is a non-test JS/TS source — the file gate."""
        return is_js_source(rel)

    def parse(self, source: str) -> ParseTree | None:
        """Wrap ``source`` as a parse tree — the JS driver parses per-file by
        path (see :meth:`locate`), so this only carries the text forward and is
        never ``None`` here (a does-not-parse file simply yields no targets)."""
        return ParseTree(tree=source)

    def locate(self, tree: ParseTree, source: str,
               query: TargetQuery) -> Target | None:
        """The stub named by ``query`` as a byte-span :class:`Target`, sourced
        from ``query.extra['stub']`` (the :class:`JsStub` the detector already
        located) — or ``None`` when absent. The JS driver locates stubs by path,
        so the detector supplies the span and this exposes it through the seam."""
        stub = query.extra.get("stub")
        if not isinstance(stub, JsStub) or stub.name != query.name:
            return None
        return Target(name=stub.name, span=(stub.body_start, stub.body_end))

    def apply(self, source: str, target: Target, edit: Edit) -> str | None:
        """``source`` with ``target``'s body span replaced by ``{ <edit.body> }``,
        or ``None`` when the span is stale — the exact :func:`_splice_body`
        splice, reconstructing the :class:`JsStub` from the located span."""
        start, end = target.span
        stub = JsStub(name=target.name, params=(), body_start=start, body_end=end)
        return _splice_body(source, stub, edit.body)

    def reparses(self, new_source: str) -> bool:
        """True when ``new_source`` is well-formed JS/TS. Proven by writing it to
        a throwaway file and asking the driver to scan it: the driver exits 2
        (read as no result) on a file that does not parse, so a scan that
        succeeds — even with zero stubs — is the well-formedness proof, the JS
        image of the Python re-``ast.parse`` guard."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            (tmp_root / "probe.js").write_text(new_source, encoding="utf-8")
            return _driver_parses(tmp_root, "probe.js")


def _driver_parses(root: Path, rel: str) -> bool:
    """True when the driver can parse ``root/rel`` — i.e. it returns a (possibly
    empty) stub list rather than refusing. The conservative-None contract of
    :mod:`app.execution.js.js_tool` means a non-parsing file yields ``None``,
    which we read as ``False``."""
    from app.execution.js.js_tool import _driver_json

    data = _driver_json(["scan", str(root / rel)], root)
    return isinstance(data, list)
