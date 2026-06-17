"""Mutation-hardening pins for the profiler modules (the grade drivers).

Standalone, deterministic redundancy for ``app/tools/project_profile.py`` and
``app/tools/profile_scanners.py``: a focused battery that exercises the
load-bearing pure helpers and branch boundaries directly, so a single-token
fault in any of them is caught even in isolation from the broader suite (the
"never fakes green" moat). Every assertion targets an exact value, boundary, or
ordering — nothing here depends on a wall clock, set/dict iteration order, or
git history, so the pins are reproducible.

Both modules already score 1.0 across their full mutant population; these tests
add independent kill-power for the specific operators/constants the profiler's
correctness hinges on (thresholds, sort keys, filter predicates, the pure
parsing/resolution helpers).
"""
from __future__ import annotations

from pathlib import Path

from app.tools.profile_scanners import _CodeQualityScansMixin
from app.tools.project_profile import (
    ProjectProfile,
    ProjectProfiler,
    render_analysis_scope_line,
)


def _bare_profiler(root: str | Path = ".") -> ProjectProfiler:
    """A profiler whose scan methods need only profile fields / pure inputs."""
    return ProjectProfiler(str(root))


# --------------------------------------------------------------------------- #
# project_profile.py — pure churn/blame helpers
# --------------------------------------------------------------------------- #

def test_parse_churn_commits_groups_author_and_files():
    stdout = (
        "@commit@Alice\n"
        "app/a.py\n"
        "app/b.py\n"
        "@commit@Bob\n"
        "app/c.py\n"
    )
    commits = ProjectProfiler._parse_churn_commits(stdout)
    assert commits == [("Alice", ["app/a.py", "app/b.py"]), ("Bob", ["app/c.py"])]


def test_parse_churn_commits_flushes_trailing_commit_only_once():
    # A trailing commit with no following @commit@ marker must still be emitted,
    # and exactly once (kills a mutated flush guard / duplicate-append).
    commits = ProjectProfiler._parse_churn_commits("@commit@Solo\nx.py\n")
    assert commits == [("Solo", ["x.py"])]


def test_parse_churn_commits_empty_marker_without_files_is_dropped():
    # An author marker with no file lines produces no commit entry (the `if
    # current` guard before flushing).
    assert ProjectProfiler._parse_churn_commits("@commit@A\n@commit@B\nx.py\n") == [
        ("B", ["x.py"])
    ]


def test_oldest_debt_ctime_returns_minimum_committer_time():
    blame = (
        "committer-time 500\n"
        "\t# TODO: newer\n"
        "committer-time 200\n"
        "\t# FIXME: older\n"
    )
    assert ProjectProfiler._oldest_debt_ctime(
        blame, ProjectProfiler.DEBT_MARKER_RE
    ) == 200


def test_oldest_debt_ctime_ignores_non_marker_and_unanchored_lines():
    # A marker line with no preceding committer-time is unanchored (None ctime),
    # and a non-marker content line is ignored entirely.
    blame = "\t# TODO: unanchored\ncommitter-time 300\n\tplain code\n"
    assert ProjectProfiler._oldest_debt_ctime(
        blame, ProjectProfiler.DEBT_MARKER_RE
    ) is None


# --------------------------------------------------------------------------- #
# project_profile.py — knowledge-risk thresholds
# --------------------------------------------------------------------------- #

def test_build_knowledge_risks_none_when_single_active_author():
    prof = _bare_profiler()
    # Only one author clears KNOWLEDGE_MIN_COMMITS (5): not multi-author, so the
    # whole signal is suppressed (returns None).
    commits = [("Solo", ["app/m.py"]) for _ in range(6)]
    from collections import Counter
    author_touches = {"app/m.py": Counter({"Solo": 6})}
    assert prof._build_knowledge_risks(commits, author_touches) is None


def test_build_knowledge_risks_flags_dominant_author_above_share():
    from collections import Counter

    prof = _bare_profiler()
    # Two active authors (>=5 commits each), so the signal runs. Module m.py is
    # touched 9x by Alice and 1x by Bob -> 90% share >= KNOWLEDGE_SHARE (0.85).
    commits = [("Alice", ["app/m.py"]) for _ in range(5)] + [
        ("Bob", ["app/n.py"]) for _ in range(5)
    ]
    author_touches = {
        "app/m.py": Counter({"Alice": 9, "Bob": 1}),
    }
    risks = prof._build_knowledge_risks(commits, author_touches)
    assert risks == [{"module": "app/m.py", "share": 90, "commits": 10}]


def test_build_knowledge_risks_skips_below_share_floor():
    from collections import Counter

    prof = _bare_profiler()
    commits = [("Alice", ["x"]) for _ in range(5)] + [("Bob", ["y"]) for _ in range(5)]
    # 8/10 == 0.8 < 0.85 share floor -> not a risk.
    author_touches = {"app/m.py": Counter({"Alice": 8, "Bob": 2})}
    assert prof._build_knowledge_risks(commits, author_touches) == []


def test_build_knowledge_risks_skips_too_few_touches():
    from collections import Counter

    prof = _bare_profiler()
    commits = [("Alice", ["x"]) for _ in range(5)] + [("Bob", ["y"]) for _ in range(5)]
    # total == 4 < KNOWLEDGE_MIN_COMMITS (5) -> module skipped even at 100%.
    author_touches = {"app/m.py": Counter({"Alice": 4})}
    assert prof._build_knowledge_risks(commits, author_touches) == []


# --------------------------------------------------------------------------- #
# project_profile.py — doc-drift reference resolution (pure classmethods)
# --------------------------------------------------------------------------- #

def test_doc_ref_path_part_accepts_path_with_known_extension():
    assert ProjectProfiler._doc_ref_path_part("`app/foo.py`".strip("`")) == "app/foo.py"


def test_doc_ref_path_part_strips_dot_slash_and_line_suffix():
    assert ProjectProfiler._doc_ref_path_part("./app/x.py:12") == "app/x.py"


def test_doc_ref_path_part_rejects_url_and_placeholder():
    assert ProjectProfiler._doc_ref_path_part("https://x/app/foo.py") is None
    assert ProjectProfiler._doc_ref_path_part("path/to/foo.py") is None


def test_doc_ref_path_part_rejects_non_path_and_unknown_extension():
    # No separator -> not a file ref; dotted module name is not path-like.
    assert ProjectProfiler._doc_ref_path_part("hashlib.md5") is None
    # Known separator but unknown extension.
    assert ProjectProfiler._doc_ref_path_part("app/foo.xyz") is None


def test_doc_ref_path_part_rejects_artifact_root():
    assert ProjectProfiler._doc_ref_path_part(".git/config.py") is None
    assert ProjectProfiler._doc_ref_path_part("node_modules/x/y.js") is None


def test_is_doc_file_ref_requires_real_extension_on_last_segment():
    assert ProjectProfiler._is_doc_file_ref("a/b.py") is True
    # Final segment has a dot but the ext after it is unknown.
    assert ProjectProfiler._is_doc_file_ref("hashlib.md5/sha1") is False
    # Leading slash (a slash-command) is rejected.
    assert ProjectProfiler._is_doc_file_ref("/abs/x.py") is False


# --------------------------------------------------------------------------- #
# project_profile.py — co-change link resolution (pure helpers)
# --------------------------------------------------------------------------- #

def test_resolve_cochange_module_longest_prefix_match():
    mmap = {"app.engine": "app/engine/__init__.py", "app.engine.foo": "app/engine/foo.py"}
    # Exact match wins.
    assert ProjectProfiler._resolve_cochange_module("app.engine.foo", mmap) == "app/engine/foo.py"
    # A deeper import resolves to the longest known prefix.
    assert ProjectProfiler._resolve_cochange_module("app.engine.foo.bar", mmap) == "app/engine/foo.py"
    # No prefix matches -> None.
    assert ProjectProfiler._resolve_cochange_module("other.mod", mmap) is None


def test_cochange_module_map_collapses_init_and_drops_suffix():
    prof = _bare_profiler()
    gaps = [{"a": "app/engine/foo.py", "b": "app/engine/__init__.py"}]
    mapping = prof._cochange_module_map(gaps)
    assert mapping == {
        "app.engine.foo": "app/engine/foo.py",
        "app.engine": "app/engine/__init__.py",
    }


def test_imported_symbols_resolves_named_imports_between_pair(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text(
        "from pkg.b import Thing, helper\nimport os\n", encoding="utf-8"
    )
    (tmp_path / "pkg" / "b.py").write_text("Thing = 1\ndef helper():\n    return 1\n", encoding="utf-8")
    prof = _bare_profiler(tmp_path)
    module_map = {"pkg.a": "pkg/a.py", "pkg.b": "pkg/b.py"}
    syms = prof._imported_symbols("pkg/a.py", "pkg/b.py", module_map)
    assert syms == ["Thing", "helper"]


def test_imported_symbols_ignores_relative_and_star_imports(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text(
        "from . import b\nfrom pkg.b import *\n", encoding="utf-8"
    )
    (tmp_path / "pkg" / "b.py").write_text("x = 1\n", encoding="utf-8")
    prof = _bare_profiler(tmp_path)
    module_map = {"pkg.a": "pkg/a.py", "pkg.b": "pkg/b.py"}
    # Relative import carries node.level (skipped); `*` is excluded.
    assert prof._imported_symbols("pkg/a.py", "pkg/b.py", module_map) == []


def test_cochange_links_sorted_and_capped(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text(
        "from pkg.b import A, B, C, D\n", encoding="utf-8"
    )
    (tmp_path / "pkg" / "b.py").write_text("A=B=C=D=1\n", encoding="utf-8")
    prof = _bare_profiler(tmp_path)
    module_map = {"pkg.a": "pkg/a.py", "pkg.b": "pkg/b.py"}
    links = prof._cochange_links("pkg/a.py", "pkg/b.py", module_map)
    # Capped at 3, sorted ascending by (from, to, symbol).
    assert links == [
        {"from": "pkg/a.py", "to": "pkg/b.py", "symbol": "A"},
        {"from": "pkg/a.py", "to": "pkg/b.py", "symbol": "B"},
        {"from": "pkg/a.py", "to": "pkg/b.py", "symbol": "C"},
    ]


# --------------------------------------------------------------------------- #
# project_profile.py — scope accounting + render line
# --------------------------------------------------------------------------- #

def test_scan_analysis_scope_ratios_and_breakdown():
    from collections import Counter

    prof = _bare_profiler()
    profile = ProjectProfile(root=".")
    ext_counter = Counter({".py": 3, ".js": 4, ".png": 9, ".zig": 1})
    prof._scan_analysis_scope(profile, ext_counter)
    # .png excluded from denominator; .zig folds into "other".
    assert profile.python_file_count == 3
    assert profile.source_file_count == 8
    assert profile.language_breakdown == {"JavaScript": 4, "other": 1}
    assert profile.analyzed_ratio == 3 / 8
    assert profile.out_of_scope_ratio == 1 - 3 / 8


def test_scan_analysis_scope_empty_repo_is_fully_analyzed():
    from collections import Counter

    prof = _bare_profiler()
    profile = ProjectProfile(root=".")
    prof._scan_analysis_scope(profile, Counter())
    assert profile.analyzed_ratio == 1.0
    assert profile.out_of_scope_ratio == 0.0


def test_render_scope_line_empty_when_no_source():
    profile = ProjectProfile(root=".", source_file_count=0)
    assert render_analysis_scope_line(profile) == ""


def test_render_scope_line_empty_when_all_python():
    profile = ProjectProfile(
        root=".", source_file_count=5, python_file_count=5,
        analyzed_ratio=1.0, out_of_scope_ratio=0.0, language_breakdown={},
    )
    assert render_analysis_scope_line(profile) == ""


# --------------------------------------------------------------------------- #
# project_profile.py — confluence threshold + ordering
# --------------------------------------------------------------------------- #

def test_confluence_requires_three_distinct_families():
    prof = _bare_profiler()
    # Module X named by exactly 3 distinct families -> flagged; Y by only 2.
    profile = ProjectProfile(
        root=".",
        dependency_hubs=["X", "Y"],
        symbol_hubs=["X", "Y"],
        fragile_modules=["X"],
    )
    prof._scan_confluences(profile)
    mods = {e["module"] for e in profile.confluence_modules}
    assert "X" in mods
    assert "Y" not in mods
    entry = next(e for e in profile.confluence_modules if e["module"] == "X")
    assert entry["family_count"] == 3
    assert entry["families"] == ("fragile", "hub", "symbol-hub")


def test_confluence_orders_by_family_count_desc_then_module():
    prof = _bare_profiler()
    # A has 4 families, B has 3 -> A first.
    profile = ProjectProfile(
        root=".",
        dependency_hubs=["A", "B"],
        symbol_hubs=["A", "B"],
        fragile_modules=["A", "B"],
        modernizable_modules=["A"],
    )
    prof._scan_confluences(profile)
    order = [e["module"] for e in profile.confluence_modules]
    assert order == ["A", "B"]
    assert profile.confluence_modules[0]["family_count"] == 4


# --------------------------------------------------------------------------- #
# project_profile.py — hub-untested gating
# --------------------------------------------------------------------------- #

class _Node:
    def __init__(self, path, in_degree=0, imports=None):
        self.path = path
        self.in_degree = in_degree
        self.imports = imports or []


def test_hub_untested_requires_fan_in_floor_and_untested():
    prof = _bare_profiler()
    graph = {
        "hub.py": _Node("hub.py", in_degree=3),       # at the floor (>=3)
        "low.py": _Node("low.py", in_degree=2),       # below floor
    }
    out = prof._scan_hub_untested_modules(
        graph, module_to_tests={}, shallow=set(), claimed=set(),
        symbol_counts={"hub.py": 1, "low.py": 1},
    )
    assert out == [{"module": "hub.py", "fan_in": 3}]


def test_hub_untested_skips_claimed_and_empty_shell():
    prof = _bare_profiler()
    graph = {
        "claimed.py": _Node("claimed.py", in_degree=5),
        "empty.py": _Node("empty.py", in_degree=5),
        "real.py": _Node("real.py", in_degree=4),
    }
    out = prof._scan_hub_untested_modules(
        graph, module_to_tests={}, shallow=set(),
        claimed={"claimed.py"},
        symbol_counts={"claimed.py": 9, "empty.py": 0, "real.py": 2},
    )
    # claimed.py framed elsewhere; empty.py has 0 symbols (below MIN_SYMBOLS).
    assert out == [{"module": "real.py", "fan_in": 4}]


def test_hub_untested_skips_modules_with_real_coverage():
    prof = _bare_profiler()
    graph = {"hub.py": _Node("hub.py", in_degree=4)}
    out = prof._scan_hub_untested_modules(
        graph, module_to_tests={"hub.py": ["tests/test_hub.py"]},
        shallow=set(), claimed=set(), symbol_counts={"hub.py": 3},
    )
    assert out == []


# --------------------------------------------------------------------------- #
# project_profile.py — mutable-default / modernizable AST predicates
# --------------------------------------------------------------------------- #

def test_is_mutable_default_detects_literals_and_empty_constructors():
    import ast

    def first_default(src):
        tree = ast.parse(src)
        fn = tree.body[0]
        return fn.args.defaults[0]

    assert ProjectProfiler._is_mutable_default(first_default("def f(x=[]):\n    pass\n"))
    assert ProjectProfiler._is_mutable_default(first_default("def f(x={}):\n    pass\n"))
    assert ProjectProfiler._is_mutable_default(first_default("def f(x=list()):\n    pass\n"))
    # A constructor WITH args is not the empty-mutable case.
    assert not ProjectProfiler._is_mutable_default(first_default("def f(x=list([1])):\n    pass\n"))
    # An immutable default.
    assert not ProjectProfiler._is_mutable_default(first_default("def f(x=()):\n    pass\n"))


def test_is_test_path_predicate_boundaries():
    assert ProjectProfiler._is_test_path("tests/test_x.py") is True
    assert ProjectProfiler._is_test_path("pkg/test_y.py") is True
    assert ProjectProfiler._is_test_path("app/foo/tests/util.py") is True
    assert ProjectProfiler._is_test_path("app/main.py") is False


def test_is_fixture_path_predicate_boundaries():
    assert ProjectProfiler._is_fixture_path("examples/demo.py") is True
    assert ProjectProfiler._is_fixture_path("app/fixtures/x.py") is True
    assert ProjectProfiler._is_fixture_path("app/test_helper.py") is True
    assert ProjectProfiler._is_fixture_path("app/engine/core.py") is False


# --------------------------------------------------------------------------- #
# profile_scanners.py — pure structural helpers
# --------------------------------------------------------------------------- #

def _scanner() -> _CodeQualityScansMixin:
    return _CodeQualityScansMixin()


def test_class_method_count_counts_only_direct_def_children():
    import ast

    src = (
        "class C:\n"
        "    def a(self):\n        pass\n"
        "    async def b(self):\n        pass\n"
        "    x = 1\n"
        "    class Inner:\n"
        "        def nested(self):\n            pass\n"
    )
    cls = ast.parse(src).body[0]
    # a + b only; the nested class's method is NOT counted.
    assert _CodeQualityScansMixin._class_method_count(cls) == 2


def test_class_attr_names_collects_self_targets_excluding_nested_class():
    import ast

    src = (
        "class C:\n"
        "    def __init__(self):\n"
        "        self.a = 1\n"
        "        self.b = 2\n"
        "    class Inner:\n"
        "        def m(self):\n"
        "            self.c = 3\n"
    )
    cls = ast.parse(src).body[0]
    attrs: set[str] = set()
    _CodeQualityScansMixin._class_attr_names(cls, attrs)
    assert attrs == {"a", "b"}


def test_god_classes_in_tree_respects_method_floor():
    import ast

    scanner = _scanner()
    floor = _CodeQualityScansMixin._GOD_CLASS_METHOD_FLOOR
    methods = "\n".join(f"    def m{i}(self):\n        self.x{i} = {i}" for i in range(floor))
    big = ast.parse(f"class Big:\n{methods}\n")
    small_methods = "\n".join(f"    def m{i}(self):\n        pass" for i in range(floor - 1))
    small = ast.parse(f"class Small:\n{small_methods}\n")
    big_out = scanner._god_classes_in_tree(big, "m.py")
    assert big_out and big_out[0]["classname"] == "Big"
    assert big_out[0]["methods"] == floor
    assert big_out[0]["attributes"] == floor
    # One below the floor is not a god-class.
    assert scanner._god_classes_in_tree(small, "m.py") == []


def test_is_stub_body_true_for_pass_or_raise_only():
    import ast

    def fn(src):
        return ast.parse(src).body[0]

    assert _CodeQualityScansMixin._is_stub_body(fn('def f():\n    """doc"""\n    pass\n'))
    assert _CodeQualityScansMixin._is_stub_body(fn("def f():\n    raise NotImplementedError\n"))
    assert not _CodeQualityScansMixin._is_stub_body(fn("def f():\n    return 1\n"))


def test_dead_params_of_excludes_self_underscore_and_read_params():
    import ast

    src = "def f(self, used, _ignored, dead):\n    return used\n"
    fn = ast.parse(src).body[0]
    assert _CodeQualityScansMixin._dead_params_of(fn) == ["dead"]


def test_module_object_refs_excludes_direct_call_targets():
    import ast

    # `helper` is the direct callee of a Call -> NOT an object ref; `cb` travels
    # as a bare object -> IS an object ref.
    tree = ast.parse("helper(cb)\n")
    refs = _CodeQualityScansMixin._module_object_refs(tree)
    assert "cb" in refs
    assert "helper" not in refs


def test_is_execution_scaffold_module_requires_dir_and_marker(tmp_path: Path):
    root = tmp_path
    (root / "app" / "execution").mkdir(parents=True)
    scaffold = root / "app" / "execution" / "bool_return.py"
    scaffold.write_text("from app.execution._transform_base import x\n", encoding="utf-8")
    plain = root / "app" / "execution" / "plain.py"
    plain.write_text("y = 1\n", encoding="utf-8")
    (root / "app" / "execution" / "objectives").mkdir()
    nested = root / "app" / "execution" / "objectives" / "deep.py"
    nested.write_text("from app.execution._transform_base import x\n", encoding="utf-8")

    scanner = ProjectProfiler(str(root))
    assert scanner._is_execution_scaffold_module("app/execution/bool_return.py") is True
    # Right dir, no scaffold marker.
    assert scanner._is_execution_scaffold_module("app/execution/plain.py") is False
    # Marker present but nested (not the flat scaffold level).
    assert scanner._is_execution_scaffold_module("app/execution/objectives/deep.py") is False
    # Wrong directory entirely.
    assert scanner._is_execution_scaffold_module("app/tools/foo.py") is False


def test_coordinator_modules_fan_out_floor_and_ordering():
    scanner = ProjectProfiler(".")
    floor = _CodeQualityScansMixin._COORDINATOR_FAN_OUT_FLOOR
    big_imports = [f"dep{i}.py" for i in range(floor + 1)]
    mid_imports = [f"dep{i}.py" for i in range(floor)]
    graph = {
        "big.py": _Node("big.py", in_degree=0, imports=big_imports),
        "mid.py": _Node("mid.py", in_degree=0, imports=mid_imports),
        "small.py": _Node("small.py", in_degree=0, imports=["dep0.py"]),
    }
    scanner._dependency_graph = graph
    profile = ProjectProfile(root=".")
    scanner._scan_coordinator_modules(profile)
    mods = [e["module"] for e in profile.coordinator_modules]
    # small.py below the fan-out floor is excluded; widest fan-out first.
    assert mods == ["big.py", "mid.py"]
    assert profile.coordinator_modules[0]["fan_out"] == floor + 1


def test_god_classes_scan_is_sorted_and_capped(tmp_path: Path):
    root = tmp_path
    (root / "app").mkdir()
    floor = _CodeQualityScansMixin._GOD_CLASS_METHOD_FLOOR
    # Two god-classes with different method counts -> sorted -methods first.
    big = "\n".join(f"    def m{i}(self):\n        pass" for i in range(floor + 2))
    small = "\n".join(f"    def m{i}(self):\n        pass" for i in range(floor))
    (root / "app" / "big.py").write_text(f"class Big:\n{big}\n", encoding="utf-8")
    (root / "app" / "small.py").write_text(f"class Small:\n{small}\n", encoding="utf-8")
    profile = ProjectProfile(root=str(root))
    ProjectProfiler(str(root))._scan_god_classes(profile)
    names = [e["classname"] for e in profile.god_classes]
    assert names[0] == "Big"  # more methods ranks first
    assert "Small" in names


def test_deeply_nested_functions_respects_depth_floor(tmp_path: Path):
    root = tmp_path
    (root / "app").mkdir()
    floor = _CodeQualityScansMixin._DEEP_NESTING_FLOOR
    # Build a function nested exactly `floor` deep with if-statements.
    lines = ["def deep():"]
    for i in range(floor):
        lines.append("    " * (i + 1) + "if True:")
    lines.append("    " * (floor + 1) + "pass")
    (root / "app" / "deep.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # A shallow function (one level) must not be flagged.
    (root / "app" / "flat.py").write_text(
        "def flat():\n    if True:\n        return 1\n", encoding="utf-8"
    )
    profile = ProjectProfile(root=str(root))
    ProjectProfiler(str(root))._scan_deeply_nested_functions(profile)
    flagged = {e["function"] for e in profile.deeply_nested_functions}
    assert "deep" in flagged
    assert "flat" not in flagged
    entry = next(e for e in profile.deeply_nested_functions if e["function"] == "deep")
    assert entry["depth"] == floor


def test_dead_params_scan_flags_unique_named_unused_param(tmp_path: Path):
    root = tmp_path
    (root / "app").mkdir()
    # A uniquely-named, undecorated, real-bodied function with an unused param.
    (root / "app" / "m.py").write_text(
        "def uniquely_named_fn(used, dead):\n    return used + 1\n", encoding="utf-8"
    )
    profile = ProjectProfile(root=str(root))
    ProjectProfiler(str(root))._scan_dead_params(profile)
    flagged = [(e["function"], e["param"]) for e in profile.dead_params]
    assert ("uniquely_named_fn", "dead") in flagged
    assert all(p != "used" for _f, p in flagged)


def test_dead_params_scan_skips_decorated_and_duplicate_named(tmp_path: Path):
    root = tmp_path
    (root / "app").mkdir()
    # Decorated function -> framework may impose signature -> never flagged.
    (root / "app" / "deco.py").write_text(
        "import functools\n"
        "@functools.cache\n"
        "def decorated_unique(used, dead):\n    return used\n",
        encoding="utf-8",
    )
    # Same NAME in two modules -> interface family -> never flagged.
    (root / "app" / "a.py").write_text(
        "def shared_iface(used, dead):\n    return used\n", encoding="utf-8"
    )
    (root / "app" / "b.py").write_text(
        "def shared_iface(used, dead):\n    return dead\n", encoding="utf-8"
    )
    profile = ProjectProfile(root=str(root))
    ProjectProfiler(str(root))._scan_dead_params(profile)
    names = {e["function"] for e in profile.dead_params}
    assert "decorated_unique" not in names
    assert "shared_iface" not in names


def test_dead_params_scan_caps_at_five(tmp_path: Path):
    root = tmp_path
    (root / "app").mkdir()
    # Seven uniquely-named functions each with a dead param -> capped to 5.
    for i in range(7):
        (root / "app" / f"m{i}.py").write_text(
            f"def fn_unique_{i}(used, dead):\n    return used\n", encoding="utf-8"
        )
    profile = ProjectProfile(root=str(root))
    ProjectProfiler(str(root))._scan_dead_params(profile)
    assert len(profile.dead_params) == 5


def test_god_classes_scan_caps_at_five(tmp_path: Path):
    root = tmp_path
    (root / "app").mkdir()
    floor = _CodeQualityScansMixin._GOD_CLASS_METHOD_FLOOR
    methods = "\n".join(f"    def m{i}(self):\n        pass" for i in range(floor))
    for c in range(7):
        (root / "app" / f"c{c}.py").write_text(
            f"class God{c}:\n{methods}\n", encoding="utf-8"
        )
    profile = ProjectProfile(root=str(root))
    ProjectProfiler(str(root))._scan_god_classes(profile)
    assert len(profile.god_classes) == 5


def test_coordinator_scan_caps_at_five():
    floor = _CodeQualityScansMixin._COORDINATOR_FAN_OUT_FLOOR
    graph = {
        f"m{i}.py": _Node(f"m{i}.py", in_degree=0,
                          imports=[f"d{j}.py" for j in range(floor)])
        for i in range(7)
    }
    scanner = ProjectProfiler(".")
    scanner._dependency_graph = graph
    profile = ProjectProfile(root=".")
    scanner._scan_coordinator_modules(profile)
    assert len(profile.coordinator_modules) == 5


def test_coordinator_top_imports_ranked_by_target_fan_in():
    floor = _CodeQualityScansMixin._COORDINATOR_FAN_OUT_FLOOR
    imports = [f"dep{i}.py" for i in range(floor)]
    graph = {"god.py": _Node("god.py", in_degree=0, imports=imports)}
    # Give dep0 the highest in-degree so it ranks first in top imports.
    for i, name in enumerate(imports):
        graph[name] = _Node(name, in_degree=(floor - i))
    scanner = ProjectProfiler(".")
    scanner._dependency_graph = graph
    profile = ProjectProfile(root=".")
    scanner._scan_coordinator_modules(profile)
    top = profile.coordinator_modules[0]["imports"]
    assert top == ["dep0.py", "dep1.py", "dep2.py"]


def test_inlinable_helpers_excludes_fixture_paths(tmp_path: Path):
    root = tmp_path
    (root / "app").mkdir()
    (root / "tests").mkdir()
    # Real single-use helper -> flagged; identical one under tests/ -> excluded.
    (root / "app" / "calc.py").write_text(
        "def fee(x):\n    return x * 2\n\n\ndef total(p):\n    return fee(p) + 1\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_calc.py").write_text(
        "def fee_helper(x):\n    return x * 2\n\n\ndef total(p):\n    return fee_helper(p)\n",
        encoding="utf-8",
    )
    profile = ProjectProfile(root=str(root))
    ProjectProfiler(str(root))._scan_inlinable_helpers(profile)
    modules = {e["module"] for e in profile.inlinable_helpers}
    assert all(not m.startswith("tests/") for m in modules)
    assert "app/calc.py" in modules
