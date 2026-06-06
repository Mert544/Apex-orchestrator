from __future__ import annotations


def _get_indent(line: str) -> str:
    stripped = line.lstrip()
    if stripped:
        return line[: line.index(stripped)]
    return line
