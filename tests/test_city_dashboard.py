from __future__ import annotations

import json
import re
import subprocess
import types
from pathlib import Path

import pytest

from app.reporting.city_dashboard import build_city, build_city_model


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    # A risky module (security finding), an untested module, and a tested hub.
    (tmp_path / "app" / "danger.py").write_text(
        "def run(cmd):\n    return eval(cmd)\n", encoding="utf-8"
    )
    (tmp_path / "app" / "util.py").write_text(
        "def helper(x):\n    return x + 1\n", encoding="utf-8"
    )
    (tmp_path / "app" / "core.py").write_text(
        "from app.util import helper\n\ndef main(x):\n    return helper(x)\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_core.py").write_text(
        "def test_main():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0'\n", encoding="utf-8")
    return tmp_path


def test_city_model_is_grounded_in_real_signals(tmp_path: Path):
    _project(tmp_path)
    model = build_city_model(str(tmp_path))

    assert model["buildings"], "should render at least one building"
    names = {b["name"] for b in model["buildings"]}
    assert any(n.endswith("danger.py") for n in names)
    # The risky module is coloured as a security building and carries a finding.
    danger = next(b for b in model["buildings"] if b["name"].endswith("danger.py"))
    assert danger["health"] == "security"
    assert danger["findings"] >= 1
    # Grade is a real 0..100 health score with a letter.
    assert 0 <= model["grade"]["score"] <= 100
    assert isinstance(model["grade"]["letter"], str) and model["grade"]["letter"]


def test_city_edges_are_real_dependency_links(tmp_path: Path):
    _project(tmp_path)
    model = build_city_model(str(tmp_path))
    n = len(model["buildings"])
    # core.py imports util.py -> there is at least one dependency road, and
    # every edge references valid, distinct building indices.
    assert model["edges"], "core imports util, so an edge should exist"
    for a, b in model["edges"]:
        assert 0 <= a < n and 0 <= b < n and a != b


def test_city_assigns_security_worker_to_finding_site(tmp_path: Path):
    _project(tmp_path)
    model = build_city_model(str(tmp_path))
    sec_idx = {i for i, b in enumerate(model["buildings"]) if b["findings"] > 0}
    auditors = [w for w in model["workers"] if w["role"] == "Security Auditor"]
    assert auditors, "a security auditor should exist when findings are present"
    # At least one auditor's route includes a real finding site.
    assert any(set(w["route"]) & sec_idx for w in auditors)


def test_build_city_emits_self_contained_html(tmp_path: Path):
    _project(tmp_path)
    html = build_city(str(tmp_path))
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "/*__DATA__*/" not in html  # placeholder was substituted
    assert "three.min.js" in html
    # The embedded model is valid JSON.
    m = re.search(r"const DATA = (\{.*?\});", html, re.S)
    assert m is not None
    data = json.loads(m.group(1))
    assert data["buildings"] and "workers" in data


def test_city_handles_empty_project(tmp_path: Path):
    # No modules -> still a valid document, no crash.
    (tmp_path / "pyproject.toml").write_text("[project]\nname='e'\nversion='0'\n", encoding="utf-8")
    html = build_city(str(tmp_path))
    assert "<!DOCTYPE html>" in html
    model = build_city_model(str(tmp_path))
    assert model["totals"]["buildings"] == len(model["buildings"])


# --- characterization: refactor is byte-identical to the pre-refactor HEAD ---


def _load_head_build_city_model():
    """Exec the pre-refactor city_dashboard from git HEAD into an isolated module.

    Returns ``None`` (the test self-skips) when HEAD already contains the
    refactor, so the guard never goes stale after this change is committed.
    """
    try:
        src = subprocess.check_output(
            ["git", "show", "HEAD:app/reporting/city_dashboard.py"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
        )
    except subprocess.CalledProcessError:
        return None
    # Only meaningful while HEAD is still the monolithic version we shrank.
    if "_coordinator_signals" in src:
        return None
    mod = types.ModuleType("_city_dashboard_head")
    exec(compile(src, "<head:city_dashboard.py>", "exec"), mod.__dict__)
    return mod.build_city_model


def _strip_clock(model: dict) -> dict:
    # The single render-time timestamp is the only non-deterministic field.
    return {k: v for k, v in model.items() if k != "generated"}


def _fixtures(tmp_path: Path) -> list[Path]:
    a = tmp_path / "a"
    a.mkdir()
    _project(a)
    b = tmp_path / "b"  # empty project (no modules)
    b.mkdir()
    (b / "pyproject.toml").write_text("[project]\nname='e'\nversion='0'\n", encoding="utf-8")
    return [a, b]


def test_refactor_is_byte_identical_to_head():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        head_fn = _load_head_build_city_model()
        if head_fn is None:
            pytest.skip("HEAD already contains the refactored city_dashboard")
        for root in _fixtures(Path(td)):
            before = head_fn(str(root))
            after = build_city_model(str(root))
            # Same model sans the single timestamp, serialized byte-for-byte.
            assert json.dumps(_strip_clock(before), sort_keys=True) == json.dumps(
                _strip_clock(after), sort_keys=True
            )
            # The timestamp field itself is still present and well-formed.
            assert re.fullmatch(
                r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", after["generated"]
            )
