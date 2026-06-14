"""The complexity-based anchor fallback.

`hotspot_functions` only lists complex *untested* functions, so on a
well-covered codebase it is empty and the concrete "focus" anchor would never
fire. The fallback parses the module directly and names its most complex
functions by cyclomatic complexity, independent of test status — so a
confluence/hub/simplify recommendation still points at the real locus.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.idea_seeder import IdeaSeeder
from app.tools.project_profile import ProjectProfile


def _empty_profile() -> ProjectProfile:
    # No function-grain hotspot data — the well-tested-repo condition.
    p = ProjectProfile(root=".")
    p.hotspot_functions = []
    p.impure_untested_functions = []
    return p


_BRANCHY = '''\
def trivial(x):
    return x + 1


def branchy(x):
    total = 0
    for i in range(x):
        if i % 2 == 0:
            total += i
        elif i % 3 == 0:
            total -= i
        else:
            total += 1
        while total > 100:
            total -= 10
            if total < 0:
                break
    return total
'''


def test_anchor_fires_by_complexity_when_no_hotspot_data(tmp_path: Path):
    (tmp_path / "m.py").write_text(_BRANCHY, encoding="utf-8")
    seeder = IdeaSeeder(str(tmp_path))
    anchors = seeder._module_anchors(_empty_profile(), "m.py")
    assert anchors, "the complex function should be named even with no hotspot data"
    top = anchors[0]
    assert top["symbol"] == "branchy"
    assert top["line"] > 0
    assert top["metric"].startswith("cyclomatic ")
    # The trivial (below-threshold) function is never named.
    assert all(a["symbol"] != "trivial" for a in anchors)


def test_fallback_is_deterministic(tmp_path: Path):
    (tmp_path / "m.py").write_text(_BRANCHY, encoding="utf-8")
    seeder = IdeaSeeder(str(tmp_path))
    prof = _empty_profile()
    assert seeder._module_anchors(prof, "m.py") == seeder._module_anchors(prof, "m.py")


def test_below_threshold_module_yields_no_anchors(tmp_path: Path):
    (tmp_path / "simple.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    seeder = IdeaSeeder(str(tmp_path))
    assert seeder._module_anchors(_empty_profile(), "simple.py") == []


def test_unreadable_module_degrades_to_empty(tmp_path: Path):
    seeder = IdeaSeeder(str(tmp_path))
    # No such file -> graceful empty, no crash.
    assert seeder._module_anchors(_empty_profile(), "does/not/exist.py") == []


def test_no_project_root_degrades_to_empty():
    seeder = IdeaSeeder("")
    assert seeder._complexity_anchors("m.py", set()) == []
