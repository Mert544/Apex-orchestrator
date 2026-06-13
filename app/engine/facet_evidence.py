"""Evidence grounding for the fractal facet zoom.

The facet vocabulary names *concerns* ("error handling", "resource limits").
This module checks whether a concern is REAL in the subject's actual code:
it routes a facet phrase to the canonical detector's findings (and to the
per-function complexity metrics) and returns concrete ``(line, detail)``
evidence. A facet with evidence is a verified observation — "this file's
error handling is genuinely weak, see line 12" — while a facet without
evidence remains an honest hypothesis to investigate.

This is what turns the fractal from a template tree into a microscope:
each zoom level *looks at the code*, and the value-guided spike follows
the evidence. Deterministic, stdlib-only.
"""

from __future__ import annotations

from app.engine.detectors import Issue, detect

# facet-phrase keywords -> which detector findings count as evidence for it.
# Each entry: (phrase keywords, predicate over an Issue).
_RULES: list[tuple[tuple[str, ...], "callable"]] = [
    (("input validation", "type and shape", "range and length", "null or empty",
      "new input", "accepted format"),
     lambda i: i.fix_kind in ("eval", "os.system", "sql") or "injection" in i.message),
    (("error handling", "catch specificity", "error propagation", "raised exception",
      "failure semantics", "cleanup on failure"),
     lambda i: ("except" in i.message or "exception" in i.message.lower()
                or i.fix_kind in ("bare except", "base-exception", "raise-from"))),
    (("resource limits", "timeout", "time and timeout"),
     lambda i: i.fix_kind == "net-timeout"),
    (("secret handling", "plaintext", "rotation", "secret store"),
     lambda i: "secret" in i.message),
    (("failure modes", "dependency unavailable", "partial or interrupted"),
     lambda i: i.fix_kind in ("net-timeout", "open-encoding", "bare except")
     or "swallowed" in i.message),
    (("public api", "signatures", "worked example", "usage example", "pre and post"),
     lambda i: i.category == "docs"),
    (("dead code", "unreachable", "redundant guard"),
     lambda i: "unreachable" in i.message or "always true" in i.message),
]

# Phrases whose evidence is per-function branch complexity, not a finding.
_COMPLEXITY_KEYS = ("edge case", "deep nesting", "property invariant",
                    "boundary case", "duplicated logic", "extract inner")
_COMPLEXITY_FLOOR = 8

# Structural evidence beyond findings and branches (each threshold is the
# point where the concern stops being taste and starts being measurable):
# a parameter list this long IS the "parameterize / api surface" concern,
# and a function this tall IS the "shared helper / split it" concern.
_SIGNATURE_KEYS = ("parameterize", "api surface", "interface", "shared helper")
_SIGNATURE_FLOOR = 6        # params (self/cls excluded)
_LENGTH_KEYS = ("extract a shared helper", "single source of truth",
                "smaller unit", "extract inner")
_LENGTH_FLOOR = 60          # statements-spanning lines per function


def _long_signatures(source: str) -> list[tuple[int, str]]:
    import ast as _ast

    out = []
    try:
        tree = _ast.parse(source)
    except SyntaxError:
        return out
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            a = node.args
            params = [p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)
                      if p.arg not in ("self", "cls")]
            if len(params) >= _SIGNATURE_FLOOR:
                out.append((node.lineno, f"{node.name}() takes {len(params)} parameters"))
    return out


def _long_functions(source: str) -> list[tuple[int, str]]:
    import ast as _ast

    out = []
    try:
        tree = _ast.parse(source)
    except SyntaxError:
        return out
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            span = (node.end_lineno or node.lineno) - node.lineno + 1
            if span >= _LENGTH_FLOOR:
                out.append((node.lineno, f"{node.name}() spans {span} lines"))
    return out


def evidence_for_facet(source: str, phrase: str, limit: int = 2) -> list[tuple[int, str]]:
    """Concrete ``(line, detail)`` evidence that ``phrase`` is a real concern in
    ``source`` — or ``[]`` when the concern is (honestly) only a hypothesis."""
    p = phrase.lower()
    out: list[tuple[int, str]] = []

    issues: list[Issue] = detect(source)
    for keys, pred in _RULES:
        if any(k in p for k in keys):
            for i in issues:
                if pred(i):
                    out.append((i.line, i.message.split("—")[0].strip()[:64]))
            break

    if not out and any(k in p for k in _SIGNATURE_KEYS):
        out += _long_signatures(source)
    if not out and any(k in p for k in _LENGTH_KEYS):
        out += _long_functions(source)
    if not out and any(k in p for k in _COMPLEXITY_KEYS):
        from app.tools.code_metrics import function_complexities

        for name, lineno, cx in function_complexities(source):
            if cx >= _COMPLEXITY_FLOOR:
                out.append((lineno, f"{name}() has {cx} branches"))

    # Deterministic order: by line; cap so a noisy file can't flood the facet.
    out.sort(key=lambda t: t[0])
    return out[:limit]
