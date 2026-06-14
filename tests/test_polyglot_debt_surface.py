"""DEBT-MARKER signal surfaced in the two places that NAME out-of-scope files.

`FileFact` (out-of-scope non-Python source) now carries a `debt_markers` count
(TODO/FIXME/HACK/XXX), and `ProjectProfile.polyglot_hotspots` dicts may carry the
same. Two surfaces name these files; this pins the additive debt clause on both:

  - `apex scope` (`render_scope_markdown` / `_scope_report` in cli_insight.py):
    an out-of-scope file with debt gets a trailing "N TODO/FIXME"; a no-debt file
    stays BYTE-IDENTICAL to before the signal existed.
  - the `polyglot-hotspot` idea (idea_seeder.py): the title/fact gains a debt
    clause ONLY IF the hotspot dict carries a truthy `debt_markers`; without the
    key the title/fact is byte-identical. The fact VALUE stays recommend-only —
    it must never contain the token "untested".

Deterministic, stdlib-only, LLM-free. The scope tests drive the render layer
directly (the real `scan_polyglot_facts` doesn't carry debt yet, so the live
`apex scope` path stays byte-identical until the profile field lands), plus a
real-repo no-debt byte-identity check.
"""

from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path

from app.cli_insight import _scope_report, render_scope_markdown
from app.engine.idea_seeder import IdeaSeeder
from app.tools.project_profile import ProjectProfile


# --- helpers ----------------------------------------------------------------

def _file_entry(debt: int | None = None) -> dict:
    """One out-of-scope file dict as `_scope_report` would build it. The
    ``debt_markers`` key is ADDED only when > 0 (mirrors the report assembler)."""
    entry = {
        "path": "web/app.js",
        "language": "JavaScript",
        "loc": 412,
        "churn": 8,
        "has_test": False,
    }
    if debt:
        entry["debt_markers"] = debt
    return entry


def _rep(files: list[dict]) -> dict:
    return {
        "source_file_count": 10,
        "python_file_count": 4,
        "analyzed_pct": 40,
        "out_of_scope_pct": 60,
        "all_python": False,
        "language_breakdown": [{"language": "JavaScript", "files": 1}],
        "files": files,
    }


def _profile(**kw) -> ProjectProfile:
    return ProjectProfile(root=".", **kw)


def _hot(path: str = "src/app.js", language: str = "JavaScript",
         loc: int = 412, churn: int = 8, **extra) -> dict:
    return {"path": path, "language": language, "loc": loc, "churn": churn, **extra}


def _polyglot_roots(profile: ProjectProfile):
    return [
        r for r in IdeaSeeder().seed(profile)
        if r.source_facts and r.source_facts[0].startswith("polyglot-hotspot")
    ]


def _run_scope(target: Path, json_out: bool = False) -> tuple[int, str]:
    from app.cli_insight import cmd_scope

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_scope(argparse.Namespace(target=str(target), json=json_out))
    return rc, buf.getvalue()


def _polyglot_repo(root: Path) -> None:
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "web").mkdir(parents=True, exist_ok=True)
    (root / "app" / "core.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (root / "app" / "util.py").write_text("VALUE = 2\n", encoding="utf-8")
    (root / "web" / "app.js").write_text("function go() { return 1; }\n" * 20,
                                         encoding="utf-8")


# --- scope render: the debt clause is additive and ONLY > 0 -----------------

def test_scope_render_shows_debt_when_present():
    out = render_scope_markdown(_rep([_file_entry(debt=5)]))
    assert "`web/app.js`" in out
    assert "5 TODO/FIXME" in out
    # Recommend-only language: the debt clause never claims "untested".
    assert "untested" not in out


def test_scope_render_no_debt_is_byte_identical():
    # The no-debt line must be byte-for-byte what it was before the signal: the
    # rendered report with a debt-free file carries no debt clause at all.
    out = render_scope_markdown(_rep([_file_entry(debt=None)]))
    assert "TODO/FIXME" not in out
    # And the file line is exactly the pre-signal shape (flag, no debt clause).
    assert "- `web/app.js` (JavaScript, 412 LOC, 8 commits) — no test found" in out


def test_scope_render_zero_debt_key_is_byte_identical():
    # A defensively-present `debt_markers: 0` must behave like an absent key.
    no_key = render_scope_markdown(_rep([_file_entry(debt=None)]))
    zero = render_scope_markdown(_rep([{**_file_entry(), "debt_markers": 0}]))
    assert no_key == zero
    assert "TODO/FIXME" not in zero


def test_scope_render_debt_only_changes_the_debt_line():
    # Adding debt to one file is purely additive: the rest of the report (every
    # line except the one named file's line) is unchanged.
    base = render_scope_markdown(_rep([_file_entry(debt=None)])).splitlines()
    debted = render_scope_markdown(_rep([_file_entry(debt=3)])).splitlines()
    assert len(base) == len(debted)
    diffs = [(b, d) for b, d in zip(base, debted) if b != d]
    assert len(diffs) == 1
    b, d = diffs[0]
    assert d == b + " — 3 TODO/FIXME"


def test_scope_render_deterministic():
    rep = _rep([_file_entry(debt=7)])
    assert render_scope_markdown(rep) == render_scope_markdown(rep)


# --- scope report over a real repo: no-debt path stays byte-identical --------

def test_scope_report_real_repo_no_debt_byte_identical(tmp_path):
    # The live `scan_polyglot_facts` carries no debt today, so a real polyglot
    # repo names the out-of-scope file WITHOUT any debt clause — byte-identical
    # to the pre-signal report. (When the profile/FileFact field lands, the
    # render layer above already shows it.)
    _polyglot_repo(tmp_path)
    rep = _scope_report(tmp_path)
    paths = {f["path"] for f in rep["files"]}
    assert "web/app.js" in paths
    # No file entry carries the key yet, and the rendered report has no clause.
    assert all("debt_markers" not in f for f in rep["files"])
    out = render_scope_markdown(rep)
    assert "web/app.js" in out
    assert "TODO/FIXME" not in out


def test_scope_cmd_runs_clean_over_real_repo(tmp_path):
    _polyglot_repo(tmp_path)
    rc, out = _run_scope(tmp_path)
    assert rc == 0
    assert "web/app.js" in out
    assert "TODO/FIXME" not in out


# --- seeder: debt clause fires only when the hotspot dict carries it ---------

def test_seed_no_debt_key_title_and_fact_byte_identical():
    plain = _polyglot_roots(_profile(polyglot_hotspots=[_hot()]))[0]
    # No `debt_markers` key on the hotspot dict -> no clause anywhere.
    assert "TODO/FIXME" not in plain.title
    assert "TODO/FIXME" not in plain.source_facts[0]
    # Recommend-only fact: never the token "untested".
    assert "untested" not in plain.source_facts[0]


def test_seed_zero_debt_is_byte_identical_to_no_key():
    no_key = _polyglot_roots(_profile(polyglot_hotspots=[_hot()]))[0]
    zero = _polyglot_roots(_profile(polyglot_hotspots=[_hot(debt_markers=0)]))[0]
    assert no_key.title == zero.title
    assert no_key.source_facts[0] == zero.source_facts[0]


def test_seed_debt_clause_in_title_and_fact():
    root = _polyglot_roots(_profile(polyglot_hotspots=[_hot(debt_markers=4)]))[0]
    assert "4 TODO/FIXME" in root.title
    assert "4 TODO/FIXME" in root.source_facts[0]
    # The fact VALUE must stay recommend-only: never "untested".
    assert "untested" not in root.source_facts[0]
    # Still grounded in the file and the awareness framing.
    assert "src/app.js" in root.title
    assert "outside Apex's Python analysis scope" in root.source_facts[0]


def test_seed_debt_clause_does_not_disturb_other_fields():
    root = _polyglot_roots(_profile(polyglot_hotspots=[_hot(debt_markers=2)]))[0]
    assert root.subject == "src/app.js"
    assert root.novelty == 1.0
    assert 0.0 <= root.value <= 1.0
    assert 0.0 <= root.feasibility <= 1.0


def test_seed_debt_is_deterministic():
    profile = _profile(polyglot_hotspots=[_hot(debt_markers=6)])
    first = [r.model_dump() for r in _polyglot_roots(profile)]
    second = [r.model_dump() for r in _polyglot_roots(profile)]
    assert first == second
