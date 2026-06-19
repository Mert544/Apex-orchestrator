"""Flag network calls made without a ``timeout=`` (Bandit B113).

``requests.get(url)`` / ``urllib.request.urlopen(url)`` / ``httpx.get(url)``
with no ``timeout=`` can block forever if the peer never responds — a common
production hang. There is no universally-safe default timeout to inject (the
right value is request-specific), so we annotate the call site with a comment
rather than rewriting it, exactly like the pickle/SQL flag transforms.

Detection is AST-based and conservative (see
``app.engine.detectors._is_network_call_without_timeout``): only the clear
``requests``/``httpx``/``urllib.request`` owners are flagged, so an ambiguous
``session.get(...)`` is left alone.
"""

from __future__ import annotations

import ast

from app.engine.detectors import _is_network_call_without_timeout

from ..result import SemanticPatchResult

_MARKER = "Apex: add a timeout="


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_network_call_without_timeout(node):
            continue

        lineno = node.lineno
        lines = source.splitlines(keepends=True)
        if lineno > len(lines):
            continue
        line_content = lines[lineno - 1]
        prev_line = lines[lineno - 2] if lineno >= 2 else ""
        if _MARKER in line_content or _MARKER in prev_line:
            continue  # already flagged (comment sits on the preceding line)
        indent = line_content[: len(line_content) - len(line_content.lstrip())]
        warning = (
            f"{indent}# RELIABILITY (Apex: add a timeout= to avoid hanging "
            f"forever)\n"
        )
        new_lines = list(lines)
        new_lines.insert(lineno - 1, warning)
        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": "".join(new_lines),
                "expected_old_content": source,
            }],
            transform_type="flag_net_timeout",
            rationale=[
                f"Flagged a network call without timeout= in {rel_path} "
                f"(can hang forever)."
            ],
        )
    return None
