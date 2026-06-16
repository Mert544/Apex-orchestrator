"""Tests for the simplification scanner and its seeder family.

The scanner finds files where a safe behaviour-preserving transform WOULD fire;
the seeder turns each into an EXECUTABLE-labelled root. The empty-default keeps
existing seeded sets byte-identical.
"""

from app.engine.idea_permutation import IdeaSeeder
from app.tools.project_profile import ProjectProfile
from app.tools.simplification_scan import scan_simplifications


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


# --- scanner ---------------------------------------------------------------

def test_scanner_detects_double_not(tmp_path):
    # A real `not not x` → the double_not transform fires → one opportunity with
    # the EXACT executable fact-label the bridge expects.
    (tmp_path / "m.py").write_text("def f(x):\n    return not not x\n", encoding="utf-8")
    opps = scan_simplifications(tmp_path)
    labels = {o["fact_label"] for o in opps}
    assert "double-not" in labels
    hit = next(o for o in opps if o["fact_label"] == "double-not")
    assert hit["module"] == "m.py"
    assert hit["transform"] == "double_not"


def test_scanner_clean_file_yields_nothing(tmp_path):
    (tmp_path / "clean.py").write_text("def f(x):\n    return bool(x)\n", encoding="utf-8")
    assert scan_simplifications(tmp_path) == []


def test_scanner_excludes_fixtures_and_tests(tmp_path):
    # The same triggering source under a tests/ dir, a fixtures/ dir, and a
    # test_*.py file must all be skipped — they exist to TRIGGER transforms.
    trigger = "def f(x):\n    return not not x\n"
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "thing.py").write_text(trigger, encoding="utf-8")
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "thing.py").write_text(trigger, encoding="utf-8")
    (tmp_path / "test_thing.py").write_text(trigger, encoding="utf-8")
    assert scan_simplifications(tmp_path) == []


def test_scanner_is_deterministic_and_sorted(tmp_path):
    (tmp_path / "b.py").write_text("def f(x):\n    return not not x\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("def f(x):\n    return not not x\n", encoding="utf-8")
    first = scan_simplifications(tmp_path)
    second = scan_simplifications(tmp_path)
    assert first == second
    modules = [o["module"] for o in first]
    assert modules == sorted(modules)


def test_scanner_caps_results(tmp_path):
    # Twelve distinct triggering files → capped at the deterministic top-N.
    for i in range(12):
        (tmp_path / f"m{i:02d}.py").write_text(
            "def f(x):\n    return not not x\n", encoding="utf-8")
    opps = scan_simplifications(tmp_path)
    assert len(opps) <= 8


# --- seeder family ---------------------------------------------------------

def test_seed_simplifications_emits_executable_labelled_root():
    profile = _profile(ci_files=["ci.yml"])
    # The profiler populating this field is out of scope; simulate its write.
    profile.simplification_opportunities = [
        {"module": "app/x.py", "transform": "double_not", "fact_label": "double-not"},
    ]
    roots = IdeaSeeder().seed(profile)
    hit = next(r for r in roots if r.subject == "app/x.py")
    assert hit.depth == 0
    assert hit.operator == "root"
    assert hit.title == "Apply double_not to simplify app/x.py"
    # The EXACT executable fact-label the bridge routes to the real transform.
    assert any("double-not" in f for f in hit.source_facts)
    # No 'untested' token (would mis-route to a test action), no leading-int.
    assert "untested" not in hit.source_facts[0]
    assert not hit.source_facts[0][:1].isdigit()


def test_seed_simplifications_empty_default_is_byte_identical():
    # With no opportunities, the seeded set must be byte-identical to a run on a
    # profile that has no such field at all (the field defaults to empty).
    profile = _profile(dependency_hubs=["app/a.py"], ci_files=["ci.yml"])
    baseline = IdeaSeeder().seed(profile)

    profile2 = _profile(dependency_hubs=["app/a.py"], ci_files=["ci.yml"])
    profile2.simplification_opportunities = []
    with_field = IdeaSeeder().seed(profile2)

    def _key(roots):
        return [(r.id, r.title, r.subject, tuple(r.source_facts), r.branch_path)
                for r in roots]

    assert _key(baseline) == _key(with_field)


def test_seed_simplifications_skips_malformed_opportunities():
    profile = _profile(ci_files=["ci.yml"])
    profile.simplification_opportunities = [
        {"transform": "double_not", "fact_label": "double-not"},  # no module
        {"module": "app/y.py", "transform": "double_not"},        # no fact_label
    ]
    roots = IdeaSeeder().seed(profile)
    assert not any(r.subject == "app/y.py" for r in roots)
