"""Polyglot safe flag-action — annotate a non-Python risk without rewriting it.

Apex's Python security passes already prefer to FLAG rather than rewrite a risk
that has no behaviour-preserving auto-fix (Zip-Slip, disabled TLS, weak hash):
``_flag_call_site`` inserts a ``# SECURITY (...)`` comment above the offending
line and changes nothing else. This module carries that exact discipline to the
polyglot frontier — TypeScript/JavaScript, YAML, shell, and HTML files that
Apex's polyglot analysers can flag but cannot safely transform.

The action is **behaviour-preserving by construction**: the only edit is the
insertion of a single COMMENT line above the flagged line. A comment cannot
change what a program does, so there is no rewrite risk to reason about — the
worst case is a no-op annotation. The original line is preserved byte-for-byte;
only one comment line is added, carrying the target line's leading indentation so
the result stays well-formed (a YAML key, an HTML element, an indented JS block).

The comment syntax is chosen from the file extension:

  ``.ts`` ``.tsx`` ``.js`` ``.jsx``   ->  ``// Apex: <message>``
  ``.yaml`` ``.yml`` ``.sh``           ->  ``# Apex: <message>``
  ``.html``                            ->  ``<!-- Apex: <message> -->``

``flag_line`` DECLINES (returns ``None``) — never raises on valid ``str`` input —
when the extension is unsupported, the line is out of range, or the exact flag is
already present immediately above. That last guard makes the action idempotent:
flagging the same line twice yields the same text as flagging it once, so a
re-run never double-annotates. Everything here is pure, deterministic, and
offline — same inputs always produce the same output, with no clock or randomness.
"""

from __future__ import annotations

import os

# Extension -> (prefix, suffix). A line comment has an empty suffix; HTML wraps
# the message in a block comment. Lower-cased extensions only; the lookup
# normalises case so ``.YAML`` and ``.yaml`` map to the same syntax.
_SLASH = ("// Apex: ", "")
_HASH = ("# Apex: ", "")
_HTML = ("<!-- Apex: ", " -->")

_COMMENT_SYNTAX: dict[str, tuple[str, str]] = {
    ".ts": _SLASH,
    ".tsx": _SLASH,
    ".js": _SLASH,
    ".jsx": _SLASH,
    ".yaml": _HASH,
    ".yml": _HASH,
    ".sh": _HASH,
    ".html": _HTML,
}


def _syntax_for(path: str) -> tuple[str, str] | None:
    """Return the ``(prefix, suffix)`` comment syntax for ``path``'s extension.

    Returns None for an unsupported or missing extension so the caller can
    decline rather than guess.
    """
    ext = os.path.splitext(path)[1].lower()
    return _COMMENT_SYNTAX.get(ext)


def _indent_of(line: str) -> str:
    """The leading-whitespace prefix of ``line`` (without its newline)."""
    stripped = line.lstrip()
    return line[: len(line) - len(stripped)]


def _format_comment(path: str, indent: str, message: str) -> str | None:
    """Render the full flag line (indent + comment) for ``path``, or None.

    Returns None when the extension is unsupported. No trailing newline is added
    here; the caller appends the line terminator it wants.
    """
    syntax = _syntax_for(path)
    if syntax is None:
        return None
    prefix, suffix = syntax
    return f"{indent}{prefix}{message}{suffix}"


def is_flagged(source: str, line: int, message: str) -> bool:
    """True when the line ABOVE ``line`` (1-based) already carries this flag.

    The check is path-agnostic on purpose: it matches the rendered comment body
    (``// Apex: <message>`` / ``# Apex: <message>`` / ``<!-- Apex: <message> -->``)
    ignoring leading indentation, so any of the supported syntaxes is recognised.
    Used by ``flag_line`` to stay idempotent. Out-of-range lines are simply not
    flagged (returns False) — never raises.
    """
    lines = source.splitlines()
    if line < 2 or line > len(lines) + 1:
        return False
    above = lines[line - 2].strip()
    for prefix, suffix in (_SLASH, _HASH, _HTML):
        if above == f"{prefix}{message}{suffix}":
            return True
    return False


def flag_line(path: str, source: str, line: int, message: str) -> str | None:
    """Insert a REVIEW-FLAG comment above ``line`` (1-based) of ``source``.

    Returns the new source, or None (decline) when:
      - ``path``'s extension is unsupported,
      - ``line`` is out of range (``< 1`` or past the last line), or
      - the exact flag is already present immediately above (idempotent).

    The inserted comment uses the file's comment syntax and the target line's
    leading indentation. Only one line is added; the target line and every other
    line are preserved unchanged, so the edit is behaviour-preserving. Never
    raises on valid ``str`` inputs.
    """
    syntax = _syntax_for(path)
    if syntax is None:
        return None
    lines = source.splitlines(keepends=True)
    if line < 1 or line > len(lines):
        return None
    if is_flagged(source, line, message):
        return None
    target = lines[line - 1]
    comment = _format_comment(path, _indent_of(target), message)
    if comment is None:  # pragma: no cover - guarded by _syntax_for above
        return None
    new_lines = list(lines)
    new_lines.insert(line - 1, comment + "\n")
    return "".join(new_lines)
