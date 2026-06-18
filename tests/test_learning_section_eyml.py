"""Tests for app.reporting.learning_section.render_learning_markdown.

Builds synthetic ``.apex/proof-of-fix.json`` artifacts in ``tmp_path`` and
asserts the rendered learning section: correct + deterministic per-action
reliability table, the empty-state section for no history, and well-formed
Markdown throughout.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.proof_of_fix import SCHEMA
from app.reporting.learning_section import render_learning_markdown


def _fix(action: str, outcome: str, target: str = "") -> dict:
    """A minimal proof ``fixes`` row with a given action type and outcome."""
    return {
        "finding": {"action": action, "target": target},
        "outcome": outcome,
        "changed_files": [],
    }


def _write_proof(root: Path, name: str, fixes: list[dict], ts: str = "") -> Path:
    """Write a valid proof-of-fix artifact under ``root/.apex/``."""
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    proof = {"schema": SCHEMA, "generated_at": ts, "fixes": fixes}
    path = apex / name
    path.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    return path


# --- empty / absent history -------------------------------------------------


def test_no_apex_dir_renders_empty_state(tmp_path):
    md = render_learning_markdown(tmp_path)
    assert "## What Apex Has Learned About Fixing This Project" in md
    assert "no fix history yet" in md.lower()
    assert "|" not in md  # no table
    assert md.endswith("\n")


def test_empty_proof_renders_empty_state(tmp_path):
    _write_proof(tmp_path, "proof-of-fix.json", fixes=[])
    md = render_learning_markdown(tmp_path)
    assert "no fix history yet" in md.lower()
    assert "| Action |" not in md


def test_never_raises_on_malformed_json(tmp_path):
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text("{not json", encoding="utf-8")
    md = render_learning_markdown(tmp_path)  # must not raise
    assert "no fix history yet" in md.lower()


# --- populated history: table correctness -----------------------------------


def test_reliability_table_values_are_correct(tmp_path):
    fixes = [
        _fix("inline_variable", "applied"),
        _fix("inline_variable", "applied"),
        _fix("inline_variable", "rolled_back"),
        _fix("inline_variable", "blocked"),  # 2 of 4 landed -> 50%
        _fix("extract_method", "applied"),  # 1 of 1 -> 100%
    ]
    _write_proof(tmp_path, "proof-of-fix.json", fixes)
    md = render_learning_markdown(tmp_path)

    assert "| Action | Reliability | Applied | Rolled back | Blocked | Total |" in md
    # extract_method: 100% reliability, sorts first (high->low).
    rows = [ln for ln in md.splitlines() if ln.startswith("| ") and "---" not in ln]
    header, extract_row, inline_row = rows[0], rows[1], rows[2]
    assert "Action" in header
    assert "| extract_method | 100% | 1 | 0 | 0 | 1 |" == extract_row
    assert "| inline_variable | 50% | 2 | 1 | 1 | 4 |" == inline_row


def test_actions_sorted_by_reliability_then_name(tmp_path):
    fixes = [
        _fix("zzz_low", "blocked"),  # 0%
        _fix("aaa_high", "applied"),  # 100%
        _fix("mmm_high", "applied"),  # 100% -> ties broken by name asc
    ]
    _write_proof(tmp_path, "proof-of-fix.json", fixes)
    md = render_learning_markdown(tmp_path)
    order = [ln.split("|")[1].strip() for ln in md.splitlines()
             if ln.startswith("| ") and "Reliability" not in ln and "---" not in ln]
    assert order == ["aaa_high", "mmm_high", "zzz_low"]


def test_headline_quantifies_overall_learning(tmp_path):
    fixes = [_fix("a", "applied"), _fix("a", "blocked")]  # 50% overall, 2 fixes
    _write_proof(tmp_path, "proof-of-fix.json", fixes)
    md = render_learning_markdown(tmp_path)
    assert "Apex has learned" in md
    assert "50%" in md
    assert "2 fixes" in md


def test_aggregates_across_multiple_proofs(tmp_path):
    _write_proof(tmp_path, "proof-a.json", [_fix("a", "applied")], ts="2024-01-01")
    _write_proof(tmp_path, "proof-b.json", [_fix("a", "rolled_back")], ts="2024-02-01")
    md = render_learning_markdown(tmp_path)
    # a: 1 applied + 1 rolled_back across both proofs -> 50%, total 2.
    assert "| a | 50% | 1 | 1 | 0 | 2 |" in md


# --- determinism ------------------------------------------------------------


def test_render_is_deterministic(tmp_path):
    fixes = [
        _fix("alpha", "applied"),
        _fix("beta", "rolled_back"),
        _fix("alpha", "blocked"),
        _fix("gamma", "applied"),
    ]
    _write_proof(tmp_path, "proof-of-fix.json", fixes)
    first = render_learning_markdown(tmp_path)
    second = render_learning_markdown(tmp_path)
    assert first == second


def test_string_root_and_path_root_agree(tmp_path):
    _write_proof(tmp_path, "proof-of-fix.json", [_fix("a", "applied")])
    assert render_learning_markdown(tmp_path) == render_learning_markdown(str(tmp_path))


# --- markdown well-formedness -----------------------------------------------


def test_table_rows_have_consistent_column_count(tmp_path):
    fixes = [_fix("a", "applied"), _fix("b", "blocked")]
    _write_proof(tmp_path, "proof-of-fix.json", fixes)
    md = render_learning_markdown(tmp_path)
    table_rows = [ln for ln in md.splitlines() if ln.startswith("|")]
    # header + separator + 2 action rows.
    assert len(table_rows) == 4
    pipe_counts = {ln.count("|") for ln in table_rows}
    assert pipe_counts == {7}  # 6 columns -> 7 pipes


def test_pipe_in_action_name_is_escaped(tmp_path):
    fixes = [_fix("weird|name", "applied")]
    _write_proof(tmp_path, "proof-of-fix.json", fixes)
    md = render_learning_markdown(tmp_path)
    assert "weird&#124;name" in md
    # The raw pipe must not survive to break the table.
    action_rows = [ln for ln in md.splitlines()
                   if ln.startswith("| weird")]
    assert action_rows and action_rows[0].count("|") == 7


def test_section_starts_with_heading_and_ends_with_newline(tmp_path):
    _write_proof(tmp_path, "proof-of-fix.json", [_fix("a", "applied")])
    md = render_learning_markdown(tmp_path)
    assert md.startswith("## What Apex Has Learned")
    assert md.endswith("\n")
