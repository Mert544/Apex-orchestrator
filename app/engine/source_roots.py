"""Project-layout source-root detection — the single shared utility.

A test (or a real caller) on a ``src/`` layout imports the package WITHOUT the
root prefix: pytest ``pythonpath=src`` / an installed package strips it, so
``src/mylib/calc.py`` is importable as ``mylib.calc``, not ``src.mylib.calc``.
Two independent features need to know that leading source root so they don't go
blind on such a layout:

* **mutation-impact scoping** (:mod:`app.engine.mutation_tester`) — to map a
  mutated module to every dotted import target a test could reach it by;
* **wire-exports** (:mod:`app.execution.export_wiring`) — so the import oracle
  validates a package under its REAL top-level path (``pkg`` with ``src/`` on the
  path), not ``src.pkg``.

Rather than replicate the detection in each, both import :func:`source_roots`
from here. The logic is byte-identical to the original
``mutation_tester._source_roots`` it was extracted from.

Determinism, stdlib-only, best-effort: the de-facto ``src/`` convention is ALWAYS
a root (no config needed), plus any root declared in ``pyproject.toml``
(``[tool.pytest.ini_options] pythonpath`` / ``[tool.setuptools] package-dir`` /
``[tool.setuptools.packages.find] where``). A missing/unparseable pyproject (or
absent ``tomllib``) degrades to the ``src/`` convention alone. Output is sorted,
so the same project always yields the same roots; nothing here touches the clock
or randomness.
"""

from __future__ import annotations

from pathlib import Path

try:  # py311+: stdlib; older: graceful no-pyproject-parse degrade
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on <3.11
    tomllib = None  # type: ignore[assignment]

__all__ = ["source_roots"]


def source_roots(project_root: Path) -> list[str]:
    """The strippable source-root path segments for ``project_root``, deterministic
    and sorted. A test on a ``src/`` (or pyproject-declared) layout imports the
    package WITHOUT the root prefix (pytest ``pythonpath=src`` / an installed
    package strips it), so ``src/mylib/calc.py`` is importable as ``mylib.calc``,
    not ``src.mylib.calc`` — a naive path-join would miss that and leave
    impact-scoping (and the wire-exports oracle) blind.

    Two sources, both best-effort and stdlib-only:

    * the de-facto ``src/`` convention is ALWAYS a root (no config needed);
    * roots declared in ``pyproject.toml`` — ``[tool.pytest.ini_options]
      pythonpath`` and ``[tool.setuptools] package-dir`` / ``[tool.setuptools.
      packages.find] where`` — so a custom root (``lib``) is honored too.

    A missing/unparseable pyproject (or absent ``tomllib``) degrades to the
    ``src/`` convention alone. The first path component of each declared root is
    used (a root like ``"./src"`` or ``"src/pkg"`` contributes ``"src"``)."""
    roots = {"src"}
    for declared in _pyproject_roots(project_root):
        head = _first_path_segment(declared)
        if head:
            roots.add(head)
    return sorted(roots)


def _first_path_segment(value: str) -> str | None:
    """The leading path component of a declared root (``"./src"`` -> ``"src"``,
    ``"src/pkg"`` -> ``"src"``, ``"."``/``""`` -> ``None``). Best-effort and pure;
    a non-str or empty value yields ``None``."""
    if not isinstance(value, str):
        return None
    parts = [p for p in value.replace("\\", "/").split("/") if p and p != "."]
    return parts[0] if parts else None


def _pyproject_roots(project_root: Path) -> list[str]:
    """The raw source-root strings declared in ``project_root``'s ``pyproject.toml``
    — ``[tool.pytest.ini_options] pythonpath``, ``[tool.setuptools] package-dir``
    (its values), and ``[tool.setuptools.packages.find] where``. Best-effort: a
    missing file, absent ``tomllib``, or a parse error yields ``[]``. Deterministic
    (source order of the parsed lists)."""
    path = project_root / "pyproject.toml"
    if tomllib is None or not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return []
    out: list[str] = []
    out.extend(_pytest_pythonpath(tool))
    out.extend(_setuptools_roots(tool))
    return out


def _pytest_pythonpath(tool: dict) -> list[str]:
    """The ``[tool.pytest.ini_options] pythonpath`` entries (a str or list of str)."""
    ini = tool.get("pytest", {})
    ini = ini.get("ini_options", {}) if isinstance(ini, dict) else {}
    return _as_str_list(ini.get("pythonpath")) if isinstance(ini, dict) else []


def _setuptools_roots(tool: dict) -> list[str]:
    """The setuptools-declared roots: ``[tool.setuptools] package-dir`` values and
    ``[tool.setuptools.packages.find] where`` entries."""
    setup = tool.get("setuptools")
    if not isinstance(setup, dict):
        return []
    out: list[str] = []
    package_dir = setup.get("package-dir")
    if isinstance(package_dir, dict):
        out.extend(v for v in package_dir.values() if isinstance(v, str))
    packages = setup.get("packages")
    find = packages.get("find") if isinstance(packages, dict) else None
    if isinstance(find, dict):
        out.extend(_as_str_list(find.get("where")))
    return out


def _as_str_list(value: object) -> list[str]:
    """Normalize a TOML scalar/list into a list of strings (a bare str becomes a
    one-element list; a list keeps only its str items; anything else -> ``[]``)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []
