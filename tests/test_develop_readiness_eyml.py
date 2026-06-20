"""Tests for the foreign-repo develop-readiness profile (eyml).

Covers the sharp question — what share of detected findings does Apex have a
landing transform for — across an all-fixable repo, a design-only/unmapped repo,
an empty repo, determinism, and the exhaustive/disjoint partition invariant.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.brief_develop import develop_readiness_section
from app.engine.develop_readiness import (
    classify_fix_kind,
    develop_readiness,
    render_develop_readiness_markdown,
)


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


# --- classify_fix_kind: the per-fix-kind routing -------------------------------

def test_classify_rewrite_fix_kinds_are_fixable_now():
    for fk in ("eval", "yaml", "bare except", "mutable-default",
               "none-comparison", "collection-literal", "docstring"):
        assert classify_fix_kind(fk) == "fixable_now", fk


def test_classify_flag_only_fix_kinds():
    for fk in ("pickle", "sql", "tempfile", "weak-hash", "os.popen",
               "tls-verify", "zip-slip", "net-timeout", "debug-flag"):
        assert classify_fix_kind(fk) == "flag_only", fk


def test_classify_empty_and_unmapped_is_unknown():
    assert classify_fix_kind("") == "unknown"
    assert classify_fix_kind("no-such-kind") == "unknown"


# --- all-fixable repo scores high ----------------------------------------------

def test_all_fixable_repo_scores_high(tmp_path):
    # eval -> literal_eval, yaml.load -> safe_load: both REWRITES (fixable now).
    _write(tmp_path, "a.py", "import yaml\nyaml.load(open('x'))\n")
    _write(tmp_path, "b.py", "result = eval(payload)\n")

    out = develop_readiness(root=str(tmp_path))

    assert out["score"] == 1.0
    assert out["counts"]["fixable_now"] >= 2
    assert out["counts"]["flag_only"] == 0
    fixable_kinds = {f["fix_kind"] for f in out["buckets"]["fixable_now"]}
    assert {"eval", "yaml"} <= fixable_kinds
    # Nothing the engine could fix is hiding in another bucket.
    assert out["buckets"]["flag_only"] == []


# --- design-only / unmapped repo scores low, honestly --------------------------

def test_design_only_repo_scores_low(tmp_path):
    # pickle.loads (flag-only) + exec / hardcoded-secret (no fix_kind -> unknown).
    _write(tmp_path, "loader.py", "import pickle\npickle.loads(blob)\n")
    _write(tmp_path, "danger.py", "exec(user_code)\n")
    _write(tmp_path, "conf.py", 'password = "supersecretvalue"\n')

    out = develop_readiness(root=str(tmp_path))

    assert out["score"] == 0.0
    assert out["counts"]["fixable_now"] == 0
    assert out["counts"]["flag_only"] >= 1   # pickle
    assert out["counts"]["unknown"] >= 1     # exec / secret
    flag_kinds = {f["fix_kind"] for f in out["buckets"]["flag_only"]}
    assert "pickle" in flag_kinds
    # The unknown bucket holds only no-fix_kind findings.
    assert all(f["fix_kind"] == "" for f in out["buckets"]["unknown"])


def test_mixed_repo_score_is_fixable_share(tmp_path):
    # One fixable (eval) + one flag (pickle) + one unknown (exec) => 1/3.
    _write(tmp_path, "m.py", "import pickle\neval(x)\npickle.loads(b)\nexec(c)\n")

    out = develop_readiness(root=str(tmp_path))

    assert out["total"] == 3
    assert out["counts"] == {"fixable_now": 1, "flag_only": 1, "unknown": 1}
    assert out["score"] == round(1 / 3, 6)


# --- empty repo -> safe zero ---------------------------------------------------

def test_empty_repo_safe_zero(tmp_path):
    out = develop_readiness(root=str(tmp_path))
    assert out["score"] == 0.0
    assert out["total"] == 0
    assert out["counts"] == {"fixable_now": 0, "flag_only": 0, "unknown": 0}
    assert out["buckets"] == {"fixable_now": [], "flag_only": [], "unknown": []}


def test_no_root_is_safe_zero():
    out = develop_readiness(root="")
    assert out["score"] == 0.0
    assert out["total"] == 0


def test_clean_repo_no_findings_safe_zero(tmp_path):
    _write(tmp_path, "clean.py", "def _helper(x):\n    return x + 1\n")
    out = develop_readiness(root=str(tmp_path))
    assert out["total"] == 0
    assert out["score"] == 0.0


# --- determinism ---------------------------------------------------------------

def test_determinism_across_two_runs(tmp_path):
    _write(tmp_path, "a.py", "import yaml\nyaml.load(x)\n")
    _write(tmp_path, "b.py", "import pickle\npickle.loads(b)\nexec(c)\n")
    _write(tmp_path, "c.py", "eval(z)\n")

    first = develop_readiness(root=str(tmp_path))
    second = develop_readiness(root=str(tmp_path))
    assert first == second


# --- partition is exhaustive AND disjoint --------------------------------------

def test_partition_is_exhaustive_and_disjoint(tmp_path):
    _write(tmp_path, "a.py", "import yaml\nyaml.load(x)\n")
    _write(tmp_path, "b.py", "import pickle\npickle.loads(b)\n")
    _write(tmp_path, "c.py", "exec(c)\n")
    _write(tmp_path, "d.py", "eval(z)\nresult = obj == None\n")

    out = develop_readiness(root=str(tmp_path))
    bucket_total = sum(out["counts"].values())
    assert bucket_total == out["total"]
    # Disjoint: no finding identity appears in two buckets.
    seen: set[tuple] = set()
    for items in out["buckets"].values():
        for f in items:
            key = (f["file"], f["line"], f["fix_kind"], f["message"])
            assert key not in seen
            seen.add(key)


# --- reliability weighting is opt-in and default-off ---------------------------

def test_weighting_default_off(tmp_path):
    _write(tmp_path, "a.py", "eval(x)\n")
    out = develop_readiness(root=str(tmp_path))
    assert out["weighted"] is False


def test_weighting_opt_in_no_history_falls_back_to_count(tmp_path):
    # No proof history => weight 1.0 each => score equals the unweighted share.
    _write(tmp_path, "a.py", "eval(x)\nimport pickle\npickle.loads(b)\n")
    weighted = develop_readiness(root=str(tmp_path), weight_by_reliability=True)
    unweighted = develop_readiness(root=str(tmp_path))
    assert weighted["score"] == unweighted["score"]
    assert weighted["weighted"] is False  # no record -> not actually weighted


# --- render ---------------------------------------------------------------------

def test_render_reports_landing_share(tmp_path):
    _write(tmp_path, "a.py", "eval(x)\nimport pickle\npickle.loads(b)\nexec(c)\n")
    md = render_develop_readiness_markdown(develop_readiness(root=str(tmp_path)))
    assert "Develop-readiness" in md
    assert "Landing share" in md
    assert "Fixable now" in md and "Flag only" in md and "Unknown" in md


def test_render_empty_repo():
    md = render_develop_readiness_markdown(develop_readiness(root=""))
    assert "No detectable findings" in md


# --- additive brief hook --------------------------------------------------------

def test_brief_hook_returns_section(tmp_path):
    _write(tmp_path, "a.py", "eval(x)\n")
    section = develop_readiness_section(tmp_path)
    assert "Develop-readiness" in section
    assert "Landing share" in section


def test_brief_hook_empty_repo(tmp_path):
    section = develop_readiness_section(tmp_path)
    assert "No detectable findings" in section
