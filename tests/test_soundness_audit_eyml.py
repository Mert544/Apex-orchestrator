"""Tests for the durable objective-soundness denetçi: `apex self-audit --soundness`.

Covers (per the spec §5):

* Layer A4 forward/reverse strategy tripwires (manifest completeness + honesty);
* Layer A1 single-gated-writer assertion (real tree clean + a planted self-applier);
* Layer A3 scope_verify allow-list (real registry clean + a planted off-list spec);
* Layer B corpus refuse/behavior-identical on the canonical pairs the round-19
  re-audit flagged (false-final, star-set shrink, frozen-on-unpack, shebang-preserve,
  env-fragile oracle, syntax-error universal refuse, idempotent already-applied);
* the §4 determinism harness (a real stable objective is byte-identical; a PLANTED
  env-fragile objective emitting ``list(set(...))`` is caught as a VIOLATION);
* the CLI exit codes + non-soundness byte-identity (regression guard);
* the audit's OWN determinism (clock-free, byte-identical report).
"""

from __future__ import annotations

import argparse
import sys
import textwrap

import pytest

from app.engine import soundness_audit as sa
from app.engine.develop_registry import ObjectiveSpec, discover
from app.engine.objective_compiler import available_objectives

_REPO = sa.repo_root()


# --- (A4) strategy manifest: forward + reverse tripwires ---------------------

def test_every_live_objective_has_a_strategy():
    table = sa.strategy_completeness(available_objectives())
    assert set(table) == set(available_objectives())
    # No live objective is left without a stated soundness argument.
    assert all(table[name] for name in table)


def test_strategy_completeness_raises_on_undeclared_objective():
    names = [*available_objectives(), "totally-new-self-registered-objective"]
    with pytest.raises(ValueError, match="soundness manifest is stale"):
        sa.strategy_completeness(names)


def test_strategy_reverse_tripwire_flags_stale_name():
    # A manifest strategy whose name is NOT in the live registry is surfaced.
    stale = sa.strategy_subset_of_registry(registered=["add-final"])
    assert "modernize" in stale  # a real manifest name absent from the tiny registry
    assert "add-final" not in stale


def test_manifest_lives_in_dependency_free_leaf_and_is_re_exported():
    # The two manifest constants live in the leaf ``soundness_manifest`` (which
    # imports nothing from the engine, so ``develop_registry`` can read it without a
    # cycle) and are RE-EXPORTED by ``soundness_audit`` as the SAME objects, so the
    # audit's public API is unchanged. Guards the cycle-avoidance decision: re-inlining
    # the manifest into ``soundness_audit`` would reintroduce the register-time cycle.
    from app.engine import soundness_manifest as manifest
    assert sa.SOUNDNESS_STRATEGY is manifest.SOUNDNESS_STRATEGY
    assert sa.SCOPE_VERIFY_ALLOWLIST is manifest.SCOPE_VERIFY_ALLOWLIST
    # The leaf imports nothing from the engine (no back-edge -> no import cycle).
    import ast
    from pathlib import Path
    src = Path(manifest.__file__).read_text(encoding="utf-8")
    engine_imports = [
        n for node in ast.walk(ast.parse(src))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for n in ([node.module] if isinstance(node, ast.ImportFrom) else
                  [a.name for a in node.names])
        if n and n.startswith("app.")
    ]
    assert engine_imports == []


def test_strategy_reverse_tripwire_clean_on_live_registry():
    assert sa.strategy_subset_of_registry() == []


# --- (A1) single gated writer ------------------------------------------------

def test_single_writer_clean_on_real_tree():
    ok, reasons = sa.check_single_writer(_REPO)
    assert ok, reasons
    assert reasons == []


def test_single_writer_detects_a_planted_self_applier(tmp_path):
    # A fake repo whose objective module calls apply_rename directly bypasses the
    # gated/rollback writer — A1 must flag it.
    objs = tmp_path / "app" / "execution" / "objectives"
    objs.mkdir(parents=True)
    (objs / "evil.py").write_text(textwrap.dedent("""
        from app.execution.cross_file_rename import apply_rename
        def moves(root):
            apply_rename(root, None)  # self-applies — bypasses the gate
            return []
    """), encoding="utf-8")
    loop = tmp_path / "app" / "engine" / "objective_compiler.py"
    loop.parent.mkdir(parents=True)
    loop.write_text("from x import apply_rename\napply_rename(1, 2)\n", encoding="utf-8")
    ok, reasons = sa.check_single_writer(tmp_path)
    assert not ok
    assert any("evil.py" in r and "apply_rename" in r for r in reasons)


def test_single_writer_detects_a_second_loop_call_site(tmp_path):
    (tmp_path / "app" / "execution" / "objectives").mkdir(parents=True)
    loop = tmp_path / "app" / "engine" / "objective_compiler.py"
    loop.parent.mkdir(parents=True)
    loop.write_text(
        "from x import apply_rename\napply_rename(1)\napply_rename(2)\n", encoding="utf-8")
    ok, reasons = sa.check_single_writer(tmp_path)
    assert not ok
    assert any("2 apply_rename call sites" in r for r in reasons)


def test_single_writer_ignores_apply_rename_in_a_docstring(tmp_path):
    # A spec module that only MENTIONS apply_rename in prose is not a violation.
    objs = tmp_path / "app" / "execution" / "objectives"
    objs.mkdir(parents=True)
    (objs / "doc.py").write_text(
        '"""This objective relies on apply_rename for rollback."""\n', encoding="utf-8")
    loop = tmp_path / "app" / "engine" / "objective_compiler.py"
    loop.parent.mkdir(parents=True)
    loop.write_text("from x import apply_rename\napply_rename(1)\n", encoding="utf-8")
    ok, reasons = sa.check_single_writer(tmp_path)
    assert ok, reasons


# --- (A3) scope_verify allow-list --------------------------------------------

def test_scope_verify_clean_on_real_registry():
    ok, reasons = sa.check_scope_verify_allowlist()
    assert ok, reasons


def test_scope_verify_real_allowlist_members_pass():
    from app.engine.develop_registry import registered_specs

    specs = registered_specs()
    for name in sa.SCOPE_VERIFY_ALLOWLIST:
        assert getattr(specs[name], "scope_verify", False) is True


def test_scope_verify_flags_an_off_list_objective():
    specs = {
        "rogue": ObjectiveSpec("rogue", lambda p: 0.0, lambda p: [], scope_verify=True),
        "implement-stub": ObjectiveSpec(
            "implement-stub", lambda p: 0.0, lambda p: [], scope_verify=True),
    }
    ok, reasons = sa.check_scope_verify_allowlist(specs)
    assert not ok
    assert any("rogue" in r for r in reasons)
    # The genuine allow-list member is NOT flagged.
    assert not any("implement-stub" in r for r in reasons)


# --- (B) corpus refuse / behavior-identical: the canonical pairs -------------

def _verdict(objective: str, shape: str) -> str:
    from app.engine.objective_compiler import _objectives_map

    _fitness, moves = _objectives_map()[objective]
    changed = sa._changed_files(moves, sa.corpus_root(_REPO) / shape)
    return sa._classify_cell(shape, objective, changed)


def test_corpus_present():
    shapes = sa.corpus_shapes(_REPO)
    assert {
        "shebang_coding", "external_subclasser", "star_consumer",
        "relative_star_consumer", "env_fragile_return", "walrus_binder",
        "unpack_decorator", "provenance_trap", "syntax_error", "already_applied",
        "init_reexport",
    } <= set(shapes)


def test_add_final_refuses_external_subclasser():
    assert _verdict("add-final", "external_subclasser") == "refused"


def test_seal_final_method_refuses_external_subclasser():
    assert _verdict("seal-final-method", "external_subclasser") == "refused"


def test_wire_module_exports_refuses_star_consumer():
    assert _verdict("wire-module-exports", "star_consumer") == "refused"


def test_wire_module_exports_refuses_relative_star_consumer():
    assert _verdict("wire-module-exports", "relative_star_consumer") == "refused"


def test_remove_unused_imports_refuses_init_reexport():
    # The buyer-facing trap: a package __init__.py whose public re-export carries
    # no __all__. remove-unused-imports must refuse the whole file, never prune the
    # re-export that IS the package's public surface.
    assert _verdict("remove-unused-imports", "init_reexport") == "refused"


def test_wire_module_exports_refuses_walrus_binder():
    assert _verdict("wire-module-exports", "walrus_binder") == "refused"


def test_freeze_dataclass_refuses_unpack_decorator():
    assert _verdict("freeze-dataclass", "unpack_decorator") == "refused"


def test_freeze_dataclass_and_add_final_refuse_provenance_trap():
    assert _verdict("freeze-dataclass", "provenance_trap") == "refused"
    assert _verdict("add-final", "provenance_trap") == "refused"


def test_top_of_file_inserter_is_behavior_identical_on_shebang():
    # wire-module-exports LANDS __all__ here, but must keep the shebang on line 1.
    assert _verdict("wire-module-exports", "shebang_coding") == "behavior-identical"


def test_idempotent_already_applied_is_refused():
    for objective in ("wire-module-exports", "add-final", "freeze-dataclass"):
        assert _verdict(objective, "already_applied") == "refused"


@pytest.mark.parametrize(
    "objective",
    ["add-final", "freeze-dataclass", "wire-module-exports", "seal-final-method",
     "modernize", "infer-type-hints", "sort-imports"],
)
def test_every_objective_refuses_syntax_error(objective):
    assert _verdict(objective, "syntax_error") == "refused"


def test_full_corpus_sweep_is_clean_on_the_live_registry():
    # The fast (cheap-objective) sweep yields NO violation cell on the clean repo.
    corpus = sa.corpus_refusal_findings(_REPO)
    bad = {f"{o}.{s}": v for o, cells in corpus.items()
           for s, v in cells.items() if v.startswith("VIOLATION")}
    assert bad == {}, bad


def test_corpus_only_slice_is_identical_to_full_row():
    # ``only`` restricts the sweep to the named objectives; the sliced row MUST be
    # byte-identical to that objective's row in the full sweep (per-objective
    # independence), and ONLY the requested objective(s) appear. This is the cost knob
    # the per-objective corpus tests use to dodge the ~2-minute heavy sweep without
    # changing any verdict. Uses cheap (light-sweep) objectives so the test stays fast.
    full = sa.corpus_refusal_findings(_REPO)  # light sweep, all cheap objectives
    assert "wire-module-exports" in full and "add-final" in full
    sliced = sa.corpus_refusal_findings(_REPO, only={"wire-module-exports"})
    assert set(sliced) == {"wire-module-exports"}  # no other objective leaks in
    assert sliced["wire-module-exports"] == full["wire-module-exports"]  # identical row
    # A two-name slice carries exactly those two rows, each identical to the full sweep.
    pair = sa.corpus_refusal_findings(_REPO, only=["wire-module-exports", "add-final"])
    assert set(pair) == {"wire-module-exports", "add-final"}
    assert pair["add-final"] == full["add-final"]


def test_corpus_only_unknown_and_heavy_names_are_dropped():
    # A name that isn't in the (light) sweep selection simply yields no row — exactly as
    # it would be absent from the full sweep — never an error. A heavy objective requested
    # under the default (light) sweep is therefore absent too; the heavy/light gate still
    # governs which objectives a slice can surface.
    only_unknown = sa.corpus_refusal_findings(_REPO, only={"not-a-real-objective"})
    assert only_unknown == {}
    # ``cover-gaps`` is heavy (subprocess-backed) — absent from a light slice.
    assert sa.corpus_refusal_findings(_REPO, only={"cover-gaps"}) == {}


def test_corpus_only_returns_independent_deep_copy():
    # The memo deep-copies on read, so mutating a sliced result cannot corrupt the cached
    # entry a later caller receives.
    a = sa.corpus_refusal_findings(_REPO, only={"wire-module-exports"})
    a["wire-module-exports"]["syntax_error"] = "MUTATED"
    a["injected"] = {}
    b = sa.corpus_refusal_findings(_REPO, only={"wire-module-exports"})
    assert "injected" not in b
    assert b["wire-module-exports"]["syntax_error"] == "refused"


# --- (B) the classifier's behavior-identical predicate -----------------------

def test_classifier_flags_a_lost_shebang_prologue():
    changed = {"pkg/mod.py": (
        "def public_one():\n    return 1\n",       # new: shebang gone
        "#!/usr/bin/env python3\n# c\n\ndef public_one():\n    return 1\n")}  # orig had it
    verdict = sa._classify_cell("shebang_coding", "some-inserter", changed)
    assert verdict.startswith("VIOLATION:shebang-prologue-not-preserved")


def test_classifier_allows_a_non_python_doc_artifact():
    # A landed USAGE.md carries no Python semantics — behavior-identical, not a
    # re-parse violation (the false positive the predicate must NOT raise).
    changed = {"pkg/USAGE.md": ("# Usage\n\nGenerated.\n", "")}
    assert sa._classify_cell("shebang_coding", "generate-usage-doc", changed) \
        == "behavior-identical"


def test_classifier_flags_a_change_where_refusal_required():
    # A PLANTED false-final on the externally-subclassed class is a VIOLATION.
    changed = {"pkg/lib.py": ("@final\nclass Widget:\n    pass\n",
                              "class Widget:\n    pass\n")}
    verdict = sa._classify_cell("external_subclasser", "add-final", changed)
    assert verdict.startswith("VIOLATION:landed-change-where-refusal-required")


def test_classifier_flags_a_non_reparsing_python_rewrite():
    changed = {"pkg/mod.py": ("def broken(:\n    pass\n", "def ok():\n    pass\n")}
    verdict = sa._classify_cell("shebang_coding", "some-rewriter", changed)
    assert verdict.startswith("VIOLATION:rewrite-does-not-reparse")


# --- (§4) determinism harness ------------------------------------------------

def test_determinism_real_objective_is_byte_identical():
    # A genuinely order-stable objective matches under BOTH env variations.
    fixture = sa.corpus_root(_REPO) / "shebang_coding"
    assert sa._determinism_verdict(_REPO, fixture, "wire-module-exports") \
        == "byte-identical"


_PLANTED_FRAGILE = '''\
"""TEMP planted env-fragile objective (removed by the test's finally)."""
from __future__ import annotations
from pathlib import Path
from app.engine.develop_registry import ObjectiveSpec, register
from app.engine.soundness_audit import SOUNDNESS_STRATEGY
from app.execution.cross_file_rename import RenamePlan

# The register-time soundness lock refuses an objective absent from the manifest.
# Declare this planted probe's strategy IN THE MODULE so it holds in BOTH the parent
# process AND the determinism subprocess (each imports this file from disk afresh); a
# parent-only monkeypatch would not reach the child. The test's finally pops the
# in-process entry; the child is short-lived, so its process-local entry dies with it.
SOUNDNESS_STRATEGY.setdefault("zz-planted-fragile", "TEST-planted-env-fragile-probe")


def _moves(project_root):
    from app.engine.objective_compiler import Move
    target = Path(project_root) / "pkg" / "mod.py"
    if not target.exists():
        return []

    def _plan():
        plan = RenamePlan(old="pkg/mod.py", new="zz-planted")
        orig = target.read_text(encoding="utf-8")
        # set-iteration order -> PYTHONHASHSEED-dependent emitted bytes.
        names = list({"alpha", "bravo", "charlie", "delta", "echo", "foxtrot"})
        plan.originals["pkg/mod.py"] = orig
        plan.new_contents["pkg/mod.py"] = orig + "\\n_ORDER = " + repr(names) + "\\n"
        plan.edits_by_file["pkg/mod.py"] = 1
        return plan

    return [Move(operator="zz_planted", target="pkg/mod.py:zz",
                 description="planted", build_plan=_plan)]


register(ObjectiveSpec(name="zz-planted-fragile", fitness=lambda p: 0.0, moves=_moves))
'''


def test_determinism_catches_a_planted_env_fragile_objective():
    # The round-19 bug class: an objective whose LANDED diff embeds a set/dict-
    # iteration order. It must diverge across the two pinned PYTHONHASHSEED runs.
    # Injected as a real (discoverable) objectives module so the determinism
    # subprocess re-derives it via `_objectives_map()` too, then removed.
    objs = _REPO / "app" / "execution" / "objectives"
    planted = objs / "zz_planted_probe.py"
    planted.write_text(_PLANTED_FRAGILE, encoding="utf-8")
    try:
        # Importing the planted module both registers the objective AND declares its
        # soundness strategy (the module inserts its own manifest entry so the
        # register-time lock passes here and in the determinism subprocess).
        import app.execution.objectives.zz_planted_probe  # noqa: F401  -- register
        discover(force=True)
        fixture = sa.corpus_root(_REPO) / "shebang_coding"
        verdict = sa._determinism_verdict(_REPO, fixture, "zz-planted-fragile")
        assert verdict.startswith("VIOLATION:diff-not-byte-identical")
    finally:
        planted.unlink(missing_ok=True)
        for cached in (objs / "__pycache__").glob("zz_planted_probe*.pyc"):
            cached.unlink(missing_ok=True)
        sys.modules.pop("app.execution.objectives.zz_planted_probe", None)
        from app.engine import develop_registry
        develop_registry._REGISTRY.pop("zz-planted-fragile", None)
        sa.SOUNDNESS_STRATEGY.pop("zz-planted-fragile", None)
        discover(force=True)


def test_determinism_probe_failure_is_a_violation():
    # An objective name the subprocess cannot resolve -> the probe declines (ok:False)
    # -> the verdict must be a VIOLATION, never a false "both runs agree on the error".
    fixture = sa.corpus_root(_REPO) / "shebang_coding"
    verdict = sa._determinism_verdict(_REPO, fixture, "no-such-objective-xyz")
    assert verdict.startswith("VIOLATION:")


def test_target_shape_is_none_for_a_refuse_everywhere_objective():
    from app.engine.objective_compiler import _objectives_map

    objectives = _objectives_map()
    # `sort-imports` lands nothing on these tiny single-import fixtures, so the
    # harness skips it (two empty diffs prove nothing).
    shape = sa._determinism_target_shape(_REPO, objectives, "sort-imports")
    assert shape is None or isinstance(shape, str)


# --- heavy/fast cost split ---------------------------------------------------

def test_cover_gaps_is_in_the_heavy_set():
    # cover-gaps is subprocess-backed but NOT registry-`expensive`; it must be in the
    # heavy set so the fast corpus sweep stays sub-second.
    assert "cover-gaps" in sa.heavy_objective_names()


def test_fast_sweep_omits_heavy_objectives():
    corpus = sa.corpus_refusal_findings(_REPO, include_heavy=False)
    assert "cover-gaps" not in corpus
    # but the cheap ones ARE swept
    assert "wire-module-exports" in corpus


# --- CLI ---------------------------------------------------------------------

def test_cli_soundness_pass_markdown(capsys):
    from app import cli_ops

    args = argparse.Namespace(
        target=".", format="markdown", north_star=False, commits=20,
        soundness=True, determinism=False)
    assert cli_ops.cmd_self_audit(args) == 0
    out = capsys.readouterr().out
    assert "Objective Soundness" in out
    assert "PASS" in out


def test_cli_soundness_json_pass(capsys):
    from app import cli_ops

    args = argparse.Namespace(
        target=".", format="json", north_star=False, commits=20,
        soundness=True, determinism=False)
    assert cli_ops.cmd_self_audit(args) == 0
    out = capsys.readouterr().out
    assert '"verdict": "PASS"' in out
    assert '"violations": []' in out


def test_cli_soundness_exits_nonzero_on_planted_violation(monkeypatch, capsys):
    from app import cli_ops

    base = sa.soundness_report(str(_REPO))
    bad = dict(base)
    bad["violations"] = ["corpus.evil.shebang_coding: VIOLATION:demo"]
    bad["verdict"] = "FAIL"
    monkeypatch.setattr(sa, "soundness_report", lambda *a, **k: bad)
    args = argparse.Namespace(
        target=".", format="json", north_star=False, commits=20,
        soundness=True, determinism=False)
    assert cli_ops.cmd_self_audit(args) == 1
    assert '"verdict": "FAIL"' in capsys.readouterr().out


def test_cli_north_star_path_is_unaffected_by_soundness_flag(monkeypatch, capsys):
    # --north-star takes precedence and stays byte-identical when --soundness is absent.
    from app import cli_ops
    from app.engine import north_star_audit as nsa

    monkeypatch.setattr(nsa, "_git_subjects", lambda *a, **k: ["feat(develop): x"])
    args = argparse.Namespace(
        target=".", format="markdown", north_star=True, commits=20,
        soundness=False, determinism=False)
    assert cli_ops.cmd_self_audit(args) == 0
    out = capsys.readouterr().out
    assert "North Star" in out
    assert "Objective Soundness" not in out


def test_cli_legacy_path_unchanged_without_soundness(monkeypatch, capsys):
    from app import cli_ops

    class _FakeAgent:
        def run(self, project_root):
            return {"findings": [], "missing_docstrings_count": 0,
                    "long_functions_count": 0, "todos_count": 0, "coverage_gap": {}}

    import app.agents.skills.self_audit_agent as sa_mod
    monkeypatch.setattr(sa_mod, "SelfAuditAgent", _FakeAgent)
    args = argparse.Namespace(target=".", format="markdown")  # no soundness attr
    assert cli_ops.cmd_self_audit(args) == 0
    out = capsys.readouterr().out
    assert "Apex Self-Audit Report" in out
    assert "Objective Soundness" not in out


# --- determinism of the AUDIT itself -----------------------------------------

def test_report_is_byte_identical_across_two_calls():
    r1 = sa.soundness_report(str(_REPO))
    r2 = sa.soundness_report(str(_REPO))
    assert r1 == r2  # pure function of repo state


def test_report_keys_are_stable_and_clockless():
    r = sa.soundness_report(str(_REPO))
    assert set(r.keys()) == {
        "total_objectives", "strategy_table", "stale_strategies",
        "single_writer_ok", "scope_verify_ok", "corpus", "determinism",
        "violations", "verdict",
    }
    flat = repr(r).lower()
    for forbidden in ("epoch", "timestamp", "wall-clock", "datetime.now"):
        assert forbidden not in flat


def test_render_markdown_is_deterministic_and_shows_verdict():
    r = sa.soundness_report(str(_REPO))
    md1 = sa.render_markdown(r, _REPO)
    md2 = sa.render_markdown(r, _REPO)
    assert md1 == md2
    assert "Verdict: **PASS**" in md1


def test_render_markdown_lists_violations_when_present():
    r = sa.soundness_report(str(_REPO))
    r = dict(r)
    r["violations"] = ["corpus.x.syntax_error: VIOLATION:demo"]
    r["verdict"] = "FAIL"
    md = sa.render_markdown(r, _REPO)
    assert "## Violations" in md
    assert "corpus.x.syntax_error" in md
