"""Characterization guard for the consolidated fstring-helper extraction.

A dedup wave hoisted the byte-identical sibling helpers ``_arg_source`` /
``_collect_arg_sources`` / ``_recover_template`` out of ``fstring_convert`` and
``percent_to_fstring`` into ``app.execution._transform_base`` as
:func:`arg_source` / :func:`collect_arg_sources` / :func:`recover_fstring_template`
(the last parameterized by the differing ``{}`` vs ``%s`` placeholder splitter).

This pins the EXACT rewritten output (and the skip behaviour) of the two affected
transforms across a battery of snippets, plus direct unit coverage of the shared
helpers including their empty / None / skip paths. Behaviour-preserving by
construction: the executable body of each hoisted helper was byte-identical."""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution._transform_base import (
    arg_source,
    collect_arg_sources,
    recover_fstring_template,
)
from app.execution.fstring_convert import plan_fstring_convert
from app.execution.percent_to_fstring import plan_percent_to_fstring


def _run(plan_fn, tmp_path: Path, body: str) -> tuple[list[str], str]:
    """Apply ``plan_fn`` to ``body`` written as ``mod.py``; return the blocker
    list and the resulting file text (the original ``body`` if unchanged)."""
    rel = "mod.py"
    (tmp_path / rel).write_text(body, encoding="utf-8")
    plan = plan_fn(tmp_path, rel)
    return list(plan.blockers), plan.new_contents.get(rel, body)


# (source, expected) — expected == source means "must NOT convert".
_CONVERT_CASES = [
    ('x = "{} = {}".format(a, b)\n', 'x = f"{a} = {b}"\n'),
    ('x = "x={}".format(v)\n', 'x = f"x={v}"\n'),
    ('x = "{}".format(self.name)\n', 'x = f"{self.name}"\n'),
    ("x = '{}'.format(v)\n", "x = f'{v}'\n"),
    ('x = "a{}b{}c".format(p, q)\n', 'x = f"a{p}b{q}c"\n'),
    # must NOT convert (empty / count mismatch / brace / non-simple):
    ('x = "no fields".format()\n', 'x = "no fields".format()\n'),
    ('x = "{} {}".format(a)\n', 'x = "{} {}".format(a)\n'),
    ('x = "{}".format(a + b)\n', 'x = "{}".format(a + b)\n'),
    ('x = "{{}}".format()\n', 'x = "{{}}".format()\n'),
]

_PERCENT_CASES = [
    ('x = "%s = %s" % (a, b)\n', 'x = f"{a} = {b}"\n'),
    ('x = "x=%s" % v\n', 'x = f"x={v}"\n'),
    ('x = "%s" % self.name\n', 'x = f"{self.name}"\n'),
    ('x = "100%% of %s" % v\n', 'x = f"100% of {v}"\n'),
    # must NOT convert (other conversion / count mismatch / non-simple):
    ('x = "%d" % v\n', 'x = "%d" % v\n'),
    ('x = "%s %s" % (a,)\n', 'x = "%s %s" % (a,)\n'),
    ('x = "%s" % (a + b)\n', 'x = "%s" % (a + b)\n'),
    ('x = "no percent" % ()\n', 'x = "no percent" % ()\n'),
]


def test_fstring_convert_characterization(tmp_path: Path) -> None:
    for src, expected in _CONVERT_CASES:
        blockers, out = _run(plan_fstring_convert, tmp_path, src)
        assert blockers == []
        assert out == expected, f"{src!r} -> {out!r} (want {expected!r})"


def test_percent_to_fstring_characterization(tmp_path: Path) -> None:
    for src, expected in _PERCENT_CASES:
        blockers, out = _run(plan_percent_to_fstring, tmp_path, src)
        assert blockers == []
        assert out == expected, f"{src!r} -> {out!r} (want {expected!r})"


def _arg(expr_src: str) -> tuple[ast.expr, str]:
    """Parse a single expression and return ``(node, source)``."""
    return ast.parse(expr_src, mode="eval").body, expr_src


def test_arg_source_recovers_simple_and_rejects_braces_backslash() -> None:
    node, src = _arg("a.b.c")
    assert arg_source(node, src) == "a.b.c"
    # A brace in the recovered text is rejected (here a set-literal source).
    node, src = _arg("{1, 2}")
    assert arg_source(node, src) is None
    # A backslash in the recovered text is rejected (a string with an escape).
    node, src = _arg(r'"a\n"')
    assert arg_source(node, src) is None


def test_collect_arg_sources_all_or_none() -> None:
    src = "f(a, b.c, d)"
    call = ast.parse(src, mode="eval").body
    assert collect_arg_sources(call.args, src) == ["a", "b.c", "d"]
    # Empty input -> empty list (not None).
    assert collect_arg_sources([], src) == []
    # One brace-bearing arg -> the whole recovery is None.
    brace_call = ast.parse("h({1}, b)", mode="eval").body
    assert collect_arg_sources(brace_call.args, "h({1}, b)") is None


def _template(literal_src: str) -> tuple[ast.Constant, str]:
    node = ast.parse(literal_src, mode="eval").body
    return node, literal_src


def test_recover_fstring_template_splits_counts_and_skips() -> None:
    # ``{}``-style splitter — returns ``(segments, extra)``; the ``{}`` form
    # carries no per-placeholder payload, so ``extra`` is None.
    def split_braces(inner: str):
        parts = inner.split("{}")
        return (parts, None) if "{" not in "".join(parts) else None

    tmpl, src = _template('"a{}b{}c"')
    assert recover_fstring_template(tmpl, src, 2, split=split_braces) == (
        '"', ["a", "b", "c"], None)
    # Count mismatch -> None.
    assert recover_fstring_template(tmpl, src, 3, split=split_braces) is None
    # Zero placeholders (nothing to interpolate) -> None.
    tmpl0, src0 = _template('"plain"')
    assert recover_fstring_template(tmpl0, src0, 0, split=split_braces) is None
    # split returning None propagates to None.
    tmpl_bad, src_bad = _template('"x{"')
    assert recover_fstring_template(
        tmpl_bad, src_bad, 1, split=split_braces) is None
    # A non-plain literal (raw prefix) is rejected by literal_inner -> None.
    tmpl_r, src_r = _template('r"a{}b"')
    assert recover_fstring_template(tmpl_r, src_r, 1, split=split_braces) is None
