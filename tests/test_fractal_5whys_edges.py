from __future__ import annotations

import pytest

from app.engine.fractal_5whys import (
    CounterEvidenceGenerator,
    Fractal5WhysEngine,
    FractalNode,
)


class TestMetaAnalyzeActionBranches:
    """Cover every action branch in Fractal5WhysEngine.meta_analyze."""

    def test_high_severity_moderate_confidence_recommends_review(self):
        # severity in ("critical", "high") with aggregate > 0.5 but not the
        # critical/>0.7 patch arm -> "review".
        engine = Fractal5WhysEngine(max_depth=5)
        finding = {"issue": "eval() usage", "file": "a.py", "severity": "high"}
        tree = engine.analyze(finding)
        meta = engine.meta_analyze(tree)
        assert meta.recommended_action == "review"
        assert 0.5 < meta.aggregate_confidence <= 0.7 or meta.aggregate_confidence > 0.5

    def test_low_aggregate_confidence_recommends_ignore(self):
        # aggregate < 0.3 -> "ignore". A single low-confidence root node with a
        # shallow tree drives the aggregate below the threshold deterministically.
        engine = Fractal5WhysEngine(max_depth=5)
        node = FractalNode(level=1, question="q", answer="a", confidence=0.2)
        node.metadata = {"finding": {"issue": "x", "severity": "info"}}
        meta = engine.meta_analyze(node)
        assert meta.recommended_action == "ignore"
        assert meta.aggregate_confidence < 0.3

    def test_mixed_signals_recommend_escalate(self):
        # Not patch, not review, aggregate >= 0.3 -> "escalate".
        engine = Fractal5WhysEngine(max_depth=5)
        finding = {"issue": "unknown thing", "file": "x.py", "severity": "info"}
        tree = engine.analyze(finding)
        meta = engine.meta_analyze(tree)
        assert meta.recommended_action == "escalate"
        assert meta.aggregate_confidence >= 0.3

    def test_critical_high_confidence_recommends_patch(self):
        engine = Fractal5WhysEngine(max_depth=5)
        finding = {"issue": "eval() usage", "file": "a.py", "severity": "critical"}
        tree = engine.analyze(finding)
        meta = engine.meta_analyze(tree)
        assert meta.recommended_action == "patch"
        assert meta.aggregate_confidence > 0.7


class TestMetaAnalyzeEdgeCases:
    def test_depth_penalty_applied_to_shallow_tree(self):
        # A tree that does not reach max_depth gets the 0.8 penalty: the
        # aggregate is strictly below the average node confidence.
        engine = Fractal5WhysEngine(max_depth=5)
        node = FractalNode(level=1, question="q", answer="a", confidence=0.9)
        node.metadata = {"finding": {"issue": "x", "severity": "info"}}
        meta = engine.meta_analyze(node)
        assert meta.depth_reached == 1
        assert meta.aggregate_confidence == pytest.approx(0.9 * 0.8)

    def test_full_depth_tree_has_no_penalty(self):
        # When max_level >= max_depth the penalty is 1.0.
        engine = Fractal5WhysEngine(max_depth=1)
        node = FractalNode(level=1, question="q", answer="a", confidence=0.9)
        node.metadata = {"finding": {"issue": "x", "severity": "info"}}
        meta = engine.meta_analyze(node)
        assert meta.depth_reached == 1
        assert meta.aggregate_confidence == pytest.approx(0.9)

    def test_meta_analyze_counts_all_nodes(self):
        engine = Fractal5WhysEngine(max_depth=5)
        finding = {"issue": "eval() usage", "file": "a.py", "severity": "critical"}
        tree = engine.analyze(finding)
        meta = engine.meta_analyze(tree)

        # Independently count the nodes to confirm node_count is exact.
        count = 0

        def walk(n: FractalNode) -> None:
            nonlocal count
            count += 1
            for c in n.children:
                walk(c)

        walk(tree)
        assert meta.node_count == count

    def test_meta_analyze_to_dict_roundtrip(self):
        engine = Fractal5WhysEngine(max_depth=5)
        finding = {"issue": "eval() usage", "file": "a.py", "severity": "critical"}
        meta = engine.meta_analyze(engine.analyze(finding))
        d = meta.to_dict()
        assert d["recommended_action"] == meta.recommended_action
        assert d["node_count"] == meta.node_count
        assert d["depth_reached"] == meta.depth_reached
        assert isinstance(d["key_insights"], list)


class TestAnalyzeDegenerateFindings:
    def test_empty_finding_uses_defaults(self):
        # No issue/file/severity keys -> default question/answer text, no crash.
        engine = Fractal5WhysEngine(max_depth=3)
        tree = engine.analyze({})
        assert tree.level == 1
        assert "Unknown issue" in tree.question
        assert "INFO" in tree.answer  # default severity "info" upper-cased
        assert "unknown" in tree.answer

    def test_zero_max_depth_yields_only_root(self):
        # max_depth=0 means parent.level(1) >= max_depth(0): no children spawned.
        engine = Fractal5WhysEngine(max_depth=0)
        tree = engine.analyze({"issue": "eval() usage", "file": "a.py"})
        assert tree.level == 1
        assert tree.children == []

    def test_min_confidence_above_all_nodes_prunes_children(self):
        # With min_confidence higher than any generated child confidence, the
        # first child fails the gate and the tree stays a single root.
        engine = Fractal5WhysEngine(max_depth=5, min_confidence=0.99)
        tree = engine.analyze({"issue": "eval() usage", "file": "a.py"})
        assert tree.children == []

    def test_os_system_why_exists_branch(self):
        engine = Fractal5WhysEngine(max_depth=2)
        tree = engine.analyze({"issue": "os.system() call", "file": "a.py"})
        assert tree.children
        assert "os.system" in tree.children[0].question

    def test_missing_docstring_why_exists_branch(self):
        engine = Fractal5WhysEngine(max_depth=2)
        tree = engine.analyze({"issue": "missing_docstring", "file": "a.py"})
        assert tree.children
        assert "docstring" in tree.children[0].question.lower()

    def test_generic_issue_why_introduced_branch(self):
        # A non-eval, non-docstring issue routes through the generic
        # _why_introduced arm at level 3.
        engine = Fractal5WhysEngine(max_depth=3)
        tree = engine.analyze({"issue": "weak_crypto", "file": "a.py"})
        level3 = []

        def collect(n: FractalNode) -> None:
            if n.level == 3:
                level3.append(n)
            for c in n.children:
                collect(c)

        collect(tree)
        assert level3
        assert any("introduced" in n.question.lower() for n in level3)


class TestCounterEvidenceGeneratorBranches:
    def test_os_system_convenience_branch(self):
        gen = CounterEvidenceGenerator()
        node = FractalNode(level=2, question="Why?", answer="for convenience",
                           confidence=0.9)
        counter, rebuttal = gen.generate(node, {"issue": "os.system() call"})
        assert any("subprocess" in c for c in counter)
        assert "PATH manipulation" in rebuttal

    def test_missing_docstring_branch(self):
        gen = CounterEvidenceGenerator()
        node = FractalNode(level=2, question="Why?", answer="no requirement",
                           confidence=0.9)
        counter, rebuttal = gen.generate(node, {"issue": "missing_docstring"})
        assert any("self-explanatory" in c for c in counter)
        assert "autocomplete" in rebuttal

    def test_missing_test_branch(self):
        gen = CounterEvidenceGenerator()
        node = FractalNode(level=2, question="Why?", answer="not covered",
                           confidence=0.9)
        counter, rebuttal = gen.generate(node, {"issue": "missing_test"})
        assert any("integration tests" in c for c in counter)
        assert "regressions" in rebuttal

    def test_eval_without_convenience_falls_through_to_default(self):
        # "eval" in issue but answer lacks "convenience" -> the default arm.
        gen = CounterEvidenceGenerator()
        node = FractalNode(level=2, question="Why?", answer="dynamic dispatch",
                           confidence=0.9)
        counter, rebuttal = gen.generate(node, {"issue": "eval() usage"})
        assert any("pattern matching" in c for c in counter)
        assert "false positive" in counter[1]

    def test_unmapped_issue_default_branch(self):
        gen = CounterEvidenceGenerator()
        node = FractalNode(level=1, question="Why?", answer="whatever",
                           confidence=0.5)
        counter, rebuttal = gen.generate(node, {"issue": "sql_injection"})
        assert len(counter) == 2
        assert "manual review" in rebuttal


class TestSummarizeTree:
    def test_summary_includes_counter_evidence_and_rebuttal(self):
        engine = Fractal5WhysEngine(max_depth=2, enable_counter_evidence=True)
        tree = engine.analyze({"issue": "eval() usage", "file": "a.py",
                               "severity": "critical"})
        summary = engine.summarize_tree(tree)
        assert "Counter-evidence" in summary
        assert "Rebuttal" in summary

    def test_summary_without_counter_evidence_omits_it(self):
        engine = Fractal5WhysEngine(max_depth=2, enable_counter_evidence=False)
        tree = engine.analyze({"issue": "eval() usage", "file": "a.py"})
        summary = engine.summarize_tree(tree)
        assert "Counter-evidence" not in summary
        assert "Level 1" in summary


class TestFractalNodeToDict:
    def test_to_dict_preserves_all_fields(self):
        node = FractalNode(
            level=2,
            question="Q?",
            answer="A.",
            confidence=0.7,
            evidence=["e1"],
            counter_evidence=["c1"],
            rebuttal="r",
            metadata={"k": "v"},
        )
        d = node.to_dict()
        assert d["evidence"] == ["e1"]
        assert d["counter_evidence"] == ["c1"]
        assert d["rebuttal"] == "r"
        assert d["metadata"] == {"k": "v"}
        assert d["children"] == []
