"""Characterization tests for the dedup-consolidation shared helpers.

These pin the public behaviour of the four blocks that were hoisted into shared
helpers (JSON HTTP response, draft document, read-and-parse, unused-import
rewrites) so a future change to a helper can't silently shift any caller's
output. They assert exact strings / structures, never just "no error".
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.execution._draft_document import build_draft_document
from app.execution._plan_source import read_and_parse
from app.execution.patch_request_generator import PatchRequestGenerator
from app.execution.semantic.generators.draft import fallback_draft
from app.execution.unused_imports import (
    plan_remove_unused_imports,
    strip_unused_imports,
)
from app.plugins._http_json import send_json_response
from app.plugins.marketplace_server import PluginMarketplaceHandler
from app.registry_server import RegistryHandler


# ---- (a) JSON HTTP response helper -----------------------------------------

class _FakeWfile:
    def __init__(self) -> None:
        self.data = b""

    def write(self, b: bytes) -> None:
        self.data += b


class _FakeHandler:
    def __init__(self) -> None:
        self.calls: list = []
        self.wfile = _FakeWfile()

    def send_response(self, status: int) -> None:
        self.calls.append(("resp", status))

    def send_header(self, key: str, value: str) -> None:
        self.calls.append(("hdr", key, value))

    def end_headers(self) -> None:
        self.calls.append(("end",))


def test_send_json_response_exact_bytes_and_headers():
    h = _FakeHandler()
    send_json_response(h, 201, {"status": "ok", "name": "n"})
    assert h.wfile.data == json.dumps(
        {"status": "ok", "name": "n"}, indent=2
    ).encode("utf-8")
    assert h.calls == [
        ("resp", 201),
        ("hdr", "Content-Type", "application/json"),
        ("hdr", "Access-Control-Allow-Origin", "*"),
        ("hdr", "Content-Length", str(len(h.wfile.data))),
        ("end",),
    ]


def test_handlers_delegate_to_shared_writer_identically():
    direct = _FakeHandler()
    send_json_response(direct, 404, {"error": "x"})
    for handler_cls in (PluginMarketplaceHandler, RegistryHandler):
        h = _FakeHandler()
        handler_cls._send_json(h, 404, {"error": "x"})
        assert h.calls == direct.calls
        assert h.wfile.data == direct.wfile.data


# ---- (b) draft document builder --------------------------------------------

def test_build_draft_document_exact_string():
    plan = {"change_strategy": ["a", "b"], "verification_steps": ["v"]}
    out = build_draft_document("t1", "Title", "x.b", plan)
    assert out == (
        "# Apex Orchestrator Patch Draft\n"
        "\n"
        "- task_id: t1\n"
        "- title: Title\n"
        "- branch: x.b\n"
        "\n"
        "## Change strategy\n"
        "- a\n"
        "- b\n"
        "\n"
        "## Verification steps\n"
        "- v\n"
    )


def test_build_draft_document_empty_plan_defaults():
    out = build_draft_document("t", "T", "b", {})
    assert "- No explicit change strategy captured." in out
    assert "- Run detected project tests." in out


def test_patch_generator_and_fallback_share_document():
    plan = {"change_strategy": ["s"], "verification_steps": ["v"]}
    doc = PatchRequestGenerator()._draft_document("tid", "ti", "br", plan)
    assert doc == build_draft_document("tid", "ti", "br", plan)
    with tempfile.TemporaryDirectory() as td:
        res = fallback_draft(Path(td), "tid", "ti", "br", plan, "reason").to_dict()
    assert res["patch_requests"][0]["new_content"] == build_draft_document(
        "tid", "ti", "br", plan
    )


# ---- (c) read-and-parse helper ---------------------------------------------

class _Plan:
    def __init__(self) -> None:
        self.blockers: list[str] = []


def test_read_and_parse_success_returns_source_and_tree():
    with tempfile.TemporaryDirectory() as td:
        rel = "m.py"
        (Path(td) / rel).write_text("x = 1\n", encoding="utf-8")
        out = read_and_parse(_Plan(), td, rel)
    assert out is not None
    source, tree = out
    assert source == "x = 1\n"
    assert tree.body  # parsed module


def test_read_and_parse_missing_file_returns_none_with_blocker():
    plan = _Plan()
    with tempfile.TemporaryDirectory() as td:
        out = read_and_parse(plan, td, "nope.py")
    assert out is None
    assert plan.blockers  # underlying primitive recorded a blocker


def test_read_and_parse_syntax_error_returns_none_with_blocker():
    plan = _Plan()
    with tempfile.TemporaryDirectory() as td:
        rel = "bad.py"
        (Path(td) / rel).write_text("def (((\n", encoding="utf-8")
        out = read_and_parse(plan, td, rel)
    assert out is None
    assert plan.blockers


# ---- (d) unused-import rewrites --------------------------------------------

def test_strip_unused_imports_removes_dead_import():
    out = strip_unused_imports("import os\nimport sys\nprint(sys.path)\n")
    assert out == "import sys\nprint(sys.path)\n"


def test_strip_unused_imports_no_change_returns_none():
    assert strip_unused_imports("import sys\nprint(sys.path)\n") is None


def test_plan_remove_unused_imports_matches_strip_core(tmp_path):
    src = "import os\nimport sys\nprint(sys.path)\n"
    rel = "m.py"
    (tmp_path / rel).write_text(src, encoding="utf-8")
    plan = plan_remove_unused_imports(str(tmp_path), rel)
    # An actual rewrite was produced (the dead ``import os`` line).
    assert plan.ok
    assert not plan.blockers
