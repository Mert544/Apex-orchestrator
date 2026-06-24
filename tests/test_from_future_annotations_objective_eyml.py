"""add-from-future-annotations develop objective — LAND ``from __future__ import
annotations`` on a module that USES type annotations but does not yet defer them.

Covers: the core transform (fresh insert after the docstring; widen an existing
``from __future__ import ...`` in place; every REFUSAL — no annotations, already
present, syntax error, test/fixture — plus idempotency and determinism); objective
registration / reachability (a facet phrase routes to it and the facet-map↔registry
1:1 parity invariant still holds); the north-star manifest classes it CONCRETE with
the reverse-tripwire clean; the facet ladder carries the phrase with the originals
still leading; the END-TO-END landing (``apply_rename`` verify=True rewrites the
module in place and the suite stays green); and the never-fake-green ROLLBACK on the
one runtime risk (eager ``get_type_hints()`` going red once annotations are lazy).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.future_annotations import (
    add_future_annotations,
    has_future_annotations,
    module_uses_annotations,
)
from app.execution.objectives.from_future_annotations import (
    plan_from_future_annotations,
)

# A fully-typed module that LACKS the lazy-annotation import.
_TYPED = (
    '"""A typed module."""\n'
    "import os\n"
    "\n"
    "\n"
    "def joinp(a: str, b: str) -> str:\n"
    "    return os.path.join(a, b)\n"
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


# --- the core transform: detection ------------------------------------------

def test_uses_annotations_return_type():
    assert module_uses_annotations("def f(x) -> int:\n    return x\n")


def test_uses_annotations_parameter():
    assert module_uses_annotations("def f(x: int):\n    return x\n")


def test_uses_annotations_annassign():
    assert module_uses_annotations("count: int = 0\n")


def test_uses_annotations_vararg_and_kwarg():
    assert module_uses_annotations("def f(*a: int):\n    return a\n")
    assert module_uses_annotations("def f(**k: str):\n    return k\n")


def test_uses_annotations_keyword_only():
    assert module_uses_annotations("def f(*, x: int):\n    return x\n")


def test_no_annotations_is_false():
    assert not module_uses_annotations("def f(x, y):\n    return x + y\n")


def test_uses_annotations_syntax_error_is_false():
    assert not module_uses_annotations("def (:\n")


def test_has_future_annotations_detects_present():
    assert has_future_annotations(
        "from __future__ import annotations\n\nx: int = 0\n")
    assert has_future_annotations(
        "from __future__ import division, annotations\n")


def test_has_future_annotations_false_when_absent():
    assert not has_future_annotations("from __future__ import division\n")
    assert not has_future_annotations("x: int = 0\n")


# --- the core transform: rewrite --------------------------------------------

def test_fresh_insert_after_docstring():
    out = add_future_annotations(_TYPED)
    assert out is not None
    lines = out.splitlines()
    # The docstring stays first; the import lands right after it (before `import os`).
    assert lines[0] == '"""A typed module."""'
    assert lines[1] == "from __future__ import annotations"
    assert lines[2] == ""  # blank line kept before the following code
    assert "import os" in lines[3]
    ast.parse(out)  # never lands broken Python


def test_fresh_insert_no_docstring():
    out = add_future_annotations("import os\n\n\ndef f(x: int):\n    return x\n")
    assert out is not None
    assert out.splitlines()[0] == "from __future__ import annotations"


def test_widen_existing_future_import_in_place():
    src = "from __future__ import division\n\nx: int = 0\n"
    out = add_future_annotations(src)
    assert out is not None
    # No SECOND __future__ line — the existing one is widened, names sorted.
    assert out.count("from __future__ import") == 1
    assert out.splitlines()[0] == "from __future__ import annotations, division"
    ast.parse(out)


def test_widen_preserves_other_future_names():
    src = "from __future__ import generator_stop\n\ny: list = []\n"
    out = add_future_annotations(src)
    assert out is not None
    assert out.splitlines()[0] == (
        "from __future__ import annotations, generator_stop")


# --- the core transform: REFUSALS (honest no-ops) ---------------------------

def test_refuses_no_annotations():
    assert add_future_annotations("def f(x):\n    return x\n") is None


def test_refuses_already_present():
    assert add_future_annotations(
        "from __future__ import annotations\n\nx: int = 0\n") is None


def test_refuses_already_present_among_others():
    assert add_future_annotations(
        "from __future__ import annotations, division\n\nx: int = 0\n") is None


def test_refuses_syntax_error():
    assert add_future_annotations("def (:\n") is None


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_noop():
    once = add_future_annotations(_TYPED)
    assert once is not None
    assert add_future_annotations(once) is None  # 2nd run = byte-identical no-op


def test_deterministic_across_two_runs():
    a = add_future_annotations(_TYPED)
    b = add_future_annotations(_TYPED)
    assert a is not None and a == b


def test_preserves_trailing_newline_absence():
    # A source with NO trailing newline keeps that exact shape.
    out = add_future_annotations("x: int = 0")
    assert out is not None and not out.endswith("\n")


# --- registration / reachability --------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "add-from-future-annotations" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["add-from-future-annotations"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(
        "annotations to make lazy with a future import"
    ) == "add-from-future-annotations"


def test_facet_reachability_parity_invariant_holds():
    # The standing 1:1 invariant: the facet map reaches EXACTLY the registered
    # objectives. Adding this objective to BOTH sides keeps the equality.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_substring_order_safe():
    # The new key must be neither a substring of, nor contain, any other key
    # (with a different objective) — else the first-match scan would mis-route.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    new = "annotations to make lazy with a future import"
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
    assert "add-from-future-annotations" in buckets["CONCRETE"]
    # No stale manifest name (a name with no live objective) was introduced.
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_signatures_and_types_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["signatures and types"]
    assert "annotations to make lazy with a future import" in ladder
    assert ladder[0] == "parameter meanings"  # originals still lead


# --- the plan: a typed-but-eager module gets the import ----------------------

def test_plan_lands_the_import(tmp_path: Path):
    _project(tmp_path, "app/util.py", _TYPED)
    plan = plan_from_future_annotations(str(tmp_path), "app/util.py")
    assert plan.ok
    new = plan.new_contents["app/util.py"]
    assert "from __future__ import annotations" in new
    assert plan.originals["app/util.py"] == _TYPED  # original captured for rollback
    assert plan.edits_by_file["app/util.py"] == 1


def test_plan_refuses_module_without_annotations(tmp_path: Path):
    _project(tmp_path, "app/util.py", "def f(x):\n    return x\n")
    assert not plan_from_future_annotations(
        str(tmp_path), "app/util.py").new_contents


def test_plan_refuses_already_present(tmp_path: Path):
    _project(tmp_path, "app/util.py",
             "from __future__ import annotations\n\nx: int = 0\n")
    assert not plan_from_future_annotations(
        str(tmp_path), "app/util.py").new_contents


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _TYPED)
    assert not plan_from_future_annotations(
        str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _TYPED)
    assert not plan_from_future_annotations(
        str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_from_future_annotations(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_lands_import_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    (tmp_path / "app" / "util.py").write_text(_TYPED, encoding="utf-8")
    (tmp_path / "tests" / "test_util.py").write_text(
        "from app.util import joinp\n"
        "def test_join():\n    assert joinp('a', 'b').endswith('b')\n",
        encoding="utf-8")

    plan = plan_from_future_annotations(str(tmp_path), "app/util.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "util.py").read_text(encoding="utf-8")
    assert "from __future__ import annotations" in landed  # the import LANDED
    # Behaviour preserved: the (now lazy-annotated) function still works, proven
    # green by the apply gate running the existing test above.
    assert "def joinp(a: str, b: str) -> str:" in landed


def test_end_to_end_auto_rollback_when_eager_get_type_hints_goes_red(tmp_path: Path):
    # never-fake-green at the engine level: the ONE runtime risk is a module that
    # EAGERLY resolves its own annotations at import time via get_type_hints(). Here
    # ``inner``'s annotation references the ENCLOSING-LOCAL name ``Local``: with
    # EAGER annotations the real class object is captured (get_type_hints succeeds);
    # once the import makes annotations LAZY, the annotation is the string
    # ``"Local"`` and get_type_hints — which only sees globals — NameErrors. The
    # suite gate catches the regression and rolls the in-place rewrite back
    # byte-for-byte. (Divergence verified independently before pinning it here.)
    _suite_project(tmp_path)
    eager = (
        "import typing\n"
        "\n"
        "\n"
        "class Helper:\n"
        "    pass\n"
        "\n"
        "\n"
        "def outer():\n"
        "    Local = Helper\n"
        "    def inner(x: Local) -> None:\n"
        "        return None\n"
        "    return inner\n"
        "\n"
        "\n"
        "_F = outer()\n"
        "# eager resolution at import time — fine while annotations are eager (the\n"
        "# real ``Local`` object is captured), but lazy annotations make this red.\n"
        "_HINTS = typing.get_type_hints(_F)\n"
    )
    target = tmp_path / "app" / "eager.py"
    target.write_text(eager, encoding="utf-8")
    (tmp_path / "tests" / "test_eager.py").write_text(
        "import app.eager  # importing must not raise\n"
        "def test_imports():\n    assert app.eager._HINTS["
        "'x'] is app.eager.Helper\n",
        encoding="utf-8")

    plan = plan_from_future_annotations(str(tmp_path), "app/eager.py")
    assert plan.ok  # there ARE annotations, so a rewrite is proposed
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is False
    assert result.get("rolled_back") is True
    # The file is restored byte-for-byte — the eager import is NEVER landed when it
    # would break the suite (a red contract is never left pinned).
    assert target.read_text(encoding="utf-8") == eager
