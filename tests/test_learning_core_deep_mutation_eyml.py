"""Deep-mutation hardening for the LEARNING core — ``idea_memory`` and
``proof_of_fix``.

These characterization tests target mutation survivors found past the standard
30-mutant cap by enumerating the FULL site universe of each module and splicing
every site. They pin the exact behaviour that the existing suites left blind:

* the Wilson-score lower-bound math (every constant/operator in the formula),
* the bounded-nudge arithmetic for sequences,
* the ``confident_ranking`` limit/ordering edge logic and default arguments,
* the ``summary`` best/worst orientation per table,
* trait-key disjunction structure,
* and on the proof side: the proof schema/field correctness — fallback defaults
  for absent summary keys, the failing-test cap, duration rounding, the
  blocked-reason guard, JSON indent, and the nested-directory write.

Every assertion below corresponds to a concrete mutant the prior suite missed;
the docstrings name the killed mutation. All values are deterministic (no
time/random), stdlib + pytest only.
"""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

from app.engine.idea_memory import (
    _MAX_NUDGE,
    _MIN_SAMPLES,
    _WILSON_Z,
    IdeaMemory,
    _Stat,
    _trait_key,
)
from app.engine.proof_of_fix import build_proof, summarize_test_run, write_proof


def _summary(*results):
    return {"results": list(results)}


def _r(operator="", label="", target="", applied=False, rolled_back=False, blocked=False):
    return {"operator": operator, "label": label, "target": target,
            "applied": applied, "rolled_back": rolled_back, "blocked": blocked}


# =============================================================================
# idea_memory — Wilson confidence math (kills L41/L117/L118/L119 mutants)
# =============================================================================

def _wilson_reference(applied: int, total: int) -> float:
    """An INDEPENDENT re-derivation of the Wilson lower bound, written out so
    any single mutation of the formula in the source diverges from it."""
    if total == 0:
        return 0.0
    z = _WILSON_Z
    phat = applied / total
    denom = 1.0 + z * z / total
    center = phat + z * z / (2.0 * total)
    margin = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * total)) / total)
    return (center - margin) / denom


def test_confidence_matches_wilson_formula_exactly():
    # Pins every operator/constant in ``_Stat.confidence`` against an
    # independent computation: flips of 1.0/2.0/4.0, +/-, */ or z (1.96) all
    # diverge from this reference for at least one of these mixes.
    for applied, rb in ((9, 1), (2, 0), (2, 8), (5, 5), (7, 3), (1, 0)):
        stat = _Stat(applied=applied, rolled_back=rb)
        assert stat.confidence == _wilson_reference(applied, applied + rb)


def test_confidence_z_constant_is_1_96():
    # The 1.96 -> 2.96 mutant changes the bound; pin a known value to 8 places.
    assert round(_Stat(applied=9, rolled_back=1).confidence, 8) == 0.59584361
    assert round(_Stat(applied=2, rolled_back=0).confidence, 8) == 0.34237195


def test_confidence_denominator_shrinks_bound_below_rate():
    # denom = 1 + z*z/n  (so denom > 1): a */ or +/- flip there would let the
    # bound meet or exceed the raw rate. The lower bound must stay strictly
    # below a perfect rate.
    stat = _Stat(applied=4, rolled_back=0)
    assert stat.success_rate == 1.0
    assert stat.confidence < 1.0


# =============================================================================
# idea_memory — bounded sequence-nudge math (kills L280 */ and 4-constant)
# =============================================================================

def test_sequence_factor_exact_bounded_value():
    # 3-of-3 sequence credit -> success_rate 1.0 -> +_MAX_NUDGE exactly.
    m = IdeaMemory()
    for _ in range(3):
        m.record_outcomes(_summary(_r(operator="test", applied=True),
                                   _r(operator="harden", applied=True)))
    expected = round(1.0 + (1.0 - 0.5) * 2.0 * _MAX_NUDGE, 4)
    assert m.sequence_factor("test", "harden") == expected
    assert m.sequence_factor("test", "harden") == round(1.0 + _MAX_NUDGE, 4)


def test_sequence_factor_all_rollbacks_is_lower_bound():
    # 0% success -> -_MAX_NUDGE; a */ flip on the *2.0 term would shift this
    # away from the exact lower bound.
    m = IdeaMemory()
    m.by_sequence["a>b"] = _Stat(applied=0, rolled_back=2)
    assert m.sequence_factor("a", "b") == round(1.0 - _MAX_NUDGE, 4)


def test_sequence_factor_rounds_to_four_places():
    # L280 ``round(..., 4)``: a 2-of-3 sequence gives 1.033333... which must be
    # reported to exactly four places (a 4->5 precision mutant keeps a 5th).
    m = IdeaMemory()
    m.by_sequence["a>b"] = _Stat(applied=2, rolled_back=1)
    assert m.sequence_factor("a", "b") == 1.0333


def test_sequence_factor_empty_operands_short_circuit():
    # L275 ``not prev_operator or not operator``: an EMPTY prev or operator
    # must return neutral 1.0 even when a matching cell exists (an ``and``
    # mutant would fall through and apply the cell's nudge instead).
    m = IdeaMemory()
    m.by_sequence[">harden"] = _Stat(applied=2)
    m.by_sequence["test>"] = _Stat(applied=2)
    assert m.sequence_factor("", "harden") == 1.0
    assert m.sequence_factor("test", "") == 1.0


# =============================================================================
# idea_memory — feasibility root guard (kills L257 or->and)
# =============================================================================

def test_root_operator_ignores_characteristic_cell():
    # L257 ``not operator or operator == 'root'``: a root lens must contribute
    # NO characteristic nudge. An ``and`` mutant would consult ``root@hub`` and
    # tilt the factor; the real code keeps it neutral.
    m = IdeaMemory()
    m.by_characteristic["root@hub"] = _Stat(applied=2)
    assert m.feasibility_factor("root", characteristic="hub") == 1.0
    assert m.feasibility_factor("root", label="dependency-hub") == 1.0


# =============================================================================
# idea_memory — trait-key disjunction structure (kills L83 or->and)
# =============================================================================

def test_trait_key_bare_testfile_name_without_slash():
    # L83 chain ``... or 'test_' in last-segment``: a bare ``test_z.py`` (no
    # slash, not under tests/) matches ONLY the final disjunct. Each or->and
    # mutant in the chain would drop it to "".
    assert _trait_key("", "test_z.py") == "testfile"


def test_trait_key_each_disjunct_independently_yields_testfile():
    # One target per disjunct, each matching only its own clause structure.
    assert _trait_key("", "a/tests/b.py") == "testfile"      # '/tests/' in tgt
    assert _trait_key("", "tests/foo.py") == "testfile"       # startswith tests/
    assert _trait_key("", "a/test_x/y.py") == "testfile"      # '/test_' in tgt
    assert _trait_key("", "deep_test_z.py") == "testfile"     # last-seg test_


# =============================================================================
# idea_memory — confident_ranking limit / default / ordering edges
# =============================================================================

def _ranking_memory(n: int) -> IdeaMemory:
    m = IdeaMemory()
    for i in range(n):
        m.by_operator[f"op{i}"] = _Stat(applied=2 + i)
    return m


def test_confident_ranking_default_limit_caps_at_five():
    # L292 default ``limit=5``: with 7 eligible keys the default must return 5.
    assert len(_ranking_memory(7).confident_ranking("operator")) == 5


def test_confident_ranking_explicit_limit_caps():
    # L311 ``seen[:limit]`` else-branch and the ``limit < 0`` comparison:
    # a positive in-range limit caps, distinguishing the ``>=``/``is not``
    # mutants that would otherwise return the full list.
    assert len(_ranking_memory(7).confident_ranking("operator", limit=3)) == 3


def test_confident_ranking_zero_limit_is_empty():
    # L311 ``limit < 0`` boundary and the ``0`` constant: limit 0 yields
    # ``seen[:0]`` == []. A ``<=`` (boundary) or ``< 1`` (0->1) mutant would
    # treat 0 as "unbounded" and return everything.
    assert _ranking_memory(7).confident_ranking("operator", limit=0) == []


def test_confident_ranking_negative_limit_is_unbounded():
    # L311 ``limit < 0`` true branch returns the whole list.
    assert len(_ranking_memory(7).confident_ranking("operator", limit=-1)) == 7


def test_confident_ranking_none_limit_is_unbounded():
    # L311 ``limit is None or limit < 0``: None must short-circuit BEFORE the
    # ``limit < 0`` numeric compare. An ``and`` mutant would evaluate
    # ``None < 0`` and raise TypeError; an ``is not`` mutant would mis-handle it.
    assert len(_ranking_memory(7).confident_ranking("operator", limit=None)) == 7


def test_confident_ranking_default_best_orientation():
    # L291 default ``best=True``: best-first ordering with no explicit arg.
    m = IdeaMemory()
    m.by_operator["good"] = _Stat(applied=10)
    m.by_operator["bad"] = _Stat(applied=0, rolled_back=10)
    assert m.confident_ranking("operator")[0]["key"] == "good"


def test_confident_ranking_rounds_to_four_and_three_places():
    # L312 ``round(confidence, 4)`` and L313 ``round(success_rate, 3)``:
    # pin both precisions against over-precise values. A 2-of-3 success_rate
    # is 0.6666... -> 0.667 at three places (a 3->4 mutant keeps a 4th).
    m = IdeaMemory()
    m.by_operator["op"] = _Stat(applied=9, rolled_back=1)
    row = m.confident_ranking("operator")[0]
    assert row["confidence"] == round(_Stat(applied=9, rolled_back=1).confidence, 4)
    assert row["confidence"] == 0.5958
    m.by_operator["frac"] = _Stat(applied=2, rolled_back=1)
    frac = next(r for r in m.confident_ranking("operator") if r["key"] == "frac")
    assert frac["success_rate"] == 0.667


# =============================================================================
# idea_memory — summary best/worst orientation per table (L321/331/332/335/336)
# =============================================================================

def test_summary_orientation_per_table():
    m = IdeaMemory()
    m.by_operator["ogood"] = _Stat(applied=10)
    m.by_operator["obad"] = _Stat(applied=0, rolled_back=10)
    m.by_sequence["a>good"] = _Stat(applied=10)
    m.by_sequence["a>bad"] = _Stat(applied=0, rolled_back=10)
    m.by_characteristic["op@good"] = _Stat(applied=10)
    m.by_characteristic["op@bad"] = _Stat(applied=0, rolled_back=10)
    s = m.summary()
    # reliable_* and most_confident use best=True; least_confident best=False.
    assert s["reliable_sequences"][0]["key"] == "a>good"          # L331
    assert s["reliable_characteristics"][0]["key"] == "op@good"   # L332
    assert s["most_confident"][0]["key"] == "ogood"               # L335
    assert s["least_confident"][0]["key"] == "obad"               # L336


def test_summary_top_rounds_success_rate_to_three_places():
    # L321 ``round(success_rate, 3)`` in summary._top.
    m = IdeaMemory()
    m.by_operator["op"] = _Stat(applied=2, rolled_back=1)  # 0.666...
    assert m.summary()["most_reliable"][0]["success_rate"] == 0.667


# =============================================================================
# idea_memory — persistence field correctness (L163 parents, L164 indent)
# =============================================================================

def test_save_creates_nested_parent_directory(tmp_path):
    # L163 ``mkdir(parents=True)``: the default path is ``.apex/...``, so the
    # parent must be created even when it doesn't exist (a ``parents=False``
    # mutant raises FileNotFoundError).
    m = IdeaMemory()
    m.by_operator["op"] = _Stat(applied=2)
    out = tmp_path / "a" / "b" / "mem.json"
    saved = m.save(str(tmp_path), path=str(out))
    assert saved == out and out.exists()


def test_save_uses_indent_two(tmp_path):
    # L164 ``json.dumps(..., indent=2)``: pin the two-space indentation.
    m = IdeaMemory()
    m.by_operator["op"] = _Stat(applied=2)
    out = tmp_path / "mem.json"
    m.save(str(tmp_path), path=str(out))
    text = out.read_text(encoding="utf-8")
    assert '\n  "by_operator"' in text


def test_learn_from_returns_memory(tmp_path):
    # L289 ``return mem``: learn_from must hand back the IdeaMemory it built
    # (a ``return None`` mutant breaks every caller that uses the result).
    mem = IdeaMemory.learn_from(
        _summary(_r(operator="test", applied=True)), str(tmp_path))
    assert isinstance(mem, IdeaMemory)
    assert mem.by_operator["test"].applied == 1


def test_min_samples_constant_gate_is_two():
    # Cross-checks the _MIN_SAMPLES gate exercised throughout: a single sample
    # is below the gate (neutral), two reach it.
    m = IdeaMemory()
    m.by_sequence["a>b"] = _Stat(applied=1)
    assert _MIN_SAMPLES == 2
    assert m.sequence_factor("a", "b") == 1.0
    m.by_sequence["a>b"] = _Stat(applied=2)
    assert m.sequence_factor("a", "b") != 1.0


# =============================================================================
# proof_of_fix — summarize_test_run fallback defaults & caps
# =============================================================================

def _trs(results, **kw):
    base = {"commands": [["pytest"]], "ok": True, "results": results}
    base.update(kw)
    return SimpleNamespace(**base)


def test_summarize_reads_counts_from_stderr():
    # L56 ``res.get('stderr') or ''``: counts living in STDERR must still be
    # parsed. An ``and`` mutant drops stderr text entirely.
    ev = summarize_test_run(_trs(
        [{"stdout": "", "stderr": "3 passed in 1s", "duration_seconds": 1.0}]))
    assert ev["tests_passed"] == 3


def test_summarize_missing_duration_defaults_to_zero():
    # L69 ``res.get('duration_seconds') or 0.0``: a row with NO duration key
    # contributes 0.0 (a 0.0->1.0 mutant would invent a second of runtime).
    ev = summarize_test_run(_trs([{"stdout": "1 passed", "stderr": ""}]))
    assert ev["duration_seconds"] == 0.0


def test_summarize_missing_ok_defaults_to_false():
    # L73 ``getattr(summary, 'ok', False)``: a summary lacking ``ok`` is not OK.
    ev = summarize_test_run(SimpleNamespace(commands=[["p"]], results=[]))
    assert ev["ok"] is False


def test_summarize_caps_failing_tests_at_five():
    # L80 ``failures[:5]``: at most five failing-test names are kept.
    txt = "\n".join(f"FAILED tests/t.py::test_{i}" for i in range(7))
    ev = summarize_test_run(_trs(
        [{"stdout": txt, "stderr": "", "duration_seconds": 0}], ok=False))
    assert len(ev["failing_tests"]) == 5
    assert ev["failing_tests"][0] == "tests/t.py::test_0"


def test_summarize_rounds_duration_to_three_places():
    # L81 ``round(duration, 3)``: the duration is reported to 3 decimals.
    ev = summarize_test_run(_trs(
        [{"stdout": "", "stderr": "", "duration_seconds": 1.23456}]))
    assert ev["duration_seconds"] == 1.235


# =============================================================================
# proof_of_fix — build_proof totals defaults & blocked-reason guard
# =============================================================================

def test_build_proof_totals_default_to_zero_when_absent():
    # L146-L150 ``summary.get('...', 0)``: a summary with no totals keys yields
    # all-zero totals (each 0->1 mutant would seed phantom counts).
    proof = build_proof({"results": []}, "/tmp/p")
    assert proof["totals"] == {"executable": 0, "applied": 0, "rolled_back": 0,
                               "blocked": 0, "committed": 0}


def test_blocked_reason_only_on_blocked_outcome():
    # L129 ``outcome == 'blocked' and r.get('reason')``: an APPLIED row that
    # also carries a reason must NOT get a ``blocked_reason`` field. An ``or``
    # mutant would attach it to non-blocked records.
    proof = build_proof(
        _summary(_r(operator="harden", target="app/x.py", applied=True)
                 | {"reason": "noise"}), "/tmp/p")
    assert "blocked_reason" not in proof["fixes"][0]
    # ...but a genuinely blocked row with a reason keeps it.
    blocked = build_proof(
        {"results": [{"target": "app/y.py", "reason": "gated"}]}, "/tmp/p")
    assert blocked["fixes"][0]["blocked_reason"] == "gated"


# =============================================================================
# proof_of_fix — write_proof field correctness (L159 parents, L160 indent)
# =============================================================================

def test_write_proof_creates_nested_directories(tmp_path):
    # L159 ``mkdir(parents=True)``: a deep out path must materialise its parents.
    out = tmp_path / "deep" / "nested" / "proof.json"
    written = write_proof({"schema": "x"}, str(tmp_path), out=str(out))
    assert written == out and out.exists()


def test_write_proof_uses_indent_two(tmp_path):
    # L160 ``json.dumps(proof, indent=2)``: two-space indentation, and the file
    # ends with a trailing newline.
    out = tmp_path / "proof.json"
    write_proof({"a": {"b": 1}}, str(tmp_path), out=str(out))
    text = out.read_text(encoding="utf-8")
    assert '\n  "a"' in text
    assert text.endswith("}\n")
    assert json.loads(text) == {"a": {"b": 1}}
