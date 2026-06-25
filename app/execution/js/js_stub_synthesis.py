"""JS/TS stub-body synthesis — the LLM-free fill space + its jest gate-driver.

The JS image of :mod:`app.execution.stub_synthesis`'s contract (NOT its Python
AST internals): a stub function's body is never AUTHORED, it is SELECTED from a
small, FIXED template space tried in a FIXED order, and the FIRST candidate that
makes the function's pinned jest test pass is accepted. If no template passes, we
REFUSE — an honest under-claim, never a fake-green.

Template space (tried in this order — mirrors the Python order):

  1. **passthrough** — ``return a;`` of a single parameter;
  2. **binary op on two args** — ``a + b``, ``a - b``, ``a * b``, ``a % b``,
     ``Math.floor(a / b)``, ``a && b``, ``a || b`` (``+`` covers number, string
     concat AND array, as in Python);
  3. **iterable reduction** — ``a.length``, ``Math.min(...a)``, ``Math.max(...a)``,
     ``[...a].sort()`` of one array parameter;
  4. **constant** (LAST RESORT) — ``return <literal>;`` only when every pinned
     test asserts the SAME literal AND >=2 DISTINCT argument tuples witness it
     (the anti-overfit floor, the JS image of the Python >=2-distinct-tuples
     constant/recursion guard). Tried last so a parameter-shaped body that also
     passes wins over a bare literal.

The gate is the project's OWN ``npm test`` (jest), run against a THROWAWAY COPY
of the project so probing never disturbs the real tree — the landed change is
carried as a :class:`RenamePlan` and applied by the gated/rollback writer. A copy
goes green only when the previously-RED pinned test passes, so the accepted body
is verified by the user's own test, exactly as the Python synthesiser is.

Deterministic (fixed template order, no clock/random — same project, same body),
offline (no install; the project owns its ``node_modules``), zero-token.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from app.execution.js.js_tool import JsStub, JsWitness, fill_body, mine_witnesses
from app.skills.execution.run_tests import RunTestsSkill

__all__ = ["candidate_bodies", "synthesize_js_body"]


def _passthrough(params: tuple[str, ...]) -> list[tuple[str, str]]:
    """The identity template for a one-param stub: ``return a;``."""
    if len(params) != 1:
        return []
    return [("passthrough", f"return {params[0]};")]


def _binary(params: tuple[str, ...]) -> list[tuple[str, str]]:
    """The two-arg binary-op templates in fixed order. ``+`` is first (it covers
    number addition, string concat AND array concat, as Python's ``+`` does)."""
    if len(params) < 2:
        return []
    a, b = params[0], params[1]
    return [
        ("a+b", f"return {a} + {b};"),
        ("a-b", f"return {a} - {b};"),
        ("a*b", f"return {a} * {b};"),
        ("a%b", f"return {a} % {b};"),
        ("a/b", f"return Math.floor({a} / {b});"),
        ("a&&b", f"return {a} && {b};"),
        ("a||b", f"return {a} || {b};"),
    ]


def _reduction(params: tuple[str, ...]) -> list[tuple[str, str]]:
    """The one-array-arg reduction templates: length, min, max, sorted copy."""
    if len(params) != 1:
        return []
    a = params[0]
    return [
        ("length", f"return {a}.length;"),
        ("min", f"return Math.min(...{a});"),
        ("max", f"return Math.max(...{a});"),
        ("sort", f"return [...{a}].sort();"),
    ]


def _constant(witnesses: list[JsWitness]) -> list[tuple[str, str]]:
    """The LAST-RESORT constant template — only when every witness pins the SAME
    expected literal AND >=2 DISTINCT argument tuples witness it.

    The anti-overfit floor: a single example (``add(2,3)==5``) must NOT land
    ``return 5;`` — only a contract a parameter-free literal genuinely satisfies
    across multiple distinct inputs is eligible. Mirrors the Python
    >=2-distinct-tuples guard exactly."""
    if not witnesses:
        return []
    expected = {w.expected for w in witnesses}
    distinct_args = {w.args for w in witnesses}
    if len(expected) != 1 or len(distinct_args) < 2:
        return []
    return [("constant", f"return {next(iter(expected))};")]


def candidate_bodies(stub: JsStub,
                     witnesses: list[JsWitness]) -> list[tuple[str, str]]:
    """The fixed-order ``(label, body)`` template space for ``stub`` given its
    mined ``witnesses``. The constant is offered LAST (and only when the
    >=2-witness floor holds), so a parameter-shaped body always wins first.
    Deterministic: same stub + witnesses -> same list."""
    out: list[tuple[str, str]] = []
    out.extend(_passthrough(stub.params))
    out.extend(_binary(stub.params))
    out.extend(_reduction(stub.params))
    out.extend(_constant(witnesses))
    return out


def _gate_green(copy_root: Path, file_rel: str, name: str, body: str,
                runner: RunTestsSkill) -> bool:
    """Fill ``body`` into the stub ``name`` in the COPY and return whether the
    copy's jest suite goes green. A driver refusal (the fill did not apply) or a
    no-suite copy is read as NOT green — never a fake-green."""
    if not fill_body(copy_root, file_rel, name, body):
        return False
    summary = runner.run(str(copy_root))
    return bool(summary.commands) and summary.ok


def synthesize_js_body(root: Path, file_rel: str, stub: JsStub,
                       test_rel: str, runner: RunTestsSkill | None = None,
                       ) -> str | None:
    """The first fixed-template body that flips the RED jest test GREEN, or
    ``None`` (REFUSE) when none does.

    Mines the witnesses the test ``test_rel`` pins on ``stub.name``, builds the
    fixed template space, and probes each candidate IN ORDER against a throwaway
    COPY of the project under ``root`` (so the real tree is never touched while
    probing). The FIRST body whose copy goes green is returned; if every template
    leaves the copy red, nothing is returned. Deterministic and offline."""
    runner = runner or RunTestsSkill()
    witnesses = mine_witnesses(root, test_rel, stub.name)
    candidates = candidate_bodies(stub, witnesses)
    if not candidates:
        return None
    with tempfile.TemporaryDirectory(prefix="apex_js_") as tmp:
        copy_root = Path(tmp) / "project"
        shutil.copytree(root, copy_root,
                        ignore=shutil.ignore_patterns(".git"))
        for _label, body in candidates:
            shutil.copy2(root / file_rel, copy_root / file_rel)
            if _gate_green(copy_root, file_rel, stub.name, body, runner):
                return body
    return None
