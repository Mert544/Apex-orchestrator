"""Characterization tests pinning the refactored ``evidence_for_facet`` and
``_compute_cohesion`` to their pre-decomposition behaviour.

Each case was captured from the original implementations (snapshotted via
``git show HEAD:<file>`` before the helper-extraction refactor) and the
refactored functions must reproduce them byte-identically. These exercise every
branch: each facet rule, the signature/length/complexity fallbacks, the
no-match path, and every cohesion outcome (single, same-package, import-connected,
no-prefix-scattered, and fractional-prefix).
"""

from __future__ import annotations

from app.engine.blast_radius import _compute_cohesion
from app.engine.facet_evidence import evidence_for_facet


class _Node:
    def __init__(self, imports):
        self.imports = list(imports)


def _graph(edges):
    return {k: _Node(v) for k, v in edges.items()}


# --- evidence_for_facet -----------------------------------------------------

_NO_MATCH_SOURCE = "def f(): pass"
_SIG_SOURCE = "def g(a, b, c, d, e, f, g): pass"
_LONG_SOURCE = "def big():\n" + "\n".join("    x%d = 1" % i for i in range(70))  # spans 71 lines
_CX_SOURCE = "def h():\n" + "\n".join("    if x%d:\n        y" % i for i in range(12))


def test_no_match_returns_empty():
    assert evidence_for_facet(_NO_MATCH_SOURCE, "nothing matches", 2) == []


def test_signature_fallback():
    out = evidence_for_facet(_SIG_SOURCE, "parameterize", 2)
    assert out == [(1, "g() takes 7 parameters")]


def test_length_fallback():
    out = evidence_for_facet(_LONG_SOURCE, "smaller unit", 2)
    assert out == [(1, "big() spans 71 lines")]


def test_complexity_fallback():
    out = evidence_for_facet(_CX_SOURCE, "deep nesting", 5)
    assert out == [(1, "h() has 12 branches")]


def test_limit_caps_output():
    assert evidence_for_facet(_CX_SOURCE, "deep nesting", 0) == []
    assert len(evidence_for_facet(_CX_SOURCE, "deep nesting", 1)) <= 1


def test_syntax_error_source_is_safe():
    assert evidence_for_facet("def f(\n", "parameterize", 2) == []
    assert evidence_for_facet("def f(\n", "smaller unit", 2) == []


def test_phrase_case_insensitive():
    lower = evidence_for_facet(_SIG_SOURCE, "interface", 2)
    upper = evidence_for_facet(_SIG_SOURCE, "INTERFACE", 2)
    assert lower == upper


def test_deterministic_repeat():
    a = evidence_for_facet(_CX_SOURCE, "edge case", 2)
    b = evidence_for_facet(_CX_SOURCE, "edge case", 2)
    assert a == b


# --- _compute_cohesion ------------------------------------------------------

_COHESION_CASES = [
    # (changed, graph_edges, expected_to_dict)
    ([], {}, {"score": 1.0, "label": "tight",
             "reason": "single changed module is cohesive by definition"}),
    (["app/a.py"], {}, {"score": 1.0, "label": "tight",
                        "reason": "single changed module is cohesive by definition"}),
    (["app/x.py", "app/y.py"], {},
     {"score": 1.0, "label": "tight", "reason": "all 2 modules share package 'app'"}),
    (["x.py", "y.py"], {},
     {"score": 1.0, "label": "tight", "reason": "all 2 modules share package '(repo root)'"}),
    (["app/a.py", "lib/b.py"], {"app/a.py": ["lib/b.py"], "lib/b.py": []},
     {"score": 1.0, "label": "tight",
      "reason": "all 2 changed modules are connected by direct imports"}),
    (["app/a.py", "lib/b.py", "core/c.py"],
     {"app/a.py": ["lib/b.py"], "lib/b.py": ["core/c.py"], "core/c.py": []},
     {"score": 1.0, "label": "tight",
      "reason": "all 3 changed modules are connected by direct imports"}),
    (["app/a.py", "lib/b.py"], {"app/a.py": ["lib/b.py"]},
     {"score": 1.0, "label": "tight",
      "reason": "all 2 changed modules are connected by direct imports"}),
    (["app/a.py", "lib/b.py"], {},
     {"score": 0.0, "label": "scattered",
      "reason": "2 modules share no common package and no import edges (possible scope creep)"}),
    (["app/engine/a.py", "app/engineering/b.py"], {},
     {"score": 1.0, "label": "tight", "reason": "2/2 modules under common prefix 'app'"}),
    # Mixed sub-packages sharing only the 'app' component: every package is
    # under that prefix by construction, so the prefix branch scores 1.0.
    (["app/engine/a.py", "app/engine/b.py", "app/engine/c.py", "app/tools/d.py"], {},
     {"score": 1.0, "label": "tight", "reason": "4/4 modules under common prefix 'app'"}),
    (["app/engine/a.py", "app/tools/b.py", "app/tools/c.py", "app/tools/d.py"], {},
     {"score": 1.0, "label": "tight", "reason": "4/4 modules under common prefix 'app'"}),
    # No shared leading component anywhere -> empty prefix -> scattered 0.0.
    (["app/a.py", "lib/b.py", "core/c.py", "x/d.py"], {},
     {"score": 0.0, "label": "scattered",
      "reason": "4 modules share no common package and no import edges (possible scope creep)"}),
    # partial chain: not fully import-connected, falls through to prefix.
    (["app/a.py", "lib/b.py", "core/c.py"],
     {"app/a.py": ["lib/b.py"], "lib/b.py": [], "core/c.py": []},
     {"score": 0.0, "label": "scattered",
      "reason": "3 modules share no common package and no import edges (possible scope creep)"}),
]


def test_cohesion_characterization():
    for changed, edges, expected in _COHESION_CASES:
        got = _compute_cohesion(changed, _graph(edges)).to_dict()
        assert got == expected, (changed, edges, got, expected)


def test_cohesion_deterministic():
    changed = ["z/m.py", "a/n.py"]
    g = _graph({"z/m.py": ["a/n.py"], "a/n.py": []})
    assert _compute_cohesion(changed, g).to_dict() == _compute_cohesion(changed, g).to_dict()
