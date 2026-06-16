"""Characterization tests for the decomposed ``_scan_doc_drift`` and
``_drop_fixture_signals`` helpers in ``app.tools.project_profile``.

These pin the exact behavior that the refactor preserved byte-for-byte: the
pure ref-classification helpers, the missing-ref generator, and the fixture
filtering (list fields, dict-record fields, and the >=2 dup-group rule),
including their empty/edge paths.
"""
from pathlib import Path

from app.tools.project_profile import ProjectProfile, ProjectProfiler


# ---- _doc_ref_path_part and its sub-helpers (pure) ----

def test_doc_ref_path_part_accepts_plain_and_line_anchored():
    f = ProjectProfiler._doc_ref_path_part
    assert f("app/main.py") == "app/main.py"
    assert f("app/x.py:12") == "app/x.py"  # :line suffix stripped
    assert f("./app/rel.py") == "app/rel.py"  # ./ prefix stripped
    assert f("././docs/g.md") == "docs/g.md"  # repeated ./ stripped


def test_doc_ref_path_part_rejects_non_paths():
    f = ProjectProfiler._doc_ref_path_part
    assert f("hashlib.md5") is None  # no separator
    assert f("/abs/path.py") is None  # leading slash (slash-command)
    assert f("app/foo.unknown") is None  # extension not whitelisted
    assert f("app/foo") is None  # no extension on final segment


def test_doc_ref_path_part_rejects_urls_placeholders_and_artifacts():
    f = ProjectProfiler._doc_ref_path_part
    assert f("http://example.com/x.py") is None
    assert f("https://example.com/x.py") is None
    assert f("path/to/file.py") is None  # placeholder token
    assert f("dir/<name>.py") is None  # placeholder bracket
    assert f(".apex/cache.json") is None  # runtime-artifact root
    assert f(".git/config.ini") is None


def test_is_doc_file_ref_and_excluded_predicates():
    assert ProjectProfiler._is_doc_file_ref("a/b.py") is True
    assert ProjectProfiler._is_doc_file_ref("noseparator.py") is False
    assert ProjectProfiler._is_doc_ref_excluded("HTTP://X/y.py", "HTTP://X/y.py") is True
    assert ProjectProfiler._is_doc_ref_excluded("app/ok.py", "app/ok.py") is False
    assert ProjectProfiler._is_doc_ref_excluded("build/x.py", "build/x.py") is True


# ---- _scan_doc_drift integration: cap, dedup, missing-only ----

def test_scan_doc_drift_caps_at_five_and_dedups(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "real.py").write_text("x = 1\n", encoding="utf-8")
    lines = ["# Doc", "Real ref `app/real.py` exists.", "Dup `app/gone.py`.",
             "Dup again `app/gone.py`."]
    lines += [f"Missing `app/m{i}.py` here." for i in range(8)]
    (tmp_path / "README.md").write_text("\n".join(lines), encoding="utf-8")

    profile = ProjectProfiler(tmp_path).profile()
    assert len(profile.doc_drift) == 5  # capped
    refs = [d["reference"] for d in profile.doc_drift]
    assert refs.count("app/gone.py") == 1  # deduped
    assert "app/real.py" not in refs  # on-disk file excluded


def test_doc_missing_refs_handles_unreadable_doc(tmp_path: Path):
    prof = ProjectProfiler(tmp_path)
    missing = tmp_path / "nope.md"  # does not exist -> OSError swallowed
    assert list(prof._doc_missing_refs(missing)) == []


def test_scan_doc_drift_empty_when_no_docs(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("x = 1\n", encoding="utf-8")
    profile = ProjectProfiler(tmp_path).profile()
    assert profile.doc_drift == []


# ---- _without_fixture_modules / _drop_fixture_dup_groups (pure) ----

def test_without_fixture_modules_filters_by_module_key(tmp_path: Path):
    prof = ProjectProfiler(tmp_path)
    records = [
        {"module": "app/keep.py", "n": 1},
        {"module": "tests/test_drop.py", "n": 2},
        {"module": "examples/demo.py", "n": 3},
        {"n": 4},  # missing key -> "" -> not a fixture -> kept
    ]
    out = prof._without_fixture_modules(records)
    assert [r.get("module", "") for r in out] == ["app/keep.py", ""]


def test_drop_fixture_dup_groups_requires_two_real_modules(tmp_path: Path):
    prof = ProjectProfiler(tmp_path)
    groups = [
        {"id": 1, "modules": ["app/a.py", "app/b.py", "tests/test_c.py"]},
        {"id": 2, "modules": ["app/a.py", "examples/e.py"]},  # only 1 real -> dropped
        {"id": 3, "modules": ["tests/test_x.py", "fixtures/y.py"]},  # 0 real -> dropped
    ]
    out = prof._drop_fixture_dup_groups(groups)
    assert [g["id"] for g in out] == [1]
    assert out[0]["modules"] == ["app/a.py", "app/b.py"]  # fixture stripped, rest kept


# ---- _drop_fixture_signals end-to-end on a synthetic profile ----

def test_drop_fixture_signals_filters_lists_records_and_dups(tmp_path: Path):
    prof = ProjectProfiler(tmp_path)
    profile = ProjectProfile(root=str(tmp_path))
    profile.untested_modules = ["app/real.py", "tests/test_x.py", "examples/e.py"]
    profile.security_finding_modules = ["app/s.py", "fixtures/f.py"]
    profile.hotspot_functions = [{"module": "app/h.py"}, {"module": "tests/test_h.py"}]
    profile.incomplete_protocols = [{"module": "app/p.py"}, {"module": "examples/p.py"}]
    profile.generalizable_duplications = [
        {"modules": ["app/a.py", "app/b.py", "tests/test_t.py"]},
        {"modules": ["app/c.py", "examples/d.py"]},
    ]

    prof._drop_fixture_signals(profile)

    assert profile.untested_modules == ["app/real.py"]
    assert profile.security_finding_modules == ["app/s.py"]
    assert profile.hotspot_functions == [{"module": "app/h.py"}]
    assert profile.incomplete_protocols == [{"module": "app/p.py"}]
    assert profile.generalizable_duplications == [
        {"modules": ["app/a.py", "app/b.py"]}
    ]


def test_drop_fixture_signals_noop_on_empty_profile(tmp_path: Path):
    prof = ProjectProfiler(tmp_path)
    profile = ProjectProfile(root=str(tmp_path))
    prof._drop_fixture_signals(profile)  # all defaults empty -> must not raise
    assert profile.untested_modules == []
    assert profile.hotspot_functions == []
    assert profile.generalizable_duplications == []
