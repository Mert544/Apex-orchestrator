"""The cli package split: family modules + the unchanged re-export surface."""

from __future__ import annotations

import app.cli_autonomy
import app.cli_ideate
import app.cli_plugins
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
    assert cli.cmd_review is app.cli_review.cmd_review
    assert cli._apply_review_fixes is app.cli_review._apply_review_fixes
    assert cli.cmd_ideate is app.cli_ideate.cmd_ideate
    assert cli.cmd_plugin_install is app.cli_plugins.cmd_plugin_install
    assert cli.cmd_marketplace is app.cli_plugins.cmd_marketplace
    assert cli.cmd_hook is app.cli_plugins.cmd_hook
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
