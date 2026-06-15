"""Second edge-coverage pass for app.cli_ops cmd_* handlers.

Targets the branches the first edge suite left uncovered: the security-agent
and unknown-agent paths of cmd_agents, the whole cmd_consensus reporting
ladder (approve/reject/abstain, cached, --use-memory, --json, the empty-claims
guard), cmd_self_audit (markdown + json), and the dry-run branches of
cmd_fix_docstrings / cmd_fix_coverage.

Deterministic, stdlib-only, no network. Every heavy collaborator (skill
agents, the claim evaluator, the self-audit agent) is monkeypatched at its
import point so the tests stay fast and hermetic.
"""

from __future__ import annotations

import argparse
import json
import types

import app.cli_ops as cli_ops


# --- cmd_agents: security branch + unknown agent type -------------------

def test_cmd_agents_security_prints_json(monkeypatch, capsys):
    class FakeSecurityAgent:
        def run(self, *, project_root):
            return {"vulnerabilities": 0, "scanned": 4}

    monkeypatch.setattr("app.agents.skills.SecurityAgent", FakeSecurityAgent)
    args = argparse.Namespace(target="", agent_type="security")
    assert cli_ops.cmd_agents(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"vulnerabilities": 0, "scanned": 4}


def test_cmd_agents_unknown_type_returns_1(capsys):
    args = argparse.Namespace(target="", agent_type="bogus")
    assert cli_ops.cmd_agents(args) == 1
    assert "Unknown agent type: bogus" in capsys.readouterr().out


def test_cmd_agents_docstring_no_patched_files_skips_line(monkeypatch, capsys):
    class FakeDocstringAgent:
        def run(self, *, project_root, patch):
            return {"gaps_found": 0, "patched_files": []}

    monkeypatch.setattr("app.agents.skills.DocstringAgent", FakeDocstringAgent)
    args = argparse.Namespace(target="", agent_type="docstring", patch=False)
    assert cli_ops.cmd_agents(args) == 0
    out = capsys.readouterr().out
    assert "Found 0 missing docstrings" in out
    assert "Patched" not in out


def test_cmd_agents_dependency_clean_skips_circular_and_orphan_lines(monkeypatch, capsys):
    class FakeDependencyAgent:
        def run(self, *, project_root):
            return {
                "total_modules": 2,
                "total_edges": 1,
                "circular_imports": [],
                "orphaned_modules": [],
            }

    monkeypatch.setattr("app.agents.skills.DependencyAgent", FakeDependencyAgent)
    args = argparse.Namespace(target="", agent_type="dependency")
    assert cli_ops.cmd_agents(args) == 0
    out = capsys.readouterr().out
    assert "Modules: 2, Edges: 1" in out
    assert "Circular imports" not in out
    assert "Orphaned modules" not in out


# --- cmd_consensus: full reporting ladder -------------------------------

class _FakeVerdict:
    def __init__(self, name: str):
        self.name = name


class _FakeVote:
    def __init__(self, verdict, agent_name, agent_role, confidence, reasoning):
        self.verdict = _FakeVerdict(verdict)
        self.agent_name = agent_name
        self.agent_role = agent_role
        self.confidence = confidence
        self.reasoning = reasoning


class _FakeResult:
    def __init__(self, claim, verdict, confidence, votes, cached=False):
        self.claim = claim
        self.final_verdict = _FakeVerdict(verdict)
        self.confidence = confidence
        self.votes = votes
        self.metadata = {"cached": cached}

    def to_dict(self):
        return {"claim": self.claim, "verdict": self.final_verdict.name}


class _FakeMemory:
    def stats(self):
        return {"total_entries": 7}


def _install_evaluator(monkeypatch, results, *, capture=None):
    class FakeEvaluator:
        def __init__(self, *, consensus_strategy, quorum, memory_dir):
            if capture is not None:
                capture.update(consensus_strategy=consensus_strategy,
                               quorum=quorum, memory_dir=memory_dir)
            self.memory = _FakeMemory()

        def evaluate_batch(self, claims):
            if capture is not None:
                capture["claims"] = list(claims)
            return results

    monkeypatch.setattr("app.agents.evaluator.ClaimEvaluator", FakeEvaluator)


def test_cmd_consensus_empty_claims_guard(monkeypatch, capsys):
    captured: dict = {}
    _install_evaluator(monkeypatch, [], capture=captured)
    args = argparse.Namespace(claims="", strategy="majority", quorum=2,
                              json=False, use_memory=False)
    assert cli_ops.cmd_consensus(args) == 1
    assert "No claims provided" in capsys.readouterr().out
    # The empty-claims guard fires before evaluate_batch runs.
    assert "claims" not in captured


def test_cmd_consensus_reports_each_verdict_class(monkeypatch, capsys):
    votes = [
        _FakeVote("APPROVE", "alpha", "engineer", 0.9, "looks right"),
        _FakeVote("REJECT", "beta", "skeptic", 0.4, "doubtful"),
    ]
    results = [
        _FakeResult("c1 is fine", "APPROVE", 0.85, votes),
        _FakeResult("c2 is wrong", "REJECT", 0.7, votes),
        _FakeResult("c3 unclear", "ABSTAIN", 0.5, votes),
    ]
    _install_evaluator(monkeypatch, results)
    args = argparse.Namespace(claims="c1 is fine;c2 is wrong;c3 unclear",
                              strategy="majority", quorum=2, json=False, use_memory=False)
    assert cli_ops.cmd_consensus(args) == 0
    out = capsys.readouterr().out
    assert "=== CONSENSUS RESULTS (majority) ===" in out
    assert "Total: 3 | Approved: 1 | Rejected: 1 | Abstained: 1" in out
    assert "[OK]" in out and "[NO]" in out and "[--]" in out
    # The matching/dissenting vote markers both appear.
    assert "+ alpha (engineer): APPROVE" in out
    # Memory line is suppressed without --use-memory.
    assert "Memory entries" not in out


def test_cmd_consensus_use_memory_reports_cache_stats(monkeypatch, capsys):
    votes = [_FakeVote("APPROVE", "a", "r", 0.9, "ok")]
    results = [
        _FakeResult("claim a", "APPROVE", 0.9, votes, cached=True),
        _FakeResult("claim b", "APPROVE", 0.8, votes, cached=False),
    ]
    captured: dict = {}
    _install_evaluator(monkeypatch, results, capture=captured)
    args = argparse.Namespace(claims="claim a;claim b", strategy="weighted",
                              quorum=3, json=False, use_memory=True)
    assert cli_ops.cmd_consensus(args) == 0
    out = capsys.readouterr().out
    assert "Cached: 1 | Memory entries: 7" in out
    assert "[CACHED]" in out
    # --use-memory threads a real memory_dir + the chosen strategy/quorum.
    assert captured["memory_dir"] is not None
    assert captured["consensus_strategy"] == "weighted"
    assert captured["quorum"] == 3


def test_cmd_consensus_json_emits_result_dicts(monkeypatch, capsys):
    votes = [_FakeVote("APPROVE", "a", "r", 0.9, "ok")]
    results = [_FakeResult("only claim", "APPROVE", 0.9, votes)]
    _install_evaluator(monkeypatch, results)
    args = argparse.Namespace(claims="only claim", strategy="majority",
                              quorum=2, json=True, use_memory=False)
    assert cli_ops.cmd_consensus(args) == 0
    out = capsys.readouterr().out
    # The JSON block is the last thing printed (its array opens on its own line).
    payload = json.loads(out[out.rindex("\n[\n"):])
    assert payload == [{"claim": "only claim", "verdict": "APPROVE"}]


# --- cmd_self_audit: markdown + json formats ----------------------------

def _install_self_audit(monkeypatch, result):
    class FakeSelfAuditAgent:
        def run(self, *, project_root):
            return result

    fake_mod = types.ModuleType("app.agents.skills.self_audit_agent")
    fake_mod.SelfAuditAgent = FakeSelfAuditAgent
    monkeypatch.setitem(__import__("sys").modules,
                        "app.agents.skills.self_audit_agent", fake_mod)


def test_cmd_self_audit_markdown(monkeypatch, capsys, tmp_path):
    _install_self_audit(monkeypatch, {
        "findings": [{"risk": "x"}, {"risk": "y"}],
        "missing_docstrings_count": 3,
        "long_functions_count": 1,
        "todos_count": 4,
        "coverage_gap": {
            "tested_modules": ["app.a", "app.b"],
            "untested_modules": ["app.c"],
        },
    })
    args = argparse.Namespace(target=str(tmp_path), format="markdown")
    assert cli_ops.cmd_self_audit(args) == 0
    out = capsys.readouterr().out
    assert "# Apex Self-Audit Report" in out
    assert "Risks found: 2" in out
    assert "Missing docstrings: 3" in out
    assert "Long functions (>50 lines): 1" in out
    assert "TODOs: 4" in out
    assert "Tested modules: app.a, app.b" in out
    assert "Untested modules: app.c" in out


def test_cmd_self_audit_markdown_defaults_for_missing_keys(monkeypatch, capsys, tmp_path):
    # A sparse result exercises the .get(...) fallbacks for every field.
    _install_self_audit(monkeypatch, {})
    args = argparse.Namespace(target=str(tmp_path), format="markdown")
    assert cli_ops.cmd_self_audit(args) == 0
    out = capsys.readouterr().out
    assert "Risks found: 0" in out
    assert "Missing docstrings: 0" in out
    assert "Tested modules: \n" in out


def test_cmd_self_audit_json(monkeypatch, capsys, tmp_path):
    _install_self_audit(monkeypatch, {"findings": [], "missing_docstrings_count": 0})
    args = argparse.Namespace(target=str(tmp_path), format="json")
    assert cli_ops.cmd_self_audit(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"findings": [], "missing_docstrings_count": 0}


def test_cmd_self_audit_empty_target_uses_project_root(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli_ops, "_get_project_root", lambda: tmp_path)
    seen: dict = {}

    class FakeSelfAuditAgent:
        def run(self, *, project_root):
            seen["root"] = project_root
            return {}

    fake_mod = types.ModuleType("app.agents.skills.self_audit_agent")
    fake_mod.SelfAuditAgent = FakeSelfAuditAgent
    monkeypatch.setitem(__import__("sys").modules,
                        "app.agents.skills.self_audit_agent", fake_mod)

    args = argparse.Namespace(target="", format="json")
    assert cli_ops.cmd_self_audit(args) == 0
    assert seen["root"] == str(tmp_path)


# --- cmd_fix_docstrings / cmd_fix_coverage: dry-run branches ------------

def test_cmd_fix_docstrings_dry_run_lists_gaps(monkeypatch, capsys):
    class FakeDocstringAgent:
        def run(self, *, project_root, patch):
            assert patch is False  # dry-run must not patch
            return {
                "total_symbols": 10,
                "gaps_found": 2,
                "patched_files": [],
                "gaps": [
                    {"file": "a.py", "line": 3, "symbol_type": "function", "name": "f"},
                    {"file": "b.py", "line": 9, "symbol_type": "class", "name": "C"},
                ],
            }

    monkeypatch.setattr("app.agents.skills.DocstringAgent", FakeDocstringAgent)
    args = argparse.Namespace(target="", dry_run=True)
    assert cli_ops.cmd_fix_docstrings(args) == 0
    out = capsys.readouterr().out
    assert "Symbols scanned: 10" in out
    assert "(Dry run — no files modified)" in out
    assert "a.py:3 function 'f'" in out
    assert "b.py:9 class 'C'" in out
    assert "Files patched" not in out


def test_cmd_fix_coverage_dry_run_notes_generate_flag(monkeypatch, capsys):
    class FakeTestStubAgent:
        def run(self, *, project_root, generate):
            assert generate is False
            return {
                "total_functions": 6,
                "tested_functions": 3,
                "coverage_ratio": 0.5,
                "gaps_found": 3,
                "stubs_generated": [],
            }

    monkeypatch.setattr("app.agents.skills.TestStubAgent", FakeTestStubAgent)
    args = argparse.Namespace(target="", generate=False)
    assert cli_ops.cmd_fix_coverage(args) == 0
    out = capsys.readouterr().out
    assert "Functions scanned: 6" in out
    assert "Coverage: 50.0%" in out
    assert "(Dry run — use --generate to create test files)" in out
    assert "Stubs generated" not in out
