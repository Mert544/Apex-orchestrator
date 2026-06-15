from __future__ import annotations

from pathlib import Path

from app.reporting.composer import ReportComposer


class TestReportComposer:
    def test_to_markdown(self, tmp_path: Path):
        results = [
            {"agent": "security", "findings": [
                {"issue": "eval() usage", "severity": "critical", "file": "app/auth.py", "suggestion": "Use ast.literal_eval"},
            ]},
        ]
        composer = ReportComposer(results)
        md = composer.to_markdown(tmp_path / "report.md")
        assert "eval() usage" in md
        assert "app/auth.py" in md
        assert (tmp_path / "report.md").exists()

    def test_timestamp_is_canonical_utc_minute_format(self):
        # The report stamp must match Apex's canonical "YYYY-MM-DD HH:MM UTC"
        # format (UTC, minute granularity) — not local second-granularity time.
        import re

        composer = ReportComposer([])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", composer.timestamp)
        assert "UTC" in composer.to_markdown()

    def test_to_html(self, tmp_path: Path):
        results = [
            {"agent": "security", "findings": [
                {"issue": "eval() usage", "severity": "critical", "file": "app/auth.py"},
            ]},
        ]
        composer = ReportComposer(results)
        html = composer.to_html(tmp_path / "report.html")
        assert "eval() usage" in html
        assert "#dc2626" in html  # critical color
        assert (tmp_path / "report.html").exists()

    def test_to_sarif(self, tmp_path: Path):
        results = [
            {"agent": "security", "findings": [
                {"issue": "eval() usage", "severity": "critical", "file": "app/auth.py", "suggestion": "fix it"},
            ]},
        ]
        composer = ReportComposer(results)
        sarif = composer.to_sarif(tmp_path / "report.sarif")
        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"][0]["results"]) == 1
        assert (tmp_path / "report.sarif").exists()

    def test_empty_results(self):
        composer = ReportComposer([])
        md = composer.to_markdown()
        assert "No findings" not in md  # Just empty sections
        html = composer.to_html()
        assert "No findings" in html

    def test_fractal_tree_markdown(self, tmp_path: Path):
        results = [
            {"agent": "fractal-security", "findings": [
                {"issue": "eval() usage", "severity": "critical", "file": "app/auth.py"},
            ], "fractal_trees": [
                {"level": 1, "question": "What is the risk?", "answer": "eval() allows RCE", "confidence": 1.0, "evidence": ["Detected in auth.py"], "children": [
                    {"level": 2, "question": "Why does eval() exist?", "answer": "Developer convenience", "confidence": 0.9, "evidence": [], "children": []},
                ]},
            ]},
        ]
        composer = ReportComposer(results)
        md = composer.to_markdown(tmp_path / "report.md")
        assert "🔬 Fractal Deep Analysis" in md
        assert "L1" in md
        assert "L2" in md
        assert "confidence: 100%" in md
        assert "confidence: 90%" in md

    def test_fractal_tree_html(self, tmp_path: Path):
        results = [
            {"agent": "fractal-security", "findings": [], "fractal_trees": [
                {"level": 1, "question": "What?", "answer": "RCE", "confidence": 1.0, "evidence": ["e1"], "children": []},
            ]},
        ]
        composer = ReportComposer(results)
        html = composer.to_html(tmp_path / "report.html")
        assert "🔬 Fractal Deep Analysis" in html
        assert "L1" in html
        assert "confidence: 100%" in html
        assert "📎 e1" in html

    def test_to_mermaid(self, tmp_path: Path):
        results = [
            {"agent": "fractal-security", "findings": [], "fractal_trees": [
                {"level": 1, "question": "Q?", "answer": "A1", "confidence": 1.0, "evidence": [], "children": [
                    {"level": 2, "question": "Q2?", "answer": "A2", "confidence": 0.8, "evidence": [], "children": []},
                ]},
            ]},
        ]
        composer = ReportComposer(results)
        mermaid = composer.to_mermaid(tmp_path / "report.mmd")
        assert "flowchart TD" in mermaid
        assert "subgraph Finding_0" in mermaid
        assert "A1" in mermaid
        assert "A2" in mermaid
        assert (tmp_path / "report.mmd").exists()
