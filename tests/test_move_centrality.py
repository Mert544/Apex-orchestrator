"""Tests for the centrality (blast-radius) move tiebreak.

The signal (``app/engine/move_centrality.py::module_in_degrees``) turns the
dependency graph's already-populated ``in_degree`` into a ``module -> fan-in``
map keyed exactly like a move's target module. ``_ordered_candidates`` consumes
it as a SUBORDINATE key on the value-aware path so a capped ``--max-steps`` budget
banks the highest-blast-radius move first.

The round-21 invariant the denetçi attacks: centrality affects apply ORDER, so it
is OPT-IN. With ``centrality=None`` (the DEFAULT, and the only state a non-value-
aware run can reach) the sort key collapses to a constant ``0`` and the order is
BYTE-IDENTICAL to before the signal existed. These pin both the new behavior and
that byte-identity, plus the flat-graph no-op and full determinism.

The candidate naming is ALPHABET-ADVERSARIAL on purpose: the high-fan-in module
``app/zzz_hub.py`` sorts ALPHABETICALLY LAST, so centrality genuinely FLIPS the
order (hub-before-leaf) rather than agreeing with the alphabet by luck — and the
byte-identical-default cases prove the leaf (``app/aaa_leaf.py``) leads when the
signal is absent.
"""

from __future__ import annotations

import textwrap

from app.engine.idea_memory import IdeaMemory
from app.engine.move_centrality import module_in_degrees
from app.engine.objective_compiler import Move, _ordered_candidates


# --- fixtures ---------------------------------------------------------------

def _write(root, rel, body=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def _move(rel: str) -> Move:
    """A cover-gaps-shaped move targeting ``rel`` (target = ``{rel}:cover-gaps``,
    so ``_move_module`` yields ``rel``). The plan thunk is never invoked here —
    ordering reads only ``operator``/``target``."""
    return Move(operator="cover_gaps", target=f"{rel}:cover-gaps",
                description=f"cover {rel}", build_plan=lambda: None)


def _generator(rels):
    """A ``generate(root)`` that yields one cover-gaps move per ``rel``, in the
    given order — the same shape ``cover_gaps.moves`` emits."""
    moves = [_move(r) for r in rels]
    return lambda _root: list(moves)


def _ordered(rels, *, value_aware, centrality):
    """``_ordered_candidates`` over ``rels`` with a fresh neutral memory, returning
    the resulting target-module order."""
    memory = IdeaMemory()  # no samples -> sequence_factor is a constant 1.0
    out = _ordered_candidates(_generator(rels), "/proj", None, memory, "",
                              value_aware=value_aware, centrality=centrality)
    return [m.target.split(":", 1)[0] for m in out]


# ``aaa_leaf`` sorts FIRST alphabetically but has zero fan-in; ``zzz_hub`` sorts
# LAST but is the 5-importer hub. So centrality must FLIP them on the value-aware
# path, while its absence leaves them in pure m.target (alphabetical) order.
HUB = "app/zzz_hub.py"
LEAF = "app/aaa_leaf.py"
_CANDIDATES = [LEAF, HUB]   # generation/alphabetical order: leaf, then hub
_FAN_IN = {HUB: 5, LEAF: 0}  # hub: 5 importers, leaf: 0


# --- 1. centrality supplied -> hub (high fan-in) sorts first ----------------

def test_centrality_supplied_hub_first():
    # The alphabet would keep the leaf first; centrality OVERRIDES that tie to
    # land the 5-importer hub before the 0-importer leaf.
    order = _ordered(_CANDIDATES, value_aware=True, centrality=_FAN_IN)
    assert order == [HUB, LEAF], "the 5-importer hub must land before the leaf"


# --- 2. centrality=None -> EXACTLY alphabetical (byte-identical guard) -------

def test_centrality_none_is_alphabetical():
    # The regression guard: with no centrality the value-aware order is the same
    # pure-alphabetical (m.target) order it was before the signal existed.
    order = _ordered(_CANDIDATES, value_aware=True, centrality=None)
    assert order == [LEAF, HUB], "without centrality, order is m.target alphabetical"


def test_centrality_ignored_off_value_aware_path():
    # Even if a map is somehow threaded in, the non-value-aware path never
    # consults it: order stays the historical sequence-credit order (here a no-op
    # neutral, so generation order is preserved unchanged).
    order = _ordered(_CANDIDATES, value_aware=False, centrality=_FAN_IN)
    assert order == _CANDIDATES, "off the value-aware path centrality is inert"


# --- 3. equal in-degree -> falls through to the m.target tiebreak -----------

def test_equal_in_degree_falls_back_to_target():
    flat = {HUB: 2, LEAF: 2}  # tie on fan-in
    order = _ordered(_CANDIDATES, value_aware=True, centrality=flat)
    assert order == [LEAF, HUB], "tied fan-in must defer to m.target alphabetical"


# --- 4. determinism: same input -> same order, 100x -------------------------

def test_determinism_100x():
    first = _ordered(_CANDIDATES, value_aware=True, centrality=_FAN_IN)
    for _ in range(100):
        assert _ordered(_CANDIDATES, value_aware=True, centrality=_FAN_IN) == first


# --- 5. flat graph (all in-degree 0) -> byte-identical to today -------------

def test_flat_graph_is_byte_identical():
    flat = {HUB: 0, LEAF: 0}  # the in-degree map of a no-import repo
    with_flat = _ordered(_CANDIDATES, value_aware=True, centrality=flat)
    baseline = _ordered(_CANDIDATES, value_aware=True, centrality=None)
    assert with_flat == baseline == [LEAF, HUB]


def test_missing_module_treated_as_zero():
    # A move whose module is absent from the map (e.g. a target the graph could
    # not resolve) reads as fan-in 0 via ``.get(..., 0)`` — never a KeyError — so
    # it sorts with the leaves and defers to the m.target tiebreak.
    order = _ordered(_CANDIDATES, value_aware=True, centrality={HUB: 4})
    assert order == [HUB, LEAF]  # hub=4 beats leaf=missing(0)


# --- module_in_degrees over a real tree -------------------------------------

def _pkg(root):
    _write(root, "pyproject.toml", "[project]\nname='demo'\nversion='0'\n")
    _write(root, "app/__init__.py")
    return root


def test_module_in_degrees_counts_real_fan_in(tmp_path):
    # hub.py imported by 5 modules; leaf.py imported by none.
    _pkg(tmp_path)
    _write(tmp_path, "app/hub.py", "VALUE = 1\n")
    _write(tmp_path, "app/leaf.py", "VALUE = 2\n")
    for i in range(5):
        _write(tmp_path, f"app/importer_{i}.py", "from app.hub import VALUE\n")

    degrees = module_in_degrees(tmp_path)
    assert degrees["app/hub.py"] == 5
    assert degrees["app/leaf.py"] == 0


def test_module_in_degrees_drives_real_order(tmp_path):
    # End-to-end: a real fan-in map flips an alphabet-adversarial pair. The hub
    # ``zzz_hub`` (5 importers) sorts AFTER ``aaa_leaf`` alphabetically, yet
    # centrality lands it first.
    _pkg(tmp_path)
    _write(tmp_path, "app/zzz_hub.py", "VALUE = 1\n")
    _write(tmp_path, "app/aaa_leaf.py", "VALUE = 2\n")
    for i in range(5):
        _write(tmp_path, f"app/imp_{i}.py", "from app.zzz_hub import VALUE\n")

    degrees = module_in_degrees(tmp_path)
    assert degrees["app/zzz_hub.py"] == 5
    order = _ordered([LEAF, HUB], value_aware=True, centrality=degrees)
    assert order == [HUB, LEAF], "the real-graph hub must land before the leaf"


def test_module_in_degrees_flat_repo_is_zero(tmp_path):
    # A repo whose modules import nothing internal -> every in-degree is 0.
    _pkg(tmp_path)
    _write(tmp_path, "app/a.py", "VALUE = 1\n")
    _write(tmp_path, "app/b.py", "VALUE = 2\n")
    degrees = module_in_degrees(tmp_path)
    assert all(d == 0 for d in degrees.values())
    # Such a map is a no-op tiebreak -> byte-identical to centrality=None.
    rels = ["app/a.py", "app/b.py"]
    assert (_ordered(rels, value_aware=True, centrality=degrees)
            == _ordered(rels, value_aware=True, centrality=None))


def test_module_in_degrees_empty_tree(tmp_path):
    # No Python modules at all -> empty map (in-degree of nothing), no crash.
    (tmp_path / "README.md").write_text("nothing here\n", encoding="utf-8")
    assert module_in_degrees(tmp_path) == {}
