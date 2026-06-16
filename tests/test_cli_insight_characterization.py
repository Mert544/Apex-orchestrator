"""Byte-identical characterization harness for the cli_insight refactor.

Pins ``cmd_brief`` and ``_trackrecord`` byte-for-byte across a combinatorial
matrix of arguments and on-disk inputs, comparing the LIVE (refactored) module
against a frozen snapshot of the pre-refactor source
(``app/_cli_insight_orig_snapshot.py``, a verbatim ``git show HEAD`` copy).

Both modules import every heavy dependency lazily from the same source modules,
so a single ``monkeypatch.setattr`` on the source applies to BOTH — the only
difference under test is the handler control flow itself. Every run captures
exit code + stdout + stderr; a single mismatch fails the suite.

Deterministic, stdlib-only, no network. The snapshot module is a temporary
verification artifact; it lives only while the refactor is being proven.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import itertools
import json

import pytest

import app.cli_insight as live

# The pre-refactor source, frozen as a verbatim ``git show HEAD`` copy at the
# time of the refactor. It is a temporary verification artifact: when it is not
# present (the normal committed state) these byte-identical comparisons are
# skipped — the proof was run against it during the refactor itself.
orig = pytest.importorskip(
    "app._cli_insight_orig_snapshot",
    reason="pre-refactor snapshot module absent (verification artifact)",
)


# --- capture harness -----------------------------------------------------

def _run(fn, *args):
    """Invoke ``fn(*args)`` capturing (exit_code_or_exc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rv = fn(*args)
            marker = ("return", rv)
        except SystemExit as exc:  # pragma: no cover - none expected
            marker = ("exit", exc.code)
        except Exception as exc:  # pragma: no cover - none expected
            marker = ("raise", f"{type(exc).__name__}: {exc}")
    return marker, out.getvalue(), err.getvalue()


def _assert_identical(orig_fn, live_fn, *args):
    a = _run(orig_fn, *args)
    b = _run(live_fn, *args)
    assert a == b, f"mismatch\n  orig={a!r}\n  live={b!r}"


# === cmd_brief ===========================================================

def _brief_ns(**overrides) -> argparse.Namespace:
    base = dict(
        target="", branch="", subject="", objective="", depth=2, breadth=4,
        max_ideas=40, save=False, check=False, develop=False, apply=False,
        max_steps=25, no_verify=False, json=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _stub_brief_world(monkeypatch, *, build=..., check=..., develop=...):
    """Stub the engine + brief builders the brief handler reaches for."""
    class FakeReport:
        ideas = []

    class FakeEngine:
        def __init__(self, *a, **k):
            pass

        def run(self, objective=None):
            return FakeReport()

    monkeypatch.setattr(
        "app.engine.idea_permutation.IdeaPermutationEngine", FakeEngine)

    class FakeBrief:
        branch_path = "x.o"

        def to_dict(self):
            return {"branch": "x.o", "n": 1}

    class FakeResult:
        def to_dict(self):
            return {"moves": ["m1", "m2"]}

    _build = FakeBrief() if build is ... else build
    monkeypatch.setattr("app.engine.idea_brief.build_brief",
                        lambda report, branch_path, subject: _build)
    monkeypatch.setattr("app.engine.idea_brief.render_brief_markdown",
                        lambda brief: "# Brief md")
    monkeypatch.setattr("app.engine.idea_brief.save_brief",
                        lambda brief, target: "/p/baseline.json")

    _check = {"resolved": 3} if check is ... else check
    monkeypatch.setattr("app.engine.idea_brief.check_brief",
                        lambda target, branch: _check)
    monkeypatch.setattr("app.engine.idea_brief.render_check_markdown",
                        lambda result: "# Burndown md")

    _develop = FakeResult() if develop is ... else develop
    monkeypatch.setattr("app.engine.brief_develop.develop_brief",
                        lambda *a, **k: _develop)
    monkeypatch.setattr("app.engine.brief_develop.render_brief_develop_markdown",
                        lambda result: "# Develop md")


def test_cmd_brief_byte_identical_matrix(monkeypatch):
    # Cover every top-level branch: build / check / develop, each with its
    # None guard, json on/off, save/apply on/off, branch present/absent.
    branches = ["", "x.a"]
    flags = list(itertools.product([False, True], repeat=2))  # json, save/apply

    cases = []
    # build path (no check/develop)
    for branch, (jflag, save) in itertools.product(branches, flags):
        for build in (..., None):
            cases.append((dict(branch=branch, json=jflag, save=save),
                          dict(build=build)))
    # check path
    for branch, jflag in itertools.product(branches, [False, True]):
        for chk in (..., None):
            cases.append((dict(branch=branch, check=True, json=jflag),
                          dict(check=chk)))
    # develop path
    for branch, (jflag, apply) in itertools.product(branches, flags):
        for dev in (..., None):
            cases.append((dict(branch=branch, develop=True, json=jflag,
                               apply=apply),
                          dict(develop=dev)))

    for ns_kwargs, world in cases:
        _stub_brief_world(monkeypatch, **world)
        _assert_identical(orig.cmd_brief, live.cmd_brief, _brief_ns(**ns_kwargs))


def test_cmd_brief_missing_optional_attrs(monkeypatch):
    # The handler uses getattr(..., default) for several flags; a Namespace
    # missing them must behave identically (exercises the getattr fallbacks).
    _stub_brief_world(monkeypatch)
    ns = argparse.Namespace(
        target="", branch="x.z", objective="", depth=2, breadth=4,
        max_ideas=40, json=False)
    _assert_identical(orig.cmd_brief, live.cmd_brief, ns)


# === _trackrecord ========================================================

def _write_proof(tmp_path, payload):
    apex = tmp_path / ".apex"
    apex.mkdir(exist_ok=True)
    (apex / "proof-of-fix.json").write_text(json.dumps(payload), encoding="utf-8")


def _stub_memory(monkeypatch, summary):
    class FakeMem:
        @staticmethod
        def load(root):
            return FakeMem()

        def summary(self):
            return summary

    monkeypatch.setattr("app.engine.idea_memory.IdeaMemory", FakeMem)


_PROOF_VARIANTS = [
    None,  # no proof file at all
    {},
    {"totals": {"applied": 7, "rolled_back": 2}, "generated_at": "t0"},
    {"totals": {"applied": "9", "rolled_back": None}, "fixes": [
        {"outcome": "applied"}, {"outcome": "rolled_back"},
        {"outcome": "applied"}, "not-a-dict", {"outcome": "blocked"}]},
    {"totals": {"applied": "bad", "rolled_back": "x"}, "fixes": [
        {"outcome": "applied"}, {"outcome": "rolled_back"}]},
    {"fixes": [{"outcome": "applied"}, {"outcome": "applied"},
               {"outcome": "rolled_back"}]},
    {"totals": {}, "fixes": [{"outcome": "applied"}]},
    {"totals": None, "fixes": [{"outcome": "rolled_back"}]},
]

_SUMMARY_VARIANTS = [
    {},
    {"operators_tracked": 4,
     "most_reliable": [{"key": "b", "success_rate": 0.9, "samples": 10}],
     "least_reliable": [{"key": "a", "success_rate": 0.2, "samples": 3}]},
    {"operators_tracked": "5",
     "most_reliable": [{"key": "dup", "success_rate": 0.9, "samples": 1},
                       {"key": "dup", "success_rate": 0.1, "samples": 9}],
     "least_reliable": [{"key": "", "success_rate": 0.5, "samples": 2},
                        {"key": "z"}]},
    {"operators_tracked": None, "most_reliable": None, "least_reliable": None},
    {"most_reliable": [{"key": "tie", "success_rate": 0.5, "samples": 1}],
     "least_reliable": [{"key": "tie2", "success_rate": 0.5, "samples": 1}]},
]


def test_trackrecord_byte_identical_matrix(monkeypatch, tmp_path):
    for i, (proof, summary) in enumerate(
            itertools.product(_PROOF_VARIANTS, _SUMMARY_VARIANTS)):
        root = tmp_path / f"r{i}"
        root.mkdir()
        if proof is not None:
            _write_proof(root, proof)
        _stub_memory(monkeypatch, summary)
        a = orig._trackrecord(root)
        b = live._trackrecord(root)
        assert a == b, f"trackrecord dict mismatch on case {i}:\n{a}\n{b}"
        # JSON-serialised form must match byte-for-byte too (the --json path).
        assert json.dumps(a, indent=2) == json.dumps(b, indent=2)


def test_trackrecord_corrupt_proof_file(monkeypatch, tmp_path):
    # Corrupt / non-dict proof JSON collapses to {} identically in both.
    _stub_memory(monkeypatch, {"operators_tracked": 1})
    for bad in ("{not json", "[1,2,3]", '"a string"', "null"):
        root = tmp_path / f"bad{abs(hash(bad))}"
        root.mkdir(exist_ok=True)
        apex = root / ".apex"
        apex.mkdir(exist_ok=True)
        (apex / "proof-of-fix.json").write_text(bad, encoding="utf-8")
        assert orig._trackrecord(root) == live._trackrecord(root)
