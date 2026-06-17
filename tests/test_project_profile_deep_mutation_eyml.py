"""Deep mutation-hardening pins for ``app/tools/project_profile.py``.

The default ``apex mutants --max-mutants 30`` cap stops enumeration at the
first 30 mutation sites in document order — yet this 1942-line module seeds
389 sites, so 359 of them live *past* the cap and are never exercised by the
standard run. This battery enumerates that full universe (via the engine's own
``_collect_sites``) and pins the load-bearing thresholds, boundaries, sort
keys, filter predicates, and pure helpers that survive deep into the file —
the blind spots no default mutation run reaches.

Every assertion targets an exact value, boundary, or ordering. Nothing depends
on a wall clock, set/dict iteration order, or real git history (the few
git-shaped scans are driven through their pure parse/tally helpers with
synthetic input), so the pins are deterministic and reproducible.

Style mirrors ``test_tools_profile_mutation_hardening_eyml.py``: direct calls
to the pure helpers and tight value assertions, no broad-suite dependency.
"""
from __future__ import annotations

import re
import types
from collections import Counter
from pathlib import Path

from app.tools.dependency_graph import DependencyGraphBuilder
from app.tools.project_profile import (
    ProjectProfile,
    ProjectProfiler,
    render_analysis_scope_line,
)
from app.tools.python_structure import PythonStructureAnalyzer


def _profiler(root: str | Path = ".") -> ProjectProfiler:
    return ProjectProfiler(str(root))


# --------------------------------------------------------------------------- #
# Base walk: max_files cap and per-top-directory tally (L412, L419, L427).
# --------------------------------------------------------------------------- #

def test_default_max_files_is_two_thousand():
    """The default scan ceiling is 2000 files (L341 ``max_files: int = 2000``)."""
    assert ProjectProfiler(".").max_files == 2000


def test_walk_respects_max_files_cap(tmp_path: Path):
    """The walk stops once ``scanned`` reaches ``max_files`` (L410 ``scanned = 0``,
    L412 ``scanned >= self.max_files``, L419 ``scanned += 1``)."""
    (tmp_path / "app").mkdir()
    for i in range(5):
        (tmp_path / "app" / f"f{i}.py").write_text("x = 1\n", encoding="utf-8")
    profile = _profiler(tmp_path)
    profile.max_files = 3
    result = profile.profile()
    assert result.total_files == 3


def test_top_directories_tally_uses_first_path_component(tmp_path: Path):
    """Directory tallies key on the FIRST path component (L427 ``rel.parts[0]``)."""
    (tmp_path / "pkg").mkdir()
    for i in range(3):
        (tmp_path / "pkg" / f"f{i}.py").write_text("x = 1\n", encoding="utf-8")
    result = _profiler(tmp_path).profile()
    assert result.top_directories == ["pkg"]


# --------------------------------------------------------------------------- #
# ProjectProfile dataclass scope defaults (L141, L142, L144, L145).
# A non-existent root makes ``profile()`` return early, BEFORE
# ``_scan_analysis_scope`` overwrites them — so the defaults are observable and
# a ``0 -> 1`` / ``1.0 -> 2.0`` / ``0.0 -> 1.0`` mutation of any default is caught.
# --------------------------------------------------------------------------- #

def test_scope_field_defaults_on_missing_root():
    profile = _profiler("/tmp/apex_no_such_dir_eyml_42").profile()
    assert profile.source_file_count == 0
    assert profile.python_file_count == 0
    assert profile.analyzed_ratio == 1.0
    assert profile.out_of_scope_ratio == 0.0


def test_profile_dataclass_constructs_with_zero_defaults():
    profile = ProjectProfile(root="x")
    assert profile.total_files == 0
    assert profile.source_file_count == 0
    assert profile.python_file_count == 0
    assert profile.analyzed_ratio == 1.0
    assert profile.out_of_scope_ratio == 0.0


# --------------------------------------------------------------------------- #
# _parse_churn_commits / _tally_churn — pure git-log parsing.
# --------------------------------------------------------------------------- #

def test_tally_churn_pair_window_lower_bound(tmp_path: Path):
    """A single-file commit yields NO co-change pair (L1016 ``2 <= len``).

    Flipping ``<=`` to ``<`` on the lower bound would let a 1-file commit
    through ``combinations(..., 2)`` (empty) silently; the boundary that matters
    is that 2 files DO couple and 1 file does not.
    """
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    one = [("Al", ["a.py"])]
    two = [("Al", ["a.py", "b.py"])]
    _c1, pairs1, _a1 = prof._tally_churn(one)
    _c2, pairs2, _a2 = prof._tally_churn(two)
    assert pairs1 == {}
    assert pairs2 == {("a.py", "b.py"): 1}


def test_tally_churn_excludes_mega_commit_at_upper_bound(tmp_path: Path):
    """A commit of exactly MAX_COMMIT_FILES (15) files still couples; 16 does not
    (L1016 ``<= self.MAX_COMMIT_FILES``)."""
    names = [f"m{i}.py" for i in range(16)]
    for n in names:
        (tmp_path / n).write_text("v = 0\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    fifteen = [("Al", names[:15])]
    sixteen = [("Al", names[:16])]
    _c, pairs15, _a = prof._tally_churn(fifteen)
    _c2, pairs16, _a2 = prof._tally_churn(sixteen)
    assert pairs15  # 15 files -> pairs recorded
    assert pairs16 == {}  # 16 files -> mega-commit, skipped


# --------------------------------------------------------------------------- #
# _build_knowledge_risks — bus-factor thresholds (L1037, L1041, L1045).
# --------------------------------------------------------------------------- #

def _two_author_commits() -> list[tuple[str, list[str]]]:
    return [("Alice", ["x"])] * 5 + [("Bob", ["x"])] * 5


def test_knowledge_risk_min_commits_is_inclusive():
    """A module with EXACTLY KNOWLEDGE_MIN_COMMITS (5) touches is kept
    (L1037 ``total < self.KNOWLEDGE_MIN_COMMITS`` — ``<`` not ``<=``)."""
    prof = _profiler(".")
    touches = {"app/y.py": Counter({"Alice": 5})}
    risks = prof._build_knowledge_risks(_two_author_commits(), touches)
    assert risks == [{"module": "app/y.py", "share": 100, "commits": 5}]


def test_knowledge_risk_share_threshold_is_inclusive():
    """A top-author share of EXACTLY 0.85 is flagged (L1041 ``share >=
    self.KNOWLEDGE_SHARE``); 0.80 is not."""
    prof = _profiler(".")
    at_85 = {"app/z.py": Counter({"Alice": 17, "Bob": 3})}   # 17/20 == 0.85
    at_80 = {"app/z.py": Counter({"Alice": 16, "Bob": 4})}   # 16/20 == 0.80
    kept = prof._build_knowledge_risks(_two_author_commits(), at_85)
    dropped = prof._build_knowledge_risks(_two_author_commits(), at_80)
    assert kept == [{"module": "app/z.py", "share": 85, "commits": 20}]
    assert dropped == []


def test_knowledge_risks_capped_at_five():
    """Only the top 5 risk modules are returned (L1045 ``risks[:5]``)."""
    prof = _profiler(".")
    touches = {
        f"app/m{i}.py": Counter({"Alice": 10 - i, "Bob": 0}) for i in range(7)
    }
    risks = prof._build_knowledge_risks(_two_author_commits(), touches)
    assert len(risks) == 5
    # widest concentration first: m0 (share 100, 10 commits) leads.
    assert risks[0]["module"] == "app/m0.py"


# --------------------------------------------------------------------------- #
# _oldest_debt_ctime — committer-time scan (L926 ``and``).
# --------------------------------------------------------------------------- #

def test_oldest_debt_ctime_picks_minimum_committer_time():
    debt_re = re.compile(r"#\s*(TODO|FIXME)\b", re.IGNORECASE)
    blame = (
        "committer-time 1000\n"
        "\t# TODO old\n"
        "committer-time 5000\n"
        "\t# FIXME newer\n"
        "committer-time 3000\n"
        "\tclean line\n"
    )
    assert ProjectProfiler._oldest_debt_ctime(blame, debt_re) == 1000


def test_oldest_debt_ctime_ignores_non_tab_marker_lines():
    """The marker must be on a ``\\t``-prefixed content line (L926 ``and``).

    A ``# TODO`` that is NOT a porcelain content line (no leading tab) must not
    register a ctime, so flipping the ``and`` joining the two guards is caught.
    """
    debt_re = re.compile(r"#\s*(TODO|FIXME)\b", re.IGNORECASE)
    blame = (
        "committer-time 1000\n"
        "summary # TODO not-a-content-line\n"  # no leading tab
    )
    assert ProjectProfiler._oldest_debt_ctime(blame, debt_re) is None


# --------------------------------------------------------------------------- #
# render_analysis_scope_line — boundary guards (L1917, L1919, L1921).
# --------------------------------------------------------------------------- #

def _scope_profile(**kw) -> ProjectProfile:
    profile = ProjectProfile(root="r")
    for key, value in kw.items():
        setattr(profile, key, value)
    return profile


def test_scope_line_empty_when_no_source_files():
    """``source_file_count == 0`` yields no line even with out-of-scope content
    set (L1917 ``<= 0`` — the boundary that swallows the zero case)."""
    profile = _scope_profile(
        source_file_count=0, out_of_scope_ratio=0.4,
        language_breakdown={"JavaScript": 3},
    )
    assert render_analysis_scope_line(profile) == ""


def test_scope_line_emitted_for_one_source_file():
    """A single out-of-scope source file (count == 1) still emits the line
    (L1917 number ``0`` — ``<= 0`` must not become ``<= 1``)."""
    profile = _scope_profile(
        source_file_count=1, python_file_count=0,
        analyzed_ratio=0.0, out_of_scope_ratio=1.0,
        language_breakdown={"JavaScript": 1},
    )
    line = render_analysis_scope_line(profile)
    assert line.startswith("Scope: analysing 0% of the repo")


def test_scope_line_empty_when_all_python():
    """All-Python (out_of_scope_ratio == 0) yields no line (L1919 ``> 0`` — the
    grade already speaks for the whole repo)."""
    profile = _scope_profile(
        source_file_count=4, python_file_count=4,
        analyzed_ratio=1.0, out_of_scope_ratio=0.0,
        language_breakdown={"JavaScript": 0},
    )
    assert render_analysis_scope_line(profile) == ""


def test_scope_line_empty_when_breakdown_missing():
    """Out-of-scope ratio > 0 but an EMPTY breakdown yields no line (L1919
    ``and`` — both conditions must hold)."""
    profile = _scope_profile(
        source_file_count=4, python_file_count=2,
        analyzed_ratio=0.5, out_of_scope_ratio=0.5,
        language_breakdown={},
    )
    assert render_analysis_scope_line(profile) == ""


def test_scope_line_percentage_uses_hundred_scale():
    """The percentage is ``round(ratio * 100)`` (L1921 number ``100``)."""
    profile = _scope_profile(
        source_file_count=10, python_file_count=6,
        analyzed_ratio=0.6, out_of_scope_ratio=0.4,
        language_breakdown={"JavaScript": 3, "CSS": 1},
    )
    line = render_analysis_scope_line(profile)
    assert "analysing 60% of the repo" in line
    assert "40% is outside analysis scope" in line
    # first language carries the " files" unit, the rest are bare counts.
    assert "JavaScript 3 files" in line
    assert "CSS 1." in line


# --------------------------------------------------------------------------- #
# Base walk classification + finalize caps, driven through ``profile()``.
# --------------------------------------------------------------------------- #

def test_ci_files_require_github_and_workflows(tmp_path: Path):
    """A CI file is one under ``.github`` AND ``workflows`` (L470 ``and``).

    A ``.github`` file outside ``workflows`` and a ``workflows`` file outside
    ``.github`` must BOTH be excluded; only the path carrying both tokens counts.
    """
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("x\n", encoding="utf-8")
    (tmp_path / ".github" / "other.yml").write_text("x\n", encoding="utf-8")
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "w.yml").write_text("x\n", encoding="utf-8")
    profile = _profiler(tmp_path).profile()
    cis = [Path(p).as_posix() for p in profile.ci_files]
    assert cis == [".github/workflows/ci.yml"]


def test_non_python_file_is_not_debt_scanned(tmp_path: Path):
    """Debt scanning skips non-``.py`` files (L487 ``or`` — the skip guard).

    A markdown file with three debt markers must NOT be flagged; flipping the
    ``ext != ".py" or is_test`` skip to ``and`` would scan it as code.
    """
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "notes.md").write_text(
        "# TODO a\n# FIXME b\n# XXX c\n", encoding="utf-8")
    (tmp_path / "app" / "real.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    profile = _profiler(tmp_path).profile()
    flagged = [Path(p).as_posix() for p in profile.debt_marker_modules]
    assert "app/notes.md" not in flagged


def test_debt_marker_threshold_is_three(tmp_path: Path):
    """A module needs >= DEBT_MARKER_THRESHOLD (3) markers to be flagged
    (L280/L523); exactly two is below the bar."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "three.py").write_text(
        "# TODO a\n# FIXME b\n# XXX c\ndef f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "app" / "two.py").write_text(
        "# TODO a\n# FIXME b\ndef f():\n    return 1\n", encoding="utf-8")
    profile = _profiler(tmp_path).profile()
    flagged = [Path(p).as_posix() for p in profile.debt_marker_modules]
    assert "app/three.py" in flagged
    assert "app/two.py" not in flagged


def test_churn_threshold_is_three(tmp_path: Path):
    """A module needs >= CHURN_THRESHOLD (3) recent commits to be a hotspot
    (L285/L952). Driven through a synthetic git-log so it stays deterministic
    (no real history); the .py files must exist on disk for the walk's
    ``(self.root / rel).exists()`` filter."""
    (tmp_path / "app").mkdir()
    for module in ("app/hot.py", "app/cool.py"):
        (tmp_path / module).write_text("def f():\n    return 1\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    log = "@commit@Al\napp/hot.py\n" * 3 + "@commit@Bo\napp/cool.py\n" * 2
    prof._run_churn_git = lambda: log
    profile = ProjectProfile(root=str(tmp_path))
    prof._scan_churn(profile)
    hot = {h["module"]: h["commits"] for h in profile.churn_hotspots}
    # exactly-3-commit module is a hotspot; the 2-commit module is not.
    assert hot.get("app/hot.py") == 3
    assert "app/cool.py" not in hot


def test_churn_hotspots_capped_and_tie_broken(tmp_path: Path):
    """Churn hotspots cap at five and tie-break alphabetically (L951 ``[:5]``
    and the ``(-kv[1], kv[0])`` sort key)."""
    (tmp_path / "app").mkdir()
    # Insert m1 BEFORE m0 in the log so the sort key's tie-break (not insertion
    # order) is what orders the tied pair: mutating ``kv[0]`` -> ``kv[1]`` makes
    # the key tie completely and a stable sort would leak m1 ahead of m0.
    counts = {"app/m1.py": 6, "app/m0.py": 6, "app/m2.py": 5, "app/m3.py": 4,
              "app/m4.py": 4, "app/m5.py": 3, "app/m6.py": 3}
    for module in counts:
        (tmp_path / module).write_text("def f():\n    return 1\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    log = ""
    for module, count in counts.items():
        log += f"@commit@Al\n{module}\n" * count
    prof._run_churn_git = lambda: log
    profile = ProjectProfile(root=str(tmp_path))
    prof._scan_churn(profile)
    assert len(profile.churn_hotspots) == 5
    # tie at 6 commits breaks alphabetically (m0 before m1), NOT by log order.
    assert profile.churn_hotspots[0]["module"] == "app/m0.py"
    assert profile.churn_hotspots[1]["module"] == "app/m1.py"


def test_cochange_threshold_is_three(tmp_path: Path):
    """A module pair needs >= COCHANGE_THRESHOLD (3) shared commits to couple
    (L289/L957)."""
    (tmp_path / "app").mkdir()
    files = [f"app/f{i}.py" for i in range(9)]
    for f in files:
        (tmp_path / f).write_text("def g():\n    return 1\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    # Below-bar pair (2 commits) plus seven >= 3 pairs, two tied at 5.
    pair_commits = [
        (("app/f0.py", "app/f1.py"), 2),   # below threshold
        (("app/f2.py", "app/f4.py"), 5),   # tie B, listed FIRST in the log
        (("app/f2.py", "app/f3.py"), 5),   # tie A (f3 < f4 -> A must sort first)
        (("app/f5.py", "app/f6.py"), 4),
        (("app/f0.py", "app/f7.py"), 4),
        (("app/f1.py", "app/f8.py"), 3),
        (("app/f3.py", "app/f5.py"), 3),
        (("app/f4.py", "app/f6.py"), 3),
    ]
    log = ""
    for (a, b), n in pair_commits:
        log += f"@commit@Al\n{a}\n{b}\n" * n
    prof._run_churn_git = lambda: log
    profile = ProjectProfile(root=str(tmp_path))
    prof._scan_churn(profile)
    pairs = {(c["a"], c["b"]): c["commits"] for c in profile.change_coupling}
    # exactly-3-commit pair couples; 2-commit pair does not.
    assert pairs.get(("app/f1.py", "app/f8.py")) == 3
    assert ("app/f0.py", "app/f1.py") not in pairs
    # capped at five (L956 ``[:5]``).
    assert len(profile.change_coupling) == 5
    # tie at 5 breaks by pair asc: (f2,f3) before (f2,f4) (L956 sort key).
    assert (profile.change_coupling[0]["a"], profile.change_coupling[0]["b"]) == (
        "app/f2.py", "app/f3.py")
    assert (profile.change_coupling[1]["a"], profile.change_coupling[1]["b"]) == (
        "app/f2.py", "app/f4.py")


def test_security_finding_modules_capped_at_five(tmp_path: Path):
    """At most five security-finding modules surface (L516 ``[:5]``)."""
    (tmp_path / "app").mkdir()
    for i in range(7):
        (tmp_path / "app" / f"s{i}.py").write_text(
            'def f():\n    eval("1")\n    return 1\n', encoding="utf-8")
    profile = _profiler(tmp_path).profile()
    assert len(profile.security_finding_modules) == 5


def test_correctness_bug_modules_capped_at_five(tmp_path: Path):
    """At most five correctness-bug modules surface (L517 ``[:5]``)."""
    (tmp_path / "app").mkdir()
    for i in range(7):
        (tmp_path / "app" / f"bug{i}.py").write_text(
            f"def f{i}():\n    try:\n        return 1\n    finally:\n        return 2\n",
            encoding="utf-8")
    profile = _profiler(tmp_path).profile()
    assert len(profile.correctness_bug_modules) == 5


def test_debt_marker_modules_capped_at_five(tmp_path: Path):
    """At most five debt-marker modules surface (L527 ``[:5]``)."""
    (tmp_path / "app").mkdir()
    for i in range(7):
        (tmp_path / "app" / f"d{i}.py").write_text(
            "# TODO a\n# FIXME b\n# XXX c\n" + "# HACK\n" * (7 - i)
            + "def f():\n    return 1\n", encoding="utf-8")
    profile = _profiler(tmp_path).profile()
    assert len(profile.debt_marker_modules) == 5


# --------------------------------------------------------------------------- #
# Dependency-graph structure: fan-in / fragility / symbol-hub caps.
# --------------------------------------------------------------------------- #

def _graph_tree(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    # A hub imported by exactly two modules (the fragility floor), untested.
    (tmp_path / "app" / "hub2.py").write_text("def h2():\n    return 1\n", encoding="utf-8")
    (tmp_path / "app" / "i0.py").write_text(
        "from app.hub2 import h2\ndef a():\n    return h2()\n", encoding="utf-8")
    (tmp_path / "app" / "i1.py").write_text(
        "from app.hub2 import h2\ndef b():\n    return h2()\n", encoding="utf-8")
    # Seven symbol-bearing modules so the symbol-hub list overflows its cap.
    for i in range(7):
        body = "\n".join(f"def s{i}_{j}():\n    return {j}" for j in range(3))
        (tmp_path / "app" / f"mod{i}.py").write_text(body + "\n", encoding="utf-8")


def test_fragile_module_fan_in_floor_is_two(tmp_path: Path):
    """A module is fragile when its fan-in reaches 2 and it is thinly tested
    (L1214 ``in_degree >= 2``). The two-importer hub qualifies."""
    _graph_tree(tmp_path)
    profile = _profiler(tmp_path).profile()
    fragile = [Path(p).as_posix() for p in profile.fragile_modules]
    assert "app/hub2.py" in fragile


def test_module_fanin_counts_two_importers(tmp_path: Path):
    """Fan-in is the in-degree, recorded for any module with importers
    (L1200 ``in_degree > 0``)."""
    _graph_tree(tmp_path)
    profile = _profiler(tmp_path).profile()
    fanin = {Path(k).as_posix(): v for k, v in profile.module_fanin.items()}
    assert fanin.get("app/hub2.py") == 2


def test_symbol_hubs_capped_at_five(tmp_path: Path):
    """At most five symbol hubs surface (L1171 ``[:5]``)."""
    _graph_tree(tmp_path)
    profile = _profiler(tmp_path).profile()
    assert len(profile.symbol_hubs) == 5


def test_symbol_hubs_require_at_least_one_symbol(tmp_path: Path):
    """A module with zero defined symbols is not a symbol hub (L1171
    ``len(m.symbols) > 0``). An empty ``__init__.py`` is excluded."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")  # 0 symbols
    (tmp_path / "app" / "real.py").write_text(
        "def f():\n    return 1\n", encoding="utf-8")
    profile = _profiler(tmp_path).profile()
    hubs = [Path(p).as_posix() for p in profile.symbol_hubs]
    assert "app/__init__.py" not in hubs
    assert "app/real.py" in hubs


def test_prepare_impure_module_skips_test_paths(tmp_path: Path):
    """``_prepare_impure_module`` skips non-``.py`` and test paths (L1458 ``or``);
    a real module yields its (source, functions) pair."""
    from app.tools.function_fractal_analyzer import FunctionFractalAnalyzer

    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        'import os\ndef f():\n    os.system("x")\n    return 1\n', encoding="utf-8")
    (tmp_path / "app" / "m.py").write_text(
        'import os\ndef f():\n    os.system("x")\n    return 1\n', encoding="utf-8")
    prof = _profiler(tmp_path)
    analyzer = FunctionFractalAnalyzer()
    assert prof._prepare_impure_module("tests/test_x.py", analyzer) is None
    assert prof._prepare_impure_module("app/x.txt", analyzer) is None
    real = prof._prepare_impure_module("app/m.py", analyzer)
    assert real is not None and len(real) == 2


def test_modernizable_and_mutable_default_modules_capped_at_five(tmp_path: Path):
    """Both refactor-candidate lists cap at five (L1222, L1223 ``[:5]``)."""
    (tmp_path / "app").mkdir()
    for i in range(7):
        (tmp_path / "app" / f"mod{i}.py").write_text(
            f"def f{i}(x):\n    return x == None\n", encoding="utf-8")
        (tmp_path / "app" / f"mut{i}.py").write_text(
            f"def g{i}(x=[]):\n    return x\n", encoding="utf-8")
    profile = _profiler(tmp_path).profile()
    assert len(profile.modernizable_modules) == 5
    assert len(profile.mutable_default_modules) == 5


def test_dependency_hubs_capped_at_five(tmp_path: Path):
    """Dependency hubs are limited to five (L1164 ``limit=5``)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    for h in range(7):
        (tmp_path / "app" / f"hub{h}.py").write_text(
            f"def fn{h}():\n    return {h}\n", encoding="utf-8")
        for c in range(3):
            (tmp_path / "app" / f"c{h}_{c}.py").write_text(
                f"from app.hub{h} import fn{h}\ndef u():\n    return fn{h}()\n",
                encoding="utf-8")
    profile = _profiler(tmp_path).profile()
    assert len(profile.dependency_hubs) == 5


def test_module_fanout_ranked_by_target_fanin_and_capped(tmp_path: Path):
    """A module's heaviest fan-out targets are its imports ranked by the
    target's own fan-in (L1206 sort key), capped at three (L1208 ``[:3]``)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    deps = [f"d{i}" for i in range(5)]
    for d in deps:
        (tmp_path / "app" / f"{d}.py").write_text(
            f"def {d}():\n    return 1\n", encoding="utf-8")
    imports = "\n".join(f"from app.{d} import {d}" for d in deps)
    (tmp_path / "app" / "coord.py").write_text(
        imports + "\ndef c():\n    return 1\n", encoding="utf-8")
    # Make d0 a hub so it sorts to the front of coord's fan-out (highest fan-in).
    for i in range(3):
        (tmp_path / "app" / f"x{i}.py").write_text(
            "from app.d0 import d0\ndef f():\n    return d0()\n", encoding="utf-8")
    profile = _profiler(tmp_path).profile()
    fanout = {Path(k).as_posix(): [Path(t).as_posix() for t in v]
              for k, v in profile.module_fanout.items()}
    coord = fanout.get("app/coord.py")
    assert coord is not None
    assert len(coord) == 3                      # capped at three
    assert coord[0] == "app/d0.py"              # most-depended-on target first


# --------------------------------------------------------------------------- #
# Doc-drift cap + Apex-report head slice (L822, L741).
# --------------------------------------------------------------------------- #

def test_doc_drift_capped_at_five(tmp_path: Path):
    """At most five doc-drift references surface (L822 ``len(drift) >= 5``)."""
    refs = "\n".join(f"See `app/missing{i}.py`." for i in range(7))
    (tmp_path / "README.md").write_text(refs + "\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    profile = ProjectProfile(root=str(tmp_path))
    prof._scan_doc_drift(profile)
    assert len(profile.doc_drift) == 5


def test_apex_report_marker_read_within_first_2000_chars(tmp_path: Path):
    """The Apex-report marker is sought only in the first 2000 chars
    (L741 ``[:2000]``). A marker whose last char lands at index 2000 is missed
    by the 2000-slice but caught by a 2001-slice — pinning the exact bound."""
    marker = "<title>Apex Idea Tree</title>"
    prefix = "x" * (2001 - len(marker))
    (tmp_path / "edge.html").write_text(prefix + marker + "yyy", encoding="utf-8")
    # A marker comfortably inside the window is detected (control).
    (tmp_path / "near.html").write_text("z" * 100 + marker, encoding="utf-8")
    prof = _profiler(tmp_path)
    assert prof._is_apex_report("near.html") is True
    assert prof._is_apex_report("edge.html") is False


def test_polyglot_hotspots_capped_at_three(tmp_path: Path):
    """At most three polyglot hotspots surface (L693 ``len(hotspots) >= 3``)."""
    (tmp_path / "web").mkdir()
    for i in range(5):
        (tmp_path / "web" / f"f{i}.js").write_text(
            "function a(){ return 1 }\n" * (20 - i * 2), encoding="utf-8")
    prof = _profiler(tmp_path)
    profile = ProjectProfile(root=str(tmp_path))
    prof._scan_polyglot_hotspots(profile)
    assert len(profile.polyglot_hotspots) == 3


def test_doc_drift_files_capped_at_ten(tmp_path: Path):
    """At most ten doc files are scanned for drift (L762 ``[:10]``)."""
    (tmp_path / "README.md").write_text("readme\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    for i in range(12):
        (tmp_path / "docs" / f"d{i:02d}.md").write_text("doc\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    assert len(prof._doc_drift_files()) == 10


# --------------------------------------------------------------------------- #
# _scan_hotspot_functions — complexity floor, dunder skip, cap (directly).
# --------------------------------------------------------------------------- #

def _branchy_body(n: int) -> str:
    return "\n".join(f"    if x == {i}:\n        return {i}" for i in range(n))


def test_hotspot_function_complexity_floor_is_eight(tmp_path: Path):
    """A function is a hotspot only at complexity >= 8 (L1403 ``< 8`` and the
    literal ``8``); complexity 7 is below the bar."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "hot.py").write_text(
        f"def cx(x):\n{_branchy_body(8)}\n    return -1\n", encoding="utf-8")
    (tmp_path / "app" / "low.py").write_text(
        f"def low(x):\n{_branchy_body(6)}\n    return -1\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    hot = prof._scan_hotspot_functions(["app/hot.py"], {"app/hot.py": []})
    low = prof._scan_hotspot_functions(["app/low.py"], {"app/low.py": []})
    assert [(d["function"], d["complexity"]) for d in hot] == [("cx", 8)]
    assert low == []


def test_hotspot_function_skips_only_full_dunder_names(tmp_path: Path):
    """The dunder skip needs BOTH leading and trailing ``__`` (L1406 ``and``).

    ``__foo`` (leading only) is a real private function and IS flagged; flipping
    the ``and`` to ``or`` would wrongly skip it.
    """
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        f"def __foo(x):\n{_branchy_body(8)}\n    return -1\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    out = prof._scan_hotspot_functions(["app/m.py"], {"app/m.py": []})
    assert [d["function"] for d in out] == ["__foo"]


def test_hotspot_functions_skip_test_path_modules(tmp_path: Path):
    """A test-path module is excluded from the hotspot-function scan
    (L1388 ``not module.endswith(".py") or self._is_test_path(module)``)."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_complex.py").write_text(
        f"def cx(x):\n{_branchy_body(8)}\n    return -1\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    out = prof._scan_hotspot_functions(
        ["tests/test_complex.py"], {"tests/test_complex.py": []})
    assert out == []


def test_hotspot_functions_capped_at_five(tmp_path: Path):
    """At most five hotspot functions are returned (L1414 ``[:5]``)."""
    (tmp_path / "app").mkdir()
    funcs = "\n\n".join(
        f"def f{i}(x):\n{_branchy_body(8 + i)}\n    return -1" for i in range(7)
    )
    (tmp_path / "app" / "many.py").write_text(funcs + "\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    out = prof._scan_hotspot_functions(["app/many.py"], {"app/many.py": []})
    assert len(out) == 5
    # highest complexity first: f6 (complexity 14) leads.
    assert out[0]["function"] == "f6"


# --------------------------------------------------------------------------- #
# _scan_shallow_tests — default-limit cap vs uncapped (L1775, L1798).
# --------------------------------------------------------------------------- #

def test_shallow_tests_default_limit_caps_and_uncapped_returns_all(tmp_path: Path):
    """Default ``limit=5`` caps the shallow list (L1775); ``limit=None`` returns
    every shallow module (L1798 ``out if limit is None``)."""
    (tmp_path / "tests").mkdir()
    module_to_tests = {}
    for i in range(7):
        rel = f"tests/test_m{i}.py"
        (tmp_path / rel).write_text(
            f"import app.m{i}\n"
            f"def test_smoke():\n    assert app.m{i} is not None\n",
            encoding="utf-8")
        module_to_tests[f"app/m{i}.py"] = [rel]
    prof = _profiler(tmp_path)
    capped = prof._scan_shallow_tests(module_to_tests)        # default limit=5
    uncapped = prof._scan_shallow_tests(module_to_tests, limit=None)
    assert len(capped) == 5
    assert len(uncapped) == 7


# --------------------------------------------------------------------------- #
# _scan_hotspots — risk ranking, fan-in candidate floor, cap (L1808, L1824).
# --------------------------------------------------------------------------- #

def test_scan_hotspots_ranks_by_risk_and_caps_at_three(tmp_path: Path):
    """Hotspot modules are ranked by risk (complexity x fan-in / tests) and
    capped at three (L1824 ``[:3]``). Higher fan-in -> higher risk -> earlier."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(10))
    for name in ("m0", "m1", "m2", "m3"):
        (tmp_path / "app" / f"{name}.py").write_text(
            f"def cx(x):\n{branches}\n    return -1\n", encoding="utf-8")
    # m0 gets three importers (highest fan-in), m1 two — so m0 outranks m1.
    for i in range(3):
        (tmp_path / "app" / f"a{i}.py").write_text(
            "from app.m0 import cx\ndef u():\n    return cx(1)\n", encoding="utf-8")
    for i in range(2):
        (tmp_path / "app" / f"b{i}.py").write_text(
            "from app.m1 import cx\ndef u():\n    return cx(1)\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    modules = PythonStructureAnalyzer(tmp_path).analyze()
    graph = DependencyGraphBuilder(tmp_path).build()
    hotspots = [Path(p).as_posix() for p in prof._scan_hotspots(modules, graph, {})]
    assert len(hotspots) == 3
    assert hotspots[0] == "app/m0.py"
    assert hotspots[1] == "app/m1.py"


def test_scan_hotspots_complexity_floor_is_eight(tmp_path: Path):
    """A module is a complexity hotspot only at complexity >= 8 (L1815 ``< 8``
    and the literal ``8``); a complexity-6 module is excluded even as a
    candidate (both have fan-in 2)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    b8 = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(8))
    b6 = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(6))
    (tmp_path / "app" / "c8.py").write_text(
        f"def cx(x):\n{b8}\n    return -1\n", encoding="utf-8")
    (tmp_path / "app" / "c6.py").write_text(
        f"def cy(x):\n{b6}\n    return -1\n", encoding="utf-8")
    for mod, sym in (("c8", "cx"), ("c6", "cy")):
        for i in range(2):
            (tmp_path / "app" / f"{mod}_imp{i}.py").write_text(
                f"from app.{mod} import {sym}\ndef u():\n    return 1\n",
                encoding="utf-8")
    prof = _profiler(tmp_path)
    modules = PythonStructureAnalyzer(tmp_path).analyze()
    graph = DependencyGraphBuilder(tmp_path).build()
    hotspots = [Path(p).as_posix() for p in prof._scan_hotspots(modules, graph, {})]
    assert "app/c8.py" in hotspots
    assert "app/c6.py" not in hotspots


def test_scan_hotspots_empty_candidates_returns_empty_list():
    """No candidates yields an empty list, not None (L1811 ``return []``)."""
    prof = _profiler(".")
    assert prof._scan_hotspots([], {}, {}) == []


def test_scan_hotspots_fan_in_candidate_floor_is_two(tmp_path: Path):
    """A complex module enters the candidate set via fan-in >= 2 even when it is
    OUTSIDE the top-15 symbol-ranked modules (L1808 ``fi >= 2`` and the ``2``).

    The module has one symbol (so 16 symbol-rich modules crowd it out of
    ``symbol_rank[:15]``) and fan-in exactly two; if the fan-in floor moved off 2
    it would never be scored and would vanish from the hotspots.
    """
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(10))
    (tmp_path / "app" / "M.py").write_text(
        f"def cx(x):\n{branches}\n    return -1\n", encoding="utf-8")
    for c in range(2):
        (tmp_path / "app" / f"impM{c}.py").write_text(
            "from app.M import cx\ndef u():\n    return cx(1)\n", encoding="utf-8")
    for i in range(16):
        body = "\n".join(f"def s{i}_{j}():\n    return {j}" for j in range(5))
        (tmp_path / "app" / f"rich{i}.py").write_text(body + "\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    modules = PythonStructureAnalyzer(tmp_path).analyze()
    graph = DependencyGraphBuilder(tmp_path).build()
    hotspots = [Path(p).as_posix() for p in prof._scan_hotspots(modules, graph, {})]
    assert "app/M.py" in hotspots


# --------------------------------------------------------------------------- #
# _scan_confluences — distinct-family floor and cap (L1570, L1633, L1641).
# --------------------------------------------------------------------------- #

def test_confluence_requires_three_distinct_families():
    """A module is a confluence only when >= _CONFLUENCE_MIN_FAMILIES (3)
    distinct families name it (L1570/L1633). Two families is below the bar."""
    prof = _profiler(".")
    profile = ProjectProfile(root="r")
    profile.dependency_hubs = ["app/three.py"]
    profile.symbol_hubs = ["app/three.py", "app/two.py"]
    profile.fragile_modules = ["app/three.py", "app/two.py"]
    prof._scan_confluences(profile)
    flagged = {c["module"]: c["family_count"] for c in profile.confluence_modules}
    assert flagged == {"app/three.py": 3}


def test_confluence_modules_capped_at_five():
    """At most five confluences surface (L1641 ``[:5]``)."""
    prof = _profiler(".")
    profile = ProjectProfile(root="r")
    mods = [f"app/m{i}.py" for i in range(6)]
    profile.dependency_hubs = list(mods)
    profile.symbol_hubs = list(mods)
    profile.fragile_modules = list(mods)
    prof._scan_confluences(profile)
    assert len(profile.confluence_modules) == 5


# --------------------------------------------------------------------------- #
# _scan_hub_untested_modules — fan-in floor, symbol floor, cap (directly).
# --------------------------------------------------------------------------- #

def _node(path: str, in_degree: int):
    return types.SimpleNamespace(path=path, in_degree=in_degree, imports=[])


def test_hub_untested_fan_in_floor_is_three():
    """A hub-coverage target needs fan-in >= _HUB_FAN_IN_FLOOR (3)
    (L1497/L1547); fan-in 2 is below the bar."""
    prof = _profiler(".")
    graph = {"app/a.py": _node("app/a.py", 3), "app/b.py": _node("app/b.py", 2)}
    out = prof._scan_hub_untested_modules(
        graph, {}, shallow=set(), claimed=set(),
        symbol_counts={"app/a.py": 1, "app/b.py": 1})
    assert [d["module"] for d in out] == ["app/a.py"]


def test_hub_untested_symbol_floor_is_one():
    """A hub with zero defined symbols is not a coverage target
    (L1507/L1552 ``< self._HUB_COVERAGE_MIN_SYMBOLS``)."""
    prof = _profiler(".")
    graph = {"app/empty.py": _node("app/empty.py", 4),
             "app/real.py": _node("app/real.py", 4)}
    out = prof._scan_hub_untested_modules(
        graph, {}, shallow=set(), claimed=set(),
        symbol_counts={"app/empty.py": 0, "app/real.py": 1})
    assert [d["module"] for d in out] == ["app/real.py"]


def test_hub_untested_capped_and_ranked_by_fan_in():
    """Hub-untested modules cap at five (L1563 ``[:5]``) and rank by fan-in."""
    prof = _profiler(".")
    graph = {f"app/h{i}.py": _node(f"app/h{i}.py", 3 + i) for i in range(7)}
    symbols = {p: 2 for p in graph}
    out = prof._scan_hub_untested_modules(
        graph, {}, shallow=set(), claimed=set(), symbol_counts=symbols)
    assert len(out) == 5
    # widest blast radius (highest fan-in) first.
    assert out[0]["module"] == "app/h6.py"
    assert out[0]["fan_in"] == 9


# --------------------------------------------------------------------------- #
# _impure_untested_hit — purity guard, dunder skip, lineno default (directly).
# --------------------------------------------------------------------------- #

def test_impure_hit_records_partial_dunder_with_default_line():
    """An impure, untested ``__foo`` (leading ``__`` only) is recorded
    (L1485 ``and``) and its missing line defaults to 0 (L1490 ``fn.get(...,0)``)."""
    hit = ProjectProfiler._impure_untested_hit(
        "app/m.py",
        {"purity": "impure", "name": "__foo", "side_effects": ["io"]},
        lambda name: False,
    )
    assert hit == {"module": "app/m.py", "function": "__foo",
                   "line": 0, "side_effects": ["io"]}


def test_cochange_gap_excludes_missing_skipped_and_shared_pairs():
    """A co-change pair is a test gap only when both modules are real, in-scope,
    and share NO test (L1670 ``not a or not b``, L1672 ``is_skipped`` ``or``,
    L1676 shared-test skip). Each excluded pair carries a HIGH cochange count so
    it would rank first if its guard were inverted."""
    prof = _profiler(".")
    profile = ProjectProfile(root="r")
    profile.change_coupling = [
        {"a": "app/a.py", "b": "app/b.py", "commits": 4},          # real gap
        {"a": "app/x.py", "b": None, "commits": 99},               # missing b
        {"a": "node_modules/y.py", "b": "app/z.py", "commits": 98},  # skipped a
        {"a": "app/s1.py", "b": "app/s2.py", "commits": 97},       # shared test
    ]
    profile.module_to_tests = {
        "app/s1.py": ["tests/shared.py"], "app/s2.py": ["tests/shared.py"]}
    gaps = prof._scan_cochange_test_gaps(profile)
    assert [(g["a"], g["b"]) for g in gaps] == [("app/a.py", "app/b.py")]


def test_cochange_gaps_capped_and_sorted():
    """Co-change gaps cap at five and rank by cochange count desc (L1680
    ``[:5]``, sort key)."""
    prof = _profiler(".")
    profile = ProjectProfile(root="r")
    profile.change_coupling = [
        {"a": f"app/m{i}.py", "b": f"app/n{i}.py", "commits": 10 - i}
        for i in range(7)
    ]
    # A coupling entry with NO ``commits`` key must record 0, not 1 (L1678).
    profile.change_coupling.append({"a": "app/z0.py", "b": "app/z1.py"})
    profile.module_to_tests = {}
    gaps = prof._scan_cochange_test_gaps(profile)
    assert len(gaps) == 5
    assert (gaps[0]["a"], gaps[0]["cochanges"]) == ("app/m0.py", 10)
    by_pair = {(g["a"], g["b"]): g["cochanges"] for g in
               prof._scan_cochange_test_gaps(_zero_commit_profile())}
    assert by_pair[("app/z0.py", "app/z1.py")] == 0


def _zero_commit_profile() -> ProjectProfile:
    profile = ProjectProfile(root="r")
    profile.change_coupling = [{"a": "app/z0.py", "b": "app/z1.py"}]
    profile.module_to_tests = {}
    return profile


def test_cochange_module_map_empty_without_root():
    """A profiler with no root yields an empty cochange module map (L1701
    ``return {}``)."""
    prof = ProjectProfiler.__new__(ProjectProfiler)
    prof.root = None
    assert prof._cochange_module_map([{"a": "app/a.py", "b": "app/b.py"}]) == {}


def test_cochange_links_empty_without_module_map():
    """No module map -> no links (L1730 ``return []``)."""
    prof = _profiler(".")
    assert prof._cochange_links("app/a.py", "app/b.py", {}) == []


def test_imported_symbols_resolves_cross_module_import(tmp_path: Path):
    """``_imported_symbols`` returns the names one module imports from another."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text(
        "from app.b import widget\ndef use():\n    return widget()\n", encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text(
        "def widget():\n    return 1\n", encoding="utf-8")
    prof = _profiler(tmp_path)
    module_map = {"app.a": "app/a.py", "app.b": "app/b.py"}
    assert prof._imported_symbols("app/a.py", "app/b.py", module_map) == ["widget"]
    # b does not import from a -> empty.
    assert prof._imported_symbols("app/b.py", "app/a.py", module_map) == []


def test_imported_symbols_empty_without_root():
    """No filesystem root -> no imported symbols (L1742 ``return []``)."""
    prof = ProjectProfiler.__new__(ProjectProfiler)
    prof.root = None
    assert prof._imported_symbols("app/a.py", "app/b.py", {"app.b": "app/b.py"}) == []


def test_imported_symbols_empty_on_unparseable_source(tmp_path: Path):
    """A module that fails to parse yields no imported symbols (L1747 ``[]``)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "broken.py").write_text(
        "from app.b import (\n", encoding="utf-8")  # syntax error
    prof = _profiler(tmp_path)
    assert prof._imported_symbols(
        "app/broken.py", "app/b.py", {"app.b": "app/b.py"}) == []


def test_impure_hit_skips_pure_and_exercised_functions():
    """Pure functions and exercised functions are not impure-untested hits
    (L1481 purity guard / L1487 exercised guard)."""
    pure = ProjectProfiler._impure_untested_hit(
        "app/m.py", {"purity": "pure", "name": "f"}, lambda name: False)
    exercised = ProjectProfiler._impure_untested_hit(
        "app/m.py", {"purity": "impure", "name": "f", "side_effects": []},
        lambda name: True)
    full_dunder = ProjectProfiler._impure_untested_hit(
        "app/m.py", {"purity": "impure", "name": "__init__", "side_effects": []},
        lambda name: False)
    assert pure is None
    assert exercised is None
    assert full_dunder is None
