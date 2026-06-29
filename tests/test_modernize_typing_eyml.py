"""modernize-typing develop objective — LAND the PEP 585 / PEP 604 typing
modernization (:func:`app.execution.modernize_typing.modernize_typing`) on the
autonomous develop surface. It rewrites ANNOTATION-POSITION ``typing.List[x]`` ->
``list[x]`` (and ``Dict``/``Tuple``/``Set``/``FrozenSet``/``Type``),
``Optional[X]`` -> ``X | None``, ``Union[A, B]`` -> ``A | B``, ``typing.Text`` ->
``str`` — a BEHAVIOUR-PRESERVING modernization made version-safe by the
load-bearing future-import gate (under PEP 563 every annotation is a lazy string,
so the modern spellings are runtime-safe on any parsing Python).

Covers the full spec matrix:

  * the load-bearing GATE: a rewrite fires ONLY with ``from __future__ import
    annotations``; NO future-import -> honest no-op (the recoverable composition);
  * POSITIVE spellings (future-import present): List/Dict/…, Optional, Union (+ None,
    nested, single-element), Text, nested generics, aliased ``import typing as t``
    and ``from typing import List as L``;
  * the SOUNDNESS BOUNDARY: a ``typing`` name in EXPRESSION position (assignment,
    ``isinstance``, ``List[int]()``, ``cast(List[int], y)``) is NEVER rewritten;
  * REFUSALS: star-import, alias-ambiguity, shadowed name, ``Tuple[()]``, string
    annotation, unparseable source — each an honest ``None``;
  * IDEMPOTENCY (a second run is a byte-identical no-op) + determinism;
  * the objective plan layer (lands + captures the original for rollback; refuses
    test/fixture/non-library; unreadable no-op);
  * the fitness/moves loop (one move per landable module; fitness 0 when none);
  * the end-to-end verified-with-rollback apply (lands on a GREEN suite, ROLLS BACK
    byte-identically on a RED suite);
  * the FIVE-registry 1:1 parity (available_objectives + move_value + north_star
    manifest + soundness strategy), the count pin, and the soundness-corpus refusal.

Every test is pure-AST / in-process except the two explicit suite-gated apply tests
— all run on the fast gate.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.modernize_typing import (
    modernizable_annotations,
    modernize_typing,
)
from app.execution.objectives.modernize_typing import plan_modernize_typing

# Every fixture module is GATED by this — the transform refuses without it.
_F = "from __future__ import annotations\n"


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return tmp_path


# --- positive spellings (future-import PRESENT) -------------------------------

def test_list_subscript_to_builtin():
    out = modernize_typing(_F + "from typing import List\nx: List[int]\n")
    assert out == _F + "from typing import List\nx: list[int]\n"


def test_dict_subscript_to_builtin():
    out = modernize_typing(_F + "from typing import Dict\nx: Dict[str, int]\n")
    assert out == _F + "from typing import Dict\nx: dict[str, int]\n"


def test_set_frozenset_type_tuple_subscripts():
    src = (_F + "from typing import Set, FrozenSet, Type, Tuple\n"
           "a: Set[int]\nb: FrozenSet[str]\nc: Type[int]\nd: Tuple[int, str]\n")
    out = modernize_typing(src)
    assert out == (_F + "from typing import Set, FrozenSet, Type, Tuple\n"
                   "a: set[int]\nb: frozenset[str]\nc: type[int]\nd: tuple[int, str]\n")


def test_optional_to_union_none():
    out = modernize_typing(_F + "from typing import Optional\nx: Optional[int]\n")
    assert out == _F + "from typing import Optional\nx: int | None\n"


def test_union_two_members():
    out = modernize_typing(_F + "from typing import Union\nx: Union[int, str]\n")
    assert out == _F + "from typing import Union\nx: int | str\n"


def test_union_with_none_member_single_none_tail():
    out = modernize_typing(_F + "from typing import Union\nx: Union[int, str, None]\n")
    assert out == _F + "from typing import Union\nx: int | str | None\n"


def test_optional_of_union_flattens_single_none():
    # Optional[Union[A, B]] -> A | B | None (one | None tail, never doubled).
    out = modernize_typing(
        _F + "from typing import Optional, Union\nx: Optional[Union[int, str]]\n")
    assert out == _F + "from typing import Optional, Union\nx: int | str | None\n"


def test_nested_union_flattens():
    out = modernize_typing(
        _F + "from typing import Union\nx: Union[int, Union[str, bytes]]\n")
    assert out == _F + "from typing import Union\nx: int | str | bytes\n"


def test_single_element_union_collapses():
    out = modernize_typing(_F + "from typing import Union\nx: Union[int]\n")
    assert out == _F + "from typing import Union\nx: int\n"


def test_text_to_str():
    out = modernize_typing(_F + "from typing import Text\nx: Text\n")
    assert out == _F + "from typing import Text\nx: str\n"


def test_nested_generic_inner_migrates():
    out = modernize_typing(
        _F + "from typing import Dict, List\nx: Dict[str, List[int]]\n")
    assert out == _F + "from typing import Dict, List\nx: dict[str, list[int]]\n"


def test_function_signature_and_return():
    src = (_F + "from typing import Optional, List, Dict\n"
           "def f(x: Optional[List[int]]) -> Dict[str, int]:\n    return {}\n")
    out = modernize_typing(src)
    assert out == (_F + "from typing import Optional, List, Dict\n"
                   "def f(x: list[int] | None) -> dict[str, int]:\n    return {}\n")


def test_aliased_module_import_typing_as_t():
    out = modernize_typing(_F + "import typing as t\nx: t.List[int]\n")
    assert out == _F + "import typing as t\nx: list[int]\n"


def test_plain_import_typing_dotted():
    out = modernize_typing(_F + "import typing\nx: typing.Optional[int]\n")
    assert out == _F + "import typing\nx: int | None\n"


def test_from_import_as_alias():
    out = modernize_typing(_F + "from typing import List as L\nx: L[int]\n")
    assert out == _F + "from typing import List as L\nx: list[int]\n"


def test_args_kwargs_and_kwonly_annotations():
    src = (_F + "from typing import List, Dict, Optional\n"
           "def f(*args: List[int], k: Optional[str] = None, **kw: Dict[str, int]):\n"
           "    return args\n")
    out = modernize_typing(src)
    # Only the annotation SPANS are spliced — the parameter default ` = None` keeps
    # its original spacing (the transform never touches outside an annotation slot).
    assert out == (_F + "from typing import List, Dict, Optional\n"
                   "def f(*args: list[int], k: str | None = None, **kw: dict[str, int]):\n"
                   "    return args\n")


def test_modernizable_annotations_predicate():
    assert modernizable_annotations(_F + "from typing import List\nx: List[int]\n")
    assert not modernizable_annotations("from typing import List\nx: List[int]\n")  # no gate
    assert not modernizable_annotations(_F + "x: int\n")  # nothing to migrate


# --- the load-bearing gate ----------------------------------------------------

def test_no_future_import_refuses():
    # The whole recipe turns on this: NO `from __future__ import annotations` ->
    # honest no-op (do NOT probe the Python version, do NOT assume 3.10).
    assert modernize_typing("from typing import List\nx: List[int]\n") is None


def test_future_import_among_other_future_names_still_gates():
    src = ("from __future__ import annotations, division\n"
           "from typing import List\nx: List[int]\n")
    out = modernize_typing(src)
    assert out is not None and "x: list[int]" in out


# --- the soundness boundary: expression position is NEVER rewritten -----------

def test_expression_assignment_untouched():
    # `MyList = List` is a runtime VALUE use, not an annotation -> untouched.
    assert modernize_typing(_F + "from typing import List\nMyList = List\n") is None


def test_isinstance_argument_untouched():
    src = _F + "from typing import List\ndef f(x):\n    return isinstance(x, List)\n"
    assert modernize_typing(src) is None


def test_subscript_call_in_expression_untouched():
    src = _F + "from typing import List\ndef f():\n    return List[int]()\n"
    assert modernize_typing(src) is None


def test_cast_first_argument_untouched():
    # cast(List[int], y): the type is in EXPRESSION position (an argument), so it
    # must NOT be rewritten — the core soundness boundary.
    src = _F + "from typing import List, cast\ndef f(y):\n    return cast(List[int], y)\n"
    assert modernize_typing(src) is None


def test_annotation_migrates_while_sibling_cast_stays():
    # A real annotation slot migrates; an expression-position cast in the same
    # function is left exactly as written.
    src = (_F + "from typing import List, cast\n"
           "def f(items: List[int]):\n    return cast(List[str], items)\n")
    out = modernize_typing(src)
    assert out == (_F + "from typing import List, cast\n"
                   "def f(items: list[int]):\n    return cast(List[str], items)\n")


# --- refusals -----------------------------------------------------------------

def test_star_import_refuses():
    # `from typing import *` -> a bare List can't be PROVEN typing's -> refuse.
    assert modernize_typing(_F + "from typing import *\nx: List[int]\n") is None


def test_alias_ambiguity_refuses():
    # The same local name bound to typing AND another module -> ambiguous -> refuse.
    src = _F + "from typing import List\nfrom collections import List\nx: List[int]\n"
    assert modernize_typing(src) is None


def test_shadowed_by_assignment_refuses():
    src = _F + "from typing import List\nList = 5\nx: List\n"
    assert modernize_typing(src) is None


def test_shadowed_by_def_refuses():
    src = _F + "from typing import List\ndef List():\n    pass\ny: List[int]\n"
    assert modernize_typing(src) is None


def test_shadowed_by_class_refuses():
    src = _F + "from typing import Optional\nclass Optional:\n    pass\ny: Optional[int]\n"
    assert modernize_typing(src) is None


def test_shadowed_by_parameter_refuses():
    src = (_F + "from typing import List\n"
           "def g(List):\n    return List\nx: List[int]\n")
    assert modernize_typing(src) is None


def test_tuple_empty_refuses():
    # Tuple[()] (the empty-tuple type) is a wave-1 sharp edge -> refuse the module.
    assert modernize_typing(_F + "from typing import Tuple\nx: Tuple[()]\n") is None


def test_string_literal_annotation_refuses():
    # x: "List[int]" — a forward-ref string -> refuse in wave 1.
    assert modernize_typing(_F + 'from typing import List\nx: "List[int]"\n') is None


def test_no_typing_import_is_noop():
    # No migratable typing name imported at all -> nothing to do (no-op).
    assert modernize_typing(_F + "x: int\ny: list[str]\n") is None


def test_unparseable_source_is_none():
    assert modernize_typing(_F + "def (:\n") is None


def test_tuple_empty_refusal_does_not_block_when_absent():
    # A sharp edge refuses the WHOLE module: a clean List beside a Tuple[()] is NOT
    # landed (soundness over recall) — but the same List alone lands fine.
    blocked = modernize_typing(
        _F + "from typing import List, Tuple\na: List[int]\nb: Tuple[()]\n")
    assert blocked is None
    fine = modernize_typing(_F + "from typing import List\na: List[int]\n")
    assert fine is not None and "a: list[int]" in fine


# --- idempotency + determinism ------------------------------------------------

def test_idempotent_second_run_is_noop():
    src = (_F + "from typing import Optional, List\n"
           "def f(x: Optional[List[int]]) -> List[str]:\n    return []\n")
    once = modernize_typing(src)
    assert once is not None
    assert modernize_typing(once) is None  # no legacy spelling left -> byte-identical


def test_deterministic_repeated_calls():
    src = (_F + "from typing import Optional, List, Dict\n"
           "def f(x: Optional[List[int]], y: Dict[str, int]) -> Optional[str]:\n"
           "    return None\n")
    first = modernize_typing(src)
    for _ in range(5):
        assert modernize_typing(src) == first


def test_rewrite_reparses():
    src = (_F + "from typing import Optional, List, Dict, Union\n"
           "def f(x: Optional[List[int]]) -> Union[Dict[str, int], None]:\n"
           "    return {}\n")
    out = modernize_typing(src)
    assert out is not None
    ast.parse(out)  # never lands broken Python


# --- objective plan layer -----------------------------------------------------

def test_plan_lands_and_captures_original(tmp_path: Path):
    src = _F + "from typing import List\nx: List[int]\n"
    root = _project(tmp_path, "pkg/m.py", src)
    plan = plan_modernize_typing(str(root), "pkg/m.py")
    assert plan.new_contents["pkg/m.py"] == _F + "from typing import List\nx: list[int]\n"
    assert plan.originals["pkg/m.py"] == src  # original kept for rollback


def test_plan_refuses_test_file(tmp_path: Path):
    root = _project(tmp_path, "tests/test_m.py", _F + "from typing import List\nx: List[int]\n")
    assert not plan_modernize_typing(str(root), "tests/test_m.py").new_contents


def test_plan_refuses_fixture_file(tmp_path: Path):
    root = _project(tmp_path, "fixtures/m.py", _F + "from typing import List\nx: List[int]\n")
    assert not plan_modernize_typing(str(root), "fixtures/m.py").new_contents


def test_plan_refuses_non_library_file(tmp_path: Path):
    # A packaging/config script (docs/conf.py) is nobody's imported API -> skip.
    root = _project(tmp_path, "docs/conf.py", _F + "from typing import List\nx: List[int]\n")
    assert not plan_modernize_typing(str(root), "docs/conf.py").new_contents


def test_plan_no_future_import_is_noop(tmp_path: Path):
    root = _project(tmp_path, "pkg/m.py", "from typing import List\nx: List[int]\n")
    assert not plan_modernize_typing(str(root), "pkg/m.py").new_contents


def test_plan_unreadable_is_noop(tmp_path: Path):
    # A path that does not exist on disk -> unreadable -> honest empty no-op plan.
    assert not plan_modernize_typing(str(tmp_path), "pkg/missing.py").new_contents


# --- fitness / moves loop -----------------------------------------------------

def _spec():
    from app.engine.develop_registry import registered_specs

    return registered_specs()["modernize-typing"]


def _runnable_project(tmp_path: Path, module_src: str) -> Path:
    """A self-contained installable project whose own module is ``module_src`` with
    a GREEN suite — so the develop fitness/moves/apply loop has a real subject."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "m.py").write_text(module_src, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_m.py").write_text(
        "import pkg.m\ndef test_i():\n    assert pkg.m.f(1) == [1]\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    return tmp_path


_RUNNABLE = (_F + "from typing import List\n"
             "def f(x: List[int]) -> List[int]:\n    return [x] if isinstance(x, int) else x\n")


def test_fitness_counts_landable_modules(tmp_path: Path):
    root = _runnable_project(tmp_path, _RUNNABLE)
    assert _spec().fitness(str(root)) == 1.0


def test_moves_one_per_landable_module(tmp_path: Path):
    root = _runnable_project(tmp_path, _RUNNABLE)
    moves = _spec().moves(str(root))
    assert len(moves) == 1
    mv = moves[0]
    assert mv.operator == "modernize_typing"
    assert mv.target.startswith("pkg/m.py:")
    plan = mv.build_plan()
    assert "x: list[int]" in plan.new_contents["pkg/m.py"]


def test_fitness_zero_when_nothing_landable(tmp_path: Path):
    # A module with NO future-import -> the transform refuses -> fitness 0, no moves.
    root = _runnable_project(
        tmp_path, "def f(x):\n    return [x] if isinstance(x, int) else x\n")
    assert _spec().fitness(str(root)) == 0.0
    assert _spec().moves(str(root)) == []


# --- end-to-end verified-with-rollback apply ----------------------------------

def test_apply_lands_on_green_suite(tmp_path: Path):
    root = _runnable_project(tmp_path, _RUNNABLE)
    plan = _spec().moves(str(root))[0].build_plan()
    out = apply_rename(str(root), plan, verify=True)
    assert out["applied"] is True
    assert out.get("rolled_back") is False
    landed = (root / "pkg" / "m.py").read_text(encoding="utf-8")
    assert "def f(x: list[int]) -> list[int]:" in landed


def test_apply_rolls_back_on_red_suite(tmp_path: Path):
    # A pre-existing-RED suite is not made green by a behaviour-preserving annotation
    # rewrite; the full-suite gate rolls the change back byte-for-byte
    # (never-fake-green).
    root = _runnable_project(tmp_path, _RUNNABLE)
    (root / "tests" / "test_m.py").write_text(
        "import pkg.m\ndef test_wrong():\n    assert pkg.m.f(1) == 999\n",
        encoding="utf-8")
    before = (root / "pkg" / "m.py").read_text(encoding="utf-8")
    plan = _spec().moves(str(root))[0].build_plan()
    out = apply_rename(str(root), plan, verify=True)
    assert out["applied"] is False
    assert out["rolled_back"] is True
    assert (root / "pkg" / "m.py").read_text(encoding="utf-8") == before


# --- registration / 5-registry 1:1 parity -------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "modernize-typing" in set(available_objectives())


def test_objective_spec_is_pure_ast_and_full_suite():
    spec = _spec()
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is False  # pure-AST scan, swept on the fast path
    assert spec.scope_verify is False  # behaviour-identical; no red-baseline veto


def test_move_value_parity():
    from app.engine.move_value import OPERATOR_VALUE, move_value, objective_value

    assert OPERATOR_VALUE["modernize_typing"] == 0.42
    assert move_value("modernize_typing") == 0.42
    # The name->operator bridge resolves by dash->underscore (no explicit remap).
    assert objective_value("modernize-typing") == 0.42


def test_north_star_manifest_parity():
    from app.engine.north_star_audit import OBJECTIVE_MANIFEST, classify_objectives
    from app.engine.objective_compiler import available_objectives

    assert "modernize-typing" in OBJECTIVE_MANIFEST["TIDY"]
    # The forward tripwire classifies the live registry without raising.
    buckets = classify_objectives(set(available_objectives()))
    assert "modernize-typing" in buckets["TIDY"]


def test_soundness_strategy_parity():
    from app.engine.soundness_audit import (
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert "modernize-typing" in SOUNDNESS_STRATEGY
    assert "future-import-gated" in SOUNDNESS_STRATEGY["modernize-typing"]
    assert "annotation-slot-only" in SOUNDNESS_STRATEGY["modernize-typing"]
    # No stale strategy name (reverse tripwire stays clean).
    assert "modernize-typing" not in strategy_subset_of_registry()


def test_audits_pass_with_new_objective():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    assert north_star_report(".")["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


def test_refuses_on_python_soundness_corpus():
    # modernize-typing is pure-AST (not expensive), swept on the DEFAULT cheap path.
    # NO corpus fixture carries `from __future__ import annotations`, so the gate
    # refuses every shape — never a VIOLATION, never a behaviour change.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=False)
    cells = corpus.get("modernize-typing", {})
    assert cells, "modernize-typing should be swept on the cheap corpus path"
    for shape, verdict in cells.items():
        assert not verdict.startswith("VIOLATION"), f"{shape}: {verdict}"
