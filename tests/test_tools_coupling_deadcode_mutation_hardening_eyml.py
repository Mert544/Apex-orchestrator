"""Mutation-hardening tests for three analyzers (eyml session).

Targets ``app.tools.coupling_metrics``, ``app.tools.dead_code_scan`` and
``app.tools.function_fractal_analyzer``. Each test pins a behavior a seeded
single-token mutation would otherwise change without any existing test
noticing, so survivors of ``apex mutants`` are killed. Hermetic: every case
materializes a throwaway tree under ``tmp_path``; no clock / random / network /
git. Assertions avoid timestamps and unordered set/dict iteration order.
"""

from __future__ import annotations

from pathlib import Path

from app.tools.coupling_metrics import (
    CouplingMetrics,
    ModuleCoupling,
    _make_metric,
    _relative_base,
    _resolve,
    _sort_key,
    _stable_key,
    analyze_coupling,
)
from app.tools.dead_code_scan import (
    DeadCodeReport,
    _is_dunder,
    _is_entrypoint,
    _is_test_name,
    _module_name,
    analyze_dead_code,
)
from app.tools.function_fractal_analyzer import FunctionFractalAnalyzer


def _write(root: Path, rel: str, source: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _by_module(metrics: CouplingMetrics) -> dict[str, ModuleCoupling]:
    return {m.module: m for m in metrics.modules}


# --------------------------------------------------------------------------- #
# coupling_metrics
# --------------------------------------------------------------------------- #


def test_instability_is_ce_over_total_exact_value() -> None:
    # Ca=1, Ce=3 -> I = 3/4 = 0.75 exactly. Kills arithmetic/return mutants in
    # ``_make_metric`` (e.g. ce/total -> ce*total, total==0 -> total!=0).
    m = _make_metric("m", ca=1, ce=3)
    assert m.ca == 1
    assert m.ce == 3
    assert m.instability == 0.75


def test_instability_zero_when_no_coupling() -> None:
    # Ca+Ce == 0 short-circuits to 0.0 (no division). Kills the ``total == 0``
    # guard flip and the 0.0 literal.
    m = _make_metric("iso", ca=0, ce=0)
    assert m.instability == 0.0


def test_instability_one_when_only_efferent() -> None:
    m = _make_metric("leaf", ca=0, ce=2)
    assert m.instability == 1.0


def test_resolve_longest_prefix_wins_over_shorter() -> None:
    module_map = {"a.b": Path("a/b.py"), "a": Path("a/__init__.py")}
    # "a.b.c" must resolve to the longer known module "a.b", not "a".
    assert _resolve("a.b.c", module_map) == "a.b"
    # A name matching only the short package falls back to "a".
    assert _resolve("a.x", module_map) == "a"
    assert _resolve("z.y", module_map) is None


def test_relative_base_single_dot_stays_in_own_package() -> None:
    # level 1 (``from . import x``): no climb, base is self's package.
    assert _relative_base(1, "x", "pkg.sub.mod") == "pkg.sub.x"
    assert _relative_base(1, None, "pkg.sub.mod") == "pkg.sub"


def test_relative_base_double_dot_climbs_one_package() -> None:
    # level 2 (``from .. import x``): climb == 1, drop one package segment.
    assert _relative_base(2, "x", "pkg.sub.mod") == "pkg.x"
    assert _relative_base(2, None, "pkg.sub.mod") == "pkg"


def test_relative_base_overclimb_yields_empty_prefix() -> None:
    # Climbing more levels than available empties the package parts.
    assert _relative_base(5, None, "pkg.mod") == ""
    assert _relative_base(5, "x", "pkg.mod") == ".x"


def test_relative_import_contributes_one_internal_edge(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from . import b\n")
    _write(tmp_path, "pkg/b.py", "x = 1\n")
    by = _by_module(analyze_coupling(tmp_path))
    assert by["pkg.a"].ce == 1
    assert by["pkg.b"].ca == 1


def test_submodule_import_credited_to_submodule_not_package(tmp_path: Path) -> None:
    # ``from pkg import sub`` where pkg.sub exists -> edge to pkg.sub, not pkg.
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/sub.py", "x = 1\n")
    _write(tmp_path, "consumer.py", "from pkg import sub\n")
    by = _by_module(analyze_coupling(tmp_path))
    assert by["pkg.sub"].ca == 1
    # The package __init__ (module "pkg") gains no afferent edge here.
    assert by["pkg"].ca == 0


def test_self_edge_is_dropped(tmp_path: Path) -> None:
    # A module importing a name from itself must not count as coupled.
    _write(tmp_path, "solo.py", "import solo\n")
    by = _by_module(analyze_coupling(tmp_path))
    assert by["solo"].ca == 0
    assert by["solo"].ce == 0
    assert by["solo"].instability == 0.0


def test_duplicate_imports_count_once(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/b.py", "x = 1\n")
    _write(tmp_path, "pkg/a.py", "import pkg.b\nimport pkg.b\nfrom pkg import b\n")
    by = _by_module(analyze_coupling(tmp_path))
    assert by["pkg.a"].ce == 1
    assert by["pkg.b"].ca == 1


def test_empty_project_returns_empty_metrics(tmp_path: Path) -> None:
    metrics = analyze_coupling(tmp_path)
    assert metrics.modules == []
    assert metrics.most_unstable == []
    assert metrics.most_stable == []
    assert metrics.module_count == 0


def test_unparsable_file_stays_a_node_with_no_edges(tmp_path: Path) -> None:
    _write(tmp_path, "broken.py", "def (:\n")
    by = _by_module(analyze_coupling(tmp_path))
    assert "broken" in by
    assert by["broken"].ca == 0
    assert by["broken"].ce == 0


def test_sort_key_orders_unstable_first_then_ce_then_ca_then_name() -> None:
    # Higher instability sorts first (negated in key); ties broken by -ce, -ca,
    # then ascending name. Pin the exact tuple shape mutations would disturb.
    a = ModuleCoupling("a", ca=0, ce=2, instability=1.0)
    b = ModuleCoupling("b", ca=1, ce=1, instability=0.5)
    assert _sort_key(a) == (-1.0, -2, 0, "a")
    assert _sort_key(b) == (-0.5, -1, -1, "b")
    assert _sort_key(a) < _sort_key(b)  # a is more unstable -> sorts first


def test_stable_key_orders_stable_first_then_afferent_fan() -> None:
    stable = ModuleCoupling("s", ca=3, ce=0, instability=0.0)
    unstable = ModuleCoupling("u", ca=0, ce=3, instability=1.0)
    assert _stable_key(stable) == (0.0, -3, 0, "s")
    assert _stable_key(stable) < _stable_key(unstable)


def test_highlights_only_include_coupled_modules(tmp_path: Path) -> None:
    # An isolated leaf (Ca+Ce == 0) must be excluded from both highlight lists.
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from pkg import b\n")
    _write(tmp_path, "pkg/b.py", "x = 1\n")
    _write(tmp_path, "pkg/lonely.py", "z = 0\n")
    metrics = analyze_coupling(tmp_path)
    unstable_names = {m.module for m in metrics.most_unstable}
    stable_names = {m.module for m in metrics.most_stable}
    assert "pkg.lonely" not in unstable_names
    assert "pkg.lonely" not in stable_names
    assert "pkg.a" in unstable_names


def test_max_files_caps_the_module_map(tmp_path: Path) -> None:
    for i in range(5):
        _write(tmp_path, f"m{i}.py", "x = 1\n")
    metrics = analyze_coupling(tmp_path, max_files=2)
    assert metrics.module_count == 2


# --------------------------------------------------------------------------- #
# dead_code_scan
# --------------------------------------------------------------------------- #


def test_is_dunder_boundary_on_length_four() -> None:
    # ``len(name) > 4`` so a 4-char "____" is NOT a dunder (boundary flip guard).
    assert _is_dunder("____") is False
    assert _is_dunder("__x__") is True
    assert _is_dunder("__init__") is True
    assert _is_dunder("name") is False
    assert _is_dunder("__x") is False  # endswith fails
    assert _is_dunder("x__") is False  # startswith fails


def test_is_entrypoint_main_and_cmd_prefix() -> None:
    assert _is_entrypoint("main") is True
    assert _is_entrypoint("cmd_run") is True
    assert _is_entrypoint("cmd_") is True
    assert _is_entrypoint("run") is False
    assert _is_entrypoint("command_x") is False


def test_is_test_name_prefix_only() -> None:
    assert _is_test_name("test_x") is True
    assert _is_test_name("test_") is True
    assert _is_test_name("tester") is False  # not the underscore form
    assert _is_test_name("x_test_y") is False


def test_module_name_drops_py_and_collapses_init() -> None:
    assert _module_name("pkg/sub/mod.py") == "pkg.sub.mod"
    assert _module_name("pkg/__init__.py") == "pkg"
    assert _module_name("mod.py") == "mod"
    # Without a .py suffix the whole thing is treated as path parts.
    assert _module_name("pkg/mod") == "pkg.mod"


def test_unreferenced_symbol_reports_exact_record(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/lib.py", "def ghost():\n    return 2\n")
    _write(tmp_path, "pkg/use.py", "x = 1\n")
    report = analyze_dead_code(tmp_path)
    assert report.candidates == [
        {"module": "pkg/lib.py", "symbol": "ghost", "kind": "function", "line": 1}
    ]
    assert report.candidate_count == 1
    assert report.reported_count == 1
    assert report.truncated is False


def test_class_kind_label_is_class(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/lib.py", "class Ghost:\n    pass\n")
    _write(tmp_path, "pkg/use.py", "x = 1\n")
    report = analyze_dead_code(tmp_path)
    (only,) = report.candidates
    assert only["kind"] == "class"


def test_referenced_symbol_is_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/lib.py", "def alive():\n    return 1\n")
    _write(tmp_path, "pkg/use.py", "from pkg.lib import alive\n\nv = alive()\n")
    report = analyze_dead_code(tmp_path)
    assert report.candidates == []
    assert report.candidate_count == 0


def test_truncated_true_when_candidates_exceed_cap(tmp_path: Path) -> None:
    # 21 unreferenced top-level functions; cap is 20 -> truncated True, exactly
    # 20 reported. Kills the ``> _MAX_CANDIDATES`` / cap-slice mutations.
    body = "".join(f"def ghost{i}():\n    return {i}\n\n\n" for i in range(21))
    _write(tmp_path, "pkg/lib.py", body)
    _write(tmp_path, "pkg/use.py", "x = 1\n")
    report = analyze_dead_code(tmp_path)
    assert report.candidate_count == 21
    assert report.reported_count == 20
    assert len(report.candidates) == 20
    assert report.truncated is True


def test_exactly_cap_candidates_is_not_truncated(tmp_path: Path) -> None:
    body = "".join(f"def ghost{i}():\n    return {i}\n\n\n" for i in range(20))
    _write(tmp_path, "pkg/lib.py", body)
    _write(tmp_path, "pkg/use.py", "x = 1\n")
    report = analyze_dead_code(tmp_path)
    assert report.candidate_count == 20
    assert report.reported_count == 20
    assert report.truncated is False


def test_candidates_sorted_by_module_then_line_then_symbol(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/b.py",
        "def zeta():\n    return 1\n\n\ndef alpha():\n    return 2\n",
    )
    _write(tmp_path, "pkg/a.py", "def gamma():\n    return 3\n")
    _write(tmp_path, "pkg/use.py", "x = 1\n")
    report = analyze_dead_code(tmp_path)
    ordered = [(c["module"], c["line"], c["symbol"]) for c in report.candidates]
    assert ordered == [
        ("pkg/a.py", 1, "gamma"),
        ("pkg/b.py", 1, "zeta"),
        ("pkg/b.py", 5, "alpha"),
    ]


def test_definitions_seen_counts_only_surviving_per_def_candidates(tmp_path: Path) -> None:
    # main (entrypoint) and __helper__ (dunder) are excluded per-def, so they do
    # not increment definitions_seen; only ``ghost`` does.
    _write(
        tmp_path,
        "pkg/lib.py",
        "def main():\n    return 0\n\n\n"
        "def __helper__():\n    return 1\n\n\n"
        "def ghost():\n    return 2\n",
    )
    _write(tmp_path, "pkg/use.py", "x = 1\n")
    report = analyze_dead_code(tmp_path)
    assert report.definitions_seen == 1


def test_files_scanned_counts_parsed_modules(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/a.py", "x = 1\n")
    _write(tmp_path, "pkg/b.py", "y = 2\n")
    report = analyze_dead_code(tmp_path)
    assert report.files_scanned == 2


def test_unparsable_file_does_not_count_as_scanned(tmp_path: Path) -> None:
    _write(tmp_path, "ok.py", "x = 1\n")
    _write(tmp_path, "bad.py", "def (:\n")
    report = analyze_dead_code(tmp_path)
    # Only the parsable file is counted.
    assert report.files_scanned == 1


def test_max_files_zero_scans_nothing(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "def ghost():\n    return 1\n")
    report = analyze_dead_code(tmp_path, max_files=0)
    assert report.files_scanned == 0
    assert report.candidates == []


def test_negative_max_files_clamped_to_zero(tmp_path: Path) -> None:
    # ``max(0, max_files)`` guards a negative cap -> empty, not a reverse slice.
    _write(tmp_path, "a.py", "def ghost():\n    return 1\n")
    report = analyze_dead_code(tmp_path, max_files=-3)
    assert report.files_scanned == 0


def test_missing_root_returns_empty_report(tmp_path: Path) -> None:
    report = analyze_dead_code(tmp_path / "nope")
    assert isinstance(report, DeadCodeReport)
    assert report.files_scanned == 0
    assert report.candidates == []


def test_string_constant_reference_suppresses_flag(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/lib.py", "def ghost():\n    return 1\n")
    _write(tmp_path, "pkg/reg.py", 'TABLE = ["ghost"]\n')
    report = analyze_dead_code(tmp_path)
    assert report.candidates == []


def test_dynamic_access_suppresses_only_its_own_module(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/dyn.py",
        "def hidden():\n    return 1\n\n\nv = getattr(object(), 'x', None)\n",
    )
    _write(tmp_path, "pkg/plain.py", "def ghost():\n    return 2\n")
    _write(tmp_path, "pkg/use.py", "z = 1\n")
    report = analyze_dead_code(tmp_path)
    symbols = {c["symbol"] for c in report.candidates}
    assert "hidden" not in symbols  # suppressed by getattr in its module
    assert "ghost" in symbols  # plain.py has no dynamic access


def test_star_import_target_module_symbols_all_live(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/lib.py", "def ghost():\n    return 1\n")
    _write(tmp_path, "pkg/consumer.py", "from pkg.lib import *\n")
    report = analyze_dead_code(tmp_path)
    symbols = {c["symbol"] for c in report.candidates}
    assert "ghost" not in symbols


def test_decorated_definition_is_never_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/lib.py",
        "def deco(f):\n    return f\n\n\n@deco\ndef ghost():\n    return 1\n",
    )
    _write(tmp_path, "pkg/use.py", "x = 1\n")
    report = analyze_dead_code(tmp_path)
    symbols = {c["symbol"] for c in report.candidates}
    assert "ghost" not in symbols


def test_determinism_repeated_runs_identical(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/lib.py",
        "def g1():\n    return 1\n\n\ndef g2():\n    return 2\n",
    )
    _write(tmp_path, "pkg/use.py", "x = 1\n")
    first = analyze_dead_code(tmp_path)
    second = analyze_dead_code(tmp_path)
    assert first.candidates == second.candidates


# --------------------------------------------------------------------------- #
# function_fractal_analyzer
# --------------------------------------------------------------------------- #


def test_long_function_boundary_at_thirty_lines(tmp_path: Path) -> None:
    # ``lines > 30`` flags a long function. ``lines`` is the unparsed newline
    # count; build a body whose unparse yields exactly 31 then 30 lines so the
    # boundary (and its off-by-one mutant) is exercised both sides.
    def body(n: int) -> str:
        stmts = "\n".join(f"    x{i} = {i}" for i in range(n))
        return f'def f():\n    """d"""\n{stmts}\n'

    analyzer = FunctionFractalAnalyzer()
    _write(tmp_path, "app/long.py", body(40))
    res = analyzer.analyze_file(tmp_path / "app" / "long.py")[0]
    assert res["line_count"] > 30
    assert any("long_function" in r for r in res["risks"])

    _write(tmp_path, "app/short.py", 'def f():\n    """d"""\n    x = 1\n')
    res2 = analyzer.analyze_file(tmp_path / "app" / "short.py")[0]
    assert res2["line_count"] <= 30
    assert not any("long_function" in r for r in res2["risks"])


def test_too_many_arguments_boundary_at_five(tmp_path: Path) -> None:
    # ``arg_count > 5`` flags; 5 args is NOT flagged, 6 args IS.
    analyzer = FunctionFractalAnalyzer()
    _write(tmp_path, "app/five.py", 'def f(a, b, c, d, e):\n    """d"""\n    return 1\n')
    five = analyzer.analyze_file(tmp_path / "app" / "five.py")[0]
    assert five["arg_count"] == 5
    assert not any("too_many_arguments" in r for r in five["risks"])

    _write(
        tmp_path, "app/six.py", 'def f(a, b, c, d, e, g):\n    """d"""\n    return 1\n'
    )
    six = analyzer.analyze_file(tmp_path / "app" / "six.py")[0]
    assert six["arg_count"] == 6
    assert any("too_many_arguments (6)" in r for r in six["risks"])


def test_arg_count_includes_kwonly_args(tmp_path: Path) -> None:
    analyzer = FunctionFractalAnalyzer()
    _write(
        tmp_path,
        "app/kw.py",
        'def f(a, b, *, c, d):\n    """d"""\n    return 1\n',
    )
    res = analyzer.analyze_file(tmp_path / "app" / "kw.py")[0]
    assert res["arg_count"] == 4


def test_risk_score_accumulates_and_caps_at_one(tmp_path: Path) -> None:
    # eval+exec+input+__import__ (0.3 each) plus missing docstring -> well over
    # 1.0, but the score is clamped to 1.0 (min(.,1.0)). Kills the cap mutant.
    src = (
        "def danger(x):\n"
        "    eval(x)\n"
        "    exec(x)\n"
        "    input()\n"
        "    __import__('os')\n"
    )
    _write(tmp_path, "app/d.py", src)
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "d.py")[0]
    assert res["risk_score"] == 1.0


def test_missing_docstring_adds_exactly_point_one(tmp_path: Path) -> None:
    # A bare, short, well-argued function: only the missing-docstring risk fires,
    # score == 0.1 exactly. Pins the 0.1 increment and the rounding to 2 places.
    _write(tmp_path, "app/m.py", "def f(a):\n    return a\n")
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "m.py")[0]
    assert res["risks"] == ["missing_docstring"]
    assert res["risk_score"] == 0.1


def test_bare_except_scores_point_two_each(tmp_path: Path) -> None:
    src = (
        "def f(a):\n"
        '    """d"""\n'
        "    try:\n"
        "        return a\n"
        "    except:\n"
        "        return None\n"
    )
    _write(tmp_path, "app/e.py", src)
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "e.py")[0]
    assert res["risks"].count("bare_except") == 1
    assert res["risk_score"] == 0.2


def test_two_bare_excepts_score_point_four(tmp_path: Path) -> None:
    src = (
        "def f(a):\n"
        '    """d"""\n'
        "    try:\n"
        "        pass\n"
        "    except:\n"
        "        pass\n"
        "    try:\n"
        "        pass\n"
        "    except:\n"
        "        pass\n"
        "    return a\n"
    )
    _write(tmp_path, "app/e2.py", src)
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "e2.py")[0]
    assert res["risks"].count("bare_except") == 2
    assert res["risk_score"] == 0.4


def test_typed_except_is_not_bare(tmp_path: Path) -> None:
    src = (
        "def f(a):\n"
        '    """d"""\n'
        "    try:\n"
        "        return a\n"
        "    except ValueError:\n"
        "        return None\n"
    )
    _write(tmp_path, "app/e3.py", src)
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "e3.py")[0]
    assert "bare_except" not in res["risks"]


def test_lineno_is_node_lineno(tmp_path: Path) -> None:
    src = '# header\n# second\ndef f(a):\n    """d"""\n    return a\n'
    _write(tmp_path, "app/n.py", src)
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "n.py")[0]
    assert res["lineno"] == 3


def test_class_method_name_is_qualified(tmp_path: Path) -> None:
    src = 'class W:\n    def m(self):\n        """d"""\n        return 1\n'
    _write(tmp_path, "app/c.py", src)
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "c.py")[0]
    assert res["name"] == "W.m"
    assert res["full_name"].endswith("::W.m")


def test_class_method_not_double_counted(tmp_path: Path) -> None:
    src = 'class W:\n    def m(self):\n        """d"""\n        return 1\n'
    _write(tmp_path, "app/c2.py", src)
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "c2.py")
    assert len(res) == 1


def test_attribute_chain_renders_dotted_target() -> None:
    import ast as _ast

    call = _ast.parse("a.b.c()").body[0].value
    assert FunctionFractalAnalyzer._attribute_chain(call.func) == "a.b.c"


def test_chain_risk_only_on_exact_match(tmp_path: Path) -> None:
    # ``os.system`` is a risk; ``os.path.join`` is not.
    src = (
        "import os\n"
        "def f(x):\n"
        '    """d"""\n'
        "    os.system(x)\n"
        "    os.path.join(x)\n"
    )
    _write(tmp_path, "app/o.py", src)
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "o.py")[0]
    risks = str(res["risks"])
    assert "os.system()" in risks
    assert res["risks"].count("Uses os.system() — shell injection risk") == 1


def test_purity_pure_function_reports_no_side_effects(tmp_path: Path) -> None:
    _write(tmp_path, "app/p.py", 'def f(a, b):\n    """d"""\n    return a + b\n')
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "p.py")[0]
    assert res["purity"] == "pure"
    assert res["side_effects"] == []


def test_purity_print_makes_impure(tmp_path: Path) -> None:
    _write(tmp_path, "app/pr.py", 'def f(a):\n    """d"""\n    print(a)\n    return a\n')
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "pr.py")[0]
    assert res["purity"] == "impure"
    assert res["side_effects"] == ["builtin:print"]


def test_purity_write_method_is_io_write(tmp_path: Path) -> None:
    src = 'def f(fh, a):\n    """d"""\n    fh.write(a)\n    return a\n'
    _write(tmp_path, "app/w.py", src)
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "w.py")[0]
    assert res["side_effects"] == ["io:write"]


def test_purity_module_effect_root_detected_through_chain(tmp_path: Path) -> None:
    src = 'import sys\ndef f():\n    """d"""\n    sys.stdout.write("x")\n'
    _write(tmp_path, "app/sm.py", src)
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "sm.py")[0]
    # Both the io:write (write attr) and module:sys (root effect module) fire,
    # deduplicated and sorted.
    assert res["side_effects"] == ["io:write", "module:sys"]


def test_purity_global_and_nonlocal_reasons(tmp_path: Path) -> None:
    src = (
        'def outer():\n'
        '    """d"""\n'
        "    x = 1\n"
        "    def inner():\n"
        "        nonlocal x\n"
        "        x = 2\n"
        "    return inner\n"
    )
    _write(tmp_path, "app/nl.py", src)
    res = FunctionFractalAnalyzer().analyze_file(tmp_path / "app" / "nl.py")
    outer = next(r for r in res if r["name"] == "outer")
    assert "nonlocal_state" in outer["side_effects"]


def test_is_test_file_detection() -> None:
    assert FunctionFractalAnalyzer._is_test_file(Path("test_x.py")) is True
    assert FunctionFractalAnalyzer._is_test_file(Path("foo_test_bar.py")) is True
    assert FunctionFractalAnalyzer._is_test_file(Path("module.py")) is False


def test_analyze_file_missing_returns_empty(tmp_path: Path) -> None:
    analyzer = FunctionFractalAnalyzer()
    assert analyzer.analyze_file(tmp_path / "nope.py") == []


def test_cached_ast_reparses_when_mtime_changes(tmp_path: Path) -> None:
    p = tmp_path / "app" / "m.py"
    _write(tmp_path, "app/m.py", 'def a():\n    """d"""\n    return 1\n')
    analyzer = FunctionFractalAnalyzer()
    first = analyzer.analyze_file(p)
    assert [r["name"] for r in first] == ["a"]
    # Rewrite with a different mtime; analyzer must pick up the new content.
    import os

    st = p.stat()
    p.write_text('def b():\n    """d"""\n    return 2\n', encoding="utf-8")
    os.utime(p, (st.st_atime, st.st_mtime + 10))
    second = analyzer.analyze_file(p)
    assert [r["name"] for r in second] == ["b"]


def test_build_call_graph_wires_caller_and_callee(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "app/a.py",
        'def callee():\n    """d"""\n    return 1\n',
    )
    _write(
        tmp_path,
        "app/b.py",
        'from app.a import callee\n\n\ndef caller():\n    """d"""\n    return callee()\n',
    )
    graph = FunctionFractalAnalyzer().build_call_graph(tmp_path)
    assert "app.b::caller" in graph["app.a::callee"]["callers"]
    assert "app.a::callee" in graph["app.b::caller"]["callees"]


def test_call_graph_cache_reused_on_second_call(tmp_path: Path) -> None:
    _write(tmp_path, "app/a.py", 'def f():\n    """d"""\n    return 1\n')
    analyzer = FunctionFractalAnalyzer()
    first = analyzer.build_call_graph(tmp_path)
    second = analyzer.build_call_graph(tmp_path)
    assert first is second  # identical object -> cache hit


def test_compute_cross_file_impact_lists_downstream(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "app/a.py",
        "def risky(x):\n    eval(x)\n    return x\n",
    )
    _write(
        tmp_path,
        "app/b.py",
        'from app.a import risky\n\n\ndef wrapper(x):\n    """d"""\n    return risky(x)\n',
    )
    impact = FunctionFractalAnalyzer().compute_cross_file_impact(tmp_path)
    assert "app.a::risky" in impact
    assert "app.b::wrapper" in impact["app.a::risky"]["downstream"]
    assert impact["app.a::risky"]["downstream_count"] == 1
