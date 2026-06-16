"""Characterization tests for the ``_try_call`` decomposition in
:mod:`app.execution.format_to_fstring`.

``_try_call`` was split into small pure helpers (``_format_template``,
``_template_parts``, ``_build_fstring``, ``_reparses_as_fstring``,
``_has_unpacking``). These tests pin the EXACT plan output — full rewritten
contents AND blockers — for a broad battery of convertible and
must-NOT-convert ``.format()`` snippets, so any future drift in the rewrite
strings or skip conditions is caught. Deterministic, stdlib-only, offline.
"""

from __future__ import annotations

import os
import tempfile

from app.execution.format_to_fstring import plan_format_to_fstring


def _plan_for(src: str):
    """Run the format-to-fstring plan over a one-module source ``src`` and
    return ``(new_contents, blockers, edits)`` — the observable outcome."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "m.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(src if src.endswith("\n") else src + "\n")
        plan = plan_format_to_fstring(d, "m.py")
        new = plan.new_contents.get("m.py")
        return new, list(plan.blockers), plan.edits_by_file.get("m.py")


# Each case: (source, expected rewritten line | None if unchanged).
# ``None`` means the occurrence is skipped (no rewrite produced for that call).
CONVERT_CASES = [
    ('"{}".format(x)', 'f"{x}"\n'),
    ('"{0}-{1}".format(a, b)', 'f"{a}-{b}"\n'),
    ('"{n}".format(n=v)', 'f"{v}"\n'),
    ('"x={}".format(self.name)', 'f"x={self.name}"\n'),
    ('"{} {} {}".format(a, b, c)', 'f"{a} {b} {c}"\n'),
    ('"{1}-{0}".format(a, b)', 'f"{b}-{a}"\n'),
    ('"{a}{b}".format(a=p, b=q)', 'f"{p}{q}"\n'),
    ("'{}'.format(x)", "f'{x}'\n"),
    ("'{}'.format(d[\"k\"])", "f'{d[\"k\"]}'\n"),
    ('"{}".format(a.b.c)', 'f"{a.b.c}"\n'),
    ('"a{}b{}c".format(x, y)', 'f"a{x}b{y}c"\n'),
    ('"{}".format(f())', 'f"{f()}"\n'),
    ('"{0}{0}".format(x)', 'f"{x}{x}"\n'),
    ('"{}".format(g(a, b))', 'f"{g(a, b)}"\n'),
]

# Snippets that must NOT be converted (skip / blocker, no rewrite).
SKIP_CASES = [
    '"val={!r}".format(x)',        # conversion
    '"{:0.2f}".format(x)',         # format spec
    '"{a.b}".format(a=o)',         # attr inside field
    '"{a[0]}".format(a=o)',        # index inside field
    '"{{literal}}".format()',      # escaped brace
    '"{}".format(*args)',          # *args
    '"{a}".format(**kw)',          # **kwargs
    '"{}".format(x + 1)',          # binop arg (not simple)
    '"{} {}".format(a)',           # too few args
    '"{}".format(a, b)',           # extra arg
    '"{x}".format(y=1)',           # missing name
    '"{} {0}".format(a, b)',       # mixed auto/manual numbering
    '"plain".format()',            # no fields
    '"{0}{0}".format(f())',        # call referenced twice
    'r"{}".format(x)',             # raw prefix
    'b"{}".format(x)',             # bytes prefix
    'f"{x}".format(x)',            # f prefix (parseable, skipped)
    "'{}'.format(d['k'])",         # quote in arg
    '"{}".format(d["k"])',         # double-quote in arg matches template quote
    '"{}\\n".format(x)',           # backslash in literal
    '"{1}{1}".format(a, b)',       # arg 0 unreferenced
    '"""{}""".format(x)',          # triple quote
    'obj.format(x)',               # not a string literal
    '"{}".format()',               # field but no arg
]


def test_convert_cases_rewrite_exactly():
    for src, expected in CONVERT_CASES:
        new, blockers, edits = _plan_for(src)
        assert new == expected, (src, new, expected)
        assert blockers == [], (src, blockers)
        assert edits == 1, (src, edits)


def test_skip_cases_leave_source_untouched():
    for src in SKIP_CASES:
        new, blockers, edits = _plan_for(src)
        # Either no plan content at all, or content equal to the input — never
        # a rewrite. An empty plan is a no-op (not a failure), so no blockers.
        if new is not None:
            assert new == (src if src.endswith("\n") else src + "\n"), (src, new)
        assert blockers == [], (src, blockers)


def test_multiple_calls_one_line_and_across_lines():
    src = 'x = "{}".format(y)\nz = "{0}".format(w)\n'
    new, blockers, edits = _plan_for(src)
    assert new == 'x = f"{y}"\nz = f"{w}"\n'
    assert blockers == []
    assert edits == 2


def test_empty_module_is_noop():
    new, blockers, edits = _plan_for("")
    assert new is None
    assert blockers == []
    assert edits is None
