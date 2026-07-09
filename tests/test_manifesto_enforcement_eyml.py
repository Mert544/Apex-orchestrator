"""L7 self-awareness — the manifesto actually GOVERNS (opt-in enforcement).

``apex manifesto`` derives the project's experience-based constitution, but
today it is read-only prose: nothing enforces it. This wires an OPT-IN
``manifesto_aware`` mode into the develop loop's EXISTING avoid-skip and
risk-order channels (no parallel machinery):

* an AVOID law skips a law-flagged move via the SAME ``skip_targets`` channel
  ``avoid_aware`` already uses, naming the law verbatim in the reason;
* a FRAGILE law demotes a matching move via the SAME stable-reorder shape
  ``risk_aware`` already uses — never dropped, only ordered later;
* every law that fired is disclosed on ``result.manifesto_laws`` and in the
  compile render, so the constitution a human reads is visibly governing.

Pins: opt-in/off-by-default byte-identical, no-history/no-laws no-op,
deterministic, and that the two surfaces (``apex manifesto`` / the applied
gate) can never disagree because enforcement reads the CURATED law text, not
the raw signal.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import app.cli_autonomy as cli_autonomy
from app.cli_autonomy import register_parsers
from app.engine.manifesto import (
    avoid_law_signatures,
    derive_manifesto,
    fragile_law_modules,
    render_manifesto_markdown,
)
from app.engine.objective_compiler import (
    CompileResult,
    Move,
    _manifesto_fragile_demoted,
    compile_objective,
    render_compile_markdown,
)
from app.engine.proof_of_fix import SCHEMA


def _mv(operator: str, module: str) -> Move:
    return Move(operator=operator, target=f"{module}:x", description="",
                build_plan=lambda: None)


def _history(root: Path, fixes: list[dict]) -> None:
    (root / ".apex").mkdir(parents=True, exist_ok=True)
    (root / ".apex" / "proof-of-fix.json").write_text(
        json.dumps({"schema": SCHEMA, "generated_at": "2026-01-01", "fixes": fixes}),
        encoding="utf-8")


def _fix(action: str, module: str, outcome: str) -> dict:
    return {"outcome": outcome, "finding": {"action": action, "target": module},
            "changed_files": [module]}


def _fragile_history(root: Path, module: str = "app/bad.py") -> None:
    # 4 rolled back + 1 applied on the SAME module -> total 5 (>=3), reliability
    # 0.2 (<0.5): a FRAGILE law for ``module`` (mirrors test_manifesto_eyml's
    # ``learned_project`` fixture; action varies so it never ALSO trips AVOID).
    _history(root, [
        *[_fix("x", module, "rolled_back") for _ in range(4)],
        _fix("x", module, "applied"),
    ])


# ``flagged.py`` is nested 3 levels deep (module_traits' "deep" trait); ``safe.py``
# is shallow — different trait buckets, so a fabricated AVOID law can flag ONE
# without touching the other (mirrors test_develop_avoid_skip_eyml's fixture).
_NONE_CHECK = "def f(x):\n    return x == None\n"


def _flagged_and_safe(root: Path) -> None:
    (root / "pkg" / "a" / "b").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "a" / "b" / "flagged.py").write_text(_NONE_CHECK, encoding="utf-8")
    (root / "pkg" / "safe.py").write_text(_NONE_CHECK, encoding="utf-8")


def _rolled_back_modernize_on_deep_module(root: Path) -> None:
    _history(root, [
        _fix("modernize", "pkg/a/b/flagged.py", "rolled_back") for _ in range(5)
    ])


def _two_modernize_modules(root: Path, first: str, second: str) -> None:
    # Two real modernizable files (both trip the SAME ``modernize`` transform),
    # named so their alphabetical generation order is explicit: ``first`` sorts
    # before ``second``.
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / first).write_text(_NONE_CHECK, encoding="utf-8")
    (root / "pkg" / second).write_text(_NONE_CHECK, encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. AVOID law names itself in the disclosed skip reason (engine level)        #
# --------------------------------------------------------------------------- #

def test_manifesto_avoid_law_named_in_skip_reason(tmp_path):
    _flagged_and_safe(tmp_path)
    _rolled_back_modernize_on_deep_module(tmp_path)
    law = avoid_law_signatures(str(tmp_path))["modernize | deep"]
    r = compile_objective(str(tmp_path), objective="modernize", apply=True,
                          verify=False, manifesto_aware=True)
    landed = {s.target for s in r.steps}
    assert "pkg/safe.py:modernize" in landed              # unflagged move still lands
    assert "pkg/a/b/flagged.py:modernize" not in landed    # law-flagged move refused
    assert any(law in a for a in r.avoided)                # law named VERBATIM
    assert law in r.manifesto_laws
    # the skipped file is untouched — the guard fired before any write.
    assert (tmp_path / "pkg" / "a" / "b" / "flagged.py").read_text() == _NONE_CHECK


# --------------------------------------------------------------------------- #
# 2/3. FRAGILE demotion reorders without dropping, stable on ties (unit level) #
# --------------------------------------------------------------------------- #

def test_fragile_demotion_reorders_without_dropping(tmp_path):
    _fragile_history(tmp_path, "app/bad.py")
    moves = [_mv("op", "app/bad.py"), _mv("op", "app/good.py")]
    ordered = _manifesto_fragile_demoted(moves, str(tmp_path))
    assert len(ordered) == 2  # never dropped
    assert [m.target for m in ordered] == ["app/good.py:x", "app/bad.py:x"]


def test_fragile_demotion_stable_on_ties(tmp_path):
    _fragile_history(tmp_path, "app/bad.py")
    # Two moves on the SAME fragile module: both demoted equally, so their
    # relative order must be preserved (stable sort), not swapped.
    moves = [_mv("modernize", "app/bad.py"), _mv("inline", "app/bad.py")]
    ordered = _manifesto_fragile_demoted(moves, str(tmp_path))
    assert [m.operator for m in ordered] == ["modernize", "inline"]


def test_fragile_demotion_noop_without_laws(tmp_path):
    moves = [_mv("op", "app/bad.py"), _mv("op", "app/good.py")]
    assert _manifesto_fragile_demoted(moves, str(tmp_path)) == moves


# --------------------------------------------------------------------------- #
# 3b. FRAGILE law disclosure requires an ACTUAL reorder (end-to-end, no over-  #
#     claim): a fragile module that was already trailing in generation order  #
#     is a no-op demotion — the law must NOT be reported as having fired.     #
# --------------------------------------------------------------------------- #

def test_manifesto_fragile_law_not_disclosed_when_no_reorder_happens(tmp_path):
    # "aaa_good.py" < "zzz_bad.py" alphabetically, so the natural generation
    # order is [good, bad] — already fragile-last, exactly what demotion would
    # produce anyway. Nothing actually moves.
    _two_modernize_modules(tmp_path, "aaa_good.py", "zzz_bad.py")
    _fragile_history(tmp_path, "pkg/zzz_bad.py")
    r = compile_objective(str(tmp_path), objective="modernize", apply=True,
                          verify=False, manifesto_aware=True)
    landed = {s.target for s in r.steps}
    # Both moves still land — FRAGILE never drops, only reorders.
    assert landed == {"pkg/aaa_good.py:modernize", "pkg/zzz_bad.py:modernize"}
    # No governance actually happened this pass, so nothing may be disclosed
    # as "fired" — over-claiming here is the exact bug this pins against.
    assert r.manifesto_laws == []


def test_manifesto_fragile_law_disclosed_when_reorder_actually_happens(tmp_path):
    # "aaa_bad.py" < "zzz_good.py" alphabetically, so the natural generation
    # order is [bad, good] — the fragile module LEADS, so demotion genuinely
    # swaps it behind the non-fragile move.
    _two_modernize_modules(tmp_path, "aaa_bad.py", "zzz_good.py")
    _fragile_history(tmp_path, "pkg/aaa_bad.py")
    r = compile_objective(str(tmp_path), objective="modernize", apply=True,
                          verify=False, manifesto_aware=True)
    landed = {s.target for s in r.steps}
    assert landed == {"pkg/aaa_bad.py:modernize", "pkg/zzz_good.py:modernize"}
    # A real demotion occurred -> the law is honestly disclosed as fired.
    assert any("pkg/aaa_bad.py" in law for law in r.manifesto_laws)


# --------------------------------------------------------------------------- #
# 4. OFF -> byte-identical (pinned)                                            #
# --------------------------------------------------------------------------- #

def test_manifesto_aware_off_byte_identical(tmp_path):
    _flagged_and_safe(tmp_path)
    _rolled_back_modernize_on_deep_module(tmp_path)
    r = compile_objective(str(tmp_path), objective="modernize", apply=True,
                          verify=False)  # manifesto_aware defaults to False
    landed = {s.target for s in r.steps}
    # Nothing skipped/demoted by the manifesto gate: both moves land, exactly
    # as the pre-existing (avoid_aware-off) behaviour already pinned.
    assert {"pkg/safe.py:modernize", "pkg/a/b/flagged.py:modernize"} <= landed
    assert r.manifesto_laws == []
    assert "manifesto_laws" not in r.to_dict()


# --------------------------------------------------------------------------- #
# 5. ON + empty manifesto (no .apex history) -> byte-identical                 #
# --------------------------------------------------------------------------- #

def test_manifesto_aware_on_empty_manifesto_noop(tmp_path):
    _flagged_and_safe(tmp_path)  # no .apex history at all
    r = compile_objective(str(tmp_path), objective="modernize", apply=True,
                          verify=False, manifesto_aware=True)
    landed = {s.target for s in r.steps}
    assert {"pkg/safe.py:modernize", "pkg/a/b/flagged.py:modernize"} <= landed
    assert r.manifesto_laws == []
    assert r.avoided == []
    assert "manifesto_laws" not in r.to_dict()


# --------------------------------------------------------------------------- #
# 6. render_compile_markdown discloses fired laws                             #
# --------------------------------------------------------------------------- #

def test_render_discloses_fired_laws():
    result = CompileResult(objective="modernize", fitness_start=2.0, fitness_end=1.0,
                           applied=True,
                           manifesto_laws=["`app/bad.py` — 4/5 rolled back "
                                           "(reliability 0.2)"])
    md = render_compile_markdown(result)
    assert "Manifesto laws fired" in md
    assert "`app/bad.py` — 4/5 rolled back (reliability 0.2)" in md


def test_render_omits_manifesto_section_when_no_laws_fired():
    result = CompileResult(objective="modernize", fitness_start=1.0, fitness_end=1.0,
                           applied=True)
    assert "Manifesto laws fired" not in render_compile_markdown(result)


# --------------------------------------------------------------------------- #
# 7/8. The two surfaces can never disagree: law-export API matches the render  #
# --------------------------------------------------------------------------- #

def test_avoid_law_signatures_matches_manifesto_lines(tmp_path):
    _flagged_and_safe(tmp_path)
    _rolled_back_modernize_on_deep_module(tmp_path)
    manifesto = derive_manifesto(str(tmp_path))
    assert set(avoid_law_signatures(str(tmp_path)).values()) == set(manifesto["avoid"])
    assert manifesto["avoid"]  # the fixture actually produced a law


def test_avoid_law_signatures_empty_without_history(tmp_path):
    assert avoid_law_signatures(str(tmp_path)) == {}


def test_fragile_law_modules_matches_render(tmp_path):
    _fragile_history(tmp_path, "app/bad.py")
    manifesto = derive_manifesto(str(tmp_path))
    md = render_manifesto_markdown(manifesto)
    laws = fragile_law_modules(str(tmp_path))
    assert laws  # the fixture actually produced a law
    for module, bullet in laws.items():
        assert f"- {bullet}" in md
        assert module in bullet


def test_fragile_law_modules_empty_without_history(tmp_path):
    assert fragile_law_modules(str(tmp_path)) == {}


# --------------------------------------------------------------------------- #
# 9. Determinism                                                               #
# --------------------------------------------------------------------------- #

def test_manifesto_aware_determinism(tmp_path):
    _flagged_and_safe(tmp_path)
    _rolled_back_modernize_on_deep_module(tmp_path)
    r1 = compile_objective(str(tmp_path), objective="modernize", apply=False,
                           verify=False, manifesto_aware=True)
    r2 = compile_objective(str(tmp_path), objective="modernize", apply=False,
                           verify=False, manifesto_aware=True)
    assert r1.to_dict() == r2.to_dict()


# --------------------------------------------------------------------------- #
# 10. CLI flag                                                                 #
# --------------------------------------------------------------------------- #

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command")
    register_parsers(sub)
    return p


def test_cli_manifesto_flag_parses():
    ns = _parser().parse_args(["develop", "--manifesto"])
    assert ns.manifesto_aware is True


def test_cli_manifesto_flag_defaults_off():
    ns = _parser().parse_args(["develop"])
    assert ns.manifesto_aware is False


# --------------------------------------------------------------------------- #
# 11. CLI honesty: --manifesto WARNS (never silently drops) on every develop  #
#     mode not yet wired to `compile_objective`'s manifesto gate              #
# --------------------------------------------------------------------------- #

def _dev_args(argv: list[str]) -> argparse.Namespace:
    return _parser().parse_args(["develop", *argv])


def test_manifesto_warns_on_session(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_autonomy, "_develop_session", lambda *a, **k: 0)
    ns = _dev_args(["session", "--manifesto", "--target", str(tmp_path)])
    assert cli_autonomy.cmd_develop(ns) == 0
    assert "not wired into `develop session`" in capsys.readouterr().err


def test_manifesto_warns_on_chain(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_autonomy, "_develop_chain", lambda *a, **k: 0)
    ns = _dev_args(["--chain", "modernize", "--manifesto", "--target", str(tmp_path)])
    assert cli_autonomy.cmd_develop(ns) == 0
    assert "not wired into `develop --chain`" in capsys.readouterr().err


def test_manifesto_warns_on_goals_fixpoint(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_autonomy, "_develop_fixpoint", lambda *a, **k: 0)
    ns = _dev_args(["--goals", "modernize", "--fixpoint", "--manifesto",
                    "--target", str(tmp_path)])
    assert cli_autonomy.cmd_develop(ns) == 0
    assert "not wired into `develop --goals --fixpoint`" in capsys.readouterr().err


def test_manifesto_warns_on_goal(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_autonomy, "_develop_goal", lambda *a, **k: 0)
    ns = _dev_args(["--goal", "tidy", "--manifesto", "--target", str(tmp_path)])
    assert cli_autonomy.cmd_develop(ns) == 0
    assert "not wired into `develop --goal`" in capsys.readouterr().err


def test_manifesto_warns_on_goal_atomic(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_autonomy, "_develop_goal_atomic", lambda *a, **k: 0)
    ns = _dev_args(["--goal", "tidy", "--atomic", "--manifesto",
                    "--target", str(tmp_path)])
    assert cli_autonomy.cmd_develop(ns) == 0
    assert "not wired into `develop --goal`" in capsys.readouterr().err


def test_manifesto_warns_on_all(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_autonomy, "_develop_all", lambda *a, **k: 0)
    ns = _dev_args(["--all", "--manifesto", "--target", str(tmp_path)])
    assert cli_autonomy.cmd_develop(ns) == 0
    assert "not wired into `develop --all`" in capsys.readouterr().err


def test_manifesto_warns_on_multifile(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_autonomy, "_develop_multifile", lambda *a, **k: 0)
    ns = _dev_args(["--multifile", "--manifesto", "--target", str(tmp_path)])
    assert cli_autonomy.cmd_develop(ns) == 0
    assert "not wired into `develop --multifile`" in capsys.readouterr().err


def test_manifesto_warns_on_from_dream(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_autonomy, "_develop_from_dream", lambda *a, **k: 0)
    ns = _dev_args(["--from-dream", "--manifesto", "--target", str(tmp_path)])
    assert cli_autonomy.cmd_develop(ns) == 0
    assert "not wired into `develop --from-dream`" in capsys.readouterr().err


def test_manifesto_no_warning_on_default_objective(tmp_path, monkeypatch, capsys):
    # The ONE path that actually enforces — no warning should ever fire here.
    monkeypatch.setattr(cli_autonomy, "_develop_objective", lambda *a, **k: 0)
    ns = _dev_args(["--manifesto", "--target", str(tmp_path)])
    assert cli_autonomy.cmd_develop(ns) == 0
    assert capsys.readouterr().err == ""


def test_manifesto_no_warning_on_auto(tmp_path, monkeypatch, capsys):
    # The OTHER path that actually enforces — no warning should ever fire here.
    monkeypatch.setattr(cli_autonomy, "_develop_auto", lambda *a, **k: 0)
    ns = _dev_args(["--auto", "--manifesto", "--target", str(tmp_path)])
    assert cli_autonomy.cmd_develop(ns) == 0
    assert capsys.readouterr().err == ""


def test_manifesto_no_warning_without_the_flag(tmp_path, monkeypatch, capsys):
    # Never warn when --manifesto wasn't passed at all — the helper is a pure
    # no-op off, exactly like every other opt-in gate in this feature.
    monkeypatch.setattr(cli_autonomy, "_develop_session", lambda *a, **k: 0)
    ns = _dev_args(["session", "--target", str(tmp_path)])
    assert cli_autonomy.cmd_develop(ns) == 0
    assert capsys.readouterr().err == ""
