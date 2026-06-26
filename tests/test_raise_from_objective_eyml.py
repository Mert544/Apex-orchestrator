"""raise-from develop objective — wire the already-built B904 transform
(:func:`app.execution.semantic.transforms.raise_from.apply`) onto the autonomous
develop surface. It turns ``raise X(...)`` inside ``except E as err:`` into
``raise X(...) from err`` (chains the re-raised exception to its cause, restoring
the traceback), a BEHAVIOUR-PRESERVING traceback-hygiene fix: the SAME exception is
raised with the SAME control flow — only ``__cause__`` changes.

Covers: the transform's land + refusal set (lands a binding chain; refuses no
``as`` binding / no raise / already-chained / multi-line raise / unparseable
source; idempotent; deterministic); the objective plan layer (lands + captures the
original for rollback, refuses test/fixture/non-library, unreadable no-op,
deterministic); the fitness/moves loop (one move per landable module, fitness
reaches 0 when none remain); the end-to-end verified-with-rollback apply (lands on
a GREEN suite, ROLLS BACK byte-identically on a RED suite); behaviour-identical
(re-parses, the ONLY textual change is the appended ``from err``); plus objective
registration / facet+manifest+soundness+move-value 1:1 parity (the FIVE registries
the new objective must appear in), the COUNT pins (78 / 36), and the
soundness-corpus refusal. Every test is pure-AST / in-process except the two
explicit suite-gated apply tests — all run on the fast gate.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.objectives.raise_from import plan_raise_from
from app.execution.semantic.transforms import raise_from

_PHRASE = "the unchained re-raise to chain from its cause"

# A minimal module with a B904 violation: a fresh raise inside a binding handler.
_B904 = (
    "def f():\n"
    "    try:\n"
    "        g()\n"
    "    except ValueError as err:\n"
    "        raise RuntimeError('boom')\n"
)
# The same module after the fix — the ONLY change is the appended ``from err``.
_B904_FIXED = (
    "def f():\n"
    "    try:\n"
    "        g()\n"
    "    except ValueError as err:\n"
    "        raise RuntimeError('boom') from err\n"
)


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return tmp_path


# --- the transform: land + the full refusal set (the soundness core) ----------

def test_apply_lands_from_err():
    res = raise_from.apply("pkg/m.py", _B904, "raise-from")
    assert res is not None
    assert res.transform_type == "raise_with_from"
    assert res.patch_requests[0]["new_content"] == _B904_FIXED
    assert res.patch_requests[0]["expected_old_content"] == _B904


def test_apply_refuses_handler_without_binding():
    # ``except ValueError:`` has no ``as <name>`` to chain from -> refuse (inventing
    # a binding is a bigger edit than this transform promises).
    src = (
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except ValueError:\n"
        "        raise RuntimeError('x')\n"
    )
    assert raise_from.apply("pkg/m.py", src, "raise-from") is None


def test_apply_refuses_when_no_raise_in_handler():
    # A binding handler that does not re-raise a fresh exception -> nothing to fix.
    src = (
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except ValueError as err:\n"
        "        log(err)\n"
    )
    assert raise_from.apply("pkg/m.py", src, "raise-from") is None


def test_apply_refuses_already_chained():
    # The raise already carries ``from err`` (cause is not None) -> idempotent no-op.
    assert raise_from.apply("pkg/m.py", _B904_FIXED, "raise-from") is None


def test_apply_refuses_bare_reraise():
    # A bare ``raise`` (re-raise the active exception) is exc=None, not a Call -> skip.
    src = (
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except ValueError as err:\n"
        "        raise\n"
    )
    assert raise_from.apply("pkg/m.py", src, "raise-from") is None


def test_apply_refuses_multiline_raise():
    # A multi-line ``raise`` segment: line surgery would be fragile, so it is skipped.
    src = (
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except ValueError as err:\n"
        "        raise RuntimeError(\n"
        "            'boom',\n"
        "        )\n"
    )
    assert raise_from.apply("pkg/m.py", src, "raise-from") is None


def test_apply_refuses_nested_function_raise():
    # The fixable raise must be in the HANDLER's own scope; a nested def is its own
    # context (mirrors the detector walk), so a raise there is not attributed.
    src = (
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except ValueError as err:\n"
        "        def inner():\n"
        "            raise RuntimeError('x')\n"
        "        return inner\n"
    )
    assert raise_from.apply("pkg/m.py", src, "raise-from") is None


def test_apply_lands_raise_nested_in_if():
    # A raise nested in plain control flow (if/for/while) inside the handler IS
    # attributed and chained.
    src = (
        "def f(c):\n"
        "    try:\n"
        "        g()\n"
        "    except ValueError as err:\n"
        "        if c:\n"
        "            raise RuntimeError('x')\n"
    )
    res = raise_from.apply("pkg/m.py", src, "raise-from")
    assert res is not None
    assert "raise RuntimeError('x') from err" in res.patch_requests[0]["new_content"]


def test_apply_unparseable_source_is_none():
    assert raise_from.apply("pkg/m.py", "def (:\n  ???\n", "raise-from") is None


def test_apply_is_deterministic():
    a = raise_from.apply("pkg/m.py", _B904, "raise-from")
    b = raise_from.apply("pkg/m.py", _B904, "raise-from")
    assert a is not None and b is not None
    assert a.patch_requests[0]["new_content"] == b.patch_requests[0]["new_content"]


# --- behaviour-identical: the ONLY change is the appended ``from err`` ---------

def test_fix_is_behaviour_identical_only_from_err_added():
    res = raise_from.apply("pkg/m.py", _B904, "raise-from")
    assert res is not None
    new = res.patch_requests[0]["new_content"]
    # Re-parses (a malformed splice is never landed).
    ast.parse(new)
    # The diff is EXACTLY the four characters " err" appended after the ``from``;
    # stripping the one added token reproduces the original byte-for-byte.
    assert new.replace(" from err", "", 1) == _B904
    # The re-raised exception type and its argument are unchanged.
    assert "raise RuntimeError('boom')" in new


# --- the objective plan layer -------------------------------------------------

def test_plan_lands_and_captures_original(tmp_path: Path):
    root = _project(tmp_path, "pkg/m.py", _B904)
    plan = plan_raise_from(str(root), "pkg/m.py")
    assert plan.originals["pkg/m.py"] == _B904  # original captured for rollback
    assert plan.new_contents["pkg/m.py"] == _B904_FIXED
    assert plan.edits_by_file["pkg/m.py"] == 1


def test_plan_refuses_test_file(tmp_path: Path):
    root = _project(tmp_path, "tests/test_m.py", _B904)
    plan = plan_raise_from(str(root), "tests/test_m.py")
    assert not plan.new_contents  # the suite is never edited


def test_plan_refuses_fixture_file(tmp_path: Path):
    root = _project(tmp_path, "fixtures/m.py", _B904)
    plan = plan_raise_from(str(root), "fixtures/m.py")
    assert not plan.new_contents


def test_plan_refuses_non_library_file(tmp_path: Path):
    # docs/conf.py is a denylisted non-library script (nobody imports it as an API).
    root = _project(tmp_path, "docs/conf.py", _B904)
    plan = plan_raise_from(str(root), "docs/conf.py")
    assert not plan.new_contents


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_raise_from(str(tmp_path), "pkg/missing.py")
    assert not plan.new_contents  # unreadable -> honest no-op


def test_plan_noop_when_nothing_fixable(tmp_path: Path):
    root = _project(tmp_path, "pkg/m.py", "def f(x):\n    return x\n")
    plan = plan_raise_from(str(root), "pkg/m.py")
    assert not plan.new_contents


def test_plan_is_deterministic(tmp_path: Path):
    root = _project(tmp_path, "pkg/m.py", _B904)
    a = plan_raise_from(str(root), "pkg/m.py").new_contents
    b = plan_raise_from(str(root), "pkg/m.py").new_contents
    assert a == b


def test_plan_idempotent_after_landing(tmp_path: Path):
    # Re-running on the already-chained output is a byte-identical no-op.
    root = _project(tmp_path, "pkg/m.py", _B904_FIXED)
    assert not plan_raise_from(str(root), "pkg/m.py").new_contents


# --- the fitness / moves loop (one move per landable module; fitness -> 0) -----

_RUNNABLE_B904 = (
    "def f():\n"
    "    try:\n"
    "        return int('x')\n"
    "    except ValueError as err:\n"
    "        raise RuntimeError('bad')\n"
)
# A runnable string-collision module: ``f()`` enters the handler and raises
# RuntimeError(1); the raise's source text also lives in an earlier string literal
# on the SAME line, so a textual replace would corrupt it (a churn loop).
_STRING_COLLISION_RUNNABLE = (
    "def f():\n"
    "    try:\n"
    "        return int('x')\n"
    "    except ValueError as err:\n"
    "        tag = \"raise RuntimeError(1)\"; raise RuntimeError(1)\n"
)


def _runnable_project_with(tmp_path: Path, module_src: str) -> Path:
    """A self-contained installable project whose own module is ``module_src`` (which
    must define ``f()`` that raises ``RuntimeError`` when called) with a GREEN suite —
    so the develop fitness/moves/apply loop has a real subject."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "m.py").write_text(module_src, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_m.py").write_text(
        "import pytest\n"
        "import pkg.m\n"
        "def test_raises():\n"
        "    with pytest.raises(RuntimeError):\n"
        "        pkg.m.f()\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _runnable_project(tmp_path: Path) -> Path:
    """A self-contained installable project with ONE B904 in its own module and a
    GREEN suite, so the develop fitness/moves loop has a real subject."""
    return _runnable_project_with(tmp_path, _RUNNABLE_B904)


def _spec():
    from app.engine.develop_registry import registered_specs

    return registered_specs()["raise-from"]


def test_fitness_counts_landable_modules(tmp_path: Path):
    root = _runnable_project(tmp_path)
    assert _spec().fitness(str(root)) == 1.0


def test_moves_one_per_landable_module(tmp_path: Path):
    root = _runnable_project(tmp_path)
    moves = _spec().moves(str(root))
    assert len(moves) == 1
    mv = moves[0]
    assert mv.operator == "raise_from"
    assert mv.target.startswith("pkg/m.py:")
    plan = mv.build_plan()
    assert "from err" in plan.new_contents["pkg/m.py"]


def test_fitness_is_zero_when_nothing_landable(tmp_path: Path):
    # No B904 anywhere -> fitness 0, no moves (the honest "done" state).
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "m.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_m.py").write_text(
        "import pkg.m\ndef test_i():\n    assert pkg.m.f(1) == 2\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='pkg'\nversion='0'\n", encoding="utf-8")
    assert _spec().fitness(str(tmp_path)) == 0.0
    assert _spec().moves(str(tmp_path)) == []


# --- end-to-end verified-with-rollback apply (lands GREEN, rolls back RED) -----

def test_apply_lands_on_green_suite(tmp_path: Path):
    root = _runnable_project(tmp_path)
    plan = _spec().moves(str(root))[0].build_plan()
    out = apply_rename(str(root), plan, verify=True)
    assert out["applied"] is True
    assert out.get("rolled_back") is False
    # The fix is on disk: the re-raise is now chained.
    landed = (root / "pkg" / "m.py").read_text(encoding="utf-8")
    assert "raise RuntimeError('bad') from err" in landed


def test_apply_rolls_back_on_red_suite(tmp_path: Path):
    # A suite that asserts the WRONG exception type stays RED before and after the
    # behaviour-preserving fix; the full-suite gate must roll the change back
    # byte-for-byte (never-fake-green: a pre-red suite is not made green by a chain).
    root = _runnable_project(tmp_path)
    (root / "tests" / "test_m.py").write_text(
        "import pytest\n"
        "import pkg.m\n"
        "def test_wrong():\n"
        "    with pytest.raises(KeyError):\n"  # f() raises RuntimeError, never KeyError
        "        pkg.m.f()\n",
        encoding="utf-8",
    )
    before = (root / "pkg" / "m.py").read_text(encoding="utf-8")
    plan = _spec().moves(str(root))[0].build_plan()
    out = apply_rename(str(root), plan, verify=True)
    assert out["applied"] is False
    assert out["rolled_back"] is True
    # Rolled back byte-for-byte — the source is exactly what it was.
    assert (root / "pkg" / "m.py").read_text(encoding="utf-8") == before


# --- registration / 5-registry 1:1 parity (always runs) -----------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "raise-from" in set(available_objectives())


def test_objective_spec_is_callable_and_flagged():
    spec = _spec()
    assert callable(spec.fitness) and callable(spec.moves)
    assert spec.expensive is False  # pure-AST scan
    assert spec.scope_verify is False  # behaviour-identical chain; no red-baseline veto


def test_registry_1_north_star_manifest_concrete():
    from app.engine.north_star_audit import (
        classify_objectives,
        manifest_subset_of_registry,
    )
    from app.engine.objective_compiler import available_objectives

    buckets = classify_objectives(available_objectives())  # raises if unclassified
    assert "raise-from" in buckets["CONCRETE"]
    assert manifest_subset_of_registry() == []  # no stale manifest name


def test_registry_2_soundness_strategy_declared():
    from app.engine.soundness_audit import (
        SCOPE_VERIFY_ALLOWLIST,
        SOUNDNESS_STRATEGY,
        strategy_subset_of_registry,
    )

    assert SOUNDNESS_STRATEGY["raise-from"] == (
        "behavior-preserving-traceback-chain-only"
        "+raise-from-except-binding-verbatim"
        "+refuse-when-no-binding")
    # scope_verify=False -> it must NOT be in the audited allowlist.
    assert "raise-from" not in SCOPE_VERIFY_ALLOWLIST
    assert strategy_subset_of_registry() == []  # no stale strategy entry


def test_registry_3_move_value_tier_matches_operator():
    from app.engine.move_value import DEFAULT_VALUE, move_value, objective_value

    # The OPERATOR_VALUE key equals the moves() operator ("raise_from"); 0.64 sits
    # in the traceback-hygiene tier — below the doc-surface cluster (0.66) and harden.
    assert move_value("raise_from") == 0.64
    assert move_value("raise_from") < move_value("harden")  # below harden (0.65)
    assert move_value("raise_from") < move_value("pin_return_type")  # below doc-surface
    assert objective_value("raise-from") == 0.64
    assert objective_value("raise-from") != DEFAULT_VALUE  # not the unknown fallback


def test_registry_4_facet_routes_and_reachability_parity():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP, facet_to_objective
    from app.engine.objective_compiler import available_objectives

    assert facet_to_objective(_PHRASE) == "raise-from"
    # The reachable set still equals the full registered objective set.
    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_registry_4_facet_phrase_is_substring_order_safe():
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP

    keys = list(FACET_OBJECTIVE_MAP)
    assert _PHRASE in keys
    for other in keys:
        if other == _PHRASE:
            continue
        assert _PHRASE not in other, f"{_PHRASE!r} is a substring of {other!r}"
        assert other not in _PHRASE, f"{other!r} is a substring of {_PHRASE!r}"


def test_registry_4_facet_distinct_from_sibling_document_raises():
    # The chaining facet must not shadow (or be shadowed by) the document-raises facet
    # — the planner matches by substring, and both live under "raised exceptions".
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective("the raised exceptions to document") == "document-raises"
    assert facet_to_objective(_PHRASE) == "raise-from"


def test_registry_5_facet_phrase_lives_in_the_raised_exceptions_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["raised exceptions"]
    assert _PHRASE in ladder
    assert ladder[0] == "which type when"  # originals still lead
    # appended AFTER the document-raises sub-aspect (the last original/added one).
    assert ladder.index(_PHRASE) > ladder.index("the raised exceptions to document")


# --- audits PASS + count pins + corpus refusal --------------------------------

def test_north_star_and_soundness_audits_pass():
    from app.engine.north_star_audit import north_star_report
    from app.engine.soundness_audit import repo_root, soundness_report

    ns = north_star_report(".")
    assert ns["verdict"] == "PASS"
    snd = soundness_report(repo_root())
    assert snd["verdict"] == "PASS"
    assert snd["violations"] == []


def test_counts_are_thirty_six_concrete_of_seventy_eight():
    from app.engine.north_star_audit import classify_objectives
    from app.engine.objective_compiler import available_objectives

    names = set(available_objectives())
    assert len(names) == 79  # 79 after java-document-throws (37th concrete)
    assert len(classify_objectives(names)["CONCRETE"]) == 37


def test_refuses_on_python_soundness_corpus():
    # raise-from is NOT expensive (pure AST), so it is swept on the DEFAULT cheap
    # path (include_heavy=False). Every fixture shape is REFUSED or behaviour-
    # identical — never a VIOLATION. The two adversarial binding shapes
    # (``raise_from_del_binding`` / ``raise_from_rebound_binding``) MUST be refused
    # (chaining a del'd/rebound name changes behaviour); ``raise_from_string_collision``
    # LANDS a correct, behaviour-identical chain (the column-offset splice leaves the
    # string literal intact). All other shapes carry no fixable ``except … as``
    # binding, so they are refused.
    from app.engine.soundness_audit import corpus_refusal_findings, repo_root

    corpus = corpus_refusal_findings(repo_root(), include_heavy=False)
    cells = corpus.get("raise-from", {})
    assert cells, "raise-from should be swept on the cheap corpus path"
    for shape, verdict in cells.items():
        assert not verdict.startswith("VIOLATION"), f"{shape}: {verdict}"
    assert cells["raise_from_del_binding"] == "refused"
    assert cells["raise_from_rebound_binding"] == "refused"
    assert cells["raise_from_string_collision"] == "behavior-identical"


# --- adversarial binding vectors: del / rebind / string-collision -------------
#
# The denetçi-flagged P0/P1 set, at the objective/plan layer. The transform AST-finds
# the raise but must verify the bound name is still the CAUGHT exception (not del'd /
# rebound) and must splice by COLUMN OFFSET (never a textual str.replace that could
# corrupt a same-line string literal). These build the fixture, run the real plan,
# and assert REFUSAL (del/rebind) or a CORRECT splice (string-collision) — plus the
# non-convergence guard (apply twice -> the 2nd pass is a byte no-op, fitness 0).

_DEL_BINDING = (
    "def f():\n"
    "    try:\n"
    "        g()\n"
    "    except ValueError as err:\n"
    "        del err\n"
    "        raise RuntimeError('boom')\n"
)
_REBOUND_BINDING = (
    "def f():\n"
    "    try:\n"
    "        g()\n"
    "    except ValueError as err:\n"
    "        err = KeyError('x')\n"
    "        raise RuntimeError('boom')\n"
)
_STRING_COLLISION = (
    "def f():\n"
    "    try:\n"
    "        g()\n"
    "    except ValueError as err:\n"
    "        tag = \"raise RuntimeError(1)\"; raise RuntimeError(1)\n"
)


def test_plan_refuses_del_binding(tmp_path: Path):
    root = _project(tmp_path, "pkg/m.py", _DEL_BINDING)
    plan = plan_raise_from(str(root), "pkg/m.py")
    assert not plan.new_contents  # del'd name -> chaining would be UnboundLocalError


def test_plan_refuses_rebound_binding(tmp_path: Path):
    root = _project(tmp_path, "pkg/m.py", _REBOUND_BINDING)
    plan = plan_raise_from(str(root), "pkg/m.py")
    assert not plan.new_contents  # rebound name -> chaining a fabricated wrong cause


def test_plan_lands_string_collision_without_corrupting_the_literal(tmp_path: Path):
    # The raise's source text repeats inside an earlier string literal on the line;
    # the column-offset splice chains the REAL raise and leaves the string untouched.
    root = _project(tmp_path, "pkg/m.py", _STRING_COLLISION)
    plan = plan_raise_from(str(root), "pkg/m.py")
    out = plan.new_contents["pkg/m.py"]
    assert "tag = \"raise RuntimeError(1)\"; raise RuntimeError(1) from err" in out
    assert "tag = \"raise RuntimeError(1) from err\"" not in out  # not spliced into the string
    ast.parse(out)  # re-parses


def test_apply_string_collision_is_idempotent_non_convergence_guard(tmp_path: Path):
    # Apply twice on the real apply path: the 2nd pass is a byte-identical no-op and
    # fitness drops to 0 — the corruption loop the textual replace caused is gone.
    root = _runnable_project_with(tmp_path, _STRING_COLLISION_RUNNABLE)
    first = _spec().moves(str(root))[0].build_plan()
    out1 = apply_rename(str(root), first, verify=True)
    assert out1["applied"] is True and out1.get("rolled_back") is False
    landed = (root / "pkg" / "m.py").read_text(encoding="utf-8")
    assert "raise RuntimeError(1) from err" in landed
    assert "tag = \"raise RuntimeError(1) from err\"" not in landed
    # Second pass: nothing left to fix -> fitness 0, no moves (byte no-op).
    assert _spec().fitness(str(root)) == 0.0
    assert _spec().moves(str(root)) == []


def test_plan_del_and_rebind_are_deterministic_refusals(tmp_path: Path):
    # Both adversarial shapes refuse the SAME way on every run (no clock/random).
    for i, src in enumerate((_DEL_BINDING, _REBOUND_BINDING)):
        root = _project(tmp_path / f"r{i}", "pkg/m.py", src)
        a = plan_raise_from(str(root), "pkg/m.py").new_contents
        b = plan_raise_from(str(root), "pkg/m.py").new_contents
        assert a == b == {}
