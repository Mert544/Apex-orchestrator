from __future__ import annotations

from app.engine.counterfactual_generator import CounterfactualGenerator


def test_generates_counterfactual_for_missing_guard():
    gen = CounterfactualGenerator()
    claim = {
        "text": "Function process lacks input validation",
        "context": "def process(data):\n    return eval(data)",
    }
    result = gen.generate(claim)
    assert len(result.scenarios) > 0
    assert any("if" in s.lower() or "without" in s.lower() for s in result.scenarios)


def test_generates_counterfactual_for_eval():
    gen = CounterfactualGenerator()
    claim = {
        "text": "Function parse uses eval()",
        "context": "def parse(expr):\n    return eval(expr)",
    }
    result = gen.generate(claim)
    assert any("expression" in s.lower() or "trusted" in s.lower() for s in result.scenarios)


def test_generates_counterfactual_for_missing_docstring():
    gen = CounterfactualGenerator()
    claim = {
        "text": "Function helper has no docstring",
        "context": "def helper(x):\n    return x * 2",
    }
    result = gen.generate(claim)
    assert len(result.scenarios) >= 1


def test_generates_what_if_scenarios():
    gen = CounterfactualGenerator()
    claim = {
        "text": "No error handling in network call",
        "context": "def fetch(url):\n    return requests.get(url).json()",
    }
    result = gen.generate(claim)
    assert any("timeout" in s.lower() or "disconnect" in s.lower() or "unavailable" in s.lower() for s in result.scenarios)


def test_result_to_dict():
    gen = CounterfactualGenerator()
    result = gen.generate({"text": "Test claim", "context": ""})
    d = result.to_dict()
    assert "scenarios" in d
    assert "insight" in d


def test_insight_generated():
    gen = CounterfactualGenerator()
    claim = {
        "text": "Database password is hardcoded",
        "context": "DB_PASSWORD = 'secret123'",
    }
    result = gen.generate(claim)
    assert result.insight != ""
    assert len(result.scenarios) >= 2


def test_caveats_are_distinct_per_lens():
    # The core "fake reasoning" fix: different development lenses must NOT all
    # collapse onto the same "malformed input" scenario.
    gen = CounterfactualGenerator()
    first = {
        op: gen.generate({"text": f"{op} app/x.py", "operator": op}).scenarios[0]
        for op in ("extend", "harden", "test", "simplify", "document",
                   "integrate", "generalize", "observe")
    }
    assert len(set(first.values())) == 8          # all eight lenses differ
    assert "attacker" in first["harden"].lower()  # harden keeps the security flavor
    assert "regression" in first["test"].lower() or "asserted" in first["test"].lower()
    assert "refactor" in first["simplify"].lower() or "silently change" in first["simplify"].lower()


def test_root_caveats_discriminate_by_fact_label():
    gen = CounterfactualGenerator()
    sec = gen.generate({"text": "harden x", "fact_label": "security-finding"}).scenarios[0]
    unt = gen.generate({"text": "test x", "fact_label": "untested"}).scenarios[0]
    assert sec != unt
    assert "attacker" in sec.lower() or "execute" in sec.lower()


def test_symbol_grounded_scenario_takes_precedence():
    gen = CounterfactualGenerator()
    res = gen.generate({"text": "test x", "operator": "test", "symbol": "crunch"})
    assert "crunch()" in res.scenarios[0]


def test_backward_compatible_without_operator_or_fact():
    # The orchestrator calls generate({"text": ...}) with no operator — the old
    # keyword behavior must still apply.
    gen = CounterfactualGenerator()
    res = gen.generate({"text": "Function lacks input validation guard"})
    assert res.scenarios and any("attacker" in s.lower() or "input" in s.lower()
                                 for s in res.scenarios)


def test_verify_lens_has_its_own_scenario():
    # The `verify` lens gets a correctness/proof-flavored counterfactual, not the
    # generic "malformed input" fallback shared by un-keyed claims.
    gen = CounterfactualGenerator()
    res = gen.generate({"text": "verify app/x.py", "operator": "verify"})
    joined = " ".join(res.scenarios).lower()
    assert "invariant" in joined or "proof" in joined or "precondition" in joined
    # And it differs from a sibling lens (harden) on the same subject.
    harden = gen.generate({"text": "harden app/x.py", "operator": "harden"}).scenarios[0]
    assert res.scenarios[0] != harden
