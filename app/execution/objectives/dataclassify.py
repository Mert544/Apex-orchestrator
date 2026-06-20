"""Self-registering objective: dataclassify.

The boilerplate every student and team writes by hand: a class whose entire
``__init__`` is field-assignment noise — ``self.x = x`` for each parameter and
nothing else. Python's ``@dataclass`` generates exactly that constructor from a
list of typed fields, so the hand-written ``__init__`` is pure ceremony.
``dataclassify`` LANDS the cleaner, behaviour-equivalent form: it adds
``@dataclass`` (and ``from dataclasses import dataclass``), emits one field per
parameter (preserving order, the parameter's annotation if present, and its
default), and DELETES the redundant ``__init__``.

The strict detection + rewrite live in :mod:`app.execution.dataclass_rewrite`
(``rewrite_dataclasses``); this module names it as a develop objective, builds
the one-module plan, and registers itself with the develop registry.

The plan is suite-gated and auto-rolled-back by the same engine every objective
uses (``apply_rename`` runs the project's tests and restores the file on any
regression). Behaviour-equivalence is the contract: a class is converted ONLY
when its ``__init__`` is PURE ``self.x = x`` boilerplate — the one shape
``@dataclass`` provably reproduces (same positional/keyword construction, same
defaults, same attribute access). Any real ``__init__`` logic (a validation
``if``, a computed attribute, ``*args``/``**kwargs``, a base class) is REFUSED —
never a guess, never a fake-green. A mutable literal default becomes
``field(default_factory=...)`` so per-instance state stays correct. Test/fixture
files are refused outright. Deterministic, stdlib-only, zero-token, idempotent
(an already-``@dataclass`` class is untouched).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.dataclass_rewrite import rewrite_dataclasses
from app.execution.objectives._base import register_module_objective


def _is_fixture_path(path: str) -> bool:
    """Example/test/fixture files are REFUSED — Apex never edits the suite it is
    gated by (a local copy on purpose: this objective stays self-contained)."""
    p = path.replace("\\", "/").lower()
    name = Path(p).name
    return (
        p.startswith(("examples/", "example/", "tests/", "test/", "fixtures/"))
        or "/examples/" in p or "/tests/" in p or "/fixtures/" in p
        or name.startswith("test_") or name.endswith("_test.py")
        or name == "conftest.py"
    )


def plan_dataclassify(project_root: str | Path, module_rel: str):
    """Build the dataclassify plan for one module, or an empty no-op plan.

    Converts every pure boilerplate-``__init__`` top-level class in
    ``module_rel`` to a ``@dataclass``. Test/fixture files are refused (empty
    plan). An empty plan means nothing convertible here — a no-op, not a
    failure. The single write goes in ``new_contents`` with the original in
    ``originals`` so the verified-apply engine can roll it back if the suite
    regresses."""
    from app.execution.cross_file_rename import RenamePlan

    plan = RenamePlan(old=module_rel, new="dataclassify")
    if _is_fixture_path(module_rel):
        return plan  # never touch a test/fixture file

    rewrite = _rewrite_for(project_root, module_rel)
    if rewrite is not None:
        source, new_source = rewrite
        plan.originals[module_rel] = source
        plan.new_contents[module_rel] = new_source
        plan.edits_by_file[module_rel] = 1
    return plan


def _rewrite_for(
    project_root: str | Path, module_rel: str
) -> tuple[str, str] | None:
    """``(original_source, converted_source)`` for ``module_rel``, or ``None``
    when there is nothing to convert (unreadable, or no boilerplate class)."""
    path = Path(project_root) / module_rel
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None
    new_source = rewrite_dataclasses(source)
    if new_source is None or new_source == source:
        return None
    return source, new_source


register_module_objective(
    "dataclassify", plan_dataclassify,
    operator="dataclassify",
    description="convert pure-boilerplate __init__ classes to @dataclass in {rel}",
)
