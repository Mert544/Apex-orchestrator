"""Confirm or refute static dead-code findings by observing your own tests run.

A static "this symbol is never called" finding is a *guess*: it can't see
``getattr`` dispatch, plugin registries, entry points or test-only use. This
module closes that gap deterministically with the standard-library ``trace``
module (NOT coverage.py — stdlib only, no third-party deps): it runs a callable
that exercises the target, records every executed ``(file, line)`` pair, and
then *confirms* a static finding (the def line really never ran), *refutes* it
(the def line did run, so the static guess is a false positive), or leaves it
``static-only`` (the file was never loaded, so runtime can't say). No LLM — an
LLM structurally cannot observe what a project's tests actually execute.
"""

from __future__ import annotations

import os
import trace as _trace
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "RuntimeEvidence",
    "StaticFinding",
    "ConfirmedFinding",
    "trace_callable",
    "confirm_findings",
]


def _norm(path: str) -> str:
    """Absolute, symlink-resolved path so static and runtime keys compare equal."""
    return os.path.realpath(os.path.abspath(path))


@dataclass(frozen=True)
class RuntimeEvidence:
    """Immutable record of which ``(file, line)`` pairs actually executed.

    Deterministic: filenames are normalised to absolute real paths and the set
    is frozen, so ``executed_lines`` / ``was_executed`` give stable answers.
    """

    executed: frozenset[tuple[str, int]]

    def was_executed(self, path: str, lineno: int) -> bool:
        """True if ``lineno`` of ``path`` ran (path normalised before lookup)."""
        return (_norm(path), lineno) in self.executed

    def executed_lines(self, path: str) -> frozenset[int]:
        """Every executed line number recorded for ``path`` (possibly empty)."""
        target = _norm(path)
        return frozenset(line for f, line in self.executed if f == target)

    def has_evidence_for(self, path: str) -> bool:
        """True if *any* line of ``path`` was observed (i.e. the file loaded)."""
        target = _norm(path)
        return any(f == target for f, _ in self.executed)


@runtime_checkable
class StaticFindingLike(Protocol):
    """Duck-typed input: anything carrying a file path, def line and symbol."""

    path: str
    lineno: int
    symbol: str


@dataclass(frozen=True)
class StaticFinding:
    """A static finding to be confirmed/refuted: a symbol at ``path``:``lineno``.

    ``body_lines`` is the optional set of the symbol's *use-only* line numbers —
    lines that run only when the symbol is actually exercised (a function's body
    statements, a class's method bodies), NOT the ``def``/``class`` header or
    class-level statements, which run at import even for never-used symbols. When
    supplied, :func:`confirm_findings` keys on these instead of the def line,
    which is the only honest runtime signal of deadness (see that function).
    """

    path: str
    lineno: int
    symbol: str
    body_lines: frozenset[int] = frozenset()


@dataclass(frozen=True)
class ConfirmedFinding:
    """A static finding annotated with runtime ``confidence``.

    ``confidence`` is one of:
      - ``"runtime-confirmed"`` — the file ran under the evidence but the
        symbol's use-only body never did (static finding strengthened);
      - ``"refuted"`` — the symbol's body executed (it *is* used at runtime; the
        static finding is a false positive);
      - ``"static-only"`` — no runtime evidence for the file (or no use-only
        body lines to observe), so runtime can neither confirm nor refute.
    """

    path: str
    lineno: int
    symbol: str
    confidence: str


def trace_callable(
    target: Callable[[], Any] | Iterable[Callable[[], Any]],
) -> RuntimeEvidence:
    """Run ``target`` under ``trace.Trace(count=True, trace=False)`` and return
    the set of executed ``(abs_real_path, lineno)`` pairs.

    ``target`` may be a single zero-arg callable or an iterable of them (each
    "exercises the target" in turn). Determinism: the result depends only on
    which lines the callables run, not on time or order of iteration.
    """
    if callable(target):
        callables: list[Callable[[], Any]] = [target]
    else:
        callables = list(target)

    tracer = _trace.Trace(count=True, trace=False)
    for fn in callables:
        tracer.runfunc(fn)

    results = tracer.results()
    executed = {
        (_norm(filename), lineno)
        for (filename, lineno) in results.counts
    }
    return RuntimeEvidence(executed=frozenset(executed))


def confirm_findings(
    findings: Iterable[StaticFindingLike],
    evidence: RuntimeEvidence,
) -> list[ConfirmedFinding]:
    """Annotate each static finding with a runtime ``confidence`` label.

    The honest signal of deadness is whether the symbol's *use-only* body ran —
    NOT its ``def`` line. A ``def``/``class`` header (and a class's body) runs at
    import even for a never-used symbol, so keying on the def line would label
    *everything* in an imported module ``"refuted"``. When a finding carries
    ``body_lines`` (the lines that run only on use), we key on those:
      - any body line executed                          -> ``"refuted"``
      - the file ran but no body line did               -> ``"runtime-confirmed"``
      - the file has no evidence (or no body lines)      -> ``"static-only"``
    A finding with no ``body_lines`` falls back to the def-line rule (best a
    generic caller can do without body information).

    Pure and deterministic: outputs are sorted by ``(path, lineno, symbol)`` and
    paths in the result are the findings' original (un-normalised) values.
    """
    out: list[ConfirmedFinding] = []
    for f in findings:
        path, lineno, symbol = f.path, f.lineno, f.symbol
        body_lines = getattr(f, "body_lines", None) or frozenset()
        if body_lines:
            if any(evidence.was_executed(path, ln) for ln in body_lines):
                confidence = "refuted"
            elif evidence.has_evidence_for(path):
                confidence = "runtime-confirmed"
            else:
                confidence = "static-only"
        elif evidence.was_executed(path, lineno):
            confidence = "refuted"
        elif evidence.has_evidence_for(path):
            confidence = "runtime-confirmed"
        else:
            confidence = "static-only"
        out.append(ConfirmedFinding(path=path, lineno=lineno,
                                    symbol=symbol, confidence=confidence))
    out.sort(key=lambda c: (c.path, c.lineno, c.symbol))
    return out
