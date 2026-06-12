"""The evidence-grounded fractal: facets verify their concern in the real AST."""

from __future__ import annotations

from app.engine.facet_evidence import evidence_for_facet


def test_validation_facet_finds_injection_sinks():
    src = "import os\ndef login(p):\n    return os.system(p)\n"
    ev = evidence_for_facet(src, "input validation")
    assert ev and ev[0][0] == 3
    assert "os.system" in ev[0][1]


def test_error_handling_facet_finds_weak_handlers():
    src = "def f():\n    try:\n        g()\n    except:\n        pass\n"
    ev = evidence_for_facet(src, "error handling")
    assert any(line == 4 for line, _ in ev)
    assert any("except" in d for _, d in ev)


def test_timeout_facet_finds_unbounded_network_calls():
    src = "import requests\ndef get(u):\n    return requests.get(u)\n"
    ev = evidence_for_facet(src, "resource limits")
    assert ev and "timeout" in ev[0][1]


def test_complexity_facets_name_the_actual_function():
    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(10))
    src = f"def gnarly(x):\n{branches}\n    return -1\n"
    ev = evidence_for_facet(src, "edge cases")
    assert ev and "gnarly()" in ev[0][1]


def test_clean_code_yields_honest_hypotheses():
    # No findings -> no evidence: the facet remains a hypothesis, never a
    # fabricated observation.
    clean = "def ok(x):\n    return x + 1\n"
    for phrase in ("input validation", "error handling", "resource limits",
                   "secret handling", "dead code"):
        assert evidence_for_facet(clean, phrase) == []


def test_evidence_is_deterministic_ordered_and_capped():
    src = (
        "import os\n"
        "def a(p):\n    return os.system(p)\n"
        "def b(p):\n    return os.system(p)\n"
        "def c(p):\n    return os.system(p)\n"
    )
    ev1 = evidence_for_facet(src, "input validation")
    ev2 = evidence_for_facet(src, "input validation")
    assert ev1 == ev2                       # deterministic
    assert len(ev1) == 2                    # capped
    assert ev1[0][0] < ev1[1][0]            # ordered by line


def test_engine_facets_carry_evidence_and_outrank_hypotheses(tmp_path):
    from app.engine.idea_permutation import IdeaPermutationEngine, render_markdown
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text(
        "import os\ndef login(p):\n    try:\n        return os.system(p)\n"
        "    except:\n        pass\n"
    )
    rep = IdeaPermutationEngine(
        {"max_total_ideas": 200, "max_idea_depth": 1, "breadth": 4,
         "fractal_facets": True, "facet_depth": 2, "facets_per_idea": 3},
        tmp_path,
    ).run()
    facets = [i for i in rep.ideas if i.kind == "facet"]
    backed = [f for f in facets if any(s.startswith("evidence:") for s in f.source_facts)]
    hypo = [f for f in facets if not any(s.startswith("evidence:") for s in f.source_facts)]
    assert backed, "expected at least one evidence-backed facet"
    assert hypo, "clean concerns must stay hypotheses"
    # The spike follows evidence: verified concerns average higher value.
    avg = lambda xs: sum(x.value for x in xs) / len(xs)  # noqa: E731
    assert avg(backed) > avg(hypo)
    # Evidence is rendered as proof under the facet; the rationale narrates it.
    md = render_markdown(rep)
    assert "📌" in md
    assert any("verified in the code" in f.rationale for f in backed)
