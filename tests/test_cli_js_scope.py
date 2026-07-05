"""The `apex js-scope` subcommand: the JS/TS analog of `apex scope`/`apex
hotspots`. Surfaces the module/dependency graph, the highest fan-in hubs, and the
untested modules (the untested hub is the highest-leverage gap) for the non-Python
half of a stack — from the already-built, already-tested ``JsProjectProfile``.

The render + command-branch tests are pure (they build a fixture profile or
monkeypatch the profiler, no driver). The graceful-empty tests run a real empty
tmp_path (the profiler returns an empty profile with no driver spawn). The one
end-to-end test that exercises the real import graph is gated on node + global
typescript, the same sentinel the profiler's own suite uses.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
from pathlib import Path

import pytest

from app.cli_insight import cmd_js_scope, render_js_scope_markdown
from app.execution.js.js_tool import global_node_modules
from app.tools.js_project_profile import JsProjectProfile, profile_js_project


def _run(target: Path, json_out: bool = False) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_js_scope(argparse.Namespace(target=str(target), json=json_out))
    return rc, buf.getvalue()


def _fixture_profile() -> JsProjectProfile:
    """A small profile: ``src/api.ts`` is a fan-in-2 hub with no linked test (the
    untested hub); ``src/util.ts`` is tested; ``src/orphan.ts`` is untested."""
    return JsProjectProfile(
        root="/proj",
        modules=["src/api.ts", "src/orphan.ts", "src/util.ts"],
        test_files=["src/util.test.ts"],
        dependency_edges=[("src/orphan.ts", "src/api.ts"),
                          ("src/util.ts", "src/api.ts")],
        external_dependencies=["react"],
        module_fanin={"src/api.ts": 2},
        module_fanout={"src/orphan.ts": ["src/api.ts"],
                       "src/util.ts": ["src/api.ts"]},
        dependency_hubs=["src/api.ts"],
        module_to_tests={"src/util.ts": ["src/util.test.ts"]},
        untested_modules=["src/api.ts", "src/orphan.ts"],
        untested_count=2,
        hub_untested_modules=[{"module": "src/api.ts", "fan_in": 2}],
    )


# --- pure render ------------------------------------------------------------

def test_render_headline_hubs_and_untested():
    md = render_js_scope_markdown(_fixture_profile())
    assert "# Apex JS/TS project scope" in md
    assert "3 module(s), 1 test file(s), 2 internal dependency edge(s)" in md
    assert "## Dependency hubs (highest fan-in)" in md
    assert "`src/api.ts` (fan-in 2)" in md
    assert "## Untested modules (2 total, top 2 shown)" in md


def test_render_untested_hub_callout_names_the_leverage():
    md = render_js_scope_markdown(_fixture_profile())
    assert "## Highest-leverage gap: untested hub" in md
    assert "`src/api.ts` has fan-in 2 and no linked test" in md


def test_render_is_deterministic():
    p = _fixture_profile()
    assert render_js_scope_markdown(p) == render_js_scope_markdown(p)


# --- command branches (monkeypatched profiler, no driver) -------------------

def test_cmd_json_serializes_the_profile(tmp_path, monkeypatch):
    import app.tools.js_project_profile as jpp
    monkeypatch.setattr(jpp, "profile_js_project", lambda *a, **k: _fixture_profile())
    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["dependency_hubs"] == ["src/api.ts"]
    assert data["hub_untested_modules"] == [{"module": "src/api.ts", "fan_in": 2}]
    # tuples serialize to JSON arrays without custom code
    assert data["dependency_edges"] == [["src/orphan.ts", "src/api.ts"],
                                        ["src/util.ts", "src/api.ts"]]


def test_cmd_markdown_branch(tmp_path, monkeypatch):
    import app.tools.js_project_profile as jpp
    monkeypatch.setattr(jpp, "profile_js_project", lambda *a, **k: _fixture_profile())
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "# Apex JS/TS project scope" in out
    assert "`src/api.ts` (fan-in 2)" in out


# --- graceful empty (real profiler, always runs — no driver spawned) --------

def test_graceful_empty_prints_friendly_message(tmp_path):
    # No package.json → the profiler returns an empty profile with no driver.
    rc, out = _run(tmp_path)
    assert rc == 0
    assert "No JS/TS project detected at this root." in out


def test_empty_json_is_valid(tmp_path):
    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["modules"] == []
    assert data["hub_untested_modules"] == []


# --- registration -----------------------------------------------------------

def test_registered_via_parser():
    import app.cli_insight as cli_insight

    parser = argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_insight.register_parsers(sub)
    assert "js-scope" in sub.choices
    assert sub.choices["js-scope"].get_default("func") is cmd_js_scope


# --- end-to-end over the real import graph (gated on node + typescript) ------

def _node_ok() -> bool:
    if shutil.which("node") is None:
        return False
    nm = global_node_modules()
    return bool(nm) and (Path(nm) / "typescript").is_dir()


@pytest.mark.skipif(not _node_ok(), reason="node + global typescript not available")
def test_integration_untested_hub_populates(tmp_path):
    (tmp_path / "package.json").write_text(
        '{ "name": "demo", "version": "1.0.0" }\n', encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    # core is imported by two modules (a fan-in-2 hub) and has NO linked test.
    (src / "core.ts").write_text(
        "export function core(x: number): number { return x; }\n", encoding="utf-8")
    (src / "a.ts").write_text(
        'import { core } from "./core";\nexport const a = () => core(1);\n',
        encoding="utf-8")
    (src / "b.ts").write_text(
        'import { core } from "./core";\nexport const b = () => core(2);\n',
        encoding="utf-8")

    profile = profile_js_project(tmp_path)
    assert profile.modules  # the driver resolved a real graph
    hubs = {h["module"] for h in profile.hub_untested_modules}
    assert any("core" in m for m in hubs)

    rc, out = _run(tmp_path, json_out=True)
    assert rc == 0
    data = json.loads(out)
    assert data["hub_untested_modules"]
