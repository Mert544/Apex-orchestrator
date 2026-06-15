"""The deterministic dependency audit: cross-check declared deps vs imports.

These tests build a real (small) project over a tmp tree and assert the audit's
three "possibly" signals plus the unpinned signal:

  * the import↔PyPI mismatch resolves: code importing ``yaml`` against a declared
    ``PyYAML`` does NOT flag pyyaml as unused (yaml→pyyaml mapped);
  * a declared-but-never-imported dep is flagged "possibly unused";
  * an imported third-party not declared is flagged "possibly undeclared";
  * stdlib and the project's own ``app`` package are excluded from imports;
  * a declared dep with no version specifier is flagged "unpinned";
  * the result is deterministic (same tree in -> same lists out);
  * requirements.txt deps are read alongside pyproject;
  * an empty repo degrades to clean empty findings + a clean report line.

Deterministic, stdlib-only, LLM-free — no network, no fixtures on disk beyond the
tmp tree pytest hands us.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.dependency_audit import (
    DependencyFindings,
    audit_dependencies,
    render_dependency_audit_markdown,
)


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _pyproject(deps: list[str], optional: dict[str, list[str]] | None = None) -> str:
    lines = [
        "[project]",
        'name = "demo"',
        'version = "0.1.0"',
        "dependencies = [",
    ]
    lines += [f'  "{d}",' for d in deps]
    lines.append("]")
    if optional:
        lines.append("[project.optional-dependencies]")
        for group, items in optional.items():
            lines.append(f"{group} = [")
            lines += [f'  "{d}",' for d in items]
            lines.append("]")
    return "\n".join(lines) + "\n"


def test_yaml_to_pyyaml_mismatch_resolves(tmp_path):
    # Declares requests + PyYAML; code imports requests + yaml. yaml→pyyaml must
    # be mapped so PyYAML is NOT flagged unused and yaml is NOT flagged undeclared.
    _write(tmp_path, "pyproject.toml", _pyproject(["requests>=2", "PyYAML>=6"]))
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/core.py", "import requests\nimport yaml\n")

    f = audit_dependencies(str(tmp_path))

    assert "pyyaml" in f.declared
    assert "requests" in f.declared
    assert "pyyaml" in f.imported_third_party
    assert "pyyaml" not in f.unused
    assert "pyyaml" not in f.undeclared
    assert f.unused == []
    assert f.undeclared == []


def test_declared_but_unused_is_flagged(tmp_path):
    _write(tmp_path, "pyproject.toml", _pyproject(["requests>=2", "rich>=13"]))
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/core.py", "import requests\n")

    f = audit_dependencies(str(tmp_path))

    assert "rich" in f.unused
    assert "requests" not in f.unused


def test_imported_third_party_undeclared_is_flagged(tmp_path):
    _write(tmp_path, "pyproject.toml", _pyproject(["requests>=2"]))
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/core.py", "import requests\nimport numpy\n")

    f = audit_dependencies(str(tmp_path))

    assert "numpy" in f.undeclared
    assert "requests" not in f.undeclared


def test_stdlib_and_local_imports_excluded(tmp_path):
    # os/sys/json are stdlib; app/* and tests/* are local — none are third-party.
    _write(tmp_path, "pyproject.toml", _pyproject(["requests>=2"]))
    _write(tmp_path, "app/__init__.py", "")
    _write(
        tmp_path, "app/core.py",
        "import os\nimport sys\nimport json\n"
        "import requests\n"
        "from app import other\n"
        "from . import sibling\n",
    )
    _write(tmp_path, "app/other.py", "x = 1\n")
    _write(tmp_path, "app/sibling.py", "y = 2\n")
    _write(tmp_path, "tests/test_x.py", "import app\n")

    f = audit_dependencies(str(tmp_path))

    assert f.imported_third_party == ["requests"]
    assert "os" not in f.imported_third_party
    assert "app" not in f.imported_third_party
    assert "tests" not in f.imported_third_party


def test_unpinned_dep_is_flagged(tmp_path):
    # requests has no specifier (unpinned); pydantic is pinned.
    _write(tmp_path, "pyproject.toml", _pyproject(["requests", "pydantic>=2,<3"]))
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/core.py", "import requests\nimport pydantic\n")

    f = audit_dependencies(str(tmp_path))

    assert "requests" in f.unpinned
    assert "pydantic" not in f.unpinned


def test_optional_dependencies_and_extras_parsed(tmp_path):
    # Optional groups are read; extras (pkg[extra]) are stripped to the bare name.
    _write(
        tmp_path, "pyproject.toml",
        _pyproject(["requests>=2"], optional={"dev": ["pytest>=8", "uvicorn[standard]>=0.30"]}),
    )
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/core.py", "import requests\n")

    f = audit_dependencies(str(tmp_path))

    assert "pytest" in f.declared
    assert "uvicorn" in f.declared  # extras stripped


def test_requirements_txt_is_read(tmp_path):
    _write(tmp_path, "pyproject.toml", _pyproject(["requests>=2"]))
    _write(tmp_path, "requirements.txt", "# comment\nrich==13.7.0\n\nclick\n")
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/core.py", "import requests\nimport rich\nimport click\n")

    f = audit_dependencies(str(tmp_path))

    assert "rich" in f.declared
    assert "click" in f.declared
    assert "rich" not in f.unpinned  # pinned ==
    assert "click" in f.unpinned     # unpinned


def test_determinism(tmp_path):
    _write(
        tmp_path, "pyproject.toml",
        _pyproject(["requests>=2", "rich>=13", "PyYAML>=6"]),
    )
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/core.py", "import requests\nimport yaml\nimport numpy\n")

    a = audit_dependencies(str(tmp_path))
    b = audit_dependencies(str(tmp_path))

    assert a == b
    # every list is sorted
    for lst in (a.declared, a.imported_third_party, a.unused, a.undeclared, a.unpinned):
        assert lst == sorted(lst)


def test_empty_repo_is_clean(tmp_path):
    f = audit_dependencies(str(tmp_path))

    assert f == DependencyFindings(
        declared=[], imported_third_party=[], unused=[], undeclared=[], unpinned=[]
    )
    report = render_dependency_audit_markdown(f)
    assert "no dependency issues found" in report.lower()


def test_render_lists_findings_with_heuristic_label(tmp_path):
    _write(tmp_path, "pyproject.toml", _pyproject(["requests", "rich>=13"]))
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/core.py", "import requests\nimport numpy\n")

    f = audit_dependencies(str(tmp_path))
    report = render_dependency_audit_markdown(f)

    assert "heuristic" in report.lower()
    assert "Possibly unused" in report
    assert "rich" in report
    assert "Possibly undeclared" in report
    assert "numpy" in report
    assert "Unpinned" in report
    assert "requests" in report


def test_missing_pyproject_only_requirements(tmp_path):
    # No pyproject at all — should not crash; reads requirements only.
    _write(tmp_path, "requirements.txt", "requests>=2\n")
    _write(tmp_path, "src/__init__.py", "")
    _write(tmp_path, "src/core.py", "import requests\n")

    f = audit_dependencies(str(tmp_path))

    assert f.declared == ["requests"]
    assert f.unused == []
