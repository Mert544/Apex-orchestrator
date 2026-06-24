"""Self-registering objective: wire-module-exports.

Land a module-level ``__all__ = [...]`` on a leaf LIBRARY ``.py`` module that
DEFINES public symbols but never declares one — the explicit public-surface line a
student or team writes by hand on a maturing module. Where a linter only NOTES the
missing ``__all__``, this WRITES it: ``__all__`` pinned to the module's DEFINED
public names (every top-level public ``def`` / ``class`` / simple assignment),
EXCLUDING imports, inserted after any shebang / PEP-263 coding line, the docstring,
and the import block.

This is the LEAF-MODULE sibling of ``wire-exports`` — distinct surface. wire-exports
populates a PACKAGE ``__init__.py`` with ``from .module import Name`` re-exports;
this declares the ``__all__`` of a module that defines its public symbols DIRECTLY,
adding no imports and re-exporting nothing.

The detection + minimal rewrite live in :mod:`app.execution.module_exports`
(``add_module_all``). It reuses the shared single-file ``plan_source_rewrite``
(refuse test/fixture, read, run the transform, record the one in-place rewrite with
its original so the verified-apply engine can roll it back), with two layers added
over the bare shape:

  - ELIGIBILITY (pilot defect #2): a plan-layer gate, applied BEFORE the shared
    rewrite, refuses a file that is not an importable LIBRARY module. A file whose
    CONTAINING directory has no ``__init__.py`` (a top-level ``setup.py``,
    ``docs/conf.py``, a loose script) is refused — UNLESS the file itself IS an
    ``__init__.py`` (a package's own ``__init__`` is a library module). A small
    denylist of known non-library scripts (``setup.py``, ``conf.py``,
    ``conftest.py``, ``manage.py``, ``noxfile.py``, ``tasks.py``, ``_version.py``,
    ``version.py``) is refused even inside a package — an ``__all__`` there is
    config / side-effect / generated-file noise.
  - SOUNDNESS (the star-set shrink): the transform is a closure that hands
    ``add_module_all`` the module's ``module_rel`` and the WHOLE-PROJECT
    (tests-INCLUSIVE, via ``all_module_sources`` — the same over-approximate scan
    add-final / seal-final-method use) source set; it lands the change only when no
    ``from <thismodule> import *`` consumer exists project-wide, else it refuses.

The existing test/fixture refusal (inside ``plan_source_rewrite`` via
``_is_fixture_path``) is kept intact, layered UNDER the eligibility gate. Soundness
is otherwise STRUCTURAL: ``__all__`` is consulted ONLY by ``from module import *``,
and either the emitted set equals the default star set (no imported publics) or a
whole-project scan proves no consumer observes the shrink — behaviour-identical,
independent of any test suite. The transform REFUSES (a no-op) a module that already
declares ``__all__`` (idempotent), one with a ``from x import *``, a walrus, no
DEFINED public names, an unmodelled top-level binder, a provable star consumer of a
shrunk set, or unparseable source. Deterministic, stdlib-only, zero-token,
idempotent (a second run sees the ``__all__`` it landed and is a byte-identical
no-op).
"""

from __future__ import annotations

from pathlib import Path

from app.execution.cross_file_rename import RenamePlan, plan_source_rewrite
from app.execution.freeze_dataclass import all_module_sources
from app.execution.module_exports import add_module_all
from app.execution.objectives._base import register_module_objective

# Known NON-LIBRARY scripts: packaging / Sphinx / task-runner / framework-manage /
# generated version files. They may live inside a package (so the dir has an
# ``__init__.py``), yet nobody ``import``s them for an API — an ``__all__`` there is
# pure noise (pilot defect #2). Kept deliberately small and explicit.
_SCRIPT_DENYLIST = frozenset({
    "setup.py", "conf.py", "conftest.py", "manage.py",
    "noxfile.py", "tasks.py", "_version.py", "version.py",
})


def _is_library_module(project_root: Path, module_rel: str) -> bool:
    """True when ``module_rel`` is an importable LIBRARY module worth an ``__all__``.

    Eligible iff (the containing directory has an ``__init__.py``) OR (the file
    itself is named ``__init__.py`` — a package's own ``__init__`` is a library
    module even though its directory "contains" it), AND the basename is not a
    known non-library script. This refuses a root ``setup.py`` / ``docs/conf.py`` /
    a loose top-level script (no ``__init__.py`` beside it) and refuses a denylisted
    script even inside a package. Pure path test — the file need not be readable
    here; the shared rewrite reads it next."""
    rel = Path(module_rel.replace("\\", "/"))
    if rel.name in _SCRIPT_DENYLIST:
        return False
    if rel.name == "__init__.py":
        return True
    return (project_root / rel.parent / "__init__.py").exists()


def plan_wire_module_exports(
    project_root: str | Path, module_rel: str
) -> RenamePlan:
    """Build the wire-module-exports plan for one module, or an honest no-op.

    A plan-layer eligibility gate (pilot defect #2) refuses a NON-library file —
    its containing dir lacks an ``__init__.py`` and it is not itself one, or it is a
    denylisted script — BEFORE delegating to the shared single-file
    ``plan_source_rewrite`` (which keeps the test/fixture refusal, reads, runs the
    transform, and records the one in-place rewrite with its original so the
    verified-apply engine can roll it back). The transform is a closure that, like
    add-final / seal-final-method, gathers the WHOLE-PROJECT (tests-INCLUSIVE,
    ``all_module_sources``) source set and the module's ``module_rel`` so
    ``add_module_all`` can prove the star-set shrink safe (no project star consumer)
    before landing. An empty plan means nothing to do here — not a library module,
    already declares ``__all__``, a star import, a walrus, no DEFINED public names,
    an unmodelled binder, a provable star consumer of the shrunk set, or unparseable
    — a no-op, not a failure."""
    root = Path(project_root)
    if not _is_library_module(root, module_rel):
        return RenamePlan(old=module_rel, new="wire_module_exports")  # defect #2

    def _transform(source: str) -> str | None:
        sources = all_module_sources(project_root, module_rel, source)
        return add_module_all(
            source, module_rel=module_rel, project_sources=sources)

    return plan_source_rewrite(
        project_root, module_rel, "wire_module_exports", _transform)


register_module_objective(
    "wire-module-exports", plan_wire_module_exports,
    operator="wire_module_exports",
    description="declare __all__ in {rel}",
)
