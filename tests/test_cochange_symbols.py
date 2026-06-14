"""Concrete co-change test-gap symbols.

The ``cochange-testgap`` signal flags module pairs ``(a, b)`` that co-change in
git but share no test. This makes the recommendation CONCRETE: instead of "add a
test exercising A and B together", it names the ACTUAL symbol that links the two
modules (which one imports from the other), via stdlib ``ast`` only.

Two layers:
  * ``ProjectProfiler._scan_cochange_test_gaps`` gains an additive ``links`` key
    (``[{"from","to","symbol"}, ...]``) — omitted entirely when no direct import
    connects the pair, so no-link gaps stay byte-identical to the original
    two-field shape.
  * ``IdeaSeeder`` turns a present ``links`` into a concrete title + ``anchors``
    pointing at the linking symbol(s); with no links it falls back to the exact
    original module-pair phrasing.
"""

from pathlib import Path

from app.engine.idea_seeder import IdeaSeeder
from app.tools.project_profile import ProjectProfile, ProjectProfiler


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _profiler(root: Path) -> ProjectProfiler:
    return ProjectProfiler(str(root))


# --------------------------------------------------------------------------- #
# _scan_cochange_test_gaps — the ``links`` key names the real interface.
# --------------------------------------------------------------------------- #

def test_links_name_the_imported_symbol(tmp_path):
    # app/b.py imports `foo` from app/a.py -> the link is concrete.
    _write(tmp_path, "app/a.py", "def foo():\n    return 1\n")
    _write(tmp_path, "app/b.py", "from app.a import foo\n\n\ndef use():\n    return foo()\n")
    profile = _profile(
        change_coupling=[{"a": "app/a.py", "b": "app/b.py", "commits": 7}],
        module_to_tests={},
    )
    _profiler(tmp_path)._scan_cochange_test_gaps(profile)
    gap = profile.cochange_test_gaps[0]
    assert gap["a"] == "app/a.py" and gap["b"] == "app/b.py"
    assert gap["cochanges"] == 7
    assert gap["links"] == [{"from": "app/b.py", "to": "app/a.py", "symbol": "foo"}]


def test_links_capture_both_directions_and_cap_at_three(tmp_path):
    # a imports x,y from b; b imports z from a -> 3 links, sorted, capped.
    _write(tmp_path, "app/a.py", "from app.b import x, y, w\nz = 1\n")
    _write(tmp_path, "app/b.py", "from app.a import z\nx = 1\ny = 2\nw = 3\n")
    profile = _profile(
        change_coupling=[{"a": "app/a.py", "b": "app/b.py", "commits": 4}],
        module_to_tests={},
    )
    _profiler(tmp_path)._scan_cochange_test_gaps(profile)
    links = profile.cochange_test_gaps[0]["links"]
    assert len(links) == 3
    # Sorted by (from, to, symbol); a<b so a->b clauses first, then symbols asc.
    assert links == [
        {"from": "app/a.py", "to": "app/b.py", "symbol": "w"},
        {"from": "app/a.py", "to": "app/b.py", "symbol": "x"},
        {"from": "app/a.py", "to": "app/b.py", "symbol": "y"},
    ]


def test_no_direct_import_yields_no_links_key(tmp_path):
    # They co-change but neither imports the other -> no ``links`` key at all, so
    # the dict is byte-identical to the original two/three-field shape.
    _write(tmp_path, "app/a.py", "import os\n\n\ndef foo():\n    return os.getcwd()\n")
    _write(tmp_path, "app/b.py", "import sys\n\n\ndef bar():\n    return sys.argv\n")
    profile = _profile(
        change_coupling=[{"a": "app/a.py", "b": "app/b.py", "commits": 5}],
        module_to_tests={},
    )
    _profiler(tmp_path)._scan_cochange_test_gaps(profile)
    gap = profile.cochange_test_gaps[0]
    assert "links" not in gap
    assert gap == {"a": "app/a.py", "b": "app/b.py", "cochanges": 5}


def test_relative_import_is_not_resolved_as_a_link(tmp_path):
    # A relative ``from . import x`` carries no absolute module -> no link.
    _write(tmp_path, "app/a.py", "x = 1\n")
    _write(tmp_path, "app/b.py", "from . import x\n")
    profile = _profile(
        change_coupling=[{"a": "app/a.py", "b": "app/b.py", "commits": 3}],
        module_to_tests={},
    )
    _profiler(tmp_path)._scan_cochange_test_gaps(profile)
    assert "links" not in profile.cochange_test_gaps[0]


def test_profile_only_scan_has_no_links(tmp_path):
    # The existing profile-only call path (no filesystem parse) yields no links
    # key — the additive field never perturbs the pre-existing two-field dict.
    profiler = ProjectProfiler.__new__(ProjectProfiler)
    profile = _profile(
        change_coupling=[{"a": "app/p.py", "b": "app/q.py", "commits": 7}],
        module_to_tests={},
    )
    profiler._scan_cochange_test_gaps(profile)
    assert profile.cochange_test_gaps == [
        {"a": "app/p.py", "b": "app/q.py", "cochanges": 7}
    ]


def test_links_are_deterministic(tmp_path):
    _write(tmp_path, "app/a.py", "def foo():\n    return 1\n")
    _write(tmp_path, "app/b.py", "from app.a import foo\n")
    kw = dict(
        change_coupling=[{"a": "app/a.py", "b": "app/b.py", "commits": 7}],
        module_to_tests={},
    )
    p1, p2 = _profile(**kw), _profile(**kw)
    _profiler(tmp_path)._scan_cochange_test_gaps(p1)
    _profiler(tmp_path)._scan_cochange_test_gaps(p2)
    assert p1.cochange_test_gaps == p2.cochange_test_gaps


# --------------------------------------------------------------------------- #
# IdeaSeeder — links produce a concrete title + anchor; no links -> fallback.
# --------------------------------------------------------------------------- #

def _gap_profile_with_links() -> ProjectProfile:
    return _profile(
        cochange_test_gaps=[{
            "a": "app/a.py", "b": "app/b.py", "cochanges": 7,
            "links": [{"from": "app/b.py", "to": "app/a.py", "symbol": "foo"}],
        }],
        ci_files=["ci.yml"],
    )


def _cochange_root(roots):
    gaps = [
        r for r in roots
        if r.source_facts and r.source_facts[0].startswith("cochange-testgap:")
    ]
    assert len(gaps) == 1
    return gaps[0]


def test_concrete_title_names_the_symbol():
    idea = _cochange_root(IdeaSeeder().seed(_gap_profile_with_links()))
    assert idea.subject == "app/a.py + app/b.py"  # subject unchanged (the PAIR)
    assert "app/b.py imports `foo` from app/a.py" in idea.title
    assert "↔" in idea.title
    assert "co-change but nothing tests them jointly" in idea.title


def test_concrete_root_has_a_symbol_anchor():
    idea = _cochange_root(IdeaSeeder().seed(_gap_profile_with_links()))
    assert idea.anchors == [{
        "module": "app/a.py", "symbol": "foo", "line": 0, "metric": "co-changes 7",
    }]


def test_anchor_line_resolved_from_root(tmp_path):
    _write(tmp_path, "app/a.py", "import os\n\n\ndef foo():\n    return 1\n")
    profile = _profile(
        cochange_test_gaps=[{
            "a": "app/a.py", "b": "app/b.py", "cochanges": 7,
            "links": [{"from": "app/b.py", "to": "app/a.py", "symbol": "foo"}],
        }],
        ci_files=["ci.yml"],
    )
    idea = _cochange_root(IdeaSeeder(str(tmp_path)).seed(profile))
    # ``def foo`` is on line 4 of app/a.py.
    assert idea.anchors[0]["line"] == 4


def test_no_links_falls_back_byte_identical():
    # The no-links gap must reproduce the ORIGINAL title/fact exactly.
    no_links = _profile(
        cochange_test_gaps=[{"a": "app/a.py", "b": "app/b.py", "cochanges": 7}],
        ci_files=["ci.yml"],
    )
    idea = _cochange_root(IdeaSeeder().seed(no_links))
    assert idea.title == (
        "Add a test that exercises app/a.py and app/b.py together — they "
        "co-change but nothing tests them jointly"
    )
    assert idea.source_facts[0] == (
        "cochange-testgap: app/a.py & app/b.py (co-change 7x but no single test "
        "exercises both — a change to one can silently break the other)"
    )
    assert idea.anchors == []


def test_invariants_value_feasibility_novelty_in_unit_interval():
    for prof in (_gap_profile_with_links(),
                 _profile(cochange_test_gaps=[{"a": "app/a.py", "b": "app/b.py",
                                               "cochanges": 7}], ci_files=["ci.yml"])):
        for r in IdeaSeeder().seed(prof):
            assert 0.0 <= r.value <= 1.0
            assert 0.0 <= r.feasibility <= 1.0
            assert 0.0 <= r.novelty <= 1.0
            if r.depth == 0:
                assert r.novelty == 1.0


def test_subject_and_dedup_unchanged_with_links():
    # Two link-bearing entries collapsing to the same PAIR subject seed one root.
    profile = _profile(
        cochange_test_gaps=[
            {"a": "app/a.py", "b": "app/b.py", "cochanges": 7,
             "links": [{"from": "app/b.py", "to": "app/a.py", "symbol": "foo"}]},
            {"a": "app/a.py", "b": "app/b.py", "cochanges": 3,
             "links": [{"from": "app/b.py", "to": "app/a.py", "symbol": "bar"}]},
        ],
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    pair_roots = [r for r in roots if r.subject == "app/a.py + app/b.py"]
    assert len(pair_roots) == 1


def test_seed_is_deterministic_with_links():
    a = IdeaSeeder().seed(_gap_profile_with_links())
    b = IdeaSeeder().seed(_gap_profile_with_links())
    assert [(r.subject, r.title, tuple(r.anchors[0].items()) if r.anchors else ())
            for r in a] == \
           [(r.subject, r.title, tuple(r.anchors[0].items()) if r.anchors else ())
            for r in b]


def test_light_mode_still_yields_nothing():
    # Git-only family: no cochange gaps -> no root, even with linked tests.
    profile = _profile(
        cochange_test_gaps=[],
        module_to_tests={"app/a.py": ["tests/test_a.py"]},
        ci_files=["ci.yml"],
    )
    roots = IdeaSeeder().seed(profile)
    assert not any(
        r.source_facts and r.source_facts[0].startswith("cochange-testgap:")
        for r in roots
    )
