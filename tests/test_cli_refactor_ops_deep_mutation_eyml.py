"""Deep mutation-hardening regression guards for app/cli_refactor.py and
app/cli_ops.py.

Context: an exhaustive enumeration of the FULL single-token mutant universe
(176 mutants for cli_refactor, 86 for cli_ops — well past the default 30-cap)
was run against the modules' covering test suites. Every non-equivalent mutant
was already killed, so there were no surviving blind spots to close. What this
file adds is *robustness*: several boundary mutants were killed by exactly one
covering test file (a fragile, single-point kill that a future edit to that one
file could silently reopen). These tests pin those exact behaviors directly and
independently, so the kills survive churn elsewhere.

Every test is deterministic, stdlib-only, offline, and drives the cmd_*
handlers in-process with argparse.Namespace on a tiny tmp_path project. Apply
paths run with no_verify=True (no pytest subprocess); --from-git and the heavy
collaborators are monkeypatched at their import points. No time/random/order
assertions.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import app.cli_ops as cli_ops
from app.cli_refactor import (
    _rewrite_resolve_pattern,
    _signature_resolve_plan,
    _teach_collect_pairs,
    cmd_rename,
    cmd_rewrite,
)


def _ns(**over) -> argparse.Namespace:
    return argparse.Namespace(**over)


def _app(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    return tmp_path / "app"


# --------------------------------------------------------------------------- #
# cli_refactor L25 — `param_of = getattr(args, "param", "") or ""`             #
#                                                                             #
# The `or` here selects the param-rename path only when a non-empty PARAM is  #
# given. The `or`->`and` mutant nulls a real param to "" (falling through to  #
# plain rename), so a truthy --param must demonstrably route to               #
# plan_param_rename. This is the single-killer-file boundary, pinned here.    #
# --------------------------------------------------------------------------- #
def test_rename_with_param_routes_to_param_rename(tmp_path, monkeypatch, capsys):
    _app(tmp_path)
    seen: dict = {}

    def _fake_param_plan(target, func, old, new):
        seen["param_func"] = func

        class _P:
            blockers = ["stopped here on purpose"]
        return _P()

    def _fake_plan_rename(target, old, new):  # plain-rename path must NOT run
        seen["plain"] = True

        class _P:
            blockers: list = []
        return _P()

    monkeypatch.setattr("app.execution.param_rename.plan_param_rename", _fake_param_plan)
    monkeypatch.setattr("app.execution.cross_file_rename.plan_rename", _fake_plan_rename)

    rc = cmd_rename(_ns(target=str(tmp_path), old="a", new="b", param="myfunc",
                        dry_run=False, no_verify=True, json=False))
    capsys.readouterr()
    assert rc == 1
    # Truthy param took the param-rename branch; the plain branch never ran.
    assert seen.get("param_func") == "myfunc"
    assert "plain" not in seen


def test_rename_empty_param_routes_to_plain_rename(tmp_path, monkeypatch, capsys):
    _app(tmp_path)
    seen: dict = {}

    def _fake_param_plan(target, func, old, new):  # must NOT run for empty param
        seen["param"] = True

        class _P:
            blockers: list = []
        return _P()

    def _fake_plan_rename(target, old, new):
        seen["plain_func"] = (old, new)

        class _P:
            blockers = ["stopped"]
        return _P()

    monkeypatch.setattr("app.execution.param_rename.plan_param_rename", _fake_param_plan)
    monkeypatch.setattr("app.execution.cross_file_rename.plan_rename", _fake_plan_rename)

    rc = cmd_rename(_ns(target=str(tmp_path), old="a", new="b", param="",
                        dry_run=False, no_verify=True, json=False))
    capsys.readouterr()
    assert rc == 1
    assert seen.get("plain_func") == ("a", "b")
    assert "param" not in seen


# --------------------------------------------------------------------------- #
# cli_refactor L340 — `if not pattern or replacement is None:`                 #
#                                                                             #
# Both arms of this guard block the rewrite. The `or`->`and` mutant would let  #
# an empty pattern through whenever a replacement is present (and vice versa). #
# These pin each arm independently so the disjunction can't collapse to a      #
# conjunction unnoticed. This is the second single-killer-file boundary.       #
# --------------------------------------------------------------------------- #
def _resolve_ns(tmp_path, pattern, replacement, rule=""):
    return _ns(target=str(tmp_path), pattern=pattern, replacement=replacement, rule=rule)


def test_resolve_pattern_blocks_when_pattern_empty_replacement_present(tmp_path, capsys):
    # not pattern is True, replacement is None is False -> OR must still block.
    pat, repl, rc = _rewrite_resolve_pattern(
        _resolve_ns(tmp_path, "", "something"), str(tmp_path))
    out = capsys.readouterr().out
    assert (pat, repl, rc) == (None, None, 1)
    assert "needs PATTERN and REPLACEMENT" in out


def test_resolve_pattern_blocks_when_pattern_present_replacement_none(tmp_path, capsys):
    # not pattern is False, replacement is None is True -> OR must still block.
    pat, repl, rc = _rewrite_resolve_pattern(
        _resolve_ns(tmp_path, "len($x)", None), str(tmp_path))
    out = capsys.readouterr().out
    assert (pat, repl, rc) == (None, None, 1)
    assert "needs PATTERN and REPLACEMENT" in out


def test_resolve_pattern_passes_when_both_present(tmp_path):
    # Both falsy-guards fail -> the pair flows through untouched (rc None).
    pat, repl, rc = _rewrite_resolve_pattern(
        _resolve_ns(tmp_path, "len($x)", "x"), str(tmp_path))
    assert (pat, repl, rc) == ("len($x)", "x", None)


def test_resolve_pattern_empty_replacement_string_is_allowed(tmp_path):
    # replacement="" is NOT None, so `replacement is None` (not `not replacement`)
    # lets an empty-string replacement through — pins the `is None` identity check.
    pat, repl, rc = _rewrite_resolve_pattern(
        _resolve_ns(tmp_path, "len($x)", ""), str(tmp_path))
    assert (pat, repl, rc) == ("len($x)", "", None)


# --------------------------------------------------------------------------- #
# cli_refactor _signature_resolve_plan — op dispatch ladder (== comparisons)   #
#                                                                             #
# Pins each op's branch so an `==`->`!=` flip on any rung is caught: each      #
# branch builds a distinct plan/label. Heavy planners are stubbed.            #
# --------------------------------------------------------------------------- #
def _stub_sig_planners(monkeypatch, seen):
    def _mk(tag):
        def _plan(*a, **k):
            seen["op"] = tag
            seen["args"] = a

            class _P:
                blockers = ["halt"]
            return _P()
        return _plan
    monkeypatch.setattr("app.execution.keywordify.plan_keywordify", _mk("keywordify"))
    monkeypatch.setattr("app.execution.param_reorder.plan_param_reorder", _mk("reorder"))
    monkeypatch.setattr("app.execution.param_add.plan_param_add", _mk("add"))
    monkeypatch.setattr("app.execution.param_drop.plan_param_drop", _mk("drop"))


def test_signature_resolve_keywordify_branch(tmp_path, monkeypatch):
    seen: dict = {}
    _stub_sig_planners(monkeypatch, seen)
    args = _ns(op="keywordify", function="f", param="", default="None")
    plan, label, rc = _signature_resolve_plan(args, str(tmp_path))
    assert seen["op"] == "keywordify" and rc is None
    assert "keywordify" not in label and "convert positional" in label


def test_signature_resolve_reorder_branch(tmp_path, monkeypatch):
    seen: dict = {}
    _stub_sig_planners(monkeypatch, seen)
    args = _ns(op="reorder", function="f", param="b, a, c", default="None")
    plan, label, rc = _signature_resolve_plan(args, str(tmp_path))
    assert seen["op"] == "reorder" and rc is None
    # The `or ""` split + comma parse feeds a cleaned order list through.
    assert seen["args"][2] == ["b", "a", "c"]
    assert "reorder" in label


def test_signature_resolve_add_branch_uses_default_fallback(tmp_path, monkeypatch):
    seen: dict = {}
    _stub_sig_planners(monkeypatch, seen)
    # default="" -> the `or "None"` fallback supplies "None"; pins that boolean.
    args = _ns(op="add", function="f", param="b", default="")
    plan, label, rc = _signature_resolve_plan(args, str(tmp_path))
    assert seen["op"] == "add" and rc is None
    assert seen["args"][3] == "None"
    assert "b=None" in label


def test_signature_resolve_drop_without_param_is_usage_error(tmp_path, capsys):
    args = _ns(op="drop", function="f", param="", default="None")
    plan, label, rc = _signature_resolve_plan(args, str(tmp_path))
    out = capsys.readouterr().out
    assert (plan, label, rc) == (None, None, 1)
    assert "needs a PARAM" in out


def test_signature_resolve_drop_with_param_builds_plan(tmp_path, monkeypatch):
    seen: dict = {}
    _stub_sig_planners(monkeypatch, seen)
    args = _ns(op="drop", function="f", param="b", default="None")
    plan, label, rc = _signature_resolve_plan(args, str(tmp_path))
    assert seen["op"] == "drop" and rc is None
    assert "drop `b`" in label


# --------------------------------------------------------------------------- #
# cli_refactor _teach_collect_pairs — --from-git commits + preview boundaries  #
# --------------------------------------------------------------------------- #
def test_teach_collect_pairs_commits_default_when_zero(tmp_path, monkeypatch):
    # commits=0 -> the `or 50` fallback supplies 50; pins that boolean+literal.
    seen: dict = {}

    def _mine(target, n):
        seen["n"] = n
        return []

    monkeypatch.setattr("app.engine.git_rule_miner.mine_git_pairs", _mine)
    pairs, rc = _teach_collect_pairs(
        _ns(from_git=True, commits=0, examples=[]), str(tmp_path))
    assert (pairs, rc) == (None, 0)
    assert seen["n"] == 50


def test_teach_collect_pairs_ellipsis_only_past_five(tmp_path, monkeypatch, capsys):
    # Exactly six mined pairs: the preview shows the first five and an ellipsis
    # appended to the 5th. Pins `len(pairs) > 5` and the `[:5]`/`pairs[4]` slice.
    mined = [(f"b{i}", f"a{i}") for i in range(6)]
    monkeypatch.setattr("app.engine.git_rule_miner.mine_git_pairs",
                        lambda target, n: mined)
    pairs, rc = _teach_collect_pairs(
        _ns(from_git=True, commits=5, examples=[]), str(tmp_path))
    out = capsys.readouterr().out
    assert rc is None and pairs == mined
    assert "Mined 6 single-line change(s)" in out
    # Five rows previewed; the 5th (index 4) carries the trailing ellipsis.
    assert "`b4` → `a4` …" in out
    assert "b5" not in out  # the sixth pair is not previewed


def test_teach_collect_pairs_no_ellipsis_at_five(tmp_path, monkeypatch, capsys):
    # Exactly five pairs: `len(pairs) > 5` is False, so no row gets an ellipsis.
    mined = [(f"b{i}", f"a{i}") for i in range(5)]
    monkeypatch.setattr("app.engine.git_rule_miner.mine_git_pairs",
                        lambda target, n: mined)
    pairs, rc = _teach_collect_pairs(
        _ns(from_git=True, commits=5, examples=[]), str(tmp_path))
    out = capsys.readouterr().out
    assert rc is None and pairs == mined
    assert "…" not in out


def test_teach_collect_pairs_odd_examples_block(tmp_path, capsys):
    # len(examples) % 2 != 0 -> usage error; pins the `% 2 != 0` arithmetic+cmp.
    pairs, rc = _teach_collect_pairs(
        _ns(from_git=False, examples=["one", "two", "three"]), str(tmp_path))
    out = capsys.readouterr().out
    assert (pairs, rc) == (None, 1)
    assert "even number" in out


def test_teach_collect_pairs_even_examples_zip(tmp_path):
    # Even count -> zipped into BEFORE/AFTER pairs via [::2]/[1::2]; pins slices.
    pairs, rc = _teach_collect_pairs(
        _ns(from_git=False, examples=["b1", "a1", "b2", "a2"]), str(tmp_path))
    assert rc is None
    assert pairs == [("b1", "a1"), ("b2", "a2")]


# --------------------------------------------------------------------------- #
# cli_refactor — `res.get("verified") is True` print branch (is / True flips)  #
#                                                                             #
# The verified-tests line prints ONLY when verified is exactly True. A         #
# non-True truthy value (e.g. "yes") must NOT print it; an explicit True must. #
# This pins the `is`/`True` tokens that several mutants flip across cmd_*.     #
# --------------------------------------------------------------------------- #
def test_rewrite_verified_line_requires_exact_true(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    monkeypatch.setattr(
        "app.execution.cross_file_rename.apply_rename",
        lambda root, plan, verify=True: {
            "applied": True, "edits": 1, "changed_files": ["app/m.py"],
            "verified": "yes", "warnings": [],
        },
    )
    rc = cmd_rewrite(_ns(target=str(tmp_path), pattern="len($x) == 0",
                         replacement="not $x", save="", rule="", rules=False,
                         all=False, dry_run=False, no_verify=False, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Rewrote" in out
    # A truthy-but-not-True verified value must NOT print the verified line.
    assert "change is verified" not in out


def test_rewrite_verified_line_prints_on_true(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path)
    (app / "m.py").write_text("def c(xs):\n    return len(xs) == 0\n")
    monkeypatch.setattr(
        "app.execution.cross_file_rename.apply_rename",
        lambda root, plan, verify=True: {
            "applied": True, "edits": 1, "changed_files": ["app/m.py"],
            "verified": True, "warnings": [],
        },
    )
    rc = cmd_rewrite(_ns(target=str(tmp_path), pattern="len($x) == 0",
                         replacement="not $x", save="", rule="", rules=False,
                         all=False, dry_run=False, no_verify=False, json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "change is verified" in out


# --------------------------------------------------------------------------- #
# cli_ops _consensus_status_icon — the == ladder + each return value           #
# --------------------------------------------------------------------------- #
def test_consensus_status_icon_each_verdict():
    assert cli_ops._consensus_status_icon("APPROVE") == "[OK]"
    assert cli_ops._consensus_status_icon("REJECT") == "[NO]"
    # Anything else falls through to the abstain/unknown marker.
    assert cli_ops._consensus_status_icon("ABSTAIN") == "[--]"
    assert cli_ops._consensus_status_icon("anything-else") == "[--]"


# --------------------------------------------------------------------------- #
# cli_ops _print_consensus_summary — counts (+=1), `in counts` membership,     #
# cached counter, and the per-result claim truncation [:80].                  #
# --------------------------------------------------------------------------- #
class _V:
    def __init__(self, name):
        self.name = name


class _Vote:
    def __init__(self, name):
        self.verdict = _V(name)
        self.agent_name = "ag"
        self.agent_role = "role"
        self.confidence = 0.5
        self.reasoning = "because"


class _Res:
    def __init__(self, claim, verdict, cached=False, votes=None):
        self.claim = claim
        self.final_verdict = _V(verdict)
        self.confidence = 0.9
        self.votes = votes or []
        self.metadata = {"cached": cached}


def test_consensus_summary_counts_and_cached(capsys):
    results = [
        _Res("c1", "APPROVE", cached=True),
        _Res("c2", "APPROVE"),
        _Res("c3", "REJECT"),
        _Res("c4", "ABSTAIN"),
        _Res("c5", "WEIRD"),  # not in counts -> must be ignored by membership guard
    ]

    class _Mem:
        def stats(self):
            return {"total_entries": 11}

    class _Ev:
        memory = _Mem()

    args = _ns(strategy="majority", use_memory=True)
    cli_ops._print_consensus_summary(args, _Ev(), results, 0.123)
    out = capsys.readouterr().out
    # Two approvals counted (not three — WEIRD is excluded by `in counts`).
    assert "Total: 5 | Approved: 2 | Rejected: 1 | Abstained: 1" in out
    # Exactly one cached result tallied by the += counter.
    assert "Cached: 1 | Memory entries: 11" in out


def test_consensus_summary_no_memory_line_without_flag(capsys):
    results = [_Res("c1", "APPROVE")]

    class _Ev:
        memory = None

    args = _ns(strategy="weighted", use_memory=False)
    cli_ops._print_consensus_summary(args, _Ev(), results, 0.0)
    out = capsys.readouterr().out
    assert "=== CONSENSUS RESULTS (weighted) ===" in out
    assert "Memory entries" not in out
    assert "Cached" not in out


def test_consensus_result_truncates_claim_at_80(capsys):
    long_claim = "x" * 200
    res = _Res(long_claim, "APPROVE", votes=[_Vote("APPROVE"), _Vote("REJECT")])
    cli_ops._print_consensus_result(res)
    out = capsys.readouterr().out
    # The claim is sliced to 80 chars then "..." is appended.
    assert ("x" * 80 + "...") in out
    assert ("x" * 81 + "...") not in out
    # The matching-verdict vote gets "+", the dissenting one gets "-".
    assert "+ ag (role): APPROVE" in out
    assert "- ag (role): REJECT" in out


def test_consensus_result_cached_mark_only_when_cached(capsys):
    res_cached = _Res("c", "APPROVE", cached=True)
    cli_ops._print_consensus_result(res_cached)
    assert "[CACHED]" in capsys.readouterr().out

    res_plain = _Res("c", "APPROVE", cached=False)
    cli_ops._print_consensus_result(res_plain)
    assert "[CACHED]" not in capsys.readouterr().out
