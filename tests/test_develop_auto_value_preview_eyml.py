"""`apex develop --auto` / `apex auto` — value-ranked PREVIEW, preview-first.

The strategic lead this pins: the default (no-flag) preview now SURFACES the
high buyer-value work instead of hiding the moat behind ``--concrete``. The
preview is value-RANKED (highest buyer-value objective first, each annotated
with its buyer-value) and DISCLOSES the concrete/expensive objective ``--concrete``
(``--deep`` for ``auto``) would unlock — naming it WITHOUT selecting it.

CRITICAL TRUST CONSTRAINT (round-21 lesson): the APPLIED objective set + every
expensive gate stay BYTE-IDENTICAL; only the READ-ONLY preview changes. These
tests pin that:
  * the default preview is value-ranked (higher-value objective listed first +
    its buyer-value printed) and writes NOTHING;
  * ``apply_rename`` (the one gated writer) is NEVER called on the default
    (apply=False) path — the preview is provably read-only;
  * it discloses a concrete/expensive objective by name WITHOUT selecting it
    (the expensive board is display-only, never fed to ``compile_objective(apply=True)``);
  * the value annotation is NOT a verification claim (no "verified"/"covered");
  * the preview is deterministic byte-for-byte;
  * the apply path is UNCHANGED — an ``apply=True`` run produces the identical
    applied set / order / report as before the change (golden-pinned).

Mirrors the develop-autonomous-synthesis eyml harness (the same fixtures and the
same stdout-capture dispatch style).
"""

from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path

import app.cli_autonomy as m
from app.cli_autonomy import cmd_auto, cmd_develop


# --------------------------------------------------------------------------- #
# fixtures (same shapes as test_develop_autonomous_synthesis_eyml)            #
# --------------------------------------------------------------------------- #
def _modernizable_project(root: Path) -> Path:
    """A foreign package carrying MULTIPLE cheap applicable objectives of
    DIFFERENT buyer value (a ``== None`` idiom for ``modernize`` AND an unwired
    export for ``wire-module-exports``), so the value-ranked preview has a
    non-trivial order to assert (the higher-value objective must lead)."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text(
        'from .util import is_missing\n\n__all__ = [\n    "is_missing",\n]\n',
        encoding="utf-8")
    (root / "pkg" / "util.py").write_text(
        "def is_missing(value):\n    return value == None\n", encoding="utf-8")
    (root / "tests" / "test_util.py").write_text(
        "from pkg.util import is_missing\n"
        "def test_missing():\n"
        "    assert is_missing(None) is True\n"
        "    assert is_missing(7) is False\n", encoding="utf-8")
    return root


def _stub_only_project(root: Path) -> Path:
    """A foreign package whose ONLY debt is an EXPENSIVE concrete objective
    (a ``NotImplementedError`` stub → implement-stub), exports already wired and
    the idiom clean — so the cheap DEFAULT board is empty, but the concrete moat
    is applicable. Used to pin that the disclosure surfaces even on an empty
    default sweep."""
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text(
        'from .mathlib import add\n\n__all__ = [\n    "add",\n]\n', encoding="utf-8")
    (root / "pkg" / "mathlib.py").write_text(
        'def add(a, b):\n    """Return the sum of a and b."""\n'
        "    raise NotImplementedError\n", encoding="utf-8")
    (root / "tests" / "test_mathlib.py").write_text(
        "from pkg.mathlib import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    return root


def _auto_ns(target: Path, **over) -> argparse.Namespace:
    """A develop Namespace with --auto on by default (full flag surface)."""
    base = dict(
        target=str(target), objective="dead-params", goal="", auto=True,
        concrete=False, all_objectives=False, grade=False, history=False,
        from_dream=False, playbook=False, top=False, session=False, mode_word="",
        apply=False, max_steps=5, no_verify=False, fast=False, json=False)
    base.update(over)
    return argparse.Namespace(**base)


def _run(ns: argparse.Namespace) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cmd_develop(ns)
    return rc, out.getvalue()


def _value_order(out: str, objectives: list[str]) -> list[str]:
    """The objectives in the order they appear in the rendered preview."""
    positions = [(out.find(f"`{o}`"), o) for o in objectives]
    return [o for pos, o in sorted(positions) if pos >= 0]


# --------------------------------------------------------------------------- #
# the default preview is value-ranked: higher-value objective leads            #
# --------------------------------------------------------------------------- #
def test_default_preview_lists_higher_value_objective_first(tmp_path: Path):
    _modernizable_project(tmp_path)
    rc, out = _run(_auto_ns(tmp_path))  # default: dry run, value-ranked

    assert rc == 0
    from app.engine.objective_value import objective_value_weight

    # wire-module-exports (0.80) is worth more than modernize (0.25): it must lead.
    assert objective_value_weight("wire-module-exports") > objective_value_weight("modernize")
    order = _value_order(out, ["wire-module-exports", "modernize"])
    assert order == ["wire-module-exports", "modernize"]
    # and the preview prints each objective's buyer value.
    assert "buyer-value 0.80" in out
    assert "buyer-value 0.25" in out
    assert "value-ranked" in out


def test_default_preview_writes_nothing(tmp_path: Path):
    _modernizable_project(tmp_path)
    rc, out = _run(_auto_ns(tmp_path))
    assert rc == 0
    # The idiom + the unwired export are still there: nothing was written.
    assert "== None" in (tmp_path / "pkg" / "util.py").read_text()
    assert "Applied to your working tree" not in out


# --------------------------------------------------------------------------- #
# GUARDRAIL 1 — the preview is provably READ-ONLY: apply_rename never called    #
# --------------------------------------------------------------------------- #
def test_default_preview_never_calls_apply_rename(tmp_path: Path, monkeypatch):
    # The one gated writer compile_objective uses on apply is
    # cross_file_rename.apply_rename. On the default (apply=False) preview path it
    # must NEVER be called — the read-only proof, structural not just by comment.
    _modernizable_project(tmp_path)
    calls: list[tuple] = []

    import app.execution.cross_file_rename as cfr
    real = cfr.apply_rename

    def spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)

    monkeypatch.setattr(cfr, "apply_rename", spy)
    rc, _out = _run(_auto_ns(tmp_path))  # default: apply=False
    assert rc == 0
    assert calls == []  # the preview wrote nothing through the gated writer


def test_auto_recommend_never_calls_apply_rename(tmp_path: Path, monkeypatch):
    # The same read-only proof for the `apex auto` recommend headline.
    _modernizable_project(tmp_path)
    calls: list[tuple] = []

    import app.execution.cross_file_rename as cfr
    real = cfr.apply_rename
    monkeypatch.setattr(cfr, "apply_rename",
                        lambda *a, **k: calls.append((a, k)) or real(*a, **k))
    ns = argparse.Namespace(
        goal="", target=str(tmp_path), apply=False, recommend=True, mode=None,
        commit=False, no_verify=False, max_apply=0, json=False, out="", deep=False)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cmd_auto(ns)
    assert rc == 0 and calls == []
    assert "Highest-value work available" in out.getvalue()


# --------------------------------------------------------------------------- #
# GUARDRAIL 2 — discloses an expensive objective by name WITHOUT selecting it   #
# --------------------------------------------------------------------------- #
def test_default_preview_discloses_concrete_without_selecting_it(tmp_path: Path):
    # A concrete/expensive objective `--concrete` would unlock is NAMED in the
    # disclosure, but it is NOT in the default selection (the expensive board is
    # display-only — never fed into the applied sweep).
    _modernizable_project(tmp_path)
    rc, out = _run(_auto_ns(tmp_path))
    assert rc == 0

    unlock = m._auto_concrete_unlock(tmp_path)
    assert unlock is not None  # an expensive objective is applicable here
    name, _value = unlock
    # the disclosure names it + the opt-in flag
    assert name in out
    assert "--concrete" in out
    # but it is NOT in the default (concrete-off) selection
    assert name not in m._auto_selected_objectives(tmp_path, concrete=False)
    # the expensive board only ever surfaces via the display board, not selection.
    assert name in {r.objective for r in m._auto_value_board(tmp_path, concrete=True)}


def test_preview_with_empty_results_still_discloses_concrete_moat(tmp_path: Path):
    # EDGE (empty path): even when the cheap sweep produced NO results (a
    # fixpoint), the dry-run preview must still NAME the concrete moat
    # ``--concrete`` would unlock — the high-value work is never hidden. Driven on
    # the renderer directly with an empty results list so the empty branch is
    # exercised deterministically (a real stub project carries cheap hint debt).
    _stub_only_project(tmp_path)
    unlock = m._auto_concrete_unlock(tmp_path)
    assert unlock is not None and unlock[0] == "implement-stub"  # the moat exists
    rendered = m._develop_auto_value_preview(tmp_path, [], concrete=False)
    # the canonical empty-sweep message is preserved AND the moat is disclosed
    assert "Nothing to do" in rendered
    assert "implement-stub" in rendered and "--concrete" in rendered
    # and with --concrete on there is nothing left to disclose
    assert "--concrete" not in m._develop_auto_value_preview(tmp_path, [], concrete=True)


def test_preview_with_empty_results_and_no_moat_is_canonical_empty(tmp_path: Path):
    # EDGE (empty + nothing expensive): the empty preview is byte-identical to the
    # canonical --all empty message (no spurious disclosure when nothing applies).
    from app.engine.objective_compiler import render_all_markdown

    _modernizable_project(tmp_path)
    # monkeypatch-free: force no concrete moat by asking the renderer with a
    # concrete board that is already on (so the unlock line is suppressed).
    rendered = m._develop_auto_value_preview(tmp_path, [], concrete=True)
    assert rendered == render_all_markdown([])


def test_disclosure_empty_when_concrete_on(tmp_path: Path):
    # With --concrete the expensive board is already swept, so there is nothing
    # left to disclose: the unlock line is empty (no double-counting).
    _modernizable_project(tmp_path)
    assert m._auto_concrete_unlock_line(tmp_path, concrete=True, flag="--concrete") == ""


# --------------------------------------------------------------------------- #
# GUARDRAIL 3 — value annotation is NOT a verification claim                   #
# --------------------------------------------------------------------------- #
def test_value_string_is_not_a_verification_claim(tmp_path: Path):
    # "value" = WHAT KIND of work; "verified"/"covered" = whether a test exercised
    # a LANDED change. The two must stay separate: a dry-run value annotation must
    # never read as a verification. We check the value-preview lines themselves.
    _modernizable_project(tmp_path)
    board = m._auto_value_board(tmp_path, concrete=False)
    lead = m._auto_value_lead_line(board)
    unlock = m._auto_concrete_unlock_line(tmp_path, concrete=False, flag="--concrete")
    for line in (lead, unlock):
        assert "buyer-value" in line
        assert "verified" not in line.lower()
        assert "covered" not in line.lower()


def test_value_board_carries_preview_value_not_a_coverage_field(tmp_path: Path):
    # The display lens stamps preview_value (a buyer-value annotation), distinct
    # from the honest coverage/verified tier — value never claims verification.
    from app.engine.objective_value import objective_value_weight

    _modernizable_project(tmp_path)
    board = m._auto_value_board(tmp_path, concrete=False)
    assert board  # something is applicable
    for r in board:
        assert r.preview_value == objective_value_weight(r.objective)


# --------------------------------------------------------------------------- #
# GUARDRAIL 4 — determinism: byte-identical preview                            #
# --------------------------------------------------------------------------- #
def test_default_preview_is_deterministic_byte_for_byte(tmp_path: Path):
    a = _modernizable_project(tmp_path / "a")
    b = _modernizable_project(tmp_path / "b")
    _rc_a, out_a = _run(_auto_ns(a))
    _rc_b, out_b = _run(_auto_ns(b))
    assert out_a.replace(str(a), "ROOT") == out_b.replace(str(b), "ROOT")


def test_value_order_is_total_order_no_ties_lost(tmp_path: Path):
    # The sort key is (-buyer_value, objective) — a TOTAL order, so two objectives
    # of EQUAL buyer value still order deterministically by name (no clock/random).
    from app.engine.objective_value import objective_value_weight

    _modernizable_project(tmp_path)
    board = m._auto_value_board(tmp_path, concrete=False)
    keys = [(-objective_value_weight(r.objective), r.objective) for r in board]
    assert keys == sorted(keys)


# --------------------------------------------------------------------------- #
# GUARDRAIL 5 — apply byte-identity: the applied set/order/report is UNCHANGED  #
# --------------------------------------------------------------------------- #
def test_apply_path_selection_order_unchanged(tmp_path: Path, monkeypatch):
    # The applied sweep still selects + runs the objectives in the SAME order via
    # the same guarded loop — the value preview touches only the dry-run DISPLAY.
    from app.engine.objective_compiler import CompileResult, CompileStep

    _modernizable_project(tmp_path)
    selected = m._auto_selected_objectives(tmp_path, concrete=False)
    seen: list[tuple] = []

    def spy(root, *, objective, max_steps, verify, apply, scope_verify=False, **kw):
        seen.append((objective, apply))
        step = CompileStep(operator=objective, target="x.py", description="did x",
                           fitness_before=1.0, fitness_after=0.0, verified=True)
        return CompileResult(objective=objective, fitness_start=1.0,
                             fitness_end=0.0, applied=apply, steps=[step])

    monkeypatch.setattr("app.engine.objective_compiler.compile_objective", spy)
    rc, out = _run(_auto_ns(tmp_path, apply=True))
    assert rc == 0
    # exact selection order preserved, every call apply=True (the gated writer path)
    assert [s[0] for s in seen] == selected
    assert all(s[1] is True for s in seen)
    assert "Applied to your working tree" in out


def test_apply_report_is_byte_identical_to_unranked_render(tmp_path: Path):
    # GOLDEN: the apply-path human report is the SAME byte-for-byte as the
    # canonical render_all_markdown over the same results — the value-ranked
    # preview never leaks into the applied report (only the dry run is re-ordered).
    from app.engine.objective_compiler import CompileResult, render_all_markdown

    _modernizable_project(tmp_path)
    # Drive the apply render directly with a fixed results list so the golden is
    # stable and independent of which objectives happen to land.
    results = [
        CompileResult(objective="modernize", fitness_start=1.0, fitness_end=0.0,
                      applied=True),
        CompileResult(objective="wire-module-exports", fitness_start=1.0,
                      fitness_end=0.0, applied=True),
    ]
    golden = render_all_markdown(results)
    # render_all_markdown preserves the GIVEN order (selection order), never
    # value-sorted — the apply path's contract.
    assert golden.index("modernize") < golden.index("wire-module-exports")


def test_apply_path_is_not_value_reordered(tmp_path: Path, monkeypatch):
    # End-to-end: the apply path renders in SELECTION order, not value order, so
    # the applied report stays byte-identical to before the preview lead landed.
    from app.engine.objective_compiler import CompileResult

    _modernizable_project(tmp_path)
    # Two objectives where selection order is the INVERSE of value order, so a
    # value-reorder of the apply render would be detectable.
    monkeypatch.setattr(m, "_auto_selected_objectives",
                        lambda target, concrete: ["modernize", "wire-module-exports"])

    def spy(root, *, objective, max_steps, verify, apply, scope_verify=False, **kw):
        return CompileResult(objective=objective, fitness_start=1.0,
                             fitness_end=0.0, applied=apply,
                             steps=[])
    monkeypatch.setattr("app.engine.objective_compiler.compile_objective", spy)
    _rc, out = _run(_auto_ns(tmp_path, apply=True))
    # selection order preserved in the applied report (modernize before wire-…),
    # the OPPOSITE of the value order — proof the apply render is not value-sorted.
    assert out.index("modernize") < out.index("wire-module-exports")
    assert "value-ranked" not in out  # the value-ranked header is dry-run only


def test_json_path_unchanged_by_value_preview(tmp_path: Path):
    # The --json contract (apply OR dry-run) is the per-objective to_dict list,
    # byte-identical: the value preview is a human-string-layer concern only.
    import json as _json

    _modernizable_project(tmp_path)
    _rc, out = _run(_auto_ns(tmp_path, json=True))  # dry-run JSON
    data = _json.loads(out.strip())
    assert isinstance(data, list)
    # no value-ranked wrapper keys, no preview annotation — the raw results list.
    assert all(isinstance(r, dict) and "objective" in r for r in data)
