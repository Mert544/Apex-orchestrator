"""Tests for the characterization-test generator (app/execution/test_shield.py)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from app.execution.test_shield import (
    ShieldTest,
    generate_characterization_test,
    write_shield_test,
)


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body), encoding="utf-8")


def _make_pkg(root: Path, rel: str, body: str) -> str:
    """Write a module at ``rel`` as part of an importable ``mypkg`` package."""
    _write(root, "mypkg/__init__.py", "")
    _write(root, rel, body)
    return rel


def test_simple_function_is_exercised(tmp_path):
    rel = _make_pkg(tmp_path, "mypkg/calc.py", "def add(a, b):\n    return a + b\n")
    shield = generate_characterization_test(tmp_path, rel)

    assert isinstance(shield, ShieldTest)
    assert shield.module == "mypkg.calc"
    assert shield.test_path == "tests/test_calc.py"
    assert shield.functions == ["add"]
    assert "import mypkg.calc" in shield.content
    assert "mypkg.calc.add" in shield.content
    assert "def test_calc_imports" in shield.content
    assert "def test_calc_add_characterization" in shield.content


def test_generated_test_passes_when_run(tmp_path):
    rel = _make_pkg(tmp_path, "mypkg/calc.py", "def add(a, b):\n    return a + b\n")
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None

    path = write_shield_test(tmp_path, shield)
    assert (tmp_path / path).exists()

    # Run the generated test in a subprocess against the synthetic project so
    # the import path resolves to the tmp project (root on sys.path).
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", path, "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_only_main_falls_back_to_import_smoke(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/cli.py",
        """
        import sys

        def main():
            print(sys.argv)
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)

    assert shield is not None
    assert shield.functions == []  # main() is never exercised
    assert "def test_cli_imports" in shield.content
    assert "main(" not in shield.content
    # Import-smoke only: no characterization body for any function.
    assert "_characterization" not in shield.content


def test_kwargs_and_decorated_functions_are_skipped(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/mixed.py",
        """
        import functools

        def flexible(*args, **kwargs):
            return args

        @functools.cache
        def decorated(x):
            return x

        async def fetch():
            return 1

        def plain(n):
            return n
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)

    assert shield is not None
    # *args/**kwargs, decorated, and async are all skipped; only `plain` runs.
    assert shield.functions == ["plain"]
    assert "flexible(" not in shield.content
    assert "decorated(" not in shield.content
    assert "fetch(" not in shield.content


def test_existing_test_file_is_not_clobbered(tmp_path):
    rel = _make_pkg(tmp_path, "mypkg/calc.py", "def add(a, b):\n    return a + b\n")
    _write(tmp_path, "tests/test_calc.py", "# hand-written, do not touch\n")

    assert generate_characterization_test(tmp_path, rel) is None


def test_write_shield_test_refuses_to_clobber(tmp_path):
    rel = _make_pkg(tmp_path, "mypkg/calc.py", "def add(a, b):\n    return a + b\n")
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None

    write_shield_test(tmp_path, shield)
    try:
        write_shield_test(tmp_path, shield)
    except FileExistsError:
        pass
    else:  # pragma: no cover - the guard must fire
        raise AssertionError("write_shield_test should refuse to clobber")


def test_deterministic_content(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/many.py",
        """
        def alpha(s: str):
            return s

        def beta(n: int, flag: bool = True):
            return n

        def gamma(x):
            return x
        """,
    )
    first = generate_characterization_test(tmp_path, rel)
    second = generate_characterization_test(tmp_path, rel)

    assert first is not None and second is not None
    assert first.content == second.content
    assert first.functions == second.functions == ["alpha", "beta", "gamma"]
    # Document order is preserved (not sorted).
    assert first.content.index("alpha") < first.content.index("beta") < first.content.index("gamma")


def test_synthesized_args_match_annotations(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/typed.py",
        """
        def typed(a: int, b: str, c: list, d: bool):
            return (a, b, c, d)
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "fn(0, '', [], False)" in shield.content


def test_defaulted_and_optional_params(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/defaults.py",
        """
        def f(a: int, b: int = 5, c: str | None = None):
            return a
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # Defaulted params are omitted; only the required `a` is synthesized.
    assert "fn(0)" in shield.content


def test_required_keyword_only_arg_is_synthesized(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/kwonly.py",
        """
        def g(a: int, *, mode: str):
            return mode
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "fn(0, mode='')" in shield.content


def test_unannotated_required_arg_defaults_to_none(tmp_path):
    rel = _make_pkg(tmp_path, "mypkg/un.py", "def h(x, y):\n    return x\n")
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # Unannotated params are safe here (call is try/except wrapped) -> None.
    assert "fn(None, None)" in shield.content


def test_private_functions_are_ignored(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/priv.py",
        """
        def _helper(x):
            return x

        def public(x):
            return x
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert shield.functions == ["public"]


def test_test_and_fixture_targets_are_refused(tmp_path):
    _write(tmp_path, "tests/test_thing.py", "def add(a, b):\n    return a + b\n")
    assert generate_characterization_test(tmp_path, "tests/test_thing.py") is None


def test_dunder_module_is_refused(tmp_path):
    _make_pkg(tmp_path, "mypkg/__init__.py", "")
    assert generate_characterization_test(tmp_path, "mypkg/__init__.py") is None


def test_non_python_and_missing_source_return_none(tmp_path):
    assert generate_characterization_test(tmp_path, "mypkg/notes.txt") is None
    assert generate_characterization_test(tmp_path, "mypkg/ghost.py") is None


def test_unparseable_source_returns_none(tmp_path):
    rel = _make_pkg(tmp_path, "mypkg/broken.py", "def oops(:\n    pass\n")
    assert generate_characterization_test(tmp_path, rel) is None


def test_empty_module_falls_back_to_import_smoke(tmp_path):
    rel = _make_pkg(tmp_path, "mypkg/empty.py", '"""No functions here."""\n')
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert shield.functions == []
    assert "def test_empty_imports" in shield.content
    assert "_characterization" not in shield.content


# --- public classes ---------------------------------------------------------


def test_public_class_is_constructed_and_methods_exercised(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/counter.py",
        """
        class Counter:
            def __init__(self, start=0):
                self.n = start

            def inc(self):
                self.n += 1
                return self.n
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "Counter" in shield.functions
    assert "Counter.inc" in shield.functions
    assert "def test_counter_Counter_characterization" in shield.content
    # `start` is defaulted -> omitted; the constructor takes no synthesized arg.
    assert "cls = mypkg.counter.Counter" in shield.content
    assert "instance = cls()" in shield.content
    assert "method = getattr(instance, 'inc', None)" in shield.content


def test_generated_class_test_passes_when_run(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/counter.py",
        """
        class Counter:
            def __init__(self, start=0):
                self.n = start

            def inc(self):
                self.n += 1
                return self.n
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None

    path = write_shield_test(tmp_path, shield)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", path, "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_class_with_required_complex_arg_is_constructed_with_none(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/needy.py",
        """
        class Service:
            def __init__(self, backend):
                self.backend = backend

            def run(self):
                return self.backend
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # `backend` is a required, unannotated arg -> synthesized as None (the
    # honest sample). Construction is try/except wrapped, so it is exercised.
    assert "Service" in shield.functions
    assert "cls = mypkg.needy.Service" in shield.content
    assert "instance = cls(None)" in shield.content


def test_class_with_required_kwargs_init_is_skipped(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/openinit.py",
        """
        class Flexible:
            def __init__(self, **kwargs):
                self.kw = kwargs

            def go(self):
                return self.kw
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert shield.functions == []
    assert "Flexible(" not in shield.content
    assert "_characterization" not in shield.content


def test_decorated_class_is_skipped(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/decorated.py",
        """
        import dataclasses

        @dataclasses.dataclass
        class Point:
            x: int = 0

            def shift(self):
                return self.x
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # A decorator may change construction -> the class is not exercised.
    assert shield.functions == []
    assert "Point(" not in shield.content
    assert "_characterization" not in shield.content


def test_private_class_is_ignored(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/priv_cls.py",
        """
        class _Hidden:
            def run(self):
                return 1

        class Public:
            def run(self):
                return 2
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "Public" in shield.functions
    assert "Public.run" in shield.functions
    assert "_Hidden" not in shield.functions


def test_class_dunders_and_private_methods_are_not_exercised(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/dunders.py",
        """
        class Box:
            def __init__(self):
                self.v = 0

            def __len__(self):
                return self.v

            def _secret(self):
                return 1

            def value(self):
                return self.v
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert shield.functions == ["Box", "Box.value"]
    assert "Box.__len__" not in shield.functions
    assert "Box._secret" not in shield.functions


def test_method_with_open_contract_is_skipped(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/openmethod.py",
        """
        class Bag:
            def __init__(self):
                self.items = []

            def add(self, *args, **kwargs):
                self.items.append(args)

            def size(self):
                return len(self.items)
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # The class constructs; `add` has *args/**kwargs -> skipped; `size` runs.
    assert "Bag" in shield.functions
    assert "Bag.size" in shield.functions
    assert "Bag.add" not in shield.functions


def test_module_with_only_a_class_is_not_import_smoke(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/onlyclass.py",
        """
        class Widget:
            def render(self):
                return "ok"
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # No functions, but a constructible class -> NOT a pure import-smoke test.
    assert shield.functions == ["Widget", "Widget.render"]
    assert "_characterization" in shield.content


def test_class_with_required_synthesizable_args_is_constructed(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/typedinit.py",
        """
        class Greeter:
            def __init__(self, name: str, times: int):
                self.name = name
                self.times = times

            def greet(self):
                return self.name * self.times
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "Greeter" in shield.functions
    assert "cls = mypkg.typedinit.Greeter" in shield.content
    assert "instance = cls('', 0)" in shield.content


def test_class_with_method_args_synthesizes_them(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/methodargs.py",
        """
        class Adder:
            def add(self, a: int, b: int):
                return a + b
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "Adder" in shield.functions
    assert "Adder.add" in shield.functions
    assert "method(0, 0)" in shield.content


def test_functions_and_classes_coexist_in_document_order(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/mixedmod.py",
        """
        def first():
            return 1

        class Thing:
            def go(self):
                return 2
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert shield.functions == ["first", "Thing", "Thing.go"]


def test_class_determinism(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/detcls.py",
        """
        class A:
            def m(self):
                return 1

        class B:
            def __init__(self, x: int):
                self.x = x

            def n(self):
                return self.x
        """,
    )
    first = generate_characterization_test(tmp_path, rel)
    second = generate_characterization_test(tmp_path, rel)
    assert first is not None and second is not None
    assert first.content == second.content
    assert first.functions == second.functions == ["A", "A.m", "B", "B.n"]


# --- value oracles ----------------------------------------------------------


def _run_generated(tmp_path, path):
    """Run the generated test against the synthetic project (root on sys.path)."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", path, "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_pure_function_gets_a_value_oracle(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/pure.py",
        """
        def add(a: int, b: int):
            return a + b
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # add(0, 0) == 0 is captured as a real value oracle (no try/except smoke).
    assert "assert fn(0, 0) == 0" in shield.content
    assert "it returns the captured value" in shield.content
    # The captured-value test is NOT a smoke shape check.
    assert "no value oracle" not in shield.content


def test_value_oracle_test_passes_when_run(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/pure.py",
        """
        def add(a: int, b: int):
            return a + b
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_string_return_value_oracle(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/greet.py",
        """
        def hello(name: str):
            return "hi " + name
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # The captured str is rendered as a Python literal via repr.
    assert "assert fn('') == 'hi '" in shield.content
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_container_return_value_oracle(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/cont.py",
        """
        def pair(n: int):
            return {"lo": n, "hi": n + 1}
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # A dict of literals round-trips to a value oracle.
    assert "assert fn(0) == {'lo': 0, 'hi': 1}" in shield.content
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_non_literal_return_falls_back_to_smoke(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/obj.py",
        """
        class Box:
            pass

        def build():
            return Box()
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "build" in shield.functions
    # A custom object is not a simple literal -> smoke fallback, no value oracle.
    assert "no value oracle" in shield.content
    assert "result = fn()" in shield.content
    assert "== mypkg.obj.Box" not in shield.content
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_function_that_raises_on_synthesized_args_falls_back_to_smoke(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/boom.py",
        """
        def explode(x: int):
            raise ValueError("nope")
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert shield.functions == ["explode"]
    # The call raises -> no value oracle, the existing smoke body is emitted.
    assert "assert fn(0) ==" not in shield.content
    assert "it is callable and runs" in shield.content
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_none_return_gets_a_value_oracle(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/noret.py",
        """
        def nothing(x: int):
            return None
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # None is a simple literal -> the oracle pins it exactly.
    assert "assert fn(0) == None" in shield.content
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_unannotated_arg_that_breaks_the_call_falls_back_to_smoke(tmp_path):
    # add(None, None) raises TypeError -> no oracle; smoke body is emitted.
    rel = _make_pkg(tmp_path, "mypkg/un2.py", "def add(a, b):\n    return a + b\n")
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "assert fn(None, None) ==" not in shield.content
    assert "result = fn(None, None)" in shield.content


def test_nan_return_does_not_get_a_value_oracle(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/nan.py",
        """
        def bad(x: int):
            return float("nan")
        """,
    )
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    # NaN is never equal to itself, so `== nan` is not a passing oracle -> smoke.
    assert "assert fn(0) ==" not in shield.content
    assert "no value oracle" in shield.content
    path = write_shield_test(tmp_path, shield)
    proc = _run_generated(tmp_path, path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_value_oracle_is_deterministic(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/detoracle.py",
        """
        def add(a: int, b: int):
            return a + b
        """,
    )
    first = generate_characterization_test(tmp_path, rel)
    second = generate_characterization_test(tmp_path, rel)
    assert first is not None and second is not None
    assert first.content == second.content
    assert "assert fn(0, 0) == 0" in first.content


def test_capture_leaves_sys_modules_and_path_unchanged(tmp_path):
    rel = _make_pkg(
        tmp_path,
        "mypkg/clean.py",
        """
        def add(a: int, b: int):
            return a + b
        """,
    )
    modules_before = dict(sys.modules)
    path_before = list(sys.path)
    shield = generate_characterization_test(tmp_path, rel)
    assert shield is not None
    assert "assert fn(0, 0) == 0" in shield.content  # the import actually ran
    # The controlled import leaves no trace in sys.modules or sys.path.
    assert sys.path == path_before
    assert set(sys.modules) == set(modules_before)
