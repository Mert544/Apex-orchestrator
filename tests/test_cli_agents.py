import argparse

from app.cli import (
    cmd_agents,
    cmd_fix_coverage,
    cmd_fix_docstrings,
    cmd_self_audit,
)


def _proj(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "import os\n\ndef run(c):\n    return eval(c)\n\ndef helper(x):\n    return x + 1\n"
    )
    return tmp_path


def test_cmd_agents_security(tmp_path, capsys):
    _proj(tmp_path)
    rc = cmd_agents(argparse.Namespace(target=str(tmp_path), agent_type="security"))
    assert rc == 0
    assert "findings" in capsys.readouterr().out


def test_cmd_agents_docstring(tmp_path, capsys):
    _proj(tmp_path)
    rc = cmd_agents(argparse.Namespace(target=str(tmp_path), agent_type="docstring", patch=False))
    assert rc == 0
    assert "missing docstrings" in capsys.readouterr().out.lower()


def test_cmd_agents_test_stub(tmp_path, capsys):
    _proj(tmp_path)
    rc = cmd_agents(argparse.Namespace(target=str(tmp_path), agent_type="test-stub", generate=False))
    assert rc == 0
    assert "Coverage" in capsys.readouterr().out


def test_cmd_agents_dependency(tmp_path, capsys):
    _proj(tmp_path)
    rc = cmd_agents(argparse.Namespace(target=str(tmp_path), agent_type="dependency"))
    assert rc == 0
    assert "Modules" in capsys.readouterr().out


def test_cmd_agents_unknown(tmp_path, capsys):
    rc = cmd_agents(argparse.Namespace(target=str(tmp_path), agent_type="bogus"))
    assert rc == 1
    assert "Unknown agent type" in capsys.readouterr().out


def test_cmd_self_audit_text(tmp_path, capsys):
    _proj(tmp_path)
    rc = cmd_self_audit(argparse.Namespace(target=str(tmp_path), format="text"))
    assert rc == 0
    assert "Apex Self-Audit Report" in capsys.readouterr().out


def test_cmd_self_audit_json(tmp_path, capsys):
    _proj(tmp_path)
    rc = cmd_self_audit(argparse.Namespace(target=str(tmp_path), format="json"))
    out = capsys.readouterr().out
    assert rc == 0
    import json
    json.loads(out)  # valid JSON


def test_cmd_fix_docstrings_dry_run(tmp_path, capsys):
    _proj(tmp_path)
    before = (tmp_path / "app" / "m.py").read_text()
    rc = cmd_fix_docstrings(argparse.Namespace(target=str(tmp_path), dry_run=True))
    assert rc == 0
    assert "Dry run" in capsys.readouterr().out
    assert (tmp_path / "app" / "m.py").read_text() == before  # untouched


def test_cmd_fix_coverage_dry_run(tmp_path, capsys):
    _proj(tmp_path)
    rc = cmd_fix_coverage(argparse.Namespace(target=str(tmp_path), generate=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Coverage" in out
    assert "Dry run" in out


def test_cmd_hook_install_uninstall(tmp_path, capsys):
    import subprocess
    from app.cli import cmd_hook
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    assert cmd_hook(argparse.Namespace(target=str(tmp_path), action="install")) == 0
    assert "Installed" in capsys.readouterr().out
    assert cmd_hook(argparse.Namespace(target=str(tmp_path), action="uninstall")) == 0
    assert "Uninstalled" in capsys.readouterr().out


def test_cmd_hook_unknown_action(tmp_path, capsys):
    from app.cli import cmd_hook
    assert cmd_hook(argparse.Namespace(target=str(tmp_path), action="bogus")) == 1
    assert "Unknown hook action" in capsys.readouterr().out


def test_cmd_plugin_list_empty(tmp_path, capsys, monkeypatch):
    import app.cli as cli
    from app.cli import cmd_plugin_list
    # Point project root at an empty dir -> "No plugins" path.
    monkeypatch.setattr(cli, "_get_project_root", lambda: tmp_path)
    assert cmd_plugin_list(argparse.Namespace()) == 0
    assert "No plugins" in capsys.readouterr().out
