"""Self-registering objective: js-tdd-implement — Apex's FIRST non-Python landing.

The JS/TS image of :mod:`app.execution.objectives.tdd_implement` — the everyday
TDD inner loop a budget-limited student or team otherwise pays an LLM for,
message by message: "I wrote the failing jest test, now write the code." Given a
top-level ``function foo(...) { throw new Error("Not implemented") }`` stub (or a
``const foo = (...) => { throw ... }`` arrow stub) that a jest test calls, this
objective DETERMINISTICALLY synthesises a real body from a FIXED template space
and lands it iff the previously-RED test flips GREEN — landing working code only
when the project's own ``npm test`` verifies it, with byte-for-byte auto-rollback
on any regression.

The pipeline mirrors the Python spine — **detect -> locate -> synthesise ->
gate** — but is JS-flavoured and touches ZERO Python objectives:

1. **DETECT** — only when a single ``package.json`` is at the project root (the
   single-project gate, the JS analogue of one Python project root). Each own
   ``.js``/``.ts`` source module is parsed by the bundled ``ts_driver.js`` (the
   TypeScript Compiler API); its top-level single-``throw`` stubs are the
   fillable candidates. Non-JS files are REFUSED outright (see
   :func:`_is_js_source`), so this objective is a clean no-op on a Python tree.
2. **LOCATE** — find the ONE jest test that both imports the stub's module AND
   references the stub by name (the test that pins it). Ambiguity — zero or many
   such tests — is REFUSED, never guessed.
3. **SYNTHESISE** — delegate the body to
   :func:`app.execution.js.js_stub_synthesis.synthesize_js_body`, which tries the
   fixed template space in order against a THROWAWAY COPY's ``npm test`` and keeps
   the FIRST body that goes green (else refuses). Zero new synthesis logic here.
4. **GATE** — the plan lands the ONE changed source as a :class:`RenamePlan`
   (``originals`` for rollback, ``new_contents`` for the body), so the develop
   engine's gated/rollback writer runs the suite and restores it byte-for-byte if
   anything regresses.

Deterministic (fixed template order, byte-span splice, no clock/random — same
project, byte-identical body), offline (the project owns its ``node_modules``,
``typescript`` is global; Apex installs nothing), zero-token. Test/fixture files
are refused as WRITE targets — Apex never edits the suite it is gated by.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.engine.skip_dirs import SKIPPED_DIRS
from app.execution.cross_file_rename import RenamePlan
from app.execution.js.js_stub_synthesis import synthesize_js_body
from app.execution.js.js_tool import JsStub, scan_stubs
from app.skills.execution.run_tests import RunTestsSkill

__all__ = ["plan_js_tdd_implement", "JsMissingBody", "detect_js_stubs", "is_js_source"]

# Source extensions the TS Compiler API parses as JS/TS. ANY other path is REFUSED
# — this is exactly what makes the objective a clean no-op on a Python (or any
# non-JS) file, so it never disturbs the Python path nor the soundness corpus.
_JS_SOURCE_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"})

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


def detect_js_stubs(project_root: str | Path) -> list[JsMissingBody]:
    """Every deterministically-located JS/TS stub a RED jest test demands a body
    for, each pinned to its single test.

    REFUSES the whole project (returns ``[]``) unless a single ``package.json`` is
    at the root — the single-project gate, the JS analogue of one Python project
    root. For each own non-test JS/TS source, each top-level single-``throw`` stub
    that locates to exactly one pinning test is kept. Deterministic: sources and
    tests in sorted order."""
    root = Path(project_root)
    if not (root / "package.json").exists():
        return []
    out: list[JsMissingBody] = []
    for file_rel in _walk_files(root, _JS_SOURCE_SUFFIXES):
        if not is_js_source(file_rel):
            continue
        for stub in scan_stubs(root, file_rel):
            test_rel = _locate_test(root, file_rel, stub.name)
            if test_rel is None:
                continue
            out.append(JsMissingBody(stub=stub, file_rel=file_rel, test_rel=test_rel))
    return out


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
    file_rel = missing.file_rel
    if not is_js_source(file_rel):
        return plan  # non-JS / test / fixture file — refuse (the no-op on .py)
    root = Path(project_root)
    target = root / file_rel
    original = _read(target)
    if not original and not target.exists():
        return plan  # unreadable / missing target — no-op

    runner = runner or RunTestsSkill()
    body = synthesize_js_body(root, file_rel, missing.stub, missing.test_rel, runner)
    if body is None:
        return plan  # no fixed template flips the RED test green — refuse

    filled = _splice_body(original, missing.stub, body)
    if filled is None or filled == original:
        return plan  # the splice did not change the source — refuse
    plan.originals[file_rel] = original
    plan.new_contents[file_rel] = filled
    plan.edits_by_file[file_rel] = 1
    return plan


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


# --- registry wiring ---------------------------------------------------------

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


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move

    root = Path(project_root)
    return [Move(
        operator="js_tdd_implement",
        target=f"{mb.file_rel}:{mb.stub.name}",
        description=(f"synthesize {mb.stub.name}() in {mb.file_rel} "
                     "to make its RED jest test green"),
        build_plan=lambda m=mb: plan_js_tdd_implement(root, m),
    ) for mb in _landable(root)]


# Detection spawns node (parse) and, per candidate body, the project's jest suite
# against a throwaway copy — heavyweight — so flag it expensive: the fast
# plan/ascend board skips the scan, but it stays runnable explicitly via
# `apex develop --objective js-tdd-implement`.
# scope_verify=True for the same reason as the Python tdd-implement: on a
# multi-module JS project several modules can each have a RED test demanding a
# not-yet-written body, so the baseline suite is legitimately RED; making module
# A's test green must not be vetoed by an unrelated module B's still-red test.
register(ObjectiveSpec(name="js-tdd-implement", fitness=fitness, moves=moves,
                       expensive=True, scope_verify=True))
