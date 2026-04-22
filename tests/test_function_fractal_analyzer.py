from __future__ import annotations

from pathlib import Path

from app.tools.function_fractal_analyzer import FunctionFractalAnalyzer


def test_analyzer_detects_risks_in_functions(tmp_path: Path):
    source = (
        "def process(data):\n"
        "    eval(data)\n"
        "    return data\n"
        "\n"
        "def safe_add(a, b):\n"
        "    return a + b\n"
    )
    _write(tmp_path / "app" / "utils.py", source)
    analyzer = FunctionFractalAnalyzer()
    result = analyzer.analyze_file(tmp_path / "app" / "utils.py")

    assert len(result) == 2
    process_fn = next(r for r in result if r["name"] == "process")
    assert "Uses eval()" in str(process_fn["risks"])
    safe_fn = next(r for r in result if r["name"] == "safe_add")
    assert safe_fn["risk_score"] < process_fn["risk_score"]


def test_analyzer_detects_missing_docstrings(tmp_path: Path):
    source = (
        "def helper(x):\n"
        "    return x * 2\n"
    )
    _write(tmp_path / "app" / "helper.py", source)
    analyzer = FunctionFractalAnalyzer()
    result = analyzer.analyze_file(tmp_path / "app" / "helper.py")

    assert result[0]["has_docstring"] is False
    assert "missing_docstring" in result[0]["risks"]


def test_analyzer_class_methods(tmp_path: Path):
    source = (
        "class Service:\n"
        "    def run(self, cmd):\n"
        "        import os\n"
        "        os.system(cmd)\n"
        "    def safe(self):\n"
        '        """Safe method."""\n'
        "        pass\n"
    )
    _write(tmp_path / "app" / "service.py", source)
    analyzer = FunctionFractalAnalyzer()
    result = analyzer.analyze_file(tmp_path / "app" / "service.py")

    run_method = next(r for r in result if r["name"] == "Service.run")
    assert "Uses os.system()" in str(run_method["risks"])
    safe_method = next(r for r in result if r["name"] == "Service.safe")
    assert safe_method["has_docstring"] is True


def test_analyzer_call_graph(tmp_path: Path):
    source_a = (
        "def a():\n"
        "    return b()\n"
        "def b():\n"
        "    return 1\n"
    )
    source_c = (
        "from app.a import a\n"
        "def c():\n"
        "    return a()\n"
    )
    _write(tmp_path / "app" / "a.py", source_a)
    _write(tmp_path / "app" / "c.py", source_c)
    analyzer = FunctionFractalAnalyzer()
    graph = analyzer.build_call_graph(tmp_path / "app")

    assert "app.a::a" in graph
    assert "app.a::b" in graph["app.a::a"]["callees"]
    assert "app.c::c" in graph
    assert "app.a::a" in graph["app.c::c"]["callees"]


def test_analyzer_cross_file_impact(tmp_path: Path):
    # a.py has risky function
    # b.py calls it
    # analyzer should flag b as indirectly risky
    source_a = (
        "def risky():\n"
        "    eval('1+1')\n"
    )
    source_b = (
        "from app.a import risky\n"
        "def wrapper():\n"
        "    return risky()\n"
    )
    _write(tmp_path / "app" / "a.py", source_a)
    _write(tmp_path / "app" / "b.py", source_b)
    analyzer = FunctionFractalAnalyzer()
    impact = analyzer.compute_cross_file_impact(tmp_path / "app")

    assert "app.a::risky" in impact
    assert "app.b::wrapper" in impact["app.a::risky"]["downstream"]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
