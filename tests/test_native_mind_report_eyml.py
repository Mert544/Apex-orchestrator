"""The native-intelligence visibility report — ``app/reporting/native_mind_report``
and the ``apex native-mind`` CLI.

Pins that the report deterministically summarises what the native intelligence
learned from a project's OWN code (idioms after positional canonicalisation,
ranked by frequency), reflecting exactly the corpus the opt-in lane learns from.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.execution.stub_synthesis import _native_mind_sources
from app.reporting.native_mind_report import (
    finishable_stubs,
    render_finishable_stubs_markdown,
    render_native_mind_markdown,
    summarize_native_mind,
)


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_corpus_cache():
    _native_mind_sources.cache_clear()
    yield
    _native_mind_sources.cache_clear()


def _project(tmp_path: Path) -> Path:
    _write(tmp_path, "pkg/__init__.py", "")
    # Two functions share the '+' idiom (different names) -> one idiom, count 2.
    _write(tmp_path, "pkg/a.py",
           "def add(a, b):\n    return a + b\n"
           "def plus(m, n):\n    return m + n\n"
           "def neg(x):\n    return -x\n")
    return tmp_path


def test_summary_counts_and_canonicalises_idioms(tmp_path):
    s = summarize_native_mind(_project(tmp_path))
    assert s["exemplars"] == 3          # add, plus, neg
    assert s["distinct_shapes"] == 2    # 'p0 + p1' and '-p0'
    assert s["by_arity"] == {1: 1, 2: 1}


def test_dominant_idiom_ranks_first_with_its_count(tmp_path):
    s = summarize_native_mind(_project(tmp_path))
    top = s["top_idioms"]
    assert top[0]["shape"] == "p0 + p1"
    assert top[0]["count"] == 2
    assert top[0]["arity"] == 2
    assert top[0]["example"] in ("add", "plus")


def test_summary_is_deterministic(tmp_path):
    root = _project(tmp_path)
    first = summarize_native_mind(root)
    _native_mind_sources.cache_clear()
    assert summarize_native_mind(root) == first


def test_top_bounds_the_idiom_list(tmp_path):
    s = summarize_native_mind(_project(tmp_path), top=1)
    assert len(s["top_idioms"]) == 1
    assert summarize_native_mind(_project(tmp_path), top=0)["top_idioms"] == []


def test_empty_project_is_honest_not_crashing(tmp_path):
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/empty.py", "GREETING = 'hi'\n")  # no learnable function
    s = summarize_native_mind(tmp_path)
    assert s["exemplars"] == 0
    assert s["top_idioms"] == []
    md = render_native_mind_markdown(s)
    assert "no" in md.lower() and "learned" in md.lower()


def test_markdown_shows_counts_and_examples(tmp_path):
    md = render_native_mind_markdown(summarize_native_mind(_project(tmp_path)))
    assert "Native intelligence" in md
    assert "`p0 + p1`" in md
    assert "**2**" in md


def test_cli_native_mind_json_and_text(tmp_path, capsys):
    import argparse

    from app.cli_insight import cmd_native_mind
    root = _project(tmp_path)

    _native_mind_sources.cache_clear()
    rc = cmd_native_mind(argparse.Namespace(target=str(root), top=20, json=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert '"exemplars": 3' in out

    _native_mind_sources.cache_clear()
    rc = cmd_native_mind(argparse.Namespace(target=str(root), top=20, json=False))
    assert rc == 0
    assert "p0 + p1" in capsys.readouterr().out


# --- the --stubs dry-run (what the native lane could finish) ------------------

def _stub_project(tmp_path: Path) -> Path:
    """A project with a 3-arg clamp exemplar and two pinned stubs: ``bound`` (only
    the native lane can finish it) and ``total`` (a fixed template also can)."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/lib.py", "def clamp(v, lo, hi):\n    return max(lo, min(v, hi))\n")
    _write(tmp_path, "pkg/work.py",
           "def bound(a, b, c):\n    raise NotImplementedError\n"
           "def total(x, y):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_work.py", """
        from pkg.work import bound, total

        def test_bound_mid():
            assert bound(5, 0, 10) == 5

        def test_bound_lo():
            assert bound(-3, 0, 10) == 0

        def test_bound_hi():
            assert bound(99, 0, 10) == 10

        def test_total():
            assert total(2, 3) == 5
        """)
    return tmp_path


def test_finishable_stubs_flags_native_only_wins(tmp_path):
    rows = finishable_stubs(_stub_project(tmp_path))
    by_name = {r["stub"]: r for r in rows}
    assert by_name["bound"]["body"] == "max(b, min(a, c))"
    assert by_name["bound"]["native_only"] is True          # no template fits
    assert by_name["total"]["body"] == "x + y"
    assert by_name["total"]["native_only"] is False         # a template fits too


def test_finishable_stubs_does_not_leak_the_env_toggle(tmp_path):
    import os
    prior = "APEX_NATIVE_MIND" in os.environ
    finishable_stubs(_stub_project(tmp_path))
    assert ("APEX_NATIVE_MIND" in os.environ) == prior


def test_finishable_stubs_is_deterministic(tmp_path):
    root = _stub_project(tmp_path)
    assert finishable_stubs(root) == finishable_stubs(root)


def test_finishable_stubs_empty_on_a_finished_project(tmp_path):
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/done.py", "def add(a, b):\n    return a + b\n")
    assert finishable_stubs(tmp_path) == []
    assert "No pinned" in render_finishable_stubs_markdown([])


def test_finishable_stubs_markdown_foregrounds_native_only(tmp_path):
    md = render_finishable_stubs_markdown(finishable_stubs(_stub_project(tmp_path)))
    assert "Native-only" in md
    assert "bound(a, b, c)" in md
    assert "max(b, min(a, c))" in md


def test_cli_native_mind_stubs(tmp_path, capsys):
    import argparse

    from app.cli_insight import cmd_native_mind
    root = _stub_project(tmp_path)
    rc = cmd_native_mind(argparse.Namespace(
        target=str(root), top=20, stubs=True, json=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert '"native_only": 1' in out
