"""Fix B904: ``raise X(...)`` inside ``except E as err:`` → ``raise X(...) from err``.

Raising a fresh exception inside an except block without ``from`` discards the
original traceback chain. When the handler *binds* the caught exception, adding
``from <name>`` is a pure, behavior-safe append (the chain is restored; nothing
else changes). Handlers without a binding are left alone — inventing a binding
would be a bigger edit than this transform promises.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None

    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler) or not handler.name:
            continue
        target = _first_fixable_raise(handler.body)
        if target is None:
            continue

        seg = ast.get_source_segment(source, target)
        if not seg or "\n" in seg:
            continue  # multi-line raise: line surgery would be fragile — skip
        lines = source.splitlines(keepends=True)
        idx = target.lineno - 1
        if idx >= len(lines) or seg not in lines[idx]:
            continue
        new_lines = list(lines)
        new_lines[idx] = lines[idx].replace(seg, f"{seg} from {handler.name}", 1)

        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": "".join(new_lines),
                "expected_old_content": source,
            }],
            transform_type="raise_with_from",
            rationale=[
                f"Chained the re-raised exception to its cause (`from {handler.name}`) "
                f"in {rel_path}, preserving the original traceback."
            ],
        )

    return None


def _first_fixable_raise(body: list) -> ast.Raise | None:
    """The first ``raise Ctor(...)`` without a cause, in handler scope.

    Mirrors the detector's walk: nested functions/classes/try blocks are their
    own contexts and are skipped.
    """
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Try)):
            continue
        if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call) and stmt.cause is None:
            return stmt
        if isinstance(stmt, (ast.If, ast.For, ast.While, ast.With, ast.AsyncFor, ast.AsyncWith)):
            found = _first_fixable_raise(stmt.body) or _first_fixable_raise(
                getattr(stmt, "orelse", [])
            )
            if found is not None:
                return found
    return None
