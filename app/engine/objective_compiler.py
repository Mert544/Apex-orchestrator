"""Objective Compiler — goal-directed composition of verified transforms.

The deterministic search controller the research (GenProg, search-based
refactoring, AutoCodeRover, MAP-Elites) identifies as Apex's next leap. Where
``apex maintain`` applies whatever single smell-fix it finds, the compiler is
*goal-directed*: given an OBJECTIVE — a measurable fitness over the project —
and a pool of safe moves, it greedily applies the move that reduces the
objective metric, **each apply gated by the test suite with automatic
rollback**, until the objective is met or no improving move remains.

This is the classic propose→apply→measure→select loop with two parts Apex
already owns and the LLM-agent crowd bolts on: the *operators* are real,
test-verified transforms (not generated text), and the *oracle* is the project's
own suite (not a model's opinion). The loop itself is stdlib + the existing
``RenamePlan`` / ``apply_rename`` engine — no model, fully deterministic.

The first wired objective is **dead-parameter elimination**: every move is an
``apex signature drop`` of a never-read parameter — semantics-preserving, so the
fitness (the count of dead parameters) strictly decreases with each landed move.
The architecture is operator-agnostic: adding inline / extract / modernize move
generators is a single function each. The applied ordering is recorded to the
composition memory, so the organism learns which move *sequences* land.

Deterministic, stdlib-only; reuses the verified-with-rollback transform engine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.execution.cross_file_rename import RenamePlan

__all__ = [
    "Move", "CompileStep", "CompileResult",
    "dead_parameter_fitness", "inlinable_helper_fitness", "long_function_fitness",
    "modernize_fitness", "dead_code_fitness", "duplication_fitness",
    "bool_return_fitness", "magic_constant_fitness",
    "compile_objective", "compile_all", "available_objectives",
    "ALL_OBJECTIVES", "SESSION_OBJECTIVES",
    "render_compile_markdown", "render_from_dream_markdown", "render_all_markdown",
    "resolve_objective", "objective_synonyms",
]


@dataclass
class Move:
    """One candidate transform the compiler may apply to the current tree.

    ``build_plan`` is a thunk that re-derives the plan against the project's
    CURRENT state (line numbers shift as earlier moves land), so a move stays
    valid only as long as its precondition holds."""
    operator: str
    target: str
    description: str
    build_plan: Callable[[], RenamePlan]


@dataclass
class CompileStep:
    operator: str
    target: str
    description: str
    fitness_before: float
    fitness_after: float
    verified: bool = False
    # Coverage strength of the green suite for THIS move (the maintain-path
    # ``assess_strength`` levels: ``function`` / ``module`` / ``none`` /
    # ``test-change``, or ``""`` when no suite ran). ``verified`` is the raw
    # suite-green bool; ``coverage`` is what that green suite actually exercised
    # — a green-but-unreferencing suite (``none``) must never be labelled a
    # genuine "verified" move (the never-fake-green hardening maintain carries).
    coverage: str = ""

    @property
    def coverage_verified(self) -> bool:
        """Did a test GENUINELY exercise the change? True only when the suite ran
        green AND a test references the changed module/function (or only test
        files changed). A green suite that never looked at the change is NOT
        coverage-verified — this is the honest tier the develop report counts."""
        return self.verified and self.coverage in (
            "function", "module", "test-change")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator, "target": self.target,
            "description": self.description,
            "fitness_before": self.fitness_before,
            "fitness_after": self.fitness_after, "verified": self.verified,
            "coverage": self.coverage,
        }


@dataclass
class CompileResult:
    objective: str
    fitness_start: float
    fitness_end: float
    steps: list[CompileStep] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    applied: bool = False  # were any moves actually written (vs. dry run)?

    @property
    def improved(self) -> bool:
        return self.fitness_end < self.fitness_start

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "fitness_start": self.fitness_start,
            "fitness_end": self.fitness_end,
            "improved": self.improved,
            "moves_applied": len(self.steps),
            "steps": [s.to_dict() for s in self.steps],
            "blocked": self.blocked,
            "applied": self.applied,
        }


# --- Objective: dead-parameter elimination -----------------------------------

def _dead_params(project_root: str | Path) -> list[dict]:
    """The project's never-read parameters (the profiler's dead-param scan, run
    in isolation — not the full ~200s profile, which this objective doesn't need)."""
    from app.tools.project_profile import ProjectProfiler

    return list(ProjectProfiler(str(project_root)).dead_params() or [])


def dead_parameter_fitness(project_root: str | Path) -> float:
    """Fitness = how many never-read parameters remain. Lower is better; the
    objective is reached at 0."""
    return float(len(_dead_params(project_root)))


def _dead_param_moves(project_root: str | Path) -> list[Move]:
    """One drop move per never-read parameter found in the current tree."""
    from app.execution.param_drop import plan_param_drop

    moves: list[Move] = []
    for dp in _dead_params(project_root):
        fn, param, mod = dp["function"], dp["param"], dp["module"]
        moves.append(Move(
            operator="drop_param",
            target=f"{mod}:{fn}({param})",
            description=f"drop never-read parameter `{param}` from {fn}() in {mod}",
            build_plan=lambda f=fn, p=param: plan_param_drop(str(project_root), f, p),
        ))
    return moves


# --- Objective: inline single-use helpers (reduce indirection) ---------------

def _inlinable_helpers(project_root: str | Path) -> list[dict]:
    """Tiny single-use helpers `apex inline` would cleanly fold away."""
    from app.execution.inline_function import suggest_inlines

    return list(suggest_inlines(str(project_root)))


def inlinable_helper_fitness(project_root: str | Path) -> float:
    """Fitness = how many single-use helpers remain to fold in. Lower is less
    indirection; the objective is reached at 0."""
    return float(len(_inlinable_helpers(project_root)))


def _guarded_inline_plan(project_root: str | Path, function: str) -> RenamePlan:
    """The inline plan for ``function``, but BLOCKED when it would fold the
    helper into a test/fixture file. A function whose only caller is a test is a
    public surface, not internal indirection — inlining it would dissolve real
    code into a test assertion (and empty its module). Safety over activity."""
    from app.engine.health_score import _is_fixture_path
    from app.execution.inline_function import plan_inline

    plan = plan_inline(str(project_root), function)
    if plan.new_contents and any(_is_fixture_path(rel) for rel in plan.new_contents):
        plan.blockers.append(
            "inlining would edit a test/fixture file — the helper is a public "
            "surface, not internal indirection; skipped")
        plan.new_contents.clear()
    return plan


def _inline_moves(project_root: str | Path) -> list[Move]:
    """One inline move per single-use helper found in the current tree."""
    moves: list[Move] = []
    for h in _inlinable_helpers(project_root):
        fn, mod = h["function"], h["module"]
        moves.append(Move(
            operator="inline",
            target=f"{mod}:{fn}()",
            description=f"inline the single-use helper `{fn}()` in {mod}",
            build_plan=lambda f=fn: _guarded_inline_plan(project_root, f),
        ))
    return moves


# --- Objective: shrink long functions by extracting helpers ------------------

def _own_modules(project_root: str | Path) -> list[tuple[str, str]]:
    """The project's own non-fixture .py modules as (rel, source).

    Backed by the parse-once source index: a campaign's many candidate scans
    (modernize, extract, inline, remove-dead-code, all repeated each pass) reuse
    ONE directory walk + read of the tree, rebuilt only when a move actually
    changes a file (mtime fingerprint). On a large repo this is the difference
    between re-walking 300 files on every scan and walking them once per pass."""
    from app.engine.source_index import indexed_project

    return indexed_project(str(project_root)).own_sources()


def _extract_suggestions(project_root: str | Path) -> list[tuple[str, dict]]:
    """The best extractable seam for each long function, as (module, seam).

    Functions named like the extractor's own output (``..._part``) are skipped
    so a campaign never cascades into the helpers it just created — one clean
    extraction per real long function, not a chain of nested ``_part_part``.

    Runs over the source index's already-parsed trees, handing each cached parse
    to ``suggest_extractions`` so a module is never re-parsed per scan. A module
    that didn't parse yields no seams either way (``suggest_extractions`` returns
    ``[]`` on a syntax error), so iterating the parsed modules is identical to
    iterating every own source."""
    from app.engine.source_index import indexed_project
    from app.execution.extract_method import suggest_extractions

    out: list[tuple[str, dict]] = []
    for module in indexed_project(str(project_root)).parsed_modules():
        for seam in suggest_extractions(module.source, module.tree):
            if not seam["function"].endswith("_part"):
                out.append((module.rel, seam))
    return out


def long_function_fitness(project_root: str | Path) -> float:
    """Fitness = how many long functions still have a clean seam to extract.
    Lower means less sprawl; the objective is reached when none remain."""
    return float(len(_extract_suggestions(project_root)))


def _extract_moves(project_root: str | Path) -> list[Move]:
    """One extract move per long function with a clean seam in the current tree."""
    from app.execution.extract_method import plan_extract

    moves: list[Move] = []
    for rel, seam in _extract_suggestions(project_root):
        moves.append(Move(
            operator="extract",
            target=f"{rel}:{seam['function']}()",
            description=(f"extract a {seam['lines_saved']}-line helper "
                        f"`{seam['name']}` from {seam['function']}() in {rel}"),
            build_plan=lambda r=rel, s=seam: plan_extract(
                str(project_root), r, s["start"], s["end"], s["name"]),
        ))
    return moves


# --- Objective: modernize tidy debt (== None / dead f-string / dict()) --------

# Each entry: (operator, human label, transform.apply). The transform rewrites
# every instance of its pattern in a file at once and is behaviour-preserving.
def _tidy_transforms() -> list[tuple[str, str, Callable]]:
    from app.execution.semantic.transforms import (
        collection_literal, fstring, modernize,
    )
    return [
        ("modernize", "modernize None comparisons", modernize.apply),
        ("fix_fstring", "drop dead f-string prefixes", fstring.apply),
        ("fix_collection", "use collection literals", collection_literal.apply),
    ]


def _content_plan(project_root: str | Path, rel: str, apply_fn: Callable,
                  title: str) -> RenamePlan:
    """Wrap a content-producing transform (a SemanticPatchResult) as a RenamePlan
    so the compiler can apply it through the same verified-with-rollback engine
    as the structural moves."""
    plan = RenamePlan(old=rel, new=title)
    try:
        source = (Path(project_root) / rel).read_text(encoding="utf-8")
    except OSError:
        return plan
    try:
        res = apply_fn(rel, source, title)
    except Exception:
        res = None
    if res and getattr(res, "patch_requests", None):
        new = res.patch_requests[0].get("new_content", "")
        if new and new != source:
            plan.originals[rel] = source
            plan.new_contents[rel] = new
            plan.edits_by_file[rel] = 1
    return plan


def _modernize_candidates(project_root: str | Path) -> list[tuple[str, str, str, Callable]]:
    """(module, operator, label, apply_fn) for every tidy transform that would
    actually change one of the project's own modules."""
    out: list[tuple[str, str, str, Callable]] = []
    transforms = _tidy_transforms()
    for rel, source in _own_modules(project_root):
        for op, label, fn in transforms:
            try:
                res = fn(rel, source, label)
            except Exception:
                res = None
            if res and getattr(res, "patch_requests", None):
                new = res.patch_requests[0].get("new_content", "")
                if new and new != source:
                    out.append((rel, op, label, fn))
    return out


def modernize_fitness(project_root: str | Path) -> float:
    """Fitness = how many tidy-debt rewrites remain across the project's own
    code (each is one module × one transform that would still change it)."""
    return float(len(_modernize_candidates(project_root)))


def _modernize_moves(project_root: str | Path) -> list[Move]:
    """One move per (module, tidy-transform) that would change something now."""
    moves: list[Move] = []
    for rel, op, label, fn in _modernize_candidates(project_root):
        moves.append(Move(
            operator=op, target=f"{rel}:{op}", description=f"{label} in {rel}",
            build_plan=lambda r=rel, f=fn, t=label: _content_plan(project_root, r, f, t),
        ))
    return moves


# --- Objective: remove unreachable (dead) code -------------------------------

def _dead_code_modules(project_root: str | Path) -> list[str]:
    """Own modules that contain unreachable code (after a terminal statement)."""
    from app.engine.detectors import has_unreachable_code

    return [rel for rel, src in _own_modules(project_root) if has_unreachable_code(src)]


def dead_code_fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still carry unreachable code. Removing it
    is behaviour-preserving (the code never ran), so the objective is reached at
    zero."""
    return float(len(_dead_code_modules(project_root)))


def _dead_code_moves(project_root: str | Path) -> list[Move]:
    """One move per module with unreachable code — delete the dead statements."""
    from app.execution.dead_code import plan_remove_dead_code

    moves: list[Move] = []
    for rel in _dead_code_modules(project_root):
        moves.append(Move(
            operator="remove_dead_code", target=f"{rel}:dead-code",
            description=f"remove unreachable code in {rel}",
            build_plan=lambda r=rel: plan_remove_dead_code(project_root, r),
        ))
    return moves


# --- Objective: de-duplicate (extract copy-pasted blocks to a shared helper) --

def _duplicate_blocks(project_root: str | Path) -> list:
    """The project's duplicated code blocks (the dedup detector's findings)."""
    from app.engine.dedup import find_duplicates

    return find_duplicates(str(project_root))


def duplication_fitness(project_root: str | Path) -> float:
    """Fitness = how many duplicated blocks remain. Each safely-extractable one
    folds into a shared helper; blocks that can't be extracted safely stay (the
    compiler skips them), so fitness reaches its achievable floor, not a false 0."""
    return float(len(_duplicate_blocks(project_root)))


def _dedup_moves(project_root: str | Path) -> list[Move]:
    """One move per duplicated block — extract it into a shared helper, replace
    every copy with a call (the dedup_extract transform, suite-verified)."""
    from app.execution.dedup_extract import plan_dedup_extract

    moves: list[Move] = []
    for block in _duplicate_blocks(project_root):
        occ = list(getattr(block, "occurrences", []) or [])
        mod = occ[0].split(":", 1)[0] if occ else "?"
        moves.append(Move(
            operator="dedup_extract", target=f"{mod}:dup",
            description=(f"extract a {block.lines}-statement block duplicated in "
                        f"{len(occ)} place(s) into a shared helper"),
            build_plan=lambda b=block: plan_dedup_extract(project_root, b),
        ))
    return moves


# --- Objective: simplify boolean returns (if c: return True ... → return c) --

def _bool_return_modules(project_root: str | Path) -> list[str]:
    """Own modules whose boolean returns can be simplified."""
    from app.execution.bool_return import plan_simplify_bool_return

    out: list[str] = []
    for rel, _src in _own_modules(project_root):
        if plan_simplify_bool_return(project_root, rel).new_contents:
            out.append(rel)
    return out


def bool_return_fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still have a simplifiable boolean return."""
    return float(len(_bool_return_modules(project_root)))


def _bool_return_moves(project_root: str | Path) -> list[Move]:
    """One move per module with a simplifiable boolean return."""
    from app.execution.bool_return import plan_simplify_bool_return

    return [Move(
        operator="simplify_bool_return", target=f"{rel}:bool-return",
        description=f"simplify boolean returns in {rel}",
        build_plan=lambda r=rel: plan_simplify_bool_return(project_root, r),
    ) for rel in _bool_return_modules(project_root)]


# --- Objective: extract repeated magic literals into named constants ---------

def _magic_constant_modules(project_root: str | Path) -> list[str]:
    """Own modules with a repeated magic literal worth naming.

    Each module's plan is built from the source the index already read, so the
    scan never re-walks the whole project per module (``plan_extract_constant``
    otherwise reads every file on every call). The plan is identical to the
    disk-read path — same bytes in, same plan out."""
    from app.execution.extract_constant import plan_extract_constant

    out: list[str] = []
    for rel, src in _own_modules(project_root):
        if plan_extract_constant(project_root, rel, source=src).new_contents:
            out.append(rel)
    return out


def magic_constant_fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still hide a repeated magic literal."""
    return float(len(_magic_constant_modules(project_root)))


def _extract_constant_moves(project_root: str | Path) -> list[Move]:
    """One move per module — name its most-repeated magic literal."""
    from app.execution.extract_constant import plan_extract_constant

    return [Move(
        operator="extract_constant", target=f"{rel}:constant",
        description=f"name a repeated magic literal in {rel}",
        build_plan=lambda r=rel: plan_extract_constant(project_root, r),
    ) for rel in _magic_constant_modules(project_root)]


# --- Objective: sort imports (group + alphabetize a clean import block) ------

def _import_sort_modules(project_root: str | Path) -> list[str]:
    """Own modules whose import block can be sorted."""
    from app.execution.import_sort import plan_sort_imports

    out: list[str] = []
    for rel, _src in _own_modules(project_root):
        if plan_sort_imports(project_root, rel).new_contents:
            out.append(rel)
    return out


def import_sort_fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still have an unsorted import block."""
    return float(len(_import_sort_modules(project_root)))


def _import_sort_moves(project_root: str | Path) -> list[Move]:
    """One move per module with a sortable import block."""
    from app.execution.import_sort import plan_sort_imports

    return [Move(
        operator="sort_imports", target=f"{rel}:sort-imports",
        description=f"sort the import block in {rel}",
        build_plan=lambda r=rel: plan_sort_imports(project_root, r),
    ) for rel in _import_sort_modules(project_root)]


# --- Objective: simplify accumulator loops into comprehensions ---------------

def _comprehension_modules(project_root: str | Path) -> list[str]:
    """Own modules with an accumulator loop that can become a comprehension."""
    from app.execution.comprehension import plan_simplify_comprehension

    out: list[str] = []
    for rel, _src in _own_modules(project_root):
        if plan_simplify_comprehension(project_root, rel).new_contents:
            out.append(rel)
    return out


def comprehension_fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still have a simplifiable accumulator loop."""
    return float(len(_comprehension_modules(project_root)))


def _comprehension_moves(project_root: str | Path) -> list[Move]:
    """One move per module with a simplifiable accumulator loop."""
    from app.execution.comprehension import plan_simplify_comprehension

    return [Move(
        operator="simplify_comprehension", target=f"{rel}:comprehension",
        description=f"simplify accumulator loops in {rel}",
        build_plan=lambda r=rel: plan_simplify_comprehension(project_root, r),
    ) for rel in _comprehension_modules(project_root)]


# --- Objective: remove unused imports (drop dead top-level imports) ----------

def _unused_import_modules(project_root: str | Path) -> list[str]:
    """Own modules with a removable unused top-level import."""
    from app.execution.unused_imports import plan_remove_unused_imports

    out: list[str] = []
    for rel, _src in _own_modules(project_root):
        if plan_remove_unused_imports(project_root, rel).new_contents:
            out.append(rel)
    return out


def unused_import_fitness(project_root: str | Path) -> float:
    """Fitness = how many own modules still carry an unused import."""
    return float(len(_unused_import_modules(project_root)))


def _unused_import_moves(project_root: str | Path) -> list[Move]:
    """One move per module with a removable unused import."""
    from app.execution.unused_imports import plan_remove_unused_imports

    return [Move(
        operator="remove_unused_imports", target=f"{rel}:unused-import",
        description=f"remove unused imports in {rel}",
        build_plan=lambda r=rel: plan_remove_unused_imports(project_root, r),
    ) for rel in _unused_import_modules(project_root)]


_OBJECTIVES: dict[str, tuple[Callable[[str | Path], float],
                             Callable[[str | Path], list[Move]]]] = {
    "modernize": (modernize_fitness, _modernize_moves),
    "simplify-bool-return": (bool_return_fitness, _bool_return_moves),
    "simplify-comprehension": (comprehension_fitness, _comprehension_moves),
    "extract-constant": (magic_constant_fitness, _extract_constant_moves),
    "remove-unused-imports": (unused_import_fitness, _unused_import_moves),
    "sort-imports": (import_sort_fitness, _import_sort_moves),
    "remove-dead-code": (dead_code_fitness, _dead_code_moves),
    "dedup": (duplication_fitness, _dedup_moves),
    "dead-params": (dead_parameter_fitness, _dead_param_moves),
    "shrink-functions": (long_function_fitness, _extract_moves),
    "inline-helpers": (inlinable_helper_fitness, _inline_moves),
}


# The objectives `apex develop --all` sweeps, in a deliberate order: tidy the
# surface (modernize), trim it (dead-params), then restructure (shrink, inline).
ALL_OBJECTIVES: tuple[str, ...] = ("modernize", "simplify-bool-return",
                                   "remove-dead-code", "dead-params",
                                   "shrink-functions", "inline-helpers")


# The objectives `apex develop session` runs — the combined BUYER artifact:
# land concrete value FIRST (implement stubs, wire exports, infer hints,
# dataclassify), THEN the idiom-modernizers (the `--all` set) to tidy the
# surface. This is a SEPARATE, opt-in list: the two high-value objectives
# `implement-stub` and `wire-exports` are flagged `expensive` and excluded from
# every automatic sweep, so a student/buyer otherwise has no single command that
# lands stubs + exports + hints + dataclass + modernizers and shows the combined
# verified diff. `apex develop session` OPTS THEM IN explicitly. This list is
# deliberately distinct from ``ALL_OBJECTIVES`` so the `--all`/`ascend` paths
# stay byte-identical — the session never changes what those sweep.
SESSION_OBJECTIVES: tuple[str, ...] = (
    "implement-stub", "wire-exports", "infer-type-hints", "dataclassify",
    "modernize", "simplify-bool-return", "remove-dead-code", "dead-params",
    "shrink-functions", "inline-helpers",
)


def _objectives_map() -> dict[str, tuple[Callable[[str | Path], float],
                                         Callable[[str | Path], list[Move]]]]:
    """The full objective table: the built-ins above plus every objective that
    self-registered under ``app/execution/objectives/`` (discovered once). A
    built-in always wins a name clash, so discovery can only ADD objectives —
    never silently change a built-in one."""
    from app.engine.develop_registry import registered_specs

    merged = {name: (spec.fitness, spec.moves)
              for name, spec in registered_specs().items()}
    merged.update(_OBJECTIVES)  # built-ins win the name clash
    return merged


def available_objectives() -> list[str]:
    """The objective names the compiler can pursue — built-in and discovered."""
    return list(_objectives_map())


# --- Natural-language intent vocabulary --------------------------------------
#
# A deterministic, table-driven phrase→objective map so a human (or an upstream
# idea) can name an objective the way they'd *say* it ("clean up the imports",
# "speed up", "lock down auth") instead of memorizing the exact registry key.
#
# Pure stdlib, no fuzzy match, no model: a phrase resolves only if one of these
# literal trigger substrings appears in the lowercased request. The map is
# APPEND-ONLY and is consulted ONLY when the request isn't already a known
# objective name (see ``resolve_objective``), so every objective that compiled a
# specific way before still resolves to itself, byte-for-byte unchanged. Earlier
# entries win ties, so a longer/more-specific phrase is listed before a shorter
# one that it contains. Every target on the right is a real built-in objective.
_OBJECTIVE_SYNONYMS: tuple[tuple[str, str], ...] = (
    # remove-dead-code: strike unreachable statements
    ("dead code", "remove-dead-code"),
    ("unreachable", "remove-dead-code"),
    ("remove dead", "remove-dead-code"),
    ("strip dead", "remove-dead-code"),
    # remove-unused-imports: drop dead top-level imports
    ("unused import", "remove-unused-imports"),
    ("dead import", "remove-unused-imports"),
    ("prune import", "remove-unused-imports"),
    ("drop import", "remove-unused-imports"),
    # sort-imports: group + alphabetize the import block
    ("sort import", "sort-imports"),
    ("order import", "sort-imports"),
    ("organize import", "sort-imports"),
    ("organise import", "sort-imports"),
    ("tidy import", "sort-imports"),
    ("clean up import", "sort-imports"),
    ("clean imports", "sort-imports"),
    # dead-params: drop never-read parameters
    ("dead param", "dead-params"),
    ("unused param", "dead-params"),
    ("unused argument", "dead-params"),
    ("never-read param", "dead-params"),
    ("drop param", "dead-params"),
    # shrink-functions: extract helpers from long functions
    ("shrink function", "shrink-functions"),
    ("long function", "shrink-functions"),
    ("split function", "shrink-functions"),
    ("break up", "shrink-functions"),
    ("extract method", "shrink-functions"),
    ("decouple", "shrink-functions"),
    ("untangle", "shrink-functions"),
    # inline-helpers: fold single-use indirection away
    ("inline", "inline-helpers"),
    ("indirection", "inline-helpers"),
    ("single-use helper", "inline-helpers"),
    ("fold helper", "inline-helpers"),
    # dedup: extract copy-pasted blocks to a shared helper
    ("duplicat", "dedup"),  # duplicate / duplication / duplicated
    ("copy-paste", "dedup"),
    ("copy paste", "dedup"),
    ("de-dup", "dedup"),
    ("dedupe", "dedup"),
    ("repeated block", "dedup"),
    # extract-constant: name a repeated magic literal
    ("magic constant", "extract-constant"),
    ("magic literal", "extract-constant"),
    ("magic number", "extract-constant"),
    ("name constant", "extract-constant"),
    ("extract constant", "extract-constant"),
    # simplify-bool-return: if c: return True ... -> return c
    ("boolean return", "simplify-bool-return"),
    ("bool return", "simplify-bool-return"),
    ("simplify return", "simplify-bool-return"),
    # simplify-comprehension: accumulator loop -> comprehension
    ("comprehension", "simplify-comprehension"),
    ("accumulator loop", "simplify-comprehension"),
    ("list build loop", "simplify-comprehension"),
    # modernize: == None / dead f-string / dict() tidy debt + broad "tidy" verbs.
    # Listed last so the specific phrases above win; these catch the generic
    # "make it nicer" asks that map best onto the surface-tidy lens.
    ("modernise", "modernize"),
    ("tidy", "modernize"),
    ("clean up", "modernize"),
    ("cleanup", "modernize"),
    ("clean code", "modernize"),
    ("simplify", "modernize"),
    ("refactor", "modernize"),
    ("optimize", "modernize"),
    ("optimise", "modernize"),
    ("speed up", "modernize"),
    ("faster", "modernize"),
    ("harden", "modernize"),
    ("fortify", "modernize"),
    ("secure", "modernize"),
    ("lock down", "modernize"),
    ("sanitize", "modernize"),
    ("sanitise", "modernize"),
)


def objective_synonyms() -> dict[str, list[str]]:
    """The phrase→objective vocabulary, grouped as ``objective: [trigger, ...]``
    for display/introspection. Deterministic; preserves declared order."""
    out: dict[str, list[str]] = {}
    for phrase, objective in _OBJECTIVE_SYNONYMS:
        out.setdefault(objective, []).append(phrase)
    return out


def resolve_objective(request: str | None) -> str | None:
    """Resolve a free-text objective request to a known objective NAME.

    An exact (case-insensitive) objective name always wins and resolves to
    itself — so the literal keys (``dead-params``, ``modernize``, …) never change
    meaning. Otherwise the request's lowercased text is scanned against the
    append-only synonym table and the FIRST matching trigger's objective is
    returned (earlier, more-specific phrases listed first). Returns ``None`` when
    nothing matches, so the caller can keep its existing "unknown objective"
    handling. Deterministic, stdlib-only, no fuzzy/LLM matching."""
    if not request:
        return None
    text = request.strip().lower()
    if not text:
        return None
    known = {name.lower(): name for name in available_objectives()}
    if text in known:
        return known[text]
    for phrase, objective in _OBJECTIVE_SYNONYMS:
        if phrase in text:
            return objective
    return None


def _move_module(move: "Move") -> str:
    """The module a move targets (the part before ':' in its target)."""
    return move.target.split(":", 1)[0]


def _resolve_compile_target(
    objective: str,
    objectives: dict[str, tuple[Callable[[str | Path], float],
                                Callable[[str | Path], list[Move]]]],
) -> tuple[str | None, CompileResult | None]:
    """Resolve ``objective`` to a runnable objective name in ``objectives``.

    A literal objective name resolves to itself. Otherwise the natural-language
    vocabulary ("clean up imports", "lock down auth", …) is consulted — an exact
    name already matched, so this can only RESOLVE an otherwise unknown request,
    never redirect a known one. Returns ``(name, None)`` when runnable, or
    ``(None, blocked_result)`` with the "unknown objective" CompileResult when
    nothing resolves."""
    if objective in objectives:
        return objective, None
    resolved = resolve_objective(objective)
    if resolved is not None and resolved in objectives:
        return resolved, None
    known = ", ".join(sorted(objectives))
    return None, CompileResult(
        objective=objective, fitness_start=0.0, fitness_end=0.0,
        blocked=[f"unknown objective '{objective}' (known: {known})"])


def _ordered_candidates(generate: Callable[[str | Path], list[Move]], root: str,
                        scope_module: str | None, memory: Any,
                        last_operator: str) -> list[Move]:
    """The candidate moves for one scan, scoped and sequence-ordered.

    Generates the objective's moves against the CURRENT tree, confines them to
    ``scope_module`` when set, then — when a move has already landed — orders
    them by the composition memory's learned sequence credit (a neutral 1.0 for
    unknown pairs keeps the order stable, so a fresh project is unchanged)."""
    moves = generate(root)
    if scope_module is not None:
        moves = [m for m in moves if _move_module(m) == scope_module]
    if last_operator:
        moves = sorted(
            moves, key=lambda m: -memory.sequence_factor(last_operator, m.operator))
    return moves


def _fill_dry_run(result: CompileResult, moves: list[Move], start: float,
                  max_steps: int) -> CompileResult:
    """List the moves available now (no writes, no suite runs) onto ``result``.

    Each move's plan is built once: a blocker is reported, a content-producing
    plan becomes a projected (unverified) step toward fitness ``start - 1``."""
    for mv in moves[:max_steps]:
        plan = mv.build_plan()
        if plan.blockers:
            result.blocked.append(f"{mv.target}: {plan.blockers[0]}")
        elif plan.new_contents:
            result.steps.append(CompileStep(
                operator=mv.operator, target=mv.target, description=mv.description,
                fitness_before=start, fitness_after=max(0.0, start - 1), verified=False))
    return result


def _apply_one_move(result: CompileResult, mv: Move, root: str, current: float,
                    verify: bool, scope_verify: bool) -> tuple[bool, float]:
    """Try to land one move against the CURRENT tree, recording its outcome.

    Builds the move's plan fresh (line numbers stay exact even as earlier moves
    in the pass edited the file). A blocked or empty plan, or a suite failure
    (auto-rolled-back), records the reason onto ``result`` and counts as not
    landed. A clean apply appends a CompileStep dropping fitness by one (these
    objectives are monotone). Returns ``(landed, new_fitness)``."""
    from app.execution.cross_file_rename import apply_rename

    plan = mv.build_plan()
    if plan.blockers or not plan.new_contents:
        if plan.blockers:
            result.blocked.append(f"{mv.target}: {plan.blockers[0]}")
        return False, current
    res = apply_rename(root, plan, verify=verify, impact_scope=scope_verify)
    if not res.get("applied"):
        # Suite failed (rolled back) or nothing applied — not a valid move.
        if res.get("reason"):
            result.blocked.append(f"{mv.target}: {res['reason']}")
        return False, current
    nxt = max(0.0, current - 1)
    result.steps.append(CompileStep(
        operator=mv.operator, target=mv.target, description=mv.description,
        fitness_before=current, fitness_after=nxt,
        verified=res.get("verified") is True,
        coverage=str(res.get("coverage") or "")))
    return True, nxt


def _run_pass(result: CompileResult, moves: list[Move], root: str, current: float,
              max_steps: int, verify: bool, scope_verify: bool,
              last_operator: str) -> tuple[bool, float, str]:
    """Apply every move in one pass's scan that still lands, in order.

    Each move's plan is re-derived against the CURRENT tree, so line numbers stay
    exact even as earlier moves in the same pass edit the file; a move whose
    precondition an earlier edit invalidated simply no-ops and is skipped. Stops
    at ``max_steps``. Returns ``(progressed, fitness, last_operator)`` — the last
    landed operator biases the next pass's move ordering."""
    progressed = False
    for mv in moves:
        if len(result.steps) >= max_steps:
            break
        landed, current = _apply_one_move(
            result, mv, root, current, verify, scope_verify)
        if landed:
            last_operator = mv.operator  # bias the next move's ordering
            progressed = True
    return progressed, current, last_operator


def _archive_campaign(result: CompileResult, root: str, objective: str,
                      start: float, end: float) -> None:
    """Record the whole verified campaign as a candidate elite in the MAP-Elites
    playbook (best composition per objective × operator-mix). Best-effort: never
    fails a good compile on a playbook write."""
    from app.engine.composition_archive import record_campaign
    try:
        record_campaign(
            root, objective, [s.operator for s in result.steps],
            start, end, len({_move_module_from_target(s.target) for s in result.steps}))
    except OSError:
        pass  # the playbook is best-effort; never fail a good compile on it


def compile_objective(project_root: str | Path, objective: str = "dead-params",
                      max_steps: int = 25, verify: bool = True,
                      apply: bool = True, scope_module: str | None = None,
                      scope_verify: bool = False) -> CompileResult:
    """Greedily compose verified moves toward ``objective``.

    Each iteration: regenerate candidate moves against the current tree, apply
    the first one that lands (suite-verified, auto-rolled-back on failure), and
    re-measure fitness. Stops at fixpoint (no candidate or none improving) or
    ``max_steps``. With ``apply=False`` it only reports the moves it WOULD make
    (no writes), measuring the projected fitness from the candidate count.

    ``scope_module`` confines the campaign to one module (a dream confluence,
    say): only moves targeting that module are composed, and fitness becomes the
    count of those scoped moves remaining — so the organism can clean up the one
    risky file its nightly dream flagged, not the whole project at once."""
    objectives = _objectives_map()
    objective_name, blocked = _resolve_compile_target(objective, objectives)
    if objective_name is None:
        return blocked  # type: ignore[return-value]  # set whenever name is None
    objective = objective_name

    # Effective gate scope = the caller's explicit ``scope_verify`` OR the
    # RESOLVED objective's own spec flag. The stub-FILLING objectives
    # (implement-stub, tdd-implement) opt into impact-scoped gating so a correct
    # per-module fill is not vetoed by an UNRELATED still-red module on a
    # multi-module project (the cross-module apply deadlock) — their baseline
    # suite is legitimately RED. The cheap tidy objectives leave the spec flag
    # False and keep full-suite gating. A maintain-only objective isn't in
    # ``registered_specs()`` (spec is None) → the passed param stands, unchanged.
    from app.engine.develop_registry import registered_specs
    spec = registered_specs().get(objective)
    effective_scope = scope_verify or bool(getattr(spec, "scope_verify", False))

    fitness, generate = objectives[objective]
    root = str(project_root)

    # The organism uses what it learned: when several move types are available,
    # prefer the operator that has historically LANDED best right after the last
    # one that landed (the composition memory's sequence credit). A neutral 1.0
    # for unknown pairs keeps the order stable — so a fresh project is unchanged.
    from app.engine.idea_memory import IdeaMemory
    memory = IdeaMemory.load(root)
    last_operator = ""

    def candidates() -> list[Move]:
        return _ordered_candidates(generate, root, scope_module, memory, last_operator)

    def measure() -> float:
        # Scoped runs measure the local debt (remaining scoped moves); a global
        # run trusts the objective's own project-wide fitness function.
        return float(len(candidates())) if scope_module is not None else fitness(root)

    start = measure()
    result = CompileResult(objective=objective, fitness_start=start, fitness_end=start,
                           applied=apply)

    if not apply:
        # Dry run: list the moves available now (no writes, no suite runs).
        return _fill_dry_run(result, candidates(), start, max_steps)

    # Greedy fixpoint, scanned PER PASS, not per move. A full project scan
    # (`candidates()`) is expensive on a large repo, so each pass scans once and
    # then applies every move that still lands — each move's plan is re-derived
    # against the CURRENT tree (build_plan is a thunk), so line numbers stay
    # exact even as earlier moves in the same pass edit the file. A move whose
    # precondition an earlier edit invalidated simply no-ops and is skipped; a
    # NEW opportunity an edit created is picked up on the next pass. Each landed
    # move clears one unit of debt, so fitness decrements by one (these
    # objectives are monotone) — no re-measure scan per step.
    current = start
    for _pass in range(max_steps + 1):
        if len(result.steps) >= max_steps:
            break
        moves = candidates()  # one scan per pass
        if not moves:
            break
        progressed, current, last_operator = _run_pass(
            result, moves, root, current, max_steps, verify, effective_scope,
            last_operator)
        if not progressed:
            break

    result.fitness_end = current
    _record_composition(result, root)
    if apply and result.steps:
        _archive_campaign(result, root, objective, start, current)
    return result


def _move_module_from_target(target: str) -> str:
    return target.split(":", 1)[0]


def compile_all(project_root: str | Path, max_steps: int = 25, verify: bool = True,
                apply: bool = True) -> list[CompileResult]:
    """Sweep EVERY objective in order — tidy, trim, then restructure the code —
    each its own suite-gated campaign. The one-shot "clean everything
    measurable" pass; returns one CompileResult per objective (skipping those
    already at zero, so the report shows only what actually had work)."""
    results: list[CompileResult] = []
    for objective in ALL_OBJECTIVES:
        result = compile_objective(project_root, objective=objective,
                                   max_steps=max_steps, verify=verify, apply=apply)
        if result.steps or result.fitness_start > 0:
            results.append(result)
    return results


def render_all_markdown(results: list[CompileResult]) -> str:
    """Render the multi-objective sweep as one report."""
    if not results:
        return "# Develop — all objectives\n\n_Nothing to do: every objective is already at zero._\n"
    total_moves = sum(len(r.steps) for r in results)
    total_gain = sum(r.fitness_start - r.fitness_end for r in results)
    lines = [f"# Develop — all objectives ({len(results)} with work)", "",
             f"**{total_moves} verified move(s)**, total fitness gain "
             f"**{total_gain:g}** across the sweep.", ""]
    for r in results:
        lines.append(render_compile_markdown(r))
    return "\n".join(lines)


def _record_composition(result: CompileResult, project_root: str) -> None:
    """Credit the applied move ordering to the composition memory, so the engine
    learns which operator sequences land (here: drop_param>drop_param chains)."""
    if not result.steps:
        return
    from app.engine.idea_memory import IdeaMemory

    summary = {"results": [{"operator": s.operator, "applied": True} for s in result.steps]}
    try:
        IdeaMemory.learn_from(summary, project_root)
    except OSError:
        pass  # learning is best-effort; never fail a successful compile on it


def _compile_tier_tag(s: CompileStep) -> str:
    """Honest per-move tag: a green suite is only "verified" when a test actually
    EXERCISED the change (function/module/test-change). A green-but-unreferencing
    suite (``coverage == none``) is disclosed as a weak tier, and a suite-less
    apply as ``no-suite`` — never blended with a genuine verified move."""
    if s.coverage_verified:
        return " ✅ tests pass (covered)"
    if s.verified:
        # Suite ran green but no test references the change — green proves nothing
        # about it. Disclose, never label "verified".
        return " ⚠️ applied — suite green but no test covers this move"
    return " ⚠️ no-suite — applied, nothing verified it"


def render_compile_markdown(result: CompileResult) -> str:
    """Render a compile campaign as a readable report.

    The headline splits the landed moves into genuinely test-COVERED ("verified")
    vs. green-but-unreferencing ("weak") vs. ``no-suite`` — the "N verified"
    count is only the moves a test actually exercised (never-fake-green: a
    green suite that never looked at the change is not counted as verified)."""
    verb = "Applied" if result.applied else "Would apply"
    landed = len(result.steps)
    verified = sum(1 for s in result.steps if s.coverage_verified)
    weak = sum(1 for s in result.steps if s.verified and not s.coverage_verified)
    no_suite = landed - verified - weak
    lines = [f"# Objective compile — `{result.objective}`", ""]
    if result.blocked and not result.steps:
        lines.append(f"_No improving move available. Fitness: {result.fitness_start:g}._")
    breakdown = f"{verb.lower()} {landed} move(s): {verified} verified"
    if weak:
        breakdown += f", {weak} weak (suite green but uncovered)"
    if no_suite:
        breakdown += f", {no_suite} no-suite"
    lines.append(
        f"Fitness {result.fitness_start:g} → **{result.fitness_end:g}** "
        f"({breakdown})."
    )
    lines.append("")
    for i, s in enumerate(result.steps, 1):
        tick = _compile_tier_tag(s)
        lines.append(f"{i}. {s.description} — {s.fitness_before:g}→{s.fitness_after:g}{tick}")
    if result.blocked:
        lines.append("")
        lines.append("## Blocked")
        for b in result.blocked[:10]:
            lines.append(f"- ⛔ {b}")
    lines.append("")
    return "\n".join(lines)


# --- Dream → action: render the dream-driven multi-module campaign -----------
# The dream→landing SEAM itself (dream_confluence_modules / compile_from_dream
# and their helpers) lives in ``app/engine/dream_landing.py`` so its imports of
# ``ascend`` and ``dream`` flow ONE-WAY (no import cycle through this module).
# Only this renderer stays here: it renders a CompileResult and pulls in nothing
# from ascend/dream, so it carries no cycle.

def render_from_dream_markdown(results: list[CompileResult],
                               modules: list[str]) -> str:
    """Render the dream-driven multi-module campaign."""
    if not modules:
        return ("# Develop from dream\n\n_The dream has graduated no confluence "
                "yet — run `apex dream --curate` over more nights first._\n")
    lines = [f"# Develop from dream — {len(modules)} confluence module(s)", "",
             "_The nightly dream flagged these files as risk confluences; "
             "here is the verified cleanup it composed for each._", ""]
    for module, result in zip(modules, results):
        lines.append(f"## `{module}`")
        lines.append(render_compile_markdown(result))
    return "\n".join(lines)
