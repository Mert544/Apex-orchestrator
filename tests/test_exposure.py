"""Exposure: a security finding's age + entrypoint reachability."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.engine.exposure import Exposure, _enclosing_function, analyze_exposure


def _git(cwd: Path, *args: str, date: str = "") -> None:
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=env)


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        "from app.svc import route_payload\n"
        "\n"
        "def main():\n"
        "    return route_payload('x')\n"
    )
    (tmp_path / "app" / "svc.py").write_text(
        "import app.util\n"
        "\n"
        "def route_payload(c):\n"
        "    return app.util.risky(c)\n"
    )
    (tmp_path / "app" / "util.py").write_text(
        "def risky(c):\n"
        "    return eval(c)\n"        # line 2 — reachable: main -> route_payload -> risky
        "\n"
        "def internal(c):\n"
        "    return exec(c)\n"        # line 5 — nothing calls it
    )
    return tmp_path


def test_enclosing_function_innermost():
    src = "def outer():\n    def inner():\n        return eval('1')\n    return inner\n"
    assert _enclosing_function(src, 3) == "inner"
    assert _enclosing_function(src, 1) == "outer"
    assert _enclosing_function("X = 1\n", 1) == ""


def test_reachability_separates_exposed_from_internal(tmp_path):
    _project(tmp_path)
    exposures = analyze_exposure(tmp_path, [("app/util.py", 2), ("app/util.py", 5)])
    exposed, internal = exposures
    assert exposed.enclosing == "risky"
    assert exposed.reachable_from == ["app/main.py"]
    assert exposed.exposed is True
    assert internal.enclosing == "internal"
    assert internal.reachable_from == [] and internal.exposed is False


def test_finding_inside_an_entrypoint_is_trivially_exposed(tmp_path):
    _project(tmp_path)
    (tmp_path / "app" / "main.py").write_text(
        "def main():\n    return eval('1')\n")
    e = analyze_exposure(tmp_path, [("app/main.py", 2)])[0]
    assert e.reachable_from == ["app/main.py"]


def test_age_anchored_to_head_commit(tmp_path):
    _project(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.com")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-qm", "old",
         date="2024-06-01T12:00:00 +0000")
    (tmp_path / "app" / "fresh.py").write_text("F = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-qm", "new",
         date="2026-06-01T12:00:00 +0000")
    e = analyze_exposure(tmp_path, [("app/util.py", 2)])[0]
    assert e.age_days is not None and 720 <= e.age_days <= 740  # ~2 years


def test_age_none_outside_git(tmp_path):
    _project(tmp_path)
    e = analyze_exposure(tmp_path, [("app/util.py", 2)])[0]
    assert e.age_days is None


def test_describe_reads_like_a_decision():
    e = Exposure(file="app/util.py", line=2, enclosing="risky",
                 age_days=430, reachable_from=["app/main.py"])
    assert e.describe() == "in the code ~14 months · reachable from `app/main.py`"
    fresh_internal = Exposure(file="app/x.py", line=9, enclosing="f", age_days=3)
    assert fresh_internal.describe() == ""  # nothing noteworthy -> say nothing
    module_level = Exposure(file="app/x.py", line=1)
    assert "module level" in module_level.describe()
