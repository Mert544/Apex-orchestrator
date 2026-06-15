"""Schema-field and edge coverage for app.engine.sarif_export.

Pins down the SARIF 2.1.0 envelope fields the GitHub code-scanning ingest
relies on (schema URI, version, driver name/uri/version, uriBaseId), the
per-result property block, multi-finding ordering, and the rule-dedup /
message-variant branches — exercised here with explicit field assertions the
existing suites don't make. Pure function of a ReviewResult; deterministic and
hermetic (no network, no wall-clock, no order-sensitive set asserts).
"""
from __future__ import annotations

from app.engine.diff_review import ReviewFinding, ReviewResult
from app.engine.proof_of_fix import tool_version
from app.engine.sarif_export import _LEVEL, review_to_sarif


def _result(findings: list[ReviewFinding]) -> ReviewResult:
    return ReviewResult(base="HEAD", files_reviewed=1, findings=findings)


# --- top-level envelope fields -----------------------------------------------

def test_envelope_schema_and_version_fields():
    sarif = review_to_sarif(_result([]))
    assert sarif["$schema"] == "https://json.schemastore.org/sarif-2.1.0.json"
    assert sarif["version"] == "2.1.0"
    assert isinstance(sarif["runs"], list) and len(sarif["runs"]) == 1


def test_driver_metadata_fields():
    driver = review_to_sarif(_result([]))["runs"][0]["tool"]["driver"]
    assert driver["name"] == "Apex Orchestrator"
    assert driver["informationUri"] == "https://github.com/Mert544/Apex-orchestrator"
    # version is sourced from proof_of_fix.tool_version() — same value, not hard-coded.
    assert driver["version"] == tool_version()
    assert driver["rules"] == []


# --- per-result location / property block ------------------------------------

def test_result_physical_location_uses_srcroot_base():
    sarif = review_to_sarif(_result([
        ReviewFinding("pkg/sub/mod.py", 42, "security", "high", "boom", False, "eval"),
    ]))
    loc = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "pkg/sub/mod.py"
    assert loc["artifactLocation"]["uriBaseId"] == "%SRCROOT%"
    assert loc["region"]["startLine"] == 42


def test_result_properties_carry_severity_category_autofixable():
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 1, "bug", "medium", "off-by-one", True, "boundary"),
    ]))
    props = sarif["runs"][0]["results"][0]["properties"]
    assert props == {"severity": "medium", "category": "bug", "autoFixable": True}


def test_every_level_table_entry_is_reachable():
    # Drive all three high/medium/low rows of _LEVEL through real findings and
    # confirm the mapping matches the table exactly (error/warning/note).
    findings = [
        ReviewFinding("a.py", 1, "security", "high", "h", False),
        ReviewFinding("a.py", 2, "security", "medium", "m", False),
        ReviewFinding("a.py", 3, "security", "low", "l", False),
    ]
    levels = [r["level"] for r in review_to_sarif(_result(findings))["runs"][0]["results"]]
    assert levels == [_LEVEL["high"], _LEVEL["medium"], _LEVEL["low"]]
    assert levels == ["error", "warning", "note"]


# --- rule list: dedup keeps first, distinct ids stay separate ----------------

def test_distinct_fix_kinds_produce_distinct_rules_sorted():
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 1, "security", "high", "eval", True, "eval"),
        ReviewFinding("a.py", 2, "style", "low", "fstring", True, "fstring-no-placeholder"),
        ReviewFinding("a.py", 3, "docs", "low", "docstring", True, "docstring"),
    ]))
    ids = [r["id"] for r in sarif["runs"][0]["tool"]["driver"]["rules"]]
    assert ids == ["apex/docstring", "apex/eval", "apex/fstring-no-placeholder"]
    # Three findings, three results — dedup only collapses the rules list.
    assert len(sarif["runs"][0]["results"]) == 3


def test_category_only_rule_id_when_fix_kind_blank():
    # fix_kind empty but category present -> rule id is apex/<category> and the
    # rule's properties.category echoes it.
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 1, "refactor", "low", "extract me", False, ""),
    ]))
    rule = sarif["runs"][0]["tool"]["driver"]["rules"][0]
    assert rule["id"] == "apex/refactor"
    assert rule["properties"]["category"] == "refactor"


def test_message_suggestion_text_embeds_old_and_new():
    sarif = review_to_sarif(_result([
        ReviewFinding("a.py", 1, "style", "low", "use is not None", True,
                      "none-comparison", suggestion=("x != None", "x is not None")),
    ]))
    text = sarif["runs"][0]["results"][0]["message"]["text"]
    assert text == ("use is not None Suggested fix: replace `x != None` "
                    "with `x is not None`.")


# --- empty review: a valid, ingestible SARIF with no results -----------------

def test_empty_review_has_well_formed_run_with_no_results():
    run = review_to_sarif(_result([]))["runs"][0]
    assert run["results"] == []
    assert run["tool"]["driver"]["rules"] == []
    # The driver block is still fully populated so the SARIF stays ingestible.
    assert set(run["tool"]["driver"]) >= {"name", "informationUri", "version", "rules"}


def test_export_is_deterministic_for_same_findings():
    findings = [
        ReviewFinding("b.py", 2, "security", "high", "eval", True, "eval"),
        ReviewFinding("a.py", 1, "docs", "low", "doc", False, ""),
    ]
    assert review_to_sarif(_result(findings)) == review_to_sarif(_result(findings))
