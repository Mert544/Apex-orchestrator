"""The coordinator (high-fan-OUT) seeding signal.

A module that IMPORTS many internal modules (high fan-OUT) is a coordination
chokepoint / god-module — a candidate to DECOUPLE. This is the OPPOSITE edge
direction from the EXISTING dependency-hub (fan-IN) signal, so the two never
restate each other.

Fan-out for a graph node is ``len(node.imports)`` (the in-scope internal modules
IT pulls). The scan reads it off the SAME import graph
``_populate_python_structure`` already builds (no second graph), flags modules at
or above ``_COORDINATOR_FAN_OUT_FLOOR``, sorts ``(-fan_out, module)`` and caps to
5. It is a whole-repo structural read the GRADE never consumes, so it is gated
behind ``not light`` — light mode yields []. Deterministic; a repo with no
god-module yields [].
"""

from __future__ import annotations

from pathlib import Path

from app.tools.project_profile import ProjectProfiler, ProjectProfiler as _PP

# How many internal modules the coordinator imports — chosen comfortably above
# the floor so the module is unambiguously a god-module.
_FAN_OUT = _PP._COORDINATOR_FAN_OUT_FLOOR + 3


def _make_project(root: Path) -> None:
    """A god-module ``coordinator.py`` importing many siblings, plus a small one."""
    pkg = root / "app"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    # The leaf modules the coordinator wires together.
    for i in range(_FAN_OUT):
        (pkg / f"leaf{i}.py").write_text(
            f"def fn_{i}(x):\n    return x + {i}\n", encoding="utf-8"
        )

    # The coordinator: imports every leaf → high fan-OUT.
    imports = "\n".join(f"import app.leaf{i}" for i in range(_FAN_OUT))
    body = "\n".join(
        f"    a = app.leaf{i}.fn_{i}(a)" for i in range(_FAN_OUT)
    )
    (pkg / "coordinator.py").write_text(
        f"{imports}\n\n\ndef run(a):\n{body}\n    return a\n", encoding="utf-8"
    )

    # A low-fan-out module: imports just one leaf → must NOT be flagged.
    (pkg / "small.py").write_text(
        "import app.leaf0\n\n\ndef go(a):\n    return app.leaf0.fn_0(a)\n",
        encoding="utf-8",
    )


def test_high_fan_out_module_is_flagged(tmp_path: Path):
    _make_project(tmp_path)
    coords = ProjectProfiler(str(tmp_path)).profile().coordinator_modules
    assert coords, "the god-module should be flagged"
    flagged = {c["module"] for c in coords}
    assert "app/coordinator.py" in flagged
    top = next(c for c in coords if c["module"] == "app/coordinator.py")
    assert top["fan_out"] >= _PP._COORDINATOR_FAN_OUT_FLOOR
    assert top["fan_out"] == _FAN_OUT
    # The ``imports`` field names a few of the internal modules it pulls.
    assert top["imports"], "a flagged coordinator names some of its imports"
    assert len(top["imports"]) <= 3
    assert all(imp.startswith("app/leaf") for imp in top["imports"])


def test_low_fan_out_module_is_not_flagged(tmp_path: Path):
    _make_project(tmp_path)
    coords = ProjectProfiler(str(tmp_path)).profile().coordinator_modules
    flagged = {c["module"] for c in coords}
    assert "app/small.py" not in flagged, "a 1-import module is not a coordinator"
    # No leaf (zero internal imports) is ever a coordinator either.
    assert not any(c["module"].startswith("app/leaf") for c in coords)


def test_light_mode_skips_the_scan(tmp_path: Path):
    _make_project(tmp_path)
    # Light mode skips every whole-repo scan the GRADE never reads, including
    # this one — so even an obvious god-module yields nothing.
    coords = ProjectProfiler(str(tmp_path)).profile(light=True).coordinator_modules
    assert coords == []


def test_empty_project_yields_no_coordinators(tmp_path: Path):
    # No source at all → the import graph is empty → [] (seeding stays
    # byte-identical for a repo with no god-module).
    coords = ProjectProfiler(str(tmp_path)).profile().coordinator_modules
    assert coords == []


def test_deterministic_and_sorted(tmp_path: Path):
    _make_project(tmp_path)
    # Add a SECOND, slightly smaller coordinator so ordering is observable.
    pkg = tmp_path / "app"
    n = _PP._COORDINATOR_FAN_OUT_FLOOR
    imports = "\n".join(f"import app.leaf{i}" for i in range(n))
    (pkg / "coordinator_b.py").write_text(
        f"{imports}\n\n\ndef run():\n    return 1\n", encoding="utf-8"
    )

    first = ProjectProfiler(str(tmp_path)).profile().coordinator_modules
    second = ProjectProfiler(str(tmp_path)).profile().coordinator_modules
    assert first == second, "same repo → identical result"
    # Widest fan-out first, then stable by module path.
    keys = [(-c["fan_out"], c["module"]) for c in first]
    assert keys == sorted(keys)
    # The bigger coordinator outranks the smaller one.
    assert first[0]["module"] == "app/coordinator.py"


def test_fixture_paths_are_excluded(tmp_path: Path):
    _make_project(tmp_path)
    # A god-module living UNDER tests/ is throwaway wiring — never a real subject.
    tests_dir = tmp_path / "tests" / "app"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    n = _FAN_OUT
    for i in range(n):
        (tests_dir / f"leaf{i}.py").write_text(
            f"def fn_{i}(x):\n    return x\n", encoding="utf-8"
        )
    imports = "\n".join(f"import tests.app.leaf{i}" for i in range(n))
    (tests_dir / "coordinator.py").write_text(
        f"{imports}\n\n\ndef run():\n    return 1\n", encoding="utf-8"
    )
    coords = ProjectProfiler(str(tmp_path)).profile().coordinator_modules
    assert not any("tests/" in c["module"] for c in coords)
