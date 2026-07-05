from __future__ import annotations


from app.engine.fractal_5whys import Fractal5WhysEngine, FractalNode


class TestFractal5WhysEngine:
    def test_analyze_single_finding(self):
        engine = Fractal5WhysEngine(max_depth=5)
        finding = {"issue": "eval() usage", "file": "app/auth.py", "severity": "critical"}
        tree = engine.analyze(finding)

        assert tree.level == 1
        assert "eval" in tree.question.lower()
        assert len(tree.children) >= 1

    def test_reaches_max_depth(self):
        engine = Fractal5WhysEngine(max_depth=3)
        finding = {"issue": "eval() usage", "file": "auth.py", "severity": "critical"}
        tree = engine.analyze(finding)

        # Tree should have level 1 -> 2 -> 3
        assert tree.level == 1
        assert any(c.level == 2 for c in tree.children)

        # Level 3 nodes should not have children (max_depth=3)
        level_3_nodes = []
        def collect(node):
            if node.level == 3:
                level_3_nodes.append(node)
            for c in node.children:
                collect(c)
        collect(tree)
        assert len(level_3_nodes) >= 1
        for n in level_3_nodes:
            assert not n.children

    def test_analyze_batch(self):
        engine = Fractal5WhysEngine(max_depth=3)
        findings = [
            {"issue": "eval() usage", "file": "a.py"},
            {"issue": "missing_docstring", "file": "b.py"},
        ]
        trees = engine.analyze_batch(findings)
        assert len(trees) == 2
        assert all(isinstance(t, FractalNode) for t in trees)

    def test_summarize_tree(self):
        engine = Fractal5WhysEngine(max_depth=3)
        finding = {"issue": "eval() usage", "file": "auth.py"}
        tree = engine.analyze(finding)
        summary = engine.summarize_tree(tree)
        assert "Level 1" in summary
        assert "Level 2" in summary

    def test_min_confidence_filter(self):
        engine = Fractal5WhysEngine(max_depth=5, min_confidence=0.9)
        finding = {"issue": "eval() usage", "file": "auth.py"}
        tree = engine.analyze(finding)
        # Some low-confidence nodes may be filtered
        assert tree.level == 1

    def test_to_dict(self):
        node = FractalNode(level=1, question="Q?", answer="A.", confidence=0.9)
        child = FractalNode(level=2, question="Q2?", answer="A2.", confidence=0.8)
        node.children.append(child)
        d = node.to_dict()
        assert d["level"] == 1
        assert len(d["children"]) == 1
        assert d["children"][0]["level"] == 2

    def test_counter_evidence_enabled(self):
        engine = Fractal5WhysEngine(max_depth=3, enable_counter_evidence=True)
        finding = {"issue": "eval() usage", "file": "auth.py"}
        tree = engine.analyze(finding)
        assert len(tree.counter_evidence) > 0
        assert tree.rebuttal != ""

    def test_counter_evidence_disabled(self):
        engine = Fractal5WhysEngine(max_depth=3, enable_counter_evidence=False)
        finding = {"issue": "eval() usage", "file": "auth.py"}
        tree = engine.analyze(finding)
        assert not tree.counter_evidence
        assert tree.rebuttal == ""

    def test_meta_analysis_recommends_patch(self):
        engine = Fractal5WhysEngine(max_depth=5)
        finding = {"issue": "eval() usage", "file": "auth.py", "severity": "critical"}
        tree = engine.analyze(finding)
        meta = engine.meta_analyze(tree)
        assert meta.recommended_action == "patch"
        assert meta.aggregate_confidence > 0.0
        assert meta.depth_reached >= 1

    def test_meta_analysis_recommends_ignore(self):
        engine = Fractal5WhysEngine(max_depth=5)
        finding = {"issue": "unknown thing", "file": "x.py", "severity": "info"}
        tree = engine.analyze(finding)
        meta = engine.meta_analyze(tree)
        assert meta.recommended_action in ("ignore", "escalate", "review")

    def test_docstring_and_test_findings_reach_patch_on_own_terms(self):
        # Non-security, behavior-preserving findings (severity="low") reach "patch"
        # via the dedicated non-security condition — the security severity ladder
        # structurally never fires for them.
        engine = Fractal5WhysEngine(max_depth=5)
        for issue in ("missing_docstring", "missing_test"):
            finding = {"issue": issue, "file": "x.py", "line": 1, "severity": "low"}
            meta = engine.meta_analyze(engine.analyze(finding))
            assert meta.recommended_action == "patch", issue

    def test_bare_except_stays_escalate_not_patch(self):
        # bare_except changes runtime behavior — deliberately NOT auto-patched here,
        # even though its aggregate confidence would clear the doc/test bar.
        engine = Fractal5WhysEngine(max_depth=5)
        finding = {"issue": "bare except", "file": "x.py", "line": 1, "severity": "medium"}
        meta = engine.meta_analyze(engine.analyze(finding))
        assert meta.recommended_action != "patch"

    def test_bare_except_never_patches_even_if_tagged_critical(self):
        # The exemption is STRUCTURAL (a deny-list), not a side effect of
        # bare_except merely being severity="medium" today.
        engine = Fractal5WhysEngine(max_depth=5)
        finding = {"issue": "bare except", "file": "x.py", "line": 1, "severity": "critical"}
        meta = engine.meta_analyze(engine.analyze(finding))
        assert meta.recommended_action != "patch"

    def test_docstring_finding_with_no_file_never_patches(self):
        # A finding with no concrete file can't be patched (nothing to read).
        engine = Fractal5WhysEngine(max_depth=5)
        finding = {"issue": "missing_docstring", "file": "", "line": 1, "severity": "low"}
        meta = engine.meta_analyze(engine.analyze(finding))
        assert meta.recommended_action != "patch"

    def test_counter_evidence_generator(self):
        from app.engine.fractal_5whys import CounterEvidenceGenerator
        gen = CounterEvidenceGenerator()
        node = FractalNode(level=2, question="Why?", answer="Developer convenience", confidence=0.9)
        finding = {"issue": "eval() usage"}
        counter, rebuttal = gen.generate(node, finding)
        assert len(counter) > 0
        assert rebuttal != ""
