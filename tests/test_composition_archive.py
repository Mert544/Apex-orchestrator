from __future__ import annotations

from app.engine.composition_archive import (
    ArchiveEntry,
    CompositionArchive,
    record_campaign,
    render_playbook_markdown,
)


def _entry(objective="dead-params", operators=("drop_param",), delta=2.0, moves=None):
    ops = list(operators)
    return ArchiveEntry(objective=objective, operators=ops,
                        moves=moves if moves is not None else len(ops),
                        fitness_delta=delta, modules=1, date="2026-06-13")


def test_first_entry_fills_empty_cell():
    a = CompositionArchive()
    assert a.consider(_entry()) is True
    assert len(a.cells) == 1


def test_better_improvement_replaces_incumbent():
    a = CompositionArchive()
    a.consider(_entry(delta=1.0))
    assert a.consider(_entry(delta=3.0)) is True  # bigger gain wins
    assert a.entries()[0].fitness_delta == 3.0


def test_worse_improvement_is_rejected():
    a = CompositionArchive()
    a.consider(_entry(delta=3.0))
    assert a.consider(_entry(delta=1.0)) is False
    assert a.entries()[0].fitness_delta == 3.0


def test_tie_on_gain_prefers_fewer_moves():
    a = CompositionArchive()
    a.consider(ArchiveEntry("dead-params", ["drop_param", "drop_param"], 2, 2.0, 1))
    # Same operator-set cell, same gain, but a shorter recipe → it wins.
    assert a.consider(ArchiveEntry("dead-params", ["drop_param"], 1, 2.0, 1)) is True
    assert a.entries()[0].moves == 1


def test_distinct_operator_mixes_are_distinct_cells():
    a = CompositionArchive()
    a.consider(_entry(operators=("drop_param",)))
    a.consider(_entry(operators=("inline",)))
    a.consider(_entry(operators=("modernize", "fix_fstring")))
    assert len(a.cells) == 3


def test_operator_order_does_not_split_cells():
    a = CompositionArchive()
    a.consider(ArchiveEntry("modernize", ["modernize", "fix_fstring"], 2, 2.0, 1))
    # Same SET of operators, different order → same cell (competes, not added).
    assert a.consider(ArchiveEntry("modernize", ["fix_fstring", "modernize"], 2, 2.0, 1)) is False
    assert len(a.cells) == 1


def test_persistence_round_trip(tmp_path):
    a = CompositionArchive()
    a.consider(_entry())
    a.save(str(tmp_path))
    reloaded = CompositionArchive.load(str(tmp_path))
    assert reloaded.entries()[0].objective == "dead-params"


def test_load_missing_is_empty(tmp_path):
    assert CompositionArchive.load(str(tmp_path)).cells == {}


def test_record_campaign_only_records_real_gains(tmp_path):
    # A campaign that did nothing (no operators) or did not improve fitness is
    # never recorded — the playbook holds only verified wins.
    assert record_campaign(str(tmp_path), "dead-params", [], 3.0, 3.0, 1) is False
    assert record_campaign(str(tmp_path), "dead-params", ["drop_param"], 3.0, 3.0, 1) is False
    assert record_campaign(str(tmp_path), "dead-params", ["drop_param"], 3.0, 1.0, 1) is True
    arch = CompositionArchive.load(str(tmp_path))
    assert arch.entries()[0].fitness_delta == 2.0


def test_entries_sorted_by_gain_then_moves():
    a = CompositionArchive()
    a.consider(_entry(objective="a", operators=("x",), delta=1.0))
    a.consider(_entry(objective="b", operators=("y",), delta=5.0))
    a.consider(_entry(objective="c", operators=("z",), delta=3.0))
    deltas = [e.fitness_delta for e in a.entries()]
    assert deltas == [5.0, 3.0, 1.0]


def test_render_playbook_markdown():
    a = CompositionArchive()
    a.consider(_entry())
    md = render_playbook_markdown(a)
    assert "Composition playbook" in md and "dead-params" in md and "drop_param" in md


def test_render_empty_playbook():
    md = render_playbook_markdown(CompositionArchive())
    assert "Empty" in md


def test_compile_objective_records_to_archive(tmp_path):
    # End to end: a real develop campaign writes its recipe into the playbook.
    from app.engine.objective_compiler import compile_objective

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def render(text, color=None, width=80):\n    return text[:width]\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "from app.m import render\ndef test_r():\n    assert render('hi', width=2) == 'hi'\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='m'\nversion='0'\n", encoding="utf-8")

    compile_objective(str(tmp_path), objective="dead-params", apply=True, verify=False)
    arch = CompositionArchive.load(str(tmp_path))
    assert "dead-params|drop_param" in arch.cells
    assert arch.cells["dead-params|drop_param"].fitness_delta == 1.0


def test_cmd_develop_playbook_flag(tmp_path, capsys):
    import argparse

    from app.cli_autonomy import cmd_develop
    from app.engine.composition_archive import CompositionArchive

    a = CompositionArchive()
    a.consider(_entry())
    a.save(str(tmp_path))
    rc = cmd_develop(argparse.Namespace(
        target=str(tmp_path), objective="dead-params", from_dream=False,
        playbook=True, apply=False, max_steps=25, no_verify=True, json=False))
    assert rc == 0
    assert "Composition playbook" in capsys.readouterr().out
