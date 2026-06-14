"""The cli package split: family modules + the unchanged re-export surface."""

from __future__ import annotations

import app.cli_autonomy
import app.cli_ideate
import app.cli_insight
import app.cli_ops
import app.cli_plugins
import app.cli_reporting
import app.cli_refactor
import app.cli_review
from app import cli
from app.cli_common import _get_project_root


def test_default_root_is_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _get_project_root() == tmp_path.resolve()


def test_cli_reexports_are_the_same_objects():
    # The split must never fork behavior: app.cli exposes the very same
    # functions the family modules define (import surface unchanged).
    assert cli.cmd_maintain is app.cli_autonomy.cmd_maintain
    assert cli.cmd_auto is app.cli_autonomy.cmd_auto
    assert cli.cmd_evolve is app.cli_autonomy.cmd_evolve
    assert cli.cmd_simulate is app.cli_autonomy.cmd_simulate
    assert cli._working_tree_clean is app.cli_autonomy._working_tree_clean
    assert cli.cmd_rename is app.cli_refactor.cmd_rename
    assert cli.cmd_move is app.cli_refactor.cmd_move
    assert cli.cmd_signature is app.cli_refactor.cmd_signature
    assert cli.cmd_review is app.cli_review.cmd_review
    assert cli._apply_review_fixes is app.cli_review._apply_review_fixes
    assert cli.cmd_ideate is app.cli_ideate.cmd_ideate
    assert cli.cmd_plugin_install is app.cli_plugins.cmd_plugin_install
    assert cli.cmd_marketplace is app.cli_plugins.cmd_marketplace
    assert cli.cmd_hook is app.cli_plugins.cmd_hook
    assert cli.cmd_scan is app.cli_ops.cmd_scan
    assert cli.cmd_agents is app.cli_ops.cmd_agents
    assert cli.cmd_metrics is app.cli_ops.cmd_metrics
    assert cli.cmd_dashboard is app.cli_reporting.cmd_dashboard
    assert cli.cmd_debug is app.cli_reporting.cmd_debug
    assert cli.cmd_report is app.cli_reporting.cmd_report
    assert cli.cmd_explain is app.cli_insight.cmd_explain
    assert cli.cmd_brief is app.cli_insight.cmd_brief
    assert cli.cmd_dream is app.cli_insight.cmd_dream
    assert cli.cmd_outcomes is app.cli_insight.cmd_outcomes
    assert cli.cmd_recipes is app.cli_insight.cmd_recipes
    assert cli.cmd_changelog is app.cli_insight.cmd_changelog
    assert cli.cmd_grade is app.cli_insight.cmd_grade
    assert cli.cmd_impact is app.cli_insight.cmd_impact
    assert cli.cmd_mutants is app.cli_insight.cmd_mutants
    assert cli._get_project_root is _get_project_root


def test_parser_dispatches_to_family_modules(tmp_path):
    # The argparse wiring points at the moved functions, not stale copies.
    parser = cli.build_parser() if hasattr(cli, "build_parser") else None
    if parser is None:  # parser built inside main(): exercise via main dispatch
        import sys
        from unittest import mock

        with mock.patch.object(sys, "argv", ["apex", "rename", "a", "b",
                                             "--target", str(tmp_path), "--dry-run"]):
            rc = cli.main()
        assert rc == 1  # blocked (no such symbol) — but dispatched and ran


def test_engine_family_reexports_are_the_same_objects():
    # The idea_permutation split (its own 4-signal confluence target) must
    # never fork behavior: re-exports ARE the family modules' objects.
    import app.engine.idea_facets as facets
    import app.engine.idea_permutation as engine
    import app.engine.idea_seeder as seeder

    assert engine.IdeaSeeder is seeder.IdeaSeeder
    assert engine._FACETS is facets._FACETS
    assert engine._FACET_SUBASPECTS is facets._FACET_SUBASPECTS
    assert engine._FACET_CASES is facets._FACET_CASES
    assert engine._FACET_CAVEAT_RULES is facets._FACET_CAVEAT_RULES


def test_family_parser_registration_covers_every_command():
    # The parser is composed from the families now — a family forgetting to
    # register (or a typo'd command name) must fail HERE, not in a user's
    # terminal. Equality, not subset: silent loss and silent growth both fail.
    import argparse

    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    for mod in (app.cli_autonomy, app.cli_insight, app.cli_ideate, app.cli_review,
                app.cli_refactor, app.cli_ops, app.cli_reporting, app.cli_plugins):
        mod.register_parsers(sub)
    cli._register_local_parsers(sub)

    assert set(sub.choices) == {
        "auto", "simulate", "evolve", "maintain", "develop", "shield", "plan", "ascend",
        "grade", "impact", "mutants", "duplication", "brief", "dream", "outcomes", "recipes", "changelog", "explain",
        "ideate", "review", "rename", "move", "signature", "rewrite", "teach", "extract", "inline",
        "bench", "run", "canvas", "changed", "idea-html", "partition",
        "scan", "agents", "consensus", "daemon", "self-audit",
        "fix-docstrings", "fix-coverage", "lsp", "metrics",
        "dashboard", "hotspots", "deadcode", "city", "report", "fractal", "debug",
        "plugin", "marketplace", "hook",
    }
    # Dispatch targets ARE the family functions (not stale copies).
    assert sub.choices["rename"].get_default("func") is app.cli_refactor.cmd_rename
    assert sub.choices["maintain"].get_default("func") is app.cli_autonomy.cmd_maintain
    assert sub.choices["dream"].get_default("func") is app.cli_insight.cmd_dream
    assert sub.choices["ideate"].get_default("func") is app.cli_ideate.cmd_ideate
    assert sub.choices["dashboard"].get_default("func") is app.cli_reporting.cmd_dashboard
    assert sub.choices["scan"].get_default("func") is app.cli_ops.cmd_scan
    assert sub.choices["hook"].get_default("func") is app.cli_plugins.cmd_hook
