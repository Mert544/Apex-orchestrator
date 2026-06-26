"""The standing objective-SOUNDNESS denetçi — `apex self-audit --soundness`.

CLAUDE.md names the durable denetçi — a deterministic, zero-token, offline check a
wave-gate fails on — as "the preferred way to make the denetçi permanent and
automatic". The North Star sibling (:mod:`app.engine.north_star_audit`) audits
*classification / ratio / commit-drift*; THIS module audits a different, equally
load-bearing invariant: that every develop objective Apex can pursue ships a
**sound** transform — one that refuses or stays behavior-identical on the
library-shaped adversarial shapes that historically broke unsound transforms,
shapes Apex's OWN application tree lacks (no ``setup.py``, no shebang script under
scan, no external subclasser, no env-fragile public return). A transform that is
behavior-changing on those shapes ships A+99-test-green and is only caught later by
a manual re-audit on a foreign repo; this check substitutes that pilot
deterministically, in-repo.

It REUSES existing engines and adds NO new safety machinery for its own sake — it
is the standing form of the manual per-objective code-review the moat already
performs:

* the develop registry (:mod:`app.engine.develop_registry`) and the objective map
  (:func:`app.engine.objective_compiler._objectives_map`) — iterated LIVE, so a
  newly-registered objective is swept by the whole corpus automatically;
* the over-approximate whole-project scans baked into the objectives themselves
  (``freeze_dataclass`` / ``final_marker`` / ``final_method`` / ``module_exports``)
  — exercised, never re-implemented;
* the env/order/hash variation constants of the value-oracle gate
  (``test_shield._ENV_VARIATION_SEEDS`` / ``_RECAPTURE_HASHSEEDS``) — reused so the
  two determinism gates stay in lockstep;
* the manifest + forward/reverse-tripwire pattern of the North Star audit — so a
  new objective MUST declare HOW it is sound before this check can pass.

Two layers, both pure functions of repo state (no clock, no random, no network):

* **Layer A — static routing/structure (registry-walk, fast):** the reviewable
  :data:`SOUNDNESS_STRATEGY` manifest with FORWARD (:func:`strategy_completeness`)
  and REVERSE (:func:`strategy_subset_of_registry`) tripwires; the single-gated-
  writer assertion (:func:`check_single_writer`); the ``scope_verify`` allow-list
  (:func:`check_scope_verify_allowlist`).
* **Layer B — adversarial corpus (behavioral, fast in-process / heavy subprocess):**
  every registered objective is run against a fixed corpus of tiny library-shaped
  fixtures and must **refuse or stay behavior-identical** on each
  (:func:`corpus_refusal_findings`); the determinism harness re-runs each objective
  twice under varied ``PYTHONHASHSEED``/cwd/HOME/TZ/TMPDIR and demands byte-
  identical plans (:func:`determinism_findings`, opt-in, the heavy part).

Dependencies: stdlib + ``app.engine.develop_registry`` / ``objective_compiler``
(both already cycle-free w.r.t. the engine) + LOCAL subprocess helpers, so importing
this module never forms an ``app`` import cycle — the same discipline
``north_star_audit`` keeps.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

__all__ = [
    "SOUNDNESS_STRATEGY",
    "strategy_completeness",
    "strategy_subset_of_registry",
    "check_single_writer",
    "check_scope_verify_allowlist",
    "repo_root",
    "corpus_root",
    "corpus_shapes",
    "corpus_refusal_findings",
    "determinism_findings",
    "soundness_report",
    "render_markdown",
]


def repo_root() -> Path:
    """The Apex repo root, derived from THIS module's location (``app/engine/`` ->
    ``parents[2]``), so the registry + corpus subject resolves the same regardless of
    the caller's cwd — ``--soundness`` audits Apex's OWN tree, not an arbitrary
    ``--target``. Mirrors the ``Path(__file__).parents[...]`` repo-root resolution the
    project's own scripts use."""
    return Path(__file__).resolve().parents[2]


# --- Layer A4: the reviewable per-objective soundness-STRATEGY manifest -------
#
# The analogue of north_star_audit.OBJECTIVE_MANIFEST: a hand-curated dict literal
# recording, per objective, WHICH soundness sub-case (S2, §1 of the spec) it relies
# on to be safe. The registry carries no soundness metadata, so this is the single
# hand-curated source of truth — and the FORWARD tripwire makes it impossible to
# leave a registered objective undeclared (a new objective MUST state its soundness
# argument here before this check can pass). The strings are reviewable prose for a
# human auditor, not parsed by the check; only their PRESENCE per name is asserted.
#
# Strategy vocabulary (the S2 sub-cases of a SOUND develop-objective):
#   runtime-noop+<scan>        — @final/@typing.final: a pure runtime no-op, made
#                                honest by a tests-INCLUSIVE over-approximate scan.
#   behavior-identical         — the rewrite cannot change observable behavior
#                                (an idiom modernizer, a star-set-preserving __all__,
#                                a type hint, a docstring, a __future__ import).
#   suite-catches+<scan>       — a runtime mismatch the green suite catches (and
#                                apply_rename rolls back), plus a static refusal scan.
#   additive+oracle-gate       — lands only NEW test code, gated by the env/order/
#                                clock-reproducible value-oracle gate (never pins an
#                                env-fragile oracle; refuses when none is provable).
#   oracle-gated-scaffold      — lands new code/docs gated by an import/usage oracle
#                                in a throwaway copy, then the full suite on top.
SOUNDNESS_STRATEGY: dict[str, str] = {
    # --- CONCRETE: lands working code ---------------------------------------
    "add-final": "runtime-noop+used-as-base-scan(tests-incl)",
    "seal-final-method": "runtime-noop+transitive-subclass-scan(tests-incl)",
    "wire-module-exports": "behavior-identical-or-star-consumer-scan(tests-incl)",
    "wire-exports": "oracle-gated-scaffold(import-oracle)+additive-init",
    "js-wire-exports": "esm-export-keyword-add(pure-surface-grow)+reparse-exported-name-superset-or-refuse(no-suite-needed)",
    "freeze-dataclass": "suite-catches-runtime+own-module-mutation-scan",
    "add-slots": "behavior-identical-storage+whole-project-closed-attribute-superset-proof-or-refuse",
    "dataclassify": "suite-catches-runtime+behavior-preserving-rewrite",
    "add-from-future-annotations": "behavior-identical-future-import",
    "infer-type-hints": "behavior-identical-annotation-only",
    "document-signature": "behavior-identical-docstring-only",
    "document-export-jsdoc": "jsdoc-leading-trivia-insert+reparse-identical-or-refuse(no-suite-needed)",
    "js-document-param-types": "jsdoc-leading-trivia-insert+declared-param-types-verbatim+reparse-identical-or-refuse(no-suite-needed)",
    "document-raises-jsdoc": "jsdoc-leading-trivia-insert+throws-types-from-literal-new-verbatim+reparse-identical-or-refuse(no-suite-needed)",
    "generate-usage-doc": "oracle-gated-scaffold(doc-only-no-source-change)",
    "pin-doctest": "additive+oracle-gate(doctest-captured-then-verified)",
    "scaffold-from-protocol": "oracle-gated-scaffold(instantiation-oracle)+impact-scoped-derived-from-gate",
    "strengthen-tests": "additive+env-reproducible-oracle-gate",
    "cover-gaps": "additive+env-reproducible-oracle-gate",
    "implement-stub": "additive-fill+impact-scoped-suite-gate",
    "tdd-implement": "additive-fill+impact-scoped-suite-gate",
    "implement-from-doctest": "additive-fill+doctest-oracle+impact-scoped-suite-gate",
    "js-tdd-implement": "js-failing-test-RED→GREEN-or-refuse+byte-rollback",
    "js-implement-from-jsdoc": "js-jsdoc-example-RED→GREEN-or-refuse+byte-rollback",
    "enforce-enum-unique": "runtime-noop(@unique)+static-value-collision-refusal",
    "complete-match-exhaustiveness": "runtime-additive(unreached-arm)+static-closed-set-refusal",
    "synthesize-dunders": "suite-catches-runtime+canonical-total-dunders-over-proven-fields+inherited-eq-refusal",
    "seal-total-ordering": "runtime-additive(filled-comparison-ops)+single-defined-order-op+eq-present+static-refusal",
    "add-dataclass-order": "runtime-additive(generated-order-ops)+stdlib-dataclass-provenance+no-existing-comparison-dunder+static-refusal",
    # --- TIDY: behavior-preserving idiom rewrites ---------------------------
    "modernize": "behavior-preserving-idiom",
    "simplify-bool-return": "behavior-preserving-idiom",
    "simplify-comprehension": "behavior-preserving-idiom",
    "simplify-bool-comparison": "behavior-preserving-idiom",
    "simplify-len-comparison": "behavior-preserving-idiom",
    "simplify-negated-comparison": "behavior-preserving-idiom",
    "simplify-ternary-bool": "behavior-preserving-idiom",
    "simplify-dict-get": "behavior-preserving-idiom",
    "extract-constant": "behavior-preserving-idiom",
    "remove-unused-imports": "behavior-preserving-idiom",
    "sort-imports": "behavior-preserving-idiom",
    "sort-dunder-all": "behavior-preserving-idiom(__all__-order-irrelevant)",
    "remove-dead-code": "behavior-preserving-idiom",
    "remove-double-negation": "behavior-preserving-idiom",
    "remove-pointless-pass": "behavior-preserving-idiom",
    "remove-redundant-else": "behavior-preserving-idiom",
    "remove-redundant-fstring": "behavior-preserving-idiom",
    "remove-unreachable-after-terminator": "behavior-preserving-idiom",
    "dedup": "behavior-preserving-idiom",
    "dedup-parameterized": "behavior-preserving-idiom",
    "dedup-total-return": "behavior-preserving-idiom",
    "dead-params": "behavior-preserving-idiom",
    "shrink-functions": "behavior-preserving-idiom",
    "inline-helpers": "behavior-preserving-idiom",
    "chain-comparison": "behavior-preserving-idiom",
    "collapse-startswith": "behavior-preserving-idiom",
    "combine-augmented-assign": "behavior-preserving-idiom",
    "combine-nested-with": "behavior-preserving-idiom",
    "dict-comprehension": "behavior-preserving-idiom",
    "extract-guard-clause": "behavior-preserving-idiom",
    "guard-clause": "behavior-preserving-idiom",
    "merge-isinstance": "behavior-preserving-idiom",
    "merge-nested-if": "behavior-preserving-idiom",
    "fix-assert-tuple": "behavior-preserving-idiom",
    "fix-not-in-is": "behavior-preserving-idiom",
    "fold-literal-string-concat": "behavior-preserving-idiom",
    "format-to-fstring": "behavior-preserving-idiom",
    "fstring-convert": "behavior-preserving-idiom",
    "percent-to-fstring": "behavior-preserving-idiom",
    "set-literal": "behavior-preserving-idiom",
    "use-enumerate": "behavior-preserving-idiom",
    "merge-duplicate-imports": "behavior-preserving-idiom",
}

# The ONLY objectives allowed to set ``ObjectiveSpec.scope_verify=True`` (Layer A3).
# Impact-scoped gating is a deliberate, audited exception: each of these has a
# legitimately-RED baseline suite on a multi-module project (an unfilled stub, an
# unwired package, an un-strengthened test file), so the FULL-suite gate would let
# an UNRELATED still-red module veto a correct change. Each runs the IMPACTED tests
# (which genuinely pass after the change, so the "verified" stamp stays honest), and
# the full suite remains the commit-time backstop (``scripts/verify.py``). Silently
# widening this set would let a NEW objective dodge full-suite gating — so a
# ``scope_verify=True`` objective NOT listed here is a FAIL.
SCOPE_VERIFY_ALLOWLIST: frozenset[str] = frozenset({
    "implement-stub", "tdd-implement", "strengthen-tests", "wire-exports",
    "implement-from-doctest", "js-tdd-implement", "js-implement-from-jsdoc",
    # scaffold-from-protocol lands a brand-new ``<stem>_impl.py`` that no test
    # imports yet, so its impact-scope gate would degrade to the full suite and an
    # unrelated still-red module would veto the oracle-proven scaffold on a
    # multi-module RED baseline. It carries the protocol module in
    # ``RenamePlan.derived_from``, so the scope is seeded from the PROTOCOL
    # module's real importing tests; the instantiation oracle stays the
    # independent correctness proof and the full suite the commit-time backstop.
    "scaffold-from-protocol",
})


def _live_objective_names() -> list[str]:
    """The objective names the compiler can pursue — built-in and discovered.

    The single live registry seam both tripwires (and the corpus / determinism
    sweeps) read, so they all agree on "what a real objective is". Imported lazily
    to keep this module's import cheap and cycle-free."""
    from app.engine.objective_compiler import available_objectives

    return list(available_objectives())


def strategy_completeness(names) -> dict[str, str]:
    """FORWARD tripwire: the strategy of each name in ``names``, per the manifest.

    HONESTY TRIPWIRE (mirrors ``north_star_audit.classify_objectives``): raises
    :class:`ValueError` if ANY name has no declared soundness strategy. Passing the
    live registry therefore fails LOUDLY the moment a new objective self-registers
    without stating HOW it is sound — the manifest can never silently fall behind the
    registry. Returns ``{name: strategy}`` for the supplied names (sorted-stable by
    the caller)."""
    missing = sorted(n for n in names if n not in SOUNDNESS_STRATEGY)
    if missing:
        raise ValueError(
            "soundness manifest is stale: objective(s) without a declared "
            f"soundness strategy {missing} — add them to SOUNDNESS_STRATEGY in "
            "app/engine/soundness_audit.py (state HOW the transform is sound)."
        )
    return {n: SOUNDNESS_STRATEGY[n] for n in names}


def strategy_subset_of_registry(registered=None) -> list[str]:
    """REVERSE tripwire: manifest strategy names with NO live objective behind them.

    The mirror of :func:`strategy_completeness` — a strategy entry for an objective
    that has been renamed/removed but left stale in the manifest. Validates against
    the SAME live set the forward tripwire uses. Returns the sorted list of stale
    names (empty == clean). ``registered`` may be passed (any iterable) to check the
    manifest against a supplied registry — the seam the tests inject a stale name
    through — otherwise the live registry is read. Pure, deterministic."""
    live = set(registered) if registered is not None else set(_live_objective_names())
    return sorted(set(SOUNDNESS_STRATEGY) - live)


# --- Layer A1: the single gated-writer assertion -----------------------------
#
# S1 (§1): every landed move routes through ``apply_rename(..., verify=True)`` —
# write, verify, roll back on failure — and NO objective writes the tree by any
# other path. The structural fact that makes this true today is that the compile
# loop's ``_apply_one_move`` is the SOLE call site of ``apply_rename``, and no
# objective module calls it. This is a cheap, exact AST assertion: it fails loudly
# the moment a future objective self-applies (bypassing the gate + rollback).
#
# NOTE: the value-oracle objectives (implement-stub / tdd-implement) DO call
# ``Path.write_text`` — but only into a THROWAWAY COPY under a tempdir, to run their
# import/value oracle in a sandbox; that is not a write to the project tree, so it is
# NOT an S1 violation. The load-bearing invariant is specifically that
# ``apply_rename`` (the gated writer) has exactly one call site and no objective
# invokes it — which is what this checks.
_OBJECTIVES_PACKAGE_DIR = ("app", "execution", "objectives")
_COMPILE_LOOP_MODULE = ("app", "engine", "objective_compiler.py")
_GATED_WRITER = "apply_rename"


def _called_names(tree: ast.AST) -> list[str]:
    """Every bare/attribute call NAME invoked in ``tree`` (``f(...)`` / ``x.f(...)``)."""
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            names.append(func.attr)
        elif isinstance(func, ast.Name):
            names.append(func.id)
    return names


def _count_calls(path: Path, func_name: str) -> int:
    """How many times ``func_name`` is CALLED in ``path`` (0 if unreadable/unparsed).

    AST-based, so a mention of the name in a docstring or comment never counts —
    only a real call node. A missing or non-parseable file contributes 0."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return 0
    return sum(1 for n in _called_names(tree) if n == func_name)


def check_single_writer(repo_root: str | Path) -> tuple[bool, list[str]]:
    """A1: ``apply_rename`` is the sole gated writer of the project tree.

    Asserts (a) NO module under ``app/execution/objectives/`` calls ``apply_rename``
    directly, and (b) the compile loop ``app/engine/objective_compiler.py`` has
    EXACTLY ONE ``apply_rename`` call site. Returns ``(ok, reasons)`` — ``reasons``
    lists each violation (an offending objective module, or a wrong call-site count),
    empty when clean. Pure AST function of the two source locations."""
    root = Path(repo_root)
    reasons: list[str] = []
    objectives_dir = root.joinpath(*_OBJECTIVES_PACKAGE_DIR)
    for mod in sorted(objectives_dir.glob("*.py")):
        if _count_calls(mod, _GATED_WRITER) > 0:
            reasons.append(
                f"objective module {mod.name} calls {_GATED_WRITER} directly "
                "(bypasses the gated/rollback writer)")
    loop = root.joinpath(*_COMPILE_LOOP_MODULE)
    loop_calls = _count_calls(loop, _GATED_WRITER)
    if loop_calls != 1:
        reasons.append(
            f"compile loop {loop.name} has {loop_calls} {_GATED_WRITER} call sites "
            "(expected exactly 1 — the single gated writer)")
    return (not reasons, reasons)


def check_scope_verify_allowlist(specs=None) -> tuple[bool, list[str]]:
    """A3: only the audited red-baseline objectives set ``scope_verify=True``.

    Walks the live registry (or a supplied ``{name: spec}`` mapping — the seam the
    tests inject a planted spec through) and flags any objective that sets
    ``scope_verify=True`` while NOT in :data:`SCOPE_VERIFY_ALLOWLIST`. Returns
    ``(ok, reasons)``. Impact-scoping is a deliberate, audited exception; silently
    widening it would let an objective dodge full-suite gating, so an off-list
    ``scope_verify`` is a FAIL. Pure, deterministic."""
    if specs is None:
        from app.engine.develop_registry import registered_specs

        specs = registered_specs()
    reasons: list[str] = []
    for name in sorted(specs):
        spec = specs[name]
        if getattr(spec, "scope_verify", False) and name not in SCOPE_VERIFY_ALLOWLIST:
            reasons.append(
                f"objective '{name}' sets scope_verify=True but is not in the "
                "audited SCOPE_VERIFY_ALLOWLIST (would dodge full-suite gating)")
    return (not reasons, reasons)


# --- Layer B: the adversarial fixture corpus ---------------------------------
#
# A fixed directory of tiny library-shaped projects, each embedding ONE adversarial
# shape Apex's own tree lacks. For EVERY registered objective we run its
# ``moves(<fixture-root>)`` / ``build_plan()`` against each fixture and assert the
# planned output is REFUSED (empty) or BEHAVIOR-IDENTICAL (re-parses, and on the
# shebang shape keeps the prologue). The shapes a given objective is DESIGNED to
# break additionally REQUIRE a refusal — that is the K2-class bug this catches.
_CORPUS_DIR = ("tests", "fixtures", "soundness_corpus")

# Per shape: the objectives this fixture is DESIGNED to break — each MUST refuse on
# it (an empty plan), never land a change. Any objective NOT listed for a shape may
# still land a BEHAVIOR-IDENTICAL change (re-parses; prologue kept on shebang). The
# universal rule (every objective refuses on a non-parseable file) is enforced
# separately, so ``syntax_error`` maps to no per-objective entries.
_SHAPE_MUST_REFUSE: dict[str, frozenset[str]] = {
    "shebang_coding": frozenset(),  # behavior-identical only (prologue kept)
    "external_subclasser": frozenset({"add-final", "seal-final-method"}),
    "star_consumer": frozenset({"wire-module-exports"}),
    "relative_star_consumer": frozenset({"wire-module-exports"}),
    "env_fragile_return": frozenset({"strengthen-tests", "cover-gaps"}),
    "walrus_binder": frozenset({"wire-module-exports"}),
    "unpack_decorator": frozenset({"freeze-dataclass", "add-dataclass-order"}),
    "provenance_trap": frozenset(
        {"freeze-dataclass", "add-final", "add-dataclass-order"}),
    # The JS/TS analogue of provenance_trap: a JS ``throw``-stub whose ONLY contract
    # is its JSDoc ``@example`` block (no jest test links it, so it IS a
    # js-implement-from-jsdoc candidate) but whose two examples are mutually
    # unsatisfiable by every fixed template — js-implement-from-jsdoc MUST refuse it
    # (no fixed body reproduces both), never land a fake-green fill.
    "jsdoc_contradiction": frozenset({"js-implement-from-jsdoc"}),
    "syntax_error": frozenset(),  # universal-refuse rule covers every objective
    "already_applied": frozenset(
        {"wire-module-exports", "add-final", "freeze-dataclass"}),
}


def corpus_root(repo_root: str | Path) -> Path:
    """The adversarial corpus directory under ``repo_root`` (resolved like
    ``scripts/self_audit.py`` resolves its app/tests dirs)."""
    return Path(repo_root).joinpath(*_CORPUS_DIR)


def corpus_shapes(repo_root: str | Path) -> list[str]:
    """The corpus shape names present under :func:`corpus_root`, sorted.

    A shape is a sub-directory that holds the fixture project (its own ``pkg/``
    package). Requiring a ``pkg/`` directory deterministically skips a stray
    ``__pycache__`` (left by importing the corpus ``conftest.py``) or any other
    non-fixture dir. Deterministic (sorted); empty when the corpus dir is absent."""
    root = corpus_root(repo_root)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and (p / "pkg").is_dir())


def _changed_files(moves_fn, fixture_root: Path) -> dict[str, tuple[str, str]]:
    """Every file ``moves_fn`` would change on ``fixture_root``, as
    ``{rel: (new_source, original_source)}``.

    Keeping the ORIGINAL alongside the new bytes lets the prologue predicate check
    that a pre-existing shebang survived (rather than demanding one on a file that
    never had it). An objective whose move generation or plan derivation raises
    contributes nothing (treated as a refusal) — the same over-strict "any failure
    declines" discipline the value-oracle gate keeps."""
    changed: dict[str, tuple[str, str]] = {}
    try:
        moves = moves_fn(str(fixture_root))
    except Exception:
        return {}
    for mv in moves:
        try:
            plan = mv.build_plan()
        except Exception:
            continue
        for rel, content in plan.new_contents.items():
            changed[rel] = (content, plan.originals.get(rel, ""))
    return changed


def _reparses(source: str) -> bool:
    """True iff ``source`` re-parses (S7: a malformed splice is never landed)."""
    try:
        ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    return True


def _reparse_violation(changed: dict[str, tuple[str, str]]) -> str | None:
    """The first changed ``.py`` file whose NEW content does not re-parse, or None.

    Only PYTHON artifacts are re-parsed (S7). A landed non-``.py`` file — a
    generated ``USAGE.md`` doc, say — carries no Python semantics, so it is
    behavior-identical by construction and never re-parsed."""
    for rel, (content, _orig) in sorted(changed.items()):
        if rel.endswith(".py") and not _reparses(content):
            return f"VIOLATION:rewrite-does-not-reparse ({rel})"
    return None


def _prologue_violation(changed: dict[str, tuple[str, str]]) -> str | None:
    """The first changed file that LOST a pre-existing shebang prologue, or None.

    A file whose ORIGINAL started with ``#!`` must keep ``#!`` on physical line 1 of
    its new content (the ``_safe_insertion_index`` invariant). A file that never had
    a shebang (an empty ``__init__.py``, a test file) is unaffected — checking the
    original is what makes this precise rather than demanding a shebang everywhere."""
    for rel, (content, orig) in sorted(changed.items()):
        if not orig.startswith("#!"):
            continue
        first = content.splitlines()[0] if content.splitlines() else ""
        if not first.startswith("#!"):
            return f"VIOLATION:shebang-prologue-not-preserved ({rel})"
    return None


def _classify_cell(shape: str, objective: str,
                   changed: dict[str, tuple[str, str]]) -> str:
    """The corpus verdict for one (objective × fixture): ``refused`` /
    ``behavior-identical`` / ``VIOLATION:<why>``.

    Rules: an empty plan is ``refused``. ``syntax_error`` (and any shape listing the
    objective in :data:`_SHAPE_MUST_REFUSE`) REQUIRES a refusal — a landed change is a
    VIOLATION. Otherwise a landed change is ``behavior-identical`` iff every changed
    PYTHON file re-parses and no file lost a pre-existing shebang prologue."""
    if not changed:
        return "refused"
    must_refuse = objective in _SHAPE_MUST_REFUSE.get(shape, frozenset())
    if shape == "syntax_error" or must_refuse:
        return ("VIOLATION:landed-change-where-refusal-required "
                f"({sorted(changed)})")
    return _reparse_violation(changed) or _prologue_violation(changed) or "behavior-identical"


def corpus_refusal_findings(repo_root: str | Path,
                            include_heavy: bool = False) -> dict[str, dict[str, str]]:
    """Layer B: per (objective × fixture) corpus verdict, ``{obj: {shape: verdict}}``.

    Runs each registered objective's ``moves``/``build_plan`` against each corpus
    fixture IN-PROCESS (no ``apply_rename``, no suite — a static plan assertion, so
    it stays fast and OOM-free) and classifies each cell via :func:`_classify_cell`.
    By default the subprocess-backed objectives (``expensive`` + the value-oracle
    ``cover-gaps``) are SKIPPED to keep the fast gate sub-second; ``include_heavy``
    sweeps them too (used by the full audit). Deterministic: sorted objectives ×
    sorted shapes, pure function of the corpus bytes + the registry."""
    from app.engine.objective_compiler import _objectives_map

    objectives = _objectives_map()
    shapes = corpus_shapes(repo_root)
    root = corpus_root(repo_root)
    names = _swept_objective_names(objectives, include_heavy)
    out: dict[str, dict[str, str]] = {}
    for name in names:
        _fitness, moves_fn = objectives[name]
        per_shape: dict[str, str] = {}
        for shape in shapes:
            changed = _changed_files(moves_fn, root / shape)
            per_shape[shape] = _classify_cell(shape, name, changed)
        out[name] = per_shape
    return out


# --- Heavy/fast cost split ----------------------------------------------------
#
# §4.4: the fast (default ``--soundness``) path is the static Layer A + the
# IN-PROCESS corpus refusal check — sub-second, gate-friendly. Objectives whose plan
# derivation spawns SUBPROCESSES are skipped there and swept in the heavy path.
# ``develop_registry.expensive_names()`` flags the slow-fitness objectives; the
# value-oracle ``cover-gaps`` is subprocess-backed too (a coverage + oracle child per
# module) but is not registry-``expensive``, so it is named here. Kept tiny and
# explicit — a reviewable analogue of the manifest, validated by a test that asserts
# the fast sweep stays cheap.
_ORACLE_BACKED: frozenset[str] = frozenset({"cover-gaps"})


def heavy_objective_names() -> set[str]:
    """The subprocess-backed objectives skipped by the fast corpus path.

    ``expensive`` (slow whole-project fitness scans) UNION the value-oracle
    ``cover-gaps`` (a coverage/oracle subprocess per module). The fast gate omits
    these so it stays sub-second; the full/determinism path sweeps them."""
    from app.engine.develop_registry import expensive_names

    return set(expensive_names()) | set(_ORACLE_BACKED)


def _swept_objective_names(objectives, include_heavy: bool) -> list[str]:
    """The sorted objective names a sweep covers: all of ``objectives`` when
    ``include_heavy``, else the cheap (pure in-process) subset."""
    if include_heavy:
        return sorted(objectives)
    heavy = heavy_objective_names()
    return sorted(n for n in objectives if n not in heavy)


# --- §4: the determinism harness (generalizing the env-reproducibility gate) --
#
# Run each objective on the corpus TWICE in clean subprocesses under deliberately
# VARIED environments and demand byte-identical planned diffs. Two varied runs (not
# one) close the parent-seed-coincidence hole: an order-stable transform matches
# BOTH, while a set/dict-iteration-ordered emission diverges under at least one. The
# variation axes reuse ``test_shield``'s constants so the two gates stay in lockstep.
#
# The probe: import Apex from the repo root, derive the objective's planned diff over
# a COPY of the fixture under the run's tmp cwd, and print canonical JSON. The two
# runs differ ONLY in env (PYTHONHASHSEED/cwd/HOME/TZ/TMPDIR), so identical JSON ==
# deterministic. A crash/timeout/empty output is a VIOLATION (over-strict is safe).
_DETERMINISM_PROBE = r"""
import json, sys
repo_root, fixture_root, name = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, repo_root)
try:
    from app.engine.objective_compiler import _objectives_map
    _fitness, moves = _objectives_map()[name]
    out = {}
    for mv in moves(fixture_root):
        plan = mv.build_plan()
        for rel, content in plan.new_contents.items():
            out[rel] = content
    print(json.dumps({"ok": True, "diff": out}, sort_keys=True))
except BaseException as exc:  # noqa: BLE001 - any failure -> VIOLATION (decline)
    print(json.dumps({"ok": False, "err": type(exc).__name__}))
    sys.exit(0)
"""


def _variation_envs():
    """The TWO pinned environment variations (run alpha / run beta), reusing the
    value-oracle gate's axes so the two determinism gates stay in lockstep.

    Each yields ``(label, overrides)``; the caller fills cwd/HOME/TMPDIR with REAL
    temp dirs (a non-existent cwd would make every child fail and spuriously flag a
    violation). ``PYTHONHASHSEED``/``TZ`` come from ``_ENV_VARIATION_SEEDS``."""
    from app.execution.test_shield import _ENV_VARIATION_SEEDS

    return [(spec["name"], {"TZ": spec["TZ"], "PYTHONHASHSEED": spec["PYTHONHASHSEED"]})
            for spec in _ENV_VARIATION_SEEDS]


def _run_determinism_probe(repo_root: Path, fixture_root: Path, name: str,
                           overrides: dict[str, str]) -> str | None:
    """Derive ``name``'s canonical planned diff over a COPY of ``fixture_root`` in a
    clean subprocess under ``overrides`` (a fresh cwd/HOME/TMPDIR + the given
    TZ/PYTHONHASHSEED), or ``None`` on ANY failure.

    The copy lives under the run's tmp cwd so a cwd-dependent emission surfaces.
    Bytecode is off and the repo root is on ``PYTHONPATH`` (the ``test_shield``
    subprocess discipline). Returns the probe's stdout JSON line, or ``None`` on a
    crash/timeout/declined child — the caller treats ``None`` as a divergence."""
    import shutil

    with tempfile.TemporaryDirectory(prefix="apex_sound_") as base:
        cwd = os.path.join(base, "cwd")
        home = os.path.join(base, "home")
        tmp = os.path.join(base, "tmp")
        copy = os.path.join(cwd, "fixture")
        for d in (cwd, home, tmp):
            os.makedirs(d, exist_ok=True)
        shutil.copytree(fixture_root, copy)
        env = {
            **os.environ, **overrides,
            "HOME": home, "TMPDIR": tmp, "TEMP": tmp, "TMP": tmp,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(repo_root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        }
        try:
            proc = subprocess.run(
                [sys.executable, "-c", _DETERMINISM_PROBE, str(repo_root), copy, name],
                cwd=cwd, capture_output=True, text=True, env=env, timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    line = proc.stdout.strip().splitlines()[-1]
    try:
        payload = json.loads(line)
    except ValueError:
        return None
    # A child that itself declined (an import error, an unknown objective, a crash
    # caught inside the probe) reports ``ok: False`` -> treat as a failure (None), so
    # the verdict is a VIOLATION rather than a false "both runs agree on the error".
    if not payload.get("ok"):
        return None
    return json.dumps(payload["diff"], sort_keys=True)


def _determinism_verdict(repo_root: Path, fixture_root: Path, name: str) -> str:
    """``byte-identical`` iff ``name``'s planned diff over ``fixture_root`` is the
    same bytes under BOTH env variations, else ``VIOLATION:<why>``.

    A ``None`` from either child (crash/timeout/decline) or any divergence between
    the two canonical JSON diffs is a VIOLATION — over-strict by design (the
    value-oracle gate's "any child failure -> decline")."""
    renders: list[str] = []
    for label, overrides in _variation_envs():
        out = _run_determinism_probe(repo_root, fixture_root, name, overrides)
        if out is None:
            return f"VIOLATION:probe-failed (run {label})"
        renders.append(out)
    if renders[0] != renders[1]:
        return "VIOLATION:diff-not-byte-identical-across-env"
    return "byte-identical"


def _determinism_target_shape(repo_root: Path, objectives, name: str) -> str | None:
    """The first corpus shape ``name`` actually CHANGES (so the property has teeth),
    or ``None`` when it refuses every shape.

    Picks a fixture whose baseline plan is non-empty — re-running a refuse-everywhere
    objective would only ever compare two empty diffs, which is trivially stable and
    proves nothing. Deterministic (sorted shapes)."""
    _fitness, moves_fn = objectives[name]
    root = corpus_root(repo_root)
    for shape in corpus_shapes(repo_root):
        if _changed_files(moves_fn, root / shape):
            return shape
    return None


def determinism_findings(repo_root: str | Path) -> dict[str, str]:
    """§4 (heavy/opt-in): per-objective byte-identical-diff verdict across two varied
    env runs, ``{objective: "byte-identical"|"VIOLATION:<why>"}``.

    Iterates the LIVE registry (so a newly-registered objective is swept twice-under-
    varied-env automatically) INCLUDING the heavy subprocess-backed objectives — this
    is the deep path. For each objective it picks a corpus shape the objective
    changes (skipping refuse-everywhere objectives, whose two empty diffs prove
    nothing) and compares the canonical planned diff under run alpha vs run beta.
    Spawns interpreters, so it is the gate's only heavy part — keep it behind
    ``--determinism`` and out of a >=3-heavy-engineer window (AGENTS.md OOM ceiling)."""
    from app.engine.objective_compiler import _objectives_map

    objectives = _objectives_map()
    root = Path(repo_root)
    out: dict[str, str] = {}
    for name in sorted(objectives):
        shape = _determinism_target_shape(root, objectives, name)
        if shape is None:
            continue  # refuses every shape -> nothing landed to check determinism on
        out[name] = _determinism_verdict(root, root.joinpath(*_CORPUS_DIR, shape), name)
    return out


# --- The assembled verdict ----------------------------------------------------

def _corpus_violations(corpus: dict[str, dict[str, str]]) -> list[str]:
    """The sorted ``<obj>.<shape>`` reasons for every VIOLATION cell in ``corpus``."""
    reasons: list[str] = []
    for obj in sorted(corpus):
        for shape in sorted(corpus[obj]):
            verdict = corpus[obj][shape]
            if verdict.startswith("VIOLATION"):
                reasons.append(f"corpus.{obj}.{shape}: {verdict}")
    return reasons


def _determinism_violations(determinism: dict[str, str]) -> list[str]:
    """The sorted ``<obj>`` reasons for every VIOLATION in the determinism table."""
    return [f"determinism.{obj}: {determinism[obj]}"
            for obj in sorted(determinism) if determinism[obj].startswith("VIOLATION")]


def soundness_report(repo_root: str | Path, with_determinism: bool = False) -> dict:
    """Assemble the full objective-soundness verdict for ``repo_root``.

    Keys (stable, no wall-clock — same discipline as ``north_star_report``):
    ``total_objectives``, ``strategy_table`` (sorted ``{name: strategy}``),
    ``stale_strategies`` (reverse tripwire; empty == clean), ``single_writer_ok``
    (A1), ``scope_verify_ok`` (A3), ``corpus`` (Layer B cells), ``determinism``
    (§4 table — empty unless ``with_determinism``), ``violations`` (the FAIL list;
    empty == PASS), and ``verdict`` ("PASS"/"FAIL").

    :func:`strategy_completeness` is called on the LIVE registry, so a manifest that
    has fallen BEHIND the registry raises here (forward tripwire) — a bare run fails
    loudly, exactly like ``classify_objectives``. The default run is FAST (static
    Layer A + the in-process cheap-objective corpus); ``with_determinism`` adds the
    heavy subprocess §4 sweep AND the heavy objectives' corpus cells."""
    names = _live_objective_names()
    strategy_table = strategy_completeness(names)  # FORWARD tripwire: raises if stale
    stale = strategy_subset_of_registry(names)
    writer_ok, writer_reasons = check_single_writer(repo_root)
    scope_ok, scope_reasons = check_scope_verify_allowlist()
    corpus = corpus_refusal_findings(repo_root, include_heavy=with_determinism)
    determinism = determinism_findings(repo_root) if with_determinism else {}

    violations: list[str] = []
    violations += [f"stale-strategy.{n}: no live objective" for n in stale]
    violations += writer_reasons
    violations += scope_reasons
    violations += _corpus_violations(corpus)
    violations += _determinism_violations(determinism)

    return {
        "total_objectives": len(names),
        "strategy_table": {n: strategy_table[n] for n in sorted(strategy_table)},
        "stale_strategies": stale,
        "single_writer_ok": writer_ok,
        "scope_verify_ok": scope_ok,
        "corpus": {obj: corpus[obj] for obj in sorted(corpus)},
        "determinism": {obj: determinism[obj] for obj in sorted(determinism)},
        "violations": sorted(violations),
        "verdict": "FAIL" if violations else "PASS",
    }


def render_markdown(report: dict, target: str | Path = ".") -> str:
    """Render :func:`soundness_report` output as a deterministic markdown block.

    Mirrors ``north_star_audit.render_markdown``: a header, ``Verdict: **PASS/FAIL**``,
    the strategy-table count and Layer A booleans, then — only when non-empty — the
    stale-strategy names and the corpus / determinism VIOLATION cells with reasons.
    Deterministic ordering throughout (no wall-clock, sorted lists)."""
    lines = [
        "# Apex Self-Audit — Objective Soundness",
        f"**Target:** {target}",
        "",
        f"- Verdict: **{report['verdict']}**",
        f"- Objectives with a declared soundness strategy: "
        f"{len(report['strategy_table'])}/{report['total_objectives']}",
        f"- Single gated writer (A1): {report['single_writer_ok']}",
        f"- scope_verify allow-list (A3): {report['scope_verify_ok']}",
        f"- Corpus shapes swept: {len(next(iter(report['corpus'].values()), {}))} "
        f"x {len(report['corpus'])} objectives",
    ]
    if report["determinism"]:
        ok = sum(1 for v in report["determinism"].values() if v == "byte-identical")
        lines.append(
            f"- Determinism (two varied env runs): {ok}/{len(report['determinism'])} "
            "byte-identical")
    if report["stale_strategies"]:
        lines.append(
            "- STALE STRATEGY ENTRIES (no live objective): "
            + ", ".join(report["stale_strategies"]))
    if report["violations"]:
        lines.append("")
        lines.append("## Violations")
        for reason in report["violations"]:
            lines.append(f"- {reason}")
    return "\n".join(lines)
