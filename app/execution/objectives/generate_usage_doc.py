"""Self-registering objective: generate-usage-doc.

The chore every student and team postpones: writing a ``USAGE.md`` for a package
so a newcomer can see, at a glance, what is public and how to call it. Apex LANDS
that doc — deterministically generated from the package's PUBLIC API alone: its
top-level public functions and classes, their SIGNATURES, the FIRST LINE of each
docstring, and any ``>>>`` doctest examples already written in those docstrings.
No prose is invented (zero-token / no-LLM); the doc only restates what the code
and its docstrings already declare.

The pure analysis lives in :mod:`app.execution.usage_doc` (``plan_usage_text``,
``render_usage_markdown``); this module names it as a develop objective, gates it
with a DOCTEST ORACLE, and registers itself with the develop registry.

The doctest oracle is the distinctive safety here: BEFORE the doc is allowed to
stand, every ``>>>`` example copied from a docstring is EXECUTED against the
imported package in a clean subprocess (:mod:`app.execution.doctest_oracle`). An
example that does not run green is OMITTED from the doc — the published doc never
shows a broken example, an honest under-claim rather than a fake-green. The
rendered doc's ``python`` code blocks are then re-parsed (``ast``) so the file is
guaranteed to carry only valid Python. That makes generate-usage-doc trustworthy
even on a project with NO test suite (its safety does not depend on a detectable
suite); where a suite exists, ``apply_rename``'s full-suite gate composes on top
with byte-for-byte rollback. The objective REFUSES a package with no public API
(nothing honest to document). Deterministic (sorted, no clock/random),
stdlib-only, zero-token, idempotent (a package whose ``USAGE.md`` already matches
is a byte-identical no-op), and it refuses test/fixture packages.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.develop_registry import ObjectiveSpec, register
from app.execution.cross_file_rename import RenamePlan
from app.execution.doctest_oracle import verify_examples
from app.execution.usage_doc import (
    plan_usage_text,
    python_code_blocks,
    render_usage_markdown,
)


def _code_blocks_parse(markdown: str) -> bool:
    """True iff every ```` ```python ```` block in the doc parses as valid Python
    — the doc is guaranteed never to ship un-runnable example code."""
    for block in python_code_blocks(markdown):
        try:
            compile(block, "<usage-doc>", "single" if ">>>" not in block else "exec")
        except (SyntaxError, ValueError):
            # Doctest blocks carry `>>>` prompts; strip them before parsing.
            stripped = _strip_doctest_prompts(block)
            try:
                ast.parse(stripped)
            except (SyntaxError, ValueError):
                return False
    return True


def _strip_doctest_prompts(block: str) -> str:
    """Drop ``>>>`` / ``...`` prompts (and expected-output lines) from a doctest
    block, leaving the bare source so it can be ``ast.parse``d."""
    out: list[str] = []
    for line in block.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(">>> ") or stripped.startswith("... "):
            out.append(line[line.index(stripped[:4]) + 4:])
        elif stripped in (">>>", "..."):
            out.append("")
    return "\n".join(out)


def plan_generate_usage_doc(project_root: str | Path, init_rel: str) -> RenamePlan:
    """Build the generate-usage-doc plan for one package, or an honest no-op.

    Collects the package's public API, runs every docstring ``>>>`` example
    through the doctest oracle, renders a ``USAGE.md`` keeping only proven
    examples, and verifies the rendered code blocks parse. A package with no
    public API, a refused test/fixture package, or a doc whose code blocks fail to
    parse all yield an EMPTY plan (a no-op refusal). When the package already
    carries a byte-identical ``USAGE.md`` the plan is empty too (idempotent). The
    single write goes in ``new_contents`` with the original in ``originals`` so the
    verified-apply engine can roll it back if a project suite regresses."""
    root = Path(project_root)
    rel = Path(init_rel)
    plan = RenamePlan(old=init_rel, new="generate-usage-doc")

    # First pass: collect the API (no oracle) to learn which symbols carry
    # examples worth executing.
    _, symbols = plan_usage_text(root, init_rel)
    if not symbols:
        return plan  # no public API — refuse, land nothing

    examples_by_symbol = {s.name: s.examples for s in symbols if s.examples}
    verified = verify_examples(root, init_rel, examples_by_symbol)
    usage = render_usage_markdown(rel.parent.name, symbols, verified)
    if usage is None or not _code_blocks_parse(usage):
        return plan  # nothing honest to land, or the doc's code would not parse

    doc_rel = (rel.parent / "USAGE.md").as_posix()
    try:
        original = (root / doc_rel).read_text(encoding="utf-8")
    except OSError:
        original = ""
    if usage == original:
        return plan  # already up to date — byte-identical no-op (idempotent)

    plan.originals[doc_rel] = original
    plan.new_contents[doc_rel] = usage
    plan.edits_by_file[doc_rel] = len(symbols)
    return plan


def _candidate_packages(project_root: str | Path) -> list[str]:
    """Every package ``__init__.py`` whose generate-usage-doc plan would change
    something — the targets the objective offers. Sorted for determinism."""
    from app.engine.skip_dirs import is_skipped, is_test_or_fixture_path

    root = Path(project_root)
    out: list[str] = []
    for path in sorted(root.rglob("__init__.py")):
        rel = path.relative_to(root)
        if is_skipped(rel) or is_test_or_fixture_path(rel.parent):
            continue
        if plan_generate_usage_doc(root, rel.as_posix()).new_contents:
            out.append(rel.as_posix())
    return out


def fitness(project_root: str | Path) -> float:
    """Fitness = how many packages still lack an up-to-date ``USAGE.md``.

    A package counts only when it has a public API whose doc would change — a
    package with nothing public to document never appears as remaining debt, an
    honest measure."""
    return float(len(_candidate_packages(project_root)))


def moves(project_root: str | Path) -> list:
    from app.engine.objective_compiler import Move

    return [Move(
        operator="generate_usage_doc",
        target=f"{rel}:generate-usage-doc",
        description=f"generate USAGE.md from the public API of {rel}",
        build_plan=lambda r=rel: plan_generate_usage_doc(project_root, r),
    ) for rel in _candidate_packages(project_root)]


# The fitness scan imports each candidate package in a subprocess (the doctest
# oracle), so it is heavyweight — flag it expensive so the fast plan/ascend board
# skips it (it stays runnable explicitly via
# `apex develop --objective generate-usage-doc`).
register(ObjectiveSpec(name="generate-usage-doc", fitness=fitness, moves=moves,
                       expensive=True))
