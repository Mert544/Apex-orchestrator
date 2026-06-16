"""Characterization tests pinning _keyword_scenarios byte-for-byte.

The keyword risk-pattern logic was refactored from a flat series of independent
guards into a folded rule table (_KEYWORD_RULES). These tests freeze the exact
emitted scenario list — order and every field — so any drift fails loudly. The
expectations below are the literal strings the original guards produced.
"""

from __future__ import annotations

from app.engine.counterfactual_generator import CounterfactualGenerator


def _kw(text: str, context: str = "") -> list[str]:
    return CounterfactualGenerator._keyword_scenarios(text, context)


def test_no_match_returns_empty():
    assert _kw("nothing matches here", "no match") == []
    assert _kw("", "") == []


def test_validation_block_exact():
    assert _kw("validation") == [
        "What if an attacker provides None or malformed input?",
        "What if the input is at the maximum possible size?",
        "What if the input contains unicode null bytes or escape sequences?",
    ]


def test_validation_synonyms_each_fire():
    for kw in ("validation", "guard", "check", "sanitize"):
        assert _kw(kw)[0] == "What if an attacker provides None or malformed input?"


def test_eval_and_exec_block():
    expected = [
        "What if the expression string contains '__import__('os').system('rm -rf /')'?",
        "What if a trusted user accidentally passes user-controlled input?",
    ]
    assert _kw("eval") == expected
    assert _kw("exec") == expected


def test_docs_block():
    expected = [
        "What if a new developer joins and cannot understand the function's contract?",
        "What if the function behavior changes but the callers assume the old contract?",
    ]
    assert _kw("docstring") == expected
    assert _kw("documented") == expected


def test_network_block():
    expected = [
        "What if the remote server is down or responds with a 500 error?",
        "What if the connection hangs indefinitely (no timeout)?",
        "What if DNS resolution fails or the network is partitioned?",
    ]
    for kw in ("network", "request", "fetch", "call"):
        assert _kw(kw) == expected


def test_secrets_block():
    expected = [
        "What if the source code is leaked or committed to a public repository?",
        "What if the hardcoded value needs to change across environments (dev/staging/prod)?",
    ]
    for kw in ("hardcoded", "secret", "password"):
        assert _kw(kw) == expected


def test_bare_except_reads_text_or_context():
    expected = [
        "What if a KeyboardInterrupt or SystemExit is silently swallowed?",
        "What if an unrelated bug is masked because all exceptions are caught?",
    ]
    assert _kw("bare except") == expected
    # The ONLY rule that inspects context rather than text.
    assert _kw("", "except:") == expected
    assert _kw("") == []


def test_complex_block():
    expected = [
        "What if a bug exists in line 40 but tests only cover lines 1-10?",
        "What if two developers modify different parts of this function simultaneously?",
    ]
    assert _kw("long") == expected
    assert _kw("complex") == expected


def test_mutable_default_block():
    expected = [
        "What if the function is called twice — does the default list accumulate state?",
    ]
    assert _kw("mutable default") == expected
    assert _kw("default arg") == expected


def test_rule_order_is_table_order_when_all_fire():
    text = (
        "validation guard eval docstring network hardcoded "
        "bare except long mutable default"
    )
    result = _kw(text, "except:")
    # Validation (3), eval (2), docs (2), network (2 distinct + dedup-free),
    # secrets (2), bare-except (2), complex (2), mutable (1) — in table order.
    assert result == [
        "What if an attacker provides None or malformed input?",
        "What if the input is at the maximum possible size?",
        "What if the input contains unicode null bytes or escape sequences?",
        "What if the expression string contains '__import__('os').system('rm -rf /')'?",
        "What if a trusted user accidentally passes user-controlled input?",
        "What if a new developer joins and cannot understand the function's contract?",
        "What if the function behavior changes but the callers assume the old contract?",
        "What if the remote server is down or responds with a 500 error?",
        "What if the connection hangs indefinitely (no timeout)?",
        "What if DNS resolution fails or the network is partitioned?",
        "What if the source code is leaked or committed to a public repository?",
        "What if the hardcoded value needs to change across environments (dev/staging/prod)?",
        "What if a KeyboardInterrupt or SystemExit is silently swallowed?",
        "What if an unrelated bug is masked because all exceptions are caught?",
        "What if a bug exists in line 40 but tests only cover lines 1-10?",
        "What if two developers modify different parts of this function simultaneously?",
        "What if the function is called twice — does the default list accumulate state?",
    ]


def test_determinism_repeated_calls():
    text = "validation network secret"
    first = _kw(text, "except:")
    for _ in range(5):
        assert _kw(text, "except:") == first


def test_generate_end_to_end_uses_keyword_fold():
    gen = CounterfactualGenerator()
    result = gen.generate({"text": "needs validation", "context": ""})
    # generate() caps at 5 scenarios; the validation block leads.
    assert result.scenarios[0] == "What if an attacker provides None or malformed input?"
    assert result.claim_text == "needs validation"
