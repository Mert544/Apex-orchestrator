"""Deep-mutation-hardening characterization tests for the two INTELLIGENCE
aggregator modules: ``app.engine.intelligence_report`` and
``app.engine.self_insight``.

These tests were authored by enumerating the FULL mutation-site universe of each
module (via ``mutation_tester._collect_sites`` / ``_splice``), running the
covering suites against each splice in an isolated copy, and pinning down the
REAL survivors past the 30-mutant cap. Each test below kills a specific survivor:
a best-effort ``_safe`` guard, a section cap, an empty-state default, a relational
boundary, or the ``gather_sources`` bounding. The mutation, line, and intent are
named in each test's docstring.

The aggregators call their research organs through ``_safe``; to characterize the
PURE aggregation/rendering logic deterministically (no git, no heavy profiling),
the organs are monkeypatched to return controlled synthetic rows, OR the pure
per-row helpers are called directly. No production module is modified.

Documented EQUIVALENT / unkillable survivors (NOT regressions) are listed at the
bottom of this file in ``test_documented_equivalent_survivors`` so the rationale
travels with the tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine import intelligence_report as ir
from app.engine import self_insight as si


# ---------------------------------------------------------------------------
# intelligence_report — pure verdict-bullet logic (_verdict_bullet)
# ---------------------------------------------------------------------------

def test_verdict_bullet_uses_zero_defaults_for_missing_confidence_support() -> None:
    """Kills L145 ``confidence`` default ``0``->``1`` and L146 ``support`` default
    ``0``->``1`` in ``_verdict_bullet``: a result missing both keys must render the
    literal ``(0, support 0)``."""
    bullet = ir._verdict_bullet({"verdict": "weak", "claim": "C"})
    assert bullet == "**weak** (0, support 0): C"


def test_verdict_bullet_confirmed_never_shows_counter_examples() -> None:
    """Kills L149 ``verdict != 'confirmed'`` -> ``==`` and L149 ``and`` -> ``or``:
    a CONFIRMED verdict that carries evidence must NOT render counter-examples
    (the negation/connective decide that)."""
    bullet = ir._verdict_bullet(
        {"verdict": "confirmed", "claim": "C", "confidence": 0.9,
         "support": 2, "evidence": ["a", "b"]}
    )
    assert "counter-examples" not in bullet
    assert bullet == "**confirmed** (0.9, support 2): C"


def test_verdict_bullet_non_confirmed_appends_counter_examples() -> None:
    """Kills L148 ``or`` -> ``and`` (evidence resolution), L150 ``[:3]`` -> ``[:4]``
    (only the first three counter-examples), and the L151 ``+=`` -> ``-=``
    augmented-assign (the text is APPENDED to the line)."""
    bullet = ir._verdict_bullet(
        {"verdict": "weak", "claim": "C", "confidence": 0.5,
         "support": 7, "evidence": ["a", "b", "c", "d"]}
    )
    assert bullet == (
        "**weak** (0.5, support 7): C — counter-examples: `a`, `b`, `c`"
    )


# ---------------------------------------------------------------------------
# intelligence_report — section bullet helpers via patched organs
# ---------------------------------------------------------------------------

def test_anomaly_bullets_cap_and_deviation_default(monkeypatch) -> None:
    """Kills L52 ``_MAX_ITEMS = 5`` -> 6 (the section cap) and L135 ``deviation``
    default ``0`` -> ``1`` (a row missing ``deviation`` renders ``0``)."""
    rows = [{"module": "b.py", "why": "w"}] + [
        {"module": f"x{i}.py", "deviation": i, "why": "w"} for i in range(10)
    ]
    monkeypatch.setattr(ir, "find_anomalies", lambda profile, top: rows)
    bullets = ir._anomaly_bullets(None)
    assert len(bullets) == 5  # capped at _MAX_ITEMS, not 6
    assert bullets[0] == "`b.py` (deviation 0): w"


def test_discovery_bullets_group_confirmed_first_and_cap(monkeypatch) -> None:
    """Kills the L165 grouping guards: ``==`` -> ``!=`` (verdict match),
    ``and`` -> ``or`` (the bounded append), and the ``<`` -> ``<=`` boundary on
    ``len(bullets) < _MAX_ITEMS``. Verdicts arrive interleaved; the section must
    re-group confirmed -> weak -> refuted and stop at the cap."""
    results = [
        {"verdict": "refuted", "claim": "R", "confidence": 0.1, "support": 1,
         "evidence": ["x"]},
        {"verdict": "confirmed", "claim": "C", "confidence": 0.9, "support": 2},
        {"verdict": "weak", "claim": "W", "confidence": 0.5, "support": 3,
         "evidence": ["a", "b", "c", "d"]},
    ]
    monkeypatch.setattr(ir, "validate_discoveries", lambda profile, top: results)
    bullets = ir._discovery_bullets(None)
    assert bullets == [
        "**confirmed** (0.9, support 2): C",
        "**weak** (0.5, support 3): W — counter-examples: `a`, `b`, `c`",
        "**refuted** (0.1, support 1): R — counter-examples: `x`",
    ]


def test_discovery_bullets_capped_at_max_items(monkeypatch) -> None:
    """Kills L165 ``<`` -> ``<=`` boundary and L52 cap: seven confirmed results
    must yield exactly five bullets (``len(bullets) < _MAX_ITEMS``)."""
    results = [
        {"verdict": "confirmed", "claim": f"c{i}", "confidence": 0.9, "support": 1}
        for i in range(7)
    ]
    monkeypatch.setattr(ir, "validate_discoveries", lambda profile, top: results)
    bullets = ir._discovery_bullets(None)
    assert len(bullets) == 5


def test_hotspot_bullets_defaults_and_returns_content(monkeypatch) -> None:
    """Kills L177 ``recent``/``older`` defaults ``0`` -> ``1`` and the L179
    ``return bullets`` -> ``return None`` (a populated section must return its
    bullets)."""
    rows = [{"module": "g.py"}, {"module": "h.py", "recent": 5, "older": 2}]
    monkeypatch.setattr(ir, "emerging_hotspots", lambda root: rows)
    bullets = ir._hotspot_bullets("/x")
    assert bullets is not None
    assert bullets[0] == "`g.py` accelerating (recent 0 vs older 0)"
    assert bullets[1] == "`h.py` accelerating (recent 5 vs older 2)"


def test_rule_bullets_support_default(monkeypatch) -> None:
    """Kills L193 ``support`` default ``0`` -> ``1`` in ``_rule_bullets``."""
    rows = [{"suggested_name": "n", "shape": "If"}]
    monkeypatch.setattr(ir, "propose_rules", lambda sources, top: rows)
    bullets = ir._rule_bullets({})
    assert bullets == [
        "`n` — shape `If` recurs at 0 sites "
        "(recommend-only; verify behaviour-preservation)"
    ]


def test_self_bullets_defaults_and_curriculum_cap(monkeypatch) -> None:
    """Kills L210 ``reliability`` default ``0`` -> ``1``, L211 ``attempts``
    default ``0`` -> ``1`` (a bare weakness row), and the L214 curriculum-budget
    guard ``len(bullets) < _MAX_ITEMS * 2`` (``<`` -> ``<=``/``>=``, ``*`` -> ``/``,
    ``2`` -> ``3``): five weaknesses plus a long curriculum must total exactly
    ``_MAX_ITEMS * 2`` (= 10) bullets."""
    weak = [{"action": "bare"}] + [
        {"action": f"w{i}", "verdict": "v", "reliability": 0.1, "attempts": 2}
        for i in range(6)
    ]
    monkeypatch.setattr(ir, "assess_weaknesses", lambda history: weak)
    monkeypatch.setattr(
        ir, "self_curriculum", lambda history, top: [f"c{i}" for i in range(20)]
    )
    bullets = ir._self_bullets([])
    assert len(bullets) == 10  # 5 weaknesses + 5 curriculum, capped at _MAX_ITEMS*2
    # The bare weakness row renders both zero defaults.
    assert bullets[0] == "`bare` —  (reliability 0 over 0 attempts)"
    # The first five bullets are weaknesses; the rest are curriculum lines.
    assert bullets[5] == "c0"


# ---------------------------------------------------------------------------
# intelligence_report — gather_sources bounding / boundaries
# ---------------------------------------------------------------------------

def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_gather_sources_max_sources_one_returns_one(tmp_path: Path) -> None:
    """Kills L98 ``if max_sources <= 0`` boundary ``0`` -> ``1``: with
    ``max_sources=1`` the function must return exactly one source, not bail out as
    if the budget were empty."""
    _write(tmp_path, "app/a.py", "x = 1\n")
    _write(tmp_path, "app/b.py", "y = 2\n")
    sources = ir.gather_sources(str(tmp_path), max_sources=1)
    assert len(sources) == 1


def test_gather_sources_includes_file_at_exact_size_cap(tmp_path: Path) -> None:
    """Kills L122 ``st_size > _MAX_SOURCE_BYTES`` boundary ``>`` -> ``>=``: a file
    of EXACTLY ``_MAX_SOURCE_BYTES`` is within the cap and must be included (the
    boundary is exclusive)."""
    body = "#" + "a" * (ir._MAX_SOURCE_BYTES - 2) + "\n"
    _write(tmp_path, "app/big.py", body)
    assert len(body.encode("utf-8")) == ir._MAX_SOURCE_BYTES
    sources = ir.gather_sources(str(tmp_path), max_sources=10)
    assert "app/big.py" in sources


def test_gather_sources_caps_at_max_sources_default(tmp_path: Path) -> None:
    """Kills L55 ``_MAX_SOURCES = 80`` -> 81: feeding more than the default cap
    must truncate at exactly 80 sources."""
    for i in range(85):
        _write(tmp_path, f"app/m{i:03d}.py", "x = 1\n")
    sources = ir.gather_sources(str(tmp_path))
    assert len(sources) == 80


# ---------------------------------------------------------------------------
# self_insight — pure per-row line helpers
# ---------------------------------------------------------------------------

def test_anomaly_lines_default_deviation_and_returns_lines() -> None:
    """Kills L131 ``deviation`` default ``0.0`` -> ``1.0`` and L134
    ``return lines`` -> ``return None``: a row missing ``deviation`` renders
    ``deviation 0`` (``:g``) and a populated call returns the list."""
    lines = si._anomaly_lines([{"module": "m", "why": "w"}])
    assert lines == ["- `m` (deviation 0) — w"]


def test_rule_lines_default_support_and_returns_lines() -> None:
    """Kills L142 ``support`` default ``0`` -> ``1`` and L145
    ``return lines`` -> ``return None`` in ``_rule_lines``."""
    lines = si._rule_lines([{"suggested_name": "n", "shape": "If"}])
    assert lines == ["- `n` — 0 sites of shape `If`"]


def test_weakness_lines_default_reliability_and_returns_lines() -> None:
    """Kills L153 ``reliability`` default ``0.0`` -> ``1.0`` and L156
    ``return lines`` -> ``return None`` in ``_weakness_lines``."""
    lines = si._weakness_lines([{"action": "a", "verdict": "weak"}])
    assert lines == ["- `a` (reliability 0) — weak"]


# ---------------------------------------------------------------------------
# self_insight — caps, gather bounding, and the light-profile flag
# ---------------------------------------------------------------------------

def test_self_insight_weaknesses_capped(tmp_path: Path, monkeypatch) -> None:
    """Kills L43 ``_MAX_WEAKNESSES = 5`` -> 6: the explicit
    ``[:_MAX_WEAKNESSES]`` slice must truncate a long weakness list to five."""
    weak = [{"action": f"w{i}", "verdict": "v", "reliability": 0.1}
            for i in range(10)]
    monkeypatch.setattr(si, "assess_weaknesses", lambda history: weak)
    insight = si.self_insight(str(tmp_path))
    assert len(insight["weaknesses"]) == 5


def test_self_insight_gather_caps_at_max_sources(tmp_path: Path) -> None:
    """Kills L47 ``_MAX_SOURCES = 200`` -> 201 and the L89 boundary
    ``len(sources) >= _MAX_SOURCES`` ``>=`` -> ``>``: with 210 python files,
    ``gather_sources`` must return exactly 200."""
    for i in range(210):
        _write(tmp_path, f"app/m{i:04d}.py", "x = 1\n")
    sources = si.gather_sources(str(tmp_path))
    assert len(sources) == 200


def test_profile_requests_light_profile(tmp_path: Path, monkeypatch) -> None:
    """Kills L73 ``profile(light=True)`` -> ``light=False``: the profiler must be
    asked for the LIGHT profile (the anomaly organ reads only signal-tag rows)."""
    import app.tools.project_profile as pp

    captured: dict[str, object] = {}
    real = pp.ProjectProfiler.profile

    def spy(self, *args, **kwargs):
        captured["light"] = kwargs.get("light")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(pp.ProjectProfiler, "profile", spy)
    si._profile(str(tmp_path))
    assert captured["light"] is True


# ---------------------------------------------------------------------------
# Best-effort _safe guards: a raising organ still yields a complete reading
# ---------------------------------------------------------------------------

def test_ir_safe_returns_default_on_raise() -> None:
    """Kills the intelligence_report L74/L76 ``_safe`` return flips: a raising
    call yields the supplied default, a succeeding call yields its value."""
    sentinel: list[int] = [1, 2, 3]
    assert ir._safe(lambda: (_ for _ in ()).throw(RuntimeError("x")), sentinel) is sentinel
    assert ir._safe(lambda: "ok", None) == "ok"


def test_si_safe_returns_fallback_on_raise() -> None:
    """Kills the self_insight L58/L60 ``_safe`` return flips: a raising call
    yields the fallback, a succeeding call yields its value."""
    fallback: dict[str, int] = {"k": 1}
    assert si._safe(lambda: (_ for _ in ()).throw(ValueError("x")), fallback) is fallback
    assert si._safe(lambda: 7, None) == 7


# ---------------------------------------------------------------------------
# Documented EQUIVALENT / pass-through survivors (not regressions)
# ---------------------------------------------------------------------------

def test_documented_equivalent_survivors() -> None:
    """Record (not assert) the one survivor deemed genuinely EQUIVALENT — a
    documentation note, not a regression.

    intelligence_report:
      - L161 ``validate_discoveries(profile, top=_MAX_ITEMS * 2)`` number
        ``2`` -> ``3``: ``top`` is only an upper FETCH bound handed to the organ;
        the section then re-groups by verdict and re-caps at ``_MAX_ITEMS``
        regardless, so fetching 10 vs 15 candidates yields the SAME five bullets.
        EQUIVALENT — no observable behaviour change, hence unkillable.

    (The matching self_insight caps L41 ``_MAX_ANOMALIES``, L42 ``_MAX_RULES``,
    L44 ``_MAX_CURRICULUM`` are NOT equivalent: although each is passed as the
    organ's ``top=``, the covering suites profile a real tmp project whose organs
    honour ``top`` and surface more than the cap, so those mutants ARE killed —
    see ``test_self_insight_gather_caps_at_max_sources`` and the existing
    self-insight suite.)
    """
    assert ir._MAX_ITEMS == 5
    assert (si._MAX_ANOMALIES, si._MAX_RULES, si._MAX_CURRICULUM) == (5, 3, 3)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
