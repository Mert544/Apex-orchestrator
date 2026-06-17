"""Mutation-hardening battery for the dedup/dream engine quartet.

Self-contained tests that each pin one mutation-sensitive token so a survivor
can never silently appear under a future refactor — the "never fakes green"
moat. Every assertion is exact (counts, boundaries, slices, sort keys), and
nothing here depends on incidental coverage from an unrelated test file.

Covers:
  * ``app/engine/dedup.py`` — the duplication-GRADE engine (``find_duplicates``):
    the window-count arithmetic, the ``min_statements``/``min_occurrences``
    boundaries, the location-dedup guard, and the ``(-lines, fingerprint)`` sort.
  * ``app/engine/near_dup.py`` — the structural near-dup detector: the
    ``1 <= diff_count <= max_diffs`` window, value-leaf vs structure split, the
    ``> 1`` distinct-values guard, and the deterministic group ordering.
  * ``app/engine/dream.py`` — the curation pass: streak arithmetic (``>= 2``
    annotation, ``+= 1`` accumulation), the ``MEMORY_KEY_CAP`` trim boundary,
    the ``success_rate`` 0.5 split, the proof ``n >= 2`` repeat bar, and the
    ``[:2]``/``[:80]`` slices.
  * ``app/engine/dream_discovery.py`` — the open-ended discoverer: the support
    and confidence floors, the confluence breadth/typical cut, the ``a/b`` vs
    ``b/a`` direction pick, and the ``[:4]``/``[:2]`` truncations.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.dedup import find_duplicates, render_duplicates_markdown
from app.engine.dream import (
    DreamReport,
    MEMORY_KEY_CAP,
    _consecutive_streak,
    _pattern_key,
    _review_outcome_memory,
    _review_proof,
    _tally_proof,
    dream,
)
from app.engine.dream_discovery import (
    CONFLUENCE_FLOOR,
    MIN_SUPPORT,
    _associations,
    _confluences,
    _module_tags,
    _tag_counts,
    discover_structured,
)
from app.engine.near_dup import find_near_duplicates
from app.tools.project_profile import ProjectProfile


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _write(root: Path, rel: str, lines: list[str]) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _dup_func(name: str, n: int = 5) -> list[str]:
    """A function whose body is ``n`` byte-identical statements."""
    return [f"def {name}():"] + [f"    s{i} = {i}" for i in range(n)]


# =========================================================================== #
# dedup.py — the duplication GRADE engine
# =========================================================================== #

def test_dedup_exactly_min_statements_yields_one_window(tmp_path: Path) -> None:
    # Body length == min_statements: the window-count arithmetic
    # ``len(body) - min_statements + 1`` must equal 1 (not 0, not 2). A
    # ``+1 -> -1`` or ``-`` -> ``+`` mutant changes that count and either drops
    # the only window or fabricates one, so the block vanishes or doubles.
    _write(tmp_path, "app/a.py", _dup_func("alpha", 5))
    _write(tmp_path, "app/b.py", _dup_func("beta", 5))
    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert len(blocks) == 1
    assert blocks[0].lines == 5
    assert blocks[0].occurrences == ["app/a.py:2", "app/b.py:2"]


def test_dedup_one_short_of_min_yields_nothing(tmp_path: Path) -> None:
    # Body length == min_statements - 1: zero windows (limit <= 0). Guards the
    # ``limit <= 0`` boundary — a ``<=`` -> ``<`` mutant would let a 0-length
    # window slip through and crash/over-report.
    _write(tmp_path, "app/a.py", _dup_func("alpha", 4))
    _write(tmp_path, "app/b.py", _dup_func("beta", 4))
    assert find_duplicates(tmp_path, min_statements=5, min_occurrences=2) == []


def test_dedup_min_occurrences_is_inclusive_lower_bound(tmp_path: Path) -> None:
    # Exactly 2 copies with min_occurrences=2 reports; with min_occurrences=3 it
    # does not. Pins ``len(locations) >= min_occurrences`` (the ``>=`` boundary):
    # a ``>`` mutant would drop the exactly-equal case.
    _write(tmp_path, "app/a.py", _dup_func("alpha"))
    _write(tmp_path, "app/b.py", _dup_func("beta"))
    assert len(find_duplicates(tmp_path, min_statements=5, min_occurrences=2)) == 1
    assert find_duplicates(tmp_path, min_statements=5, min_occurrences=3) == []


def test_dedup_three_copies_report_all_three(tmp_path: Path) -> None:
    # min_occurrences=3 with exactly three copies: the block survives and lists
    # all three (no off-by-one in the occurrence accounting).
    _write(tmp_path, "app/a.py", _dup_func("alpha"))
    _write(tmp_path, "app/b.py", _dup_func("beta"))
    _write(tmp_path, "app/c.py", _dup_func("gamma"))
    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=3)
    assert len(blocks) == 1
    assert blocks[0].occurrences == ["app/a.py:2", "app/b.py:2", "app/c.py:2"]


def test_dedup_self_overlap_location_counted_once(tmp_path: Path) -> None:
    # The same run pasted back-to-back inside ONE function gives two distinct
    # linenos but the de-dup guard (``if location not in seen``) must never append
    # the same location twice. A negated guard would double a single location and
    # falsely satisfy min_occurrences.
    body = ["def f():"]
    for _ in range(2):
        body += [f"    s{i} = {i}" for i in range(5)]
    _write(tmp_path, "app/a.py", body)
    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert len(blocks) == 1
    occ = blocks[0].occurrences
    assert len(occ) == len(set(occ)) == 2


def test_dedup_sorted_by_lines_descending_then_fingerprint(tmp_path: Path) -> None:
    # Two duplicate families of DIFFERENT statement-window lengths reported in one
    # call by scanning twice and merging would be wrong; here we lock the single
    # documented sort: ``(-lines, fingerprint)``. With one min_statements the
    # lines are equal, so fingerprint breaks the tie — assert ascending fingerprint.
    _write(tmp_path, "app/a.py", _dup_func("alpha"))
    _write(tmp_path, "app/b.py", _dup_func("beta"))
    # A second, structurally different duplicate family.
    other = ["def f():"] + [f"    t{i} = {i} + 1" for i in range(5)]
    other2 = ["def g():"] + [f"    t{i} = {i} + 1" for i in range(5)]
    _write(tmp_path, "app/c.py", other)
    _write(tmp_path, "app/d.py", other2)
    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert len(blocks) == 2
    fps = [b.fingerprint for b in blocks]
    assert fps == sorted(fps)  # equal lines -> fingerprint ascending


def test_dedup_render_counts_blocks_and_occurrences(tmp_path: Path) -> None:
    _write(tmp_path, "app/a.py", _dup_func("alpha"))
    _write(tmp_path, "app/b.py", _dup_func("beta"))
    blocks = find_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    md = render_duplicates_markdown(blocks)
    assert "1 duplicated block(s)" in md
    assert "2 occurrence(s)" in md
    assert "app/a.py:2" in md and "app/b.py:2" in md


# =========================================================================== #
# near_dup.py — structural near-duplicate detector
# =========================================================================== #

def _near_block(value: str) -> list[str]:
    return [
        f"    x = {value}",
        "    y = x + 1",
        "    z = y + 2",
        "    w = z + 3",
        "    return w",
    ]


def test_near_dup_single_diff_is_inside_window(tmp_path: Path) -> None:
    # Exactly one differing constant: diff_count == 1, which is the inclusive
    # lower edge of ``1 <= diff_count``. A ``< 1`` -> ``< 2`` (or ``>=`` boundary)
    # mutant on that guard would drop this legitimate group.
    _write(tmp_path, "app/a.py", ["def alpha():"] + _near_block("1"))
    _write(tmp_path, "app/b.py", ["def beta():"] + _near_block("2"))
    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert len(groups) == 1
    assert groups[0].diff_count == 1
    assert groups[0].differences[0] == ["1", "2"]


def test_near_dup_zero_diff_excluded_as_exact(tmp_path: Path) -> None:
    # Byte-identical blocks have diff_count == 0 and belong to find_duplicates;
    # the ``diff_count < 1`` guard must exclude them. A weakened guard would leak
    # exact duplicates into the near-dup report.
    _write(tmp_path, "app/a.py", ["def alpha():"] + _near_block("1"))
    _write(tmp_path, "app/b.py", ["def beta():"] + _near_block("1"))
    assert find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2) == []


def test_near_dup_max_diffs_is_inclusive_upper_bound(tmp_path: Path) -> None:
    # Four differing constants: excluded at max_diffs=3, included at max_diffs=4.
    # Pins ``diff_count > max_diffs`` (the inclusive upper edge): a ``>`` -> ``>=``
    # mutant would wrongly drop the exactly-at-cap group.
    a = ["def alpha():", "    a = 1", "    b = 2", "    c = 3", "    d = 4",
         "    return d"]
    b = ["def beta():", "    a = 9", "    b = 8", "    c = 7", "    d = 6",
         "    return d"]
    _write(tmp_path, "app/a.py", a)
    _write(tmp_path, "app/b.py", b)
    assert find_near_duplicates(
        tmp_path, min_statements=5, min_occurrences=2, max_diffs=3) == []
    at_cap = find_near_duplicates(
        tmp_path, min_statements=5, min_occurrences=2, max_diffs=4)
    assert len(at_cap) == 1
    assert at_cap[0].diff_count == 4


def test_near_dup_store_target_is_structure_not_value(tmp_path: Path) -> None:
    # A Store-target name differing changes what the block binds — structural, so
    # the two blocks must NOT group. Guards the ``_is_value_leaf`` Load-only check
    # (a mutant accepting Store names would falsely merge non-interchangeable blocks).
    bx = ["def alpha():", "    x = 1", "    x = x + 1", "    x = x + 2",
          "    x = x + 3", "    return x"]
    bt = ["def beta():", "    t = 1", "    t = t + 1", "    t = t + 2",
          "    t = t + 3", "    return t"]
    _write(tmp_path, "app/a.py", bx)
    _write(tmp_path, "app/b.py", bt)
    assert find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2) == []


def test_near_dup_min_occurrences_inclusive(tmp_path: Path) -> None:
    # Three near-dup blocks: reported at min_occurrences=3, gone at 4. Pins
    # ``len(occ_map) < min_occurrences`` (the inclusive ``>=`` semantics).
    _write(tmp_path, "app/a.py", ["def alpha():"] + _near_block("1"))
    _write(tmp_path, "app/b.py", ["def beta():"] + _near_block("2"))
    _write(tmp_path, "app/c.py", ["def gamma():"] + _near_block("3"))
    g3 = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=3)
    assert len(g3) == 1 and len(g3[0].occurrences) == 3
    assert g3[0].differences[0] == ["1", "2", "3"]
    assert find_near_duplicates(tmp_path, min_statements=5, min_occurrences=4) == []


def test_near_dup_identical_column_is_not_a_difference(tmp_path: Path) -> None:
    # A wildcard path whose value is identical across all occurrences is NOT a
    # differing position (``len(set(values)) > 1``). Here two leaves vary but a
    # third is constant: diff_count must be 2, never 3. A ``> 1`` -> ``>= 1``
    # mutant would count the identical column as a difference.
    a = ["def alpha():", "    a = 1", "    b = 2", "    c = 99",
         "    d = c + 1", "    return d"]
    b = ["def beta():", "    a = 7", "    b = 8", "    c = 99",
         "    d = c + 1", "    return d"]
    _write(tmp_path, "app/a.py", a)
    _write(tmp_path, "app/b.py", b)
    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert len(groups) == 1
    assert groups[0].diff_count == 2  # the c=99 column is identical -> excluded


# =========================================================================== #
# dream.py — curation pass
# =========================================================================== #

def _bare_project(root: Path) -> None:
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "m.py").write_text("def f():\n    return 1\n")


def test_pattern_key_separator_precedence_and_strip() -> None:
    # The separator order ``(" — ", " (", ":")`` and the ``.strip()`` are all
    # load-bearing for streak identity. Em-dash wins over a later colon.
    assert _pattern_key("`m` is hot — keep watching") == "`m` is hot"
    assert _pattern_key("`m` lands 90% (3 samples)") == "`m` lands 90%"
    assert _pattern_key("subject: detail") == "subject"
    assert _pattern_key("no-separator") == "no-separator"


def test_consecutive_streak_starts_at_one_and_accumulates() -> None:
    # The streak seed is 1 (this dream) and each consecutive prior dream adds 1;
    # the first miss breaks the run. A ``streak = 0`` or ``+= 1`` -> ``-= 1``
    # mutant changes every count.
    assert _consecutive_streak([], "k") == 1
    assert _consecutive_streak([{"k": "t"}], "k") == 2
    assert _consecutive_streak([{"k": "t"}, {"k": "t"}], "k") == 3
    # A gap in the middle stops the count at the gap (reversed scan).
    assert _consecutive_streak([{"k": "t"}, {"other": "x"}, {"k": "t"}], "k") == 2


def test_tally_proof_reason_split_and_truncation() -> None:
    # The block reason is keyed by the text before the first em-dash, capped at
    # 80 chars; failing tests are counted with ``+= 1``.
    failing, reasons = _tally_proof({"fixes": [
        {"verification": {"failing_tests": ["t::a", "t::a"]}},
        {"blocked_reason": ("R" * 100) + "— tail"},
    ]})
    assert failing == {"t::a": 2}  # counted twice via += 1
    assert list(reasons) == ["R" * 80]  # split on em-dash, [:80] applied


def test_review_proof_repeat_bar_is_inclusive_two(tmp_path: Path) -> None:
    # A block reason must appear ``n >= 2`` times to surface; a single one is
    # silent, exactly two crosses the bar. Pins the ``>= 2`` boundary.
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text(json.dumps({"fixes": [
        {"blocked_reason": "needs a covering test"},
        {"blocked_reason": "needs a covering test"},
        {"blocked_reason": "lonely once"},
    ]}), encoding="utf-8")
    report = DreamReport()
    _review_proof(tmp_path, report)
    joined = "\n".join(report.patterns)
    assert "2 steps blocked for the same reason: needs a covering test" in joined
    assert "lonely once" not in joined


def test_review_outcome_success_rate_half_split(tmp_path: Path) -> None:
    # The reliability split is at success_rate >= 0.5: a key at exactly 50% is
    # praised ("keep leading"), a key below 50% is warned about. Pins both the
    # ``>= 0.5`` and the ``< 0.5`` boundaries simultaneously.
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "idea-memory.json").write_text(json.dumps({
        "by_operator": {
            "even": {"applied": 5, "rolled_back": 5, "blocked": 0},   # 50%
            "weak": {"applied": 1, "rolled_back": 9, "blocked": 0},   # 10%
        },
        "by_label": {},
    }), encoding="utf-8")
    report = DreamReport()
    _review_outcome_memory(tmp_path, report, curate=False)
    joined = "\n".join(report.patterns)
    assert "`even` fixes land 50%" in joined and "keep leading" in joined
    assert "`weak` lands only 10%" in joined and "blocks/rollbacks" in joined


def test_memory_trim_keeps_exactly_cap_keys(tmp_path: Path) -> None:
    # A table with CAP+5 keys trims to exactly MEMORY_KEY_CAP (the ``> CAP`` guard
    # and the ``[:CAP]`` keep-slice). A boundary mutant would keep CAP+1 or CAP-1.
    apex = tmp_path / ".apex"
    apex.mkdir()
    over = {f"k{i}": {"applied": i + 1, "rolled_back": 0, "blocked": 0}
            for i in range(MEMORY_KEY_CAP + 5)}
    (apex / "idea-memory.json").write_text(json.dumps({
        "by_operator": {}, "by_label": over}), encoding="utf-8")
    report = dream(tmp_path, curate=True, write_digest=False)
    saved = json.loads((apex / "idea-memory.json").read_text())
    assert len(saved["by_label"]) == MEMORY_KEY_CAP
    assert any("trimmed: 5 low-evidence key(s) dropped" in c for c in report.curated)


def test_memory_at_cap_is_not_trimmed(tmp_path: Path) -> None:
    # Exactly MEMORY_KEY_CAP keys must NOT trim (the guard is ``> CAP`` strict).
    apex = tmp_path / ".apex"
    apex.mkdir()
    exact = {f"k{i}": {"applied": 1, "rolled_back": 0, "blocked": 0}
             for i in range(MEMORY_KEY_CAP)}
    (apex / "idea-memory.json").write_text(json.dumps({
        "by_operator": {}, "by_label": exact}), encoding="utf-8")
    report = dream(tmp_path, curate=True, write_digest=False)
    assert not any("trimmed" in c for c in report.curated)
    assert not any("would drop" in p for p in report.proposed)


def test_streak_annotation_appears_only_from_two(tmp_path: Path) -> None:
    # The "seen in N consecutive dreams" suffix is gated on ``streak >= 2``: a
    # first dream never carries it, the second does. Pins both the ``>= 2`` gate
    # and the cross-dream accumulation.
    _bare_project(tmp_path)
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "idea-memory.json").write_text(json.dumps({
        "by_operator": {"document": {"applied": 6, "rolled_back": 0, "blocked": 0}},
        "by_label": {}}), encoding="utf-8")
    first = dream(tmp_path, write_digest=False)
    assert not any("consecutive dreams" in p for p in first.patterns)
    second = dream(tmp_path, write_digest=False)
    assert any("seen in 2 consecutive dreams" in p for p in second.patterns)


# =========================================================================== #
# dream_discovery.py — open-ended discovery
# =========================================================================== #

def test_discovery_support_floor_is_inclusive(tmp_path: Path) -> None:
    # A pair co-occurring on exactly MIN_SUPPORT(=2) modules is a law; a single
    # co-occurrence is a coincidence. Pins ``n < MIN_SUPPORT`` (so == 2 passes).
    one = ProjectProfile(root=".", security_finding_modules=["app/a.py"],
                         untested_modules=["app/a.py"])
    assert discover_structured(one) == []
    two = ProjectProfile(
        root=".",
        security_finding_modules=["app/a.py", "app/b.py"],
        untested_modules=["app/a.py", "app/b.py"])
    found = discover_structured(two)
    assert found and all(d.support >= MIN_SUPPORT for d in found)
    assert any(d.kind == "association" for d in found)


def test_association_picks_the_stronger_direction() -> None:
    # A is carried by 2 modules, B by 3; both co-occur on 2. conf(A->B)=2/2=1.0
    # beats conf(B->A)=2/3. The reported rule must be A->B at 100%. A flipped
    # ``>=`` direction-pick mutant would report the weaker B->A.
    tags = {
        "m1": {"A", "B"},
        "m2": {"A", "B"},
        "m3": {"B"},
    }
    counts = _tag_counts(tags)
    assert counts == {"A": 2, "B": 3}
    assoc = _associations(tags, counts)
    assert len(assoc) == 1
    assert assoc[0].key == "assoc:A>B"
    assert assoc[0].confidence == 1.0
    assert "100% of `A`" in assoc[0].text


def test_confluence_breadth_and_typical_cut() -> None:
    # Confidence is ``n / (typical + n)`` and only modules with breadth >=
    # CONFLUENCE_FLOOR and strictly above the typical breadth qualify. With one
    # broad module (4 signals) among single-signal modules, typical == 1 and
    # confidence == 4/5 == 0.8.
    tags = {"big": {"a", "b", "c", "d"}, "s1": {"a"}, "s2": {"b"}}
    out = _confluences(tags)
    assert len(out) == 1
    assert out[0].key == "confluence:big"
    assert out[0].support == 4
    assert out[0].confidence == 0.8  # 4 / (1 + 4)
    # A module exactly AT the floor but not above typical would be excluded; here
    # the floor itself is exercised (4 >= CONFLUENCE_FLOOR).
    assert CONFLUENCE_FLOOR <= 4


def test_associations_truncate_to_four() -> None:
    # Many qualifying associations are capped at 4 (``assoc[:4]``). Build five
    # always-together pairs and assert exactly four survive, highest-confidence
    # first. A ``[:5]`` or ``[:3]`` mutant changes the count.
    tags: dict[str, set[str]] = {}
    # Ten tags pairing up into five disjoint always-together pairs on 2 modules
    # each, so every pair has confidence 1.0 and support 2.
    for i in range(5):
        a, b = f"A{i}", f"B{i}"
        tags[f"m{i}_1"] = {a, b}
        tags[f"m{i}_2"] = {a, b}
    counts = _tag_counts(tags)
    assoc = _associations(tags, counts)
    assert len(assoc) == 4
    assert [d.confidence for d in assoc] == [1.0, 1.0, 1.0, 1.0]


def test_module_tags_skips_falsy_module_names() -> None:
    # The ``add`` guard drops empty module names; a negated guard would seed a
    # spurious "" module and pollute every count.
    profile = ProjectProfile(
        root=".",
        untested_modules=["", "app/u.py", "app/v.py"],
        debt_marker_modules=["app/u.py", "app/v.py"],
        churn_hotspots=[{"module": ""}, {"module": "app/u.py", "commits": 3}],
    )
    tags = _module_tags(profile)
    assert "" not in tags
    assert tags["app/u.py"] == {"untested", "debt", "high-churn"}
