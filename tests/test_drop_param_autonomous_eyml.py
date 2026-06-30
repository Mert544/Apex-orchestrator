"""Autonomous-39: the ``dead-parameter`` seeder fact is now an EXECUTABLE
``drop_param`` landing, not a human ``design_task`` handoff.

A never-read parameter used to be devolved to a person — the work order carried
the exact ``apex signature drop`` command for a human to run under supervision.
The transform hands ALREADY existed (``plan_param_drop`` via ``apply_rename`` —
dry-run / suite-verify / auto-rollback); it was a handoff ONLY because it was a
supervised CLI muscle. So the fact is flipped to the delegated ``drop_param``
action: the bridge re-runs the dead-parameter detector for the named module and
lands the drop (def header rebuilt WITHOUT the param + every in-project KEYWORD
call site pruned) through ``apply_rename(impact_scope=True)`` with auto-rollback.

THE AUTONOMY SOUNDNESS RAIL — PUBLIC-API REFUSAL: the supervised CLI relied on a
HUMAN to judge external impact. Autonomy removes the human, so an external
(out-of-project) caller could pass the provably-dead parameter BY KEYWORD
(``lib.func(x, dead=1)``) — a call the in-project scan can't see and the
suite-gate can't exercise (positional + ``**kwargs`` are already blocked by
param_drop, so external-keyword is the residual hole). The lander therefore
REFUSES to drop a parameter from a PUBLIC-API function (an ``__all__``-listed
name, or — with no ``__all__`` — a top-level non-underscore name), reusing the
same ``is_public_name`` predicate add-final / freeze-dataclass use; it drops ONLY
from a provably NON-public function, where all callers are necessarily in-project.

SCOPE: top-level functions ONLY (``plan_param_drop`` resolves via
``resolve_sole_definition``; the dead-param scan keys on a name UNIQUE
project-wide), so no method-override / Protocol / ABC LSP hazard arises.

These tests lock:
  * T1 — a private top-level fn with a provably-dead keyword-called param LANDS
    the drop + rewrites the in-project caller, suite GREEN (driving the
    BRIDGE → lander path, not just ``plan_param_drop``);
  * T2 — the PUBLIC-API rail: a fn in ``__all__`` with a dead param is REFUSED,
    proven NON-TAUTOLOGICAL (``plan_param_drop`` alone WOULD land it);
  * T3 — the existing param_drop refusals still hold through the autonomous path
    (positional / ``**kwargs`` / body-read / comment-in-signature / multiply-defined);
  * T4 — auto-rollback: a drop that breaks an impacted test restores the tree
    byte-identical (never-fake-green);
  * T5 — the bridge reports dead-parameter EXECUTABLE with the honest description
    (the old ``apex signature drop`` handoff text is gone);
  * the parity wiring (tier, delegated registry, action strategy, move-value,
    soundness / north-star manifests, facet reachability) + the unchanged counts.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

from app.engine.idea_action_bridge import IdeaActionBridge, _FACT_ACTIONS
from app.execution.freeze_dataclass import is_public_name
from app.execution.param_drop import plan_param_drop
from app.models.idea import IdeaNode


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def _dp_idea(subject: str = "pkg/m.py", func: str = "_calc",
             param: str = "unused_flag") -> IdeaNode:
    """A ``dead-parameter`` root, exactly as the seeder emits it: a MODULE-only
    subject and the fact label on ``source_facts[0]`` carrying the function/param
    (the seeder writes ``"<module>:<line> <fn>(<param>) never read — `apex
    signature drop <fn> <param>`"``)."""
    return IdeaNode(
        id="d", title=f"Drop the dead parameter `{param}` from {func}() in {subject}",
        subject=subject, operator="root", branch_path="x.d",
        source_facts=[f"dead-parameter: {subject}:1 {func}({param}) never read — "
                      f"`apex signature drop {func} {param}`"],
    )


def _project(root: Path, module_src: str, *, caller_src: str | None = None,
             test_src: str | None = None) -> None:
    """A minimal importable project: ``pkg/m.py`` carries ``module_src``; optional
    in-project caller and test."""
    (root / "pkg").mkdir(exist_ok=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "m.py").write_text(module_src, encoding="utf-8")
    if caller_src is not None:
        (root / "pkg" / "caller.py").write_text(caller_src, encoding="utf-8")
    if test_src is not None:
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "test_m.py").write_text(test_src, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='p'\nversion='0'\n", encoding="utf-8")


_PRIVATE_SRC = "def _calc(x, unused_flag):\n    return x * 2\n"
_PRIVATE_CALLER = ("from pkg.m import _calc\n\n"
                   "def use():\n    return _calc(3, unused_flag=True)\n")
_PRIVATE_TEST = ("from pkg.caller import use\n\n"
                 "def test_use():\n    assert use() == 6\n")

# A PUBLIC-surface function in ``__all__`` with a dead param.
_PUBLIC_SRC = '__all__ = ["api"]\n\n\ndef api(x, dead):\n    return x * 2\n'
_PUBLIC_CALLER = ("from pkg.m import api\n\n"
                  "def use():\n    return api(3, dead=True)\n")
_PUBLIC_TEST = ("from pkg.caller import use\n\n"
                "def test_use():\n    assert use() == 6\n")


# ── 1. the flip itself: the fact row is now executable ────────────────────────

def test_fact_action_is_executable_drop_param():
    action_type, _desc, executable = _FACT_ACTIONS["dead-parameter"]
    assert action_type == "drop_param"
    assert executable is True


def test_plan_idea_surfaces_executable_drop_param():
    step = IdeaActionBridge().plan_idea(_dp_idea())
    assert step.action_type == "drop_param"
    assert step.executable is True
    # The subject is the module rel; the surfaced target is that module (not "").
    assert step.target == "pkg/m.py"


# ── 2. registry / delegation wiring ───────────────────────────────────────────

def test_drop_param_is_registered_delegated():
    assert "drop_param" in IdeaActionBridge._DELEGATED_SYNTHESIS
    assert "drop_param" in IdeaActionBridge._DELEGATED_ACTIONS
    lander_name, reason = IdeaActionBridge._DELEGATED_SYNTHESIS["drop_param"]
    assert lander_name == "_plan_drop_param_lander"
    assert reason  # a non-empty disclosed default reason


def test_drop_param_in_action_strategy():
    assert "drop_param" in IdeaActionBridge._ACTION_STRATEGY


# ── T1: a private fn with a dead keyword-called param LANDS, suite GREEN ───────

def test_t1_private_fn_lands_drop_and_rewrites_caller_suite_green(tmp_path: Path):
    _project(tmp_path, _PRIVATE_SRC, caller_src=_PRIVATE_CALLER,
             test_src=_PRIVATE_TEST)
    step = IdeaActionBridge().plan_idea(_dp_idea())
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised",
                                        verify=True)
    assert res["applied"] is True, res
    assert res["transform_type"] == "drop_param"
    assert res.get("suite_green") is True
    assert set(res["changed_files"]) == {"pkg/m.py", "pkg/caller.py"}

    # The def lost the parameter and the in-project keyword caller lost the arg.
    assert "def _calc(x):" in (tmp_path / "pkg" / "m.py").read_text()
    assert "_calc(3)" in (tmp_path / "pkg" / "caller.py").read_text()


def test_t1_lander_returns_the_concrete_drop_plan(tmp_path: Path):
    # The lander itself produces the project-wide drop plan (def + caller).
    _project(tmp_path, _PRIVATE_SRC, caller_src=_PRIVATE_CALLER)
    plan = IdeaActionBridge._plan_drop_param_lander()(str(tmp_path), "pkg/m.py")
    assert plan.new_contents
    assert "def _calc(x):" in plan.new_contents["pkg/m.py"]
    assert "_calc(3)" in plan.new_contents["pkg/caller.py"]


# ── T2: the PUBLIC-API rail — refuse, and prove it is NOT a tautology ─────────

def test_t2_public_api_fn_is_refused(tmp_path: Path):
    _project(tmp_path, _PUBLIC_SRC, caller_src=_PUBLIC_CALLER,
             test_src=_PUBLIC_TEST)
    step = IdeaActionBridge().plan_idea(_dp_idea(func="api", param="dead"))
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised",
                                        verify=True)
    assert res["applied"] is False, res
    assert res["transform_type"] == "drop_param"
    assert res.get("reason")
    assert "public API" in res["reason"]
    # NOTHING was written — the public signature is byte-identical.
    assert (tmp_path / "pkg" / "m.py").read_text() == _PUBLIC_SRC


def test_t2_lander_refuses_public_api_with_disclosed_reason(tmp_path: Path):
    _project(tmp_path, _PUBLIC_SRC, caller_src=_PUBLIC_CALLER)
    plan = IdeaActionBridge._plan_drop_param_lander()(str(tmp_path), "pkg/m.py")
    assert not plan.new_contents
    assert any("public API" in b for b in plan.blockers)


def test_t2_rail_is_not_a_tautology(tmp_path: Path):
    # NON-TAUTOLOGY PROOF: the rail is what blocks T2 — ``plan_param_drop`` ALONE
    # (no rail) WOULD land the drop on the same public function. Remove the rail
    # and T2 lands; that is exactly the unsupervised hole the rail closes.
    _project(tmp_path, _PUBLIC_SRC, caller_src=_PUBLIC_CALLER)
    assert is_public_name("api", _PUBLIC_SRC)  # the fn is on the public surface
    raw = plan_param_drop(str(tmp_path), "api", "dead")
    assert raw.new_contents, "param_drop alone must land — the rail is non-tautological"
    assert "def api(x):" in raw.new_contents["pkg/m.py"]


def test_t2_module_without_all_top_level_public_name_refused(tmp_path: Path):
    # No ``__all__`` ⇒ a top-level NON-underscore name is still public-by-default
    # (REFUSE-on-ambiguity), so it is refused exactly like an ``__all__`` member.
    src = "def render(text, unused):\n    return text\n"
    _project(tmp_path, src,
             caller_src="from pkg.m import render\n"
                        "def u():\n    return render('a', unused=1)\n")
    plan = IdeaActionBridge._plan_drop_param_lander()(str(tmp_path), "pkg/m.py")
    assert not plan.new_contents
    assert any("public API" in b for b in plan.blockers)


def test_t2_underscore_private_fn_is_dropped_even_without_all(tmp_path: Path):
    # The mirror of the above: an underscore-prefixed name is NEVER public (the
    # in-project scan is authoritative), so the drop LANDS — the rail is precise,
    # not a blanket refusal.
    _project(tmp_path, _PRIVATE_SRC, caller_src=_PRIVATE_CALLER)
    plan = IdeaActionBridge._plan_drop_param_lander()(str(tmp_path), "pkg/m.py")
    assert plan.new_contents
    assert "def _calc(x):" in plan.new_contents["pkg/m.py"]


# ── T3: the existing param_drop refusals still hold through the autonomous path ─

def _lander_noop(tmp_path: Path) -> list[str]:
    """Run the lander on ``pkg/m.py`` and assert it wrote nothing; return blockers."""
    plan = IdeaActionBridge._plan_drop_param_lander()(str(tmp_path), "pkg/m.py")
    assert not plan.new_contents
    return plan.blockers


def test_t3_positional_call_site_refused(tmp_path: Path):
    _project(tmp_path, _PRIVATE_SRC,
             caller_src="from pkg.m import _calc\n"
                        "def u():\n    return _calc(3, 9)\n")  # positional pass
    blockers = _lander_noop(tmp_path)
    assert any("POSITIONALLY" in b for b in blockers)


def test_t3_kwargs_splat_call_site_refused(tmp_path: Path):
    _project(tmp_path, _PRIVATE_SRC,
             caller_src="from pkg.m import _calc\n"
                        "def u(opts):\n    return _calc(3, **opts)\n")
    blockers = _lander_noop(tmp_path)
    assert any("**" in b and "refused" in b for b in blockers)


def test_t3_param_read_in_body_is_not_dead_noop(tmp_path: Path):
    # A param the body READS is not dead, so the detector never surfaces it: an
    # honest no-op (the detector, not a blocker, is what excludes it).
    _project(tmp_path, "def _calc(x, used):\n    return x + used\n")
    blockers = _lander_noop(tmp_path)
    assert blockers  # a disclosed "no droppable dead parameter" reason


def test_t3_comment_inside_signature_refused(tmp_path: Path):
    # A comment INSIDE the signature span (param_drop preserves comments, so it
    # refuses the one edit that couldn't).
    _project(tmp_path,
             "def _calc(x,\n          unused,  # never used\n"
             "          y=1):\n    return x + y\n")
    blockers = _lander_noop(tmp_path)
    assert any("comment" in b for b in blockers)


def test_t3_multiply_defined_name_refused(tmp_path: Path):
    # A name defined by 2+ modules is an interface family — never dropped.
    _project(tmp_path, _PRIVATE_SRC)
    (tmp_path / "pkg" / "n.py").write_text(
        "def _calc(y, unused_flag):\n    return y\n", encoding="utf-8")
    blockers = _lander_noop(tmp_path)
    assert blockers  # the detector excludes non-unique names ⇒ disclosed no-op


# ── T4: auto-rollback — never fake green ──────────────────────────────────────

def test_t4_planted_regression_rolls_back_byte_identical(tmp_path: Path):
    # An impacted test that pins the PRE-drop signature regresses after the drop;
    # the impact-scoped gate must ROLL BACK, leaving every file byte-identical.
    pin_test = ("import inspect\nfrom pkg.m import _calc\n\n"
                "def test_sig_pins_unused_flag():\n"
                "    assert 'unused_flag' in inspect.signature(_calc).parameters\n")
    _project(tmp_path, _PRIVATE_SRC, caller_src=_PRIVATE_CALLER, test_src=pin_test)
    before_m = (tmp_path / "pkg" / "m.py").read_text()
    before_c = (tmp_path / "pkg" / "caller.py").read_text()

    step = IdeaActionBridge().plan_idea(_dp_idea())
    res = IdeaActionBridge().apply_step(step, str(tmp_path), mode="supervised",
                                        verify=True)
    assert res["applied"] is False, res
    assert res.get("rolled_back") is True
    # Byte-identical restoration — the regression never landed.
    assert (tmp_path / "pkg" / "m.py").read_text() == before_m
    assert (tmp_path / "pkg" / "caller.py").read_text() == before_c


# ── T5: the bridge now reports dead-parameter EXECUTABLE (handoff text gone) ───

def test_t5_description_is_honest_and_handoff_text_gone():
    _action, desc, _executable = _FACT_ACTIONS["dead-parameter"]
    # States EXACTLY what lands and names the public-API refusal …
    assert "provably-unused parameter" in desc
    assert "in-project call sites" in desc
    assert "public-API" in desc
    # … and the OLD supervised-handoff command text is GONE (no over-claim, no
    # "run this command yourself").
    assert "apex signature drop" not in desc
    assert "apex signature keywordify" not in desc


def test_t5_plan_idea_description_carries_the_subject(tmp_path: Path):
    step = IdeaActionBridge().plan_idea(_dp_idea())
    assert "pkg/m.py" in step.description
    assert "apex signature drop" not in step.description


# ── 6. the SCOPE / determinism notes ──────────────────────────────────────────

def test_lander_missing_target_is_empty_noop_plan(tmp_path: Path):
    _project(tmp_path, _PRIVATE_SRC)
    plan = IdeaActionBridge._plan_drop_param_lander()(
        str(tmp_path), "pkg/absent.py")
    assert not plan.new_contents
    assert plan.blockers  # an honest "cannot read" reason, never a raise


def test_lander_strips_symbol_suffix_to_module_rel(tmp_path: Path):
    # A plain module target and a defensively-suffixed one resolve identically.
    _project(tmp_path, _PRIVATE_SRC, caller_src=_PRIVATE_CALLER)
    lander = IdeaActionBridge._plan_drop_param_lander()
    via_plain = lander(str(tmp_path), "pkg/m.py")
    via_suffix = lander(str(tmp_path), "pkg/m.py::_calc")
    assert via_plain.new_contents == via_suffix.new_contents
    assert via_plain.new_contents


def test_lander_is_deterministic(tmp_path: Path):
    _project(tmp_path, _PRIVATE_SRC, caller_src=_PRIVATE_CALLER)
    lander = IdeaActionBridge._plan_drop_param_lander()
    first = lander(str(tmp_path), "pkg/m.py").new_contents
    second = lander(str(tmp_path), "pkg/m.py").new_contents
    assert first == second and first


# ── 7. parity registries (verify each — these have drift tripwires) ───────────

def test_tier_is_zero_and_consistent_across_action_and_operator():
    from app.execution.risk_tiers import (
        BEHAVIOUR_CHANGING_OPERATORS,
        TIER_BY_ACTION,
        tier_for,
        tier_for_operator,
    )

    # drop_param is behaviour-PRESERVING (dead param + in-project callers rewritten
    # + public-API refusal), so it is NOT behaviour-changing and is Tier 0 — and
    # the ACTION tier (used by the delegated apply path) AGREES with the OPERATOR
    # tier (used by apply_rename), no drift.
    assert "drop_param" not in BEHAVIOUR_CHANGING_OPERATORS
    assert TIER_BY_ACTION["drop_param"] == 0
    assert tier_for("drop_param") == 0 == tier_for_operator("drop_param")


def test_move_value_has_drop_param():
    from app.engine.move_value import OPERATOR_VALUE

    assert "drop_param" in OPERATOR_VALUE
    assert 0.0 <= OPERATOR_VALUE["drop_param"] <= 1.0


def test_north_star_manifest_classifies_dead_params_as_tidy():
    # The flip introduces NO new objective: the objective compiler's ``dead-params``
    # (the operator's objective name) already classifies the drop. It is a
    # behaviour-preserving structural cleanup ⇒ TIDY (removes dead surface), exactly
    # like remove-dead-code / shrink-functions.
    from app.engine.north_star_audit import OBJECTIVE_MANIFEST, classify_objectives
    from app.engine.objective_compiler import available_objectives

    assert "dead-params" in OBJECTIVE_MANIFEST["TIDY"]
    buckets = classify_objectives(set(available_objectives()))  # raises if unclassified
    assert "dead-params" in buckets["TIDY"]
    assert "dead-params" not in buckets["CONCRETE"]


def test_soundness_strategy_declared_for_dead_params():
    from app.engine.objective_compiler import available_objectives
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_completeness,
    )

    sc = strategy_completeness(available_objectives())  # raises if undeclared
    assert "dead-params" in sc
    assert SOUNDNESS_STRATEGY["dead-params"]  # non-empty
    # A behaviour-preserving structural refactor that uses impact_scope at apply
    # time via the bridge — but its OBJECTIVE never sets scope_verify, so it is
    # correctly NOT in the allowlist (the allowlist is the red-baseline objectives).
    assert "dead-params" not in SCOPE_VERIFY_ALLOWLIST


def test_facet_routes_to_dead_params_objective():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective("unused parameter") == "dead-params"
    assert facet_to_objective("api surface") == "dead-params"


def test_object_count_pins_unchanged_by_the_bridge_flip():
    # The flip is BRIDGE-only — it registers no new objective_compiler objective,
    # so the 86/41 objective + CONCRETE counts must be byte-identical.
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    names = set(available_objectives())
    assert len(names) == 87
    assert len(classify_objectives(names)["CONCRETE"]) == 42


# ── 8. the buyer-proof transcript: an INDEPENDENT tiny project ────────────────

def test_buyer_proof_private_lands_public_refused(tmp_path: Path):
    # The spec's buyer-proof, exercised end-to-end on a fresh project: a private
    # ``_calc`` with an in-project keyword caller LANDS the drop (suite GREEN via a
    # real subprocess pytest); a PUBLIC ``api`` in ``__all__`` is an HONEST no-op.
    proj = tmp_path / "buyer"
    (proj / "pkg").mkdir(parents=True)
    (proj / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (proj / "pkg" / "calc.py").write_text(
        "def _calc(x, unused_flag):\n    return x * 2\n", encoding="utf-8")
    (proj / "pkg" / "api.py").write_text(
        '__all__ = ["api"]\n\n\ndef api(x, dead):\n    return x + 1\n',
        encoding="utf-8")
    (proj / "pkg" / "use.py").write_text(
        "from pkg.calc import _calc\n\n"
        "def use():\n    return _calc(3, unused_flag=True)\n", encoding="utf-8")
    (proj / "tests").mkdir()
    (proj / "tests" / "test_use.py").write_text(
        "from pkg.use import use\n\n"
        "def test_use():\n    assert use() == 6\n", encoding="utf-8")
    (proj / "pyproject.toml").write_text(
        "[project]\nname='buyer'\nversion='0'\n", encoding="utf-8")

    bridge = IdeaActionBridge()

    # 1) the private helper: the autonomous drop LANDS.
    priv_step = bridge.plan_idea(_dp_idea("pkg/calc.py", "_calc", "unused_flag"))
    priv = bridge.apply_step(priv_step, str(proj), mode="supervised", verify=True)
    assert priv["applied"] is True, priv
    assert "def _calc(x):" in (proj / "pkg" / "calc.py").read_text()
    assert "_calc(3)" in (proj / "pkg" / "use.py").read_text()

    # 2) the PUBLIC api: an honest no-op (the rail), nothing written.
    pub_before = (proj / "pkg" / "api.py").read_text()
    pub_step = bridge.plan_idea(_dp_idea("pkg/api.py", "api", "dead"))
    pub = bridge.apply_step(pub_step, str(proj), mode="supervised", verify=True)
    assert pub["applied"] is False
    assert "public API" in (pub.get("reason") or "")
    assert (proj / "pkg" / "api.py").read_text() == pub_before

    # 3) prove the whole project's suite is GREEN after the landed drop.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(proj / "tests"), "-q"],
        cwd=str(proj), capture_output=True, text=True,
        env={"PYTHONPATH": str(proj), "PATH": __import__("os").environ["PATH"]})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # And the public signature genuinely still carries its param (rail held).
    assert "def api(x, dead):" in (proj / "pkg" / "api.py").read_text()
    # ``inspect`` confirms the dropped private signature really lost the param.
    sys.path.insert(0, str(proj))
    try:
        import importlib

        calc = importlib.import_module("pkg.calc")
        importlib.reload(calc)
        assert "unused_flag" not in inspect.signature(calc._calc).parameters
    finally:
        sys.path.remove(str(proj))
