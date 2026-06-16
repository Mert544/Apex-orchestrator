"""Deterministic comment-quality analyzer (no clock / random / network).

Two signals, computed purely from the source tree:

  (a) COMMENTED-OUT CODE — a dead-code smell. A ``#`` comment whose body, once
      stripped of the leading ``#``, parses as a Python statement (or has an
      unmistakable code *shape*) is almost certainly source someone disabled and
      forgot to delete. We are deliberately CONSERVATIVE: a false positive on a
      prose comment is worse than a miss, so a line is flagged ONLY when it both
      parses as code AND carries a code shape (``=`` / ``(`` / ``:`` / import
      keyword), and is not an obvious prose sentence or a recognized marker.

  (b) COMMENT-TO-CODE RATIO — per module and overall. Both extremes are
      informative: a near-zero ratio hints at under-documented logic; a very high
      ratio can hint at narration or large commented-out blocks.

Comments are located with :mod:`tokenize`, so a ``#`` *inside a string literal* is
never mistaken for a comment.

Public API: :func:`analyze_comment_quality`. Fixtures and tests are excluded so
the analyzer grades real product code only. Empty-safe and stdlib-only; reuses
:func:`app.engine.skip_dirs.iter_source_files` for worktree-safe traversal.

Commented-out detection rule (a line's text is the part AFTER ``#``):

  1. Strip the ``#`` and surrounding whitespace to get ``body``.
  2. SKIP recognized non-code markers, regardless of shape:
       - shebang (``#!...``, i.e. the comment started at column 0 with ``!``);
       - tool/typing directives: ``type:``, ``noqa``, ``pragma``, ``pylint:``,
         ``mypy:``, ``flake8:``, ``pyright:``, ``isort:``, ``fmt:``,
         ``coding:`` / ``-*- coding`` encoding lines;
       - task markers: ``TODO``, ``FIXME``, ``XXX``, ``HACK``, ``NOTE``,
         ``WARNING``, ``BUG`` (with or without a trailing colon);
       - lines that contain a URL (``http://`` / ``https://``).
  3. SKIP empty bodies and bodies that are a bare section divider (only
     punctuation, e.g. ``# -----``).
  4. Require a CODE SHAPE: the body must contain ``=``, ``(``, end with ``:``,
     or begin with an import keyword (``import`` / ``from``). A bare word or a
     plain sentence has none of these and is left alone.
  5. REJECT prose: if the body reads like a sentence — it ends with sentence
     punctuation (``.``, ``!``, ``?``) AND has no statement-terminal code, or it
     contains a run of >= 6 alphabetic words with no operator/bracket — treat it
     as prose, not code.
  6. CONFIRM with the parser: the body must ``ast.parse`` cleanly in ``exec``
     mode as exactly one statement (assignment, call/expr, ``def``/``class``,
     ``import``, ``return``, ``if``-header via the trailing colon, etc.). The
     parser is the final authority; the shape/prose gates above only suppress the
     parser's eagerness to accept short prose like ``do this`` (a call-less Expr).
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import iter_source_files

__all__ = ["CommentQuality", "analyze_comment_quality"]

# Cap on how many commented-out hits we surface. Determinism comes from a stable
# sort, not from collection order.
_MAX_COMMENTED_OUT = 20

# Markers that look code-ish but are intentional directives or notes, never dead
# code. Matched case-insensitively against the START of the comment body.
_MARKER_PREFIXES = (
    "type:", "noqa", "pragma", "pylint:", "mypy:", "flake8:", "pyright:",
    "isort:", "fmt:", "coding:", "todo", "fixme", "xxx", "hack", "note",
    "warning", "bug", "-*-",
)

# A code shape must be present before we even consult the parser.
_SHAPE_RE = re.compile(r"[=(]|:\s*$")
_IMPORT_RE = re.compile(r"^(import|from)\s+\w")
_URL_RE = re.compile(r"https?://")
# A body that is only punctuation / box-drawing — a section divider, not code.
_DIVIDER_RE = re.compile(r"^[\W_]+$")
# A "word" for the prose heuristic: an alphabetic run, possibly with an apostrophe.
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']*")
_SENTENCE_END = (".", "!", "?")


@dataclass
class CommentQuality:
    """Result of :func:`analyze_comment_quality`.

    Attributes:
        commented_out: up to :data:`_MAX_COMMENTED_OUT` dead-code hits, each
            ``{"module": str, "line": int, "text": str}`` (``text`` is the
            comment body without the ``#``), sorted by ``(module, line)``.
        module_ratios: per-module ``comment_lines / code_lines`` (root-relative
            module path -> float), where ``code_lines`` are non-blank, non-comment
            logical source lines. A module with zero code lines maps to ``0.0``.
        overall_ratio: total comment lines / total code lines across all scanned
            modules (``0.0`` when there is no code).
        files_scanned: number of modules actually analyzed (after exclusions/cap).
    """

    commented_out: list[dict] = field(default_factory=list)
    module_ratios: dict[str, float] = field(default_factory=dict)
    overall_ratio: float = 0.0
    files_scanned: int = 0


def _is_excluded(rel: Path) -> bool:
    """True for fixture/test modules — graded code only.

    A part named ``tests``/``fixtures``/``testdata`` anywhere in the path, or a
    filename matching ``test_*.py`` / ``*_test.py`` / ``conftest.py``.
    """
    parts = {p.lower() for p in rel.parts[:-1]}
    if parts & {"tests", "test", "fixtures", "fixture", "testdata"}:
        return True
    name = rel.name.lower()
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def _looks_like_prose(body: str) -> bool:
    """True if ``body`` reads like an English sentence rather than code.

    Conservative gate that runs BEFORE the parser, to stop short prose such as
    ``# do this thing`` (which ``ast.parse``s as a bare-name ``Expr``) from being
    misread as code. Two ways to qualify as prose:

      - it ends with sentence punctuation AND contains no ``=``/``(`` operator
        (so ``# x = compute(y).`` is still code, but ``# explains why.`` is prose);
      - it is a long natural run: >= 6 alphabetic words and no operator/bracket.
    """
    has_op = "=" in body or "(" in body
    if body.endswith(_SENTENCE_END) and not has_op:
        return True
    if not has_op:
        words = _WORD_RE.findall(body)
        if len(words) >= 6:
            return True
    return False


def _parses_as_code(body: str) -> bool:
    """True if ``body`` is exactly one parseable Python statement.

    A trailing ``:`` (an ``if``/``for``/``def`` header someone commented out)
    would make ``ast.parse`` raise on the missing suite, so for that shape we
    append a ``pass`` body before parsing. We require exactly ONE top-level
    statement: a multi-statement body is more likely coincidental prose with
    stray punctuation than a single disabled line.
    """
    candidate = body
    if body.endswith(":"):
        candidate = body + " pass"
    try:
        tree = ast.parse(candidate, mode="exec")
    except (SyntaxError, ValueError):
        return False
    return len(tree.body) == 1


def _is_commented_out_code(body: str, *, first_char_after_hash: str) -> bool:
    """Apply the full conservative rule to a single comment body.

    ``first_char_after_hash`` distinguishes a shebang (``#!``) cheaply without
    needing the original column.
    """
    if first_char_after_hash == "!":  # shebang
        return False
    stripped = body.strip()
    if not stripped:
        return False
    lower = stripped.lower()
    if any(lower.startswith(p) for p in _MARKER_PREFIXES):
        return False
    if _URL_RE.search(stripped):
        return False
    if _DIVIDER_RE.match(stripped):
        return False
    # Must carry a code shape (assignment / call / header / import).
    if not (_SHAPE_RE.search(stripped) or _IMPORT_RE.match(stripped)):
        return False
    if _looks_like_prose(stripped):
        return False
    return _parses_as_code(stripped)


def _analyze_source(source: str) -> tuple[list[tuple[int, str]], int, int]:
    """Tokenize ``source`` -> ``(hits, comment_lines, code_lines)``.

    ``hits`` are ``(line, body)`` for commented-out code. ``comment_lines`` counts
    lines bearing a comment token; ``code_lines`` counts distinct source lines that
    carry a non-trivial (non-comment, non-newline, non-indent) token. Using token
    rows means a trailing ``# ...`` on a code line counts toward BOTH a comment
    line and a code line, which is the honest reading of the ratio.
    """
    hits: list[tuple[int, str]] = []
    comment_rows: set[int] = set()
    code_rows: set[int] = set()
    reader = io.StringIO(source).readline
    try:
        for tok in tokenize.generate_tokens(reader):
            if tok.type == tokenize.COMMENT:
                row = tok.start[0]
                comment_rows.add(row)
                raw = tok.string
                # Body is everything after the first '#'. Record the char right
                # after '#' to detect shebangs before stripping.
                after = raw[1:]
                first = after[:1]
                body = after.strip()
                if _is_commented_out_code(body, first_char_after_hash=first):
                    hits.append((row, body))
            elif tok.type not in (
                tokenize.NEWLINE,
                tokenize.NL,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.ENCODING,
                tokenize.ENDMARKER,
                tokenize.COMMENT,
            ):
                code_rows.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        # Partial results from a malformed file are still useful and deterministic.
        pass
    return hits, len(comment_rows), len(code_rows)


def analyze_comment_quality(root: str | Path, max_files: int = 500) -> CommentQuality:
    """Analyze comment quality across the Python sources under ``root``.

    Walks ``root`` via :func:`iter_source_files` (worktree-safe, sorted),
    excludes test/fixture modules, and scans at most ``max_files`` files. Pure and
    deterministic: identical input trees yield byte-identical results, with no use
    of the clock, randomness, or the network.

    Returns an empty-safe :class:`CommentQuality`; a missing ``root`` yields the
    default (all-zero) result.
    """
    result = CommentQuality()
    root = Path(root)
    if not root.exists():
        return result

    total_comments = 0
    total_code = 0
    all_hits: list[tuple[str, int, str]] = []
    scanned = 0

    for path in iter_source_files(root):
        if scanned >= max_files:
            break
        rel = path.relative_to(root)
        if _is_excluded(rel):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1

        hits, comment_lines, code_lines = _analyze_source(source)
        rel_str = rel.as_posix()
        ratio = (comment_lines / code_lines) if code_lines else 0.0
        result.module_ratios[rel_str] = round(ratio, 4)
        total_comments += comment_lines
        total_code += code_lines
        for line, body in hits:
            all_hits.append((rel_str, line, body))

    result.files_scanned = scanned
    result.overall_ratio = round(total_comments / total_code, 4) if total_code else 0.0

    # Deterministic order, then cap.
    all_hits.sort(key=lambda h: (h[0], h[1], h[2]))
    result.commented_out = [
        {"module": m, "line": ln, "text": txt}
        for m, ln, txt in all_hits[:_MAX_COMMENTED_OUT]
    ]
    return result
