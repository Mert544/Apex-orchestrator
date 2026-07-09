"""Extra coverage for ``app/engine/intelligence_report.py``: the test/fixture
skip and oversized-source guard in ``gather_sources``, the counter-examples
branch of a validated-discovery bullet, and the emerging-hotspot bullet body.
Deterministic — crafted inputs, no git/time/random.
"""

from __future__ import annotations

from pathlib import Path

from app.engine import intelligence_report as ir
from app.engine.intelligence_report import gather_sources


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_gather_sources_skips_test_files(tmp_path: Path) -> None:
    # iter_source_files yields test files (tests/ is not a skipped dir); the
    # is_test_or_fixture_path guard is what drops them from the shipped surface.
    _write(tmp_path, "app/a.py", "x = 1\n")
    _write(tmp_path, "tests/test_a.py", "y = 2\n")
    sources = gather_sources(str(tmp_path))
    assert "app/a.py" in sources
    assert "tests/test_a.py" not in sources


def test_gather_sources_skips_oversized(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ir, "_MAX_SOURCE_BYTES", 3)
    _write(tmp_path, "app/big.py", "x = 123456789\n")
    # The lone source exceeds the byte cap, so nothing is gathered.
    assert gather_sources(str(tmp_path)) == {}


def test_verdict_bullet_adds_counter_examples() -> None:
    bullet = ir._verdict_bullet({
        "verdict": "weak",
        "claim": "security implies untested",
        "confidence": "low",
        "support": 4,
        "evidence": ["app/a.py", "app/b.py", "app/c.py", "app/d.py"],
    })
    assert "**weak**" in bullet
    assert "counter-examples:" in bullet
    # only the first three counter-examples are surfaced.
    assert "`app/a.py`" in bullet
    assert "`app/d.py`" not in bullet


def test_verdict_bullet_confirmed_has_no_counter_examples() -> None:
    bullet = ir._verdict_bullet({
        "verdict": "confirmed",
        "claim": "c",
        "confidence": "high",
        "support": 6,
        "evidence": ["app/a.py"],
    })
    assert "counter-examples:" not in bullet


def test_hotspot_bullets_render_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        ir,
        "emerging_hotspots",
        lambda root: [{"module": "app/x.py", "recent": 5, "older": 1}],
    )
    bullets = ir._hotspot_bullets("/any/root")
    assert bullets == ["`app/x.py` accelerating (recent 5 vs older 1)"]
