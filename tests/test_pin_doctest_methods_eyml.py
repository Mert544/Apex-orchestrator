"""pin-doctest DESCENT into public class methods + class docstrings.

pin-doctest used to iterate only top-level ``tree.body`` functions, so a worked
``>>>`` example living in a class docstring or a public method docstring was run
by NOTHING — 0% covered. This deepening makes it descend into every top-level
PUBLIC class and land one additive gating test per qualifying symbol
(``test_<Class>_doctest`` for the class docstring, ``test_<Class>_<method>_doctest``
for each public method, plus ``__init__``), each re-running the symbol's live
``__doc__`` examples via the stdlib :mod:`doctest` runner.

Every NEW symbol clears the SAME prove-or-refuse gates the function path uses,
with name resolution generalized function -> ``Class`` / ``Class.method``:
has-an-enforceable-example, gate-1 green TODAY (in the module namespace), not
already pinned (DUAL KEY — the method leaf name OR its class name), not a
``set``/``dict``-repr (hash-seed-fragile) want, env-stable under varied
cwd/``$HOME``/``$TZ``/``$TMPDIR``/``PYTHONHASHSEED``. Additive NEW-file only; the
apply_rename full-suite gate + byte rollback compose on top. Off-by-default
byte-identity (function-only modules emit the EXACT current bytes) is asserted
here too.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.execution.cross_file_rename import apply_rename
from app.execution.objectives.pin_doctest import (
    _Symbol,
    _dedup_test_names,
    _examples_env_stable,
    _symbol_examples_pass,
    plan_pin_doctest,
)

# A public class with a green class-docstring example AND a green public method.
_CLASS = (
    "class C:\n"
    '    """A counter.\n\n'
    "    >>> C() is not None\n"
    "    True\n"
    '    """\n\n'
    "    def __init__(self):\n"
    "        self.n = 0\n\n"
    "    def value(self):\n"
    '        """Return the value.\n\n'
    "        >>> C().value()\n"
    "        0\n"
    '        """\n'
    "        return self.n\n"
)

# A public function (top-level) — used to assert source-order + byte-identity.
_FUNC = (
    "def double(n):\n"
    '    """Double n.\n\n'
    "    >>> double(3)\n"
    "    6\n"
    '    """\n'
    "    return n * 2\n"
)


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    (tmp_path / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(src, encoding="utf-8")
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def _suite_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='d'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def _gen(tmp_path: Path, rel: str = "app/calc.py") -> str:
    return plan_pin_doctest(str(tmp_path), rel).new_contents.get(
        f"tests/test_{Path(rel).stem}_doctest.py", "")


# --- pins a PUBLIC METHOD's green example ------------------------------------


def test_pins_public_method_green_example(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _CLASS)
    gen = _gen(tmp_path)
    assert "def test_C_value_doctest():" in gen
    # the live function is fetched off the class so its __doc__ runs in the module
    # namespace (where C lives, so ``C().value()`` resolves):
    assert "getattr(_module.C, 'value')" in gen
    assert "result.failed == 0" in gen


# --- pins a CLASS DOCSTRING example ------------------------------------------


def test_pins_class_docstring_example(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _CLASS)
    gen = _gen(tmp_path)
    assert "def test_C_doctest():" in gen
    assert "_run_enforceable(_module.C)" in gen


def test_class_symbol_before_its_methods(tmp_path: Path):
    # The class-docstring symbol is emitted before its methods (source order).
    _project(tmp_path, "app/calc.py", _CLASS)
    gen = _gen(tmp_path)
    assert gen.index("test_C_doctest") < gen.index("test_C_value_doctest")


# --- REFUSALS: honest under-claims -------------------------------------------


def test_refuses_private_underscore_method(tmp_path: Path):
    src = (
        "class C:\n"
        "    def _helper(self):\n"
        '        """\n        >>> C()._helper()\n        7\n        """\n'
        "        return 7\n"
    )
    _project(tmp_path, "app/calc.py", src)
    gen = _gen(tmp_path)
    assert "_helper" not in gen  # private — never pinned
    assert gen == ""  # nothing else qualifies -> a clean no-op


def test_pins_dunder_init_method(tmp_path: Path):
    # __init__ is the one underscore-name exception (a real public contract).
    src = (
        "class C:\n"
        "    def __init__(self):\n"
        '        """\n        >>> C() is not None\n        True\n        """\n'
        "        self.n = 0\n"
    )
    _project(tmp_path, "app/calc.py", src)
    gen = _gen(tmp_path)
    assert "def test_C___init___doctest():" in gen


def test_refuses_red_method_example(tmp_path: Path):
    # The method example FAILS against the real body -> never pin a red contract.
    red = _CLASS.replace("return self.n", "return self.n + 1")
    _project(tmp_path, "app/calc.py", red)
    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    gen = plan.new_contents.get("tests/test_calc_doctest.py", "")
    assert "def test_C_value_doctest():" not in gen  # red method dropped
    assert not plan.blockers


def test_refuses_set_repr_method_want(tmp_path: Path):
    # A method whose expected output is a SET repr is hash-seed-fragile -> refused.
    src = (
        "class C:\n"
        "    def letters(self):\n"
        '        """\n        >>> C().letters()\n        {\'a\', \'b\', \'c\'}\n        """\n'
        "        return set('abc')\n"
    )
    _project(tmp_path, "app/calc.py", src)
    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    assert "def test_C_letters_doctest():" not in plan.new_contents.get(
        "tests/test_calc_doctest.py", "")
    assert not plan.blockers


def test_refuses_dict_repr_class_docstring_want(tmp_path: Path):
    # A class docstring whose expected output is a multi-key DICT repr -> refused.
    src = (
        "class C:\n"
        '    """\n    >>> C().sizes()\n    {\'a\': 1, \'bb\': 2}\n    """\n'
        "    def sizes(self):\n"
        "        return {'a': 1, 'bb': 2}\n"
    )
    _project(tmp_path, "app/calc.py", src)
    gen = _gen(tmp_path)
    assert "def test_C_doctest():" not in gen  # the class-doc set/dict want refused


def test_refuses_home_dependent_method_end_to_end(tmp_path: Path):
    # A method whose doctest output reads $HOME -> "green" under the generation env
    # but RED under a different $HOME, so the env gate refuses it end-to-end.
    import os

    home = os.path.expanduser("~")
    src = (
        "import os\n"
        "class C:\n"
        "    def myhome(self):\n"
        f'        """\n        >>> C().myhome()\n        {home!r}\n        """\n'
        "        return os.path.expanduser('~')\n"
    )
    _project(tmp_path, "app/calc.py", src)
    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    assert "def test_C_myhome_doctest():" not in plan.new_contents.get(
        "tests/test_calc_doctest.py", "")
    assert not plan.blockers


# --- DUAL-KEY duplicate refusal ----------------------------------------------


def test_dual_key_refusal_when_method_name_pinned(tmp_path: Path):
    # A test_*.py imports the module AND references the METHOD leaf name -> the
    # method's contract is (effectively) exercised, so don't land a duplicate gate.
    _project(tmp_path, "app/calc.py", _CLASS)
    _project(tmp_path, "tests/test_calc.py",
             "from app.calc import C\n"
             "def test_v():\n    assert C().value() == 0\n")
    gen = _gen(tmp_path)
    assert "def test_C_value_doctest():" not in gen


def test_dual_key_refusal_when_class_name_pinned(tmp_path: Path):
    # A test_*.py references the CLASS name (not the method) -> the conservative
    # dual key still suppresses the method pin (the class is exercised).
    _project(tmp_path, "app/calc.py", _CLASS)
    _project(tmp_path, "tests/test_calc.py",
             "from app.calc import C\n"
             "def test_c():\n    assert C() is not None\n")
    gen = _gen(tmp_path)
    assert "def test_C_value_doctest():" not in gen
    assert "def test_C_doctest():" not in gen


# --- mixed module: a function AND a class method, byte-identity preserved -----


def test_mixed_module_pins_both_function_first(tmp_path: Path):
    src = _FUNC + "\n\n" + _CLASS
    _project(tmp_path, "app/calc.py", src)
    gen = _gen(tmp_path)
    assert "def test_double_doctest():" in gen      # the function pinned
    assert "def test_C_value_doctest():" in gen      # the method pinned
    # the function test is emitted in source order BEFORE the class methods:
    assert gen.index("test_double_doctest") < gen.index("test_C_value_doctest")
    # the function portion keeps its exact current shape (byte-identity markers):
    assert "_run_enforceable(_module.double)" in gen


def test_function_only_module_is_byte_identical(tmp_path: Path):
    # The off-by-default byte-identity invariant: a module with NO qualifying
    # class/method emits the EXACT current function-only bytes (helper uses
    # ``func.__name__``, NOT the getattr-safe form).
    _project(tmp_path, "app/calc.py", _FUNC)
    gen = _gen(tmp_path)
    assert "func.__name__," in gen
    assert 'getattr(func, "__name__"' not in gen
    assert "def test_double_doctest():" in gen
    assert "_run_enforceable(_module.double)" in gen


# --- determinism --------------------------------------------------------------


def test_deterministic_across_two_runs(tmp_path: Path):
    # Two classes + methods: classes in source order, methods in lineno order.
    src = (
        "class B:\n"
        "    def beta(self):\n"
        '        """\n        >>> B().beta()\n        2\n        """\n'
        "        return 2\n\n"
        "class A:\n"
        "    def gamma(self):\n"
        '        """\n        >>> A().gamma()\n        3\n        """\n'
        "        return 3\n"
        "    def alpha(self):\n"
        '        """\n        >>> A().alpha()\n        1\n        """\n'
        "        return 1\n"
    )
    _project(tmp_path, "app/calc.py", src)
    one = _gen(tmp_path)
    two = _gen(tmp_path)
    assert one and one == two
    # classes in SOURCE order (B before A), methods in LINENO order (gamma<alpha):
    assert one.index("test_B_beta") < one.index("test_A_gamma")
    assert one.index("test_A_gamma") < one.index("test_A_alpha")


def test_generated_source_parses(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _CLASS)
    ast.parse(_gen(tmp_path))  # the generated test source is valid Python


# --- the gates, unit-tested directly -----------------------------------------


def test_symbol_examples_pass_true_for_green_method(tmp_path: Path):
    src = _CLASS
    lineno = next(
        child.lineno
        for node in ast.parse(src).body if isinstance(node, ast.ClassDef)
        for child in node.body
        if getattr(child, "name", None) == "value")
    assert _symbol_examples_pass(src, "value", lineno) is True


def test_symbol_examples_pass_false_for_red_method(tmp_path: Path):
    src = _CLASS.replace("return self.n", "return self.n + 1")
    lineno = next(
        child.lineno
        for node in ast.parse(src).body if isinstance(node, ast.ClassDef)
        for child in node.body
        if getattr(child, "name", None) == "value")
    assert _symbol_examples_pass(src, "value", lineno) is False


def test_examples_env_stable_true_for_stable_method(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _CLASS)
    assert _examples_env_stable(tmp_path, "app.calc", "C.value") is True


def test_examples_env_stable_true_for_class_docstring(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _CLASS)
    assert _examples_env_stable(tmp_path, "app.calc", "C") is True


def test_examples_env_stable_false_for_unimportable_method(tmp_path: Path):
    assert _examples_env_stable(tmp_path, "app.nope", "C.value") is False


# --- end-to-end: gated apply lands the method test, suite stays green ---------


def test_end_to_end_lands_method_test_and_keeps_green(tmp_path: Path):
    _suite_project(tmp_path)
    (tmp_path / "app" / "calc.py").write_text(_CLASS, encoding="utf-8")
    (tmp_path / "tests" / "test_existing.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")

    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is True
    assert result.get("rolled_back") in (False, None)

    landed = tmp_path / "tests" / "test_calc_doctest.py"
    assert landed.exists()
    text = landed.read_text(encoding="utf-8")
    assert "def test_C_value_doctest():" in text
    assert "def test_C_doctest():" in text
    assert "result.failed == 0" in text


def test_end_to_end_auto_rollback_when_method_goes_red(tmp_path: Path):
    # never-fake-green at the engine level: break the method body AFTER the plan is
    # built but BEFORE apply, so the about-to-land method test fails under the
    # suite -> the verified apply rolls the create back, leaving nothing pinned.
    _suite_project(tmp_path)
    (tmp_path / "app" / "calc.py").write_text(_CLASS, encoding="utf-8")
    plan = plan_pin_doctest(str(tmp_path), "app/calc.py")
    assert plan.ok
    (tmp_path / "app" / "calc.py").write_text(
        _CLASS.replace("return self.n", "return self.n + 1"), encoding="utf-8")
    result = apply_rename(str(tmp_path), plan, verify=True, impact_scope=False)
    assert result.get("applied") is False
    assert result.get("rolled_back") is True
    landed = tmp_path / "tests" / "test_calc_doctest.py"
    surviving = landed.read_text(encoding="utf-8") if landed.exists() else ""
    assert surviving == ""  # a red contract is never left pinned


# --- test-name UNIQUENESS: colliding flattened names get distinct pinned tests


def _def_names(gen: str) -> list[str]:
    return re.findall(r"^def (test_\w+)\(", gen, re.MULTILINE)


# A function ``C_value`` and class ``C`` method ``value`` BOTH flatten to the same
# ``test_C_value`` under the underscore renderer — the previously-impossible-to-
# collide path the descent opened up.
_COLLIDING_FUNC_VS_METHOD = (
    "def C_value():\n"
    '    """One.\n\n'
    "    >>> C_value()\n"
    "    1\n"
    '    """\n'
    "    return 1\n\n\n"
    "class C:\n"
    "    def value(self):\n"
    '        """Two.\n\n'
    "        >>> C().value()\n"
    "        0\n"
    '        """\n'
    "        return 0\n"
)

# class ``A_b`` method ``c`` and class ``A`` method ``b_c`` BOTH flatten to
# ``test_A_b_c`` — a method-vs-method collision across two classes.
_COLLIDING_METHOD_VS_METHOD = (
    "class A_b:\n"
    "    def c(self):\n"
    '        """One.\n\n'
    "        >>> A_b().c()\n"
    "        1\n"
    '        """\n'
    "        return 1\n\n\n"
    "class A:\n"
    "    def b_c(self):\n"
    '        """Two.\n\n'
    "        >>> A().b_c()\n"
    "        2\n"
    '        """\n'
    "        return 2\n"
)


def test_colliding_function_and_method_get_distinct_pinned_tests(tmp_path: Path):
    # Both verified contracts must be pinned under DISTINCT def names — the renderer
    # must never emit two identical ``def test_C_value_doctest()`` (the second would
    # shadow the first at collection, silently dropping one contract).
    _project(tmp_path, "app/calc.py", _COLLIDING_FUNC_VS_METHOD)
    gen = _gen(tmp_path)
    names = _def_names(gen)
    assert len(names) == 2  # both symbols pinned (neither dropped)
    assert len(set(names)) == 2  # ...and under distinct names
    # the function and the method are BOTH actually run (distinct accessors present):
    assert "_run_enforceable(_module.C_value)" in gen
    assert "_run_enforceable(getattr(_module.C, 'value'))" in gen
    # disambiguation is by source lineno, so each name is stably tied to its def:
    assert all(re.search(r"_l\d+_doctest$", n) for n in names)
    ast.parse(gen)  # still valid Python


def test_colliding_methods_across_classes_get_distinct_pinned_tests(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _COLLIDING_METHOD_VS_METHOD)
    gen = _gen(tmp_path)
    names = _def_names(gen)
    assert len(names) == 2 and len(set(names)) == 2
    assert "_run_enforceable(getattr(_module.A_b, 'c'))" in gen
    assert "_run_enforceable(getattr(_module.A, 'b_c'))" in gen


def test_collision_fix_is_deterministic(tmp_path: Path):
    _project(tmp_path, "app/calc.py", _COLLIDING_FUNC_VS_METHOD)
    assert _gen(tmp_path) == _gen(tmp_path)  # two runs, byte-identical


def test_dedup_test_names_leaves_unique_names_untouched():
    # The byte-identity guard: with NO collision the records pass through UNCHANGED
    # (so a function-only module renders exactly its current bytes).
    syms = [
        _Symbol("f", 1, "f", "test_f", "_module.f"),
        _Symbol("g", 5, "g", "test_g", "_module.g"),
    ]
    assert _dedup_test_names(syms) == syms


def test_dedup_test_names_disambiguates_only_the_colliding_pair():
    # A unique name is untouched; only the two that collide gain the ``_l<lineno>``
    # suffix — and they become distinct.
    syms = [
        _Symbol("C_value", 2, "C_value", "test_C_value", "_module.C_value"),
        _Symbol("uniq", 7, "uniq", "test_uniq", "_module.uniq"),
        _Symbol("value", 12, "C.value", "test_C_value",
                "getattr(_module.C, 'value')"),
    ]
    out = _dedup_test_names(syms)
    assert out[1].test_name == "test_uniq"  # untouched
    assert out[0].test_name == "test_C_value_l2"
    assert out[2].test_name == "test_C_value_l12"
    assert out[0].test_name != out[2].test_name
