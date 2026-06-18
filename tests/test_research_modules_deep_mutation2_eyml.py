"""Deep-mutation hardening for the three DISCOVERY research modules.

Companion to the per-module feature suites
(``test_anomaly_discovery_eyml``, ``test_temporal_discovery_eyml``,
``test_rule_synthesis_eyml``). Those pin the happy paths; this file targets the
*deep* mutation survivors that slip past the mutation tester's 30-mutant cap —
the fixed thresholds, boundary inclusivities, sort-key arithmetic, deviation
rounding and return-value branches that a coarse pass never reaches.

Each test below is a CHARACTERISATION test: it pins the exact observable
behaviour at a boundary so that flipping a single operator/constant in the
source (``<=`` -> ``<``, ``n`` -> ``n+1``, ``and`` -> ``or``, a ``return`` value
-> ``None``, ``a - b`` -> ``a + b``) makes the assertion fail. The module
docstrings name these constants — DEVIATION_FLOOR, the rarity/breadth blend, the
co-change support floor, MIN_SUPPORT — and the tests pin their effect rather than
the literal value, so the kill survives a future re-tuning that is mirrored here.

Determinism only: synthetic profiles, fixed-history throwaway git repos, and
fixed AST sources. No timestamps, no wall-clock, no set/dict-order assertions.

Equivalent mutants (documented, intentionally NOT pinned — verified unkillable
by any deterministic test, not merely uncovered):
  * anomaly_discovery L145/L163/L164 ``freq.get(tag, 0)`` default 0->1 — a tag in
    ``tagset`` is always present in ``freq`` (the frequency table is built FROM
    the profiles), so the default branch is dead.
  * anomaly_discovery L215 ``top <= 0`` boundary <= -> < — ``top == 0`` then
    falls through to ``anomalies[:0]`` which is ``[]`` anyway: same result.
  * temporal_discovery L100 ``max_commits <= 0`` boundary <= -> < and L298
    ``top <= 0`` <= -> < — at the boundary value the function falls through to a
    ``[:0]`` slice that is empty anyway, so the result is identical.
  * temporal_discovery L51 ``_COMMIT_WINDOW`` 1000->1001 and L82 ``timeout=15``
    15->16 — neither bound is observable on a small fixed-history repo.
  * temporal_discovery L133 ``started = False`` -> True — before the first
    ``@commit@`` marker ``current`` is empty, so a True initial ``started`` still
    flushes nothing (the ``1 <= len`` guard is False there).
  * temporal_discovery L264/L304 ``not recent or not older`` or -> and — the
    halves are empty together or non-empty together (``_split_halves``), so the
    disjunction and conjunction are equal on every reachable input.
  * temporal_discovery L136 ``started and 1 <= len(current)`` and -> or — when
    ``started`` is False ``current`` is always ``[]`` (reset on the same line it
    is set True), so ``1 <= len`` is False there too: the connective can't flip
    the result.
  * temporal_discovery L117 ``return False`` -> ``return None`` in ``_is_source``
    — the result is only used in a boolean context, ``None`` and ``False`` are
    indistinguishable there.
  * rule_synthesis L66 ``getattr(node, "lineno", 0)`` default 0->1 — every mined
    statement carries a real ``lineno``, so the default is dead.
  * rule_synthesis L132 ``split("[", 1)`` / ``split("(", 1)`` maxsplit 1->2 — the
    first element is identical regardless of maxsplit.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.engine.anomaly_discovery import (
    _breadth_score,
    _median,
    _rare_tags,
    _rarity_score,
    _why,
    dominant_pattern,
    find_anomalies,
    module_profiles,
)
from app.engine.rule_synthesis import (
    _shape_key,
    _suggested_name,
    mine_recurring_patterns,
    propose_rules,
    synthesise_candidate_rule,
)
from app.engine.temporal_discovery import (
    _trend,
    file_evolution,
    spreading_pairs,
)
from app.tools.project_profile import ProjectProfile
import ast


# =========================================================================== #
# anomaly_discovery — deviation score, rarity/breadth blend, fixed thresholds
# =========================================================================== #


def test_rare_tags_boundary_includes_exactly_half_carriers():
    """``_rare_tags`` keeps a tag carried by EXACTLY half the modules.

    The predicate is ``freq * 2 <= modules``. A tag on 2 of 4 modules sits on
    the boundary (``2*2 == 4``) and IS rare; flipping ``<=`` to ``<`` would drop
    it. Pins L163 boundary.
    """
    freq = {"half": 2, "singleton": 1}
    rare = _rare_tags({"half", "singleton"}, freq, modules=4)
    # Both qualify; the half-carrier must be present (the boundary case).
    assert "half" in rare
    assert "singleton" in rare
    # Rarest first: singleton (freq 1) before half (freq 2).
    assert rare == ["singleton", "half"]


def test_rare_tags_uses_twice_frequency_against_module_count():
    """``_rare_tags`` rarity test is ``freq * 2 <= modules`` (factor TWO).

    A tag on 3 of 4 modules (``3*2 = 6 > 4``) is NOT rare. Pins L163
    ``freq * 2`` against the ``/ 2`` mutant (``3/2 = 1.5 <= 4`` would wrongly call
    it rare).
    """
    assert _rare_tags({"t"}, {"t": 3}, modules=4) == []
    # And a tag on 2 of 5 IS rare (``2*2 = 4 <= 5``); the ``*2`` -> ``*3`` mutant
    # (``2*3 = 6 > 5``) would drop it.
    assert _rare_tags({"t"}, {"t": 2}, modules=5) == ["t"]


def test_median_even_length_averages_two_middle_values():
    """``_median`` of an even-length list averages the two central values.

    ``_median([1, 2, 3, 4]) == 2.5`` pins L108 ``len // 2`` (// 3 -> mid 1),
    L111 ``ordered[mid - 1]`` (mid + 1 / mid - 2 shift the window) and the
    ``/ 2.0`` averaging.
    """
    assert _median([1, 2, 3, 4]) == 2.5
    assert _median([10, 20]) == 15.0


def test_median_odd_length_takes_the_middle_value():
    """``_median`` of an odd-length list returns the exact central element.

    ``_median([1, 2, 3]) == 2`` pins L109 ``len % 2`` (% 3 would take the even
    branch and average 1 and 2 to 1.5).
    """
    assert _median([1, 2, 3]) == 2.0
    assert _median([5, 7, 9, 11, 13]) == 9.0


def test_rarity_score_of_empty_fingerprint_is_zero():
    """An untagged module has rarity exactly 0.0 (not 1.0, not None).

    Pins L144 ``return 0.0`` against both the ``0.0 -> 1.0`` numeric flip and the
    ``return ... -> None`` flip.
    """
    result = _rarity_score(set(), {}, modules=3)
    assert result == 0.0
    assert isinstance(result, float)


def test_breadth_score_zero_gap_is_zero_but_positive_gap_scores():
    """``_breadth_score`` returns 0 only when the gap is non-positive.

    Pins L156 ``max_gap <= 0`` number (0 -> 1 would make a unit gap return 0).
    With ``max_gap == 1.0`` a breadth far from the median still scores (clamped
    to 1.0).
    """
    assert _breadth_score(5, 2.0, 0.0) == 0.0
    assert _breadth_score(5, 2.0, 1.0) == 1.0


def test_breadth_score_is_distance_over_gap_clamped_to_one():
    """``_breadth_score`` is ``abs(size - median) / max_gap``, clamped at 1.0.

    A small gap (distance 1, gap 4) gives 0.25 — pinning L158 ``/ max_gap``
    (``* max_gap`` would give 4.0 -> clamp 1.0). A large distance clamps to 1.0 —
    pinning the ``min(1.0, ...)`` ceiling (2.0 would let it exceed the bound).
    """
    assert _breadth_score(3, 2.0, 4.0) == 0.25
    assert _breadth_score(10, 2.0, 3.0) == 1.0


def test_module_profiles_reads_row_fields_and_change_coupling():
    """Row-shaped signal sources (churn, change-coupling) contribute tags.

    The ``getattr(...) or []`` guards must yield the real list, not ``[]``. Pins
    L88 and L90 ``or []`` (and -> [] would silently drop every row-field and
    co-change tag).
    """
    churn = ProjectProfile(root=".", churn_hotspots=[{"module": "app/c.py"}])
    assert module_profiles(churn) == {"app/c.py": {"high-churn"}}

    coupled = ProjectProfile(
        root=".", change_coupling=[{"a": "app/x.py", "b": "app/y.py"}])
    assert module_profiles(coupled) == {
        "app/x.py": {"co-change"}, "app/y.py": {"co-change"},
    }


def test_why_names_at_most_four_rare_signals():
    """``_why`` lists at most the four rarest signals (``rare[:4]``).

    A module carrying six distinct rare signals must mention exactly four — the
    two rarest-by-tiebreak omitted. Pins L172 ``[:4]`` (5 would leak a fifth).
    """
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b", "c", "d", "e"],
        untested_modules=["a", "b", "c", "d", "e"],
        fragile_modules=["app/odd.py"],
        debt_marker_modules=["app/odd.py"],
        modernizable_modules=["app/odd.py"],
        symbol_hubs=["app/odd.py"],
        mutable_default_modules=["app/odd.py"],
        sensitive_paths=["app/odd.py"],
    )
    top = [a for a in find_anomalies(profile, top=10)
           if a["module"] == "app/odd.py"][0]
    why = top["why"]
    # Exactly four backticked rare signals are named in the "rare signal(s)" clause.
    rare_clause = why.split(";")[0]
    assert rare_clause.count("`") == 8  # four `tag` pairs
    # The two highest-sorting names are dropped (symbol-hub, sensitive-path).
    assert "`symbol-hub`" not in rare_clause
    assert "`sensitive-path`" not in rare_clause


def test_why_breadth_equal_to_median_is_neither_broad_nor_narrow():
    """At breadth == median ``_why`` says neither "broad" nor "narrow".

    This pins both relational boundaries in ``_why``: ``size > median`` (L175,
    > -> >=) and ``size < median`` (L177, < -> <= and < -> >=). A module whose
    breadth equals the median falls through to the generic phrasing.
    """
    norm = {"median_breadth": 2.0, "typical": set(), "frequency": {}, "modules": 3}
    text = _why({"x", "y"}, norm, size=2, rare=[])
    assert "unusually broad" not in text
    assert "unusually narrow" not in text
    assert "off-pattern fingerprint" in text
    # And the asymmetric cases still classify correctly (guards the flips both ways).
    assert "unusually broad" in _why({"a", "b", "c"}, norm, size=3, rare=[])
    assert "unusually narrow" in _why({"a"}, norm, size=1, rare=[])


def test_why_lists_at_most_three_missing_typical_signals():
    """``_why`` names at most three lacked-typical signals (``missing[:3]``).

    Four typical signals all absent from a module must surface exactly three.
    Pins L181 ``[:3]``.
    """
    # Four signals each on a strict majority (3 of 5) => all typical.
    common = ["a", "b", "c"]
    profile = ProjectProfile(
        root=".",
        security_finding_modules=common,
        untested_modules=common,
        fragile_modules=common,
        debt_marker_modules=common,
        # The outlier carries one unrelated rare signal and none of the typical four.
        symbol_hubs=["app/odd.py", "app/p.py"],
    )
    top = [a for a in find_anomalies(profile, top=10)
           if a["module"] == "app/odd.py"][0]
    lacks_clause = [c for c in top["why"].split(";") if "lacks" in c][0]
    # Exactly three backticked typical signals named (3 `tag` pairs == 6 backticks).
    assert lacks_clause.count("`") == 6


def test_deviation_floor_drops_on_pattern_modules():
    """Modules at/under DEVIATION_FLOOR are dropped (``deviation < FLOOR``).

    Every surfaced anomaly clears the floor; a perfectly on-pattern module never
    appears. Pins L195 ``deviation < DEVIATION_FLOOR`` boundary (< -> <=).
    """
    from app.engine.anomaly_discovery import DEVIATION_FLOOR
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b", "c", "d"],
        untested_modules=["a", "b", "c", "d"],
        debt_marker_modules=["app/odd.py"],
    )
    anomalies = find_anomalies(profile, top=99)
    assert all(a["deviation"] >= DEVIATION_FLOOR for a in anomalies)
    # The four on-pattern modules (identical fingerprint) never surface.
    surfaced = {a["module"] for a in anomalies}
    assert surfaced == {"app/odd.py"}


def test_module_at_exactly_the_floor_is_kept():
    """A module whose deviation equals DEVIATION_FLOOR exactly is KEPT.

    The guard is ``deviation < DEVIATION_FLOOR`` (strictly below is dropped), so
    a module sitting precisely ON the floor survives. Three modules each carrying
    only the shared ``security`` signal (rarity 0.25, breadth 0) land on
    deviation == 0.15 == DEVIATION_FLOOR. Pins L195 boundary < -> <= (which would
    drop the on-floor modules).
    """
    from app.engine.anomaly_discovery import DEVIATION_FLOOR
    assert DEVIATION_FLOOR == 0.15
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b", "c"],
        untested_modules=["d"],
    )
    anomalies = find_anomalies(profile, top=99)
    surfaced = {a["module"]: a["deviation"] for a in anomalies}
    # a, b, c each sit exactly on the floor and must be retained.
    for mod in ("a", "b", "c"):
        assert surfaced[mod] == DEVIATION_FLOOR


def test_deviation_and_rarity_rounded_to_three_places():
    """Deviation and rarity are rounded to exactly THREE decimals.

    The wide module's underlying rarity is 0.5625 and deviation 0.7375; rounded
    to 3 places they are 0.562 and 0.738 — distinct from a 4-place rounding
    (0.5625 / 0.7375). Pins L200/L201 ``round(..., 3)`` (4 would expose a fourth
    digit) AND L222 ``abs(b - median)`` (+ would inflate max_gap and shrink the
    breadth part, moving deviation off 0.738).
    """
    profile = ProjectProfile(
        root=".",
        untested_modules=["m1", "m2", "m3", "app/wide.py"],
        security_finding_modules=["app/wide.py"],
        fragile_modules=["app/wide.py"],
        debt_marker_modules=["app/wide.py"],
    )
    wide = [a for a in find_anomalies(profile)
            if a["module"] == "app/wide.py"][0]
    assert wide["rarity"] == 0.562
    assert wide["deviation"] == 0.738


def test_default_top_caps_at_five():
    """The default ``top`` is 5: at most five anomalies without an explicit cap.

    Six clearly-deviant modules must yield exactly five by default. Pins L206
    ``top: int = 5`` (6 would return a sixth).
    """
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["base1", "base2", "base3", "base4"],
        untested_modules=["base1", "base2", "base3", "base4"],
        fragile_modules=["x1"],
        debt_marker_modules=["x2"],
        modernizable_modules=["x3"],
        symbol_hubs=["x4"],
        mutable_default_modules=["x5"],
        sensitive_paths=["x6"],
    )
    assert len(find_anomalies(profile)) == 5


def test_top_one_returns_exactly_one_anomaly():
    """``top=1`` returns exactly one anomaly (not zero).

    Pins L215 number ``top <= 0`` (0 -> 1 would make ``top <= 1`` swallow the
    single result).
    """
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b", "c", "d"],
        untested_modules=["a", "b", "c"],
        debt_marker_modules=["app/odd.py"],
    )
    assert len(find_anomalies(profile, top=1)) == 1


def test_exactly_min_modules_still_produces_anomalies():
    """A codebase of EXACTLY MIN_MODULES modules is analysed, not abstained.

    Three tagged modules (the minimum) with one outlier must surface it. Pins
    L218 ``len(profiles) < MIN_MODULES`` boundary (< -> <= would abstain at 3).
    """
    from app.engine.anomaly_discovery import MIN_MODULES
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b"],
        untested_modules=["a", "b"],
        debt_marker_modules=["app/odd.py"],
    )
    assert len(module_profiles(profile)) == MIN_MODULES == 3
    anomalies = find_anomalies(profile)
    assert anomalies
    assert anomalies[0]["module"] == "app/odd.py"


def test_dominant_pattern_typical_needs_strict_majority():
    """``typical`` is the signals a STRICT majority carry (``n * 2 > count``).

    With 4 modules, a signal on exactly 2 (half) is NOT typical; one on 3 is.
    Guards the strict-majority comparison in ``dominant_pattern``.
    """
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a", "b", "c"],          # 3 of 4 -> typical
        untested_modules=["a", "b"],                        # 2 of 4 -> NOT typical
        debt_marker_modules=["a", "b", "c", "d"],           # 4 of 4 -> typical
    )
    norm = dominant_pattern(module_profiles(profile))
    assert norm["modules"] == 4
    assert norm["typical"] == {"security", "debt"}
    assert "untested" not in norm["typical"]


# =========================================================================== #
# temporal_discovery — trend classification + co-change support thresholds
# =========================================================================== #

_ENV = {
    "GIT_AUTHOR_NAME": "Apex", "GIT_AUTHOR_EMAIL": "apex@example.com",
    "GIT_COMMITTER_NAME": "Apex", "GIT_COMMITTER_EMAIL": "apex@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=repo, env={"PATH": os.environ.get("PATH", ""), **_ENV},
        check=True, capture_output=True, text=True,
    )


def _commit(repo: Path, n: int, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"commit {n}")


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    return repo


def test_trend_exact_tie_is_stable_not_accelerating():
    """``_trend`` classifies an exact recent==older tie as STABLE.

    Pins L192 (``recent > older`` > -> >=) and L194 (``recent < older``
    < -> <= and < -> >=): only a STRICT majority either way moves off "stable".
    """
    assert _trend(2, 2) == "stable"
    assert _trend(3, 2) == "accelerating"
    assert _trend(2, 3) == "cooling"


def test_trend_returns_each_label_literally():
    """Each ``_trend`` branch returns its own non-None label.

    Pins L195 (``return _TREND_COOLING`` -> None) and L196
    (``return _TREND_STABLE`` -> None): a flattened return would collapse two of
    the three verdicts to ``None``.
    """
    assert _trend(0, 5) == "cooling"
    assert _trend(4, 4) == "stable"
    assert _trend(5, 0) == "accelerating"
    # All three are distinct, non-None strings.
    assert len({_trend(5, 0), _trend(4, 4), _trend(0, 5)}) == 3


def test_cochange_group_surfaces_at_exactly_two_supporting_commits(tmp_path):
    """A pair co-changing exactly twice clears the support floor.

    The floor is ``cochanges >= _MIN_COCHANGES`` with ``_MIN_COCHANGES == 2``.
    A pair seen in exactly two commits must surface. Pins L59 (constant 2 -> 3
    would require three) and L231 (>= -> > would require three).
    """
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {"app/a.py": "0\n", "app/b.py": "0\n"})
    _commit(repo, 1, {"app/a.py": "1\n", "app/b.py": "1\n"})
    groups = file_evolution(str(repo))["cochange_groups"]
    assert groups == [{"a": "app/a.py", "b": "app/b.py", "cochanges": 2}]


def test_fifty_file_commit_kept_but_fifty_one_dropped(tmp_path):
    """A 50-file commit is analysed; a 51-file mega-commit is ignored.

    ``_MAX_COMMIT_FILES == 50`` and the keep test is ``len <= _MAX_COMMIT_FILES``.
    Pins L55 (50 -> 51 would keep the mega-commit) and L136 col-41
    (``<= _MAX_COMMIT_FILES`` boundary <= -> < would drop the 50-file commit).
    """
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {f"app/m{i}.py": "x\n" for i in range(50)})   # kept
    _commit(repo, 1, {f"big/b{i}.py": "y\n" for i in range(51)})   # dropped
    mods = {r["module"] for r in file_evolution(str(repo))["frequency"]}
    # All 50 files of the kept commit are present.
    assert sum(1 for m in mods if m.startswith("app/m")) == 50
    # No file from the 51-file mega-commit leaks in.
    assert not any(m.startswith("big/") for m in mods)


def test_max_commits_one_reads_a_single_commit(tmp_path):
    """``max_commits=1`` truncates to one commit (it does not abstain).

    Pins L100 number ``max_commits <= 0`` (0 -> 1 would make ``<= 1`` abstain at
    1). With one commit there is no recent/older split, but ``file_evolution``
    still reports that single commit's snapshot.
    """
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {"app/x.py": "0\n"})
    _commit(repo, 1, {"app/y.py": "1\n"})
    out = file_evolution(str(repo), max_commits=1)
    assert out["commits"] == 1


def test_emerging_hotspots_sorted_by_acceleration_delta(tmp_path):
    """Hotspots lead by the largest recent-minus-older delta.

    File ``h`` (recent 4, older 0; delta 4) outranks file ``g`` (recent 3, older
    2; delta 1) even though ``g`` has the larger recent+older SUM. Pins L278
    ``-(recent - older)`` (- -> + would order by the sum and swap them).
    """
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {"app/g.py": "0\n"})
    _commit(repo, 1, {"app/g.py": "1\n"})
    _commit(repo, 2, {"z/z.py": "2\n"})
    _commit(repo, 3, {"z/z.py": "3\n"})
    _commit(repo, 4, {"z/z.py": "4\n"})
    _commit(repo, 5, {"z/z.py": "5\n"})
    _commit(repo, 6, {"app/g.py": "6\n", "app/h.py": "6\n"})
    _commit(repo, 7, {"app/g.py": "7\n"})
    _commit(repo, 8, {"app/g.py": "8\n"})
    _commit(repo, 9, {"app/h.py": "9\n"})
    _commit(repo, 10, {"app/h.py": "10\n"})
    _commit(repo, 11, {"app/h.py": "11\n"})
    from app.engine.temporal_discovery import emerging_hotspots
    rows = emerging_hotspots(str(repo))
    order = [r["module"] for r in rows]
    assert order.index("app/h.py") < order.index("app/g.py")
    h = next(r for r in rows if r["module"] == "app/h.py")
    g = next(r for r in rows if r["module"] == "app/g.py")
    assert (h["recent"], h["older"]) == (4, 0)
    assert (g["recent"], g["older"]) == (3, 2)


def test_spreading_pairs_default_top_caps_at_five(tmp_path):
    """``spreading_pairs`` returns at most five pairs by default.

    Six strengthening pairs must trim to five. Pins L283 ``top: int = 5``.
    """
    repo = _init_repo(tmp_path)
    pair_files = [("app/a.py", "app/b.py"), ("app/c.py", "app/d.py"),
                  ("app/e.py", "app/f.py"), ("app/g.py", "app/h.py"),
                  ("app/i.py", "app/j.py"), ("app/k.py", "app/l.py")]
    # Older half: enough non-co-changing filler that every pair commit lands in
    # the recent half. 13 filler + 12 pair commits = 25, half=12 => recent half
    # is exactly the 12 newest (all pair) commits, older half is the 13 fillers.
    n = 0
    for _ in range(13):
        _commit(repo, n, {"z/z.py": f"{n}\n"})
        n += 1
    for first, second in pair_files:
        for _ in range(2):  # two recent co-changes each => total 2, recent 2, older 0
            _commit(repo, n, {first: f"{n}\n", second: f"{n}\n"})
            n += 1
    assert len(spreading_pairs(str(repo))) == 5


def test_spreading_pair_total_uses_recent_plus_older(tmp_path):
    """A pair's ``cochanges`` total is recent PLUS older, and gates the floor.

    Pair (a,b) has recent 2, older 1 => total 3 (clears the floor); its reported
    ``cochanges`` is 3. Pins L313 ``total = r + o`` (- would give 1 and drop the
    pair below the floor). Pair (s,t) is recent 1 / older 1 and is excluded.
    Pins L314 ``r > o`` boundary (> -> >= would admit the tie) and the
    ``and`` connective (or would admit (s,t) on the total alone).
    """
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {"app/a.py": "0\n", "app/b.py": "0\n"})   # ab older 1
    _commit(repo, 1, {"app/s.py": "1\n", "app/t.py": "1\n"})   # st older 1
    _commit(repo, 2, {"z/z.py": "2\n"})
    _commit(repo, 3, {"z/z.py": "3\n"})
    _commit(repo, 4, {"z/z.py": "4\n"})
    _commit(repo, 5, {"app/a.py": "5\n", "app/b.py": "5\n"})   # ab recent 1
    _commit(repo, 6, {"app/a.py": "6\n", "app/b.py": "6\n"})   # ab recent 2
    _commit(repo, 7, {"app/s.py": "7\n", "app/t.py": "7\n"})   # st recent 1
    _commit(repo, 8, {"z/z.py": "8\n"})
    _commit(repo, 9, {"z/z.py": "9\n"})
    pairs = spreading_pairs(str(repo))
    by_pair = {(p["a"], p["b"]): p for p in pairs}
    assert ("app/a.py", "app/b.py") in by_pair
    ab = by_pair[("app/a.py", "app/b.py")]
    assert (ab["recent"], ab["older"], ab["cochanges"]) == (2, 1, 3)
    # The recent==older pair never strengthens, so it is excluded.
    assert ("app/s.py", "app/t.py") not in by_pair


def test_spreading_pair_floor_at_exactly_two_total(tmp_path):
    """A pair with total exactly two (recent 2, older 0) clears the floor.

    Pins L314 ``total >= _MIN_COCHANGES`` boundary (>= -> > would require three).
    """
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {"app/x.py": "0\n"})
    _commit(repo, 1, {"app/x.py": "1\n"})
    _commit(repo, 2, {"app/a.py": "2\n", "app/b.py": "2\n"})
    _commit(repo, 3, {"app/a.py": "3\n", "app/b.py": "3\n"})
    pairs = spreading_pairs(str(repo))
    ab = [p for p in pairs if (p["a"], p["b"]) == ("app/a.py", "app/b.py")]
    assert len(ab) == 1
    assert ab[0]["cochanges"] == 2


def test_spreading_pairs_sorted_by_strengthening_delta(tmp_path):
    """Pairs lead by largest recent-minus-older delta, not by raw total.

    Pair (a,b) strengthens by delta 3 (recent 3 / older 0) and must outrank pair
    (c,d) which strengthens by delta 1 (recent 3 / older 2) despite (c,d)'s
    larger total. Pins L318 ``-(recent - older)`` (- -> + would order by the sum
    and swap them).
    """
    repo = _init_repo(tmp_path)
    _commit(repo, 0, {"app/c.py": "0\n", "app/d.py": "0\n"})   # cd older
    _commit(repo, 1, {"app/c.py": "1\n", "app/d.py": "1\n"})   # cd older
    _commit(repo, 2, {"z/z.py": "2\n"})
    _commit(repo, 3, {"z/z.py": "3\n"})
    _commit(repo, 4, {"z/z.py": "4\n"})
    _commit(repo, 5, {"z/z.py": "5\n"})
    _commit(repo, 6, {"app/a.py": "6\n", "app/b.py": "6\n"})   # ab recent
    _commit(repo, 7, {"app/a.py": "7\n", "app/b.py": "7\n"})   # ab recent
    _commit(repo, 8, {"app/a.py": "8\n", "app/b.py": "8\n"})   # ab recent
    _commit(repo, 9, {"app/c.py": "9\n", "app/d.py": "9\n"})   # cd recent
    _commit(repo, 10, {"app/c.py": "10\n", "app/d.py": "10\n"})  # cd recent
    _commit(repo, 11, {"app/c.py": "11\n", "app/d.py": "11\n"})  # cd recent
    pairs = spreading_pairs(str(repo))
    order = [(p["a"], p["b"]) for p in pairs]
    assert order.index(("app/a.py", "app/b.py")) < order.index(("app/c.py", "app/d.py"))
    ab = next(p for p in pairs if (p["a"], p["b"]) == ("app/a.py", "app/b.py"))
    cd = next(p for p in pairs if (p["a"], p["b"]) == ("app/c.py", "app/d.py"))
    assert (ab["recent"], ab["older"]) == (3, 0)
    assert (cd["recent"], cd["older"]) == (3, 2)


# =========================================================================== #
# rule_synthesis — shape keys, support threshold, descriptor wiring, bounding
# =========================================================================== #

_AUGMENT_SOURCES = {
    "a.py": "a = a + 1\n",
    "b.py": "count = count + 5\n",
    "c.py": "total = total + 2\n",
}


def test_shape_key_attribute_returns_nested_tag():
    """``_shape_key`` renders an attribute access as ``A(...)``, never ``None``.

    Pins L49 ``return f"A(...)"`` -> None: the attribute branch must produce a
    concrete nested key so attribute-bearing statements form a real pattern.
    """
    node = ast.parse("x = a.b\n").body[0].value
    assert _shape_key(node) == "A(N)"
    deep = ast.parse("x = a.b.c\n").body[0].value
    assert _shape_key(deep) == "A(A(N))"


def test_min_support_one_admits_single_recurrence_threshold(tmp_path):
    """``min_support=1`` admits any mined shape (>= 1 site).

    Pins L108 ``min_support < 1`` boundary (< -> <= AND 1 -> 2 both make
    ``min_support == 1`` wrongly abort to ``[]``).
    """
    sources = {"a.py": "a = a + 1\n", "b.py": "b = b + 1\n", "c.py": "c = c + 1\n"}
    patterns = mine_recurring_patterns(sources, min_support=1)
    assert patterns
    assert max(p["support"] for p in patterns) == 3


def test_suggested_name_empty_slug_falls_back_to_pattern():
    """An all-punctuation shape head falls back to the ``pattern`` slug.

    Pins L134 ``slug.strip("_") or "pattern"`` (or -> and would yield the empty
    slug, producing ``synthesised__rule``).
    """
    assert _suggested_name("___") == "synthesised_pattern_rule"
    assert _suggested_name("[x]") == "synthesised_pattern_rule"


def test_suggested_name_uses_leading_structural_tag():
    """The suggested name slug comes from the shape's LEADING tag (index 0).

    Pins L132 ``split("[", 1)[0]`` index (0 -> 1 would slug the tail, e.g.
    ``synthesised_n_rule`` instead of ``synthesised_if_rule``).
    """
    assert _suggested_name("If[N]") == "synthesised_if_rule"
    assert _suggested_name("Assign[N,N]") == "synthesised_assign_rule"


def test_descriptor_support_defaults_to_zero_when_absent():
    """A descriptor for a pattern lacking ``support`` reports support 0.

    Pins L148 ``int(pattern.get("support", 0))`` default (0 -> 1 would invent a
    phantom support count).
    """
    rule = synthesise_candidate_rule({"shape": "If[N]", "example_sites": []})
    assert rule["support"] == 0
    assert "recurs across 0 sites" in rule["rationale"]


def test_propose_rules_default_top_is_three():
    """``propose_rules`` returns at most three descriptors by default.

    Four distinct high-support shapes must trim to three. Pins L170
    ``top: int = 3`` (4 would return a fourth).
    """
    sources = {}
    # Four distinct recurring shapes (attribute-depth varies the key), 3 sites each.
    for depth in range(4):
        chain = "a" + ".b" * depth
        for k in range(3):
            sources[f"d{depth}_{k}.py"] = f"x = {chain}\n"
    assert len(propose_rules(sources)) == 3


def test_propose_rules_top_one_returns_one():
    """``propose_rules(top=1)`` returns exactly one descriptor.

    Pins L177 ``top < 1`` boundary (< -> <= AND 1 -> 2 both make ``top == 1``
    wrongly abort to ``[]``).
    """
    rules = propose_rules(_AUGMENT_SOURCES, top=1)
    assert len(rules) == 1


def test_mined_shapes_capped_at_sixty_four():
    """At most ``_MAX_SHAPES`` (64) distinct shapes are retained.

    Seventy distinct recurring shapes must trim to 64. Pins L26
    ``_MAX_SHAPES = 64`` (65 would retain a 65th).
    """
    sources = {}
    for depth in range(70):
        chain = "a" + ".b" * depth
        for k in range(3):
            sources[f"d{depth}_{k}.py"] = f"x = {chain}\n"
    patterns = mine_recurring_patterns(sources)
    assert len(patterns) == 64
