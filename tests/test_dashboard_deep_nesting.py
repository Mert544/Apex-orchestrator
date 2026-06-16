"""Dashboard surfacing of the deep-nesting maintainability signal.

``profile.deeply_nested_functions`` (a ``list[dict]`` of
``{module, function, depth}``) names top-level functions whose control flow
nests deeply — guard-clause / extract-the-inner-block refactor candidates. The
dashboard renders these as a small block inside the Architecture section, near
the coordinator/fragile reads.

The pure ``_deep_nesting_block`` helper is driven directly with lightweight
stand-ins (no scan, no network) for content + escaping + determinism + the
empty/legacy paths; one end-to-end ``build_dashboard`` over a fixture with a
genuinely deep function guards the self-contained + single-timestamp invariants.
"""

import re
from pathlib import Path
from types import SimpleNamespace

from app.reporting import dashboard as D
from app.reporting.dashboard import build_dashboard


# --- _deep_nesting_block: empty / defensive paths --------------------------

def _profile(**kw):
    base = dict(
        coordinator_modules=[], import_cycles=[], fragile_modules=[],
        dependency_edges=[], deeply_nested_functions=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_deep_nesting_block_empty_is_blank():
    assert D._deep_nesting_block(_profile(deeply_nested_functions=[])) == ""


def test_deep_nesting_block_missing_attribute_is_blank():
    assert D._deep_nesting_block(SimpleNamespace()) == ""


def test_deep_nesting_block_non_dict_entries_ignored():
    assert D._deep_nesting_block(
        _profile(deeply_nested_functions=["x", 7])) == ""


def test_deep_nesting_block_renders_module_function_and_depth():
    out = D._deep_nesting_block(_profile(deeply_nested_functions=[
        {"module": "app/engine/runner.py", "function": "execute", "depth": 6},
    ]))
    assert "Deeply nested functions" in out
    assert "app/engine/runner.py" in out
    assert "execute" in out
    assert "depth 6" in out
    # Labelled as a refactor candidate, not just a raw metric.
    assert "guard-clause" in out.lower() or "refactor" in out.lower()


def test_deep_nesting_block_orders_as_given():
    out = D._deep_nesting_block(_profile(deeply_nested_functions=[
        {"module": "app/x.py", "function": "deep_a", "depth": 8},
        {"module": "app/y.py", "function": "deep_b", "depth": 6},
    ]))
    assert out.index("deep_a") < out.index("deep_b")


def test_deep_nesting_block_caps_at_five():
    entries = [
        {"module": f"app/m{i}.py", "function": f"fn{i}", "depth": 9 - i}
        for i in range(7)
    ]
    out = D._deep_nesting_block(_profile(deeply_nested_functions=entries))
    assert "fn5" not in out
    assert "fn6" not in out
    assert out.count("<li>") == 5


def test_deep_nesting_block_escapes_codebase_strings():
    out = D._deep_nesting_block(_profile(deeply_nested_functions=[
        {"module": "app/<x>.py", "function": "f&g", "depth": 5},
    ]))
    assert "app/<x>.py" not in out
    assert "&lt;x&gt;" in out
    assert "f&amp;g" in out


def test_deep_nesting_block_deterministic():
    p = _profile(deeply_nested_functions=[
        {"module": "app/x.py", "function": "deep", "depth": 7},
    ])
    assert D._deep_nesting_block(p) == D._deep_nesting_block(p)


# --- _architecture_section integration + legacy guard ----------------------

def test_architecture_section_includes_deep_nesting_when_otherwise_clean():
    # No cycles / fragile / coordinators, but a deep function exists: the card
    # surfaces the block instead of the "all clear" message.
    out = D._architecture_section(_profile(deeply_nested_functions=[
        {"module": "app/engine/runner.py", "function": "execute", "depth": 6},
    ]))
    assert "Architecture health" in out
    assert "Deeply nested functions" in out
    assert "app/engine/runner.py" in out
    assert "No import cycles or fragile hubs detected" not in out


def test_architecture_section_includes_deep_nesting_alongside_other_signals():
    out = D._architecture_section(_profile(
        coordinator_modules=[
            {"module": "app/hub.py", "fan_out": 17, "imports": ["app/a.py"]},
        ],
        deeply_nested_functions=[
            {"module": "app/engine/runner.py", "function": "execute", "depth": 6},
        ],
    ))
    assert "Coordinator modules" in out
    assert "Deeply nested functions" in out
    assert "execute" in out


def test_architecture_section_no_signals_is_byte_identical_to_legacy():
    # An all-clean profile (no cycles, no fragile, no coordinators, no deep
    # functions) renders the historical "all clear" card unchanged.
    out = D._architecture_section(_profile())
    assert "Deeply nested functions" not in out
    assert "No import cycles or fragile hubs detected" in out


# --- end-to-end: a deeply-nested fixture + invariants ----------------------

def _deep_nesting_fixture(tmp: Path) -> Path:
    """A package whose ``runner.py`` holds a function nested 5+ levels deep.

    The deep-nesting floor is 5, so we build a staircase of nested compound
    statements (if/for/while/with/try) to a depth the profiler flags.
    """
    pkg = tmp / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    runner = (
        "def execute(items):\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        if item:\n"
        "            while total < 10:\n"
        "                with open('x') as fh:\n"
        "                    try:\n"
        "                        total += len(fh.read())\n"
        "                    except OSError:\n"
        "                        total += 1\n"
        "    return total\n"
    )
    (pkg / "runner.py").write_text(runner)
    (pkg / "main.py").write_text("def main():\n    return 1\n")
    return tmp


def test_dashboard_surfaces_deep_nesting_block(tmp_path):
    _deep_nesting_fixture(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=20, idea_depth=2, breadth=3, quality=False)
    assert "Deeply nested functions" in html_doc
    assert "execute" in html_doc
    assert "depth" in html_doc


def test_dashboard_without_deep_nesting_omits_block(tmp_path):
    # An all-flat repo never reaches the nesting floor, so the block is absent.
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "main.py").write_text("def main():\n    return 1\n")
    html_doc = build_dashboard(str(tmp_path), max_ideas=20, idea_depth=2, breadth=3, quality=False)
    assert "Deeply nested functions" not in html_doc


def test_dashboard_with_deep_nesting_stays_self_contained(tmp_path):
    _deep_nesting_fixture(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=20, idea_depth=2, breadth=3, quality=False)
    assert html_doc.startswith("<!doctype html>")
    assert "<script src=" not in html_doc
    assert 'rel="stylesheet"' not in html_doc
    # Only the SVG xmlns namespace may reference a remote URL.
    without_ns = html_doc.replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert "http://" not in without_ns and "https://" not in without_ns


def test_dashboard_with_deep_nesting_has_single_timestamp(tmp_path):
    _deep_nesting_fixture(tmp_path)
    html_doc = build_dashboard(str(tmp_path), max_ideas=20, idea_depth=2, breadth=3, quality=False)
    stamps = re.findall(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", html_doc)
    assert len(stamps) == 1
