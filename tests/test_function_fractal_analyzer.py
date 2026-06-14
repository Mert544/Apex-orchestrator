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


def test_analyze_function_risk_branches(tmp_path: Path):
    (tmp_path / "app").mkdir()
    src = (
        "def dangers(x):\n"
        "    exec(x)\n"
        "    __import__('os')\n"
        "    import pickle, yaml, subprocess\n"
        "    pickle.loads(x)\n"
        "    yaml.load(x)\n"
        "    subprocess.call(x)\n"
    )
    (tmp_path / "app" / "d.py").write_text(src, encoding="utf-8")
    res = {r["name"]: r for r in FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "d.py")}
    risks = str(res["dangers"]["risks"])
    assert "exec()" in risks
    assert "Dynamic import" in risks
    assert "pickle.loads()" in risks
    assert "yaml.load()" in risks
    assert "subprocess" in risks
    # Many distinct 0.3 risks, but the score is capped at 1.0.
    assert res["dangers"]["risk_score"] == 1.0
    assert res["dangers"]["full_name"].endswith("::dangers")


def test_analyze_function_size_and_arg_and_except_heuristics(tmp_path: Path):
    (tmp_path / "app").mkdir()
    body = "\n".join(f'    x{i} = {i}' for i in range(35))      # > 30 lines
    src = (
        '"""mod."""\n'
        "def big(a, b, c, d, e, f):\n"                          # > 5 args
        '    """Has a docstring so that risk is not docstring-driven."""\n'
        f"{body}\n"
        "    try:\n"
        "        pass\n"
        "    except:\n"                                          # bare except
        "        pass\n"
    )
    (tmp_path / "app" / "big.py").write_text(src, encoding="utf-8")
    info = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "big.py")[0]
    risks = str(info["risks"])
    assert info["has_docstring"] is True
    assert "long_function" in risks
    assert "too_many_arguments (6)" in risks
    assert "bare_except" in risks
    assert info["arg_count"] == 6
    assert info["line_count"] > 30


def test_purity_pure_function_has_no_side_effects(tmp_path: Path):
    """Rule: a function is `pure` (side_effects == []) when its body shows none
    of the impure signals — no global/nonlocal, no print/open/input builtin
    call, no os/sys/subprocess/shutil/socket/logging/requests-rooted call, and
    no `.write(...)` method call. It just computes from args and returns."""
    (tmp_path / "app").mkdir()
    src = (
        "def add(a, b):\n"
        '    """Pure: computes from args only."""\n'
        "    total = a + b\n"
        "    return total\n"
    )
    (tmp_path / "app" / "pure.py").write_text(src, encoding="utf-8")
    info = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "pure.py")[0]
    assert info["purity"] == "pure"
    assert info["side_effects"] == []


def test_purity_fires_on_print_open_global_and_module_effects(tmp_path: Path):
    """Each impure signal is detected with a stable, sorted reason string:
    `print`/`open` builtins, a `global` statement, an `os.`-rooted call, and a
    `.write(...)` method call all mark the function `impure`."""
    (tmp_path / "app").mkdir()
    src = (
        "_CACHE = {}\n"
        "def emit(path, data):\n"
        '    """Impure: I/O, global mutation, module + write effects."""\n'
        "    global _CACHE\n"
        "    print(data)\n"
        "    os.makedirs(path)\n"
        "    f = open(path)\n"
        "    f.write(data)\n"
        "    return path\n"
    )
    (tmp_path / "app" / "impure.py").write_text(src, encoding="utf-8")
    info = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "impure.py")[0]
    assert info["purity"] == "impure"
    assert info["side_effects"] == [
        "builtin:open",
        "builtin:print",
        "global_state",
        "io:write",
        "module:os",
    ]


def test_purity_nonlocal_and_nested_module_chain(tmp_path: Path):
    """`nonlocal` rebinding is impure, and a deep attribute chain rooted at an
    effect module (e.g. `sys.stdout.write`) is attributed to its root module
    (`module:sys`) plus the `io:write` method signal."""
    (tmp_path / "app").mkdir()
    src = (
        "def outer():\n"
        '    """Uses nonlocal and a sys-rooted write."""\n'
        "    count = 0\n"
        "    def bump():\n"
        "        nonlocal count\n"
        "        count += 1\n"
        "        sys.stdout.write(str(count))\n"
        "    bump()\n"
        "    return count\n"
    )
    (tmp_path / "app" / "nl.py").write_text(src, encoding="utf-8")
    res = {r["name"]: r for r in FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "nl.py")}
    # `outer` walks into nested `bump` too (effects of nested scopes belong here).
    assert res["outer"]["purity"] == "impure"
    assert "nonlocal_state" in res["outer"]["side_effects"]
    assert "module:sys" in res["outer"]["side_effects"]
    assert "io:write" in res["outer"]["side_effects"]
    # The nested function is also analyzed on its own and flagged.
    assert res["bump"]["purity"] == "impure"
    assert res["bump"]["side_effects"] == ["io:write", "module:sys", "nonlocal_state"]


def test_purity_dimension_is_additive_and_existing_claims_unchanged(tmp_path: Path):
    """The purity dimension is additive: every prior key remains, and the
    existing risk/complexity/doc claims plus risk_score are unchanged on a
    function that is simultaneously risky and impure."""
    (tmp_path / "app").mkdir()
    src = (
        "def handler(data):\n"
        "    print(data)\n"
        "    eval(data)\n"
        "    return data\n"
    )
    (tmp_path / "app" / "mix.py").write_text(src, encoding="utf-8")
    info = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "mix.py")[0]
    # Every prior key still present.
    for key in ("name", "full_name", "module", "has_docstring", "risks",
                "risk_score", "line_count", "arg_count"):
        assert key in info
    # Existing claims byte-for-byte: eval risk + missing docstring, score intact.
    assert "Uses eval() — arbitrary code execution risk" in info["risks"]
    assert "missing_docstring" in info["risks"]
    assert info["risk_score"] == 0.4  # 0.3 (eval) + 0.1 (missing docstring)
    # New dimension lives alongside, not folded into risks/risk_score.
    assert info["purity"] == "impure"
    assert info["side_effects"] == ["builtin:print"]
    assert "purity" not in str(info["risks"])
    assert "builtin:print" not in str(info["risks"])


def test_purity_dimension_is_deterministic(tmp_path: Path):
    """Same input -> same output across repeated, independent analyses."""
    (tmp_path / "app").mkdir()
    src = (
        "def g(x):\n"
        '    """g."""\n'
        "    logging.info(x)\n"
        "    return x\n"
    )
    (tmp_path / "app" / "detp.py").write_text(src, encoding="utf-8")
    first = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "detp.py")
    second = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "detp.py")
    assert first == second
    assert first[0]["purity"] == "impure"
    assert first[0]["side_effects"] == ["module:logging"]
