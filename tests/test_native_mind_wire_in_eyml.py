"""Wire-in of the native intelligence (``app.engine.native_synth``) into the
deterministic ``stub_synthesis`` candidate path — the opt-in ``APEX_NATIVE_MIND``
lane.

Pins the amended-North-Star contract: with the lane DISABLED the candidate list
is byte-identical to the zero-token template core (nothing native is even
imported); with it ENABLED, a body learned from the project's OWN proven
functions is PROPOSED after the fixed templates and still passes the SAME
never-fake-green gate — so Apex can finish a stub no fixed template covers, yet
never lands anything unverified.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.execution.stub_synthesis import (
    _native_mind_sources,
    _ordered_candidates,
    find_stub_functions,
    synthesize_expr_from_witnesses,
)


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")


@pytest.fixture()
def clamp_project(tmp_path: Path) -> Path:
    """A project whose own ``clamp`` is a 3-arg body the fixed templates lack, and
    a stub ``bound`` pinned (by tests) to that exact behaviour."""
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/lib.py", "def clamp(v, lo, hi):\n    return max(lo, min(v, hi))\n")
    _write(tmp_path, "pkg/bound.py", "def bound(a, b, c):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_bound.py", """
        from pkg.bound import bound

        def test_mid():
            assert bound(5, 0, 10) == 5

        def test_low():
            assert bound(-3, 0, 10) == 0

        def test_high():
            assert bound(99, 0, 10) == 10
        """)
    return tmp_path


@pytest.fixture(autouse=True)
def _clean_native_cache():
    """The corpus loader is process-cached; clear it around every test so an env
    flip is honoured and no per-root corpus leaks between cases."""
    _native_mind_sources.cache_clear()
    yield
    _native_mind_sources.cache_clear()


def _stub(root: Path):
    src = (root / "pkg" / "bound.py").read_text(encoding="utf-8")
    return src, find_stub_functions(src)[0]


def test_disabled_is_byte_identical(clamp_project, monkeypatch):
    """With the lane OFF the candidate list carries ZERO native-mind entries — the
    output is the template core, unchanged."""
    monkeypatch.delenv("APEX_NATIVE_MIND", raising=False)
    _, stub = _stub(clamp_project)
    cands = _ordered_candidates(clamp_project, ["tests/test_bound.py"], stub)
    assert all(not label.startswith("native-mind:") for label, _ in cands)


def test_enabled_surfaces_learned_candidate(clamp_project, monkeypatch):
    """With the lane ON, the project's own ``clamp`` is learned and adapted to the
    stub's params (positionally: ``max(b, min(a, c))``), appended after the fixed
    templates."""
    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _, stub = _stub(clamp_project)
    cands = _ordered_candidates(clamp_project, ["tests/test_bound.py"], stub)
    native = [(label, expr) for label, expr in cands if label.startswith("native-mind:")]
    assert ("native-mind:clamp", "max(b, min(a, c))") in native


def test_enabled_appends_after_templates(clamp_project, monkeypatch):
    """Ordering invariant: a native-mind candidate never precedes a fixed template
    (a template still takes priority; the learned body ranks below it)."""
    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _, stub = _stub(clamp_project)
    labels = [label for label, _ in _ordered_candidates(
        clamp_project, ["tests/test_bound.py"], stub)]
    first_native = next(i for i, la in enumerate(labels) if la.startswith("native-mind:"))
    assert all(not la.startswith("native-mind:") for la in labels[:first_native])


def test_lands_a_stub_no_fixed_template_covers(clamp_project, monkeypatch):
    """End-to-end, gated: OFF the 3-arg clamp is unsynthesizable (no template
    fits) so Apex refuses; ON the learned body verifies against every pinned test
    and lands. The gate — not the proposal — decides, so nothing lands unverified."""
    _, stub = _stub(clamp_project)

    monkeypatch.delenv("APEX_NATIVE_MIND", raising=False)
    _native_mind_sources.cache_clear()
    assert synthesize_expr_from_witnesses(
        clamp_project, ["tests/test_bound.py"], stub) is None

    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _native_mind_sources.cache_clear()
    assert synthesize_expr_from_witnesses(
        clamp_project, ["tests/test_bound.py"], stub) == "max(b, min(a, c))"


def test_wrong_learned_body_is_refused_by_the_gate(tmp_path, monkeypatch):
    """A learned body that does NOT satisfy the stub's tests lands NOTHING even
    with the lane ON — never-fake-green holds through the wire-in."""
    _write(tmp_path, "pkg/__init__.py", "")
    # The only 3-arg exemplar is a SUM — wrong for a clamp contract.
    _write(tmp_path, "pkg/lib.py", "def add3(x, y, z):\n    return x + y + z\n")
    _write(tmp_path, "pkg/bound.py", "def bound(a, b, c):\n    raise NotImplementedError\n")
    _write(tmp_path, "tests/test_bound.py", """
        from pkg.bound import bound

        def test_mid():
            assert bound(5, 0, 10) == 5

        def test_high():
            assert bound(99, 0, 10) == 10
        """)
    src = (tmp_path / "pkg" / "bound.py").read_text(encoding="utf-8")
    stub = find_stub_functions(src)[0]
    monkeypatch.setenv("APEX_NATIVE_MIND", "1")
    _native_mind_sources.cache_clear()
    # add3 adapts to a+b+c; it does NOT satisfy the clamp witnesses -> refused.
    assert synthesize_expr_from_witnesses(
        tmp_path, ["tests/test_bound.py"], stub) is None
