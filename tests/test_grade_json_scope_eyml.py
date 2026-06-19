"""`apex grade --json` must carry the same honest scope disclosure as markdown.

A red-team audit found the JSON form of the grade dropped ``scope_line`` from
``HealthScore.to_dict()`` — so a scripted/JSON consumer saw a bare A+/100 on a
repo Apex only partly analysed (e.g. a pure-TypeScript project), with no signal
that 0% of it was actually graded, while the markdown form disclosed it. That is
an over-claim the proof-carrying moat must not make.

These tests pin: the JSON carries ``scope_line``; it is the real disclosure on a
non-Python repo; and it is empty (JSON unchanged) on an all-Python repo.
Deterministic; stdlib-only.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.health_score import grade


def test_to_dict_includes_scope_line_key(tmp_path: Path):
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
    d = grade(str(tmp_path)).to_dict()
    assert "scope_line" in d


def test_non_python_repo_json_discloses_out_of_scope(tmp_path: Path):
    (tmp_path / "app.ts").write_text("const x = eval(y)\n", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    d = grade(str(tmp_path)).to_dict()
    # The JSON must NOT present a bare clean grade with no disclosure.
    assert d["scope_line"]  # non-empty
    assert "outside analysis scope" in d["scope_line"]


def test_all_python_repo_json_scope_line_empty(tmp_path: Path):
    # Nothing out of scope -> empty scope_line -> JSON unchanged for Python repos.
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    d = grade(str(tmp_path)).to_dict()
    assert d["scope_line"] == ""
