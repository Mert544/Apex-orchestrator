"""JS/TS test-coverage awareness seeding (RECOMMEND-ONLY language breadth).

The first contained increment of Apex's JS/TS direction: ``IdeaSeeder`` turns the
already-shipped, deterministic polyglot facts (``scan_polyglot_facts``: path,
churn, LOC, convention-based test presence) into a grounded, recommend-only
development IDEA for an UNTESTED, high-churn JS/TS module — surfaced by
``apex ideate`` alongside the Python ideas.

These tests pin the increment end to end AND its invariants:
  * an untested high-churn ``.ts`` module seeds a ``js-ts-coverage`` root anchored
    to the real file + its metric (with the public-export line when cheap);
  * a ``.ts`` module WITH a ``.test.ts``/``.spec.ts`` sibling seeds NOTHING (honest
    under-claim — no false positive);
  * a Python-only repo's seed set is byte-identical to before (regression guard);
  * the family is deterministic (same repo -> identical ideas twice);
  * roots stay in [0,1] with novelty == 1.0, and route RECOMMEND-ONLY through the
    bridge (Apex never claims to fix non-Python source).
"""

import subprocess
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge
from app.engine.idea_permutation import IdeaSeeder


# --- helpers ----------------------------------------------------------------

def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True,
                   capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "T")
    _git(root, "config", "commit.gpgsign", "false")


def _commit_all(root: Path, msg: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", msg)


def _js_ts_roots(root: Path):
    profile = _profile_for(root)
    return [
        r for r in IdeaSeeder(str(root)).seed(profile)
        if r.source_facts and r.source_facts[0].startswith("js-ts-coverage")
    ]


def _profile_for(root: Path):
    from app.tools.project_profile import ProjectProfiler

    return ProjectProfiler(str(root)).profile()


def _churned_ts_repo(tmp_path: Path) -> Path:
    """A repo with an untested, multi-commit ``web/handler.ts`` module."""
    _init_repo(tmp_path)
    (tmp_path / "app").mkdir()
    (tmp_path / "web").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        "def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "web" / "handler.ts").write_text(
        "export function handle(req) {\n  return req;\n}\n", encoding="utf-8")
    _commit_all(tmp_path, "init")
    # A few more commits so churn > 0 (git-only signal).
    for i in range(2):
        (tmp_path / "web" / "handler.ts").write_text(
            f"export function handle(req) {{\n  return req + {i};\n}}\n",
            encoding="utf-8")
        _commit_all(tmp_path, f"c{i}")
    return tmp_path


# --- core seeding -----------------------------------------------------------

def test_untested_high_churn_ts_module_seeds_coverage_idea(tmp_path: Path):
    root = _churned_ts_repo(tmp_path)
    roots = _js_ts_roots(root)
    assert len(roots) == 1
    idea = roots[0]
    # Subject carries the additive ``::js-ts-coverage`` suffix (never collides
    # with the bare-path polyglot-hotspot subject).
    assert idea.subject == "web/handler.ts::js-ts-coverage"
    assert "web/handler.ts" in idea.title
    assert "Establish test coverage" in idea.title
    assert "no test found" in idea.title
    assert "TypeScript" in idea.title
    # Grounded in real facts: the fact label + the path/language in the value.
    assert idea.source_facts[0].startswith("js-ts-coverage")
    assert "web/handler.ts" in idea.source_facts[0]
    assert "TypeScript" in idea.source_facts[0]
    # Honest framing: never claims dead code or a mandatory refactor.
    assert "dead code" not in idea.title.lower()
    assert "must refactor" not in idea.title.lower()


def test_idea_anchors_to_public_export_line(tmp_path: Path):
    root = _churned_ts_repo(tmp_path)
    idea = _js_ts_roots(root)[0]
    assert idea.anchors, "expected a concrete export anchor"
    anchor = idea.anchors[0]
    assert anchor["module"] == "web/handler.ts"
    assert anchor["symbol"] == "handle"
    assert anchor["line"] == 1
    assert "start with `handle`" in idea.title


def test_commit_word_singular_for_one_commit(tmp_path: Path):
    _init_repo(tmp_path)
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "one.ts").write_text(
        "export const x = 1;\n", encoding="utf-8")
    _commit_all(tmp_path, "init")
    idea = _js_ts_roots(tmp_path)[0]
    assert "1 recent commit" in idea.title
    assert "1 recent commits" not in idea.title


# --- honest under-claim -----------------------------------------------------

def test_tested_ts_module_seeds_no_idea(tmp_path: Path):
    # A ``.ts`` module WITH a ``.test.ts`` sibling has a convention test, so it
    # is NOT a coverage gap — no idea (no false positive).
    _init_repo(tmp_path)
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "client.ts").write_text(
        "export const tested = 1;\n", encoding="utf-8")
    (tmp_path / "web" / "client.test.ts").write_text(
        "import {tested} from './client';\ntest('ok', () => {});\n",
        encoding="utf-8")
    _commit_all(tmp_path, "init")
    subjects = {r.subject for r in _js_ts_roots(tmp_path)}
    assert "web/client.ts::js-ts-coverage" not in subjects


def test_spec_sibling_also_counts_as_tested(tmp_path: Path):
    _init_repo(tmp_path)
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "svc.ts").write_text(
        "export const svc = 1;\n", encoding="utf-8")
    (tmp_path / "web" / "svc.spec.ts").write_text(
        "import {svc} from './svc';\n", encoding="utf-8")
    _commit_all(tmp_path, "init")
    assert not _js_ts_roots(tmp_path)


def test_test_file_itself_is_not_seeded(tmp_path: Path):
    # A test file is JS/TS source with no test of its OWN — but recommending a
    # test for a test file is a false positive, so it is filtered out.
    _init_repo(tmp_path)
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "lonely.test.ts").write_text(
        "test('x', () => {});\n", encoding="utf-8")
    _commit_all(tmp_path, "init")
    assert not _js_ts_roots(tmp_path)


def test_files_under_tests_dir_are_not_seeded(tmp_path: Path):
    _init_repo(tmp_path)
    (tmp_path / "__tests__").mkdir()
    (tmp_path / "__tests__" / "helper.ts").write_text(
        "export const h = 1;\n", encoding="utf-8")
    _commit_all(tmp_path, "init")
    assert not _js_ts_roots(tmp_path)


# --- language scope ---------------------------------------------------------

def test_non_js_ts_language_is_not_seeded_by_this_family(tmp_path: Path):
    # An untested Go/HTML file is covered by the broader polyglot-hotspot family,
    # NOT this JS/TS-scoped one — so no js-ts-coverage root for it.
    _init_repo(tmp_path)
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "page.html").write_text(
        "<html><body><h1>Hi</h1></body></html>\n", encoding="utf-8")
    (tmp_path / "main.go").write_text(
        "package main\nfunc main() {}\n", encoding="utf-8")
    _commit_all(tmp_path, "init")
    assert not _js_ts_roots(tmp_path)


def test_jsx_and_js_modules_are_in_scope(tmp_path: Path):
    _init_repo(tmp_path)
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "view.jsx").write_text(
        "export function View() { return null; }\n", encoding="utf-8")
    _commit_all(tmp_path, "init")
    roots = _js_ts_roots(tmp_path)
    assert len(roots) == 1
    assert roots[0].subject == "web/view.jsx::js-ts-coverage"
    assert "JavaScript" in roots[0].title


# --- empty / Python-only regression guard -----------------------------------

def test_python_only_repo_seeds_no_js_ts_idea_and_is_unchanged(tmp_path: Path):
    # A Python-only repo seeds nothing new here, and the WHOLE seed set is
    # byte-identical to one produced without a wired project root (the only
    # source of polyglot facts) — the regression guard.
    _init_repo(tmp_path)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text("y = 2\n", encoding="utf-8")
    _commit_all(tmp_path, "init")
    profile = _profile_for(tmp_path)
    assert not [
        r for r in IdeaSeeder(str(tmp_path)).seed(profile)
        if r.source_facts and r.source_facts[0].startswith("js-ts-coverage")
    ]
    # Byte-identical: wiring a project root onto a Python-only repo adds no
    # js-ts root, so the rooted seed set equals the rootless one.
    rooted = [r.model_dump() for r in IdeaSeeder(str(tmp_path)).seed(profile)]
    rootless = [r.model_dump() for r in IdeaSeeder().seed(profile)]
    assert rooted == rootless


def test_bare_seeder_without_root_seeds_nothing_here(tmp_path: Path):
    # No wired project_root -> no polyglot facts read -> hermetic, no js-ts root,
    # even when the (in-memory) profile is otherwise populated.
    root = _churned_ts_repo(tmp_path)
    profile = _profile_for(root)
    roots = IdeaSeeder().seed(profile)  # note: NO root wired
    assert not [
        r for r in roots
        if r.source_facts and r.source_facts[0].startswith("js-ts-coverage")
    ]


# --- determinism ------------------------------------------------------------

def test_seeding_is_deterministic(tmp_path: Path):
    root = _churned_ts_repo(tmp_path)
    # A second untested module so ordering matters.
    (root / "web" / "extra.ts").write_text(
        "export const e = 1;\n", encoding="utf-8")
    _commit_all(root, "extra")
    first = [r.model_dump() for r in _js_ts_roots(root)]
    second = [r.model_dump() for r in _js_ts_roots(root)]
    assert first == second
    # Subjects are a stable, sorted-by-fact order (most churned first).
    assert first[0]["subject"] == "web/handler.ts::js-ts-coverage"


def test_capped_at_three(tmp_path: Path):
    _init_repo(tmp_path)
    (tmp_path / "web").mkdir()
    # Five untested JS/TS modules; module m{i} gets (i+1) commits so churn is
    # distinct and the ranking is total (most churned first).
    for i in range(5):
        (tmp_path / "web" / f"m{i}.ts").write_text(
            f"export const m{i} = 0;\n", encoding="utf-8")
    _commit_all(tmp_path, "init all")
    for i in range(5):
        for rev in range(i):
            (tmp_path / "web" / f"m{i}.ts").write_text(
                f"export const m{i} = {rev + 1};\n", encoding="utf-8")
            _commit_all(tmp_path, f"touch m{i} rev{rev}")
    assert len(_js_ts_roots(tmp_path)) == 3


# --- value axes + recommend-only --------------------------------------------

def test_root_value_axes_in_unit_interval(tmp_path: Path):
    root = _churned_ts_repo(tmp_path)
    idea = _js_ts_roots(root)[0]
    assert 0.0 <= idea.value <= 1.0
    assert 0.0 <= idea.feasibility <= 1.0
    assert 0.0 <= idea.novelty <= 1.0
    # Roots keep novelty == 1.0 (invariant).
    assert idea.novelty == 1.0
    assert idea.operator == "root"


def test_action_is_recommend_only(tmp_path: Path):
    root = _churned_ts_repo(tmp_path)
    idea = _js_ts_roots(root)[0]
    step = IdeaActionBridge().plan_idea(idea)
    # Apex has NO deterministic transform for JS/TS: the step must NOT claim to be
    # executable, even though the path looks like a real file.
    assert step.executable is False
    assert step.action_type == "design_task"


# --- export-line guard (string/comment-safe, pure) --------------------------

def test_export_anchor_skips_commented_and_stringy_exports(tmp_path: Path):
    _init_repo(tmp_path)
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "guarded.ts").write_text(
        "// export function fake() {}\n"
        "/* export const alsoFake = 1; */\n"
        "const s = 'export function stringy() {}';\n"
        "export function real(a) { return a; }\n",
        encoding="utf-8")
    _commit_all(tmp_path, "init")
    idea = _js_ts_roots(tmp_path)[0]
    assert idea.anchors[0]["symbol"] == "real"
    assert idea.anchors[0]["line"] == 4


def test_export_anchor_absent_when_no_public_export(tmp_path: Path):
    _init_repo(tmp_path)
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "internal.ts").write_text(
        "const helper = 1;\nfunction local() { return helper; }\n",
        encoding="utf-8")
    _commit_all(tmp_path, "init")
    idea = _js_ts_roots(tmp_path)[0]
    # No public export -> no anchor, and the title omits the export clause.
    assert idea.anchors == []
    assert "start with" not in idea.title


# --- pure unit on the test-file classifier ----------------------------------

def test_is_js_ts_test_file_classifier():
    is_test = IdeaSeeder._is_js_ts_test_file
    assert is_test("web/foo.test.ts")
    assert is_test("web/foo.spec.tsx")
    assert is_test("web/foo_test.js")
    assert is_test("web/test_foo.ts")
    assert is_test("tests/foo.ts")
    assert is_test("src/__tests__/foo.ts")
    assert not is_test("web/handler.ts")
    assert not is_test("src/components/Button.tsx")
