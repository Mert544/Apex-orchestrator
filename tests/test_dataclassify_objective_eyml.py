"""dataclassify develop objective — convert pure boilerplate ``__init__``
classes into ``@dataclass``.

Covers: objective registration / reachability + the facet route + the standing
``FACET_OBJECTIVE_MAP`` invariant; strict convertible-class detection; the
deterministic rewrite (order/annotation/default preserved); mutable defaults via
``field(default_factory=...)``; the full battery of REFUSALS (logic-bearing
``__init__``, ``*args``/``**kwargs``, base classes, an existing decorator, extra
statements, already-``@dataclass``); test/fixture refusal; behaviour-equivalence
(positional + keyword construction, defaults, attribute access); determinism;
idempotence; the suite-gated rollback on a synthetic regression; and the
end-to-end gated apply that lands real ``@dataclass`` code.
"""

from __future__ import annotations

from pathlib import Path

from app.execution.dataclass_rewrite import (
    convertible_classes,
    is_boilerplate_init,
    rewrite_dataclasses,
)
from app.execution.objectives.dataclassify import plan_dataclassify


# --- registration / reachability ---------------------------------------------

def test_objective_registers_and_is_available():
    from app.engine.objective_compiler import available_objectives

    assert "dataclassify" in set(available_objectives())


def test_objective_spec_is_callable():
    from app.engine.develop_registry import registered_specs

    spec = registered_specs()["dataclassify"]
    assert callable(spec.fitness) and callable(spec.moves)


def test_objective_is_reachable_from_a_facet():
    from app.engine.facet_develop import facet_to_objective

    assert facet_to_objective(
        "a boilerplate constructor to make a dataclass") == "dataclassify"


def test_facet_reachability_invariant_holds():
    # The standing invariant: the facet map reaches exactly the available
    # objectives. Adding dataclassify to both sides keeps the equality.
    from app.engine.facet_develop import FACET_OBJECTIVE_MAP
    from app.engine.objective_compiler import available_objectives

    assert set(FACET_OBJECTIVE_MAP.values()) == set(available_objectives())


def test_facet_phrase_is_in_the_vocabulary():
    # The routing phrase must genuinely live in the L3 ladder so the zoom can
    # reach it — not just in the objective map.
    from app.engine.idea_facets import _FACET_SUBASPECTS

    all_l3 = {p for subs in _FACET_SUBASPECTS.values() for p in subs}
    assert "a boilerplate constructor to make a dataclass" in all_l3


# --- strict convertible-class detection --------------------------------------

def _cls(src: str):
    import ast

    return ast.parse(src).body[0]


def test_detects_pure_boilerplate_class():
    src = (
        "class Point:\n"
        "    def __init__(self, x, y=0):\n"
        "        self.x = x\n"
        "        self.y = y\n"
    )
    assert is_boilerplate_init(_cls(src)) is True
    assert convertible_classes(src) == ["Point"]


def test_detects_with_init_docstring_tolerated():
    src = (
        "class D:\n"
        "    def __init__(self, a):\n"
        '        """build a D."""\n'
        "        self.a = a\n"
    )
    assert is_boilerplate_init(_cls(src)) is True


# --- the rewrite: order, annotations, defaults preserved ---------------------

def test_converts_pure_class_preserving_construction():
    src = (
        "class Point:\n"
        "    def __init__(self, x, y=0):\n"
        "        self.x = x\n"
        "        self.y = y\n"
    )
    out = rewrite_dataclasses(src)
    assert out is not None
    assert "@dataclass" in out
    assert "from dataclasses import dataclass" in out
    assert "def __init__" not in out  # boilerplate constructor deleted

    ns: dict = {}
    exec(out, ns)
    Point = ns["Point"]
    assert (Point(1).x, Point(1).y) == (1, 0)        # positional + default
    assert (Point(1, 2).x, Point(1, 2).y) == (1, 2)  # positional
    assert (Point(x=3, y=4).x, Point(x=3, y=4).y) == (3, 4)  # keyword


def test_preserves_parameter_annotations():
    src = (
        "class P:\n"
        "    def __init__(self, x: int, y: str = 'a'):\n"
        "        self.x = x\n"
        "        self.y = y\n"
    )
    out = rewrite_dataclasses(src)
    assert "x: int" in out
    assert "y: str = 'a'" in out


def test_field_order_is_preserved():
    src = (
        "class T:\n"
        "    def __init__(self, alpha, beta, gamma):\n"
        "        self.alpha = alpha\n"
        "        self.beta = beta\n"
        "        self.gamma = gamma\n"
    )
    out = rewrite_dataclasses(src)
    assert out.index("alpha:") < out.index("beta:") < out.index("gamma:")


def test_other_methods_are_preserved():
    src = (
        "class Box:\n"
        "    def __init__(self, w, h):\n"
        "        self.w = w\n"
        "        self.h = h\n"
        "\n"
        "    def area(self):\n"
        "        return self.w * self.h\n"
    )
    out = rewrite_dataclasses(src)
    ns: dict = {}
    exec(out, ns)
    assert ns["Box"](3, 4).area() == 12


# --- mutable defaults -> field(default_factory=...) --------------------------

def test_mutable_list_default_becomes_factory():
    src = (
        "class Config:\n"
        "    def __init__(self, items=[]):\n"
        "        self.items = items\n"
    )
    out = rewrite_dataclasses(src)
    assert "field(default_factory=list)" in out
    assert "from dataclasses import dataclass, field" in out

    ns: dict = {}
    exec(out, ns)
    Config = ns["Config"]
    a, b = Config(), Config()
    a.items.append(1)
    assert b.items == []  # no shared-mutable-default bug


def test_mutable_dict_and_set_defaults_become_factories():
    src = (
        "class S:\n"
        "    def __init__(self, d={}, s=set()):\n"
        "        self.d = d\n"
        "        self.s = s\n"
    )
    out = rewrite_dataclasses(src)
    assert "d: Any = field(default_factory=dict)" in out
    assert "s: Any = field(default_factory=set)" in out


# --- refusals: only PURE boilerplate qualifies (honest, never a guess) -------

def test_refuses_logic_bearing_init():
    src = (
        "class Validated:\n"
        "    def __init__(self, x):\n"
        "        if x < 0:\n"
        "            raise ValueError\n"
        "        self.x = x\n"
    )
    assert is_boilerplate_init(_cls(src)) is False
    assert rewrite_dataclasses(src) is None


def test_refuses_computed_attribute():
    src = (
        "class C:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
        "        self.doubled = x * 2\n"  # not a pure param copy
    )
    assert rewrite_dataclasses(src) is None


def test_refuses_renamed_assignment():
    src = (
        "class C:\n"
        "    def __init__(self, x):\n"
        "        self._x = x\n"  # attr name != param name
    )
    assert rewrite_dataclasses(src) is None


def test_refuses_varargs_and_kwargs():
    src = (
        "class C:\n"
        "    def __init__(self, *args, **kwargs):\n"
        "        self.args = args\n"
        "        self.kwargs = kwargs\n"
    )
    assert is_boilerplate_init(_cls(src)) is False
    assert rewrite_dataclasses(src) is None


def test_refuses_base_class():
    src = (
        "class Sub(Base):\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
    )
    assert is_boilerplate_init(_cls(src)) is False
    assert rewrite_dataclasses(src) is None


def test_refuses_existing_decorator():
    src = (
        "@register\n"
        "class C:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
    )
    assert is_boilerplate_init(_cls(src)) is False
    assert rewrite_dataclasses(src) is None


def test_already_dataclass_is_untouched_idempotent():
    src = (
        "from dataclasses import dataclass\n"
        "\n"
        "@dataclass\n"
        "class Q:\n"
        "    x: int\n"
    )
    assert rewrite_dataclasses(src) is None


def test_class_without_init_is_untouched():
    src = "class Plain:\n    VALUE = 1\n"
    assert rewrite_dataclasses(src) is None


def test_unparseable_source_is_refused():
    assert rewrite_dataclasses("class (:\n") is None
    assert convertible_classes("def (:\n") == []


# --- plan layer: refuses fixtures, no-op when nothing convertible ------------

def test_plan_converts_module(tmp_path: Path):
    rel = "app/models.py"
    (tmp_path / "app").mkdir()
    (tmp_path / rel).write_text(
        "class Point:\n"
        "    def __init__(self, x, y=0):\n"
        "        self.x = x\n"
        "        self.y = y\n",
        encoding="utf-8",
    )
    plan = plan_dataclassify(str(tmp_path), rel)
    assert "@dataclass" in plan.new_contents[rel]
    assert plan.edits_by_file[rel] == 1


def test_plan_refuses_test_file(tmp_path: Path):
    rel = "tests/test_thing.py"
    (tmp_path / "tests").mkdir()
    (tmp_path / rel).write_text(
        "class Point:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n",
        encoding="utf-8",
    )
    plan = plan_dataclassify(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_plan_noop_when_nothing_convertible(tmp_path: Path):
    rel = "app/logic.py"
    (tmp_path / "app").mkdir()
    (tmp_path / rel).write_text(
        "class V:\n"
        "    def __init__(self, x):\n"
        "        if x < 0:\n"
        "            raise ValueError\n"
        "        self.x = x\n",
        encoding="utf-8",
    )
    plan = plan_dataclassify(str(tmp_path), rel)
    assert not plan.new_contents


def test_plan_unreadable_module_is_noop(tmp_path: Path):
    plan = plan_dataclassify(str(tmp_path), "app/missing.py")
    assert not plan.new_contents and not plan.blockers


# --- determinism + idempotence -----------------------------------------------

def test_rewrite_is_deterministic():
    src = (
        "class Point:\n"
        "    def __init__(self, x, y=0):\n"
        "        self.x = x\n"
        "        self.y = y\n"
    )
    assert rewrite_dataclasses(src) == rewrite_dataclasses(src)


def test_rewrite_is_idempotent():
    src = (
        "class Point:\n"
        "    def __init__(self, x, y=0):\n"
        "        self.x = x\n"
        "        self.y = y\n"
    )
    once = rewrite_dataclasses(src)
    assert rewrite_dataclasses(once) is None  # re-running lands nothing


# --- end-to-end: gated apply lands @dataclass; a regression rolls back -------

def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_end_to_end_gated_apply_lands_dataclass(tmp_path: Path):
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    (tmp_path / "app" / "models.py").write_text(
        "class Point:\n"
        "    def __init__(self, x, y=0):\n"
        "        self.x = x\n"
        "        self.y = y\n",
        encoding="utf-8")
    # A test that constructs Point — the behaviour-equivalence contract.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_point.py").write_text(
        "from app.models import Point\n"
        "def test_point():\n"
        "    assert Point(1).y == 0\n"
        "    assert Point(1, 2).x == 1\n"
        "    assert Point(x=3, y=4).y == 4\n",
        encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="dataclassify",
                               apply=True, verify=True)
    assert result.steps and result.steps[0].verified is True

    text = (tmp_path / "app" / "models.py").read_text()
    assert "@dataclass" in text
    assert "def __init__" not in text  # the boilerplate constructor is gone


def test_end_to_end_rolls_back_on_synthetic_regression(tmp_path: Path):
    # A test that asserts the hand-written ``def __init__`` text is still in the
    # source file passes BEFORE the conversion and fails AFTER it (the rewrite
    # deletes that constructor) -> the engine must restore the file byte-for-byte.
    from app.engine.objective_compiler import compile_objective

    _suite_project(tmp_path)
    original = (
        "class Point:\n"
        "    def __init__(self, x, y=0):\n"
        "        self.x = x\n"
        "        self.y = y\n"
    )
    (tmp_path / "app" / "models.py").write_text(original, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_point.py").write_text(
        "from app.models import Point\n"
        "def test_source_keeps_init():\n"
        "    # the hand-written constructor text is present before conversion and\n"
        "    # absent after -> this regresses, forcing a rollback.\n"
        "    src = open(Point.__module__.replace('.', '/') + '.py').read()\n"
        "    assert 'def __init__' in src\n",
        encoding="utf-8")

    result = compile_objective(str(tmp_path), objective="dataclassify",
                               apply=True, verify=True)
    # The conversion regressed the suite -> rolled back, file restored verbatim.
    assert (tmp_path / "app" / "models.py").read_text() == original
    if result.steps:
        assert result.steps[0].verified is False
