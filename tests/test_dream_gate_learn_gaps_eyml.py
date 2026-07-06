"""Gap-closing tests for dream_gate_learn's corrupt/non-list journal tolerance.

The existing suite (test_dream_gate_learn_eyml.py) exercises the happy journal
paths; this wave pins the malformed-store edge: ``_load_journal`` must swallow an
unparseable ``.apex/dream-journal.json`` (``ValueError`` from ``json.loads``) and a
well-formed-but-non-list JSON, returning ``[]`` rather than raising — so
``gate_tighten_factors`` on a corrupt store is byte-identical to a fresh project
(``{}``), never a crash and never a fabricated tighten factor.

Deterministic, stdlib-only, no LLM. The ``_eyml`` house suffix.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.dream_gate_learn import _load_journal, gate_tighten_factors


def _write_journal(root: Path, text: str) -> None:
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "dream-journal.json").write_text(text, encoding="utf-8")


def test_corrupt_journal_load_returns_empty(tmp_path):
    # Unparseable JSON -> json.loads raises ValueError -> tolerated -> [].
    _write_journal(tmp_path, "not valid json {{{")
    assert _load_journal(tmp_path) == []


def test_corrupt_journal_gate_factors_is_neutral(tmp_path):
    # A corrupt store must read like a fresh project: no factors, no crash.
    _write_journal(tmp_path, "]]] broken [[[")
    assert gate_tighten_factors(str(tmp_path)) == {}


def test_non_list_json_journal_is_ignored(tmp_path):
    # Valid JSON but not a list (a dict) is not a journal -> [].
    _write_journal(tmp_path, '{"generation": 1}')
    assert _load_journal(tmp_path) == []
    assert gate_tighten_factors(str(tmp_path)) == {}


def test_missing_journal_is_empty(tmp_path):
    # No store at all -> [] / {} (the byte-identical fresh-project default).
    assert _load_journal(tmp_path) == []
    assert gate_tighten_factors(str(tmp_path)) == {}
