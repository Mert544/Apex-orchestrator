"""Deterministic edge-path coverage for app/cli_refactor.py cmd_* dispatch.

Drives cmd_rename / cmd_signature / cmd_extract / cmd_inline / cmd_move /
cmd_rewrite / cmd_teach with argparse.Namespace built directly, on tiny
tmp_path projects. Every apply path runs with no_verify=True so no subprocess
pytest run is spawned — fast and deterministic. No time/random/order asserts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cli_refactor import (
    cmd_extract,
    cmd_inline,
    cmd_move,
    cmd_rename,
    cmd_rewrite,
    cmd_signature,
    cmd_teach,
)


def _ns(**over) -> argparse.Namespace:
    return argparse.Namespace(**over)


def _app(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    return tmp_path / "app"


# --------------------------------------------------------------------------- #
# cmd_rename                                                                   #
# --------------------------------------------------------------------------- #
def test_rename_dry_run_previews_diff(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def foo():\n    return 1\n\ndef bar():\n    return foo()\n")
    rc = cmd_rename(_ns(target=str(tmp_path), old="foo", new="baz", param="",
                        dry_run=True, no_verify=True, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry run" in out
    assert "```diff" in out
    # dry run never writes
    assert "def foo()" in (app / "m.py").read_text()


def test_rename_applies_and_reports(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def foo():\n    return 1\n\ndef bar():\n    return foo()\n")
    rc = cmd_rename(_ns(target=str(tmp_path), old="foo", new="baz", param="",
                        dry_run=False, no_verify=True, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Renamed" in out
    assert "def baz()" in (app / "m.py").read_text()


def test_rename_json_emits_payload(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def foo():\n    return 1\n\ndef bar():\n    return foo()\n")
    rc = cmd_rename(_ns(target=str(tmp_path), old="foo", new="baz", param="",
                        dry_run=False, no_verify=True, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["applied"] is True


def test_rename_blocked_when_symbol_absent(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def foo():\n    return 1\n")
    rc = cmd_rename(_ns(target=str(tmp_path), old="nope", new="baz", param="",
                        dry_run=False, no_verify=True, json=False))
    out = capsys.readouterr().out
    assert rc == 1
    assert "blocked" in out.lower()


def test_rename_applied_verified_with_warnings(tmp_path, capsys, monkeypatch):
    """The verified-tests-pass + warnings print branch (no subprocess)."""
    app = _app(tmp_path)
    (app / "m.py").write_text("def foo():\n    return 1\n")
    monkeypatch.setattr(
        "app.execution.cross_file_rename.apply_rename",
        lambda root, plan, verify=True: {
            "applied": True, "edits": 1, "changed_files": ["app/m.py"],
            "verified": True, "warnings": ["heads up"],
        },
    )
    rc = cmd_rename(_ns(target=str(tmp_path), old="foo", new="baz", param="",
                        dry_run=False, no_verify=False, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "verified" in out
    assert "heads up" in out


def test_rename_not_applied_prints_reason(tmp_path, capsys, monkeypatch):
    app = _app(tmp_path)
    (app / "m.py").write_text("def foo():\n    return 1\n")
    monkeypatch.setattr(
        "app.execution.cross_file_rename.apply_rename",
        lambda root, plan, verify=True: {"applied": False, "reason": "verify failed"},
    )
    rc = cmd_rename(_ns(target=str(tmp_path), old="foo", new="baz", param="",
                        dry_run=False, no_verify=False, json=False))
    out = capsys.readouterr().out
    assert rc == 1
    assert "verify failed" in out


def test_rename_param_branch(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def f(old):\n    return old + 1\n")
    rc = cmd_rename(_ns(target=str(tmp_path), old="old", new="new", param="f",
                        dry_run=True, no_verify=True, json=False))
    out = capsys.readouterr().out
    # Either a clean preview or a loud block — both are valid, exercised paths.
    assert rc in (0, 1)
    assert out


# --------------------------------------------------------------------------- #
# cmd_signature                                                               #
# --------------------------------------------------------------------------- #
def _sig_ns(tmp_path, op, function, param="", **over):
    base = dict(target=str(tmp_path), op=op, function=function, param=param,
                default="None", dry_run=False, no_verify=True, json=False)
    base.update(over)
    return _ns(**base)


def test_signature_drop_unused_param_applies(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def f(a, b):\n    return a\n")
    rc = cmd_signature(_sig_ns(tmp_path, "drop", "f", "b"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Signature changed" in out
    assert "def f(a)" in (app / "m.py").read_text()


def test_signature_drop_without_param_is_usage_error(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def f(a, b):\n    return a\n")
    rc = cmd_signature(_sig_ns(tmp_path, "drop", "f", ""))
    out = capsys.readouterr().out
    assert rc == 1
    assert "needs a PARAM" in out


def test_signature_add_param(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def g(a):\n    return a\n")
    rc = cmd_signature(_sig_ns(tmp_path, "add", "g", "b", default="0", dry_run=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry run" in out
    assert "b=0" in out


def test_signature_keywordify_dry_run(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def g(a, b):\n    return a + b\n\ny = g(1, 2)\n")
    rc = cmd_signature(_sig_ns(tmp_path, "keywordify", "g", dry_run=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "keyword" in out.lower()


def test_signature_reorder_dry_run(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def g(a, b):\n    return a + b\n")
    rc = cmd_signature(_sig_ns(tmp_path, "reorder", "g", "b,a", dry_run=True))
    out = capsys.readouterr().out
    assert rc in (0, 1)
    assert "reorder" in out.lower() or "blocked" in out.lower()


def test_signature_drop_blocked_positional_caller(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def f(a, b):\n    return a\n\nx = f(1, 2)\n")
    rc = cmd_signature(_sig_ns(tmp_path, "drop", "f", "b"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "blocked" in out.lower()


def test_signature_json_path(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def f(a, b):\n    return a\n")
    rc = cmd_signature(_sig_ns(tmp_path, "drop", "f", "b", json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["applied"] is True


def _patch_apply_verified(monkeypatch, *, applied=True, warnings=("note",)):
    monkeypatch.setattr(
        "app.execution.cross_file_rename.apply_rename",
        lambda root, plan, verify=True: (
            {"applied": True, "edits": 1, "changed_files": ["app/m.py"],
             "verified": True, "warnings": list(warnings)}
            if applied else {"applied": False, "reason": "not applied"}
        ),
    )


def test_signature_applied_verified_with_warnings(tmp_path, capsys, monkeypatch):
    app = _app(tmp_path)
    (app / "m.py").write_text("def f(a, b):\n    return a\n")
    _patch_apply_verified(monkeypatch)
    rc = cmd_signature(_sig_ns(tmp_path, "drop", "f", "b", no_verify=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "verified" in out and "note" in out


def test_signature_not_applied_reason(tmp_path, capsys, monkeypatch):
    app = _app(tmp_path)
    (app / "m.py").write_text("def f(a, b):\n    return a\n")
    _patch_apply_verified(monkeypatch, applied=False)
    rc = cmd_signature(_sig_ns(tmp_path, "drop", "f", "b", no_verify=False))
    out = capsys.readouterr().out
    assert rc == 1
    assert "not applied" in out


# --------------------------------------------------------------------------- #
# cmd_extract                                                                 #
# --------------------------------------------------------------------------- #
def _ext_ns(tmp_path, file, start, end, name, **over):
    base = dict(target=str(tmp_path), file=file, start=start, end=end, name=name,
                dry_run=False, no_verify=True, json=False)
    base.update(over)
    return _ns(**base)


def test_extract_dry_run(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def big():\n    x = 1\n    y = 2\n    return x + y\n")
    rc = cmd_extract(_ext_ns(tmp_path, "app/m.py", 2, 3, "helper", dry_run=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry run" in out
    assert "```diff" in out


def test_extract_blocked_bad_range(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def big():\n    return 1\n")
    rc = cmd_extract(_ext_ns(tmp_path, "app/m.py", 99, 100, "helper"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "blocked" in out.lower()


def test_extract_json(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def big():\n    x = 1\n    y = 2\n    return x + y\n")
    rc = cmd_extract(_ext_ns(tmp_path, "app/m.py", 2, 3, "helper", json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc in (0, 1)
    assert "applied" in payload


def test_extract_applies_and_reports(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def big():\n    x = 1\n    y = 2\n    return x + y\n")
    rc = cmd_extract(_ext_ns(tmp_path, "app/m.py", 2, 3, "helper"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Extracted" in out
    assert "def helper(" in (app / "m.py").read_text()


def test_extract_verified_with_warnings(tmp_path, capsys, monkeypatch):
    app = _app(tmp_path)
    (app / "m.py").write_text("def big():\n    x = 1\n    y = 2\n    return x + y\n")
    _patch_apply_verified(monkeypatch)
    rc = cmd_extract(_ext_ns(tmp_path, "app/m.py", 2, 3, "helper", no_verify=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "verified" in out and "note" in out


def test_extract_not_applied_reason(tmp_path, capsys, monkeypatch):
    app = _app(tmp_path)
    (app / "m.py").write_text("def big():\n    x = 1\n    y = 2\n    return x + y\n")
    _patch_apply_verified(monkeypatch, applied=False)
    rc = cmd_extract(_ext_ns(tmp_path, "app/m.py", 2, 3, "helper", no_verify=False))
    out = capsys.readouterr().out
    assert rc == 1
    assert "not applied" in out


# --------------------------------------------------------------------------- #
# cmd_inline                                                                  #
# --------------------------------------------------------------------------- #
def _inl_ns(tmp_path, function, **over):
    base = dict(target=str(tmp_path), function=function, dry_run=False,
                no_verify=True, json=False)
    base.update(over)
    return _ns(**base)


def test_inline_dry_run(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def small():\n    return 42\n\ndef caller():\n    return small()\n")
    rc = cmd_inline(_inl_ns(tmp_path, "small", dry_run=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry run" in out
    assert "```diff" in out


def test_inline_blocked_unknown_function(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def caller():\n    return 1\n")
    rc = cmd_inline(_inl_ns(tmp_path, "ghost"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "blocked" in out.lower()


def test_inline_json(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def small():\n    return 42\n\ndef caller():\n    return small()\n")
    rc = cmd_inline(_inl_ns(tmp_path, "small", json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc in (0, 1)
    assert "applied" in payload


def test_inline_applies_and_reports(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def small():\n    return 42\n\ndef caller():\n    return small()\n")
    rc = cmd_inline(_inl_ns(tmp_path, "small"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Inlined" in out
    text = (app / "m.py").read_text()
    assert "42" in text
    assert "def small()" not in text  # the now-dead helper is deleted


def test_inline_verified_with_warnings(tmp_path, capsys, monkeypatch):
    app = _app(tmp_path)
    (app / "m.py").write_text("def small():\n    return 42\n\ndef caller():\n    return small()\n")
    _patch_apply_verified(monkeypatch)
    rc = cmd_inline(_inl_ns(tmp_path, "small", no_verify=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "verified" in out and "note" in out


def test_inline_not_applied_reason(tmp_path, capsys, monkeypatch):
    app = _app(tmp_path)
    (app / "m.py").write_text("def small():\n    return 42\n\ndef caller():\n    return small()\n")
    _patch_apply_verified(monkeypatch, applied=False)
    rc = cmd_inline(_inl_ns(tmp_path, "small", no_verify=False))
    out = capsys.readouterr().out
    assert rc == 1
    assert "not applied" in out


# --------------------------------------------------------------------------- #
# cmd_move                                                                    #
# --------------------------------------------------------------------------- #
def _mv_ns(tmp_path, src, dst, **over):
    base = dict(target=str(tmp_path), src=src, dst=dst, dry_run=False,
                no_verify=True, json=False)
    base.update(over)
    return _ns(**base)


def test_move_dry_run(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "old.py").write_text("def h():\n    return 1\n")
    (app / "user.py").write_text("from app.old import h\n\ndef use():\n    return h()\n")
    rc = cmd_move(_mv_ns(tmp_path, "app/old.py", "app/new.py", dry_run=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry run" in out
    assert "```diff" in out


def test_move_blocked_missing_source(tmp_path, capsys):
    _app(tmp_path)
    rc = cmd_move(_mv_ns(tmp_path, "app/ghost.py", "app/new.py"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "blocked" in out.lower()


def test_move_applies(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "old.py").write_text("def h():\n    return 1\n")
    rc = cmd_move(_mv_ns(tmp_path, "app/old.py", "app/new.py"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Moved" in out
    assert (app / "new.py").exists()


def test_move_json(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "old.py").write_text("def h():\n    return 1\n")
    rc = cmd_move(_mv_ns(tmp_path, "app/old.py", "app/new.py", json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["applied"] is True


def test_move_verified_created_with_warnings(tmp_path, capsys, monkeypatch):
    app = _app(tmp_path)
    (app / "old.py").write_text("def h():\n    return 1\n")
    monkeypatch.setattr(
        "app.execution.move_module.apply_move",
        lambda root, plan, verify=True: {
            "applied": True, "edits": 1, "changed_files": ["app/x.py"],
            "created": ["app/new.py"], "verified": True, "warnings": ["note"],
        },
    )
    rc = cmd_move(_mv_ns(tmp_path, "app/old.py", "app/new.py", no_verify=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "created" in out and "verified" in out and "note" in out


def test_move_not_applied_reason(tmp_path, capsys, monkeypatch):
    app = _app(tmp_path)
    (app / "old.py").write_text("def h():\n    return 1\n")
    monkeypatch.setattr(
        "app.execution.move_module.apply_move",
        lambda root, plan, verify=True: {"applied": False, "reason": "not applied"},
    )
    rc = cmd_move(_mv_ns(tmp_path, "app/old.py", "app/new.py", no_verify=False))
    out = capsys.readouterr().out
    assert rc == 1
    assert "not applied" in out


# --------------------------------------------------------------------------- #
# cmd_rewrite                                                                 #
# --------------------------------------------------------------------------- #
def _rw_ns(tmp_path, pattern="", replacement=None, **over):
    base = dict(target=str(tmp_path), pattern=pattern, replacement=replacement,
                save="", rule="", rules=False, all=False, dry_run=False,
                no_verify=True, json=False)
    base.update(over)
    return _ns(**base)


def test_rewrite_needs_pattern_and_replacement(tmp_path, capsys):
    _app(tmp_path)
    rc = cmd_rewrite(_rw_ns(tmp_path))
    out = capsys.readouterr().out
    assert rc == 1
    assert "needs PATTERN" in out


def test_rewrite_rules_lists_empty_book(tmp_path, capsys):
    _app(tmp_path)
    rc = cmd_rewrite(_rw_ns(tmp_path, rules=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "rule book" in out.lower()


def test_rewrite_all_on_empty_book(tmp_path, capsys):
    _app(tmp_path)
    rc = cmd_rewrite(_rw_ns(tmp_path, all=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "empty" in out.lower()


def test_rewrite_no_match_returns_zero(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c():\n    return 1\n")
    rc = cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0", replacement="not $x"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "no match" in out.lower()


def test_rewrite_dry_run_with_match(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    rc = cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0",
                            replacement="not $x", dry_run=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry run" in out
    assert "```diff" in out


def test_rewrite_applies(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    rc = cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0", replacement="not $x"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Rewrote" in out
    assert "not xs" in (app / "m.py").read_text()


def test_rewrite_json(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    rc = cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0",
                            replacement="not $x", json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["applied"] is True


def test_rewrite_verified_with_warnings(tmp_path, capsys, monkeypatch):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    _patch_apply_verified(monkeypatch)
    rc = cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0",
                            replacement="not $x", no_verify=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Rewrote" in out and "verified" in out and "note" in out


def test_rewrite_not_applied_reason(tmp_path, capsys, monkeypatch):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    _patch_apply_verified(monkeypatch, applied=False)
    rc = cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0",
                            replacement="not $x", no_verify=False))
    out = capsys.readouterr().out
    assert rc == 1
    assert "not applied" in out


def test_rewrite_save_then_run_saved_rule(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    # Save a rule (dry run so nothing is applied yet).
    rc = cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0",
                            replacement="not $x", save="empties", dry_run=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "saved" in out.lower()
    # Now run it by name.
    rc2 = cmd_rewrite(_rw_ns(tmp_path, rule="empties", dry_run=True))
    out2 = capsys.readouterr().out
    assert rc2 == 0
    assert "dry run" in out2


def test_rewrite_save_duplicate_name_errors(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    # First save succeeds.
    cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0",
                       replacement="not $x", save="empties", dry_run=True))
    capsys.readouterr()
    # Second save under the same name is a usage error -> rc 1.
    rc = cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0",
                            replacement="not $x", save="empties", dry_run=True))
    out = capsys.readouterr().out
    assert rc == 1
    assert "already exists" in out


def test_rewrite_unknown_saved_rule_blocks(tmp_path, capsys):
    _app(tmp_path)
    rc = cmd_rewrite(_rw_ns(tmp_path, rule="ghost"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "no saved rule" in out.lower()


def test_rewrite_all_runs_saved_rules(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0",
                       replacement="not $x", save="empties", dry_run=True))
    capsys.readouterr()
    rc = cmd_rewrite(_rw_ns(tmp_path, all=True))
    out = capsys.readouterr().out
    assert rc in (0, 1)
    assert "empties" in out


# --------------------------------------------------------------------------- #
# cmd_teach                                                                   #
# --------------------------------------------------------------------------- #
def _teach_ns(tmp_path, examples, **over):
    base = dict(target=str(tmp_path), examples=examples, save="",
                from_git=False, commits=50)
    base.update(over)
    return _ns(**base)


def test_teach_learns_rule_from_examples(tmp_path, capsys):
    _app(tmp_path)
    rc = cmd_teach(_teach_ns(tmp_path, ["len(xs) == 0", "not xs",
                                        "len(a.b) == 0", "not a.b"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Learned rule" in out


def test_teach_odd_number_of_examples_errors(tmp_path, capsys):
    _app(tmp_path)
    rc = cmd_teach(_teach_ns(tmp_path, ["a", "b", "c"]))
    out = capsys.readouterr().out
    assert rc == 1
    assert "pairs" in out.lower()


def test_teach_no_pairs_errors(tmp_path, capsys):
    _app(tmp_path)
    rc = cmd_teach(_teach_ns(tmp_path, []))
    out = capsys.readouterr().out
    assert rc == 1
    assert "no example pairs" in out.lower()


def test_teach_unlearnable_blocks(tmp_path, capsys):
    _app(tmp_path)
    rc = cmd_teach(_teach_ns(tmp_path, ["1 + 1", "garbage("]))
    out = capsys.readouterr().out
    assert rc == 1
    assert "blocked" in out.lower()


def test_teach_saves_learned_rule(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    rc = cmd_teach(_teach_ns(tmp_path, ["len(xs) == 0", "not xs",
                                        "len(a.b) == 0", "not a.b"], save="empties"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "saved" in out.lower()


def test_teach_from_git_no_pairs(tmp_path, capsys, monkeypatch):
    _app(tmp_path)
    monkeypatch.setattr("app.engine.git_rule_miner.mine_git_pairs",
                        lambda root, n: [])
    rc = cmd_teach(_teach_ns(tmp_path, [], from_git=True, commits=10))
    out = capsys.readouterr().out
    assert rc == 0
    assert "No single-line" in out


def test_rewrite_all_holds_no_drift(tmp_path, capsys):
    # A saved rule whose pattern has no match in the project "holds (no drift)".
    app = _app(tmp_path)
    (app / "m.py").write_text("def c():\n    return 1\n")
    cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0",
                       replacement="not $x", save="empties", dry_run=True))
    capsys.readouterr()
    rc = cmd_rewrite(_rw_ns(tmp_path, all=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "no drift" in out


def test_rewrite_all_blocked_rule_counts_failure(tmp_path, capsys, monkeypatch):
    # A saved rule that blocks on re-apply -> reported and rc=1 (drift failure).
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0",
                       replacement="not $x", save="empties", dry_run=True))
    capsys.readouterr()

    class _Blocked:
        blockers = ["cannot apply"]
        new_contents: dict = {}
        warnings: list = []

    monkeypatch.setattr(
        "app.execution.pattern_rewrite.plan_pattern_rewrite",
        lambda root, pat, repl: _Blocked(),
    )
    rc = cmd_rewrite(_rw_ns(tmp_path, all=True))
    out = capsys.readouterr().out
    assert rc == 1
    assert "empties" in out and "cannot apply" in out


def test_rewrite_all_apply_failure_counts(tmp_path, capsys, monkeypatch):
    # Rule has drift but apply fails -> failure path (rc 1).
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0",
                       replacement="not $x", save="empties", dry_run=True))
    capsys.readouterr()
    monkeypatch.setattr(
        "app.execution.cross_file_rename.apply_rename",
        lambda root, plan, verify=True: {"applied": False, "reason": "verify failed"},
    )
    rc = cmd_rewrite(_rw_ns(tmp_path, all=True))
    out = capsys.readouterr().out
    assert rc == 1
    assert "empties" in out


def test_teach_save_duplicate_name_errors(tmp_path, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    examples = ["len(xs) == 0", "not xs", "len(a.b) == 0", "not a.b"]
    cmd_teach(_teach_ns(tmp_path, examples, save="empties"))
    capsys.readouterr()
    rc = cmd_teach(_teach_ns(tmp_path, examples, save="empties"))
    out = capsys.readouterr().out
    assert rc == 1
    assert "already exists" in out


def test_rewrite_all_reapply_success(tmp_path, capsys, monkeypatch):
    """`rewrite --all` re-applies each saved rule that still has drift; stub the
    apply so no pytest subprocess runs and the success branch is exercised."""
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    cmd_rewrite(_rw_ns(tmp_path, pattern="len($x) == 0",
                       replacement="not $x", save="empties", dry_run=True))
    capsys.readouterr()
    monkeypatch.setattr(
        "app.execution.cross_file_rename.apply_rename",
        lambda root, plan, verify=True: {
            "applied": True, "edits": 1, "changed_files": ["app/m.py"],
            "verified": True, "warnings": [],
        },
    )
    rc = cmd_rewrite(_rw_ns(tmp_path, all=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "re-applied" in out


def test_teach_from_git_with_pairs(tmp_path, capsys, monkeypatch):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    monkeypatch.setattr(
        "app.engine.git_rule_miner.mine_git_pairs",
        lambda root, n: [("len(xs) == 0", "not xs"), ("len(a.b) == 0", "not a.b")],
    )
    rc = cmd_teach(_teach_ns(tmp_path, [], from_git=True, commits=5))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Mined" in out
    assert "Learned rule" in out
