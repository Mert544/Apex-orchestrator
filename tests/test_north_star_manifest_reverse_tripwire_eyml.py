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


# --- (3) determinism ---------------------------------------------------------

def test_reverse_tripwire_is_deterministic():
    from app.engine.north_star_audit import manifest_subset_of_registry

    a = manifest_subset_of_registry()
    b = manifest_subset_of_registry()
    assert a == b


def test_injected_finding_is_deterministic():
    from app.engine.north_star_audit import manifest_subset_of_registry
    from app.engine.objective_compiler import available_objectives

    registry_missing = [n for n in available_objectives() if n != "tdd-implement"]
    first = manifest_subset_of_registry(registry_missing)
    second = manifest_subset_of_registry(registry_missing)
    assert first == second == ["tdd-implement"]
