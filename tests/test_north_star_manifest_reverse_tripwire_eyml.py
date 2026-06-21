"""The REVERSE manifest tripwire in the North-Star denetçi.

The North-Star auditor classifies develop objectives against an EXPLICIT manifest
taxonomy (``OBJECTIVE_MANIFEST``). A FORWARD tripwire already exists:
``classify_objectives`` RAISES if a REGISTERED objective is missing from the
manifest (the manifest can't fall BEHIND the registry).

The denetçi flagged the MIRROR hazard: the manifest can list a name that is NOT a
currently-registered objective (a renamed/removed objective left stale in the
manifest), and nothing caught that drift. :func:`manifest_subset_of_registry` is
the REVERSE tripwire — it returns the manifest names with no live objective
behind them, validated against the SAME live set the forward tripwire uses
(``available_objectives()`` — built-in + discovered). ``north_star_report`` folds
any stale entry into ``drift`` so the ``--north-star`` CLI exits non-zero on it,
matching the forward tripwire's severity.

These tests prove: (1) with the REAL manifest + REAL registry the reverse check
PASSES (the current manifest is clean — the one real stale entry, ``fix-docstrings``,
a CLI-only subcommand, was removed as part of this fix); (2) a synthetic stale
manifest name is FLAGGED, both by the function directly and through the report's
``drift``/``verdict``; and (3) determinism (same inputs -> identical finding).
"""

from __future__ import annotations


# --- (1) the REAL manifest + REAL registry is clean --------------------------

def test_real_manifest_is_clean_no_stale_entries():
    from app.engine.north_star_audit import manifest_subset_of_registry

    # Every manifest name has a live objective behind it. If this ever fails it is
    # a REAL finding (a stale manifest entry) — remove the name from
    # OBJECTIVE_MANIFEST rather than papering over it here.
    assert manifest_subset_of_registry() == []


def test_real_report_key_set_is_unchanged():
    from app.engine.north_star_audit import north_star_report

    # The reverse tripwire folds into `drift` WITHOUT adding a new report key —
    # the report's key set stays stable (existing JSON consumers are unaffected).
    report = north_star_report(".")
    assert set(report.keys()) == {
        "concrete_ratio", "buckets", "bucket_counts",
        "total_objectives", "commit_window", "drift", "verdict",
    }
    # A clean manifest contributes nothing to drift on its own.
    from app.engine.north_star_audit import manifest_subset_of_registry
    assert manifest_subset_of_registry() == []


def test_fix_docstrings_was_removed_from_manifest():
    # `fix-docstrings` is a standalone CLI subcommand, NOT a develop objective in
    # available_objectives(), so it was the one real stale entry — confirm it is
    # gone from the manifest (the fix that made the real manifest clean).
    from app.engine.north_star_audit import OBJECTIVE_MANIFEST
    from app.engine.objective_compiler import available_objectives

    names = set().union(*OBJECTIVE_MANIFEST.values())
    assert "fix-docstrings" not in names
    assert "fix-docstrings" not in set(available_objectives())


# --- (2) a synthetic stale entry is FLAGGED ----------------------------------

def test_injected_stale_manifest_entry_is_flagged():
    from app.engine.north_star_audit import manifest_subset_of_registry

    # The live registry is missing one name the manifest lists (here we supply a
    # registry that lacks `strengthen-tests`) -> that manifest name is stale.
    from app.engine.objective_compiler import available_objectives

    registry_missing_one = [n for n in available_objectives()
                            if n != "strengthen-tests"]
    stale = manifest_subset_of_registry(registry_missing_one)
    assert stale == ["strengthen-tests"]


def test_constructed_stale_manifest_entry_via_monkeypatch(monkeypatch):
    import app.engine.north_star_audit as ns

    # Inject a wholly synthetic stale name into the manifest taxonomy.
    patched = dict(ns.OBJECTIVE_MANIFEST)
    patched["CONCRETE"] = frozenset(patched["CONCRETE"] | {"renamed-away-objective"})
    monkeypatch.setattr(ns, "OBJECTIVE_MANIFEST", patched)

    stale = ns.manifest_subset_of_registry()
    assert "renamed-away-objective" in stale


def test_report_drift_and_verdict_on_injected_stale(monkeypatch):
    import app.engine.north_star_audit as ns

    patched = dict(ns.OBJECTIVE_MANIFEST)
    patched["CONCRETE"] = frozenset(patched["CONCRETE"] | {"ghost-objective"})
    monkeypatch.setattr(ns, "OBJECTIVE_MANIFEST", patched)

    report = ns.north_star_report(".")
    # A stale manifest name with no live objective folds straight into drift, so
    # the --north-star CLI (which exits non-zero on report["drift"]) trips.
    assert report["drift"] is True
    assert report["verdict"] == "DRIFT"
    # No new report key was introduced (the key set is held stable).
    assert "stale_manifest_entries" not in report


def test_render_markdown_surfaces_stale_entries(monkeypatch):
    import app.engine.north_star_audit as ns

    # render_markdown recomputes the reverse-tripwire names from module state, so
    # inject a stale name into the manifest and assert it is displayed.
    patched = dict(ns.OBJECTIVE_MANIFEST)
    patched["CONCRETE"] = frozenset(patched["CONCRETE"] | {"ghost-objective"})
    monkeypatch.setattr(ns, "OBJECTIVE_MANIFEST", patched)

    report = {
        "verdict": "DRIFT",
        "concrete_ratio": 0.5,
        "bucket_counts": {"CONCRETE": 1, "TIDY": 1, "SAFETY": 0},
        "total_objectives": 2,
        "commit_window": None,
        "buckets": {"CONCRETE": ["x"], "TIDY": ["y"], "SAFETY": []},
    }
    md = ns.render_markdown(report, "/tmp/x")
    assert "STALE MANIFEST ENTRIES" in md
    assert "ghost-objective" in md


# --- (3) the REAL recent window reads accurately (concrete-count fidelity) ----
#
# The denetçi audited ITSELF and found the commit-window concrete count was
# under-reported: the develop CORE ships under finer scopes than `develop`
# (`stub-synthesis`, `implement-stub`, `wire-exports`, `type-hints`, ...), so
# genuinely concrete commits were mis-bucketed as neutral. With those scopes
# credited, the real window must (a) still PASS with drift=False and (b) report a
# concrete count that reflects the develop-core commits (several, not ~1).

def test_real_recent_window_passes_with_accurate_concrete_count():
    from app.engine.north_star_audit import commit_drift, north_star_report

    window = commit_drift(".", 30)
    if window is None:  # non-git checkout (e.g. exported tarball) — nothing to assert
        return
    # The drift CONDITION is unchanged (concrete==0 AND safety>0); the recent
    # window has real landing work, so it does not drift.
    assert window["drift"] is False
    # Fidelity: the recent window credits multiple develop-core commits, not ~1.
    assert window["concrete"] >= 5
    # Counts are coherent and exhaustive.
    assert window["concrete"] + window["safety"] + window["neutral"] == window["total"]

    report = north_star_report(".", 30)
    assert report["verdict"] == "PASS"
    assert report["drift"] is False
    assert report["commit_window"]["concrete"] >= 5


def test_real_window_is_not_inflated_meta_stays_non_concrete():
    # Honesty guard against the real repo: a pure-meta commit TYPE must never be
    # classified concrete even when it carries a develop-core SCOPE. Only feat/fix
    # land/gate code; a `refactor(implement-stub)`/`perf(implement-stub)` tidies or
    # tunes EXISTING code, so `_classify_subject` must return non-concrete. (This
    # is exactly the `refactor(implement-stub)`/`perf(implement-stub)` shape in the
    # live window — the type gate, not the scope set, keeps them honest.)
    import re

    from app.engine.north_star_audit import _CONCRETE_SCOPES, _classify_subject, _git_subjects

    # A meta TYPE carrying a concrete SCOPE must still be non-concrete — the type
    # gate (only feat/fix land/gate code), not the scope set, is what keeps it
    # honest. Exercise this directly so the guard is meaningful regardless of which
    # commits sit in the live window.
    a_core_scope = sorted(_CONCRETE_SCOPES)[0]
    for meta in ("refactor", "perf", "docs", "chore", "build", "style", "ci", "test"):
        assert _classify_subject(f"{meta}({a_core_scope}): tidy existing code") != "concrete"

    # And against the REAL window: no meta-typed subject is ever bucketed concrete.
    subjects = _git_subjects(".", 30)
    if subjects is None:
        return
    meta_types = {"docs", "ci", "test", "chore", "build", "refactor", "perf", "style"}
    scope_re = re.compile(r"^(\w+)\(")
    for s in subjects:
        m = scope_re.match(s)
        if m and m.group(1) in meta_types:
            assert _classify_subject(s) != "concrete", s


# --- (4) determinism ---------------------------------------------------------

def test_reverse_tripwire_is_deterministic():
    from app.engine.north_star_audit import manifest_subset_of_registry

    a = manifest_subset_of_registry()
    b = manifest_subset_of_registry()
    assert a == b


def test_real_commit_window_classification_is_deterministic():
    # Same window classified twice -> identical counts (no clock/random leak).
    from app.engine.north_star_audit import commit_drift

    first = commit_drift(".", 30)
    second = commit_drift(".", 30)
    assert first == second


def test_injected_finding_is_deterministic():
    from app.engine.north_star_audit import manifest_subset_of_registry
    from app.engine.objective_compiler import available_objectives

    registry_missing = [n for n in available_objectives() if n != "tdd-implement"]
    first = manifest_subset_of_registry(registry_missing)
    second = manifest_subset_of_registry(registry_missing)
    assert first == second == ["tdd-implement"]
