"""Value-landed — the deterministic buyer-value measurement layer.

``value_landed`` is a pure fold over the SAME proof-of-fix ``fixes`` records the
tamper seal consumes; ``value_landed_from_session`` is the in-memory adapter; the
``proof_of_value.value_bundle`` adds a value block OUTSIDE ``proof_hash``; the
``render_session_markdown`` value section is additive/present-only-when-present;
and ``apex self-audit --value-landed`` (+ ``--min-verified-value``) is the durable
check. These tests pin:

  * the NEVER-FAKE-GREEN gate — value counted ONLY for applied-and-held moves;
  * the HONEST tier separation — verified / weak / unverified never blended;
  * buyer-tier rollups over the ``move_value`` cutoffs (unknown → DEFAULT, no
    starvation, no crash);
  * full DETERMINISM (byte-identical out, stable top-contribution order);
  * the session adapter's tier→bucket map;
  * the bundle's ``proof_hash`` byte-identity (value is a derived view);
  * the render section's additive present-only-when-present byte-identity;
  * the CLI exit codes + JSON;
  * the value-coverage tripwire;
  * the empty / nothing-held edge.

Deterministic, stdlib-only, no LLM. The ``_eyml`` house suffix.
"""

from __future__ import annotations

import argparse
import json

from app.engine.develop_session import (
    SessionMove,
    SessionObjective,
    SessionReport,
    render_session_markdown,
)
from app.engine.move_value import DEFAULT_VALUE, move_value
from app.engine.proof_of_fix import build_proof, proof_hash
from app.engine.proof_of_value import (
    proof_bundle,
    value_bundle,
    write_value_bundle,
)
from app.engine.value_landed import (
    VALUE_SCHEMA,
    value_coverage_gaps,
    value_landed,
    value_landed_from_session,
)


# --------------------------------------------------------------------------- #
# helpers — build a proof-of-fix record the exact way _fix_record shapes it     #
# --------------------------------------------------------------------------- #
def _rec(operator, outcome="applied", level="function", rolled_back=False,
         target="app/m.py"):
    return {
        "finding": {"operator": operator, "target": target},
        "outcome": outcome,
        "verification": {"strength": {"level": level}},
        "rollback": {"occurred": rolled_back},
    }


# --------------------------------------------------------------------------- #
# never-fake-green: only applied-AND-held moves count                          #
# --------------------------------------------------------------------------- #
def test_value_landed_verified_only_counts_applied_and_held():
    held = _rec("implement_stub", level="function")          # value 1.00, verified
    reverted = _rec("implement_stub", outcome="rolled_back",  # rolled back -> 0
                    rolled_back=True)
    blocked = _rec("extract", outcome="blocked")             # blocked -> 0
    m = value_landed([held, reverted, blocked])
    assert m["value_landed_verified"] == 1.0
    assert m["moves_verified"] == 1
    # The reverted + blocked moves contribute ZERO to every bucket.
    assert m["value_landed_weak"] == 0.0 and m["value_landed_unverified"] == 0.0
    assert m["moves_weak"] == 0 and m["moves_unverified"] == 0


def test_applied_but_rollback_occurred_true_contributes_nothing():
    # outcome applied yet rollback.occurred True (a paranoid record) -> not held.
    rec = _rec("implement_stub", outcome="applied", rolled_back=True)
    m = value_landed([rec])
    assert m["value_landed_verified"] == 0.0 and m["moves_verified"] == 0
    assert m["verdict"] == "no value landed"


# --------------------------------------------------------------------------- #
# honest tier separation: verified / weak / unverified never blended           #
# --------------------------------------------------------------------------- #
def test_value_landed_separates_weak_from_verified():
    weak = _rec("dedup_extract", level="none")          # green but uncovered -> weak
    base_red = _rec("implement_stub", level="baseline-red")  # inconclusive -> unverif
    no_suite = _rec("modernize", level="no-suite")           # nothing ran -> unverif
    m = value_landed([weak, base_red, no_suite])
    # weak value is the dedup move, NOT in the verified total.
    assert m["value_landed_verified"] == 0.0
    assert m["value_landed_weak"] == move_value("dedup_extract")
    assert m["moves_weak"] == 1
    # baseline-red + no-suite are unverified, contributing 0 toward verified.
    assert m["value_landed_unverified"] == round(
        move_value("implement_stub") + move_value("modernize"), 4)
    assert m["moves_unverified"] == 2


def test_test_change_coverage_is_verified():
    m = value_landed([_rec("strengthen_tests", level="test-change")])
    assert m["value_landed_verified"] == move_value("strengthen_tests")
    assert m["moves_verified"] == 1


def test_unrecognized_level_is_treated_as_weak_never_promoted():
    # An unknown/missing coverage level must NEVER silently count as verified.
    m = value_landed([_rec("implement_stub", level="bogus-level")])
    assert m["value_landed_verified"] == 0.0
    assert m["value_landed_weak"] == 1.0 and m["moves_weak"] == 1


# --------------------------------------------------------------------------- #
# determinism: byte-identical out, stable top-contribution order               #
# --------------------------------------------------------------------------- #
def test_value_landed_is_byte_identical_across_runs():
    recs = [_rec("implement_stub", target="a.py"),
            _rec("dedup_extract", level="none", target="b.py"),
            _rec("modernize", level="none", target="c.py")]
    first = json.dumps(value_landed(recs), sort_keys=True)
    second = json.dumps(value_landed(recs), sort_keys=True)
    assert first == second


def test_top_contributions_order_stable_under_input_reordering():
    a = _rec("modernize", target="z.py", level="none")      # 0.25 weak
    b = _rec("implement_stub", target="a.py")               # 1.00 verified
    c = _rec("dedup_extract", target="m.py", level="none")  # 0.60 weak
    forward = value_landed([a, b, c])["top_contributions"]
    reverse = value_landed([c, b, a])["top_contributions"]
    assert forward == reverse
    # sorted by (-value, operator, target): implement_stub(1.0), dedup(0.6), mod(0.25)
    assert [c["operator"] for c in forward] == [
        "implement_stub", "dedup_extract", "modernize"]


def test_value_landed_value_tie_breaks_by_operator_then_target():
    # Two equal-value moves -> stable order by operator then target.
    x = _rec("dedup_total_return", target="b.py", level="none")  # 0.60
    y = _rec("dedup_extract", target="a.py", level="none")       # 0.60
    top = value_landed([x, y])["top_contributions"]
    assert [c["operator"] for c in top] == ["dedup_extract", "dedup_total_return"]


# --------------------------------------------------------------------------- #
# buyer-tier rollups + no-starvation of an unknown operator                    #
# --------------------------------------------------------------------------- #
def test_value_landed_buckets_by_buyer_tier():
    t1 = _rec("implement_stub")                  # 1.00 -> tier1
    t2 = _rec("dedup_extract")                   # 0.60 -> tier2
    t3 = _rec("modernize")                       # 0.25 -> tier3
    m = value_landed([t1, t2, t3])
    assert m["moves_by_tier"] == {"tier1": 1, "tier2": 1, "tier3": 1}
    assert m["by_tier"]["tier1"] == 1.0
    assert m["by_tier"]["tier2"] == move_value("dedup_extract")
    assert m["by_tier"]["tier3"] == move_value("modernize")


def test_unknown_operator_uses_default_value_and_never_crashes():
    m = value_landed([_rec("brand_new_operator_no_row")])
    # DEFAULT_VALUE (0.30) lands in tier2 (>= 0.32 is tier2; 0.30 is tier3 actually)
    assert m["value_landed_verified"] == DEFAULT_VALUE
    assert m["moves_verified"] == 1
    # 0.30 < 0.32 so it is tier3 by the documented cutoffs — never starved (>0).
    assert m["moves_by_tier"]["tier3"] == 1


def test_empty_operator_string_does_not_crash():
    rec = {"finding": {}, "outcome": "applied", "rollback": {"occurred": False},
           "verification": {"strength": {"level": "function"}}}
    m = value_landed([rec])
    assert m["moves_verified"] == 1  # empty operator -> DEFAULT, still counts


# --------------------------------------------------------------------------- #
# session adapter maps tiers onto the same buckets                             #
# --------------------------------------------------------------------------- #
def _session(*moves):
    obj = SessionObjective(objective="o", moves=list(moves))
    return SessionReport(applied=True, objectives=[obj])


def test_value_landed_from_session_maps_tiers():
    report = _session(
        SessionMove("o", "implement_stub", "a.py", "fill", "verified"),
        SessionMove("o", "dedup_extract", "b.py", "lift", "weak"),
        SessionMove("o", "modernize", "c.py", "tidy", "no-suite"),
    )
    m = value_landed_from_session(report)
    assert m["value_landed_verified"] == move_value("implement_stub")
    assert m["value_landed_weak"] == move_value("dedup_extract")
    assert m["value_landed_unverified"] == move_value("modernize")
    assert m["schema"] == VALUE_SCHEMA


def test_value_landed_from_session_empty_is_zeroed():
    m = value_landed_from_session(SessionReport(applied=True))
    assert m["value_landed_verified"] == 0.0
    assert m["verdict"] == "no value landed"


# --------------------------------------------------------------------------- #
# bundle: proof_hash byte-identical (value block is outside the seal)           #
# --------------------------------------------------------------------------- #
_SUMMARY = {
    "mode": "supervised", "verify": True, "applied": 1, "rolled_back": 0,
    "blocked": 0, "committed": 0, "total_executable": 1,
    "results": [
        {"branch": "1", "action": "implement", "operator": "implement_stub",
         "label": "stub", "target": "app/s.py", "applied": True,
         "transform_type": "tdd", "changed_files": ["app/s.py"],
         "diff": "--- a/app/s.py\n+++ b/app/s.py\n+return a+b\n",
         "rolled_back": False,
         "verification_strength": {"level": "function"}},
    ],
}


def test_value_bundle_keeps_proof_hash_byte_identical():
    proof = build_proof(_SUMMARY, "/tmp/p")
    pb = proof_bundle(proof)
    vb = value_bundle(proof)
    assert pb["proof_hash"] == vb["proof_hash"]
    assert pb["summary"] == vb["summary"]
    # The value block is ADDED alongside, never inside the seal.
    assert "value" in vb and "value" not in pb
    assert vb["value"]["value_landed_verified"] == 1.0


def test_value_bundle_hash_matches_records_proof_hash():
    proof = build_proof(_SUMMARY, "/tmp/p")
    assert value_bundle(proof)["proof_hash"] == proof_hash(proof)


def test_write_value_bundle_writes_sidecar_without_touching_proof(tmp_path):
    proof = build_proof(_SUMMARY, str(tmp_path))
    # a pre-existing proof-of-fix.json the value bundle must NOT touch
    apex = tmp_path / ".apex"
    apex.mkdir()
    pof = apex / "proof-of-fix.json"
    pof.write_text("SENTINEL", encoding="utf-8")
    out = write_value_bundle(proof, str(tmp_path))
    assert out == apex / "value-bundle.json"
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["value"]["value_landed_verified"] == 1.0
    # the proof-of-fix.json is byte-untouched.
    assert pof.read_text(encoding="utf-8") == "SENTINEL"


# --------------------------------------------------------------------------- #
# render: additive, present-only-when-present byte-identity                     #
# --------------------------------------------------------------------------- #
def test_render_value_section_present_only_when_applied_with_moves():
    move = SessionMove("o", "implement_stub", "app/s.py", "fill body", "verified")
    landed = SessionReport(applied=True, objectives=[
        SessionObjective(objective="o", moves=[move])],
        diff="--- a/app/s.py\n+++ b/app/s.py\n+x\n")
    md = render_session_markdown(landed)
    assert "## Value landed (what a buyer would pay for)" in md
    # the section sits ABOVE the diff (the buyer scores the diff below it).
    assert md.index("## Value landed") < md.index("## The verified diff")
    assert "`implement_stub` → app/s.py (1.00)" in md


def test_render_byte_identical_when_nothing_landed():
    # report-only (applied False) and applied-with-zero-moves both render WITHOUT
    # the value section — byte-identical to the pre-change output. We assert the
    # section is absent (the gate never fires), the present-only-when-present law.
    report_only = SessionReport(applied=False)
    applied_empty = SessionReport(applied=True, diff="--- a\n+++ b\n")
    assert "## Value landed" not in render_session_markdown(report_only)
    assert "## Value landed" not in render_session_markdown(applied_empty)


def test_render_value_section_is_deterministic():
    move = SessionMove("o", "dedup_extract", "app/d.py", "lift", "weak")
    rep = SessionReport(applied=True, objectives=[
        SessionObjective(objective="o", moves=[move])], diff="--- a\n+++ b\n")
    assert render_session_markdown(rep) == render_session_markdown(rep)


# --------------------------------------------------------------------------- #
# value-coverage tripwire                                                       #
# --------------------------------------------------------------------------- #
def test_value_coverage_tripwire_flags_untiered_objective():
    # An injected objective whose operator has NO OPERATOR_VALUE row is flagged.
    gaps = value_coverage_gaps(["this-objective-has-no-tier-row"])
    assert gaps == ["this-objective-has-no-tier-row"]


def test_value_coverage_tripwire_passes_for_tiered_objective():
    # A real objective whose operator carries a tier is NOT flagged.
    assert value_coverage_gaps(["modernize"]) == []
    assert value_coverage_gaps(["dead-params"]) == []  # via OBJECTIVE_OPERATOR


def test_value_coverage_tripwire_live_registry_is_clean():
    # Every registered objective already carries a tier (the move_value drift-test
    # guarantee) — belt-and-suspenders, the live registry must pass.
    assert value_coverage_gaps() == []


# --------------------------------------------------------------------------- #
# CLI: apex self-audit --value-landed exit codes + json                        #
# --------------------------------------------------------------------------- #
def _ns(target, **over):
    base = dict(target=str(target), format="markdown", north_star=False,
                soundness=False, determinism=False, commits=20,
                value_landed=True, min_verified_value=None)
    base.update(over)
    return argparse.Namespace(**base)


def _write_proof(tmp_path):
    apex = tmp_path / ".apex"
    apex.mkdir()
    proof = build_proof(_SUMMARY, str(tmp_path))
    (apex / "proof-of-fix.json").write_text(
        json.dumps(proof, indent=2), encoding="utf-8")


def test_self_audit_value_landed_reports_exit_zero(tmp_path, capsys):
    from app.cli_ops import cmd_self_audit

    _write_proof(tmp_path)
    rc = cmd_self_audit(_ns(tmp_path))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Apex Self-Audit — Value landed" in out
    assert "Verified value: 1.00" in out


def test_self_audit_value_landed_floor_blocks_below(tmp_path, capsys):
    from app.cli_ops import cmd_self_audit

    _write_proof(tmp_path)
    # verified value is 1.00; a 2.0 floor is not met -> exit non-zero.
    assert cmd_self_audit(_ns(tmp_path, min_verified_value=2.0)) == 1
    capsys.readouterr()
    # a 0.5 floor IS met -> exit 0.
    assert cmd_self_audit(_ns(tmp_path, min_verified_value=0.5)) == 0


def test_self_audit_value_landed_json_emits_metric(tmp_path, capsys):
    from app.cli_ops import cmd_self_audit

    _write_proof(tmp_path)
    rc = cmd_self_audit(_ns(tmp_path, format="json"))
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == VALUE_SCHEMA
    assert data["value_landed_verified"] == 1.0
    assert data["value_coverage_gaps"] == []


def test_self_audit_value_landed_handles_missing_proof(tmp_path, capsys, monkeypatch):
    # No .apex/proof-of-fix.json -> falls back to a report-only session (which on
    # an empty dir lands nothing). Stub run_develop_session to keep it fast.
    from app.cli_ops import cmd_self_audit
    import app.engine.develop_session as ds

    monkeypatch.setattr(ds, "run_develop_session",
                        lambda *a, **k: SessionReport(applied=False))
    rc = cmd_self_audit(_ns(tmp_path))
    assert rc == 0
    assert "no value landed" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# empty / nothing-held edge                                                     #
# --------------------------------------------------------------------------- #
def test_empty_records_yield_zeroed_metric_no_crash():
    m = value_landed([])
    assert m["value_landed_verified"] == 0.0
    assert m["value_landed_weak"] == 0.0
    assert m["value_landed_unverified"] == 0.0
    assert m["by_tier"] == {"tier1": 0.0, "tier2": 0.0, "tier3": 0.0}
    assert m["moves_by_tier"] == {"tier1": 0, "tier2": 0, "tier3": 0}
    assert m["top_contributions"] == []
    assert m["verdict"] == "no value landed"


def test_value_landed_accepts_full_artifact_or_bare_list():
    recs = [_rec("implement_stub")]
    artifact = {"schema": "apex-proof-of-fix", "fixes": recs}
    assert value_landed(artifact) == value_landed(recs)


def test_value_landed_none_and_empty_artifact_are_safe():
    assert value_landed(None)["verdict"] == "no value landed"
    assert value_landed({})["verdict"] == "no value landed"
    assert value_landed({"fixes": []})["verdict"] == "no value landed"
