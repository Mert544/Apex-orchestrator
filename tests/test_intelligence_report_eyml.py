"""Tests for the unified Apex Intelligence report (``intelligence_report``).

Cover the five sections rendering real content from a synthetic profile + tmp
root, the empty-project empty-state, determinism (byte-identical), and the
best-effort guard keeping the report complete when one organ raises.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine import intelligence_report as ir
from app.engine.intelligence_report import build_intelligence_report, gather_sources
from app.tools.project_profile import ProjectProfile


# A profile whose module fingerprints DEFY a dominant pattern (so anomalies fire)
# AND form a clean ``security -> untested`` association across enough modules that
# the hypothesis validator can confirm/refute it.
def _rich_profile(root: str) -> ProjectProfile:
    return ProjectProfile(
        root=root,
        # Six modules carry both security + untested -> a strong association.
        security_finding_modules=[f"app/m{i}.py" for i in range(6)],
        untested_modules=[f"app/m{i}.py" for i in range(6)] + ["app/lonely.py"],
        # One off-pattern module carrying a rare bundle of signals -> an anomaly.
        correctness_bug_modules=["app/odd.py"],
        fragile_modules=["app/odd.py"],
        debt_marker_modules=["app/odd.py"],
        hotspot_modules=["app/odd.py"],
    )


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# A source with the SAME structural micro-pattern repeated enough to be mined.
_RECURRING = "\n".join(
    f"def f{i}(x):\n    if x:\n        return x\n    return None\n" for i in range(4)
)


def _proof(outcome: str, action: str) -> dict:
    from app.engine.proof_of_fix import SCHEMA

    one = {"outcome": outcome, "finding": {"action": action},
           "verification": {"performed": True}}
    # Two attempts so the action clears self_assessment's _MIN_ATTEMPTS floor.
    return {"schema": SCHEMA, "generated_at": "2020-01-01", "fixes": [one, dict(one)]}


def test_sections_render_content(tmp_path: Path) -> None:
    import json

    _write(tmp_path, "app/a.py", _RECURRING)
    _write(tmp_path, "app/b.py", _RECURRING)
    apex = tmp_path / ".apex"
    apex.mkdir()
    (apex / "proof-of-fix.json").write_text(
        json.dumps(_proof("rolled_back", "harden_security")), encoding="utf-8"
    )

    profile = _rich_profile(str(tmp_path))
    report = build_intelligence_report(profile, str(tmp_path))

    assert report.startswith("# Apex Intelligence")
    for heading in (
        "## Anomalies", "## Validated discoveries", "## Emerging hotspots",
        "## Proposed fix-rules", "## Self-assessment",
    ):
        assert heading in report
    # Anomaly organ surfaced the off-pattern module.
    assert "app/odd.py" in report
    # Hypothesis organ surfaced a verdict.
    assert any(v in report for v in ("**confirmed**", "**weak**", "**refuted**"))
    # Rule synthesis surfaced a recommend-only descriptor.
    assert "recommend-only" in report
    # Self-assessment surfaced the weak action family.
    assert "harden_security" in report


def test_empty_project_empty_state(tmp_path: Path) -> None:
    profile = ProjectProfile(root=str(tmp_path))
    report = build_intelligence_report(profile, str(tmp_path))

    assert report.startswith("# Apex Intelligence")
    # Every section present, all in their empty state.
    assert report.count("## ") == 5
    assert report.count("_Nothing notable._") == 5


def test_deterministic_byte_identical(tmp_path: Path) -> None:
    _write(tmp_path, "app/a.py", _RECURRING)
    _write(tmp_path, "app/b.py", _RECURRING)
    profile = _rich_profile(str(tmp_path))
    first = build_intelligence_report(profile, str(tmp_path))
    second = build_intelligence_report(profile, str(tmp_path))
    assert first == second


def test_raising_organ_still_completes(tmp_path: Path, monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise RuntimeError("organ exploded")

    # Make the anomaly organ raise; the report must still carry all five sections.
    monkeypatch.setattr(ir, "find_anomalies", _boom)
    profile = _rich_profile(str(tmp_path))
    report = build_intelligence_report(profile, str(tmp_path))

    assert report.startswith("# Apex Intelligence")
    assert report.count("## ") == 5
    # The raising section degraded to empty-state, not an abort.
    assert "## Anomalies\n\n_Nothing notable._" in report


def test_every_organ_raising_still_valid(tmp_path: Path, monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    for name in (
        "find_anomalies", "validate_discoveries", "emerging_hotspots",
        "propose_rules", "assess_weaknesses", "self_curriculum",
        "load_proof_history", "gather_sources",
    ):
        monkeypatch.setattr(ir, name, _boom)
    report = build_intelligence_report(ProjectProfile(root=str(tmp_path)), str(tmp_path))
    assert report.startswith("# Apex Intelligence")
    assert report.count("_Nothing notable._") == 5


def test_gather_sources_bounded_and_sorted(tmp_path: Path) -> None:
    for i in range(5):
        _write(tmp_path, f"app/s{i}.py", "x = 1\n")
    # A test file must be excluded from the shipped-surface mine.
    _write(tmp_path, "tests/test_x.py", "y = 2\n")
    sources = gather_sources(str(tmp_path), max_sources=3)
    assert len(sources) == 3
    assert all(p.startswith("app/") for p in sources)
    assert list(sources) == sorted(sources)
    assert gather_sources(str(tmp_path), max_sources=0) == {}


def test_gather_sources_tolerates_unreadable(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path, "app/a.py", "x = 1\n")

    def _bad_read(self, *args, **kwargs):
        raise OSError("nope")

    monkeypatch.setattr(Path, "read_text", _bad_read)
    # A read error per file is swallowed -> the file is simply skipped.
    assert gather_sources(str(tmp_path)) == {}


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
