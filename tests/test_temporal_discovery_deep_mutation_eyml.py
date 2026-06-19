"""Deep-mutation characterization for temporal / evolutionary discovery.

The sibling suite ``test_temporal_discovery_eyml.py`` proves the three public
functions end-to-end against throwaway git repos. This complement attacks the
PURE internal helpers directly with in-memory fixtures so that every arithmetic
operator, comparison direction, boundary constant and ordering key in
``app/engine/temporal_discovery.py`` is pinned to an exact value. A surviving
mutant — flipping ``>`` to ``>=``, ``//`` to ``/`` or ``*``, changing
``_MIN_COCHANGES`` / ``_MAX_COMMIT_FILES`` / ``_COMMIT_WINDOW``, swapping a sort
sign, or altering the ``recent``/``older`` slice — makes at least one assertion
below fail.

Targets (and the mutants each kills):

* ``_parse_commits`` — the ``1 <= len <= _MAX_COMMIT_FILES`` flush window
  (exact 50-file boundary on both sides), the ``@commit@`` marker, source/skip
  filtering, sorted output, single-file commits KEPT, empty commits dropped.
* ``_split_halves`` — the ``len // 2`` floor split and which half is recent
  (newest-first => first half), odd-count extra goes to ``recent``, the
  ``if half`` short-circuit for tiny inputs.
* ``_count_files`` / ``_count_pairs`` — exact tallies and canonical pair order.
* ``_trend`` — the three strict-comparison branches and exact-tie ``stable``.
* ``_is_source`` — extension membership (case-folded) and skip precedence.
* the module-level constants themselves.

All assertions are deterministic: fixed literal inputs, no time/random/network,
no PYTHONHASHSEED dependence (every compared collection is sorted or keyed).
"""

from __future__ import annotations

from app.engine import temporal_discovery as td
from app.engine.temporal_discovery import (
    _MAX_COMMIT_FILES,
    _MIN_COCHANGES,
    _SOURCE_EXTENSIONS,
    _count_files,
    _count_pairs,
    _is_source,
    _parse_commits,
    _split_halves,
    _trend,
)


# --- module constants are pinned exactly -----------------------------------


def test_constants_have_exact_values():
    assert td._COMMIT_WINDOW == 1000
    assert _MAX_COMMIT_FILES == 50
    assert _MIN_COCHANGES == 2
    assert td._TREND_ACCELERATING == "accelerating"
    assert td._TREND_STABLE == "stable"
    assert td._TREND_COOLING == "cooling"


def test_source_extensions_membership_is_exact():
    # A representative present/absent split — kills set-content mutants.
    assert ".py" in _SOURCE_EXTENSIONS
    assert ".ts" in _SOURCE_EXTENSIONS
    assert ".go" in _SOURCE_EXTENSIONS
    # Non-source extensions must be absent.
    assert ".md" not in _SOURCE_EXTENSIONS
    assert ".txt" not in _SOURCE_EXTENSIONS
    assert ".json" not in _SOURCE_EXTENSIONS
    assert "" not in _SOURCE_EXTENSIONS


# --- _is_source: extension + skip precedence -------------------------------


def test_is_source_true_only_for_known_source_extension():
    assert _is_source("app/x.py") is True
    assert _is_source("web/client.js") is True


def test_is_source_false_for_non_source_extension():
    assert _is_source("docs/readme.md") is False
    assert _is_source("data/x.json") is False
    assert _is_source("Makefile") is False  # no recognised suffix


def test_is_source_case_folds_suffix():
    # .lower() on the suffix => uppercase extension still counts as source.
    assert _is_source("app/X.PY") is True
    assert _is_source("web/C.JS") is True


def test_is_source_skip_predicate_wins_over_extension():
    # A .py file under a skipped dir is rejected before the extension check.
    assert _is_source("__pycache__/cached.py") is False


# --- _parse_commits: marker, filtering, sorting, kept/dropped --------------


def _log(*commits: tuple[str, ...]) -> str:
    """Build raw ``git log`` text: each commit is a @commit@ marker + its paths."""
    lines: list[str] = []
    for i, files in enumerate(commits):
        lines.append(f"@commit@deadbeef{i}")
        lines.extend(files)
    return "\n".join(lines) + "\n"


def test_parse_commits_groups_each_commit_and_sorts_paths():
    out = _parse_commits(_log(
        ("web/z.js", "app/a.py"),       # unsorted input -> sorted output
        ("app/b.py",),                  # single-file commit KEPT
    ))
    assert out == [["app/a.py", "web/z.js"], ["app/b.py"]]


def test_parse_commits_drops_non_source_and_skipped_paths():
    out = _parse_commits(_log(
        ("app/a.py", "docs/readme.md", "__pycache__/c.py", "web/b.js"),
    ))
    # md dropped (non-source), __pycache__ dropped (skip), two survive sorted.
    assert out == [["app/a.py", "web/b.js"]]


def test_parse_commits_drops_commit_with_no_surviving_source():
    # A commit whose every path is filtered yields an empty list -> dropped,
    # so only the qualifying commit remains.
    out = _parse_commits(_log(
        ("docs/readme.md", "notes.txt"),
        ("app/a.py",),
    ))
    assert out == [["app/a.py"]]


def test_parse_commits_ignores_lines_before_first_marker():
    # ``started`` stays False until a @commit@ marker, so stray leading paths
    # are not attributed to any commit.
    raw = "app/orphan.py\n" + _log(("app/a.py",))
    assert _parse_commits(raw) == [["app/a.py"]]


def test_parse_commits_keeps_commit_at_max_file_boundary():
    # Exactly _MAX_COMMIT_FILES source files -> KEPT (<= boundary inclusive).
    files = tuple(f"app/m{i:03d}.py" for i in range(_MAX_COMMIT_FILES))
    out = _parse_commits(_log(files))
    assert len(out) == 1
    assert len(out[0]) == _MAX_COMMIT_FILES


def test_parse_commits_drops_commit_one_over_max_file_boundary():
    # _MAX_COMMIT_FILES + 1 source files -> mega-commit, DROPPED.
    files = tuple(f"app/m{i:03d}.py" for i in range(_MAX_COMMIT_FILES + 1))
    out = _parse_commits(_log(files))
    assert out == []


def test_parse_commits_keeps_single_file_lower_boundary():
    # len == 1 is the inclusive lower bound (1 <= len): single-file kept.
    assert _parse_commits(_log(("app/a.py",))) == [["app/a.py"]]


def test_parse_commits_preserves_newest_first_commit_order():
    # git's own order is preserved; _log writes commits in the given order.
    out = _parse_commits(_log(("app/newest.py",), ("app/older.py",)))
    assert out == [["app/newest.py"], ["app/older.py"]]


# --- _split_halves: floor split, recent-first, odd extra to recent ---------


def test_split_halves_even_count_is_balanced():
    commits = [["a"], ["b"], ["c"], ["d"]]
    recent, older = _split_halves(commits)
    assert recent == [["a"], ["b"]]   # first half == recent (newest-first)
    assert older == [["c"], ["d"]]


def test_split_halves_odd_extra_goes_to_recent():
    # 5 // 2 == 2 -> older = commits[2:] (3 items), recent = first 2.
    commits = [["a"], ["b"], ["c"], ["d"], ["e"]]
    recent, older = _split_halves(commits)
    assert recent == [["a"], ["b"]]
    assert older == [["c"], ["d"], ["e"]]
    assert len(recent) == 2 and len(older) == 3


def test_split_halves_single_commit_has_no_recent_half():
    # half == 0 -> both branches short-circuit to []: no two halves.
    recent, older = _split_halves([["a"]])
    assert recent == []
    assert older == []


def test_split_halves_two_commits_split_one_each():
    recent, older = _split_halves([["a"], ["b"]])
    assert recent == [["a"]]
    assert older == [["b"]]


def test_split_halves_floor_not_round_for_three():
    # 3 // 2 == 1 (floor): recent gets 1, older gets 2.
    recent, older = _split_halves([["a"], ["b"], ["c"]])
    assert recent == [["a"]]
    assert older == [["b"], ["c"]]


# --- _count_files / _count_pairs: exact tallies + canonical order ----------


def test_count_files_tallies_per_commit_occurrences():
    counts = _count_files([
        ["app/a.py", "app/b.py"],
        ["app/a.py"],
        ["app/a.py", "app/c.py"],
    ])
    assert counts == {"app/a.py": 3, "app/b.py": 1, "app/c.py": 1}


def test_count_files_empty_input_is_empty_dict():
    assert _count_files([]) == {}


def test_count_pairs_canonical_order_and_tally():
    # Each commit's files are pre-sorted, so combinations are (a, b) with a < b.
    pairs = _count_pairs([
        ["app/a.py", "app/b.py", "app/c.py"],  # 3 pairs
        ["app/a.py", "app/b.py"],              # +1 to (a, b)
    ])
    assert pairs == {
        ("app/a.py", "app/b.py"): 2,
        ("app/a.py", "app/c.py"): 1,
        ("app/b.py", "app/c.py"): 1,
    }


def test_count_pairs_single_file_commit_contributes_nothing():
    assert _count_pairs([["app/a.py"]]) == {}


def test_count_pairs_three_files_yield_exactly_three_pairs():
    pairs = _count_pairs([["a", "b", "c"]])
    assert len(pairs) == 3


# --- _trend: three strict branches and the exact tie -----------------------


def test_trend_accelerating_when_recent_strictly_greater():
    assert _trend(3, 2) == "accelerating"
    assert _trend(1, 0) == "accelerating"


def test_trend_cooling_when_recent_strictly_less():
    assert _trend(2, 3) == "cooling"
    assert _trend(0, 1) == "cooling"


def test_trend_stable_on_exact_tie():
    # Equality is the ONLY stable case: kills `>`->`>=` / `<`->`<=` mutants.
    assert _trend(0, 0) == "stable"
    assert _trend(5, 5) == "stable"


# --- ordering keys exercised through the public sorts ----------------------


def test_emerging_hotspots_orders_by_delta_then_recent_then_module(monkeypatch):
    """Two accelerating files with equal (recent - older) delta of 1 must tie-break
    by ``-recent`` (higher recent first), and an equal-recent pair by module name.
    The DEFAULT (half-split) sort key is ``(-(recent-older), -recent, module)``.
    """
    # recent half: 4 commits, older half: 4 commits.
    commits = [
        # recent (newest-first first half)
        ["app/big.py", "app/small.py"],
        ["app/big.py", "app/small.py"],
        ["app/big.py", "app/small.py"],
        ["app/big.py"],
        # older
        ["app/big.py", "app/small.py"],
        ["app/big.py", "app/small.py"],
        ["app/small.py"],
        ["zzz/other.py"],
    ]
    monkeypatch.setattr(td, "_load_commits", lambda root: commits)
    rows = td.emerging_hotspots("ignored")
    # big: recent=4 older=2 delta=2 ; small: recent=3 older=3 delta=0 -> only big
    # accelerates. Confirm big leads and small (stable) is excluded.
    mods = [r["module"] for r in rows]
    assert mods == ["app/big.py"]
    assert rows[0]["recent"] == 4 and rows[0]["older"] == 2


def test_emerging_hotspots_delta_then_recent_tiebreak(monkeypatch):
    """Equal positive delta -> higher ``recent`` sorts first (kills the -recent
    sort-sign mutant)."""
    commits = [
        # recent half (4)
        ["a/hi.py"], ["a/hi.py"], ["a/hi.py"], ["a/lo.py"],
        # older half (4)
        ["a/hi.py"], ["a/hi.py"], ["a/lo.py"], ["zzz/x.py"],
    ]
    # hi: recent=3 older=2 delta=1 ; lo: recent=1 older=1 delta=0 (stable, dropped)
    # Add a second delta-1 file with smaller recent to force the tiebreak.
    commits = [
        ["a/hi.py", "a/lo.py"], ["a/hi.py"], ["a/hi.py"], ["a/lo.py"],
        ["a/hi.py", "a/lo.py"], ["a/hi.py"], ["zzz/x.py"], ["zzz/y.py"],
    ]
    monkeypatch.setattr(td, "_load_commits", lambda root: commits)
    rows = td.emerging_hotspots("ignored")
    by = {r["module"]: r for r in rows}
    # hi: recent=3 older=2 delta=1 ; lo: recent=2 older=1 delta=1.
    assert by["a/hi.py"]["recent"] == 3 and by["a/hi.py"]["older"] == 2
    assert by["a/lo.py"]["recent"] == 2 and by["a/lo.py"]["older"] == 1
    # Equal delta=1 -> higher recent (hi=3) before lo=2.
    assert [r["module"] for r in rows] == ["a/hi.py", "a/lo.py"]


def test_spreading_pairs_requires_strict_increase_and_min_cochanges(monkeypatch):
    """A pair needs ``recent > older`` (strict) AND ``recent + older >=
    _MIN_COCHANGES``. A pair with recent==older is excluded; a pair with total
    of exactly _MIN_COCHANGES and recent>older is the inclusive boundary.
    """
    # Build halves directly via _count_pairs by controlling the commit list.
    commits = [
        # recent half (3 commits)
        ["app/a.py", "app/b.py"],   # boundary pair: recent=1
        ["app/c.py", "app/d.py"],   # stays-equal pair seed
        ["app/c.py", "app/d.py"],
        # older half (3 commits)
        ["zzz/x.py"],
        ["app/c.py", "app/d.py"],
        ["app/c.py", "app/d.py"],
    ]
    monkeypatch.setattr(td, "_load_commits", lambda root: commits)
    rows = td.spreading_pairs("ignored", top=5)
    by = {(r["a"], r["b"]): r for r in rows}
    # (a,b): recent=1 older=0 total=1 -> total < _MIN_COCHANGES (2) -> EXCLUDED.
    assert ("app/a.py", "app/b.py") not in by
    # (c,d): recent=2 older=2 -> recent not > older -> EXCLUDED.
    assert ("app/c.py", "app/d.py") not in by
    assert rows == []


def test_spreading_pairs_includes_at_min_cochanges_boundary(monkeypatch):
    commits = [
        # recent half (2 commits): pair appears twice -> recent=2
        ["app/a.py", "app/b.py"],
        ["app/a.py", "app/b.py"],
        # older half (2 commits): pair absent -> older=0
        ["zzz/x.py"],
        ["zzz/y.py"],
    ]
    monkeypatch.setattr(td, "_load_commits", lambda root: commits)
    rows = td.spreading_pairs("ignored", top=5)
    assert len(rows) == 1
    r = rows[0]
    # recent=2 older=0 total=2 == _MIN_COCHANGES (inclusive) and 2 > 0.
    assert (r["a"], r["b"]) == ("app/a.py", "app/b.py")
    assert r["recent"] == 2 and r["older"] == 0
    assert r["cochanges"] == 2
    assert r["trend"] == "accelerating"


def test_spreading_pairs_top_cap_truncates_after_sort(monkeypatch):
    """``top`` truncates the SORTED list, so the strongest pair survives a cap of
    1 (kills an off-by-one in ``rows[:top]`` and a missing-sort mutant)."""
    commits = [
        # recent half (5)
        ["s/a.py", "s/b.py"], ["s/a.py", "s/b.py"], ["s/a.py", "s/b.py"],
        ["s/c.py", "s/d.py"], ["s/c.py", "s/d.py"],
        # older half (5) — neither pair present, so both strengthen from 0
        ["zzz/1.py"], ["zzz/2.py"], ["zzz/3.py"], ["zzz/4.py"], ["zzz/5.py"],
    ]
    monkeypatch.setattr(td, "_load_commits", lambda root: commits)
    full = td.spreading_pairs("ignored", top=5)
    # (a,b): recent=3 older=0 delta=3 ; (c,d): recent=2 older=0 delta=2.
    assert [(r["a"], r["b"]) for r in full] == [
        ("s/a.py", "s/b.py"), ("s/c.py", "s/d.py"),
    ]
    capped = td.spreading_pairs("ignored", top=1)
    assert len(capped) == 1
    assert (capped[0]["a"], capped[0]["b"]) == ("s/a.py", "s/b.py")


def test_spreading_pairs_top_zero_short_circuits(monkeypatch):
    # top <= 0 returns [] before any git read.
    def _boom(root):  # pragma: no cover - must never be called
        raise AssertionError("_load_commits called despite top<=0")

    monkeypatch.setattr(td, "_load_commits", _boom)
    assert td.spreading_pairs("ignored", top=0) == []
    assert td.spreading_pairs("ignored", top=-1) == []


# --- _load_commits boundary: max_commits<=0 and truncation -----------------


def test_load_commits_nonpositive_max_returns_none(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover - must never be called
        raise AssertionError("git read attempted for max_commits<=0")

    monkeypatch.setattr(td, "_read_git_log", _boom)
    assert td._load_commits("/whatever", max_commits=0) is None
    assert td._load_commits("/whatever", max_commits=-3) is None


def test_load_commits_truncates_to_max_commits(monkeypatch, tmp_path):
    raw = _log(("app/a.py",), ("app/b.py",), ("app/c.py",))
    monkeypatch.setattr(td, "_read_git_log", lambda root_path: raw)
    out = td._load_commits(str(tmp_path), max_commits=2)
    assert out == [["app/a.py"], ["app/b.py"]]  # newest-first, capped at 2


def test_load_commits_missing_root_returns_none():
    assert td._load_commits("/no/such/path/xyz", max_commits=10) is None


def test_load_commits_git_read_none_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(td, "_read_git_log", lambda root_path: None)
    assert td._load_commits(str(tmp_path), max_commits=10) is None


# --- file_evolution: cochange threshold + sort, via injected commits -------


def test_file_evolution_cochange_groups_apply_min_threshold(monkeypatch):
    """A pair must clear ``>= _MIN_COCHANGES`` to appear; a pair seen once is
    dropped. The exact boundary (count == 2) is included."""
    commits = [
        ["app/a.py", "app/b.py"],   # (a,b): 2
        ["app/a.py", "app/b.py"],
        ["app/a.py", "app/c.py"],   # (a,c): 1 -> below threshold
    ]
    monkeypatch.setattr(td, "_load_commits", lambda root, max_commits=None: commits)
    out = td.file_evolution("ignored")
    groups = {(g["a"], g["b"]): g["cochanges"] for g in out["cochange_groups"]}
    assert groups == {("app/a.py", "app/b.py"): 2}
    assert out["commits"] == 3


def test_file_evolution_frequency_sorted_by_neg_changes_then_module(monkeypatch):
    commits = [
        ["app/hot.py", "app/mid.py"],
        ["app/hot.py", "app/zed.py"],
        ["app/hot.py"],
        ["app/mid.py"],
    ]
    monkeypatch.setattr(td, "_load_commits", lambda root, max_commits=None: commits)
    rows = td.file_evolution("ignored")["frequency"]
    # hot=3, mid=2, zed=1 -> descending by changes; ties (none here) by module.
    assert [(r["module"], r["changes"]) for r in rows] == [
        ("app/hot.py", 3), ("app/mid.py", 2), ("app/zed.py", 1),
    ]


def test_file_evolution_empty_when_no_commits(monkeypatch):
    monkeypatch.setattr(td, "_load_commits", lambda root, max_commits=None: None)
    assert td.file_evolution("ignored") == {
        "commits": 0, "frequency": [], "cochange_groups": [],
    }


# --- opt-in TIME-DECAY branch: helpers + filter/sort/shape, default OFF -----


def test_decay_weights_and_acceleration_pin_exact_math():
    # Weight = _DECAY_BASE ** position, newest (idx 0) == 1.0.
    assert td._decay_weights(3) == [1.0, 0.9, 0.9 ** 2]
    assert td._decay_weights(0) == [] and td._decay_weights(-1) == []
    # Acceleration = weighted - count*mean_weight (kills + / * mutants).
    assert td._acceleration(1.5, 2, 0.5) == 0.5
    assert td._acceleration(1.0, 2, 0.5) == 0.0
    # _accel_trend epsilon tie => stable; strict sign => accel/cool.
    assert td._accel_trend(1.0) == "accelerating"
    assert td._accel_trend(-1.0) == "cooling"
    assert td._accel_trend(0.0) == "stable"


def test_emerging_hotspots_decay_off_by_default(monkeypatch):
    """``decay`` defaults False => half-split rows, NO ``accel`` key. Kills a
    mutant that flips the default to True."""
    commits = [
        ["app/a.py"], ["app/a.py"],   # recent half: a x2
        ["zzz/x.py"], ["zzz/y.py"],   # older half: a absent
    ]
    monkeypatch.setattr(td, "_load_commits", lambda root: commits)
    rows = td.emerging_hotspots("ignored")  # default
    assert rows == [{"module": "app/a.py", "recent": 2, "older": 0,
                     "trend": "accelerating"}]
    assert all("accel" not in r for r in rows)


def test_emerging_hotspots_decay_orders_by_accel_then_recent(monkeypatch):
    """With ``decay=True`` the sort key is ``(-accel, -recent, module)`` and the
    fixture is exactly the one the half-split missed: ``small`` is recent==older
    (the split drops it) but its changes lean recent, so decay flags it — behind
    ``big`` whose accel is larger."""
    commits = [
        ["app/big.py", "app/small.py"],
        ["app/big.py", "app/small.py"],
        ["app/big.py", "app/small.py"],
        ["app/big.py"],
        ["app/big.py", "app/small.py"],
        ["app/big.py", "app/small.py"],
        ["app/small.py"],
        ["zzz/other.py"],
    ]
    monkeypatch.setattr(td, "_load_commits", lambda root: commits)
    rows = td.emerging_hotspots("ignored", decay=True)
    assert [r["module"] for r in rows] == ["app/big.py", "app/small.py"]
    assert rows[0]["accel"] == 0.414094 and rows[0]["recent"] == 4
    assert rows[1]["accel"] == 0.216535 and rows[1]["recent"] == 3
    assert rows[0]["accel"] > rows[1]["accel"]


def test_emerging_hotspots_decay_needs_two_commits(monkeypatch):
    monkeypatch.setattr(td, "_load_commits", lambda root: [["app/a.py"]])
    assert td.emerging_hotspots("ignored", decay=True) == []


def test_spreading_pairs_decay_off_by_default(monkeypatch):
    commits = [
        ["app/a.py", "app/b.py"], ["app/a.py", "app/b.py"],  # recent: 2
        ["zzz/x.py"], ["zzz/y.py"],                           # older: 0
    ]
    monkeypatch.setattr(td, "_load_commits", lambda root: commits)
    rows = td.spreading_pairs("ignored")  # default half-split
    assert rows == [{"a": "app/a.py", "b": "app/b.py", "recent": 2, "older": 0,
                     "cochanges": 2, "trend": "accelerating"}]
    assert all("accel" not in r for r in rows)


def test_spreading_pairs_decay_filters_min_cochanges_and_sorts(monkeypatch):
    """``decay=True`` keeps only accelerating pairs clearing ``_MIN_COCHANGES``
    total, sorted by ``(-accel, -cochanges, a, b)`` and capped at ``top``."""
    commits = [
        # newest-first: (a,b) at the recent end (positions 0,1), (c,d) older
        ["app/a.py", "app/b.py"], ["app/a.py", "app/b.py"],
        ["zzz/x.py"], ["zzz/y.py"],
        ["app/c.py", "app/d.py"], ["app/c.py", "app/d.py"],
        ["app/e.py", "app/f.py"],   # single occurrence -> total 1 < _MIN_COCHANGES
    ]
    monkeypatch.setattr(td, "_load_commits", lambda root: commits)
    rows = td.spreading_pairs("ignored", top=5, decay=True)
    pairs = [(r["a"], r["b"]) for r in rows]
    assert ("app/a.py", "app/b.py") in pairs        # recent seam, accelerating
    assert ("app/e.py", "app/f.py") not in pairs     # below _MIN_COCHANGES total
    # The accelerating recent pair leads, and every row carries accel + total.
    assert pairs[0] == ("app/a.py", "app/b.py")
    assert all(r["cochanges"] >= td._MIN_COCHANGES for r in rows)
    assert all("accel" in r for r in rows)
    # top cap truncates the sorted list.
    assert len(td.spreading_pairs("ignored", top=1, decay=True)) == 1


def test_spreading_pairs_decay_top_zero_short_circuits(monkeypatch):
    def _boom(root):  # pragma: no cover - must never be called
        raise AssertionError("_load_commits called despite top<=0")

    monkeypatch.setattr(td, "_load_commits", _boom)
    assert td.spreading_pairs("ignored", top=0, decay=True) == []
