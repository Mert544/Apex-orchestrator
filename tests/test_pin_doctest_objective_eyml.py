"""pin-doctest develop objective — LAND a gating test that EXECUTES a function's
unenforced ``>>>`` docstring examples, turning documentation into a contract.

Covers: objective registration / reachability (a facet phrase routes to it and
the facet-map↔registry 1:1 parity invariant still holds); the north-star manifest
classes it CONCRETE with the reverse-tripwire clean; the facet ladder carries the
phrase with the originals still leading; the END-TO-END landing (``apply_rename``
verify=True creates ``tests/test_<stem>_doctest.py`` and the suite stays green);
and every REFUSAL that keeps it honest — red examples (never pin a failing
contract), a ``+SKIP``-only docstring, an ALREADY-ENFORCED symbol (a pinned test,
or the project running ``pytest --doctest-modules``), and a test/fixture input.
Idempotency (a second run is a byte-identical no-op) and determinism (same input
-> same output) are pinned too.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.objectives.pin_doctest import plan_pin_doctest

# A function with two enforceable, currently-GREEN examples and NO test pinning it.
_GREEN = (
    "def double(n):\n"
    '    """Double n.\n\n'
    "    >>> double(3)\n"
    "    6\n"
    "    >>> double(5)\n"
    "    10\n"
    '    """\n'
    "    return n * 2\n"
)


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    return tmp_path


def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


# --- registration / reachability ---------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "pin-doctest" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["pin-doctest"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(
        "the unenforced doctest examples to pin") == "pin-doctest"


def test_facet_reachability_parity_invariant_holds():
    # The standing 1:1 invariant: the facet map reaches EXACTLY the registered
    # objectives. Adding pin-doctest to BOTH sides keeps the equality.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_substring_order_safe():
    # The new key must be neither a substring of, nor contain, any other key
    # (with a different objective) — else the first-match scan would mis-route.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    new = "the unenforced doctest examples to pin"
    keys = list(FACET_OBJECTIVE_MAP)
    assert new in keys
    for other in keys:
        if other == new:
            continue
        assert new not in other, f"{new!r} is a substring of {other!r}"
        assert other not in new, f"{other!r} is a substring of {new!r}"


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "pin-doctest" in buckets["CONCRETE"]
    # No stale manifest name (a name with no live objective) was introduced.
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_worked_examples_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["worked examples"]
    assert "the unenforced doctest examples to pin" in ladder
    assert ladder[0] == "minimal runnable example"  # originals still lead


# --- the plan: a green-but-unenforced function gets pinned --------------------

def test_plan_lands_a_gating_test(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _GREEN)
    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    assert plan.ok
    doc_rel = "tests/test_calc_doctest.py"
    gen = plan.new_contents[doc_rel]
    assert "import doctest" in gen
    assert "importlib.import_module('app.calc')" in gen
    assert "def test_double_doctest():" in gen
    assert "result.failed == 0" in gen
    # The original is captured (existing-or-"") so the engine can roll the create
    # back; here the file did not exist, so the original is the empty string.
    assert plan.originals[doc_rel] == ""
    assert plan.edits_by_file[doc_rel] == 1


def test_generated_test_source_parses(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _GREEN)
    gen = plan_pin_doctest(str(tmp_path), "app/calc.py").new_contents[
        "tests/test_calc_doctest.py"]
    ast.parse(gen)  # gate 2: the generated test source is valid Python


def test_plan_pins_only_qualifying_functions(tmp_path: Path):
    # Three functions: one green+unenforced (pinned), one with NO example
    # (skipped), one whose example is RED (skipped — never pin a failing one).
    src = (
        _GREEN
        + "\ndef plain(x):\n    return x\n"
        + "\ndef wrong(n):\n"
        '    """\n    >>> wrong(2)\n    99\n    >>> wrong(3)\n    99\n    """\n'
        "    return n + 1\n"
    )
    _project(tmp_path, "app/calc.py", src)
    gen = plan_pin_doctest(str(tmp_path), "app/calc.py").new_contents[
        "tests/test_calc_doctest.py"]
    assert "def test_double_doctest():" in gen
    assert "def test_plain_doctest():" not in gen   # no example
    assert "def test_wrong_doctest():" not in gen   # red today


# --- REFUSALS: honest under-claims -------------------------------------------

def test_refuses_red_examples_no_pin(tmp_path: Path):
    # The examples FAIL against the real body today -> never pin a red contract.
    red = _GREEN.replace("return n * 2", "return n * 3")
    _project(tmp_path, "app/calc.py", red)
    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    assert not plan.new_contents
    assert not plan.blockers


def test_refuses_skip_only_docstring(tmp_path: Path):
    # Every example is ``# doctest: +SKIP`` -> no enforceable contract to pin.
    skip = (
        "def double(n):\n"
        '    """\n'
        "    >>> double(3)  # doctest: +SKIP\n"
        "    6\n"
        '    """\n'
        "    return n * 2\n"
    )
    _project(tmp_path, "app/calc.py", skip)
    assert not plan_pin_doctest(str(tmp_path), "app/calc.py").new_contents


def test_refuses_function_with_no_examples(tmp_path: Path):
    _project(tmp_path, "app/calc.py", "def f(x):\n    return x\n")
    assert not plan_pin_doctest(str(tmp_path), "app/calc.py").new_contents


def test_refuses_already_enforced_by_pinned_test(tmp_path: Path):
    # A ``test_*.py`` already imports the module AND references the symbol, so the
    # examples are (effectively) covered — don't land a duplicate gate.
    _project(tmp_path, "app/calc.py", _GREEN)
    _project(tmp_path, "tests/test_calc.py",
             "from app.calc import double\n"
             "def test_d():\n    assert double(2) == 4\n")
    assert not plan_pin_doctest(str(tmp_path), "app/calc.py").new_contents


def test_refuses_when_doctest_modules_configured(tmp_path: Path):
    # The biggest false-negative risk: ``pytest --doctest-modules`` runs EVERY
    # module docstring suite-wide with NO test_*.py reference, so the per-symbol
    # linkage check would miss it. The config scan refuses project-wide.
    _project(tmp_path, "app/calc.py", _GREEN)
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"--doctest-modules\"\n",
        encoding="utf-8")
    assert not plan_pin_doctest(str(tmp_path), "app/calc.py").new_contents


def test_refuses_when_conftest_enables_doctest(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _GREEN)
    (tmp_path / "conftest.py").write_text(
        "# enable doctest collection\ncollect_ignore = []\n", encoding="utf-8")
    assert not plan_pin_doctest(str(tmp_path), "app/calc.py").new_contents


def test_refuses_in_other_config_files(tmp_path: Path):
    # The scan covers pytest.ini / setup.cfg / tox.ini too, not just pyproject.
    for cfg, body in (
        ("pytest.ini", "[pytest]\naddopts = --doctest-modules\n"),
        ("setup.cfg", "[tool:pytest]\naddopts = --doctest-modules\n"),
        ("tox.ini", "[pytest]\naddopts = --doctest-modules\n"),
    ):
        sub = tmp_path / cfg.replace(".", "_")
        _project(sub, "app/calc.py", _GREEN)
        (sub / cfg).write_text(body, encoding="utf-8")
        assert not plan_pin_doctest(str(sub), "app/calc.py").new_contents, cfg


def test_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _GREEN)
    assert not plan_pin_doctest(str(tmp_path), "tests/test_x.py").new_contents


def test_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _GREEN)
    assert not plan_pin_doctest(str(tmp_path), "fixtures/sample.py").new_contents


def test_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_pin_doctest(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- idempotency / determinism -----------------------------------------------

def test_idempotent_second_run_is_a_noop(tmp_path: Path):
    # After the gating test exists, the symbol is now pinned by it -> a second run
    # both sees the byte-identical file AND the new linkage, so it is a no-op.
    _suite_project(tmp_path)
    (tmp_path / "app" / "calc.py").write_text(_GREEN, encoding="utf-8")
    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    doc_rel = "tests/test_calc_doctest.py"
    (tmp_path / doc_rel).write_text(plan.new_contents[doc_rel], encoding="utf-8")
    again = plan_pin_doctest(str(tmp_path), "app/calc.py")
    assert not again.new_contents


def test_deterministic_across_two_runs(tmp_path: Path):
    src = _GREEN + "\ndef triple(n):\n" \
        '    """\n    >>> triple(2)\n    6\n    >>> triple(3)\n    9\n    """\n' \
        "    return n * 3\n"
    _project(tmp_path, "app/calc.py", src)
    one = plan_pin_doctest(str(tmp_path), "app/calc.py").new_contents.get(
        "tests/test_calc_doctest.py")
    two = plan_pin_doctest(str(tmp_path), "app/calc.py").new_contents.get(
        "tests/test_calc_doctest.py")
    assert one is not None and one == two
    # Source order is preserved (double before triple).
    assert one.index("test_double_doctest") < one.index("test_triple_doctest")


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_lands_gating_test_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    (tmp_path / "app" / "calc.py").write_text(_GREEN, encoding="utf-8")
    (tmp_path / "tests" / "test_existing.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")

    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = tmp_path / "tests" / "test_calc_doctest.py"
    assert landed.exists()                       # the new gating test LANDED
    text = landed.read_text(encoding="utf-8")
    assert "def test_double_doctest():" in text
    # The landed test genuinely enforces the examples: it imports the module and
    # asserts zero doctest failures (verified green by the apply gate above).
    assert "result.failed == 0" in text


def test_end_to_end_auto_rollback_when_examples_go_red_under_suite(tmp_path: Path):
    # never-fake-green at the engine level: if the module's body is then made to
    # VIOLATE the examples (so the generated gating test would fail under the
    # suite), the verified apply rolls the create back and leaves no gating-test
    # content on disk. We force this by mutating the body AFTER the plan is built
    # but BEFORE apply, so the gate runs the new test against a now-red contract.
    _suite_project(tmp_path)
    (tmp_path / "app" / "calc.py").write_text(_GREEN, encoding="utf-8")
    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    assert plan.ok  # green at plan time
    # Now break the body so the (about-to-land) gating test fails its examples.
    (tmp_path / "app" / "calc.py").write_text(
        _GREEN.replace("return n * 2", "return n * 3"), encoding="utf-8")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is False
    assert result.get("rolled_back") is True
    # never-fake-green: the file is restored to its pre-change state (it did not
    # exist before, captured as the empty original), so NO gating-test content
    # survives on disk — a red contract is never left pinned.
    landed = tmp_path / "tests" / "test_calc_doctest.py"
    surviving = landed.read_text(encoding="utf-8") if landed.exists() else ""
    assert "def test_double_doctest():" not in surviving
    assert surviving == ""
