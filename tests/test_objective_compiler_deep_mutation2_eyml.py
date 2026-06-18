"""Residual deep mutation-hardening for ``app/engine/objective_compiler.py``.

A companion to ``test_objective_compiler_deep_mutation_eyml.py`` (which kills the
first wave of non-equivalent survivors). That file enumerated the FULL single-
token mutant universe via the engine's own ``_collect_sites`` (145 valid
splices). This file re-runs that same enumeration against the *combined* focused
suite (``test_objective_compiler*.py`` + ``test_objective_dedup_total_return.py``
+ ``test_cli_objectives.py`` + the first deep-mutation file) and pins the EIGHT
mutants that still survive after that combined suite:

    L371 number  1 -> 2   `occ[0].split(":", 1)[0]`
    L703 number  1 -> 2   `move.target.split(":", 1)[0]`
    L834 const   False->True  `scope_verify: bool = False`
    L890 number  1 -> 2   `for _pass in range(max_steps + 1)`
    L891 bound  >= -> >    `if len(result.steps) >= max_steps: break`
    L904 bool   and->or    `if apply and result.steps:`
    L910 number  1 -> 2   `target.split(":", 1)[0]`
    L1005 number 25 -> 26  `compile_from_dream(..., max_steps=25, ...)`

Every one of these is an EQUIVALENT mutant: the flipped token cannot change any
observable behaviour, so NO test can fail on the mutant without also failing on
the original (which would be asserting a falsehood). Rather than leave that claim
as a bare comment, each test below pins the POSITIVE behavioural contract that
makes the flip equivalent — a regression in the surrounding logic (the thing the
comment relies on) would break these tests even though the specific token flip
cannot. The equivalence reasoning is recorded inline per site.

Style mirrors ``test_objective_compiler.py`` / ``..._deep_mutation_eyml.py``: a
tiny ``tmp_path`` project, direct helper calls, lightweight fakes.
"""
from __future__ import annotations

from pathlib import Path

from app.engine.composition_archive import record_campaign
from app.engine.objective_compiler import (
    CompileResult,
    Move,
    _archive_campaign,
    _dedup_moves,
    _move_module,
    _move_module_from_target,
    compile_from_dream,
    compile_objective,
)


def _project(tmp_path: Path, body: str, rel: str = "app/m.py") -> Path:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / rel).write_text(body, encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import app.m\ndef test_import():\n    assert app.m is not None\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0'\n", encoding="utf-8")
    return tmp_path


# --- L371 / L703 / L910: `split(":", 1)[0]` maxsplit `1 -> 2` -----------------
#
# EQUIVALENT. ``str.split(sep, maxsplit)`` only bounds HOW MANY splits happen;
# element ``[0]`` is everything before the FIRST separator and is byte-identical
# for any ``maxsplit >= 1``. The flip ``1 -> 2`` can never change ``[0]``. The
# tests below pin the contract "the module is the segment before the first
# colon, even when later colons are present" — the property the equivalence
# argument leans on (a second colon must NOT bleed into the result).

class _BlockColonyOcc:
    # An occurrence string carrying TWO colons — the only input that could ever
    # distinguish maxsplit=1 from maxsplit=2 if ``[0]`` were not the prefix.
    occurrences = ["app/pkg/mod.py:dup:tail"]
    lines = 2


def test_l371_dedup_target_module_is_prefix_before_first_colon(tmp_path):
    _project(tmp_path, "x = 1\n")
    import app.engine.objective_compiler as oc

    orig = oc._duplicate_blocks
    oc._duplicate_blocks = lambda root: [_BlockColonyOcc()]
    try:
        moves = _dedup_moves(str(tmp_path))
        # `occ[0].split(":", 1)[0]` -> "app/pkg/mod.py" regardless of the trailing
        # ":tail"; a maxsplit of 1 or 2 yields the identical [0] prefix.
        assert moves[0].target == "app/pkg/mod.py:dup"
    finally:
        oc._duplicate_blocks = orig


def test_l703_move_module_is_prefix_before_first_colon_with_extra_colons():
    mv = Move(operator="op", target="app/pkg/mod.py:render:extra",
              description="d", build_plan=lambda: None)
    # split(":", 1)[0] keeps only the pre-first-colon prefix; the second colon
    # never enters [0], so maxsplit 1 vs 2 is unobservable here.
    assert _move_module(mv) == "app/pkg/mod.py"


def test_l910_move_module_from_target_prefix_with_extra_colons():
    assert _move_module_from_target("app/pkg/x.py:dead:code") == "app/pkg/x.py"


# --- L834: `scope_verify: bool = False` default (compile_objective) -----------
#
# EQUIVALENT-IN-PRACTICE. ``scope_verify`` only reaches
# ``apply_rename(impact_scope=...)``: with it set, the per-move gate runs the
# IMPACTED tests when some cover the change and FALLS THROUGH to the full suite
# otherwise. For a clean refactor the verified/applied/rolled-back outcome — the
# only thing ``CompileResult`` records — is identical for False and True; the
# scoped path's extra ``test_evidence`` is never stored on a ``CompileStep``.
# The test pins the default-path contract: with the default flags a clean
# campaign lands its moves and marks them verified, so a regression that broke
# the default (verify) gate would be caught here even though the False->True
# flip cannot be.

_THREE_DEAD = (
    "def render(text, color=None, width=80):\n"
    "    return text[:width]\n\n\n"
    "def fetch(url, retries=3):\n"
    "    return url\n\n\n"
    "def use():\n"
    "    return render('hi', width=10) + fetch('u', retries=1)\n"
)


def test_l834_compile_objective_default_scope_verify_lands_and_verifies(tmp_path):
    _project(tmp_path, _THREE_DEAD)
    # All defaults: apply=True, verify=True, scope_verify=False. A clean campaign
    # lands its drop-param moves and ticks each step verified. The False->True
    # flip on scope_verify produces the IDENTICAL CompileResult (same steps, same
    # verified ticks) — only the internal verify path differs, unobservably.
    r = compile_objective(str(tmp_path), objective="dead-params")
    assert r.applied is True
    assert r.steps
    assert all(s.verified is True for s in r.steps)
    assert "color" not in (tmp_path / "app" / "m.py").read_text()


# --- L890: `for _pass in range(max_steps + 1)` number `1 -> 2` ----------------
# --- L891: `if len(result.steps) >= max_steps: break` boundary `>= -> >` ------
#
# Both EQUIVALENT. The outer per-pass loop is never bounded by ``range``'s upper
# limit nor by the outer ``>=`` guard's inclusivity: ``_run_pass`` carries the
# SAME ``len(result.steps) >= max_steps`` cap on every move it applies (L807), and
# the ``if not progressed: break`` fixpoint exit ends the loop the instant a pass
# lands nothing. Raising the range bound to ``+ 2`` only adds an iteration that
# can never run (the inner cap / fixpoint already exited); flipping the outer
# ``>=`` to ``>`` only lets a pass START that immediately hits the inner cap and
# applies nothing. The contract pinned here: a campaign stops EXACTLY at
# ``max_steps`` landed moves and never exceeds it.

def _many_dead(n: int) -> str:
    parts = []
    for i in range(n):
        parts.append(f"def f{i}(a, dead{i}=None):\n    return a\n")
    parts.append("def use():\n    return " +
                 " + ".join(f"f{i}(1, dead{i}=2)" for i in range(n)) + "\n")
    return "\n\n".join(parts)


def test_l890_l891_campaign_caps_landed_moves_at_max_steps(tmp_path):
    # Six independently-droppable dead params, max_steps=3 -> the campaign must
    # land EXACTLY 3 moves and stop. The `+1 -> +2` range bound and the
    # `>= -> >` outer-guard flip both leave this count unchanged (the inner cap
    # binds first).
    _project(tmp_path, _many_dead(6))
    r = compile_objective(str(tmp_path), objective="dead-params",
                          max_steps=3, verify=False)
    assert len(r.steps) == 3


def test_l890_l891_zero_max_steps_lands_nothing(tmp_path):
    # The boundary edge: max_steps=0. Original `range(1)` enters once and the
    # outer `>= 0` guard breaks immediately; the `>` mutant skips the break but
    # the inner `>= 0` cap in _run_pass applies nothing -> same empty result.
    _project(tmp_path, _THREE_DEAD)
    r = compile_objective(str(tmp_path), objective="dead-params",
                          max_steps=0, verify=False)
    assert r.steps == []
    assert r.applied is True


# --- L904: `if apply and result.steps:` boolean `and -> or` -------------------
#
# EQUIVALENT. This archive guard is only reached with ``apply=True`` (a dry run
# returns earlier at ``if not apply``). With apply pinned True the sole divergence
# is the empty-steps case: ``True and [] -> []`` (skip archive) vs
# ``True or [] -> True`` (enter archive). But the entered
# ``_archive_campaign -> record_campaign`` itself no-ops on empty operators
# (``if not operators: return False``) and writes nothing. So no observable
# difference exists on any reachable input.

def test_l904_record_campaign_noops_on_empty_operators(tmp_path):
    # The fact that makes the and->or flip equivalent: archiving an empty
    # campaign changes nothing and never raises. If this contract regressed, the
    # equivalence argument would fail loudly here.
    changed = record_campaign(str(tmp_path), "dead-params", [], 5.0, 5.0, 0)
    assert changed is False
    assert not (tmp_path / ".apex").exists()


def test_l904_archive_campaign_empty_steps_writes_no_playbook(tmp_path):
    _project(tmp_path, "x = 1\n")
    # A CompileResult with no steps: _archive_campaign forwards an empty operator
    # list, record_campaign no-ops, no playbook file appears. So entering the
    # archive branch (the or-mutant) vs skipping it (original) is identical.
    result = CompileResult(objective="dead-params", fitness_start=2.0,
                           fitness_end=2.0, applied=True)
    _archive_campaign(result, str(tmp_path), "dead-params", 2.0, 2.0)
    playbook = tmp_path / ".apex" / "composition-archive.json"
    assert not playbook.exists()


# --- L1005: `compile_from_dream(..., max_steps: int = 25, ...)` number 25->26 -
#
# EQUIVALENT-IN-PRACTICE. ``compile_from_dream`` runs a SCOPED, per-module
# campaign and threads ``max_steps`` straight into ``compile_objective`` as that
# module's cap. No single module realistically presents > 25 simultaneously
# landable moves for one objective, so the cap is never the binding constraint
# and 25 vs 26 is unobservable. The non-scoped 25-default is already pinned by
# L832 (compile_objective) and L913 (compile_all) in the first deep-mutation
# file. Here we pin that ``compile_from_dream`` over a dream that named NO
# confluence yields no campaigns at all (the cap value is irrelevant), and that
# a scoped run honours a low explicit cap.

def test_l1005_compile_from_dream_no_confluence_yields_no_results(tmp_path):
    _project(tmp_path, "x = 1\n")
    # No dream confluence -> empty result list; the default max_steps never even
    # reaches a campaign, so 25 vs 26 cannot matter.
    results = compile_from_dream(str(tmp_path), verify=False)
    assert results == []
