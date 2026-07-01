"""add-functools-wraps develop objective — LAND ``@functools.wraps(<callee>)``
on a decorator-factory's inner WRAPPER function that calls its outer's single
parameter but carries no ``wraps`` yet.

Covers: the core transform (detect the outer-tail-returns-nested-wrapper
shape; the plausible-callee scan, including a call buried in a nested
``lambda``; the fresh/no-op ``import functools`` insertion; every REFUSAL —
already-wrapped, ambiguous callee, reassigned/shadowed callee, no single
unambiguous returned wrapper, wrapper not the direct return value, no call at
all, syntax error, test/fixture — plus idempotency and determinism); objective
registration / reachability (a facet phrase routes to it and the facet-map
1:1 parity invariant still holds); the north-star manifest classes it
CONCRETE with the reverse-tripwire clean; the facet ladder carries the phrase
with the originals still leading; the END-TO-END landing against the real
in-repo target shape (``apply_rename`` verify=True rewrites the module in
place and the suite stays green); and the must-refuse-on-the-soundness-corpus
ambiguous-callee fixture.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.functools_wraps import add_functools_wraps, wrappable_functions
from app.execution.objectives.add_functools_wraps import plan_add_functools_wraps

_PHRASE = "the wrapper missing functools.wraps"

# The in-repo target shape this objective was built against
# (app/agents/swarm_stability.py's with_timeout): decorator's inner wrapper
# calls func TWICE (an attribute read + a call inside a nested lambda) but
# carries no @functools.wraps.
_DECORATOR_FACTORY = (
    "from typing import Any, Callable\n"
    "\n"
    "\n"
    "def with_timeout(timeout: float, default_return: Any = None):\n"
    '    """Decorator to add timeout to a function."""\n'
    "\n"
    "    def decorator(func: Callable) -> Callable:\n"
    "        def wrapper(*args, **kwargs):\n"
    "            try:\n"
    "                return run(func.__name__, lambda: func(*args, **kwargs), timeout)\n"
    "            except TimeoutError:\n"
    "                return default_return\n"
    "\n"
    "        return wrapper\n"
    "\n"
    "    return decorator\n"
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


# --- the core transform: detection -------------------------------------------

def test_detects_the_in_repo_target_shape():
    assert wrappable_functions(_DECORATOR_FACTORY) == ["wrapper"]


def test_detects_plain_call_callee():
    src = (
        "def factory(func):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == ["wrapper"]


def test_detects_callee_call_inside_nested_lambda():
    src = (
        "def factory(func):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        run = lambda: func(*args, **kwargs)\n"
        "        return run()\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == ["wrapper"]


def test_no_call_to_any_param_is_honest_noop():
    src = (
        "def factory(func):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return None\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == []


def test_attribute_only_use_never_called_is_not_plausible():
    src = (
        "def factory(func):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func.__name__\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == []


def test_async_wrapper_is_detected():
    src = (
        "def factory(func):\n"
        "    async def wrapper(*args, **kwargs):\n"
        "        return await func(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == ["wrapper"]


def test_plain_non_decorator_function_is_noop():
    assert wrappable_functions("def plain(x):\n    return x + 1\n") == []


# --- the core transform: REFUSALS (honest no-ops, non-tautological) ---------

def test_refuses_already_wrapped_dotted():
    src = (
        "import functools\n"
        "\n"
        "def factory(func):\n"
        "    @functools.wraps(func)\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == []


def test_refuses_already_wrapped_bare():
    src = (
        "from functools import wraps\n"
        "\n"
        "def factory(func):\n"
        "    @wraps(func)\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == []


def test_refuses_ambiguous_callee_two_params_called():
    # Non-tautological: WITHOUT the "exactly one called param" check, this would
    # wrongly pick one of the two by accident (list order) and mislabel the wrapper.
    src = (
        "def factory(primary, fallback):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        try:\n"
        "            return primary(*args, **kwargs)\n"
        "        except Exception:\n"
        "            return fallback(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == []


def test_refuses_callee_reassigned_before_wrapper():
    # Non-tautological: WITHOUT the rebind scan, this would emit
    # @functools.wraps(func) even though `func` was rebound to something else
    # before the wrapper closes over it — wrapping the WRONG object.
    src = (
        "def factory(func):\n"
        "    func = lambda *a: None\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == []


def test_refuses_callee_shadowed_by_for_loop_before_wrapper():
    src = (
        "def factory(func):\n"
        "    for func in [func]:\n"
        "        pass\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == []


def test_allows_callee_reassigned_after_wrapper_closes():
    # A rebind AFTER the wrapper def does not affect what the wrapper already
    # closed over — still landable.
    src = (
        "def factory(func):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    func = None\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == ["wrapper"]


def test_refuses_duplicate_named_nested_defs():
    # Non-tautological: two DIFFERENT wrapper bodies share the name "wrapper";
    # without the uniqueness check the wrong one's identity could be assumed.
    src = (
        "def factory(func):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return 1\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == []


def test_refuses_wrapper_not_direct_return_value():
    src = (
        "def factory(func):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper()\n"
    )
    assert wrappable_functions(src) == []


def test_refuses_empty_return():
    src = (
        "def factory(func):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return\n"
    )
    assert wrappable_functions(src) == []


def test_refuses_kwonly_only_callee():
    # Scope: only REGULAR (posonly/positional-or-keyword) params are eligible
    # callees for this first cut.
    src = (
        "def factory(*, func):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == []


def test_refuses_syntax_error():
    assert add_functools_wraps("def (:\n") is None


# --- the core transform: rewrite ---------------------------------------------

def test_lands_decorator_and_import():
    out = add_functools_wraps(_DECORATOR_FACTORY)
    assert out is not None
    assert "@functools.wraps(func)\n        def wrapper(" in out
    assert "import functools" in out
    ast.parse(out)  # never lands broken Python


def test_does_not_duplicate_existing_functools_import():
    src = (
        "import functools\n"
        "\n"
        "\n"
        "def factory(func):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    out = add_functools_wraps(src)
    assert out is not None
    assert out.count("import functools") == 1
    assert "@functools.wraps(func)" in out


def test_ensures_import_when_only_from_functools_import_present():
    # `from functools import total_ordering` does NOT satisfy the dotted
    # `@functools.wraps` spelling, so a bare `import functools` is still added
    # (a second, harmless import line — never corrupting).
    src = (
        "from functools import total_ordering\n"
        "\n"
        "\n"
        "def factory(func):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    out = add_functools_wraps(src)
    assert out is not None
    assert "import functools\n" in out
    assert "@functools.wraps(func)" in out


# --- idempotency / determinism -----------------------------------------------

def test_idempotent_second_run_is_noop():
    once = add_functools_wraps(_DECORATOR_FACTORY)
    assert once is not None
    assert add_functools_wraps(once) is None  # 2nd run = byte-identical no-op


def test_deterministic_across_two_runs():
    a = add_functools_wraps(_DECORATOR_FACTORY)
    b = add_functools_wraps(_DECORATOR_FACTORY)
    assert a is not None and a == b


def test_preserves_trailing_newline_absence():
    src = (
        "def factory(func):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper"
    )
    out = add_functools_wraps(src)
    assert out is not None and not out.endswith("\n")


# --- registration / reachability ---------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "add-functools-wraps" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["add-functools-wraps"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_total_is_ninety_three():
    from app.engine.objective_compiler import available_objectives

    assert len(set(available_objectives())) == 93


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "add-functools-wraps"


def test_facet_reachability_parity_invariant_holds():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_substring_order_safe():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    keys = list(FACET_OBJECTIVE_MAP)
    assert _PHRASE in keys
    for other in keys:
        if other == _PHRASE:
            continue
        assert _PHRASE not in other, f"{_PHRASE!r} is a substring of {other!r}"
        assert other not in _PHRASE, f"{other!r} is a substring of {_PHRASE!r}"


def test_manifest_classes_it_concrete_and_reverse_tripwire_clean():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert "add-functools-wraps" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []


def test_parity_concrete_count_is_forty_eight():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())
    assert len(buckets["CONCRETE"]) == 48  # add-functools-wraps (48th CONCRETE)


def test_facet_phrase_lives_in_the_signatures_and_types_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert _PHRASE in ladder
    assert ladder[0] == "parameter meanings"  # originals still lead
    assert ladder[ladder.index(_PHRASE) - 1] == "annotations to make lazy with a future import"


def test_parity_move_value_tier_matches_future_annotations():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    assert move_value("add_functools_wraps") == 0.32
    assert move_value("add_functools_wraps") == move_value("add_from_future_annotations")
    assert objective_value("add-functools-wraps") == 0.32
    assert objective_value("add-functools-wraps") != DEFAULT_VALUE


def test_parity_soundness_strategy_present():
    from app.engine.objective_compiler import available_objectives
    from app.engine.soundness_audit import (
        SOUNDNESS_STRATEGY,
        strategy_completeness,
        strategy_subset_of_registry,
    )

    sc = strategy_completeness(available_objectives())  # raises if undeclared
    assert "add-functools-wraps" in sc
    assert SOUNDNESS_STRATEGY["add-functools-wraps"]
    assert strategy_subset_of_registry() == []


# --- the plan: an unwrapped decorator-factory wrapper gets @functools.wraps --

def test_plan_lands_wraps_and_import(tmp_path: Path):
    _project(tmp_path, "app/deco.py", _DECORATOR_FACTORY)
    plan = plan_add_functools_wraps(str(tmp_path), "app/deco.py")
    assert plan.ok
    new = plan.new_contents["app/deco.py"]
    assert "@functools.wraps(func)" in new
    assert "import functools" in new
    assert plan.originals["app/deco.py"] == _DECORATOR_FACTORY
    assert plan.edits_by_file["app/deco.py"] == 1


def test_plan_refuses_module_without_qualifying_shape(tmp_path: Path):
    _project(tmp_path, "app/plain.py", "def f(x):\n    return x + 1\n")
    assert not plan_add_functools_wraps(
        str(tmp_path), "app/plain.py").new_contents


def test_plan_refuses_already_wrapped(tmp_path: Path):
    src = (
        "import functools\n"
        "\n"
        "def factory(func):\n"
        "    @functools.wraps(func)\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    _project(tmp_path, "app/deco.py", src)
    assert not plan_add_functools_wraps(
        str(tmp_path), "app/deco.py").new_contents


def test_plan_refuses_ambiguous_callee(tmp_path: Path):
    src = (
        "def factory(primary, fallback):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        try:\n"
        "            return primary(*args, **kwargs)\n"
        "        except Exception:\n"
        "            return fallback(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    _project(tmp_path, "app/deco.py", src)
    assert not plan_add_functools_wraps(
        str(tmp_path), "app/deco.py").new_contents


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _DECORATOR_FACTORY)
    assert not plan_add_functools_wraps(
        str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _DECORATOR_FACTORY)
    assert not plan_add_functools_wraps(
        str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_add_functools_wraps(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ---------------

def test_end_to_end_lands_wraps_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    src = (
        "def make_logger(func):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper\n"
        "\n"
        "\n"
        "@make_logger\n"
        "def add(a, b):\n"
        '    """Add two numbers."""\n'
        "    return a + b\n"
    )
    (tmp_path / "app" / "deco.py").write_text(src, encoding="utf-8")
    (tmp_path / "tests" / "test_deco.py").write_text(
        "from app.deco import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n"
        "def test_name_preserved():\n    assert add.__name__ == 'add'\n",
        encoding="utf-8")

    plan = plan_add_functools_wraps(str(tmp_path), "app/deco.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "deco.py").read_text(encoding="utf-8")
    assert "@functools.wraps(func)" in landed  # the decorator LANDED
    assert "import functools" in landed
    # Behaviour preserved: add still works AND now reports its real __name__ —
    # proven green by the apply gate running the suite above (including the
    # NEW __name__ assertion the metadata fix now satisfies).
    assert "def wrapper(*args, **kwargs):" in landed


# --- must-refuse on the soundness-corpus fixture (the ambiguous-callee trap) --

def test_refuses_on_ambiguous_callee_corpus_shape():
    # The standing soundness corpus carries an ambiguous-callee trap shape: a
    # decorator wrapper calling BOTH of its outer's parameters. add-functools-wraps
    # MUST refuse it — no single callee is provable. Non-tautological: WITHOUT the
    # exactly-one-called-param check, one of the two would be picked arbitrarily.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), only={"add-functools-wraps"})
    cells = corpus.get("add-functools-wraps", {})
    assert cells, "add-functools-wraps should be swept in the light corpus path"
    assert cells.get("functools_wraps_ambiguous_callee") == "refused"


def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []
