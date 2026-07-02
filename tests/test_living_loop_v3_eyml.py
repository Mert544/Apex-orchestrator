"""The living loop's V3 contracts (living-assistant program, wave V3).

Three seams, each pinned: the agenda ARTIFACT (single-writer, deterministic,
rebuildable — the vault contract mirrored), the daemon's per-cycle memory
beat (refresh happens every cycle; a refresh failure NEVER kills the
supervision loop), and the agenda→assist hand-off (rank-1 landable becomes a
normal understand→plan→act request, preview-first, honest when empty).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.engine.agenda import AGENDA_REL, write_agenda


def _pyproject(tmp: Path) -> None:
    (tmp / "pyproject.toml").write_text("[project]\nname='p'\nversion='0'\n")


# --------------------------------------------------------------------------- #
# write_agenda: the artifact contract
# --------------------------------------------------------------------------- #


def test_write_agenda_is_deterministic_and_rebuildable(tmp_path: Path):
    _pyproject(tmp_path)
    path = write_agenda(tmp_path)
    assert path == tmp_path / AGENDA_REL
    first = path.read_bytes()
    assert write_agenda(tmp_path).read_bytes() == first  # byte-idempotent
    path.unlink()
    assert write_agenda(tmp_path).read_bytes() == first  # fully rebuildable
    parsed = json.loads(first)
    assert set(parsed["lanes"]) == {"landable", "human", "watched", "user"}


# --------------------------------------------------------------------------- #
# Daemon memory beat
# --------------------------------------------------------------------------- #


def _daemon_for(tmp_path: Path):
    from app.daemon import ApexDaemon

    return ApexDaemon(goal="", interval_sec=1.0, target=str(tmp_path))


def test_refresh_memory_writes_both_artifacts(tmp_path: Path, capsys):
    from app.memory.vault import VAULT_REL

    _pyproject(tmp_path)
    _daemon_for(tmp_path)._refresh_memory()
    assert (tmp_path / VAULT_REL).exists()
    assert (tmp_path / AGENDA_REL).exists()
    assert "Memory refreshed" in capsys.readouterr().out


def test_refresh_failure_never_kills_the_loop(tmp_path: Path, monkeypatch, capsys):
    # The supervision contract: a broken refresh reports and returns — it must
    # not raise into the daemon loop.
    _pyproject(tmp_path)
    import app.memory.vault as vault_mod

    def _boom(_root):
        raise OSError("disk went away")

    monkeypatch.setattr(vault_mod, "write_vault", _boom)
    _daemon_for(tmp_path)._refresh_memory()  # must not raise
    out = capsys.readouterr().out
    assert "Memory refresh skipped" in out
    assert "disk went away" in out


def test_daemon_cycle_calls_refresh_after_run(tmp_path: Path, monkeypatch):
    # One supervised cycle: _run_apex then _refresh_memory, in that order.
    _pyproject(tmp_path)
    daemon = _daemon_for(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(daemon, "_run_apex", lambda: calls.append("run"))

    real_refresh = daemon._refresh_memory

    def _tracked_refresh():
        calls.append("refresh")
        real_refresh()
        daemon.stop()  # end after the first full cycle

    monkeypatch.setattr(daemon, "_refresh_memory", _tracked_refresh)
    monkeypatch.setattr(daemon, "_register_signal_handlers", lambda: None)
    daemon.start()
    assert calls == ["run", "refresh"]
    assert (tmp_path / AGENDA_REL).exists()


# --------------------------------------------------------------------------- #
# assist --from-agenda hand-off
# --------------------------------------------------------------------------- #


def _assist_ns(**overrides):
    ns = argparse.Namespace(request="", target="", apply=False, commit=False,
                            json=False, from_agenda=True)
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def test_from_agenda_hands_rank_one_to_assist(tmp_path: Path, monkeypatch, capsys):
    from app import cli as cli_mod

    _pyproject(tmp_path)
    canned = {"lanes": {"landable": [
        {"rank": 1, "fix_kind": "infer_type_hints", "file": "pkg/mod.py",
         "line": 7, "category": "types", "value": 0.62},
    ]}}
    import app.engine.agenda as agenda_mod
    monkeypatch.setattr(agenda_mod, "build_agenda", lambda _root: canned)

    seen: dict[str, str] = {}

    class _Result:
        narrative = "ok"

        def to_dict(self):
            return {}

    import app.agent.assist as assist_mod

    def _fake_assist(request, target="", apply=False, commit=False):
        seen["request"] = request
        seen["apply"] = apply
        return _Result()

    monkeypatch.setattr(assist_mod, "assist", _fake_assist)
    rc = cli_mod.cmd_assist(_assist_ns(target=str(tmp_path)))
    assert rc == 0
    # The synthesized request names the action AND the file, and stays preview.
    assert seen["request"] == "infer type hints in pkg/mod.py"
    assert seen["apply"] is False
    assert "rank-1 landable" in capsys.readouterr().out


def test_from_agenda_empty_is_honest_not_an_error(tmp_path: Path, monkeypatch, capsys):
    from app import cli as cli_mod

    _pyproject(tmp_path)
    import app.engine.agenda as agenda_mod
    monkeypatch.setattr(agenda_mod, "build_agenda",
                        lambda _root: {"lanes": {"landable": []}})
    rc = cli_mod.cmd_assist(_assist_ns(target=str(tmp_path)))
    assert rc == 0
    assert "no landable entries" in capsys.readouterr().out


def test_no_request_and_no_flag_is_a_usage_error(tmp_path: Path, capsys):
    from app import cli as cli_mod

    _pyproject(tmp_path)
    rc = cli_mod.cmd_assist(_assist_ns(target=str(tmp_path), from_agenda=False))
    assert rc == 2
    assert "needs a request" in capsys.readouterr().out
