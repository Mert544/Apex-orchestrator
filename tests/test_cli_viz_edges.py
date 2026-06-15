"""Edge-path coverage for app.cli_viz cmd_* dispatch functions.

Deterministic, stdlib-only, no network. The heavy builders (dependency /
idea canvas, idea-tree HTML, blast radius, work partition) are monkeypatched
at their source modules — these handlers import them lazily — so every test
exercises the handler's own argument/output/error branches in isolation and
stays fast and hermetic.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import app.cli_viz as cli_viz


# --- cmd_canvas: deps vs idea kind, default vs explicit --out -----------

def test_cmd_canvas_deps_default_out(tmp_path, monkeypatch, capsys):
    captured: dict = {}

    def fake_dependency_canvas(root):
        captured["root"] = root
        return {"nodes": [1, 2, 3], "edges": [("a", "b")]}

    def fake_write_canvas(canvas, path):
        captured["written"] = (canvas, Path(path))

    monkeypatch.setattr("app.reporting.canvas_export.dependency_canvas", fake_dependency_canvas)
    monkeypatch.setattr("app.reporting.canvas_export.write_canvas", fake_write_canvas)

    args = argparse.Namespace(target=str(tmp_path), kind="deps", out="")
    assert cli_viz.cmd_canvas(args) == 0

    out = capsys.readouterr().out
    assert "3 nodes, 1 edges" in out
    # Default path lands under <target>/.apex/apex.canvas
    assert captured["written"][1] == tmp_path.resolve() / ".apex" / "apex.canvas"


def test_cmd_canvas_idea_kind_uses_idea_canvas(tmp_path, monkeypatch, capsys):
    captured: dict = {}

    def fake_idea_canvas(root):
        captured["root"] = root
        return {"nodes": [1], "edges": []}

    monkeypatch.setattr("app.reporting.idea_canvas.idea_canvas", fake_idea_canvas)
    monkeypatch.setattr("app.reporting.canvas_export.write_canvas",
                        lambda canvas, path: captured.__setitem__("path", Path(path)))

    args = argparse.Namespace(target=str(tmp_path), kind="idea", out="")
    assert cli_viz.cmd_canvas(args) == 0

    out = capsys.readouterr().out
    assert "1 nodes, 0 edges" in out
    # Idea kind picks the apex-ideas.canvas default name.
    assert captured["path"] == tmp_path.resolve() / ".apex" / "apex-ideas.canvas"


def test_cmd_canvas_explicit_out_path_honored(tmp_path, monkeypatch, capsys):
    out_file = tmp_path / "custom" / "graph.canvas"
    captured: dict = {}

    monkeypatch.setattr("app.reporting.canvas_export.dependency_canvas",
                        lambda root: {"nodes": [], "edges": []})
    monkeypatch.setattr("app.reporting.canvas_export.write_canvas",
                        lambda canvas, path: captured.__setitem__("path", Path(path)))

    args = argparse.Namespace(target=str(tmp_path), kind="deps", out=str(out_file))
    assert cli_viz.cmd_canvas(args) == 0
    assert captured["path"] == out_file


def test_cmd_canvas_empty_target_uses_project_root(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli_viz, "_get_project_root", lambda: tmp_path)
    captured: dict = {}

    def fake_dependency_canvas(root):
        captured["root"] = root
        return {"nodes": [], "edges": []}

    monkeypatch.setattr("app.reporting.canvas_export.dependency_canvas", fake_dependency_canvas)
    monkeypatch.setattr("app.reporting.canvas_export.write_canvas", lambda canvas, path: None)

    args = argparse.Namespace(target="", kind="deps", out="")
    assert cli_viz.cmd_canvas(args) == 0
    assert captured["root"] == str(tmp_path)


def test_cmd_canvas_kind_defaults_to_deps_when_absent(tmp_path, monkeypatch, capsys):
    # getattr(args, "kind", "deps") fallback when the attribute is missing.
    monkeypatch.setattr("app.reporting.canvas_export.dependency_canvas",
                        lambda root: {"nodes": [], "edges": []})
    written: dict = {}
    monkeypatch.setattr("app.reporting.canvas_export.write_canvas",
                        lambda canvas, path: written.__setitem__("path", Path(path)))

    args = argparse.Namespace(target=str(tmp_path), out="")
    assert cli_viz.cmd_canvas(args) == 0
    assert written["path"].name == "apex.canvas"


# --- cmd_changed: markdown vs json output ------------------------------

def test_cmd_changed_markdown(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("app.engine.blast_radius.changed_from_git",
                        lambda root, base: ["app/x.py"])

    class FakeBR:
        def to_dict(self):
            return {"changed": ["app/x.py"]}

    monkeypatch.setattr("app.engine.blast_radius.blast_radius",
                        lambda root, changed: FakeBR())
    monkeypatch.setattr("app.engine.blast_radius.render_blast_radius_markdown",
                        lambda br: "# Blast radius\n")

    args = argparse.Namespace(target=str(tmp_path), base="HEAD", json=False)
    assert cli_viz.cmd_changed(args) == 0
    assert "# Blast radius" in capsys.readouterr().out


def test_cmd_changed_json(tmp_path, monkeypatch, capsys):
    import json as _json

    monkeypatch.setattr("app.engine.blast_radius.changed_from_git",
                        lambda root, base: [])

    class FakeBR:
        def to_dict(self):
            return {"changed": [], "dependents": ["b"]}

    monkeypatch.setattr("app.engine.blast_radius.blast_radius",
                        lambda root, changed: FakeBR())

    args = argparse.Namespace(target=str(tmp_path), base="main", json=True)
    assert cli_viz.cmd_changed(args) == 0
    payload = _json.loads(capsys.readouterr().out)
    assert payload == {"changed": [], "dependents": ["b"]}


def test_cmd_changed_threads_base_into_git(tmp_path, monkeypatch, capsys):
    seen: dict = {}

    def fake_changed_from_git(root, base):
        seen["base"] = base
        return []

    monkeypatch.setattr("app.engine.blast_radius.changed_from_git", fake_changed_from_git)
    monkeypatch.setattr("app.engine.blast_radius.blast_radius",
                        lambda root, changed: type("B", (), {"to_dict": lambda self: {}})())
    monkeypatch.setattr("app.engine.blast_radius.render_blast_radius_markdown",
                        lambda br: "ok")

    args = argparse.Namespace(target=str(tmp_path), base="origin/main", json=False)
    assert cli_viz.cmd_changed(args) == 0
    assert seen["base"] == "origin/main"


# --- cmd_idea_html: writes a self-contained report ----------------------

def test_cmd_idea_html_writes_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("app.reporting.idea_html.idea_tree_html",
                        lambda root: "<html>ideas</html>")

    args = argparse.Namespace(target=str(tmp_path), out="")
    assert cli_viz.cmd_idea_html(args) == 0

    out_path = tmp_path.resolve() / ".apex" / "apex-ideas.html"
    assert out_path.read_text(encoding="utf-8") == "<html>ideas</html>"
    out = capsys.readouterr().out
    assert "[idea-html] Written to" in out
    assert f"({len('<html>ideas</html>')} bytes)" in out


def test_cmd_idea_html_explicit_out_creates_parents(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("app.reporting.idea_html.idea_tree_html", lambda root: "X")
    nested = tmp_path / "deep" / "nest" / "report.html"

    args = argparse.Namespace(target=str(tmp_path), out=str(nested))
    assert cli_viz.cmd_idea_html(args) == 0
    assert nested.read_text(encoding="utf-8") == "X"


def test_cmd_idea_html_empty_target_uses_root(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli_viz, "_get_project_root", lambda: tmp_path)
    monkeypatch.setattr("app.reporting.idea_html.idea_tree_html", lambda root: "Y")

    args = argparse.Namespace(target="", out="")
    assert cli_viz.cmd_idea_html(args) == 0
    assert (tmp_path / ".apex" / "apex-ideas.html").read_text(encoding="utf-8") == "Y"


# --- cmd_partition: task spec parsing & rendering -----------------------

def test_cmd_partition_parses_task_specs(tmp_path, monkeypatch, capsys):
    seen_tasks: list = []

    def fake_partition_work(root, tasks):
        seen_tasks.extend(tasks)
        return ["group"]

    monkeypatch.setattr("app.engine.work_partition.partition_work", fake_partition_work)
    monkeypatch.setattr("app.engine.work_partition.render_partition_markdown",
                        lambda parts: "# Partition\n")

    args = argparse.Namespace(
        target=str(tmp_path),
        task=["alpha = a.py, b.py", "beta=c.py"],
    )
    assert cli_viz.cmd_partition(args) == 0
    assert "# Partition" in capsys.readouterr().out

    names = [t.name for t in seen_tasks]
    assert names == ["alpha", "beta"]
    # Whitespace is stripped and empty file slots dropped.
    assert seen_tasks[0].files == ["a.py", "b.py"]
    assert seen_tasks[1].files == ["c.py"]


def test_cmd_partition_spec_without_equals_yields_no_files(tmp_path, monkeypatch, capsys):
    seen_tasks: list = []
    monkeypatch.setattr("app.engine.work_partition.partition_work",
                        lambda root, tasks: seen_tasks.extend(tasks) or [])
    monkeypatch.setattr("app.engine.work_partition.render_partition_markdown",
                        lambda parts: "ok")

    # "solo" has no '=' so partition("=") leaves files empty.
    args = argparse.Namespace(target=str(tmp_path), task=["solo"])
    assert cli_viz.cmd_partition(args) == 0
    assert seen_tasks[0].name == "solo"
    assert seen_tasks[0].files == []


def test_cmd_partition_no_tasks_is_empty_list(tmp_path, monkeypatch, capsys):
    # args.task None → `args.task or []` short-circuits to empty.
    seen: dict = {}
    monkeypatch.setattr("app.engine.work_partition.partition_work",
                        lambda root, tasks: seen.setdefault("tasks", tasks) or [])
    monkeypatch.setattr("app.engine.work_partition.render_partition_markdown",
                        lambda parts: "none")

    args = argparse.Namespace(target=str(tmp_path), task=None)
    assert cli_viz.cmd_partition(args) == 0
    assert seen["tasks"] == []


# --- register_parsers: the family wiring --------------------------------

def test_register_parsers_wires_every_viz_command():
    import argparse as _argparse

    parser = _argparse.ArgumentParser(prog="apex")
    sub = parser.add_subparsers(dest="command")
    cli_viz.register_parsers(sub)

    assert set(sub.choices) == {"canvas", "changed", "idea-html", "partition"}
    assert sub.choices["canvas"].get_default("func") is cli_viz.cmd_canvas
    assert sub.choices["changed"].get_default("func") is cli_viz.cmd_changed
    assert sub.choices["idea-html"].get_default("func") is cli_viz.cmd_idea_html
    assert sub.choices["partition"].get_default("func") is cli_viz.cmd_partition
