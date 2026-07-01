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

The second half (``js_module_fanin`` / ``_move_centrality`` / ``js_centrality``)
covers the JS/TS sibling: ``move_fanin`` was built + tested in
``js_project_profile`` but had ZERO production call site — a JS move's target
never matched the Python-``ast``-only ``centrality`` map, so its blast-radius
tiebreak silently no-opped. These pin the SAME opt-in/byte-identity contract for
the JS lane, plus the language-routing (a Python module never reads the JS map
and vice versa) that makes it safe to supply both maps at once on a mixed repo.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.engine.idea_memory import IdeaMemory
from app.engine.move_centrality import js_module_fanin, module_in_degrees
from app.engine.objective_compiler import (
    Move,
    _is_js_module,
    _move_centrality,
    _ordered_candidates,
)


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


# ============================================================================ #
# JS/TS sibling: _is_js_module / _move_centrality — the language-routing seam  #
# ============================================================================ #

def test_is_js_module_recognizes_js_ts_suffixes():
    for rel in ("src/util.ts", "src/util.tsx", "src/util.js", "src/util.jsx",
               "src/util.mjs", "src/util.cjs"):
        assert _is_js_module(rel), rel


def test_is_js_module_rejects_python_and_other():
    for rel in ("app/util.py", "app/util", "README.md", "app/util.pyi"):
        assert not _is_js_module(rel), rel


def test_move_centrality_python_module_uses_python_map():
    # A .py module is looked up in the Python-ast-only `centrality` map (the
    # ONLY graph a Python module path can ever appear in).
    assert _move_centrality("app/hub.py", {"app/hub.py": 5}, {}) == 5


def test_move_centrality_js_module_falls_through_to_js_map():
    # A .ts module is ABSENT from the Python ast-only graph by construction
    # (real callers never see it there), so it must fall through to
    # js_centrality — the exact bug this wave fixes.
    assert _move_centrality("src/hub.ts", {}, {"src/hub.ts": 5}) == 5
    assert _move_centrality("src/hub.ts", None, {"src/hub.ts": 5}) == 5


def test_move_centrality_js_module_with_no_js_map_is_zero():
    # A JS module with NO js_centrality supplied has no signal to consult (the
    # Python map is, by construction, never asked about a JS path) -> the
    # honest uniform-zero no-op, same as an untracked Python leaf.
    assert _move_centrality("src/hub.ts", {}, None) == 0
    assert _move_centrality("src/hub.ts", None, None) == 0


def test_move_centrality_missing_key_and_no_maps_is_zero():
    assert _move_centrality("app/leaf.py", {}, {}) == 0
    assert _move_centrality("app/leaf.py", None, None) == 0
    assert _move_centrality("src/leaf.ts", {}, {}) == 0


# ============================================================================ #
# JS/TS sibling: js_centrality wired into _ordered_candidates                  #
# ============================================================================ #

JS_HUB = "src/zzz_hub.ts"
JS_LEAF = "src/aaa_leaf.ts"
_JS_CANDIDATES = [JS_LEAF, JS_HUB]  # generation/alphabetical order: leaf, then hub
_JS_FAN_IN = {JS_HUB: 5, JS_LEAF: 0}


def _ordered_js(rels, *, value_aware, js_centrality):
    memory = IdeaMemory()
    out = _ordered_candidates(_generator(rels), "/proj", None, memory, "",
                              value_aware=value_aware, js_centrality=js_centrality)
    return [m.target.split(":", 1)[0] for m in out]


def test_js_centrality_supplied_hub_first():
    # The alphabet would keep the leaf first; js_centrality OVERRIDES that tie to
    # land the 5-importer JS hub before the 0-importer JS leaf — the SAME lift
    # module_in_degrees gives a Python hub, now reaching a JS/TS target.
    order = _ordered_js(_JS_CANDIDATES, value_aware=True, js_centrality=_JS_FAN_IN)
    assert order == [JS_HUB, JS_LEAF], "the 5-importer JS hub must land before the leaf"


def test_js_centrality_none_is_alphabetical():
    # Byte-identical regression guard: with no js_centrality the JS moves sort
    # exactly as they did before this signal existed (pure m.target order).
    order = _ordered_js(_JS_CANDIDATES, value_aware=True, js_centrality=None)
    assert order == [JS_LEAF, JS_HUB]


def test_js_centrality_ignored_off_value_aware_path():
    order = _ordered_js(_JS_CANDIDATES, value_aware=False, js_centrality=_JS_FAN_IN)
    assert order == _JS_CANDIDATES, "off the value-aware path js_centrality is inert"


def test_python_and_js_centrality_coexist_on_a_mixed_repo():
    # A mixed repo's move set carries BOTH a Python hub/leaf pair and a JS
    # hub/leaf pair in one scan; each move consults ONLY the map for its own
    # language, so both blast-radius lifts land in the SAME ordered call.
    py_hub, py_leaf = "app/zzz_hub.py", "app/aaa_leaf.py"
    rels = [py_leaf, py_hub, JS_LEAF, JS_HUB]
    memory = IdeaMemory()
    out = _ordered_candidates(
        _generator(rels), "/proj", None, memory, "", value_aware=True,
        centrality={py_hub: 5, py_leaf: 0}, js_centrality=_JS_FAN_IN)
    order = [m.target.split(":", 1)[0] for m in out]
    # Both hubs (fan-in 5) beat both leaves (fan-in 0); within the fan-in=5 tier
    # and the fan-in=0 tier the final m.target tiebreak decides alphabetically.
    assert order == [py_hub, JS_HUB, py_leaf, JS_LEAF]


def test_js_determinism_100x():
    first = _ordered_js(_JS_CANDIDATES, value_aware=True, js_centrality=_JS_FAN_IN)
    for _ in range(100):
        assert _ordered_js(_JS_CANDIDATES, value_aware=True,
                           js_centrality=_JS_FAN_IN) == first


# ============================================================================ #
# js_module_fanin — the memoized JS/TS project-fanin accessor                  #
# ============================================================================ #

def _node_ok() -> bool:
    """True when ``node`` is on PATH and the global ``typescript`` resolves —
    mirrors ``test_js_project_profile_eyml``'s own gate, so the driver-spawning
    tests here run under the same environment condition (and skip honestly,
    never silently pass, when node/typescript are unavailable)."""
    import shutil

    from app.execution.js.js_tool import global_node_modules

    if shutil.which("node") is None:
        return False
    nm = global_node_modules()
    return bool(nm) and (Path(nm) / "typescript").is_dir()


_needs_node = pytest.mark.skipif(
    not _node_ok(), reason="node + global typescript not available")


def _write_js(root: Path, rel: str, src: str) -> None:
    (root / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(src, encoding="utf-8")


def _js_pkg(root: Path) -> None:
    (root / "package.json").write_text(
        '{ "name": "demo", "version": "1.0.0" }\n', encoding="utf-8")


@_needs_node
def test_js_module_fanin_counts_real_fan_in(tmp_path):
    # hub.ts imported by 5 modules; leaf.ts imported by none — the JS mirror of
    # test_module_in_degrees_counts_real_fan_in.
    _js_pkg(tmp_path)
    _write_js(tmp_path, "src/hub.ts", "export const VALUE = 1;\n")
    _write_js(tmp_path, "src/leaf.ts", "export const VALUE = 2;\n")
    for i in range(5):
        _write_js(tmp_path, f"src/importer_{i}.ts",
                  'import { VALUE } from "./hub";\n')

    fanin = js_module_fanin(tmp_path)
    assert fanin.get("src/hub.ts") == 5
    assert fanin.get("src/leaf.ts", 0) == 0


@_needs_node
def test_js_module_fanin_drives_real_order(tmp_path):
    # End-to-end: a REAL fan-in map (through the driver, not a hand-built dict)
    # flips an alphabet-adversarial JS pair via _ordered_candidates — the JS
    # mirror of test_module_in_degrees_drives_real_order.
    _js_pkg(tmp_path)
    _write_js(tmp_path, "src/zzz_hub.ts", "export const VALUE = 1;\n")
    _write_js(tmp_path, "src/aaa_leaf.ts", "export const VALUE = 2;\n")
    for i in range(5):
        _write_js(tmp_path, f"src/imp_{i}.ts",
                  'import { VALUE } from "./zzz_hub";\n')

    fanin = js_module_fanin(tmp_path)
    assert fanin.get("src/zzz_hub.ts") == 5
    order = _ordered_js(["src/aaa_leaf.ts", "src/zzz_hub.ts"],
                        value_aware=True, js_centrality=fanin)
    assert order == ["src/zzz_hub.ts", "src/aaa_leaf.ts"], \
        "the real-driver-graph JS hub must land before the leaf"


def test_js_module_fanin_non_js_project_is_empty(tmp_path):
    # No package.json at all -> the profiler's own graceful-empty gate returns
    # {} WITHOUT spawning the driver (this assertion needs no node/typescript).
    _write(tmp_path, "app/a.py", "VALUE = 1\n")
    assert js_module_fanin(tmp_path) == {}


def test_js_module_fanin_is_memoized_per_root(tmp_path):
    # Two calls for the SAME root return the identical (memoized) dict object
    # (or at minimum equal content) without re-spawning the driver, mirroring
    # module_in_degrees's own per-root memo contract.
    _write(tmp_path, "app/a.py", "VALUE = 1\n")  # non-JS -> the cheap empty path
    first = js_module_fanin(tmp_path)
    second = js_module_fanin(tmp_path)
    assert first == second == {}
