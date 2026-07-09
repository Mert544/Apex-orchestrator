"""Pin the GRADE-DEFINING parameters behaviorally — the grader grades itself, so
its own constants must be falsifiable.

Apex's own `apex mutants app/engine/health_score.py` found live survivors: the
severity weights (`_SEVERITY_WEIGHT`), the maintainability/duplication caps
(`_MAINT_CAP`/`_DUP_CAP`), and `Component.to_dict`'s `asdict(self)` could all be
mutated and every existing test still passed. The pre-existing tests pin only
RELATIVE behavior ("a critical costs more than a medium") and the 30-cap, so
tuning the exact weights/caps was silent — a real gap in the exact code that
certifies quality.

These tests pin the exact grade OUTPUT for a controlled real input (not a shallow
`assert _CONST == 12`), so changing a grade parameter fails a test instead of
silently re-scoring every project Apex grades. Each test names the mutation it
kills.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.health_score import Component, grade


def _security_points(tmp: Path, files: dict[str, str]) -> int:
    for rel, txt in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return next(c.points_lost for c in grade(str(tmp)).components
               if c.name == "Security")


def test_component_to_dict_is_the_full_record():
    # Kills `Component.to_dict` -> `asdict(self)` mutated to `None`: no test
    # asserted the serialized shape, so a nulled to_dict (which every JSON
    # consumer / dashboard / CI gate reads) survived.
    assert Component("X", 3, "d").to_dict() == {
        "name": "X", "points_lost": 3, "detail": "d", "top_files": []}


def test_high_severity_finding_costs_exactly_its_weight(tmp_path):
    # Kills `_SEVERITY_WEIGHT["high"]: 4 -> 5`. One `eval` (a high-severity
    # finding, below the 30-cap) must cost EXACTLY its weight — the relative-only
    # "critical > medium" test let the weight drift silently.
    assert _security_points(tmp_path, {"a.py": "def r(c):\n    return eval(c)\n"}) == 4


def test_medium_severity_finding_costs_exactly_its_weight(tmp_path):
    # Kills `_SEVERITY_WEIGHT["medium"]: 2 -> 3`. One bare-except (medium) costs
    # exactly 2.
    assert _security_points(
        tmp_path,
        {"a.py": "def f():\n    try:\n        pass\n    except:\n        pass\n"}) == 2


def _grade_components(tmp_path):
    # Six functions each with 14 branches: over the complexity ceiling, and
    # identical (so also duplicated) — enough to bind BOTH small caps.
    branchy = "".join(
        f"def f{i}(a):\n" + "".join(f"    if a == {j}:\n        return {j}\n"
                                    for j in range(14)) + "    return 0\n"
        for i in range(6))
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "m.py").write_text(branchy, encoding="utf-8")
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_m.py").write_text(
        "def test_x():\n    assert 1\n", encoding="utf-8")
    return {c.name: c.points_lost for c in grade(str(tmp_path)).components}


def test_maintainability_cap_is_exactly_ten(tmp_path):
    # Kills `_MAINT_CAP: 10 -> 11`. Six over-ceiling functions cost 6*2=12 raw,
    # capped to exactly 10 — the cap must BIND at 10, not 11.
    assert _grade_components(tmp_path)["Maintainability"] == 10


def test_duplication_cap_is_exactly_ten(tmp_path):
    # Kills `_DUP_CAP: 10 -> 11`. The six identical functions produce well over
    # ten duplicated blocks, capped to exactly 10.
    assert _grade_components(tmp_path)["Duplication"] == 10
