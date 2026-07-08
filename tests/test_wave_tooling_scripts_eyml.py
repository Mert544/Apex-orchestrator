"""Smoke tests for the wave tooling under scripts/ — the verim+hızlandırma
paketi: ``gate_runner.py`` (content-keyed checkpoints, monitor grammar, push
retries), ``preflight.py`` (short-circuit decision table), and
``session_pulse.py`` (honest-absent reporting).

Everything subprocess- or pytest-running is mocked or exercised only through
pure helpers: no test here spawns a pytest chunk, touches the network, or
pushes. That keeps the file gate-cheap while pinning the exact contracts the
session monitor and the recovery drill depend on.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(script_name: str):
    path = ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(script_name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(script_name[:-3], mod)
    spec.loader.exec_module(mod)
    return mod


# --- verify.py: heavy-solo quarantine + impacted selection (dev-velocity) -------

def test_split_heavy_partitions_without_loss():
    v = _load("verify.py")
    files = [v.ROOT / "tests" / "test_a.py",
             v.ROOT / "tests" / "test_stub_fstring_body_eyml.py",
             v.ROOT / "tests" / "test_b.py"]
    pool, solos = v.split_heavy(files)
    assert [p.name for p in pool] == ["test_a.py", "test_b.py"]
    assert [p.name for p in solos] == ["test_stub_fstring_body_eyml.py"]
    # No loss, no duplication — every file lands on exactly one side.
    assert sorted(pool + solos, key=str) == sorted(files, key=str)


def test_split_heavy_defaults_cover_the_known_flake():
    # The quarantine list must actually contain the 3×-flaked file; an empty
    # or typo'd HEAVY_SOLO would silently put it back into the contention pool.
    v = _load("verify.py")
    assert "tests/test_stub_fstring_body_eyml.py" in v.HEAVY_SOLO
    discovered = v.discover_tests()
    pool, solos = v.split_heavy(discovered)
    assert any(p.name == "test_stub_fstring_body_eyml.py" for p in solos)
    assert not any(p.name == "test_stub_fstring_body_eyml.py" for p in pool)


def test_impacted_selection_maps_changes_through_reachability(tmp_path):
    # Pure mapping check on a tmp project: a changed module selects the test
    # that imports it; a changed test selects itself; an uncovered module is
    # DISCLOSED, never silently dropped (never-fake-green on the fast gate).
    v = _load("verify.py")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "core.py").write_text(
        "def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "lonely.py").write_text(
        "def g():\n    return 9\n", encoding="utf-8")
    (tmp_path / "tests" / "test_core.py").write_text(
        "from pkg.core import f\n\n\ndef test_f():\n    assert f() == 1\n",
        encoding="utf-8")
    files, uncovered = v.impacted_selection(
        ["pkg/core.py", "pkg/lonely.py", "tests/test_core.py", "README.md"],
        root=tmp_path)
    assert [p.name for p in files] == ["test_core.py"]
    assert uncovered == ["pkg/lonely.py"]


def test_impacted_selection_empty_changes_run_nothing(tmp_path):
    v = _load("verify.py")
    files, uncovered = v.impacted_selection([], root=tmp_path)
    assert files == [] and uncovered == []


# --- gate_runner: chunk-key purity ---------------------------------------------

def test_chunk_key_is_pure():
    gr = _load("gate_runner.py")
    assert gr.chunk_key("base", ["a", "b"]) == gr.chunk_key("base", ["a", "b"])


def test_chunk_key_is_content_sensitive():
    gr = _load("gate_runner.py")
    base = gr.chunk_key("base", ["a", "b"])
    assert base != gr.chunk_key("base", ["a", "c"])   # a test blob changed
    assert base != gr.chunk_key("other", ["a", "b"])  # app/scripts changed
    assert base != gr.chunk_key("base", ["b", "a"])   # order is part of identity


def test_chunk_key_shape_and_empty_chunk():
    gr = _load("gate_runner.py")
    key = gr.chunk_key("", [])
    assert re.fullmatch(r"[0-9a-f]{64}", key)  # sha256 hex, even for empty input


# --- gate_runner: monitor grammar ------------------------------------------------

GRAMMAR = re.compile(r"^chunk \d{2,}: (GREEN \(\d+s\)|RED \(\d+s\) rc=\d+)")


def test_chunk_line_green_grammar():
    gr = _load("gate_runner.py")
    line = gr.chunk_line(3, 0, 12.4)
    assert line == "chunk 03: GREEN (12s)"
    assert GRAMMAR.match(line)


def test_chunk_line_red_grammar():
    gr = _load("gate_runner.py")
    line = gr.chunk_line(12, 2, 100.0)
    assert line == "chunk 12: RED (100s) rc=2"
    assert GRAMMAR.match(line)


def test_chunk_line_cached_keeps_grammar_prefix():
    gr = _load("gate_runner.py")
    line = gr.chunk_line(4, 0, 0.0, cached=True)
    assert line == "chunk 04: GREEN (0s) cached"
    assert GRAMMAR.match(line)  # suffix never breaks a prefix-anchored monitor


# --- gate_runner: OOM ceiling + parser -------------------------------------------

def test_oom_ceiling_is_three_and_clamped():
    gr = _load("gate_runner.py")
    assert gr.MAX_JOBS == 3
    assert gr.effective_jobs(8) == 3   # requests above the ceiling clamp down
    assert gr.effective_jobs(0) == 1   # and never drop below one worker
    assert gr.effective_jobs(2) == 2


def test_gate_runner_parser_defaults():
    gr = _load("gate_runner.py")
    args = gr._build_parser().parse_args([])
    assert args.chunks == 16
    assert args.jobs == 3
    assert args.state_dir == ".apex/gatechk"
    assert args.tip is None and args.branch is None
    assert args.insurance is False  # insurance is OPT-IN
    assert args.no_push is False


def test_gate_runner_parser_accepts_all_flags():
    gr = _load("gate_runner.py")
    args = gr._build_parser().parse_args(
        ["--chunks", "4", "--jobs", "9", "--state-dir", "x", "--tip", "abc",
         "--branch", "b", "--insurance", "--no-push"])
    assert (args.chunks, args.jobs, args.state_dir) == (4, 9, "x")
    assert args.tip == "abc" and args.branch == "b"
    assert args.insurance and args.no_push


def test_chunk_keys_follow_content_not_git_status(monkeypatch):
    """The invalidation contract: keys change with CONTENT — a merely-flagged
    (unmodified) file changes nothing; an edited test file invalidates ONLY its
    own chunk; any app/ change invalidates every chunk. All git mocked."""
    gr = _load("gate_runner.py")
    monkeypatch.setattr(gr.wc, "head_hash", lambda spec: "tree:" + spec)
    monkeypatch.setattr(gr.wc, "working_blob_hash",
                        lambda rel: {"tests/test_a.py": "blobA"}.get(rel, "absent"))
    monkeypatch.setattr(gr, "head_test_blobs",
                        lambda: {"tests/test_a.py": "blobA",
                                 "tests/test_b.py": "blobB"})
    chunks = [[Path("tests/test_a.py")], [Path("tests/test_b.py")]]

    monkeypatch.setattr(gr.wc, "dirty_paths", lambda *p: set())
    clean = gr.chunk_keys(chunks)
    monkeypatch.setattr(gr.wc, "dirty_paths", lambda *p: {"tests/test_a.py"})
    assert gr.chunk_keys(chunks) == clean  # flagged but identical content

    monkeypatch.setattr(gr.wc, "working_blob_hash",
                        lambda rel: {"tests/test_a.py": "blobA-EDITED"}.get(rel, "absent"))
    edited = gr.chunk_keys(chunks)
    assert edited[0] != clean[0]  # its own chunk re-runs...
    assert edited[1] == clean[1]  # ...the untouched chunk stays cached

    monkeypatch.setattr(gr.wc, "dirty_paths", lambda *p: {"app/engine/new.py"})
    app_dirty = gr.chunk_keys(chunks)
    assert all(a != b for a, b in zip(clean, app_dirty))  # source change: all re-run


# --- gate_runner: checkpoints -----------------------------------------------------

def test_checkpoint_roundtrip(tmp_path):
    gr = _load("gate_runner.py")
    key = gr.chunk_key("base", ["blob1"])
    assert not gr.checkpoint_path(tmp_path, 7, key).exists()
    gr.write_checkpoint(tmp_path, 7, key, [Path("tests/test_a.py")])
    path = gr.checkpoint_path(tmp_path, 7, key)
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["chunk"] == 7 and payload["key"] == key and payload["rc"] == 0
    # A different key (content changed) does NOT reuse the old checkpoint.
    assert not gr.checkpoint_path(tmp_path, 7, gr.chunk_key("base", ["blob2"])).exists()


# --- gate_runner: push retries (pusher + sleep injected — no git, no network) ----

def test_push_with_retries_backs_off_then_succeeds(capsys):
    gr = _load("gate_runner.py")
    calls, sleeps = [], []

    def pusher(refspec):
        calls.append(refspec)
        return 1 if len(calls) < 3 else 0

    assert gr.push_with_retries("br", "abcdef123456",
                                pusher=pusher, sleep=sleeps.append) is True
    assert sleeps == [2, 4]  # the 2/4/8/16 ladder, stopped at success
    assert calls == ["HEAD:refs/heads/br"] * 3
    assert "PUSHED: origin/br @ abcdef123456" in capsys.readouterr().out


def test_push_with_retries_gives_up_after_ladder(capsys):
    gr = _load("gate_runner.py")
    sleeps = []
    assert gr.push_with_retries("br", "abcdef123456",
                                pusher=lambda r: 1, sleep=sleeps.append) is False
    assert sleeps == [2, 4, 8, 16]
    out = capsys.readouterr().out
    assert "UNPUSHED" in out and "PUSHED: origin/br" not in out


# --- gate_runner: verdict grammar --------------------------------------------------

def test_gate_verdict_all_green_line(capsys):
    gr = _load("gate_runner.py")
    assert gr.gate_verdict([0, 0, 0], 0, 0, 3, "abcdef123456") is True
    out = capsys.readouterr().out
    assert "✅ GATE ALL GREEN (3/3 chunks + ruff + north-star) on abcdef123456" in out


def test_gate_verdict_red_names_every_failure(capsys):
    gr = _load("gate_runner.py")
    assert gr.gate_verdict([0, 1, 0], 1, 1, 3, "abcdef123456") is False
    out = capsys.readouterr().out
    assert "⛔ GATE RED on abcdef123456" in out
    assert "chunk 02" in out and "ruff" in out and "north-star" in out
    assert "NOT pushing" in out


# --- gate_runner: insurance encoding ----------------------------------------------

def test_encode_bundle_is_deterministic_and_reversible():
    gr = _load("gate_runner.py")
    import base64
    import gzip
    data = b"wave bundle bytes"
    one, two = gr.encode_bundle(data), gr.encode_bundle(data)
    assert one == two  # mtime=0 pins the gzip header — transcript-stable
    assert gzip.decompress(base64.b64decode(one)) == data


# --- preflight: the pure decision table --------------------------------------------

def test_preflight_decide_empty():
    pf = _load("preflight.py")
    decision, reason = pf.decide([], [])
    assert decision == "empty" and "no changed files" in reason


def test_preflight_decide_hub_short_circuits():
    pf = _load("preflight.py")
    for hub in ("app/cli.py", "app/cli_ideate.py",
                "app/engine/objective_compiler.py",
                "app/engine/idea_action_bridge.py", "tests/conftest.py"):
        decision, reason = pf.decide([hub, "app/engine/wilson.py"], ["tests/test_a.py"])
        assert decision == "hub", hub
        assert hub in reason


def test_preflight_decide_wide_short_circuits_above_limit():
    pf = _load("preflight.py")
    at_limit = [f"tests/test_{i}.py" for i in range(pf.IMPACT_LIMIT)]
    over = at_limit + ["tests/test_over.py"]
    assert pf.decide(["app/engine/agenda.py"], at_limit)[0] == "run"  # 120 still runs
    decision, reason = pf.decide(["app/engine/agenda.py"], over)
    assert decision == "wide" and str(pf.IMPACT_LIMIT) in reason


def test_preflight_decide_uncovered_source_defers_to_full_gate():
    pf = _load("preflight.py")
    decision, reason = pf.decide(["app/engine/brand_new.py"], [])
    assert decision == "uncovered" and "app/engine/brand_new.py" in reason


def test_preflight_decide_docs_only_is_honest_empty():
    pf = _load("preflight.py")
    decision, _ = pf.decide(["docs/DEVELOPING.md", "scripts/gate_runner.py"], [])
    assert decision == "empty"


def test_preflight_is_hub_has_no_prefix_false_positives():
    pf = _load("preflight.py")
    assert pf.is_hub("app/cli.py") and pf.is_hub("app/cli_viz.py")
    assert not pf.is_hub("app/client.py")          # 'cli' prefix trap
    assert not pf.is_hub("app/climate.py")
    assert not pf.is_hub("app/engine/cli_thing.py")  # hubs live in app/, not deeper


def test_preflight_run_path_invokes_one_mocked_pytest(monkeypatch, capsys):
    pf = _load("preflight.py")
    monkeypatch.setattr(pf, "resolve_changed",
                        lambda base, files: (["app/engine/wilson.py"], "origin/x"))
    monkeypatch.setattr(pf, "impacted_test_files",
                        lambda root, changed: ["tests/test_wilson.py"])
    runs = []

    def fake_pytest(impacted):
        runs.append(list(impacted))
        return 0

    monkeypatch.setattr(pf, "run_pytest", fake_pytest)
    assert pf.main([]) == 0
    assert runs == [["tests/test_wilson.py"]]  # exactly ONE pytest invocation
    assert "GREEN" in capsys.readouterr().out


def test_preflight_red_run_exits_one(monkeypatch, capsys):
    pf = _load("preflight.py")
    monkeypatch.setattr(pf, "resolve_changed",
                        lambda base, files: (["app/engine/wilson.py"], "origin/x"))
    monkeypatch.setattr(pf, "impacted_test_files",
                        lambda root, changed: ["tests/test_wilson.py"])
    monkeypatch.setattr(pf, "run_pytest", lambda impacted: 1)
    assert pf.main([]) == 1
    assert "RED" in capsys.readouterr().out


def test_preflight_hub_change_skips_without_running_pytest(monkeypatch, capsys):
    pf = _load("preflight.py")
    monkeypatch.setattr(pf, "resolve_changed",
                        lambda base, files: (["app/cli.py"], "origin/x"))
    monkeypatch.setattr(pf, "impacted_test_files",
                        lambda root, changed: (_ for _ in ()).throw(
                            AssertionError("impact must not be computed for a hub")))
    monkeypatch.setattr(pf, "run_pytest",
                        lambda impacted: (_ for _ in ()).throw(
                            AssertionError("pytest must not run for a hub change")))
    assert pf.main([]) == 0  # 0-with-skip-notice
    assert "SKIP smoke" in capsys.readouterr().out


# --- session_pulse: honest-absent reporting ----------------------------------------

def test_pulse_agenda_absent_is_honest(tmp_path):
    sp = _load("session_pulse.py")
    line = sp.agenda_line(tmp_path / "agenda.json")
    assert "absent" in line and "agenda.json" in line


def test_pulse_agenda_rank1_landable(tmp_path):
    sp = _load("session_pulse.py")
    (tmp_path / "agenda.json").write_text(json.dumps({"lanes": {"landable": [
        {"fix_kind": "add_docstring", "file": "app/a.py", "line": 7,
         "value": 0.5, "rank": 1},
        {"fix_kind": "other", "file": "app/b.py", "line": 1, "value": 0.4,
         "rank": 2},
    ]}}), encoding="utf-8")
    line = sp.agenda_line(tmp_path / "agenda.json")
    assert "add_docstring" in line and "app/a.py:7" in line  # rank-1, not rank-2
    assert "other" not in line


def test_pulse_agenda_unreadable_and_empty_are_honest(tmp_path):
    sp = _load("session_pulse.py")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert "unreadable" in sp.agenda_line(bad)
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"lanes": {"landable": []}}), encoding="utf-8")
    assert "no landable entries" in sp.agenda_line(empty)


def test_pulse_progress_newest_entry_and_absent(tmp_path):
    sp = _load("session_pulse.py")
    assert "absent" in sp.progress_line(tmp_path / "PROGRESS.md")
    (tmp_path / "PROGRESS.md").write_text(
        "# Header\n\n> intro block\n\n---\n\n"
        "**W99 WAVE — the newest entry line.**\n\nolder text\n",
        encoding="utf-8")
    line = sp.progress_line(tmp_path / "PROGRESS.md")
    assert line.startswith("progress: **W99 WAVE")
    assert "older text" not in line


def test_pulse_deferred_markers_found_and_none(tmp_path):
    sp = _load("session_pulse.py")
    path = tmp_path / "PROGRESS.md"
    path.write_text("---\nERTELENEN: thing one\nnormal line\n"
                    "AÇIK KARAR: thing two\n", encoding="utf-8")
    lines = sp.deferred_lines(path)
    assert lines[0].startswith("deferred: 2 marker line(s)")
    assert any("thing one" in line for line in lines)
    assert any("thing two" in line for line in lines)
    path.write_text("---\nnothing deferred here\n", encoding="utf-8")
    assert "none found" in sp.deferred_lines(path)[0]


def test_pulse_gatechk_absent_empty_and_fast(tmp_path):
    sp = _load("session_pulse.py")
    assert "no checkpoint dir" in sp.gatechk_line(tmp_path / "gatechk")
    state = tmp_path / "gatechk"
    state.mkdir()
    assert "0 checkpoints" in sp.gatechk_line(state)
    (state / "chunk-01-abcdef0123456789.json").write_text("{}", encoding="utf-8")
    fast = sp.gatechk_line(state, fast=True)
    assert "1 checkpoint file(s)" in fast and "not verified" in fast


def test_pulse_parser_defaults():
    sp = _load("session_pulse.py")
    args = sp._build_parser().parse_args([])
    assert args.fast is False
    assert sp._build_parser().parse_args(["--fast"]).fast is True
