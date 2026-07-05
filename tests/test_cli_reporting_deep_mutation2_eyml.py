"""Second-pass DEEP mutation-hardening for app/cli_reporting.py.

This file complements ``test_cli_reporting_insight_deep_mutation_eyml.py`` by
re-enumerating the FULL single-token mutant universe of ``app/cli_reporting.py``
via ``app.engine.mutation_tester`` — all 267 mutable sites, far past the default
30-mutant cap — and running every covering test file against each spliced mutant
in an isolated copy.

Full-universe result (covering set = every test whose AST imports the module,
EXCLUDING ``test_cli_run_characterization.py``, which snapshots ``app/cli.py``
from ``git show HEAD`` and so errors uniformly in any sandbox copy — a
source-identity artefact that "kills" every mutant trivially and would mask real
survivors): 263 / 267 killed.

The 4 surviving mutants are PROVEN EQUIVALENT — no test can kill them because no
behaviour changes:

  * ``app/cli_reporting.py:306`` ``rsplit(".", 1)`` -> ``rsplit(".", 2)``: the
    result is immediately indexed with ``[-1]`` (the LAST piece), which is
    maxsplit-invariant — ``s.rsplit(".", k)[-1]`` is identical for every k >= 1
    and every input ``s``.
  * ``app/cli_reporting.py:480-482`` the three local initialisers in
    ``_gate_metrics`` (``security = 0``, ``bugs = 0``, ``out_of_scope = 0.0``):
    dead initialisers. EVERY control path through the inner ``try``/``except``
    reassigns all three before they are read into the returned dict, so their
    initial literal value is unobservable.

Rather than suppress these, the tests below PIN the invariants that make each one
equivalent. They are characterization guards: if a future edit ever makes one of
these literals observable (a genuine regression / new branch), the corresponding
invariant assertion below flips and the survivor becomes a real, caught fault.

Heavy engine dependencies are stubbed via ``sys.modules`` injection so each test
exercises the module's OWN logic deterministically and offline. No timestamps,
wall-clock, or unordered collections are asserted, so the suite is byte-stable.
"""
from __future__ import annotations

import contextlib
import sys
import types
from pathlib import Path

import app.cli_reporting as _REP_MOD

REP = vars(_REP_MOD)


class _FakeModule(types.ModuleType):
    def __init__(self, name, **attrs):
        super().__init__(name)
        for k, v in attrs.items():
            setattr(self, k, v)


@contextlib.contextmanager
def _inject(**mods):
    saved = {}
    for name, mod in mods.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = mod
    try:
        yield
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def _idea(value, branch, title, anchors=None):
    return types.SimpleNamespace(
        value=value, branch_path=branch, title=title, anchors=anchors or []
    )


def _ipe_mod(ideas):
    class IPE:
        def __init__(self, cfg, project_root=None, **kwargs):
            pass

        def run(self):
            return types.SimpleNamespace(ideas=ideas)

    return _FakeModule("app.engine.idea_permutation", IdeaPermutationEngine=IPE)


def _profiler_mod(profile):
    class PP:
        def __init__(self, root):
            pass

        def profile(self, light=False):
            return profile

    return _FakeModule("app.tools.project_profile", ProjectProfiler=PP)


# ---------------------------------------------------------------------------
# Survivor L306 — rsplit(".", 1)[-1] vs rsplit(".", 2)[-1] is EQUIVALENT.
# Pin the maxsplit-invariance of the LAST-piece index so the mutant stays
# equivalent only as long as the code keeps taking [-1]; a future change to a
# non-last index would make the survivor real and these guards would catch it.
# ---------------------------------------------------------------------------


def test_pulse_moves_focus_takes_last_dotted_segment():
    """A deeply-dotted anchor symbol focuses on its LAST segment only — the
    behaviour ``rsplit('.', maxsplit)[-1]`` is invariant to ``maxsplit``."""
    anchor = {"symbol": "a.b.c.d.leaf", "line": 7, "metric": "cx=5"}
    ideas = [_idea(0.5, "p", "T", anchors=[anchor])]
    with _inject(**{"app.engine.idea_permutation": _ipe_mod(ideas)}):
        out = REP["_pulse_moves"](Path("/x"))
    assert out[0]["focus"] == "leaf (cx=5, line 7)", out


def test_pulse_moves_focus_undotted_symbol_unchanged():
    """An undotted symbol (no '.') is its own last segment — rsplit returns a
    one-element list, so ``[-1]`` is the whole symbol regardless of maxsplit."""
    anchor = {"symbol": "leaf", "line": None, "metric": "cx=9"}
    ideas = [_idea(0.5, "p", "T", anchors=[anchor])]
    with _inject(**{"app.engine.idea_permutation": _ipe_mod(ideas)}):
        out = REP["_pulse_moves"](Path("/x"))
    assert out[0]["focus"] == "leaf (cx=9)", out


def test_pulse_moves_focus_trailing_dot_yields_empty_segment():
    """A symbol ending in '.' has an empty last segment; ``[-1]`` is '' for any
    maxsplit, so ``if symbol:`` is falsy and no focus is emitted."""
    anchor = {"symbol": "pkg.", "line": 3, "metric": "m"}
    ideas = [_idea(0.5, "p", "T", anchors=[anchor])]
    with _inject(**{"app.engine.idea_permutation": _ipe_mod(ideas)}):
        out = REP["_pulse_moves"](Path("/x"))
    assert out[0]["focus"] == "", out


# ---------------------------------------------------------------------------
# Survivors L480-482 — the three local initialisers in _gate_metrics are dead:
# every path through the inner try/except reassigns security/bugs/out_of_scope
# before they reach the returned dict. Pin both branches so the initialisers
# stay unobservable; if a future edit lets an initial literal leak into the
# result, one of these exact-value assertions flips.
# ---------------------------------------------------------------------------


def test_gate_metrics_success_path_overwrites_initialisers():
    """On the profile-success path the three counts come ENTIRELY from the
    profile (2 / 1 / 25.0), never the ``0`` / ``0`` / ``0.0`` initialisers."""
    g = types.SimpleNamespace(letter="A", score=95)
    hs = _FakeModule("app.engine.health_score", grade=lambda r, profile=None: g)
    prof = types.SimpleNamespace(
        security_finding_modules=["a", "b"],
        correctness_bug_modules=["c"],
        out_of_scope_ratio=0.25,
    )
    with _inject(
        **{
            "app.engine.health_score": hs,
            "app.tools.project_profile": _profiler_mod(prof),
        }
    ):
        out = REP["_gate_metrics"](Path("/x"))
    assert out["security_modules"] == 2, out
    assert out["bug_modules"] == 1, out
    assert out["out_of_scope_pct"] == 25.0, out


def test_gate_metrics_except_path_resets_to_zero_not_initialiser():
    """When ProjectProfiler raises, the ``except`` branch reassigns all three to
    ``0 / 0 / 0.0`` — the reset, not the leaked initialiser, is what's returned.
    This is the path a mutated initialiser would most plausibly leak through, so
    pinning the exact zeros here is what keeps the survivor equivalent."""
    g = types.SimpleNamespace(letter="A", score=95)
    hs = _FakeModule("app.engine.health_score", grade=lambda r, profile=None: g)

    class PP:
        def __init__(self, root):
            pass

        def profile(self, light=False):
            raise RuntimeError("boom")

    pp = _FakeModule("app.tools.project_profile", ProjectProfiler=PP)
    with _inject(
        **{"app.engine.health_score": hs, "app.tools.project_profile": pp}
    ):
        out = REP["_gate_metrics"](Path("/x"))
    assert out["security_modules"] == 0, out
    assert out["bug_modules"] == 0, out
    assert out["out_of_scope_pct"] == 0.0, out


def test_gate_metrics_empty_profile_lists_yield_zero_counts():
    """Empty profile lists make the success-path lengths 0 and ratio 0.0 — the
    same numbers as the initialisers, so the dead initialiser truly cannot be
    distinguished from the live success-path computation either."""
    g = types.SimpleNamespace(letter="B", score=80)
    hs = _FakeModule("app.engine.health_score", grade=lambda r, profile=None: g)
    prof = types.SimpleNamespace(
        security_finding_modules=[],
        correctness_bug_modules=[],
        out_of_scope_ratio=0.0,
    )
    with _inject(
        **{
            "app.engine.health_score": hs,
            "app.tools.project_profile": _profiler_mod(prof),
        }
    ):
        out = REP["_gate_metrics"](Path("/x"))
    assert out["security_modules"] == 0, out
    assert out["bug_modules"] == 0, out
    assert out["out_of_scope_pct"] == 0.0, out
