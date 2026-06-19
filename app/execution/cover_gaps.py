"""Cover gaps — turn an UNTESTED module into the ACTION of writing a test.

The purest detection->action move in the develop family: where the auditors
SEE that a module has no test, this WRITES one. For a single module that lacks
a linked test, it synthesizes a *characterization* test (via
:mod:`app.execution.test_shield`) that pins the module's CURRENT behaviour and
proposes that brand-new file as the plan's only write.

Conservative by design — any ambiguity is a **blocker**, never a guess:
  - the test is generated only when the module can be honestly characterized
    (a public, blindly-callable function or constructible class); when nothing
    is safely exercisable the generator declines and this is an empty no-op
    plan, not a failure;
  - an existing ``tests/test_<stem>.py`` is NEVER overwritten — that path is a
    no-op too (the test net is already there);
  - the synthesized content must parse, or the whole plan blocks.

The proposed file is a NEW write: it goes in ``new_contents`` with no entry in
``originals`` (the file does not exist yet — the apply layer deletes a
never-existed file on rollback). Example/fixture/test subjects are excluded.
Deterministic, stdlib-only; reuses :class:`RenamePlan`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import RenamePlan
from app.execution.test_shield import generate_characterization_test

__all__ = ["plan_cover_gaps"]


def _is_fixture_path(path: str) -> bool:
    """Example/fixture/test code is excluded as a subject — its "behaviour" is
    boilerplate, not project logic. A local copy (like ``bool_return.py`` keeps)
    on purpose: importing this from health_score would risk an import cycle, and
    this module is meant to stay a self-contained transform."""
    p = path.replace("\\", "/").lower()
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def plan_cover_gaps(project_root: str | Path, module_rel: str) -> RenamePlan:
    """Build the single-module characterization-test plan, or its blockers.

    ``module_rel`` is a project-relative path (as produced by ``_py_files``).
    The plan's only write is a NEW ``tests/test_<stem>.py`` capturing the
    module's current behaviour. An empty plan means there is nothing to do (the
    module cannot be characterized, or a test already exists) — a no-op, not a
    failure."""
    plan = RenamePlan(old=module_rel, new="cover-gaps")

    if _is_fixture_path(module_rel):
        return plan  # not a characterization subject — empty no-op plan

    try:
        shield = generate_characterization_test(project_root, module_rel)
    except OSError:
        plan.blockers.append(f"cannot read {module_rel}")
        return plan
    except Exception as e:  # noqa: BLE001 — any generator failure is a blocker
        plan.blockers.append(f"{module_rel}: cannot generate a test ({e})")
        return plan

    if shield is None:
        return plan  # nothing to characterize / test already exists — no-op

    # Never overwrite an existing test (a second safety net on top of the
    # generator's own check): the test net is already in place — no-op.
    if (Path(project_root) / shield.test_path).exists():
        return plan

    try:
        ast.parse(shield.content)
    except (SyntaxError, RecursionError, MemoryError) as e:
        plan.blockers.append(
            f"{module_rel}: generated test would not parse ({e}) — blocked")
        return plan

    # A NEW file: it lands in new_contents only. Leaving originals empty is
    # correct — the file does not exist yet, and the apply layer deletes a
    # never-existed file on rollback.
    plan.new_contents[shield.test_path] = shield.content
    plan.edits_by_file[shield.test_path] = 1
    return plan
