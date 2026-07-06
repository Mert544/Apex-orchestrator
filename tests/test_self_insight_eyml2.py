"""Extra coverage for ``app/engine/self_insight.py``: the source-cap break in
``gather_sources`` and the markdown weakness bullets. Uses a small synthetic tmp
project (never profiles the whole Apex repo) and is deterministic (no time/random).
"""

from __future__ import annotations

import json

import app.engine.self_insight as si
from app.engine.proof_of_fix import SCHEMA
from app.engine.self_insight import gather_sources, render_self_insight_markdown


def _write(root, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_gather_sources_stops_at_cap(tmp_path, monkeypatch):
    # A tiny cap makes the bound observable: the walk breaks after one source.
    monkeypatch.setattr(si, "_MAX_SOURCES", 1)
    _write(tmp_path, "a.py", "x = 1\n")
    _write(tmp_path, "b.py", "y = 2\n")
    _write(tmp_path, "c.py", "z = 3\n")
    sources = gather_sources(str(tmp_path))
    assert len(sources) == 1


def _write_rollback_proof(root) -> None:
    apex = root / ".apex"
    apex.mkdir()
    fixes = [
        {"finding": {"action": "harden_eval"}, "outcome": "rolled_back"},
        {"finding": {"action": "harden_eval"}, "outcome": "rolled_back"},
    ]
    proof = {"schema": SCHEMA, "generated_at": "x", "fixes": fixes}
    (apex / "proof-of-fix.json").write_text(json.dumps(proof), encoding="utf-8")


def test_markdown_renders_weakness_bullets(tmp_path):
    _write(tmp_path, "only.py", "x = 1\n")
    _write_rollback_proof(tmp_path)
    md = render_self_insight_markdown(str(tmp_path))
    # The weakness organ surfaced the repeatedly-rolled-back action; its bullet
    # names the action and its reliability, so the empty-state line is gone.
    assert "`harden_eval`" in md
    assert "reliability" in md
    assert "No proof history to grade fixing from." not in md
