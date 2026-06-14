"""Edge-case coverage for app/execution/dead_code.py.

Targets the conservative plan-level guards the canonical suite leaves open: the
"deletion changed nothing" early return (line 118) and the re-parse-failure
blocker that clears any partial output (lines 123-127). Both are exercised by
forcing ``_delete_spans`` to produce a degenerate result while real dead spans
exist. Deterministic, stdlib-only.
"""

from __future__ import annotations

import app.execution.dead_code as dead_code
from app.execution.dead_code import plan_remove_dead_code


def _write(tmp_path, rel: str, source: str) -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return rel


def test_deletion_that_changes_nothing_is_noop(tmp_path, monkeypatch):
    # Real dead spans exist, but if the splice yields source identical to the
    # original the plan stays an empty no-op (the `new == source` guard).
    rel = _write(tmp_path, "m.py", "def f():\n    return 1\n    x = 2\n")
    monkeypatch.setattr(dead_code, "_delete_spans", lambda src, spans: src)
    plan = plan_remove_dead_code(tmp_path, rel)
    assert not plan.new_contents
    assert not plan.blockers
    assert not plan.ok


def test_unparseable_removal_blocks_and_clears_output(tmp_path, monkeypatch):
    # If a slice would produce source that doesn't re-parse, the transform must
    # never emit it: it records a blocker and clears any staged new content.
    rel = _write(tmp_path, "m.py", "def f():\n    return 1\n    x = 2\n")
    monkeypatch.setattr(
        dead_code, "_delete_spans", lambda src, spans: "def broken(:\n")
    msg = "removal produced unparseable source"
    plan = plan_remove_dead_code(tmp_path, rel)
    assert plan.blockers
    assert any(msg in b for b in plan.blockers)
    assert not plan.new_contents
    assert not plan.ok


def test_delete_spans_dedupes_and_deletes_bottom_up():
    # Direct unit on the splice helper: duplicate spans collapse and the inclusive
    # 1-based span is removed without disturbing surrounding lines.
    source = "a\nb\nc\nd\ne\n"
    out = dead_code._delete_spans(source, [(2, 3), (2, 3)])
    assert out == "a\nd\ne\n"


def test_dead_spans_one_finding_per_block():
    import ast

    # Two terminals in the same block: only the first (and everything after it)
    # is reported — one finding per block, the rest is already covered.
    tree = ast.parse(
        "def f():\n    return 1\n    a = 2\n    return 3\n    b = 4\n")
    spans = dead_code._dead_spans(tree)
    assert spans == [(3, 5)]
