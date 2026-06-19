"""Time-decay acceleration for app.engine.temporal_discovery.

The intelligence red-team flagged a data-SHAPE sensitivity in the original
``emerging_hotspots`` / ``spreading_pairs``: they split git history into an OLDER
half and a RECENT half and compared raw counts. A hard median boundary mis-reads
a bursty / contiguous churn history — a file whose changes plainly cluster toward
the recent end can land recent==older and read as "stable", and a file straddling
the median can hide real acceleration.

The fix weights each commit by its ORDER in the newest-first log (NOT wall-clock
time, so it stays deterministic and offline): newest weighs ``_DECAY_BASE**0``,
the next ``_DECAY_BASE**1``, and so on. A subject's acceleration is its weighted
activity minus the activity an evenly-spread subject with the same change count
would earn — positive when changes cluster recent, ~= 0 when even, negative when
old. No median boundary to straddle.

This suite pins:

  * the decay primitives (``_decay_weights`` / ``_weighted_activity`` /
    ``_acceleration`` / ``_accel_trend``) to exact values;
  * the HARD GATE: within a single contiguous burst, a recent-clustered file
    scores higher acceleration than the same number of changes spread evenly,
    which in turn beats an early-clustered file — the case the half-split missed;
  * determinism: same git state => identical output across two runs;
  * the best-effort contract: non-git / missing / empty root => ``[]``.

All inputs are fixed literals or a hermetic throwaway repo; no time/random/network.
"""

from __future__ import annotations

import os
import subprocess

from app.engine import temporal_discovery as td
from app.engine.temporal_discovery import (
    _DECAY_BASE,
    _accel_trend,
    _acceleration,
    _decay_weights,
    _weighted_activity,
    _weighted_pair_activity,
    emerging_hotspots,
    spreading_pairs,
)


# --- decay constant + primitives pinned exactly ----------------------------


def test_decay_base_is_the_pinned_constant():
    assert _DECAY_BASE == 0.9


def test_decay_weights_decay_from_one_by_position():
    # Newest commit (index 0) weighs 1.0; weight = _DECAY_BASE ** position.
    w = _decay_weights(4)
    assert w[0] == 1.0
    assert w == [1.0, 0.9, 0.9 ** 2, 0.9 ** 3]
    # Strictly decreasing: newer always outweighs older.
    assert all(w[i] > w[i + 1] for i in range(len(w) - 1))


def test_decay_weights_nonpositive_is_empty():
    assert _decay_weights(0) == []
    assert _decay_weights(-3) == []


def test_weighted_activity_sums_recency_weights_per_file():
    weights = _decay_weights(3)  # [1.0, 0.9, 0.81]
    activity = _weighted_activity(
        [["app/a.py"], ["app/a.py", "app/b.py"], ["app/b.py"]],
        weights,
    )
    # a: commits 0 + 1 = 1.0 + 0.9 ; b: commits 1 + 2 = 0.9 + 0.81.
    assert activity["app/a.py"] == 1.0 + 0.9
    assert activity["app/b.py"] == 0.9 + 0.81


def test_weighted_pair_activity_uses_canonical_order():
    weights = _decay_weights(2)  # [1.0, 0.9]
    activity = _weighted_pair_activity(
        [["app/a.py", "app/b.py"], ["app/a.py", "app/b.py"]],
        weights,
    )
    assert activity == {("app/a.py", "app/b.py"): 1.0 + 0.9}


def test_acceleration_is_weighted_minus_even_baseline():
    # 2 changes, mean_weight 0.5 => even baseline = 1.0; weighted 1.5 => +0.5.
    assert _acceleration(1.5, 2, 0.5) == 0.5
    # Evenly spread => weighted == count*mean => zero excess.
    assert _acceleration(1.0, 2, 0.5) == 0.0
    # Old-clustered => below baseline => negative.
    assert _acceleration(0.5, 2, 0.5) == -0.5


def test_accel_trend_three_branches_with_epsilon_tie():
    assert _accel_trend(0.5) == "accelerating"
    assert _accel_trend(-0.5) == "cooling"
    # Float dust around an evenly-spread subject reads stable, not flapping.
    assert _accel_trend(0.0) == "stable"
    assert _accel_trend(1e-12) == "stable"
    assert _accel_trend(-1e-12) == "stable"


# --- HARD GATE: recent-clustered > even-spread > early-clustered ------------


def test_recent_cluster_beats_even_beats_early_within_one_burst():
    """The case the hard half-split missed.

    Nine commits form ONE contiguous burst. Three files each change EXACTLY twice
    (same raw count), but at different positions in the sequence:

      recent.py -> the two NEWEST commits (0, 1)
      even.py   -> the dead center (4, 5)
      old.py    -> the two OLDEST commits (7, 8)

    Decay scores them strictly recent > even > old, so only ``recent.py`` is an
    accelerating hotspot — acceleration the median split could not see.
    """
    weights = _decay_weights(9)
    mean = sum(weights) / 9
    commits = [
        ["app/recent.py"], ["app/recent.py"],
        ["z/x.py"], ["z/x.py"],
        ["app/even.py"], ["app/even.py"],
        ["z/y.py"],
        ["app/old.py"], ["app/old.py"],
    ]
    wa = _weighted_activity(commits, weights)
    accel = {m: _acceleration(wa[m], 2, mean)
             for m in ("app/recent.py", "app/even.py", "app/old.py")}

    # Strict monotone ordering on identical change counts.
    assert accel["app/recent.py"] > accel["app/even.py"] > accel["app/old.py"]
    # Recent-clustered is the only accelerating one.
    assert _accel_trend(accel["app/recent.py"]) == "accelerating"
    assert _accel_trend(accel["app/even.py"]) != "accelerating"
    assert _accel_trend(accel["app/old.py"]) == "cooling"


def test_emerging_hotspots_surfaces_recent_cluster_within_burst(monkeypatch):
    """End-to-end gate through the public function: the recent-clustered file is
    returned accelerating; the even and early files are not, even though all three
    have the same change count inside one contiguous burst."""
    commits = [
        ["app/recent.py"], ["app/recent.py"],
        ["z/x.py"], ["z/x.py"],
        ["app/even.py"], ["app/even.py"],
        ["z/y.py"],
        ["app/old.py"], ["app/old.py"],
    ]
    monkeypatch.setattr(td, "_load_commits", lambda root: commits)
    rows = emerging_hotspots("ignored", decay=True)
    mods = [r["module"] for r in rows]
    assert "app/recent.py" in mods
    assert "app/even.py" not in mods
    assert "app/old.py" not in mods
    # The accel field is present, positive, and rounded to 6 places.
    top = rows[0]
    assert top["module"] == "app/recent.py"
    assert top["accel"] > 0
    assert top["accel"] == round(top["accel"], 6)


def test_spreading_pairs_surfaces_recent_cluster_within_burst(monkeypatch):
    """Same gate for co-change pairs: a seam tightening at the recent end of a
    contiguous burst surfaces, while an early-clustered seam (cooling) does not."""
    commits = [
        ["app/a.py", "app/b.py"], ["app/a.py", "app/b.py"],   # recent pair
        ["z/x.py", "z/w.py"], ["z/x.py", "z/w.py"],
        ["app/c.py", "app/d.py"], ["app/c.py", "app/d.py"],   # old pair
        ["z/y.py", "z/v.py"],
    ]
    monkeypatch.setattr(td, "_load_commits", lambda root: commits)
    rows = spreading_pairs("ignored", top=5, decay=True)
    pairs = {(r["a"], r["b"]) for r in rows}
    assert ("app/a.py", "app/b.py") in pairs       # recent seam tightens
    assert ("app/c.py", "app/d.py") not in pairs    # early seam is cooling
    # cochanges remains the integer total; accel is present and positive.
    hit = next(r for r in rows if (r["a"], r["b"]) == ("app/a.py", "app/b.py"))
    assert hit["cochanges"] == 2
    assert hit["accel"] > 0
    assert hit["trend"] == "accelerating"


# --- determinism + best-effort contract (git-backed, hermetic) -------------


_ENV = {
    "GIT_AUTHOR_NAME": "Apex", "GIT_AUTHOR_EMAIL": "apex@example.com",
    "GIT_COMMITTER_NAME": "Apex", "GIT_COMMITTER_EMAIL": "apex@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=repo, env={"PATH": os.environ.get("PATH", ""), **_ENV},
        check=True, capture_output=True, text=True,
    )


def _commit(repo, n, files):
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"commit {n}")


def _burst_repo(tmp_path):
    """A single contiguous burst (oldest-first build): a noise anchor in every
    commit plus a target file that appears only in the two NEWEST commits, so the
    decay signal must read it as accelerating without any older/recent gap."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    for i in range(4):  # older part of the burst: anchor only
        _commit(repo, i, {"app/anchor.py": f"# anchor {i}\n"})
    for i in range(4, 6):  # newest two commits add the target
        _commit(repo, i, {
            "app/anchor.py": f"# anchor {i}\n",
            "app/target.py": f"# target {i}\n",
        })
    return repo


def test_decay_signal_deterministic_across_two_runs(tmp_path):
    repo = _burst_repo(tmp_path)
    assert emerging_hotspots(str(repo), decay=True) == \
        emerging_hotspots(str(repo), decay=True)
    assert spreading_pairs(str(repo), decay=True) == \
        spreading_pairs(str(repo), decay=True)
    # And the recent-clustered target is actually flagged accelerating.
    mods = {r["module"] for r in emerging_hotspots(str(repo), decay=True)}
    assert "app/target.py" in mods


def test_decay_default_off_preserves_half_split(tmp_path):
    """Opt-in invariant: ``decay`` defaults OFF, so the public functions return
    the historical half-split rows (no ``accel`` key) unless asked."""
    repo = _burst_repo(tmp_path)
    default_rows = emerging_hotspots(str(repo))
    assert default_rows  # the burst still surfaces the target via the half-split
    assert all("accel" not in r for r in default_rows)
    decay_rows = emerging_hotspots(str(repo), decay=True)
    assert all("accel" in r for r in decay_rows)


def test_non_git_directory_yields_empty(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "app").mkdir()
    (plain / "app" / "x.py").write_text("# x\n", encoding="utf-8")
    assert emerging_hotspots(str(plain), decay=True) == []
    assert spreading_pairs(str(plain), decay=True) == []
    # Default path is empty for a non-git dir too.
    assert emerging_hotspots(str(plain)) == []
    assert spreading_pairs(str(plain)) == []


def test_missing_directory_yields_empty(tmp_path):
    missing = tmp_path / "nope"
    assert emerging_hotspots(str(missing), decay=True) == []
    assert spreading_pairs(str(missing), decay=True) == []


def test_single_commit_has_no_acceleration(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _commit(repo, 0, {"app/a.py": "# a\n", "app/b.py": "# b\n"})
    # Fewer than two commits to weigh => no decay signal possible.
    assert emerging_hotspots(str(repo), decay=True) == []
    assert spreading_pairs(str(repo), decay=True) == []
    # Default half-split also has no two halves for one commit.
    assert emerging_hotspots(str(repo)) == []
    assert spreading_pairs(str(repo)) == []
