"""Deep-mutation hardening for four LEARNING/DISCOVERY research modules.

These characterization tests kill mutation survivors that slip past the 30-mutant
cap in the per-module ``*_eyml`` suites. They pin the high-value blind spots a
mutation run surfaced: the reliability/confidence MATH (exact rounding precision,
clamp-of-negative, default-tally fan-out) and the FIXED THRESHOLDS that decide a
verdict (the self-assessment fragile/calibration bands, the counterfactual
avoid-rate floor, the hypothesis confirm/weak confidence cutoffs and the
minimum-antecedent/evidence caps).

Each test below was derived by splicing a single operator/constant in the source
(via ``mutation_tester._collect_sites``/``_splice``), running the covering tests
against the mutant, and recording the SURVIVORS — then writing an assertion the
original passes but every recorded mutant fails. Equivalent mutants (those that
cannot change observable behaviour, e.g. a boundary flip on an unreachable edge or
an order-map shift that preserves relative rank) are documented in the module-level
notes and intentionally NOT pinned.

Covers: knowledge_corpus, self_assessment, counterfactual_learning,
hypothesis_validation. Deterministic; stdlib + pytest only.
"""

from __future__ import annotations

from app.engine.counterfactual_learning import (
    _AVOID_FAILURE_RATE,
    failure_signatures,
    module_traits,
    near_miss_insights,
)
from app.engine.hypothesis_validation import (
    CONFIRM_CONFIDENCE,
    MAX_EVIDENCE,
    WEAK_CONFIDENCE,
    _rank_key,
    _verdict as _hyp_verdict,
    discovery_to_hypothesis,
    validate_discoveries,
    validate_hypothesis,
)
from app.engine.knowledge_corpus import (
    SCHEMA,
    consult,
    merge_run,
    new_corpus,
    record_outcome,
    save_corpus,
)
from app.engine.self_assessment import (
    _calibration_verdict,
    assess_weaknesses,
    confidence_calibration,
    self_curriculum,
)
from app.tools.project_profile import ProjectProfile

# =========================================================================
# knowledge_corpus
# -------------------------------------------------------------------------
# Survivors killed here: the clamp-of-negative floor (a negative stored count
# must read back as 0, not 1 or None), the per-outcome ``.get(outcome, 0)``
# defaults that fan a missing-outcome row into the right zero counts, the
# ``and`` guard that tolerates a non-int count instead of crashing on it, and
# the byte-identical JSON indent.
#
# Documented EQUIVALENT survivors (not pinned): the ``value < 0`` boundary and
# ``< 0``->``< 1`` number flips in ``_clamp_count`` (differ only at value 0,
# where the clamp output is 0 either way); the ``> _MAX_COUNT`` boundary (the
# upper clamp is _MAX_COUNT at the edge either way); the ``added > 0`` boundary
# flip (only differs at added==0, which contributes 0 regardless); the
# ``.get(o, 0)`` defaults inside ``_reliability``/``record_outcome``/``_add_counts``
# target whose tallies always carry every key (default never used); and the
# ``exist_ok=True``->``False`` flip (``mkdir(parents=True)`` does not raise on an
# already-present parent here).
# =========================================================================


def _raw_corpus(signature: str, tally: dict) -> dict:
    """A corpus with a hand-built (non-normalised) tally — exercises the
    tolerant ``.get`` paths in ``consult`` that normalisation would otherwise
    hide."""
    return {"schema": SCHEMA, "version": "1.0", "signatures": {signature: tally}}


def test_consult_clamps_negative_stored_count_to_zero():
    # A hand-edited corpus with a NEGATIVE count must read back as 0 — this kills
    # the `_clamp_count` `return 0`->`return 1` and `return None` survivors.
    corpus = _raw_corpus("s|", {"applied": -5, "rolled_back": 2, "blocked": 0})
    result = consult(corpus, "s|")
    assert result["applied"] == 0
    assert result["rolled_back"] == 2


def test_consult_defaults_missing_outcomes_to_zero_not_one():
    # A partial tally (only `applied` present) must default the other outcomes to
    # 0 — kills the `tally.get(o, 0)`->`tally.get(o, 1)` survivor in `consult`.
    corpus = _raw_corpus("sig|", {"applied": 1})
    result = consult(corpus, "sig|")
    assert result["rolled_back"] == 0
    assert result["blocked"] == 0
    assert result["samples"] == 1


def test_merge_run_defaults_absent_summary_outcomes_to_zero():
    # A by_action group missing rolled_back/blocked must fold them as 0 — kills
    # the `counts.get(outcome, 0)`->`...1` survivor in `_add_counts`.
    summary = {"by_action": {"sigA": {"applied": 2}}}
    corpus = merge_run(new_corpus(), summary)
    assert corpus["signatures"]["sigA"] == {"applied": 2, "rolled_back": 0, "blocked": 0}


def test_merge_run_tolerates_non_int_count_without_raising():
    # A non-int count must be ignored (folded as 0), never crash — kills the
    # `isinstance(added, int) and added > 0`->`... or ...` survivor, which would
    # evaluate `added > 0` on a string and raise TypeError.
    summary = {"by_action": {"sigA": {"applied": "oops"}}}
    corpus = merge_run(new_corpus(), summary)
    assert corpus["signatures"]["sigA"] == {"applied": 0, "rolled_back": 0, "blocked": 0}


def test_record_outcome_then_consult_counts_exactly_one():
    # A single recorded outcome reads back as exactly one applied — anchors the
    # fold so a count perturbation surfaces.
    corpus = record_outcome(new_corpus(), "s|", "applied")
    result = consult(corpus, "s|")
    assert result["applied"] == 1
    assert result["samples"] == 1


def test_save_corpus_uses_indent_two_byte_identical(tmp_path):
    # The persisted JSON is byte-identical with a 2-space indent — kills the
    # `indent=2`->`indent=3` survivor.
    corpus = record_outcome(new_corpus(), "s|", "applied")
    path = save_corpus(corpus, tmp_path / "kc.json")
    text = path.read_text(encoding="utf-8")
    # 2-space indent: the first nested key sits at exactly two leading spaces.
    assert '\n  "schema":' in text
    assert '\n   "schema":' not in text


# =========================================================================
# self_assessment
# -------------------------------------------------------------------------
# Survivors killed here: the fragile threshold (`reliability >= _FRAGILE_AT`
# at EXACTLY 0.5), the block-dominance verdict math (`blocked * 2 >= lost`),
# the default `top=3` curriculum size, the `claimed` rounding precision, and the
# calibration band edges (`gap > 0.1` / `gap < -0.1` at exactly +/-0.1).
#
# Documented EQUIVALENT survivors (not pinned): the `lost > 0`->`>= 0` and
# `lost > 0`->`lost > 1` flips (a verdict with `lost <= 1` always has
# reliability >= 0.5 and returns "reliable" before that line — unreachable); the
# `top <= 0`->`top < 0` flip (`top == 0` slices to `[:0]` -> [] either way); the
# `.get("total", 0)` / `.get("reliability", 0.0)` defaults (summarise always
# supplies those keys); and the `round(gap, 4)`->`round(gap, 5)` flip (gap is a
# difference of two 4-decimal values, so it already has <= 4 decimals).
# =========================================================================


def _fix(action: str, outcome: str, *, performed: bool = True) -> dict:
    return {
        "finding": {"action": action},
        "outcome": outcome,
        "verification": {"performed": performed},
    }


def _history(*fixes: dict) -> list[dict]:
    return [{"schema": "x", "fixes": list(fixes)}]


def test_verdict_reliable_at_exactly_fragile_threshold():
    # reliability exactly 0.5 (1 applied, 1 rolled_back) is "reliable" — kills the
    # `reliability >= _FRAGILE_AT`->`reliability > _FRAGILE_AT` boundary flip.
    history = _history(_fix("a", "applied"), _fix("a", "rolled_back"))
    item = assess_weaknesses(history)[0]
    assert item["reliability"] == 0.5
    assert item["verdict"] == "reliable"


def test_verdict_blocked_when_blocks_dominate_at_boundary():
    # 1 rolled_back + 1 blocked: blocked*2 == lost (2 == 2) -> blocks dominate ->
    # "blocked — ...". Kills both `blocked * 2 >= lost`->`> lost` (boundary) and
    # `blocked * 2`->`blocked * 3` (number) survivors.
    history = _history(_fix("a", "rolled_back"), _fix("a", "blocked"))
    item = assess_weaknesses(history)[0]
    assert item["reliability"] == 0.0
    assert item["verdict"].startswith("blocked")


def test_verdict_fragile_when_rollbacks_dominate():
    # 2 rolled_back + 1 blocked: blocked*2 (2) < lost (3) -> rollbacks dominate ->
    # "fragile". Distinguishes the `* 2`->`* 3` mutant (which would read blocked
    # dominant) from the original.
    history = _history(
        _fix("a", "rolled_back"), _fix("a", "rolled_back"), _fix("a", "blocked")
    )
    item = assess_weaknesses(history)[0]
    assert item["verdict"].startswith("fragile")


def test_curriculum_default_top_is_three():
    # With four-plus weaknesses, the default curriculum lists exactly three —
    # kills the `top: int = 3`->`top: int = 4` default survivor.
    fixes: list[dict] = []
    for action in ("a", "b", "c", "d", "e"):
        fixes += [
            _fix(action, "applied"),
            _fix(action, "rolled_back"),
            _fix(action, "rolled_back"),
        ]
    assert len(self_curriculum(_history(*fixes))) == 3


def test_calibration_claimed_rounds_to_four_places():
    # claimed = 2/3 rounds to 0.6667 (4 places) — kills the `round(..., 4)`->
    # `round(..., 5)` survivor on the claimed rate.
    history = _history(
        _fix("a", "applied", performed=True),
        _fix("a", "applied", performed=False),
        _fix("a", "rolled_back", performed=True),
    )
    assert confidence_calibration(history)["claimed"] == 0.6667


def test_calibration_verdict_well_calibrated_at_upper_band_edge():
    # gap exactly +0.1 is still "well calibrated" — kills the `gap > 0.1`->
    # `gap >= 0.1` boundary flip.
    assert _calibration_verdict(0.1) == "well calibrated"


def test_calibration_verdict_well_calibrated_at_lower_band_edge():
    # gap exactly -0.1 is still "well calibrated" — kills the `gap < -0.1`->
    # `gap <= -0.1` boundary flip.
    assert _calibration_verdict(-0.1) == "well calibrated"


def test_calibration_band_edges_reachable_through_public_api():
    # End-to-end: a history with claimed 0.6 / actual 0.5 lands gap == +0.1 and
    # must read "well calibrated" (the +0.1 boundary kill, reachable publicly).
    over = _history(
        *([_fix("a", "applied", performed=True)] * 5),
        _fix("a", "rolled_back", performed=True),
        *([_fix("a", "rolled_back", performed=False)] * 4),
    )
    result = confidence_calibration(over)
    assert result["gap"] == 0.1
    assert result["verdict"] == "well calibrated"


# =========================================================================
# counterfactual_learning
# -------------------------------------------------------------------------
# Survivors killed here: the `_module_of` fallback chain (use changed_files when
# there is no target, use the FIRST changed file, return the module string not
# None), the `module_traits` flag logic (the `or`-chain for the test trait, the
# `>= 3` deep-path boundary), the failure classification `or` (an unknown outcome
# is a failure), the failure-rate rounding precision, the avoid-rate floor
# (`rate >= _AVOID_FAILURE_RATE` at EXACTLY 0.6), and the `_MAX_INSIGHTS` cap.
#
# Documented EQUIVALENT survivors (not pinned): `return ""`->`return None` in
# `_module_of` (both empty/None map to the `generic` trait); `rsplit("/", 1)`->
# `rsplit("/", 2)` (the `[-1]` basename is identical); `else 0.0`->`else 1.0`
# in the rate (the else-branch needs attempts==0, but a signature only exists
# once attempts>=1); and the `item[0]`->`item[1]` sort tiebreak (the signatures
# are already emitted in sorted-key order, so the tiebreak never reorders).
# =========================================================================


def _cf_fix(action: str, outcome: str, *, target: str = "", changed=None) -> dict:
    fix: dict = {"finding": {"action": action, "target": target}, "outcome": outcome}
    if changed is not None:
        fix["changed_files"] = changed
    return fix


def _cf_history(*fixes: dict) -> list[dict]:
    return [{"schema": "x", "fixes": list(fixes)}]


def test_module_of_uses_first_changed_file_when_no_target():
    # No finding target -> the FIRST changed file decides the module (and thus its
    # traits). Kills the `changed_files or []`->`... and []` survivor (which would
    # blank the module) and the `changed[0]`->`changed[1]` / `return ...`->
    # `return None` survivors (the test trait would vanish).
    history = _cf_history(
        _cf_fix("a", "rolled_back", changed=["tests/test_z.py", "app/x.py"]),
        _cf_fix("a", "rolled_back", changed=["tests/test_z.py", "app/x.py"]),
        _cf_fix("a", "rolled_back", changed=["tests/test_z.py", "app/x.py"]),
    )
    sigs = failure_signatures(history)
    assert "a | test" in sigs
    assert sigs["a | test"]["failures"] == 3


def test_traits_test_flag_requires_only_one_marker():
    # `/tests/` mid-path marks a test file even without a `test_` basename —
    # kills the `or`-chain `and` survivor in `module_traits` (which would demand
    # ALL markers).
    assert "test" in module_traits("app/tests/y.py")
    assert "test" in module_traits("test_x.py")


def test_traits_deep_at_exactly_three_slashes():
    # Exactly three '/' is "deep" — kills both the `>= 3`->`> 3` boundary flip and
    # the `>= 3`->`>= 4` number flip.
    assert "deep" in module_traits("a/b/c/d.py")
    assert "deep" not in module_traits("a/b/c.py")


def test_unknown_outcome_counts_as_failure():
    # An out-of-vocabulary outcome is a non-landing -> counts as a failure. Kills
    # the `in _FAILURE_OUTCOMES or outcome != _LANDING_OUTCOME`->`... and ...`
    # survivor (which would treat the unknown outcome as a non-failure).
    history = _cf_history(
        _cf_fix("a", "weird", target="app/m.py"),
        _cf_fix("a", "weird", target="app/m.py"),
        _cf_fix("a", "weird", target="app/m.py"),
    )
    sigs = failure_signatures(history)
    assert sigs["a | generic"]["failures"] == 3
    assert sigs["a | generic"]["failure_rate"] == 1.0


def test_failure_rate_rounds_to_four_places():
    # 1 failure of 3 -> 0.3333 (4 places). Kills the `round(..., 4)`->
    # `round(..., 5)` survivor on the failure rate.
    history = _cf_history(
        _cf_fix("a", "rolled_back", target="app/m.py"),
        _cf_fix("a", "applied", target="app/m.py"),
        _cf_fix("a", "applied", target="app/m.py"),
    )
    assert failure_signatures(history)["a | generic"]["failure_rate"] == 0.3333


def test_avoid_at_exactly_the_failure_rate_floor():
    # 3 failures of 5 -> rate exactly 0.6 == _AVOID_FAILURE_RATE, with attempts
    # >= _MIN_ATTEMPTS -> avoid. Kills the `rate >= _AVOID_FAILURE_RATE`->
    # `rate > _AVOID_FAILURE_RATE` boundary flip.
    history = _cf_history(
        *([_cf_fix("a", "rolled_back", target="app/m.py")] * 3),
        *([_cf_fix("a", "applied", target="app/m.py")] * 2),
    )
    entry = failure_signatures(history)["a | generic"]
    assert entry["failure_rate"] == _AVOID_FAILURE_RATE
    assert entry["avoid"] is True


def test_near_miss_insights_capped_at_eight():
    # Ten avoid-worthy signatures yield at most eight insight lines — kills the
    # `_MAX_INSIGHTS = 8`->`9` survivor.
    fixes: list[dict] = []
    for i in range(10):
        action = f"act{i:02d}"
        fixes += [_cf_fix(action, "rolled_back", target="app/m.py")] * 3
    assert len(near_miss_insights(_cf_history(*fixes))) == 8


# =========================================================================
# hypothesis_validation
# -------------------------------------------------------------------------
# Survivors killed here: the key-splitting `maxsplit=1` on ':' and '>' (a key
# with extra delimiters must NOT raise), the clique any-member antecedent
# (`t in tags`), the verdict thresholds (MIN_ANTECEDENT at exactly 2, WEAK and
# CONFIRM confidence at their exact edges), the `antecedent_any` default (a
# triple without the flag uses ALL-mode), the confidence rounding precision,
# MAX_EVIDENCE, the default `top=5`, and the verdict rank-order map.
#
# Documented EQUIVALENT survivors (not pinned): the `order.get(verdict, 3)`->
# `... 4)` default (any value above the known ranks 0/1/2 sorts unknowns last
# identically); and the `top <= 0`->`top < 0` flip (`top == 0` slices to
# `[:0]` -> [] either way).
# =========================================================================


def test_split_key_tolerates_extra_colon_without_raising():
    # A key carrying a second ':' must split only once (consequent keeps the
    # tail) and never raise — kills the `split(":", 1)`->`split(":", 2)` survivor
    # (which unpacks 3 parts into 2 and raises ValueError).
    hyp = discovery_to_hypothesis({"key": "assoc:s>d:extra"})
    assert hyp is not None
    assert hyp["consequent"] == ["d:extra"]


def test_assoc_body_tolerates_extra_gt_without_raising():
    # `src>dst>tail` splits once -> consequent `dst>tail`; kills the assoc
    # `split(">", 1)`->`split(">", 2)` survivor.
    hyp = discovery_to_hypothesis({"key": "assoc:a>b>c"})
    assert hyp is not None
    assert hyp["consequent"] == ["b>c"]


def test_triple_body_tolerates_extra_gt_without_raising():
    # `a&b>c>d` splits once -> consequent `c>d`; kills the triple
    # `split(">", 1)`->`split(">", 2)` survivor.
    hyp = discovery_to_hypothesis({"key": "triple:a&b>c>d"})
    assert hyp is not None
    assert hyp["antecedent"] == ["a", "b"]
    assert hyp["consequent"] == ["c>d"]


def test_clique_full_bundle_module_is_a_supporter():
    # A module carrying ALL clique tags satisfies the any-member antecedent AND the
    # consequent -> it is a SUPPORTER. Kills the `t in tags`->`t not in tags`
    # survivor in `_antecedent_holds`: under the mutation a full-bundle module has
    # no missing tag, so `any(t not in tags)` is False and it stops counting as a
    # supporter (support drops from 1 to 0).
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["full.py", "part.py"],
        untested_modules=["full.py"],
        fragile_modules=["full.py"],
    )
    hyp = {
        "kind": "clique",
        "antecedent": ["security", "untested", "fragile"],
        "consequent": ["security", "untested", "fragile"],
        "antecedent_any": True,
        "key": "clique:fragile&security&untested",
    }
    result = validate_hypothesis(hyp, profile)
    assert result["support"] == 1            # full.py supports the bundle
    assert result["antecedent_modules"] == 2  # full.py and part.py both qualify
    assert result["evidence"] == ["part.py"]


def test_verdict_confirmed_at_exactly_min_antecedent():
    # A law holding at confidence 1.0 on exactly MIN_ANTECEDENT (2) modules is
    # "confirmed" — kills the `antecedent_n < MIN_ANTECEDENT`->`<=` boundary flip
    # and the `MIN_ANTECEDENT = 2`->`3` number flip.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a.py", "b.py"],
        untested_modules=["a.py", "b.py"],
    )
    hyp = discovery_to_hypothesis({"key": "assoc:security>untested"})
    result = validate_hypothesis(hyp, profile)
    assert result["antecedent_modules"] == 2
    assert result["confidence"] == 1.0
    assert result["verdict"] == "confirmed"


def test_verdict_weak_at_exactly_weak_confidence_floor():
    # confidence exactly WEAK_CONFIDENCE (0.6) with enough antecedents is "weak",
    # not "refuted" — kills the `confidence < WEAK_CONFIDENCE`->`<=` boundary flip.
    assert _hyp_verdict(WEAK_CONFIDENCE, 5) == "weak"


def test_verdict_confirmed_at_exactly_confirm_confidence():
    # confidence exactly CONFIRM_CONFIDENCE (0.9) is "confirmed", not "weak" —
    # kills the `confidence >= CONFIRM_CONFIDENCE`->`>` boundary flip.
    assert _hyp_verdict(CONFIRM_CONFIDENCE, 5) == "confirmed"


def test_triple_without_any_flag_uses_all_mode_antecedent():
    # A triple hypothesis (no `antecedent_any`) requires ALL antecedent tags. Kills
    # the `hypothesis.get("antecedent_any", False)`->`..., True)` default flip,
    # which would switch the antecedent to ANY-mode and change which modules match.
    profile = ProjectProfile(
        root=".",
        security_finding_modules=["a.py"],
        fragile_modules=["a.py", "b.py"],
        untested_modules=["a.py"],
    )
    hyp = discovery_to_hypothesis({"key": "triple:fragile&security>untested"})
    result = validate_hypothesis(hyp, profile)
    # ALL-mode: only `a.py` carries both fragile AND security -> 1 antecedent.
    assert result["antecedent_modules"] == 1
    assert result["counter_examples"] == 0
    assert result["evidence"] == []


def test_confidence_rounds_to_three_places():
    # 2 of 3 antecedent modules support -> confidence 0.667 (3 places). Kills the
    # `round(confidence, 3)`->`round(confidence, 4)` survivor.
    profile = ProjectProfile(
        root=".",
        dependency_hubs=["a.py", "b.py", "c.py"],
        untested_modules=["a.py", "b.py"],
    )
    hyp = {
        "kind": "association",
        "antecedent": ["hub"],
        "consequent": ["untested"],
        "key": "assoc:hub>untested",
    }
    assert validate_hypothesis(hyp, profile)["confidence"] == 0.667


def test_evidence_capped_at_max_evidence():
    # Seven counter-examples are listed at most MAX_EVIDENCE (5) — kills the
    # `MAX_EVIDENCE = 5`->`6` number flip and the `counter[:MAX_EVIDENCE]` slice.
    mods = [f"app/m{i}.py" for i in range(7)]
    profile = ProjectProfile(
        root=".",
        dependency_hubs=list(mods),
        security_finding_modules=list(mods),
        untested_modules=[],
    )
    hyp = {
        "kind": "association",
        "antecedent": ["hub"],
        "consequent": ["untested"],
        "key": "assoc:hub>untested",
    }
    result = validate_hypothesis(hyp, profile)
    assert result["counter_examples"] == 7
    # Assert the literal 5 (not the imported MAX_EVIDENCE, which the mutant would
    # also shift) so the `MAX_EVIDENCE = 5`->`6` survivor is genuinely killed.
    assert MAX_EVIDENCE == 5
    assert len(result["evidence"]) == 5


def test_validate_discoveries_default_top_is_five():
    # A profile yielding seven discoveries returns exactly five by default — kills
    # the `top: int = 5`->`top: int = 6` default survivor.
    mods = [f"app/m{i}.py" for i in range(8)]
    profile = ProjectProfile(
        root=".",
        dependency_hubs=mods[:6],
        untested_modules=mods[:6],
        security_finding_modules=mods[:6],
        fragile_modules=mods[:6],
        debt_marker_modules=mods[:6],
    )
    assert len(validate_discoveries(profile, top=99)) >= 6
    assert len(validate_discoveries(profile)) == 5


def _rk_result(verdict: str, confidence: float, support: int, key: str) -> dict:
    return {"verdict": verdict, "confidence": confidence, "support": support, "key": key}


def test_rank_order_confirmed_before_weak():
    # confirmed ranks strictly before weak even when the weak result's key sorts
    # first — kills the order-map `"confirmed": 0`->`1` survivor (which collapses
    # confirmed into weak's rank, letting the key tiebreak reorder them).
    confirmed = _rk_result("confirmed", 0.9, 3, "zzz")
    weak = _rk_result("weak", 0.9, 3, "aaa")
    ranked = sorted([weak, confirmed], key=_rank_key)
    assert [r["verdict"] for r in ranked] == ["confirmed", "weak"]


def test_rank_order_weak_before_refuted():
    # weak ranks strictly before refuted regardless of key — kills the order-map
    # `"weak": 1`->`2` survivor.
    weak = _rk_result("weak", 0.5, 1, "zzz")
    refuted = _rk_result("refuted", 0.5, 1, "aaa")
    ranked = sorted([refuted, weak], key=_rank_key)
    assert [r["verdict"] for r in ranked] == ["weak", "refuted"]


def test_rank_order_refuted_before_unknown_verdict():
    # a known refuted ranks before an unrecognised verdict regardless of key —
    # kills the order-map `"refuted": 2`->`3` survivor (which collapses refuted
    # into the unknown default rank).
    refuted = _rk_result("refuted", 0.5, 1, "zzz")
    unknown = _rk_result("weird", 0.5, 1, "aaa")
    ranked = sorted([unknown, refuted], key=_rank_key)
    assert [r["verdict"] for r in ranked] == ["refuted", "weird"]
