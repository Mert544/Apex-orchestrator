"""Characterization guard for the fstring-conversion transform family.

Pins the exact rewritten output (and the skip/blocker behaviour) of the three
transforms — ``fstring_convert`` (anonymous ``{}`` ``.format``), ``percent_to_fstring``
(``%s`` ``%``-format), and ``format_to_fstring`` (bare ``{}`` / ``{0}`` / ``{name}``
``.format``) — across a wide battery of snippets, including many edge cases that
must NOT convert.

This locks the byte-for-byte behaviour the targets ``_try_call`` / ``_try_binop`` /
``_map_args`` were decomposed under: each case asserts the full new file contents
(or that the source is left untouched with no blockers)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.execution.format_to_fstring import plan_format_to_fstring
from app.execution.fstring_convert import plan_fstring_convert
from app.execution.percent_to_fstring import plan_percent_to_fstring


def _run(plan_fn, tmp_path: Path, body: str) -> tuple[list[str], str]:
    """Apply ``plan_fn`` to ``body`` written as ``mod.py``; return the blocker
    list and the resulting file text (the original ``body`` if unchanged)."""
    rel = "mod.py"
    (tmp_path / rel).write_text(body, encoding="utf-8")
    plan = plan_fn(tmp_path, rel)
    return list(plan.blockers), plan.new_contents.get(rel, body)


# (source, expected_output) — expected == source means "must NOT convert".
_FSTRING_CONVERT_CASES = [
    ('x = "{} = {}".format(a, b)\n', 'x = f"{a} = {b}"\n'),
    ('x = "x={}".format(v)\n', 'x = f"x={v}"\n'),
    ('x = "{}".format(self.name)\n', 'x = f"{self.name}"\n'),
    ('x = "{}".format(42)\n', 'x = f"{42}"\n'),
    ("x = '{}'.format(v)\n", "x = f'{v}'\n"),
    ('x = "pre{}mid{}post".format(a, b)\n', 'x = f"pre{a}mid{b}post"\n'),
    ('x = "{} {} {}".format(a, b, c)\n', 'x = f"{a} {b} {c}"\n'),
    # must NOT convert:
    ('x = "{0}".format(v)\n', 'x = "{0}".format(v)\n'),
    ('x = "{n}".format(n=v)\n', 'x = "{n}".format(n=v)\n'),
    ('x = "{:0.2f}".format(v)\n', 'x = "{:0.2f}".format(v)\n'),
    ('x = "{!r}".format(v)\n', 'x = "{!r}".format(v)\n'),
    ('x = "{{}}".format()\n', 'x = "{{}}".format()\n'),
    ('x = "}".format()\n', 'x = "}".format()\n'),
    ('x = "{".format()\n', 'x = "{".format()\n'),
    ('x = "{} {}".format(a)\n', 'x = "{} {}".format(a)\n'),
    ('x = "{}".format(a, b)\n', 'x = "{}".format(a, b)\n'),
    ('x = "{}".format(a + b)\n', 'x = "{}".format(a + b)\n'),
    ('x = "{}".format(f(1))\n', 'x = "{}".format(f(1))\n'),
    ('x = "{}".format(*args)\n', 'x = "{}".format(*args)\n'),
    ('x = "{}".format(**kw)\n', 'x = "{}".format(**kw)\n'),
    ('x = r"{}".format(v)\n', 'x = r"{}".format(v)\n'),
    ('x = b"{}".format(v)\n', 'x = b"{}".format(v)\n'),
    ('x = "\\n{}".format(v)\n', 'x = "\\n{}".format(v)\n'),
    ('x = "no placeholders".format()\n', 'x = "no placeholders".format()\n'),
    ('y = obj.format(a)\n', 'y = obj.format(a)\n'),
]

_PERCENT_CASES = [
    ('x = "%s = %s" % (a, b)\n', 'x = f"{a} = {b}"\n'),
    ('x = "x=%s" % v\n', 'x = f"x={v}"\n'),
    ('x = "%s" % self.name\n', 'x = f"{self.name}"\n'),
    ('x = "100%% of %s" % v\n', 'x = f"100% of {v}"\n'),
    ("x = '%s' % v\n", "x = f'{v}'\n"),
    ('x = "%s%s" % (a, b)\n', 'x = f"{a}{b}"\n'),
    ('x = "pre%smid%spost" % (a, b)\n', 'x = f"pre{a}mid{b}post"\n'),
    # brace in the percent template gets escaped:
    ('x = "{%s}" % v\n', 'x = f"{{{v}}}"\n'),
    # widened (proven byte-for-byte equivalent) conversions DO convert now:
    ('x = "%r" % v\n', 'x = f"{v!r}"\n'),
    ('x = "%5s" % v\n', 'x = f"{v!s:>5}"\n'),
    ('x = "%.2f" % v\n', 'x = f"{v:.2f}"\n'),
    ('x = "%x" % v\n', 'x = f"{v:x}"\n'),
    # must NOT convert — ``%d``/``%i`` truncate floats but ``{:d}`` raises, so the
    # decimal conversions are refused; mapping keys / count mismatch / lone % too:
    ('x = "%d" % v\n', 'x = "%d" % v\n'),
    ('x = "%(name)s" % d\n', 'x = "%(name)s" % d\n'),
    ('x = "%s %s" % (a,)\n', 'x = "%s %s" % (a,)\n'),
    ('x = "%s" % (a, b)\n', 'x = "%s" % (a, b)\n'),
    ('x = "%" % v\n', 'x = "%" % v\n'),
    ('x = "%s" % (a + b)\n', 'x = "%s" % (a + b)\n'),
    ('x = "%s" % f(1)\n', 'x = "%s" % f(1)\n'),
    ('x = "%s %s" % (*a,)\n', 'x = "%s %s" % (*a,)\n'),
    ('x = r"%s" % v\n', 'x = r"%s" % v\n'),
    ('x = "%s" % obj["k"]\n', 'x = "%s" % obj["k"]\n'),
    ('x = a % b\n', 'x = a % b\n'),
    ('x = 5 % 2\n', 'x = 5 % 2\n'),
]

_FORMAT_CASES = [
    ('x = "{}".format(v)\n', 'x = f"{v}"\n'),
    ('x = "{0}".format(v)\n', 'x = f"{v}"\n'),
    ('x = "{0}-{1}".format(a, b)\n', 'x = f"{a}-{b}"\n'),
    ('x = "{1}-{0}".format(a, b)\n', 'x = f"{b}-{a}"\n'),
    ('x = "{n}".format(n=v)\n', 'x = f"{v}"\n'),
    ('x = "{a} {b}".format(a=x, b=y)\n', 'x = f"{x} {y}"\n'),
    # arg source contains the template quote (``"``) -> rejected, left as-is:
    ('x = "{}".format(d["k"])\n', 'x = "{}".format(d["k"])\n'),
    ("x = '{}'.format(d['k'])\n", "x = '{}'.format(d['k'])\n"),
    ('x = "{}".format(f(1))\n', 'x = f"{f(1)}"\n'),
    ('x = "{0} {0}".format(a)\n', 'x = f"{a} {a}"\n'),
    ('x = "{x} {x}".format(x=p)\n', 'x = f"{p} {p}"\n'),
    ('val = "{x}{y}".format(x=a.b, y=c)\n', 'val = f"{a.b}{c}"\n'),
    # must NOT convert:
    ('x = "{0} {0}".format(f(1))\n', 'x = "{0} {0}".format(f(1))\n'),
    ('x = "{x} {x}".format(x=g())\n', 'x = "{x} {x}".format(x=g())\n'),
    ('x = "{:0.2f}".format(v)\n', 'x = "{:0.2f}".format(v)\n'),
    ('x = "{!r}".format(v)\n', 'x = "{!r}".format(v)\n'),
    ('x = "{a.b}".format(a=v)\n', 'x = "{a.b}".format(a=v)\n'),
    ('x = "{a[0]}".format(a=v)\n', 'x = "{a[0]}".format(a=v)\n'),
    ('x = "{} {0}".format(a, b)\n', 'x = "{} {0}".format(a, b)\n'),
    ('x = "{0} {}".format(a, b)\n', 'x = "{0} {}".format(a, b)\n'),
    ('x = "{x}".format(y=v)\n', 'x = "{x}".format(y=v)\n'),
    ('x = "{0}".format(a, b)\n', 'x = "{0}".format(a, b)\n'),
    ('x = "{1}".format(a, b)\n', 'x = "{1}".format(a, b)\n'),
    ('x = "{n}".format(**kw)\n', 'x = "{n}".format(**kw)\n'),
    ('x = "{}".format(*args)\n', 'x = "{}".format(*args)\n'),
    ('x = "{}".format(a + b)\n', 'x = "{}".format(a + b)\n'),
    ('x = "{{}}".format()\n', 'x = "{{}}".format()\n'),
    ('x = "no placeholders".format()\n', 'x = "no placeholders".format()\n'),
    ('y = obj.format(a)\n', 'y = obj.format(a)\n'),
    ('x = r"{}".format(v)\n', 'x = r"{}".format(v)\n'),
]


@pytest.mark.parametrize("body,expected", _FSTRING_CONVERT_CASES)
def test_fstring_convert_characterized(tmp_path, body, expected):
    blockers, out = _run(plan_fstring_convert, tmp_path, body)
    assert blockers == []
    assert out == expected


@pytest.mark.parametrize("body,expected", _PERCENT_CASES)
def test_percent_to_fstring_characterized(tmp_path, body, expected):
    blockers, out = _run(plan_percent_to_fstring, tmp_path, body)
    assert blockers == []
    assert out == expected


@pytest.mark.parametrize("body,expected", _FORMAT_CASES)
def test_format_to_fstring_characterized(tmp_path, body, expected):
    blockers, out = _run(plan_format_to_fstring, tmp_path, body)
    assert blockers == []
    assert out == expected


def test_multiple_rewrites_single_module(tmp_path):
    """Several occurrences on different lines all rewrite, bottom-up."""
    body = 'a = "{}".format(p)\nb = "%s" % q\nc = "{0}".format(r)\n'
    _, fc = _run(plan_fstring_convert, tmp_path, body)
    assert fc == 'a = f"{p}"\nb = "%s" % q\nc = "{0}".format(r)\n'
    _, pc = _run(plan_percent_to_fstring, tmp_path, body)
    assert pc == 'a = "{}".format(p)\nb = f"{q}"\nc = "{0}".format(r)\n'
    _, ff = _run(plan_format_to_fstring, tmp_path, body)
    assert ff == 'a = f"{p}"\nb = "%s" % q\nc = f"{r}"\n'


def test_empty_module_no_blockers(tmp_path):
    """Empty / no-match input yields an empty plan with no blockers."""
    for plan_fn in (plan_fstring_convert, plan_percent_to_fstring,
                    plan_format_to_fstring):
        blockers, out = _run(plan_fn, tmp_path, "x = 1\n")
        assert blockers == []
        assert out == "x = 1\n"
