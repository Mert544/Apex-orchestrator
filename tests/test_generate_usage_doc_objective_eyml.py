"""generate-usage-doc develop objective — deterministic USAGE.md from the API.

Covers: objective registration/reachability + facet route + the standing
facet-reachability invariant; public-API collection (functions/classes, signatures
with annotations/defaults, ``self`` dropped, ``_private``/``__all__`` honoured);
docstring summary + ``>>>`` example extraction; the doctest ORACLE keeping only
green examples and OMITTING a failing one; ``USAGE.md`` rendering and its
``python`` code blocks parsing; no-public-API refusal; determinism across two
runs; idempotence (regenerate → byte-identical no-op); refusal of test/fixture
packages; and the end-to-end gated apply that lands a real ``USAGE.md`` whose
examples execute green.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.doctest_oracle import verify_examples
from app.execution.objectives.generate_usage_doc import plan_generate_usage_doc
from app.execution.usage_doc import (
    collect_public_api,
    plan_usage_text,
    python_code_blocks,
    render_usage_markdown,
)


# --- registration / reachability ---------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "generate-usage-doc" in set(available_objectives())


def test_objective_spec_is_callable_and_expensive():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["generate-usage-doc"]
    assert callable(spec.fitness) and callable(spec.moves)
    # The fitness scan imports each package in a subprocess (the doctest oracle),
    # so it is flagged expensive — the fast plan/ascend board skips it.
    assert spec.expensive is True


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(
        "the package usage doc to generate") == "generate-usage-doc"


def test_facet_reachability_invariant_holds():
    # The standing invariant: every objective the facet map names is a real
    # available objective. Adding generate-usage-doc to both sides keeps the
    # facet values a SUBSET of the available objectives (other in-flight objectives
    # may extend the available set, so subset rather than strict equality).
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    available = set(available_objectives())
    assert "generate-usage-doc" in available
    assert "generate-usage-doc" in set(FACET_OBJECTIVE_MAP.values())


# --- helpers -----------------------------------------------------------------

def _pkg(tmp_path: Path, files: dict[str, str], init: str = "") -> Path:
    pkg = tmp_path / "mathy"
    pkg.mkdir()
    for name, src in files.items():
        (pkg / name).write_text(src, encoding="utf-8")
    (pkg / "__init__.py").write_text(init, encoding="utf-8")
    return pkg


_CORE = (
    '"""Core helpers."""\n\n\n'
    "def add(a: int, b: int = 0) -> int:\n"
    '    """Return the sum of two integers.\n\n'
    "    >>> add(2, 3)\n    5\n"
    '    """\n'
    "    return a + b\n\n\n"
    "class Counter:\n"
    '    """A simple counter.\n\n'
    "    >>> Counter(10).value\n    10\n"
    '    """\n\n'
    "    def __init__(self, value: int = 0):\n"
    "        self.value = value\n\n\n"
    "def _private():\n    return 1\n"
)


# --- public-API collection (pure AST) ----------------------------------------

def test_collects_functions_and_classes_with_signatures(tmp_path: Path):
    pkg = _pkg(tmp_path, {"core.py": _CORE})
    api = collect_public_api(pkg, "")
    names = [s.name for s in api]
    assert names == ["Counter", "add"]  # sorted, _private excluded
    by_name = {s.name: s for s in api}
    assert by_name["add"].signature == "(a: int, b: int = 0) -> int"
    assert by_name["add"].kind == "function"
    # The class signature drops `self` and reads its __init__ params.
    assert by_name["Counter"].signature == "(value: int = 0)"
    assert by_name["Counter"].kind == "class"


def test_summary_and_examples_extracted(tmp_path: Path):
    pkg = _pkg(tmp_path, {"core.py": _CORE})
    by_name = {s.name: s for s in collect_public_api(pkg, "")}
    assert by_name["add"].summary == "Return the sum of two integers."
    assert by_name["add"].examples == [">>> add(2, 3)\n5"]
    assert by_name["Counter"].examples == [">>> Counter(10).value\n10"]


def test_all_restricts_the_surface(tmp_path: Path):
    pkg = _pkg(tmp_path, {"core.py": _CORE}, init="__all__ = ['add']\n")
    api = collect_public_api(pkg, "__all__ = ['add']\n")
    assert [s.name for s in api] == ["add"]  # Counter excluded by __all__


def test_first_sorted_module_wins_on_collision(tmp_path: Path):
    pkg = _pkg(tmp_path, {
        "aaa.py": "def shared():\n    '''From aaa.'''\n    return 1\n",
        "bbb.py": "def shared():\n    '''From bbb.'''\n    return 2\n",
    })
    api = collect_public_api(pkg, "")
    assert len(api) == 1 and api[0].module == "aaa"  # sorted-first wins, no dup


def test_unparseable_module_contributes_nothing(tmp_path: Path):
    pkg = _pkg(tmp_path, {
        "ok.py": "def good():\n    '''Good.'''\n    return 1\n",
        "bad.py": "def (:\n",
    })
    assert [s.name for s in collect_public_api(pkg, "")] == ["good"]


# --- rendering / refusal -----------------------------------------------------

def test_render_none_when_no_public_api():
    assert render_usage_markdown("mathy", []) is None


def test_render_lists_each_symbol_sorted(tmp_path: Path):
    pkg = _pkg(tmp_path, {"core.py": _CORE})
    api = collect_public_api(pkg, "")
    # Trust every example (no oracle): both example blocks appear.
    md = render_usage_markdown("mathy", api, verified_examples=None)
    assert md is not None
    assert md.index("`Counter(value: int = 0)`") < md.index("`add(")  # sorted
    assert "Return the sum of two integers." in md
    assert "```python\n>>> add(2, 3)\n5\n```" in md


def test_unverified_examples_are_omitted(tmp_path: Path):
    pkg = _pkg(tmp_path, {"core.py": _CORE})
    api = collect_public_api(pkg, "")
    # Only `add` is verified -> Counter's example block must be dropped.
    md = render_usage_markdown("mathy", api, verified_examples={"add"})
    assert ">>> add(2, 3)" in md
    assert ">>> Counter(10).value" not in md
    # Counter is still listed (header + summary), just without a code block.
    assert "`Counter(value: int = 0)`" in md and "A simple counter." in md


def test_code_blocks_extractor(tmp_path: Path):
    md = "# t\n\n```python\n>>> add(1, 2)\n3\n```\n\ntext\n"
    assert python_code_blocks(md) == [">>> add(1, 2)\n3"]


# --- the doctest oracle: keep green, drop failing ----------------------------

def test_oracle_keeps_green_and_drops_failing(tmp_path: Path):
    _pkg(tmp_path, {
        "core.py": (
            "def good(x):\n    '''Good.\n\n    >>> good(2)\n    2\n    '''\n    return x\n\n"
            "def bad(x):\n    '''Bad.\n\n    >>> bad(1)\n    999\n    '''\n    return x\n"
        ),
    }, init="from .core import bad, good\n")
    verified = verify_examples(str(tmp_path), "mathy/__init__.py", {
        "good": [">>> good(2)\n2"],
        "bad": [">>> bad(1)\n999"],
    })
    assert verified == {"good"}  # the wrong-output example is not claimed


def test_oracle_empty_payload_is_empty_set(tmp_path: Path):
    _pkg(tmp_path, {"core.py": "def f():\n    return 1\n"},
         init="from .core import f\n")
    assert verify_examples(str(tmp_path), "mathy/__init__.py", {}) == set()


def test_oracle_refuses_when_package_cannot_import(tmp_path: Path):
    _pkg(tmp_path, {"core.py": "def f():\n    return 1\n"},
         init="raise RuntimeError('boom')\n")
    assert verify_examples(str(tmp_path), "mathy/__init__.py",
                           {"f": [">>> f()\n1"]}) == set()


# --- plan layer: lands a doc, refuses, idempotent ----------------------------

def test_plan_lands_usage_doc(tmp_path: Path):
    _pkg(tmp_path, {"core.py": _CORE}, init="from .core import Counter, add\n")
    plan = plan_generate_usage_doc(str(tmp_path), "mathy/__init__.py")
    md = plan.new_contents["mathy/USAGE.md"]
    assert "`add(a: int, b: int = 0) -> int`" in md
    assert ">>> add(2, 3)" in md            # verified example kept
    assert ">>> Counter(10).value" in md    # verified example kept
    assert "_private" not in md


def test_plan_refuses_package_with_no_public_api(tmp_path: Path):
    _pkg(tmp_path, {"core.py": "def _hidden():\n    return 0\n"})
    plan = plan_generate_usage_doc(str(tmp_path), "mathy/__init__.py")
    assert not plan.new_contents and not plan.blockers


def test_plan_refuses_test_package(tmp_path: Path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "helper.py").write_text(
        "def helper():\n    '''Help.'''\n    return 1\n", encoding="utf-8")
    (tests / "__init__.py").write_text("", encoding="utf-8")
    plan = plan_generate_usage_doc(str(tmp_path), "tests/__init__.py")
    assert not plan.new_contents


def test_plan_is_idempotent_after_apply(tmp_path: Path):
    _pkg(tmp_path, {"core.py": _CORE}, init="from .core import Counter, add\n")
    rel = "mathy/__init__.py"
    plan = plan_generate_usage_doc(str(tmp_path), rel)
    doc_rel = "mathy/USAGE.md"
    (tmp_path / doc_rel).write_text(plan.new_contents[doc_rel], encoding="utf-8")
    again = plan_generate_usage_doc(str(tmp_path), rel)
    assert not again.new_contents  # re-running lands nothing (byte-identical)


def test_plan_is_deterministic_across_two_runs(tmp_path: Path):
    _pkg(tmp_path, {"core.py": _CORE}, init="from .core import Counter, add\n")
    a, _ = plan_usage_text(str(tmp_path), "mathy/__init__.py", verified_examples=set())
    b, _ = plan_usage_text(str(tmp_path), "mathy/__init__.py", verified_examples=set())
    assert a == b and a is not None


# --- end-to-end: gated apply lands USAGE.md, examples are green --------------

def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_end_to_end_lands_usage_doc(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    pkg = tmp_path / "app" / "mathy"
    pkg.mkdir()
    (pkg / "core.py").write_text(_CORE, encoding="utf-8")
    (pkg / "__init__.py").write_text(
        "from .core import Counter, add\n", encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="generate-usage-doc",
                               apply=True, verify=True)
    assert result.steps and result.steps[0].verified is True

    doc = (pkg / "USAGE.md").read_text()
    assert "`add(a: int, b: int = 0) -> int`" in doc
    assert ">>> add(2, 3)" in doc
    assert python_code_blocks(doc)  # the doc carries runnable example blocks

    # The headline proof: every ``>>>`` example in the LANDED doc runs green
    # against the real package — verified in a clean subprocess (the oracle), so
    # the host process's own `app` package cannot shadow the tmp package.
    examples = {block.split()[1].split("(")[0]: [block]
                for block in python_code_blocks(doc)}
    verified = verify_examples(str(tmp_path), "app/mathy/__init__.py", examples)
    assert verified == set(examples)  # every block in the doc executes green


def test_end_to_end_noop_on_already_generated(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    pkg = tmp_path / "app" / "mathy"
    pkg.mkdir()
    (pkg / "core.py").write_text(_CORE, encoding="utf-8")
    (pkg / "__init__.py").write_text(
        "from .core import Counter, add\n", encoding="utf-8")
    # Generate once.
    plan = plan_generate_usage_doc(str(tmp_path), "app/mathy/__init__.py")
    (pkg / "USAGE.md").write_text(
        plan.new_contents["app/mathy/USAGE.md"], encoding="utf-8")
    before = (pkg / "USAGE.md").read_text()

    result = compile_objective(str(tmp_path), objective="generate-usage-doc",
                               apply=True, verify=True)
    assert not result.steps  # nothing landed
    assert (pkg / "USAGE.md").read_text() == before  # byte-identical no-op
