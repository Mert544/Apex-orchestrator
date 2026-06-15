"""Grounded signals the dream digest surfaces — coordinator god-modules and
the evidence-aware (Wilson) reliability ranking.

Both are GATED on availability: a repo with no god-module leaves
``coordinator_modules`` empty, so the digest stays byte-identical when the
signal is absent; the confidence ranking falls back to the raw rate for an
older memory store with no ``most_confident`` key.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.dream import dream, render_dream_markdown
from app.tools.project_profile import ProjectProfiler as _PP

# Comfortably above the floor so the module is unambiguously a god-module.
_FAN_OUT = _PP._COORDINATOR_FAN_OUT_FLOOR + 3


def _make_coordinator_project(root: Path) -> None:
    """A god-module ``coordinator.py`` importing many internal siblings."""
    pkg = root / "app"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for i in range(_FAN_OUT):
        (pkg / f"leaf{i}.py").write_text(
            f"def fn_{i}(x):\n    return x + {i}\n", encoding="utf-8")
    imports = "\n".join(f"import app.leaf{i}" for i in range(_FAN_OUT))
    body = "\n".join(f"    a = app.leaf{i}.fn_{i}(a)" for i in range(_FAN_OUT))
    (pkg / "coordinator.py").write_text(
        f"{imports}\n\n\ndef run(a):\n{body}\n    return a\n", encoding="utf-8")


def test_coordinator_god_module_surfaces_as_decoupling_candidate(tmp_path):
    _make_coordinator_project(tmp_path)
    report = dream(tmp_path, write_digest=False)
    text = " | ".join(report.patterns)
    assert "app/coordinator.py" in text
    assert "decoupling candidate" in text
    # It names the fan-out count and at least one wired-together internal module.
    coord = next(p for p in report.patterns if "decoupling candidate" in p)
    assert f"coordinates {_FAN_OUT} internal" in coord
    assert "app/leaf" in coord


def test_coordinator_reflection_omitted_byte_identically_when_absent(tmp_path):
    # A plain project with NO god-module: the reflection must not appear, and
    # the digest must be byte-identical to one rendered with no coordinator.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    report = dream(tmp_path, write_digest=False)
    assert not any("decoupling candidate" in p for p in report.patterns)
    md = render_dream_markdown(report)
    assert "coordinates" not in md
    assert "decoupling candidate" not in md


def test_coordinator_digest_is_deterministic(tmp_path):
    # Same input -> same output: two independent roots (so the cross-dream
    # journal can't carry streak state between them) yield identical bodies.
    a, b = tmp_path / "a", tmp_path / "b"
    _make_coordinator_project(a)
    _make_coordinator_project(b)
    first = render_dream_markdown(dream(a, write_digest=False))
    second = render_dream_markdown(dream(b, write_digest=False))
    # Strip the once-per-render timestamp line; everything else is byte-stable.
    def _body(md: str) -> str:
        return "\n".join(ln for ln in md.splitlines() if "Curated" not in ln)
    assert _body(first) == _body(second)
    assert "app/coordinator.py" in first


def test_confident_ranking_beats_a_lucky_one_of_one(tmp_path):
    # `lucky` lands 1-of-1 (raw 100%, but tiny evidence); `steady` lands 9-of-10
    # (raw 90%, well-attested). The evidence-aware ranking must headline
    # `steady` — a lucky single sample should not lead.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    apex = tmp_path / ".apex"
    apex.mkdir()
    apex.joinpath("idea-memory.json").write_text(json.dumps({
        "by_operator": {
            "lucky": {"applied": 1, "rolled_back": 0, "blocked": 0},
            "steady": {"applied": 9, "rolled_back": 1, "blocked": 0},
        },
        "by_label": {},
    }))
    report = dream(tmp_path, write_digest=False)
    leading = [p for p in report.patterns if "keep leading" in p]
    assert leading, "a reliable operator should be praised"
    assert "`steady`" in leading[0], "well-attested key headlines, not the 1-of-1"


def test_confidence_ranking_falls_back_for_legacy_memory(tmp_path):
    # An older memory store still reads via most_reliable; the praise line for a
    # solid multi-sample key must still appear (no confidence keys required).
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n")
    apex = tmp_path / ".apex"
    apex.mkdir()
    apex.joinpath("idea-memory.json").write_text(json.dumps({
        "by_operator": {"document": {"applied": 6, "rolled_back": 0, "blocked": 0}},
        "by_label": {},
    }))
    report = dream(tmp_path, write_digest=False)
    assert any("`document` fixes land 100%" in p for p in report.patterns)
