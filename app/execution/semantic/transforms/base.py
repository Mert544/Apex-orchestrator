from __future__ import annotations


class TransformError(Exception):
    """Base exception for semantic transform failures."""


def _get_indent(line: str) -> str:
    stripped = line.lstrip()
    if stripped:
        return line[: line.index(stripped)]
    return line
