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
