"""Deterministic logging-hygiene analyzer for library (non-entrypoint) code.

Application library code should *log*, not print, and should let the logging
framework decide whether a message is worth formatting. Three habits violate
that and this analyzer flags them, conservatively, by static AST inspection:

  - ``print``        — a bare ``print(...)`` call in library code. Diagnostics
    belong in a logger (level-controllable, redirectable, structured); a print
    is invisible to handlers and noisy in production. Excluded where printing is
    legitimate: ``__main__`` guards and entrypoint/CLI modules (see below).

  - ``eager_format`` — an *eagerly* interpolated string passed as the message
    argument of a logging call: ``logger.info(f"x={x}")``,
    ``logger.info("x=%s" % x)``, or ``logger.info("x={}".format(x))``. Lazy
    logging (``logger.info("x=%s", x)``) pays the format cost only when the
    level is enabled; eager interpolation always pays it, defeating the point.
    A plain non-f string literal (``logger.info("done")``) is fine.

  - ``error_outside_except`` — ``logger.error(...)`` / ``logger.exception(...)``
    (and ``logging.error`` / ``logging.exception``) not lexically inside an
    ``except`` block. ``exception`` outside ``except`` has no active exception
    to attach; ``error`` outside an error path is usually a mis-levelled
    message. This is a HEURISTIC: it only inspects lexical nesting within the
    same module, so an error logged from a helper *called* inside ``except`` is
    (intentionally) not credited.

A "logging call" is a ``Call`` whose ``func`` is an ``Attribute`` (method) whose
attribute name is a logging level (``debug``/``info``/``warning``/``warn``/
``error``/``exception``/``critical``/``fatal``/``log``) and whose receiver is a
``Name`` that looks like a logger (``log``/``logger``/``logging``/``LOG``/
``LOGGER``) or a ``self.<logger-name>`` attribute access. This name heuristic
avoids false positives on unrelated ``.info`` attributes.

Excluded files (printing/entrypoint conventions make flags there noise):

  - modules named like an entrypoint/CLI: ``main.py``, ``__main__.py``,
    ``cli.py``, or any ``cli*.py`` / ``*_cli.py``;
  - test/example/fixture modules (``tests/``, ``test_*.py``, ``examples/``,
    ``fixtures/``).

And within any scanned file, code lexically under an ``if __name__ ==
"__main__":`` guard is skipped wholesale (its prints and logging are entrypoint
behaviour).

Pure and offline: no clock, no random, no network, no filesystem writes; the
same tree always yields the same :class:`LoggingHygiene`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.skip_dirs import iter_source_files

__all__ = ["LoggingHygiene", "analyze_logging_hygiene"]

# How many offenders to surface. Enough to act on, capped so a sloppy tree does
# not emit a thousand-line list.
_OFFENDER_CAP = 20

# Logging level methods that constitute a "logging call".
_LOG_LEVELS = frozenset({
    "debug", "info", "warning", "warn", "error",
    "exception", "critical", "fatal", "log",
})

# Logging level methods whose use OUTSIDE an except block is suspicious.
_ERROR_LEVELS = frozenset({"error", "exception"})

# Receiver names that look like a logger object.
_LOGGER_NAMES = frozenset({"log", "logger", "logging", "LOG", "LOGGER"})


@dataclass
class LoggingHygiene:
    """Logging-hygiene findings for a project's library code.

    The three counts are totals across all scanned modules. ``offenders`` lists
    individual findings as ``{"module", "line", "kind"}`` dicts (``kind`` is one
    of ``"print"``, ``"eager_format"``, ``"error_outside_except"``), sorted
    deterministically and capped at :data:`_OFFENDER_CAP`. An empty or missing
    tree yields all-zero counts and an empty list.
    """

    print_calls: int = 0
    eager_format_calls: int = 0
    error_outside_except: int = 0
    offenders: list[dict] = field(default_factory=list)


def _is_entrypoint_module(stem: str) -> bool:
    """True for files whose name suggests a CLI/entrypoint, where ``print`` and
    top-level logging are conventional rather than a smell."""
    if stem in {"main", "__main__", "cli"}:
        return True
    return stem.startswith("cli") or stem.endswith("_cli")


def _is_excluded_path(rel: str) -> bool:
    """Test/example/fixture modules are excluded — their logging habits say
    nothing about the project's library discipline."""
    p = rel.replace("\\", "/").lower()
    return (
        p.startswith(("tests/", "test/", "examples/", "example/", "fixtures/"))
        or "/tests/" in p or "/test/" in p
        or "/examples/" in p or "/example/" in p or "/fixtures/" in p
        or Path(p).name.startswith("test_")
    )


def _is_main_guard(node: ast.AST) -> bool:
    """True if ``node`` is an ``if __name__ == "__main__":`` statement, so its
    body can be skipped wholesale (entrypoint behaviour)."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.comparators) != 1:
        return False
    left, right = test.left, test.comparators[0]
    name_is_dunder = isinstance(left, ast.Name) and left.id == "__name__"
    right_is_main = isinstance(right, ast.Constant) and right.value == "__main__"
    # Also accept the reversed form: "__main__" == __name__.
    left_is_main = isinstance(left, ast.Constant) and left.value == "__main__"
    name_is_right = isinstance(right, ast.Name) and right.id == "__name__"
    return (name_is_dunder and right_is_main) or (left_is_main and name_is_right)


def _logger_method(call: ast.Call) -> str | None:
    """Return the level-method name if ``call`` is a logging call, else ``None``.

    A logging call is ``<receiver>.<level>(...)`` where ``<level>`` is in
    :data:`_LOG_LEVELS` and ``<receiver>`` looks like a logger: a bare name in
    :data:`_LOGGER_NAMES`, or a ``self.<logger-name>`` attribute access.
    """
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr not in _LOG_LEVELS:
        return None
    recv = func.value
    if isinstance(recv, ast.Name) and recv.id in _LOGGER_NAMES:
        return func.attr
    # self.log / self.logger style receivers.
    if (
        isinstance(recv, ast.Attribute)
        and recv.attr in _LOGGER_NAMES
        and isinstance(recv.value, ast.Name)
    ):
        return func.attr
    return None


def _message_arg(call: ast.Call, level: str) -> ast.expr | None:
    """The positional message argument of a logging call, or ``None``.

    For ``logger.log(level, msg, ...)`` the message is the SECOND positional
    arg; for every other level it is the first. Keyword-only or no-arg calls
    have no message to inspect.
    """
    pos = [a for a in call.args if not isinstance(a, ast.Starred)]
    idx = 1 if level == "log" else 0
    if len(pos) <= idx:
        return None
    return pos[idx]


def _is_eager_format(msg: ast.expr) -> bool:
    """True if ``msg`` eagerly interpolates: an f-string with fields, a ``%``
    on a string literal, or a ``"...".format(...)`` call.

    An f-string with no replacement fields (a constant ``JoinedStr``) is not
    flagged — it costs nothing and behaves like a plain literal.
    """
    # f-string with at least one {field}.
    if isinstance(msg, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in msg.values)
    # "literal %s" % args  (only when the left side is a string literal).
    if (
        isinstance(msg, ast.BinOp)
        and isinstance(msg.op, ast.Mod)
        and isinstance(msg.left, ast.Constant)
        and isinstance(msg.left.value, str)
    ):
        return True
    # "literal {}".format(...)  — Attribute .format on a string literal.
    if (
        isinstance(msg, ast.Call)
        and isinstance(msg.func, ast.Attribute)
        and msg.func.attr == "format"
        and isinstance(msg.func.value, ast.Constant)
        and isinstance(msg.func.value.value, str)
    ):
        return True
    return False


class _ModuleVisitor(ast.NodeVisitor):
    """Walks one module, collecting offenders. Tracks ``except``-block depth so
    error/exception logging can be classified, and skips ``__main__`` guards."""

    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.offenders: list[dict] = []
        self._except_depth = 0

    def visit_If(self, node: ast.If) -> None:
        if _is_main_guard(node):
            # Entrypoint behaviour — skip the guarded body, but still walk the
            # ``orelse`` (e.g. an ``else`` that is normal library code).
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._except_depth += 1
        self.generic_visit(node)
        self._except_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        self._classify_call(node)
        self.generic_visit(node)

    def _classify_call(self, node: ast.Call) -> None:
        func = node.func
        # Bare print(...).
        if isinstance(func, ast.Name) and func.id == "print":
            self.offenders.append(
                {"module": self.rel, "line": node.lineno, "kind": "print"}
            )
            return
        level = _logger_method(node)
        if level is None:
            return
        msg = _message_arg(node, level)
        if msg is not None and _is_eager_format(msg):
            self.offenders.append(
                {"module": self.rel, "line": node.lineno, "kind": "eager_format"}
            )
        if level in _ERROR_LEVELS and self._except_depth == 0:
            self.offenders.append(
                {
                    "module": self.rel,
                    "line": node.lineno,
                    "kind": "error_outside_except",
                }
            )


def analyze_logging_hygiene(
    root: str | Path, max_files: int = 500
) -> LoggingHygiene:
    """Scan library code under ``root`` for logging-hygiene offences.

    Walks every non-excluded ``*.py`` file (skipping VCS/cache/worktree dirs via
    :func:`iter_source_files`, plus entrypoint/CLI modules via
    :func:`_is_entrypoint_module` and test/example/fixture modules via
    :func:`_is_excluded_path`). At most ``max_files`` files are parsed, applied
    AFTER filtering so the cap is deterministic. Within each file ``__main__``
    guards are skipped. Returns a :class:`LoggingHygiene`; an empty or missing
    tree yields an all-zero, empty result.
    """
    root = Path(root)
    offenders: list[dict] = []

    if root.exists():
        scanned = 0
        for path in iter_source_files(root):
            if scanned >= max_files:
                break
            rel = str(path.relative_to(root))
            if _is_excluded_path(rel):
                continue
            if _is_entrypoint_module(path.stem):
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(source)
            except (SyntaxError, OSError, ValueError, RecursionError, MemoryError):
                continue
            scanned += 1
            visitor = _ModuleVisitor(rel)
            visitor.visit(tree)
            offenders.extend(visitor.offenders)

    print_calls = sum(1 for o in offenders if o["kind"] == "print")
    eager = sum(1 for o in offenders if o["kind"] == "eager_format")
    err_outside = sum(1 for o in offenders if o["kind"] == "error_outside_except")

    # Deterministic ordering: module path, then line, then kind. Cap last so the
    # surfaced offenders are stable regardless of walk order.
    offenders.sort(key=lambda o: (o["module"], o["line"], o["kind"]))

    return LoggingHygiene(
        print_calls=print_calls,
        eager_format_calls=eager,
        error_outside_except=err_outside,
        offenders=offenders[:_OFFENDER_CAP],
    )
