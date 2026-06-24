"""add-final develop objective — LAND ``@typing.final`` on a project's own
top-level class that is PROVABLY never subclassed anywhere in the project.

``@typing.final`` is a PURE runtime no-op (it only sets ``__final__`` and is a
type-checker hint), so marking a class ``@final`` is behaviour-preserving BY
CONSTRUCTION — there is nothing at runtime to break. The only honesty risk is a
FALSE "final" on a class that IS subclassed; that is closed STRUCTURALLY by a
whole-project over-approximate subclass scan (reused from freeze-dataclass), NOT by
the suite — which is exactly why the never-fake-green guard here is structural: a
subclassed class is never finalized even though the no-op decorator would keep the
suite green (a fake-green the structural scan forbids).

Covers: the core transform (fresh import insert; widen an existing ``from typing
import ...``; the dotted ``@typing.final`` fallback when ``final`` is shadowed but
``typing`` is bound; decorator/indent preservation; trailing-newline preservation)
plus EVERY refusal — subclassed (bare AND dotted base, single- and cross-module),
already ``@final`` / ``@typing.final``, Protocol / ABC / ``abc.ABC`` / Enum /
``ABCMeta`` metaclass / ``Protocol[T]``, a shadowed ``final`` with no usable
``typing``, a ``final`` imported from another module, test/fixture, syntax error;
plus idempotency and determinism; the whole-project used-as-base over-approximation;
objective registration / reachability (available, callable spec,
reachable-from-facet, the facet-map<->registry 1:1 parity invariant,
substring-safety, the north-star manifest classing it CONCRETE with the reverse
tripwire clean, the facet ladder carrying the phrase with the originals still
leading); the END-TO-END landing (``apply_rename`` verify=True adds ``@final`` in
place and the suite stays green); and the never-fake-green guarantee (a subclassed
class is NOT finalized — the structural scan refuses the false claim a no-op
decorator's green suite would otherwise hide).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.final_marker import (
    add_final_decorator,
    class_has_final_decorator,
    finalizable_classes,
)
from app.execution.objectives.add_final import plan_add_final

# A leaf class never subclassed: gains a fresh ``from typing import final`` + @final.
_LEAF = (
    '"""A leaf module."""\n'
    "\n"
    "\n"
    "class Config:\n"
    "    value = 1\n"
    "\n"
    "\n"
    "def make() -> Config:\n"
    "    return Config()\n"
)

_PHRASE = "a class to seal as final"


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

def test_finalizable_detects_never_subclassed_class():
    assert finalizable_classes(_LEAF) == ["Config"]


def test_class_has_final_decorator_true_for_bare_final():
    cls = ast.parse("@final\nclass C:\n    pass\n").body[0]
    assert class_has_final_decorator(cls)


def test_class_has_final_decorator_true_for_dotted_typing_final():
    cls = ast.parse("@typing.final\nclass C:\n    pass\n").body[0]
    assert class_has_final_decorator(cls)


def test_class_has_final_decorator_false_when_absent():
    cls = ast.parse("@dataclass\nclass C:\n    pass\n").body[0]
    assert not class_has_final_decorator(cls)


# --- the core transform: rewrite --------------------------------------------

def test_adds_final_and_fresh_typing_import():
    out = add_final_decorator(_LEAF)
    assert out is not None
    lines = out.splitlines()
    assert lines[0] == '"""A leaf module."""'  # docstring stays first
    # The import lands at the canonical spot (after the docstring/__future__, before
    # the first real statement) and precedes the @final-decorated class.
    assert "from typing import final" in lines
    assert lines.index("from typing import final") < lines.index("@final")
    assert "@final" in out
    assert "class Config:" in out
    ast.parse(out)  # never lands broken Python


def test_final_decorator_sits_directly_above_the_class():
    out = add_final_decorator(_LEAF)
    assert out is not None
    # The @final line is immediately above the ``class Config:`` header.
    assert "\n@final\nclass Config:\n" in out


def test_widens_existing_typing_import_in_place():
    src = "from typing import Any\n\n\nclass C:\n    x: Any = 1\n"
    out = add_final_decorator(src)
    assert out is not None
    assert out.count("from typing import") == 1  # widened, not a second line
    assert out.splitlines()[0] == "from typing import Any, final"
    assert "@final" in out
    ast.parse(out)


def test_uses_dotted_typing_final_when_final_name_is_shadowed():
    # ``final`` is shadowed by a local def, but ``typing`` is bound bare — so the
    # dotted ``@typing.final`` is provable and used (and NO ``from typing import
    # final`` is added, which would re-bind the shadowed name).
    src = (
        "import typing\n"
        "\n"
        "\n"
        "def final(c):\n"
        "    return c\n"
        "\n"
        "\n"
        "class C:\n"
        "    pass\n"
    )
    out = add_final_decorator(src)
    assert out is not None
    assert "@typing.final" in out
    assert "from typing import final" not in out  # the shadow is not re-imported
    ast.parse(out)


def test_preserves_an_existing_decorator():
    src = "import dataclasses\n\n\n@dataclasses.dataclass\nclass C:\n    x: int = 1\n"
    out = add_final_decorator(src)
    assert out is not None
    # The existing decorator stays; @final is added directly above the class.
    assert "@dataclasses.dataclass\n@final\nclass C:" in out
    ast.parse(out)


def test_preserves_trailing_newline_absence():
    out = add_final_decorator("class C:\n    x = 1")
    assert out is not None and not out.endswith("\n")


# --- the whole-project used-as-base over-approximation ----------------------

def test_project_scan_can_only_add_refusals():
    # A class finalizable in isolation REFUSES once a SIBLING module subclasses it.
    assert finalizable_classes(_LEAF) == ["Config"]
    out = add_final_decorator(_LEAF, [_LEAF, "from m import Config\nclass S(Config):\n    pass\n"])
    assert out is None


def test_dotted_base_subclass_refused_cross_module():
    # A sibling module subclasses the leaf through a DOTTED base (``a.Config``); the
    # whole-project used-as-base scan (final ``.attr``) must see it and refuse.
    sub = "import a\n\n\nclass S(a.Config):\n    pass\n"
    assert finalizable_classes(_LEAF) == ["Config"]  # finalizable in isolation
    assert add_final_decorator(_LEAF, [_LEAF, sub]) is None


# --- the core transform: REFUSALS (honest no-ops) ---------------------------

def test_refuses_subclassed_class_same_module():
    src = "class Base:\n    pass\n\n\nclass Sub(Base):\n    pass\n"
    # ``Base`` is subclassed -> refused; ``Sub`` (a leaf) is finalizable.
    assert finalizable_classes(src) == ["Sub"]


def test_refuses_already_final_bare_idempotent():
    src = "from typing import final\n\n\n@final\nclass C:\n    pass\n"
    assert add_final_decorator(src) is None


def test_refuses_already_typing_final_idempotent():
    src = "import typing\n\n\n@typing.final\nclass C:\n    pass\n"
    assert add_final_decorator(src) is None


def test_refuses_protocol():
    src = "from typing import Protocol\n\n\nclass P(Protocol):\n    pass\n"
    assert add_final_decorator(src) is None


def test_refuses_subscripted_protocol():
    src = (
        "from typing import Protocol, TypeVar\n"
        "T = TypeVar('T')\n"
        "\n"
        "\n"
        "class P(Protocol[T]):\n"
        "    pass\n"
    )
    assert add_final_decorator(src) is None


def test_refuses_abc_base():
    src = "from abc import ABC\n\n\nclass A(ABC):\n    pass\n"
    assert add_final_decorator(src) is None


def test_refuses_dotted_abc_base():
    src = "import abc\n\n\nclass A(abc.ABC):\n    pass\n"
    assert add_final_decorator(src) is None


def test_refuses_abcmeta_metaclass():
    src = "from abc import ABCMeta\n\n\nclass A(metaclass=ABCMeta):\n    pass\n"
    assert add_final_decorator(src) is None


def test_refuses_enum_subclass():
    src = "from enum import Enum\n\n\nclass Color(Enum):\n    RED = 1\n"
    assert add_final_decorator(src) is None


def test_refuses_when_final_shadowed_and_no_usable_typing():
    # ``final`` is shadowed by a local def and ``typing`` is NOT bound bare — there
    # is no provable spelling of ``typing.final``, so refuse (round-16 lesson).
    src = "def final(c):\n    return c\n\n\nclass C:\n    pass\n"
    assert add_final_decorator(src) is None


def test_refuses_when_final_bound_to_another_module():
    # ``final`` is imported from a DIFFERENT module, so a bare ``@final`` would not
    # be ``typing.final`` — refuse (no fresh import would override a real binding).
    src = "from foo import final\n\n\nclass C:\n    pass\n"
    assert add_final_decorator(src) is None


def test_refuses_syntax_error():
    assert add_final_decorator("def (:\n") is None


# --- idempotency / determinism ----------------------------------------------

def test_idempotent_second_run_is_noop():
    once = add_final_decorator(_LEAF)
    assert once is not None
    assert add_final_decorator(once) is None  # 2nd run = byte-identical no-op


def test_deterministic_across_two_runs():
    a = add_final_decorator(_LEAF)
    b = add_final_decorator(_LEAF)
    assert a is not None and a == b


# --- registration / reachability --------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "add-final" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["add-final"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(_PHRASE) == "add-final"


def test_facet_reachability_parity_invariant_holds():
    # The standing 1:1 invariant: the facet map reaches EXACTLY the registered
    # objectives. Adding this objective to BOTH sides keeps the equality.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_substring_order_safe():
    # The new key must be neither a substring of, nor contain, any other key (with
    # a different objective) — else the first-match scan would mis-route.
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
    assert "add-final" in buckets["CONCRETE"]
    # No stale manifest name (a name with no live objective) was introduced.
    assert manifest_subset_of_registry() == []


def test_facet_phrase_lives_in_the_extension_points_ladder():
    from app.engine.idea_facets import _FACET_SUBASPECTS

    ladder = _FACET_SUBASPECTS["extension points"]
    assert _PHRASE in ladder
    assert ladder[0] == "the hook interface"  # originals still lead


# --- the plan: a never-subclassed class gets @final --------------------------

# A PRIVATE leaf class: not public surface, so the objective (which turns the
# public-surface refusal ON) still seals it.
_LEAF_PRIV = (
    '"""A leaf module."""\n'
    "\n"
    "\n"
    "class _Config:\n"
    "    value = 1\n"
    "\n"
    "\n"
    "def make() -> _Config:\n"
    "    return _Config()\n"
)


def test_plan_lands_final(tmp_path: Path):
    _project(tmp_path, "app/core.py", _LEAF_PRIV)
    plan = plan_add_final(str(tmp_path), "app/core.py")
    assert plan.ok
    new = plan.new_contents["app/core.py"]
    assert "@final" in new
    assert "from typing import final" in new
    assert plan.originals["app/core.py"] == _LEAF_PRIV  # original captured for rollback
    assert plan.edits_by_file["app/core.py"] == 1


def test_plan_uses_whole_project_used_as_base_scan(tmp_path: Path):
    # The class is never subclassed in its OWN module, but a SIBLING module
    # subclasses it — the whole-project scan must refuse.
    _project(tmp_path, "app/core.py", _LEAF)
    _project(tmp_path, "app/other.py",
             "from app.core import Config\n\n\nclass Sub(Config):\n    pass\n")
    plan = plan_add_final(str(tmp_path), "app/core.py")
    assert not plan.new_contents  # refused by the cross-module subclass


def test_plan_refuses_already_final(tmp_path: Path):
    _project(tmp_path, "app/core.py",
             "from typing import final\n\n\n@final\nclass Config:\n    pass\n")
    assert not plan_add_final(str(tmp_path), "app/core.py").new_contents


def test_plan_refuses_protocol_in_module(tmp_path: Path):
    _project(tmp_path, "app/iface.py",
             "from typing import Protocol\n\n\nclass P(Protocol):\n    pass\n")
    assert not plan_add_final(str(tmp_path), "app/iface.py").new_contents


def test_plan_refuses_test_file_input(tmp_path: Path):
    _project(tmp_path, "tests/test_x.py", _LEAF)
    assert not plan_add_final(str(tmp_path), "tests/test_x.py").new_contents


def test_plan_refuses_fixture_file_input(tmp_path: Path):
    _project(tmp_path, "fixtures/sample.py", _LEAF)
    assert not plan_add_final(str(tmp_path), "fixtures/sample.py").new_contents


def test_plan_refuses_non_library_config_file(tmp_path: Path):
    # Round-19 re-audit F4 (the CONFIRMED bug): ``@final`` had landed on a class in
    # ``docs/conf.py``. The shared single-file gate now refuses a NON-LIBRARY
    # packaging / config / task script (denylisted basename at ANY path) — nobody
    # imports ``docs/conf.py`` for an API, so sealing a class there is noise. An
    # honest no-op, no blocker. (``setup.py`` at the root is refused the same way.)
    _project(tmp_path, "docs/conf.py", _LEAF)
    _project(tmp_path, "setup.py", _LEAF)
    conf = plan_add_final(str(tmp_path), "docs/conf.py")
    setup = plan_add_final(str(tmp_path), "setup.py")
    assert not conf.new_contents and not conf.blockers
    assert not setup.new_contents and not setup.blockers


def test_plan_unreadable_path_is_noop(tmp_path: Path):
    plan = plan_add_final(str(tmp_path), "app/missing.py")
    assert not plan.new_contents
    assert not plan.blockers


# --- end-to-end: gated apply, real landing, suite stays green ----------------

def test_end_to_end_lands_final_and_keeps_green(tmp_path: Path):
    # A PRIVATE (underscore-prefixed) class in a package module: NOT public surface,
    # so the project-own subclass scan is authoritative and the seal lands. (The
    # public-surface refusal — added below — protects only published API names.)
    _suite_project(tmp_path)
    src = (
        '"""A leaf module."""\n'
        "\n"
        "\n"
        "class _Config:\n"
        "    value = 1\n"
        "\n"
        "\n"
        "def make() -> _Config:\n"
        "    return _Config()\n"
    )
    (tmp_path / "app" / "core.py").write_text(src, encoding="utf-8")
    (tmp_path / "tests" / "test_core.py").write_text(
        "from app.core import _Config, make\n"
        "def test_make():\n"
        "    assert make().value == 1\n"
        "def test_final_flag():\n"
        "    assert _Config.__final__ is True\n",
        encoding="utf-8")

    plan = plan_add_final(str(tmp_path), "app/core.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = (tmp_path / "app" / "core.py").read_text(encoding="utf-8")
    assert "@final" in landed  # the decorator LANDED
    assert "from typing import final" in landed
    # Behaviour preserved (proven green by the apply gate running the tests above):
    # the class still constructs and now carries ``__final__``.
    assert "class _Config:" in landed


def test_never_fake_green_subclassed_class_is_not_finalized(tmp_path: Path):
    # never-fake-green, STRUCTURAL form. ``@typing.final`` is a pure runtime no-op,
    # so adding it to a SUBCLASSED class would NOT break the suite — the suite would
    # stay green on a FALSE "final" claim (a type checker would later reject the
    # subclass). The honesty guard is therefore the whole-project subclass scan, not
    # the suite: ``_Base`` is provably subclassed, so the engine REFUSES to finalize
    # it. The no-op decorator can never be landed on a wrongly-claimed-final class.
    # (PRIVATE names, so the public-surface refusal does not also fire — this test
    # isolates the SUBCLASS guard.)
    src = (
        "class _Base:\n"
        "    pass\n"
        "\n"
        "\n"
        "class _Sub(_Base):\n"
        "    pass\n"
    )
    _project(tmp_path, "app/hier.py", src)
    plan = plan_add_final(str(tmp_path), "app/hier.py")
    # A rewrite IS proposed (the leaf ``_Sub`` is finalizable) ...
    assert plan.ok
    landed = plan.new_contents["app/hier.py"]
    # ... but ``_Base`` (subclassed) is NEVER marked @final — only the leaf is.
    tree = ast.parse(landed)
    finals = {n.name for n in tree.body
              if isinstance(n, ast.ClassDef) and class_has_final_decorator(n)}
    assert finals == {"_Sub"}, finals
    assert "@final\nclass _Base:" not in landed  # the false claim is never landed


# --- CONFIRMED code-review fixes (one regression test per soundness hole) ----

def test_fixA_not_sealed_when_subclassed_via_subscripted_base():
    # FIX A (soundness, shared used-as-base helper): a SUBSCRIPTED base
    # ``class Sub(Foo[int])`` really subclasses ``Foo`` — the base expr is an
    # ``ast.Subscript`` whose head ``Foo`` must be recorded as used-as-base. Sealing
    # ``Foo`` ``@typing.final`` would make a type checker REJECT ``class
    # Sub(Foo[int])`` (a false "leaf" claim), so the whole-project scan must see the
    # subscript head and REFUSE. (Previously ``_base_name`` returned None for a
    # Subscript, so ``Foo`` was never recorded and the seal wrongly landed.)
    foo_src = (
        "from typing import Generic, TypeVar\n"
        "T = TypeVar('T')\n"
        "\n"
        "\n"
        "class Foo(Generic[T]):\n"
        "    pass\n"
    )
    sub_src = "from m import Foo\n\n\nclass Sub(Foo[int]):\n    pass\n"
    # ``Foo`` is finalizable in isolation (its own module never subclasses it) ...
    assert finalizable_classes(foo_src) == ["Foo"]
    # ... but the whole-project scan sees ``class Sub(Foo[int])`` and refuses to seal.
    assert add_final_decorator(foo_src, [foo_src, sub_src]) is None


def test_fixA_not_sealed_when_subclassed_via_dotted_subscripted_base():
    # FIX A: the dotted-AND-subscripted form ``class Sub(pkg.Foo[int])`` — the
    # subscript head is a dotted ``Attribute`` (``pkg.Foo``) resolved to its final
    # ``.attr`` ``"Foo"``. Must also be recorded as used-as-base.
    foo_src = "class Foo:\n    pass\n"
    sub_src = "import pkg\nfrom typing import Any\n\n\nclass Sub(pkg.Foo[Any]):\n    pass\n"
    assert finalizable_classes(foo_src) == ["Foo"]
    assert add_final_decorator(foo_src, [foo_src, sub_src]) is None


def test_fixC_lands_final_on_parenthesized_multiline_typing_import():
    # FIX C (recall): the module's only typing import is the COMMON parenthesized
    # multi-line form. ``_existing_typing_import_index`` used to match the OPEN line
    # ``from typing import (`` and ``_widen_typing_import`` emitted the corrupt
    # ``from typing import (, final`` -> ``rejoin_guarded`` failed -> SILENT NO-OP.
    # The fix detects the un-cleanly-widenable form and inserts a fresh
    # ``from typing import final`` line instead. The seal must now LAND.
    src = (
        "from typing import (\n"
        "    Any,\n"
        "    Optional,\n"
        ")\n"
        "\n"
        "\n"
        "class Config:\n"
        "    value: Optional[Any] = None\n"
    )
    out = add_final_decorator(src)
    assert out is not None  # no longer a silent no-op
    assert "@final" in out
    ast.parse(out)  # valid Python
    # ``final`` is importable from typing at runtime — exec the module + use it.
    ns: dict[str, object] = {}
    exec(compile(out, "<fixC>", "exec"), ns)  # noqa: S102 - test-only
    assert ns["Config"].__final__ is True  # the decorator really bound typing.final
    # The original parenthesized block is untouched (not corrupted), and the fresh
    # import is a SECOND, valid from-import line.
    assert "from typing import (" in out
    assert "from typing import final" in out


def test_fixC_single_line_widen_is_unchanged_byte_for_byte():
    # FIX C must keep the already-tested single-line-widen case byte-identical: a
    # clean ``from typing import Any`` is widened in place to ``Any, final`` (NOT a
    # second line).
    src = "from typing import Any\n\n\nclass C:\n    x: Any = 1\n"
    out = add_final_decorator(src)
    assert out is not None
    assert out.count("from typing import") == 1  # widened in place, not duplicated
    assert out.splitlines()[0] == "from typing import Any, final"
    assert "@final" in out


def test_fixC_commented_typing_import_falls_back_to_fresh_line():
    # FIX C robustness: a typing import with a trailing ``#`` comment is NOT cleanly
    # widenable (splitting on ``,`` would swallow the comment into a name). Fall back
    # to a fresh ``from typing import final`` line; the commented line is untouched.
    src = "from typing import Any  # noqa: F401\n\n\nclass C:\n    x: Any = 1\n"
    out = add_final_decorator(src)
    assert out is not None
    assert "@final" in out
    ast.parse(out)
    assert "from typing import Any  # noqa: F401" in out  # comment preserved intact
    assert "from typing import final" in out  # fresh import added
    ns: dict[str, object] = {}
    exec(compile(out, "<fixC2>", "exec"), ns)  # noqa: S102 - test-only
    assert ns["C"].__final__ is True


def test_fixC_backslash_continued_typing_import_falls_back_to_fresh_line():
    # FIX C robustness: a backslash line-continuation also makes the import
    # un-cleanly-widenable on one line — fall back to a fresh import line.
    src = "from typing import Any, \\\n    Optional\n\n\nclass C:\n    x: Any = 1\n"
    out = add_final_decorator(src)
    assert out is not None
    assert "@final" in out
    ast.parse(out)
    assert "from typing import final" in out
    ns: dict[str, object] = {}
    exec(compile(out, "<fixC3>", "exec"), ns)  # noqa: S102 - test-only
    assert ns["C"].__final__ is True


def test_fixC_alias_on_single_line_typing_import_is_preserved_when_widened():
    # FIX C robustness: an ``X as Y`` alias on a clean single-line import is kept
    # VERBATIM through the widen (the alias item is preserved whole), so the re-emit
    # is value-identical and ``final`` is still added.
    src = "from typing import Any as A\n\n\nclass C:\n    x: A = 1\n"
    out = add_final_decorator(src)
    assert out is not None
    assert "@final" in out
    ast.parse(out)
    assert out.count("from typing import") == 1  # widened in place
    assert "Any as A" in out  # the alias survives
    ns: dict[str, object] = {}
    exec(compile(out, "<fixC4>", "exec"), ns)  # noqa: S102 - test-only
    assert ns["C"].__final__ is True


# --- FIX 1: a TEST-FILE subclass is a REAL one @final breaks for a type checker --

def test_fix1_not_sealed_when_subclassed_only_in_a_test_file(tmp_path: Path):
    # FIX 1 (soundness, test-INCLUSIVE scan). ``@typing.final`` is a pure runtime
    # no-op, so a class subclassed ONLY in a test (a mock / fake) stays GREEN even
    # though a TYPE CHECKER would reject that subclass once the class is sealed — a
    # false "final" the pytest suite can NEVER catch. The plan now scans EVERY
    # module (``all_module_sources``), tests INCLUDED, so the test-only subclass is
    # seen and the seal is REFUSED. (Under the old tests-EXCLUDING ``project_sources``
    # scan the mock was invisible and ``Config`` was wrongly sealed.)
    _project(tmp_path, "app/core.py", "class Config:\n    value = 1\n")
    _project(tmp_path, "tests/test_core.py",
             "from app.core import Config\n\n\nclass FakeConfig(Config):\n    pass\n")
    plan = plan_add_final(str(tmp_path), "app/core.py")
    assert not plan.new_contents  # the test-only subclass forbids the seal


def test_fix1_leaf_with_no_test_subclass_still_seals(tmp_path: Path):
    # FIX 1 must not over-refuse: a genuine (PRIVATE) leaf — used (not subclassed) in
    # a test — STILL seals under the test-inclusive scan. The test file merely
    # constructs the class, so it contributes no used-as-base name. (Private name, so
    # the public-surface refusal does not fire either.)
    _project(tmp_path, "app/core.py", _LEAF_PRIV)
    _project(tmp_path, "tests/test_core.py",
             "from app.core import _Config\n\n\ndef test_v():\n    assert _Config().value == 1\n")
    plan = plan_add_final(str(tmp_path), "app/core.py")
    assert plan.ok
    assert "@final" in plan.new_contents["app/core.py"]


def test_fix1_all_module_sources_includes_test_files():
    # FIX 1, the helper directly: ``all_module_sources`` is the test-INCLUSIVE
    # sibling of ``project_sources`` — it returns this_source even with no real
    # project shape (the single-module conservative floor), and is a public,
    # ``__all__``-exported name.
    import app.execution.freeze_dataclass as fz

    assert "all_module_sources" in fz.__all__
    only = fz.all_module_sources(".", "app/x.py", "class X:\n    pass\n")
    assert "class X:\n    pass\n" in only  # this_source always present
