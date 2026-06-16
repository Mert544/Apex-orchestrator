"""Shared read-then-parse helper for single-module rewrite plans.

The transforms that build a :class:`RenamePlan` for one module all open with the
exact same two steps: read the module source (recording a blocker if it can't be
read) and parse it (recording a blocker if it won't parse). Either failure is a
clean early return with the plan as-is.

Hoisting this into one helper keeps that boilerplate in a single place. It reuses
the same ``read_module_source`` / ``parse_module_source`` primitives the callers
already used, so behaviour — including the exact blocker text those primitives
record onto ``plan`` — is byte-for-byte unchanged. Deterministic, stdlib-only.
"""

from __future__ import annotations

import ast

from pathlib import Path

from app.execution._transform_base import (
    parse_module_source as _parse_module_source,
    read_module_source as _read_module_source,
)


def read_and_parse(
    plan: object, project_root: str | Path, module_rel: str
) -> tuple[str, ast.Module] | None:
    """Read and parse ``module_rel`` for a plan, or ``None`` to early-return.

    On success returns ``(source, tree)``. On a read or parse failure returns
    ``None`` after the underlying primitive has recorded the appropriate blocker
    onto ``plan`` — the caller simply returns its plan unchanged.
    """
    source = _read_module_source(plan, project_root, module_rel)
    if source is None:
        return None
    tree = _parse_module_source(plan, module_rel, source)
    if tree is None:
        return None
    return source, tree
