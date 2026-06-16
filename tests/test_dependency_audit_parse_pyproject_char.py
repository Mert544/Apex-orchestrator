"""Characterization test for the refactor of ``_parse_pyproject``.

This pins the BEHAVIOR of ``_parse_pyproject`` against a wide spread of
``pyproject.toml`` contents (every branch: missing file, malformed TOML,
non-table top level, absent/odd ``project``, list/non-list dependencies,
dict/non-dict optional-dependencies, non-str items, extras/markers/urls, ...).

The decomposition into ``_load_pyproject_data`` /
``_requirements_from_string_list`` must keep the output IDENTICAL. The golden
values below were captured from the pre-refactor implementation; the harness in
``tests/`` that compared the original snapshot against the refactored module
produced zero mismatches across these cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.dependency_audit import _parse_pyproject

# (label, file_contents_or_None).  None means "do not create the file".
_CASES: list[tuple[str, str | None]] = [
    ("no_file", None),
    ("empty", ""),
    ("malformed", "this is = = not toml ["),
    ("no_project", "[tool.black]\nline-length = 88\n"),
    ("project_not_table", "project = 'oops'\n"),
    ("project_empty", "[project]\nname = 'x'\n"),
    ("deps_not_list", "[project]\ndependencies = 'requests'\n"),
    (
        "deps_simple",
        "[project]\ndependencies = ['requests', 'click>=8.0']\n",
    ),
    (
        "deps_with_non_str",
        "[project]\ndependencies = ['requests', 42, true, 'flask==2.0']\n",
    ),
    (
        "deps_extras_markers",
        "[project]\ndependencies = [\n"
        "  'pkg[extra]>=1.0',\n"
        "  'mod; python_version < \"3.10\"',\n"
        "  'git+https://example.com/x.git',\n"
        "  '# a comment line',\n"
        "  '',\n"
        "  'numpy~=1.24',\n"
        "]\n",
    ),
    (
        "optional_basic",
        "[project]\ndependencies = ['a']\n"
        "[project.optional-dependencies]\n"
        "dev = ['pytest>=7', 'ruff']\n"
        "docs = ['sphinx']\n",
    ),
    (
        "optional_not_dict",
        "[project]\noptional-dependencies = ['nope']\n",
    ),
    (
        "optional_group_not_list",
        "[project]\n"
        "[project.optional-dependencies]\n"
        "dev = 'pytest'\n",
    ),
    (
        "optional_group_non_str_items",
        "[project]\n"
        "[project.optional-dependencies]\n"
        "dev = ['pytest', 0, false, 'mypy>=1.0']\n",
    ),
    (
        "deps_and_optional",
        "[project]\n"
        "dependencies = ['requests>=2', 'PyYAML']\n"
        "[project.optional-dependencies]\n"
        "test = ['pytest', 'coverage==7.4']\n"
        "lint = ['ruff', 'black>=24']\n",
    ),
    (
        "deps_empty_list",
        "[project]\ndependencies = []\n[project.optional-dependencies]\n",
    ),
]

# Golden outputs captured from the pre-refactor ``_parse_pyproject``.
_GOLDEN: dict[str, list[tuple[str, bool]]] = {
    "no_file": [],
    "empty": [],
    "malformed": [],
    "no_project": [],
    "project_not_table": [],
    "project_empty": [],
    "deps_not_list": [],
    "deps_simple": [("requests", False), ("click", True)],
    "deps_with_non_str": [("requests", False), ("flask", True)],
    "deps_extras_markers": [
        ("pkg", True),
        ("mod", False),
        ("", False),
        ("", False),
        ("", False),
        ("numpy", True),
    ],
    "optional_basic": [
        ("a", False),
        ("pytest", True),
        ("ruff", False),
        ("sphinx", False),
    ],
    "optional_not_dict": [],
    "optional_group_not_list": [],
    "optional_group_non_str_items": [("pytest", False), ("mypy", True)],
    "deps_and_optional": [
        ("requests", True),
        ("PyYAML", False),
        ("pytest", False),
        ("coverage", True),
        ("ruff", False),
        ("black", True),
    ],
    "deps_empty_list": [],
}


@pytest.mark.parametrize("label,contents", _CASES, ids=[c[0] for c in _CASES])
def test_parse_pyproject_matches_golden(
    label: str, contents: str | None, tmp_path: Path
) -> None:
    if contents is not None:
        (tmp_path / "pyproject.toml").write_text(contents, encoding="utf-8")
    assert _parse_pyproject(tmp_path) == _GOLDEN[label]


def test_every_case_has_a_golden() -> None:
    assert {c[0] for c in _CASES} == set(_GOLDEN)
