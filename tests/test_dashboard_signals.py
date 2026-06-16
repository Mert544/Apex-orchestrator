"""Two newly-grounded dashboard signals:

1. ``profile.coordinator_modules`` — high-fan-OUT "god-modules" (decoupling
   candidates), surfaced as a block inside the Architecture section. This is the
   OPPOSITE edge direction from the dependency-hub (fan-IN) read-out.
2. The idea-tree-shape ``grounding_ratio``/``grounded_count`` — what fraction of
   ideas tie to concrete code facts — surfaced as a line in the Shape section.

The pure render helpers are driven directly with lightweight stand-ins (no scan,
no network) for the content + escaping + determinism + empty/legacy paths; one
end-to-end ``build_dashboard`` over a fixture with a real god-module guards the
self-contained + single-timestamp invariants.
"""

import re
from pathlib import Path
from types import SimpleNamespace

from app.reporting import dashboard as D
from app.reporting.dashboard import build_dashboard


# --- _coordinator_block: empty / defensive paths ---------------------------

def _profile(**kw):
    base = dict(
        coordinator_modules=[], import_cycles=[], fragile_modules=[],
        dependency_edges=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_coordinator_block_empty_is_blank():
    assert D._coordinator_block(_profile(coordinator_modules=[])) == ""


def test_coordinator_block_missing_attribute_is_blank():
    assert D._coordinator_block(SimpleNamespace()) == ""


def test_coordinator_block_non_dict_entries_ignored():
    assert D._coordinator_block(_profile(coordinator_modules=["x", 7])) == ""


def test_coordinator_block_renders_module_and_fan_out():
    out = D._coordinator_block(_profile(coordinator_modules=[
        {"module": "app/engine/wirer.py", "fan_out": 17,
         "imports": ["app/a.py", "app/b.py", "app/c.py"]},
    ]))
    assert "Coordinator modules" in out
    assert "app/engine/wirer.py" in out
    assert "17" in out
    # The top internal modules it pulls are named (the decoupling targets).
    assert "app/a.py" in out


def test_coordinator_block_orders_as_given():
    out = D._coordinator_block(_profile(coordinator_modules=[
        {"module": "app/x.py", "fan_out": 20, "imports": []},
        {"module": "app/y.py", "fan_out": 13, "imports": []},
    ]))
    assert out.index("app/x.py") < out.index("app/y.py")


def test_coordinator_block_escapes_codebase_strings():
    out = D._coordinator_block(_profile(coordinator_modules=[
        {"module": "app/<x>.py", "fan_out": 12, "imports": ["app/&evil.py"]},
    ]))
    assert "app/<x>.py" not in out
    assert "&lt;x&gt;" in out
    assert "&amp;evil" in out


def test_coordinator_block_deterministic():
    p = _profile(coordinator_modules=[
        {"module": "app/x.py", "fan_out": 14, "imports": ["app/a.py"]},
    ])
    assert D._coordinator_block(p) == D._coordinator_block(p)


# --- _architecture_section integration + legacy guard ----------------------

def test_architecture_section_includes_coordinators():
    out = D._architecture_section(_profile(coordinator_modules=[
        {"module": "app/engine/wirer.py", "fan_out": 17, "imports": ["app/a.py"]},
    ]))
    assert "Architecture health" in out
    assert "Coordinator modules" in out
    assert "app/engine/wirer.py" in out
    # Complements (does not replace) the existing cycles/fragile chips.
    assert "coordinator" in out.lower()


def test_architecture_section_no_signals_is_byte_identical_to_legacy():
    # An all-clean profile (no cycles, no fragile, no coordinators) renders the
    # historical "all clear" card — the coordinator block adds nothing.
    out = D._architecture_section(_profile())
    assert "Coordinator modules" not in out
    assert "No import cycles or fragile hubs detected" in out


# --- _shape_section grounding ratio: content + empty path -------------------

def _shape(**kw):
    base = dict(
        total_ideas=8, by_kind={"permutation": 8}, depth_distribution={0: 4, 1: 4},
        max_depth=1, branching_factor=2.0, distinct_subjects=4,
        facet_penetration=0.0, distinct_values=5, total_measured_loc=0,
        heaviest_module="", heaviest_loc=0, top_subject="app/x.py",
        top_subject_share=0.5, observations=["ok"],
        grounded_count=6, grounding_ratio=0.75,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_shape_section_renders_grounding_ratio():
    out = D._shape_section(_shape(grounded_count=6, grounding_ratio=0.75))
    assert "grounding" in out.lower()
    assert "75%" in out
    assert "6/8" in out


def test_shape_section_skips_grounding_when_field_absent():
    # A shape object from a worktree without the field renders byte-identically:
    # no grounding line at all.
    bare = SimpleNamespace(
        total_ideas=8, by_kind={"permutation": 8}, depth_distribution={0: 8},
        max_depth=0, branching_factor=0.0, distinct_subjects=4,
        facet_penetration=0.0, distinct_values=5, total_measured_loc=0,
        heaviest_module="", heaviest_loc=0, top_subject="app/x.py",
        top_subject_share=0.5, observations=["ok"],
    )
    out = D._shape_section(bare)
    assert "grounding:" not in out


def test_shape_section_skips_grounding_when_zero():
    out = D._shape_section(_shape(grounded_count=0, grounding_ratio=0.0))
    assert "grounding:" not in out


def test_shape_section_grounding_deterministic():
    s = _shape()
    assert D._shape_section(s) == D._shape_section(s)


# --- end-to-end: a real god-module fixture + invariants --------------------

def _coordinator_fixture(tmp: Path) -> Path:
    """A package whose ``hub.py`` imports many sibling modules (high fan-out).

    The fan-out floor for a coordinator is 12, so we wire 14 leaf modules and a
    single hub importing all of them — a genuine god-module the profiler flags.
    """
    pkg = tmp / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    leaves = [f"m{i}" for i in range(14)]
    for name in leaves:
        (pkg / f"{name}.py").write_text(f"def {name}():\n    return 1\n")
    imports = "".join(f"import app.{name}\n" for name in leaves)
    calls = "".join(f"    app.{name}.{name}()\n" for name in leaves)
    (pkg / "hub.py").write_text(f"{imports}\n\ndef wire():\n{calls}    return 0\n")
    (pkg / "main.py").write_text("def main():\n    return 1\n")
    return tmp


def test_dashboard_surfaces_coordinator_block(tmp_path):
    _coordinator_fixture(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=20, idea_depth=2, breadth=3, quality=False)
    assert "Coordinator modules" in html_doc
    assert "hub.py" in html_doc
    assert "fan-out" in html_doc


def test_dashboard_with_coordinator_stays_self_contained(tmp_path):
    _coordinator_fixture(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=20, idea_depth=2, breadth=3, quality=False)
    assert html_doc.startswith("<!doctype html>")
    assert "<script src=" not in html_doc
    assert 'rel="stylesheet"' not in html_doc
    # Only the SVG xmlns namespace may reference a remote URL.
    without_ns = html_doc.replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert "http://" not in without_ns and "https://" not in without_ns


def test_dashboard_with_coordinator_has_single_timestamp(tmp_path):
    _coordinator_fixture(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=20, idea_depth=2, breadth=3, quality=False)
    stamps = re.findall(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", html_doc)
    assert len(stamps) == 1
