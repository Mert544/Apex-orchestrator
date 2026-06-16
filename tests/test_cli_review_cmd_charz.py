"""Characterization harness: prove `cmd_review` is byte-identical before vs
after the decomposition refactor.

The pre-refactor function body is loaded verbatim from the HEAD snapshot
(`git show HEAD:app/cli_review.py`, captured at the refactor's base commit and
re-embedded here so the test is self-contained) and run side-by-side with the
current implementation against the SAME stubbed dependencies across many
arg/input combinations. For every scenario the stdout, the exit code, and the
bytes of any file written must match exactly. Offline, stdlib-only,
deterministic.
"""
from __future__ import annotations

import argparse
import importlib
import io
import types
from contextlib import redirect_stderr, redirect_stdout

import pytest

import app.cli_review as cr
from app.engine.diff_review import ReviewFinding, ReviewResult

# ── The verbatim pre-refactor cmd_review (HEAD snapshot) ─────────────────────
# This is the EXACT body of `cmd_review` as it stood at the refactor's base
# commit (extracted via `git show HEAD:app/cli_review.py`); copied byte-for-byte
# so the harness compares against the genuine original, not a paraphrase. Its
# free names (`Path`, `json`, `_get_project_root`, `_apply_review_fixes`,
# `_render_findings_format`, `_render_review_fixes_markdown`) are injected from
# the live `app.cli_review` module so both versions share identical helpers.
_ORIGINAL_SRC = '''
def cmd_review(args):
    from app.engine.diff_review import (
        render_review_markdown,
        render_review_summary,
        review,
    )

    target = Path(args.target).resolve() if args.target else _get_project_root()
    result = review(str(target), base=getattr(args, "base", "HEAD") or "HEAD")

    if getattr(args, "summary", False):
        print(render_review_summary(result))
        if getattr(args, "fail_on_high", False):
            from app.engine.diff_review import blocking_high_findings

            if blocking_high_findings(result):
                return 1
        return 0

    fix_report = None
    if getattr(args, "fix", False):
        fix_report = _apply_review_fixes(str(target), result)

    sarif_out = getattr(args, "sarif", "")
    if sarif_out:
        from app.engine.sarif_export import review_to_sarif

        sarif_path = Path(sarif_out)
        sarif_path.parent.mkdir(parents=True, exist_ok=True)
        sarif_path.write_text(json.dumps(review_to_sarif(result), indent=2) + "\\n",
                              encoding="utf-8")

    fmt = getattr(args, "format", "") or ""
    if fmt:
        text = _render_findings_format(fmt, result)
        fmt_out = getattr(args, "format_out", "") or ""
        if fmt_out:
            p = Path(fmt_out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text if text.endswith("\\n") else text + "\\n", encoding="utf-8")
            print(f"[review] {fmt} written to {fmt_out}")
        else:
            print(text)
        if getattr(args, "fail_on_high", False):
            from app.engine.diff_review import blocking_high_findings

            if blocking_high_findings(result):
                return 1
        return 0

    if args.json:
        payload = result.to_dict()
        if fix_report is not None:
            payload["fixes"] = fix_report
        print(json.dumps(payload, indent=2))
    else:
        print(render_review_markdown(result, limit=getattr(args, "max_findings", 0) or 0))
        if fix_report is not None:
            print(_render_review_fixes_markdown(fix_report))
        if sarif_out:
            print(f"[review] SARIF written to {sarif_out}")
    if getattr(args, "fail_on_high", False):
        from app.engine.diff_review import blocking_high_findings

        if blocking_high_findings(result):
            return 1
    return 0
'''


def _load_original():
    import json as _json
    from pathlib import Path as _Path
    mod = types.ModuleType("_cli_review_cmd_original")
    mod.__dict__.update({
        "Path": _Path,
        "json": _json,
        "_get_project_root": cr._get_project_root,
        "_apply_review_fixes": cr._apply_review_fixes,
        "_render_findings_format": cr._render_findings_format,
        "_render_review_fixes_markdown": cr._render_review_fixes_markdown,
    })
    exec(compile(_ORIGINAL_SRC, "<original>", "exec"), mod.__dict__)
    return mod.cmd_review


def _ns(**overrides):
    base = dict(target="", base="HEAD", json=False, fail_on_high=False,
                summary=False, fix=False, sarif="", format="", format_out="",
                max_findings=0)
    base.update(overrides)
    return argparse.Namespace(**base)


def _rf(file, severity, kind="convention", auto=True):
    return ReviewFinding(file, 5, "convention", severity, f"msg {file}",
                         auto_fixable=auto, fix_kind=kind)


# Each scenario builds a fresh ReviewResult so the two runs never share state.
_RESULTS = {
    "clean": lambda: ReviewResult(base="HEAD", files_reviewed=2, findings=[]),
    "low": lambda: ReviewResult(base="HEAD", files_reviewed=1,
                                findings=[_rf("app/a.py", "low")]),
    "high": lambda: ReviewResult(base="HEAD", files_reviewed=3,
                                 findings=[_rf("app/a.py", "high"),
                                           _rf("app/b.py", "medium")]),
}


def _scenarios(tmp):
    return [
        ("default_clean", _ns(), "clean"),
        ("default_high", _ns(), "high"),
        ("json_low", _ns(json=True), "low"),
        ("json_high", _ns(json=True), "high"),
        ("failonhigh_clean", _ns(fail_on_high=True), "clean"),
        ("failonhigh_high", _ns(fail_on_high=True), "high"),
        ("failonhigh_low", _ns(fail_on_high=True), "low"),
        ("json_failonhigh_high", _ns(json=True, fail_on_high=True), "high"),
        ("summary_clean", _ns(summary=True), "clean"),
        ("summary_high", _ns(summary=True), "high"),
        ("summary_failonhigh_high", _ns(summary=True, fail_on_high=True), "high"),
        ("summary_failonhigh_clean", _ns(summary=True, fail_on_high=True), "clean"),
        ("fix_high", _ns(fix=True), "high"),
        ("fix_json_high", _ns(fix=True, json=True), "high"),
        ("fix_failonhigh_high", _ns(fix=True, fail_on_high=True), "high"),
        ("format_stdout_high", _ns(format="csv"), "high"),
        ("format_stdout_clean", _ns(format="github"), "clean"),
        ("format_failonhigh_high", _ns(format="junit", fail_on_high=True), "high"),
        ("format_failonhigh_low", _ns(format="csv", fail_on_high=True), "low"),
        ("format_out_high", _ns(format="csv", format_out=str(tmp / "out.csv")), "high"),
        ("format_out_nested", _ns(format="junit",
                                  format_out=str(tmp / "sub" / "o.xml")), "low"),
        ("sarif_high", _ns(sarif=str(tmp / "s.sarif")), "high"),
        ("sarif_nested", _ns(sarif=str(tmp / "deep" / "s.sarif")), "low"),
        ("sarif_json_high", _ns(sarif=str(tmp / "s2.sarif"), json=True), "high"),
        ("sarif_fix_high", _ns(sarif=str(tmp / "s3.sarif"), fix=True), "high"),
        ("maxfindings", _ns(max_findings=1), "high"),
        ("base_override", _ns(base="main~3"), "low"),
        ("base_empty", _ns(base=""), "low"),
    ]


def _patch(monkeypatch, captured):
    """Stub every external dependency both versions call, deterministically.
    Render fns return sentinel strings keyed by their args; review returns the
    scenario's prebuilt result; file-writers go through the real Path so written
    bytes are comparable. `_apply_review_fixes` is stubbed to a fixed report."""
    import app.engine.diff_review as dr
    import app.engine.sarif_export as se

    monkeypatch.setattr(dr, "render_review_markdown",
                        lambda result, limit=0: f"MD<files={result.files_reviewed},limit={limit}>")
    monkeypatch.setattr(dr, "render_review_summary",
                        lambda result, top=8: f"SUMMARY<files={result.files_reviewed}>")
    monkeypatch.setattr(dr, "blocking_high_findings",
                        lambda result: [f for f in result.findings if f.severity == "high"])
    monkeypatch.setattr(se, "review_to_sarif",
                        lambda result: {"version": "2.1.0",
                                        "files": result.files_reviewed})
    monkeypatch.setattr(cr, "_render_findings_format",
                        lambda fmt, result: f"FMT[{fmt}]files={result.files_reviewed}")
    monkeypatch.setattr(cr, "_apply_review_fixes",
                        lambda target, result: {"applied": [{"file": "x", "transform": "t"}],
                                                "applied_count": 1, "files_touched": ["x"],
                                                "blocked": []})


def _run(fn, args, result, monkeypatch):
    import app.engine.diff_review as dr
    monkeypatch.setattr(dr, "review", lambda root, base="HEAD": result)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = fn(args)
    return rc, out.getvalue(), err.getvalue()


def _snapshot(root):
    """Map of {relative-posix-path: bytes} for every file under ``root``."""
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("name", [s[0] for s in _scenarios(__import__("pathlib").Path("/tmp"))])
def test_cmd_review_byte_identical(name, tmp_path, monkeypatch):
    # Both runs target the SAME directory so any path echoed into stdout (the
    # SARIF note / format-out message) is identical — a genuine byte compare,
    # not a path artifact. The original's written files are snapshotted, then
    # the tree is wiped, then the refactored run writes into the same paths.
    shared = tmp_path / "shared"
    shared.mkdir()

    _, args, result_key = {s[0]: s for s in _scenarios(shared)}[name]

    _patch(monkeypatch, None)

    original = _load_original()
    rc_o, out_o, err_o = _run(original, args, _RESULTS[result_key](), monkeypatch)
    files_o = _snapshot(shared)

    for p in sorted(shared.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()

    rc_n, out_n, err_n = _run(cr.cmd_review, args, _RESULTS[result_key](), monkeypatch)
    files_n = _snapshot(shared)

    assert rc_n == rc_o, f"{name}: exit {rc_n} != {rc_o}"
    assert out_n == out_o, f"{name}: stdout {out_n!r} != {out_o!r}"
    assert err_n == err_o, f"{name}: stderr {err_n!r} != {err_o!r}"
    assert files_n == files_o, f"{name}: written files differ"


def test_format_out_message_uses_literal_path(tmp_path, monkeypatch):
    # Guards the one place the written-file path appears in stdout: the
    # "[review] csv written to <path>" line must echo the exact format_out arg.
    _patch(monkeypatch, None)
    out_path = tmp_path / "report.csv"
    args = _ns(format="csv", format_out=str(out_path))
    rc, out, err = _run(cr.cmd_review, args, _RESULTS["high"](), monkeypatch)
    assert rc == 0
    assert out == f"[review] csv written to {out_path}\n"
    assert out_path.read_text() == "FMT[csv]files=3\n"


def test_module_importer_reexports_cmd_review():
    # app.cli must still re-export cmd_review (import-surface invariant).
    cli = importlib.import_module("app.cli")
    assert cli.cmd_review is cr.cmd_review
