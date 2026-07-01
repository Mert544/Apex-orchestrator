"""Buyer-value spine (``app/engine/move_value.py``) + value-aware move selection.

The shared ``move_value`` table is the one place "what a buyer values" is
defined, so the idea tree and the move loop can never disagree. These tests pin:

  * the drift guard — EVERY operator any move generator emits (built-in or
    self-registered) carries a tier, so a new operator can't slip in untiered;
  * the buyer thesis numerically (Tier 1 > Tier 2 > Tier 3) and the
    unknown-operator default;
  * the reliability multiplier (neutral without memory, bounded + clamped with);
  * value-greedy ordering and the opt-in refusal floor inside ``compile_objective``,
    INCLUDING the off-by-default byte-identity of the existing step list;
  * the recorded ``CompileStep.value`` (serialized only when set; mean in the
    markdown headline) and the determinism of the value-led order;
  * ``compile_objective`` WIRING the proof-of-fix VALUE-REALIZATION factor
    (``value_reliability.operator_realization_factors``) into its
    ``scored_move_value`` calls end-to-end: an operator that over-promised on
    THIS project is demoted in both the recorded step ``value`` and the
    value-aware ordering, ONLY on the opt-in value-aware path (a fresh/default
    campaign never reads ``.apex/proof-of-fix.json`` and stays byte-identical).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from app.engine.idea_memory import IdeaMemory
from app.engine.move_value import (
    DEFAULT_VALUE,
    OPERATOR_VALUE,
    move_value,
    objective_value,
    scored_move_value,
)
from app.engine.objective_compiler import (
    compile_objective,
    render_compile_markdown,
)
from app.engine.proof_of_fix import SCHEMA as PROOF_SCHEMA


# --- the authoritative operator inventory (mirrors how move_value derives it) -

def _emitted_operators() -> set[str]:
    """Every ``operator="..."`` string literal a move generator constructs —
    the built-in generators in ``objective_compiler`` plus every self-registering
    spec under ``app/execution/objectives/`` — plus the modernize family's
    sub-transform operators (set inside ``_tidy_transforms`` as plain locals)."""
    root = Path(__file__).resolve().parents[1]
    files = [root / "app" / "engine" / "objective_compiler.py"]
    files += sorted((root / "app" / "execution" / "objectives").glob("*.py"))
    ops: set[str] = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.keyword) and node.arg == "operator"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                ops.add(node.value.value)
    ops.update({"modernize", "fix_fstring", "fix_collection"})
    return ops


# --- 1. drift guard ----------------------------------------------------------

def test_move_value_table_covers_every_operator():
    # Every operator a move generator can emit must carry a tier, so a newly
    # registered objective without a value is caught here (the append-only guard).
    missing = sorted(op for op in _emitted_operators() if op not in OPERATOR_VALUE)
    assert missing == [], f"operators with no buyer-value tier: {missing}"


def test_move_value_table_has_no_phantom_rows():
    # The table is exactly the emitted set — no stale row for an operator no
    # generator produces (keeps the frozen contract honest in both directions).
    phantom = sorted(op for op in OPERATOR_VALUE if op not in _emitted_operators())
    assert phantom == [], f"table rows for non-emitted operators: {phantom}"


def test_every_value_in_unit_range():
    assert all(0.0 <= v <= 1.0 for v in OPERATOR_VALUE.values())


# --- 2. the buyer thesis -----------------------------------------------------

def test_move_value_tiers_ordered():
    # The North Star thesis, numerically: land real code > restructure > tidy.
    assert move_value("implement_stub") > move_value("dedup_extract")
    assert move_value("dedup_extract") > move_value("sort_imports")
    # The two Tier-1 body-landers top the table.
    assert move_value("implement_stub") == 1.00
    assert move_value("tdd_implement") == 1.00


def test_objective_value_bridges_name_to_operator():
    # Layer (a) routes by objective NAME; the value must agree with the operator.
    assert objective_value("implement-stub") == move_value("implement_stub")
    assert objective_value("cover-gaps") == move_value("cover_gaps")
    assert objective_value("dead-params") == move_value("drop_param")  # built-in remap
    assert objective_value("sort-imports") == move_value("sort_imports")


# --- 3. unknown operator default ---------------------------------------------

def test_unknown_operator_gets_default():
    assert move_value("totally_new") == 0.30
    assert move_value("totally_new") == DEFAULT_VALUE
    assert objective_value("totally-new-objective") == DEFAULT_VALUE


# --- 4. reliability multiplier: neutral without memory -----------------------

def test_scored_value_neutral_without_memory():
    # A fresh project (no memory) sees exactly the static table.
    for op in ("implement_stub", "drop_param", "sort_imports", "unknown_op"):
        assert scored_move_value(op, None) == move_value(op)


# --- 5. reliability multiplier: bounded + clamped ----------------------------

def _summary(*results):
    return {"results": list(results)}


def _r(operator="", applied=False, rolled_back=False):
    return {"operator": operator, "label": "", "target": "",
            "applied": applied, "rolled_back": rolled_back, "blocked": False}


def test_scored_value_reliability_nudges_down_and_clamps():
    # A poor track record (mostly rollbacks) nudges the value DOWN, bounded to
    # ±10% of the static prior; a perfect record on a Tier-1 op stays clamped ≤1.
    mem = IdeaMemory()
    mem.record_outcomes(_summary(
        _r(operator="drop_param", rolled_back=True),
        _r(operator="drop_param", rolled_back=True),
        _r(operator="drop_param", applied=True),
    ))
    base = move_value("drop_param")
    scored = scored_move_value("drop_param", mem)
    assert scored < base                      # a worse-than-even record drags it down
    assert scored >= round(base * 0.9, 4) - 1e-9   # but only within the ±10% bound

    # A Tier-1 op with an all-success record would exceed 1.0 without the clamp.
    good = IdeaMemory()
    good.record_outcomes(_summary(
        _r(operator="implement_stub", applied=True),
        _r(operator="implement_stub", applied=True),
    ))
    assert scored_move_value("implement_stub", good) == 1.0


# --- 6. value-greedy ordering ------------------------------------------------

def _modernize_and_sortimports_project(tmp_path: Path) -> Path:
    """A module carrying BOTH a modernize opportunity (``== None``) and an
    unsorted import block — the modernize objective emits one move per tidy
    transform, so the (higher-value) modernize move and the (lower-value)
    sort-imports move are candidates that the value order must rank."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "import os\n"
        "import collections\n"
        "import abc\n"
        "\n"
        "def f(x):\n"
        "    if x == None:\n"
        "        return collections.OrderedDict()\n"
        "    return abc.ABC or os.getpid()\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_i():\n    assert app.m is not None\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_ordering_prefers_high_value(tmp_path):
    # On a project where a single module offers BOTH a Tier-3 modernize move and a
    # Tier-3 sort move, the value-aware order banks modernize (0.25) before the
    # lower-valued sort (0.18) within a capped budget. (A floor that refuses
    # nothing — well below sort's value — just engages the value ordering.)
    _modernize_and_sortimports_project(tmp_path)
    # modernize is the objective; its moves include the import-sort-adjacent tidy
    # only through its own transforms, so prove the order on the values directly:
    assert move_value("modernize") > move_value("sort_imports")
    r = compile_objective(str(tmp_path), objective="modernize", apply=False,
                          min_move_value=0.05)
    # The dry run lists value-ordered candidates; the modernize move leads.
    assert r.steps, "expected at least one modernize candidate"
    assert r.steps[0].operator in {"modernize", "fix_collection", "fix_fstring"}


# --- 7. refusal floor refuses low-value --------------------------------------

def _modernize_only_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(
        "def f(x):\n    return x == None\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_i():\n    assert app.m is not None\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_min_move_value_floor_refuses_low(tmp_path):
    # modernize (0.25) is below a 0.5 floor → 0 moves land, a "low buyer value"
    # blocker is recorded, and the source is untouched.
    _modernize_only_project(tmp_path)
    before = (tmp_path / "app" / "m.py").read_text()
    r = compile_objective(str(tmp_path), objective="modernize", apply=True,
                          verify=False, min_move_value=0.5)
    assert r.steps == []
    assert any("low buyer value" in b for b in r.blocked)
    assert (tmp_path / "app" / "m.py").read_text() == before  # nothing rewritten


# --- 8. default floor is byte-identical --------------------------------------

# render/fetch are non-public (only ``use`` is exported) so the public-API rail
# in ``_dead_param_moves`` permits dropping their dead params — an external
# keyword caller cannot reach them, so the in-project suite gate is sound proof.
_THREE_DEAD = (
    "__all__ = ['use']\n\n\n"
    "def render(text, color=None, width=80):\n"
    "    return text[:width]\n\n\n"
    "def fetch(url, retries=3):\n"
    "    return url\n\n\n"
    "def use():\n"
    "    return render('hi', width=10) + fetch('u', retries=1)\n"
)


def _dead_params_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "m.py").write_text(_THREE_DEAD, encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_i():\n    assert app.m is not None\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_default_floor_is_byte_identical(tmp_path):
    # min_move_value=0.0 (the default) reproduces the EXACT step list + to_dict of
    # the historical fixpoint campaign — no reorder, no recorded value, no key.
    _dead_params_project(tmp_path)
    r = compile_objective(str(tmp_path), apply=True, verify=False)
    assert [s.fitness_after for s in r.steps] == [1.0, 0.0]
    assert all(s.value == 0.0 for s in r.steps)
    # The serialized step shape is unchanged: no "value" key when 0.0.
    assert all("value" not in s.to_dict() for s in r.steps)
    assert r.to_dict()["steps"][0] == {
        "operator": "drop_param",
        "target": "app/m.py:render(color)",
        "description": "drop never-read parameter `color` from render() in app/m.py",
        "fitness_before": 2.0, "fitness_after": 1.0,
        "verified": False, "coverage": "",
    }


# --- 9. step value recorded + serialized + headlined -------------------------

def test_step_value_recorded_and_serialized(tmp_path):
    # With value-awareness engaged (a floor below drop_param's 0.40), a landed
    # step carries the non-zero value, to_dict surfaces it, and the markdown
    # headline reports the mean.
    _dead_params_project(tmp_path)
    r = compile_objective(str(tmp_path), apply=True, verify=False,
                          min_move_value=0.1)
    assert len(r.steps) == 2
    assert all(s.value == move_value("drop_param") for s in r.steps)
    assert r.to_dict()["steps"][0]["value"] == move_value("drop_param")
    md = render_compile_markdown(r)
    assert "mean buyer-value 0.40" in md


# --- 10. value-led order is deterministic ------------------------------------

def test_value_selection_deterministic(tmp_path):
    # Two identical value-aware runs over the same tree yield the identical step
    # order (the m.target tiebreak gives a total order).
    _dead_params_project(tmp_path)
    a = compile_objective(str(tmp_path), apply=False, min_move_value=0.1)

    other = tmp_path / "two"
    other.mkdir()
    _dead_params_project(other)
    b = compile_objective(str(other), apply=False, min_move_value=0.1)

    assert [s.target for s in a.steps] == [s.target for s in b.steps]
    # Both drops are drop_param (equal value, neutral sequence), so the stable
    # m.target tiebreak decides: "fetch(retries)" sorts before "render(color)".
    assert [s.target for s in a.steps] == [
        "app/m.py:fetch(retries)", "app/m.py:render(color)"]


# --- 11. value-REALIZATION wired end-to-end into compile_objective ------------
#
# ``value_reliability.operator_realization_factors`` was built + tested but had
# ZERO production call site: ``scored_move_value``'s ``realization=`` kwarg was
# designed but never filled. These pin the wiring at both scored_move_value call
# sites compile_objective drives (the value-aware ORDER, and the recorded step
# VALUE), the demote-only direction, and the opt-in byte-identity.

def _proof_rec(operator: str, level: str = "none") -> dict:
    """One HELD-but-weak fix record in ``proof_of_fix._fix_record``'s shape —
    ``applied`` + not rolled back (so ``value_landed._held`` counts it) with a
    green-but-uncovered ('none') coverage level, so it credits the predicted
    denominator but NOT the verified numerator (an over-promiser)."""
    return {
        "finding": {"operator": operator, "target": "app/m.py"},
        "outcome": "applied",
        "verification": {"strength": {"level": level}},
        "rollback": {"occurred": False},
    }


def _write_proof(root: Path, fixes: list[dict]) -> None:
    """Persist one apex-proof-of-fix artifact under ``<root>/.apex/`` — the SAME
    store ``operator_realization_factors`` reads, mirrored from
    ``test_value_reliability_eyml``'s helper."""
    apex = root / ".apex"
    apex.mkdir(parents=True, exist_ok=True)
    (apex / "proof-0001.json").write_text(
        json.dumps({"schema": PROOF_SCHEMA, "generated_at": "2026-01-01T00:00:00Z",
                    "fixes": fixes}),
        encoding="utf-8")


def test_realization_demotes_recorded_step_value(tmp_path):
    # drop_param HELD 8 weak (uncovered) landings on THIS project -> it never
    # realized the verified value it promised, so operator_realization_factors
    # demotes it below 1.0 and the recorded CompileStep.value must reflect that
    # correction, not the bare static prior.
    _dead_params_project(tmp_path)
    _write_proof(tmp_path, [_proof_rec("drop_param") for _ in range(8)])
    r = compile_objective(str(tmp_path), apply=True, verify=False,
                          min_move_value=0.1)
    assert len(r.steps) == 2
    prior = move_value("drop_param")
    assert all(0.0 < s.value < prior for s in r.steps), \
        "an over-promising operator's recorded value must be demoted, never zero"


def test_realization_never_inflates_a_reliable_operator(tmp_path):
    # drop_param HELD 8 FUNCTION-verified (fully realized) landings -> the factor
    # is bounded at <= 1.0 (neutral, never a boost), so the recorded value never
    # exceeds the static prior.
    _dead_params_project(tmp_path)
    _write_proof(tmp_path, [_proof_rec("drop_param", level="function")
                            for _ in range(8)])
    r = compile_objective(str(tmp_path), apply=True, verify=False,
                          min_move_value=0.1)
    prior = move_value("drop_param")
    assert all(s.value <= prior + 1e-9 for s in r.steps)


def test_realization_reorders_toward_the_proven_operator(tmp_path):
    # On a project offering BOTH a modernize move and a sort-imports move (equal
    # static tiers would otherwise decide only by the static prior), a proof
    # history where modernize chronically over-promises drags its scored value
    # below sort_imports's — proving realization corrects the ORDER, not just
    # the disclosed value. (modernize's static prior is well above
    # sort_imports's floor, so only a real demotion could flip them.)
    _modernize_and_sortimports_project(tmp_path)
    assert move_value("modernize") > move_value("sort_imports")
    _write_proof(tmp_path, [_proof_rec("modernize") for _ in range(10)])
    from app.engine.value_reliability import operator_realization_factors

    factors = operator_realization_factors(str(tmp_path))
    demoted = scored_move_value("modernize", None, realization=factors)
    assert demoted < move_value("sort_imports"), \
        "a chronic over-promiser's realized value must fall below a lesser tier"


def test_realization_off_by_default_is_byte_identical(tmp_path):
    # min_move_value=0.0 (the default) never engages value_aware, so
    # compile_objective must not even READ the proof history: a demoting proof
    # file present on disk has ZERO effect on the default campaign's steps.
    _dead_params_project(tmp_path)
    _write_proof(tmp_path, [_proof_rec("drop_param") for _ in range(8)])
    r = compile_objective(str(tmp_path), apply=True, verify=False)
    assert [s.fitness_after for s in r.steps] == [1.0, 0.0]
    assert all(s.value == 0.0 for s in r.steps)


def test_realization_no_proof_history_is_byte_identical_to_static(tmp_path):
    # A fresh project (no .apex/proof-of-fix.json at all) sees the EXACT static
    # values recorded — the neutral-1.0-default byte-identity this wiring must
    # preserve for every project that hasn't accumulated proof history yet.
    _dead_params_project(tmp_path)
    r = compile_objective(str(tmp_path), apply=True, verify=False,
                          min_move_value=0.1)
    assert all(s.value == move_value("drop_param") for s in r.steps)
